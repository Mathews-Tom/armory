# GitHub-native stacked pull requests

GitHub-native stacked pull requests are public preview. Use them only as an
optional GitHub adapter over Armory's existing provenance and manual workflow.

## Eligibility

Require all of the following before linking or merging natively:

1. GitHub CLI is version 2.0 or later and `gh stack --help` succeeds. Install
   the extension when absent: `gh extension install github/gh-stack`.
2. Every branch and pull request is in the same GitHub repository. Reject forks
   and cross-repository stacks.
3. Repository native-stack support is enabled. Treat native command exit code 9
   as unavailable and fall back to manual mode.
4. Armory branch order, PR base order, and `Stack-Id`/`Stack-Position` trailers
   agree with the proposed native order.
5. The repository permits merge commits or rebase merges. A squash-only
   repository may link natively but must use Armory's manual squash-body merge
   path so trailers survive.
6. The user explicitly selects `github-native` mode or accepts the preview risk.

Do not use native mode for cross-fork stacks, unavailable preview tooling,
disabled repository support, squash-only merge, or topology mismatch. Report the
reason and use manual Armory mode instead.

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

### Merge queues

When the base uses a merge queue, stack members enter the queue together but can
land in separate merge groups. Merge-method flags are ignored, auto-merge is
unsupported, and atomicity does not hold across queue groups. Require explicit
queue acceptance, then verify topology, CI, and provenance after every group.

## CI and fallback

GitHub applies the bottom pull request's base-branch requirements across a
native stack. Still inspect every displayed stack layer as green before a merge.

Manual Armory mode remains mandatory for every ineligible stack and retains its
root-to-leaf merge, explicit rebase/retarget, and trailer-preservation rules.
