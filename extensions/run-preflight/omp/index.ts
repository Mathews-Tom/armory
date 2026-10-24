import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { execFile, spawn } from "node:child_process";
import { dirname } from "node:path";
import { promisify } from "node:util";
import { COMMAND, COMMAND_DESCRIPTION, HELP, HELPER_TIMEOUT_MS, MAX_HELPER_BYTES, helperArgv, parseCommand, parseHelperAnswer, projectAnswer, renderAnswer, renderFailure, requestsJson } from "../core/protocol.ts";
import type { PreflightCommand, RunCommand } from "../core/protocol.ts";

export interface HelperExecution {
  readonly stdout: string;
  readonly exitCode: number | null;
  readonly signal: string | null;
  readonly cleanupConfirmed: boolean;
}
export interface Runtime {
  readonly packageRoot: string;
  readonly now: () => number;
  readonly execute: (argv: readonly string[], signal: AbortSignal) => Promise<HelperExecution>;
}
interface Owned { abort: AbortController; done: Promise<void> }
interface Session { id: string; cwd: string | undefined }
interface ProcessIdentity { pid: number; ppid: number; group: number; command: string }
class CleanupError extends Error { constructor() { super("run-preflight-cleanup-unconfirmed"); } }
function sleep(ms: number): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<undefined>();
  setTimeout(resolve, ms);
  return promise;
}
const inspect = promisify(execFile);
async function inventory(): Promise<Map<number, ProcessIdentity>> {
  const { stdout } = await inspect("/bin/ps", ["-axo", "pid=,ppid=,pgid=,command="], { timeout: 2_000, maxBuffer: MAX_HELPER_BYTES, encoding: "utf8" });
  const table = new Map<number, ProcessIdentity>();
  for (const line of stdout.split("\n")) {
    const match = /^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.+)$/u.exec(line);
    if (match !== null) table.set(Number(match[1]), { pid: Number(match[1]), ppid: Number(match[2]), group: Number(match[3]), command: match[4] ?? "" });
  }
  return table;
}
function exists(group: number): boolean {
  try { process.kill(-group, 0); return true; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ESRCH") return false; throw error; }
}
function kill(group: number, signal: NodeJS.Signals): void {
  try { process.kill(-group, signal); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error; }
}

/** Literal Bun argv, bounded combined output, and TERM-before-KILL so the helper
 * can reap its own detached project bridge before its owner is terminated. */
export async function executeHelper(argv: readonly string[], signal: AbortSignal, timeoutMs = HELPER_TIMEOUT_MS, byteLimit = MAX_HELPER_BYTES): Promise<HelperExecution> {
  if (argv[0] !== "bun" || argv[1] === undefined || signal.aborted) return { stdout: "", exitCode: null, signal: null, cleanupConfirmed: true };
  const child = spawn("bun", argv.slice(1), { detached: true, shell: false, stdio: ["ignore", "pipe", "pipe"] });
  const pid = child.pid;
  let exitCode: number | null = null;
  let exitSignal: string | null = null;
  let closed = false;
  let failed = false;
  let bytes = 0;
  const chunks: Buffer[] = [];
  const owned = new Map<number, ProcessIdentity>();
  let inventoryFailed = false;
  let cancellation: Promise<void> | undefined;
  let sampling: Promise<void> = Promise.resolve();
  let samplingBusy = false;
  const interrupted = Promise.withResolvers<undefined>();
  const sample = async (): Promise<void> => {
    if (pid === undefined) return;
    const table = await inventory();
    for (const item of table.values()) {
      let current = item;
      const seen = new Set<number>();
      while (!seen.has(current.pid)) {
        if (current.pid === pid) { owned.set(item.pid, item); break; }
        seen.add(current.pid);
        const parent = table.get(current.ppid);
        if (parent === undefined) break;
        current = parent;
      }
    }
  };
  const cancel = (): void => {
    failed = true;
    if (cancellation !== undefined) return;
    clearInterval(sampler);
    interrupted.resolve(undefined);
    cancellation = (async () => {
      await sampling;
      try { await sample(); } catch { inventoryFailed = true; }
      if (pid !== undefined) kill(pid, "SIGTERM");
      // The CLI's nested bridge has its own 100ms graceful cleanup deadline.
      await sleep(750);
      try {
        const table = await inventory();
        for (const identity of owned.values()) {
          const live = table.get(identity.pid);
          if (live !== undefined && live.command === identity.command && live.group === identity.group && identity.group === identity.pid) kill(identity.group, "SIGTERM");
        }
      } catch { inventoryFailed = true; }
      await sleep(250);
      if (pid !== undefined && exists(pid)) kill(pid, "SIGKILL");
      try {
        const remaining = await inventory();
        for (const identity of owned.values()) {
          const live = remaining.get(identity.pid);
          if (live !== undefined && live.command === identity.command && live.group === identity.group && identity.group === identity.pid) kill(identity.group, "SIGKILL");
        }
      } catch { inventoryFailed = true; }
    })();
    // The caller awaits this promise after child close, including rejection.
    void cancellation.catch(() => { inventoryFailed = true; });
  };
  const receive = (chunk: Buffer, stdout: boolean): void => {
    bytes += chunk.byteLength;
    if (bytes > byteLimit) { cancel(); return; }
    if (stdout && !failed) chunks.push(chunk);
  };
  child.stdout?.on("data", (chunk: Buffer) => receive(chunk, true));
  child.stderr?.on("data", (chunk: Buffer) => receive(chunk, false));
  const finished = Promise.withResolvers<undefined>();
  child.once("error", () => { failed = true; });
  child.once("close", (code, termination) => { exitCode = code; exitSignal = termination; closed = true; finished.resolve(undefined); });
  // Remember detached descendant groups while ownership can still be proven.
  const sampler = setInterval(() => {
    if (samplingBusy) return;
    samplingBusy = true;
    sampling = sample().catch(() => { inventoryFailed = true; cancel(); }).finally(() => { samplingBusy = false; });
  }, 100);
  const timer = setTimeout(cancel, timeoutMs);
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) cancel();
  try {
    // A descendant retaining inherited pipes cannot keep this owner alive forever.
    await Promise.race([finished.promise, interrupted.promise]);
    clearInterval(sampler);
    await sampling;
    clearTimeout(timer);
    if (closed && cancellation === undefined) {
      const table = await inventory();
      if (pid !== undefined && exists(pid) || [...owned.values()].some((identity) => table.has(identity.pid) || identity.group === identity.pid && exists(identity.group))) cancel();
    }
    if (cancellation !== undefined) await cancellation;
    if (!closed) {
      await Promise.race([finished.promise, sleep(2_000)]);
      if (!closed) inventoryFailed = true;
    }
    const deadline = Date.now() + 2_000;
    let clean = false;
    while (Date.now() < deadline) {
      const table = await inventory();
      const survivors = [...owned.values()].some((identity) => table.has(identity.pid) || (identity.group === identity.pid && exists(identity.group)));
      if (!survivors && (pid === undefined || !table.has(pid) && !exists(pid))) { clean = true; break; }
      await sleep(25);
    }
    let stdout = "";
    if (!failed) { try { stdout = new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)); } catch { failed = true; } }
    return { stdout: failed ? "" : stdout, exitCode: failed ? null : exitCode, signal: exitSignal, cleanupConfirmed: clean && closed && !inventoryFailed };
  } catch { return { stdout: "", exitCode: null, signal: exitSignal, cleanupConfirmed: false }; }
  finally {
    clearInterval(sampler);
    clearTimeout(timer);
    signal.removeEventListener("abort", cancel);
    child.stdout?.destroy();
    child.stderr?.destroy();
  }
}
function sessionId(ctx: ExtensionContext): string | null {
  try { const id = ctx.sessionManager.getSessionId(); return typeof id === "string" && id.length > 0 ? id : null; }
  catch { return null; }
}

/** Host boundary is explicit: deterministic tests replace execution, never PATH,
 * package files, module caches, authentication or the shared decision protocol. */
export function createRunPreflight(runtime: Runtime): (pi: ExtensionAPI) => void {
  return (pi) => {
    const owned = new Set<Owned>();
    let active: Owned | null = null;
    let session: Session | null = null;
    let accepting = false;
    let registered = false;
    let epoch = 0;
    let cleanupFailed = false;
    function current(ctx: ExtensionContext, expected: Session, task?: Owned): boolean {
      return accepting && !cleanupFailed && session === expected && sessionId(ctx) === expected.id && ctx.cwd === expected.cwd &&
        (task === undefined || active === task && !task.abort.signal.aborted);
    }
    function send(ctx: ExtensionContext, expected: Session, content: string, details: object, task?: Owned): void {
      if (!current(ctx, expected, task)) return;
      pi.sendMessage({ customType: COMMAND, content, display: true, details: { ...details,
        correlation: { host: "omp", sessionId: expected.id, ...(expected.cwd === undefined ? {} : { cwd: expected.cwd }) } } }, { triggerTurn: false });
    }
    async function settle(tasks: readonly Owned[]): Promise<void> {
      const results = await Promise.allSettled(tasks.map((task) => task.done));
      if (results.some((item) => item.status === "rejected")) { cleanupFailed = true; accepting = false; throw new CleanupError(); }
    }
    async function handle(args: string, ctx: ExtensionContext): Promise<void> {
      const expected = session;
      if (expected === null || !current(ctx, expected)) return;
      let command: PreflightCommand;
      try { command = parseCommand(args); }
      catch { send(ctx, expected, renderFailure("invalid-arguments", requestsJson(args)), { error: "invalid-arguments" }); return; }
      if (command.action === "help") { send(ctx, expected, HELP, { help: true }); return; }
      const run: RunCommand = command;
      const previous = [...owned];
      for (const task of previous) task.abort.abort();
      const abort = new AbortController();
      const task: Owned = { abort, done: Promise.resolve().then(async () => {
        try {
          await settle(previous);
          if (!current(ctx, expected, task)) return;
          let result: HelperExecution;
          try { result = await runtime.execute(helperArgv(run, runtime.packageRoot), abort.signal); }
          catch { throw new CleanupError(); }
          if (!result.cleanupConfirmed) throw new CleanupError();
          if (!current(ctx, expected, task)) return;
          if (result.signal !== null || result.exitCode === null) throw new Error("helper-failed");
          const report = parseHelperAnswer(JSON.parse(result.stdout), run, runtime.packageRoot, runtime.now(), result.exitCode);
          const view = projectAnswer(report, run.selection);
          send(ctx, expected, renderAnswer(report, view, run.json), { view }, task);
        } catch (error) {
          if (error instanceof CleanupError) { cleanupFailed = true; accepting = false; throw error; }
          send(ctx, expected, renderFailure("operation-failed", run.json), { error: "operation-failed" }, task);
        } finally { owned.delete(task); if (active === task) active = null; }
      }) };
      owned.add(task);
      active = task;
      await task.done;
    }
    async function changeSession(ctx: ExtensionContext, next: boolean): Promise<void> {
      const own = ++epoch;
      const id = sessionId(ctx);
      const cwd = ctx.cwd;
      accepting = false;
      session = null;
      const tasks = [...owned];
      for (const task of tasks) task.abort.abort();
      await settle(tasks);
      if (own !== epoch || cleanupFailed || !next || id === null || sessionId(ctx) !== id || ctx.cwd !== cwd) return;
      session = { id, cwd };
      accepting = true;
    }
    pi.on("session_start", (_event, ctx) => {
      if (cleanupFailed) throw new CleanupError();
      const matches = pi.getCommands().filter((item) => item.name === COMMAND);
      if (matches.length > 1 || matches.length === 1 && (!registered || matches[0]?.source !== "extension" || matches[0]?.description !== COMMAND_DESCRIPTION) || registered && matches.length !== 1) {
        accepting = false;
        for (const task of owned) task.abort.abort();
        return settle([...owned]).then(() => { throw new Error("command-collision"); });
      }
      if (!registered) { pi.registerCommand(COMMAND, { description: COMMAND_DESCRIPTION, handler: handle }); registered = true; }
      if (session !== null && current(ctx, session)) return;
      return changeSession(ctx, true);
    });
    pi.on("session_switch", async (_event, ctx) => { await changeSession(ctx, true); });
    pi.on("session_shutdown", async (_event, ctx) => { await changeSession(ctx, false); });
    // OMP 18.12.6 supplies no slash-command signal or unload disposer. No Escape hook.
  };
}

// Production's root wrapper loads this bundle from artifact-root/omp/index.ts.
// The host is compiled: process.execPath is NOT a Bun executable.
export default createRunPreflight({ packageRoot: dirname(import.meta.dir), now: Date.now, execute: executeHelper });
