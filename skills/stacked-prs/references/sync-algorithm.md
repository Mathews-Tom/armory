# Sync Algorithm

Sync moves each child's own commits onto its parent's new tip (the trunk tip once the parent has landed), proves the result, publishes it with an explicit expected-old lease, and retargets the PR. A plain `git rebase` followed by a bare `--force-with-lease` is not this algorithm: it proves nothing about what the rewritten child contains and leases against whatever the last fetch happened to see.

## Executable Owner

The installed `ship-workflow` skill's `scripts/ship.py --stack-plan PATH` is the one execution owner of graph continuation once a parent has landed (packet: `references/stack-model.md` § Explicit Stack Decision Packet). At landing endpoints it promotes each selected child after its parent landed, with Git plumbing only, pushes it under an expected-old lease, retargets it to the trunk and renews its gates, enforcing this reference's clean promotion proof. For separately authorized source-only work, its manual-graph `--until renewed` endpoint instead renews open parents and children without landing; independently reviewed conflicts and historical external landings use the registered lifecycle reference's **Source-only renewal** contract. Post-landing renewal, promotion and retargeting are never hand-run. Behavior is fixture-tested against local Git repositories and a stateful provider fixture, not every provider configuration.

The hand-run recipe below is the standalone restack of an open stack before anything lands: a parent branch was rewritten or the trunk moved, and the children must follow it with the same proof. It never retargets a PR and never deletes a branch.

## Preflight

```bash
git rev-parse --show-toplevel
git status --porcelain
git fetch origin
gh pr list --state open --json number,title,headRefName,headRefOid,baseRefName,state,url
```

Stop if the parent graph is ambiguous or contradicts the packet. A dirty checkout is not rewritten and not stashed; the rewrite happens outside it. The executable still refuses to push or retarget while the invoking checkout has local changes (`NEEDS_JUDGMENT`) or a conflict or Git operation in progress (`BLOCKED`). `git fetch --prune` is not part of preflight: a pruned remote-tracking ref can erase the only local name of an old parent head.

## Promotion Identities

Record these before the parent is rewritten or its merge is dispatched, for every open child of that parent that will be promoted (in the executable, every open selected child; an unselected child is never promoted and keeps the parent branch retained):

| Identity | Meaning |
| --- | --- |
| `C` | The child's exact old head OID |
| `F` | The fork point: the old parent head the child's own commits sit on. Must be an ancestor of `C`; an explicit `fork` OID in the packet is an acceptable source-backed boundary |
| slice | `F..C`: the child's own commits, one linear chain with no merge commits |

After the parent lands, observe:

| Identity | Meaning |
| --- | --- |
| `L` | In the delegated run, the current trunk tip containing the parent's landing, re-read after every landing and never assumed from an earlier one. For a standalone restack, `L` is the rewritten parent's new head, or the current trunk tip for a root branch whose trunk moved, and the PR is not retargeted |

If `F` is not an ancestor of `C` or the boundary cannot be proven, stop before merging the parent: name the missing identity and sync or supply the explicit fork first. `F` must be available locally. Git fetches advertised refs, not arbitrary objects, and a deleted parent ref advertises nothing, so an `F` that is no current ref tip is available only when it is already local or arrives with the history of the fetched child head.

## Proof

The expected result tree is the clean three-way merge with base `F`, ours `L` and theirs `C`:

```bash
git merge-tree --write-tree --merge-base=<F> <L> <C>
```

Exit status `0` prints the expected tree OID. Exit status `1` is a conflict: stop and report it; never auto-resolve. `--write-tree` with `--merge-base` needs Git 2.40 or later.

The rewritten child head `N` is accepted only when all of these hold:

1. `N` has exactly the expected tree.
2. `L` is an ancestor of `N`.
3. `L..N` is one linear chain with exactly as many commits as `F..C`, in order, with the same author name, email and date and the same message bytes, so published trailers survive byte for byte.
4. No commit of the slice became empty on `L`; an emptied commit stops the promotion and is never dropped silently.
5. No commit of the squash-landed parent is reintroduced: the replay starts at `F`, so only the child's own commits are carried.

None of these is proof on its own: a plain rebase result, `git cherry`, patch IDs, or equality of the old and new net delta. Legitimate unrelated trunk changes, including changes to files the child also touches, alter the literal delta; the three-way expected tree accounts for them.

The rewrite gets a new committer identity and timestamp. The executable replays with plumbing and never signs: it refuses the promotion, with nothing rewritten, when the effective `commit.gpgSign` is set or a slice commit is signed, and never disables signing. Whether the provider requires signed commits is not observable there; a remote that refuses the push while still holding `C` leaves the run `BLOCKED`. A hand-run replay re-signs only under the operator's own signing configuration; original signatures never carry over.

The delegated controller freezes the proposed commit objects and reuses their exact IDs after a definite refusal when `F`, `C` and `L` remain unchanged; it re-proves their tree and unchanged provenance instead of recreating timestamps. Requested `--gates` run before push in isolated clean checkouts with independent deadlines; `per_commit: true` validates every replay commit. Hooks are preserved, not replaced by validation. Unknown push outcomes reconcile first. The standalone recipe below does not provide saved proposal/validation authority; use the delegated controller for post-landing shipping.

## Hand-Run Recipe

Replay in a detached scratch worktree so no existing checkout, index or branch moves:

```bash
git rev-list --merges <F>..<C>
git merge-base --is-ancestor <F> <C>
git merge-tree --write-tree --merge-base=<F> <L> <C>
git worktree add --detach <scratch-dir> <L>
git -C <scratch-dir> cherry-pick <F>..<C>
git -C <scratch-dir> rev-parse HEAD
```

The first command must print nothing and the second must succeed. Stop if `merge-tree` reports a conflict or `cherry-pick` stops on a conflict or an empty commit (`git -C <scratch-dir> cherry-pick --abort`). With `N` the printed head, verify before publishing:

```bash
git rev-parse "<N>^{tree}"
git merge-base --is-ancestor <L> <N>
git rev-list --merges <L>..<N>
git rev-list --count <F>..<C>
git rev-list --count <L>..<N>
git log --reverse --format='%an%x00%ae%x00%ad%x00%B%x00' <F>..<C>
git log --reverse --format='%an%x00%ae%x00%ad%x00%B%x00' <L>..<N>
```

The tree must equal the `merge-tree` output, the ancestry check must succeed, `--merges` must print nothing, both counts must be equal, and both logs must be identical (a commit hook that edited a message fails this check). Then publish with an explicit expected-old lease and remove the scratch worktree:

```bash
git push --force-with-lease=refs/heads/<child-branch>:<C> origin <N>:refs/heads/<child-branch>
git ls-remote origin refs/heads/<child-branch>
git worktree remove <scratch-dir>
```

Never use a bare `--force-with-lease` (it leases against a possibly stale remote-tracking ref), never `--force`, and never push to the remote default branch.

## Retarget

The delegated run retargets a child to the trunk only after its parent landed and the promoted head's push is confirmed. The provider documents no atomic head/base guard for a base edit, so it reads the PR immediately before and after and treats any mismatch as a stop: before, `OPEN`, head `N`, base still the old parent branch; after, base the trunk and head still `N`. A new base changes the provider diff and test context: gates are renewed for the new head and base; earlier green is never carried over.

A repository can auto-delete a merged head branch and retarget its open children itself. When the child is already based on the trunk, or the parent head ref is already gone, the run reconciles that observed state instead of failing or re-sending the edit. The child head is still the old `C` in that case, so promotion is still required; the recorded `F` keeps the slice provable without the deleted ref.

## Unknown Outcomes

An interrupted or timed-out push or retarget is reconciled from current remote and provider facts, never resent blindly:

| Observed | Meaning | Action |
| --- | --- | --- |
| Remote head `N` / PR base `<trunk>` at head `N` | Applied | Record it and continue |
| Remote head `C` / PR base unchanged at head `N` | Not applied | Re-observe and re-prove, then dispatch once with a fresh lease |
| Anything else | Foreign change | Stop for judgment; name the observed identity |

## Local Branches

A local branch is advanced to `N` only when it points at exactly `C` and is not checked out in any worktree, with a compare-and-swap update:

```bash
git worktree list --porcelain
git update-ref refs/heads/<child-branch> <N> <C>
```

A local branch that is checked out, dirty, has extra local commits or otherwise diverges is never rewritten; it is reported as retained with the exact remaining action.

## Sync Order

Process parent-first. Re-read the trunk tip after each landing. Selected siblings of one parent are promoted independently, each from its own recorded `F` (the same parent head unless the packet gives an explicit `fork`) onto the trunk tip current at its promotion. A grandchild's fork point is the parent head its own commits sit on, which is the parent's head before the parent itself was promoted, not the parent's `F`. That boundary must be recorded before the parent is rewritten or supplied as an explicit `fork`; otherwise the grandchild stops for judgment. Promote it only after its parent lands.

## Conflict Handling

A conflict from `merge-tree` or during the replay stops the affected child and every node below it. Report the child branch, `F`, `C`, `L` and the conflicted paths. Do not continue to children. Do not auto-resolve conflicts.

## Lease Failure

A refused expected-old push must be classified by re-observing the remote. If it still holds the expected old OID, publication was refused without advancing that ref; preserve the exact frozen proposal and resolve the reported hook, transport or provider refusal before renewing validation. A different head needs fresh proof and a new exact-old decision. An unknown outcome remains pending until observation confirms the proposed head or establishes refusal; never resend blindly or replace the lease with plain `--force`.

## Validation After Sync

Run validation according to the target repository's detected gates and required provider checks for the new head and base. Do not substitute armory package-evaluation commands for another repository's local gate.

For armory package development only:

```bash
uv run python scripts/validate_evals.py
uv run python scripts/generate_manifest.py
uv run python scripts/evaluate_package.py --path skills/stacked-prs
```

Record validation results in the bodies of PRs the skill is creating when provider mutation is part of the requested workflow. Sync never edits the title or body of an existing published PR.
