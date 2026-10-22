import { expect, test } from "bun:test";
import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import type { Socket } from "node:net";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { isSuccessfulProof } from "../core/index.ts";
import type { Configuration, Context, Gate, Receipt } from "../core/index.ts";
import { executeGate } from "../helpers/runner.ts";
import { resolveRepository } from "../helpers/scope.ts";
import { createStore } from "../helpers/storage.ts";

const CLI = fileURLToPath(new URL("../helpers/cli.ts", import.meta.url));
const CONTEXT: Context = { host: "standalone", sessionId: "execution-test", accountId: "local-test", workContext: "execution-tests" };

interface Fixture { directory: string; repositoryRoot: string; dataRoot: string; }
interface CliResult { code: number | null; signal: string | null; stdout: string; stderr: string; }
interface PublicReceipt {
  executionId: string;
  status: Receipt["result"]["status"];
  applicability: Receipt["applicability"];
  proof: boolean;
  output: Pick<Receipt["artifact"], "sha256" | "capturedBytes" | "totalBytes" | "truncated">;
}

async function deadline<T>(promise: Promise<T>, milliseconds = 10_000): Promise<T> {
  // These bound actual OS child/IPC operations; fake timers cannot stop those
  // processes. Readiness and cancellation use explicit IPC, never a fixed sleep.
  const expired = Promise.withResolvers<T>();
  const timer = setTimeout(() => expired.reject(new Error("execution test deadline exceeded")), milliseconds);
  try { return await Promise.race([promise, expired.promise]); } finally { clearTimeout(timer); }
}

async function fixture(): Promise<Fixture> {
  // Keep Unix IPC paths short even when the OS temp directory has a long name.
  const directory = await mkdtemp("/tmp/armory-vr-execution-");
  const repositoryRoot = join(directory, "repository");
  await mkdir(repositoryRoot);
  const git = spawn("git", ["init", "--quiet", repositoryRoot], { stdio: "ignore" });
  const initialized = Promise.withResolvers<undefined>();
  git.once("error", initialized.reject);
  git.once("close", (code) => code === 0 ? initialized.resolve(undefined) : initialized.reject(new Error("temporary Git initialization failed")));
  await initialized.promise;
  await writeFile(join(repositoryRoot, "input.txt"), "original input\n");
  return { directory, repositoryRoot, dataRoot: join(directory, "private-state") };
}

async function configure(value: Fixture, overrides: Partial<Gate> = {}): Promise<void> {
  const configuration: Configuration = {
    schemaVersion: 1,
    configId: "execution-tests",
    gates: {
      check: {
        criterionId: "configured-check", kind: "unit", executable: process.execPath,
        args: ["-e", "process.stdout.write('receipt-success')"], cwd: ".",
        timeoutMs: 10_000, maxOutputBytes: 4096, requiresCompleteOutput: true,
        scope: { paths: ["input.txt"], configPaths: [], environmentNames: [], datasetIdentity: null },
        ...overrides,
      },
    },
  };
  await writeFile(join(value.repositoryRoot, "receipts.json"), JSON.stringify(configuration));
}

function request(value: Fixture, signal?: AbortSignal) {
  return { repositoryRoot: value.repositoryRoot, configPath: "receipts.json", gateId: "check", dataRoot: value.dataRoot, context: CONTEXT, signal };
}

async function storeFor(value: Fixture) {
  return await createStore(value.dataRoot, await resolveRepository(value.repositoryRoot), CONTEXT);
}

function digest(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function startCLI(value: Fixture, command: string, extra: string[] = [], host = "standalone") {
  const child = spawn(process.execPath, [CLI, command,
    "--repo", value.repositoryRoot, "--config", "receipts.json", "--data-root", value.dataRoot,
    "--host", host, "--session", CONTEXT.sessionId, "--account", CONTEXT.accountId,
    "--work-context", CONTEXT.workContext, ...extra,
  ], { stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
  child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
  const completed = Promise.withResolvers<CliResult>();
  child.once("error", completed.reject);
  child.once("close", (code, signal) => completed.resolve({ code, signal, stdout, stderr }));
  return { child, completed: completed.promise };
}

async function invokeCLI(value: Fixture, command: string, extra: string[] = [], host = "standalone"): Promise<CliResult> {
  const running = startCLI(value, command, extra, host);
  try { return await deadline(running.completed, 15_000); } finally {
    if (running.child.exitCode === null && running.child.signalCode === null) {
      running.child.kill("SIGTERM");
      try { await deadline(running.completed); } catch { running.child.kill("SIGKILL"); }
    }
  }
}

interface Ready { pid: number; socket: Socket; }

async function barrier(value: Fixture) {
  const root = Promise.withResolvers<Ready>();
  const descendant = Promise.withResolvers<Ready>();
  const sockets = new Set<Socket>();
  const path = join(value.directory, "ipc.sock");
  const server = createServer((socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
    socket.on("error", () => { /* Test cleanup can close an already-stopping peer. */ });
    socket.setEncoding("utf8");
    let message = "";
    const receive = (chunk: string): void => {
      message += chunk;
      if (message.length > 4096) { socket.destroy(); return; }
      const end = message.indexOf("\n");
      if (end === -1) return;
      socket.removeListener("data", receive);
      const match = /^(root|descendant):([1-9][0-9]*)$/u.exec(message.slice(0, end));
      if (match === null) { socket.destroy(); return; }
      const pid = Number(match[2]);
      if (!Number.isSafeInteger(pid)) { socket.destroy(); return; }
      (match[1] === "root" ? root : descendant).resolve({ pid, socket });
    };
    socket.on("data", receive);
  });
  const listening = Promise.withResolvers<undefined>();
  server.once("error", listening.reject);
  server.listen(path, () => { server.removeListener("error", listening.reject); listening.resolve(undefined); });
  await listening.promise;
  return {
    path,
    root: root.promise,
    descendant: descendant.promise,
    async close(): Promise<void> {
      for (const socket of sockets) socket.destroy();
      const closed = Promise.withResolvers<undefined>();
      server.close((error) => error ? closed.reject(error) : closed.resolve(undefined));
      await closed.promise;
    },
  };
}

async function configureTree(value: Fixture, socketPath: string): Promise<void> {
  await writeFile(join(value.repositoryRoot, "descendant.cjs"), `
    const net = require('node:net');
    setInterval(() => {}, 1000);
    const socket = net.createConnection(process.argv[2], () => socket.end('descendant:' + process.pid + '\\n'));
  `);
  await writeFile(join(value.repositoryRoot, "root.cjs"), `
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
    const socket = net.createConnection(process.argv[2], () => socket.end('root:' + process.pid + '\\n'));
  `);
  await configure(value, { args: ["root.cjs", socketPath] });
}

function stopped(pid: number): boolean {
  try { process.kill(pid, 0); return false; } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ESRCH") return true;
    throw error;
  }
}

function cleanOwnedGroup(pid: number | undefined): void {
  if (pid === undefined) return;
  try { process.kill(-pid, "SIGKILL"); } catch (error) {
    if (!(error instanceof Error && "code" in error && error.code === "ESRCH")) throw error;
  }
}

test("configured execution records actual success, private output bytes and a durable proof", async () => {
  const value = await fixture();
  try {
    await configure(value);
    const receipt = await executeGate(request(value));
    expect(receipt.result).toEqual({ status: "passed", exitCode: 0, signal: null, reason: null, descendantsStopped: true });
    expect(receipt.artifact).toEqual({ file: "output.bin", sha256: digest("receipt-success"), capturedBytes: 15, totalBytes: 15, truncated: false });
    expect(receipt.applicability).toBe("current");
    expect(isSuccessfulProof(receipt, receipt.after)).toBe(true);
    const store = await storeFor(value);
    expect(await store.read(receipt.plan.executionId)).toEqual(receipt);
    const outputPath = join(store.root, "runs", receipt.plan.executionId, "artifacts", "output.bin");
    expect(await readFile(outputPath, "utf8")).toBe("receipt-success");
    expect((await stat(outputPath)).mode & 0o777).toBe(0o600);
  } finally { await rm(value.directory, { recursive: true, force: true }); }
});

test("nonzero configured execution fails and missing executable is durably incomplete", async () => {
  const value = await fixture();
  try {
    await configure(value, { args: ["-e", "process.stderr.write('check-failed'); process.exitCode = 23"] });
    const failed = await executeGate(request(value));
    expect(failed.result.status).toBe("failed");
    expect(failed.result.exitCode).toBe(23);
    expect(failed.artifact.sha256).toBe(digest("check-failed"));
    expect(isSuccessfulProof(failed, failed.after)).toBe(false);
    await configure(value, { executable: "./does-not-exist", args: [] });
    const missing = await executeGate(request(value));
    expect(missing.result).toEqual({ status: "incomplete", exitCode: null, signal: null, reason: "launch-failed", descendantsStopped: true });
    expect(missing.artifact.sha256).toBe(digest(""));
    expect(missing.artifact.capturedBytes).toBe(0);
    const store = await storeFor(value);
    expect((await store.read(missing.plan.executionId)).result.status).toBe("incomplete");
    expect((await store.list()).length).toBe(2);
  } finally { await rm(value.directory, { recursive: true, force: true }); }
});

test("output flooding drains fully but keeps only bounded private bytes and cannot prove complete output", async () => {
  const value = await fixture();
  try {
    await configure(value, {
      args: ["-e", "const {writeSync}=require('node:fs'); const bytes=Buffer.alloc(65536,120); for(let i=0;i<32;i++){let offset=0;while(offset<bytes.length){offset+=writeSync(1,bytes,offset,bytes.length-offset);}}"],
      maxOutputBytes: 1024,
    });
    const receipt = await executeGate(request(value));
    expect(receipt.result.status).toBe("passed");
    expect(receipt.artifact).toEqual({ file: "output.bin", sha256: digest(Buffer.alloc(1024, 120)), capturedBytes: 1024, totalBytes: 2 * 1024 * 1024, truncated: true });
    expect(isSuccessfulProof(receipt, receipt.after)).toBe(false);
    const store = await storeFor(value);
    expect((await stat(join(store.root, "runs", receipt.plan.executionId, "artifacts", "output.bin"))).size).toBe(1024);
    expect((await store.read(receipt.plan.executionId)).artifact).toEqual(receipt.artifact);
  } finally { await rm(value.directory, { recursive: true, force: true }); }
});

test("a configured timeout terminates and reaps the real process, recording no successful proof", async () => {
  const value = await fixture();
  try {
    await configure(value, { args: ["-e", "process.on('SIGTERM',()=>{}); setInterval(()=>{},1000)"], timeoutMs: 100 });
    const receipt = await deadline(executeGate(request(value)));
    expect(receipt.result.status).toBe("incomplete");
    expect(receipt.result.reason).toBe("timeout");
    expect(receipt.result.descendantsStopped).toBe(true);
    expect(receipt.durationMs).toBeLessThan(10_000);
    expect(isSuccessfulProof(receipt, receipt.after)).toBe(false);
    expect((await (await storeFor(value)).read(receipt.plan.executionId)).result).toEqual(receipt.result);
  } finally { await rm(value.directory, { recursive: true, force: true }); }
}, 15_000);

test("AbortSignal cancellation waits for an IPC-ready owned descendant and leaves neither process alive", async () => {
  const value = await fixture();
  const ipc = await barrier(value);
  const abort = new AbortController();
  let execution: Promise<Receipt> | undefined;
  let rootPid: number | undefined;
  try {
    await configureTree(value, ipc.path);
    execution = executeGate(request(value, abort.signal));
    const [root, descendant] = await deadline(Promise.all([ipc.root, ipc.descendant]));
    rootPid = root.pid;
    abort.abort();
    const receipt = await deadline(execution);
    expect(receipt.result.status).toBe("cancelled");
    expect(receipt.result.descendantsStopped).toBe(true);
    expect(stopped(root.pid)).toBe(true);
    expect(stopped(descendant.pid)).toBe(true);
    expect((await (await storeFor(value)).read(receipt.plan.executionId)).result.status).toBe("cancelled");
    expect(isSuccessfulProof(receipt, receipt.after)).toBe(false);
  } finally {
    abort.abort();
    if (execution !== undefined) await deadline(execution).catch(() => {});
    cleanOwnedGroup(rootPid);
    await ipc.close();
    await rm(value.directory, { recursive: true, force: true });
  }
}, 20_000);

test("an input changed after the IPC launch barrier makes the completed receipt unknown", async () => {
  const value = await fixture();
  const ipc = await barrier(value);
  const abort = new AbortController();
  let execution: Promise<Receipt> | undefined;
  try {
    await writeFile(join(value.repositoryRoot, "wait.cjs"), `
      const net = require('node:net');
      const socket = net.createConnection(process.argv[2], () => socket.write('root:' + process.pid + '\\n'));
      socket.once('data', () => { process.stdout.write('completed'); socket.end(); });
    `);
    await configure(value, { args: ["wait.cjs", ipc.path] });
    execution = executeGate(request(value, abort.signal));
    const ready = await deadline(ipc.root);
    await writeFile(join(value.repositoryRoot, "input.txt"), "changed during execution\n");
    ready.socket.end("continue\n");
    const receipt = await deadline(execution);
    expect(receipt.result.status).toBe("passed");
    expect(receipt.applicability).toBe("unknown");
    expect(receipt.applicabilityReason).toBe("inputs-changed-during-execution");
    expect(isSuccessfulProof(receipt, receipt.after)).toBe(false);
  } finally {
    abort.abort();
    if (execution !== undefined) await deadline(execution).catch(() => {});
    await ipc.close();
    await rm(value.directory, { recursive: true, force: true });
  }
}, 20_000);

test("standalone CLI keeps metacharacters inert and secret-bearing output out of its public JSON", async () => {
  const value = await fixture();
  try {
    const secret = "private-output-credential-like-value-93d7";
    const argumentsAsData = ["; touch SHELL-RAN", "$(touch SHELL-RAN)", "`touch SHELL-RAN`", `\u001b[31m${secret}`];
    await writeFile(join(value.repositoryRoot, "argv.cjs"), "process.stdout.write(JSON.stringify(process.argv.slice(2)))");
    await configure(value, { args: ["argv.cjs", ...argumentsAsData] });
    const result = await invokeCLI(value, "run", ["--gate", "check"]);
    expect(result.code).toBe(0);
    const receipt = JSON.parse(result.stdout) as PublicReceipt;
    expect(receipt.status).toBe("passed");
    expect(receipt.proof).toBe(true);
    expect(Object.keys(receipt).sort()).toEqual(["applicability", "executionId", "output", "proof", "status"]);
    for (const forbidden of [secret, value.repositoryRoot, value.dataRoot, "touch", "\u001b", "argv.cjs", CONTEXT.accountId]) expect((result.stdout + result.stderr).includes(forbidden)).toBe(false);
    expect(await stat(join(value.repositoryRoot, "SHELL-RAN")).then(() => true, () => false)).toBe(false);
    const store = await storeFor(value);
    const privateOutput = await readFile(join(store.root, "runs", receipt.executionId, "artifacts", "output.bin"), "utf8");
    expect(JSON.parse(privateOutput)).toEqual(argumentsAsData);
    expect(receipt.output.sha256).toBe(digest(privateOutput));
    const unsupported = await invokeCLI(value, "run", ["--gate", "check"], "omp");
    expect(unsupported.code).toBe(2);
    expect(unsupported.stdout).toBe("");
  } finally { await rm(value.directory, { recursive: true, force: true }); }
}, 20_000);

test("show and list recapture current scope rather than replay saved freshness; reconcile is usable", async () => {
  const value = await fixture();
  try {
    await configure(value);
    const run = await invokeCLI(value, "run", ["--gate", "check"]);
    expect(run.code).toBe(0);
    const receipt = JSON.parse(run.stdout) as PublicReceipt;
    await writeFile(join(value.repositoryRoot, "unrelated.txt"), "outside declared scope");
    const current = await invokeCLI(value, "show", ["--id", receipt.executionId]);
    expect((JSON.parse(current.stdout) as PublicReceipt).applicability).toBe("current");
    await writeFile(join(value.repositoryRoot, "input.txt"), "new covered input\n");
    const show = await invokeCLI(value, "show", ["--id", receipt.executionId]);
    expect(show.code).toBe(0);
    expect((JSON.parse(show.stdout) as PublicReceipt).applicability).toBe("stale");
    expect((JSON.parse(show.stdout) as PublicReceipt).proof).toBe(false);
    const list = await invokeCLI(value, "list");
    expect(list.code).toBe(0);
    const listed = JSON.parse(list.stdout) as PublicReceipt[];
    expect(listed.length).toBe(1);
    expect(listed[0]?.applicability).toBe("stale");
    expect(listed[0]?.proof).toBe(false);
    const reconciled = await invokeCLI(value, "reconcile");
    expect(reconciled.code).toBe(0);
    expect(JSON.parse(reconciled.stdout)).toEqual([]);
    await rm(join(value.repositoryRoot, "receipts.json"));
    const unknown = await invokeCLI(value, "show", ["--id", receipt.executionId]);
    expect(unknown.code).toBe(0);
    expect((JSON.parse(unknown.stdout) as PublicReceipt).applicability).toBe("unknown");
    expect((JSON.parse(unknown.stdout) as PublicReceipt).proof).toBe(false);
  } finally { await rm(value.directory, { recursive: true, force: true }); }
}, 20_000);

test("CLI exit codes distinguish nonzero failure, launch failure and a truncated non-proof", async () => {
  const value = await fixture();
  try {
    await configure(value, { args: ["-e", "process.exitCode=7"] });
    const failed = await invokeCLI(value, "run", ["--gate", "check"]);
    expect(failed.code).toBe(1);
    expect((JSON.parse(failed.stdout) as PublicReceipt).status).toBe("failed");
    await configure(value, { executable: "./not-installed", args: [] });
    const missing = await invokeCLI(value, "run", ["--gate", "check"]);
    expect(missing.code).toBe(2);
    expect((JSON.parse(missing.stdout) as PublicReceipt).status).toBe("incomplete");
    await configure(value, { args: ["-e", "process.stdout.write('too much output')"], maxOutputBytes: 1 });
    const truncated = await invokeCLI(value, "run", ["--gate", "check"]);
    expect(truncated.code).toBe(2);
    expect((JSON.parse(truncated.stdout) as PublicReceipt).status).toBe("passed");
    expect((JSON.parse(truncated.stdout) as PublicReceipt).proof).toBe(false);
    expect((JSON.parse(truncated.stdout) as PublicReceipt).output.truncated).toBe(true);
  } finally { await rm(value.directory, { recursive: true, force: true }); }
}, 20_000);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  test(`CLI ${signal} waits for owned descendant cleanup and durably reports cancellation`, async () => {
    const value = await fixture();
    const ipc = await barrier(value);
    let rootPid: number | undefined;
    let running: { child: ChildProcess; completed: Promise<CliResult> } | undefined;
    try {
      await configureTree(value, ipc.path);
      running = startCLI(value, "run", ["--gate", "check"]);
      const [root, descendant] = await deadline(Promise.all([ipc.root, ipc.descendant]));
      rootPid = root.pid;
      running.child.kill(signal);
      const result = await deadline(running.completed);
      expect(result.code).toBe(signal === "SIGINT" ? 130 : 143);
      expect(result.signal).toBeNull();
      expect(result.stderr).toBe("");
      const receipt = JSON.parse(result.stdout) as PublicReceipt;
      expect(receipt.status).toBe("cancelled");
      expect(receipt.proof).toBe(false);
      expect(stopped(root.pid)).toBe(true);
      expect(stopped(descendant.pid)).toBe(true);
      const saved = await (await storeFor(value)).read(receipt.executionId);
      expect(saved.result.status).toBe("cancelled");
      expect(saved.result.descendantsStopped).toBe(true);
    } finally {
      if (running !== undefined && running.child.exitCode === null && running.child.signalCode === null) {
        running.child.kill("SIGTERM");
        try { await deadline(running.completed); } catch { running.child.kill("SIGKILL"); }
      }
      cleanOwnedGroup(rootPid);
      await ipc.close();
      await rm(value.directory, { recursive: true, force: true });
    }
  }, 20_000);
}
