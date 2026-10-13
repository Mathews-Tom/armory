# GitHub-native stacked pull requests

Native-stack membership is a provider-side property of a pull request;
detect it for every open stack PR during Inspect (`references/stack-model.md`
§ Native Stack Detection) before any landing decision. This reference owns
native linking, sync and the landing policy; the landing itself is delegated to
the installed `ship-workflow` skill's stack graph run, and native members are
never merged by the ordinary single-PR path or the manual graph path.

## Two distinct operations, two different opt-in rules

- **Creating native state** — `gh stack link` converts a manual stack (or
  links loose PRs) into a native stack on GitHub. This is a provider
  mutation; it requires the eligibility checks below plus explicit user
  consent.
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
5. The user explicitly selects `github-native` mode.

Do not use native linking for cross-fork stacks, unavailable `gh stack`
tooling, disabled repository support, or topology mismatch. Report the reason and use
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
open stack PR during Inspect, before merge planning. Read the complete,
ordered membership from the stack itself:

```bash
gh api repos/{owner}/{repo}/stacks/<stack-number>
```

Members are listed bottom to top, including members that already merged (they
keep their original heads). After a partial landing the stack still lists
every position.

If the probe is unavailable for any reason, membership is unknown: do not
author a landing packet until the reads above succeed. The delegated run stops
a selection whose stack number, position, size or base it cannot read.

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

## Landing policy

An already-native stack lands through one asynchronous request on the highest
selected pull request. GitHub merges the prefix of open members ending at
that pull request; there is no per-member request and no synchronous
fallback. This skill decides the scope and authors the stack decision packet
(`references/stack-model.md` § Explicit Stack Decision Packet); the installed
`ship-workflow` skill's `scripts/ship.py --stack-plan PATH` run sends the
request, follows it and proves every landing. Require a fully linear history
between stack branches before delegating.

Never infer a prefix. Require the exact highest pull request number the user
authorized, select it and every open member below it, and list every open
member above it as an unselected packet node so its retention can be proved.

The delegated run applies these provider facts; they also define what its
results mean:

- **Only the selected head is guarded.** The request sends the highest
  selected pull request's inspected head as `sha` with `bypass_rules=false`;
  the lower members' heads and the stack membership are not checked by the
  server atomically. The run re-reads every member immediately before
  dispatch and refuses when an open lower member is outside the selection.
- **Route on the stack base.** The stack base branch (the bottom pull
  request's base) carries the rules that govern the whole stack; a middle
  member's own base is just another stack branch. The run sends
  `merge_action=merge_queue` when that trunk has a merge queue and
  `direct_merge` when its policy is fully known without one. An unreadable
  trunk policy is blocked; it never falls back to `direct_merge`.
- **`default` is supported but not a routing shortcut.** `merge_action=default`
  (also what the server uses when the parameter is omitted) uses a merge
  queue when one is configured for the target branch and merges directly
  otherwise. A personal-repository request with `merge_action=default` and
  `merge_method=squash` was accepted and echoed both. Because `default` does
  not say in advance which path applies, it guarantees no merge method;
  `merge_method` is documented as supported only for direct merges, so the
  run routes from the inspected trunk policy and sends the explicit action.
- **Queue requests omit direct-only parameters.** A `merge_queue` request
  that also sent `merge_method` was refused with HTTP 422 ("Custom merge
  params (merge_method, commit_title, commit_message) are not supported with
  the merge_queue merge action."). The same request without it was accepted;
  the queue rules choose the method, and the packet's method is reported as
  not sent.
- **No resend.** An accepted request echoes `merge_action`, `merge_method`
  (`default` when none was sent), `expected_head_sha` and `bypass_rules`.
  GitHub answers an immediate 200 without a new request when the pull
  request is already merged or already in a merge queue. A 400 or 422 is a
  definite refusal. A timeout, transport failure or unechoed answer leaves
  the outcome unknown: it is reconciled from pull request facts, never by
  sending the request again, and a 409 naming a request with other options is
  never adopted.
- **Statuses are not landings.** Documented statuses are `pending`, `merged`
  (naming only the selected pull request's landing), `enqueued` and
  `failed`. `enqueued` is terminal for the request and never means merged: it
  stayed `enqueued` after the queue had landed both selected pull requests,
  and queue members can land in separate merge groups. Request results are
  retained for 24 hours; a later 404 is an unknown request, never a merge.
- **No atomicity claim.** The prefix is not promised to land at once. Each
  selected member is proved from its own pull request facts: state `MERGED`,
  a landing reachable from the stack base, and a full landing tree equal to
  the clean three-way application of its reviewed own slice to the
  canonical-trunk base before that landing. A merged upper member keeps its
  review base (the lower member's branch) although it landed on the stack
  base; that is expected, not a contradiction, and is never rewritten.
- **Retained members are verified, not rewritten.** GitHub retargets the
  lowest retained member to the stack base and rebases it onto the new
  landing; higher retained members stay based on the member immediately
  below them and contain its current head. The run verifies each full
  rebased tree and exact own-slice identity against that placement and
  never pushes, retargets or rewrites a retained member. Cleanup keeps every
  base an open member still uses.

After the run, re-inspect the remaining stack topology, CI and provenance
before any further sync or delegation.

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

Under `BLANK`, decide `merge_method=merge`/`rebase` for a direct merge, or
obtain the user's decision to change the repository's message policy;
`merge_method=squash` gives up provenance with no recovery path. Under a merge
queue the queue rules pick the method, so check the queue's method against
this table before delegating.

### Commit-title control under squash

With `squash_merge_commit_title: COMMIT_OR_PR_TITLE` (GitHub's default), a
pull request that squashes a single commit takes that commit's headline as the
base-branch commit subject, not the PR title. This cannot be corrected after
merge without rewriting pushed base-branch history. Before delegating, when the
visible base-branch subject matters for a single-commit PR under a squash
merge, align the unmerged commit headline with the PR title first and record
the new head in the packet:

```bash
git commit --amend -m "<pr-title>"
git push --force-with-lease=refs/heads/<branch>:<old-head> origin <branch>
```

### Merge queues

When the stack base uses a merge queue, the delegated run sends
`merge_action=merge_queue` without direct-only parameters. Members enter the
queue and can land in separate merge groups: a two-member prefix produced two
successful `merge_group` runs. Group count and cross-group atomicity are not
guaranteed. The run keeps following pull request facts after the request
reports `enqueued` and proves each member's landing as its group lands; a run
that reaches its monitoring window first returns `WAITING` and is resumed,
never re-requested.

## CI and manual stacks

GitHub applies the bottom pull request's base-branch requirements across a
native stack. The delegated run still renews every open selected member's
gate before the request.

A stack Inspect has NOT found native stays manual: failed creation checks, a
cross-fork stack, unavailable `gh stack` tooling, or topology mismatch. Its
landing is delegated through the same stack decision packet, which the run
continues parent-first with slice-preserving promotion, explicit leases,
retargeting and trailer preservation. The manual path is not available once
Inspect finds a stack already native — see "Two distinct operations" above.
