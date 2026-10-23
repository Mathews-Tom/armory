import { FEATURE, LIMITS } from "./index.ts";
import type { Card, Context, Discrepancy } from "./index.ts";
import { bool, context, HOSTS, int, list, nullable, oneOf, ROLES, sha, shape, STATUSES, str } from "./snapshot.ts";
import type { Check } from "./snapshot.ts";
import { assertSnapshotId } from "./snapshot.ts";

// The literal `/armory-brief` grammar shared by both native adapters, the
// result envelopes the helper returns, and strict validation of those results
// on the Claude mod's side of the process boundary.

export const COMMAND = "armory-brief" as const;
export const COMMAND_DESCRIPTION = "Record, reopen, show or list freshness-checked project briefs (read-only)" as const;
export const ARGUMENT_HINT = "record | reopen [id] | show [id] | list [--json]" as const;

export type BriefCommand =
  | { action: "help" }
  | { action: "record"; json: boolean }
  | { action: "reopen" | "show"; snapshot: string; json: boolean }
  | { action: "list"; json: boolean };

export class CommandError extends Error {}

const MAX_ARGUMENT_CHARS = 256;

/** Parse the literal argument text. Nothing here is interpreted as a shell or a prompt. */
export function parseCommand(args: string): BriefCommand {
  if (args.length > MAX_ARGUMENT_CHARS) throw new CommandError("arguments are too long");
  const tokens = args.trim().split(/\s+/u).filter((token) => token.length > 0);
  const json = tokens.filter((token) => token === "--json").length;
  if (json > 1) throw new CommandError("--json is repeated");
  const words = tokens.filter((token) => token !== "--json");
  const [action, target, ...rest] = words;
  if (action === undefined || action === "help") {
    if (words.length > 1 || json > 0) throw new CommandError("help takes no arguments");
    return { action: "help" };
  }
  if (rest.length > 0) throw new CommandError("too many arguments");
  if (action === "record" || action === "list") {
    if (target !== undefined) throw new CommandError(`${action} takes no snapshot`);
    return { action, json: json === 1 };
  }
  if (action === "reopen" || action === "show") {
    const snapshot = target ?? "latest";
    if (snapshot !== "latest") {
      try { assertSnapshotId(snapshot); } catch { throw new CommandError("snapshot must be an id from list or latest"); }
    }
    return { action, snapshot, json: json === 1 };
  }
  throw new CommandError("expected record, reopen, show, list or help");
}

export const HELP = `/armory-brief — read-only resume brief for the explicitly configured project.
  record            observe the selected repository and sources once and store a private derived snapshot
  reopen [id]       re-read the recorded selection and list exact source-linked discrepancies (default latest)
  show [id]         print a recorded card without reading sources (default latest)
  list              list recorded snapshots for the selected repository
  --json            print the validated result as ASCII-escaped JSON instead of text
Nothing is executed or resumed. Recorded approvals are non-executable holds and never transfer between hosts, accounts or sessions.
`;

export interface RecordResult { action: "record"; snapshotId: string; card: Card }
export interface ShowResult { action: "show"; snapshotId: string; observations: "recorded"; card: Card }
export interface ReopenResult {
  action: "reopen";
  snapshotId: string;
  recordedAtMs: number;
  recordedBy: Context;
  recorded: Card;
  current: Card;
  discrepancies: Discrepancy[];
  resumed: false;
  authority: "none";
}
export interface ListEntry { snapshotId: string; recordedAtMs: number; recordedBy: Context; branch: string | null; contextPath: string }
export interface ListResult { action: "list"; snapshots: ListEntry[] }
export type BriefResult = RecordResult | ShowResult | ReopenResult | ListResult;

export type BriefErrorCode = "invalid-arguments" | "invalid-configuration" | "rejected" | "operation-failed" | "context-changed" | "session-unavailable";
export interface BriefError { error: BriefErrorCode; detail: string | null }

const MAX_SNAPSHOTS = 10_000;

function jsonValue(depth: number): Check {
  return (value, path) => {
    if (value === null || typeof value === "boolean") return;
    if (typeof value === "string") { str()(value, path); return; }
    if (typeof value === "number") { if (!Number.isFinite(value)) throw new Error(`malformed result at ${path}`); return; }
    if (depth === 0 || typeof value !== "object") throw new Error(`malformed result at ${path}`);
    if (Array.isArray(value)) { list(jsonValue(depth - 1), LIMITS.blockers)(value, path); return; }
    const entries = Object.entries(value);
    if (entries.length > 16) throw new Error(`malformed result at ${path}`);
    for (const [key, item] of entries) { str(64)(key, path); jsonValue(depth - 1)(item, `${path}.${key}`); }
  };
}

const flag = nullable(bool);
const count = nullable(int);
const hold = shape({
  id: str(128), scope: str(LIMITS.scopeChars),
  origin: shape({ host: oneOf(...HOSTS), accountId: nullable(str(LIMITS.referenceChars)), sessionId: nullable(str(LIMITS.referenceChars)) }),
  source: oneOf("context", "omp-session"), grantedAtMs: int, expiresAtMs: nullable(int),
  status: oneOf("expired", "unexpired-hold", "no-expiry-hold", "not-yet-valid"), foreignOrigin: bool, executable: oneOf(false), reason: str(2048),
});
const card = shape({
  feature: oneOf(FEATURE), featureVersion: str(32), observedAtMs: int, evaluatedAtMs: int, evaluatedFor: context,
  objective: nullable(str(LIMITS.objectiveChars)),
  plan: shape({ ref: nullable(str(1024)), sha256: sha, lastCommit: nullable(str(64)), modifiedInWorktree: flag }),
  lastVerification: shape({
    ref: nullable(str()), sha256: sha, executionId: nullable(str(128)), gateId: nullable(str(LIMITS.referenceChars)),
    status: oneOf(null, "passed", "failed", "cancelled", "incomplete"), finishedAtMs: count, sameRepository: flag, freshness: oneOf("not-evaluated"),
  }),
  repository: shape({
    observation: oneOf("ok", "unavailable", "changed-during-read"), branch: nullable(str(1024)), detached: flag, head: nullable(str(64)),
    upstream: nullable(str(1024)), dirty: flag, worktreeRoot: nullable(str()),
    pullRequest: shape({ declared: nullable(shape({ number: int, url: nullable(str(LIMITS.urlChars)) })), observed: oneOf(null) }),
  }),
  blockers: nullable(list(shape({ id: str(128), summary: str(LIMITS.summaryChars), status: oneOf("open", "resolved") }), LIMITS.blockers)),
  nextAction: shape({ text: nullable(str(LIMITS.objectiveChars)), executed: oneOf(false) }),
  session: shape({
    kind: oneOf(null, "omp-session"), id: nullable(str(LIMITS.referenceChars)), cwdMatchesWorktree: flag, entryCount: count,
    lastEntryAt: nullable(str(64)), handoffGeneratedAt: nullable(str(64)),
  }),
  claudeSession: shape({
    kind: oneOf(null, "claude-session"), id: nullable(str(LIMITS.referenceChars)), cwdMatchesWorktree: flag, rootMatchesWorktree: flag,
    startedAtMs: count, turns: count, observedMessages: count, messagesComplete: flag, lastRole: oneOf(null, "user", "assistant"), toolUses: count,
  }),
  approvals: list(hold, 2 * LIMITS.approvals),
  sources: list(shape({
    role: oneOf(...ROLES), ref: str(), status: oneOf(...STATUSES), sha256: sha, bytes: count, mtimeMs: nullable((value, path) => {
      if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new Error(`malformed result at ${path}`);
    }), diagnostic: nullable(str(512)),
  }), ROLES.length),
  unknowns: list(shape({ field: str(128), reason: str(1024) }), 2 * LIMITS.diagnostics),
  authority: oneOf("none"),
});
const discrepancy = shape({
  field: str(256), kind: oneOf("changed", "added", "removed", "became-unknown", "became-known", "expired-since-record"),
  recorded: jsonValue(3), current: jsonValue(3),
  source: shape({ role: oneOf(...ROLES, "git", "clock"), ref: nullable(str()), recordedSha256: sha, currentSha256: sha }),
});
const snapshotId: Check = (value, path) => {
  str(64)(value, path);
  try { assertSnapshotId(value as string); } catch { throw new Error(`malformed result at ${path}`); }
};
const results: Record<BriefResult["action"], Check> = {
  record: shape({ action: oneOf("record"), snapshotId, card }),
  show: shape({ action: oneOf("show"), snapshotId, observations: oneOf("recorded"), card }),
  reopen: shape({
    action: oneOf("reopen"), snapshotId, recordedAtMs: int, recordedBy: context, recorded: card, current: card,
    discrepancies: list(discrepancy, 4096), resumed: oneOf(false), authority: oneOf("none"),
  }),
  list: shape({
    action: oneOf("list"),
    snapshots: list(shape({ snapshotId, recordedAtMs: int, recordedBy: context, branch: nullable(str(1024)), contextPath: str(1024) }), MAX_SNAPSHOTS),
  }),
};
const ERRORS: readonly BriefErrorCode[] = ["invalid-arguments", "invalid-configuration", "rejected", "operation-failed", "context-changed", "session-unavailable"];
const failure = shape({ error: oneOf(...ERRORS), detail: nullable(str(300)) });

/**
 * Validate a helper answer before anything is rendered. Unknown actions,
 * extra fields, prototype names and out-of-bound values are refused whole.
 */
export function parseHelperAnswer(value: unknown): BriefResult | BriefError {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("malformed helper answer");
  const record = value as Record<string, unknown>;
  if (Object.hasOwn(record, "error")) {
    failure(value, "answer");
    return value as BriefError;
  }
  const action = Object.hasOwn(record, "action") ? record.action : undefined;
  if (action !== "record" && action !== "show" && action !== "reopen" && action !== "list") throw new Error("malformed helper answer");
  results[action](value, "answer");
  return value as BriefResult;
}
