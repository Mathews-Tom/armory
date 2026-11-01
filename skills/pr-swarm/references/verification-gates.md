# Verification Gates

Contents: [Termination conditions](#termination-conditions) · [First-failure reaction](#react-to-the-first-failing-check-not-the-full-matrix) · [Merge-state staleness](#merge-state-staleness) · [Review-thread pagination](#review-thread-pagination) · [Body-only reviews](#body-only-reviews-the-critical-gap) · [Stale statusCheckRollup entries](#stale-statuscheckrollup-entries) · [The closed-PR trap](#the-closed-pr-trap) · [Final state read](#final-state-read) · [Review triage and round cap](#review-triage-and-round-cap)

These are GitHub API/`gh` CLI behaviors, not agent-specific — they apply regardless of which lane process produced the work.

## Termination conditions

A PR/lane is genuinely done only when **all** of the following hold simultaneously:

1. `state == OPEN`
2. Current mergeability is confirmed and provider-required review/protection conditions applicable at this readiness stage are satisfied; `CLEAN` alone is not proof and a queue-ready PR need not have that display state.
3. Provider-required, repository-mandated and unclassified applicable checks passed in the required current head/base context. Explicitly classified advisory jobs are reported separately and may be pending or failed; use `ship-workflow`'s sourced policy contract rather than guessing from names or runtime.
4. Every substantive in-scope finding has a verified fix or authorized disposition, including body-only review findings. Optional feedback has a reasoned disposition without a fix commit; preserve provider-required thread-resolution and reviewer rules.
5. A final current-state read confirms no new blocking evidence. No fixed quiet window or bot-silence requirement applies.
6. Worktree clean; local HEAD matches the pushed remote head.
7. Acceptance was exercised and repository-required local preflight passed. An open, unqueued PR can be **ready-for-enrollment** without candidate validation: queue-only checks have not run yet, not passed or been waived. Required `merge_group`/integration-candidate checks must pass on the actual candidate before landing; pending required candidate checks block validation of an already-queued PR. Do not enqueue or merge without separate authority: enrollment can itself trigger automatic landing.

## React to the first failing check, not the full matrix

`gh pr checks <N>` reports per-job status, not just a run-level aggregate. Start diagnosing an individually failed blocking job immediately while pending jobs continue. Classify review feedback and explicitly advisory failures before acting; they do not automatically justify another fix push. A provider-required check stays blocking regardless of an advisory declaration.

This also means a lane rarely needs to force a fresh CI run at all: pushing the fix for an already-failed job triggers a brand-new run on its own. `gh run rerun` requires repo admin rights a contributor-driven lane typically doesn't have (`Must have admin rights to Repository`) — that's a non-issue here, not a blocker, because the normal fix-and-push cycle never depends on it. Reserve the close/reopen technique (`force-fresh-ci-without-admin-rerun` skill) for the narrow case of re-testing a suspected-flaky failure with no code change to push — not as a routine response to red CI.

## Merge-state staleness

`gh pr view N --json mergeable,mergeStateStatus` can report `CONFLICTING`/`DIRTY` long after the branch would actually merge cleanly — GitHub's async mergeability recompute can simply not have re-run. Before believing "needs conflict resolution," check ground truth directly:

```bash
git merge-tree --write-tree upstream/main origin/<head>   # git >= 2.38
```

Exit `0` means a clean merge is possible right now, regardless of what the API says. If clean, `git merge upstream/main -m "..."` and push — don't replay commits one-by-one with `rebase` (a multi-commit branch can contain fixup commits tailored to an older base state that conflict individually even though the net merge doesn't). The push alone is usually what makes GitHub recompute and flip to `CLEAN`. On a repo with high upstream commit velocity, a verified-`CLEAN` state can regress within hours purely from cadence — re-check immediately before any final report, don't trust a read from earlier in the same run.

## Review-thread pagination

```bash
gh api graphql -f query='
  query($owner:String!, $repo:String!, $n:Int!, $after:String) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$n) {
        reviewThreads(first:100, after:$after) {
          pageInfo { hasNextPage endCursor }
          nodes { isResolved }
        }
      }
    }
  }' -F owner=<o> -F repo=<r> -F n=<N>
```

`gh api graphql --paginate` does not reliably terminate against a cursor-based query with variables — drive the `pageInfo.hasNextPage`/`endCursor` loop by hand. The response is wrapped in a top-level `data` key (`{"data": {"repository": {...}}}`); unwrap it explicitly before dereferencing `.repository.pullRequest...` — skipping `.data` doesn't throw immediately, it just makes `.repository` silently `undefined` until something dereferences it further down, which reads like an unrelated bug.

## Body-only reviews — the critical gap

`reviewThreads` only aggregates properly-anchored inline comments. A bot reviewer can instead submit a full review (`state: COMMENTED`) whose `body` text embeds a finding directly — including a manually-constructed blob-permalink pointing at flagged lines — with no inline comment object backing it at all. This has **no node in `reviewThreads`** and **no entry in the REST inline-comments endpoint**. A check that only queries `reviewThreads` will report 0 unresolved and pass a PR as clean while a real, unaddressed finding sits on the Conversation tab.

Before declaring any PR clean, also fetch and scan every review's raw body:

```bash
gh api graphql -f query='
  query($owner:String!, $repo:String!, $n:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$n) {
        reviews(first:100) { nodes { id state author { login } body submittedAt url } }
      }
    }
  }' -F owner=<o> -F repo=<r> -F n=<N>
```

Read every `COMMENTED`/`CHANGES_REQUESTED` review's `body` for severity badges, blocking/should-fix markers, or blob-permalink references. Cross-reference flagged lines against the branch's commit history to check whether a later commit already fixed it. A body-only review has no `resolveReviewThread` mutation to apply — the correct closure signal is a `gh pr comment` reply citing the review's timestamp/URL, not a thread-resolve call. For an Important fix the reply cites the fixing commit SHA; for a declined Nit, Pre-existing or Repeat finding it gives the one-line reason instead.

## Stale `statusCheckRollup` entries

Historical check-run rows can include superseded attempts. A display name or latest timestamp alone cannot establish which workflow, event, publisher and current attempt a result belongs to. Use `ship-workflow`'s current evidence classification and provider protections; `gh pr checks N` and mergeability are cross-checks, not substitutes for missing evidence. Revalidate affected integration behavior after a head or base change; reuse passing results only when their covered inputs and context are unchanged.

## The closed-PR trap

`mergeStateStatus`/`mergeable`/CI conclusions/thread counts all keep returning normal-looking (even clean) data after a maintainer closes a PR — nothing about those fields signals closure. Always include `state` in every `gh pr view` call in this skill, at resolution and at final verification, and treat anything other than `OPEN` as an immediate stop, not something to work around by continuing to push commits to a dead PR.

A closed PR is not automatically safe to reopen or replace with a fresh PR — some repos gate PR creation behind a contributor-approval mechanism, and reopening/opening fresh re-triggers that gate's evaluation even if the original PR predated the policy. If a PR closes mid-run: stop pushing, read the closing comment, check for a `CONTRIBUTING.md` contributor-gating policy and any existing issue/discussion already addressing it, and report the finding rather than reopening or opening a new PR without explicit instruction.

## Final state read

After current acceptance, blocking checks and review requirements pass, re-read PR state, head/base and applicable feedback, then report readiness. If those inputs changed, re-evaluate only affected evidence. Do not add a quiet timer or second insurance wait for an advisory reviewer; unreadable or pending required evidence still blocks. A later substantive finding remains actionable when received, not a reason to hold every completed lane open speculatively.

## Review triage and round cap

An agent author and an agent reviewer can keep each other busy indefinitely: a person waves off a nit in seconds, an agent fixes it, which means another commit and another review round. Two rules keep a lane converging:

- **Triage before fixing.** Each finding is Important (fix it), Nit or Pre-existing (reply with a one-line reason and resolve the thread, no commit), or a Repeat of an answered finding (point to the earlier reply and resolve, no commit). Fixes name the bug class and cover every instance in the PR's diff in one push. A resolved thread with a decline reason counts as addressed for condition 4.
- **Cap rounds at three.** A round is one feedback-answering push plus the re-review it triggers; merge-only and CI-flake pushes don't count. After round 1, re-verify changed code and affected interactions, including unchanged callers; broaden only when a contract or base change invalidates evidence. If new Important findings still arrive after round 3, the lane stops pushing and reports the recurring findings and their bug class; the orchestrator reports that PR unresolved and the user decides whether to rethink the approach or allow another round.
