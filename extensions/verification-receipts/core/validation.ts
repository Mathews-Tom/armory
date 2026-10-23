import { FEATURE, FINGERPRINT_ALGORITHM, SCHEMA_VERSION } from "./index.ts";
import type { Configuration, Context, Gate, PendingRun, Receipt, RunPlan, Scope, Snapshot } from "./index.ts";

const MAX_OUTPUT = 16 * 1024 * 1024;
const DIGEST = /^[a-f0-9]{64}$/u;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/u;
const ENVIRONMENT_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,127}$/u;

function reject(): never {
  throw new Error("invalid verification receipt or configuration");
}

function object(value: unknown, keys?: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) reject();
  const prototype: unknown = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) reject();
  const result = value as Record<string, unknown>;
  if (keys !== undefined) {
    const names = Object.keys(result);
    if (names.length !== keys.length || names.some((key) => !keys.includes(key))) reject();
  }
  return result;
}

function text(value: unknown, maximum = 4096): asserts value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum || value.includes("\0")) reject();
}

function reference(value: unknown): asserts value is string {
  text(value, 256);
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) reject();
  }
}

function integer(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): asserts value is number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) reject();
}

function boolean(value: unknown): asserts value is boolean {
  if (typeof value !== "boolean") reject();
}

function digest(value: unknown): asserts value is string {
  if (typeof value !== "string" || !DIGEST.test(value)) reject();
}

function path(value: unknown, root = false): asserts value is string {
  text(value);
  if (root && value === ".") return;
  if (value.startsWith("/") || value.includes("\\") || value.split("/").some((part) => part === "" || part === "." || part === ".." || part === ".git")) reject();
}

function list(value: unknown, maximum: number): unknown[] {
  if (!Array.isArray(value) || value.length > maximum) reject();
  return value as unknown[];
}

function scope(value: unknown): Scope {
  const item = object(value, ["paths", "configPaths", "environmentNames", "datasetIdentity"]);
  for (const entry of list(item.paths, 10_000)) path(entry, true);
  for (const entry of list(item.configPaths, 10_000)) path(entry);
  for (const entry of list(item.environmentNames, 256)) {
    if (typeof entry !== "string" || !ENVIRONMENT_NAME.test(entry)) reject();
  }
  if (item.datasetIdentity !== null) reference(item.datasetIdentity);
  return value as Scope;
}

function gate(value: unknown): Gate {
  const item = object(value, ["criterionId", "kind", "executable", "args", "cwd", "timeoutMs", "maxOutputBytes", "requiresCompleteOutput", "scope"]);
  reference(item.criterionId);
  if (item.kind !== "unit" && item.kind !== "integration" && item.kind !== "static" && item.kind !== "live" && item.kind !== "human") reject();
  text(item.executable);
  for (const arg of list(item.args, 1024)) {
    if (typeof arg !== "string" || arg.length > 4096 || arg.includes("\0")) reject();
  }
  path(item.cwd, true);
  integer(item.timeoutMs, 1, 3_600_000);
  integer(item.maxOutputBytes, 1, MAX_OUTPUT);
  boolean(item.requiresCompleteOutput);
  scope(item.scope);
  return value as Gate;
}

export function assertExecutionId(value: string): void {
  if (typeof value !== "string" || !UUID.test(value)) reject();
}

export function assertContext(value: unknown): asserts value is Context {
  const item = object(value, ["host", "sessionId", "accountId", "workContext"]);
  if (item.host !== "standalone" && item.host !== "omp" && item.host !== "claude") reject();
  reference(item.sessionId);
  reference(item.accountId);
  reference(item.workContext);
}

export function parseConfiguration(value: unknown): Configuration {
  const item = object(value, ["schemaVersion", "configId", "gates"]);
  if (item.schemaVersion !== SCHEMA_VERSION) reject();
  reference(item.configId);
  const gates = object(item.gates);
  const entries = Object.entries(gates);
  if (entries.length === 0 || entries.length > 256) reject();
  for (const [name, configured] of entries) {
    reference(name);
    gate(configured);
  }
  return value as Configuration;
}

function snapshot(value: unknown): Snapshot {
  const item = object(value, ["algorithm", "digest", "observedAtMs", "entries", "environment", "configDigest", "datasetIdentity"]);
  if (item.algorithm !== FINGERPRINT_ALGORITHM) reject();
  digest(item.digest);
  digest(item.configDigest);
  integer(item.observedAtMs);
  if (item.datasetIdentity !== null) reference(item.datasetIdentity);
  const entries = list(item.entries, 10_000);
  const paths = new Set<string>();
  for (const entry of entries) {
    const file = object(entry, ["path", "kind", "executable", "sha256"]);
    path(file.path, true);
    if (paths.has(file.path)) reject();
    paths.add(file.path);
    boolean(file.executable);
    if (file.kind === "file") digest(file.sha256);
    else if (file.kind !== "directory" && file.kind !== "absent") reject();
    else if (file.sha256 !== null || file.executable) reject();
  }
  const environment = Object.entries(object(item.environment));
  if (environment.length > 256) reject();
  for (const [name, hashed] of environment) {
    if (!ENVIRONMENT_NAME.test(name)) reject();
    if (hashed !== null) digest(hashed);
  }
  return value as Snapshot;
}

function plan(value: unknown): RunPlan {
  const item = object(value, ["schemaVersion", "feature", "featureVersion", "coreVersion", "executionId", "repository", "context", "gateId", "gate", "configId", "configPath", "configDigest", "before", "startedAtMs"]);
  if (item.schemaVersion !== SCHEMA_VERSION || item.feature !== FEATURE) reject();
  // Schema compatibility governs historical reads; version identity governs proof.
  reference(item.featureVersion);
  reference(item.coreVersion);
  if (typeof item.executionId !== "string") reject();
  assertExecutionId(item.executionId);
  const repository = object(item.repository, ["repositoryId", "repositoryRoot", "worktreeId", "worktreeRoot", "revision", "dirty"]);
  digest(repository.repositoryId);
  digest(repository.worktreeId);
  for (const root of [repository.repositoryRoot, repository.worktreeRoot]) {
    text(root);
    if (!root.startsWith("/")) reject();
  }
  if (repository.revision !== null && (typeof repository.revision !== "string" || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/u.test(repository.revision))) reject();
  if (repository.dirty !== null) boolean(repository.dirty);
  assertContext(item.context);
  reference(item.gateId);
  const configured = gate(item.gate);
  reference(item.configId);
  path(item.configPath);
  digest(item.configDigest);
  const before = snapshot(item.before);
  if (before.configDigest !== item.configDigest || before.datasetIdentity !== configured.scope.datasetIdentity) reject();
  const environment = Object.keys(before.environment);
  const declared = new Set(configured.scope.environmentNames);
  if (environment.length !== declared.size || environment.some((name) => !declared.has(name))) reject();
  integer(item.startedAtMs);
  return value as RunPlan;
}

export function parsePendingRun(value: unknown): PendingRun {
  const item = object(value, ["schemaVersion", "ownerPid", "plan"]);
  if (item.schemaVersion !== SCHEMA_VERSION) reject();
  integer(item.ownerPid, 1);
  plan(item.plan);
  return value as PendingRun;
}

export function parseReceipt(value: unknown): Receipt {
  const item = object(value, ["schemaVersion", "plan", "result", "after", "artifact", "finishedAtMs", "durationMs", "applicability", "applicabilityReason"]);
  if (item.schemaVersion !== SCHEMA_VERSION) reject();
  const execution = plan(item.plan);
  const result = object(item.result, ["status", "exitCode", "signal", "reason", "descendantsStopped"]);
  if (result.status !== "passed" && result.status !== "failed" && result.status !== "cancelled" && result.status !== "incomplete") reject();
  if (result.exitCode !== null) integer(result.exitCode, 0, 255);
  if (result.signal !== null) reference(result.signal);
  if (result.reason !== null) reference(result.reason);
  boolean(result.descendantsStopped);
  if (result.status === "passed" && (result.exitCode !== 0 || result.signal !== null || result.reason !== null || !result.descendantsStopped)) reject();
  if (result.status === "failed" && (result.exitCode === null || result.exitCode === 0)) reject();
  const after = item.after === null ? null : snapshot(item.after);
  if (item.applicability !== "current" && item.applicability !== "stale" && item.applicability !== "unknown") reject();
  if (item.applicabilityReason !== null) reference(item.applicabilityReason);
  if (item.applicability === "current" && (after === null || after.digest !== execution.before.digest)) reject();
  const artifact = object(item.artifact, ["file", "sha256", "capturedBytes", "totalBytes", "truncated"]);
  if (artifact.file !== "output.bin") reject();
  digest(artifact.sha256);
  integer(artifact.capturedBytes, 0, execution.gate.maxOutputBytes);
  if (artifact.totalBytes === null || artifact.truncated === null) {
    if (artifact.totalBytes !== null || artifact.truncated !== null || result.status !== "incomplete" || result.reason !== "owner-interrupted" || item.applicability !== "unknown") reject();
  } else {
    integer(artifact.totalBytes, artifact.capturedBytes);
    boolean(artifact.truncated);
    if (artifact.truncated !== (artifact.totalBytes > artifact.capturedBytes)) reject();
  }
  integer(item.finishedAtMs);
  if (typeof item.durationMs !== "number" || !Number.isFinite(item.durationMs) || item.durationMs < 0) reject();
  return value as Receipt;
}
