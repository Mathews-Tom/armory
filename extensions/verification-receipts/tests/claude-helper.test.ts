import { expect, test } from "bun:test";
import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import type { Socket } from "node:net";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseNativeObservation } from "../core/claude-protocol.ts";
import type { NativeReceiptProjection } from "../core/claude-protocol.ts";
import type { Configuration, Context, Gate } from "../core/index.ts";
import { resolveRepository } from "../helpers/scope.ts";
import { createStore } from "../helpers/storage.ts";

const CLI = fileURLToPath(new URL("../helpers/claude-cli.ts", import.meta.url));
const CONTEXT: Context = { host: "claude", sessionId: "native-session-one", accountId: "opaque-test-account", workContext: "selected-work" };
const PRIVATE_OUTPUT = "private-command-output: do not render\noriginal input\n";
interface Fixture { directory: string; repositoryRoot: string; dataRoot: string; }
interface Result { code: number | null; signal: string | null; stdout: string; stderr: string; }

async function deadline<T>(promise: Promise<T>, milliseconds = 15_000): Promise<T> {
  // Only bound actual OS process/IPC operations; readiness is event-driven and
  // fake timers cannot stop or observe these independently running processes.
  const expired = Promise.withResolvers<T>();
  const timer = setTimeout(() => expired.reject(new Error("Claude helper test deadline exceeded")), milliseconds);
  try { return await Promise.race([promise, expired.promise]); } finally { clearTimeout(timer); }
}

async function fixture(): Promise<Fixture> {
  const directory = await mkdtemp("/tmp/armory-vr-claude-helper-");
  const repositoryRoot = join(directory, "repository ; not shell");
  await mkdir(repositoryRoot);
  const git = spawn("git", ["init", "--quiet", repositoryRoot], { stdio: "ignore" });
  const initialized = Promise.withResolvers<undefined>();
  git.once("error", initialized.reject);
  git.once("close", (code) => code === 0 ? initialized.resolve(undefined) : initialized.reject(new Error("temporary Git initialization failed")));
  await initialized.promise;
  await writeFile(join(repositoryRoot, "input.txt"), "original input\n");
  await writeFile(join(repositoryRoot, "check.cjs"), `
    const fs = require('node:fs');
    const input = fs.readFileSync('input.txt', 'utf8');
    fs.writeFileSync('spawned.txt', 'configured child ran');
    process.stdout.write('private-command-output: do not render\\n' + input);
    process.exitCode = Number(process.argv[2]);
  `);
  const gate: Gate = {
    criterionId: "actual-file-check", kind: "integration", executable: process.execPath,
    args: ["check.cjs", "0"], cwd: ".", timeoutMs: 10_000, maxOutputBytes: 4096, requiresCompleteOutput: true,
    scope: { paths: ["input.txt", "check.cjs"], configPaths: [], environmentNames: [], datasetIdentity: null },
  };
  const configuration: Configuration = {
    schemaVersion: 1, configId: "claude-helper-tests",
    gates: {
      check: gate,
      fail: { ...gate, args: ["check.cjs", "23"] },
      missing: { ...gate, executable: "./missing-executable", args: [] },
      limited: { ...gate, maxOutputBytes: 8 },
    },
  };
  await writeFile(join(repositoryRoot, "receipts.json"), JSON.stringify(configuration));
  return { directory, repositoryRoot, dataRoot: join(directory, "private-state") };
}

function argumentsFor(value: Fixture, command: string, context: Context = CONTEXT): string[] {
  return [command, "--repo", value.repositoryRoot, "--config", "receipts.json", "--data-root", value.dataRoot,
    "--session", context.sessionId, "--account", context.accountId, "--work-context", context.workContext];
}

function start(args: string[]) {
  const child = spawn(process.execPath, [CLI, ...args], { stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
  child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
  const completed = Promise.withResolvers<Result>();
  child.once("error", completed.reject);
  child.once("close", (code, signal) => completed.resolve({ code, signal, stdout, stderr }));
  return { child, completed: completed.promise };
}

async function stop(child: ChildProcess, completed: Promise<Result>): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  try { await deadline(completed); } catch { child.kill("SIGKILL"); await deadline(completed); }
}

async function invoke(args: string[]): Promise<Result> {
  const running = start(args);
  try { return await deadline(running.completed); } finally { await stop(running.child, running.completed); }
}

function observation(result: Result) {
  expect(result.stderr).toBe("");
  expect(result.stdout.endsWith("\n")).toBe(true);
  expect(result.stdout.trim().split("\n")).toHaveLength(1);
  return parseNativeObservation(JSON.parse(result.stdout) as unknown);
}

function receipt(result: Result): NativeReceiptProjection {
  const value = observation(result);
  if (!("executionId" in value)) throw new Error("expected receipt projection");
  return value;
}

async function storeFor(value: Fixture, context: Context = CONTEXT) {
  return await createStore(value.dataRoot, await resolveRepository(value.repositoryRoot), context);
}

test("Claude helper executes real gates, preserves exact private output and reopens current scoped evidence", async () => {
  const value = await fixture();
  try {
    const successResult = await invoke([...argumentsFor(value, "run"), "--gate", "check"]);
    const success = receipt(successResult);
    expect(successResult.code).toBe(0);
    expect(success).toMatchObject({ status: "passed", applicability: "current", proof: true });
    expect(success.output).toEqual({
      sha256: createHash("sha256").update(PRIVATE_OUTPUT).digest("hex"),
      capturedBytes: Buffer.byteLength(PRIVATE_OUTPUT), totalBytes: Buffer.byteLength(PRIVATE_OUTPUT), truncated: false,
    });
    const store = await storeFor(value);
    const saved = await store.read(success.executionId);
    expect(saved.plan.context).toEqual(CONTEXT);
    expect(saved.result.exitCode).toBe(0);
    const outputPath = join(store.root, "runs", success.executionId, "artifacts", "output.bin");
    expect(await readFile(outputPath, "utf8")).toBe(PRIVATE_OUTPUT);
    expect((await stat(outputPath)).mode & 0o777).toBe(0o600);
    for (const privateValue of [PRIVATE_OUTPUT.trim(), value.directory, CONTEXT.sessionId, CONTEXT.accountId]) {
      expect(successResult.stdout).not.toContain(privateValue);
    }
    const reopenedContext = { ...CONTEXT, sessionId: "native-session-two" };
    const reopened = observation(await invoke(argumentsFor(value, "list", reopenedContext)));
    expect(reopened).toEqual({ receipts: [success] });
    await writeFile(join(value.repositoryRoot, "input.txt"), "covered drift\n");
    expect(observation(await invoke(argumentsFor(value, "list", reopenedContext)))).toEqual({
      receipts: [{ ...success, applicability: "stale", proof: false }],
    });
    expect(observation(await invoke(argumentsFor(value, "list", { ...CONTEXT, accountId: "another-account" })))).toEqual({ receipts: [] });
    expect(observation(await invoke(argumentsFor(value, "list", { ...CONTEXT, workContext: "another-work-context" })))).toEqual({ receipts: [] });
    expect((await store.read(success.executionId)).plan.context.sessionId).toBe(CONTEXT.sessionId);
  } finally { await rm(value.directory, { recursive: true, force: true }); }
}, 30_000);

test("Claude helper distinguishes failed, launch-incomplete and truncated evidence without exposing output", async () => {
  const value = await fixture();
  try {
    const failedResult = await invoke([...argumentsFor(value, "run"), "--gate", "fail"]);
    const failed = receipt(failedResult);
    expect(failedResult.code).toBe(1);
    expect(failed).toMatchObject({ status: "failed", proof: false });
    const missingResult = await invoke([...argumentsFor(value, "run"), "--gate", "missing"]);
    const missing = receipt(missingResult);
    expect(missingResult.code).toBe(2);
    expect(missing).toMatchObject({ status: "incomplete", proof: false });
    const limitedResult = await invoke([...argumentsFor(value, "run"), "--gate", "limited"]);
    const limited = receipt(limitedResult);
    expect(limitedResult.code).toBe(2);
    expect(limited).toMatchObject({ status: "passed", proof: false, output: { capturedBytes: 8, totalBytes: Buffer.byteLength(PRIVATE_OUTPUT), truncated: true } });
    const store = await storeFor(value);
    expect((await store.read(failed.executionId)).result.exitCode).toBe(23);
    expect((await store.read(missing.executionId)).result.reason).toBe("launch-failed");
    expect(await readFile(join(store.root, "runs", limited.executionId, "artifacts", "output.bin"), "utf8")).toBe(PRIVATE_OUTPUT.slice(0, 8));
    expect((await store.list()).map((item) => item.plan.executionId).sort()).toEqual([failed.executionId, missing.executionId, limited.executionId].sort());
    for (const result of [failedResult, missingResult, limitedResult]) {
      expect(result.stdout).not.toContain("private-command-output");
      expect(result.stdout).not.toContain(value.directory);
    }
  } finally { await rm(value.directory, { recursive: true, force: true }); }
}, 30_000);

test("malformed native helper arguments fail before creating storage or starting a configured gate", async () => {
  const value = await fixture();
  try {
    const valid = [...argumentsFor(value, "run"), "--gate", "check"];
    const invalid: string[][] = [[], ["show"], [...valid, "--host", "standalone"], [...valid, "--gate", "check"], [...valid, "--unknown", "private-value"], [...valid, "dangling"]];
    for (const flag of ["--repo", "--config", "--data-root", "--session", "--account", "--work-context", "--gate"]) {
      const index = valid.indexOf(flag);
      invalid.push([...valid.slice(0, index), ...valid.slice(index + 2)]);
      invalid.push([...valid.slice(0, index + 1), "", ...valid.slice(index + 2)]);
    }
    const configIndex = valid.indexOf("--config") + 1;
    invalid.push([...valid.slice(0, configIndex), "../escape.json", ...valid.slice(configIndex + 1)]);
    const sessionIndex = valid.indexOf("--session") + 1;
    invalid.push([...valid.slice(0, sessionIndex), "bad\nsession", ...valid.slice(sessionIndex + 1)]);
    invalid.push([...argumentsFor(value, "list"), "--gate", "check"]);
    invalid.push([...argumentsFor(value, "reconcile"), "--gate", "check"]);
    for (const args of invalid) {
      const result = await invoke(args);
      expect(result.code).toBe(2);
      expect(observation(result)).toEqual({ error: "invalid-arguments" });
    }
    await expect(stat(value.dataRoot)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(stat(join(value.repositoryRoot, "spawned.txt"))).rejects.toMatchObject({ code: "ENOENT" });
    const unknown = await invoke([...argumentsFor(value, "run"), "--gate", "unconfigured; not shell"]);
    expect(unknown.code).toBe(2);
    expect(observation(unknown)).toEqual({ error: "operation-failed" });
    await expect(stat(value.dataRoot)).rejects.toMatchObject({ code: "ENOENT" });
  } finally { await rm(value.directory, { recursive: true, force: true }); }
}, 30_000);

async function treeBarrier(value: Fixture) {
  const root = Promise.withResolvers<number>();
  const descendant = Promise.withResolvers<number>();
  const sockets = new Set<Socket>();
  const socketPath = join(value.directory, "tree.sock");
  const server = createServer((socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
    socket.on("error", () => { /* Cleanup may close a peer already stopping. */ });
    socket.setEncoding("utf8");
    let message = "";
    socket.on("data", (chunk: string) => {
      message += chunk;
      if (message.length > 256) { socket.destroy(); return; }
      const match = /^(root|descendant):([1-9][0-9]*)\n$/u.exec(message);
      if (match === null) return;
      const pid = Number(match[2]);
      if (!Number.isSafeInteger(pid)) { socket.destroy(); return; }
      (match[1] === "root" ? root : descendant).resolve(pid);
    });
  });
  const listening = Promise.withResolvers<undefined>();
  server.once("error", listening.reject);
  server.listen(socketPath, () => listening.resolve(undefined));
  await listening.promise;
  await writeFile(join(value.repositoryRoot, "descendant.cjs"), `
    const net = require('node:net');
    setInterval(() => {}, 1000);
    net.createConnection(process.argv[2], function () { this.end('descendant:' + process.pid + '\\n'); });
  `);
  await writeFile(join(value.repositoryRoot, "tree.cjs"), `
    const net = require('node:net');
    const { spawn } = require('node:child_process');
    const child = spawn(process.execPath, ['descendant.cjs', process.argv[2]], { stdio: 'ignore' });
    let stopping = false;
    const keepAlive = setInterval(() => {}, 1000);
    child.once('exit', () => { if (stopping) process.exit(0); });
    process.on('SIGTERM', () => {
      stopping = true;
      clearInterval(keepAlive);
      if (child.exitCode !== null || child.signalCode !== null) process.exit(0);
    });
    net.createConnection(process.argv[2], function () { this.end('root:' + process.pid + '\\n'); });
  `);
  const config: Configuration = {
    schemaVersion: 1, configId: "cancel-tree",
    gates: { tree: {
      criterionId: "cancel-owned-descendants", kind: "integration", executable: process.execPath,
      args: ["tree.cjs", socketPath], cwd: ".", timeoutMs: 60_000, maxOutputBytes: 4096, requiresCompleteOutput: true,
      scope: { paths: ["input.txt", "tree.cjs", "descendant.cjs"], configPaths: [], environmentNames: [], datasetIdentity: null },
    } },
  };
  await writeFile(join(value.repositoryRoot, "receipts.json"), JSON.stringify(config));
  return {
    root: root.promise, descendant: descendant.promise,
    async close(): Promise<void> {
      for (const socket of sockets) socket.destroy();
      const closed = Promise.withResolvers<undefined>();
      server.close((error) => error ? closed.reject(error) : closed.resolve(undefined));
      await closed.promise;
    },
  };
}

function expectStopped(pid: number): void {
  try { process.kill(pid, 0); } catch (error) {
    expect(error).toMatchObject({ code: "ESRCH" });
    return;
  }
  throw new Error("owned process remained after helper exit");
}

for (const signal of ["SIGTERM", "SIGINT"] as const) {
  test(`${signal} waits for owned descendants and a durable cancelled receipt before helper exit`, async () => {
    const value = await fixture();
    const barrier = await treeBarrier(value);
    const running = start([...argumentsFor(value, "run"), "--gate", "tree"]);
    let rootPid: number | undefined;
    try {
      rootPid = await deadline(barrier.root);
      const ready = [rootPid, await deadline(barrier.descendant)] as const;
      expect(running.child.kill(signal)).toBe(true);
      const result = await deadline(running.completed);
      const cancelled = receipt(result);
      expect(result.code).toBe(signal === "SIGTERM" ? 143 : 130);
      expect(result.signal).toBeNull();
      expect(cancelled).toMatchObject({ status: "cancelled", proof: false });
      expectStopped(ready[0]);
      expectStopped(ready[1]);
      const store = await storeFor(value);
      const saved = await store.read(cancelled.executionId);
      expect(saved.result).toMatchObject({ status: "cancelled", reason: "cancelled", descendantsStopped: true });
    } finally {
      await stop(running.child, running.completed);
      if (rootPid !== undefined) {
        try { process.kill(-rootPid, "SIGKILL"); } catch (error) {
          expect(error).toMatchObject({ code: "ESRCH" });
        }
      }
      await barrier.close();
      await rm(value.directory, { recursive: true, force: true });
    }
  }, 25_000);
}

const SAFE: NativeReceiptProjection = {
  executionId: "12345678-1234-1234-1234-123456789abc", status: "passed", applicability: "current", proof: true,
  output: { sha256: "a".repeat(64), capturedBytes: 8, totalBytes: 8, truncated: false },
};

test("native protocol produces fresh exact projections and preserves legitimate non-proof states", () => {
  const normalized = parseNativeObservation(SAFE);
  expect(normalized).toEqual(SAFE);
  const states: NativeReceiptProjection[] = [SAFE,
    { ...SAFE, status: "failed", proof: false },
    { ...SAFE, status: "cancelled", proof: false },
    { ...SAFE, applicability: "stale", proof: false },
    { ...SAFE, applicability: "unknown", proof: false },
    { ...SAFE, output: { ...SAFE.output, totalBytes: 16, truncated: true } },
    { ...SAFE, status: "incomplete", applicability: "unknown", proof: false, output: { ...SAFE.output, totalBytes: null, truncated: null } },
  ];
  expect(parseNativeObservation({ receipts: states })).toEqual({ receipts: states });
  expect(parseNativeObservation({ receipts: [] })).toEqual({ receipts: [] });
  for (const error of ["invalid-arguments", "operation-failed"] as const) expect(parseNativeObservation({ error })).toEqual({ error });
});

test("native protocol refuses private fields and malformed or inconsistent proof with sanitized errors", () => {
  const unsafe: unknown[] = [null, [], "private-path", {}, { error: "private-path" }, { error: "operation-failed", detail: "private-path" },
    { ...SAFE, path: "private-path" }, { ...SAFE, status: "failed" }, { ...SAFE, status: "cancelled" }, { ...SAFE, status: "incomplete" },
    { ...SAFE, applicability: "stale" }, { ...SAFE, applicability: "unknown" }, { ...SAFE, status: "successful" },
    { ...SAFE, proof: "true" }, { ...SAFE, executionId: "private-path" },
    { ...SAFE, output: { ...SAFE.output, raw: "private-path" } },
    { ...SAFE, output: { ...SAFE.output, sha256: "private-path" } },
    ...[-1, 1.5, Number.NaN, Number.MAX_SAFE_INTEGER + 1, 16 * 1024 * 1024 + 1].map((capturedBytes) => ({ ...SAFE, output: { ...SAFE.output, capturedBytes } })),
    { ...SAFE, output: { ...SAFE.output, totalBytes: 7 } },
    { ...SAFE, output: { ...SAFE.output, totalBytes: 9 } },
    { ...SAFE, output: { ...SAFE.output, truncated: true } },
    { ...SAFE, output: { ...SAFE.output, totalBytes: null } },
    { ...SAFE, output: { ...SAFE.output, totalBytes: null, truncated: null } },
    { receipts: [SAFE, { ...SAFE, private: "private-path" }] }, { receipts: new Array(1) }, { receipts: new Array(10_001).fill(SAFE) },
    Object.create({ private: "private-path" }) as unknown,
    Object.defineProperty({ ...SAFE }, "proof", { get() { throw new Error("private-path"); } }),
  ];
  for (const value of unsafe) expect(() => parseNativeObservation(value)).toThrow(/^invalid native receipt observation$/u);
});
