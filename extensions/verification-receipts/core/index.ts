export const SCHEMA_VERSION = 1 as const;
export const CORE_VERSION = "1.0.0" as const;
export const FEATURE_VERSION = "1.0.0" as const;
export const FEATURE = "verification-receipts" as const;
export const FINGERPRINT_ALGORITHM = "armory-scope-v1" as const;

export type Host = "standalone" | "omp" | "claude";
export type CriterionKind = "unit" | "integration" | "static" | "live" | "human";
export type ExecutionStatus = "passed" | "failed" | "cancelled" | "incomplete";
export type Applicability = "current" | "stale" | "unknown";

export interface Context {
  host: Host;
  sessionId: string;
  accountId: string;
  workContext: string;
}

export interface RepositoryIdentity {
  repositoryId: string;
  repositoryRoot: string;
  worktreeId: string;
  worktreeRoot: string;
  revision: string | null;
  dirty: boolean | null;
}

export interface Scope {
  paths: string[];
  configPaths: string[];
  environmentNames: string[];
  datasetIdentity: string | null;
}

export interface Gate {
  criterionId: string;
  kind: CriterionKind;
  executable: string;
  args: string[];
  cwd: string;
  timeoutMs: number;
  maxOutputBytes: number;
  requiresCompleteOutput: boolean;
  scope: Scope;
}

export interface Configuration {
  schemaVersion: 1;
  configId: string;
  gates: Record<string, Gate>;
}

export interface ScopeEntry {
  path: string;
  kind: "file" | "directory" | "absent";
  executable: boolean;
  sha256: string | null;
}

export interface Snapshot {
  algorithm: typeof FINGERPRINT_ALGORITHM;
  digest: string;
  observedAtMs: number;
  entries: ScopeEntry[];
  environment: Record<string, string | null>;
  configDigest: string;
  datasetIdentity: string | null;
}

export interface RunPlan {
  schemaVersion: 1;
  feature: typeof FEATURE;
  featureVersion: string;
  coreVersion: string;
  executionId: string;
  repository: RepositoryIdentity;
  context: Context;
  gateId: string;
  gate: Gate;
  configId: string;
  configPath: string;
  configDigest: string;
  before: Snapshot;
  startedAtMs: number;
}

export interface Artifact {
  file: "output.bin";
  sha256: string;
  capturedBytes: number;
  totalBytes: number | null;
  truncated: boolean | null;
}

export interface Result {
  status: ExecutionStatus;
  exitCode: number | null;
  signal: string | null;
  reason: string | null;
  descendantsStopped: boolean;
}

export interface Receipt {
  schemaVersion: 1;
  plan: RunPlan;
  result: Result;
  after: Snapshot | null;
  artifact: Artifact;
  finishedAtMs: number;
  durationMs: number;
  applicability: Applicability;
  applicabilityReason: string | null;
}

export interface PendingRun {
  schemaVersion: 1;
  ownerPid: number;
  plan: RunPlan;
}

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

export function canonicalJson(value: Json): string {
  if (value === null || typeof value !== "object") {
    if (value !== null && typeof value !== "boolean" && typeof value !== "string" && typeof value !== "number") {
      throw new Error("unsupported JSON value");
    }
    if (typeof value === "number" && !Number.isFinite(value)) throw new Error("non-finite JSON number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${Array.from(value, canonicalJson).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => {
    const item = value[key];
    if (item === undefined) throw new Error("unsupported JSON value");
    return `${JSON.stringify(key)}:${canonicalJson(item)}`;
  }).join(",")}}`;
}

export function compareSnapshots(before: Snapshot, after: Snapshot | null): Applicability {
  if (after === null || before.algorithm !== after.algorithm) return "unknown";
  return before.digest === after.digest ? "current" : "stale";
}

export function executionApplicability(before: Snapshot, after: Snapshot | null): Applicability {
  return compareSnapshots(before, after) === "current" ? "current" : "unknown";
}

export function isSuccessfulProof(receipt: Receipt, current: Snapshot | null): boolean {
  return receipt.plan.featureVersion === FEATURE_VERSION
    && receipt.plan.coreVersion === CORE_VERSION
    && receipt.result.status === "passed"
    && receipt.result.descendantsStopped
    && receipt.applicability === "current"
    && compareSnapshots(receipt.plan.before, current) === "current"
    && (!receipt.plan.gate.requiresCompleteOutput || receipt.artifact.truncated === false);
}
