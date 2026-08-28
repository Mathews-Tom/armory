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

Outside a merge queue, a native stack merge is atomic: a selected pull request
merges with every lower layer, or none merge. Require a fully linear history
between stack branches before merging.

```bash
# Entire current stack, only after explicit user request; no positional argument
gh stack merge --yes --merge-method merge

# Explicit prefix through PR #42
gh stack merge 42 --yes --merge-method merge
```

Never infer a prefix. Require the exact highest pull request number. GitHub
applies branch protection at merge time. After completion, re-fetch, verify
stack topology/CI/provenance, and clean only confirmed merged branches.

### Choosing a merge method for trailer survival

Key the method choice on the repository's squash message policy, not on
whether squash is merely one of the allowed methods:

```bash
gh api repos/{owner}/{repo} \
  --jq '{title: .squash_merge_commit_title, message: .squash_merge_commit_message}'
```

| `squash_merge_commit_message` | Trailers under `--merge-method squash` |
| --- | --- |
| `COMMIT_MESSAGES` (GitHub default) | Survive automatically, once per squashed commit |
| `PR_BODY` | Survive only if every PR body already carries them |
| `BLANK` | Always lost; `gh stack merge` has no `--subject`/`--body` override |

Under `BLANK`, either change the repository's message policy before merging or
use `--merge-method merge`/`rebase` for this merge; `--merge-method squash`
gives up provenance with no recovery path.

### Commit-title control under squash

`gh stack merge` exposes only `--merge`, `--merge-method`, `--rebase`,
`--squash`, `--yes` — no `--subject` or `--body`. With
`squash_merge_commit_title: COMMIT_OR_PR_TITLE` (GitHub's default), a pull
request that squashes a single commit takes that commit's headline as the
base-branch commit subject, not the PR title. This cannot be corrected after
merge without rewriting pushed base-branch history. Before merging, when the
visible base-branch subject matters for a single-commit PR under
`--merge-method squash`, align the commit headline with the PR title first:

```bash
git commit --amend -m "<pr-title>"
git push --force-with-lease origin <branch>
```

### Merge queues

When the base uses a merge queue, stack members enter the queue together but can
land in separate merge groups. Merge-method flags are ignored, auto-merge is
unsupported, and atomicity does not hold across queue groups. Require explicit
queue acceptance, then verify topology, CI, and provenance after every group.

## CI and fallback

GitHub applies the bottom pull request's base-branch requirements across a
native stack. Still inspect every displayed stack layer as green before a merge.

Manual Armory mode remains mandatory for a stack Inspect has NOT already found
native: an ineligible creation probe, a cross-fork stack, unavailable preview
tooling, or topology mismatch. It retains its root-to-leaf merge, explicit
rebase/retarget, and trailer-preservation rules. Manual mode is not available
once Inspect finds a stack already native — see "Two distinct operations"
above.
