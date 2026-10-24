import { afterEach, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { chmod, cp, lstat, mkdir, readFile, realpath, rename, rm, symlink, utimes, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { admit, check, parseProbeResponse, parseResponse } from "../core/index.ts";
import type { Declaration, ProbeResponse, ProjectConfig, Response } from "../core/index.ts";
import { observe, sha256 } from "../helpers/filesystem.ts";
import { fixture, HELPER, requireAdmission } from "./fixtures.ts";
import type { Fixture } from "./fixtures.ts";

const fixtures: Fixture[] = [];
afterEach(async () => { for (const value of fixtures.splice(0)) await value.dispose(); });
async function selected(bridgeBody?: string): Promise<Fixture> {
  const value = await fixture(bridgeBody);
  fixtures.push(value);
  return value;
}
function cli(value: Fixture, action: string, extras: readonly string[] = []): { code: number; response: Response; stdout: string } {
  const completed = Bun.spawnSync([process.execPath, HELPER, action, "--config", value.configPath, "--declaration", value.declarationPath, ...extras], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
  const stdout = new TextDecoder().decode(completed.stdout);
  return { code: completed.exitCode, response: JSON.parse(stdout) as Response, stdout };
}
async function issue(value: Fixture): Promise<{ recordPath: string; invocationPath: string }> {
  const report = cli(value, "check");
  expect(report.code).toBe(0);
  const record = parseResponse(report.response).admission;
  expect(record).not.toBeNull();
  const recordPath = join(value.root, "admission.json");
  const invocationPath = join(value.root, "actual-invocation.json");
  await writeFile(recordPath, JSON.stringify(record));
  await writeFile(invocationPath, JSON.stringify(value.declaration.invocation));
  return { recordPath, invocationPath };
}

async function configure(value: Fixture, config: ProjectConfig): Promise<Declaration> {
  await writeFile(value.configPath, JSON.stringify(config));
  const configSha256 = sha256(await readFile(value.configPath, "utf8"));
  const declaration = { ...value.declaration, configSha256, inputs: {
    ...value.declaration.inputs,
    config: value.declaration.inputs.config.map((binding) => binding.path === value.configPath ? { ...binding, sha256: configSha256 } : binding),
  } };
  await writeFile(value.declarationPath, JSON.stringify(declaration));
  return declaration;
}

for (const source of ["interpreter-only", "unrelated-operand"] as const) {
  test(`CLI probe refuses a ${source} source binding before invoking the unbound bridge`, async () => {
    const value = await selected();
    const boundPath = source === "interpreter-only" ? await realpath(process.execPath) : join(value.root, "unrelated-source.ts");
    if (source === "unrelated-operand") await writeFile(boundPath, "export {};\n");
    const config: ProjectConfig = { ...value.config, bridgeArgv: source === "interpreter-only"
      ? [boundPath, value.sourcePath]
      : [...value.config.bridgeArgv, boundPath] };
    const declaration = await configure(value, config);
    const sha256 = createHash("sha256").update(await readFile(boundPath)).digest("hex");
    await writeFile(value.declarationPath, JSON.stringify({ ...declaration, inputs: {
      ...declaration.inputs, source: [{ path: boundPath, sha256 }],
    } }));
    const result = cli(value, "probe");
    expect(result.code).toBe(2);
    expect(parseProbeResponse(result.response)).toMatchObject({ status: "blocked", admitted: false, admission: null, probe: null });
    await expect(readFile(value.marker)).rejects.toThrow();
  });
}

test("admission refuses an equal-length source rewrite with restored mtime during observation", async () => {
  const value = await selected();
  const timestamp = Math.floor(Date.now() / 1000) - 1;
  await utimes(value.sourcePath, timestamp, timestamp);
  const { recordPath, invocationPath } = await issue(value);
  const args = ["admit", "--config", value.configPath, "--declaration", value.declarationPath, "--record", recordPath, "--invocation", invocationPath];
  const baseline = cli(value, "admit", ["--record", recordPath, "--invocation", invocationPath]);
  expect(baseline.code).toBe(0);
  expect(baseline.response.admitted).toBe(true);
  const before = await lstat(value.sourcePath, { bigint: true });
  const original = await readFile(value.sourcePath, "utf8");
  const changed = " " + original.slice(1);
  const racePath = join(value.root, "rewrite-during-observation.ts");
  // The child intercepts scheduling only; reads, writes, timestamps and stats
  // are real. The source has been hashed before the selected data is opened.
  await writeFile(racePath, `
import { mock } from "bun:test";
import * as filesystem from "node:fs/promises";
const actual = { ...filesystem };
let changed = false;
mock.module("node:fs/promises", () => ({ ...actual, lstat: async (...args) => {
  const result = await actual.lstat(...args);
  if (!changed && args[0] === ${JSON.stringify(value.dataPath)}) {
    changed = true;
    const source = ${JSON.stringify(value.sourcePath)};
    const before = await actual.lstat(source);
    await actual.writeFile(source, ${JSON.stringify(changed)});
    await actual.utimes(source, before.atime, before.mtime);
  }
  return result;
} }));
const { main } = await import(${JSON.stringify(pathToFileURL(HELPER).href)});
process.exitCode = await main(${JSON.stringify(args)});
`);
  const result = Bun.spawnSync([process.execPath, racePath], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
  const after = await lstat(value.sourcePath, { bigint: true });
  expect(after.ino).toBe(before.ino);
  expect(after.size).toBe(before.size);
  expect(after.mtimeNs).toBe(before.mtimeNs);
  expect(after.ctimeNs).not.toBe(before.ctimeNs);
  expect(await readFile(value.sourcePath, "utf8")).toBe(changed);
  expect(result.exitCode).toBe(2);
  expect(parseResponse(JSON.parse(new TextDecoder().decode(result.stdout)))).toMatchObject({ status: "blocked", admitted: false, admission: null });
});

for (const rootName of ["projectRoot", "packageRoot"] as const) {
  test(`admission refuses actual ${rootName} replacement during its final observation`, async () => {
    const value = await selected();
    const root = join(value.root, rootName);
    await mkdir(root);
    let helper = HELPER;
    if (rootName === "packageRoot") {
      const packageRoot = value.config.packageRoot;
      await cp(join(packageRoot, "core"), join(root, "core"), { recursive: true });
      await cp(join(packageRoot, "helpers"), join(root, "helpers"), { recursive: true });
      helper = join(root, "helpers/cli.ts");
    }
    await configure(value, { ...value.config, [rootName]: root });
    const observation = await observe(value.configPath, value.declarationPath, helper);
    const record = requireAdmission(check(observation, value.now, sha256));
    const recordPath = join(value.root, "admission.json");
    const invocationPath = join(value.root, "actual-invocation.json");
    await writeFile(recordPath, JSON.stringify(record));
    await writeFile(invocationPath, JSON.stringify(value.declaration.invocation));
    const admissionArgs = ["admit", "--config", value.configPath, "--declaration", value.declarationPath, "--record", recordPath, "--invocation", invocationPath];
    const baseline = Bun.spawnSync([process.execPath, helper, ...admissionArgs], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
    expect(baseline.exitCode).toBe(0);
    expect(parseResponse(JSON.parse(new TextDecoder().decode(baseline.stdout))).admitted).toBe(true);
    const rootBefore = await lstat(root, { bigint: true });
    const helperBefore = await lstat(helper, { bigint: true });
    const racePath = join(value.root, "replace-during-observation.ts");
    // Interception lives only in this child. Every operation/stat is real; moving
    // the package entries preserves all selected files while replacing their root.
    await writeFile(racePath, `
import { mock } from "bun:test";
import * as filesystem from "node:fs/promises";
const actual = { ...filesystem };
let replaced = false;
mock.module("node:fs/promises", () => ({ ...actual, lstat: async (...args) => {
  const result = await actual.lstat(...args);
  if (!replaced && args[0] === ${JSON.stringify(value.dataPath)}) {
    replaced = true;
    const root = ${JSON.stringify(root)};
    const oldRoot = root + "-old";
    await actual.rename(root, oldRoot);
    await actual.mkdir(root);
    for (const entry of await actual.readdir(oldRoot)) await actual.rename(oldRoot + "/" + entry, root + "/" + entry);
  }
  return result;
} }));
// The selected helper must load after builtin interception, inside this child only.
const { main } = await import(${JSON.stringify(pathToFileURL(helper).href)});
process.exitCode = await main(${JSON.stringify(admissionArgs)});
`);
    const completed = Bun.spawnSync([process.execPath, racePath], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
    expect(completed.exitCode).toBe(2);
    const response = parseResponse(JSON.parse(new TextDecoder().decode(completed.stdout)));
    expect(response).toMatchObject({ status: "blocked", admitted: false, admission: null });
    expect((await lstat(root, { bigint: true })).ino).not.toBe(rootBefore.ino);
    expect((await lstat(helper, { bigint: true })).ino).toBe(helperBefore.ino);
    await expect(readFile(value.marker)).rejects.toThrow();
  });
}

test("source-prefix CLI check is read-only and complete record admits through a second real CLI", async () => {
  const value = await selected();
  const { recordPath, invocationPath } = await issue(value);
  await expect(readFile(value.marker)).rejects.toThrow();
  const result = cli(value, "admit", ["--record", recordPath, "--invocation", invocationPath]);
  expect(result.code).toBe(0);
  expect(parseResponse(result.response)).toMatchObject({ status: "unknown", admitted: true });
  await expect(readFile(value.marker)).rejects.toThrow();
});

test("actual local-child transport probe runs once, retains unknown quota and unavailable terminal receipt", async () => {
  const value = await selected();
  const result = cli(value, "probe");
  expect(result.code).toBe(0);
  const response = parseProbeResponse(result.response);
  expect(response.status).toBe("unknown");
  expect(response.admitted).toBe(false);
  expect(response.probe).toMatchObject({ status: "terminal-receipt-unavailable", managedSpawns: 1, providerCalls: 0 });
  expect(await readFile(value.marker, "utf8")).toBe("local-child\n");
  expect(result.stdout).not.toContain("DerivedReceipt");
});

test("expired synthetic declaration reaches the transport bridge zero times", async () => {
  const value = await selected();
  await writeFile(value.declarationPath, JSON.stringify({ ...value.declaration, issuedAt: "2020-01-01T00:00:00Z", expiresAt: "2020-01-01T00:01:00Z" }));
  const result = cli(value, "probe");
  expect(result.response.status).toBe("blocked");
  expect((result.response as ProbeResponse).probe).toBeNull();
  await expect(readFile(value.marker)).rejects.toThrow();
});

for (const role of ["source", "config", "data", "identity", "contract"] as const) {
  test(`real ${role} file drift refuses a previously issued record without spawning`, async () => {
    const value = await selected();
    const { recordPath, invocationPath } = await issue(value);
    const path = { source: value.sourcePath, config: value.configPath, data: value.dataPath, identity: value.identityPath, contract: value.contractPath }[role];
    await writeFile(path, `${await readFile(path, "utf8")}\n`);
    const result = cli(value, "admit", ["--record", recordPath, "--invocation", invocationPath]);
    expect(result.response.admitted).toBe(false);
    expect(result.response.status).toBe("blocked");
    await expect(readFile(value.marker)).rejects.toThrow();
  });
}

test("a rewritten complete declaration with identical semantics still invalidates its raw binding", async () => {
  const value = await selected();
  const { recordPath, invocationPath } = await issue(value);
  await writeFile(value.declarationPath, JSON.stringify(value.declaration, null, 2));
  const result = cli(value, "admit", ["--record", recordPath, "--invocation", invocationPath]);
  expect(result.response).toMatchObject({ status: "blocked", admitted: false });
});

test("checkpoint directory replacement and unwritable readiness refuse a record", async () => {
  const value = await selected();
  const { recordPath, invocationPath } = await issue(value);
  await rename(value.checkpoint, `${value.checkpoint}-old`);
  await mkdir(value.checkpoint);
  const replaced = cli(value, "admit", ["--record", recordPath, "--invocation", invocationPath]);
  expect(replaced.response.admitted).toBe(false);
  await chmod(value.checkpoint, 0o500);
  const unwritable = cli(value, "check");
  expect(unwritable.code).toBe(2);
  expect(unwritable.response.status).toBe("blocked");
  await chmod(value.checkpoint, 0o700);
});

test("selected input symlinks, missing identity and malformed structured records refuse", async () => {
  const value = await selected();
  const { recordPath, invocationPath } = await issue(value);
  await writeFile(recordPath, JSON.stringify({ status: "ready", admitted: true }));
  expect(cli(value, "admit", ["--record", recordPath, "--invocation", invocationPath]).response.admitted).toBe(false);
  await rename(value.dataPath, `${value.dataPath}-real`);
  await symlink(`${value.dataPath}-real`, value.dataPath);
  expect(cli(value, "check").response.status).toBe("blocked");
  await rm(value.identityPath);
  expect(cli(value, "probe").response.status).toBe("blocked");
  await expect(readFile(value.marker)).rejects.toThrow();
});

test("fresh observation time does not itself cause drift, but filesystem identity does", async () => {
  const value = await selected();
  const first = await observe(value.configPath, value.declarationPath, HELPER);
  const record = requireAdmission(check(first, value.now, sha256));
  const next = await observe(value.configPath, value.declarationPath, HELPER);
  expect(admit(next, record, value.declaration.invocation, value.now + 2000, sha256).admitted).toBe(true);
  const content = await readFile(value.dataPath);
  await rename(value.dataPath, `${value.dataPath}-old`);
  await writeFile(value.dataPath, content);
  const replacement = await observe(value.configPath, value.declarationPath, HELPER);
  expect(admit(replacement, record, value.declaration.invocation, value.now + 2001, sha256).admitted).toBe(false);
});

test("CLI refuses unsupported action, missing/duplicate arguments and wrong helper bootstrap", async () => {
  const value = await selected();
  expect(cli(value, "launch").code).toBe(2);
  expect(cli(value, "admit").code).toBe(2);
  expect(cli(value, "check", ["--config", value.configPath]).code).toBe(2);
  await writeFile(value.configPath, JSON.stringify({ ...value.config, coreVersion: "0.0.0" }));
  const invalid = cli(value, "check");
  expect(invalid.code).toBe(2);
  expect(invalid.response.status).toBe("blocked");
});

test("configured prefix/helper mismatch has no fallback to the source checkout", async () => {
  const value = await selected();
  const changedConfig = { ...value.config, packageRoot: value.root };
  await writeFile(value.configPath, JSON.stringify(changedConfig));
  const configSha256 = sha256(await readFile(value.configPath, "utf8"));
  await writeFile(value.declarationPath, JSON.stringify({ ...value.declaration, configSha256, inputs: { ...value.declaration.inputs, config: value.declaration.inputs.config.map((binding) => binding.path === value.configPath ? { ...binding, sha256: configSha256 } : binding) } }));
  const result = cli(value, "check");
  expect(result.code).toBe(2);
  expect(result.response.status).toBe("blocked");
});

test("bridge failures never echo stderr secrets or claim a successful sentinel", async () => {
  const value = await selected('process.stderr.write("SECRET-MUST-NOT-LEAK"); process.exit(7);');
  const result = cli(value, "probe");
  expect(result.code).toBe(2);
  expect(result.response.status).toBe("blocked");
  expect(result.stdout).not.toContain("SECRET-MUST-NOT-LEAK");
  expect((result.response as ProbeResponse).probe).toBeNull();
});
