import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import type { Context } from "../core/index.ts";
import { assertContext } from "../core/validation.ts";
import { projectReceipt } from "../helpers/evidence.ts";
import type { ReceiptProjection } from "../helpers/evidence.ts";
import { executeGate } from "../helpers/runner.ts";
import { resolveRepository } from "../helpers/scope.ts";
import { createStore } from "../helpers/storage.ts";

interface Options {
  repositoryRoot: string;
  configPath: string;
  dataRoot: string;
  context: Context;
}

type Observation = { state: "running" } | ReceiptProjection | { receipts: ReceiptProjection[] } | { error: string };
interface OwnedTask { abort: AbortController; done: Promise<void>; }
interface SessionState { active: OwnedTask | null; }

const COMMANDS = {
  "armory-verify": "Run one configured verification gate; use /armory-evidence wait or cancel",
  "armory-evidence": "Reopen private verification evidence; optional wait or cancel",
} as const;
const WIDGET = "armory-receipts";

export default function verificationReceipts(pi: ExtensionAPI): void {
  for (const [suffix, description] of [
    ["repo", "Explicit Git worktree root for verification"],
    ["config", "Worktree-relative verification configuration path"],
    ["data-root", "External private verification state root"],
    ["account", "Opaque account partition reference, not authentication"],
    ["work-context", "Opaque work-context partition reference"],
  ] as const) pi.registerFlag(`armory-receipts-${suffix}`, { type: "string", description });

  const sessions = new Map<string, SessionState>();
  let accepting = false;
  let transition = 0;
  let registered = false;

  function publish(ctx: ExtensionContext, value: Observation): void {
    const text = JSON.stringify(value);
    pi.sendMessage({ customType: "armory-receipts", content: text, display: true }, { triggerTurn: false });
    if (ctx.mode === "tui" && ctx.hasUI) ctx.ui.setWidget(WIDGET, [text]);
  }

  function options(ctx: ExtensionContext): Options {
    const required = (suffix: string): string => {
      const value = pi.getFlag(`armory-receipts-${suffix}`);
      if (typeof value !== "string" || value.trim().length === 0 || value.includes("\0")) throw new Error("missing-configuration");
      return value;
    };
    const result: Options = {
      repositoryRoot: required("repo"), configPath: required("config"), dataRoot: required("data-root"),
      context: { host: "omp", sessionId: ctx.sessionManager.getSessionId(), accountId: required("account"), workContext: required("work-context") },
    };
    assertContext(result.context);
    return result;
  }

  function stateFor(ctx: ExtensionContext): SessionState | undefined {
    if (!accepting) return undefined;
    const id = ctx.sessionManager.getSessionId();
    let state = sessions.get(id);
    if (state === undefined) { state = { active: null }; sessions.set(id, state); }
    return state;
  }

  function isCurrent(scope: Options, state: SessionState, ctx: ExtensionContext): boolean {
    return accepting && sessions.get(scope.context.sessionId) === state && ctx.sessionManager.getSessionId() === scope.context.sessionId;
  }

  async function evidence(scope: Options): Promise<{ receipts: ReceiptProjection[] }> {
    const repository = await resolveRepository(scope.repositoryRoot);
    const store = await createStore(scope.dataRoot, repository, scope.context);
    const receipts: ReceiptProjection[] = [];
    for (const receipt of await store.list()) receipts.push(await projectReceipt(receipt, scope, store.key));
    return { receipts };
  }

  async function verify(args: string, ctx: ExtensionContext): Promise<void> {
    const tokens = args.trim().split(/\s+/u);
    if (tokens.length !== 1 || tokens[0] === "") { publish(ctx, { error: "invalid-arguments" }); return; }
    const gateId = tokens[0];
    if (gateId === undefined) { publish(ctx, { error: "invalid-arguments" }); return; }
    const state = stateFor(ctx);
    if (state === undefined) { publish(ctx, { error: "session-unavailable" }); return; }
    if (state.active !== null) { publish(ctx, { error: "verification-running" }); return; }
    let scope: Options;
    try { scope = options(ctx); } catch { publish(ctx, { error: "invalid-configuration" }); return; }
    const abort = new AbortController();
    // Install ownership before any await or filesystem/process work. The task's
    // retained promise includes durable publication, observation and cleanup.
    const task: OwnedTask = { abort, done: Promise.resolve().then(async () => {
      let value: Observation;
      try {
        const receipt = await executeGate({ ...scope, gateId, signal: abort.signal });
        const store = await createStore(scope.dataRoot, await resolveRepository(scope.repositoryRoot), scope.context);
        value = await projectReceipt(await store.read(receipt.plan.executionId), scope, store.key);
      } catch { value = { error: "operation-failed" }; }
      try {
        if (isCurrent(scope, state, ctx)) publish(ctx, value);
      } catch { process.stderr.write('{"error":"publication-failed"}\n'); }
      finally { if (state.active === task) state.active = null; }
    }) };
    state.active = task;
    publish(ctx, { state: "running" });
  }

  async function observe(args: string, ctx: ExtensionContext): Promise<void> {
    const action = args.trim();
    if (action !== "" && action !== "wait" && action !== "cancel") { publish(ctx, { error: "invalid-arguments" }); return; }
    const state = stateFor(ctx);
    if (state === undefined) { publish(ctx, { error: "session-unavailable" }); return; }
    let scope: Options;
    try { scope = options(ctx); } catch { publish(ctx, { error: "invalid-configuration" }); return; }
    const task = state.active;
    if (action === "cancel") task?.abort.abort();
    if (action !== "") await task?.done;
    // A wait resumed after session_switch must not publish into the new session.
    if (!isCurrent(scope, state, ctx)) return;
    let value: Observation;
    try { value = await evidence(scope); } catch { value = { error: "operation-failed" }; }
    if (isCurrent(scope, state, ctx)) publish(ctx, value);
  }

  async function changeSession(ctx: ExtensionContext, next: boolean): Promise<void> {
    const ownTransition = ++transition;
    accepting = false;
    const owned = [...sessions.values()].flatMap((state) => state.active === null ? [] : [state.active]);
    for (const task of owned) task.abort.abort();
    await Promise.all(owned.map((task) => task.done));
    if (ownTransition !== transition) return;
    sessions.clear();
    if (ctx.mode === "tui" && ctx.hasUI) ctx.ui.setWidget(WIDGET, undefined);
    accepting = next;
  }

  pi.on("session_start", () => {
    // getCommands requires an initialized runtime. Check both names before
    // registering either: OMP aggregation is last-wins, not collision-safe.
    const existing = pi.getCommands();
    for (const [name, description] of Object.entries(COMMANDS)) {
      const matches = existing.filter((command) => command.name === name);
      if (matches.some((command) => !registered || command.source !== "extension" || command.description !== description)
        || matches.length > 1 || (registered && matches.length !== 1)) {
        accepting = false;
        throw new Error("command-collision");
      }
    }
    if (!registered) {
      pi.registerCommand("armory-verify", { description: COMMANDS["armory-verify"], handler: verify });
      pi.registerCommand("armory-evidence", { description: COMMANDS["armory-evidence"], handler: observe });
      registered = true;
    }
    accepting = true;
  });
  pi.on("session_switch", async (_event, ctx) => { await changeSession(ctx, true); });
  pi.on("session_shutdown", async (_event, ctx) => { await changeSession(ctx, false); });
}
