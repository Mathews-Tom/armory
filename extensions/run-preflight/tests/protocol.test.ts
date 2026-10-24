import { afterAll, beforeAll, expect, test } from "bun:test";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { admit, check, parseDeclaration, refusal } from "../core/index.ts";
import type { BridgeResult, Observation, ProjectConfig, Response } from "../core/index.ts";
import { COMMAND, parseCommand, parseHelperAnswer, projectAnswer, renderAnswer } from "../core/protocol.ts";
import type { RunCommand } from "../core/protocol.ts";
import { observe, sha256 } from "../helpers/filesystem.ts";
import { fixture, HELPER, requireAdmission } from "./fixtures.ts";
import type { Fixture } from "./fixtures.ts";

let selected: Fixture;
let packageRoot: string;
let observation: Observation;
let report: Response;
let command: RunCommand;
let now: number;

beforeAll(async () => {
  selected = await fixture();
  packageRoot = join(selected.root, "detached package");
  const helpers = join(packageRoot, "helpers");
  await mkdir(helpers, { recursive: true });
  const entry = join(selected.root, "bundle-entry.ts");
  await writeFile(entry, `export * from ${JSON.stringify(HELPER)};\n`);
  const built = await Bun.build({ entrypoints: [entry], target: "bun", outdir: helpers, naming: "cli.js" });
  if (!built.success) throw new Error(`native protocol fixture helper build failed: ${built.logs.join("\n")}`);
  const config: ProjectConfig = { ...selected.config, packageRoot, helperPath: "helpers/cli.js" };
  const content = JSON.stringify(config);
  await writeFile(selected.configPath, content);
  const configSha256 = sha256(content);
  const declaration = parseDeclaration({ ...selected.declaration, configSha256,
    inputs: { ...selected.declaration.inputs, config: selected.declaration.inputs.config.map((file) =>
      file.path === selected.configPath ? { path: file.path, sha256: configSha256 } : file) } });
  await writeFile(selected.declarationPath, JSON.stringify(declaration));
  observation = await observe(selected.configPath, selected.declarationPath, join(helpers, "cli.js"));
  now = Date.now();
  report = check(observation, now, sha256);
  const parsed = parseCommand(`check ${JSON.stringify({ config: selected.configPath, declaration: selected.declarationPath })} --json`);
  if (parsed.action === "help") throw new Error("explicit check parsed as help");
  command = parsed;
});
afterAll(async () => { await selected?.dispose(); });

function run(args: string): RunCommand {
  const value = parseCommand(args);
  if (value.action === "help") throw new Error("expected run command");
  return value;
}

test("bundled helper executes the selected check and binds its actual installed file", () => {
  const child = Bun.spawnSync(["bun", join(packageRoot, "helpers/cli.js"), "check", "--config", selected.configPath,
    "--declaration", selected.declarationPath, "--format", "json"], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
  expect(child.exitCode).toBe(0);
  const actual = parseHelperAnswer(JSON.parse(new TextDecoder().decode(child.stdout)), command, packageRoot, Date.now(), child.exitCode);
  expect(actual.status).toBe("unknown");
  expect(actual.quota?.status).toBe("unknown");
  expect(actual.admitted).toBe(false);
  const record = requireAdmission(actual);
  expect(record.facts.helper.realPath).toBe(join(packageRoot, "helpers/cli.js"));
  expect(record.facts.config.realPath).toBe(selected.configPath);
  expect(record.scope.runId).toBe(selected.declaration.runId);
});

test("installed OMP default adapter executes its sibling packaged helper", async () => {
  const adapterRoot = join(packageRoot, "omp");
  await mkdir(adapterRoot);
  const built = await Bun.build({ entrypoints: [fileURLToPath(new URL("../omp/index.ts", import.meta.url))],
    target: "bun", outdir: adapterRoot, naming: "index.ts" });
  if (!built.success) throw new Error(`installed OMP fixture build failed: ${built.logs.join("\n")}`);
  const adapter = await import(pathToFileURL(join(adapterRoot, "index.ts")).href) as { default: (pi: ExtensionAPI) => void };
  type Registered = Parameters<ExtensionAPI["registerCommand"]>[1];
  const commands = new Map<string, Registered>();
  const events = new Map<string, (event: unknown, ctx: ExtensionContext) => unknown>();
  const messages: { content: string }[] = [];
  const api = {
    getCommands: () => [...commands].map(([name, spec]) => ({ name, description: spec.description, source: "extension" })),
    registerCommand: (name: string, spec: Registered) => { commands.set(name, spec); },
    on: (event: string, listener: (event: unknown, ctx: ExtensionContext) => unknown) => { events.set(event, listener); },
    sendMessage: (message: { content: string }) => { messages.push(message); },
  };
  const ctx = { cwd: selected.root, sessionManager: { getSessionId: () => "installed-default-session" } } as unknown as ExtensionCommandContext;
  adapter.default(api as unknown as ExtensionAPI);
  await events.get("session_start")?.({}, ctx);
  const registered = commands.get(COMMAND);
  if (registered === undefined) throw new Error("installed command not registered");
  await registered.handler(`check ${JSON.stringify(command.selection)} --json`, ctx);
  const actual = JSON.parse(messages[0]?.content ?? "null");
  expect(actual.status).toBe("unknown");
  expect(actual.quota.status).toBe("unknown");
  expect(actual.admitted).toBe(false);
  expect(actual.selection).toEqual(command.selection);
  await events.get("session_shutdown")?.({}, ctx);
});

test("explicit JSON path selection preserves spaces and shell characters as data", () => {
  const selection = { config: "/tmp/a directory/$(not-a-command).json", declaration: "/tmp/a directory/declaration.json" };
  const parsed = run(`probe ${JSON.stringify(selection)} --json`);
  expect(parsed).toEqual({ action: "probe", selection, json: true });
});

test("native grammar refuses implicit dispatch, ambiguous selections and unsafe paths", () => {
  for (const args of [
    "", "probe", 'admit {"config":"/a","declaration":"/b"}',
    'check {"config":"relative","declaration":"/b"}',
    'check {"config":"/a/../x","declaration":"/b"}',
    'check {"config":"/a//x","declaration":"/b"}',
    'check {"config":"/a","declaration":"/a"}',
    'check {"config":"/a","declaration":"/b","extra":true}',
    'check {"config":"/a","declaration":"/b"} {}',
    'check {"config":"/a","declaration":"/b"} --json --json',
    `check ${JSON.stringify({ config: "/a\nforged", declaration: "/b" })}`,
  ]) expect(() => parseCommand(args)).toThrow();
});

test("a current own-package check stays unknown and is not consumed admission", () => {
  const parsed = parseHelperAnswer(report, command, packageRoot, now, 0);
  expect(parsed.status).toBe("unknown");
  expect(parsed.admitted).toBe(false);
  expect(parsed.admission?.scope.purpose).toBe("synthetic-local-sentinel");
});

test("another selected file or another installed package cannot reuse the report", () => {
  for (const selectedCommand of [
    { ...command, selection: { ...command.selection, config: "/another-config.json" } },
    { ...command, selection: { ...command.selection, declaration: "/another-declaration.json" } },
  ]) expect(() => parseHelperAnswer(report, selectedCommand, packageRoot, now, 0)).toThrow();
  expect(() => parseHelperAnswer(report, command, `${packageRoot}-other`, now, 0)).toThrow();
});

test("source-prefix helpers cannot masquerade as installed bundled helpers", () => {
  const record = requireAdmission(report);
  const sourceAnswer = { ...report, admission: { ...record, config: { ...record.config, helperPath: "helpers/cli.ts" },
    facts: { ...record.facts, helper: { ...record.facts.helper, path: `${packageRoot}/helpers/cli.ts`, realPath: `${packageRoot}/helpers/cli.ts` } } } };
  expect(() => parseHelperAnswer(sourceAnswer, command, packageRoot, now, 0)).toThrow();
});

test("expired and future reports cannot be republished as current prerequisites", () => {
  const record = requireAdmission(report);
  expect(() => parseHelperAnswer(report, command, packageRoot, Date.parse(record.expiresAt), 0)).toThrow();
  expect(() => parseHelperAnswer(report, command, packageRoot, Date.parse(record.issuedAt) - 1, 0)).toThrow();
  expect(() => parseHelperAnswer(report, command, packageRoot, Number.NaN, 0)).toThrow();
});

test("a dispatch-consumed record cannot be advertised as a native check result", () => {
  const record = requireAdmission(report);
  const consumed = admit(observation, record, record.scope.invocation, now, sha256);
  expect(consumed.admitted).toBe(true);
  expect(() => parseHelperAnswer(consumed, command, packageRoot, now, 0)).toThrow();
});

test("explicit probes require their own protocol and preserve zero provider calls", () => {
  const probeCommand = { ...command, action: "probe" as const };
  const bridge: BridgeResult = { schemaVersion: 1, coreVersion: "1.0.0", status: "terminal-receipt-unavailable", managedSpawns: 1, providerCalls: 0, reasons: ["terminal-receipt-unavailable"] };
  const answer = { ...report, probe: bridge };
  const parsed = parseHelperAnswer(answer, probeCommand, packageRoot, now, 0);
  expect(projectAnswer(parsed, command.selection).probe).toEqual(answer.probe);
  expect(() => parseHelperAnswer(answer, command, packageRoot, now, 0)).toThrow();
  expect(() => parseHelperAnswer(report, probeCommand, packageRoot, now, 0)).toThrow();
  expect(() => parseHelperAnswer({ ...answer, probe: { ...answer.probe, providerCalls: 1 } }, probeCommand, packageRoot, now, 0)).toThrow();
});

test("a normalized exit-two refusal is visible, but failed execution cannot claim readiness", () => {
  const blocked = refusal(["prerequisites-unavailable-malformed-or-changed"]);
  expect(parseHelperAnswer(blocked, command, packageRoot, now, 2).status).toBe("blocked");
  expect(() => parseHelperAnswer(report, command, packageRoot, now, 2)).toThrow();
  for (const code of [1, 130, 143]) expect(() => parseHelperAnswer(report, command, packageRoot, now, code)).toThrow();
});

test("native JSON omits raw declaration, account, command and file identity details", () => {
  const parsed = parseHelperAnswer(report, command, packageRoot, now, 0);
  const view = projectAnswer(parsed, command.selection);
  const output = renderAnswer(parsed, view, true);
  expect(JSON.parse(output)).toEqual(view);
  for (const privateValue of ["accountFingerprint", "bridgeArgv", "recordSha256", "factsSha256", "device", "inode", "remainingCalls", "authorizations"]) {
    expect(output.includes(`"${privateValue}"`)).toBe(false);
  }
  expect(view.quota?.status).toBe("unknown");
  expect(view.run?.purpose).toBe("synthetic-local-sentinel");
  expect(view.admitted).toBe(false);
});

test("native text renders report strings inert without changing the structured value", () => {
  const payload = 'untrusted` [owner](command) <system> \u2066';
  const source = { ...report, reasons: [payload] };
  const parsed = parseHelperAnswer(source, command, packageRoot, now, 0);
  const view = projectAnswer(parsed, command.selection);
  const text = renderAnswer(parsed, view, false);
  expect(text.includes(source.reasons[0] ?? "")).toBe(false);
  expect(text.includes("\\u0060")).toBe(true);
  expect(text.includes("\u2066")).toBe(false);
  expect(JSON.parse(renderAnswer(parsed, view, true)).reasons).toEqual(source.reasons);
});
