import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { LIMITS } from "../core/index.ts";
import { COMMAND, COMMAND_DESCRIPTION, CommandError, HELP, parseCommand } from "../core/protocol.ts";
import type { BriefCommand, BriefError, BriefResult } from "../core/protocol.ts";
import { asciiJson, renderError, renderResult, summarize } from "../core/render.ts";
import { InputError, listBriefs, recordBrief, reopenBrief, resolveSelection, showBrief } from "../helpers/brief.ts";
import type { RawSelection, Scope } from "../helpers/brief.ts";
import { StateError } from "../helpers/state.ts";

const MESSAGE = "armory-brief";
const WIDGET = "armory-brief";
const CONFIGURATION_HINT = "set --armory-brief-repo, --armory-brief-data-root and --armory-brief-account; record and reopen also need --armory-brief-context";

interface Configured {
  repositoryRoot: string;
  dataRoot: string;
  accountId: string;
  selection: RawSelection | null;
}

/** One invocation, bound to the host session that issued it. */
interface Owned {
  abort: AbortController;
  done: Promise<void>;
}

class ConfigurationError extends Error {}

function failure(error: unknown): BriefError {
  if (error instanceof StateError || error instanceof InputError) return { error: "rejected", detail: error.message.slice(0, 300) };
  return { error: "operation-failed", detail: null };
}

export default function resumeBrief(pi: ExtensionAPI): void {
  for (const [suffix, description] of [
    ["repo", "Explicit Git worktree root for the resume brief"],
    ["context", "Worktree-relative armory.resume-brief.context/v1 artifact"],
    ["data-root", "External private resume-brief state root"],
    ["account", "Opaque account reference used to judge approval origin, not authentication"],
    ["omp-session", "Optional explicitly selected OMP JSONL session file"],
    ["omp-handoff", "Optional explicitly selected OMP handoff-<timestamp>.md file"],
    ["receipt", "Optional explicitly selected Verification Receipts receipt file"],
  ] as const) pi.registerFlag(`armory-brief-${suffix}`, { type: "string", description });

  const owned = new Set<Owned>();
  let accepting = false;
  let registered = false;
  let transition = 0;

  function flag(suffix: string, required: boolean): string | null {
    const value = pi.getFlag(`armory-brief-${suffix}`);
    if (value === undefined && !required) return null;
    if (typeof value !== "string" || value.trim().length === 0 || value.length > 4096 || value.includes("\0")) throw new ConfigurationError(suffix);
    return value;
  }

  function configured(): Configured {
    const accountId = flag("account", true) ?? "";
    if (accountId.length > LIMITS.referenceChars || !/^[\x21-\x7e]+$/.test(accountId)) throw new ConfigurationError("account");
    const contextPath = flag("context", false);
    return {
      repositoryRoot: flag("repo", true) ?? "",
      dataRoot: flag("data-root", true) ?? "",
      accountId,
      selection: contextPath === null ? null : {
        contextPath, ompSessionPath: flag("omp-session", false), ompHandoffPath: flag("omp-handoff", false), receiptPath: flag("receipt", false),
      },
    };
  }

  function current(ctx: ExtensionContext, sessionId: string): boolean {
    return accepting && ctx.sessionManager.getSessionId() === sessionId;
  }

  /** Text is the inert rendering; details carry the same validated answer for programmatic clients. */
  function send(ctx: ExtensionContext, sessionId: string, text: string, details: unknown, widget: string[] | null): void {
    if (!current(ctx, sessionId)) return;
    pi.sendMessage({ customType: MESSAGE, content: text, display: true, details }, { triggerTurn: false });
    if (widget !== null && ctx.mode === "tui" && ctx.hasUI) ctx.ui.setWidget(WIDGET, widget);
  }

  async function run(command: Exclude<BriefCommand, { action: "help" }>, config: Configured, sessionId: string, signal: AbortSignal): Promise<BriefResult> {
    const scope: Scope = { repositoryRoot: config.repositoryRoot, dataRoot: config.dataRoot, context: { host: "omp", accountId: config.accountId, sessionId } };
    if (command.action === "list") return listBriefs(scope, { signal });
    if (command.action === "show") return showBrief(scope, command.snapshot);
    if (config.selection === null) throw new InputError("no context artifact is configured; set --armory-brief-context");
    const selection = await resolveSelection(config.selection);
    if (command.action === "record") return recordBrief(scope, selection, { signal });
    return reopenBrief(scope, command.snapshot, { signal, configured: selection });
  }

  async function handle(args: string, ctx: ExtensionContext): Promise<void> {
    if (!accepting) return;
    const sessionId = ctx.sessionManager.getSessionId();
    let command: BriefCommand;
    try { command = parseCommand(args); } catch (error) {
      const answer: BriefError = { error: "invalid-arguments", detail: error instanceof CommandError ? error.message : null };
      send(ctx, sessionId, `${renderError(answer)}${HELP}`, answer, summarize(answer));
      return;
    }
    if (command.action === "help") { send(ctx, sessionId, HELP, { help: true }, null); return; }
    let config: Configured;
    try { config = configured(); } catch {
      const answer: BriefError = { error: "invalid-configuration", detail: CONFIGURATION_HINT };
      send(ctx, sessionId, command.json ? `${asciiJson(answer)}\n` : renderError(answer), answer, summarize(answer));
      return;
    }
    // Ownership exists before the first await, so a session transition can
    // cancel this read and suppress its publication into another session.
    const abort = new AbortController();
    const done = (async () => {
      let answer: BriefResult | BriefError;
      try { answer = await run(command, config, sessionId, abort.signal); } catch (error) {
        if (abort.signal.aborted) return;
        answer = failure(error);
      }
      if (abort.signal.aborted) return;
      const text = command.json ? `${asciiJson(answer)}\n` : "error" in answer ? renderError(answer) : renderResult(answer);
      send(ctx, sessionId, text, answer, summarize(answer));
    })();
    const task: Owned = { abort, done };
    owned.add(task);
    try { await done; } finally { owned.delete(task); }
  }

  async function changeSession(ctx: ExtensionContext, next: boolean): Promise<void> {
    const own = ++transition;
    accepting = false;
    const tasks = [...owned];
    for (const task of tasks) task.abort.abort();
    await Promise.all(tasks.map((task) => task.done));
    if (own !== transition) return;
    if (ctx.mode === "tui" && ctx.hasUI) ctx.ui.setWidget(WIDGET, undefined);
    accepting = next;
  }

  pi.on("session_start", () => {
    // OMP command aggregation is last-wins: refuse a foreign or duplicate
    // registration instead of shadowing it or being shadowed.
    const matches = pi.getCommands().filter((item) => item.name === COMMAND);
    if (matches.length > 1 || (matches.length === 1 && (!registered || matches[0]?.source !== "extension" || matches[0]?.description !== COMMAND_DESCRIPTION))
      || (registered && matches.length !== 1)) {
      accepting = false;
      throw new Error("command-collision");
    }
    if (!registered) {
      pi.registerCommand(COMMAND, { description: COMMAND_DESCRIPTION, handler: handle });
      registered = true;
    }
    accepting = true;
  });
  pi.on("session_switch", async (_event, ctx) => { await changeSession(ctx, true); });
  pi.on("session_shutdown", async (_event, ctx) => { await changeSession(ctx, false); });
}
