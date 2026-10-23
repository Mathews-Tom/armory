import { LIMITS } from "../core/index.ts";
import type { Context } from "../core/index.ts";
import { parseClaudeHostPayload } from "../core/claude-session.ts";
import type { ClaudeHostPayload } from "../core/claude-session.ts";
import type { BriefError, BriefResult } from "../core/protocol.ts";
import { assertSnapshotId } from "../core/snapshot.ts";
import { SourceError } from "../core/validation.ts";
import { InputError, listBriefs, recordBrief, reopenBrief, resolveSelection, showBrief } from "./brief.ts";
import { StateError } from "./state.ts";

// Private helper the Claude Code mod runs through `$.process.run`. The mod
// supplies the invoking session id and a bounded host-session projection on
// stdin; this process performs every filesystem and Git effect. Output is one
// JSON answer that the mod validates again before rendering anything.

type Action = "record" | "reopen" | "show" | "list";
const MAX_STDIN_BYTES = 64 * 1024;

class ArgumentError extends Error {}

interface Arguments {
  action: Action;
  repositoryRoot: string;
  dataRoot: string;
  context: Context;
  contextPath: string | null;
  ompSessionPath: string | null;
  ompHandoffPath: string | null;
  receiptPath: string | null;
  snapshot: string;
}

function printable(value: string, name: string): string {
  if (value.length === 0 || value.length > LIMITS.referenceChars || !/^[\x21-\x7e]+$/.test(value)) throw new ArgumentError(`${name} is invalid`);
  return value;
}

function parseArguments(args: string[]): Arguments {
  const action = args[0];
  if (action !== "record" && action !== "reopen" && action !== "show" && action !== "list") throw new ArgumentError("unknown action");
  const allowed = new Set(["--repo", "--data-root", "--account", "--session", "--context", "--omp-session", "--omp-handoff", "--receipt"]);
  if (action === "reopen" || action === "show") allowed.add("--snapshot");
  const values = new Map<string, string>();
  for (let index = 1; index < args.length; index += 2) {
    const key = args[index];
    const value = args[index + 1];
    if (key === undefined || value === undefined || !allowed.has(key) || values.has(key) || value.length === 0 || value.length > 4096 || value.startsWith("--") || value.includes("\0")) {
      throw new ArgumentError("invalid arguments");
    }
    values.set(key, value);
  }
  const required = (name: string): string => {
    const value = values.get(name);
    if (value === undefined) throw new ArgumentError(`missing ${name}`);
    return value;
  };
  const snapshot = values.get("--snapshot") ?? "latest";
  if (snapshot !== "latest") {
    try { assertSnapshotId(snapshot); } catch { throw new ArgumentError("invalid snapshot id"); }
  }
  return {
    action,
    repositoryRoot: required("--repo"),
    dataRoot: required("--data-root"),
    context: { host: "claude", accountId: printable(required("--account"), "--account"), sessionId: printable(required("--session"), "--session") },
    contextPath: values.get("--context") ?? null,
    ompSessionPath: values.get("--omp-session") ?? null,
    ompHandoffPath: values.get("--omp-handoff") ?? null,
    receiptPath: values.get("--receipt") ?? null,
    snapshot,
  };
}

async function hostPayload(): Promise<ClaudeHostPayload> {
  const chunks: Uint8Array[] = [];
  let length = 0;
  for await (const chunk of Bun.stdin.stream()) {
    length += chunk.byteLength;
    if (length > MAX_STDIN_BYTES) throw new ArgumentError("host session payload is too large");
    chunks.push(chunk);
  }
  const bytes = Buffer.concat(chunks, length);
  let value: unknown;
  try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { throw new ArgumentError("host session payload is not JSON"); }
  try { return parseClaudeHostPayload(value); } catch (error) {
    if (error instanceof SourceError) throw new ArgumentError("host session payload is malformed");
    throw error;
  }
}

async function answer(options: Arguments, payload: ClaudeHostPayload): Promise<BriefResult> {
  const scope = { repositoryRoot: options.repositoryRoot, dataRoot: options.dataRoot, context: options.context };
  if (options.action === "list") return listBriefs(scope);
  if (options.action === "show") return showBrief(scope, options.snapshot);
  if (options.contextPath === null) throw new InputError("no context artifact is configured");
  const selection = await resolveSelection({
    contextPath: options.contextPath, ompSessionPath: options.ompSessionPath, ompHandoffPath: options.ompHandoffPath, receiptPath: options.receiptPath,
  });
  if (options.action === "record") return recordBrief(scope, selection, { claudeHost: payload });
  return reopenBrief(scope, options.snapshot, { claudeHost: payload, configured: selection });
}

function emit(value: BriefResult | BriefError): void {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

export async function main(args: string[]): Promise<number> {
  let options: Arguments;
  let payload: ClaudeHostPayload;
  try {
    options = parseArguments(args);
    payload = await hostPayload();
  } catch (error) {
    emit({ error: "invalid-arguments", detail: error instanceof ArgumentError ? error.message : null });
    return 2;
  }
  try {
    const result = await answer(options, payload);
    emit(result);
    return result.action === "reopen" && result.discrepancies.length > 0 ? 1 : 0;
  } catch (error) {
    // Only this feature's own refusal text crosses the boundary.
    const known = error instanceof StateError || error instanceof InputError;
    emit(known ? { error: "rejected", detail: error.message.slice(0, 300) } : { error: "operation-failed", detail: null });
    return 2;
  }
}

process.exitCode = await main(process.argv.slice(2));
