import { randomBytes, randomUUID } from "node:crypto";
import { closeSync, constants, fstatSync, fsyncSync, readSync, writeSync } from "node:fs";
import type { Stats } from "node:fs";
import { realpath } from "node:fs/promises";
import { basename, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { canonicalJson, CORE_VERSION, FEATURE, FEATURE_VERSION, formatTimestamp, SNAPSHOT_SCHEMA } from "../core/index.ts";
import type { Context, Json, Observations } from "../core/index.ts";
import { assertSnapshotId, parseSnapshot } from "../core/snapshot.ts";
import type { Snapshot } from "../core/snapshot.ts";
import type { Repository, Selection } from "./sources.ts";
import { createTemporary, directoryNames, linkAt, openAt, openDirectory, unlinkAt } from "./contained-open.ts";

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

function privateStat(descriptor: number): Stats {
  const stat = fstatSync(descriptor);
  if (!stat.isDirectory() || (stat.mode & 0o777) !== 0o700 || !owned(stat)) {
    throw new StateError("state directory must be an owned 0700 directory, not a link");
  }
  return stat;
}

function privateDirectory(path: string, create: boolean): Stats {
  const descriptor = openDirectory(path, create);
  try { return privateStat(descriptor); } finally { closeSync(descriptor); }
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
function publish(directory: number, name: string, bytes: Uint8Array): void {
  const { descriptor, name: staging } = createTemporary(directory, `.pending-${randomUUID()}`);
  try {
    try {
      let offset = 0;
      while (offset < bytes.length) {
        const written = writeSync(descriptor, bytes, offset, bytes.length - offset);
        if (written === 0) throw new StateError("snapshot write made no progress");
        offset += written;
      }
      fsyncSync(descriptor);
    } finally {
      closeSync(descriptor);
    }
    linkAt(directory, staging, name);
  } finally {
    unlinkAt(directory, staging);
  }
  fsyncSync(directory);
}

function privateRead(directory: number, name: string): Buffer {
  const descriptor = openAt(directory, name, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(descriptor);
    if (!before.isFile() || (before.mode & 0o777) !== 0o600 || !owned(before) || before.nlink !== 1 || before.size > MAX_SNAPSHOT_BYTES) {
      throw new StateError("snapshot must be an owned, private, single-link regular file within its size bound");
    }
    const bytes = Buffer.alloc(before.size + 1);
    let length = 0;
    while (length < bytes.length) {
      const bytesRead = readSync(descriptor, bytes, length, bytes.length - length, length);
      if (bytesRead === 0) break;
      length += bytesRead;
    }
    const current = openAt(directory, name, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    let after: Stats;
    try { after = fstatSync(current); } finally { closeSync(current); }
    if (length !== before.size || after.dev !== before.dev || after.ino !== before.ino || after.size !== before.size || after.mtimeMs !== before.mtimeMs) {
      throw new StateError("snapshot changed while being read");
    }
    return bytes.subarray(0, length);
  } finally {
    closeSync(descriptor);
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
  let identity = privateDirectory(external, true);
  let root = external;
  for (const component of [FEATURE, repository.repositoryId, "snapshots"]) {
    root = join(root, component);
    identity = privateDirectory(root, true);
  }
  const directory = root;
  const expected = identity;

  function withDirectory<T>(action: (descriptor: number) => T): T {
    let descriptor: number;
    try { descriptor = openDirectory(directory); } catch (error) {
      if (code(error) === "ENOTDIR" || code(error) === "ELOOP") throw new StateError("snapshot directory was replaced");
      throw error;
    }
    try {
      const current = privateStat(descriptor);
      if (current.dev !== expected.dev || current.ino !== expected.ino) throw new StateError("snapshot directory was replaced");
      return action(descriptor);
    } finally {
      closeSync(descriptor);
    }
  }

  async function read(snapshotId: string): Promise<Snapshot> {
    assertSnapshotId(snapshotId);
    let bytes: Buffer;
    try { bytes = withDirectory(descriptor => privateRead(descriptor, `${snapshotId}.json`)); } catch (error) {
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

  function* snapshotIds(descriptor: number): Generator<string> {
    let count = 0;
    for (const name of directoryNames(descriptor)) {
      if (name.startsWith(".pending-")) continue;
      if (!name.endsWith(".json")) throw new StateError("unexpected entry in snapshot directory");
      const entry = openAt(descriptor, name, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
      try { if (!fstatSync(entry).isFile()) throw new StateError("unexpected entry in snapshot directory"); } finally { closeSync(entry); }
      const id = name.slice(0, -".json".length);
      try { assertSnapshotId(id); } catch { throw new StateError("unexpected entry in snapshot directory"); }
      if (++count > MAX_SNAPSHOTS) throw new StateError("snapshot limit exceeded");
      yield id;
    }
  }

  async function list(): Promise<string[]> {
    return withDirectory(descriptor => [...snapshotIds(descriptor)].sort());
  }

  async function record(recordedBy: Context, selection: Selection, observations: Observations, recordedAtMs: number): Promise<Snapshot> {
    return withDirectory(descriptor => {
      let count = 0;
      for (const id of snapshotIds(descriptor)) {
        if (++count >= MAX_SNAPSHOTS) throw new StateError(`snapshot limit reached at ${id}; no snapshot was published`);
      }
      const snapshot: Snapshot = {
        schema: SNAPSHOT_SCHEMA, featureVersion: FEATURE_VERSION, coreVersion: CORE_VERSION,
        snapshotId: newSnapshotId(recordedAtMs), recordedAtMs, recordedBy, repositoryId: repository.repositoryId, selection, observations,
      };
      parseSnapshot(JSON.parse(JSON.stringify(snapshot)) as unknown);
      const bytes = new TextEncoder().encode(`${canonicalJson(snapshot as unknown as Json)}\n`);
      if (bytes.byteLength > MAX_SNAPSHOT_BYTES) throw new StateError("snapshot exceeds its size bound");
      publish(descriptor, `${snapshot.snapshotId}.json`, bytes);
      return snapshot;
    });
  }

  return { root: directory, record, read, list };
}
