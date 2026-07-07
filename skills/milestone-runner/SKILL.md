---
name: milestone-runner
description: 'Run milestone `/goal` blocks from `.docs/EXECUTION_PROMPTS.md` in dependency order, sequentially or in parallel when milestones are independent. Use when asked "run these milestone prompts", "execute EXECUTION_PROMPTS.md", "run the milestones sequentially", "run independent milestones in parallel", "orchestrate plan-prompts output", "continue the milestone sequence", "merge the stack", or "ensure CI is green and clean branches". NOT for generating plan files; use plan-prompts. NOT for repairing one existing stack; use stacked-prs.'
metadata:
  version: 1.0.0
  category: development
  tags: [milestones, orchestration, stacked-prs, ci, execution-prompts]
  difficulty: advanced
  phase: ship
  complements:
    - plan-prompts
    - stacked-prs
    - ship-workflow
---

# Milestone Runner

Run milestone prompts produced by `plan-prompts` from `.docs/EXECUTION_PROMPTS.md`. The skill coordinates execution order, isolation, verification, CI checks, review gates, and optional stack merge/cleanup.

This skill executes existing milestone prompts. It does not generate `DEVELOPMENT_PLAN.md` or `EXECUTION_PROMPTS.md`; use `plan-prompts` for that. It does not replace `stacked-prs`; it invokes that workflow when a stack must be validated, merged, retargeted, or cleaned.

## Core model

Milestone prompts are designed to stop at "PR stack open, checks green, reviewed, ready for human review." That is intentional. A milestone process exiting successfully or reporting `DONE` is not proof that the milestone is safe to advance from. Advance only when external state proves it.

| Evidence | Use |
| --- | --- |
| `.docs/DEVELOPMENT_PLAN.md` dependency rows | Build the milestone DAG. |
| `.docs/EXECUTION_PROMPTS.md` `/goal` blocks | Exact executable prompt text. |
| Git branch/worktree state | Ensure isolated runs do not share an index or branch. |
| Provider PR metadata | Confirm PRs exist and are based correctly. |
| CI/check provider state | Confirm each PR is green before merge or handoff. |
| Milestone verification commands | Confirm behavior after the stack is built and again after merge when continuing. |

## Modes

| Mode | Trigger | Behavior |
| --- | --- | --- |
| Sequential build | "run milestones", "run them one after another" | Run the next ready milestone, verify its stack, then stop for review/merge unless the user explicitly asked to continue after observed merge. |
| Parallel build | "run independent milestones in parallel" | Run a wave of dependency-ready milestones concurrently, one isolated worktree/session per milestone. Halt the wave on any failure. |
| Resume | "continue the milestone sequence" | Read prior state, observe which milestone stacks are merged, then launch the next dependency-ready milestone or wave. |
| Merge and clean | "merge the stack", "ensure CI is green", "clean branches" | Use stacked-PR merge discipline: verify order and CI, merge root-to-leaf, retarget children, clean merged local and remote branches. |

Default to sequential build when the user does not explicitly request parallel execution. Default to human-review stop points; do not merge unless the user explicitly requests merge/cleanup.

## Workflow

### 1. Inspect inputs

1. Read `.docs/EXECUTION_PROMPTS.md` and extract each milestone heading plus the fenced `/goal` block that follows it.
2. Read `.docs/DEVELOPMENT_PLAN.md` when present and extract `Depends on` rows. Use these dependencies to build the DAG.
3. If the plan is missing or dependency rows are ambiguous, fall back to file order and treat milestones as sequential unless the prompt text explicitly says they are independent.
4. Confirm the worktree is clean before launching, merging, rebasing, or cleanup. Stop on dirty state unless the user only asked for inspection.
5. Confirm the current branch/base context. Do not run milestone work on an unrelated dirty branch.

### 2. Build the execution DAG

Create a table before launching work:

| Milestone | Depends on | Status | Runnable now | Execution lane |
| --- | --- | --- | --- | --- |
| M1 | none | pending | yes | wave-1 |
| M2 | M1 | blocked | no | wave-2 |

Rules:

- A milestone with unmerged dependencies is blocked.
- Milestones with no dependencies between them can share a wave.
- Parallel wave members must run in separate git worktrees and separate headless sessions.
- If two independent milestones touch the same files, prefer sequential execution unless the user accepts conflict risk.

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
| PR existence | Expected PR stack exists. |
| PR bases | Root PR targets the intended base; child PRs target the previous PR branch. |
| Checks | CI/checks are green or pending state is explicitly reported and treated as not done. |
| Verification | Milestone `VERIFICATION` commands pass with expected output. |
| Review | Generated prompt's per-PR and whole-stack review criteria are complete. |
| Cleanliness | No accidental dirty files remain in the worktree. |

If any gate fails, stop the sequence. Report the failure, the last safe state, and the next required human/agent action. Do not launch downstream milestones on a broken base.

### 5. Merge and continue

Only merge when the user explicitly asks. Use the `stacked-prs` skill for stack topology and merge discipline.

Safe merge loop:

1. Verify PR order, branch bases, and CI/check state.
2. Merge root PR first.
3. Fetch and update local state.
4. Rebase or retarget the child PR onto the new base according to the stack workflow.
5. Re-run checks before merging the next PR.
6. After the final PR merges, clean merged local and remote branches.
7. Re-run the milestone verification commands on the merged base before launching dependent milestones.

If the user wants to preserve the human review gate, stop after reporting the stack as ready and wait for observed merge before continuing.

## Output Format

For inspection or launch planning, output:

```text
## Milestone Runner Plan

| Milestone | Depends on | Mode | Worktree/Profile | Status |
| --- | --- | --- | --- | --- |

## Launches
- M1: <command/session/worktree summary>

## Gates
- PR bases: <pass/fail/pending>
- CI: <pass/fail/pending>
- Verification: <pass/fail/pending>
- Review: <pass/fail/pending>

## Stop/Continue Decision
<Continue to next ready milestone | Stop for human review | Stop on failure | Merge requested and complete>
```

For merge-and-clean requests, output:

```text
## Merge Result

| PR | Branch | Base | CI before merge | Merge result | Cleanup |
| --- | --- | --- | --- | --- | --- |

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
| Dirty worktree | Stop before launching, merging, rebasing, or cleanup. |
| Parallel run file overlap | Prefer sequential execution; parallel only with explicit approval. |
| Headless command unavailable | Fall back to manual copy/paste execution guidance and preserve the same gates. |
| A milestone fails | Stop all downstream work, report failed gate, leave worktrees/branches intact for debugging. |
| CI pending | Treat as not complete; wait or stop with pending status. |
| Merge conflict | Stop and invoke stack conflict resolution; do not continue to downstream milestones. |
| User asks to merge without green checks | Refuse the merge and report failing checks. |

## Safety checklist

Before yielding:

- Every launched milestone has an observed state: pending, running, ready for review, merged, or failed.
- No downstream milestone launched before its dependencies were externally observed as merged.
- Parallel milestones used isolated worktrees/sessions.
- Merge happened only after explicit user request.
- CI and verification evidence is reported exactly, not inferred from agent self-report.
- Local/remote cleanup only removed branches verified as merged.
