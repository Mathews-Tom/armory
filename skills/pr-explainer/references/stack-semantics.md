# Stack semantics for explanation

Read before choosing comparisons for a whole stack, one selected member, or a standalone PR whose verified base is another PR. This reference supplies attribution rules, not shipping authority. The common source/evidence/output rules remain in SKILL.md.

## 1. Resolve membership without widening the request

| Selection | Requested members |
|---|---|
| Explicit PR list/parents | Exactly that selection; unselected prerequisites are labeled context |
| Verified native stack identity | All registered members, including merged and closed-unmerged entries, with state preserved |
| Manual stack from a seed | Connected family of verified PR-parent edges: ancestors to the earliest proved PR root, then its descendants/sibling trajectories |
| One member / single PR based on another PR | That PR only; inherited behavior supplies necessary context |

Sharing trunk does not connect unrelated PRs. A branch name, title, PR-body link, stack trailer or local `.stack-prs.yaml` is a relationship lead, not proof of current topology or source inclusion. Explicit selection defines the requested scope but cannot override contradictory provider/source facts.

For every requested PR record: base/head repository and ref/OID; provider state; parent and proof; proved fork/comparison boundary; landing identity if relevant; source availability; membership certainty. Deduplicate provider/repository/number identities, not branch names. Keep disagreements and unresolved nodes visible. A topological presentation order is not proof that the graph is a linear chain.

Use the initial provider response already collected. Where supported, a pull response's `stack` object identifies native membership; read its complete ordered membership using the observed stack identity:

```bash
gh api --method GET repos/OWNER/REPO/pulls/NUMBER
gh api --method GET repos/OWNER/REPO/stacks/STACK_NUMBER
```

Do not repeat the pull read just to recover a field already in the frozen response. Discover the actual provider surface; an unsupported endpoint, forbidden read or missing field means unknown membership, not a negative result. An explicit null is distinct from unavailable metadata. Do not use current-branch-only `gh stack view` to discover an arbitrary PR, and never link/unstack/repair native state.

For manual families, use provider base/head repository identities, explicit selections and exact source/history evidence. Historical membership after retargeting can require provider base-change history/timeline or earlier immutable base/fork observations with verifiable landing identities. A current base name alone cannot recover the original parent. If closure or historical members cannot be established, report the discovered family and missing relationship evidence as partial; do not silently present only today's open PRs as the complete stack.

**Exit:** all requested members have verified relationships or explicit unresolved entries; no mutation or imaginary lineage was used to make the graph convenient.

## 2. Keep three comparisons separate

| Comparison | Establishes | Does not establish |
|---|---|---|
| Published review delta | What the provider currently presents for review between the proved comparison baseline and frozen head | Historical ownership after squash/retargeting, or future integrated behavior |
| Incremental owned contribution | That member's source changes relative to its proved parent/fork boundary | That every ancestor's newest changes are present, or that the contribution remains active later |
| Final represented behavior | Functional state at a real verified leaf/integration revision relative to the selected root baseline | Deployed availability or sibling integration absent from that revision |

For a child, prove the exact fork/parent boundary rather than comparing it with trunk. Inspect whether the frozen parent's head is represented in the child. A parent that advanced or was force-pushed after the fork can make the hosted review diff include old-parent work, while the child's own incremental slice is different. Report both concepts when necessary. If ownership cannot be proved, source-backed snapshot behavior can still be explained, but attribution remains unresolved.

Source dependency is not a prediction about landing order. A child head can already contain its parent's code even when the parent PR has not separately merged. Describe the observed inheritance and imports; do not claim “landing/reviewing the child without the parent breaks the import” by imagining a child-only patch on another base. Only an inspected actual revision can establish that missing-code outcome.

Use raw object/history reads. An ancestry relationship supports inclusion, but a green check, matching commit subject, patch ID, `git cherry` result or a quiet net diff does not independently prove historical complete inclusion after rewritten history. Reuse observed OIDs; branch names can move while the briefing is being prepared.

## 3. Linear stack: explain the outcome, then its construction

1. Freeze the pre-stack root baseline and every member's head and comparison/fork boundary.
2. Prove that the selected contributions are represented at the final leaf. Exact ancestry is useful for an unrevised chain; rewritten/landed contributions need independently verifiable historical/landing evidence.
3. Trace final behavior through the actual leaf source. Group by affected capability, not PR count.
4. Attribute each member's own contribution. Explain why later members depend on it and when its behavior becomes reachable/usable.
5. Reconcile the contribution map with the final outcome. A later change can replace, cancel, rename or gate an earlier contribution.

A stale descendant that omits a newer ancestor contribution is not a coherent integrated final stack. Explain the verified snapshots separately and name the mismatch. Do not mentally merge branches, concatenate patches, restack them or choose an expected end state. Summed line counts are not functionality.

If a later PR removes an earlier feature, the earlier row retains its historical contribution, while the final briefing says the capability is absent or restored to its earlier behavior. Fully canceled behavior is no net behavior change, not two new final capabilities. Internal structure may still have changed; explain it from source rather than forcing a product feature.

## 4. Siblings: there may be no single “after”

Preserve parent edges. A common foundation plus two sibling leaves is not one tree containing both leaves.

Lead with shared-root behavior and separate per-leaf changes. Trace each materially affected capability on the leaf where it actually exists. State that cross-sibling interaction/integration is unverified unless a real integration revision represents both. Independent green checks do not establish that combined state. If an integration revision is supplied, inspect/prove its source inclusion before using it as the combined “after.”

Shared filenames, nearby edits and overlapping context are not proof that changed lines overlap or that a merge conflicts. Attribute each leaf's actual edits from its frozen comparison. Claim same-line changes only when those changed lines are observed; otherwise leave integration unverified rather than inventing a conflict.

Do not create a synthetic merge or imply a linear dependency from presentation order. Unknown multi-parent relationships remain unresolved rather than being forced into the one-parent stack model.

## 5. Landed and retargeted members

Keep open, merged and closed-unmerged states distinct. Provider auto-retargeting/deletion and squash/rebase landing can erase the branch relationship while leaving old commits in a child's ancestry. A current child base of trunk does not mean the parent contribution vanished, nor does it prove clean incremental attribution.

Maintain two labeled views when evidence supports them:

- **Historical selected-stack change:** proved pre-stack baseline → final represented state across the requested members.
- **Remaining proposed change:** verified current baseline → the still-proposed contribution, with landed prerequisite behavior treated as inherited context.

Never substitute a later trunk tip for a missing pre-stack baseline. Recover boundaries using exact source/history plus provider-verifiable original/landed identities. A merge's first parent → landing shows its integration delta. A provider-identified single-parent landing for a one-commit PR has a readable parent → landing delta without establishing its landing method. One-commit squash and rebase can be observationally indistinguishable; commit subjects, matching blobs and patch similarity do not prove the method. Preserve an available exact delta while reporting the method unknown.

For a proved squash landing inspect parent → landing; for a multi-commit rebased landing prove the complete pre-first → post-last interval. Keep integration/conflict-resolution differences separate from the originally published head.

Source similarity alone does not recover a missing rebase boundary. If a historical or landed view is unavailable, say which boundary is missing and what cannot be attributed. Preserve every requested member in the map rather than silently dropping the hard portion. A closed-unmerged member can be historical context or an explicitly selected unlanded contribution, never merged by implication. Its closed state does not mean its capability is absent at its own head or was never active elsewhere.

Merged is not deployed. Distinguish source reachability, inherited/remaining work and configuration gates; deployment remains not assessed unless separately evidenced by supplied provenance.

## 6. Contribution and activation map

For each requested member, include the following in the briefing or supporting detail:

| Field | Developer consequence |
|---|---|
| PR identity and observed state | Which published or historical work is being explained |
| Parent / fork boundary and certainty | What prerequisite state its contribution is measured against |
| Incremental responsibility | What this PR actually adds/changes, excluding inherited behavior |
| Activation point | Independently usable, foundation only, completed by a later member, flag/config gated, or removed/superseded |
| Functional/source connection | Entrypoint → changed rule → state/output, with revision-bound source evidence |
| Unknowns | Missing objects, incomplete membership, ambiguous ownership or unverified integration |

Infer activation from entrypoint reachability, loaders/configuration, callers and state transitions, not position or naming. A new helper with no caller is groundwork even if tests exercise it directly. A later entrypoint/configuration change can activate it. Describe the condition without asserting production availability.

**Completion:** the combined functional account matches real represented source; every selected PR's contribution and activation is attributed or explicitly unresolved; supersession, partial landing and sibling uncertainty are visible; inherited work is not double-counted; freshness is checked once under the main workflow. This is an explanation, not a merge-readiness or correctness verdict.
