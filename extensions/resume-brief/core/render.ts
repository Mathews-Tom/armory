import { canonicalJson, formatTimestamp, inert } from "./index.ts";
import type { Card, Discrepancy } from "./index.ts";

// Plain-text projection. Every value that came from a repository, a source file
// or a native session is passed through `inert`, so it is shown, never obeyed.

function value(item: string | number | boolean | null): string {
  if (item === null) return "unknown";
  return typeof item === "string" ? inert(item) : String(item);
}

function time(ms: number | null): string {
  return ms === null ? "unknown" : formatTimestamp(ms);
}

export function renderCard(card: Card): string {
  const lines = [
    `Resume Brief ${card.featureVersion} — observed ${time(card.observedAtMs)}, evaluated ${time(card.evaluatedAtMs)} for ${card.evaluatedFor.host}`,
    "Authority: none. This card executes nothing and grants no approval.",
    `Objective: ${value(card.objective)}`,
    `Plan: ${value(card.plan.ref)} sha256=${value(card.plan.sha256)} lastCommit=${value(card.plan.lastCommit)} modifiedInWorktree=${value(card.plan.modifiedInWorktree)}`,
    `Last verification: receipt ${value(card.lastVerification.ref)} sha256=${value(card.lastVerification.sha256)} gate=${value(card.lastVerification.gateId)} status=${value(card.lastVerification.status)} finished=${time(card.lastVerification.finishedAtMs)} sameRepository=${value(card.lastVerification.sameRepository)} freshness=not-evaluated (referenced, not re-proved)`,
    `Repository (${card.repository.observation}): branch=${value(card.repository.branch)} detached=${value(card.repository.detached)} head=${value(card.repository.head)} upstream=${value(card.repository.upstream)} dirty=${value(card.repository.dirty)} worktree=${value(card.repository.worktreeRoot)}`,
    `Pull request: declared=${card.repository.pullRequest.declared === null ? "none" : `#${card.repository.pullRequest.declared.number} ${value(card.repository.pullRequest.declared.url)}`} observed=unknown`,
  ];
  if (card.blockers === null) lines.push("Blockers: unknown");
  else if (card.blockers.length === 0) lines.push("Blockers: none recorded");
  else for (const blocker of card.blockers) lines.push(`Blocker ${value(blocker.id)} [${blocker.status}]: ${value(blocker.summary)}`);
  lines.push(`Next action (not executed): ${value(card.nextAction.text)}`);
  lines.push(`Session: ${card.session.kind ?? "none"} id=${value(card.session.id)} cwdMatchesWorktree=${value(card.session.cwdMatchesWorktree)} entries=${value(card.session.entryCount)} lastEntryAt=${value(card.session.lastEntryAt)} handoff=${value(card.session.handoffGeneratedAt)}`);
  if (card.approvals.length === 0) lines.push("Approvals: none recorded");
  for (const hold of card.approvals) {
    lines.push(`Approval hold ${value(hold.id)} (${hold.source}) ${hold.status}${hold.foreignOrigin ? " foreign-origin" : ""} executable=false scope=${value(hold.scope)} origin=${value(`${hold.origin.host}/${hold.origin.accountId ?? "unknown"}/${hold.origin.sessionId ?? "unknown"}`)} granted=${time(hold.grantedAtMs)} expires=${hold.expiresAtMs === null ? "none" : time(hold.expiresAtMs)}`);
  }
  for (const source of card.sources) {
    lines.push(`Source ${source.role}: ${source.status} ${value(source.ref)} sha256=${value(source.sha256)} bytes=${value(source.bytes)} mtime=${time(source.mtimeMs)}${source.diagnostic === null ? "" : ` diagnostic=${value(source.diagnostic)}`}`);
  }
  for (const unknown of card.unknowns) lines.push(`Unknown ${unknown.field}: ${value(unknown.reason)}`);
  return `${lines.join("\n")}\n`;
}

export function renderDiscrepancies(items: readonly Discrepancy[]): string {
  if (items.length === 0) return "Discrepancies: none between the recorded and current observations.\n";
  const lines = [`Discrepancies: ${items.length}`];
  for (const item of items) {
    lines.push(`- ${inert(item.field)} ${item.kind}: recorded=${inert(canonicalJson(item.recorded))} current=${inert(canonicalJson(item.current))} source=${item.source.role} ${value(item.source.ref)} recordedSha256=${value(item.source.recordedSha256)} currentSha256=${value(item.source.currentSha256)}`);
  }
  return `${lines.join("\n")}\n`;
}
