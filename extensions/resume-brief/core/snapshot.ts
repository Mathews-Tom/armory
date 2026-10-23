import { LIMITS, SNAPSHOT_SCHEMA } from "./index.ts";
import type { Context, Host, Observations, SourceRole, SourceStatus } from "./index.ts";

/**
 * A private derived cache of what was observed when a brief was recorded.
 * It holds source references and hashes, never source bodies or transcripts,
 * and is never an authoritative plan, memory or receipt store.
 */
export interface Snapshot {
  schema: typeof SNAPSHOT_SCHEMA;
  featureVersion: string;
  coreVersion: string;
  snapshotId: string;
  recordedAtMs: number;
  recordedBy: Context;
  repositoryId: string;
  selection: { contextPath: string; ompSessionPath: string | null; ompHandoffPath: string | null; receiptPath: string | null };
  observations: Observations;
}

export const SNAPSHOT_ID = /^\d{8}T\d{9}Z-[0-9a-f]{8}$/;

export function assertSnapshotId(value: string): void {
  if (!SNAPSHOT_ID.test(value)) throw new Error("invalid snapshot id");
}

// Strict structural validation of persisted state: an unexpected key, type or
// enum value rejects the snapshot instead of being reinterpreted.

type Check = (value: unknown, path: string) => void;

function fail(path: string, expected: string): never {
  throw new Error(`malformed snapshot at ${path}: expected ${expected}`);
}

const str = (maximum = 4096): Check => (value, path) => { if (typeof value !== "string" || value.length > maximum) fail(path, "bounded string"); };
const int: Check = (value, path) => { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) fail(path, "non-negative integer"); };
const num: Check = (value, path) => { if (typeof value !== "number" || !Number.isFinite(value) || value < 0) fail(path, "non-negative number"); };
const bool: Check = (value, path) => { if (typeof value !== "boolean") fail(path, "boolean"); };
const oneOf = (...items: readonly unknown[]): Check => (value, path) => { if (!items.includes(value)) fail(path, items.join("|")); };
const nullable = (check: Check): Check => (value, path) => { if (value !== null) check(value, path); };
const list = (check: Check, maximum: number): Check => (value, path) => {
  if (!Array.isArray(value) || value.length > maximum) fail(path, `list of at most ${maximum}`);
  value.forEach((item, index) => check(item, `${path}[${index}]`));
};
const shape = (fields: Record<string, Check>): Check => (value, path) => {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail(path, "object");
  const record = value as Record<string, unknown>;
  for (const key of Object.keys(record)) if (!Object.hasOwn(fields, key)) fail(`${path}.${key}`, "no such field");
  for (const [key, check] of Object.entries(fields)) {
    if (!Object.hasOwn(record, key)) fail(`${path}.${key}`, "present field");
    check(record[key], `${path}.${key}`);
  }
};

const HOSTS: readonly Host[] = ["standalone", "omp", "claude"];
const ROLES: readonly SourceRole[] = ["context", "plan", "blockers", "receipt", "omp-session", "omp-handoff"];
const STATUSES: readonly SourceStatus[] = ["ok", "missing", "unreadable", "rejected", "too-large", "unsupported-schema", "malformed", "changed-during-read", "not-selected"];
const sha = nullable((value, path) => { if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) fail(path, "sha256"); });
const context = shape({ host: oneOf(...HOSTS), accountId: str(LIMITS.referenceChars), sessionId: str(LIMITS.referenceChars) });
const approval = shape({
  id: str(128), scope: str(LIMITS.scopeChars),
  origin: shape({ host: oneOf(...HOSTS), accountId: nullable(str(LIMITS.referenceChars)), sessionId: nullable(str(LIMITS.referenceChars)) }),
  grantedAtMs: int, expiresAtMs: nullable(int), source: oneOf("context", "omp-session"),
});

const observations = shape({
  observedAtMs: int,
  git: shape({
    status: oneOf("ok", "unavailable", "changed-during-read"), repositoryId: sha, worktreeId: sha, worktreeRoot: nullable(str()),
    branch: nullable(str(1024)), detached: nullable(bool), head: nullable(str(64)), upstream: nullable(str(1024)), dirty: nullable(bool), diagnostic: nullable(str(512)),
  }),
  sources: list(shape({
    role: oneOf(...ROLES), ref: str(), status: oneOf(...STATUSES), sha256: sha, bytes: nullable(int), mtimeMs: nullable(num), diagnostic: nullable(str(512)),
  }), ROLES.length),
  context: nullable(shape({
    objective: str(LIMITS.objectiveChars), planPath: nullable(str(1024)), blockersPath: nullable(str(1024)),
    pullRequest: nullable(shape({ number: int, url: nullable(str(LIMITS.urlChars)) })),
    approvals: list(approval, LIMITS.approvals),
  })),
  plan: nullable(shape({ sha256: sha, lastCommit: nullable(str(64)), modifiedInWorktree: nullable(bool) })),
  blockers: nullable(shape({
    blockers: list(shape({ id: str(128), summary: str(LIMITS.summaryChars), status: oneOf("open", "resolved") }), LIMITS.blockers),
    nextAction: nullable(str(LIMITS.objectiveChars)),
  })),
  receipt: nullable(shape({
    executionId: str(128), gateId: str(LIMITS.referenceChars), status: oneOf("passed", "failed", "cancelled", "incomplete"),
    finishedAtMs: int, repositoryId: sha, host: oneOf(...HOSTS),
  })),
  ompSession: nullable(shape({
    sessionId: str(LIMITS.referenceChars), version: int, startedAt: str(64), cwd: str(), cwdResolved: nullable(str()),
    entryCount: int, lastEntryId: nullable(str(LIMITS.referenceChars)), lastEntryAt: nullable(str(64)), approvals: list(approval, LIMITS.approvals),
  })),
  ompHandoff: nullable(shape({ generatedAt: nullable(str(64)) })),
});

const snapshot = shape({
  schema: oneOf(SNAPSHOT_SCHEMA), featureVersion: str(32), coreVersion: str(32), snapshotId: str(64), recordedAtMs: int,
  recordedBy: context, repositoryId: sha,
  selection: shape({ contextPath: str(1024), ompSessionPath: nullable(str()), ompHandoffPath: nullable(str()), receiptPath: nullable(str()) }),
  observations,
});

export function parseSnapshot(value: unknown): Snapshot {
  if (value !== null && typeof value === "object" && "schema" in value && value.schema !== SNAPSHOT_SCHEMA) {
    throw new Error("unsupported snapshot schema; refusing to reinterpret it");
  }
  snapshot(value, "snapshot");
  const parsed = value as Snapshot;
  assertSnapshotId(parsed.snapshotId);
  return parsed;
}
