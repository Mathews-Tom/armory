import { execFile } from "node:child_process";
import { createHash, createHmac } from "node:crypto";
import { constants } from "node:fs";
import { lstat, open, opendir, realpath } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import { promisify } from "node:util";
import { canonicalJson, FINGERPRINT_ALGORITHM } from "../core/index.ts";
import type { Configuration, Json, RepositoryIdentity, Scope, ScopeEntry, Snapshot } from "../core/index.ts";
import { parseConfiguration } from "../core/validation.ts";

const exec = promisify(execFile);
const MAX_CONFIG_BYTES = 1024 * 1024;
const MAX_FILE_BYTES = 16 * 1024 * 1024;
const MAX_SCOPE_BYTES = 128 * 1024 * 1024;
const MAX_ENTRIES = 10_000;

function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function absent(error: unknown): boolean {
  return error instanceof Error && "code" in error && error.code === "ENOENT";
}

function scopedPath(value: string, allowRoot = true): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 4096 || value.includes("\0") || value.includes("\\") || isAbsolute(value)) {
    throw new Error("scope path must be a bounded relative path");
  }
  if (value === "." && allowRoot) return value;
  if (value.split("/").some((part) => part === "" || part === "." || part === ".." || part === ".git")) {
    throw new Error("scope path contains a forbidden component");
  }
  return value;
}

async function contained(root: string, path: string): Promise<string> {
  const parts = path === "." ? [] : path.split("/");
  let current = root;
  for (const part of parts) {
    current = join(current, part);
    try {
      const stat = await lstat(current);
      if (stat.isSymbolicLink()) throw new Error("scope symlinks are not supported");
      if (!stat.isDirectory() && current !== join(root, path)) throw new Error("scope ancestor is not a directory");
    } catch (error) {
      if (!absent(error)) throw error;
      break;
    }
  }
  return join(root, path);
}

async function readRegular(path: string, maximum: number): Promise<{ bytes: Buffer; executable: boolean }> {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = await handle.stat();
    if (!before.isFile() || before.size > maximum) throw new Error("scope file is not regular or exceeds its byte limit");
    const data = Buffer.alloc(before.size + 1);
    let length = 0;
    while (length < data.length) {
      const { bytesRead } = await handle.read(data, length, data.length - length, length);
      if (bytesRead === 0) break;
      length += bytesRead;
    }
    const after = await handle.stat();
    const pathStat = await lstat(path);
    if (length !== before.size || before.size !== after.size || before.mode !== after.mode || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs || before.ino !== pathStat.ino || before.dev !== pathStat.dev || after.mode !== pathStat.mode || after.size !== pathStat.size || after.mtimeMs !== pathStat.mtimeMs || after.ctimeMs !== pathStat.ctimeMs || !pathStat.isFile()) {
      throw new Error("scope file changed while being read");
    }
    return { bytes: data.subarray(0, length), executable: (before.mode & 0o111) !== 0 };
  } finally {
    await handle.close();
  }
}

async function git(root: string, args: string[]): Promise<string> {
  const result = await exec("git", ["-C", root, ...args], {
    encoding: "utf8", timeout: 5000, maxBuffer: 64 * 1024,
    env: { ...process.env, GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" },
  });
  return result.stdout.trim();
}

export async function resolveRepository(root: string): Promise<RepositoryIdentity> {
  const requested = await realpath(root);
  const worktreeRoot = await realpath(await git(requested, ["rev-parse", "--show-toplevel"]));
  const common = await git(worktreeRoot, ["rev-parse", "--git-common-dir"]);
  const commonDir = await realpath(resolve(worktreeRoot, common));
  const repositoryRoot = basename(commonDir) === ".git" ? dirname(commonDir) : commonDir;
  let revision: string | null = null;
  let dirty: boolean | null = null;
  try {
    const value = await git(worktreeRoot, ["rev-parse", "--verify", "HEAD"]);
    if (/^[a-f0-9]{40,64}$/.test(value)) revision = value;
  } catch { /* Unborn or unavailable revision remains unknown, never invented. */ }
  try {
    dirty = (await git(worktreeRoot, ["status", "--porcelain=v1", "--untracked-files=normal"])).length !== 0;
  } catch { /* Bounded metadata failure leaves dirty state unknown. */ }
  return { repositoryId: sha256(commonDir), repositoryRoot, worktreeId: sha256(worktreeRoot), worktreeRoot, revision, dirty };
}

export async function loadConfiguration(repositoryRoot: string, configPath: string): Promise<{ config: Configuration; configPath: string; configDigest: string }> {
  const root = await realpath(repositoryRoot);
  const normalized = scopedPath(configPath, false);
  const path = await contained(root, normalized);
  const { bytes } = await readRegular(path, MAX_CONFIG_BYTES);
  const config = parseConfiguration(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown);
  return { config, configPath: normalized, configDigest: sha256(bytes) };
}

export async function captureSnapshot(repositoryRoot: string, scope: Scope, configPath: string, key: Uint8Array): Promise<Snapshot> {
  if (key.byteLength !== 32) throw new Error("scope fingerprint key must be 32 bytes");
  const root = await realpath(repositoryRoot);
  const configuration = await loadConfiguration(root, configPath);
  if (!Array.isArray(scope.paths) || !Array.isArray(scope.configPaths) || !Array.isArray(scope.environmentNames) || (scope.datasetIdentity !== null && typeof scope.datasetIdentity !== "string")) {
    throw new Error("invalid fingerprint scope");
  }
  const paths = [...new Set(scope.paths.map((path) => scopedPath(path)))].sort();
  const configPaths = [...new Set(scope.configPaths.map((path) => scopedPath(path, false)))].sort();
  const environmentNames = [...new Set(scope.environmentNames)].sort();
  if (paths.length + configPaths.length > MAX_ENTRIES || environmentNames.length > 256 || environmentNames.some((name) => !/^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name))) {
    throw new Error("fingerprint scope exceeds limits or contains an invalid environment name");
  }
  const entries = new Map<string, ScopeEntry>();
  let bytesRead = 0;
  async function visit(path: string): Promise<void> {
    if (entries.has(path)) return;
    if (entries.size >= MAX_ENTRIES) throw new Error("scope entry limit exceeded");
    const absolute = await contained(root, path);
    let stat;
    try { stat = await lstat(absolute); } catch (error) {
      if (!absent(error)) throw error;
      entries.set(path, { path, kind: "absent", executable: false, sha256: null });
      return;
    }
    if (stat.isSymbolicLink()) throw new Error("scope symlinks are not supported");
    if (stat.isFile()) {
      const content = await readRegular(absolute, Math.min(MAX_FILE_BYTES, MAX_SCOPE_BYTES - bytesRead));
      bytesRead += content.bytes.byteLength;
      entries.set(path, { path, kind: "file", executable: content.executable, sha256: sha256(content.bytes) });
    } else if (stat.isDirectory()) {
      entries.set(path, { path, kind: "directory", executable: false, sha256: null });
      const directory = await opendir(absolute);
      for await (const entry of directory) {
        if (entry.name === ".git") continue;
        await visit(path === "." ? entry.name : `${path}/${entry.name}`);
      }
      const after = await lstat(absolute);
      if (!after.isDirectory() || after.dev !== stat.dev || after.ino !== stat.ino || after.mtimeMs !== stat.mtimeMs || after.ctimeMs !== stat.ctimeMs) {
        throw new Error("scope directory changed while being read");
      }
    } else {
      throw new Error("special files cannot be fingerprinted");
    }
  }
  for (const path of [...new Set([...paths, ...configPaths, configuration.configPath])].sort()) await visit(path);
  if (entries.get(configuration.configPath)?.sha256 !== configuration.configDigest) throw new Error("configuration changed during snapshot capture");
  const environment: Record<string, string | null> = Object.create(null) as Record<string, string | null>;
  for (const name of environmentNames) {
    const value = process.env[name];
    environment[name] = value === undefined ? null : createHmac("sha256", key).update(canonicalJson(["armory-environment-v1", name, value])).digest("hex");
  }
  const sortedEntries = [...entries.values()].sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  const digest = sha256(canonicalJson({
    algorithm: FINGERPRINT_ALGORITHM,
    fileAlgorithm: "sha256-content-executable-membership-v1",
    environmentAlgorithm: "hmac-sha256-selected-v1",
    datasetAlgorithm: "declared-identity-v1",
    scope: { paths, configPaths, environmentNames, datasetIdentity: scope.datasetIdentity },
    entries: sortedEntries as unknown as Json,
    environment,
    configDigest: configuration.configDigest,
  }));
  return { algorithm: FINGERPRINT_ALGORITHM, digest, observedAtMs: Date.now(), entries: sortedEntries, environment, configDigest: configuration.configDigest, datasetIdentity: scope.datasetIdentity };
}
