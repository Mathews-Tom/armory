# Merge Discipline

Stacked PRs land bottom-up from the base perspective: merge the root PR first, then the next child, then the leaf.

## Rules

- Require parent PR checks before merging a child.
- Merge only one stack PR at a time.
- After each merge, fetch, rebase the next child onto the updated base, push with lease, and retarget the child PR.
- Do not delete a branch while any open PR still has that branch as its base.
- Delete remote stack branches only during final cleanup after descendants are merged or retargeted.
- Delete local branches only when `git branch --merged <base>` proves they are merged.

## Root Merge

```bash
git log --format='%H %(trailers:key=Stack-Id,valueonly)' <parent>..<branch>
gh api repos/{owner}/{repo} \
  --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'
gh pr list --state open --json number,baseRefName,headRefName \
  --jq '.[] | select(.baseRefName == "<branch-being-merged>")'
gh pr merge <root-pr> --merge
git fetch origin --prune
```

Verify `Stack-Id` and `Stack-Position` trailers before each merge. Prefer `gh pr merge <pr> --merge` when merge commits are allowed. If the repository squashes and `squash_merge_commit_message` is `PR_BODY` or `BLANK`, use the squash-body path from `references/provenance.md`; do not merge until the trailers are present. Under `COMMIT_MESSAGES` (GitHub's default), squash already preserves trailers automatically.

If the child-base guard returns any PRs, keep the parent branch. On GitHub, deleting a branch that is still a child PR base can close the child PR unmerged.

## Promote Next Child

```bash
git switch <child-branch>
git rebase origin/main
git push --force-with-lease origin <child-branch>
gh pr edit <child-pr> --base main
```

Then validate and merge that child.

## Cleanup

```bash
git switch main
git pull --ff-only origin main
git fetch --prune origin
git branch --merged main
git branch -d <merged-stack-branch>
```

Before deleting any remote stack branch, verify no open PR still targets it:

```bash
gh pr list --state open --json number,baseRefName,headRefName \
  --jq '.[] | select(.baseRefName == "<merged-stack-branch>")'
git push origin --delete <merged-stack-branch>
```

Never use `git branch -D` for stack cleanup unless the user explicitly asks to delete an unmerged branch after reviewing the risk.

## Recovery: Deleted Parent Branch Closed A Child PR

Use this path only for the specific provider failure where a child PR was closed unmerged because its base branch disappeared.

1. Confirm the closed child PR has `mergedAt: null`.
2. Confirm the deleted branch was the closed PR's `baseRefName`.
3. Confirm the child `headRefName` still exists on `origin`.
4. Confirm the child head commit is still the intended stack slice.
5. Recreate the PR against `main` or the current merged parent.
6. Wait for required provider checks on the recreated PR.
7. Continue root-to-leaf merging.

## Stop Conditions

- Parent PR is not merged.
- Required checks are failing or pending.
- A stack commit is missing `Stack-Id` or has a `Stack-Id` that differs from `.stack-prs.yaml`.
- Squash message policy is `PR_BODY` or `BLANK` and stack trailers are not present in the squash body or PR body.
- Provider reports branch protection failure.
- Rebase conflict occurs after parent merge.
- Local branch is not listed by `git branch --merged <base>`.
- A closed unmerged child PR cannot be traced to deleted-base recovery.

Report the stopped branch and next safe command.
