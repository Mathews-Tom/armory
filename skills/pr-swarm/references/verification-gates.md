# Verification Gates

Contents: [Termination conditions](#termination-conditions) · [Merge-state staleness](#merge-state-staleness) · [Review-thread pagination](#review-thread-pagination) · [Body-only reviews](#body-only-reviews-the-critical-gap) · [Stale statusCheckRollup entries](#stale-statuscheckrollup-entries) · [The closed-PR trap](#the-closed-pr-trap) · [Quiet window](#quiet-window)

These are GitHub API/`gh` CLI behaviors, not agent-specific — they apply regardless of which lane process produced the work.

## Termination conditions

A PR/lane is genuinely done only when **all** of the following hold simultaneously:

1. `state == OPEN`
2. `mergeStateStatus == CLEAN` and `mergeable == MERGEABLE`
3. Latest CI: every non-skipped check passed, none pending
4. Unresolved review threads = 0, **and** no unaddressed finding embedded in a body-only review (see below)
5. No new feedback landed in the last ~10-minute quiet window
6. Worktree clean; local HEAD matches the pushed remote head
7. The repo's own test/lint/typecheck gate ran green on the merged tree, not just on the pre-merge branch

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

Read every `COMMENTED`/`CHANGES_REQUESTED` review's `body` for severity badges, blocking/should-fix markers, or blob-permalink references. Cross-reference flagged lines against the branch's commit history to check whether a later commit already fixed it. A body-only review has no `resolveReviewThread` mutation to apply — the correct closure signal is a `gh pr comment` reply citing the review's timestamp/URL and the fixing commit SHA, not a thread-resolve call.

## Stale `statusCheckRollup` entries

The raw `statusCheckRollup` array accumulates every historical check-run row for a PR's head SHA, including ones superseded by a later rerun of the identically-named job. A naive tally of `conclusion` values can show `FAILURE > 0` on a genuinely green, mergeable PR. `mergeStateStatus`/`mergeable` are already the correct aggregate (computed from only the latest run per required check) — trust those over a manual count of the raw array. To confirm one specific job's true state, group entries by `name` and take the one with the latest `completedAt`; `gh pr checks N` (which already dedupes per job) is a fast independent cross-check.

## The closed-PR trap

`mergeStateStatus`/`mergeable`/CI conclusions/thread counts all keep returning normal-looking (even clean) data after a maintainer closes a PR — nothing about those fields signals closure. Always include `state` in every `gh pr view` call in this skill, at resolution and at final verification, and treat anything other than `OPEN` as an immediate stop, not something to work around by continuing to push commits to a dead PR.

A closed PR is not automatically safe to reopen or replace with a fresh PR — some repos gate PR creation behind a contributor-approval mechanism, and reopening/opening fresh re-triggers that gate's evaluation even if the original PR predated the policy. If a PR closes mid-run: stop pushing, read the closing comment, check for a `CONTRIBUTING.md` contributor-gating policy and any existing issue/discussion already addressing it, and report the finding rather than reopening or opening a new PR without explicit instruction.

## Quiet window

After each push, CI restarts and `mergeStateStatus` typically goes `UNSTABLE` while pending. Wait roughly 10 minutes, re-check every condition. If new feedback landed during the wait, fix it, push, and reset the quiet-window timer — including feedback that lands in the few minutes right after a lane's own final self-check but before the orchestrator's external re-check catches it (a real race, not a bug in either check). One extra quiet window as insurance against reviewer lag before declaring a lane done is worth the wall-clock cost.
