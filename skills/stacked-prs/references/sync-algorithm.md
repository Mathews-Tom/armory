# Sync Algorithm

Sync rebases every stack branch onto its current parent and pushes rewritten history with a lease.

## Preflight

```bash
git rev-parse --show-toplevel
git status --porcelain
git fetch origin --prune
gh pr list --state open --json number,title,headRefName,baseRefName,state,url
```

Stop if the worktree is dirty or the parent chain is ambiguous.

## Rebase Order

Start at the root branch above the base and walk toward the leaf:

```bash
git switch <root-branch>
git rebase <base-branch>
git push --force-with-lease origin <root-branch>

git switch <child-branch>
git rebase <root-branch>
git push --force-with-lease origin <child-branch>
```

Use the local parent branch after rebasing it. Do not rebase children onto stale remote refs.

## Retargeting After Parent Merge

When a parent lands into `<base>`, the child must be rebased onto `origin/<base>` and its PR base retargeted to `<base>`:

```bash
git fetch origin --prune
git switch <child-branch>
git rebase origin/<base>
git push --force-with-lease origin <child-branch>
gh pr edit <child-pr> --base <base>
```

Then repeat for the next child.

## Conflict Handling

On conflict:

```bash
git status --short
git diff --name-only --diff-filter=U
```

Report the active branch, parent branch, and conflicted files. Do not continue to children. Do not auto-resolve conflicts.

## Lease Failure

If `--force-with-lease` fails, the remote branch changed since fetch. Stop and run a fresh inspect. Do not use plain `--force`.

## Validation After Sync

Run validation according to the target repository's detected gates and required provider checks. Do not substitute armory package-evaluation commands for another repository's local gate.

For armory package development only:

```bash
uv run python scripts/validate_evals.py
uv run python scripts/generate_manifest.py
uv run python scripts/evaluate_package.py --path skills/stacked-prs
```

Record validation results in PR bodies when provider mutation is part of the requested workflow.
