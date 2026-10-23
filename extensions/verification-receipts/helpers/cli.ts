import { userInfo } from "node:os";
import { join } from "node:path";
import { FEATURE_VERSION } from "../core/index.ts";
import type { Context } from "../core/index.ts";
import { assertContext, assertExecutionId } from "../core/validation.ts";
import { projectReceipt } from "./evidence.ts";
import type { ReceiptProjection } from "./evidence.ts";
import { executeGate } from "./runner.ts";
import { resolveRepository } from "./scope.ts";
import { createStore } from "./storage.ts";

const HELP = `Development-only verification receipts (${FEATURE_VERSION}); standalone host only.
Usage: bun helpers/cli.ts <run|show|list|reconcile> [arguments]
  --repo <root>           Required Git worktree root.
  --config <path>         Required worktree-relative configuration path.
  --data-root <root>      Private state root; defaults to the OS account home
                         .local/state/armory/verification-receipts (not HOME).
  --host standalone      Required; this CLI does not run OMP/Claude sessions.
  --session <reference>  Required session reference.
  --account <reference>  Required account reference (not a credential).
  --work-context <ref>   Required work-context reference.
  --gate <configured-id> Required only for run; no arbitrary shell commands.
  --id <execution-id>    Required only for show.
  --help                 Print this help without filesystem/process effects.
run exit codes: 0=current successful proof, 1=failed, 2=incomplete/not proof,
130=cancelled/SIGINT, 143=SIGTERM. Read commands return 0 or 2 on error.
JSON contains safe status/proof/hash metadata, never command output or paths.
show/list/reconcile recapture current declared inputs; unknown is not fresh.
`;

interface Arguments {
  command: "run" | "show" | "list" | "reconcile";
  repositoryRoot: string;
  configPath: string;
  dataRoot: string;
  context: Context;
  gateId?: string;
  executionId?: string;
}

function parseArguments(args: string[]): Arguments {
  const command = args[0];
  if (command !== "run" && command !== "show" && command !== "list" && command !== "reconcile") throw new Error("invalid arguments");
  const allowed = new Set(["--repo", "--config", "--data-root", "--host", "--session", "--account", "--work-context"]);
  if (command === "run") allowed.add("--gate");
  if (command === "show") allowed.add("--id");
  const values = new Map<string, string>();
  for (let index = 1; index < args.length; index += 2) {
    const key = args[index];
    const value = args[index + 1];
    if (key === undefined || value === undefined || !allowed.has(key) || values.has(key) || value.startsWith("--") || value.length === 0) throw new Error("invalid arguments");
    values.set(key, value);
  }
  const required = (name: string): string => {
    const value = values.get(name);
    if (value === undefined) throw new Error("missing argument");
    return value;
  };
  if (required("--host") !== "standalone") throw new Error("standalone host required");
  const context: Context = { host: "standalone", sessionId: required("--session"), accountId: required("--account"), workContext: required("--work-context") };
  assertContext(context);
  const result: Arguments = {
    command, repositoryRoot: required("--repo"), configPath: required("--config"),
    dataRoot: values.get("--data-root") ?? join(userInfo().homedir, ".local", "state", "armory", "verification-receipts"), context,
  };
  if (command === "run") result.gateId = required("--gate");
  if (command === "show") { result.executionId = required("--id"); assertExecutionId(result.executionId); }
  return result;
}


export async function main(args: string[]): Promise<number> {
  if (args.length === 1 && args[0] === "--help") { process.stdout.write(HELP); return 0; }
  let options: Arguments;
  try { options = parseArguments(args); } catch { process.stderr.write('{"error":"invalid-arguments"}\n'); return 2; }
  const abort = new AbortController();
  let interrupted: "SIGINT" | "SIGTERM" | null = null;
  const interrupt = (signal: "SIGINT" | "SIGTERM"): void => { interrupted ??= signal; abort.abort(); };
  const sigint = (): void => interrupt("SIGINT");
  const sigterm = (): void => interrupt("SIGTERM");
  if (options.command === "run") { process.on("SIGINT", sigint); process.on("SIGTERM", sigterm); }
  try {
    const repository = await resolveRepository(options.repositoryRoot);
    const store = await createStore(options.dataRoot, repository, options.context);
    if (options.command === "run") {
      if (options.gateId === undefined) throw new Error("missing gate");
      const receipt = await executeGate({ ...options, gateId: options.gateId, signal: abort.signal });
      const projection = await projectReceipt(receipt, options, store.key);
      process.stdout.write(`${JSON.stringify(projection)}\n`);
      if (interrupted === "SIGTERM") return 143;
      if (interrupted === "SIGINT" || receipt.result.status === "cancelled") return 130;
      if (receipt.result.status === "failed") return 1;
      return projection.proof ? 0 : 2;
    }
    const receipts = options.command === "show"
      ? [await store.read(options.executionId ?? "")]
      : options.command === "reconcile" ? await store.reconcile() : await store.list();
    const projections: ReceiptProjection[] = [];
    for (const receipt of receipts) projections.push(await projectReceipt(receipt, options, store.key));
    process.stdout.write(`${JSON.stringify(options.command === "show" ? projections[0] : projections)}\n`);
    return 0;
  } catch {
    process.stderr.write('{"error":"operation-failed"}\n');
    return interrupted === "SIGTERM" ? 143 : interrupted === "SIGINT" ? 130 : 2;
  } finally {
    process.removeListener("SIGINT", sigint);
    process.removeListener("SIGTERM", sigterm);
  }
}

if (import.meta.main) process.exitCode = await main(process.argv.slice(2));
