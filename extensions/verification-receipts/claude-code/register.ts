import { parseNativeObservation } from "../core/claude-protocol.ts";
import type { NativeObservation } from "../core/claude-protocol.ts";

// Only the declared Claude Code 2.1.309 API used here. The module has no runtime
// dependency on an SDK, Node, Bun, a checkout, a model turn, or a UI surface.
interface ProcessResult { code: number | null; signal: string | null; }
interface ProcessChunk { stream: "stdout" | "stderr"; text: string; }
type ProcessStream = AsyncGenerator<ProcessChunk, ProcessResult> & { readonly result: Promise<ProcessResult> };
interface ModApi {
  plugin: { root: string };
  env: { get(name: string): Promise<string | undefined> };
  session: { id(): Promise<string> };
  command: {
    list(): Promise<{ name: string }[]>;
    register(spec: { name: string; description: string; argumentHint?: string; immediate?: true }): Promise<unknown>;
  };
  process: {
    spawn(request: { argv: readonly string[]; cwd?: string; env?: Record<string, string>; input?: string }): ProcessStream;
    run(argv: readonly string[], init?: { cwd?: string; env?: Record<string, string>; stdin?: string; timeoutMs?: number }): Promise<{
      exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean;
    }>;
  };
}
type Next<E> = (event: E) => Promise<unknown>;
interface EndEvent { sessionId: string; reason: string; }
interface CommandEvent { command: string; args: string; }
type On = {
  (event: "session.start", hook: ($: ModApi, e: unknown, next: Next<unknown>) => Promise<unknown>): unknown;
  (event: "session.end", hook: ($: ModApi, e: EndEvent, next: Next<EndEvent>) => Promise<unknown>): unknown;
  (event: "command.run", matcher: { command: string }, hook: ($: ModApi, e: CommandEvent) => Promise<{ text: string }>): unknown;
};
interface Scope { repo: string; config: string; data: string; account: string; work: string; session: string; helper: string; }
interface Owned {
  epoch: number;
  scope?: Scope;
  stream?: ProcessStream;
  cancelled: boolean;
  earlyClose: boolean;
  finished: boolean;
  done: Promise<NativeObservation>;
  finish(value: NativeObservation): void;
  closing?: Promise<void>;
}
const MAX_OBSERVATION_CHARS = 4_194_304;
const FAILED = { error: "operation-failed" } as const;

function answer(value: unknown): { text: string } { return { text: JSON.stringify(value) }; }
function sameScope(left: Scope, right: Scope): boolean {
  return left.repo === right.repo && left.config === right.config && left.data === right.data &&
    left.account === right.account && left.work === right.work && left.session === right.session && left.helper === right.helper;
}
function selectedScope(values: readonly (string | undefined)[]): Scope {
  const [repo, config, data, account, work, session, root] = values;
  if (repo === undefined || config === undefined || data === undefined || account === undefined || work === undefined ||
      session === undefined || root === undefined || [repo, config, data, account, work, session, root].some((value) => {
        if (value.length === 0) return true;
        for (let index = 0; index < value.length; index++) {
          const code = value.charCodeAt(index);
          if (code < 32 || code === 127) return true;
        }
        return false;
      })) {
    throw new Error("explicit receipt configuration required");
  }
  return { repo, config, data, account, work, session, helper: `${root}/helpers/claude-cli.js` };
}
function argv(scope: Scope, command: "run" | "list" | "reconcile", gate?: string): string[] {
  const result = ["bun", scope.helper, command, "--repo", scope.repo, "--config", scope.config, "--data-root", scope.data,
    "--session", scope.session, "--account", scope.account, "--work-context", scope.work];
  if (gate !== undefined) result.push("--gate", gate);
  return result;
}
function observation(text: string): NativeObservation {
  if (text.length > MAX_OBSERVATION_CHARS) throw new Error("receipt observation too large");
  return parseNativeObservation(JSON.parse(text) as unknown);
}
async function consume(owner: Owned, stream: ProcessStream): Promise<void> {
  let stdout = "";
  let overflow = false;
  // Closing a HookStream rejects result by contract. Observe it immediately so
  // cancellation cannot create an unhandled rejection; it is not a kill receipt.
  const result = stream.result.catch(() => undefined);
  try {
    for await (const piece of stream) {
      if (piece.stream !== "stdout" || overflow) continue;
      if (stdout.length + piece.text.length > MAX_OBSERVATION_CHARS) { overflow = true; stdout = ""; }
      else stdout += piece.text;
    }
    const ended = await result;
    if (owner.earlyClose || overflow || ended === undefined) { owner.finish(FAILED); return; }
    const value = observation(stdout);
    if (!("executionId" in value) || (ended.code === 0 ? !value.proof : value.proof) ||
        ![0, 1, 2, 130, 143].includes(ended.code ?? -1)) { owner.finish(FAILED); return; }
    owner.finish(value);
  } catch { owner.finish(FAILED); }
}
async function close(owner: Owned): Promise<void> {
  owner.cancelled = true;
  owner.closing ??= (async () => {
    const stream = owner.stream;
    if (stream !== undefined && !owner.finished) {
      owner.earlyClose = true;
      try { await stream.return({ code: null, signal: null }); } catch { /* Reconcile the original scope, never assert cleanup. */ }
    }
    await owner.done;
  })();
  await owner.closing;
}

export function register(on: On): void {
  let epoch = 0;
  let active: Owned | undefined;
  let registration: Promise<void> | undefined;
  let ready = false;

  on("session.start", async ($, e, next) => {
    if (registration === undefined) {
      const completion = Promise.withResolvers<undefined>();
      registration = completion.promise;
      try {
        const commands = await $.command.list();
        if (commands.some((command) => command.name === "armory-verify" || command.name === "armory-evidence")) {
          throw new Error("Armory receipt command name collision");
        }
        await $.command.register({ name: "armory-verify", description: "Run one explicitly configured local verification gate", argumentHint: "<gate>" });
        await $.command.register({ name: "armory-evidence", description: "Read persisted verification evidence, wait, or request cancellation", argumentHint: "[wait|cancel]", immediate: true });
        ready = true;
        completion.resolve(undefined);
      } catch (error) { completion.reject(error); }
    }
    await registration;
    return next(e);
  });

  on("command.run", { command: "armory-verify" }, async ($, e) => {
    const gate = e.args.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/u.test(gate)) return answer({ error: "invalid-arguments" });
    if (!ready) return answer({ error: "commands-unavailable" });
    if (active?.finished) active = undefined;
    if (active !== undefined) return answer({ state: "busy" });
    // Reserve synchronously, before even reading session/configuration effects.
    const completion = Promise.withResolvers<NativeObservation>();
    const owner: Owned = { epoch, cancelled: false, earlyClose: false, finished: false, done: completion.promise,
      finish(value) { owner.finished = true; completion.resolve(value); },
    };
    active = owner;
    try {
      const scope = selectedScope(await Promise.all([
        $.env.get("ARMORY_RECEIPTS_REPO"), $.env.get("ARMORY_RECEIPTS_CONFIG"),
        $.env.get("ARMORY_RECEIPTS_DATA_ROOT"), $.env.get("ARMORY_RECEIPTS_ACCOUNT"),
        $.env.get("ARMORY_RECEIPTS_WORK_CONTEXT"), $.session.id(), $.plugin.root,
      ]));
      owner.scope = scope;
      const current = selectedScope(await Promise.all([
        $.env.get("ARMORY_RECEIPTS_REPO"), $.env.get("ARMORY_RECEIPTS_CONFIG"),
        $.env.get("ARMORY_RECEIPTS_DATA_ROOT"), $.env.get("ARMORY_RECEIPTS_ACCOUNT"),
        $.env.get("ARMORY_RECEIPTS_WORK_CONTEXT"), $.session.id(), $.plugin.root,
      ]));
      if (owner.cancelled || epoch !== owner.epoch || !sameScope(scope, current)) {
        owner.finish(FAILED);
        return answer({ error: "context-changed" });
      }
      // Only immutable scope and the owned stream/done survive this hook. `$`
      // is not retained by the background reader and it never emits a model turn.
      const stream = $.process.spawn({ argv: argv(scope, "run", gate), cwd: scope.repo });
      owner.stream = stream;
      void consume(owner, stream);
      return answer({ state: "running" });
    } catch {
      owner.finish(FAILED);
      return answer(FAILED);
    } finally {
      // Selection failures release only their own reservation.
      if (owner.stream === undefined && active === owner) active = undefined;
    }
  });

  on("command.run", { command: "armory-evidence" }, async ($, e) => {
    const mode = e.args.trim();
    if (mode !== "" && mode !== "wait" && mode !== "cancel") return answer({ error: "invalid-arguments" });
    if (!ready) return answer({ error: "commands-unavailable" });
    const observedEpoch = epoch;
    const owner = active;
    try {
      const scope = selectedScope(await Promise.all([
        $.env.get("ARMORY_RECEIPTS_REPO"), $.env.get("ARMORY_RECEIPTS_CONFIG"),
        $.env.get("ARMORY_RECEIPTS_DATA_ROOT"), $.env.get("ARMORY_RECEIPTS_ACCOUNT"),
        $.env.get("ARMORY_RECEIPTS_WORK_CONTEXT"), $.session.id(), $.plugin.root,
      ]));
      if (epoch !== observedEpoch) return answer({ error: "context-changed" });
      if (owner !== undefined && (owner.scope === undefined || !sameScope(owner.scope, scope))) {
        // Selection may still be pending; close marks cancellation before waiting.
        await close(owner);
        const previous = owner.scope;
        if (previous !== undefined && owner.stream !== undefined) {
          const reconciled = await $.process.run(argv(previous, "reconcile"), { cwd: previous.repo, timeoutMs: 30_000 });
          if (reconciled.isStdoutTruncated) throw new Error("receipt observation too large");
          observation(reconciled.stdout);
        }
        if (active === owner) active = undefined;
        return answer({ error: "context-changed" });
      }
      if (owner !== undefined && mode === "cancel") await close(owner);
      if (owner !== undefined && (mode === "wait" || mode === "cancel")) await owner.done;
      // Reopen interrupted owners as incomplete before listing all durable
      // receipts. reconcile returns only newly recovered records, not the list.
      const recovered = await $.process.run(argv(scope, "reconcile"), { cwd: scope.repo, timeoutMs: 30_000 });
      if (recovered.isStdoutTruncated || recovered.exitCode !== 0 || !("receipts" in observation(recovered.stdout))) {
        throw new Error("receipt reconciliation failed");
      }
      const reconciledScope = selectedScope(await Promise.all([
        $.env.get("ARMORY_RECEIPTS_REPO"), $.env.get("ARMORY_RECEIPTS_CONFIG"),
        $.env.get("ARMORY_RECEIPTS_DATA_ROOT"), $.env.get("ARMORY_RECEIPTS_ACCOUNT"),
        $.env.get("ARMORY_RECEIPTS_WORK_CONTEXT"), $.session.id(), $.plugin.root,
      ]));
      if (epoch !== observedEpoch || !sameScope(scope, reconciledScope)) return answer({ error: "context-changed" });
      const read = await $.process.run(argv(scope, "list"), { cwd: scope.repo, timeoutMs: 30_000 });
      if (read.isStdoutTruncated || (read.exitCode !== 0 && read.exitCode !== 2)) throw new Error("receipt read failed");
      const value = observation(read.stdout);
      if (!("receipts" in value)) return answer(FAILED);
      const current = selectedScope(await Promise.all([
        $.env.get("ARMORY_RECEIPTS_REPO"), $.env.get("ARMORY_RECEIPTS_CONFIG"),
        $.env.get("ARMORY_RECEIPTS_DATA_ROOT"), $.env.get("ARMORY_RECEIPTS_ACCOUNT"),
        $.env.get("ARMORY_RECEIPTS_WORK_CONTEXT"), $.session.id(), $.plugin.root,
      ]));
      if (epoch !== observedEpoch || !sameScope(scope, current)) return answer({ error: "context-changed" });
      if (owner !== undefined && (mode === "wait" || mode === "cancel") && active === owner) active = undefined;
      // The API promises only that return() kills the direct helper. Neither it
      // nor stream settlement proves graceful signalling or descendant cleanup.
      // An interrupted helper is reconciled as incomplete/unknown by the store.
      // Keep that limitation explicit even if older receipts contain successes.
      return owner?.earlyClose ? answer({ state: "cancellation-unconfirmed", applicability: "unknown", evidence: value }) : answer(value);
    } catch { return answer(FAILED); }
  });

  on("session.end", async ($, e, next) => {
    // /clear and /resume do not refire session.start. Retain registration, revoke
    // every in-flight selector, and reconcile ONLY the original owned scope.
    epoch++;
    const owner = active;
    if (owner !== undefined) {
      await close(owner);
      const scope = owner.scope;
      if (scope !== undefined && owner.stream !== undefined) {
        try {
          const read = await $.process.run(argv(scope, "reconcile"), { cwd: scope.repo, timeoutMs: 30_000 });
          if (!read.isStdoutTruncated) observation(read.stdout);
        } catch { /* No proof/cleanup claim: session.end has a shared 1.5s default budget. */ }
      }
      if (active === owner) active = undefined;
    }
    return next(e);
  });
}
