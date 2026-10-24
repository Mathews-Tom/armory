import { ARGUMENT_HINT, COMMAND, COMMAND_DESCRIPTION, HELP, HELPER_TIMEOUT_MS, MAX_HELPER_BYTES, helperArgv, parseCommand, parseHelperAnswer, projectAnswer, renderAnswer, renderFailure, requestsJson } from "../core/protocol.ts";
import type { Failure, HelperAnswer, NativeView, PreflightCommand } from "../core/protocol.ts";

// Structural subset of the pinned Claude Code 2.1.310 SDK. Core imports are
// pure; the host owns every executable effect, including interruption cleanup.
interface Chunk { stream: "stdout" | "stderr"; text: string }
interface Exit { code: number | null; signal: string | null }
export type Stream = AsyncGenerator<Chunk, Exit> & { readonly result: Promise<Exit> };
export interface Api {
  plugin: { readonly root: string };
  session: { id(): Promise<string> };
  command: {
    list(): Promise<{ name: string }[]>;
    register(spec: { name: string; description: string; argumentHint?: string }): Promise<unknown>;
  };
  process: { spawn(request: { argv: readonly string[] }): Stream };
  clock: { now(): Promise<number>; after(ms: number, fn: () => void): { cancel(): void } };
}
type Next<E> = ((event: E) => Promise<unknown>) & { readonly signal: AbortSignal };
interface End { sessionId: string; reason: string }
interface Command { command: string; args: string }
export type On = {
  (event: "session.start", hook: ($: Api, e: unknown, next: Next<unknown>) => Promise<unknown>): unknown;
  (event: "session.end", hook: ($: Api, e: End, next: Next<End>) => Promise<unknown>): unknown;
  (event: "command.run", matcher: { command: string }, hook: ($: Api, e: Command, next: Next<Command>) => Promise<{ text: string }>): unknown;
  (event: "ui.render", matcher: { component: "CommandOutput"; props: { command: string } }, hook: ($: unknown, e: { props: { text: string } }) => {
    type: "Box"; props: { borderStyle: "single"; flexDirection: "column" };
    children: { type: "Text"; props: { wrap: "wrap" }; children: string[] }[];
  }): unknown;
};
type Outcome = { ok: true; exit: Exit } | { ok: false };
interface Invocation {
  epoch: number;
  reason: Failure | null;
  stream: Stream | null;
  result: Promise<Outcome> | null;
  completed: boolean;
  cleanup: Promise<boolean> | null;
  cleanupFailed: boolean;
  timer: { cancel(): void } | null;
}
const failed = (error: Failure, json: boolean): { text: string } => ({ text: renderFailure(error, json) });
function bytes(value: string): number {
  let size = 0;
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    size += code <= 0x7f ? 1 : code <= 0x7ff ? 2 : code <= 0xffff ? 3 : 4;
  }
  return size;
}
function clearTimer(invocation: Invocation): void {
  const timer = invocation.timer;
  invocation.timer = null;
  try { timer?.cancel(); } catch { invocation.cleanupFailed = true; }
}
function stop(invocation: Invocation, reason: Failure): Promise<boolean> {
  invocation.reason ??= reason;
  clearTimer(invocation);
  if (invocation.cleanup !== null) return invocation.cleanup;
  if (invocation.stream === null || invocation.completed) return Promise.resolve(!invocation.cleanupFailed);
  let returned: Promise<boolean>;
  try {
    // The iterator argument is NOT a process status. Only stream.result below
    // observes the real child exit; it is subscribed immediately after spawn.
    returned = invocation.stream.return(undefined as never).then(() => true, () => false);
  } catch { returned = Promise.resolve(false); }
  invocation.cleanup = Promise.all([returned, invocation.result]).then(([closed]) => {
    if (!closed) invocation.cleanupFailed = true;
    return !invocation.cleanupFailed;
  });
  return invocation.cleanup;
}

export function register(on: On): void {
  let registration: Promise<void> | undefined;
  let ready = false;
  let cleanupBlocked = false;
  let epoch = 0;
  let endedSession: string | null = null;
  let current: Invocation | null = null;
  const inflight = new Set<Invocation>();
  const owns = (invocation: Invocation): boolean => current === invocation && invocation.epoch === epoch && invocation.reason === null;
  const revoke = async (): Promise<void> => {
    // stop never rejects: every owner is awaited even if another cleanup fails.
    const clean = await Promise.all([...inflight].map((invocation) => stop(invocation, "context-changed")));
    if (clean.some((value) => !value)) {
      cleanupBlocked = true;
      throw new Error("Run Preflight helper cleanup unconfirmed");
    }
  };
  on("ui.render", { component: "CommandOutput", props: { command: COMMAND } },
    (_$, event) => ({ type: "Box", props: { borderStyle: "single", flexDirection: "column" },
      children: [{ type: "Text", props: { wrap: "wrap" }, children: [event.props.text] }] }));
  on("session.start", async ($, event, next) => {
    epoch++;
    endedSession = null;
    await revoke();
    if (registration === undefined) {
      const completion = Promise.withResolvers<undefined>();
      registration = completion.promise;
      try {
        const commands = await $.command.list();
        if (commands.some((command) => command.name === COMMAND)) throw new Error("Run Preflight command name collision");
        await $.command.register({ name: COMMAND, description: COMMAND_DESCRIPTION, argumentHint: ARGUMENT_HINT });
        ready = true;
        completion.resolve(undefined);
      } catch (error) { completion.reject(error); }
    }
    await registration;
    return next(event);
  });
  on("session.end", async (_$, event, next) => {
    epoch++;
    endedSession = event.sessionId;
    await revoke();
    return next(event);
  });
  on("command.run", { command: COMMAND }, async ($, event, next) => {
    let command: PreflightCommand;
    try { command = parseCommand(event.args); } catch { return failed("invalid-arguments", requestsJson(event.args)); }
    if (command.action === "help") return { text: HELP };
    if (!ready) return failed("session-unavailable", command.json);
    if (cleanupBlocked) return failed("operation-failed", command.json);
    const invocation: Invocation = { epoch, reason: null, stream: null, result: null, completed: false, cleanup: null, cleanupFailed: false, timer: null };
    const previous = [...inflight];
    current = invocation;
    inflight.add(invocation);
    const interrupt = (): void => { void stop(invocation, "cancelled"); };
    next.signal.addEventListener("abort", interrupt, { once: true });
    if (next.signal.aborted) interrupt();
    let owner: string | null = null;
    let report: HelperAnswer | undefined;
    let view: NativeView | undefined;
    let error: Failure | null = null;
    try {
      if ((await Promise.all(previous.map((task) => stop(task, "context-changed")))).some((closed) => !closed)) {
        invocation.cleanupFailed = true;
        throw new Error("cleanup unconfirmed");
      }
      if (owns(invocation)) {
        owner = await $.session.id();
        if (!owns(invocation)) invocation.reason ??= "context-changed";
        else if (typeof owner !== "string" || owner.length === 0 || owner.length > 4096 || /\p{Cc}/u.test(owner) || owner === endedSession) error = "session-unavailable";
        else {
          const stream = $.process.spawn({ argv: helperArgv(command, $.plugin.root) });
          invocation.stream = stream;
          invocation.result = stream.result.then((exit): Outcome => ({ ok: true, exit }), (): Outcome => ({ ok: false }));
          if (invocation.reason !== null) await stop(invocation, invocation.reason);
          else {
            invocation.timer = $.clock.after(HELPER_TIMEOUT_MS, () => { void stop(invocation, "operation-failed"); });
            const output: string[] = [];
            let size = 0;
            for await (const chunk of stream) {
              if (!owns(invocation)) break;
              if (chunk.text.length > MAX_HELPER_BYTES - size || (size += bytes(chunk.text)) > MAX_HELPER_BYTES) {
                await stop(invocation, "operation-failed");
                break;
              }
              if (chunk.stream === "stdout") output.push(chunk.text);
            }
            const result = await invocation.result;
            invocation.completed = result.ok;
            clearTimer(invocation);
            if (owns(invocation)) {
              if (!result.ok || result.exit.signal !== null || (result.exit.code !== 0 && result.exit.code !== 2) || invocation.cleanupFailed) error = "operation-failed";
              else {
                const now = await $.clock.now();
                if (owns(invocation)) {
                  report = parseHelperAnswer(JSON.parse(output.join("")), command, $.plugin.root, now, result.exit.code);
                  view = projectAnswer(report, command.selection);
                }
              }
            }
          }
        }
      }
    } catch { error = "operation-failed"; }
    finally {
      if (!invocation.completed && invocation.stream !== null) await stop(invocation, invocation.reason ?? "operation-failed");
      if (invocation.cleanup !== null) await invocation.cleanup;
      clearTimer(invocation);
      if (owner !== null && owns(invocation)) {
        try { if (await $.session.id() !== owner) invocation.reason ??= "context-changed"; }
        catch { error = "session-unavailable"; }
      }
      if (next.signal.aborted) invocation.reason ??= "cancelled";
      next.signal.removeEventListener("abort", interrupt);
      inflight.delete(invocation);
      if (invocation.cleanupFailed) cleanupBlocked = true;
    }
    if (invocation.cleanupFailed) return failed("operation-failed", command.json);
    if (!owns(invocation)) return failed(invocation.reason ?? "context-changed", command.json);
    if (error !== null || report === undefined || view === undefined) return failed(error ?? "operation-failed", command.json);
    const text = renderAnswer(report, view, command.json);
    // The native terminal wraps at spaces. Preserve spaces within JSON strings
    // so copying the complete frame remains lossless, including selected paths.
    return { text: command.json ? text.replace(/ /g, "\\u0020") : text };
  });
}
