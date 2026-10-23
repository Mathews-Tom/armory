import { userInfo } from "node:os";
import { join } from "node:path";
import { buildCard, discrepancies } from "../core/card.ts";
import { FEATURE_VERSION, inert, LIMITS } from "../core/index.ts";
import type { Card, Context, Discrepancy } from "../core/index.ts";
import { renderCard, renderDiscrepancies } from "../core/render.ts";
import { assertSnapshotId } from "../core/snapshot.ts";
import type { Snapshot } from "../core/snapshot.ts";
import { canonicalSelection, observe, resolveRepository } from "./sources.ts";
import type { Selection } from "./sources.ts";
import { openStore, StateError } from "./state.ts";

const HELP = `Resume Brief ${FEATURE_VERSION} standalone CLI (development prefix; no OMP/Claude commands yet).
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

async function selected(path: string | null, extension: string): Promise<string | null> {
  if (path === null) return null;
  try { return await canonicalSelection(path, extension); } catch (error) {
    throw new UsageError(error instanceof Error ? error.message : "invalid selected source");
  }
}

async function selection(options: Arguments): Promise<Selection> {
  if (options.contextPath === null) throw new UsageError("missing --context");
  return {
    contextPath: options.contextPath,
    ompSessionPath: await selected(options.ompSessionPath, ".jsonl"),
    ompHandoffPath: await selected(options.ompHandoffPath, ".md"),
    receiptPath: await selected(options.receiptPath, ".json"),
  };
}

function write(options: Arguments, json: unknown, text: string): void {
  process.stdout.write(options.format === "json" ? `${JSON.stringify(json)}\n` : text);
}

interface Reopened {
  snapshotId: string;
  recordedAtMs: number;
  recordedBy: Context;
  recorded: Card;
  current: Card;
  discrepancies: Discrepancy[];
  resumed: false;
  authority: "none";
}

export async function main(args: string[]): Promise<number> {
  if (args.length === 1 && args[0] === "--help") { process.stdout.write(HELP); return 0; }
  let options: Arguments;
  try { options = parseArguments(args); } catch (error) {
    process.stderr.write(`${JSON.stringify({ error: "invalid-arguments", detail: error instanceof Error ? error.message : "invalid arguments" })}\n`);
    return 2;
  }
  try {
    const repository = await resolveRepository(options.repositoryRoot).catch((error: unknown) => {
      const detail = error instanceof Error && error.message.startsWith("repository must") ? error.message : "--repo is not an accessible Git worktree";
      throw new UsageError(detail);
    });
    const store = await openStore(options.dataRoot, repository);
    if (options.command === "list") {
      const items: { snapshotId: string; recordedAtMs: number; branch: string | null; contextPath: string }[] = [];
      for (const id of await store.list()) {
        const snapshot = await store.read(id);
        items.push({ snapshotId: id, recordedAtMs: snapshot.recordedAtMs, branch: snapshot.observations.git.branch, contextPath: snapshot.selection.contextPath });
      }
      write(options, items, items.map((item) => `${item.snapshotId} branch=${item.branch === null ? "unknown" : inert(item.branch)}\n`).join("") || "No snapshots recorded.\n");
      return 0;
    }
    const context = options.context;
    if (context === null) throw new UsageError("missing --account/--session");
    if (options.command === "record") {
      const selected = await selection(options);
      const observations = await observe(repository, selected, Date.now);
      const snapshot = await store.record(context, selected, observations, Date.now());
      const card = buildCard(snapshot.observations, context, snapshot.recordedAtMs);
      write(options, { snapshotId: snapshot.snapshotId, card }, `Recorded snapshot ${snapshot.snapshotId}\n${renderCard(card)}`);
      return 0;
    }
    let snapshot: Snapshot;
    if (options.snapshotId === "latest") {
      const ids = await store.list();
      const last = ids[ids.length - 1];
      if (last === undefined) throw new StateError("no snapshot recorded for this repository");
      snapshot = await store.read(last);
    } else snapshot = await store.read(options.snapshotId ?? "");
    if (options.command === "show") {
      const card = buildCard(snapshot.observations, context, Date.now());
      write(options, { snapshotId: snapshot.snapshotId, observations: "recorded", card }, `Recorded snapshot ${snapshot.snapshotId} (recorded observations; no sources read)\n${renderCard(card)}`);
      return 0;
    }
    const current = await observe(repository, snapshot.selection, Date.now);
    const recordedCard = buildCard(snapshot.observations, context, snapshot.recordedAtMs);
    const currentCard = buildCard(current, context, current.observedAtMs);
    const result: Reopened = {
      snapshotId: snapshot.snapshotId, recordedAtMs: snapshot.recordedAtMs, recordedBy: snapshot.recordedBy,
      recorded: recordedCard, current: currentCard, discrepancies: discrepancies(recordedCard, currentCard), resumed: false, authority: "none",
    };
    write(options, result, `Reopened snapshot ${snapshot.snapshotId}; nothing was resumed or executed.\n${renderDiscrepancies(result.discrepancies)}Current card:\n${renderCard(currentCard)}`);
    return result.discrepancies.length === 0 ? 0 : 1;
  } catch (error) {
    // Only this feature's own messages are echoed; foreign exception text is not.
    const known = error instanceof UsageError || error instanceof StateError;
    process.stderr.write(`${JSON.stringify(known ? { error: "rejected", detail: error.message } : { error: "operation-failed" })}\n`);
    return 2;
  }
}

if (import.meta.main) process.exitCode = await main(process.argv.slice(2));
