import { afterEach, expect, test } from "bun:test";
import { spawn } from "node:child_process";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveRepository } from "../helpers/sources.ts";
import { openStore } from "../helpers/state.ts";
import { BLOCKERS, CONTEXT, ompSession, project } from "./fixture.ts";
import type { Project } from "./fixture.ts";

const CLI = fileURLToPath(new URL("../helpers/cli.ts", import.meta.url));
const projects: Project[] = [];
afterEach(async () => {
  for (const item of projects.splice(0)) await item.cleanup();
});

interface Run { code: number | null; stdout: string; stderr: string }

function run(args: string[]): Promise<Run> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [CLI, ...args], { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

async function setup(): Promise<{ item: Project; common: string[] }> {
  const item = await project();
  projects.push(item);
  return { item, common: ["--repo", item.root, "--data-root", item.dataRoot, "--host", "standalone", "--account", "acct-a", "--session", "s-1"] };
}

test("record then reopen after branch, plan and blocker mutation reports exact discrepancies", async () => {
  const { item, common } = await setup();
  const sessionPath = join(item.external, "session.jsonl");
  await writeFile(sessionPath, ompSession(item.root));
  const recorded = await run(["record", ...common, "--context", "brief.json", "--omp-session", sessionPath]);
  expect(recorded.stderr).toBe("");
  expect(recorded.code).toBe(0);
  const { snapshotId, card } = JSON.parse(recorded.stdout) as { snapshotId: string; card: { authority: string; approvals: { executable: boolean; status: string; foreignOrigin: boolean }[] } };
  expect(card.authority).toBe("none");
  expect(card.approvals).toEqual([expect.objectContaining({ executable: false, status: "expired", foreignOrigin: true })]);

  const unchanged = await run(["reopen", ...common, "--id", snapshotId]);
  expect(unchanged.code).toBe(0);
  expect((JSON.parse(unchanged.stdout) as { discrepancies: unknown[] }).discrepancies).toEqual([]);

  await item.git("checkout", "--quiet", "-b", "feature/next");
  await item.write("docs/PLAN.md", "# Plan\n\n1. Parse\n2. Emit\n");
  await item.write("docs/blockers.json", JSON.stringify({ ...BLOCKERS, blockers: [{ id: "flaky-ci", summary: "CI job times out", status: "resolved" }] }));
  const reopened = await run(["reopen", ...common, "--latest"]);
  expect(reopened.code).toBe(1);
  const result = JSON.parse(reopened.stdout) as { resumed: boolean; authority: string; discrepancies: { field: string; kind: string; recorded: unknown; current: unknown; source: { role: string; ref: string } }[] };
  expect(result.resumed).toBe(false);
  expect(result.authority).toBe("none");
  const fields = new Map(result.discrepancies.map((item) => [item.field, item]));
  expect(fields.get("repository.branch")).toMatchObject({ recorded: "main", current: "feature/next", source: { role: "git" } });
  expect(fields.get("sources.plan")).toMatchObject({ kind: "changed", source: { role: "plan", ref: "docs/PLAN.md" } });
  expect(fields.get("plan.modifiedInWorktree")).toMatchObject({ recorded: false, current: true });
  expect(fields.get("blockers[flaky-ci]")).toMatchObject({ recorded: { status: "open" }, current: { status: "resolved" }, source: { role: "blockers", ref: "docs/blockers.json" } });

  const text = await run(["reopen", ...common, "--id", snapshotId, "--format", "text"]);
  expect(text.code).toBe(1);

  const shown = await run(["show", ...common, "--id", snapshotId]);
  expect(shown.code).toBe(0);
  expect(JSON.parse(shown.stdout)).toMatchObject({ observations: "recorded", card: { repository: { branch: "main" } } });
  expect((JSON.parse((await run(["list", "--repo", item.root, "--data-root", item.dataRoot, "--host", "standalone"])).stdout) as unknown[]).length).toBe(1);
  expect(await readdir(join(item.root))).not.toContain("state");
});

test("source text is rendered inert and never executed", async () => {
  const { item, common } = await setup();
  const marker = join(item.external, "pwned");
  await item.write("brief.json", JSON.stringify({ ...CONTEXT, objective: `\u001b[2J$(touch ${marker}) \`touch ${marker}\` [click](javascript:alert(1))` }));
  const text = await run(["record", ...common, "--context", "brief.json", "--format", "text"]);
  expect(text.code).toBe(0);
  expect(text.stdout).not.toContain("\u001b");
  expect(text.stdout).not.toContain("$(touch");
  expect(text.stdout).not.toContain("`touch");
  expect(await readdir(item.external)).not.toContain("pwned");
});

test("missing and unsupported sources produce unknowns, not defaults", async () => {
  const { item, common } = await setup();
  const handoff = join(item.external, "notes.md");
  await writeFile(handoff, "free text");
  const result = await run(["record", ...common, "--context", "absent.json", "--omp-handoff", handoff]);
  expect(result.code).toBe(0);
  const card = (JSON.parse(result.stdout) as { card: { objective: unknown; blockers: unknown; unknowns: { field: string; reason: string }[] } }).card;
  expect(card.objective).toBeNull();
  expect(card.blockers).toBeNull();
  expect(card.unknowns.map((item) => item.field)).toEqual(expect.arrayContaining(["sources.context", "sources.plan", "sources.blockers", "sources.omp-handoff"]));
});

test("invalid arguments, foreign hosts and unsafe data roots are refused", async () => {
  const { item, common } = await setup();
  expect((await run(["record", ...common])).code).toBe(2);
  expect((await run(["reopen", ...common, "--id", "../../x"])).code).toBe(2);
  expect((await run(["record", "--repo", item.root, "--host", "omp", "--account", "a", "--session", "s", "--context", "brief.json"])).code).toBe(2);
  const inside = await run(["record", "--repo", item.root, "--data-root", join(item.root, "state"), "--host", "standalone", "--account", "a", "--session", "s", "--context", "brief.json"]);
  expect(inside.code).toBe(2);
  expect(JSON.parse(inside.stderr)).toEqual({ error: "rejected", detail: "data root must be outside the repository, worktree and package" });
  const subdir = await run(["record", ...common.map((value) => (value === item.root ? join(item.root, "docs") : value)), "--context", "brief.json"]);
  expect(JSON.parse(subdir.stderr)).toEqual({ error: "rejected", detail: "repository must be the worktree root itself" });
  expect((await run(["reopen", ...common, "--latest"])).code).toBe(2);
});

test("malformed snapshot names are rejected without publishing or replacing existing state", async () => {
  const { item, common } = await setup();
  const first = await run(["record", ...common, "--context", "brief.json"]);
  expect(first.code).toBe(0);
  const { snapshotId } = JSON.parse(first.stdout) as { snapshotId: string };
  const store = await openStore(item.dataRoot, await resolveRepository(item.root));
  const snapshotPath = join(store.root, `${snapshotId}.json`);
  const original = await readFile(snapshotPath);
  await writeFile(join(store.root, "notes.json"), "{}\n");
  const names = (await readdir(store.root)).sort();
  for (const args of [["record", ...common, "--context", "brief.json"], ["list", ...common]]) {
    const result = await run(args);
    expect(result.code).toBe(2);
    expect(JSON.parse(result.stderr)).toMatchObject({ error: "rejected" });
    expect((await readdir(store.root)).sort()).toEqual(names);
    expect(await readFile(snapshotPath)).toEqual(original);
  }
});
