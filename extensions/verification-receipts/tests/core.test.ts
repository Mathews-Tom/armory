import { describe, expect, test } from "bun:test";
import { CORE_VERSION, FEATURE, FEATURE_VERSION, FINGERPRINT_ALGORITHM, canonicalJson, compareSnapshots, executionApplicability, isSuccessfulProof } from "../core/index.ts";
import type { Configuration, Json, Receipt, Snapshot } from "../core/index.ts";
import { assertExecutionId, parseConfiguration, parsePendingRun, parseReceipt } from "../core/validation.ts";

const A = "a".repeat(64);
const B = "b".repeat(64);

function receipt(): Receipt {
  const before: Snapshot = {
    algorithm: FINGERPRINT_ALGORITHM, digest: A, observedAtMs: 100,
    entries: [{ path: "source.ts", kind: "file", executable: false, sha256: B }],
    environment: {}, configDigest: B, datasetIdentity: null,
  };
  return {
    schemaVersion: 1,
    plan: {
      schemaVersion: 1, feature: FEATURE, featureVersion: FEATURE_VERSION, coreVersion: CORE_VERSION,
      executionId: "00000000-0000-4000-8000-000000000001",
      repository: { repositoryId: A, repositoryRoot: "/synthetic/project", worktreeId: B, worktreeRoot: "/synthetic/worktree", revision: null, dirty: true },
      context: { host: "standalone", sessionId: "session", accountId: "synthetic", workContext: "work" },
      gateId: "unit", configId: "configured", configPath: "gates.json", configDigest: B,
      gate: { criterionId: "unit", kind: "unit", executable: "tool", args: [], cwd: ".", timeoutMs: 1000, maxOutputBytes: 1024, requiresCompleteOutput: true, scope: { paths: ["source.ts"], configPaths: [], environmentNames: [], datasetIdentity: null } },
      before, startedAtMs: 101,
    },
    result: { status: "passed", exitCode: 0, signal: null, reason: null, descendantsStopped: true },
    after: { ...before, observedAtMs: 102 },
    artifact: { file: "output.bin", sha256: A, capturedBytes: 0, totalBytes: 0, truncated: false },
    finishedAtMs: 103, durationMs: 1.5, applicability: "current", applicabilityReason: null,
  };
}

function configuration(): Configuration {
  return { schemaVersion: 1, configId: "configured", gates: { unit: receipt().plan.gate } };
}

describe("receipt truth", () => {
  test("execution change is unknown while later divergence is stale", () => {
    const success = receipt();
    const changed = { ...success.plan.before, digest: B };
    expect(executionApplicability(success.plan.before, changed)).toBe("unknown");
    expect(compareSnapshots(success.plan.before, changed)).toBe("stale");
    expect(isSuccessfulProof(success, changed)).toBe(false);
    expect(isSuccessfulProof(success, success.plan.before)).toBe(true);
    expect(isSuccessfulProof(success, null)).toBe(false);
  });

  test("historical versions remain readable without becoming current proof", () => {
    for (const key of ["featureVersion", "coreVersion"] as const) {
      const value = receipt();
      value.plan[key] = "0.0.0-historical";
      expect(parseReceipt(value)).toEqual(value);
      expect(isSuccessfulProof(value, value.plan.before)).toBe(false);
    }
  });

  test("non-success, unknown applicability and truncated required output never prove success", () => {
    for (const status of ["failed", "cancelled", "incomplete"] as const) {
      const value = receipt();
      value.result.status = status;
      expect(isSuccessfulProof(value, value.plan.before)).toBe(false);
    }
    const value = receipt();
    value.applicability = "unknown";
    expect(isSuccessfulProof(value, value.plan.before)).toBe(false);
    value.applicability = "current";
    value.artifact.truncated = true;
    expect(isSuccessfulProof(value, value.plan.before)).toBe(false);
    value.artifact.truncated = null;
    expect(isSuccessfulProof(value, value.plan.before)).toBe(false);
    value.artifact.truncated = false;
    value.result.descendantsStopped = false;
    expect(isSuccessfulProof(value, value.plan.before)).toBe(false);
  });

  test("parser rejects positive assertions contradicted by the envelope", () => {
    const noExit = receipt();
    noExit.result.exitCode = null;
    expect(() => parseReceipt(noExit)).toThrow();
    const noSnapshot = receipt();
    noSnapshot.after = null;
    expect(() => parseReceipt(noSnapshot)).toThrow();
    const changed = receipt();
    if (changed.after !== null) changed.after.digest = B;
    expect(() => parseReceipt(changed)).toThrow();
    const overCapture = receipt();
    overCapture.artifact.capturedBytes = overCapture.plan.gate.maxOutputBytes + 1;
    expect(() => parseReceipt(overCapture)).toThrow();
    const fakeTruncation = receipt();
    fakeTruncation.artifact.truncated = true;
    expect(() => parseReceipt(fakeTruncation)).toThrow();
  });

  test("interrupted output counters remain unknown rather than invented", () => {
    const value = receipt();
    value.result = { status: "incomplete", exitCode: null, signal: null, reason: "owner-interrupted", descendantsStopped: false };
    value.after = null;
    value.applicability = "unknown";
    value.applicabilityReason = "owner-interrupted";
    value.artifact.totalBytes = null;
    value.artifact.truncated = null;
    expect(parseReceipt(value).artifact.totalBytes).toBeNull();
    expect(isSuccessfulProof(value, value.plan.before)).toBe(false);
    value.result.status = "passed";
    expect(() => parseReceipt(value)).toThrow();
  });
});

describe("untrusted data boundaries", () => {
  test("unknown schemas, unknown fields and foreign artifact paths are rejected", () => {
    expect(() => parseReceipt({ ...receipt(), schemaVersion: 2 })).toThrow();
    expect(() => parseReceipt({ ...receipt(), arbitrary: true })).toThrow();
    const value = receipt();
    expect(() => parseReceipt({ ...value, artifact: { ...value.artifact, file: "../../foreign" } })).toThrow();
    expect(() => parsePendingRun({ schemaVersion: 2, ownerPid: 10, plan: value.plan })).toThrow();
    expect(() => assertExecutionId("../foreign")).toThrow();
  });

  test("configuration rejects escaping paths, unbounded execution and plaintext environment", () => {
    for (const invalid of [
      { ...receipt().plan.gate, cwd: "../foreign" },
      { ...receipt().plan.gate, timeoutMs: 0 },
      { ...receipt().plan.gate, maxOutputBytes: 16 * 1024 * 1024 + 1 },
      { ...receipt().plan.gate, scope: { ...receipt().plan.gate.scope, environment: { TOKEN: "value" } } },
    ]) expect(() => parseConfiguration({ ...configuration(), gates: { unit: invalid } })).toThrow();
    expect(() => parseConfiguration({ ...configuration(), schemaVersion: 2 })).toThrow();
  });

  test("canonical JSON preserves null and rejects undefined instead of changing evidence", () => {
    expect(canonicalJson({ z: null, a: [true, 2] })).toBe('{"a":[true,2],"z":null}');
    expect(() => canonicalJson({ absent: undefined } as unknown as Json)).toThrow();
    expect(() => canonicalJson([undefined] as unknown as Json)).toThrow();
    expect(() => canonicalJson(new Array<Json>(1))).toThrow();
    expect(() => canonicalJson(Number.NaN)).toThrow();
  });
});
