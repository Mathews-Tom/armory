# Merge Discipline

Stacked PRs land parent-first in any graph shape: the root first, and a child only after every ancestor has landed. Siblings of one parent are independent of each other; each selected sibling is promoted separately from its own recorded fork point (the same parent head unless an explicit fork is given) and lands on its own.

The one executable owner is the installed `ship-workflow` skill's `scripts/ship.py --stack-plan PATH` (`references/stack-model.md` § Explicit Stack Decision Packet). It lands each selected node through the single-PR lifecycle (gates, guarded merge, landing and post-merge checks, cleanup) and promotes children between landings per `references/sync-algorithm.md`. This reference states the rules that run enforces so the packet selects the right scope and its outcomes are read correctly; there is no hand-run landing or cleanup alternative.

## Rules

- A selected node lands only after every ancestor is provider-confirmed merged, in this run or an earlier one.
- Before merging a parent, the exact old head and fork point of every open selected child of that parent is recorded (`references/sync-algorithm.md` § Promotion Identities). The parent merge is refused while any such child's fork boundary is unprovable. An open child that is not promoted keeps the parent branch retained.
- Push, retarget or merge only from an invoking checkout without local changes, conflicts or a Git operation in progress.
- Merge one node at a time, bound to its verified head. Gates are current for that head and its current base; earlier green from another head or base is never reused.
- After each landing, re-read the trunk tip, promote each open selected child onto it, push with an explicit expected-old lease, retarget, and renew the child's gates.
- Never use provider merge-time branch deletion, admin bypass, or automatic conflict resolution.
- Never touch an unselected node: its refs, PR, base and local branches stay as they are.

## Merge Method

Each selected node's decision names its method (`merge`, `squash` or `rebase`), one the repository allows. A requested method the repository disables is a stop, not a reason to pick another. The run never overrides the squash commit title or message, so a decision that needs stack trailers in trunk history under a `PR_BODY` or `BLANK` squash policy selects `merge` or `rebase` (`references/provenance.md` § Merge Mode Coupling). For a stack the skill created, verify `Stack-Id` and `Stack-Position` trailers before delegating. For an existing published stack, provenance is preserved as found (`references/provenance.md` § Existing Published Stacks).

## Landing Proof

Cleanup requires a complete landing proof:

| Landing | Proof |
| --- | --- |
| Merge commit or fast-forward | The branch head is an ancestor of the landing, and the landing is reachable from the trunk |
| Squash or rebase | A recorded or provider-verifiable landed head equal to the branch head, plus a landing reachable from the trunk; or independently verified complete inclusion of the branch's entire net change in the landing |

`git cherry`, whitespace-normalized patch IDs, and a quiet `git diff` against the trunk are not proof: a multi-commit branch squashed into one commit, a partial inclusion, or later trunk changes defeat them. A branch with any work added after the proved landing is retained.

## Retention

A parent head ref, local and remote, is retained while any of these holds:

- Any open PR uses it as head or base: selected or not, in the same repository or from a fork.
- An active, dirty or locked worktree holds it.
- The local or remote ref has work added after the landing.

Retention is not a failure of the node: it is reported with the dependent PRs or the holding worktree and the exact remaining action.

## Provider Auto-Delete And Auto-Retarget

A repository setting can delete a merged head branch and retarget its open children to the trunk on its own. That retarget does not promote the child: its head still sits on the old parent head. Facts are checked after every landing and neither outcome is assumed. An already-retargeted child or an already-deleted parent head is reconciled as the observed state; the fork point recorded before the merge keeps the child's slice provable.

Deleting a branch that an open PR uses as its base is unsafe whatever the provider then does: depending on provider and repository settings, the child PR may be closed unmerged or retargeted with a diff that now includes landed parent commits. Neither is acceptable without promotion.

## Endpoints

| Endpoint | Finishes when |
| --- | --- |
| `pr` | Observation only: the packet is checked against provider facts; nothing is captured, promoted, retargeted, merged or deleted |
| `merged` | Every selected node is landed and its post-merge checks passed. No feature branch is deleted |
| `clean` | `merged`, plus proof-based cleanup of each selected node's stale branches and worktrees after its children were retargeted or landed |

A node that merged but failed a post-merge check, or whose required cleanup is incomplete, is merged-but-incomplete (`BLOCKED` with the confirmed merge preserved), never complete. Resuming continues from the confirmed merge in the same run without another merge. A parent whose only cleanup obstruction is an open child base resumes cleanup after that child is retargeted or landed.

An unselected sibling or child that stays open keeps the parent branch retained. Under `clean` that makes the run `BLOCKED` with the exact dependent PRs, not `COMPLETE`; under `merged` the branch is simply not deleted.

A cleanup-only request selects only nodes the provider already reports merged; the run then verifies their landings and cleans up without landing anything. Deleting an unmerged branch is never part of the run and requires the user explicitly asking after reviewing the risk.

## Recovery: Deleted Parent Branch Closed A Child PR

Use this path only for the specific provider failure where a child PR was closed unmerged because its base branch disappeared. It recreates the same manual PR; it never converts the stack to a native one or changes repository settings.

1. Confirm the closed child PR has `mergedAt: null`.
2. Confirm the deleted branch was the closed PR's `baseRefName`.
3. Confirm the child `headRefName` still exists on `origin`.
4. Confirm the child head commit is still the intended stack slice.
5. If its parent landed, restack the child onto the trunk tip with the standalone procedure in `references/sync-algorithm.md`, recording `F` from the old parent head.
6. Recreate the PR against `<base>` or the current merged parent.
7. Continue by delegating the remaining landing with a fresh stack decision packet; its gates wait for the recreated PR's checks.

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
- The node is a native stack member (`references/stack-model.md` § Native Stack Detection): the manual path stops, and the stack is landed only through the guarded prefix request in `references/github-native.md` § Landing policy.
- In a stack the skill created, a commit is missing `Stack-Id` or has a `Stack-Id` that differs from `.stack-prs.yaml`.
- Provider reports branch protection failure.
- A branch fails its landing proof.
- A closed unmerged child PR cannot be traced to deleted-base recovery.

The delegated run reports the stopped node and the next safe action.
