import { createHash, randomBytes, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import type { Stats } from "node:fs";
import { link, lstat, mkdir, open, opendir, realpath, unlink } from "node:fs/promises";
import { basename, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { canonicalJson } from "../core/index.ts";
import type { Context, Json, PendingRun, Receipt, RepositoryIdentity, RunPlan } from "../core/index.ts";
import { assertContext, assertExecutionId, parsePendingRun, parseReceipt } from "../core/validation.ts";

const MAX_JSON_BYTES = 1024 * 1024;
const MAX_OUTPUT_BYTES = 16 * 1024 * 1024;
const MAX_RECORDS = 10_000;

export interface RunLease {
  executionId: string;
  directory: string;
  outputPath: string;
  plan: RunPlan;
}

export interface ReceiptStore {
  key: Uint8Array;
  root: string;
  reserve(plan: RunPlan): Promise<RunLease>;
  finalize(lease: RunLease, receipt: Receipt): Promise<void>;
  read(executionId: string): Promise<Receipt>;
  list(): Promise<Receipt[]>;
  reconcile(): Promise<Receipt[]>;
}

function errorCode(error: unknown): string | undefined {
  return error instanceof Error && "code" in error && typeof error.code === "string" ? error.code : undefined;
}

function hash(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function inside(root: string, path: string): boolean {
  const child = relative(root, path);
  return child === "" || (child !== ".." && !child.startsWith("../") && !child.startsWith("/"));
}

async function privateDirectory(path: string, create = false): Promise<void> {
  let created = false;
  if (create) {
    try { await mkdir(path, { mode: 0o700 }); created = true; } catch (error) { if (errorCode(error) !== "EEXIST") throw error; }
  }
  const stat = await lstat(path);
  if (!stat.isDirectory() || stat.isSymbolicLink() || (stat.mode & 0o777) !== 0o700 || (process.getuid && stat.uid !== process.getuid())) {
    throw new Error("receipt directory must be owned, private, and not a link");
  }
  if (created) await syncDirectory(dirname(path));
}

function privateFile(stat: Stats, maximum: number): void {
  if (!stat.isFile() || (stat.mode & 0o777) !== 0o600 || (process.getuid && stat.uid !== process.getuid()) || stat.size > maximum) {
    throw new Error("receipt file must be owned, regular, private, and bounded");
  }
}

async function publicationState(path: string, initial: Stats, maximum: number): Promise<Stats> {
  privateFile(initial, maximum);
  if (initial.nlink === 1) return initial;
  if (initial.nlink !== 2) throw new Error("receipt file has foreign hard links");
  // A just-published file has precisely one destination-bound staging alias.
  // Account for that alias only; an arbitrary second link is never trusted.
  const prefix = `.pending-${basename(path)}-`;
  const directory = await opendir(dirname(path));
  let found = false;
  let count = 0;
  for await (const entry of directory) {
    if (++count > MAX_RECORDS * 2) throw new Error("receipt directory entry limit exceeded");
    if (!entry.name.startsWith(prefix) || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(entry.name.slice(prefix.length))) continue;
    let alias: Stats;
    try { alias = await lstat(join(dirname(path), entry.name)); } catch (error) {
      if (errorCode(error) === "ENOENT") continue;
      throw error;
    }
    if (alias.dev !== initial.dev || alias.ino !== initial.ino) continue;
    privateFile(alias, maximum);
    if (found || (alias.nlink !== 1 && alias.nlink !== 2)) throw new Error("receipt file has foreign hard links");
    found = alias.nlink === 2;
  }
  const current = await lstat(path);
  privateFile(current, maximum);
  if (current.dev !== initial.dev || current.ino !== initial.ino || current.size !== initial.size || current.mtimeMs !== initial.mtimeMs) {
    throw new Error("receipt file changed during publication");
  }
  // The publisher may have removed its alias while the directory was scanned.
  if (current.nlink === 1) return current;
  if (current.nlink === 2 && found && current.ctimeMs === initial.ctimeMs) return current;
  throw new Error("receipt file has foreign hard links");
}

async function privateRead(path: string, maximum: number): Promise<Buffer> {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = await publicationState(path, await handle.stat(), maximum);
    const bytes = Buffer.alloc(before.size + 1);
    let length = 0;
    while (length < bytes.length) {
      const { bytesRead } = await handle.read(bytes, length, bytes.length - length, length);
      if (bytesRead === 0) break;
      length += bytesRead;
    }
    const after = await publicationState(path, await handle.stat(), maximum);
    const current = await lstat(path);
    privateFile(current, maximum);
    const publicationCompleted = before.nlink === 2 && after.nlink === 1;
    const finalPublicationCompleted = after.nlink === 2 && current.nlink === 1;
    if (length !== before.size || before.size !== after.size || before.mtimeMs !== after.mtimeMs || (!publicationCompleted && before.ctimeMs !== after.ctimeMs) || current.ino !== before.ino || current.dev !== before.dev || current.size !== after.size || current.mtimeMs !== after.mtimeMs || (!finalPublicationCompleted && (current.nlink !== after.nlink || current.ctimeMs !== after.ctimeMs))) {
      throw new Error("receipt file changed while being read");
    }
    return bytes.subarray(0, length);
  } finally {
    await handle.close();
  }
}

async function exclusiveFile(path: string, bytes: Uint8Array): Promise<void> {
  const handle = await open(path, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW, 0o600);
  try {
    await handle.writeFile(bytes);
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function syncDirectory(path: string): Promise<void> {
  const directory = await open(path, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try { await directory.sync(); } finally { await directory.close(); }
}

async function publish(path: string, bytes: Uint8Array): Promise<void> {
  const temporary = join(dirname(path), `.pending-${basename(path)}-${randomUUID()}`);
  await exclusiveFile(temporary, bytes);
  try {
    await link(temporary, path);
  } finally {
    await unlink(temporary);
  }
  await syncDirectory(dirname(path));
}

async function recordNames(path: string, suffix: string): Promise<string[]> {
  await privateDirectory(path);
  const names: string[] = [];
  const directory = await opendir(path);
  for await (const entry of directory) {
    if (entry.name.startsWith(".pending-")) continue;
    if (names.length >= MAX_RECORDS || (suffix && !entry.name.endsWith(suffix))) throw new Error("unexpected receipt directory entry or record limit exceeded");
    const id = suffix ? entry.name.slice(0, -suffix.length) : entry.name;
    assertExecutionId(id);
    names.push(id);
  }
  return names.sort();
}

async function canonicalFuture(path: string): Promise<string> {
  let ancestor = resolve(path);
  const parts: string[] = [];
  for (;;) {
    try { return resolve(await realpath(ancestor), ...parts); } catch (error) {
      if (errorCode(error) !== "ENOENT") throw error;
      parts.unshift(basename(ancestor));
      const parent = dirname(ancestor);
      if (parent === ancestor) throw error;
      ancestor = parent;
    }
  }
}

export async function createStore(dataRoot: string, repository: RepositoryIdentity, context: Context): Promise<ReceiptStore> {
  assertContext(context);
  if (!dataRoot || dataRoot.includes("\0")) throw new Error("explicit external receipt data root is required");
  const external = await canonicalFuture(dataRoot);
  const packageRoot = await realpath(fileURLToPath(new URL("..", import.meta.url)));
  for (const forbidden of [repository.repositoryRoot, repository.worktreeRoot, packageRoot]) {
    if (inside(await realpath(forbidden), external)) throw new Error("receipt data root must be outside repository, worktree, and package");
  }
  const createdRoot = await mkdir(resolve(dataRoot), { recursive: true, mode: 0o700 });
  await privateDirectory(resolve(dataRoot));
  const base = await realpath(dataRoot);
  if (base !== external) throw new Error("receipt root changed during creation");
  if (createdRoot) {
    const firstCreated = await realpath(createdRoot);
    let directory = base;
    for (;;) {
      await syncDirectory(dirname(directory));
      if (directory === firstCreated) break;
      const parent = dirname(directory);
      if (parent === directory) throw new Error("receipt root creation identity mismatch");
      directory = parent;
    }
  }
  let root = base;
  for (const component of ["verification-receipts", hash(repository.repositoryId), hash(canonicalJson([context.host, context.accountId, context.workContext]))]) {
    root = join(root, component);
    await privateDirectory(root, true);
  }
  const runs = join(root, "runs");
  const receipts = join(root, "receipts");
  await privateDirectory(runs, true);
  await privateDirectory(receipts, true);
  const keyPath = join(root, "key.bin");
  try { await publish(keyPath, randomBytes(32)); } catch (error) { if (errorCode(error) !== "EEXIST") throw error; }
  const key = await privateRead(keyPath, 32);
  if (key.byteLength !== 32) throw new Error("invalid receipt fingerprint key");

  function assertPartition(plan: RunPlan, currentWorktree = false): void {
    if (plan.repository.repositoryId !== repository.repositoryId || plan.context.host !== context.host || plan.context.accountId !== context.accountId || plan.context.workContext !== context.workContext || (currentWorktree && (plan.repository.worktreeId !== repository.worktreeId || plan.repository.worktreeRoot !== repository.worktreeRoot))) {
      throw new Error("receipt belongs to another repository or context");
    }
  }

  async function pending(id: string): Promise<PendingRun> {
    assertExecutionId(id);
    await privateDirectory(root);
    await privateDirectory(runs);
    const directory = join(runs, id);
    await privateDirectory(directory);
    const value = parsePendingRun(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await privateRead(join(directory, "pending.json"), MAX_JSON_BYTES))) as unknown);
    assertPartition(value.plan);
    if (value.plan.executionId !== id) throw new Error("pending execution identity mismatch");
    return value;
  }

  async function read(executionId: string): Promise<Receipt> {
    assertExecutionId(executionId);
    await privateDirectory(root);
    await privateDirectory(receipts);
    const receipt = parseReceipt(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await privateRead(join(receipts, `${executionId}.json`), MAX_JSON_BYTES))) as unknown);
    assertPartition(receipt.plan);
    if (receipt.plan.executionId !== executionId) throw new Error("receipt execution identity mismatch");
    const directory = join(runs, executionId);
    await privateDirectory(runs);
    await privateDirectory(directory);
    await privateDirectory(join(directory, "artifacts"));
    const output = await privateRead(join(directory, "artifacts", "output.bin"), Math.min(MAX_OUTPUT_BYTES, receipt.plan.gate.maxOutputBytes));
    if (output.byteLength !== receipt.artifact.capturedBytes || hash(output) !== receipt.artifact.sha256) throw new Error("receipt artifact missing or altered");
    return receipt;
  }

  async function finalize(lease: RunLease, value: Receipt): Promise<void> {
    const receipt = parseReceipt(value);
    assertExecutionId(lease.executionId);
    assertPartition(receipt.plan);
    const state = await pending(lease.executionId);
    const directory = join(runs, lease.executionId);
    if (lease.directory !== directory || lease.outputPath !== join(directory, "output.bin") || receipt.plan.executionId !== lease.executionId || canonicalJson(state.plan as unknown as Json) !== canonicalJson(receipt.plan as unknown as Json) || canonicalJson(lease.plan as unknown as Json) !== canonicalJson(state.plan as unknown as Json)) {
      throw new Error("receipt does not match its exclusive run reservation");
    }
    const metadata = Buffer.from(canonicalJson(receipt as unknown as Json));
    if (metadata.byteLength > MAX_JSON_BYTES) throw new Error("receipt metadata limit exceeded");
    const output = await privateRead(lease.outputPath, Math.min(MAX_OUTPUT_BYTES, state.plan.gate.maxOutputBytes));
    if (output.byteLength !== receipt.artifact.capturedBytes || hash(output) !== receipt.artifact.sha256) throw new Error("finalized artifact does not match captured bytes and digest");
    const artifacts = join(directory, "artifacts");
    await privateDirectory(artifacts, true);
    const artifact = join(artifacts, "output.bin");
    try { await publish(artifact, output); } catch (error) {
      if (errorCode(error) !== "EEXIST") throw error;
      const existing = await privateRead(artifact, MAX_OUTPUT_BYTES);
      if (!existing.equals(output)) throw new Error("immutable artifact already exists with different bytes", { cause: error });
    }
    await syncDirectory(directory);
    await privateDirectory(receipts);
    await publish(join(receipts, `${lease.executionId}.json`), metadata);
  }

  return {
    root,
    key,
    async reserve(plan: RunPlan): Promise<RunLease> {
      const state = parsePendingRun({ schemaVersion: 1, ownerPid: process.pid, plan });
      assertPartition(state.plan, true);
      const bytes = Buffer.from(canonicalJson(state as unknown as Json));
      if (bytes.byteLength > MAX_JSON_BYTES) throw new Error("pending metadata limit exceeded");
      await privateDirectory(root);
      await privateDirectory(runs);
      if ((await recordNames(runs, "")).length >= MAX_RECORDS) throw new Error("receipt record limit exceeded");
      const directory = join(runs, plan.executionId);
      await mkdir(directory, { mode: 0o700 });
      await publish(join(directory, "pending.json"), bytes);
      await syncDirectory(directory);
      await syncDirectory(runs);
      return { executionId: plan.executionId, directory, outputPath: join(directory, "output.bin"), plan: state.plan };
    },
    finalize,
    read,
    async list(): Promise<Receipt[]> {
      const result: Receipt[] = [];
      for (const id of await recordNames(receipts, ".json")) result.push(await read(id));
      return result;
    },
    async reconcile(): Promise<Receipt[]> {
      const result: Receipt[] = [];
      for (const id of await recordNames(runs, "")) {
        let state: PendingRun;
        try { state = await pending(id); } catch (error) {
          // A reservation directory is visible before its atomic pending record.
          // Missing metadata proves nothing about ownership, so leave it alone.
          if (errorCode(error) === "ENOENT") continue;
          throw error;
        }
        try {
          await lstat(join(receipts, `${id}.json`));
          await read(id);
          continue;
        } catch (error) {
          if (errorCode(error) !== "ENOENT") throw error;
          // Only an absent finalized record may be reconciled. Missing artifacts
          // in an existing record are corruption, not an interrupted reservation.
          try { await lstat(join(receipts, `${id}.json`)); throw new Error("finalized receipt artifact is missing", { cause: error }); } catch (check) { if (errorCode(check) !== "ENOENT") throw check; }
        }
        let dead = false;
        try { process.kill(state.ownerPid, 0); } catch (error) {
          if (errorCode(error) === "ESRCH") dead = true;
          else if (errorCode(error) !== "EPERM") throw error;
        }
        if (!dead) continue;
        const directory = join(runs, id);
        const outputPath = join(directory, "output.bin");
        let output: Buffer;
        try { output = await privateRead(outputPath, Math.min(MAX_OUTPUT_BYTES, state.plan.gate.maxOutputBytes)); } catch (error) {
          if (errorCode(error) !== "ENOENT") throw error;
          try { await exclusiveFile(outputPath, new Uint8Array()); } catch (createError) { if (errorCode(createError) !== "EEXIST") throw createError; }
          output = await privateRead(outputPath, Math.min(MAX_OUTPUT_BYTES, state.plan.gate.maxOutputBytes));
        }
        const finishedAtMs = Math.max(Date.now(), state.plan.startedAtMs);
        const receipt: Receipt = {
          schemaVersion: 1, plan: state.plan,
          result: { status: "incomplete", exitCode: null, signal: null, reason: "owner-interrupted", descendantsStopped: false },
          after: null,
          artifact: { file: "output.bin", sha256: hash(output), capturedBytes: output.byteLength, totalBytes: null, truncated: null },
          finishedAtMs, durationMs: finishedAtMs - state.plan.startedAtMs,
          applicability: "unknown", applicabilityReason: "owner-interrupted",
        };
        try { await finalize({ executionId: id, directory, outputPath, plan: state.plan }, receipt); } catch (error) { if (errorCode(error) !== "EEXIST") throw error; }
        result.push(await read(id));
      }
      return result;
    },
  };
}
