# GitHub-native stacked pull requests

GitHub-native stacked pull requests are public preview. Native-stack
membership is a provider-side property of a pull request; detect it for every
open stack PR during Inspect (`references/stack-model.md` § Native Stack
Detection) before any merge planning.

## Two distinct operations, two different opt-in rules

- **Creating native state** — `gh stack link` converts a manual stack (or
  links loose PRs) into a native stack on GitHub. This is a mutation with
  public-preview risk; it requires the eligibility probe below plus explicit
  user consent.
- **Operating on a stack Inspect already found to be native** — merging,
  syncing, or otherwise mutating a PR the provider already registers as a
  stack member. This is not a choice: the provider's synchronous merge
  mutation (`gh pr merge`, the legacy `PUT .../pulls/{n}/merge`, and the
  `mergePullRequest` GraphQL mutation) refuses any pull request that is part
  of a stack with an explicit "must be merged using the asynchronous merge
  REST API" error. There is no manual Armory merge path for an already-native
  stack; do not present one as an alternative.

## Eligibility (creating native state)

Require all of the following before running `gh stack link`:

1. GitHub CLI is version 2.0 or later and `gh stack --help` succeeds. Install
   the extension when absent: `gh extension install github/gh-stack`.
2. Every branch and pull request is in the same GitHub repository. Reject forks
   and cross-repository stacks.
3. Repository native-stack support is enabled. Treat native command exit code 9
   as unavailable and fall back to manual mode.
4. Armory branch order, PR base order, and `Stack-Id`/`Stack-Position` trailers
   agree with the proposed native order.
5. The user explicitly selects `github-native` mode or accepts the preview risk.

Do not use native linking for cross-fork stacks, unavailable preview tooling,
disabled repository support, or topology mismatch. Report the reason and use
manual Armory mode instead.

Condition 5 gates linking only. Once Inspect finds a PR already native (see
below), skip condition 5 and proceed with native merge; conditions 1-4 remain
in force as safety checks.

## Detecting an already-native stack

`gh stack view` is current-branch-only and takes no PR argument; it fails with
`current branch "<branch>" is not part of a stack` from any other branch,
including the stack's own base branch. Probe per PR instead, non-mutating:

```bash
gh api repos/{owner}/{repo}/pulls/<number> --jq '.stack'
```

Returns `null` when the PR is not part of a native stack, or an object with
`number`, `size`, `position`, and `base.ref` when it is. Run this for every
open stack PR during Inspect, before merge planning.

If the probe is unavailable for any reason, treat the merge-time
`mergePullRequest`/`merge-async` "part of a stack" rejection as authoritative
detection and switch to the native merge path below rather than reporting
failure.

## Link and inspect

Arguments are bottom-to-top:

```bash
gh stack link --base main feat/core feat/api feat/ui
gh stack view
```

`gh stack link` can push named branches, create missing pull requests, and
correct existing PR bases to the expected chain. Run dirty-worktree,
provenance, and topology checks before it mutates anything.

Link updates are additive only: it never removes an existing member. `--base`
is ignored when appending to an existing stack. A wrong native order requires
`gh stack unstack` followed by a verified relink; do not use link as a repair.

Record both GitHub stack position and Armory provenance in the stack report. A
native stack object never replaces `.stack-prs.yaml` or commit trailers.

## Sync and rebase

```bash
gh stack sync
gh stack sync --prune
```

`sync` fetches, cascade-rebases, force-with-lease pushes, and links open PRs.
Use `--prune` only after confirming the pruned branches' pull requests merged.

Do not trust a successful non-interactive exit alone: stack divergence can abort
without a failing exit status. Re-run `gh stack view` and compare composition
against Armory branch/PR/trailer metadata before continuing. For wrong native
order, unstack and relink. For a non-linear history or a lower-branch amend,
run `gh stack rebase`, resolve conflicts interactively, then `gh stack push`.

## Merge

Merge an already-native stack with one asynchronous request on the highest
selected pull request. GitHub merges the prefix of open members ending at
that pull request; there is no per-member request and no synchronous
fallback. Require a fully linear history between stack branches before
merging.

```bash
# Stack base without a merge queue: direct merge with an explicit method
gh api --method PUT repos/{owner}/{repo}/pulls/<highest>/merge-async \
  -f sha=<inspected head of <highest>> -f merge_action=direct_merge \
  -f merge_method=merge -F bypass_rules=false

# Stack base governed by a merge queue: no merge_method, commit_title or commit_message
gh api --method PUT repos/{owner}/{repo}/pulls/<highest>/merge-async \
  -f sha=<inspected head of <highest>> -f merge_action=merge_queue \
  -F bypass_rules=false
```

Never infer a prefix. Require the exact highest pull request number and send
its inspected head as `sha` on every request. Always send `bypass_rules=false`.

- **Only the selected head is guarded.** `sha` binds the highest selected
  pull request's head; the lower members' heads are not checked by the
  server. Immediately before dispatch, re-read every member (head, base,
  checks, provenance) and refuse when an open lower member is outside the
  authorized selection.
- **Route on the stack base.** The stack base branch (the bottom pull
  request's base) carries the rules that govern the whole stack; a middle
  member's own base is just another stack branch. Choose `merge_queue` when
  that trunk has a merge queue and `direct_merge` when its policy is fully
  known without one. When the trunk policy cannot be read, stop as blocked;
  never fall back to `direct_merge`.
- **`default` is supported but not a routing shortcut.** `merge_action=default`
  (also what the server uses when the parameter is omitted) uses a merge
  queue when one is configured for the target branch and merges directly
  otherwise. A personal-repository request with `merge_action=default` and
  `merge_method=squash` was accepted and echoed both. Because `default` does
  not say in advance which path applies, it guarantees no merge method;
  `merge_method` is documented as supported only for direct merges. Route
  from the inspected trunk policy and send the explicit action.
- **Queue requests omit direct-only parameters.** A `merge_queue` request
  that also sent `merge_method` was refused with HTTP 422 ("Custom merge
  params (merge_method, commit_title, commit_message) are not supported with
  the merge_queue merge action."). The same request without it was accepted;
  the queue rules choose the method.
- **No blind retry.** An accepted new request answers 202 with
  `status: pending` and a request `uuid` that echoes `merge_action`,
  `merge_method` (`default` when none was sent), `expected_head_sha` and
  `bypass_rules`; check the echo against the request. GitHub documents an
  immediate 200 without a new request when the pull request is already
  merged (`merged`, with `details.sha`) or already in a merge queue
  (`enqueued`); record it and confirm from pull request facts. A 400 (pull
  request closed or draft, not ready to merge) or 422 is a definite refusal.
  A timeout or transport failure leaves the outcome unknown: reconcile from
  pull request state and request status, never by sending the request again.
  A 409 that names an existing request returns that request's identity;
  reconcile its options before assuming yours took effect.
- **No atomicity claim.** Do not promise that the prefix lands all at once.
  Verify every member individually.

Poll the request on the same pull request:

```bash
gh api repos/{owner}/{repo}/pulls/<highest>/merge-async/<uuid>
```

Documented statuses are `pending`, `merged` (with `details.sha`, the
selected pull request's landing commit), `enqueued` (added to the merge
queue) and `failed` (`details.message` describes the failure). Treat any
other value as unreadable evidence. `enqueued` is terminal for the request
and does not mean merged: it stayed `enqueued` after the queue had landed
both selected pull requests. `failed` is a recorded outcome, not a reason to
resend; reconcile from pull request facts. Even `merged` names only the
selected pull request's landing. Request results are retained for 24 hours;
afterwards the status read returns 404. Treat a 404 as an unknown request,
never as merged, and reconcile from pull request facts.

After the request settles:

1. Confirm each selected member from its own pull request facts: state
   `MERGED`, merge commit, and a landing tree equal to the reviewed tree.
2. Confirm each retained (unselected) open member. GitHub retargeted the
   lowest retained member to the stack base and rebased it onto the new
   landing. Its tree, and its diff against the new base, must still equal the
   reviewed slice.
3. Re-fetch, verify stack topology, CI and provenance, then rebuild or
   resync the remaining stack. Clean only confirmed merged branches; never
   delete a base that an open member still uses.

### Choosing a merge method for trailer survival

Key the method choice on the repository's squash message policy, not on
whether squash is merely one of the allowed methods:

```bash
gh api repos/{owner}/{repo} \
  --jq '{title: .squash_merge_commit_title, message: .squash_merge_commit_message}'
```

| `squash_merge_commit_message` | Trailers under `merge_method=squash` |
| --- | --- |
| `COMMIT_MESSAGES` (GitHub default) | Survive automatically, once per squashed commit |
| `PR_BODY` | Survive only if every PR body already carries them |
| `BLANK` | Always lost; Armory sends no `commit_title`/`commit_message` override |

Under `BLANK`, either change the repository's message policy before merging or
use `merge_method=merge`/`rebase` for a direct merge; `merge_method=squash`
gives up provenance with no recovery path. Under a merge queue the queue rules
pick the method, so check the queue's method against this table before
enqueueing.

### Commit-title control under squash

With `squash_merge_commit_title: COMMIT_OR_PR_TITLE` (GitHub's default), a
pull request that squashes a single commit takes that commit's headline as the
base-branch commit subject, not the PR title. This cannot be corrected after
merge without rewriting pushed base-branch history. Before merging, when the
visible base-branch subject matters for a single-commit PR under a squash
merge, align the commit headline with the PR title first:

```bash
git commit --amend -m "<pr-title>"
git push --force-with-lease origin <branch>
```

### Merge queues

When the stack base uses a merge queue, send `merge_action=merge_queue`
without direct-only parameters. Members enter the queue and can land in
separate merge groups: a two-member prefix produced two successful
`merge_group` runs. Group count and cross-group atomicity are not guaranteed.
Require explicit queue acceptance, then verify topology, CI, provenance and
each member's landing after every group, and keep polling pull request facts
after the request reports `enqueued`.

## CI and fallback

GitHub applies the bottom pull request's base-branch requirements across a
native stack. Still inspect every displayed stack layer as green before a merge.

Manual Armory mode remains mandatory for a stack Inspect has NOT already found
native: an ineligible creation probe, a cross-fork stack, unavailable preview
tooling, or topology mismatch. It retains its root-to-leaf merge, explicit
rebase/retarget, and trailer-preservation rules. Manual mode is not available
once Inspect finds a stack already native — see "Two distinct operations"
above.
