import { CLAUDE_MESSAGE_WINDOW, LIMITS } from "./index.ts";
import type { ClaudeSessionProjection } from "./index.ts";
import { SourceError } from "./validation.ts";

// The Claude Code mod reads its current session through `$.session` and hands
// only this projection to the bundled helper. Message text, tool input and
// tool results are never read here, so they cannot reach the helper, a
// snapshot or rendered output.

export const CLAUDE_HOST_SCHEMA = "armory.resume-brief.claude-host/v1" as const;
const MAX_TOOL_USES = 1_000_000;

/** One host API answer: its value, or the fact that the host did not supply it. */
export type Reading<T> = { ok: true; value: T } | { ok: false };

export interface ClaudeHostReadings {
  sessionId: string;
  cwd: Reading<unknown>;
  root: Reading<unknown>;
  turns: Reading<unknown>;
  startedAt: Reading<unknown>;
  messages: Reading<unknown>;
}

export type UnavailableReason = "host-api-unavailable" | "host-api-malformed";

/** What the mod sends the helper on stdin. */
export type ClaudeHostPayload =
  | { schema: typeof CLAUDE_HOST_SCHEMA; claudeSession: ClaudeSessionProjection }
  | { schema: typeof CLAUDE_HOST_SCHEMA; claudeSessionUnavailable: UnavailableReason };

function malformed(message: string): never {
  throw new SourceError("malformed", message);
}

function reference(value: unknown, what: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > LIMITS.referenceChars || !/^[\x21-\x7e]+$/.test(value)) {
    malformed(`${what} must be a printable reference of at most ${LIMITS.referenceChars} characters`);
  }
  return value;
}

function absolute(value: unknown, what: string): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.length > 4096) malformed(`${what} must be an absolute path`);
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) malformed(`${what} contains a control character`);
  }
  return value;
}

function count(value: unknown, what: string, maximum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > maximum) malformed(`${what} must be an integer from 0 to ${maximum}`);
  return value;
}

function plain(value: unknown, what: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) malformed(`${what} must be an object`);
  const prototype: unknown = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) malformed(`${what} must be a plain object`);
  return value as Record<string, unknown>;
}

/** Own data properties with exactly these names; accessors and extra keys are refused. */
function exact(value: unknown, what: string, keys: readonly string[]): Record<string, unknown> {
  const record = plain(value, what);
  const names = Reflect.ownKeys(record);
  if (names.length !== keys.length || names.some((name) => typeof name !== "string" || !keys.includes(name))) malformed(`${what} has unexpected fields`);
  const result: Record<string, unknown> = {};
  for (const key of keys) {
    const descriptor = Object.getOwnPropertyDescriptor(record, key);
    if (descriptor === undefined || !("value" in descriptor)) malformed(`${what}.${key} must be a data field`);
    result[key] = descriptor.value as unknown;
  }
  return result;
}

function messageFacts(value: unknown): Pick<ClaudeSessionProjection, "observedMessages" | "messagesComplete" | "lastRole" | "toolUses"> {
  if (!Array.isArray(value)) malformed("session messages must be a list");
  const length = value.length;
  if (length > CLAUDE_MESSAGE_WINDOW) malformed(`session messages exceed the ${CLAUDE_MESSAGE_WINDOW}-row host window`);
  let toolUses = 0;
  let lastRole: ClaudeSessionProjection["lastRole"] = null;
  for (let index = 0; index < length; index++) {
    const row = value[index] as unknown;
    if (row === null || typeof row !== "object" || Array.isArray(row)) malformed(`session message ${index} must be an object`);
    const role = Object.getOwnPropertyDescriptor(row, "role")?.value as unknown;
    const uses = Object.getOwnPropertyDescriptor(row, "toolUses")?.value as unknown;
    if (role !== "user" && role !== "assistant") malformed(`session message ${index} has an unsupported role`);
    if (!Array.isArray(uses)) malformed(`session message ${index} has no tool-use list`);
    toolUses += uses.length;
    if (toolUses > MAX_TOOL_USES) malformed(`session tool uses exceed ${MAX_TOOL_USES}`);
    lastRole = role;
  }
  return { observedMessages: length, messagesComplete: length < CLAUDE_MESSAGE_WINDOW, lastRole, toolUses };
}

/**
 * Reduce host API answers to bounded counts. Location and transcript answers
 * are required; turn count and start time stay unknown when unanswered.
 */
export function projectClaudeSession(readings: ClaudeHostReadings): ClaudeHostPayload {
  if (!readings.cwd.ok || !readings.root.ok || !readings.messages.ok) {
    return { schema: CLAUDE_HOST_SCHEMA, claudeSessionUnavailable: "host-api-unavailable" };
  }
  try {
    const usage = readings.startedAt.ok ? readings.startedAt.value : null;
    const projection: ClaudeSessionProjection = {
      sessionId: reference(readings.sessionId, "session id"),
      cwd: absolute(readings.cwd.value, "session cwd"),
      root: absolute(readings.root.value, "session root"),
      startedAtMs: usage === null ? null : count(usage, "session start", Number.MAX_SAFE_INTEGER),
      turns: readings.turns.ok ? count(readings.turns.value, "session turns", Number.MAX_SAFE_INTEGER) : null,
      ...messageFacts(readings.messages.value),
    };
    return { schema: CLAUDE_HOST_SCHEMA, claudeSession: projection };
  } catch (error) {
    if (!(error instanceof SourceError)) throw error;
    return { schema: CLAUDE_HOST_SCHEMA, claudeSessionUnavailable: "host-api-malformed" };
  }
}

const PROJECTION_KEYS = ["sessionId", "cwd", "root", "startedAtMs", "turns", "observedMessages", "messagesComplete", "lastRole", "toolUses"] as const;

/** Strict validation on the helper side of the process boundary. */
export function parseClaudeSessionProjection(value: unknown): ClaudeSessionProjection {
  const fields = exact(value, "claude session", PROJECTION_KEYS);
  const observedMessages = count(fields.observedMessages, "observedMessages", CLAUDE_MESSAGE_WINDOW);
  if (fields.messagesComplete !== (observedMessages < CLAUDE_MESSAGE_WINDOW)) malformed("messagesComplete contradicts the observed row count");
  const lastRole = fields.lastRole;
  if (observedMessages === 0 ? lastRole !== null : lastRole !== "user" && lastRole !== "assistant") malformed("lastRole contradicts the observed rows");
  return {
    sessionId: reference(fields.sessionId, "sessionId"),
    cwd: absolute(fields.cwd, "cwd"),
    root: absolute(fields.root, "root"),
    startedAtMs: fields.startedAtMs === null ? null : count(fields.startedAtMs, "startedAtMs", Number.MAX_SAFE_INTEGER),
    turns: fields.turns === null ? null : count(fields.turns, "turns", Number.MAX_SAFE_INTEGER),
    observedMessages,
    messagesComplete: observedMessages < CLAUDE_MESSAGE_WINDOW,
    lastRole: lastRole as ClaudeSessionProjection["lastRole"],
    toolUses: count(fields.toolUses, "toolUses", MAX_TOOL_USES),
  };
}

/** Parse the stdin envelope; anything else is malformed rather than ignored. */
export function parseClaudeHostPayload(value: unknown): ClaudeHostPayload {
  const record = plain(value, "claude host payload");
  if (Object.hasOwn(record, "claudeSession")) {
    const fields = exact(record, "claude host payload", ["schema", "claudeSession"]);
    if (fields.schema !== CLAUDE_HOST_SCHEMA) throw new SourceError("unsupported-schema", `expected ${CLAUDE_HOST_SCHEMA}`);
    return { schema: CLAUDE_HOST_SCHEMA, claudeSession: parseClaudeSessionProjection(fields.claudeSession) };
  }
  const fields = exact(record, "claude host payload", ["schema", "claudeSessionUnavailable"]);
  if (fields.schema !== CLAUDE_HOST_SCHEMA) throw new SourceError("unsupported-schema", `expected ${CLAUDE_HOST_SCHEMA}`);
  const reason = fields.claudeSessionUnavailable;
  if (reason !== "host-api-unavailable" && reason !== "host-api-malformed") malformed("unknown unavailable reason");
  return { schema: CLAUDE_HOST_SCHEMA, claudeSessionUnavailable: reason };
}
