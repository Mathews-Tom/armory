import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { close, constants, fstat, read } from "node:fs";
import type { Stats } from "node:fs";
import { lstat, open, realpath } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import { promisify } from "node:util";
import { openRepositoryFile } from "./contained-open.ts";
import type {
  BlockersDocument,
  ContextDocument,
  GitObservation,
  Observations,
  OmpHandoffObservation,
  OmpSessionObservation,
  PlanObservation,
  ReceiptReference,
  SourceIdentity,
  SourceRole,
} from "../core/index.ts";
import {
  parseBlockers,
  parseContext,
  parseOmpHandoffName,
  parseOmpSession,
  parseReceiptReference,
  repositoryPath,
  SourceError,
} from "../core/validation.ts";

const closeDescriptor = promisify(close);
const descriptorStat = promisify(fstat);
const descriptorRead = promisify(read);
const exec = promisify(execFile);

export const MAX_BYTES: Record<SourceRole, number> = {
  context: 64 * 1024,
  plan: 1024 * 1024,
  blockers: 256 * 1024,
  receipt: 1024 * 1024,
  "omp-session": 16 * 1024 * 1024,
  "omp-handoff": 1024 * 1024,
};
const MAX_SESSION_LINES = 200_000;

/** Explicit selection: a repository-relative context artifact plus absolute native/receipt files. */
export interface Selection {
  contextPath: string;
  ompSessionPath: string | null;
  ompHandoffPath: string | null;
  receiptPath: string | null;
}

export interface Repository {
  repositoryId: string;
  repositoryRoot: string;
  worktreeRoot: string;
}

function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function code(error: unknown): string | undefined {
  return error instanceof Error && "code" in error && typeof error.code === "string" ? error.code : undefined;
}

const GIT_LOCATION_ENV = new Set([
  "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
  "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
]);

async function gitOutput(root: string, args: string[]): Promise<Buffer> {
  const env: NodeJS.ProcessEnv = { GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0", GIT_NO_LAZY_FETCH: "1", LC_ALL: "C" };
  for (const name of Object.keys(process.env)) {
    if (!GIT_LOCATION_ENV.has(name) && !Object.hasOwn(env, name)) env[name] = process.env[name];
  }
  const result = await exec("git", ["--literal-pathspecs", "-c", "core.fsmonitor=false", "-C", root, ...args], {
    encoding: "buffer", timeout: 5000, maxBuffer: MAX_BYTES.plan + 1,
    env,
  });
  return result.stdout;
}

async function git(root: string, args: string[]): Promise<string> {
  return (await gitOutput(root, args)).toString("utf8").trim();
}

/** Exit status 1 from a query means "no value" (unborn HEAD, detached HEAD, no upstream). */
async function gitOptional(root: string, args: string[]): Promise<string | null> {
  try {
    const value = await git(root, args);
    return value.length === 0 ? null : value;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === 1) return null;
    if (error instanceof Error && "code" in error && error.code === 128 && args.includes("@{upstream}")) return null;
    throw error;
  }
}

/** The selected path must be exactly a Git worktree root; no subdirectory aliasing. */
export async function resolveRepository(root: string): Promise<Repository> {
  if (!isAbsolute(root)) throw new Error("repository must be an absolute worktree root");
  const requested = await realpath(root);
  const worktreeRoot = await realpath(await git(requested, ["rev-parse", "--show-toplevel"]));
  if (worktreeRoot !== requested) throw new Error("repository must be the worktree root itself");
  const commonDir = await realpath(resolve(worktreeRoot, await git(worktreeRoot, ["rev-parse", "--git-common-dir"])));
  const repositoryRoot = basename(commonDir) === ".git" ? dirname(commonDir) : commonDir;
  // Same derivation as Verification Receipts, so receipt repository identity is comparable.
  return { repositoryId: sha256(commonDir), repositoryRoot, worktreeRoot };
}

async function gitFacts(repository: Repository): Promise<GitObservation> {
  const root = repository.worktreeRoot;
  try {
    const branch = await gitOptional(root, ["symbolic-ref", "--quiet", "--short", "HEAD"]);
    const head = await gitOptional(root, ["rev-parse", "--quiet", "--verify", "HEAD"]);
    const upstream = branch === null ? null : await gitOptional(root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]);
    if (head !== null && !/^[a-f0-9]{40,64}$/.test(head)) throw new Error("unexpected HEAD format");
    return {
      status: "ok", repositoryId: repository.repositoryId, worktreeId: sha256(root), worktreeRoot: root,
      branch, detached: branch === null, head, upstream, dirty: null,
      diagnostic: "working-tree dirty state is not evaluated: Git status may execute repository-configured commands",
    };
  } catch (error) {
    return {
      status: "unavailable", repositoryId: repository.repositoryId, worktreeId: sha256(root), worktreeRoot: root,
      branch: null, detached: null, head: null, upstream: null, dirty: null,
      diagnostic: `git query failed${code(error) === undefined ? "" : ` (${code(error)})`}`,
    };
  }
}

function sameFile(a: Stats, b: Stats): boolean {
  return a.dev === b.dev && a.ino === b.ino && a.size === b.size && a.mtimeMs === b.mtimeMs && a.ctimeMs === b.ctimeMs && a.mode === b.mode;
}

interface Read {
  identity: SourceIdentity;
  bytes: Buffer | null;
}

function failed(role: SourceRole, ref: string, status: SourceIdentity["status"], diagnostic: string, stat?: Stats): Read {
  return { identity: { role, ref, status, sha256: null, bytes: stat?.size ?? null, mtimeMs: stat?.mtimeMs ?? null, diagnostic }, bytes: null };
}

function errorStatus(error: unknown): { status: SourceIdentity["status"]; diagnostic: string } {
  const value = code(error);
  if (value === "ENOENT" || value === "ENOTDIR") return { status: "missing", diagnostic: "source does not exist" };
  if (value === "ELOOP") return { status: "rejected", diagnostic: "source is a symbolic link" };
  if (value === "EACCES" || value === "EPERM") return { status: "unreadable", diagnostic: `permission denied (${value})` };
  return { status: "unreadable", diagnostic: `read failed${value === undefined ? "" : ` (${value})`}` };
}

/**
 * Read one regular file without following a final symlink, refusing special
 * files and oversize content, and comparing identity before and after the read
 * so a concurrently changed source is reported as changed, never as stable.
 */
async function boundedRead(role: SourceRole, ref: string, path: string, repositoryRoot?: string): Promise<Read> {
  const maximum = MAX_BYTES[role];
  let handle;
  let descriptor: number;
  try {
    if (repositoryRoot === undefined) {
      handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
      descriptor = handle.fd;
    } else descriptor = await openRepositoryFile(repositoryRoot, ref);
  } catch (error) {
    if (repositoryRoot !== undefined && code(error) === "ENOTDIR") {
      return failed(role, ref, "changed-during-read", "source ancestor changed before it could be opened");
    }
    const { status, diagnostic } = errorStatus(error);
    return failed(role, ref, status, diagnostic);
  }
  try {
    const before = await descriptorStat(descriptor);
    if (!before.isFile()) return failed(role, ref, "rejected", "source is not a regular file");
    if (before.size > maximum) return failed(role, ref, "too-large", `source exceeds ${maximum} bytes`, before);
    const data = Buffer.alloc(before.size + 1);
    let length = 0;
    while (length < data.length) {
      const { bytesRead } = await descriptorRead(descriptor, data, length, data.length - length, length);
      if (bytesRead === 0) break;
      length += bytesRead;
    }
    const after = await descriptorStat(descriptor);
    let current: Stats;
    try { current = await lstat(path); } catch { return failed(role, ref, "changed-during-read", "source was removed while being read", before); }
    if (length !== before.size || !sameFile(before, after) || !sameFile(after, current) || !current.isFile()) {
      return failed(role, ref, "changed-during-read", "source identity changed while being read", after);
    }
    const bytes = data.subarray(0, length);
    return { identity: { role, ref, status: "ok", sha256: sha256(bytes), bytes: length, mtimeMs: before.mtimeMs, diagnostic: null }, bytes };
  } catch (error) {
    const { status, diagnostic } = errorStatus(error);
    return failed(role, ref, status, diagnostic);
  } finally {
    if (handle === undefined) await closeDescriptor(descriptor);
    else await handle.close();
  }
}

/** Preflight diagnostics plus descriptor-relative no-follow opens, never pathname-only containment. */
async function readInRepository(role: SourceRole, root: string, relative: unknown): Promise<Read> {
  let path: string;
  try { path = repositoryPath(relative, `${role} path`); } catch (error) {
    return failed(role, typeof relative === "string" ? relative.slice(0, 256) : "(invalid)", "rejected", error instanceof Error ? error.message : "invalid path");
  }
  let current = root;
  const parts = path.split("/");
  for (const [index, part] of parts.entries()) {
    current = join(current, part);
    let stat: Stats;
    try { stat = await lstat(current); } catch (error) {
      const { status, diagnostic } = errorStatus(error);
      return failed(role, path, status, diagnostic);
    }
    if (stat.isSymbolicLink()) return failed(role, path, "rejected", "source path contains a symbolic link");
    if (index < parts.length - 1 && !stat.isDirectory()) return failed(role, path, "missing", "source ancestor is not a directory");
  }
  return boundedRead(role, path, current, root);
}

/** Absolute explicitly selected file outside the repository (native session, handoff or receipt). */
export async function canonicalSelection(path: string, extension: string): Promise<string> {
  if (!isAbsolute(path) || path.includes("\0") || path.length > 4096) throw new Error(`selected ${extension} source must be an absolute path`);
  if (!basename(path).endsWith(extension)) throw new Error(`selected source must be a ${extension} file`);
  try {
    return join(await realpath(dirname(path)), basename(path));
  } catch {
    return resolve(path);
  }
}

function decode(bytes: Buffer): string {
  try { return new TextDecoder("utf-8", { fatal: true }).decode(bytes); } catch { throw new SourceError("malformed", "source is not valid UTF-8"); }
}

function json(bytes: Buffer): unknown {
  try { return JSON.parse(decode(bytes)) as unknown; } catch (error) {
    if (error instanceof SourceError) throw error;
    throw new SourceError("malformed", "source is not valid JSON");
  }
}

/** Apply a pure parser; a parse failure downgrades the source to an explicit unknown status. */
function interpret<T>(read: Read, parse: (bytes: Buffer) => T): { identity: SourceIdentity; value: T | null } {
  if (read.bytes === null) return { identity: read.identity, value: null };
  try {
    return { identity: read.identity, value: parse(read.bytes) };
  } catch (error) {
    if (!(error instanceof SourceError)) throw error;
    return { identity: { ...read.identity, status: error.status, diagnostic: error.message.slice(0, 300) }, value: null };
  }
}

function notSelected(role: SourceRole, diagnostic: string | null = null): SourceIdentity {
  return { role, ref: "", status: "not-selected", sha256: null, bytes: null, mtimeMs: null, diagnostic };
}

/** Git history facts for the plan; a failed query stays unknown and is named in the source diagnostic. */
async function planFacts(root: string, path: string, digest: string): Promise<{ plan: PlanObservation; diagnostic: string | null }> {
  const failures: string[] = [];
  const lastCommit = await gitOptional(root, ["log", "--no-show-signature", "--no-ext-diff", "--no-textconv", "--no-patch", "-1", "--format=%H", "--", path]).catch(() => { failures.push("last commit unavailable"); return null; });
  const modifiedInWorktree = await gitOutput(root, ["cat-file", "blob", `HEAD:${path}`]).then(
    (bytes) => sha256(bytes) !== digest,
    () => { failures.push("raw HEAD plan content unavailable"); return null; },
  );
  return { plan: { sha256: digest, lastCommit, modifiedInWorktree }, diagnostic: failures.length === 0 ? null : failures.join("; ") };
}

function sessionLines(bytes: Buffer): string[] {
  const lines = decode(bytes).split("\n");
  if (lines.length > MAX_SESSION_LINES) throw new SourceError("too-large", `session exceeds ${MAX_SESSION_LINES} lines`);
  return lines;
}

async function resolvedCwd(session: OmpSessionObservation): Promise<OmpSessionObservation> {
  try { return { ...session, cwdResolved: await realpath(session.cwd) }; } catch { return session; }
}

/** A Git fact that differs between the start and end of one observation is unknown. */
export function stableGit(before: GitObservation, after: GitObservation): GitObservation {
  if (before.status !== "ok" || after.status !== "ok") return after.status === "ok" ? before : after;
  if (before.branch === after.branch && before.head === after.head && before.dirty === after.dirty && before.upstream === after.upstream) return after;
  return {
    ...after, status: "changed-during-read", branch: null, detached: null, head: null, upstream: null, dirty: null,
    diagnostic: "branch, HEAD, upstream or dirty state changed while sources were read",
  };
}

/** Observe the selected repository and sources once, with bounded reads only. */
export async function observe(repository: Repository, selection: Selection, now: () => number): Promise<Observations> {
  const root = repository.worktreeRoot;
  const gitBefore = await gitFacts(repository);
  const sources: SourceIdentity[] = [];

  const contextRead = interpret(await readInRepository("context", root, selection.contextPath), (bytes): ContextDocument => parseContext(json(bytes)));
  sources.push(contextRead.identity);
  const context = contextRead.value;

  const contextUnknown = context === null ? "context artifact unavailable, so its selection is unknown" : null;
  let plan: PlanObservation | null = null;
  if (context?.planPath) {
    const read = await readInRepository("plan", root, context.planPath);
    if (read.identity.status === "ok" && read.identity.sha256 !== null) {
      const facts = await planFacts(root, context.planPath, read.identity.sha256);
      plan = facts.plan;
      sources.push({ ...read.identity, diagnostic: facts.diagnostic });
    } else sources.push(read.identity);
  } else sources.push(notSelected("plan", contextUnknown));

  let blockers: BlockersDocument | null = null;
  if (context?.blockersPath) {
    const read = interpret(await readInRepository("blockers", root, context.blockersPath), (bytes) => parseBlockers(json(bytes)));
    sources.push(read.identity);
    blockers = read.value;
  } else sources.push(notSelected("blockers", contextUnknown));

  let receipt: ReceiptReference | null = null;
  if (selection.receiptPath !== null) {
    const read = interpret(await boundedRead("receipt", selection.receiptPath, selection.receiptPath), (bytes) => parseReceiptReference(json(bytes)));
    sources.push(read.identity);
    receipt = read.value;
  } else sources.push(notSelected("receipt"));

  let ompSession: OmpSessionObservation | null = null;
  if (selection.ompSessionPath !== null) {
    const read = interpret(await boundedRead("omp-session", selection.ompSessionPath, selection.ompSessionPath), (bytes) => parseOmpSession(sessionLines(bytes)));
    sources.push(read.identity);
    ompSession = read.value === null ? null : await resolvedCwd(read.value);
  } else sources.push(notSelected("omp-session"));

  let ompHandoff: OmpHandoffObservation | null = null;
  if (selection.ompHandoffPath !== null) {
    const path = selection.ompHandoffPath;
    const read = interpret(await boundedRead("omp-handoff", path, path), () => parseOmpHandoffName(basename(path)));
    sources.push(read.identity);
    ompHandoff = read.value;
  } else sources.push(notSelected("omp-handoff"));

  const gitAfter = await gitFacts(repository);
  return { observedAtMs: now(), git: stableGit(gitBefore, gitAfter), sources, context, plan, blockers, receipt, ompSession, ompHandoff };
}
