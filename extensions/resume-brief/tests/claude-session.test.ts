import { describe, expect, test } from "bun:test";
import { buildCard, discrepancies } from "../core/card.ts";
import { CLAUDE_HOST_SCHEMA, parseClaudeHostPayload, parseClaudeSessionProjection, projectClaudeSession } from "../core/claude-session.ts";
import type { ClaudeHostReadings } from "../core/claude-session.ts";
import { parseTimestamp } from "../core/index.ts";
import type { ClaudeSessionObservation, ClaudeSessionProjection, Context, Observations, SourceIdentity } from "../core/index.ts";
import { renderCard } from "../core/render.ts";
import { parseSnapshot } from "../core/snapshot.ts";
import { parseBlockers, parseContext } from "../core/validation.ts";
import { BLOCKERS, CONTEXT } from "./fixture.ts";

const SECRET = "PRIVATE TRANSCRIPT TEXT";
const T0 = parseTimestamp("2026-01-01T00:00:00Z") ?? 0;

function rows(count: number, tools = 0): unknown[] {
  return Array.from({ length: count }, (_, index) => ({
    role: index % 2 === 0 ? "user" : "assistant", text: `${SECRET} ${index}`,
    toolUses: index === 1 ? Array.from({ length: tools }, () => ({ name: "Bash", input: { command: SECRET }, result: SECRET })) : [],
  }));
}

function readings(overrides: Partial<ClaudeHostReadings> = {}): ClaudeHostReadings {
  return {
    sessionId: "claude-session-1", cwd: { ok: true, value: "/work" }, root: { ok: true, value: "/work" },
    turns: { ok: true, value: 2 }, startedAt: { ok: true, value: T0 }, messages: { ok: true, value: rows(3, 2) }, ...overrides,
  };
}

function projection(overrides: Partial<ClaudeHostReadings> = {}): ClaudeSessionProjection {
  const payload = projectClaudeSession(readings(overrides));
  if (!("claudeSession" in payload)) throw new Error("expected a projection");
  return payload.claudeSession;
}

describe("host session projection", () => {
  test("keeps identity, locations and counts but never message or tool bodies", () => {
    const value = projection();
    expect(value).toEqual({
      sessionId: "claude-session-1", cwd: "/work", root: "/work", startedAtMs: T0, turns: 2,
      observedMessages: 3, messagesComplete: true, lastRole: "user", toolUses: 2,
    });
    expect(JSON.stringify(value)).not.toContain(SECRET);
  });

  test("a full host window is incomplete, not a complete transcript total", () => {
    const value = projection({ messages: { ok: true, value: rows(4096) } });
    expect(value).toMatchObject({ observedMessages: 4096, messagesComplete: false });
    expect(projectClaudeSession(readings({ messages: { ok: true, value: rows(4097) } }))).toEqual({ schema: CLAUDE_HOST_SCHEMA, claudeSessionUnavailable: "host-api-malformed" });
  });

  test("an unanswered required query is unavailable and an unanswered optional one stays unknown", () => {
    expect(projectClaudeSession(readings({ messages: { ok: false } }))).toEqual({ schema: CLAUDE_HOST_SCHEMA, claudeSessionUnavailable: "host-api-unavailable" });
    expect(projectClaudeSession(readings({ cwd: { ok: false } }))).toMatchObject({ claudeSessionUnavailable: "host-api-unavailable" });
    expect(projection({ turns: { ok: false }, startedAt: { ok: false } })).toMatchObject({ turns: null, startedAtMs: null });
  });

  test("answers outside the supported shape are malformed rather than coerced", () => {
    for (const bad of [
      { messages: { ok: true as const, value: [{ role: "system", toolUses: [] }] } },
      { messages: { ok: true as const, value: [{ role: "user" }] } },
      { cwd: { ok: true as const, value: "relative/path" } },
      { root: { ok: true as const, value: "/work\u001b[31m" } },
      { turns: { ok: true as const, value: -1 } },
      { sessionId: "has space" },
    ]) {
      expect(projectClaudeSession(readings(bad))).toMatchObject({ claudeSessionUnavailable: "host-api-malformed" });
    }
  });
});

describe("helper-side validation", () => {
  test("accepts exactly the projection and refuses extra, inherited, accessor or contradictory fields", () => {
    const value = projection();
    expect(parseClaudeSessionProjection(JSON.parse(JSON.stringify(value)))).toEqual(value);
    expect(() => parseClaudeSessionProjection({ ...value, text: SECRET })).toThrow("unexpected fields");
    expect(() => parseClaudeSessionProjection(JSON.parse(`{"__proto__":{"sessionId":"x"},${JSON.stringify(value).slice(1)}`))).toThrow("unexpected fields");
    const accessor = { ...value };
    Object.defineProperty(accessor, "turns", { get: () => 2, enumerable: true });
    expect(() => parseClaudeSessionProjection(accessor)).toThrow("data field");
    expect(() => parseClaudeSessionProjection({ ...value, observedMessages: 4096, messagesComplete: true })).toThrow("contradicts");
    expect(() => parseClaudeSessionProjection({ ...value, observedMessages: 0 })).toThrow("contradicts");
  });

  test("the stdin envelope carries a projection or a fixed unavailable reason only", () => {
    expect(parseClaudeHostPayload({ schema: CLAUDE_HOST_SCHEMA, claudeSessionUnavailable: "host-api-unavailable" })).toMatchObject({ claudeSessionUnavailable: "host-api-unavailable" });
    expect(() => parseClaudeHostPayload({ schema: CLAUDE_HOST_SCHEMA, claudeSessionUnavailable: "denied by policy" })).toThrow();
    expect(() => parseClaudeHostPayload({ schema: "armory.resume-brief.claude-host/v0", claudeSession: projection() })).toThrow();
  });
});

const HERE: Context = { host: "claude", accountId: "acct-a", sessionId: "claude-session-1" };

function observations(claude: ClaudeSessionObservation | null, sha: string): Observations {
  const source = (role: SourceIdentity["role"], digit: string): SourceIdentity => ({ role, ref: `${role}.ref`, status: "ok", sha256: digit.repeat(64), bytes: 1, mtimeMs: T0, diagnostic: null });
  return {
    observedAtMs: T0,
    git: { status: "ok", repositoryId: "a".repeat(64), worktreeId: "b".repeat(64), worktreeRoot: "/work", branch: "main", detached: false, head: "c".repeat(40), upstream: null, dirty: null, diagnostic: null },
    sources: [source("context", "1"), source("plan", "2"), source("blockers", "3"), claude === null
      ? { role: "claude-session", ref: "", status: "not-selected", sha256: null, bytes: null, mtimeMs: null, diagnostic: null }
      : { ...source("claude-session", sha), ref: `claude-host-api:session/${claude.sessionId}`, mtimeMs: null }],
    context: parseContext(CONTEXT), plan: { sha256: "2".repeat(64), lastCommit: null, modifiedInWorktree: false }, blockers: parseBlockers(BLOCKERS),
    receipt: null, ompSession: null, ompHandoff: null, claudeSession: claude,
  };
}

describe("cards and discrepancies with a Claude host session", () => {
  test("the card reports bounded session facts and an incomplete window as unknown", () => {
    const full = { ...projection({ messages: { ok: true, value: rows(4096) } }), cwdResolved: "/work", rootResolved: "/elsewhere" };
    const card = buildCard(observations(full, "4"), HERE, T0);
    expect(card.claudeSession).toMatchObject({ kind: "claude-session", cwdMatchesWorktree: true, rootMatchesWorktree: false, messagesComplete: false });
    expect(card.unknowns.map((item) => item.field)).toContain("claudeSession.observedMessages");
    expect(renderCard(card)).toContain("newest 4096 rows only");
    expect(renderCard(card)).not.toContain(SECRET);
  });

  test("reopening from another host session changes only Claude session facts", () => {
    const recorded = buildCard(observations({ ...projection(), cwdResolved: "/work", rootResolved: "/work" }, "4"), HERE, T0);
    const other = { ...projection({ sessionId: "claude-session-2", messages: { ok: true, value: rows(1) } }), cwdResolved: "/work", rootResolved: "/work" };
    const found = discrepancies(recorded, buildCard(observations(other, "5"), { ...HERE, sessionId: "claude-session-2" }, T0));
    expect(found.every((item) => item.source.role === "claude-session")).toBe(true);
    expect(found.find((item) => item.field === "claudeSession.id")).toMatchObject({ recorded: "claude-session-1", current: "claude-session-2" });
    expect(found.find((item) => item.field === "sources.claude-session")).toMatchObject({ source: { recordedSha256: "4".repeat(64), currentSha256: "5".repeat(64) } });
  });

  test("a recorded host session that the current host cannot observe becomes unknown", () => {
    const recorded = buildCard(observations({ ...projection(), cwdResolved: null, rootResolved: null }, "4"), HERE, T0);
    const found = discrepancies(recorded, buildCard(observations(null, "4"), { host: "omp", accountId: "acct-a", sessionId: "omp-1" }, T0));
    expect(found).toEqual([expect.objectContaining({ field: "sources.claude-session", kind: "became-unknown" })]);
  });

  test("snapshots persist the projection strictly", () => {
    const snapshot = {
      schema: "armory.resume-brief.snapshot/v2", featureVersion: "1.0.0", coreVersion: "1.0.0", snapshotId: "20260101T000000000Z-0123abcd",
      recordedAtMs: T0, recordedBy: HERE, repositoryId: "a".repeat(64),
      selection: { contextPath: "brief.json", ompSessionPath: null, ompHandoffPath: null, receiptPath: null },
      observations: observations({ ...projection(), cwdResolved: "/work", rootResolved: "/work" }, "4"),
    };
    expect(parseSnapshot(JSON.parse(JSON.stringify(snapshot))).observations.claudeSession?.observedMessages).toBe(3);
    const tampered = JSON.parse(JSON.stringify(snapshot)) as { observations: { claudeSession: Record<string, unknown> } };
    tampered.observations.claudeSession.text = SECRET;
    expect(() => parseSnapshot(tampered)).toThrow("malformed snapshot");
  });
});
