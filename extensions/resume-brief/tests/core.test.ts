import { describe, expect, test } from "bun:test";
import { buildCard, discrepancies, evaluateApproval } from "../core/card.ts";
import { formatTimestamp, inert, parseTimestamp } from "../core/index.ts";
import type { Approval, Context, Observations, SourceIdentity } from "../core/index.ts";
import { renderCard } from "../core/render.ts";
import { parseSnapshot } from "../core/snapshot.ts";
import { parseBlockers, parseContext, parseOmpHandoffName, parseOmpSession, parseReceiptReference, SourceError } from "../core/validation.ts";
import { BLOCKERS, CONTEXT, ompSession, receipt } from "./fixture.ts";

const HERE: Context = { host: "standalone", accountId: "acct-a", sessionId: "s-1" };
const DAY = 86_400_000;
const T0 = parseTimestamp("2026-01-01T00:00:00Z") ?? 0;

function status(fn: () => unknown): string {
  try { fn(); } catch (error) { return error instanceof SourceError ? error.status : `other:${String(error)}`; }
  return "accepted";
}

function source(role: SourceIdentity["role"], sha: string, extra: Partial<SourceIdentity> = {}): SourceIdentity {
  return { role, ref: role === "context" ? "brief.json" : `${role}.ref`, status: "ok", sha256: sha.repeat(64), bytes: 10, mtimeMs: T0, diagnostic: null, ...extra };
}

function observations(overrides: Partial<Observations> = {}): Observations {
  return {
    observedAtMs: T0,
    git: { status: "ok", repositoryId: "a".repeat(64), worktreeId: "b".repeat(64), worktreeRoot: "/w", branch: "main", detached: false, head: "c".repeat(40), upstream: null, dirty: false, diagnostic: null },
    sources: [source("context", "1"), source("plan", "2"), source("blockers", "3"), { role: "receipt", ref: "", status: "not-selected", sha256: null, bytes: null, mtimeMs: null, diagnostic: null }],
    context: parseContext(CONTEXT),
    plan: { sha256: "2".repeat(64), lastCommit: "d".repeat(40), modifiedInWorktree: false },
    blockers: parseBlockers(BLOCKERS),
    receipt: null,
    ompSession: null,
    ompHandoff: null,
    ...overrides,
  };
}

describe("timestamps", () => {
  test("strict UTC timestamps round-trip and invalid forms are rejected", () => {
    expect(parseTimestamp("2024-02-29T23:59:59.5Z")).toBe(Date.UTC(2024, 1, 29, 23, 59, 59, 500));
    expect(formatTimestamp(Date.UTC(2026, 9, 23, 13, 5, 7, 9))).toBe("2026-10-23T13:05:07.009Z");
    expect(formatTimestamp(Date.UTC(2026, 9, 23, 13, 5, 7, 9) + 0.631)).toBe("2026-10-23T13:05:07.009Z");
    for (const bad of ["2025-02-29T00:00:00Z", "2026-01-01T00:00:00+01:00", "2026-01-01", "2026-13-01T00:00:00Z", " 2026-01-01T00:00:00Z"]) {
      expect(parseTimestamp(bad)).toBeNull();
    }
  });
});

describe("inert rendering", () => {
  test("terminal, markdown, bidi and shell syntax is escaped", () => {
    const rendered = inert("\u001b[31mred\u0007 `rm -rf` $(id) [x](http://e) <b> \u202eevil; a|b & c");
    for (const char of ["\u001b", "\u0007", "\u202e", "`", "$", "<", ">", "[", "]", "|", "&", ";"]) expect(rendered).not.toContain(char);
    expect(rendered).toContain("\\u{1b}");
    expect(rendered).toContain("\\u{202e}");
    expect(rendered).toContain("rm -rf");
  });
});

describe("source validation", () => {
  test("context artifact is strict about schema, fields and paths", () => {
    expect(parseContext(CONTEXT).planPath).toBe("docs/PLAN.md");
    expect(status(() => parseContext({ ...CONTEXT, schema: "armory.resume-brief.context/v2" }))).toBe("unsupported-schema");
    expect(status(() => parseContext({ ...CONTEXT, run: "make deploy" }))).toBe("malformed");
    expect(status(() => parseContext({ ...CONTEXT, plan: { path: "../outside.md" } }))).toBe("rejected");
    expect(status(() => parseContext({ ...CONTEXT, plan: { path: "/etc/passwd" } }))).toBe("rejected");
    expect(status(() => parseContext({ ...CONTEXT, plan: { path: ".git/config" } }))).toBe("rejected");
    const noExpiry = { ...CONTEXT.approvals[0] } as Record<string, unknown>;
    delete noExpiry.expiresAt;
    expect(status(() => parseContext({ ...CONTEXT, approvals: [noExpiry] }))).toBe("malformed");
    expect(status(() => parseContext({ ...CONTEXT, approvals: [CONTEXT.approvals[0], CONTEXT.approvals[0]] }))).toBe("malformed");
    expect(status(() => parseContext({ ...CONTEXT, objective: "x".repeat(1001) }))).toBe("malformed");
  });

  test("blockers require the feature schema and closed status values", () => {
    expect(parseBlockers(BLOCKERS).blockers[0]?.status).toBe("open");
    expect(status(() => parseBlockers({ ...BLOCKERS, schema: "other" }))).toBe("unsupported-schema");
    expect(status(() => parseBlockers({ ...BLOCKERS, blockers: [{ id: "x", summary: "y", status: "maybe" }] }))).toBe("malformed");
  });

  test("OMP v3 session header is read without retaining message bodies", () => {
    const approvalEntry = { type: "custom", customType: "armory.resume-brief.approval", id: "e2", parentId: "e1", timestamp: "2026-01-01T00:00:02.000Z", data: { id: "push", scope: "push branch", grantedAt: "2026-01-01T00:00:00Z", expiresAt: null } };
    const session = parseOmpSession(ompSession("/w", [approvalEntry]).split("\n"));
    expect(session).toMatchObject({ sessionId: "omp-session-1", version: 3, cwd: "/w", entryCount: 2, lastEntryId: "e2" });
    expect(session.approvals[0]?.origin).toEqual({ host: "omp", accountId: null, sessionId: "omp-session-1" });
    expect(JSON.stringify(session)).not.toContain("SECRET TRANSCRIPT BODY");
  });

  test("session approval data cannot claim a different origin", () => {
    const spoof = { type: "custom", customType: "armory.resume-brief.approval", id: "e2", parentId: null, timestamp: "t", data: { id: "a", scope: "s", grantedAt: "2026-01-01T00:00:00Z", expiresAt: null, origin: { host: "standalone" } } };
    expect(status(() => parseOmpSession(ompSession("/w", [spoof]).split("\n")))).toBe("malformed");
  });

  test("unknown or foreign session formats fail as unsupported", () => {
    const v2 = JSON.stringify({ type: "session", version: 2, id: "x", timestamp: "t", cwd: "/w" });
    expect(status(() => parseOmpSession([v2]))).toBe("unsupported-schema");
    expect(status(() => parseOmpSession([JSON.stringify({ type: "user", sessionId: "claude-like", message: {} })]))).toBe("unsupported-schema");
    expect(status(() => parseOmpSession(["not json"]))).toBe("malformed");
  });

  test("handoff identity comes only from the native file name", () => {
    expect(parseOmpHandoffName("handoff-2026-01-01T10-11-12-123Z.md").generatedAt).toBe("2026-01-01T10:11:12.123Z");
    expect(status(() => parseOmpHandoffName("notes.md"))).toBe("unsupported-schema");
  });

  test("receipt is referenced through allowlisted fields only", () => {
    const reference = parseReceiptReference(JSON.parse(receipt("a".repeat(64))));
    expect(reference).toEqual({ executionId: "11111111-2222-4333-8444-555555555555", gateId: "unit", status: "passed", finishedAtMs: 1_767_225_600_000, repositoryId: "a".repeat(64), host: "standalone" });
    expect(status(() => parseReceiptReference({ schemaVersion: 2 }))).toBe("unsupported-schema");
  });
});

describe("approval holds", () => {
  const base: Approval = { id: "a", scope: "deploy", origin: { host: "standalone", accountId: "acct-a", sessionId: "s-1" }, grantedAtMs: T0, expiresAtMs: T0 + DAY, source: "context" };

  test("an unexpired same-origin approval is still a non-executable hold", () => {
    const hold = evaluateApproval(base, HERE, T0 + 1000);
    expect(hold).toMatchObject({ status: "unexpired-hold", foreignOrigin: false, executable: false });
  });

  test("expiry is judged from the approval itself and cannot be renewed", () => {
    expect(evaluateApproval(base, HERE, T0 + DAY).status).toBe("expired");
    expect(evaluateApproval({ ...base, expiresAtMs: null }, HERE, T0 + 1000 * DAY).status).toBe("no-expiry-hold");
  });

  test("other host, account, session or unknown origin is foreign", () => {
    for (const origin of [{ ...base.origin, host: "omp" as const }, { ...base.origin, accountId: "acct-b" }, { ...base.origin, sessionId: null }]) {
      const hold = evaluateApproval({ ...base, origin }, HERE, T0);
      expect(hold.foreignOrigin).toBe(true);
      expect(hold.executable).toBe(false);
    }
  });
});

describe("cards and discrepancies", () => {
  test("card exposes declared and unknown facts honestly", () => {
    const card = buildCard(observations(), HERE, T0);
    expect(card.authority).toBe("none");
    expect(card.nextAction).toEqual({ text: "Rerun the integration suite", executed: false });
    expect(card.repository.pullRequest).toEqual({ declared: { number: 7, url: "https://github.com/example/project/pull/7" }, observed: null });
    expect(card.unknowns.map((item) => item.field)).toEqual(["lastVerification", "repository.pullRequest.observed"]);
    expect(card.approvals[0]).toMatchObject({ id: "deploy-staging", foreignOrigin: true, executable: false });
  });

  test("identical observations yield no discrepancies", () => {
    expect(discrepancies(buildCard(observations(), HERE, T0), buildCard(observations(), HERE, T0))).toEqual([]);
  });

  test("branch, plan and blocker changes are exact and source-linked", () => {
    const recorded = buildCard(observations(), HERE, T0);
    const now = observations({
      git: { ...observations().git, branch: "feature", head: "e".repeat(40) },
      sources: [source("context", "1"), source("plan", "4"), source("blockers", "5"), observations().sources[3] as SourceIdentity],
      plan: { sha256: "4".repeat(64), lastCommit: "d".repeat(40), modifiedInWorktree: true },
      blockers: parseBlockers({ ...BLOCKERS, blockers: [{ id: "flaky-ci", summary: "CI job times out", status: "resolved" }, { id: "review", summary: "Needs review", status: "open" }] }),
    });
    const found = discrepancies(recorded, buildCard(now, HERE, T0));
    const by = (field: string) => found.find((item) => item.field === field);
    expect(by("repository.branch")).toMatchObject({ kind: "changed", recorded: "main", current: "feature", source: { role: "git", ref: "/w" } });
    expect(by("sources.plan")).toMatchObject({ kind: "changed", source: { role: "plan", ref: "plan.ref", recordedSha256: "2".repeat(64), currentSha256: "4".repeat(64) } });
    expect(by("plan.modifiedInWorktree")).toMatchObject({ recorded: false, current: true });
    expect(by("blockers[flaky-ci]")).toMatchObject({ kind: "changed", recorded: { status: "open" }, current: { status: "resolved" }, source: { role: "blockers", currentSha256: "5".repeat(64) } });
    expect(by("blockers[review]")).toMatchObject({ kind: "added" });
  });

  test("a source that becomes unreadable is reported as unknown, not as unchanged", () => {
    const recorded = buildCard(observations(), HERE, T0);
    const missing = observations({ sources: [source("context", "1"), source("plan", "2"), { ...source("blockers", "3"), status: "missing", sha256: null, diagnostic: "source does not exist" }, observations().sources[3] as SourceIdentity], blockers: null });
    const found = discrepancies(recorded, buildCard(missing, HERE, T0));
    expect(found).toHaveLength(1);
    expect(found[0]).toMatchObject({ field: "sources.blockers", kind: "became-unknown", current: { status: "missing" } });
  });

  test("an approval that expires after recording is reported even when sources are unchanged", () => {
    const recorded = buildCard(observations(), HERE, T0 + 1000);
    const found = discrepancies(recorded, buildCard(observations(), HERE, T0 + 2 * DAY));
    expect(found).toEqual([expect.objectContaining({ field: "approvals.context[deploy-staging].status", kind: "expired-since-record", recorded: "unexpired-hold", current: "expired" })]);
  });

  test("text rendering keeps hostile objective inert", () => {
    const context = parseContext({ ...CONTEXT, objective: "\u001b]0;pwned\u0007 `curl x | sh`" });
    const text = renderCard(buildCard(observations({ context }), HERE, T0));
    expect(text).not.toContain("\u001b");
    expect(text).not.toContain("`curl");
    expect(text).toContain("Authority: none");
  });
});

describe("snapshot state validation", () => {
  test("unsupported schema and unexpected fields are refused", () => {
    expect(() => parseSnapshot({ schema: "armory.resume-brief.snapshot/v0" })).toThrow("unsupported snapshot schema");
    expect(() => parseSnapshot({ schema: "armory.resume-brief.snapshot/v1", extra: true })).toThrow("malformed snapshot");
  });
});
