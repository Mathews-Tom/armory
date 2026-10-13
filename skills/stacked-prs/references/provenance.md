# Stack Provenance

Stack identity must survive in plain git history, not only in the provider.
Branch topology is not recoverable after a rebase-based merge; stack identity is,
via commit trailers.

## Trailers

Every commit in a stack the skill creates carries:

```text
Stack-Id: <slug>-<shortid>
Stack-Position: <n>/<total>
```

Trailers live in the last paragraph of the commit message, separated from the
body by one blank line. Because they are part of the message, they survive
rebase, cherry-pick, amend, and the slice promotion in
`references/sync-algorithm.md`, which replays message bytes unchanged.

`Stack-Position` is an advisory label from stack creation; siblings carry
distinct positions (`references/metadata-format.md` § Stack Identity). Labels of
a published stack are never recomputed.

## Stamping On Commit Creation

When the skill itself creates commits, including split-mode cherry-picks and
any commit it authors, append trailers with `git interpret-trailers`:

```bash
git interpret-trailers --in-place \
  --trailer "Stack-Id: <stack-id>" \
  --trailer "Stack-Position: <n>/<total>" \
  <commit-msg-file>
```

For a commit the skill created during split that still needs trailers:

```bash
git commit --amend --no-edit \
  --trailer "Stack-Id: <stack-id>" \
  --trailer "Stack-Position: <n>/<total>"
```

`git commit --trailer` requires Git >= 2.32. If unavailable, pipe the message
through `git interpret-trailers` and amend with `-F`.

## Restamping Unpublished Commits

Rewriting history to add trailers applies only to commits the skill itself
created in this run that are not yet published: no remote ref and no PR contains
them. Rewrite the range unique to each branch above its parent without changing
tree content:

```bash
git rebase <parent> <branch> \
  --exec 'git commit --amend --no-edit \
    --trailer "Stack-Id: <stack-id>" \
    --trailer "Stack-Position: <n>/<total>"'
```

Never restamp commits that are published, already merged into the base, or
authored outside the skill.

## Existing Published Stacks

Provenance of an externally created or already published stack is preserved as
found: commit trailers, PR titles and bodies, and `.stack-prs.yaml` are never
stamped, backfilled, restamped, or rewritten to satisfy missing provenance, and
no historic lineage is invented.

A published stack that lacks provenance needs an explicit, scoped provenance
decision instead: in the stack decision packet each selected node carries
`provenance` with disposition `preserve` (the only accepted value) and the
`sources` that were inspected, such as trailers, PR bodies, or
`.stack-prs.yaml` (`references/stack-model.md` § Explicit Stack Decision
Packet). The executable validates that decision and journals it with the frozen
packet; it changes no provenance and never reports or invents lineage.

Promoting a child after its parent lands keeps the child's own commits, in
order, with the same author and message bytes, so any trailers they carry
survive unchanged. The committer identity and timestamp are new. The replay
cannot sign: a signed slice commit or configured commit signing stops the
promotion for judgment with nothing rewritten, so no signature is silently
dropped.

## Verifying Trailers

Before merging a stack the skill created, confirm every commit unique to each
branch carries the correct trailers:

```bash
git log --format='%H %(trailers:key=Stack-Id,valueonly)' <parent>..<branch>
```

Stop if any commit in the range is missing `Stack-Id` or carries a different ID
than `.stack-prs.yaml`. For an existing published stack, the same command
reports what is present; a missing trailer is reported, not stamped.

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

| Merge method | Commit messages | Trailers survive |
| --- | --- | --- |
| `merge` | Original commits preserved | Yes, automatically |
| `rebase` | Original commits replayed | Yes, automatically |
| `squash`, policy `COMMIT_MESSAGES` (GitHub default) | Every squashed commit's full message concatenated | Yes, automatically, once per squashed commit |
| `squash`, policy `PR_BODY` | PR body only | Only if the PR body carries the trailers |
| `squash`, policy `BLANK` | Discarded | No |

Merge mode affects only the trunk's landing commit. A child's own commits are
promoted with their messages unchanged whichever mode landed its parent, and
cleanup relies on the landing proof in `references/merge-discipline.md`, not on
trailers.

Detect the repo's squash message policy before choosing a node's merge
method, not merely whether squash is allowed:

```bash
gh api repos/{owner}/{repo} \
  --jq '{title: .squash_merge_commit_title, message: .squash_merge_commit_message}'
```

- `COMMIT_MESSAGES` (GitHub's default): trailers survive a squash
  automatically.
- `PR_BODY`: trailers survive a squash only if the PR body includes them. For
  a stack the skill created, put them in each PR body while publishing;
  otherwise decide `merge` or `rebase`.
- `BLANK`: trailers are always discarded by a squash; decide `merge` or
  `rebase`.

The delegated `ship-workflow` stack run merges each node with the method its
decision authorizes and the repository allows, bound to the verified head,
without overriding the squash commit title or message and never with
merge-time branch deletion. When only squash is allowed under `BLANK`, or
under `PR_BODY` for a stack whose PR bodies lack the trailers, losing them in
trunk history is a provenance decision for the user, never a silent default.
For an existing published stack, do not add trailers to PR bodies it never
carried.

A GitHub-native stack is landed with one `merge-async` request by the delegated
run (`references/github-native.md` § Landing policy). Its `merge_method` applies to direct
merges only; `commit_title` and `commit_message` exist but are direct-merge-only
too, and Armory sends neither. A queue request omits all three, and the queue
rules select the method. Under `COMMIT_MESSAGES` a squash is safe by default;
under `PR_BODY`, for a stack the skill created, fold the trailers into each PR
body before merging so the squash captures them. Under `BLANK` trailers are
lost: change the repository's policy first or merge directly with
`merge_method=merge` or `rebase`. Under a merge queue, check the queue's method
against this policy before enqueueing.

Detect the repo's overall merge policy (which methods are allowed) separately,
to choose a method at all:

```bash
gh api repos/{owner}/{repo} \
  --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'
```

If only squash is allowed, confirm `COMMIT_MESSAGES` or follow the `PR_BODY`
and `BLANK` rules above. Otherwise prefer `merge`.
