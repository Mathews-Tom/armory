import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { parseBridgeResult } from "../core/index.ts";
import type { BridgeResult, ProjectConfig } from "../core/index.ts";

export const BRIDGE_TIMEOUT_MS = 30_000;
export const BRIDGE_OUTPUT_BYTES = 64 * 1024;
export interface BridgeExecution { readonly result: BridgeResult | null; readonly reason: string | null }

/** The configured bridge is trusted project code, not a sandbox or provider adapter. */
export async function runBridge(config: ProjectConfig, configPath: string, declarationPath: string, signal?: AbortSignal, timeoutMs = BRIDGE_TIMEOUT_MS): Promise<BridgeExecution> {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > BRIDGE_TIMEOUT_MS) return { result: null, reason: "bridge-invalid-timeout" };
  if (signal?.aborted) return { result: null, reason: "bridge-cancelled" };
  const { promise, resolve } = Promise.withResolvers<BridgeExecution>();
  const argv = [...config.bridgeArgv, "--config", configPath, "--declaration", declarationPath];
  const executable = config.bridgeArgv[0];
  if (executable === undefined) return { result: null, reason: "bridge-start-failed" };
  let failure: string | null = null;
  let child: ChildProcess;
  try { child = spawn(executable, argv.slice(1), { cwd: config.projectRoot, shell: false, detached: true, stdio: ["ignore", "pipe", "pipe"] }); }
  catch { return { result: null, reason: "bridge-start-failed" }; }
  const chunks: Buffer[] = [];
  let bytes = 0;
  let killTimer: NodeJS.Timeout | undefined;
  let settled = false;
  const finish = (result: BridgeExecution): void => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    clearTimeout(killTimer);
    signal?.removeEventListener("abort", cancel);
    if (child.pid !== undefined) { try { process.kill(-child.pid, "SIGKILL"); } catch { /* Already reaped. */ } }
    child.stdout?.destroy();
    child.stderr?.destroy();
    resolve(result);
  };
  const terminate = (reason: string): void => {
    if (failure !== null || settled) return;
    failure = reason;
    if (child.pid !== undefined) { try { process.kill(-child.pid, "SIGTERM"); } catch { /* Already exited. */ } }
    // Do not wait forever for inherited pipes, even if trusted bridge code
    // accidentally leaves a descendant holding them open.
    killTimer = setTimeout(() => finish({ result: null, reason }), 100);
  };
  const cancel = (): void => terminate("bridge-cancelled");
  const timer = setTimeout(() => terminate("bridge-timeout"), timeoutMs);
  signal?.addEventListener("abort", cancel, { once: true });
  const receive = (chunk: Buffer, stdout: boolean): void => {
    if (settled || failure !== null) return;
    bytes += chunk.byteLength;
    if (bytes > BRIDGE_OUTPUT_BYTES) { terminate("bridge-output-too-large"); return; }
    if (stdout) chunks.push(Buffer.from(chunk));
  };
  child.stdout?.on("data", (chunk: Buffer) => receive(chunk, true));
  child.stderr?.on("data", (chunk: Buffer) => receive(chunk, false));
  child.on("error", () => finish({ result: null, reason: "bridge-start-failed" }));
  child.once("close", (code) => {
    if (settled) return;
    if (failure !== null) { finish({ result: null, reason: failure }); return; }
    if (code !== 0) { finish({ result: null, reason: "bridge-nonzero-exit" }); return; }
    try {
      const decoded = new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks));
      finish({ result: parseBridgeResult(JSON.parse(decoded)), reason: null });
    } catch { finish({ result: null, reason: "bridge-response-malformed" }); }
  });
  if (signal?.aborted) cancel();
  return promise;
}
