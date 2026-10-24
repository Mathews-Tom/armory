import { ADAPTER_ID, ADAPTER_VERSION, CORE_VERSION, MAX_BINDINGS, SCHEMA_VERSION } from "./types.ts";
import type { AdmissionRecord, BridgeResult, Declaration, Facts, Identity, Invocation, ProbeResponse, ProjectConfig, Quota, Response } from "./types.ts";
import { canonicalJson } from "./canonical.ts";
import { parseTimestamp } from "./timestamp.ts";
import { hasUnsafeCharacters } from "./text.ts";

export class ValidationError extends Error {
  constructor() { super("preflight document is malformed or unsupported"); }
}
type ObjectValue = Record<string, unknown>;
function fail(): never { throw new ValidationError(); }
function object(value: unknown, keys: readonly string[]): ObjectValue {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return fail();
  const result = value as ObjectValue;
  const actual = Object.keys(result);
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key))) return fail();
  return result;
}
function text(value: unknown, maximum = 256): asserts value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum || hasUnsafeCharacters(value)) fail();
}
function absolute(value: unknown): asserts value is string {
  text(value, 4096);
  if (!value.startsWith("/") || value.includes("//") || value.split("/").some((part) => part === "." || part === "..") || (value.length > 1 && value.endsWith("/"))) fail();
}
function digest(value: unknown): void { if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) fail(); }
function integer(value: unknown, minimum = 1): asserts value is number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) fail();
}
function bool(value: unknown): void { if (typeof value !== "boolean") fail(); }
function literal(value: unknown, choices: readonly unknown[]): void { if (!choices.includes(value)) fail(); }
function timestamp(value: unknown): number {
  if (typeof value !== "string") fail();
  const result = parseTimestamp(value);
  if (result === null) fail();
  return result;
}
function interval(start: unknown, end: unknown): void { if (timestamp(end) <= timestamp(start)) fail(); }
function array(value: unknown, check: (item: unknown) => void, minimum = 1, maximum = MAX_BINDINGS): asserts value is unknown[] {
  if (!Array.isArray(value) || value.length < minimum || value.length > maximum) fail();
  for (const item of value) check(item);
}
export function freeze<T>(value: T): T {
  if (value !== null && typeof value === "object") {
    for (const item of Object.values(value)) freeze(item);
    Object.freeze(value);
  }
  return value;
}
// Parsing JSON into a fresh tree prevents caller-owned aliases from changing a validated record.
function copy<T>(value: unknown): T { return freeze(JSON.parse(JSON.stringify(value)) as T); }
function binding(value: unknown): void { const item = object(value, ["path", "sha256"]); absolute(item.path); digest(item.sha256); }
function invocation(value: unknown): void {
  const item = object(value, ["adapterId", "adapterVersion", "targetId", "targetModel", "targetThinking", "profile", "cell", "wallSeconds", "checkpointRoot"]);
  literal(item.adapterId, [ADAPTER_ID]); literal(item.adapterVersion, [ADAPTER_VERSION]);
  for (const key of ["targetId", "targetModel", "targetThinking", "profile"]) text(item[key]);
  if (!(item.targetModel as string).includes("/")) fail();
  const cell = object(item.cell, ["taskId", "condition", "targetId", "repetition", "conditionHash"]);
  for (const key of ["taskId", "condition", "targetId"]) text(cell[key]);
  integer(cell.repetition); digest(cell.conditionHash);
  if (cell.targetId !== item.targetId) fail();
  integer(item.wallSeconds); absolute(item.checkpointRoot);
}
export function parseInvocation(value: unknown): Invocation { invocation(value); return copy(value); }
function config(value: unknown): void {
  const item = object(value, ["schemaVersion", "adapterId", "adapterVersion", "coreVersion", "packageRoot", "helperPath", "projectRoot", "contractPath", "bridgeArgv"]);
  literal(item.schemaVersion, [SCHEMA_VERSION]); literal(item.adapterId, [ADAPTER_ID]); literal(item.adapterVersion, [ADAPTER_VERSION]); literal(item.coreVersion, [CORE_VERSION]);
  for (const key of ["packageRoot", "projectRoot", "contractPath"]) absolute(item[key]);
  literal(item.helperPath, ["helpers/cli.ts", "helpers/cli.js"]);
  array(item.bridgeArgv, (arg) => text(arg, 4096), 2, 64);
  absolute((item.bridgeArgv as unknown[])[0]);
  absolute((item.bridgeArgv as unknown[])[1]);
}
export function parseConfig(value: unknown): ProjectConfig { config(value); return copy(value); }
function identity(value: unknown): void {
  const item = object(value, ["schemaVersion", "provider", "profile", "accountFingerprint", "kind", "auth", "observedAt", "expiresAt"]);
  literal(item.schemaVersion, [SCHEMA_VERSION]);
  for (const key of ["provider", "profile", "accountFingerprint"]) text(item[key]);
  literal(item.kind, ["synthetic-local", "managed"]); literal(item.auth, ["not-applicable", "attested"]); interval(item.observedAt, item.expiresAt);
}
export function parseIdentity(value: unknown): Identity { identity(value); return copy(value); }
function quota(value: unknown): void {
  const item = object(value, ["status", "observedAt", "expiresAt", "reason", "source", "remainingCalls"]);
  literal(item.status, ["observed", "unknown"]); interval(item.observedAt, item.expiresAt); text(item.reason, 512); text(item.source);
  if (item.status === "unknown") { if (item.remainingCalls !== null) fail(); } else integer(item.remainingCalls, 0);
}
function limit(value: unknown, currency = false): void {
  const item = object(value, currency ? ["value", "required", "unit"] : ["value", "required"]);
  if (currency) {
    if (typeof item.value !== "number" || !Number.isFinite(item.value) || item.value <= 0) fail();
    text(item.unit, 16);
  } else integer(item.value);
  bool(item.required);
}
function authorization(value: unknown): void {
  const item = object(value, ["runId", "purpose", "accountFingerprint", "scope", "invocationSha256", "acknowledgeUnknownQuota", "issuedAt", "expiresAt"]);
  text(item.runId); text(item.accountFingerprint); literal(item.purpose, ["synthetic-local-sentinel", "managed"]);
  literal(item.scope, ["local-sentinel-only", "managed-invocation"]); digest(item.invocationSha256); bool(item.acknowledgeUnknownQuota); interval(item.issuedAt, item.expiresAt);
}
function declaration(value: unknown): void {
  const item = object(value, ["schemaVersion", "runId", "purpose", "issuedAt", "expiresAt", "configSha256", "invocation", "inputs", "checkpoint", "limits", "quota", "authorizations"]);
  literal(item.schemaVersion, [SCHEMA_VERSION]); text(item.runId); literal(item.purpose, ["synthetic-local-sentinel", "managed"]); interval(item.issuedAt, item.expiresAt); digest(item.configSha256); invocation(item.invocation);
  const inputs = object(item.inputs, ["source", "config", "data", "identity"]);
  for (const key of ["source", "config", "data"]) array(inputs[key], binding);
  binding(inputs.identity);
  const all = [...inputs.source as unknown[], ...inputs.config as unknown[], ...inputs.data as unknown[], inputs.identity] as { path: string }[];
  if (new Set(all.map((file) => file.path)).size !== all.length) fail();
  const checkpoint = object(item.checkpoint, ["path"]); absolute(checkpoint.path);
  const limits = object(item.limits, ["calls", "workers", "concurrency", "wallSeconds", "tokens", "currency"]);
  for (const key of ["calls", "workers", "concurrency", "wallSeconds"]) limit(limits[key]);
  if (limits.tokens !== null) limit(limits.tokens);
  if (limits.currency !== null) limit(limits.currency, true);
  quota(item.quota); array(item.authorizations, authorization, 0, 64);
}
export function parseDeclaration(value: unknown): Declaration { declaration(value); return copy(value); }
function fileFact(value: unknown): void {
  const item = object(value, ["path", "sha256", "realPath", "device", "inode", "size", "modifiedNs"]);
  absolute(item.path); absolute(item.realPath); digest(item.sha256); integer(item.size, 0);
  for (const key of ["device", "inode", "modifiedNs"]) if (typeof item[key] !== "string" || !/^[0-9]+$/.test(item[key] as string)) fail();
}
function directoryFact(value: unknown): void {
  const item = object(value, ["path", "realPath", "device", "inode", "mode", "uid", "gid", "writable"]);
  absolute(item.path); absolute(item.realPath);
  for (const key of ["device", "inode"]) if (typeof item[key] !== "string" || !/^[0-9]+$/.test(item[key] as string)) fail();
  for (const key of ["mode", "uid", "gid"]) integer(item[key], 0);
  bool(item.writable);
}
function facts(value: unknown): void {
  const item = object(value, ["config", "declaration", "helper", "source", "configs", "data", "identityFile", "identity", "checkpoint", "projectRoot", "packageRoot"]);
  for (const key of ["config", "declaration", "helper", "identityFile"]) fileFact(item[key]);
  for (const key of ["source", "configs", "data"]) array(item[key], fileFact);
  identity(item.identity);
  for (const key of ["checkpoint", "projectRoot", "packageRoot"]) directoryFact(item[key]);
}
export function parseFacts(value: unknown): Facts { facts(value); return copy(value); }
function capabilities(value: unknown): void {
  const item = object(value, ["wallSeconds", "runnerMaxSeconds", "calls", "workers", "concurrency", "tokens", "currency"]);
  literal(item.wallSeconds, [630]); literal(item.runnerMaxSeconds, [600]);
  for (const key of ["calls", "workers", "concurrency"]) literal(item[key], ["caller-discipline"]);
  for (const key of ["tokens", "currency"]) literal(item[key], ["unsupported"]);
}
function record(value: unknown): void {
  const item = object(value, ["schemaVersion", "coreVersion", "issuedAt", "expiresAt", "declarationSha256", "configSha256", "invocationSha256", "factsSha256", "scopeSha256", "recordSha256", "declaration", "config", "facts", "scope", "capabilities"]);
  literal(item.schemaVersion, [SCHEMA_VERSION]); literal(item.coreVersion, [CORE_VERSION]); interval(item.issuedAt, item.expiresAt);
  for (const key of ["declarationSha256", "configSha256", "invocationSha256", "factsSha256", "scopeSha256", "recordSha256"]) digest(item[key]);
  declaration(item.declaration); config(item.config); facts(item.facts); capabilities(item.capabilities);
  const scope = object(item.scope, ["runId", "purpose", "accountFingerprint", "authorization", "invocation"]);
  text(scope.runId); text(scope.accountFingerprint); literal(scope.purpose, ["synthetic-local-sentinel", "managed"]); authorization(scope.authorization); invocation(scope.invocation);
  const typed = value as AdmissionRecord;
  if (typed.declarationSha256 !== typed.facts.declaration.sha256 || typed.configSha256 !== typed.facts.config.sha256
    || typed.configSha256 !== typed.declaration.configSha256 || typed.scope.runId !== typed.declaration.runId
    || typed.scope.purpose !== typed.declaration.purpose || typed.scope.accountFingerprint !== typed.facts.identity.accountFingerprint
    || canonicalJson(typed.scope.invocation) !== canonicalJson(typed.declaration.invocation)
    || !typed.declaration.authorizations.some((auth) => canonicalJson(auth) === canonicalJson(typed.scope.authorization))
    || timestamp(typed.expiresAt) > Math.min(...[typed.declaration.expiresAt, typed.facts.identity.expiresAt, typed.declaration.quota.expiresAt, typed.scope.authorization.expiresAt].map(timestamp))) fail();
}
export function parseRecord(value: unknown): AdmissionRecord { record(value); return copy(value); }
export function parseResponse(value: unknown): Response {
  const item = object(value, ["schemaVersion", "coreVersion", "status", "reasons", "quota", "admission", "admitted"]);
  literal(item.schemaVersion, [SCHEMA_VERSION]); literal(item.coreVersion, [CORE_VERSION]); literal(item.status, ["ready", "blocked", "unknown"]);
  array(item.reasons, (reason) => text(reason, 512), 0, 128); bool(item.admitted);
  if (item.quota !== null) quota(item.quota);
  if (item.admission !== null) record(item.admission);
  if ((item.status === "blocked" && (item.admission !== null || item.admitted)) || (item.admitted && item.admission === null) || (item.status === "ready" && ((item.quota as Quota | null)?.status !== "observed" || item.admission === null)) || (item.status === "unknown" && (item.quota as Quota | null)?.status !== "unknown")) fail();
  const typed = value as Response;
  if (typed.admission !== null && canonicalJson(typed.quota) !== canonicalJson(typed.admission.declaration.quota)) fail();
  return copy(value);
}
export function parseBridgeResult(value: unknown): BridgeResult {
  const item = object(value, ["schemaVersion", "coreVersion", "status", "managedSpawns", "providerCalls", "reasons"]);
  literal(item.schemaVersion, [SCHEMA_VERSION]); literal(item.coreVersion, [CORE_VERSION]); literal(item.status, ["terminal-receipt-unavailable", "blocked"]);
  literal(item.providerCalls, [0]); literal(item.managedSpawns, item.status === "blocked" ? [0] : [1]);
  array(item.reasons, (reason) => { text(reason, 128); if (!/^[a-z0-9][a-z0-9-]*$/.test(reason)) fail(); }, 1, 128);
  return copy(value);
}
export function parseProbeResponse(value: unknown): ProbeResponse {
  const item = object(value, ["schemaVersion", "coreVersion", "status", "reasons", "quota", "admission", "admitted", "probe"]);
  const { probe, ...response } = item;
  parseResponse(response);
  if (probe !== null) parseBridgeResult(probe);
  if (item.admitted || (probe !== null && (probe as BridgeResult).status === "blocked" && item.status !== "blocked")
    || (probe !== null && (probe as BridgeResult).status === "terminal-receipt-unavailable" && (item.status !== "unknown" || (item.admission as AdmissionRecord | null)?.scope.purpose !== "synthetic-local-sentinel"))) fail();
  return copy(value);
}
