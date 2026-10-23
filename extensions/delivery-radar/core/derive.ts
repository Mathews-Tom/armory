import { SCHEMA } from "./types.ts";
import type { Binding, Dimension, Observation, PullIdentity, PullObservation, PullView, RadarView, RequiredPolicy, Review, State } from "./types.ts";
import { checks, DEFAULT_MAX_AGE_MS, diagnostic, identity, policy, provenance, publication, record, reviews, text, threads, timestamp, validateSelection } from "./validation.ts";

type Read<T> = { value: T | null; refs: string[]; issues: string[] };
type Window = { start: number; finish: number; now: number; maxAge: number; valid: boolean };
type Pull = { view: PullView; identity: PullIdentity | null };

function dimension(state: State, reasons: string[], ...refs: readonly (readonly string[])[]): Dimension {
  return { state, reasons, sources: [...new Set(refs.flat())].sort() };
}

function sameBinding(value: unknown, expected: Binding): boolean {
  return record(value) && value.repository === expected.repository && value.pullRequest === expected.pullRequest && value.headOid === expected.headOid && value.baseOid === expected.baseOid && value.viewerId === expected.viewerId;
}

function read<T>(source: unknown, valid: (value: unknown) => value is T, name: string, window: Window, binding?: Binding): Read<T> {
  const refs = record(source) && provenance(source.reference) ? [String(source.reference)] : [];
  const unavailable = (reason: string): Read<T> => ({ value: null, refs, issues: [`${name}: ${reason}`] });
  if (!record(source)) return unavailable("source missing or malformed");
  if (!["available", "partial", "unavailable", "rate-limited", "malformed", "not-selected"].includes(source.status as string)) return unavailable("malformed status");
  if (source.status !== "available") return unavailable(String(source.status));
  if (!window.valid) return unavailable("observation time window invalid or stale");
  const at = timestamp(source.observedAt);
  if (at === null || at < window.start || at > window.finish || at > window.now || window.now - at > window.maxAge) return unavailable("source time invalid, outside observation, or stale");
  if (refs.length === 0 || !diagnostic(source.diagnostic)) return unavailable("provenance malformed");
  if (binding && !sameBinding(source.binding, binding)) return unavailable("repository/PR/head/base/viewer binding mismatch");
  if (!valid(source.value)) return unavailable("source value malformed");
  return { value: source.value, refs, issues: [] };
}

function binding(repository: string, value: PullIdentity, viewerId: string): Binding {
  return { repository, pullRequest: value.number, headOid: value.headOid, baseOid: value.baseOid, viewerId };
}

function unknownPull(number: number, at: number, reasons: string[], identityValue: PullIdentity | null = null): Pull {
  const unknown = dimension("unknown", reasons);
  return { identity: null, view: {
    number, title: identityValue?.title ?? "Identity unavailable", url: identityValue?.url ?? "", headOid: identityValue?.headOid ?? null, baseOid: identityValue?.baseOid ?? null, observedAt: at,
    implementation: unknown, verification: unknown, review: unknown, merge: unknown, publication: unknown,
    action: "owner-decision", nextAction: "Refresh complete source-bound observations before deciding readiness", diagnostics: reasons,
  } };
}

function verificationDimension(observation: PullObservation, current: PullIdentity, required: Read<RequiredPolicy>, window: Window, bound: Binding): Dimension {
  const observed = read(observation.checks, checks, "checks", window, bound);
  if (!required.value || !observed.value) return dimension("unknown", [...required.issues, ...observed.issues], required.refs, observed.refs);
  if (required.value.unsupported.length > 0) return dimension("unknown", ["Required policy includes unmodelled rules"], required.refs, observed.refs);
  if (required.value.checks.length === 0) return dimension("unknown", ["No required checks configured; this does not prove tested integration"], required.refs, observed.refs);
  const results: { state: State; reason: string }[] = [];
  const checkIds: string[] = [];
  for (const expected of required.value.checks) {
    const matching = observed.value.filter((check) => check.context === expected.context && (expected.publisherId === null || check.publisherId === expected.publisherId) && check.headOid === current.headOid);
    if (matching.length === 0) {
      results.push({ state: "unknown", reason: `Missing required check: ${expected.context}` });
      continue;
    }
    // Multiple runs/status contexts cannot be safely ordered without a run-attempt identity.
    if (matching.length !== 1) {
      results.push({ state: "unknown", reason: `Ambiguous required check runs: ${expected.context}` });
      continue;
    }
    const check = matching[0];
    if (!check) continue;
    checkIds.push(`check:${check.id}`);
    if (check.completedAt !== null && check.completedAt > observation.checks.observedAt) {
      results.push({ state: "unknown", reason: `Check completion is after its observation: ${expected.context}` });
    } else if (check.state === "failed" || check.state === "cancelled") {
      results.push({ state: "failed", reason: `Required check ${check.state}: ${expected.context}` });
    } else if (check.state === "pending") {
      results.push({ state: "pending", reason: `Required check pending: ${expected.context}` });
    } else if (check.state === "unknown") {
      results.push({ state: "unknown", reason: `Required check state unknown: ${expected.context}` });
    } else if (check.testedBaseOid !== current.baseOid) {
      results.push({ state: "unknown", reason: `Head-only or old-base check does not prove tested base: ${expected.context}` });
    } else {
      results.push({ state: "passed", reason: `Required check passed on observed head and tested base: ${expected.context}` });
    }
  }
  const state = results.some((result) => result.state === "failed") ? "failed" : results.some((result) => result.state === "unknown") ? "unknown" : results.some((result) => result.state === "pending") ? "pending" : "passed";
  return dimension(state, results.map((result) => result.reason), required.refs, observed.refs, checkIds);
}

function reviewDimension(observation: PullObservation, current: PullIdentity, required: Read<RequiredPolicy>, window: Window, bound: Binding): Dimension {
  const observed = read(observation.reviews, reviews, "reviews", window, bound);
  const discussion = read(observation.threads, threads, "threads", window, bound);
  const refs = [required.refs, observed.refs, discussion.refs];
  if (!observed.value || !discussion.value) return dimension("unknown", [...observed.issues, ...discussion.issues, ...required.issues], ...refs);
  const latest = new Map<string, Review>();
  const ambiguous = new Set<string>();
  for (const review of observed.value) {
    if (review.state === "PENDING") continue;
    if (review.submittedAt === null || review.submittedAt > observation.reviews.observedAt) return dimension("unknown", ["Review submission time invalid"], ...refs);
    // Comment-only submissions do not dismiss a prior approval/change request.
    if (review.state === "COMMENTED") continue;
    const previous = latest.get(review.reviewerId);
    if (previous && previous.submittedAt === review.submittedAt && previous.id !== review.id) ambiguous.add(review.reviewerId);
    if (!previous || (previous.submittedAt ?? -1) < review.submittedAt) {
      latest.set(review.reviewerId, review);
      ambiguous.delete(review.reviewerId);
    }
  }
  const decisions = [...latest.values()];
  refs.push(decisions.map((review) => `review:${review.id}`), discussion.value.filter((thread) => !thread.resolved).map((thread) => `thread:${thread.id}`));
  const reasons: string[] = [];
  if (decisions.some((review) => review.state === "CHANGES_REQUESTED")) reasons.push("Outstanding changes requested");
  if (discussion.value.some((thread) => !thread.resolved)) reasons.push("Unresolved review threads (including outdated threads)");
  if (reasons.length > 0) return dimension("failed", reasons, ...refs);
  if (ambiguous.size > 0) return dimension("unknown", ["Latest review decision is ambiguous"], ...refs);
  if (!required.value) return dimension("unknown", required.issues, ...refs);
  if (required.value.unsupported.length > 0 || required.value.requireCodeOwnerReview || required.value.requireLatestApproval) {
    return dimension("unknown", ["Codeowner/latest-approval or unmodelled policy cannot be proved from basic reviews"], ...refs);
  }
  const approved = decisions.filter((review) => review.state === "APPROVED" && review.commitOid === current.headOid).length;
  if (decisions.some((review) => review.state === "DISMISSED")) reasons.push("Dismissed reviews do not count as approval");
  if (decisions.some((review) => review.state === "APPROVED" && review.commitOid !== current.headOid)) reasons.push("Old-head approvals do not prove current review");
  if (approved < required.value.requiredApprovals) return dimension("pending", [...reasons, `Current-head approvals ${approved}/${required.value.requiredApprovals}`], ...refs);
  return dimension("passed", [...reasons, "Current-head review requirements satisfied; no unresolved threads"], ...refs);
}

function publicationDimension(observation: PullObservation, current: PullIdentity, window: Window, bound: Binding): Dimension {
  const observed = read(observation.publication, publication, "publication", window, bound);
  if (!observed.value) return dimension("unknown", observed.issues, observed.refs);
  const artifact = observed.value;
  const expectedCommit = current.state === "MERGED" ? current.mergeCommitOid : current.headOid;
  if (artifact.state === "unknown") return dimension("unknown", ["Publication source does not establish artifact publication"], observed.refs);
  if (expectedCommit === null || artifact.commitOid !== expectedCommit) return dimension("unknown", ["Publication commit does not match observed delivery identity"], observed.refs);
  if (artifact.state === "pending" || artifact.state === "failed") return dimension(artifact.state, [`Artifact publication ${artifact.state}`], observed.refs);
  if (artifact.artifactIds.length === 0 || artifact.url === null || observation.publication.reference === observation.checks?.reference) return dimension("unknown", ["Publication needs independently sourced artifact identity, commit and URL; workflow success is insufficient"], observed.refs);
  return dimension("passed", ["Independently observed published artifacts match delivery commit", ...artifact.artifactIds], observed.refs);
}

function chooseAction(view: PullView): void {
  if (view.implementation.state === "failed" || view.verification.state === "failed" || view.merge.state === "failed") {
    view.action = "agent-work";
    view.nextAction = "Address closed implementation, merge conflicts or failed verification before continuing";
  } else if (view.implementation.state === "pending") {
    view.action = "agent-work";
    view.nextAction = "Finish implementation and leave draft state when ready";
  } else if (view.review.state === "failed") {
    view.action = "agent-work";
    view.nextAction = "Address requested changes and unresolved review discussion; do not resolve threads automatically";
  } else if ([view.implementation, view.verification, view.review, view.merge].some((item) => item.state === "unknown")) {
    view.action = "owner-decision";
    view.nextAction = "Obtain missing current evidence or decide unsupported policy; readiness is unknown";
  } else if ([view.verification, view.review, view.merge, view.publication].some((item) => item.state === "pending")) {
    view.action = "external-wait";
    view.nextAction = "Wait for current checks, review, selected parent merge or artifact publication; refresh explicitly";
  } else if (view.publication.state === "unknown" || view.publication.state === "failed" || !view.merge.reasons.includes("Already merged (not proof of verification or publication)")) {
    view.action = "owner-decision";
    view.nextAction = "Owner decides merge/publication; merged or workflow success alone does not establish publication";
  } else {
    view.action = "none";
    view.nextAction = "No outstanding action demonstrated by the selected evidence";
  }
}

function derivePull(number: number, observation: PullObservation, repository: string, viewerId: string, window: Window): Pull {
  const before = read(observation.before, identity, "PR before", window);
  const after = read(observation.after, identity, "PR after", window);
  const current = after.value;
  const issues = [...before.issues, ...after.issues];
  if (!before.value || !current) return unknownPull(number, window.finish, issues, current);
  const initial = before.value;
  const stable = initial.number === number && current.number === number && initial.headOid === current.headOid && initial.baseOid === current.baseOid &&
    initial.headRef === current.headRef && initial.baseRef === current.baseRef && initial.headRepository === current.headRepository && initial.state === current.state && initial.draft === current.draft && initial.mergeCommitOid === current.mergeCommitOid;
  const bound = binding(repository, current, viewerId);
  if (!stable || !sameBinding(observation.before.binding, bound) || !sameBinding(observation.after.binding, bound) || observation.before.observedAt > observation.after.observedAt) {
    return unknownPull(number, window.finish, ["PR identity/head/base/state changed during observation or identity binding mismatched"], current);
  }
  const sourceWindow = { ...window, start: observation.before.observedAt, finish: observation.after.observedAt };
  const required = read(observation.policy, policy, "required policy", sourceWindow, bound);
  const implementation = dimension(current.state === "CLOSED" ? "failed" : current.draft ? "pending" : "passed", [current.state === "MERGED" ? "Implementation merged; verification and publication remain independent" : current.state === "CLOSED" ? "PR closed without merge" : current.draft ? "Implementation remains draft" : "Implementation submitted (not proof of verification)"], before.refs, after.refs);
  const verification = verificationDimension(observation, current, required, sourceWindow, bound);
  const review = reviewDimension(observation, current, required, sourceWindow, bound);
  let merge: Dimension;
  if (current.state === "MERGED") merge = dimension("passed", ["Already merged (not proof of verification or publication)"], before.refs, after.refs);
  else if (current.state === "CLOSED") merge = dimension("not-applicable", ["Closed without merge"], after.refs);
  else if (current.mergeable === "CONFLICTING") merge = dimension("failed", ["Merge conflicts observed"], after.refs);
  else if (current.mergeable === "UNKNOWN" || !required.value || required.value.unsupported.length > 0 || verification.state === "unknown" || review.state === "unknown") merge = dimension("unknown", ["Mergeability, policy or current readiness evidence unknown"], after.refs, required.refs, verification.sources, review.sources);
  else if (current.draft || verification.state !== "passed" || review.state !== "passed") merge = dimension("pending", ["Implementation, verification or review requirements remain outstanding"], after.refs, verification.sources, review.sources);
  else merge = dimension("passed", ["Observed merge prerequisites satisfied; no merge action performed"], after.refs, verification.sources, review.sources);
  const view: PullView = { number, title: current.title, url: current.url, headOid: current.headOid, baseOid: current.baseOid, observedAt: window.finish, implementation, verification, review, merge,
    publication: publicationDimension(observation, current, sourceWindow, bound), action: "none", nextAction: "", diagnostics: [] };
  view.diagnostics = [...new Set([verification, review, view.publication].filter((item) => item.state === "unknown").flatMap((item) => item.reasons))];
  chooseAction(view);
  return { view, identity: current };
}

function deriveGraph(pulls: Pull[], repository: string): { edges: RadarView["edges"]; diagnostics: string[] } {
  const edges: { parent: number; child: number }[] = [];
  const diagnostics: string[] = [];
  const ambiguous = new Set<number>();
  if (pulls.some((pull) => pull.identity === null)) {
    diagnostics.push("Selected stack graph incomplete because a selected PR identity is unknown");
    for (const pull of pulls) if (pull.identity?.state === "OPEN") ambiguous.add(pull.view.number);
  }
  for (const child of pulls) {
    if (!child.identity) continue;
    const duplicates = pulls.filter((candidate) => candidate.identity && candidate.view.number !== child.view.number &&
      candidate.identity.headRepository?.toLowerCase() === repository.toLowerCase() && child.identity?.headRepository?.toLowerCase() === repository.toLowerCase() &&
      candidate.identity.headRef === child.identity?.headRef);
    if (duplicates.length > 0) {
      ambiguous.add(child.view.number);
      diagnostics.push(`Ambiguous selected head branch for PR ${child.view.number}`);
    }
    const parents = pulls.filter((parent) => parent.identity && parent.view.number !== child.view.number && parent.identity.headRepository?.toLowerCase() === repository.toLowerCase() && parent.identity.headRef === child.identity?.baseRef);
    if (parents.length > 1) {
      ambiguous.add(child.view.number);
      diagnostics.push(`Ambiguous selected branch dependency for PR ${child.view.number}`);
    } else if (parents[0]) edges.push({ parent: parents[0].view.number, child: child.view.number });
    if (child.identity.headRepository?.toLowerCase() === repository.toLowerCase() && child.identity.headRef === child.identity.baseRef) {
      ambiguous.add(child.view.number);
      diagnostics.push(`Self-cycle in selected branch identity for PR ${child.view.number}`);
    }
  }
  const cyclic = new Set<number>();
  function visit(number: number, path: number[]): void {
    const index = path.indexOf(number);
    if (index >= 0) { for (const member of path.slice(index)) cyclic.add(member); return; }
    for (const edge of edges) if (edge.parent === number) visit(edge.child, [...path, number]);
  }
  for (const pull of pulls) visit(pull.view.number, []);
  if (cyclic.size > 0) diagnostics.push(`Cycle in selected branch dependencies: ${[...cyclic].sort((a, b) => a - b).join(", ")}`);
  // Ambiguous ancestors also invalidate descendant readiness.
  const blocked = new Set([...ambiguous, ...cyclic]);
  for (let step = 0; step < pulls.length; step++) for (const edge of edges) if (blocked.has(edge.parent)) blocked.add(edge.child);
  for (const pull of pulls) {
    if (blocked.has(pull.view.number)) {
      pull.view.merge = dimension("unknown", ["Selected stack graph ambiguous or cyclic"], pull.view.merge.sources);
      pull.view.diagnostics = [...pull.view.diagnostics, "Selected stack graph ambiguous or cyclic"];
    } else if (pull.identity?.state === "OPEN") {
      const parent = edges.find((edge) => edge.child === pull.view.number);
      if (parent && pulls.find((candidate) => candidate.view.number === parent.parent)?.identity?.state !== "MERGED" && pull.view.merge.state === "passed") {
        pull.view.merge = dimension("pending", [`Selected parent PR ${parent.parent} is not yet observed merged`], pull.view.merge.sources);
      }
    }
    chooseAction(pull.view);
  }
  return { edges: edges.sort((a, b) => a.parent - b.parent || a.child - b.child), diagnostics };
}

export function deriveRadar(observation: Observation, now: number, maxAgeMs = DEFAULT_MAX_AGE_MS): RadarView {
  if (timestamp(now) === null || !Number.isSafeInteger(maxAgeMs) || maxAgeMs < 0) throw new TypeError("now and maxAgeMs must be valid nonnegative epoch milliseconds");
  if (!record(observation) || observation.schema !== SCHEMA) throw new TypeError("unsupported observation schema");
  const selection = validateSelection(observation.selection);
  const start = timestamp(observation.startedAt);
  const finish = timestamp(observation.finishedAt);
  const window: Window = { start: start ?? now, finish: finish ?? now, now, maxAge: maxAgeMs,
    valid: start !== null && finish !== null && start <= finish && finish <= now && now - start <= maxAgeMs };
  const before = read(observation.viewerBefore, text, "viewer before", window);
  const after = read(observation.viewerAfter, text, "viewer after", window);
  const viewerId = before.value && before.value === after.value && observation.viewerBefore.observedAt <= observation.viewerAfter.observedAt ? before.value : null;
  const diagnostics = [...before.issues, ...after.issues];
  if (!viewerId) diagnostics.push("Viewer identity unavailable or changed during observation");
  if (!window.valid) diagnostics.push("Observation time window invalid or stale");
  const rawPulls: readonly PullObservation[] = Array.isArray(observation.pulls) && observation.pulls.length <= 20 ? observation.pulls : [];
  const selected = new Set(selection.pullRequests);
  const completeSelection = rawPulls.length === selection.pullRequests.length;
  if (!completeSelection) diagnostics.push("Selected PR observation count mismatch");
  if (rawPulls.some((pull) => !record(pull) || !record(pull.before) || !identity(pull.before.value) || !selected.has(pull.before.value.number))) diagnostics.push("Malformed or unselected PR observation present");
  const pulls = selection.pullRequests.map((number) => {
    if (!completeSelection) return unknownPull(number, window.finish, ["Selected PR observation count mismatch"]);
    const matching = rawPulls.filter((pull) => record(pull) && ((record(pull.before) && identity(pull.before.value) && pull.before.value.number === number) || (record(pull.after) && identity(pull.after.value) && pull.after.value.number === number)));
    if (!viewerId || matching.length !== 1) return unknownPull(number, window.finish, !viewerId ? diagnostics : ["Selected PR observation missing or duplicated"]);
    const candidate = matching[0];
    if (!candidate) return unknownPull(number, window.finish, ["Selected PR observation missing"]);
    const viewerWindow = { ...window, start: observation.viewerBefore.observedAt, finish: observation.viewerAfter.observedAt };
    return derivePull(number, candidate, selection.repository, viewerId, viewerWindow);
  });
  const graph = deriveGraph(pulls, selection.repository);
  return { schema: "armory.delivery-radar.view/v1", repository: selection.repository, viewerId, observedAt: window.finish, pulls: pulls.map((pull) => pull.view), edges: graph.edges, diagnostics: [...diagnostics, ...graph.diagnostics] };
}
