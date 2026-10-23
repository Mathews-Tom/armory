import { describe, expect, test } from "bun:test";
import { buildCard } from "../core/card.ts";
import { parseTimestamp } from "../core/index.ts";
import type { Context, Observations } from "../core/index.ts";
import { CommandError, parseCommand, parseHelperAnswer } from "../core/protocol.ts";
import type { RecordResult, ReopenResult } from "../core/protocol.ts";
import { asciiJson, renderResult } from "../core/render.ts";
import { parseBlockers, parseContext } from "../core/validation.ts";
import { BLOCKERS, CONTEXT } from "./fixture.ts";

const T0 = parseTimestamp("2026-01-01T00:00:00Z") ?? 0;
const HERE: Context = { host: "claude", accountId: "acct-a", sessionId: "claude-session-1" };
const ID = "20260101T000000000Z-0123abcd";

describe("/armory-brief grammar", () => {
  test("accepts only the literal actions and snapshot ids", () => {
    expect(parseCommand("")).toEqual({ action: "help" });
    expect(parseCommand("  record  ")).toEqual({ action: "record", json: false });
    expect(parseCommand("reopen")).toEqual({ action: "reopen", snapshot: "latest", json: false });
    expect(parseCommand(`show ${ID} --json`)).toEqual({ action: "show", snapshot: ID, json: true });
    expect(parseCommand("--json list")).toEqual({ action: "list", json: true });
  });

  test("shell syntax, paths, extra words and unknown actions are refused, not interpreted", () => {
    for (const bad of ["record; rm -rf /", "reopen ../../etc/passwd", "show $(id)", "record extra", "resume", "list --json --json", "help me", "x".repeat(300)]) {
      expect(() => parseCommand(bad)).toThrow(CommandError);
    }
  });
});

function observations(objective: string): Observations {
  return {
    observedAtMs: T0,
    git: { status: "ok", repositoryId: "a".repeat(64), worktreeId: "b".repeat(64), worktreeRoot: "/work", branch: "main", detached: false, head: "c".repeat(40), upstream: null, dirty: null, diagnostic: null },
    sources: [{ role: "context", ref: "brief.json", status: "ok", sha256: "1".repeat(64), bytes: 1, mtimeMs: T0, diagnostic: null }],
    context: parseContext({ ...CONTEXT, objective }), plan: null, blockers: parseBlockers(BLOCKERS),
    receipt: null, ompSession: null, ompHandoff: null, claudeSession: null,
  };
}

function record(objective = "Ship it"): RecordResult {
  return { action: "record", snapshotId: ID, card: buildCard(observations(objective), HERE, T0) };
}

describe("helper answer validation", () => {
  test("accepts complete answers as produced", () => {
    const card = record().card;
    const reopen: ReopenResult = {
      action: "reopen", snapshotId: ID, recordedAtMs: T0, recordedBy: HERE, recorded: card, current: card,
      discrepancies: [{ field: "repository.branch", kind: "changed", recorded: "main", current: "next", source: { role: "git", ref: "/work", recordedSha256: null, currentSha256: null } }],
      resumed: false, authority: "none",
    };
    for (const answer of [record(), reopen, { action: "list", snapshots: [] }, { error: "rejected", detail: "snapshot not found" }]) {
      expect(parseHelperAnswer(JSON.parse(JSON.stringify(answer)))).toEqual(answer as never);
    }
  });

  test("extra, prototype-named, authority-granting or unknown answers are refused whole", () => {
    const value = JSON.parse(JSON.stringify(record())) as { card: Record<string, unknown> } & Record<string, unknown>;
    expect(() => parseHelperAnswer({ ...value, transcript: "body" })).toThrow();
    expect(() => parseHelperAnswer({ ...value, card: { ...value.card, authority: "granted" } })).toThrow();
    expect(() => parseHelperAnswer({ ...value, card: { ...value.card, nextAction: { text: "x", executed: true } } })).toThrow();
    expect(() => parseHelperAnswer(JSON.parse(`{"__proto__":{},${JSON.stringify(value).slice(1)}`))).toThrow();
    expect(() => parseHelperAnswer({ action: "resume" })).toThrow();
    expect(() => parseHelperAnswer({ error: "rejected", detail: "x", path: "/private" })).toThrow();
    expect(() => parseHelperAnswer({ action: "list", snapshots: [{ snapshotId: "../x", recordedAtMs: 0, recordedBy: HERE, branch: null, contextPath: "b" }] })).toThrow();
  });
});

describe("rendering", () => {
  test("text and JSON answers keep hostile source text inert", () => {
    const hostile = "\u001b]0;pwned\u0007 `curl x | sh` ‮ [x](javascript:y)";
    const answer = record(hostile);
    const text = renderResult(answer);
    for (const char of ["\u001b", "\u0007", "‮", "`"]) expect(text).not.toContain(char);
    expect(text).toContain("Authority: none");
    const json = asciiJson(answer);
    expect(/^[\x20-\x7e]*$/.test(json)).toBe(true);
    expect(JSON.parse(json)).toEqual(answer as never);
  });
});
