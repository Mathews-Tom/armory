import { describe, expect, test } from "bun:test";
import { deriveRadar, renderRadar, SCHEMA, transitionKey, validateSelection } from "../core/index.ts";
import type { Binding, Check, Observation, PullIdentity, PullObservation, PullView, RequiredPolicy, Review, ReviewThread, Source } from "../core/index.ts";

const T = 1_000_000;
const HEAD = "a".repeat(40);
const BASE = "b".repeat(40);
const OTHER = "c".repeat(40);
const REPOSITORY = "owner/project";

function source<V>(value: V, name: string, binding: Binding | null, at = T + 20): Source<V> {
  return { status: "available", binding, observedAt: at, reference: `https://api.github.com/repos/owner/project/${name}`, diagnostic: null, value };
}

function pull(number = 1, changes: Partial<PullIdentity> = {}): PullObservation {
  const identity: PullIdentity = { number, url: `https://github.com/owner/project/pull/${number}`, title: `Feature ${number}`, state: "OPEN", headOid: HEAD, baseOid: BASE,
    headRef: `feature-${number}`, baseRef: "main", headRepository: REPOSITORY, draft: false, mergeable: "MERGEABLE", mergeCommitOid: null, ...changes };
  const binding: Binding = { repository: REPOSITORY, pullRequest: number, headOid: identity.headOid, baseOid: identity.baseOid, viewerId: "viewer-1" };
  return {
    before: source({ ...identity }, `pulls/${number}/before`, binding, T + 10), after: source({ ...identity }, `pulls/${number}/after`, binding, T + 30),
    reviews: source<readonly Review[]>([{ id: "review-1", reviewerId: "reviewer-1", state: "APPROVED", commitOid: HEAD, submittedAt: T - 10 }], `pulls/${number}/reviews`, binding),
    threads: source<readonly ReviewThread[]>([], `pulls/${number}/threads`, binding),
    checks: source<readonly Check[]>([{ id: "check-1", context: "test", publisherId: 1, state: "passed", headOid: HEAD, testedBaseOid: BASE, url: "https://github.com/check/1", completedAt: T }], `pulls/${number}/checks`, binding),
    policy: source<RequiredPolicy>({ checks: [{ context: "test", publisherId: 1 }], requiredApprovals: 1, requireCodeOwnerReview: false, requireLatestApproval: false, dismissStaleReviews: true, strict: true, unsupported: [] }, `pulls/${number}/policy`, binding),
    publication: { ...source(null, `pulls/${number}/publication`, binding), status: "not-selected" },
  };
}

function observation(pulls = [pull()]): Observation {
  return { schema: SCHEMA, selection: { repository: REPOSITORY, pullRequests: pulls.map((item) => item.before.value?.number ?? 0) },
    viewerBefore: source("viewer-1", "viewer/before", null, T), viewerAfter: source("viewer-1", "viewer/after", null, T + 40), startedAt: T, finishedAt: T + 50, pulls };
}

function first(value: Observation): PullView {
  const result = deriveRadar(value, T + 100).pulls[0];
  if (!result) throw new Error("missing selected view");
  return result;
}

function check(value: PullObservation) {
  const result = value.checks.value?.[0];
  if (!result) throw new Error("missing fixture check");
  return result;
}

function review(state: Review["state"], submittedAt: number, id: string = state): Review {
  return { id, state, submittedAt, reviewerId: "reviewer-1", commitOid: HEAD };
}

describe("explicit bounded selections", () => {
  test("rejects shell/path syntax, coercions, duplicates, empty and oversized sets", () => {
    expect(validateSelection({ repository: REPOSITORY, pullRequests: [7, 2] })).toEqual({ repository: REPOSITORY, pullRequests: [7, 2] });
    for (const repository of ["owner/project;id", "owner/../project", "owner/..", "https://github.com/owner/project", "owner/project\n", "-owner/project"]) expect(() => validateSelection({ repository, pullRequests: [1] })).toThrow();
    for (const pullRequests of [[], [1, 1], ["1"], [0], [-1], [1.5], [Number.MAX_SAFE_INTEGER + 1], Array.from({ length: 21 }, (_, index) => index + 1)]) expect(() => validateSelection({ repository: REPOSITORY, pullRequests })).toThrow();
    expect(() => validateSelection({ repository: REPOSITORY, pullRequests: [1], all: true })).toThrow();
  });
});

describe("independent evidence dimensions", () => {
  test("submitted/ready is neither merged nor published; no remote action is implied", () => {
    const view = first(observation());
    expect([view.implementation.state, view.verification.state, view.review.state, view.merge.state, view.publication.state]).toEqual(["passed", "passed", "passed", "passed", "unknown"]);
    expect(view.action).toBe("owner-decision");
    expect(view.merge.reasons.join(" ")).toContain("no merge action performed");
  });

  test("merged fact survives missing CI but never supplies verification or publication", () => {
    const value = pull(1, { state: "MERGED", mergeCommitOid: OTHER });
    value.checks.status = "unavailable";
    const view = first(observation([value]));
    expect(view.merge.state).toBe("passed");
    expect(view.verification.state).toBe("unknown");
    expect(view.publication.state).toBe("unknown");
    expect(view.action).toBe("owner-decision");
  });

  test("draft and closed implementation remain different from verification", () => {
    expect(first(observation([pull(1, { draft: true })])).implementation.state).toBe("pending");
    const closed = first(observation([pull(1, { state: "CLOSED" })]));
    expect(closed.implementation.state).toBe("failed");
    expect(closed.merge.state).toBe("not-applicable");
    expect(closed.verification.state).toBe("passed");
  });

  test("unavailable/partial/malformed/rate-limited sources cannot turn empty values green", () => {
    for (const status of ["partial", "unavailable", "rate-limited", "malformed", "not-selected"] as const) {
      const value = pull();
      value.checks.status = status;
      expect(first(observation([value])).verification.state).toBe("unknown");
      value.reviews.status = status;
      expect(first(observation([value])).review.state).toBe("unknown");
    }
    const value = pull();
    value.policy.status = "unavailable";
    expect(first(observation([value])).merge.state).toBe("unknown");
    value.policy.status = "available";
    if (value.policy.value) value.policy.value.unsupported = ["required deployments"];
    expect(first(observation([value])).merge.state).toBe("unknown");
  });

  test("null mergeability and no required CI policy never establish merge readiness", () => {
    expect(first(observation([pull(1, { mergeable: "UNKNOWN" })])).merge.state).toBe("unknown");
    const value = pull();
    if (value.policy.value) value.policy.value.checks = [];
    expect(first(observation([value])).verification.state).toBe("unknown");
    expect(first(observation([value])).merge.state).toBe("unknown");
  });
});

describe("binding and observation freshness", () => {
  test("head, base and viewer drift invalidate readiness even when every CI result passed", () => {
    for (const field of ["headOid", "baseOid"] as const) {
      const value = pull();
      if (value.after.value) value.after.value[field] = OTHER;
      expect(first(observation([value])).merge.state).toBe("unknown");
      expect(first(observation([value])).verification.state).toBe("unknown");
    }
    const value = observation();
    value.viewerAfter.value = "different-viewer";
    expect(first(value).implementation.state).toBe("unknown");
  });

  test("each source needs its own current full binding and valid observation time", () => {
    for (const field of ["repository", "headOid", "baseOid", "viewerId"] as const) {
      const value = pull();
      if (value.checks.binding) value.checks.binding = { ...value.checks.binding, [field]: "foreign" };
      expect(first(observation([value])).verification.state).toBe("unknown");
    }
    for (const at of [T - 1, T + 5, T + 35, T + 51, Number.NaN]) {
      const value = pull();
      value.checks.observedAt = at;
      expect(first(observation([value])).verification.state).toBe("unknown");
    }
    expect(deriveRadar(observation(), T + 400_000).pulls[0]?.implementation.state).toBe("unknown");
    expect(deriveRadar(observation(), T + 100, 50).pulls[0]?.implementation.state).toBe("unknown");
    const value = observation();
    value.finishedAt = T - 1;
    expect(first(value).merge.state).toBe("unknown");
  });

  test("malformed available payloads and missing provenance are not successful empty reads", () => {
    const value = pull();
    Object.assign(check(value), { state: "unexpected" });
    expect(first(observation([value])).verification.state).toBe("unknown");
    const noReference = pull();
    noReference.checks.reference = "";
    expect(first(observation([noReference])).verification.state).toBe("unknown");
    const foreignNumber = pull();
    if (foreignNumber.checks.binding) foreignNumber.checks.binding.pullRequest = 2;
    expect(first(observation([foreignNumber])).verification.state).toBe("unknown");
    const viewerOrder = observation();
    viewerOrder.viewerBefore.observedAt = T + 15;
    expect(first(viewerOrder).merge.state).toBe("unknown");
  });

  test("missing and duplicate selected observations stay visible and unknown", () => {
    const value = observation();
    value.pulls = [];
    expect(first(value).number).toBe(1);
    expect(first(value).merge.state).toBe("unknown");
    value.pulls = [pull(), pull()];
    expect(first(value).merge.state).toBe("unknown");
    expect(() => deriveRadar({ ...value, schema: "other" } as unknown as Observation, T + 100)).toThrow();
  });

  test("extra unselected evidence invalidates the selected snapshot instead of leaving a green subset", () => {
    const value = observation();
    value.pulls = [pull(), pull(2)];
    const view = first(value);
    expect(view.verification.state).toBe("unknown");
    expect(view.merge.state).toBe("unknown");
    expect(view.action).toBe("owner-decision");
  });
});

describe("required checks distinguish missing, pending, failure and tested base", () => {
  test("old head, head-only green, old base and wrong publisher do not satisfy current CI", () => {
    for (const changes of [{ headOid: OTHER }, { testedBaseOid: null }, { testedBaseOid: OTHER }, { publisherId: 2 }]) {
      const value = pull();
      Object.assign(check(value), changes);
      expect(first(observation([value])).verification.state).toBe("unknown");
      expect(first(observation([value])).merge.state).toBe("unknown");
    }
  });

  test("required checks report missing/pending/failed/unknown distinctly and reject ambiguous runs", () => {
    const value = pull();
    value.checks.value = [];
    expect(first(observation([value])).verification.reasons.join(" ")).toContain("Missing required check");
    for (const state of ["pending", "failed", "cancelled", "unknown"] as const) {
      const candidate = pull();
      check(candidate).state = state;
      expect(first(observation([candidate])).verification.state).toBe(state === "cancelled" ? "failed" : state);
    }
    const duplicate = pull();
    duplicate.checks.value = [check(duplicate), { ...check(duplicate), id: "second-run" }];
    expect(first(observation([duplicate])).verification.state).toBe("unknown");
    const future = pull();
    check(future).completedAt = T + 25;
    expect(first(observation([future])).verification.state).toBe("unknown");
  });
});

describe("review decisions and discussion", () => {
  test("latest submitted decision, not input order or total approval count, controls review", () => {
    const value = pull();
    value.reviews.value = [review("DISMISSED", T - 5), review("APPROVED", T - 10)];
    expect(first(observation([value])).review.state).toBe("pending");
    value.reviews.value = [review("APPROVED", T - 5), review("CHANGES_REQUESTED", T - 10)];
    expect(first(observation([value])).review.state).toBe("passed");
    value.reviews.value = [review("CHANGES_REQUESTED", T - 5), review("APPROVED", T - 10)];
    expect(first(observation([value])).review.state).toBe("failed");
    value.reviews.value = [review("PENDING", T), review("APPROVED", T - 10)];
    expect(first(observation([value])).review.state).toBe("passed");
    value.reviews.value = [review("COMMENTED", T), review("CHANGES_REQUESTED", T - 10)];
    expect(first(observation([value])).review.state).toBe("failed");
    value.reviews.value = [review("APPROVED", T), review("APPROVED", T - 10, "old-approval"), review("DISMISSED", T - 10)];
    expect(first(observation([value])).review.state).toBe("passed");
  });

  test("old approvals, outdated unresolved threads and unprovable policy block review green", () => {
    const value = pull();
    value.reviews.value = [{ ...review("APPROVED", T - 10), commitOid: OTHER }];
    expect(first(observation([value])).review.state).toBe("pending");
    value.threads.value = [{ id: "thread-1", resolved: false, outdated: true }];
    expect(first(observation([value])).review.state).toBe("failed");
    expect(first(observation([value])).action).toBe("agent-work");
    for (const key of ["requireCodeOwnerReview", "requireLatestApproval"] as const) {
      const candidate = pull();
      if (candidate.policy.value) candidate.policy.value[key] = true;
      expect(first(observation([candidate])).review.state).toBe("unknown");
    }
  });

  test("identical timestamps from conflicting decisions and malformed decisions are not green", () => {
    const value = pull();
    value.reviews.value = [review("APPROVED", T), review("DISMISSED", T)];
    expect(first(observation([value])).review.state).toBe("unknown");
    value.reviews.value = [review("APPROVED", T + 21)];
    expect(first(observation([value])).review.state).toBe("unknown");
  });
});

describe("explicit selected branch graph", () => {
  test("only selected same-repository parent branches create dependencies, and unmerged parent holds child", () => {
    const parent = pull(1);
    const child = pull(2, { baseRef: "feature-1" });
    const value = deriveRadar(observation([parent, child]), T + 100);
    expect(value.edges).toEqual([{ parent: 1, child: 2 }]);
    expect(value.pulls[1]?.merge.state).toBe("pending");
    expect(deriveRadar(observation([child]), T + 100).edges).toEqual([]);
    const fork = pull(1, { headRepository: "someone/fork" });
    expect(deriveRadar(observation([fork, child]), T + 100).edges).toEqual([]);
  });

  test("ambiguous branches and cyclic selected dependencies are visible unknown, never invented order", () => {
    const value = deriveRadar(observation([pull(1), pull(2, { headRef: "feature-1" }), pull(3, { baseRef: "feature-1" })]), T + 100);
    expect(value.edges).toEqual([]);
    expect(value.pulls[2]?.merge.state).toBe("unknown");
    expect(value.diagnostics.join(" ")).toContain("Ambiguous");
    const cycle = deriveRadar(observation([pull(1, { baseRef: "feature-2" }), pull(2, { baseRef: "feature-1" })]), T + 100);
    expect(cycle.pulls.map((item) => item.merge.state)).toEqual(["unknown", "unknown"]);
    expect(cycle.diagnostics.join(" ")).toContain("Cycle");
  });
});

describe("publication is separately evidenced", () => {
  test("workflow-only or mismatched commit cannot prove artifacts; independent artifact evidence can", () => {
    const value = pull(1, { state: "MERGED", mergeCommitOid: OTHER });
    value.publication = { ...value.publication, status: "available", value: { state: "published", commitOid: OTHER, artifactIds: [], url: "https://registry.example/artifact" } };
    expect(first(observation([value])).publication.state).toBe("unknown");
    if (value.publication.value) value.publication.value.artifactIds = ["package@1.0.0"];
    expect(first(observation([value])).publication.state).toBe("passed");
    value.publication.reference = value.checks.reference;
    expect(first(observation([value])).publication.state).toBe("unknown");
    value.publication.reference = "https://registry.example/artifact";
    if (value.publication.value) value.publication.value.commitOid = HEAD;
    expect(first(observation([value])).publication.state).toBe("unknown");
  });
});

describe("consumer text and transition identity", () => {
  test("provider titles and source text cannot forge headings, terminal controls, links or Markdown", () => {
    const value = pull(1, { title: "Safe\n# Forged\u001b[31m `instruction` [run](https://evil.example)\u202e" });
    const rendered = renderRadar(deriveRadar(observation([value]), T + 100));
    expect(rendered).not.toContain("\u001b");
    expect(rendered).not.toContain("\u202e");
    expect(rendered).not.toContain("\n# Forged");
    expect(rendered).not.toContain("`instruction`");
    expect(rendered).not.toContain("[run](https://evil.example)");
    expect(rendered).toContain("Rendering disclosure: removed");
    expect(rendered).toContain("Safe");
  });

  test("sampling time alone is deduplicated; changed identities, policy outcomes and artifacts are not", () => {
    const view = deriveRadar(observation(), T + 100);
    const fresh = structuredClone(view);
    fresh.observedAt += 100;
    for (const item of fresh.pulls) item.observedAt += 100;
    expect(transitionKey(fresh)).toBe(transitionKey(view));
    for (const change of [(item: PullView) => { item.baseOid = OTHER; }, (item: PullView) => { item.review.state = "pending"; }, (item: PullView) => { item.action = "external-wait"; }, (item: PullView) => { item.publication.reasons = ["new artifact"]; }, (item: PullView) => { item.verification.sources = ["check:new-attempt"]; }]) {
      const changed = structuredClone(view);
      const item = changed.pulls[0];
      if (!item) throw new Error("missing view");
      change(item);
      expect(transitionKey(changed)).not.toBe(transitionKey(view));
    }
  });
});
