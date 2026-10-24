import { CORE_VERSION, RUNNER_GRACE_SECONDS, RUNNER_MAX_SECONDS, SCHEMA_VERSION, SYNTHETIC_AUTHORITY_SECONDS } from "./types.ts";
import type { AdmissionRecord, AdmissionScope, Authorization, Capabilities, FileBinding, FileFact, Hash, Invocation, Observation, Response } from "./types.ts";
import { freeze, parseConfig, parseDeclaration, parseFacts, parseInvocation, parseRecord, ValidationError } from "./validation.ts";
import { canonicalJson } from "./canonical.ts";
import { formatTimestamp, parseTimestamp } from "./timestamp.ts";
export * from "./types.ts";
export { canonicalJson } from "./canonical.ts";
export { parseBridgeResult, parseConfig, parseDeclaration, parseIdentity, parseInvocation, parseProbeResponse, parseRecord, parseResponse, ValidationError } from "./validation.ts";

export const CAPABILITIES: Capabilities = freeze({
  runnerMaxSeconds: RUNNER_MAX_SECONDS, wallSeconds: RUNNER_MAX_SECONDS + RUNNER_GRACE_SECONDS,
  calls: "caller-discipline", workers: "caller-discipline", concurrency: "caller-discipline", tokens: "unsupported", currency: "unsupported",
});
export function refusal(reasons: readonly string[]): Response {
  return freeze({ schemaVersion: SCHEMA_VERSION, coreVersion: CORE_VERSION, status: "blocked", reasons: [...reasons], quota: null, admission: null, admitted: false });
}
function timestampMs(value: string): number {
  const result = parseTimestamp(value);
  if (result === null) throw new ValidationError();
  return result;
}
function current(start: string, end: string, nowMs: number): boolean { return timestampMs(start) <= nowMs && nowMs < timestampMs(end); }
function sameBindings(bindings: readonly FileBinding[], facts: readonly FileFact[]): boolean {
  return bindings.length === facts.length && bindings.every((binding, index) => binding.path === facts[index]?.path && binding.sha256 === facts[index]?.sha256);
}
function recordBody(record: AdmissionRecord): Omit<AdmissionRecord, "recordSha256"> {
  return {
    schemaVersion: record.schemaVersion, coreVersion: record.coreVersion, issuedAt: record.issuedAt, expiresAt: record.expiresAt,
    declarationSha256: record.declarationSha256, configSha256: record.configSha256, invocationSha256: record.invocationSha256,
    factsSha256: record.factsSha256, scopeSha256: record.scopeSha256, declaration: record.declaration,
    config: record.config, facts: record.facts, scope: record.scope, capabilities: record.capabilities,
  };
}
function selectedAuthorization(observation: Observation, nowMs: number, hash: Hash): Authorization | undefined {
  const { declaration, facts } = observation;
  return declaration.authorizations.find((item) => item.runId === declaration.runId
    && item.purpose === declaration.purpose
    && item.accountFingerprint === facts.identity.accountFingerprint
    && item.invocationSha256 === hash(canonicalJson(declaration.invocation))
    && current(item.issuedAt, item.expiresAt, nowMs)
    && (declaration.purpose === "synthetic-local-sentinel"
      ? item.scope === "local-sentinel-only" && item.acknowledgeUnknownQuota
        && timestampMs(item.expiresAt) - timestampMs(item.issuedAt) <= SYNTHETIC_AUTHORITY_SECONDS * 1000
      : item.scope === "managed-invocation"));
}
/** Pure evaluation. All observations, evaluation time and hashing are explicit inputs. */
export function check(input: Observation, nowMs: number, hash: Hash): Response {
  const observation = freeze({ config: parseConfig(input.config), declaration: parseDeclaration(input.declaration), facts: parseFacts(input.facts) });
  const { config, declaration, facts } = observation;
  const { invocation, limits, quota } = declaration;
  const problems: string[] = [];
  if (!Number.isFinite(nowMs) || !current(declaration.issuedAt, declaration.expiresAt, nowMs)) problems.push("declaration-not-current");
  if (!current(facts.identity.observedAt, facts.identity.expiresAt, nowMs)) problems.push("identity-not-current");
  if (!current(quota.observedAt, quota.expiresAt, nowMs)) problems.push("quota-not-current");
  if (declaration.configSha256 !== facts.config.sha256) problems.push("config-digest-mismatch");
  if (!sameBindings(declaration.inputs.source, facts.source) || !sameBindings(declaration.inputs.config, facts.configs) || !sameBindings(declaration.inputs.data, facts.data)
    || !sameBindings([declaration.inputs.identity], [facts.identityFile])) problems.push("input-binding-mismatch");
  if (!declaration.inputs.config.some((file) => file.path === facts.config.path && file.sha256 === facts.config.sha256)
    || !declaration.inputs.config.some((file) => file.path === config.contractPath)) problems.push("config-or-contract-not-bound");
  if (!declaration.inputs.source.some((file) => file.path === config.bridgeArgv[1])) problems.push("project-bridge-not-bound");
  if (facts.projectRoot.path !== config.projectRoot || facts.packageRoot.path !== config.packageRoot || facts.helper.path !== `${config.packageRoot}/${config.helperPath}`) problems.push("configured-path-mismatch");
  if (declaration.checkpoint.path !== invocation.checkpointRoot || facts.checkpoint.path !== invocation.checkpointRoot || !facts.checkpoint.writable) problems.push("checkpoint-not-ready");
  if (invocation.wallSeconds !== CAPABILITIES.wallSeconds) problems.push("runner-timeout-mismatch");
  if (limits.wallSeconds.required && limits.wallSeconds.value < CAPABILITIES.wallSeconds) problems.push("required-wall-time-unsupported");
  for (const name of ["calls", "workers", "concurrency", "tokens", "currency"] as const) if (limits[name]?.required) problems.push(`required-${name}-unsupported`);
  if (facts.identity.profile !== invocation.profile) problems.push("identity-profile-mismatch");
  if (declaration.purpose === "synthetic-local-sentinel") {
    if (facts.identity.kind !== "synthetic-local" || facts.identity.auth !== "not-applicable" || facts.identity.provider !== "synthetic-local") problems.push("synthetic-identity-required");
    if (quota.status !== "unknown") problems.push("synthetic-quota-must-remain-unknown");
    if (limits.calls.value !== 1 || limits.workers.value !== 1 || limits.concurrency.value !== 1) problems.push("synthetic-scope-must-be-single-local-invocation");
  } else if (facts.identity.kind !== "managed" || facts.identity.auth !== "attested" || facts.identity.provider !== invocation.targetModel.split("/")[0]) problems.push("managed-identity-attestation-required");
  const authorization = selectedAuthorization(observation, nowMs, hash);
  if (authorization === undefined) problems.push("required-authorization-missing-or-not-current");
  if (quota.status === "observed" && (quota.remainingCalls === null || quota.remainingCalls < limits.calls.value)) problems.push("quota-insufficient");
  if (problems.length > 0) return freeze({ ...refusal(problems), quota });
  // Unknown never becomes capacity. Only the explicitly bounded, no-account synthetic
  // authority permits a local sentinel; managed unknown observations carry no admission.
  if (quota.status === "unknown" && declaration.purpose !== "synthetic-local-sentinel") {
    return freeze({ schemaVersion: SCHEMA_VERSION, coreVersion: CORE_VERSION, status: "unknown", reasons: ["quota-unknown", "managed-capacity-unavailable"], quota, admission: null, admitted: false });
  }
  if (authorization === undefined) throw new ValidationError();
  const scope: AdmissionScope = { runId: declaration.runId, purpose: declaration.purpose, accountFingerprint: facts.identity.accountFingerprint, authorization, invocation };
  const expiresAt = formatTimestamp(Math.min(...[declaration.expiresAt, facts.identity.expiresAt, quota.expiresAt, authorization.expiresAt].map(timestampMs)));
  const body: Omit<AdmissionRecord, "recordSha256"> = {
    schemaVersion: SCHEMA_VERSION, coreVersion: CORE_VERSION, issuedAt: formatTimestamp(nowMs), expiresAt,
    declarationSha256: facts.declaration.sha256, configSha256: facts.config.sha256,
    invocationSha256: hash(canonicalJson(invocation)), factsSha256: hash(canonicalJson(facts)), scopeSha256: hash(canonicalJson(scope)),
    declaration, config, facts, scope, capabilities: CAPABILITIES,
  };
  const admission = freeze({ ...body, recordSha256: hash(canonicalJson(body)) });
  return freeze({ schemaVersion: SCHEMA_VERSION, coreVersion: CORE_VERSION, status: quota.status === "unknown" ? "unknown" : "ready",
    reasons: quota.status === "unknown" ? ["quota-unknown", "bounded-synthetic-authority-only", "advisory-caps-are-caller-discipline"] : ["attested-prerequisites-current", "advisory-caps-are-caller-discipline"],
    quota, admission, admitted: false });
}
/** Rebuild prerequisites from current observations, then bind the actual consumer tuple. */
export function admit(input: Observation, recordValue: unknown, actualValue: unknown, nowMs: number, hash: Hash): Response {
  let record: AdmissionRecord;
  let actual: Invocation;
  try { record = parseRecord(recordValue); actual = parseInvocation(actualValue); } catch { return refusal(["admission-or-invocation-malformed"]); }
  const report = check(input, nowMs, hash);
  const expected = report.admission;
  if (expected === null) return report;
  const stale = !current(record.issuedAt, record.expiresAt, nowMs)
    || record.recordSha256 !== hash(canonicalJson(recordBody(record)))
    || record.declarationSha256 !== expected.declarationSha256 || record.configSha256 !== expected.configSha256
    || record.invocationSha256 !== hash(canonicalJson(actual)) || record.invocationSha256 !== expected.invocationSha256
    || record.factsSha256 !== expected.factsSha256 || record.scopeSha256 !== expected.scopeSha256
    || record.expiresAt !== expected.expiresAt
    || canonicalJson(record.declaration) !== canonicalJson(expected.declaration)
    || canonicalJson(record.config) !== canonicalJson(expected.config)
    || canonicalJson(record.facts) !== canonicalJson(expected.facts)
    || canonicalJson(record.scope) !== canonicalJson(expected.scope)
    || canonicalJson(record.capabilities) !== canonicalJson(CAPABILITIES);
  if (stale) return freeze({ ...refusal(["admission-expired-drifted-or-invalid"]), quota: report.quota });
  return freeze({ ...report, admission: record, admitted: true });
}
