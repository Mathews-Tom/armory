import { afterEach, expect, test } from "bun:test";
import { chmod, lstat, mkdir, readFile, readdir, rename, symlink, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Context } from "../core/index.ts";
import { observe, resolveRepository } from "../helpers/sources.ts";
import type { Selection } from "../helpers/sources.ts";
import { openStore } from "../helpers/state.ts";
import { ompSession, project } from "./fixture.ts";
import type { Project } from "./fixture.ts";

const projects: Project[] = [];
afterEach(async () => {
  for (const item of projects.splice(0)) await item.cleanup();
});

const WHO: Context = { host: "standalone", accountId: "acct-a", sessionId: "s-1" };

async function recorded(): Promise<{ item: Project; selection: Selection }> {
  const item = await project();
  projects.push(item);
  const sessionPath = join(item.external, "session.jsonl");
  await writeFile(sessionPath, ompSession(item.root));
  return { item, selection: { contextPath: "brief.json", ompSessionPath: sessionPath, ompHandoffPath: null, receiptPath: null } };
}

test("data root inside the repository or package is refused", async () => {
  const { item } = await recorded();
  const repository = await resolveRepository(item.root);
  await expect(openStore(join(item.root, ".state"), repository)).rejects.toThrow("outside the repository");
  const packageRoot = fileURLToPath(new URL("..", import.meta.url));
  await expect(openStore(join(packageRoot, "state"), repository)).rejects.toThrow("outside the repository");
});

test("snapshots are private, preserved and contain references rather than bodies", async () => {
  const { item, selection } = await recorded();
  const repository = await resolveRepository(item.root);
  const store = await openStore(item.dataRoot, repository);
  const first = await store.record(WHO, selection, await observe(repository, selection, Date.now), 1_767_225_600_000);
  const second = await store.record(WHO, selection, await observe(repository, selection, Date.now), 1_767_225_600_000);
  expect(first.snapshotId).not.toBe(second.snapshotId);
  expect(await store.list()).toEqual([first.snapshotId, second.snapshotId].sort());
  expect((await lstat(store.root)).mode & 0o777).toBe(0o700);
  expect((await lstat(item.dataRoot)).mode & 0o777).toBe(0o700);
  const file = join(store.root, `${first.snapshotId}.json`);
  expect((await lstat(file)).mode & 0o777).toBe(0o600);
  const text = await readFile(file, "utf8");
  expect(text).not.toContain("SECRET TRANSCRIPT BODY");
  expect(text).not.toContain("# Plan");
  expect(text).toContain("Ship the parser rewrite");
  expect((await store.read(first.snapshotId)).observations).toEqual(first.observations);
});

test("tampered, foreign or linked state is rejected explicitly", async () => {
  const { item, selection } = await recorded();
  const repository = await resolveRepository(item.root);
  const store = await openStore(item.dataRoot, repository);
  const snapshot = await store.record(WHO, selection, await observe(repository, selection, Date.now), Date.now());
  const file = join(store.root, `${snapshot.snapshotId}.json`);

  await chmod(file, 0o644);
  await expect(store.read(snapshot.snapshotId)).rejects.toThrow("private");
  await chmod(file, 0o600);

  const original = await readFile(file, "utf8");
  await writeFile(file, original.replace('"objective":"Ship the parser rewrite"', '"objective":"Ship","injected":true'));
  await expect(store.read(snapshot.snapshotId)).rejects.toThrow("malformed snapshot");
  await writeFile(file, "{not json");
  await expect(store.read(snapshot.snapshotId)).rejects.toThrow("not valid JSON");

  await unlink(file);
  await writeFile(join(item.external, "elsewhere.json"), original, { mode: 0o600 });
  await symlink(join(item.external, "elsewhere.json"), file);
  await expect(store.read(snapshot.snapshotId)).rejects.toThrow();
  await unlink(file);

  await writeFile(join(store.root, "notes.txt"), "foreign");
  await expect(store.list()).rejects.toThrow("unexpected entry");
  await expect(store.read("../../escape")).rejects.toThrow("invalid snapshot id");
});

test("a non-private existing data root is refused rather than loosened", async () => {
  const { item } = await recorded();
  const repository = await resolveRepository(item.root);
  await chmod(item.external, 0o755);
  await expect(openStore(item.external, repository)).rejects.toThrow("0700");
});

test("the last permitted snapshot stays listable and further records refuse before publication", async () => {
  const { item, selection } = await recorded();
  const repository = await resolveRepository(item.root);
  const store = await openStore(item.dataRoot, repository);
  for (let start = 0; start < 9999; start += 100) {
    await Promise.all(Array.from({ length: Math.min(100, 9999 - start) }, async (_, offset) => {
      const id = `20260101T000000000Z-${(start + offset).toString(16).padStart(8, "0")}`;
      await writeFile(join(store.root, `${id}.json`), "{}", { mode: 0o600 });
    }));
  }
  const observations = await observe(repository, selection, Date.now);
  const last = await store.record(WHO, selection, observations, Date.now());
  const full = await store.list();
  expect(full).toContain(last.snapshotId);
  await expect(store.record(WHO, selection, observations, Date.now())).rejects.toThrow("snapshot limit");
  expect(await store.list()).toEqual(full);
  const excess = join(store.root, "20260101T000000000Z-ffffffff.json");
  await writeFile(excess, "{}", { mode: 0o600 });
  await expect(store.list()).rejects.toThrow("snapshot limit");
});

test("a replaced snapshot-directory link cannot redirect publication", async () => {
  const { item, selection } = await recorded();
  const repository = await resolveRepository(item.root);
  const store = await openStore(item.dataRoot, repository);
  const observations = await observe(repository, selection, Date.now);
  const outside = join(item.external, "foreign-snapshot-target");
  await mkdir(outside, { mode: 0o700 });
  await rename(store.root, `${store.root}-preserved`);
  await symlink(outside, store.root);
  let rejected = false;
  try { await store.record(WHO, selection, observations, Date.now()); } catch { rejected = true; }
  expect({ rejected, outside: await readdir(outside) }).toEqual({ rejected: true, outside: [] });
});

for (const operation of ["record", "read", "list"] as const) {
  test(`a replaced storage ancestor cannot redirect ${operation}`, async () => {
    const { item, selection } = await recorded();
    const repository = await resolveRepository(item.root);
    const store = await openStore(item.dataRoot, repository);
    const observations = await observe(repository, selection, Date.now);
    const snapshot = await store.record(WHO, selection, observations, Date.now());
    const name = `${snapshot.snapshotId}.json`;
    const original = await readFile(join(store.root, name));
    const outside = join(item.external, "foreign-store");
    const foreignSnapshots = join(outside, "snapshots");
    await mkdir(foreignSnapshots, { recursive: true, mode: 0o700 });
    await writeFile(join(foreignSnapshots, name), original, { mode: 0o600 });
    await rename(dirname(store.root), `${dirname(store.root)}-preserved`);
    await symlink(outside, dirname(store.root));
    const action = operation === "record"
      ? store.record(WHO, selection, observations, Date.now())
      : operation === "read" ? store.read(snapshot.snapshotId) : store.list();
    await expect(action).rejects.toThrow();
    expect(await readdir(foreignSnapshots)).toEqual([name]);
    expect(await readFile(join(foreignSnapshots, name))).toEqual(original);
  });
}
