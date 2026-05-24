---
name: stacked-prs
description: 'Manages dependent branch stacks and stacked pull requests using safe Git topology rules. Triggers on: "create stacked PRs", "publish this stack", "sync my PR stack", "rebase this stack", "merge the stack", "retarget child PRs", "split this branch into stacked PRs", "validate this stack", "cleanup stacked branches". Use when local branches or one source branch need to become a dependency-ordered PR stack with correct parent bases, validation, synchronization, merge order, and cleanup.'
metadata:
  version: 0.1.0
  category: development
  tags: [git, pull-requests, stacked-prs, workflow]
  difficulty: advanced
  phase: ship
---

# Stacked PRs

Build, publish, synchronize, validate, merge, and clean up stacked pull requests without corrupting branch topology.

The package identity is provider-neutral. Git is the source of truth for branch ancestry; provider PR metadata is the source of truth for review bases. GitHub through `gh` is the first documented provider adapter.

## Reference Files

| File | Contents | Load When |
| --- | --- | --- |
| `references/stack-model.md` | Stack inference, explicit ordering, and `.stack-prs.yaml` rules | Inspecting, publishing, validating, or cleaning a stack |
| `references/provider-adapters.md` | Provider adapter contract and GitHub `gh` commands | Creating, retargeting, checking, merging, or deleting PRs |
| `references/sync-algorithm.md` | Rebase and force-with-lease synchronization workflow | Syncing a stack after a parent or base moves |
| `references/merge-discipline.md` | Bottom-up merge and branch cleanup rules | Merging or closing out a stack |
| `references/metadata-format.md` | Optional metadata schema and validation rules | `.stack-prs.yaml` exists or inference is ambiguous |

## When To Use

| Use this skill | Use another package |
| --- | --- |
| Multiple dependent branches need PRs against parent branches | `ship-workflow` for one independent release PR |
| A feature branch must be split into reviewable dependent branches | `task-decomposer` for planning tasks before code exists |
| An existing stack needs rebasing, retargeting, validation, or merge sequencing | `pr-review` for reviewing one PR diff |
| A stack must be cleaned after merge | General Git commands for unrelated branch cleanup |

## Core Rules

- Run `git rev-parse --show-toplevel` before any workflow.
- Run `git status --porcelain` before rebases, pushes, PR creation, PR retargeting, merge, or cleanup.
- Stop on a dirty worktree unless the user explicitly scopes the operation to inspection only.
- Prefer existing PR `baseRefName` values over inferred ancestry.
- Use explicit branch order or `.stack-prs.yaml` when parent inference is ambiguous.
- Never use plain `git push --force`; use `git push --force-with-lease origin <branch>`.
- Merge from root to leaf. Never merge a child before its parent.
- Do not delete unmerged stack branches without explicit user instruction.

## Workflow

### 1. Inspect

Build a stack model without modifying anything:

```bash
git rev-parse --show-toplevel
git status --porcelain
git branch --show-current
git for-each-ref --format='%(refname:short)' refs/heads
git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'
gh pr list --state open --json number,title,headRefName,baseRefName,state,url
```

Produce a table with one row per stack branch:

| Order | Branch | Parent | PR | State | Checks |
| ---: | --- | --- | --- | --- | --- |
| 1 | `feat/parser-core` | `main` | `#101` | open | pending |
| 2 | `feat/parser-cache` | `feat/parser-core` | `#102` | open | pending |

Stop when no provider adapter is available, no local branches match the requested stack, or parent order cannot be inferred from PR bases, explicit order, or metadata.

### 2. Publish

Create missing PRs and retarget wrong bases:

```bash
git status --porcelain
git push -u origin <branch>
gh pr create \
  --base <parent-branch> \
  --head <branch> \
  --title "<title>" \
  --body-file <generated-body-file>
gh pr edit <number> --base <parent-branch>
```

Generated PR bodies must include the stack order and validation state:

```markdown
## Stack

Base: `main`

1. `feat/parser-core` -> this PR
2. `feat/parser-cache` -> depends on #102

## Validation

- Pending: commands not run yet
```

Stop when a branch has no commits beyond its parent, an existing PR is closed and unmerged, or the provider rejects base retargeting.

### 3. Sync

Rebase each stack branch onto its parent after `main` or any parent branch moves:

```bash
git status --porcelain
git fetch origin --prune
git switch <branch>
git rebase <parent-branch>
git push --force-with-lease origin <branch>
```

Start at the first branch above the base and continue toward the leaf. Stop on conflicts, remote lease failures, or a parent PR that closed without merge.

### 4. Validate

Validate the stack as reviewable slices. Run cheap checks on every branch when practical; run expensive full checks on the leaf when branch-by-branch validation is not reasonable. Record exactly what ran in each PR body.

Use the target repository's detected local gate and provider checks. Do not run armory package-evaluation commands when operating on another repository's stack.

For this armory package implementation only, use:

```bash
uv run python scripts/validate_evals.py
uv run python scripts/generate_manifest.py
uv run python scripts/evaluate_package.py --path skills/stacked-prs
```

### 5. Merge

Merge root to leaf:

```bash
gh pr list --state open --json number,baseRefName,headRefName \
  --jq '.[] | select(.baseRefName == "<branch-being-merged>")'
gh pr merge <root-pr> --merge
git fetch origin --prune
git switch <child-branch>
git rebase origin/main
git push --force-with-lease origin <child-branch>
gh pr edit <child-pr> --base main
```

On GitHub, do not pass `--delete-branch` while any open PR still has the branch being merged as its `baseRefName`. Deleting a parent branch that is still a child PR base can close the child PR unmerged. Repeat for each child. Require parent checks and provider merge confirmation before moving to the next branch.

### 6. Cleanup

After the stack lands:

```bash
git switch main
git pull --ff-only origin main
git fetch --prune origin
git branch --merged main
git branch -d <merged-stack-branch>
```

Delete only branches confirmed merged into the current base.

Delete remote stack branches only after every stack PR has landed or been retargeted away from the branch:

```bash
gh pr list --state open --json number,baseRefName,headRefName \
  --jq '.[] | select(.baseRefName == "<merged-stack-branch>")'
git push origin --delete <merged-stack-branch>
```

## Splitting One Branch Into A Stack

Use split mode when one source branch contains a feature that needs reviewable dependent PRs. Require the source branch, base branch, and target branch order from the user or from unambiguous commit names.

Inspect first:

```bash
git status --porcelain
git fetch origin --prune
git merge-base <base> <source-branch>
git log --oneline --reverse <base>..<source-branch>
git diff --stat <base>...<source-branch>
git diff --name-status <base>...<source-branch>
```

Select the safest split mode:

| Mode | Use When | Behavior |
| --- | --- | --- |
| Commit-range split | Contiguous commits map cleanly to slices | Create dependent branches and cherry-pick ranges |
| Commit-list split | Non-contiguous commits map cleanly to slices | Cherry-pick explicit commit lists in stack order |
| Patch-guided split | File or hunk boundaries are clear but commits are mixed | Stop for user-approved split map before mutation |
| Refuse automatic split | Changes are tangled across required boundaries | Report why the split is unsafe |

After creating branches, compare the leaf with the source branch before publishing:

```bash
git diff --stat <source-branch>...<leaf-branch>
git diff --exit-code <source-branch>...<leaf-branch>
```

Do not publish if the leaf differs from the source branch.

## Error Handling

| Condition | Action |
| --- | --- |
| Dirty worktree before mutation | Stop and report changed paths |
| Ambiguous parent order | Request explicit branch order or `.stack-prs.yaml` |
| Existing closed unmerged PR | Stop before creating replacements |
| Closed unmerged child after parent branch deletion | Confirm the head branch and intended commit still exist, recreate the PR against `main` or the current merged parent, wait for checks, then continue |
| Rebase or cherry-pick conflict | Stop, report branch and conflicted files, do not continue children |
| Remote branch changed since fetch | Stop; do not retry without a fresh inspect |
| Failed validation | Record the failed command and stop merge or publish |
| Top split branch differs from source | Stop before PR creation and report remaining diff |

## Recovery: Deleted Parent Branch Closed A Child PR

Use this only when a provider closed a child PR because its base branch was deleted during stack landing.

1. Confirm the closed PR is unmerged.
2. Confirm the closed PR's base branch was deleted by the parent merge or cleanup command.
3. Confirm the child head branch still exists on `origin`.
4. Confirm the child head commit is the intended stack slice.
5. Recreate the PR against `main` or the current merged parent.
6. Wait for required checks on the recreated PR.
7. Continue the root-to-leaf merge sequence.

## Output Format

Report:

1. Stack order with branch, parent, PR number or URL, and state.
2. Mutations performed, including PR creation, base edits, rebases, pushes, merges, or branch deletion.
3. Validation commands and exact pass/fail status.
4. Next safe action, usually merge root PR, fix validation, resolve conflict, or provide explicit branch order.
