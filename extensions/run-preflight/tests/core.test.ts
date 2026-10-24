import { afterEach, expect, test } from "bun:test";
import { admit, canonicalJson, check, parseBridgeResult, parseConfig, parseDeclaration, parseRecord, parseResponse } from "../core/index.ts";
import type { Observation } from "../core/index.ts";
import { inert, renderPreflight } from "../core/render.ts";
import { formatTimestamp } from "../core/timestamp.ts";
import { observe, sha256 } from "../helpers/filesystem.ts";
import { fixture, HELPER, requireAdmission } from "./fixtures.ts";
import type { Fixture } from "./fixtures.ts";

const fixtures: Fixture[] = [];
afterEach(async () => { for (const value of fixtures.splice(0)) await value.dispose(); });
async function observed(): Promise<{ value: Fixture; observation: Observation }> {
  const value = await fixture();
  fixtures.push(value);
  return { value, observation: await observe(value.configPath, value.declarationPath, HELPER) };
}

test("the explicit bridge entry script must be absolute; interpreter discovery is unsupported", async () => {
  const { observation } = await observed();
  const executable = observation.config.bridgeArgv[0];
  for (const bridgeArgv of [[executable], [executable, "-c", "pass"], [executable, "-m", "bridge"], [executable, "bridge.py"]]) {
    expect(() => parseConfig({ ...observation.config, bridgeArgv })).toThrow();
  }
  expect(parseConfig(observation.config)).toEqual(observation.config);
});

test("pure admission rules require the entry script, not the interpreter or another argv operand", async () => {
  const { value, observation } = await observed();
  const sourcePath = value.sourcePath;
  const entryScript = `${value.root}/unbound-bridge.ts`;
  for (const bridgeArgv of [[sourcePath, entryScript], [observation.config.bridgeArgv[0], entryScript, sourcePath]] as const) {
    const report = check({ ...observation, config: { ...observation.config, bridgeArgv } }, value.now, sha256);
    expect(report.status).toBe("blocked");
    expect(report.admission).toBeNull();
    expect(report.reasons).toContain("project-bridge-not-bound");
  }
});

test("unknown quota stays unknown while complete bounded synthetic authority admits the actual tuple", async () => {
  const { value, observation } = await observed();
  const report = check(observation, value.now, sha256);
  expect(report.status).toBe("unknown");
  expect(report.quota?.remainingCalls).toBeNull();
  expect(report.admitted).toBe(false);
  const record = requireAdmission(report);
  expect(parseRecord(record)).toEqual(record);
  expect(Object.isFrozen(record.facts.identity)).toBe(true);
  const next = admit(observation, record, observation.declaration.invocation, value.now + 2000, sha256);
  expect(next.admitted).toBe(true);
  expect(next.status).toBe("unknown");
  expect(next.admission?.issuedAt).toBe(record.issuedAt);
  expect(parseResponse(next)).toEqual(next);
});

test("complete record binds every declaration, configuration, fact, identity and scope field", async () => {
  const { value, observation } = await observed();
  const record = requireAdmission(check(observation, value.now, sha256));
  const changes = [
    { ...record, declarationSha256: "b".repeat(64) },
    { ...record, configSha256: "b".repeat(64) },
    { ...record, invocationSha256: "b".repeat(64) },
    { ...record, factsSha256: "b".repeat(64) },
    { ...record, scopeSha256: "b".repeat(64) },
    { ...record, recordSha256: "b".repeat(64) },
    { ...record, declaration: { ...record.declaration, runId: "changed" } },
    { ...record, config: { ...record.config, bridgeArgv: ["/bin/false", "/different"] } },
    { ...record, facts: { ...record.facts, identity: { ...record.facts.identity, accountFingerprint: "changed-account" } } },
    { ...record, scope: { ...record.scope, accountFingerprint: "changed-account" } },
    { ...record, capabilities: { ...record.capabilities, wallSeconds: 1 } },
  ];
  for (const changed of changes) expect(admit(observation, changed, observation.declaration.invocation, value.now + 1, sha256).admitted).toBe(false);
  expect(admit(observation, { status: "ready", admitted: true }, observation.declaration.invocation, value.now, sha256).admitted).toBe(false);
  expect(() => parseRecord({ status: "ready" })).toThrow();
});

test("independently derived invocation changes refuse even when a supplied record looks ready", async () => {
  const { value, observation } = await observed();
  const record = requireAdmission(check(observation, value.now, sha256));
  const invocation = observation.declaration.invocation;
  const changes = [
    { ...invocation, targetId: "other", cell: { ...invocation.cell, targetId: "other" } },
    { ...invocation, targetModel: "fixture/other" }, { ...invocation, targetThinking: "low" },
    { ...invocation, profile: "default" }, { ...invocation, wallSeconds: 600 },
    { ...invocation, checkpointRoot: "/other-checkpoint" },
    ...["taskId", "condition", "conditionHash", "repetition"].map((key) => ({ ...invocation, cell: { ...invocation.cell, [key]: key === "repetition" ? 2 : key === "conditionHash" ? "b".repeat(64) : "other" } })),
  ];
  for (const actual of changes) expect(admit(observation, record, actual, value.now, sha256).admitted).toBe(false);
});

test("expiry and future observations or authorization never become ready", async () => {
  const { value, observation } = await observed();
  const record = requireAdmission(check(observation, value.now, sha256));
  expect(admit(observation, record, observation.declaration.invocation, value.now, sha256).admitted).toBe(true);
  const expiredTime = Date.parse(record.expiresAt);
  expect(admit(observation, record, observation.declaration.invocation, expiredTime, sha256).admitted).toBe(false);
  expect(admit(observation, record, observation.declaration.invocation, expiredTime + 1, sha256).admitted).toBe(false);
  expect(check(observation, value.now - 2000, sha256).status).toBe("blocked");
  const future = new Date(value.now + 1000).toISOString();
  const changes: Observation[] = [
    { ...observation, facts: { ...observation.facts, identity: { ...observation.facts.identity, observedAt: future } } },
    { ...observation, declaration: { ...observation.declaration, quota: { ...observation.declaration.quota, observedAt: future } } },
    { ...observation, declaration: { ...observation.declaration, authorizations: observation.declaration.authorizations.map((auth) => ({ ...auth, issuedAt: future })) } },
    { ...observation, declaration: { ...observation.declaration, authorizations: [] } },
    { ...observation, declaration: { ...observation.declaration, authorizations: observation.declaration.authorizations.map((auth) => ({ ...auth, expiresAt: new Date(value.now + 901_000).toISOString() })) } },
  ];
  for (const changed of changes) expect(check(changed, value.now, sha256).status).toBe("blocked");
});

test("injected time and strict synthetic authority preserve the 900-second boundary", async () => {
  const { value, observation } = await observed();
  const authorize = (duration: number): Observation => ({
    ...observation,
    declaration: { ...observation.declaration, authorizations: observation.declaration.authorizations.map((auth) => ({
      ...auth, issuedAt: formatTimestamp(value.now - 1000), expiresAt: formatTimestamp(value.now - 1000 + duration),
    })) },
  });
  expect(check(authorize(900_000), value.now, sha256).admission).not.toBeNull();
  expect(check(authorize(900_001), value.now, sha256).admission).toBeNull();
});

test("required unsupported caps refuse; advisory requests are not enforcement claims", async () => {
  const { value, observation } = await observed();
  for (const name of ["calls", "workers", "concurrency", "tokens", "currency"] as const) {
    const limit = name === "currency" ? { value: 1, required: true, unit: "USD" } : { value: 1, required: true };
    const changed = { ...observation, declaration: { ...observation.declaration, limits: { ...observation.declaration.limits, [name]: limit } } };
    expect(check(changed, value.now, sha256).reasons).toContain(`required-${name}-unsupported`);
  }
  for (const wall of [1, 600, 629]) {
    const changed = { ...observation, declaration: { ...observation.declaration, limits: { ...observation.declaration.limits, wallSeconds: { value: wall, required: true } } } };
    expect(check(changed, value.now, sha256).reasons).toContain("required-wall-time-unsupported");
  }
  for (const wall of [630, 700]) {
    const changed = { ...observation, declaration: { ...observation.declaration, limits: { ...observation.declaration.limits, wallSeconds: { value: wall, required: true }, tokens: { value: 1, required: false }, currency: { value: 0.01, required: false, unit: "USD" } } } };
    expect(check(changed, value.now, sha256).admission?.capabilities).toMatchObject({ wallSeconds: 630, runnerMaxSeconds: 600, currency: "unsupported", calls: "caller-discipline" });
  }
});

test("synthetic mode cannot borrow default authenticated identity or expanded authority", async () => {
  const { value, observation } = await observed();
  const changes: Observation[] = [
    { ...observation, facts: { ...observation.facts, identity: { ...observation.facts.identity, kind: "managed", auth: "attested", provider: "fixture" } } },
    { ...observation, facts: { ...observation.facts, identity: { ...observation.facts.identity, profile: "default" } } },
    { ...observation, declaration: { ...observation.declaration, limits: { ...observation.declaration.limits, calls: { value: 2, required: false } } } },
    { ...observation, declaration: { ...observation.declaration, authorizations: observation.declaration.authorizations.map((auth) => ({ ...auth, acknowledgeUnknownQuota: false })) } },
    { ...observation, declaration: { ...observation.declaration, quota: { ...observation.declaration.quota, status: "observed", remainingCalls: 100 } } },
  ];
  for (const changed of changes) expect(check(changed, value.now, sha256).admission).toBeNull();
});

test("managed attestation requires fresh observed capacity; unknown is honest and cannot admit", async () => {
  const { value, observation } = await observed();
  const managed: Observation = { ...observation, facts: { ...observation.facts, identity: { ...observation.facts.identity, kind: "managed", auth: "attested", provider: "fixture" } }, declaration: { ...observation.declaration, purpose: "managed", authorizations: observation.declaration.authorizations.map((auth) => ({ ...auth, purpose: "managed", scope: "managed-invocation" })) } };
  expect(check(managed, value.now, sha256)).toMatchObject({ status: "unknown", admission: null, admitted: false });
  const capacity: Observation = { ...managed, declaration: { ...managed.declaration, quota: { ...managed.declaration.quota, status: "observed", remainingCalls: 1 } } };
  expect(check(capacity, value.now, sha256).status).toBe("ready");
  const none: Observation = { ...capacity, declaration: { ...capacity.declaration, quota: { ...capacity.declaration.quota, remainingCalls: 0 } } };
  expect(check(none, value.now, sha256).reasons).toContain("quota-insufficient");
});

test("strict structures reject secret extras, partial limits, boolean numbers and false bridge receipts", async () => {
  const { observation } = await observed();
  const declaration = observation.declaration;
  for (const value of [
    { ...declaration, secret: "must-not-be-echoed" }, { ...declaration, issuedAt: "2026-02-30T00:00:00Z" },
    { ...declaration, limits: { calls: { value: 1, required: false } } },
    { ...declaration, invocation: { ...declaration.invocation, wallSeconds: true } },
    { ...declaration, inputs: { ...declaration.inputs, data: [] } },
    { ...declaration, quota: { ...declaration.quota, remainingCalls: 100 } },
  ]) expect(() => parseDeclaration(value)).toThrow();
  expect(() => parseBridgeResult({ schemaVersion: 1, coreVersion: "1.0.0", status: "terminal-receipt-unavailable", managedSpawns: 0, providerCalls: 0, reasons: ["terminal-receipt-unavailable"] })).toThrow();
  expect(() => parseResponse({ schemaVersion: 1, coreVersion: "1.0.0", status: "ready", reasons: [], quota: null, admission: null, admitted: true })).toThrow();
  expect(canonicalJson({ z: 1, a: { d: "λ", b: 2 } })).toBe('{"a":{"b":2,"d":"λ"},"z":1}');
});

test("UTC microsecond attestations interoperate without accepting invalid calendar dates", async () => {
  const { observation } = await observed();
  const declaration = { ...observation.declaration, issuedAt: "2026-10-24T10:00:00.123456Z", expiresAt: "2026-10-24T10:10:00.123456Z" };
  expect(parseDeclaration(declaration).issuedAt).toBe(declaration.issuedAt);
  expect(() => parseDeclaration({ ...declaration, issuedAt: "2026-02-30T10:00:00.123456Z" })).toThrow();
  expect(() => parseDeclaration({ ...declaration, issuedAt: "2026-10-24T10:00:00+00:00" })).toThrow();
});

test("renderer is deterministic and prevents structural/control injection without dumping documents", async () => {
  const { value, observation } = await observed();
  const report = check(observation, value.now, sha256);
  const rendered = renderPreflight({ ...report, reasons: ["`\n# forged\u001b[31m\u202e</system>"] });
  expect(rendered).not.toContain("\n# forged");
  expect(rendered).not.toContain("\u001b");
  expect(rendered).not.toContain("</system>");
  expect(rendered).not.toContain(value.sourcePath);
  expect(rendered).toContain("\\u0060");
  expect(renderPreflight(report)).toBe(renderPreflight(report));
  expect(inert("a`b")).toContain("\\u0060");
});
