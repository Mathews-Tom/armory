import { canonicalJson, CLAUDE_MESSAGE_WINDOW, FEATURE, FEATURE_VERSION, formatTimestamp } from "./index.ts";
import type {
  Approval,
  ApprovalHold,
  Card,
  Context,
  Discrepancy,
  DiscrepancyKind,
  HoldStatus,
  Json,
  Observations,
  SourceIdentity,
  SourceRole,
  Unknown,
} from "./index.ts";

type Origin = SourceRole | "git";

function holdStatus(approval: Approval, nowMs: number): HoldStatus {
  if (approval.grantedAtMs > nowMs) return "not-yet-valid";
  if (approval.expiresAtMs === null) return "no-expiry-hold";
  return approval.expiresAtMs <= nowMs ? "expired" : "unexpired-hold";
}

/**
 * Every approval is projected as a non-executable hold. Expiry is judged only
 * from the approval's own recorded time, so a fresh source read cannot renew
 * it, and any origin other than the exact current host/account/session is
 * foreign: unknown origin account or session is never assumed to match.
 */
export function evaluateApproval(approval: Approval, context: Context, nowMs: number): ApprovalHold {
  const status = holdStatus(approval, nowMs);
  const { origin } = approval;
  const foreignOrigin = origin.host !== context.host || origin.accountId !== context.accountId || origin.sessionId !== context.sessionId;
  const reasons = ["recorded approval is evidence only; resume-brief grants no authority and executes nothing"];
  if (status === "expired" && approval.expiresAtMs !== null) reasons.push(`expired at ${formatTimestamp(approval.expiresAtMs)}; source freshness cannot renew it`);
  if (status === "not-yet-valid") reasons.push("granted time is after the evaluation time");
  if (status === "no-expiry-hold") reasons.push("recorded without expiry; retained as an unresolved hold");
  if (foreignOrigin) reasons.push(`origin ${origin.host}/${origin.accountId ?? "unknown-account"}/${origin.sessionId ?? "unknown-session"} is not the current ${context.host} context; approvals are not portable`);
  return {
    id: approval.id,
    scope: approval.scope,
    origin,
    source: approval.source,
    grantedAtMs: approval.grantedAtMs,
    expiresAtMs: approval.expiresAtMs,
    status,
    foreignOrigin,
    executable: false,
    reason: reasons.join("; "),
  };
}

function source(observations: Observations, role: SourceRole): SourceIdentity | undefined {
  return observations.sources.find((item) => item.role === role);
}

function unknowns(observations: Observations): Unknown[] {
  const result: Unknown[] = [];
  if (observations.git.status !== "ok") result.push({ field: "repository", reason: `git ${observations.git.status}: ${observations.git.diagnostic ?? "no detail"}` });
  else if (observations.git.dirty === null) result.push({ field: "repository.dirty", reason: observations.git.diagnostic ?? "working-tree dirty state was not evaluated" });
  for (const item of observations.sources) {
    if (item.status === "ok" || (item.status === "not-selected" && item.diagnostic === null)) continue;
    result.push({ field: `sources.${item.role}`, reason: `${item.status}: ${item.diagnostic ?? "no detail"}` });
  }
  const context = source(observations, "context");
  if (context?.status === "ok" && observations.context?.planPath === null) result.push({ field: "plan", reason: "context selects no plan source" });
  if (context?.status === "ok" && observations.context?.blockersPath === null) result.push({ field: "blockers", reason: "context selects no blockers source" });
  if (source(observations, "receipt")?.status === "not-selected") result.push({ field: "lastVerification", reason: "no receipt selected" });
  if (source(observations, "omp-session")?.status === "not-selected") result.push({ field: "session", reason: "no native session selected" });
  if (observations.claudeSession?.messagesComplete === false) {
    result.push({ field: "claudeSession.observedMessages", reason: `the host returns only the newest ${CLAUDE_MESSAGE_WINDOW} transcript rows; earlier rows were not observed` });
  }
  result.push({ field: "repository.pullRequest.observed", reason: "pull request state is not observed: no network or GitHub calls" });
  return result;
}

function matches(resolved: string | null, worktreeRoot: string | null): boolean | null {
  return resolved === null || worktreeRoot === null ? null : resolved === worktreeRoot;
}

/** Build the card for one set of observations, evaluating approvals for `context` at `nowMs`. */
export function buildCard(observations: Observations, context: Context, nowMs: number): Card {
  const { git, plan, blockers, receipt, ompSession, claudeSession } = observations;
  const ctx = observations.context;
  const approvals = [...(ctx?.approvals ?? []), ...(ompSession?.approvals ?? [])].map((item) => evaluateApproval(item, context, nowMs));
  return {
    feature: FEATURE,
    featureVersion: FEATURE_VERSION,
    observedAtMs: observations.observedAtMs,
    evaluatedAtMs: nowMs,
    evaluatedFor: context,
    objective: ctx?.objective ?? null,
    plan: {
      ref: ctx?.planPath ?? null,
      sha256: plan?.sha256 ?? null,
      lastCommit: plan?.lastCommit ?? null,
      modifiedInWorktree: plan?.modifiedInWorktree ?? null,
    },
    lastVerification: {
      ref: source(observations, "receipt")?.status === "not-selected" ? null : source(observations, "receipt")?.ref ?? null,
      sha256: source(observations, "receipt")?.sha256 ?? null,
      executionId: receipt?.executionId ?? null,
      gateId: receipt?.gateId ?? null,
      status: receipt?.status ?? null,
      finishedAtMs: receipt?.finishedAtMs ?? null,
      sameRepository: receipt === null || git.repositoryId === null ? null : receipt.repositoryId === git.repositoryId,
      freshness: "not-evaluated",
    },
    repository: {
      observation: git.status,
      branch: git.branch,
      detached: git.detached,
      head: git.head,
      upstream: git.upstream,
      dirty: git.dirty,
      worktreeRoot: git.worktreeRoot,
      pullRequest: { declared: ctx?.pullRequest ?? null, observed: null },
    },
    blockers: blockers?.blockers ?? null,
    nextAction: { text: blockers?.nextAction ?? null, executed: false },
    session: {
      kind: ompSession === null ? null : "omp-session",
      id: ompSession?.sessionId ?? null,
      cwdMatchesWorktree: ompSession === null || git.worktreeRoot === null || ompSession.cwdResolved === null ? null : ompSession.cwdResolved === git.worktreeRoot,
      entryCount: ompSession?.entryCount ?? null,
      lastEntryAt: ompSession?.lastEntryAt ?? null,
      handoffGeneratedAt: observations.ompHandoff?.generatedAt ?? null,
    },
    claudeSession: {
      kind: claudeSession === null ? null : "claude-session",
      id: claudeSession?.sessionId ?? null,
      cwdMatchesWorktree: matches(claudeSession?.cwdResolved ?? null, git.worktreeRoot),
      rootMatchesWorktree: matches(claudeSession?.rootResolved ?? null, git.worktreeRoot),
      startedAtMs: claudeSession?.startedAtMs ?? null,
      turns: claudeSession?.turns ?? null,
      observedMessages: claudeSession?.observedMessages ?? null,
      messagesComplete: claudeSession?.messagesComplete ?? null,
      lastRole: claudeSession?.lastRole ?? null,
      toolUses: claudeSession?.toolUses ?? null,
    },
    approvals,
    sources: observations.sources,
    unknowns: unknowns(observations),
    authority: "none",
  };
}

function known(card: Card, origin: Origin): boolean {
  if (origin === "git") return card.repository.observation === "ok";
  return card.sources.find((item) => item.role === origin)?.status === "ok";
}

function sha(card: Card, origin: Origin): string | null {
  return origin === "git" ? null : card.sources.find((item) => item.role === origin)?.sha256 ?? null;
}

function ref(card: Card, origin: Origin): string | null {
  const value = origin === "git" ? card.repository.worktreeRoot : card.sources.find((item) => item.role === origin)?.ref;
  return value === "" ? null : value ?? null;
}

class Collector {
  readonly items: Discrepancy[] = [];
  constructor(private readonly recorded: Card, private readonly current: Card) {}

  private push(field: string, kind: DiscrepancyKind, origin: Origin | "clock", recorded: Json, current: Json): void {
    const linked = origin === "clock" ? null : origin;
    this.items.push({
      field,
      kind,
      recorded,
      current,
      source: {
        role: origin,
        ref: linked === null ? null : ref(this.current, linked) ?? ref(this.recorded, linked),
        recordedSha256: linked === null ? null : sha(this.recorded, linked),
        currentSha256: linked === null ? null : sha(this.current, linked),
      },
    });
  }

  value(field: string, origin: Origin, recorded: Json, current: Json): void {
    if (canonicalJson(recorded) === canonicalJson(current)) return;
    const before = known(this.recorded, origin);
    const after = known(this.current, origin);
    const kind: DiscrepancyKind = before && !after ? "became-unknown" : !before && after ? "became-known" : "changed";
    this.push(field, kind, origin, recorded, current);
  }

  keyed(field: string, origin: Origin, recorded: Map<string, Json>, current: Map<string, Json>): void {
    if (known(this.recorded, origin) !== known(this.current, origin)) return; // Reported once as a source status change.
    for (const [key, value] of recorded) {
      const next = current.get(key);
      if (next === undefined) this.push(`${field}[${key}]`, "removed", origin, value, null);
      else if (canonicalJson(value) !== canonicalJson(next)) this.push(`${field}[${key}]`, "changed", origin, value, next);
    }
    for (const [key, value] of current) if (!recorded.has(key)) this.push(`${field}[${key}]`, "added", origin, null, value);
  }

  expired(field: string, recorded: Json, current: Json): void {
    this.push(field, "expired-since-record", "clock", recorded, current);
  }
}

function sourceJson(item: SourceIdentity | undefined): Json {
  return item === undefined ? null : { ref: item.ref, status: item.status, sha256: item.sha256, diagnostic: item.diagnostic };
}

function approvalJson(hold: ApprovalHold): Json {
  return { scope: hold.scope, origin: { ...hold.origin }, grantedAtMs: hold.grantedAtMs, expiresAtMs: hold.expiresAtMs };
}

/**
 * Exact field-level differences between a recorded card and a current card.
 * Every entry names the source it was read from and both content hashes.
 */
export function discrepancies(recorded: Card, current: Card): Discrepancy[] {
  const out = new Collector(recorded, current);
  const roles = new Set<SourceRole>([...recorded.sources, ...current.sources].map((item) => item.role));
  for (const role of [...roles].sort()) {
    const before = recorded.sources.find((item) => item.role === role);
    const after = current.sources.find((item) => item.role === role);
    if (before?.status !== after?.status || before?.ref !== after?.ref || before?.sha256 !== after?.sha256) {
      out.value(`sources.${role}`, role, sourceJson(before), sourceJson(after));
    }
  }
  const git = (card: Card): Json => ({ observation: card.repository.observation });
  out.value("repository.observation", "git", git(recorded), git(current));
  for (const key of ["worktreeRoot", "branch", "detached", "head", "upstream", "dirty"] as const) {
    if (!known(recorded, "git") || !known(current, "git")) break;
    out.value(`repository.${key}`, "git", recorded.repository[key], current.repository[key]);
  }
  const both = (origin: Origin): boolean => known(recorded, origin) && known(current, origin);
  if (both("context")) {
    out.value("objective", "context", recorded.objective, current.objective);
    out.value("repository.pullRequest.declared", "context", recorded.repository.pullRequest.declared === null ? null : { ...recorded.repository.pullRequest.declared }, current.repository.pullRequest.declared === null ? null : { ...current.repository.pullRequest.declared });
  }
  if (both("plan")) {
    out.value("plan.lastCommit", "plan", recorded.plan.lastCommit, current.plan.lastCommit);
    out.value("plan.modifiedInWorktree", "plan", recorded.plan.modifiedInWorktree, current.plan.modifiedInWorktree);
  }
  if (both("blockers")) {
    const blockers = (card: Card): Map<string, Json> => new Map((card.blockers ?? []).map((item) => [item.id, { summary: item.summary, status: item.status }]));
    out.keyed("blockers", "blockers", blockers(recorded), blockers(current));
    out.value("nextAction.text", "blockers", recorded.nextAction.text, current.nextAction.text);
  }
  if (both("receipt")) {
    for (const key of ["executionId", "gateId", "status", "finishedAtMs", "sameRepository"] as const) {
      out.value(`lastVerification.${key}`, "receipt", recorded.lastVerification[key], current.lastVerification[key]);
    }
  }
  if (both("omp-session")) {
    for (const key of ["id", "cwdMatchesWorktree", "entryCount", "lastEntryAt"] as const) {
      out.value(`session.${key}`, "omp-session", recorded.session[key], current.session[key]);
    }
  }
  if (both("omp-handoff")) out.value("session.handoffGeneratedAt", "omp-handoff", recorded.session.handoffGeneratedAt, current.session.handoffGeneratedAt);
  if (both("claude-session")) {
    for (const key of ["id", "cwdMatchesWorktree", "rootMatchesWorktree", "startedAtMs", "turns", "observedMessages", "messagesComplete", "lastRole", "toolUses"] as const) {
      out.value(`claudeSession.${key}`, "claude-session", recorded.claudeSession[key], current.claudeSession[key]);
    }
  }
  for (const origin of ["context", "omp-session"] as const) {
    const holds = (card: Card): Map<string, Json> => new Map(card.approvals.filter((item) => item.source === origin).map((item) => [item.id, approvalJson(item)]));
    out.keyed(`approvals.${origin}`, origin, holds(recorded), holds(current));
  }
  for (const hold of current.approvals) {
    const before = recorded.approvals.find((item) => item.source === hold.source && item.id === hold.id);
    if (before !== undefined && before.status !== "expired" && hold.status === "expired") {
      out.expired(`approvals.${hold.source}[${hold.id}].status`, before.status, hold.status);
    }
  }
  return out.items;
}
