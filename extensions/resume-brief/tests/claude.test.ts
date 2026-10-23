import { afterEach, expect, test } from "bun:test";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { register } from "../claude-code/register.ts";
import type { RecordResult, ReopenResult } from "../core/protocol.ts";
import { BLOCKERS, project } from "./fixture.ts";
import type { Project } from "./fixture.ts";

// A recording `$` boundary, not an implementation of the native engine: every
// process effect really runs the bundled helper against real temporary Git
// repositories and private state. Session answers are synthetic host values.

type Hook = ($: unknown, event: unknown, next: (event: unknown) => Promise<unknown>) => Promise<unknown>;
interface Row { role: "user" | "assistant"; text: string; toolUses: unknown[] }
interface Run { exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean }

const SECRET = "PRIVATE CLAUDE TRANSCRIPT";
const projects: Project[] = [];
afterEach(async () => {
  for (const item of projects.splice(0)) await item.cleanup();
});

async function plugin(item: Project): Promise<string> {
  const root = join(item.base, "detached-plugin");
  await mkdir(join(root, "helpers"), { recursive: true });
  const built = await Bun.build({
    entrypoints: [new URL("../helpers/claude-cli.ts", import.meta.url).pathname],
    outdir: join(root, "helpers"), naming: "claude-cli.js", target: "bun",
  });
  if (!built.success) throw new Error("test helper bundle failed");
  return root;
}

function execute(argv: readonly string[], cwd: string | undefined, stdin: string | undefined): Promise<Run> {
  return new Promise((resolve, reject) => {
    const child = spawn(argv[0] === "bun" ? process.execPath : argv[0] ?? "", argv.slice(1), { cwd, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
    child.once("error", reject);
    child.once("close", (code) => resolve({ exitCode: code ?? 1, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false }));
    child.stdin.end(stdin ?? "");
  });
}

async function native(item: Project, extra: Record<string, string> = {}) {
  const root = await plugin(item);
  const env = new Map<string, string>(Object.entries({
    ARMORY_BRIEF_REPO: item.root, ARMORY_BRIEF_DATA_ROOT: item.dataRoot, ARMORY_BRIEF_ACCOUNT: "acct-a", ARMORY_BRIEF_CONTEXT: "brief.json", ...extra,
  }));
  const hooks = new Map<string, Hook>();
  const runs: { argv: readonly string[]; stdin: string | undefined }[] = [];
  let session = "claude-session-1";
  let messages: () => Promise<Row[]> = async () => [
    { role: "user", text: SECRET, toolUses: [] },
    { role: "assistant", text: SECRET, toolUses: [{ name: "Bash", input: { command: SECRET } }] },
  ];
  let during: (() => void) | undefined;
  let transform = (run: Run): Run => run;
  const api = {
    plugin: { root },
    env: { async get(name: string) { return env.get(name); } },
    session: {
      async id() { return session; },
      async cwd() { return item.root; },
      async root() { return item.root; },
      async turns() { return 1; },
      async usage() { return { startedAt: 1_767_225_600_000, context: {}, rateLimits: [] }; },
      messages: () => messages(),
    },
    command: {
      async list() { return []; },
      async register(spec: { name: string }) { return { command: spec.name }; },
    },
    process: {
      async run(argv: readonly string[], init?: { cwd?: string; stdin?: string; timeoutMs?: number }) {
        runs.push({ argv, stdin: init?.stdin });
        const result = await execute(argv, init?.cwd, init?.stdin);
        during?.();
        return transform(result);
      },
    },
  };
  register(((event: string, ...rest: unknown[]) => {
    const matcher = typeof rest[0] === "object" ? rest[0] as { command: string } : undefined;
    hooks.set(matcher === undefined ? event : `${event}:${matcher.command}`, rest.at(-1) as Hook);
  }) as Parameters<typeof register>[0]);
  async function emit(event: string, input: unknown = {}): Promise<unknown> {
    const hook = hooks.get(event);
    if (hook === undefined) throw new Error(`missing adapter hook ${event}`);
    return hook(api, input, async (e) => e);
  }
  await emit("session.start");
  return {
    env, runs,
    setSession(id: string) { session = id; },
    setMessages(fn: () => Promise<Row[]>) { messages = fn; },
    whileRunning(fn?: () => void) { during = fn; },
    transform(fn: (run: Run) => Run) { transform = fn; },
    end() { return emit("session.end", { sessionId: session, reason: "clear" }); },
    async run(args: string): Promise<string> {
      const reply = await emit("command.run:armory-brief", { command: "armory-brief", args }) as { text: string };
      return reply.text;
    },
  };
}

async function setup(): Promise<Project> {
  const item = await project();
  projects.push(item);
  return item;
}

async function privateBytes(root: string): Promise<string> {
  let text = "";
  for (const entry of await readdir(root, { recursive: true }).catch(() => [])) {
    const path = join(root, String(entry));
    if ((await stat(path)).isFile()) text += await readFile(path, "utf8");
  }
  return text;
}

test("record observes the host session as counts only and binds approvals to the invoking session", async () => {
  const item = await setup();
  const host = await native(item);
  const recorded = JSON.parse(await host.run("record --json")) as RecordResult;
  expect(recorded.card.evaluatedFor).toEqual({ host: "claude", accountId: "acct-a", sessionId: "claude-session-1" });
  expect(recorded.card.claudeSession).toMatchObject({ kind: "claude-session", id: "claude-session-1", cwdMatchesWorktree: true, observedMessages: 2, messagesComplete: true, toolUses: 1, lastRole: "assistant" });
  expect(recorded.card.approvals.every((hold) => hold.executable === false && hold.foreignOrigin)).toBe(true);
  expect(host.runs[0]?.stdin).not.toContain(SECRET);
  expect(await privateBytes(item.dataRoot)).not.toContain(SECRET);
  const text = await host.run("show");
  expect(text).not.toContain(SECRET);
});

test("reopen in a fresh host session reports branch, plan and blocker changes with exact hashes", async () => {
  const item = await setup();
  const host = await native(item);
  await host.run("record");
  await host.end();
  host.setSession("claude-session-2");
  await item.git("checkout", "--quiet", "-b", "feature/next");
  await item.write("docs/PLAN.md", "# Plan\n\n1. Parse\n2. Emit\n");
  await item.write("docs/blockers.json", JSON.stringify({ ...BLOCKERS, nextAction: "Ship it" }));
  const reopened = JSON.parse(await host.run("reopen --json")) as ReopenResult;
  expect(reopened.current.evaluatedFor.sessionId).toBe("claude-session-2");
  const by = new Map(reopened.discrepancies.map((entry) => [entry.field, entry]));
  expect(by.get("repository.branch")).toMatchObject({ recorded: "main", current: "feature/next" });
  const plan = createHash("sha256").update(await readFile(join(item.root, "docs/PLAN.md"))).digest("hex");
  expect(by.get("sources.plan")?.source.currentSha256).toBe(plan);
  expect(by.get("nextAction.text")).toMatchObject({ recorded: "Rerun the integration suite", current: "Ship it" });
  expect(by.get("claudeSession.id")).toMatchObject({ recorded: "claude-session-1", current: "claude-session-2" });
});

test("a full host window and a denied session query stay incomplete or unknown", async () => {
  const item = await setup();
  const host = await native(item);
  host.setMessages(async () => Array.from({ length: 4096 }, () => ({ role: "user" as const, text: SECRET, toolUses: [] })));
  const full = JSON.parse(await host.run("record --json")) as RecordResult;
  expect(full.card.claudeSession.messagesComplete).toBe(false);
  expect(full.card.unknowns.map((entry) => entry.field)).toContain("claudeSession.observedMessages");
  host.setMessages(async () => { throw new Error("denied"); });
  const denied = JSON.parse(await host.run("record --json")) as RecordResult;
  expect(denied.card.claudeSession.kind).toBeNull();
  expect(denied.card.sources.find((entry) => entry.role === "claude-session")).toMatchObject({ status: "unreadable" });
  expect(denied.card.objective).toBe("Ship the parser rewrite");
});

test("a session end or selection change during the helper run publishes no answer", async () => {
  const item = await setup();
  const host = await native(item);
  host.whileRunning(() => { void host.end(); });
  expect(JSON.parse(await host.run("record --json"))).toEqual({ error: "context-changed", detail: null });
  host.whileRunning(() => { host.env.set("ARMORY_BRIEF_REPO", item.external); });
  expect(JSON.parse(await host.run("list --json"))).toEqual({ error: "context-changed", detail: null });
});

test("reopen refuses a snapshot recorded for a different selection", async () => {
  const item = await setup();
  const host = await native(item);
  await host.run("record");
  host.env.set("ARMORY_BRIEF_RECEIPT", join(item.external, "receipt.json"));
  expect(JSON.parse(await host.run("reopen --json"))).toMatchObject({ error: "rejected" });
});

test("unsafe, truncated or failed helper answers are refused without rendering them", async () => {
  const item = await setup();
  const host = await native(item);
  host.transform((run) => ({ ...run, stdout: run.stdout.replace("{", `{"privatePath":"${item.dataRoot}",`) }));
  expect(JSON.parse(await host.run("list --json"))).toEqual({ error: "operation-failed", detail: null });
  host.transform((run) => ({ ...run, isStdoutTruncated: true }));
  expect(JSON.parse(await host.run("list --json"))).toEqual({ error: "operation-failed", detail: null });
  host.transform((run) => ({ ...run, exitCode: 143 }));
  expect(JSON.parse(await host.run("list --json"))).toEqual({ error: "operation-failed", detail: null });
});

test("invalid arguments and missing configuration start no process", async () => {
  const item = await setup();
  const host = await native(item);
  await host.run("record && touch /tmp/x");
  host.env.delete("ARMORY_BRIEF_ACCOUNT");
  expect(JSON.parse(await host.run("record --json"))).toMatchObject({ error: "invalid-configuration" });
  await host.run("");
  expect(host.runs).toEqual([]);
});
