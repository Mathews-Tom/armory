import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { closeSync, constants, fsyncSync, openSync, writeSync } from "node:fs";
import { lstat, realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { performance } from "node:perf_hooks";
import { CORE_VERSION, FEATURE, FEATURE_VERSION, SCHEMA_VERSION, executionApplicability } from "../core/index.ts";
import type { Artifact, Context, Gate, Receipt, Result, RunPlan, Snapshot } from "../core/index.ts";
import { assertContext } from "../core/validation.ts";
import { captureSnapshot, loadConfiguration, resolveRepository } from "./scope.ts";
import { createStore } from "./storage.ts";

export interface ExecuteRequest {
  repositoryRoot: string;
  configPath: string;
  gateId: string;
  dataRoot: string;
  context: Context;
  signal?: AbortSignal;
}

const TERMINATE_GRACE_MS = 200;
const CLEANUP_LIMIT_MS = 2_000;

function contained(root: string, path: string): boolean {
  const suffix = relative(root, path);
  return suffix === "" || (!isAbsolute(suffix) && suffix !== ".." && !suffix.startsWith(`..${sep}`));
}

async function commandLocation(root: string, gate: Gate): Promise<{ cwd: string; executable: string }> {
  if (isAbsolute(gate.cwd) || gate.cwd.split(/[\\/]/u).includes("..")) throw new Error("invalid gate working directory");
  const cwd = await realpath(resolve(root, gate.cwd));
  if (!contained(root, cwd) || !(await lstat(cwd)).isDirectory()) throw new Error("invalid gate working directory");
  // Bare executable names are resolved by execvp, never a shell. Relative paths
  // are bound to the approved worktree rather than the helper's own directory.
  let executable = gate.executable;
  if (!isAbsolute(executable) && /[\\/]/u.test(executable)) {
    if (executable.split(/[\\/]/u).includes("..")) throw new Error("invalid executable path");
    executable = resolve(cwd, executable);
    if (!contained(root, executable)) throw new Error("invalid executable path");
    try {
      if (!contained(root, await realpath(executable))) throw new Error("escaping executable path");
    } catch (error) {
      // Missing executables are real launch failures, recorded after reservation.
      if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) throw error;
    }
  }
  return { cwd, executable };
}

function groupExists(pid: number): boolean {
  try {
    process.kill(-pid, 0);
    return true;
  } catch (error) {
    return !(error instanceof Error && "code" in error && error.code === "ESRCH");
  }
}

function signalGroup(pid: number, signal: NodeJS.Signals): void {
  try {
    process.kill(-pid, signal);
  } catch (error) {
    if (!(error instanceof Error && "code" in error && error.code === "ESRCH")) throw error;
  }
}

async function stopGroup(pid: number): Promise<boolean> {
  if (!groupExists(pid)) return true;
  try {
    signalGroup(pid, "SIGTERM");
  } catch {
    return false;
  }
  const { promise, resolve: done } = Promise.withResolvers<boolean>();
  const started = performance.now();
  let killed = false;
  const timer = setInterval(() => {
    if (!groupExists(pid)) {
      clearInterval(timer);
      done(true);
    } else if (performance.now() - started >= CLEANUP_LIMIT_MS) {
      clearInterval(timer);
      done(false);
    } else if (!killed && performance.now() - started >= TERMINATE_GRACE_MS) {
      killed = true;
      try { signalGroup(pid, "SIGKILL"); } catch { /* Report uncertainty at the bounded deadline. */ }
    }
  }, 10);
  return await promise;
}

async function bounded<T>(promise: Promise<T>, timeoutMs: number, fallback: T): Promise<T> {
  const limit = Promise.withResolvers<T>();
  const timer = setTimeout(() => limit.resolve(fallback), timeoutMs);
  try {
    return await Promise.race([promise, limit.promise]);
  } finally {
    clearTimeout(timer);
  }
}
async function runProcess(
  gate: Gate,
  location: { cwd: string; executable: string },
  outputPath: string,
  signal?: AbortSignal,
  configurationCurrent = true,
): Promise<{ result: Result; artifact: Artifact }> {
  const fd = openSync(outputPath, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  const hash = createHash("sha256");
  let capturedBytes = 0;
  let totalBytes = 0;
  let outputFailed = false;
  let cause: "cancelled" | "timeout" | "output-unavailable" | null = signal?.aborted ? "cancelled" : null;
  let result: Result = { status: "incomplete", exitCode: null, signal: null, reason: "launch-failed", descendantsStopped: true };
  try {
    if (cause === "cancelled") {
      result = { ...result, status: "cancelled", reason: "cancelled" };
    } else if (!configurationCurrent) {
      result = { ...result, reason: "configuration-changed-before-launch" };
    } else if (process.platform === "win32") {
      result = { ...result, reason: "process-groups-unavailable" };
    } else {
      const child = (() => {
        try {
          return spawn(location.executable, gate.args, { cwd: location.cwd, detached: true, shell: false, stdio: ["ignore", "pipe", "pipe"] });
        } catch {
          return null;
        }
      })();
      if (child !== null) {
        let launchFailed = false;
        let exitCode: number | null = null;
        let exitSignal: string | null = null;
        let cleanup: Promise<boolean> | undefined;
        const stopped = Promise.withResolvers<boolean>();
        const stop = (): Promise<boolean> => {
          cleanup ??= (child.pid === undefined ? Promise.resolve(true) : stopGroup(child.pid)).then((complete) => {
            stopped.resolve(complete);
            return complete;
          });
          return cleanup;
        };
        const cancel = (): void => {
          cause ??= "cancelled";
          void stop();
        };
        const capture = (chunk: Buffer): void => {
          totalBytes += chunk.byteLength;
          if (outputFailed) return;
          const selected = chunk.subarray(0, Math.max(0, gate.maxOutputBytes - capturedBytes));
          try {
            let offset = 0;
            while (offset < selected.byteLength) {
              const written = writeSync(fd, selected, offset, selected.byteLength - offset);
              if (written === 0) throw new Error("output write made no progress");
              hash.update(selected.subarray(offset, offset + written));
              capturedBytes += written;
              offset += written;
            }
          } catch {
            outputFailed = true;
            cause ??= "output-unavailable";
            void stop();
          }
        };
        child.stdout.on("data", capture);
        child.stderr.on("data", capture);
        child.stdout.on("error", () => { outputFailed = true; cause ??= "output-unavailable"; void stop(); });
        child.stderr.on("error", () => { outputFailed = true; cause ??= "output-unavailable"; void stop(); });
        const exited = Promise.withResolvers<boolean>();
        const timeout = setTimeout(() => { cause ??= "timeout"; void stop(); }, gate.timeoutMs);
        child.once("error", () => { launchFailed = true; clearTimeout(timeout); exited.resolve(true); });
        child.once("exit", (code, childSignal) => {
          exitCode = code;
          exitSignal = childSignal;
          clearTimeout(timeout);
          exited.resolve(true);
        });
        const closed = Promise.withResolvers<boolean>();
        child.once("close", () => closed.resolve(true));
        signal?.addEventListener("abort", cancel, { once: true });
        if (signal?.aborted) cancel();
        let reaped: boolean;
        let descendantsStopped: boolean;
        let drained: boolean;
        try {
          // Cancellation must not wait for the gate's (potentially long) runtime
          // deadline if the OS cannot confirm that the process group stopped.
          await Promise.race([exited.promise, stopped.promise]);
          reaped = await bounded(exited.promise, CLEANUP_LIMIT_MS, false);
          descendantsStopped = await stop();
          drained = await bounded(closed.promise, CLEANUP_LIMIT_MS, false);
        } finally {
          clearTimeout(timeout);
          signal?.removeEventListener("abort", cancel);
          child.stdout.removeListener("data", capture);
          child.stderr.removeListener("data", capture);
          child.stdout.destroy();
          child.stderr.destroy();
        }
        let status: Result["status"] = exitCode === 0 ? "passed" : "failed";
        let reason: string | null = null;
        if (!reaped || !descendantsStopped) { status = "incomplete"; reason = "cleanup-incomplete"; }
        else if (outputFailed || !drained) { status = "incomplete"; reason = "output-unavailable"; }
        else if (cause === "cancelled") { status = "cancelled"; reason = "cancelled"; }
        else if (cause === "timeout") { status = "incomplete"; reason = "timeout"; }
        else if (launchFailed) { status = "incomplete"; reason = "launch-failed"; }
        else if (exitCode === null) { status = "incomplete"; reason = "terminated"; }
        result = { status, exitCode, signal: exitSignal, reason, descendantsStopped: descendantsStopped && reaped };
      }
    }
    try { fsyncSync(fd); } catch { outputFailed = true; }
  } finally {
    try { closeSync(fd); } catch { outputFailed = true; }
  }
  if (outputFailed) result = { ...result, status: "incomplete", reason: "output-unavailable" };
  return {
    result,
    artifact: { file: "output.bin", sha256: hash.digest("hex"), capturedBytes, totalBytes, truncated: totalBytes > capturedBytes },
  };
}

export async function executeGate(request: ExecuteRequest): Promise<Receipt> {
  assertContext(request.context);
  const repository = await resolveRepository(request.repositoryRoot);
  const loaded = await loadConfiguration(repository.worktreeRoot, request.configPath);
  if (!Object.hasOwn(loaded.config.gates, request.gateId)) throw new Error("unknown configured gate");
  const gate = loaded.config.gates[request.gateId];
  if (gate === undefined) throw new Error("unknown configured gate");
  const location = await commandLocation(repository.worktreeRoot, gate);
  const store = await createStore(request.dataRoot, repository, request.context);
  const before = await captureSnapshot(repository.worktreeRoot, gate.scope, loaded.configPath, store.key);
  if (loaded.configDigest !== before.configDigest) throw new Error("configuration changed before execution");
  const startedAtMs = Date.now();
  const started = performance.now();
  const plan: RunPlan = {
    schemaVersion: SCHEMA_VERSION, feature: FEATURE, featureVersion: FEATURE_VERSION, coreVersion: CORE_VERSION,
    executionId: randomUUID(), repository, context: { ...request.context }, gateId: request.gateId, gate,
    configId: loaded.config.configId, configPath: loaded.configPath, configDigest: loaded.configDigest, before, startedAtMs,
  };
  const lease = await store.reserve(plan);
  let configurationCurrent = false;
  try {
    configurationCurrent = (await loadConfiguration(repository.worktreeRoot, loaded.configPath)).configDigest === before.configDigest;
  } catch { /* A changed or unreadable configuration cannot authorize a spawn. */ }
  const observed = await runProcess(gate, location, lease.outputPath, request.signal, configurationCurrent);
  let after: Snapshot | null = null;
  try { after = await captureSnapshot(repository.worktreeRoot, gate.scope, loaded.configPath, store.key); } catch { /* Missing observations remain unknown. */ }
  const applicability = executionApplicability(before, after);
  const receipt: Receipt = {
    schemaVersion: SCHEMA_VERSION, plan, ...observed, after, finishedAtMs: Date.now(),
    durationMs: Math.max(0, performance.now() - started), applicability,
    applicabilityReason: applicability === "current" ? null : after === null ? "snapshot-unavailable" : "inputs-changed-during-execution",
  };
  await store.finalize(lease, receipt);
  return receipt;
}
