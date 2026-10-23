// Pure Resume Brief vocabulary. No host, runtime, filesystem, clock or process
// effects: helpers supply observations and the evaluation time explicitly.

export const FEATURE = "resume-brief" as const;
export const FEATURE_VERSION = "1.0.0" as const;
export const CORE_VERSION = "1.0.0" as const;
export const CONTEXT_SCHEMA = "armory.resume-brief.context/v1" as const;
export const BLOCKERS_SCHEMA = "armory.resume-brief.blockers/v1" as const;
export const SNAPSHOT_SCHEMA = "armory.resume-brief.snapshot/v2" as const;
export const OMP_SESSION_VERSION = 3 as const;

export const LIMITS = {
  objectiveChars: 1000,
  summaryChars: 300,
  scopeChars: 300,
  referenceChars: 256,
  urlChars: 512,
  blockers: 128,
  approvals: 64,
  diagnostics: 64,
} as const;

export type Host = "standalone" | "omp" | "claude";

/** Explicit invocation context. References are opaque labels, never credentials. */
export interface Context {
  host: Host;
  accountId: string;
  sessionId: string;
}

export type SourceRole = "context" | "plan" | "blockers" | "receipt" | "omp-session" | "omp-handoff" | "claude-session";

/** `$.session.messages()` returns at most this many newest rows, never a complete total. */
export const CLAUDE_MESSAGE_WINDOW = 4096 as const;

/** Why a source fact is not known. A source is never silently treated as current. */
export type SourceStatus =
  | "ok"
  | "missing"
  | "unreadable"
  | "rejected"
  | "too-large"
  | "unsupported-schema"
  | "malformed"
  | "changed-during-read"
  | "not-selected";

/** Identity of one explicitly selected source, captured around a bounded read. */
export interface SourceIdentity {
  role: SourceRole;
  ref: string;
  status: SourceStatus;
  sha256: string | null;
  bytes: number | null;
  mtimeMs: number | null;
  diagnostic: string | null;
}

export interface GitObservation {
  status: "ok" | "unavailable" | "changed-during-read";
  repositoryId: string | null;
  worktreeId: string | null;
  worktreeRoot: string | null;
  branch: string | null;
  detached: boolean | null;
  head: string | null;
  upstream: string | null;
  dirty: boolean | null;
  diagnostic: string | null;
}

export interface PlanObservation {
  sha256: string;
  lastCommit: string | null;
  modifiedInWorktree: boolean | null;
}

export interface Blocker {
  id: string;
  summary: string;
  status: "open" | "resolved";
}

export interface BlockersDocument {
  blockers: Blocker[];
  nextAction: string | null;
}

export interface ApprovalOrigin {
  host: Host;
  accountId: string | null;
  sessionId: string | null;
}

/** A recorded approval. It is evidence that someone approved something, never a grant. */
export interface Approval {
  id: string;
  scope: string;
  origin: ApprovalOrigin;
  grantedAtMs: number;
  expiresAtMs: number | null;
  source: "context" | "omp-session";
}

export interface PullRequestClaim {
  number: number;
  url: string | null;
}

export interface ContextDocument {
  objective: string;
  planPath: string | null;
  blockersPath: string | null;
  pullRequest: PullRequestClaim | null;
  approvals: Approval[];
}

export interface ReceiptReference {
  executionId: string;
  gateId: string;
  status: "passed" | "failed" | "cancelled" | "incomplete";
  finishedAtMs: number;
  repositoryId: string;
  host: Host;
}

export interface OmpSessionObservation {
  sessionId: string;
  version: number;
  startedAt: string;
  cwd: string;
  /** Canonical form of cwd supplied by the helper when it resolves; null when unresolvable. */
  cwdResolved: string | null;
  entryCount: number;
  lastEntryId: string | null;
  lastEntryAt: string | null;
  approvals: Approval[];
}

export interface OmpHandoffObservation {
  generatedAt: string | null;
}

/**
 * Feature-owned projection of the current Claude Code session, derived from
 * the host API at invocation time. It is not a native file format: only
 * identity, locations and bounded counts are kept, never message text, tool
 * input or tool results.
 */
export interface ClaudeSessionProjection {
  sessionId: string;
  cwd: string;
  root: string;
  /** `$.session.usage().startedAt`; null when the host did not answer. */
  startedAtMs: number | null;
  /** `$.session.turns()`; null when the host did not answer. */
  turns: number | null;
  /** Rows returned by `$.session.messages()`, at most CLAUDE_MESSAGE_WINDOW. */
  observedMessages: number;
  /** False when the window was full, so earlier rows were not observed. */
  messagesComplete: boolean;
  lastRole: "user" | "assistant" | null;
  /** Tool uses among the observed rows only. */
  toolUses: number;
}

export interface ClaudeSessionObservation extends ClaudeSessionProjection {
  /** Canonical forms supplied by the helper when they resolve; null otherwise. */
  cwdResolved: string | null;
  rootResolved: string | null;
}

/** Everything a helper observed at one moment. Unknown facts are null plus a source status. */
export interface Observations {
  observedAtMs: number;
  git: GitObservation;
  sources: SourceIdentity[];
  context: ContextDocument | null;
  plan: PlanObservation | null;
  blockers: BlockersDocument | null;
  receipt: ReceiptReference | null;
  ompSession: OmpSessionObservation | null;
  ompHandoff: OmpHandoffObservation | null;
  claudeSession: ClaudeSessionObservation | null;
}

export type HoldStatus = "expired" | "unexpired-hold" | "no-expiry-hold" | "not-yet-valid";

export interface ApprovalHold {
  id: string;
  scope: string;
  origin: ApprovalOrigin;
  source: Approval["source"];
  grantedAtMs: number;
  expiresAtMs: number | null;
  status: HoldStatus;
  /** Origin differs from the current host/account/session: never portable. */
  foreignOrigin: boolean;
  executable: false;
  reason: string;
}

export interface Unknown {
  field: string;
  reason: string;
}

export interface Card {
  feature: typeof FEATURE;
  featureVersion: typeof FEATURE_VERSION;
  observedAtMs: number;
  evaluatedAtMs: number;
  evaluatedFor: Context;
  objective: string | null;
  plan: { ref: string | null; sha256: string | null; lastCommit: string | null; modifiedInWorktree: boolean | null };
  lastVerification: {
    ref: string | null;
    sha256: string | null;
    executionId: string | null;
    gateId: string | null;
    status: ReceiptReference["status"] | null;
    finishedAtMs: number | null;
    sameRepository: boolean | null;
    freshness: "not-evaluated";
  };
  repository: {
    observation: GitObservation["status"];
    branch: string | null;
    detached: boolean | null;
    head: string | null;
    upstream: string | null;
    dirty: boolean | null;
    worktreeRoot: string | null;
    pullRequest: { declared: PullRequestClaim | null; observed: null };
  };
  blockers: Blocker[] | null;
  nextAction: { text: string | null; executed: false };
  session: {
    kind: "omp-session" | null;
    id: string | null;
    cwdMatchesWorktree: boolean | null;
    entryCount: number | null;
    lastEntryAt: string | null;
    handoffGeneratedAt: string | null;
  };
  claudeSession: {
    kind: "claude-session" | null;
    id: string | null;
    cwdMatchesWorktree: boolean | null;
    rootMatchesWorktree: boolean | null;
    startedAtMs: number | null;
    turns: number | null;
    observedMessages: number | null;
    messagesComplete: boolean | null;
    lastRole: ClaudeSessionProjection["lastRole"];
    toolUses: number | null;
  };
  approvals: ApprovalHold[];
  sources: SourceIdentity[];
  unknowns: Unknown[];
  authority: "none";
}

export type DiscrepancyKind = "changed" | "added" | "removed" | "became-unknown" | "became-known" | "expired-since-record";

export interface Discrepancy {
  field: string;
  kind: DiscrepancyKind;
  recorded: Json;
  current: Json;
  source: { role: SourceRole | "git" | "clock"; ref: string | null; recordedSha256: string | null; currentSha256: string | null };
}

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

export function canonicalJson(value: Json): string {
  if (value === null || typeof value !== "object") {
    if (typeof value === "number" && !Number.isFinite(value)) throw new Error("non-finite JSON number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => {
    const item = value[key];
    if (item === undefined) throw new Error("unsupported JSON value");
    return `${JSON.stringify(key)}:${canonicalJson(item)}`;
  }).join(",")}}`;
}

const TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z$/;

function daysFromCivil(year: number, month: number, day: number): number {
  const y = month <= 2 ? year - 1 : year;
  const era = Math.floor(y / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5) + day - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

/** Strict UTC RFC 3339 (`Z` only) to epoch milliseconds; anything else is null. */
export function parseTimestamp(value: string): number | null {
  const match = TIMESTAMP.exec(value);
  if (match === null) return null;
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number) as [number, number, number, number, number, number];
  const fraction = match[7] ?? "";
  const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  const monthDays = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  if (year < 1970 || monthDays === undefined || day < 1 || day > monthDays || hour > 23 || minute > 59 || second > 59) return null;
  const millis = Number(fraction.padEnd(3, "0").slice(0, 3));
  return ((daysFromCivil(year, month, day) * 24 + hour) * 60 + minute) * 60_000 + second * 1000 + millis;
}

/** Whole-millisecond UTC rendering; sub-millisecond file times are truncated. */
export function formatTimestamp(value: number): string {
  const ms = Math.floor(value);
  const days = Math.floor(ms / 86_400_000);
  const rest = ms - days * 86_400_000;
  // Inverse of daysFromCivil (Howard Hinnant's civil_from_days).
  const z = days + 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const day = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const month = mp < 10 ? mp + 3 : mp - 9;
  const year = yoe + era * 400 + (month <= 2 ? 1 : 0);
  const pad = (value: number, width = 2): string => String(value).padStart(width, "0");
  const hour = Math.floor(rest / 3_600_000);
  const minute = Math.floor((rest % 3_600_000) / 60_000);
  const second = Math.floor((rest % 60_000) / 1000);
  return `${pad(year, 4)}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}:${pad(second)}.${pad(rest % 1000, 3)}Z`;
}

// Characters that could steer a terminal, a Markdown renderer or a shell when
// source text is echoed. Escaped as \u{..} so the rendered value stays inert.
const SYNTAX = new Set(["`", "$", "\\", "\"", "<", ">", "[", "]", "*", "_", "#", "|", "~", "&", ";"]);

function unsafe(code: number): boolean {
  return code <= 0x1f || (code >= 0x7f && code <= 0x9f) || code === 0xad || code === 0x61c || code === 0x180e
    || (code >= 0x200b && code <= 0x200f) || (code >= 0x2028 && code <= 0x202e) || (code >= 0x2060 && code <= 0x206f)
    || code === 0xfeff || (code >= 0xfff9 && code <= 0xfffb) || (code >= 0xfe00 && code <= 0xfe0f)
    || (code >= 0xe0000 && code <= 0xe007f) || (code >= 0xe0100 && code <= 0xe01ef);
}

/** Render untrusted text as a quoted inert literal. */
export function inert(value: string): string {
  let output = "";
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    output += unsafe(code) || SYNTAX.has(char) ? `\\u{${code.toString(16)}}` : char;
  }
  return `"${output}"`;
}
