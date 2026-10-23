import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { renderRadar, transitionKey } from "../core/index.ts";
import type { Observation, RadarView } from "../core/index.ts";
import { COMMAND, COMMAND_DESCRIPTION, HELP, asciiJson, cleanupUnconfirmed, parseCommand, parseHelperAnswer, renderFailure } from "../core/protocol.ts";
import type { DeliveryCommand } from "../core/protocol.ts";
import { observe } from "../helpers/github.ts";

interface Runtime {
  observe: typeof observe;
  now: () => number;
}
interface Session {
  id: string;
  semantics: Map<string, string>;
}
interface Owned {
  abort: AbortController;
  done: Promise<void>;
}
interface Correlation {
  host: "omp";
  sessionId: string;
  /** Actual host cwd, not a resolved Git root or an inferred selected repository. */
  cwd?: string;
}
interface Answer {
  view: RadarView;
  /** A changed semantic observation, not an unsolicited/background notification. */
  transition: boolean;
}
class CleanupError extends Error {
  constructor() { super("delivery-radar-cleanup-unconfirmed"); }
}

function sessionId(ctx: ExtensionContext): string | null {
  try {
    const id = ctx.sessionManager.getSessionId();
    return typeof id === "string" && id.length > 0 ? id : null;
  } catch { return null; }
}


/** An injected boundary keeps deterministic tests local without mutating module caches or PATH. */
export function createDeliveryRadar(runtime: Runtime): (pi: ExtensionAPI) => void {
  return (pi) => {
    const owned = new Set<Owned>();
    let active: Owned | null = null;
    let session: Session | null = null;
    let accepting = false;
    let registered = false;
    let epoch = 0;
    let cleanupFailed = false;

    function current(ctx: ExtensionContext, expected: Session, task?: Owned): boolean {
      return accepting && !cleanupFailed && session === expected && sessionId(ctx) === expected.id &&
        (task === undefined || (active === task && !task.abort.signal.aborted));
    }

    function send(ctx: ExtensionContext, expected: Session, text: string, answer: unknown, task?: Owned): void {
      if (!current(ctx, expected, task)) return;
      // Host cwd is correlation data only, never repository selection.
      const host: Correlation = { host: "omp", sessionId: expected.id,
        ...(typeof ctx.cwd === "string" && ctx.cwd.length > 0 ? { cwd: ctx.cwd } : {}) };
      pi.sendMessage({ customType: COMMAND, content: text, display: true,
        details: { ...(answer as Record<string, unknown>), correlation: host } }, { triggerTurn: false });
    }

    async function settle(tasks: readonly Owned[]): Promise<void> {
      // Wait for every owner, even when one rejects: Promise.all alone could
      // return before a different gh process has finished terminating.
      const results = await Promise.allSettled(tasks.map((task) => task.done));
      if (results.some((result) => result.status === "rejected")) {
        cleanupFailed = true;
        accepting = false;
        throw new CleanupError();
      }
    }

    async function handle(args: string, ctx: ExtensionContext): Promise<void> {
      if (!accepting || cleanupFailed) return;
      const expected = session;
      if (expected === null || !current(ctx, expected)) return;
      let command: DeliveryCommand;
      try { command = parseCommand(args); } catch {
        send(ctx, expected, renderFailure("invalid-arguments"), { error: "invalid-arguments" });
        return;
      }
      if (command.action === "help") {
        send(ctx, expected, HELP, { help: true });
        return;
      }
      const previous = [...owned];
      for (const task of previous) task.abort.abort();
      const abort = new AbortController();
      // Promise callbacks cannot run until this synchronous section has added
      // the owner. Lifecycle hooks can cancel even an invocation not yet started.
      const task: Owned = { abort, done: Promise.resolve().then(async () => {
        try {
          await settle(previous);
          if (!current(ctx, expected, task)) return;
          const observation: Observation = await runtime.observe(command.selection, { signal: abort.signal });
          // Inspect termination evidence before suppressing a cancelled result.
          if (cleanupUnconfirmed(observation)) throw new CleanupError();
          if (!current(ctx, expected, task)) return;
          const view = parseHelperAnswer({ observation }, command.selection, runtime.now());
          if (!current(ctx, expected, task)) return;
          const selectionKey = asciiJson(command.selection);
          const key = transitionKey(view);
          const previousKey = expected.semantics.get(selectionKey);
          const answer: Answer = { view, transition: previousKey !== undefined && previousKey !== key };
          const text = command.json ? `${asciiJson(answer)}\n`
            : `${answer.transition ? "Explicit refresh; meaningful transition observed." : "Explicit refresh; current selected evidence."}\n${renderRadar(view)}\n`;
          send(ctx, expected, text, answer, task);
          if (current(ctx, expected, task)) expected.semantics.set(selectionKey, key);
        } catch (error) {
          if (error instanceof CleanupError) {
            cleanupFailed = true;
            accepting = false;
            throw error;
          }
          if (!abort.signal.aborted) send(ctx, expected, renderFailure("operation-failed", command.json), { error: "operation-failed" }, task);
        } finally {
          owned.delete(task);
          if (active === task) active = null;
        }
      }) };
      owned.add(task);
      active = task;
      await task.done;
    }

    async function changeSession(ctx: ExtensionContext, next: boolean): Promise<void> {
      const own = ++epoch;
      const id = sessionId(ctx);
      accepting = false;
      session = null;
      const tasks = [...owned];
      for (const task of tasks) task.abort.abort();
      await settle(tasks);
      if (own !== epoch || cleanupFailed || !next || id === null || sessionId(ctx) !== id) return;
      session = { id, semantics: new Map() };
      accepting = true;
    }

    pi.on("session_start", (_event, ctx) => {
      if (cleanupFailed) throw new CleanupError();
      // Pinned OMP aggregates commands last-wins. Never shadow a command or
      // accept a missing/replaced registration on a later session_start.
      const matches = pi.getCommands().filter((item) => item.name === COMMAND);
      if (matches.length > 1 || (matches.length === 1 && (!registered || matches[0]?.source !== "extension" || matches[0]?.description !== COMMAND_DESCRIPTION)) ||
        (registered && matches.length !== 1)) {
        accepting = false;
        for (const task of owned) task.abort.abort();
        // A later start may reveal a collision while work is still owned.
        return settle([...owned]).then(() => { throw new Error("command-collision"); });
      }
      if (!registered) {
        pi.registerCommand(COMMAND, { description: COMMAND_DESCRIPTION, handler: handle });
        registered = true;
      }
      if (accepting && session !== null && session.id === sessionId(ctx)) return;
      return changeSession(ctx, true);
    });
    pi.on("session_switch", async (_event, ctx) => { await changeSession(ctx, true); });
    pi.on("session_shutdown", async (_event, ctx) => { await changeSession(ctx, false); });
    // OMP 18.12.6 exposes neither a slash-command AbortSignal nor a factory
    // unload disposer. Session disposal/reload must deliver session_shutdown;
    // no key interception, process signal handler or invented hook is installed.
  };
}

export default createDeliveryRadar({ observe, now: () => Date.now() });
