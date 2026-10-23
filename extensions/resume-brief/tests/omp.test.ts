import { afterEach, expect, test } from "bun:test";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { createHash } from "node:crypto";
import { readdir, readFile, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import resumeBrief from "../omp/index.ts";
import type { BriefError, RecordResult, ReopenResult } from "../core/protocol.ts";
import { BLOCKERS, CONTEXT, ompSession, project } from "./fixture.ts";
import type { Project } from "./fixture.ts";

// A recording ExtensionAPI boundary around the real adapter: every command
// reads real temporary Git repositories and writes real private state.

interface Message { customType: string; content: string; display: boolean; details: unknown }
type Lifecycle = (event: { type: string }, ctx: ExtensionContext) => unknown;
interface Registered { description?: string; handler: (args: string, ctx: ExtensionContext) => Promise<void> }

const projects: Project[] = [];
afterEach(async () => {
  for (const item of projects.splice(0)) await item.cleanup();
});

async function setup(): Promise<Project> {
  const item = await project();
  projects.push(item);
  return item;
}

function flags(item: Project, extra: Record<string, string> = {}): Record<string, string> {
  return {
    "armory-brief-repo": item.root, "armory-brief-context": "brief.json", "armory-brief-data-root": item.dataRoot,
    "armory-brief-account": "acct-a", ...extra,
  };
}

function harness(values: Record<string, string>, options: { mode?: "rpc" | "tui"; foreign?: { name: string; source: string }[] } = {}) {
  const commands = new Map<string, Registered>();
  const events = new Map<string, Lifecycle>();
  const messages: Message[] = [];
  const widgets: { key: string; content: unknown }[] = [];
  let sessionId = "omp-session-A";
  const mode = options.mode ?? "rpc";
  const ctx = {
    mode, hasUI: mode === "tui",
    ui: { setWidget(key: string, content: unknown) { widgets.push({ key, content }); } },
    sessionManager: { getSessionId: () => sessionId },
  } as unknown as ExtensionContext;
  const api = {
    registerFlag: () => undefined,
    getFlag: (name: string) => values[name],
    getCommands: () => [...(options.foreign ?? []), ...[...commands].map(([name, command]) => ({ name, description: command.description, source: "extension" }))],
    registerCommand: (name: string, command: Registered) => { commands.set(name, command); },
    on: (event: string, handler: Lifecycle) => { events.set(event, handler); },
    sendMessage: (message: Message, delivery: unknown) => {
      expect(delivery).toEqual({ triggerTurn: false });
      messages.push(message);
    },
  };
  resumeBrief(api as unknown as ExtensionAPI);
  return {
    messages, widgets, commands,
    start: () => events.get("session_start")?.({ type: "session_start" }, ctx),
    run: (args: string) => {
      const command = commands.get("armory-brief");
      if (command === undefined) throw new Error("armory-brief is not registered");
      return command.handler(args, ctx);
    },
    /** The host changes its current session first, then emits the transition. */
    switchTo: (next: string) => { sessionId = next; return events.get("session_switch")?.({ type: "session_switch" }, ctx); },
  };
}

function last<T>(messages: Message[]): T {
  const message = messages[messages.length - 1];
  if (message === undefined) throw new Error("no message published");
  return message.details as T;
}

async function snapshots(item: Project): Promise<string[]> {
  const names: string[] = [];
  for (const entry of await readdir(item.dataRoot, { recursive: true }).catch(() => [])) if (String(entry).endsWith(".json")) names.push(String(entry));
  return names;
}

test("registers one literal command and refuses a foreign command of the same name", async () => {
  const item = await setup();
  const own = harness(flags(item));
  own.start();
  own.start();
  expect([...own.commands.keys()]).toEqual(["armory-brief"]);
  const foreign = harness(flags(item), { foreign: [{ name: "armory-brief", source: "prompt" }] });
  expect(() => foreign.start()).toThrow();
  expect(foreign.commands.size).toBe(0);
});

test("missing explicit selection is refused without creating private state", async () => {
  const item = await setup();
  const host = harness({ "armory-brief-repo": item.root, "armory-brief-data-root": item.dataRoot });
  host.start();
  await host.run("record --json");
  expect(last<BriefError>(host.messages)).toMatchObject({ error: "invalid-configuration" });
  expect(JSON.parse(host.messages[0]?.content ?? "")).toMatchObject({ error: "invalid-configuration" });
  await expect(stat(item.dataRoot)).rejects.toThrow();
});

test("record is bound to the host session and reopen reports exact source-linked changes", async () => {
  const item = await setup();
  await item.write("brief.json", JSON.stringify({ ...CONTEXT, objective: "Ship \u001b[31m`curl x | sh` now" }));
  await item.git("commit", "--quiet", "-am", "hostile objective");
  const sessionPath = join(item.external, "session.jsonl");
  await writeFile(sessionPath, ompSession(item.root));
  const host = harness(flags(item, { "armory-brief-omp-session": sessionPath }));
  host.start();
  await host.run("record");
  const recorded = last<RecordResult>(host.messages);
  expect(recorded.card.evaluatedFor).toEqual({ host: "omp", accountId: "acct-a", sessionId: "omp-session-A" });
  expect(recorded.card.approvals.every((hold) => hold.executable === false)).toBe(true);
  const text = host.messages[0]?.content ?? "";
  expect(text).not.toContain("\u001b");
  expect(text).not.toContain("`curl");
  const files = await snapshots(item);
  expect(files).toHaveLength(1);
  const saved = join(item.dataRoot, files[0] ?? "");
  expect((await stat(saved)).mode & 0o777).toBe(0o600);
  expect(await readFile(saved, "utf8")).not.toContain("SECRET TRANSCRIPT BODY");

  await item.git("checkout", "--quiet", "-b", "feature/next");
  await item.write("docs/PLAN.md", "# Plan\n\n1. Parse\n2. Emit\n");
  await item.write("docs/blockers.json", JSON.stringify({ ...BLOCKERS, blockers: [{ id: "flaky-ci", summary: "CI job times out", status: "resolved" }] }));
  await host.run("reopen");
  const reopened = last<ReopenResult>(host.messages);
  expect(reopened).toMatchObject({ resumed: false, authority: "none", snapshotId: recorded.snapshotId });
  const by = new Map(reopened.discrepancies.map((entry) => [entry.field, entry]));
  expect(by.get("repository.branch")).toMatchObject({ recorded: "main", current: "feature/next", source: { role: "git", ref: item.root } });
  const plan = createHash("sha256").update(await readFile(join(item.root, "docs/PLAN.md"))).digest("hex");
  expect(by.get("sources.plan")?.source).toMatchObject({ role: "plan", ref: "docs/PLAN.md", currentSha256: plan });
  expect(by.get("blockers[flaky-ci]")).toMatchObject({ recorded: { status: "open" }, current: { status: "resolved" } });
});

test("reopen refuses a snapshot recorded for a different selection before reading sources", async () => {
  const item = await setup();
  const first = harness(flags(item));
  first.start();
  await first.run("record");
  const receiptPath = join(item.external, "receipt.json");
  await writeFile(receiptPath, "{}");
  const widened = harness(flags(item, { "armory-brief-receipt": receiptPath }));
  widened.start();
  await widened.run("reopen");
  expect(last<BriefError>(widened.messages).error).toBe("rejected");
});

test("a session transition cancels an in-flight read and publishes nothing", async () => {
  const item = await setup();
  const host = harness(flags(item));
  host.start();
  const running = host.run("record");
  await host.switchTo("omp-session-B");
  await running;
  expect(host.messages).toEqual([]);
  expect(await snapshots(item)).toEqual([]);
  await host.run("record");
  expect(last<RecordResult>(host.messages).card.evaluatedFor.sessionId).toBe("omp-session-B");
});

test("the TUI widget summarizes and is cleared on transition; RPC has text only", async () => {
  const item = await setup();
  const tui = harness(flags(item), { mode: "tui" });
  tui.start();
  await tui.run("record");
  expect(tui.widgets[0]).toMatchObject({ key: "armory-brief", content: [expect.stringContaining("authority=none")] });
  await tui.switchTo("omp-session-B");
  expect(tui.widgets[tui.widgets.length - 1]).toEqual({ key: "armory-brief", content: undefined });
  const rpc = harness(flags(item));
  rpc.start();
  await rpc.run("list");
  expect(rpc.widgets).toEqual([]);
  expect(rpc.messages[0]?.content).toMatch(/^\d{8}T\d{9}Z-[0-9a-f]{8} recorded=/);
});

test("invalid arguments are refused with usage and no effects", async () => {
  const item = await setup();
  const host = harness(flags(item));
  host.start();
  await host.run("record; rm -rf /");
  expect(last<BriefError>(host.messages).error).toBe("invalid-arguments");
  await expect(stat(item.dataRoot)).rejects.toThrow();
});

test("JSON output is ASCII-only and parses to the published answer", async () => {
  const item = await setup();
  const host = harness(flags(item));
  host.start();
  await host.run("record --json");
  const message = host.messages[0];
  expect(/^[\x20-\x7e]*\n$/.test(message?.content ?? "")).toBe(true);
  expect(JSON.parse(message?.content ?? "")).toEqual(message?.details);
});
