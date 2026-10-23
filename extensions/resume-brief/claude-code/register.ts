import { CLAUDE_HOST_SCHEMA, projectClaudeSession } from "../core/claude-session.ts";
import type { ClaudeHostPayload, Reading } from "../core/claude-session.ts";
import { ARGUMENT_HINT, COMMAND, COMMAND_DESCRIPTION, CommandError, HELP, parseCommand, parseHelperAnswer } from "../core/protocol.ts";
import type { BriefCommand, BriefError } from "../core/protocol.ts";
import { asciiJson, renderError, renderResult } from "../core/render.ts";

// Only the declared Claude Code 2.1.309 API used here, matching the generated
// SDK signatures. The module has no runtime dependency on an SDK, Node, Bun, a
// checkout, a model turn or a UI surface; the bundled helper performs every
// filesystem and Git effect through the explicit `$.process.run` boundary.
interface SessionMessageRow { role: "user" | "assistant"; text: string; toolUses: readonly unknown[] }
interface ModApi {
  plugin: { readonly root: string };
  env: { get(name: string): Promise<string | undefined> };
  session: {
    id(): Promise<string>;
    cwd(): Promise<string>;
    root(): Promise<string>;
    turns(): Promise<number>;
    usage(): Promise<{ startedAt: number }>;
    messages(): Promise<SessionMessageRow[]>;
  };
  command: {
    list(): Promise<{ name: string }[]>;
    register(spec: { name: string; description: string; argumentHint?: string }): Promise<unknown>;
  };
  process: {
    run(argv: readonly string[], init?: { cwd?: string; env?: Record<string, string>; stdin?: string; timeoutMs?: number }): Promise<{
      exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean;
    }>;
  };
}
type Next<E> = (event: E) => Promise<unknown>;
interface EndEvent { sessionId: string; reason: string }
interface CommandEvent { command: string; args: string }
type On = {
  (event: "session.start", hook: ($: ModApi, e: unknown, next: Next<unknown>) => Promise<unknown>): unknown;
  (event: "session.end", hook: ($: ModApi, e: EndEvent, next: Next<EndEvent>) => Promise<unknown>): unknown;
  (event: "command.run", matcher: { command: string }, hook: ($: ModApi, e: CommandEvent) => Promise<{ text: string }>): unknown;
};

interface Scope {
  repo: string; data: string; account: string; session: string; helper: string;
  context: string | null; ompSession: string | null; ompHandoff: string | null; receipt: string | null;
}
const HELPER_TIMEOUT_MS = 30_000;
const CONFIGURATION_HINT = "set ARMORY_BRIEF_REPO, ARMORY_BRIEF_DATA_ROOT and ARMORY_BRIEF_ACCOUNT; record and reopen also need ARMORY_BRIEF_CONTEXT";

function text(value: string): { text: string } { return { text: value }; }
function failed(error: BriefError["error"], detail: string | null = null, json = false): { text: string } {
  const answer: BriefError = { error, detail };
  return text(json ? `${asciiJson(answer)}\n` : renderError(answer));
}

function valid(value: string): boolean {
  if (value.length === 0 || value.length > 4096) return false;
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) return false;
  }
  return true;
}

/** Explicit environment selection plus the host's session id; refuse anything partial. */
function selectedScope(values: readonly (string | undefined)[], root: string): Scope {
  const [repo, data, account, context, ompSession, ompHandoff, receipt, session] = values;
  const optional = [context, ompSession, ompHandoff, receipt];
  if (repo === undefined || data === undefined || account === undefined || session === undefined
    || ![repo, data, account, session, root].every(valid) || !optional.every((item) => item === undefined || valid(item))
    || !/^[\x21-\x7e]{1,256}$/.test(account)) {
    throw new Error("explicit resume-brief configuration required");
  }
  return {
    repo, data, account, session, helper: `${root}/helpers/claude-cli.js`,
    context: context ?? null, ompSession: ompSession ?? null, ompHandoff: ompHandoff ?? null, receipt: receipt ?? null,
  };
}

function sameScope(left: Scope, right: Scope): boolean {
  return left.repo === right.repo && left.data === right.data && left.account === right.account && left.session === right.session
    && left.helper === right.helper && left.context === right.context && left.ompSession === right.ompSession
    && left.ompHandoff === right.ompHandoff && left.receipt === right.receipt;
}

function argv(scope: Scope, command: Exclude<BriefCommand, { action: "help" }>): string[] {
  const result = ["bun", scope.helper, command.action, "--repo", scope.repo, "--data-root", scope.data, "--account", scope.account, "--session", scope.session];
  for (const [name, value] of [["--context", scope.context], ["--omp-session", scope.ompSession], ["--omp-handoff", scope.ompHandoff], ["--receipt", scope.receipt]] as const) {
    if (value !== null) result.push(name, value);
  }
  if (command.action === "reopen" || command.action === "show") result.push("--snapshot", command.snapshot);
  return result;
}

function reading<T>(settled: PromiseSettledResult<T>): Reading<unknown> {
  return settled.status === "fulfilled" ? { ok: true, value: settled.value } : { ok: false };
}

export function register(on: On): void {
  let epoch = 0;
  let registration: Promise<void> | undefined;
  let ready = false;

  on("session.start", async ($, e, next) => {
    if (registration === undefined) {
      const completion = Promise.withResolvers<undefined>();
      registration = completion.promise;
      try {
        const commands = await $.command.list();
        if (commands.some((command) => command.name === COMMAND)) throw new Error("Armory brief command name collision");
        await $.command.register({ name: COMMAND, description: COMMAND_DESCRIPTION, argumentHint: ARGUMENT_HINT });
        ready = true;
        completion.resolve(undefined);
      } catch (error) { completion.reject(error); }
    }
    await registration;
    return next(e);
  });

  on("command.run", { command: COMMAND }, async ($, e) => {
    let command: BriefCommand;
    try { command = parseCommand(e.args); } catch (error) {
      return text(`${renderError({ error: "invalid-arguments", detail: error instanceof CommandError ? error.message : null })}${HELP}`);
    }
    if (command.action === "help") return text(HELP);
    if (!ready) return failed("session-unavailable", null, command.json);
    const observed = epoch;
    let scope: Scope;
    try {
      scope = selectedScope(await Promise.all([
        $.env.get("ARMORY_BRIEF_REPO"), $.env.get("ARMORY_BRIEF_DATA_ROOT"), $.env.get("ARMORY_BRIEF_ACCOUNT"),
        $.env.get("ARMORY_BRIEF_CONTEXT"), $.env.get("ARMORY_BRIEF_OMP_SESSION"), $.env.get("ARMORY_BRIEF_OMP_HANDOFF"),
        $.env.get("ARMORY_BRIEF_RECEIPT"), $.session.id(),
      ]), $.plugin.root);
    } catch { return failed("invalid-configuration", CONFIGURATION_HINT, command.json); }
    try {
      // Record and reopen observe the current host session. Only counts and
      // locations leave this hook; message text and tool bodies do not.
      let payload: ClaudeHostPayload = { schema: CLAUDE_HOST_SCHEMA, claudeSessionUnavailable: "host-api-unavailable" };
      if (command.action === "record" || command.action === "reopen") {
        const [cwd, root, turns, usage, messages] = await Promise.allSettled([
          $.session.cwd(), $.session.root(), $.session.turns(), $.session.usage(), $.session.messages(),
        ]);
        payload = projectClaudeSession({
          sessionId: scope.session, cwd: reading(cwd), root: reading(root), turns: reading(turns),
          startedAt: usage.status === "fulfilled" ? { ok: true, value: usage.value.startedAt } : { ok: false },
          messages: reading(messages),
        });
      }
      const result = await $.process.run(argv(scope, command), { cwd: scope.repo, stdin: JSON.stringify(payload), timeoutMs: HELPER_TIMEOUT_MS });
      // Revalidate the observation scope before publishing anything.
      const after = selectedScope(await Promise.all([
        $.env.get("ARMORY_BRIEF_REPO"), $.env.get("ARMORY_BRIEF_DATA_ROOT"), $.env.get("ARMORY_BRIEF_ACCOUNT"),
        $.env.get("ARMORY_BRIEF_CONTEXT"), $.env.get("ARMORY_BRIEF_OMP_SESSION"), $.env.get("ARMORY_BRIEF_OMP_HANDOFF"),
        $.env.get("ARMORY_BRIEF_RECEIPT"), $.session.id(),
      ]), $.plugin.root);
      if (epoch !== observed || !sameScope(scope, after)) return failed("context-changed", null, command.json);
      if (result.isStdoutTruncated || (result.exitCode !== 0 && result.exitCode !== 1 && result.exitCode !== 2)) return failed("operation-failed", null, command.json);
      const answer = parseHelperAnswer(JSON.parse(result.stdout) as unknown);
      return text(command.json ? `${asciiJson(answer)}\n` : "error" in answer ? renderError(answer) : renderResult(answer));
    } catch { return failed("operation-failed", null, command.json); }
  });

  on("session.end", async (_$, e, next) => {
    // /clear and /resume do not refire session.start. Keep the registration and
    // revoke every in-flight invocation; a helper already running finishes its
    // bounded read, but its answer is never published into another session.
    epoch++;
    return next(e);
  });
}
