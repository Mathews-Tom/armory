import { afterEach, expect, test } from "bun:test";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { runBridge } from "../helpers/bridge.ts";
import type { ProjectConfig } from "../core/index.ts";
import { fixture } from "./fixtures.ts";
import type { Fixture } from "./fixtures.ts";

const fixtures: Fixture[] = [];
afterEach(async () => { for (const value of fixtures.splice(0)) await value.dispose(); });
async function selected(body: string): Promise<Fixture> {
  const value = await fixture(body);
  fixtures.push(value);
  return value;
}

test("trusted argv stays literal, receives explicit file flags and is not interpreted by a shell", async () => {
  const value = await selected(`import { writeFileSync } from "node:fs";
writeFileSync(process.argv[2]!, JSON.stringify(process.argv.slice(3)));
process.stdout.write(JSON.stringify({schemaVersion:1,coreVersion:"1.0.0",status:"blocked",managedSpawns:0,providerCalls:0,reasons:["admission-refused"]}));`);
  const argsFile = join(value.root, "argv.json");
  const shellMarker = join(value.root, "must-not-exist");
  const literal = `; touch ${shellMarker}`;
  const config: ProjectConfig = { ...value.config, bridgeArgv: [...value.config.bridgeArgv, argsFile, literal] };
  const result = await runBridge(config, value.configPath, value.declarationPath);
  expect(result.result).toMatchObject({ status: "blocked", managedSpawns: 0, providerCalls: 0 });
  expect(JSON.parse(await readFile(argsFile, "utf8"))).toEqual([literal, "--config", value.configPath, "--declaration", value.declarationPath]);
  await expect(readFile(shellMarker)).rejects.toThrow();
});

for (const [body, reason] of [
  ['process.stdout.write("not JSON");', "bridge-response-malformed"],
  ['process.stdout.write(JSON.stringify({ready:true}));', "bridge-response-malformed"],
  ['process.stderr.write("private-provider-text"); process.exit(8);', "bridge-nonzero-exit"],
  ['process.stdout.write("x".repeat(70*1024));', "bridge-output-too-large"],
  ['process.stderr.write("x".repeat(70*1024));', "bridge-output-too-large"],
  ['process.stdout.write(JSON.stringify({schemaVersion:1,coreVersion:"1.0.0",status:"terminal-receipt-unavailable",managedSpawns:1,providerCalls:1,reasons:["terminal-receipt-unavailable"]}));', "bridge-response-malformed"],
  ['process.stdout.write(JSON.stringify({schemaVersion:1,coreVersion:"1.0.0",status:"terminal-receipt-unavailable",managedSpawns:0,providerCalls:0,reasons:["terminal-receipt-unavailable"]}));', "bridge-response-malformed"],
] as const) {
  test(`bridge transport refuses ${reason} without exposing process output`, async () => {
    const value = await selected(body);
    const result = await runBridge(value.config, value.configPath, value.declarationPath);
    expect(result).toEqual({ result: null, reason });
    expect(JSON.stringify(result)).not.toContain("private-provider-text");
  });
}

test("missing trusted executable is an explicit start failure", async () => {
  const value = await selected("");
  const result = await runBridge({ ...value.config, bridgeArgv: [join(value.root, "not-a-program"), value.sourcePath] }, value.configPath, value.declarationPath);
  expect(result).toEqual({ result: null, reason: "bridge-start-failed" });
});

// Deliberate platform-clock/process integration: fake timers cannot drive a
// separate TERM-resistant child or prove real process-group timeout handling.
test("timeout kills a real TERM-resistant bridge process and returns a bounded refusal", async () => {
  const value = await selected('process.on("SIGTERM", () => {}); setInterval(() => {}, 1000);');
  const started = Date.now();
  const result = await runBridge(value.config, value.configPath, value.declarationPath, undefined, 100);
  expect(result).toEqual({ result: null, reason: "bridge-timeout" });
  expect(Date.now() - started).toBeLessThan(5000);
});

test("cancellation terminates an in-flight real process and pre-cancellation launches nothing", async () => {
  const value = await selected('setInterval(() => {}, 1000);');
  const controller = new AbortController();
  const pending = runBridge(value.config, value.configPath, value.declarationPath, controller.signal);
  controller.abort();
  expect(await pending).toEqual({ result: null, reason: "bridge-cancelled" });
  await writeFile(value.sourcePath, `import { writeFileSync } from "node:fs"; writeFileSync(${JSON.stringify(value.marker)}, "unexpected");`);
  expect(await runBridge(value.config, value.configPath, value.declarationPath, controller.signal)).toEqual({ result: null, reason: "bridge-cancelled" });
  await expect(readFile(value.marker)).rejects.toThrow();
});
