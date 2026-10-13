# Merge Discipline

Stacked PRs land parent-first in any graph shape: the root first, and a child only after every ancestor has landed. Siblings of one parent are independent of each other; each selected sibling is promoted separately from its own recorded fork point (the same parent head unless an explicit fork is given) and lands on its own.

The executable owner is `skills/ship-workflow` `scripts/ship.py --stack-plan PATH` (`references/stack-model.md` § Explicit Stack Decision Packet). It lands each selected node through the single-PR lifecycle (gates, guarded merge, landing and post-merge checks, cleanup) and promotes children between landings per `references/sync-algorithm.md`. The commands below are the hand-run equivalents and state the same rules.

## Rules

- A selected node lands only after every ancestor is provider-confirmed merged, in this run or an earlier one.
- Before merging a parent, record the exact old head and fork point of every open child of that parent that will be promoted; the executable does this for every open selected child (`references/sync-algorithm.md` § Promotion Identities). Refuse the parent merge while any such child's fork boundary is unprovable. An open child that is not promoted keeps the parent branch retained.
- Push, retarget or merge only from an invoking checkout without local changes, conflicts or a Git operation in progress.
- Merge one node at a time, bound to its verified head. Gates are current for that head and its current base; earlier green from another head or base is never reused.
- After each landing, re-read the trunk tip, promote each open selected child onto it, push with an explicit expected-old lease, retarget, and renew the child's gates.
- Never use provider merge-time branch deletion, admin bypass, or automatic conflict resolution.
- Never touch an unselected node: its refs, PR, base and local branches stay as they are.

## Landing A Node

```bash
git log --format='%H %(trailers:key=Stack-Id,valueonly)' <parent>..<branch>
gh api repos/{owner}/{repo} \
  --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'
gh pr list --state open --json number,baseRefName,headRefName,headRefOid \
  --jq '.[] | select(.baseRefName == "<branch-being-merged>")'
gh pr merge <pr> --merge --match-head-commit <head-oid>
git fetch origin
```

The method (`--merge`, `--squash` or `--rebase`) is the one the node's decision authorizes and the repository allows. A requested method the repository disables is a stop, not a reason to pick another.

For a stack the skill created, verify `Stack-Id` and `Stack-Position` trailers before each merge. If the repository squashes and `squash_merge_commit_message` is `PR_BODY` or `BLANK`, use the squash-body path from `references/provenance.md` for a hand-run merge; the executable never overrides the squash commit message, so a decision that needs trailers in trunk history under those policies selects `merge` or `rebase`. For an existing published stack, provenance is preserved as found (`references/provenance.md` § Existing Published Stacks).

If the child-base query returns any PRs, record their promotion identities before merging and keep the parent branch.

## Promote Next Child

Follow `references/sync-algorithm.md` § Proof, § Hand-Run Recipe and § Retarget, then validate and land the child.

## Landing Proof

Cleanup requires a complete landing proof:

| Landing | Proof |
| --- | --- |
| Merge commit or fast-forward | The branch head is an ancestor of the landing, and the landing is reachable from the trunk |
| Squash or rebase | A recorded or provider-verifiable landed head equal to the branch head, plus a landing reachable from the trunk; or independently verified complete inclusion of the branch's entire net change in the landing |

`git cherry`, whitespace-normalized patch IDs, and a quiet `git diff` against the trunk are not proof: a multi-commit branch squashed into one commit, a partial inclusion, or later trunk changes defeat them. A branch with any work added after the proved landing is retained.

```bash
gh pr view <pr> --json state,headRefOid,mergeCommit
git rev-parse refs/heads/<branch>
git merge-base --is-ancestor <landing-oid> origin/<trunk>
```

## Retention

A parent head ref, local and remote, is retained while any of these holds:

- Any open PR uses it as head or base: selected or not, in the same repository or from a fork.
- An active, dirty or locked worktree holds it.
- The local or remote ref has work added after the landing.

Retention is not a failure of the node: it is reported with the dependent PRs or the holding worktree and the exact remaining action.

## Provider Auto-Delete And Auto-Retarget

A repository setting can delete a merged head branch and retarget its open children to the trunk on its own. That retarget does not promote the child: its head still sits on the old parent head. Check facts after every landing and never assume either outcome. An already-retargeted child or an already-deleted parent head is reconciled as the observed state; the fork point recorded before the merge keeps the child's slice provable.

Deleting a branch that an open PR uses as its base is unsafe whatever the provider then does: depending on provider and repository settings, the child PR may be closed unmerged or retargeted with a diff that now includes landed parent commits. Neither is acceptable without promotion.

## Endpoints

| Endpoint | Finishes when |
| --- | --- |
| `pr` | Observation only: the packet is checked against provider facts; nothing is captured, promoted, retargeted, merged or deleted |
| `merged` | Every selected node is landed and its post-merge checks passed. No feature branch is deleted |
| `clean` | `merged`, plus proof-based cleanup of each selected node's stale branches and worktrees after its children were retargeted or landed |

A node that merged but failed a post-merge check, or whose required cleanup is incomplete, is merged-but-incomplete (`BLOCKED` with the confirmed merge preserved), never complete. Resuming continues from the confirmed merge in the same run without another merge. A parent whose only cleanup obstruction is an open child base resumes cleanup after that child is retargeted or landed.

An unselected sibling or child that stays open keeps the parent branch retained. Under `clean` that makes the run `BLOCKED` with the exact dependent PRs, not `COMPLETE`; under `merged` the branch is simply not deleted.

## Cleanup

```bash
git fetch origin
git worktree list --porcelain
```

Delete a local branch only with a passed landing proof, as a compare-and-swap on the proved OID, and only when no worktree holds it:

```bash
git update-ref -d refs/heads/<merged-stack-branch> <proved-oid>
```

Before deleting a remote stack branch, verify no open PR uses it as head or base, then delete with an explicit expected-old lease:

```bash
gh pr list --state open --json number,baseRefName,headRefName \
  --jq '.[] | select(.baseRefName == "<merged-stack-branch>" or .headRefName == "<merged-stack-branch>")'
git push --force-with-lease=refs/heads/<merged-stack-branch>:<proved-oid> origin :refs/heads/<merged-stack-branch>
```

A provider that already deleted the remote branch is an observed no-op, not permission to discard a changed local branch. `git branch -D` on unproven say-so is never used; deleting an unmerged branch requires the user explicitly asking after reviewing the risk.

## Recovery: Deleted Parent Branch Closed A Child PR

Use this path only for the specific provider failure where a child PR was closed unmerged because its base branch disappeared. It recreates the same manual PR; it never converts the stack to a native one or changes repository settings.

1. Confirm the closed child PR has `mergedAt: null`.
2. Confirm the deleted branch was the closed PR's `baseRefName`.
3. Confirm the child `headRefName` still exists on `origin`.
4. Confirm the child head commit is still the intended stack slice.
5. Promote the child onto the trunk per `references/sync-algorithm.md` if its parent landed.
6. Recreate the PR against `<base>` or the current merged parent.
7. Wait for required provider checks on the recreated PR.
8. Continue parent-first merging.

## Stop Conditions

- An ancestor of the node is not merged.
- Required checks are failing, pending, or not current for the node's head and base.
- A child's fork boundary is unprovable before its parent merges.
- The three-way expected tree conflicts.
- The child's slice contains a merge commit.
- A slice commit becomes empty on the new base.
- Commit signing is configured, or a slice commit is signed: the executable's plumbing replay cannot sign.
- The invoking checkout has local changes, a conflict or a Git operation in progress before a push, retarget or merge.
- An expected-old lease is stale.
- Topology or a head changed since the packet was written for a selected node or one of its ancestors: a new, missing, rebased, retargeted or closed node, a changed parent, or a head moved outside the controller. The same change to another unselected node is reported, not a stop.
- The node is a native stack member (`references/stack-model.md` § Native Stack Detection).
- In a stack the skill created, a commit is missing `Stack-Id` or has a `Stack-Id` that differs from `.stack-prs.yaml`.
- Squash message policy is `PR_BODY` or `BLANK`, the merge is hand-run, and stack trailers the skill created are not present in the squash body or PR body.
- Provider reports branch protection failure.
- A branch fails its landing proof.
- A closed unmerged child PR cannot be traced to deleted-base recovery.

Report the stopped node and the next safe action.
