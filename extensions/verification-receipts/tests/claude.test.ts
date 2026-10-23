import { expect, test } from "bun:test";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import type { Socket } from "node:net";
import { join } from "node:path";
import { register } from "../claude-code/register.ts";
import { parseNativeObservation } from "../core/claude-protocol.ts";
import type { NativeReceiptProjection } from "../core/claude-protocol.ts";
import type { Configuration, Context, Gate } from "../core/index.ts";
import { resolveRepository } from "../helpers/scope.ts";
import { createStore } from "../helpers/storage.ts";

interface Fixture { root: string; repo: string; data: string; plugin: string; }
interface Chunk { stream: "stdout" | "stderr"; text: string; }
interface End { code: number | null; signal: string | null; }
type Stream = AsyncGenerator<Chunk, End> & { result: Promise<End> };
interface Reader { resolve(value: IteratorResult<Chunk, End>): void; reject(reason?: unknown): void; }
type Hook = ($: unknown, event: unknown, next: (event: unknown) => Promise<unknown>) => Promise<unknown>;
type Reply = Record<string, unknown>;

async function deadline<T>(promise: Promise<T>): Promise<T> {
  // Only a failure deadline for real OS subprocess/IPC work; readiness and
  // completion use explicit signals, not timing guesses or simulated clocks.
  const failure = Promise.withResolvers<T>();
  const timer = setTimeout(() => failure.reject(new Error("Claude adapter test deadline exceeded")), 15_000);
  try { return await Promise.race([promise, failure.promise]); } finally { clearTimeout(timer); }
}
async function command(argv: readonly string[], cwd?: string) {
  const child = spawn(argv[0] ?? "", argv.slice(1), { cwd, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  const done = Promise.withResolvers<number>();
  child.stdout.on("data", (part: Buffer) => { stdout += part.toString(); });
  child.stderr.on("data", (part: Buffer) => { stderr += part.toString(); });
  child.once("error", done.reject);
  child.once("close", (code) => done.resolve(code ?? 1));
  return { exitCode: await done.promise, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false };
}
async function fixture(): Promise<Fixture> {
  const root = await mkdtemp("/tmp/armory-vr-claude-");
  const repo = join(root, "repository ; inert");
  const plugin = join(root, "detached-plugin");
  await mkdir(repo);
  await mkdir(join(plugin, "helpers"), { recursive: true });
  expect((await command(["git", "init", "--quiet", repo])).exitCode).toBe(0);
  await writeFile(join(repo, "input.txt"), "original\n");
  const built = await Bun.build({
    entrypoints: [new URL("../helpers/claude-cli.ts", import.meta.url).pathname],
    outdir: join(plugin, "helpers"), naming: "claude-cli.js", target: "bun",
  });
  if (!built.success) throw new Error("test helper bundle failed");
  return { root, repo, plugin, data: join(root, "private-state") };
}
async function configure(value: Fixture, gates: Record<string, Partial<Gate>> = { check: {} }): Promise<void> {
  const configuration: Configuration = { schemaVersion: 1, configId: "claude-adapter-tests", gates: {} };
  for (const [id, overrides] of Object.entries(gates)) configuration.gates[id] = {
    criterionId: `configured-${id}`, kind: "unit", executable: process.execPath,
    args: ["-e", "process.stdout.write('PRIVATE-SECRET\\x1b[31m')"], cwd: ".", timeoutMs: 12_000,
    maxOutputBytes: 4096, requiresCompleteOutput: true,
    scope: { paths: ["input.txt"], configPaths: [], environmentNames: [], datasetIdentity: null }, ...overrides,
  };
  await writeFile(join(value.repo, "receipts.json"), JSON.stringify(configuration));
}

// A recording boundary, not an implementation of the native engine: each effect
// really launches the bundled helper/runner and uses its private durable store.
// return() here delivers SIGTERM. That is a controlled test fixture, NOT a claim
// about the signal/grace used by Claude's actual engine (qualified separately).
function native(value: Fixture) {
  const env = new Map<string, string>([
    ["ARMORY_RECEIPTS_REPO", value.repo], ["ARMORY_RECEIPTS_CONFIG", "receipts.json"],
    ["ARMORY_RECEIPTS_DATA_ROOT", value.data], ["ARMORY_RECEIPTS_ACCOUNT", "account-SECRET"],
    ["ARMORY_RECEIPTS_WORK_CONTEXT", "work-SECRET"],
  ]);
  const hooks = new Map<string, Hook>();
  const specs: { name: string; immediate?: true }[] = [];
  const calls: { kind: string; argv: readonly string[] }[] = [];
  const foreign: { name: string }[] = [];
  const outputs: string[] = [];
  const streams = new Set<Stream>();
  let session = "native-session-one";
  let selection: Promise<void> | undefined;
  let readBarrier: Promise<void> | undefined;
  let readEntered: (() => void) | undefined;
  let transform = (text: string): string => text;
  function stream(argv: readonly string[], cwd?: string): Stream {
    const child = spawn(argv[0] ?? "", argv.slice(1), { cwd, stdio: ["ignore", "pipe", "pipe"] });
    const queue: Chunk[] = [];
    const waiting: Reader[] = [];
    const completion = Promise.withResolvers<End>();
    const closed = Promise.withResolvers<End>();
    let ended: End | undefined;
    let closing = false;
    const push = (piece: Chunk): void => {
      const reader = waiting.shift();
      if (reader === undefined) queue.push(piece); else reader.resolve({ done: false, value: piece });
    };
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (text: string) => push({ stream: "stdout", text: transform(text) }));
    child.stderr.on("data", (text: string) => push({ stream: "stderr", text }));
    child.once("error", (error) => { completion.reject(error); for (const reader of waiting.splice(0)) reader.reject(error); });
    child.once("close", (code, signal) => {
      ended = { code, signal };
      closed.resolve(ended);
      if (closing) completion.reject(new Error("owned stream closed early")); else completion.resolve(ended);
      for (const reader of waiting.splice(0)) reader.resolve({ done: true, value: ended });
      streams.delete(result);
    });
    const result: Stream = {
      result: completion.promise,
      [Symbol.asyncIterator]() { return this; },
      async next() {
        const piece = queue.shift();
        if (piece !== undefined) return { done: false, value: piece };
        if (ended !== undefined) return { done: true, value: ended };
        const next = Promise.withResolvers<IteratorResult<Chunk, End>>();
        waiting.push(next);
        return await next.promise;
      },
      async return() {
        closing = true;
        if (ended === undefined) child.kill("SIGTERM");
        return { done: true, value: await closed.promise };
      },
      async throw(error: unknown) { await this.return({ code: null, signal: null }); throw error; },
      async [Symbol.asyncDispose]() { await this.return({ code: null, signal: null }); },
    };
    streams.add(result);
    return result;
  }
  const api = {
    plugin: { root: value.plugin },
    env: { async get(name: string) { await selection; return env.get(name); } },
    session: { async id() { await selection; return session; } },
    command: {
      async list() { return [...foreign, ...specs]; },
      async register(spec: { name: string; immediate?: true }) { specs.push(spec); return { command: spec.name }; },
    },
    process: {
      spawn(request: { argv: readonly string[]; cwd?: string }) { calls.push({ kind: "spawn", argv: request.argv }); return stream(request.argv, request.cwd); },
      async run(argv: readonly string[], init?: { cwd?: string }) {
        calls.push({ kind: "run", argv });
        readEntered?.(); readEntered = undefined;
        const result = await command(argv, init?.cwd);
        await readBarrier;
        return { ...result, stdout: transform(result.stdout) };
      },
    },
  };
  register(((event: string, ...rest: unknown[]) => {
    const matcher = typeof rest[0] === "object" ? rest[0] as { command: string } : undefined;
    hooks.set(matcher === undefined ? event : `${event}:${matcher.command}`, rest.at(-1) as Hook);
  }) as Parameters<typeof register>[0]);
  async function emit(event: string, input: unknown = {}): Promise<unknown> {
    const hook = hooks.get(event);
    if (hook === undefined) throw new Error("missing adapter hook");
    return await deadline(hook(api, input, async (e) => e));
  }
  return { env, specs, calls, foreign,
    setSession(id: string) { session = id; },
    holdSelection(promise?: Promise<void>) { selection = promise; },
    holdRead(promise?: Promise<void>) { readBarrier = promise; },
    nextRead(): Promise<void> { const entered = Promise.withResolvers<undefined>(); readEntered = () => entered.resolve(undefined); return entered.promise; },
    transformOutput(fn: (text: string) => string) { transform = fn; },
    start() { return emit("session.start"); },
    end(reason = "clear") { return emit("session.end", { sessionId: session, reason }); },
    async run(name: "armory-verify" | "armory-evidence", args = ""): Promise<Reply> {
      const result = await emit(`command.run:${name}`, { command: name, args }) as { text: string };
      outputs.push(result.text);
      const parsed: unknown = JSON.parse(result.text);
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("expected safe JSON text");
      return parsed as Reply;
    },
    async cleanup() { await emit("session.end", { sessionId: session, reason: "other" }); for (const child of streams) await child.return({ code: null, signal: null }); },
    assertSafe() {
      for (const text of outputs) {
        expect(text).not.toContain("SECRET"); expect(text).not.toContain(value.root); expect(text).not.toContain("\u001b");
      }
      for (const call of calls) { expect(call.argv[0]).toBe("bun"); expect(call.argv[1]).toBe(join(value.plugin, "helpers", "claude-cli.js")); }
    },
    context(): Context { return { host: "claude", sessionId: session, accountId: env.get("ARMORY_RECEIPTS_ACCOUNT") ?? "", workContext: env.get("ARMORY_RECEIPTS_WORK_CONTEXT") ?? "" }; },
  };
}
function receipts(reply: Reply): NativeReceiptProjection[] {
  const value = parseNativeObservation(reply.evidence ?? reply);
  if (!("receipts" in value)) throw new Error("expected durable receipt list");
  return value.receipts;
}
async function store(value: Fixture, context: Context) { return await createStore(value.data, await resolveRepository(value.repo), context); }

async function tree(value: Fixture) {
  const ready = Promise.withResolvers<number[]>();
  const pids: number[] = [];
  const sockets = new Set<Socket>();
  const socketPath = join(value.root, "ready.sock");
  const server = createServer((socket) => {
    sockets.add(socket); socket.once("close", () => sockets.delete(socket)); socket.on("error", () => undefined);
    socket.setEncoding("utf8"); let text = "";
    socket.on("data", (part: string) => {
      text += part;
      if (!text.endsWith("\n")) return;
      const pid = Number(text.trim());
      if (!Number.isSafeInteger(pid) || pid < 1 || pids.includes(pid)) return;
      pids.push(pid); if (pids.length === 2) ready.resolve(pids);
    });
  });
  const listening = Promise.withResolvers<undefined>();
  server.once("error", listening.reject); server.listen(socketPath, () => listening.resolve(undefined)); await listening.promise;
  await writeFile(join(value.repo, "descendant.cjs"), `const net=require('node:net');setInterval(()=>{},1000);net.createConnection(process.argv[2],function(){this.end(process.pid+'\\n')});`);
  await writeFile(join(value.repo, "root.cjs"), `
    const net=require('node:net'),{spawn}=require('node:child_process');
    const child=spawn(process.execPath,['descendant.cjs',process.argv[2]],{stdio:'ignore'});
    const alive=setInterval(()=>{},1000);let stopping=false;
    child.once('exit',()=>{if(stopping)process.exit(0)});
    process.on('SIGTERM',()=>{stopping=true;clearInterval(alive);if(child.exitCode!==null||child.signalCode!==null)process.exit(0)});
    net.createConnection(process.argv[2],function(){this.end(process.pid+'\\n')});
  `);
  await configure(value, { check: { args: ["root.cjs", socketPath] } });
  return { ready: ready.promise,
    async close() { for (const socket of sockets) socket.destroy(); const done = Promise.withResolvers<undefined>(); server.close((error) => error ? done.reject(error) : done.resolve(undefined)); await done.promise; },
  };
}
function stopped(pid: number): boolean {
  try { process.kill(pid, 0); return false; } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ESRCH") return true;
    throw error;
  }
}

test("Claude text commands execute detached real helpers, preserve status/output, and reopen scoped evidence", async () => {
  const value = await fixture(); const host = native(value);
  try {
    await configure(value, { check: {}, fail: { args: ["-e", "process.stderr.write('PRIVATE-SECRET');process.exit(7)"] } });
    await host.start(); await host.start();
    expect(await host.run("armory-verify", "check")).toEqual({ state: "running" });
    const passed = receipts(await host.run("armory-evidence", "wait"));
    expect(passed).toHaveLength(1); expect(passed[0]).toMatchObject({ status: "passed", applicability: "current", proof: true });
    expect(passed[0]?.output.sha256).toBe(createHash("sha256").update("PRIVATE-SECRET\x1b[31m").digest("hex"));
    expect(await host.run("armory-verify", "fail")).toEqual({ state: "running" });
    expect(receipts(await host.run("armory-evidence", "wait")).some((item) => item.status === "failed" && !item.proof)).toBe(true);
    const saved = await (await store(value, host.context())).list();
    expect(saved.find((item) => item.result.status === "failed")?.result.exitCode).toBe(7);
    expect(saved.every((item) => item.plan.context.host === "claude" && item.plan.context.sessionId === "native-session-one")).toBe(true);
    const reopened = native(value); await reopened.start();
    expect(receipts(await reopened.run("armory-evidence"))).toHaveLength(2);
    await writeFile(join(value.repo, "unrelated.txt"), "irrelevant");
    expect(receipts(await reopened.run("armory-evidence")).find((item) => item.status === "passed")?.proof).toBe(true);
    await writeFile(join(value.repo, "input.txt"), "changed");
    expect(receipts(await reopened.run("armory-evidence")).find((item) => item.status === "passed")).toMatchObject({ applicability: "stale", proof: false });
    await reopened.cleanup(); host.assertSafe(); reopened.assertSafe();
  } finally { await host.cleanup(); await rm(value.root, { recursive: true, force: true }); }
});

test("invalid gates, absent explicit configuration, and collisions do not execute configured side effects", async () => {
  const value = await fixture(); const host = native(value);
  try {
    await configure(value, { check: { args: ["-e", "require('node:fs').writeFileSync('spawned','unsafe')"] } });
    host.foreign.push({ name: "armory-verify" });
    await expect(host.start()).rejects.toThrow("collision");
    expect(host.specs).toHaveLength(0);
    expect(await host.run("armory-verify", "check")).toEqual({ error: "commands-unavailable" });
    const unconfigured = native(value); await unconfigured.start();
    expect(await unconfigured.run("armory-verify", "check; touch spawned")).toEqual({ error: "invalid-arguments" });
    expect(await unconfigured.run("armory-evidence", "unknown")).toEqual({ error: "invalid-arguments" });
    unconfigured.env.delete("ARMORY_RECEIPTS_ACCOUNT");
    expect(await unconfigured.run("armory-verify", "check")).toEqual({ error: "operation-failed" });
    expect(unconfigured.calls).toHaveLength(0);
    await expect(stat(join(value.repo, "spawned"))).rejects.toHaveProperty("code", "ENOENT");
    await expect(stat(value.data)).rejects.toHaveProperty("code", "ENOENT");
    await unconfigured.cleanup();
  } finally { await host.cleanup(); await rm(value.root, { recursive: true, force: true }); }
});

test("ownership is reserved before asynchronous selection and clear revokes pending launch without session.start", async () => {
  const value = await fixture(); const host = native(value); const selection = Promise.withResolvers<undefined>();
  try {
    await configure(value); await host.start(); host.holdSelection(selection.promise);
    const first = host.run("armory-verify", "check");
    expect(await host.run("armory-verify", "check")).toEqual({ state: "busy" });
    const ending = host.end("clear");
    host.setSession("native-session-two"); selection.resolve(undefined);
    expect(await first).toEqual({ error: "context-changed" }); await ending;
    expect(host.calls).toHaveLength(0);
    expect(await host.run("armory-verify", "check")).toEqual({ state: "running" });
    expect(receipts(await host.run("armory-evidence", "wait"))).toHaveLength(1);
    expect((await (await store(value, host.context())).list())[0]?.plan.context.sessionId).toBe("native-session-two");
    expect(host.specs).toHaveLength(2); host.assertSafe();
  } finally { selection.resolve(undefined); await host.cleanup(); await rm(value.root, { recursive: true, force: true }); }
});

test("controlled stream close awaits real helper descendant cleanup/durability but never advertises native cleanup proof", async () => {
  const value = await fixture(); const host = native(value); const child = await tree(value);
  try {
    await host.start(); expect(await host.run("armory-verify", "check")).toEqual({ state: "running" });
    const pids = await deadline(child.ready);
    expect(await host.run("armory-verify", "check")).toEqual({ state: "busy" });
    const cancelled = await host.run("armory-evidence", "cancel");
    expect(cancelled).toMatchObject({ state: "cancellation-unconfirmed", applicability: "unknown" });
    expect(pids.every(stopped)).toBe(true);
    expect(receipts(cancelled)).toHaveLength(1); expect(receipts(cancelled)[0]).toMatchObject({ status: "cancelled", proof: false });
    const durable = await (await store(value, host.context())).list();
    expect(durable[0]?.result).toMatchObject({ status: "cancelled", descendantsStopped: true });
    expect(await readFile(join((await store(value, host.context())).root, "receipts", `${durable[0]?.plan.executionId}.json`), "utf8")).toContain('"cancelled"');
    host.assertSafe();
  } finally { await host.cleanup(); await child.close(); await rm(value.root, { recursive: true, force: true }); }
});

test("account/config transitions cancel only original ownership and never expose its evidence to the new scope", async () => {
  const value = await fixture(); const host = native(value); const child = await tree(value);
  try {
    await host.start(); const original = host.context();
    await host.run("armory-verify", "check"); const pids = await deadline(child.ready);
    host.env.set("ARMORY_RECEIPTS_ACCOUNT", "different-account-SECRET");
    host.env.set("ARMORY_RECEIPTS_CONFIG", "different-config.json");
    expect(await host.run("armory-evidence", "cancel")).toEqual({ error: "context-changed" });
    expect(pids.every(stopped)).toBe(true);
    expect((await (await store(value, original)).list())[0]?.result.status).toBe("cancelled");
    host.assertSafe();
  } finally { await host.cleanup(); await child.close(); await rm(value.root, { recursive: true, force: true }); }
});

test("a transition while evidence is being read cannot transfer old-session authority", async () => {
  const value = await fixture(); const host = native(value); const held = Promise.withResolvers<undefined>();
  try {
    await configure(value); await host.start(); await host.run("armory-verify", "check"); await host.run("armory-evidence", "wait");
    host.holdRead(held.promise); const entered = host.nextRead(); const reading = host.run("armory-evidence");
    await deadline(entered);
    // The explicit process-effect barrier proves old-scope selection happened;
    // the result barrier prevents publication until after the resume event.
    const ending = host.end("resume"); host.setSession("resumed-native-session"); held.resolve(undefined); await ending;
    expect(await reading).toEqual({ error: "context-changed" });
    host.assertSafe();
  } finally { held.resolve(undefined); await host.cleanup(); await rm(value.root, { recursive: true, force: true }); }
});

test("unsafe/oversized helper observations are rejected rather than leaking private fields or becoming empty evidence", async () => {
  const value = await fixture(); const host = native(value);
  try {
    await configure(value); await host.start(); await host.run("armory-verify", "check"); await host.run("armory-evidence", "wait");
    host.transformOutput((text) => {
      const value = JSON.parse(text) as { receipts?: unknown[] };
      return JSON.stringify({ ...value, privatePath: "PRIVATE-SECRET" });
    });
    expect(await host.run("armory-evidence")).toEqual({ error: "operation-failed" });
    host.transformOutput(() => "x".repeat(4_194_305));
    expect(await host.run("armory-evidence")).toEqual({ error: "operation-failed" });
    host.transformOutput(() => { throw new Error(`PRIVATE-SECRET ${value.root}`); });
    expect(await host.run("armory-evidence")).toEqual({ error: "operation-failed" });
    host.transformOutput((text) => text); host.assertSafe();
  } finally { await host.cleanup(); await rm(value.root, { recursive: true, force: true }); }
});

test("session.end closes owned real work and awaits durable old-scope outcome before a resumed session can run", async () => {
  const value = await fixture(); const host = native(value); const child = await tree(value);
  try {
    await host.start(); const original = host.context();
    await host.run("armory-verify", "check"); const pids = await deadline(child.ready);
    await host.end("resume");
    expect(pids.every(stopped)).toBe(true);
    expect((await (await store(value, original)).list())[0]?.result).toMatchObject({ status: "cancelled", descendantsStopped: true });
    const reconciliation = host.calls.filter((call) => call.argv[2] === "reconcile");
    expect(reconciliation).toHaveLength(1); expect(reconciliation[0]?.argv).toContain(original.sessionId);
    host.setSession("resumed-session"); host.env.set("ARMORY_RECEIPTS_ACCOUNT", "resumed-account-SECRET");
    await configure(value);
    // No session.start event is fired on resume. Existing command hooks must
    // reselect native identity; old account evidence cannot authorize this run.
    expect(receipts(await host.run("armory-evidence"))).toHaveLength(0);
    expect(await host.run("armory-verify", "check")).toEqual({ state: "running" });
    const current = receipts(await host.run("armory-evidence", "wait"));
    expect(current).toHaveLength(1); expect(current[0]?.proof).toBe(true);
    const saved = await (await store(value, host.context())).list();
    expect(saved[0]?.plan.context.sessionId).toBe("resumed-session");
    expect(saved[0]?.plan.context.accountId).toBe("resumed-account-SECRET");
    expect(host.specs).toHaveLength(2); host.assertSafe();
  } finally { await host.cleanup(); await child.close(); await rm(value.root, { recursive: true, force: true }); }
});
