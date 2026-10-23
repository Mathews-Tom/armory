import { afterEach, expect, test } from "bun:test";
import { execFile } from "node:child_process";
import { chmod, readFile, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";
import { buildCard, discrepancies } from "../core/card.ts";
import { inert } from "../core/index.ts";
import type { Observations } from "../core/index.ts";
import { renderDiscrepancies } from "../core/render.ts";
import { parseOmpSession, parseReceiptReference } from "../core/validation.ts";
import { observe, resolveRepository } from "../helpers/sources.ts";
import { openStore } from "../helpers/state.ts";
import { CONTEXT, ompSession, project, receipt } from "./fixture.ts";
import type { Project } from "./fixture.ts";

const exec = promisify(execFile);
const projects: Project[] = [];
afterEach(async () => { for (const item of projects.splice(0)) await item.cleanup(); });
async function setup(): Promise<Project> { const item = await project(); projects.push(item); return item; }
const SELECTION = { contextPath: "brief.json", ompSessionPath: null, ompHandoffPath: null, receiptPath: null };
const CONTEXT_REF = { host: "standalone" as const, accountId: "test-account", sessionId: "test-session" };

test("native OMP title slots are skipped without retaining their title", () => {
  const title = { type: "title", v: 1, title: "PRIVATE TITLE", updatedAt: "2026-10-23T00:00:00Z", pad: "" };
  const unpadded = JSON.stringify(title);
  title.pad = " ".repeat(255 - Buffer.byteLength(unpadded));
  const parsed = parseOmpSession([JSON.stringify(title), ...ompSession("/selected").split("\n")]);
  expect(parsed).toMatchObject({ sessionId: "omp-session-1", cwd: "/selected", entryCount: 1, lastEntryId: "e1" });
  expect(JSON.stringify(parsed)).not.toContain("PRIVATE TITLE");
  expect(() => parseOmpSession([JSON.stringify({ ...title, v: 2 }), ...ompSession("/selected").split("\n")])).toThrow();
});

for (const gateId of ["ci/unit tests", "verify (+integration)", "x".repeat(256)]) {
  test(`valid receipts retain gate references through private persistence (${gateId.length} chars)`, async () => {
    const item = await setup();
    const repository = await resolveRepository(item.root);
    const value = JSON.parse(receipt(repository.repositoryId)) as { plan: { gateId: string } };
    value.plan.gateId = gateId;
    expect(parseReceiptReference(value).gateId).toBe(gateId);
    const path = join(item.external, "receipt.json");
    await writeFile(path, JSON.stringify(value));
    const selected = { ...SELECTION, receiptPath: path };
    const observed = await observe(repository, selected, Date.now);
    const store = await openStore(item.dataRoot, repository);
    const recorded = await store.record(CONTEXT_REF, selected, observed, Date.now());
    expect((await store.read(recorded.snapshotId)).observations.receipt?.gateId).toBe(gateId);
  });
}

for (const kind of ["fsmonitor", "clean-filter"] as const) {
  test(`observations never execute repository-configured ${kind} commands`, async () => {
    const item = await setup();
    const marker = join(item.external, "executed");
    const command = join(item.external, "configured-command.sh");
    await writeFile(command, `#!/bin/sh\nprintf executed >> '${marker}'\n${kind === "clean-filter" ? "cat\n" : "exit 1\n"}`);
    await chmod(command, 0o700);
    if (kind === "fsmonitor") await item.git("config", "core.fsmonitor", command);
    else {
      await item.write(".gitattributes", "docs/PLAN.md filter=example\n");
      await item.git("add", ".gitattributes");
      await item.git("commit", "--quiet", "-m", "configure attributes");
      await item.git("config", "filter.example.clean", command);
      const plan = await readFile(join(item.root, "docs/PLAN.md"), "utf8");
      await item.write("docs/PLAN.md", plan.replace("Parse", "Write"));
    }
    const observed = await observe(await resolveRepository(item.root), SELECTION, Date.now);
    expect(await Bun.file(marker).exists()).toBe(false);
    expect(observed.git.branch).toBe("main");
    expect(observed.plan?.lastCommit).toMatch(/^[a-f0-9]{40,64}$/);
  });
}

test("literal wildcard plan names cannot borrow another file's revision or change state", async () => {
  const item = await setup();
  await item.write("docs/*.md", "selected literal plan\n");
  await item.write("brief.json", JSON.stringify({ ...CONTEXT, plan: { path: "docs/*.md" } }));
  await item.git("add", "."); await item.git("commit", "--quiet", "-m", "select literal plan");
  const revision = await item.git("rev-parse", "HEAD");
  await item.write("docs/OTHER.md", "unrelated plan\n");
  await item.git("add", "."); await item.git("commit", "--quiet", "-m", "change other plan");
  await item.write("docs/OTHER.md", "modified unrelated plan\n");
  const observed = await observe(await resolveRepository(item.root), SELECTION, Date.now);
  expect(observed.plan).toMatchObject({ lastCommit: revision, modifiedInWorktree: false });
});

test("an ancestor swapped immediately before the file open cannot expose an outside plan", async () => {
  const item = await setup();
  await writeFile(join(item.external, "PLAN.md"), "OUTSIDE SOURCE MUST NOT BE READ\n");
  const child = await exec(process.execPath, [join(import.meta.dir, "ancestor-race-child.ts"), item.root, item.external, join(import.meta.dir, "../helpers/sources.ts")], { timeout: 20_000 });
  const result = JSON.parse(child.stdout) as { swapped: boolean; plan: unknown; source: { status: string; sha256: string | null } };
  expect(result.swapped).toBe(true);
  expect(result.plan).toBeNull();
  expect(result.source.sha256).toBeNull();
  expect(["rejected", "changed-during-read"]).toContain(result.source.status);
});

test("a source that becomes unselected retains its recorded evidence pointer", async () => {
  const item = await setup();
  const repository = await resolveRepository(item.root);
  const recorded = buildCard(await observe(repository, SELECTION, Date.now), CONTEXT_REF, Date.now());
  await unlink(join(item.root, "brief.json"));
  const current = buildCard(await observe(repository, SELECTION, Date.now), CONTEXT_REF, Date.now());
  const changes = discrepancies(recorded, current);
  expect(changes.find((change) => change.field === "sources.plan")?.source.ref).toBe("docs/PLAN.md");
  expect(changes.find((change) => change.field === "sources.blockers")?.source.ref).toBe("docs/blockers.json");
});

test("invisible Unicode tag and variation-selector content is visibly escaped", () => {
  const hidden = [0xe0001, 0xe0061, 0xe007f, 0xfe0f, 0xe0100, 0xe01ef].map((code) => String.fromCodePoint(code)).join("");
  const rendered = inert(`visible${hidden}`);
  for (const character of hidden) expect(rendered).not.toContain(character);
  expect(rendered).toContain("visible");
});

test("discrepancy fields cannot inject terminal controls or a forged line", () => {
  const field = "blockers[\u001b[31m\nAuthority: forged]";
  const rendered = renderDiscrepancies([{
    field, kind: "removed", recorded: "open", current: null,
    source: { role: "blockers", ref: "docs/blockers.json", recordedSha256: null, currentSha256: null },
  }]);
  expect(rendered).not.toContain("\u001b");
  expect(rendered.split("\n")).toHaveLength(3);
  expect(rendered).not.toContain("\nAuthority: forged");
});

for (const key of ["constructor", "__proto__"]) {
  test(`persisted snapshots reject unexpected own ${key} fields`, async () => {
    const item = await setup();
    const repository = await resolveRepository(item.root);
    const store = await openStore(item.dataRoot, repository);
    const snapshot = await store.record(CONTEXT_REF, SELECTION, await observe(repository, SELECTION, Date.now), Date.now());
    const path = join(store.root, `${snapshot.snapshotId}.json`);
    const value = JSON.parse(await readFile(path, "utf8")) as { recordedBy: Record<string, unknown> };
    Object.defineProperty(value.recordedBy, key, { value: "unexpected private content", enumerable: true });
    await writeFile(path, JSON.stringify(value));
    await expect(store.read(snapshot.snapshotId)).rejects.toThrow("no such field");
  });
}

test("inherited Git locations cannot redirect selected repository observations", async () => {
  const selected = await setup();
  const foreign = await setup();
  await foreign.git("checkout", "--quiet", "-b", "foreign-branch");
  await foreign.write("docs/PLAN.md", "FOREIGN PLAN\n");
  await foreign.git("add", ".");
  await foreign.git("commit", "--quiet", "-m", "foreign plan");
  const repository = await resolveRepository(selected.root);
  const expected = await observe(repository, SELECTION, Date.now);
  const module = join(import.meta.dir, "../helpers/sources.ts");
  const script = `const {resolveRepository,observe}=await import(${JSON.stringify(module)}); const r=await resolveRepository(process.argv[1]); console.log(JSON.stringify({repository:r,observations:await observe(r,${JSON.stringify(SELECTION)},Date.now)}));`;
  for (const locations of [
    { GIT_COMMON_DIR: join(foreign.root, ".git") },
    { GIT_DIR: join(foreign.root, ".git"), GIT_WORK_TREE: selected.root, GIT_COMMON_DIR: join(foreign.root, ".git"), GIT_INDEX_FILE: join(foreign.root, ".git/index"), GIT_OBJECT_DIRECTORY: join(foreign.root, ".git/objects"), GIT_ALTERNATE_OBJECT_DIRECTORIES: join(foreign.root, ".git/objects"), GIT_NAMESPACE: "foreign", GIT_CEILING_DIRECTORIES: selected.root, GIT_DISCOVERY_ACROSS_FILESYSTEM: "0" },
  ]) {
    const child = await exec(process.execPath, ["-e", script, selected.root], { env: { ...process.env, ...locations }, timeout: 20_000 });
    const actual = JSON.parse(child.stdout) as { repository: typeof repository; observations: typeof expected };
    expect(actual.repository).toEqual(repository);
    expect(actual.observations.git).toEqual(expected.git);
    expect(actual.observations.plan).toEqual(expected.plan);
  }
});

for (const variable of ["GIT_GRAFT_FILE", "GIT_SHALLOW_FILE"]) {
  test(`${variable} cannot rewrite the selected plan's last-changing commit`, async () => {
    const item = await setup();
    const planCommit = await item.git("rev-parse", "HEAD");
    await item.write("unrelated.txt", "later work\n");
    await item.git("add", "unrelated.txt");
    await item.git("commit", "--quiet", "-m", "unrelated work");
    const head = await item.git("rev-parse", "HEAD");
    const historyFile = join(item.external, "foreign-history");
    await writeFile(historyFile, `${head}\n`);
    const module = join(import.meta.dir, "../helpers/sources.ts");
    const script = `const {resolveRepository,observe}=await import(${JSON.stringify(module)}); const r=await resolveRepository(process.argv[1]); console.log(JSON.stringify(await observe(r,${JSON.stringify(SELECTION)},Date.now)));`;
    const child = await exec(process.execPath, ["-e", script, item.root], {
      env: { ...process.env, [variable]: historyFile }, timeout: 20_000,
    });
    const actual = JSON.parse(child.stdout) as Observations;
    expect(actual.git.head).toBe(head);
    expect(actual.plan?.lastCommit).toBe(planCommit);
    expect(actual.plan?.modifiedInWorktree).toBe(false);
  });
}
