import { BLOCKERS_SCHEMA, CONTEXT_SCHEMA, LIMITS, OMP_SESSION_VERSION, parseTimestamp } from "./index.ts";
import type {
  Approval,
  Blocker,
  BlockersDocument,
  ContextDocument,
  Host,
  OmpHandoffObservation,
  OmpSessionObservation,
  PullRequestClaim,
  ReceiptReference,
  SourceStatus,
} from "./index.ts";

/** A source that was read but cannot supply facts. The status is reported, never swallowed. */
export class SourceError extends Error {
  readonly status: SourceStatus;
  constructor(status: SourceStatus, message: string) {
    super(message);
    this.status = status;
  }
}

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const HOSTS: readonly Host[] = ["standalone", "omp", "claude"];
export const APPROVAL_CUSTOM_TYPE = "armory.resume-brief.approval" as const;

function malformed(message: string): never {
  throw new SourceError("malformed", message);
}

type Fields = Record<string, unknown>;

function object(value: unknown, what: string, allowed: readonly string[]): Fields {
  if (value === null || typeof value !== "object" || Array.isArray(value)) malformed(`${what} must be an object`);
  const fields = value as Fields;
  for (const key of Object.keys(fields)) if (!allowed.includes(key)) malformed(`${what} has unsupported field ${JSON.stringify(key)}`);
  return fields;
}

function text(value: unknown, what: string, maximum: number): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > maximum) malformed(`${what} must be non-empty text of at most ${maximum} characters`);
  return value;
}

function optionalText(value: unknown, what: string, maximum: number): string | null {
  return value === undefined || value === null ? null : text(value, what, maximum);
}

function identifier(value: unknown, what: string): string {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) malformed(`${what} must match ${IDENTIFIER.source}`);
  return value;
}

function receiptGateReference(value: unknown): string {
  if (typeof value !== "string" || value.length === 0 || value.length > LIMITS.referenceChars) malformed("receipt gateId is invalid");
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) malformed("receipt gateId contains a control character");
  }
  return value;
}

function timestamp(value: unknown, what: string): number {
  const parsed = typeof value === "string" ? parseTimestamp(value) : null;
  if (parsed === null) malformed(`${what} must be a UTC timestamp like 2026-01-02T03:04:05Z`);
  return parsed;
}

function list(value: unknown, what: string, maximum: number): unknown[] {
  if (!Array.isArray(value) || value.length > maximum) malformed(`${what} must be a list of at most ${maximum} items`);
  return value;
}

function schema(fields: Fields, expected: string): void {
  if (fields.schema !== expected) {
    throw new SourceError("unsupported-schema", `expected schema ${expected}`);
  }
}

/** Repository-relative POSIX path with no traversal, absolute form, Git metadata or hidden escape. */
export function repositoryPath(value: unknown, what: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 1024 || value.includes("\0") || value.includes("\\") || value.startsWith("/")) {
    throw new SourceError("rejected", `${what} must be a bounded repository-relative path`);
  }
  if (value.split("/").some((part) => part === "" || part === "." || part === ".." || part === ".git")) {
    throw new SourceError("rejected", `${what} contains a forbidden path component`);
  }
  return value;
}

function uniqueIds<T extends { id: string }>(items: T[], what: string): T[] {
  const seen = new Set<string>();
  for (const item of items) {
    if (seen.has(item.id)) malformed(`${what} id ${JSON.stringify(item.id)} is duplicated`);
    seen.add(item.id);
  }
  return items;
}

function host(value: unknown, what: string): Host {
  if (typeof value !== "string" || !HOSTS.includes(value as Host)) malformed(`${what} must be one of ${HOSTS.join(", ")}`);
  return value as Host;
}

function approval(value: unknown, index: number): Approval {
  const what = `approvals[${index}]`;
  const fields = object(value, what, ["id", "scope", "origin", "grantedAt", "expiresAt"]);
  const origin = object(fields.origin, `${what}.origin`, ["host", "accountId", "sessionId"]);
  const grantedAtMs = timestamp(fields.grantedAt, `${what}.grantedAt`);
  if (!("expiresAt" in fields)) malformed(`${what}.expiresAt is required; use null for an approval recorded without expiry`);
  const expiresAtMs = fields.expiresAt === null ? null : timestamp(fields.expiresAt, `${what}.expiresAt`);
  if (expiresAtMs !== null && expiresAtMs <= grantedAtMs) malformed(`${what}.expiresAt must follow grantedAt`);
  return {
    id: identifier(fields.id, `${what}.id`),
    scope: text(fields.scope, `${what}.scope`, LIMITS.scopeChars),
    origin: {
      host: host(origin.host, `${what}.origin.host`),
      accountId: optionalText(origin.accountId, `${what}.origin.accountId`, LIMITS.referenceChars),
      sessionId: optionalText(origin.sessionId, `${what}.origin.sessionId`, LIMITS.referenceChars),
    },
    grantedAtMs,
    expiresAtMs,
    source: "context",
  };
}

function pullRequest(value: unknown): PullRequestClaim | null {
  if (value === undefined || value === null) return null;
  const fields = object(value, "pullRequest", ["number", "url"]);
  if (typeof fields.number !== "number" || !Number.isSafeInteger(fields.number) || fields.number < 1) malformed("pullRequest.number must be a positive integer");
  const url = optionalText(fields.url, "pullRequest.url", LIMITS.urlChars);
  if (url !== null && !/^https:\/\/[^\s/]+\/\S+$/.test(url)) malformed("pullRequest.url must be an https URL");
  return { number: fields.number, url };
}

function sourcePath(value: unknown, what: string): string | null {
  if (value === undefined || value === null) return null;
  const fields = object(value, what, ["path"]);
  return repositoryPath(fields.path, `${what}.path`);
}

/** Project context artifact: objective, selected plan/blocker sources, declared PR and approvals. */
export function parseContext(value: unknown): ContextDocument {
  const fields = object(value, "context", ["schema", "objective", "plan", "blockers", "pullRequest", "approvals"]);
  schema(fields, CONTEXT_SCHEMA);
  return {
    objective: text(fields.objective, "objective", LIMITS.objectiveChars),
    planPath: sourcePath(fields.plan, "plan"),
    blockersPath: sourcePath(fields.blockers, "blockers"),
    pullRequest: pullRequest(fields.pullRequest),
    approvals: uniqueIds(list(fields.approvals ?? [], "approvals", LIMITS.approvals).map(approval), "approval"),
  };
}

function blocker(value: unknown, index: number): Blocker {
  const what = `blockers[${index}]`;
  const fields = object(value, what, ["id", "summary", "status"]);
  if (fields.status !== "open" && fields.status !== "resolved") malformed(`${what}.status must be open or resolved`);
  return { id: identifier(fields.id, `${what}.id`), summary: text(fields.summary, `${what}.summary`, LIMITS.summaryChars), status: fields.status };
}

export function parseBlockers(value: unknown): BlockersDocument {
  const fields = object(value, "blockers document", ["schema", "blockers", "nextAction"]);
  schema(fields, BLOCKERS_SCHEMA);
  return {
    blockers: uniqueIds(list(fields.blockers, "blockers", LIMITS.blockers).map(blocker), "blocker"),
    nextAction: optionalText(fields.nextAction, "nextAction", LIMITS.objectiveChars),
  };
}

/**
 * Allowlisted reference fields of a Verification Receipts schema-1 receipt.
 * The receipt is referenced by identity, never copied or re-proved here.
 */
export function parseReceiptReference(value: unknown): ReceiptReference {
  if (value === null || typeof value !== "object" || Array.isArray(value)) malformed("receipt must be an object");
  const receipt = value as Fields;
  const plan = receipt.plan as Fields | undefined;
  if (receipt.schemaVersion !== 1 || plan === null || typeof plan !== "object" || plan.feature !== "verification-receipts") {
    throw new SourceError("unsupported-schema", "expected a verification-receipts schema 1 receipt");
  }
  const result = receipt.result as Fields | undefined;
  const repository = plan.repository as Fields | undefined;
  const context = plan.context as Fields | undefined;
  const status = result?.status;
  if (status !== "passed" && status !== "failed" && status !== "cancelled" && status !== "incomplete") malformed("receipt result status is not recognised");
  if (typeof receipt.finishedAtMs !== "number" || !Number.isSafeInteger(receipt.finishedAtMs) || receipt.finishedAtMs < 0) malformed("receipt finishedAtMs is invalid");
  if (typeof repository?.repositoryId !== "string" || !/^[a-f0-9]{64}$/.test(repository.repositoryId)) malformed("receipt repository identity is invalid");
  return {
    executionId: identifier(plan.executionId, "receipt executionId"),
    gateId: receiptGateReference(plan.gateId),
    status,
    finishedAtMs: receipt.finishedAtMs,
    repositoryId: repository.repositoryId,
    host: host(context?.host, "receipt context host"),
  };
}

function ompApproval(entry: Fields, sessionId: string, index: number): Approval {
  const data = object(entry.data, `session custom entry ${index} data`, ["id", "scope", "grantedAt", "expiresAt"]);
  const parsed = approval({ ...data, origin: { host: "omp", sessionId } }, index);
  return { ...parsed, source: "omp-session" };
}

/**
 * OMP JSONL session (header version 3). Only header identity, entry counts and
 * feature-owned approval custom entries are read; message bodies are never kept.
 */
export function parseOmpSession(lines: readonly string[]): OmpSessionObservation {
  const first = lines[0];
  if (first === undefined) malformed("session file is empty");
  let header: Fields;
  try { header = JSON.parse(first) as Fields; } catch { return malformed("session header is not JSON"); }
  let headerIndex = 0;
  if (header !== null && typeof header === "object" && header.type === "title" && header.v === 1) {
    headerIndex = 1;
    const line = lines[headerIndex];
    if (line === undefined) malformed("session title slot has no following header");
    try { header = JSON.parse(line) as Fields; } catch { return malformed("session header is not JSON"); }
  }
  if (header === null || typeof header !== "object" || header.type !== "session" || header.version !== OMP_SESSION_VERSION) {
    throw new SourceError("unsupported-schema", `expected an OMP session header with version ${OMP_SESSION_VERSION}`);
  }
  const sessionId = text(header.id, "session id", LIMITS.referenceChars);
  const startedAt = text(header.timestamp, "session timestamp", 64);
  const cwd = text(header.cwd, "session cwd", 4096);
  if (!cwd.startsWith("/")) malformed("session cwd must be absolute");
  const approvals: Approval[] = [];
  let entryCount = 0;
  let lastEntryId: string | null = null;
  let lastEntryAt: string | null = null;
  for (let index = headerIndex + 1; index < lines.length; index++) {
    const line = lines[index];
    if (line === undefined || line.length === 0) continue;
    let entry: Fields;
    try { entry = JSON.parse(line) as Fields; } catch { return malformed(`session line ${index + 1} is not JSON`); }
    if (entry === null || typeof entry !== "object" || typeof entry.type !== "string" || typeof entry.id !== "string" || typeof entry.timestamp !== "string") {
      malformed(`session line ${index + 1} is not a session entry`);
    }
    entryCount++;
    lastEntryId = entry.id.slice(0, LIMITS.referenceChars);
    lastEntryAt = entry.timestamp.slice(0, 64);
    if (entry.type === "custom" && entry.customType === APPROVAL_CUSTOM_TYPE) {
      if (approvals.length >= LIMITS.approvals) malformed("session approval limit exceeded");
      approvals.push(ompApproval(entry, sessionId, approvals.length));
    }
  }
  return { sessionId, version: OMP_SESSION_VERSION, startedAt, cwd, cwdResolved: null, entryCount, lastEntryId, lastEntryAt, approvals: uniqueIds(approvals, "session approval") };
}

const HANDOFF_NAME = /^handoff-(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z\.md$/;

/** OMP saves handoffs as `handoff-<ISO with : and . replaced by ->.md`; only the name is interpreted. */
export function parseOmpHandoffName(name: string): OmpHandoffObservation {
  const match = HANDOFF_NAME.exec(name);
  if (match === null) throw new SourceError("unsupported-schema", "expected an OMP handoff-<timestamp>.md file");
  const iso = `${match[1]}T${match[2]}:${match[3]}:${match[4]}.${match[5]}Z`;
  if (parseTimestamp(iso) === null) malformed("handoff file name timestamp is invalid");
  return { generatedAt: iso };
}
