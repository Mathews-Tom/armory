import { userInfo } from "node:os";
import { join } from "node:path";
import { FEATURE_VERSION, LIMITS } from "../core/index.ts";
import type { Context } from "../core/index.ts";
import { renderResult } from "../core/render.ts";
import { assertSnapshotId } from "../core/snapshot.ts";
import { InputError, listBriefs, recordBrief, reopenBrief, resolveSelection, showBrief } from "./brief.ts";
import { StateError } from "./state.ts";

const HELP = `Resume Brief ${FEATURE_VERSION} standalone CLI (OMP and Claude Code use /armory-brief instead).
Usage: bun extensions/resume-brief/helpers/cli.ts <record|reopen|show|list> [options]
  --repo <worktree-root>     Required. Absolute path of exactly one Git worktree root.
  --data-root <dir>          Private derived-state root outside the repository and package;
                             defaults to <OS account home>/.local/state/armory/resume-brief.
  --host standalone          Required. This CLI evaluates approvals for the standalone host.
  --account <reference>      Required except for list. Opaque account label, not a credential.
  --session <reference>      Required except for list. Opaque session label.
  --format json|text         Output format (default json). Text escapes all source values.
record only:
  --context <repo-path>      Required. Repository-relative armory.resume-brief.context/v1 artifact.
  --omp-session <file.jsonl> Optional explicitly selected OMP JSONL session (header version 3).
  --omp-handoff <file.md>    Optional explicitly selected OMP handoff-<timestamp>.md file.
  --receipt <file.json>      Optional explicitly selected Verification Receipts receipt file.
reopen/show:
  --id <snapshot-id> | --latest
record observes and stores a private derived snapshot (references and hashes, no bodies).
reopen re-reads the recorded selection and prints exact source-linked discrepancies.
show prints the recorded card, re-evaluating approval expiry now; it reads no sources.
Nothing is executed or resumed; approvals are always non-executable holds.
Exit codes: 0 ok / no discrepancy, 1 reopen found discrepancies, 2 invalid input or failure.
`;

type Command = "record" | "reopen" | "show" | "list";

interface Arguments {
  command: Command;
  repositoryRoot: string;
  dataRoot: string;
  format: "json" | "text";
  context: Context | null;
  contextPath: string | null;
  ompSessionPath: string | null;
  ompHandoffPath: string | null;
  receiptPath: string | null;
  snapshotId: string | "latest" | null;
}

class UsageError extends Error {}

function reference(value: string, name: string): string {
  if (value.length > LIMITS.referenceChars || !/^[\x21-\x7e]+$/.test(value)) throw new UsageError(`${name} must be a printable ASCII reference of at most ${LIMITS.referenceChars} characters`);
  return value;
}

function parseArguments(args: string[]): Arguments {
  const command = args[0];
  if (command !== "record" && command !== "reopen" && command !== "show" && command !== "list") throw new UsageError("expected record, reopen, show or list");
  const allowed = new Set(["--repo", "--data-root", "--host", "--account", "--session", "--format"]);
  if (command === "record") for (const flag of ["--context", "--omp-session", "--omp-handoff", "--receipt"]) allowed.add(flag);
  if (command === "reopen" || command === "show") allowed.add("--id");
  const values = new Map<string, string>();
  let latest = false;
  for (let index = 1; index < args.length; index++) {
    const key = args[index] ?? "";
    if (key === "--latest" && (command === "reopen" || command === "show") && !latest) { latest = true; continue; }
    const value = args[index + 1];
    if (!allowed.has(key) || values.has(key) || value === undefined || value.length === 0 || value.startsWith("--")) throw new UsageError(`invalid or repeated argument ${JSON.stringify(key.slice(0, 64))}`);
    values.set(key, value);
    index++;
  }
  const required = (name: string): string => {
    const value = values.get(name);
    if (value === undefined) throw new UsageError(`missing ${name}`);
    return value;
  };
  if (required("--host") !== "standalone") throw new UsageError("--host must be standalone for this CLI");
  const format = values.get("--format") ?? "json";
  if (format !== "json" && format !== "text") throw new UsageError("--format must be json or text");
  const context: Context | null = command === "list" && !values.has("--account") && !values.has("--session")
    ? null
    : { host: "standalone", accountId: reference(required("--account"), "--account"), sessionId: reference(required("--session"), "--session") };
  let snapshotId: Arguments["snapshotId"] = null;
  if (command === "reopen" || command === "show") {
    const id = values.get("--id");
    if ((id === undefined) === !latest) throw new UsageError("exactly one of --id or --latest is required");
    if (id !== undefined) assertSnapshotId(id);
    snapshotId = id ?? "latest";
  }
  return {
    command,
    repositoryRoot: required("--repo"),
    dataRoot: values.get("--data-root") ?? join(userInfo().homedir, ".local", "state", "armory", "resume-brief"),
    format,
    context,
    contextPath: command === "record" ? required("--context") : null,
    ompSessionPath: values.get("--omp-session") ?? null,
    ompHandoffPath: values.get("--omp-handoff") ?? null,
    receiptPath: values.get("--receipt") ?? null,
    snapshotId,
  };
}

function write(options: Arguments, json: unknown, text: string): void {
  process.stdout.write(options.format === "json" ? `${JSON.stringify(json)}\n` : text);
}

export async function main(args: string[]): Promise<number> {
  if (args.length === 1 && args[0] === "--help") { process.stdout.write(HELP); return 0; }
  let options: Arguments;
  try { options = parseArguments(args); } catch (error) {
    process.stderr.write(`${JSON.stringify({ error: "invalid-arguments", detail: error instanceof Error ? error.message : "invalid arguments" })}\n`);
    return 2;
  }
  try {
    const location = { repositoryRoot: options.repositoryRoot, dataRoot: options.dataRoot };
    if (options.command === "list") {
      const result = await listBriefs(location);
      write(options, result.snapshots, renderResult(result));
      return 0;
    }
    const context = options.context;
    if (context === null) throw new UsageError("missing --account/--session");
    const scope = { ...location, context };
    if (options.command === "record") {
      if (options.contextPath === null) throw new UsageError("missing --context");
      const selection = await resolveSelection({
        contextPath: options.contextPath, ompSessionPath: options.ompSessionPath, ompHandoffPath: options.ompHandoffPath, receiptPath: options.receiptPath,
      });
      const result = await recordBrief(scope, selection);
      write(options, result, renderResult(result));
      return 0;
    }
    const snapshot = options.snapshotId ?? "latest";
    if (options.command === "show") {
      const result = await showBrief(scope, snapshot);
      write(options, result, renderResult(result));
      return 0;
    }
    const result = await reopenBrief(scope, snapshot);
    write(options, result, renderResult(result));
    return result.discrepancies.length === 0 ? 0 : 1;
  } catch (error) {
    // Only this feature's own messages are echoed; foreign exception text is not.
    const known = error instanceof UsageError || error instanceof StateError || error instanceof InputError;
    process.stderr.write(`${JSON.stringify(known ? { error: "rejected", detail: error.message } : { error: "operation-failed" })}\n`);
    return 2;
  }
}

if (import.meta.main) process.exitCode = await main(process.argv.slice(2));
