import { randomBytes, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import type { Stats } from "node:fs";
import { link, lstat, mkdir, open, opendir, realpath, unlink } from "node:fs/promises";
import { basename, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { canonicalJson, CORE_VERSION, FEATURE, FEATURE_VERSION, formatTimestamp, SNAPSHOT_SCHEMA } from "../core/index.ts";
import type { Context, Json, Observations } from "../core/index.ts";
import { assertSnapshotId, parseSnapshot } from "../core/snapshot.ts";
import type { Snapshot } from "../core/snapshot.ts";
import type { Repository, Selection } from "./sources.ts";

const MAX_SNAPSHOT_BYTES = 1024 * 1024;
const MAX_SNAPSHOTS = 10_000;

export class StateError extends Error {}

export interface SnapshotStore {
  root: string;
  record(recordedBy: Context, selection: Selection, observations: Observations, recordedAtMs: number): Promise<Snapshot>;
  read(snapshotId: string): Promise<Snapshot>;
  list(): Promise<string[]>;
}

function code(error: unknown): string | undefined {
  return error instanceof Error && "code" in error && typeof error.code === "string" ? error.code : undefined;
}

function inside(root: string, path: string): boolean {
  const child = relative(root, path);
  return child === "" || (child !== ".." && !child.startsWith("../") && !child.startsWith("/"));
}

function owned(stat: Stats): boolean {
  return process.getuid === undefined || stat.uid === process.getuid();
}

async function privateDirectory(path: string, create: boolean): Promise<void> {
  if (create) {
    try { await mkdir(path, { mode: 0o700 }); } catch (error) { if (code(error) !== "EEXIST") throw error; }
  }
  const stat = await lstat(path);
  if (!stat.isDirectory() || stat.isSymbolicLink() || (stat.mode & 0o777) !== 0o700 || !owned(stat)) {
    throw new StateError("state directory must be an owned 0700 directory, not a link");
  }
}

async function syncDirectory(path: string): Promise<void> {
  const directory = await open(path, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try { await directory.sync(); } finally { await directory.close(); }
}

/** Resolve a possibly not-yet-existing path through its deepest existing ancestor. */
async function canonicalFuture(path: string): Promise<string> {
  let ancestor = resolve(path);
  const parts: string[] = [];
  for (;;) {
    try { return resolve(await realpath(ancestor), ...parts); } catch (error) {
      if (code(error) !== "ENOENT") throw error;
      parts.unshift(basename(ancestor));
      const parent = dirname(ancestor);
      if (parent === ancestor) throw error;
      ancestor = parent;
    }
  }
}

/** Exclusive, durable, no-clobber publication: a staged 0600 file is hard-linked into place. */
async function publish(path: string, bytes: Uint8Array): Promise<void> {
  const staging = join(dirname(path), `.pending-${randomUUID()}`);
  const handle = await open(staging, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW, 0o600);
  try {
    await handle.writeFile(bytes);
    await handle.sync();
  } finally {
    await handle.close();
  }
  try {
    await link(staging, path);
  } finally {
    await unlink(staging);
  }
  await syncDirectory(dirname(path));
}

async function privateRead(path: string): Promise<Buffer> {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = await handle.stat();
    if (!before.isFile() || (before.mode & 0o777) !== 0o600 || !owned(before) || before.nlink !== 1 || before.size > MAX_SNAPSHOT_BYTES) {
      throw new StateError("snapshot must be an owned, private, single-link regular file within its size bound");
    }
    const bytes = Buffer.alloc(before.size + 1);
    let length = 0;
    while (length < bytes.length) {
      const { bytesRead } = await handle.read(bytes, length, bytes.length - length, length);
      if (bytesRead === 0) break;
      length += bytesRead;
    }
    const after = await lstat(path);
    if (length !== before.size || after.ino !== before.ino || after.size !== before.size || after.mtimeMs !== before.mtimeMs) {
      throw new StateError("snapshot changed while being read");
    }
    return bytes.subarray(0, length);
  } finally {
    await handle.close();
  }
}

function newSnapshotId(recordedAtMs: number): string {
  const stamp = formatTimestamp(recordedAtMs).replace(/[-:.]/g, "");
  return `${stamp}-${randomBytes(4).toString("hex")}`;
}

/**
 * Open the private per-repository snapshot directory under an explicit data
 * root that must lie outside the repository, the worktree and this package.
 */
export async function openStore(dataRoot: string, repository: Repository): Promise<SnapshotStore> {
  if (dataRoot.length === 0 || dataRoot.includes("\0")) throw new StateError("an explicit data root is required");
  const external = await canonicalFuture(dataRoot);
  const packageRoot = await realpath(fileURLToPath(new URL("..", import.meta.url)));
  for (const forbidden of [repository.repositoryRoot, repository.worktreeRoot, packageRoot]) {
    if (inside(await realpath(forbidden), external)) throw new StateError("data root must be outside the repository, worktree and package");
  }
  await mkdir(external, { recursive: true, mode: 0o700 });
  await privateDirectory(external, false);
  let root = external;
  for (const component of [FEATURE, repository.repositoryId, "snapshots"]) {
    root = join(root, component);
    await privateDirectory(root, true);
  }
  const directory = root;

  async function read(snapshotId: string): Promise<Snapshot> {
    assertSnapshotId(snapshotId);
    let bytes: Buffer;
    try { bytes = await privateRead(join(directory, `${snapshotId}.json`)); } catch (error) {
      if (code(error) === "ENOENT") throw new StateError("snapshot not found");
      throw error;
    }
    let value: unknown;
    try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { throw new StateError("snapshot is not valid JSON"); }
    let snapshot: Snapshot;
    try { snapshot = parseSnapshot(value); } catch (error) { throw new StateError(error instanceof Error ? error.message : "malformed snapshot"); }
    if (snapshot.snapshotId !== snapshotId || snapshot.repositoryId !== repository.repositoryId) throw new StateError("snapshot identity does not match its location");
    return snapshot;
  }

  async function* snapshotIds(): AsyncGenerator<string> {
    let count = 0;
    for await (const entry of await opendir(directory)) {
      if (entry.name.startsWith(".pending-")) continue;
      if (!entry.isFile() || !entry.name.endsWith(".json")) throw new StateError("unexpected entry in snapshot directory");
      const id = entry.name.slice(0, -".json".length);
      try { assertSnapshotId(id); } catch { throw new StateError("unexpected entry in snapshot directory"); }
      if (++count > MAX_SNAPSHOTS) throw new StateError("snapshot limit exceeded");
      yield id;
    }
  }

  async function list(): Promise<string[]> {
    const names: string[] = [];
    for await (const id of snapshotIds()) names.push(id);
    return names.sort();
  }

  async function record(recordedBy: Context, selection: Selection, observations: Observations, recordedAtMs: number): Promise<Snapshot> {
    let count = 0;
    for await (const id of snapshotIds()) {
      if (++count >= MAX_SNAPSHOTS) throw new StateError(`snapshot limit reached at ${id}; no snapshot was published`);
    }
    const snapshot: Snapshot = {
      schema: SNAPSHOT_SCHEMA, featureVersion: FEATURE_VERSION, coreVersion: CORE_VERSION,
      snapshotId: newSnapshotId(recordedAtMs), recordedAtMs, recordedBy, repositoryId: repository.repositoryId, selection, observations,
    };
    parseSnapshot(JSON.parse(JSON.stringify(snapshot)) as unknown);
    const bytes = new TextEncoder().encode(`${canonicalJson(snapshot as unknown as Json)}\n`);
    if (bytes.byteLength > MAX_SNAPSHOT_BYTES) throw new StateError("snapshot exceeds its size bound");
    await publish(join(directory, `${snapshot.snapshotId}.json`), bytes);
    return snapshot;
  }

  return { root: directory, record, read, list };
}
