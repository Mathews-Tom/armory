import { expect, test } from "bun:test";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { check, refusal } from "../core/index.ts";
import type { Response } from "../core/index.ts";
import { COMMAND } from "../core/protocol.ts";
import { observe, sha256 } from "../helpers/filesystem.ts";
import { createRunPreflight, executeHelper } from "../omp/index.ts";
import type { HelperExecution, Runtime } from "../omp/index.ts";
import { fixture, HELPER, PACKAGE_ROOT, requireAdmission } from "./fixtures.ts";

type Registered = Parameters<ExtensionAPI["registerCommand"]>[1];
type Lifecycle = (event: { type: string }, ctx: ExtensionContext) => unknown;
interface Message { content: string; display: boolean; details: { view?: Record<string, unknown>; error?: string; help?: boolean; correlation?: Record<string, unknown> } }
const T = Date.now();
const selection = { config: "/selected project/config.json", declaration: "/selected project/declaration.json" };
const args = (action = "check", json = true): string => `${action} ${JSON.stringify(selection)}${json ? " --json" : ""}`;
const unknownReport: Response = { ...refusal([]), status: "unknown", reasons: ["quota-unknown"], quota: {
  status: "unknown", observedAt: new Date(T - 1000).toISOString(), expiresAt: new Date(T + 60_000).toISOString(), reason: "no-provider-observation", source: "synthetic-fixture", remainingCalls: null,
} };
function execution(value: unknown = unknownReport, extra: Partial<HelperExecution> = {}): HelperExecution {
  return { stdout: JSON.stringify(value), exitCode: 0, signal: null, cleanupConfirmed: true, ...extra };
}
function harness(execute: Runtime["execute"], foreign: { name: string; source: string; description?: string }[] = [], now = T) {
  const commands = new Map<string, Registered>();
  const events = new Map<string, Lifecycle>();
  const messages: Message[] = [];
  const deliveries: unknown[] = [];
  let id = "session-A";
  const ctx = { cwd: "/actual/host", sessionManager: { getSessionId: () => id } } as unknown as ExtensionCommandContext;
  const api = {
    getCommands: () => [...foreign, ...[...commands].map(([name, command]) => ({ name, description: command.description, source: "extension" }))],
    registerCommand: (name: string, command: Registered) => { commands.set(name, command); },
    on: (name: string, listener: Lifecycle) => { events.set(name, listener); },
    sendMessage: (message: Message, delivery: unknown) => { messages.push(message); deliveries.push(delivery); },
  };
  createRunPreflight({ packageRoot: PACKAGE_ROOT, now: () => now, execute })(api as unknown as ExtensionAPI);
  return { commands, messages, deliveries, ctx, events,
    async start() { await events.get("session_start")?.({ type: "session_start" }, ctx); },
    async run(text = args()) { const command = commands.get(COMMAND); if (command === undefined) throw new Error("not registered"); await command.handler(text, ctx); },
    async switchTo(next: string) { id = next; await events.get("session_switch")?.({ type: "session_switch" }, ctx); },
    async shutdown() { await events.get("session_shutdown")?.({ type: "session_shutdown" }, ctx); },
    move(next: string) { id = next; },
  };
}

test("literal own installed helper selection, projected JSON and native text never trigger a model turn", async () => {
  const calls: string[][] = [];
  const host = harness(async (argv) => { calls.push([...argv]); return execution(); });
  await host.start();
  await host.start();
  expect(host.commands.size).toBe(1);
  await host.run();
  expect(calls).toEqual([["bun", `${PACKAGE_ROOT}/helpers/cli.js`, "check", "--config", selection.config, "--declaration", selection.declaration, "--format", "json"]]);
  const json = JSON.parse(host.messages[0]?.content ?? "null");
  expect(json.status).toBe("unknown");
  expect(json.admitted).toBe(false);
  expect(json.quota.status).toBe("unknown");
  expect(json).not.toHaveProperty("admission");
  expect(host.messages[0]?.details.correlation).toEqual({ host: "omp", sessionId: "session-A", cwd: "/actual/host" });
  await host.run(args("check", false));
  expect(host.messages[1]?.content).toContain("Selected config:");
  expect(host.messages[1]?.content).toContain("unknown");
  expect(() => JSON.parse(host.messages[1]?.content ?? "")).toThrow();
  await host.run("help");
  expect(host.messages[2]?.details.help).toBe(true);
  expect(calls.length).toBe(2);
  expect(host.deliveries).toEqual([{ triggerTurn: false }, { triggerTurn: false }, { triggerTurn: false }]);
});

test("invalid selections and native admit refuse before any execution; collision never shadows", async () => {
  let calls = 0;
  const effect: Runtime["execute"] = async () => { calls++; return execution(); };
  const host = harness(effect);
  await host.start();
  for (const text of ["", "admit {} --json", "check {} --json", 'check {"config":"relative","declaration":"/absolute"} --json', args() + " unexpected"]) {
    await host.run(text);
    expect(host.messages.at(-1)?.details.error).toBe("invalid-arguments");
  }
  expect(calls).toBe(0);
  for (const source of ["prompt", "extension"]) {
    const collision = harness(effect, [{ name: COMMAND, source }]);
    await expect(collision.start()).rejects.toThrow("command-collision");
    expect(collision.commands.size).toBe(0);
  }
});

test("only validated blocked exit2 is publishable; signals, nonzero, malformed and stale reports fail closed", async () => {
  const cases = [execution(unknownReport, { exitCode: 2 }), execution(unknownReport, { exitCode: 1 }), execution(unknownReport, { signal: "SIGTERM" }), execution(unknownReport, { stdout: "not json" }), execution({ ...unknownReport, quota: { ...unknownReport.quota, expiresAt: new Date(T - 1).toISOString() } })];
  for (const result of cases) {
    const host = harness(async () => result);
    await host.start(); await host.run();
    expect(JSON.parse(host.messages[0]?.content ?? "null")).toEqual({ error: "operation-failed" });
    expect(host.messages[0]?.details.view).toBeUndefined();
  }
  const blocked = harness(async () => execution(refusal(["input-binding-mismatch"]), { exitCode: 2 }));
  await blocked.start(); await blocked.run();
  expect(JSON.parse(blocked.messages[0]?.content ?? "null").status).toBe("blocked");
});

test("probe projection removes admission, identity, input facts and bridge argv from both public views", async () => {
  const f = await fixture();
  try {
    const response = check(await observe(f.configPath, f.declarationPath, HELPER), f.now, sha256);
    const original = requireAdmission(response);
    const report = { ...response, admission: { ...original, config: { ...original.config, helperPath: "helpers/cli.js" },
      facts: { ...original.facts, helper: { ...original.facts.helper, path: `${PACKAGE_ROOT}/helpers/cli.js`, realPath: `${PACKAGE_ROOT}/helpers/cli.js` } } },
      probe: { schemaVersion: 1, coreVersion: "1.0.0", status: "terminal-receipt-unavailable", managedSpawns: 1, providerCalls: 0, reasons: ["terminal-receipt-unavailable"] } };
    const host = harness(async () => execution(report), [], f.now);
    await host.start();
    const command = `probe ${JSON.stringify({ config: f.configPath, declaration: f.declarationPath })}`;
    await host.run(command + " --json"); await host.run(command);
    for (const message of host.messages) {
      const rendered = JSON.stringify(message);
      expect(message.details.view?.probe).toEqual(report.probe);
      for (const secret of ["accountFingerprint", "synthetic-no-account", "bridgeArgv", "recordSha256", "identityFile", f.identityPath, f.sourcePath]) expect(rendered).not.toContain(secret);
    }
  } finally { await f.dispose(); }
});

test("session switch awaits cancelled execution, suppresses stale output and permits a fresh command", async () => {
  const entered = Promise.withResolvers<undefined>();
  const released = Promise.withResolvers<HelperExecution>();
  let calls = 0;
  let aborted = false;
  const host = harness(async (_argv, signal) => {
    if (++calls > 1) return execution();
    signal.addEventListener("abort", () => { aborted = true; }, { once: true });
    entered.resolve(undefined);
    return released.promise;
  });
  await host.start();
  const pending = host.run(); await entered.promise;
  let switched = false;
  const transition = host.switchTo("session-B").then(() => { switched = true; });
  await Promise.resolve();
  expect(aborted).toBe(true);
  expect(switched).toBe(false);
  await host.run(); expect(calls).toBe(1);
  released.resolve(execution());
  await pending; await transition;
  expect(host.messages).toHaveLength(0);
  await host.run();
  expect(host.messages).toHaveLength(1);
  expect(host.messages[0]?.details.correlation?.sessionId).toBe("session-B");
});

test("a replacement invocation waits for old cleanup; cwd/session drift never publishes", async () => {
  for (const drift of ["cwd", "session", "replace"] as const) {
    const entered = Promise.withResolvers<undefined>();
    const release = Promise.withResolvers<HelperExecution>();
    let calls = 0;
    const host = harness(async () => { if (++calls === 1) { entered.resolve(undefined); return release.promise; } return execution(); });
    await host.start(); const first = host.run(); await entered.promise;
    let second: Promise<void> | undefined;
    if (drift === "cwd") host.ctx.cwd = "/another/host";
    else if (drift === "session") host.move("session-B");
    else { second = host.run(); await Promise.resolve(); expect(calls).toBe(1); }
    release.resolve(execution()); await first; await second;
    expect(host.messages).toHaveLength(drift === "replace" ? 1 : 0);
  }
});

test("unconfirmed cleanup permanently blocks later commands and lifecycle acceptance", async () => {
  let calls = 0;
  const host = harness(async () => { calls++; return execution(unknownReport, { cleanupConfirmed: false }); });
  await host.start();
  await expect(host.run()).rejects.toThrow("cleanup-unconfirmed");
  await host.run();
  await expect(host.start()).rejects.toThrow("cleanup-unconfirmed");
  await host.switchTo("session-B");
  await host.run();
  expect(calls).toBe(1); expect(host.messages).toHaveLength(0);
});

test("shutdown awaits every owner and publishes neither cancelled output nor future commands", async () => {
  const entered = Promise.withResolvers<undefined>();
  const release = Promise.withResolvers<HelperExecution>();
  const host = harness(async () => { entered.resolve(undefined); return release.promise; });
  await host.start(); const pending = host.run(); await entered.promise;
  let disposed = false;
  const shutdown = host.shutdown().then(() => { disposed = true; });
  await Promise.resolve(); expect(disposed).toBe(false);
  release.resolve(execution()); await pending; await shutdown;
  await host.run(); expect(host.messages).toHaveLength(0);
});

test("owned execution validates actual exit and bounds stdout plus stderr", async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), "preflight-native-execution-")));
  const helper = join(root, "helper.js");
  try {
    await writeFile(helper, 'process.stdout.write("report"); process.exitCode = 2;');
    const result = await executeHelper(["bun", helper], new AbortController().signal, 2_000);
    expect(result).toEqual({ stdout: "report", exitCode: 2, signal: null, cleanupConfirmed: true });
    await writeFile(helper, 'process.stderr.write("x".repeat(4096)); setInterval(() => {}, 1000);');
    const bounded = await executeHelper(["bun", helper], new AbortController().signal, 2_000, 512);
    expect(bounded.stdout).toBe(""); expect(bounded.exitCode).toBeNull(); expect(bounded.cleanupConfirmed).toBe(true);
    await writeFile(helper, 'setInterval(() => {}, 1000);');
    const timed = await executeHelper(["bun", helper], new AbortController().signal, 100);
    expect(timed.exitCode).toBeNull(); expect(timed.cleanupConfirmed).toBe(true);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("cancellation gives the helper time to reap its detached nested bridge and confirms both groups absent", async () => {
  // Real-process integration: fake timers cannot drive another Bun process or
  // observe OS PID/group disappearance; poll the actual ready file, not a delay.
  const root = await realpath(await mkdtemp(join(tmpdir(), "preflight-native-cancel-")));
  const helper = join(root, "helper.js");
  const pidPath = join(root, "pid");
  try {
    await writeFile(helper, `import { spawn } from "node:child_process"; import { writeFileSync } from "node:fs";
const child = spawn("bun", ["-e", "setInterval(() => {}, 1000)"], { detached: true, stdio: "ignore" });
writeFileSync(${JSON.stringify(pidPath)}, String(child.pid));
process.on("SIGTERM", () => { process.kill(-child.pid, "SIGTERM"); child.on("close", () => { process.exitCode = 143; }); });`);
    const abort = new AbortController();
    const pending = executeHelper(["bun", helper], abort.signal, 5_000);
    let pid = 0;
    const deadline = Date.now() + 3_000;
    while (Date.now() < deadline) {
      try { pid = Number(await readFile(pidPath, "utf8")); break; } catch { await Bun.sleep(10); }
    }
    if (pid === 0) { abort.abort(); await pending; throw new Error("actual nested bridge did not start"); }
    abort.abort();
    const result = await pending;
    expect(result.cleanupConfirmed).toBe(true);
    expect(result.exitCode).toBeNull();
    expect(() => process.kill(pid, 0)).toThrow();
    expect(() => process.kill(-pid, 0)).toThrow();
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("cancellation discovers a detached descendant created by a termination handler", async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), "preflight-native-late-child-")));
  const helper = join(root, "helper.js");
  const ready = join(root, "ready");
  const pidPath = join(root, "pid");
  let pid = 0;
  const alive = (): boolean => {
    try { process.kill(pid, 0); return true; }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ESRCH") return false; throw error; }
  };
  const awaitAbsent = async (): Promise<void> => {
    const deadline = Date.now() + 2_000;
    while (alive()) {
      if (Date.now() >= deadline) throw new Error("fixture descendant cleanup unconfirmed");
      await Bun.sleep(10);
    }
  };
  try {
    await writeFile(helper, `import { spawn } from "node:child_process"; import { writeFileSync } from "node:fs";
const timer = setInterval(() => {}, 1000);
process.once("SIGTERM", () => {
  const child = spawn("bun", ["-e", "setInterval(() => {}, 1000)"], { detached: true, stdio: "ignore" });
  writeFileSync(${JSON.stringify(pidPath)}, String(child.pid));
  child.once("close", () => { clearInterval(timer); process.exitCode = 143; });
});
writeFileSync(${JSON.stringify(ready)}, "ready");`);
    const abort = new AbortController();
    const pending = executeHelper(["bun", helper], abort.signal, 5_000);
    const deadline = Date.now() + 3_000;
    while (!(await Bun.file(ready).exists())) {
      if (Date.now() >= deadline) { abort.abort(); await pending; throw new Error("termination fixture did not start"); }
      await Bun.sleep(10);
    }
    abort.abort();
    const result = await pending;
    pid = Number(await readFile(pidPath, "utf8"));
    expect(result.exitCode).toBeNull();
    expect(result.cleanupConfirmed).toBe(true);
    expect(alive()).toBe(false);
    expect(() => process.kill(-pid, 0)).toThrow();
  } finally {
    if (pid === 0 && await Bun.file(pidPath).exists()) pid = Number(await readFile(pidPath, "utf8"));
    if (pid > 0 && alive()) {
      process.kill(-pid, "SIGKILL");
      await awaitAbsent();
    }
    await rm(root, { recursive: true, force: true });
  }
});

test("an execution rejection cannot bypass the cleanup latch, including a cancelled owner", async () => {
  const entered = Promise.withResolvers<undefined>();
  const release = Promise.withResolvers<HelperExecution>();
  let calls = 0;
  const host = harness(async () => { calls++; entered.resolve(undefined); return release.promise; });
  await host.start();
  const first = host.run();
  await entered.promise;
  const second = host.run();
  const shutdown = host.shutdown();
  release.reject(new Error("private helper transport failure"));
  const settled = await Promise.allSettled([first, second, shutdown]);
  expect(settled.every((result) => result.status === "rejected")).toBe(true);
  expect(calls).toBe(1);
  expect(host.messages).toHaveLength(0);
  await host.run();
  expect(calls).toBe(1);
});
