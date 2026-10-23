import { renderRadar, transitionKey } from "../core/index.ts";
import type { RadarView } from "../core/index.ts";
import { ARGUMENT_HINT, COMMAND, COMMAND_DESCRIPTION, HELP, MAX_HELPER_BYTES, asciiJson, cleanupUnconfirmed, parseCommand, parseHelperAnswer, renderFailure } from "../core/protocol.ts";
import type { DeliveryCommand, Failure } from "../core/protocol.ts";
import { record } from "../core/validation.ts";

// This is the used structural subset of Claude Code 2.1.309's generated SDK.
// Static core imports are pure; every helper/gh effect belongs to the host's
// process.spawn stream, never to this module's environment or a model turn.
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
const HELPER_TIMEOUT_MS = 65_000;

function failed(error: Failure, json: boolean): { text: string } { return { text: renderFailure(error, json) }; }

// Count UTF-8 without retaining stderr or allocating a second copy of a chunk.
// The host guarantees that a multi-byte character is not split across pieces.
function bytes(value: string): number {
  let size = 0;
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    size += code <= 0x7f ? 1 : code <= 0x7ff ? 2 : code <= 0xffff ? 3 : 4;
  }
  return size;
}
function clearTimer(invocation: Invocation): void {
  if (invocation.timer === null) return;
  const timer = invocation.timer;
  invocation.timer = null;
  try { timer.cancel(); } catch { invocation.cleanupFailed = true; }
}

/** Mark invalid synchronously, then end AND await the actual owned stream. */
function stop(invocation: Invocation, reason: Failure): Promise<boolean> {
  invocation.reason ??= reason;
  clearTimer(invocation);
  if (invocation.cleanup !== null) return invocation.cleanup;
  if (invocation.stream === null || invocation.completed) return Promise.resolve(!invocation.cleanupFailed);
  let returned: Promise<boolean>;
  try {
    // AsyncGenerator.return's argument is only the iterator's return value, NOT
    // the child's exit status. Supply no synthetic status; only result below
    // represents process completion. The SDK types require an argument.
    returned = invocation.stream.return(undefined as never).then(() => true, () => false);
  } catch { returned = Promise.resolve(false); }
  invocation.cleanup = Promise.all([returned, invocation.result]).then(([closed]) => {
    // result rejecting on early close is expected and was observed immediately
    // at spawn. A failing return, however, is not confirmed cleanup.
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
  let session: string | null = null;
  let endedSession: string | null = null;
  let current: Invocation | null = null;
  const inflight = new Set<Invocation>();
  const transitions = new Map<string, string>();

  const owns = (invocation: Invocation): boolean => current === invocation && invocation.epoch === epoch && invocation.reason === null;
  const revoke = async (): Promise<void> => {
    const clean = await Promise.all([...inflight].map((invocation) => stop(invocation, "context-changed")));
    if (clean.some((value) => !value)) {
      cleanupBlocked = true;
      throw new Error("Delivery Radar helper cleanup failed");
    }
  };

  // The default command row truncates long results. Keep this command's full
  // text in its own native frame, distinct from ambient host notices.
  on("ui.render", { component: "CommandOutput", props: { command: COMMAND } },
    (_$, event) => ({ type: "Box", props: { borderStyle: "single", flexDirection: "column" },
      children: [{ type: "Text", props: { wrap: "wrap" }, children: [event.props.text] }] }));

  on("session.start", async ($, event, next) => {
    epoch++;
    session = null;
    endedSession = null;
    transitions.clear();
    await revoke();
    if (registration === undefined) {
      const completion = Promise.withResolvers<undefined>();
      registration = completion.promise;
      try {
        const commands = await $.command.list();
        if (commands.some((command) => command.name === COMMAND)) throw new Error("Delivery Radar command name collision");
        await $.command.register({ name: COMMAND, description: COMMAND_DESCRIPTION, argumentHint: ARGUMENT_HINT });
        ready = true;
        completion.resolve(undefined);
      } catch (error) { completion.reject(error); }
    }
    await registration;
    return next(event);
  });

  on("command.run", { command: COMMAND }, async ($, event, next) => {
    let command: DeliveryCommand;
    try { command = parseCommand(event.args); } catch { return failed("invalid-arguments", false); }
    if (command.action === "help") return { text: HELP };
    if (!ready) return failed("session-unavailable", command.json);
    if (cleanupBlocked) return failed("operation-failed", command.json);

    // Reserve ownership and install interruption before the first await, even
    // when the first host session read has not answered yet.
    const invocation: Invocation = { epoch, reason: null, stream: null, result: null, completed: false, cleanup: null, cleanupFailed: false, timer: null };
    const previous = inflight.size === 0 ? null : [...inflight];
    current = invocation;
    inflight.add(invocation);
    const interrupt = (): void => { void stop(invocation, "cancelled"); };
    next.signal.addEventListener("abort", interrupt, { once: true });
    if (next.signal.aborted) interrupt();
    let owner: string | null = null;
    let view: RadarView | undefined;
    let error: Failure | null = null;
    try {
      if (previous !== null && (await Promise.all(previous.map((task) => stop(task, "context-changed")))).some((closed) => !closed)) {
        invocation.cleanupFailed = true;
        throw new Error("cleanup failed");
      }
      if (owns(invocation)) {
        owner = await $.session.id();
        if (!owns(invocation)) invocation.reason ??= "context-changed";
        else if (typeof owner !== "string" || owner.length === 0 || owner.length > 4096 || /\p{Cc}/u.test(owner) || owner === endedSession) error = "session-unavailable";
        else {
          if (session !== owner) { session = owner; transitions.clear(); }
          const stream = $.process.spawn({ argv: ["bun", `${$.plugin.root}/helpers/cli.js`, "refresh", "--repo", command.selection.repository, "--prs", command.selection.pullRequests.join(","), "--format", "json"] });
          invocation.stream = stream;
          // Observe rejection BEFORE any pull: cancellation/unload can reject
          // result without a final output piece, including before first next().
          invocation.result = stream.result.then((exit): Outcome => ({ ok: true, exit }), (): Outcome => ({ ok: false }));
          if (invocation.reason !== null) await stop(invocation, invocation.reason);
          else {
            invocation.timer = $.clock.after(HELPER_TIMEOUT_MS, () => { void stop(invocation, "operation-failed"); });
            const output: string[] = [];
            let size = 0;
            for await (const chunk of stream) {
              if (!owns(invocation)) break;
              // Bound BOTH pipes, before storing text or attempting JSON.parse.
              if (chunk.text.length > MAX_HELPER_BYTES - size || (size += bytes(chunk.text)) > MAX_HELPER_BYTES) {
                await stop(invocation, "operation-failed");
                break;
              }
              if (chunk.stream === "stdout") output.push(chunk.text);
            }
            const result = await invocation.result;
            invocation.completed = true;
            clearTimer(invocation);
            const succeeded = result.ok && result.exit.code === 0 && result.exit.signal === null;
            const payload: unknown = succeeded ? JSON.parse(output.join("")) : null;
            if (record(payload) && cleanupUnconfirmed(payload.observation)) invocation.cleanupFailed = true;
            if (owns(invocation)) {
              if (!succeeded || invocation.cleanupFailed) error = "operation-failed";
              else {
                const now = await $.clock.now();
                if (owns(invocation)) view = parseHelperAnswer(payload, command.selection, now);
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
      // Even failed observations never publish a source result into a different
      // host session. /clear and /resume need not fire another session.start.
      if (owner !== null && owns(invocation)) {
        try {
          const after = await $.session.id();
          if (owns(invocation) && after !== owner) {
            invocation.reason = "context-changed";
            session = null;
            transitions.clear();
          }
        } catch { error = "session-unavailable"; }
      }
      if (next.signal.aborted) invocation.reason ??= "cancelled";
      next.signal.removeEventListener("abort", interrupt);
      inflight.delete(invocation);
      if (invocation.cleanupFailed) cleanupBlocked = true;
    }
    if (invocation.cleanupFailed) return failed("operation-failed", command.json);
    if (!owns(invocation)) return failed(invocation.reason ?? "context-changed", command.json);
    if (error !== null || view === undefined) return failed(error ?? "operation-failed", command.json);
    const selected = JSON.stringify(command.selection);
    const key = transitionKey(view);
    const before = transitions.get(selected);
    const transition = before !== undefined && before !== key;
    transitions.set(selected, key);
    // These are explicit command responses, never unsolicited notifications.
    // Compact JSON's spaces occur only inside strings. Escape them so terminal
    // word wrapping cannot discard source-title/reason whitespace on copy/read.
    return { text: command.json ? `${asciiJson({ view, transition }).replace(/ /g, "\\u0020")}\n`
      : `Explicit refresh${transition ? "; meaningful evidence transition observed" : ""}.\n${renderRadar(view)}\n` };
  });

  on("session.end", async (_$, event, next) => {
    epoch++;
    endedSession = event.sessionId;
    session = null;
    transitions.clear();
    await revoke();
    return next(event);
  });
  // There is no invented unload hook. In the pinned host, unloading aborts the
  // dispatch and closes its process.spawn streams. The same result observer and
  // finally cleanup above handle that lifecycle; returning this hook does not.
}
