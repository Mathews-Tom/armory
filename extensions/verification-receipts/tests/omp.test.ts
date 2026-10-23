import { expect, spyOn, test } from "bun:test";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext, RegisteredCommand } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { chmod, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import type { Socket } from "node:net";
import { join } from "node:path";
import verificationReceipts from "../omp/index.ts";
import type { Configuration, Context, Gate } from "../core/index.ts";
import type { ReceiptProjection } from "../helpers/evidence.ts";
import { resolveRepository } from "../helpers/scope.ts";
import { createStore } from "../helpers/storage.ts";

interface Fixture { directory: string; repositoryRoot: string; dataRoot: string; }
type Observation = { state: string } | ReceiptProjection | { receipts: ReceiptProjection[] } | { error: string };
type Lifecycle = (event: { type: string }, ctx: ExtensionContext) => void | Promise<void>;
interface CommandInfo { name: string; description?: string; source: "extension" | "prompt" | "skill"; }

async function deadline<T>(promise: Promise<T>): Promise<T> {
  // Real OS process/IPC work cannot use fake clocks. This is only a failure
  // deadline; all readiness and completion assertions await explicit signals.
  const expired = Promise.withResolvers<T>();
  const timer = setTimeout(() => expired.reject(new Error("native adapter test deadline exceeded")), 10_000);
  try { return await Promise.race([promise, expired.promise]); } finally { clearTimeout(timer); }
}

async function fixture(): Promise<Fixture> {
  const directory = await mkdtemp("/tmp/armory-vr-omp-");
  const repositoryRoot = join(directory, "repository");
  await mkdir(repositoryRoot);
  const initialized = Promise.withResolvers<undefined>();
  const git = spawn("git", ["init", "--quiet", repositoryRoot], { stdio: "ignore" });
  git.once("error", initialized.reject);
  git.once("close", (code) => code === 0 ? initialized.resolve(undefined) : initialized.reject(new Error("temporary Git initialization failed")));
  await initialized.promise;
  await writeFile(join(repositoryRoot, "input.txt"), "original input\n");
  return { directory, repositoryRoot, dataRoot: join(directory, "private-state") };
}

async function configure(value: Fixture, overrides: Partial<Gate> = {}): Promise<void> {
  const configuration: Configuration = {
    schemaVersion: 1, configId: "native-adapter-tests",
    gates: { check: {
      criterionId: "configured-check", kind: "unit", executable: process.execPath,
      args: ["-e", "process.stdout.write('private-output-SECRET\\x1b[31m')"], cwd: ".",
      timeoutMs: 15_000, maxOutputBytes: 4096, requiresCompleteOutput: true,
      scope: { paths: ["input.txt"], configPaths: [], environmentNames: [], datasetIdentity: null },
      ...overrides,
    } },
  };
  await writeFile(join(value.repositoryRoot, "receipts.json"), JSON.stringify(configuration));
}

function harness(value: Fixture, partition = { account: "private-account-SECRET", work: "private-work-SECRET" }, configured = true) {
  const flags = new Map<string, string | boolean>(configured ? [
    ["armory-receipts-repo", value.repositoryRoot], ["armory-receipts-config", "receipts.json"],
    ["armory-receipts-data-root", value.dataRoot], ["armory-receipts-account", partition.account],
    ["armory-receipts-work-context", partition.work],
  ] : []);
  const commands = new Map<string, { description?: string; handler: RegisteredCommand["handler"] }>();
  const events = new Map<string, Lifecycle>();
  const foreignCommands: CommandInfo[] = [];
  const messages: Observation[] = [];
  const widgets: { key: string; content: unknown }[] = [];
  const deliveries: unknown[] = [];
  const waiting = new Set<{ after: number; predicate: (message: Observation) => boolean; resolve: (message: Observation) => void }>();
  let forbiddenCalls = 0;
  let rejectCompletion = false;
  verificationReceipts({
    registerFlag: () => undefined,
    getFlag(name: string) { return flags.get(name); },
    getCommands() {
      return [...foreignCommands, ...[...commands].map(([name, command]) => ({ name, description: command.description, source: "extension" }))];
    },
    registerCommand(name: string, command: { description?: string; handler: RegisteredCommand["handler"] }) { commands.set(name, command); },
    on(name: string, handler: Lifecycle) { events.set(name, handler); },
    sendMessage(message: { customType: string; content: string; display: boolean }, options: unknown) {
      deliveries.push(options);
      const observation = JSON.parse(message.content) as Observation;
      if (rejectCompletion && "executionId" in observation) {
        rejectCompletion = false;
        throw new Error(`private-output-SECRET at ${value.directory}`);
      }
      messages.push(observation);
      for (const item of waiting) if (messages.length > item.after && item.predicate(observation)) { waiting.delete(item); item.resolve(observation); }
    },
    sendUserMessage() { forbiddenCalls++; throw new Error("model-turn API forbidden"); },
  } as unknown as ExtensionAPI);
  function context(id = "native-session", mode: ExtensionContext["mode"] = "print", hasUI = false): ExtensionCommandContext {
    return { mode, hasUI, cwd: "/deliberately-not-the-verified-repository", sessionManager: { getSessionId: () => id },
      ui: { setWidget(key: string, content: unknown) { widgets.push({ key, content }); } },
    } as unknown as ExtensionCommandContext;
  }
  return {
    flags, commands, foreignCommands, messages, widgets, deliveries, context,
    failNextCompletion() { rejectCompletion = true; },
    async emit(name: string, ctx: ExtensionContext = context()): Promise<void> {
      const handler = events.get(name);
      if (handler === undefined) throw new Error("missing lifecycle handler");
      await handler({ type: name }, ctx);
    },
    async command(name: string, args = "", ctx = context()): Promise<void> {
      const command = commands.get(name);
      if (command === undefined) throw new Error("missing native command");
      await command.handler(args, ctx);
    },
    next(predicate: (message: Observation) => boolean, after = messages.length): Promise<Observation> {
      const observed = messages.slice(after).find(predicate);
      if (observed !== undefined) return Promise.resolve(observed);
      const pending = Promise.withResolvers<Observation>();
      waiting.add({ after, predicate, resolve: pending.resolve });
      return pending.promise;
    },
    assertSafe() {
      expect(forbiddenCalls).toBe(0);
      for (const delivery of deliveries) {
        const options = delivery as { triggerTurn?: unknown; deliverAs?: unknown };
        expect(options.triggerTurn).toBe(false);
        expect(options.deliverAs).not.toBe("aside");
      }
      const rendered = JSON.stringify({ messages, widgets });
      for (const secret of [value.directory, partition.account, partition.work, "private-output-SECRET", "receipts.json", "root.cjs", "process.stdout", "\\u001b"]) expect(rendered).not.toContain(secret);
    },
    scope(id = "native-session"): Context { return { host: "omp", sessionId: id, accountId: partition.account, workContext: partition.work }; },
  };
}

function receiptList(value: Observation | undefined): ReceiptProjection[] {
  if (value === undefined || !("receipts" in value)) throw new Error("expected saved evidence observation");
  return value.receipts;
}

async function storeFor(value: Fixture, context: Context) {
  return await createStore(value.dataRoot, await resolveRepository(value.repositoryRoot), context);
}

async function barrier(value: Fixture, expectedTrees = 1) {
  const root = Promise.withResolvers<{ pid: number; socket: Socket }>();
  const descendant = Promise.withResolvers<{ pid: number; socket: Socket }>();
  const all = Promise.withResolvers<{ roots: number[]; descendants: number[] }>();
  const roots: number[] = [];
  const descendants: number[] = [];
  const sockets = new Set<Socket>();
  const path = join(value.directory, "ready.sock");
  const server = createServer((socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
    socket.on("error", () => { /* Cleanup can close an already-stopping peer. */ });
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
      (match[1] === "root" ? roots : descendants).push(pid);
      if (roots.length === expectedTrees && descendants.length === expectedTrees) all.resolve({ roots, descendants });
    };
    socket.on("data", receive);
  });
  const listening = Promise.withResolvers<undefined>();
  server.once("error", listening.reject);
  server.listen(path, () => listening.resolve(undefined));
  await listening.promise;
  return { path, root: root.promise, descendant: descendant.promise, all: all.promise,
    async close(): Promise<void> {
      for (const socket of sockets) socket.destroy();
      const closed = Promise.withResolvers<undefined>();
      server.close((error) => error ? closed.reject(error) : closed.resolve(undefined));
      await closed.promise;
    },
  };
}

async function configureTree(value: Fixture, path: string): Promise<void> {
  await writeFile(join(value.repositoryRoot, "descendant.cjs"), `
    const net = require('node:net');
    setInterval(() => {}, 1000);
    net.createConnection(process.argv[2], function () { this.end('descendant:' + process.pid + '\\n'); });
  `);
  await writeFile(join(value.repositoryRoot, "root.cjs"), `
    const net = require('node:net');
    const { spawn } = require('node:child_process');
    const child = spawn(process.execPath, ['descendant.cjs', process.argv[2]], { stdio: 'ignore' });
    let stopping = false;
    const keepAlive = setInterval(() => {}, 1000);
    child.once('exit', () => { if (stopping) process.exit(0); });
    process.on('SIGTERM', () => {
      stopping = true; clearInterval(keepAlive);
      if (child.exitCode !== null || child.signalCode !== null) process.exit(0);
    });
    net.createConnection(process.argv[2], function () { this.end('root:' + process.pid + '\\n'); });
  `);
  await configure(value, { args: ["root.cjs", path] });
}

function stopped(pid: number): boolean {
  try { process.kill(pid, 0); return false; } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ESRCH") return true;
    throw error;
  }
}

test("command name collisions fail closed before configured execution or state creation", async () => {
  const value = await fixture();
  const native = harness(value);
  try {
    await configure(value, { args: ["-e", "require('node:fs').writeFileSync('spawned', 'unsafe')"] });
    const registrationContext = { mode: "print", hasUI: false } as ExtensionContext;
    native.foreignCommands.push({ name: "armory-evidence", source: "prompt" });
    await expect(native.emit("session_start", registrationContext)).rejects.toThrow();
    expect(native.commands.size).toBe(0);
    native.foreignCommands.length = 0;
    await native.emit("session_start", registrationContext);
    await native.emit("session_start", registrationContext);
    native.foreignCommands.push({ name: "armory-verify", source: "skill" });
    await expect(native.emit("session_start", registrationContext)).rejects.toThrow();
    await native.command("armory-verify", "check");
    await native.command("armory-evidence");
    await expect(stat(value.dataRoot)).rejects.toHaveProperty("code", "ENOENT");
    await expect(stat(join(value.repositoryRoot, "spawned"))).rejects.toHaveProperty("code", "ENOENT");
    native.assertSafe();
  } finally { await native.emit("session_shutdown"); await rm(value.directory, { recursive: true, force: true }); }
});

test("invalid arguments and missing explicit flags have no filesystem or configured-command effects", async () => {
  const value = await fixture();
  const native = harness(value, undefined, false);
  try {
    await configure(value, { args: ["-e", "require('node:fs').writeFileSync('spawned', 'unsafe')"] });
    await native.emit("session_start");
    for (const args of ["", "check extra", "check\nextra"]) await native.command("armory-verify", args);
    for (const args of ["unknown", "wait extra", "cancel extra"]) await native.command("armory-evidence", args);
    expect(native.messages).toEqual(Array.from({ length: 6 }, () => ({ error: "invalid-arguments" })));
    await native.command("armory-verify", "check");
    await native.command("armory-evidence");
    expect(native.messages.slice(-2)).toEqual([{ error: "invalid-configuration" }, { error: "invalid-configuration" }]);
    await expect(stat(value.dataRoot)).rejects.toHaveProperty("code", "ENOENT");
    await expect(stat(join(value.repositoryRoot, "spawned"))).rejects.toHaveProperty("code", "ENOENT");
    native.assertSafe();
  } finally { await native.emit("session_shutdown"); await rm(value.directory, { recursive: true, force: true }); }
});

test("owned asynchronous success and failure publish only safe actual text and guarded TUI widgets", async () => {
  const value = await fixture();
  const native = harness(value);
  try {
    await configure(value);
    await native.emit("session_start");
    const ctx = native.context("actual-session", "tui", true);
    await native.command("armory-verify", "check", ctx);
    expect(native.messages[0]).toEqual({ state: "running" });
    await native.command("armory-evidence", "wait", ctx);
    const receipt = receiptList(native.messages.at(-1))[0];
    expect(receipt).toMatchObject({ status: "passed", applicability: "current", proof: true });
    expect(Object.keys(receipt ?? {}).sort()).toEqual(["applicability", "executionId", "output", "proof", "status"]);
    expect(receipt?.output.sha256).toBe(createHash("sha256").update("private-output-SECRET\x1b[31m").digest("hex"));
    const store = await storeFor(value, native.scope("actual-session"));
    const saved = await store.read(receipt?.executionId ?? "");
    expect(saved.plan.context.sessionId).toBe("actual-session");
    expect(saved.plan.context.host).toBe("omp");
    expect(await readFile(join(store.root, "runs", saved.plan.executionId, "artifacts", "output.bin"), "utf8")).toBe("private-output-SECRET\x1b[31m");
    expect((await stat(store.root)).mode & 0o777).toBe(0o700);
    expect((await stat(join(store.root, "receipts", `${saved.plan.executionId}.json`))).mode & 0o777).toBe(0o600);
    await configure(value, { args: ["-e", "process.stderr.write('private-output-SECRET'); process.exit(7)"] });
    const widgetsBefore = native.widgets.length;
    await native.command("armory-verify", "check", native.context("actual-session", "rpc", true));
    await native.command("armory-evidence", "wait", native.context("actual-session", "rpc", true));
    expect(receiptList(native.messages.at(-1)).some((item) => item.status === "failed" && !item.proof)).toBe(true);
    expect(native.widgets.length).toBe(widgetsBefore);
    await native.command("armory-evidence", "", native.context("actual-session", "tui", false));
    expect(native.widgets.length).toBe(widgetsBefore);
    native.assertSafe();
  } finally { await native.emit("session_shutdown"); await rm(value.directory, { recursive: true, force: true }); }
});

test("cancel waits for the owned IPC-ready root and descendant, blocks overlap, and releases session state", async () => {
  const value = await fixture();
  const native = harness(value);
  const ipc = await barrier(value);
  try {
    await configureTree(value, ipc.path);
    await native.emit("session_start");
    await native.command("armory-verify", "check");
    const [root, child] = await deadline(Promise.all([ipc.root, ipc.descendant]));
    await native.command("armory-verify", "check");
    expect(native.messages.at(-1)).toEqual({ error: "verification-running" });
    await native.command("armory-evidence");
    expect(receiptList(native.messages.at(-1))).toEqual([]);
    await deadline(native.command("armory-evidence", "cancel"));
    expect(stopped(root.pid)).toBe(true);
    expect(stopped(child.pid)).toBe(true);
    const saved = receiptList(native.messages.at(-1));
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ status: "cancelled", proof: false });
    expect((await (await storeFor(value, native.scope())).list())[0]?.result.status).toBe("cancelled");
    await configure(value);
    await native.command("armory-verify", "check");
    await native.command("armory-evidence", "wait");
    expect(receiptList(native.messages.at(-1)).some((receipt) => receipt.status === "passed" && receipt.proof)).toBe(true);
    native.assertSafe();
  } finally { await native.emit("session_shutdown"); await ipc.close(); await rm(value.directory, { recursive: true, force: true }); }
}, 25_000);

test("session shutdown and switch await cancellation without crossing independent factory ownership or publishing into the next session", async () => {
  const first = await fixture();
  const second = await fixture();
  const a = harness(first);
  const b = harness(second);
  const aIpc = await barrier(first);
  const bIpc = await barrier(second);
  try {
    await configureTree(first, aIpc.path);
    await configureTree(second, bIpc.path);
    await a.emit("session_start");
    await b.emit("session_start");
    await a.command("armory-verify", "check");
    await b.command("armory-verify", "check");
    const [aRoot, aChild, bRoot, bChild] = await deadline(Promise.all([aIpc.root, aIpc.descendant, bIpc.root, bIpc.descendant]));
    const aCount = a.messages.length;
    await deadline(a.emit("session_shutdown"));
    expect(stopped(aRoot.pid)).toBe(true);
    expect(stopped(aChild.pid)).toBe(true);
    expect(stopped(bRoot.pid)).toBe(false);
    expect(stopped(bChild.pid)).toBe(false);
    expect(a.messages.length).toBe(aCount);
    await a.command("armory-verify", "check");
    expect(a.messages.at(-1)).toEqual({ error: "session-unavailable" });
    const wait = b.command("armory-evidence", "wait");
    const bCount = b.messages.length;
    await deadline(b.emit("session_switch", b.context("next-session")));
    await deadline(wait);
    expect(stopped(bRoot.pid)).toBe(true);
    expect(stopped(bChild.pid)).toBe(true);
    expect(b.messages.length).toBe(bCount);
    await b.command("armory-evidence", "", b.context("next-session"));
    expect(receiptList(b.messages.at(-1))[0]).toMatchObject({ status: "cancelled", proof: false });
    expect((await (await storeFor(first, a.scope())).list())[0]?.result.status).toBe("cancelled");
    a.assertSafe(); b.assertSafe();
  } finally {
    await a.emit("session_shutdown"); await b.emit("session_shutdown");
    await aIpc.close(); await bIpc.close();
    await rm(first.directory, { recursive: true, force: true }); await rm(second.directory, { recursive: true, force: true });
  }
}, 25_000);

test("new sessions reopen private saved evidence, recompute scoped freshness, and reject altered artifacts without leaking errors", async () => {
  const value = await fixture();
  const original = harness(value);
  const reopened = harness(value);
  try {
    await configure(value);
    await original.emit("session_start");
    await original.command("armory-verify", "check");
    await original.command("armory-evidence", "wait");
    const initial = receiptList(original.messages.at(-1));
    await original.emit("session_shutdown");
    await reopened.emit("session_start");
    const ctx = reopened.context("reopened-session");
    await reopened.command("armory-evidence", "", ctx);
    expect(receiptList(reopened.messages.at(-1))).toEqual(initial);
    await writeFile(join(value.repositoryRoot, "unrelated.txt"), "not covered\n");
    await reopened.command("armory-evidence", "", ctx);
    expect(receiptList(reopened.messages.at(-1))[0]).toMatchObject({ applicability: "current", proof: true });
    await writeFile(join(value.repositoryRoot, "input.txt"), "covered edit\n");
    await reopened.command("armory-evidence", "", ctx);
    expect(receiptList(reopened.messages.at(-1))[0]).toMatchObject({ applicability: "stale", proof: false });
    await rm(join(value.repositoryRoot, "receipts.json"));
    await reopened.command("armory-evidence", "", ctx);
    expect(receiptList(reopened.messages.at(-1))[0]).toMatchObject({ applicability: "unknown", proof: false });
    const store = await storeFor(value, reopened.scope("reopened-session"));
    const artifact = join(store.root, "runs", initial[0]?.executionId ?? "", "artifacts", "output.bin");
    await writeFile(artifact, "private-output-SECRET tamper");
    await reopened.command("armory-evidence", "", ctx);
    expect(reopened.messages.at(-1)).toEqual({ error: "operation-failed" });
    original.assertSafe(); reopened.assertSafe();
  } finally { await original.emit("session_shutdown"); await reopened.emit("session_shutdown"); await rm(value.directory, { recursive: true, force: true }); }
});

test("account, work-context, repository and host remain separate while session changes share only their intended evidence partition", async () => {
  const value = await fixture();
  const otherRepository = await fixture();
  const owner = harness(value);
  const others = [harness(value, { account: "different-account", work: "private-work-SECRET" }),
    harness(value, { account: "private-account-SECRET", work: "different-work" }),
    harness({ ...otherRepository, dataRoot: value.dataRoot })];
  try {
    await configure(value);
    await owner.emit("session_start");
    await owner.command("armory-verify", "check");
    await owner.command("armory-evidence", "wait");
    for (const other of others) {
      await other.emit("session_start");
      await other.command("armory-evidence");
      expect(receiptList(other.messages.at(-1))).toEqual([]);
      other.assertSafe();
    }
    const standalone = await storeFor(value, { ...owner.scope(), host: "standalone" });
    expect(await standalone.list()).toEqual([]);
    const own = await storeFor(value, owner.scope());
    expect(await own.list()).toHaveLength(1);
    await chmod(own.root, 0o755);
    await owner.command("armory-evidence");
    expect(owner.messages.at(-1)).toEqual({ error: "operation-failed" });
    expect((await stat(own.root)).mode & 0o777).toBe(0o755);
    owner.assertSafe();
  } finally {
    await owner.emit("session_shutdown"); for (const other of others) await other.emit("session_shutdown");
    await rm(value.directory, { recursive: true, force: true }); await rm(otherRepository.directory, { recursive: true, force: true });
  }
});

test("a configured gate that changes covered inputs during execution stays unknown even after the original content returns", async () => {
  const value = await fixture();
  const native = harness(value);
  const ipc = await barrier(value);
  try {
    await writeFile(join(value.repositoryRoot, "root.cjs"), `
      const net = require('node:net');
      const socket = net.createConnection(process.argv[2], () => socket.write('root:' + process.pid + '\\n'));
      socket.on('data', () => socket.end());
    `);
    await configure(value, { args: ["root.cjs", ipc.path] });
    await native.emit("session_start");
    await native.command("armory-verify", "check");
    const root = await deadline(ipc.root);
    await writeFile(join(value.repositoryRoot, "input.txt"), "changed during verification\n");
    root.socket.end("finish\n");
    await deadline(native.command("armory-evidence", "wait"));
    expect(receiptList(native.messages.at(-1))[0]).toMatchObject({ status: "passed", applicability: "unknown", proof: false });
    await writeFile(join(value.repositoryRoot, "input.txt"), "original input\n");
    await native.command("armory-evidence");
    expect(receiptList(native.messages.at(-1))[0]).toMatchObject({ applicability: "unknown", proof: false });
    native.assertSafe();
  } finally { await native.emit("session_shutdown"); await ipc.close(); await rm(value.directory, { recursive: true, force: true }); }
}, 20_000);

test("unknown configured gates do not execute arbitrary text and report only a stable error", async () => {
  const value = await fixture();
  const native = harness(value);
  try {
    await configure(value);
    await native.emit("session_start");
    const failed = native.next((message) => "error" in message && message.error === "operation-failed");
    await native.command("armory-verify", "unknown;touch-sentinel");
    await deadline(failed);
    expect(native.messages).toEqual([{ state: "running" }, { error: "operation-failed" }]);
    await expect(stat(value.dataRoot)).rejects.toHaveProperty("code", "ENOENT");
    native.assertSafe();
  } finally { await native.emit("session_shutdown"); await rm(value.directory, { recursive: true, force: true }); }
});

test("lifecycle cancellation awaits every session task owned by one factory, not just the last active session", async () => {
  const value = await fixture();
  const native = harness(value);
  const ipc = await barrier(value, 2);
  try {
    await configureTree(value, ipc.path);
    await native.emit("session_start");
    await native.command("armory-verify", "check", native.context("first-session"));
    await native.command("armory-verify", "check", native.context("second-session"));
    const ready = await deadline(ipc.all);
    const before = native.messages.length;
    await deadline(native.emit("session_shutdown"));
    for (const pid of [...ready.roots, ...ready.descendants]) expect(stopped(pid)).toBe(true);
    expect(native.messages.length).toBe(before);
    const receipts = await (await storeFor(value, native.scope())).list();
    expect(receipts).toHaveLength(2);
    expect(new Set(receipts.map((receipt) => receipt.plan.context.sessionId))).toEqual(new Set(["first-session", "second-session"]));
    expect(receipts.every((receipt) => receipt.result.status === "cancelled" && receipt.result.descendantsStopped)).toBe(true);
    native.assertSafe();
  } finally { await native.emit("session_shutdown"); await ipc.close(); await rm(value.directory, { recursive: true, force: true }); }
}, 25_000);

test("immediate cancel retains ownership before asynchronous preparation and prevents a configured spawn", async () => {
  const value = await fixture();
  const native = harness(value);
  try {
    await configure(value, { args: ["-e", "require('node:fs').writeFileSync('spawned', 'unexpected')"] });
    await native.emit("session_start");
    await native.command("armory-verify", "check");
    await deadline(native.command("armory-evidence", "cancel"));
    expect(receiptList(native.messages.at(-1))[0]).toMatchObject({ status: "cancelled", proof: false });
    await expect(stat(join(value.repositoryRoot, "spawned"))).rejects.toHaveProperty("code", "ENOENT");
    native.assertSafe();
  } finally { await native.emit("session_shutdown"); await rm(value.directory, { recursive: true, force: true }); }
});

test("a failed native completion publication reports sanitized stderr while preserving receipts and releasing ownership", async () => {
  const value = await fixture();
  const native = harness(value);
  const diagnostics: string[] = [];
  const stderr = spyOn(process.stderr, "write").mockImplementation((chunk) => { diagnostics.push(String(chunk)); return true; });
  try {
    await configure(value);
    await native.emit("session_start");
    native.failNextCompletion();
    await native.command("armory-verify", "check");
    await deadline(native.command("armory-evidence", "wait"));
    expect(diagnostics.map((line) => JSON.parse(line) as unknown)).toContainEqual({ error: "publication-failed" });
    const first = receiptList(native.messages.at(-1))[0];
    expect(first).toMatchObject({ status: "passed", proof: true });
    const store = await storeFor(value, native.scope());
    expect((await store.read(first?.executionId ?? "")).result.status).toBe("passed");
    await native.command("armory-verify", "check");
    await deadline(native.command("armory-evidence", "wait"));
    const receipts = receiptList(native.messages.at(-1));
    expect(receipts.some((receipt) => receipt.executionId === first?.executionId)).toBe(true);
    const second = receipts.find((receipt) => receipt.executionId !== first?.executionId);
    expect(second).toMatchObject({ status: "passed", proof: true });
    expect((await store.read(second?.executionId ?? "")).result.status).toBe("passed");
    const diagnosticText = diagnostics.join("");
    expect(diagnosticText).not.toContain(value.directory);
    expect(diagnosticText).not.toContain("private-output-SECRET");
    native.assertSafe();
  } finally { stderr.mockRestore(); await native.emit("session_shutdown"); await rm(value.directory, { recursive: true, force: true }); }
});
