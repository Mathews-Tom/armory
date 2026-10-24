import { afterEach, expect, test } from "bun:test";
import { admit, check, parseBridgeResult, parseConfig, parseDeclaration, parseIdentity, parseInvocation, parseProbeResponse, parseRecord, parseResponse, ValidationError } from "../core/index.ts";
import type { Observation, ProjectConfig } from "../core/index.ts";
import { parseFacts } from "../core/validation.ts";
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

// The hook is inherited so the caller's own wire-schema keys remain unchanged.
function projected<T extends object>(value: T, projection: () => unknown): T {
  return Object.assign(Object.create({ toJSON: projection }), value) as T;
}

const parsers = [
  ["invocation", parseInvocation], ["config", parseConfig], ["identity", parseIdentity],
  ["declaration", parseDeclaration], ["facts", parseFacts], ["record", parseRecord],
  ["response", parseResponse], ["bridge", parseBridgeResult], ["probe", parseProbeResponse],
] as const;

async function documents(): Promise<Record<typeof parsers[number][0], object>> {
  const { value, observation } = await observed();
  const response = check(observation, value.now, sha256);
  return {
    invocation: observation.declaration.invocation, config: observation.config,
    identity: observation.facts.identity, declaration: observation.declaration, facts: observation.facts,
    record: requireAdmission(response), response,
    bridge: { schemaVersion: 1, coreVersion: "1.0.0", status: "blocked", managedSpawns: 0, providerCalls: 0, reasons: ["fixture-blocked"] },
    probe: { ...response, probe: null },
  };
}

for (const [name, parse] of parsers) {
  test(`${name} parser rejects an inherited toJSON projection outside its schema`, async () => {
    const document = (await documents())[name];
    expect(() => parse(projected(document, () => ({ ...document, unexpected: true })))).toThrow(ValidationError);
  });

}

for (const failure of ["cycle", "bigint"] as const) {
  test(`parser normalizes ${failure} snapshot failure to ValidationError`, async () => {
    const document = (await documents()).config;
    const cycle: { self?: unknown } = {};
    cycle.self = cycle;
    expect(() => parseConfig(projected(document, () => failure === "cycle" ? cycle : 1n))).toThrow(ValidationError);
  });
}

test("config parser validates the getter projection it actually returns", async () => {
  const { observation } = await observed();
  let reads = 0;
  const config = { ...observation.config };
  Object.defineProperty(config, "schemaVersion", { enumerable: true, get: () => ++reads === 1 ? 1 : 999 });
  // Either a single valid snapshot or a validation refusal is safe; returning an
  // invalid frozen config after validating an earlier getter value is not.
  let parsed: ProjectConfig;
  try { parsed = parseConfig(config); } catch (error) {
    expect(error).toBeInstanceOf(ValidationError);
    return;
  }
  expect(parsed.schemaVersion).toBe(1);
  expect(Object.isFrozen(parsed)).toBe(true);
});

test("check refuses a declaration whose inherited projection adds unvalidated authority fields", async () => {
  const { value, observation } = await observed();
  const declaration = projected(observation.declaration, () => ({ ...observation.declaration, unexpectedAuthority: true }));
  expect(() => check({ ...observation, declaration }, value.now, sha256)).toThrow(ValidationError);
});

test("admit cannot admit an inherited record projection containing unvalidated fields", async () => {
  const { value, observation } = await observed();
  const record = requireAdmission(check(observation, value.now, sha256));
  const supplied = projected(record, () => ({ ...record, unexpectedAuthority: true }));
  const result = admit(observation, supplied, observation.declaration.invocation, value.now, sha256);
  expect(result.admitted).toBe(false);
  expect(result.admission).toBeNull();
});
