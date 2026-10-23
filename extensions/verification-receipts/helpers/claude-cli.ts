import { parseNativeObservation } from "../core/claude-protocol.ts";
import type { NativeObservation, NativeReceiptProjection } from "../core/claude-protocol.ts";
import type { Context } from "../core/index.ts";
import { assertContext } from "../core/validation.ts";
import { projectReceipt } from "./evidence.ts";
import { executeGate } from "./runner.ts";
import { resolveRepository } from "./scope.ts";
import { createStore } from "./storage.ts";

interface Arguments {
  command: "run" | "list" | "reconcile";
  repositoryRoot: string;
  configPath: string;
  dataRoot: string;
  context: Context;
  gateId?: string;
}

function parseArguments(args: string[]): Arguments {
  const command = args[0];
  if (command !== "run" && command !== "list" && command !== "reconcile") throw new Error("invalid arguments");
  const allowed = new Set(["--repo", "--config", "--data-root", "--session", "--account", "--work-context"]);
  if (command === "run") allowed.add("--gate");
  const values = new Map<string, string>();
  for (let index = 1; index < args.length; index += 2) {
    const key = args[index];
    const value = args[index + 1];
    if (key === undefined || value === undefined || !allowed.has(key) || values.has(key)
      || value.length === 0 || value.length > 4096 || value.startsWith("--") || value.includes("\0")) throw new Error("invalid arguments");
    values.set(key, value);
  }
  const required = (name: string): string => {
    const value = values.get(name);
    if (value === undefined) throw new Error("missing argument");
    return value;
  };
  const context: Context = {
    host: "claude", sessionId: required("--session"), accountId: required("--account"), workContext: required("--work-context"),
  };
  assertContext(context);
  const configPath = required("--config");
  if (configPath.startsWith("/") || configPath.includes("\\")
    || configPath.split("/").some((part) => part === "" || part === "." || part === ".." || part === ".git")) throw new Error("invalid config path");
  const result: Arguments = {
    command, repositoryRoot: required("--repo"), configPath, dataRoot: required("--data-root"), context,
  };
  if (command === "run") {
    const gateId = required("--gate");
    if (gateId.length > 256) throw new Error("invalid gate reference");
    for (let index = 0; index < gateId.length; index++) {
      const code = gateId.charCodeAt(index);
      if (code < 32 || code === 127) throw new Error("invalid gate reference");
    }
    result.gateId = gateId;
  }
  return result;
}

function emit(value: NativeObservation): void {
  process.stdout.write(`${JSON.stringify(parseNativeObservation(value))}\n`);
}

/** Dedicated native helper: no environment defaults and no private output. */
async function main(args: string[]): Promise<number> {
  let options: Arguments;
  try { options = parseArguments(args); } catch { emit({ error: "invalid-arguments" }); return 2; }
  const abort = new AbortController();
  let interrupted: "SIGINT" | "SIGTERM" | null = null;
  const interrupt = (signal: "SIGINT" | "SIGTERM"): void => { interrupted ??= signal; abort.abort(); };
  const sigint = (): void => interrupt("SIGINT");
  const sigterm = (): void => interrupt("SIGTERM");
  const interruptionCode = (): number | null => interrupted === "SIGTERM" ? 143 : interrupted === "SIGINT" ? 130 : null;
  process.on("SIGINT", sigint);
  process.on("SIGTERM", sigterm);
  try {
    if (options.command === "run") {
      if (options.gateId === undefined) throw new Error("missing gate");
      // executeGate owns process-group termination and durable finalization.
      // Do not exit from a signal handler or return before that work completes.
      const receipt = await executeGate({ ...options, gateId: options.gateId, signal: abort.signal });
      const repository = await resolveRepository(options.repositoryRoot);
      const store = await createStore(options.dataRoot, repository, options.context);
      const projection = await projectReceipt(receipt, options, store.key);
      emit(projection);
      const interruptedCode = interruptionCode();
      if (interruptedCode !== null) return interruptedCode;
      if (receipt.result.status === "cancelled") return 130;
      if (receipt.result.status === "failed") return 1;
      return projection.proof ? 0 : 2;
    }
    const repository = await resolveRepository(options.repositoryRoot);
    const store = await createStore(options.dataRoot, repository, options.context);
    const receipts = options.command === "reconcile" ? await store.reconcile() : await store.list();
    const projections: NativeReceiptProjection[] = [];
    for (const receipt of receipts) projections.push(await projectReceipt(receipt, options, store.key));
    emit({ receipts: projections });
    return interruptionCode() ?? 0;
  } catch {
    emit({ error: "operation-failed" });
    return interruptionCode() ?? 2;
  } finally {
    process.removeListener("SIGINT", sigint);
    process.removeListener("SIGTERM", sigterm);
  }
}

process.exitCode = await main(process.argv.slice(2));
