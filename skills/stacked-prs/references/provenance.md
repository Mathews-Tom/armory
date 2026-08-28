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

Trailer survival depends on merge mode and, for squash, on the repository's
squash message policy — not on a blanket "squash discards messages"
assumption.

| Merge mode | Commit messages | Trailers survive |
| --- | --- | --- |
| `gh pr merge --merge` | Original commits preserved | Yes, automatically |
| `gh pr merge --rebase` | Original commits replayed | Yes, automatically |
| `gh pr merge --squash`, policy `COMMIT_MESSAGES` (GitHub default) | Every squashed commit's full message concatenated | Yes, automatically, once per squashed commit |
| `gh pr merge --squash`, policy `PR_BODY` | PR body only | Only if the PR body carries the trailers |
| `gh pr merge --squash`, policy `BLANK` | Discarded | No; fold trailers in with `--body` |

Detect the repo's squash message policy before merging, not merely whether
squash is allowed:

```bash
gh api repos/{owner}/{repo} \
  --jq '{title: .squash_merge_commit_title, message: .squash_merge_commit_message}'
```

- `COMMIT_MESSAGES` (GitHub's default): trailers survive automatically. No
  `--body` override needed.
- `PR_BODY`: trailers survive only if the PR body includes them; use the
  squash-body path below.
- `BLANK`: trailers are always discarded; use the squash-body path below or
  switch to `--merge`/`--rebase`.

The documented merge path uses `--merge`, so trailers survive as-is by
default. When the target repository squashes and `squash_merge_commit_message`
is `PR_BODY` or `BLANK`, inject the trailers into the squash commit body:

```bash
gh pr merge <pr> --squash \
  --subject "<pr-title>" \
  --body "$(printf '%s\n\n%s\n%s' \
    '<pr-summary>' \
    'Stack-Id: <stack-id>' \
    'Stack-Position: <n>/<total>')"
```

For a GitHub-native stack merged with `gh stack merge`, no `--subject`/`--body`
override exists (`references/github-native.md` § Merge). Under
`COMMIT_MESSAGES` this is safe by default; under `PR_BODY` or `BLANK`, fold
the trailers into each PR body before merging so the squash captures them, or
use `--merge-method merge`/`rebase` instead of squash.

Detect the repo's overall merge policy (which methods are allowed) separately,
to choose a method at all:

```bash
gh api repos/{owner}/{repo} \
  --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'
```

If only squash is allowed, take the squash-body path (or confirm
`COMMIT_MESSAGES`). Otherwise prefer `--merge`.
