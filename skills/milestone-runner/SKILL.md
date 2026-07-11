---
name: milestone-runner
description: 'Run milestone `/goal` blocks from `.docs/EXECUTION_PROMPTS.md` in dependency order, sequentially or in parallel when milestones are independent. Use when asked "run these milestone prompts", "execute EXECUTION_PROMPTS.md", "run the milestones sequentially", "run independent milestones in parallel", "orchestrate plan-prompts output", "continue the milestone sequence", "merge the stack", or "ensure CI is green and clean branches". NOT for generating plan files; use plan-prompts. NOT for repairing one existing stack; use stacked-prs.'
metadata:
  version: 1.1.0
  category: development
  tags: [milestones, orchestration, stacked-prs, ci, release-management, execution-prompts]
  difficulty: advanced
  phase: ship
  complements:
    - plan-prompts
    - stacked-prs
    - ship-workflow
---

# Milestone Runner

Run milestone prompts produced by `plan-prompts` from `.docs/EXECUTION_PROMPTS.md`. The skill coordinates execution order, isolation, verification, CI checks, review gates, stack merge/cleanup, and release preparation.

This skill executes existing milestone prompts. It does not generate `DEVELOPMENT_PLAN.md` or `EXECUTION_PROMPTS.md`; use `plan-prompts` for that. It does not replace `stacked-prs`; it invokes that workflow when a stack must be validated, merged, retargeted, or cleaned. It invokes `ship-workflow` only after a complete shared release train requires release preparation.

## Core model

Milestone prompts end with a structured, release-aware `GO`/`NO-GO` merge verdict. A milestone process exiting successfully or reporting `DONE` is not proof that the milestone is safe to advance from. Advance only when the milestone reports `GO` and external state proves every gate. A stack-level `GO` does not complete its release train: release preparation begins only after every milestone assigned to that train is externally merged.

| Evidence | Use |
| --- | --- |
| `.docs/DEVELOPMENT_PLAN.md` dependency rows and release-train table | Build the milestone DAG and determine release-train completion. |
| `.docs/EXECUTION_PROMPTS.md` `/goal` blocks and `RELEASE TRAIN` fields | Extract exact executable prompt text, target release, required artifacts, release verification, and publication requirement. |
| Git branch/worktree state | Ensure isolated runs do not share an index or branch. |
| Provider PR metadata | Confirm PRs exist and are based correctly. |
| CI/check provider state | Confirm each PR is green before merge or handoff. |
| Milestone `GO`/`NO-GO` verdict | Confirm the implementation session reached an explicit merge-readiness decision and reports the correct release target. |
| Milestone verification commands | Confirm behavior after the stack is built and again after merge when continuing. |
| Version source, `CHANGELOG.md`, release workflow, and release-preparation PR | Prepare and verify the declared release exactly once after its train completes. |

## Modes

| Mode | Trigger | Behavior |
| --- | --- | --- |
| Sequential build | "run milestones", "run them one after another" | Run the next ready milestone, verify its stack, merge automatically after `GO` plus external gates, clean merged branches, prepare a completed release train when required, then continue to the next dependency-ready milestone. |
| Parallel build | "run independent milestones in parallel" | Run a wave of dependency-ready milestones concurrently, one isolated worktree/session per milestone. Halt the wave on any `NO-GO` or failed external gate. Merge only stacks whose lane reports `GO` and whose external gates pass; prepare a release only after all of its train members merge. |
| Resume | "continue the milestone sequence" | Read prior state, observe which milestone stacks and release-preparation PRs are merged, then launch the next dependency-ready milestone, release preparation, or wave. |
| Merge and clean | "merge the stack", "ensure CI is green", "clean branches" | Treat the request as an explicit `GO` candidate for the current stack, then use stacked-PR discipline: verify order and CI, merge root-to-leaf, retarget children, clean merged local and remote branches, and evaluate whether the train is ready for release preparation. |

Default to sequential build when the user does not explicitly request parallel execution. Default to autonomous merge-and-continue after a milestone reports `GO` and all external gates pass. Stop instead when the user explicitly requests human-review stop points, the milestone reports `NO-GO`, a required gate fails or is pending, a release target is unresolved, a required release-preparation gate fails, or the milestone contains a `HUMAN REVIEW GATE`.

## Workflow

### 1. Inspect inputs

1. Read `.docs/EXECUTION_PROMPTS.md` and extract each milestone heading plus the fenced `/goal` block that follows it.
2. Read `.docs/DEVELOPMENT_PLAN.md` when present and extract `Depends on` rows and the release-train table. Use dependencies to build the DAG and release-train memberships to determine when preparation may start.
3. For every milestone, reconcile its `RELEASE TRAIN` field with the plan. Record target release, included milestones, preparation trigger, required artifacts, release verification, and publication requirement. Stop on contradictions or unresolved `> GAP:` values.
4. If the plan is missing or dependency rows are ambiguous, fall back to file order and treat milestones as sequential unless the prompt text explicitly says they are independent. Do not infer a release target or version.
5. Confirm the worktree is clean before launching, merging, rebasing, cleanup, or release preparation. Stop on dirty state unless the user only asked for inspection.
6. Confirm the current branch/base context. Do not run milestone work on an unrelated dirty branch.

### 2. Build the execution DAG

Create a table before launching work:

| Milestone | Depends on | Target release | Status | Runnable now | Execution lane |
| --- | --- | --- | --- | --- | --- |
| M1 | none | v2.4.0 | pending | yes | wave-1 |
| M2 | M1 | v2.4.0 | blocked | no | wave-2 |

Rules:

- A milestone with unmerged dependencies is blocked.
- Milestones with no dependencies between them can share a wave.
- Parallel wave members must run in separate git worktrees and separate headless sessions.
- If two independent milestones touch the same files, prefer sequential execution unless the user accepts conflict risk.
- A release train becomes eligible for preparation only when every included milestone is externally observed as merged. A train with target `none` has no release-preparation work.

### 3. Launch milestone work

Use a fresh top-level session per milestone. Do not use same-context subagents for milestone implementation; shared context and a shared checkout can hide ordering bugs.

Preferred headless shape for omp environments:

```bash
omp -p --profile <run-name> --auto-approve --mode json --max-time <seconds> "<milestone /goal block>"
```

Isolation rules:

1. Sequential mode can use the main checkout when the tree is clean.
2. Parallel mode must create one worktree per milestone from the correct base.
3. Name worktrees and temporary run branches with milestone IDs and a short slug; avoid branch names that imply chronology beyond the dependency DAG.
4. Capture each run's final output, PR URLs, branch names, and verification output.

### 4. Verify before advancing

Treat runner output as a hint. Verify with external state:

| Gate | Requirement |
| --- | --- |
| Stack verdict | Milestone final output contains `GO — RELEASE: <target>` with evidence; `NO-GO`, missing verdict, ambiguous verdict, or target mismatch stops the sequence. |
| PR existence | Expected PR stack exists. |
| PR bases | Root PR targets the intended base; child PRs target the previous PR branch. |
| Checks | CI/checks are green or pending state is explicitly reported and treated as not done. |
| Verification | Milestone `VERIFICATION` commands pass with expected output. |
| Review | Generated prompt's per-PR and whole-stack review criteria are complete. |
| Cleanliness | No accidental dirty files remain in the worktree. |
| Release target | The target agrees between plan, prompt, and verdict; it is neither unresolved nor invented. |
| Release readiness | Before train completion, release preparation remains pending and no version or changelog update starts. After completion, every train member is externally merged. |
| Release preparation | Applies only after train completion when artifacts are required: version source and/or `CHANGELOG.md` changes are present, reviewed, green, merged, and pass the train's release verification. |

If any gate fails, stop the sequence. Report the failure, the last safe state, and the next required human/agent action. Do not launch downstream milestones on a broken base.

### 5. Merge, prepare release, and continue

After a milestone reports `GO` and every external gate passes, merge the stack automatically unless the user explicitly requested no merge or the milestone contains a `HUMAN REVIEW GATE`. Use the `stacked-prs` skill for stack topology and merge discipline.

Safe merge loop:

1. Verify PR order, branch bases, and CI/check state.
2. Merge root PR first.
3. Fetch and update local state.
4. Rebase or retarget the child PR onto the new base according to the stack workflow.
5. Re-run checks before merging the next PR.
6. After the final PR merges, clean merged local and remote branches.
7. Re-run the milestone verification commands on the merged base.
8. Recompute the release train from external merge state. If another included milestone remains unmerged, report `Continue within release train` and launch only dependency-ready work.
9. If the completed train's target is `none` or its required artifacts are `none`, record `RELEASE PREP: not-required`; do not invoke `ship-workflow`.
10. If the completed train requires release preparation, launch a fresh isolated release-preparation session from the clean merged base. Invoke `ship-workflow` on a dedicated release-preparation branch and preserve its pre-flight, test, review, version-bump, changelog, atomic-commit, PR, and CI gates.
11. Detect the version source and changelog from the plan and repository rather than assuming either exists. Update the version to the declared target only when the train requires a version update; update `CHANGELOG.md` only when the train requires it. Do not tag, publish, or create a hosted release unless the train explicitly requires that action.
12. Verify the release-preparation PR is reviewed, green, and merged; then run the train's release verification on the merged base. Report `RELEASE PREP: ready` only after the required artifacts and verification pass.

If the user wants to preserve the human review gate, stop after reporting the stack or release-preparation PR as ready and wait for observed merge before continuing. If the milestone or release preparation reports `NO-GO`, do not merge or advance; report the failed or pending gates.

## Output Format

For inspection or launch planning, output:

```text
## Milestone Runner Plan

| Milestone | Depends on | Target release | Mode | Worktree/Profile | Status |
| --- | --- | --- | --- | --- | --- |

## Launches
- M1: <command/session/worktree summary>

## Gates
- Stack verdict: <GO/NO-GO/missing>
- PR bases: <pass/fail/pending>
- CI: <pass/fail/pending>
- Verification: <pass/fail/pending>
- Review: <pass/fail/pending>
- Release train: <target, included/merged milestones, pending members>
- Release preparation: <not-required/pending/ready/NO-GO>

## Stop/Continue Decision
<Continue within release train | Prepare release | RELEASE PREP: ready and continue | Stop for human review | Stop on NO-GO | Stop on failed gate>
```

For merge-and-clean requests, output:

```text
## Merge Result

| PR | Branch | Base | CI before merge | Merge result | Cleanup |
| --- | --- | --- | --- | --- | --- |

## Release Train
- Target:
- Included milestones:
- Externally merged milestones:
- Required artifacts:
- Release-preparation PR:
- Version transition:
- CHANGELOG.md status:
- Publication status:
- Verification after release preparation:

## Remaining State
- Open PRs:
- Local branches:
- Remote branches:
- Verification after merge:
```

## Error handling

| Problem | Resolution |
| --- | --- |
| Missing `.docs/EXECUTION_PROMPTS.md` | Stop; ask for the prompt file or run `plan-prompts` first. |
| Ambiguous dependency graph | Use sequential execution unless the user explicitly authorizes parallel conflict risk. |
| Dirty worktree | Stop before launching, merging, rebasing, cleanup, or release preparation. |
| Parallel run file overlap | Prefer sequential execution; parallel only with explicit approval. |
| Headless command unavailable | Fall back to manual copy/paste execution guidance and preserve the same gates. |
| A milestone fails | Stop all downstream work, report failed gate, leave worktrees/branches intact for debugging. |
| CI pending | Treat as not complete; wait or stop with pending status. |
| Merge conflict | Stop and invoke stack conflict resolution; do not continue to downstream milestones. |
| Missing or `NO-GO` verdict | Refuse the merge and report the failed, pending, or ambiguous gates. |
| Release target is missing, contradictory, or unresolved | Stop the affected release train. Do not infer a semantic version or create a version/changelog update. |
| Release train is incomplete | Continue only with its remaining dependency-ready milestones. Do not start release preparation. |
| Required release preparation fails or is pending | Stop the affected train and only milestones whose declared dependency closure includes it. Independent trains may continue in isolated lanes. Leave the release-preparation branch and PR intact for remediation. |

## Safety checklist

Before yielding:

- Every launched milestone has an observed state: pending, running, `GO`, `NO-GO`, merged, or failed.
- No downstream milestone launched before its dependencies were externally observed as merged.
- Parallel milestones used isolated worktrees/sessions.
- Merge happened only after a `GO` verdict and green external gates, or after an explicit merge-and-clean request whose gates passed.
- Every completed release train has an observed `RELEASE PREP` state: `not-required`, `pending`, `ready`, or `NO-GO`; no version/changelog preparation began before all train milestones merged.
- Required version and changelog changes match the declared release target, are merged through a reviewed green release-preparation PR, and pass release verification.
- CI and verification evidence is reported exactly, not inferred from agent self-report.
- Local/remote cleanup only removed branches verified as merged.
