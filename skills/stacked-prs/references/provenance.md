# Stack Provenance

Stack identity must survive in plain git history, not only in the provider.
Branch topology is not recoverable after a rebase-based merge; stack identity is,
via commit trailers.

## Trailers

Every commit in a stack carries:

```text
Stack-Id: <slug>-<shortid>
Stack-Position: <n>/<total>
```

Trailers live in the last paragraph of the commit message, separated from the
body by one blank line. Because they are part of the message, they survive
rebase, cherry-pick, and amend.

## Stamping On Commit Creation

When the skill itself creates commits, including split-mode cherry-picks and
any commit it authors, append trailers with `git interpret-trailers`:

```bash
git interpret-trailers --in-place \
  --trailer "Stack-Id: <stack-id>" \
  --trailer "Stack-Position: <n>/<total>" \
  <commit-msg-file>
```

For an existing commit that needs trailers added during split:

```bash
git commit --amend --no-edit \
  --trailer "Stack-Id: <stack-id>" \
  --trailer "Stack-Position: <n>/<total>"
```

`git commit --trailer` requires Git >= 2.32. If unavailable, pipe the message
through `git interpret-trailers` and amend with `-F`.

## Backfilling An Existing Stack

To stamp a stack that was created before provenance existed, rewrite each
branch's commit range that is unique to that branch above its parent, adding
trailers without changing tree content:

```bash
git rebase <parent> <branch> \
  --exec 'git commit --amend --no-edit \
    --trailer "Stack-Id: <stack-id>" \
    --trailer "Stack-Position: <n>/<total>"'
```

This is history-rewriting. Apply only to unmerged stack branches, then
force-with-lease push. Never backfill commits already merged into the base.

## Verifying Trailers

Before merge, confirm every commit unique to each branch carries the correct
trailers:

```bash
git log --format='%H %(trailers:key=Stack-Id,valueonly)' <parent>..<branch>
```

Stop if any commit in the range is missing `Stack-Id` or carries a different ID
than `.stack-prs.yaml`.

## Recovering A Stack From History

After the stack has landed:

```bash
git log --grep 'Stack-Id: <stack-id>' --oneline
git log --grep 'Stack-Id: <stack-id>' \
  --format='%(trailers:key=Stack-Position,valueonly) %h %s' | sort
```

## Merge Mode Coupling

Trailer survival depends on merge mode:

| Merge mode | Commit messages | Trailers survive |
| --- | --- | --- |
| `gh pr merge --merge` | Original commits preserved | Yes, automatically |
| `gh pr merge --rebase` | Original commits replayed | Yes, automatically |
| `gh pr merge --squash` | Messages collapsed and rewritten | No, unless folded into squash body |

The documented merge path uses `--merge`, so trailers survive as-is. If a
target repo enforces squash merges, inject the trailers into the squash commit
body because GitHub's squash default discards per-commit messages:

```bash
gh pr merge <pr> --squash \
  --subject "<pr-title>" \
  --body "$(printf '%s\n\n%s\n%s' \
    '<pr-summary>' \
    'Stack-Id: <stack-id>' \
    'Stack-Position: <n>/<total>')"
```

Detect the repo's merge policy before merging:

```bash
gh api repos/{owner}/{repo} \
  --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'
```

If only squash is allowed, take the squash-body path. Otherwise prefer `--merge`.
