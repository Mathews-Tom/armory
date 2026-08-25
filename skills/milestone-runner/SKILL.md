---
name: milestone-runner
description: 'Use when asked to "run milestones", "execute EXECUTION_PROMPTS.md", "continue the milestone sequence", "run independent milestones in parallel", "merge the stack", or "reconcile M5" after prior work changes the current design. Not for generating plan files; use plan-prompts. Not for repairing one stack; use stacked-prs.'
metadata:
  version: 1.4.0
  category: development
  tags: [milestones, orchestration, adaptive-planning, stacked-prs, ci, release-management, execution-prompts]
  difficulty: advanced
  phase: ship
  complements:
    - plan-prompts
    - stacked-prs
    - ship-workflow
---

# Milestone Runner

Run milestone prompts produced by `plan-prompts`. The runner coordinates mandatory design reconciliation, dependency-safe execution, verification, CI, review, merge/cleanup, and release preparation.

The runner executes existing prompts; it does not author a new product plan. It may require a docs-only reconciliation PR when the current plan no longer matches repository evidence. It invokes `stacked-prs` for stack topology and `ship-workflow` only after a complete release train requires preparation.

## Core model

A milestone has two independent gates:

1. **Design gate.** Before implementation, inspect the authoritative plan/prompt, current codebase, merged predecessor diffs, predecessor verification, CI, and local history. Require `DESIGN GO` or stop on `DESIGN NO-GO`.
2. **Merge gate.** After implementation, require release-aware `GO` plus external PR, CI, verification, and review evidence.

An ignored history ledger is reconstructible local evidence, not authoritative state. `.docs/DEVELOPMENT_PLAN.md` and `.docs/EXECUTION_PROMPTS.md`, merged PRs, CI, and current code remain authoritative.

Every terminal milestone result must print the literal heading `NEXT STEPS:` followed by concrete, ordered actions: the current milestone action, release-preparation state, and the next runnable milestone. A `NO-GO` must name remediation and either an independent milestone that can proceed or the reason no milestone can. A prose follow-up or JSON `next_steps` key is insufficient.


| Evidence | Use |
| --- | --- |
| Authoritative plan and prompts | Build the DAG, release trains, milestone contract, and design-gate scope. |
| Local history ledger | Carry prior gate decisions and verified outcomes; rebuild it when absent. |
| Current code plus merged predecessor diffs and PR evidence | Validate the plan’s assumptions, interfaces, dependencies, and acceptance. |
| CI/check state and verification commands | Confirm predecessor outcomes, reconciliation PRs, and implementation stacks. |
| Provider PR metadata | Confirm bases, reviewed reconciliation, stack topology, and merge state. |

## Capability-first proportionality

The runner exists to ship useful product behavior, not to maximize process.

- When an existing package has an observable defect and an established evaluator
  can verify a focused correction, prioritize that authorized product-code change
  over new benchmark, telemetry, dispatcher, or release-control infrastructure.
- Treat a new measurement or control-plane prerequisite as justified only when
  its output directly decides a concrete product change already in scope.
- An unresolved release target blocks release preparation, not an otherwise
  authorized product-code change, unless the plan explicitly makes release
  identity a runtime prerequisite.
- Scope a `DESIGN NO-GO` to the affected dependency closure. Continue an
  independent milestone lane only when it holds its own current `DESIGN GO` and
  shares no invalidated assumption.
- State the smallest observable next action. Do not substitute more gates,
  dashboards, or experimental machinery for a product improvement.

## Modes

| Mode | Trigger | Behavior |
| --- | --- | --- |
| Sequential build | "run milestones", "one after another" | Reconcile the next ready milestone, run it only after `DESIGN GO`, merge after external gates, then continue. |
| Parallel build | "run independent milestones in parallel" | Reconcile every candidate serially on the latest base; launch only the stable `DESIGN GO` wave in isolated worktrees. |
| Resume | "continue the milestone sequence" | Reconstruct state from authoritative artifacts and external evidence, then reconcile the next ready milestone or release train. |
| Merge and clean | "merge the stack", "ensure CI is green" | Verify design and merge gates, use stacked-PR discipline, clean verified merged branches, and evaluate release preparation. |

Default to sequential. Never launch code after `DESIGN NO-GO`, a failed or pending gate, an unresolved release target for release preparation or where the plan makes release identity a runtime prerequisite, or a required human gate.

## Workflow

### 1. Inspect inputs and local evidence

1. Read `.docs/DEVELOPMENT_PLAN.md`, `.docs/EXECUTION_PROMPTS.md`, and every `/goal` block. Extract dependencies, release-train fields, design-reevaluation rows, and exact verification commands.
2. Read `.docs/DEVELOPMENT_PLAN_HISTORY.md` when it exists. Verify it is ignored. Maintain this single ledger only in the canonical runner workspace.
3. When the ledger is absent, reconstruct the gate context from committed plan/prompt history, merged predecessor PRs and diffs, CI/check results, verification output, and current code. Create a local ledger header and append the reconstruction evidence; do not claim unavailable history.
4. Reconcile each prompt release-train field with the plan. Stop on contradictions or unresolved `> GAP:`.
5. Confirm a clean canonical workspace before reconciliation, launches, merges, rebases, cleanup, or release preparation. Stop on unrelated dirty state.

### 2. Build the provisional DAG

Before any launch, report:

| Milestone | Depends on | Target release | Design status | Implementation status | Runnable now | Lane |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | none | v2.4.0 | awaiting design | pending | no | design-1 |
| M2 | M1 | v2.4.0 | blocked | blocked | no | design-2 |

Rules:

- An unmerged dependency blocks both design and implementation.
- Release preparation begins only after every train member is externally merged.
- A `DESIGN GO` applies only to the exact authoritative plan/prompt revision that was inspected.
- A material reconciliation invalidates every provisional design result for affected milestones. Re-read the artifacts and rebuild the DAG before any implementation launch.

### 3. Reconcile milestone design

Run design gates serially in fresh top-level sessions from the canonical clean base. A design session must do only the prompt’s `PRE-IMPLEMENTATION DESIGN GATE`; it must not create product-code branches, write product code, or launch implementation PRs.

For each dependency-ready milestone:

1. Supply the current authoritative plan/prompt and local history context.
2. Inspect the milestone’s source-map rows, current code, merged predecessor diffs, predecessor PR outcomes, CI/check evidence, verification output, release fields, and every declared dependent milestone.
3. Require one exact outcome:
   - `DESIGN GO — PLAN REVISION: none`
   - `DESIGN GO — PLAN REVISION: <entry IDs>`
   - `DESIGN NO-GO — REASON: <blocking evidence>`
4. Append the evidence, decision, changed sections, downstream impact, and authorization to the canonical ignored ledger.
5. On `DESIGN NO-GO`, stop the affected dependency closure. Leave no product-code branch or PR.
6. On a material revision, require a docs-only reconciliation PR containing all affected plan/prompt updates and no product code. Require that PR to be reviewed, green, and externally merged. Then update the canonical base, reload both authoritative artifacts, rebuild the DAG/release trains/waves, and rerun invalidated design gates.
7. On `DESIGN GO — PLAN REVISION: none`, retain the result only until the next authoritative artifact revision or predecessor merge.

Do not run design gates concurrently. The ignored ledger has one canonical writer. A parallel implementation wave is eligible only after each member has a current `DESIGN GO`.

HARD STOP FOR SHARED DRIFT: A shared invalidated assumption blocks every affected implementation lane. A request to keep lanes running does not authorize scaffolding, partial code, or work on allegedly unaffected surfaces. Stop or leave those implementation sessions unlaunched; only the serialized canonical design-reconciliation session may continue. Never let an isolated worktree write the history ledger.

### 4. Launch implementation

Use a fresh top-level session per milestone. Provide the exact prompt plus the already-verified design evidence and authoritative artifact revision. The implementation session must confirm that revision before changing code; any newly discovered design mismatch returns to Step 3.

Preferred headless shape for omp:

```bash
omp -p --profile <run-name> --auto-approve --mode json --max-time <seconds> "<milestone /goal block>"
```

Rules:

1. Sequential mode may use the canonical checkout only when clean.
2. Parallel mode uses separate worktrees and sessions from the same reconciled base.
3. If independent milestones overlap files after reconciliation, run them sequentially unless the user explicitly accepts conflict risk.
4. Capture final verdicts, PR URLs, bases, verification output, review evidence, and material learnings.

### 5. Verify before merging

Treat runner output as a hint. Verify externally:

| Gate | Requirement |
| --- | --- |
| Design verdict | A current `DESIGN GO` matches the authoritative artifact revision used by the implementation. |
| Reconciliation | When revised, the docs-only PR is scope-clean, reviewed, green, and merged before code starts. |
| Stack verdict | Final output contains `GO — RELEASE: <target>` with evidence. Missing, ambiguous, or `NO-GO` stops. |
| PR topology | Root targets the intended base and children target the preceding branch. |
| Checks and verification | CI is green and every milestone command passes with expected output. Pending is not done. |
| Review | Per-PR and whole-stack criteria are complete. |
| Release target | Plan, prompt, and verdict agree; never invent a target. An unresolved target blocks release preparation and the merge verdict only when the plan makes release identity a runtime prerequisite. |
| Cleanliness | No accidental non-ignored worktree files remain. |

Any failed gate stops the affected dependency closure. Report the last safe state and required remediation; independent release trains may continue only in isolated lanes.

### 6. Merge, record outcomes, and prepare release

After all gates pass, merge with `stacked-prs` root-to-leaf. Recheck CI after each retarget or rebase. After the leaf merges:

1. Clean only verified merged branches.
2. Re-run milestone verification on the merged base.
3. Append verified material learnings and downstream milestones requiring renewed design review to the canonical local ledger.
4. Recompute the DAG and release train from external merge state. Treat all downstream design results as stale after a predecessor merge.
5. If the train is incomplete, continue only with dependency-ready design gates.
6. If target or required artifacts are `none`, record `RELEASE PREP: not-required`.
7. If required, run `ship-workflow` in an isolated release-preparation branch only after all train milestones merge. Update only source-traceable version/changelog artifacts; require reviewed green merged release-preparation PR and post-merge release verification. Do not tag, publish, or create a hosted release without explicit plan evidence.
8. After every `GO` or `NO-GO`, derive and report `NEXT STEPS` from the observed DAG, external merge state, and release-train contract. On `GO`, state whether to merge or record the milestone as merged, whether release preparation is deferred or must begin, and the next dependency-ready milestone. On `NO-GO`, state the exact remediation and retry gate, then either `SKIP <current milestone> FOR NOW; RUN <next milestone> — independent of <blocked dependency closure>` or `NO NEXT MILESTONE — <blocking reason>`. Do not advance a dependent milestone or invent release work.

## Output format

```text
## Milestone Runner Plan

| Milestone | Depends on | Target release | Design status | Mode | Worktree/Profile | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Design evidence
- Authoritative plan/prompt revision:
- Local history: present | reconstructed
- Reconciliation PR:
- Affected downstream milestones:

## Gates
- Design verdict:
- Reconciliation:
- PR bases:
- CI:
- Verification:
- Review:
- Release train:
- Release preparation:

## NEXT STEPS:
1. Current milestone: <merge the reviewed stack | already merged | stop on NO-GO>.
2. Release: <deferred until listed train members merge | begin declared preparation | not-required | blocked with reason>.
3. Next milestone: <M# and dependency/release-train evidence | `SKIP <current> FOR NOW; RUN M# — independent of <closure>` | `none — reason`>.
4. For `NO-GO`: <specific remediation and exact retry gate>; otherwise `not applicable`.

## Stop/Continue Decision
<Run design gate | Reconcile plan | Launch implementation wave | Continue within release train | Prepare release | Stop on DESIGN NO-GO | Stop on failed gate>
```

For merge-and-clean requests, also report each PR’s base, pre-merge CI, merge result, cleanup, post-merge verification, release-train state, and downstream milestones marked for renewed design review.

## Error handling

| Problem | Resolution |
| --- | --- |
| Missing plan or prompt file | Stop; run `plan-prompts` first. |
| Missing ignored history ledger | Reconstruct from authoritative artifacts, merged PRs, CI, and current code; recreate it locally. |
| History path is not ignored | Stop before writing it; add or verify the exact ignore rule. |
| Ambiguous dependency graph | Use sequential design gates; do not infer parallel safety. |
| `DESIGN NO-GO` or missing design verdict | Stop the affected dependency closure before code work. |
| Reconciliation changes plan/prompt | Merge the reviewed green docs-only PR, reload artifacts, rebuild the DAG, and rerun invalidated gates. |
| Dirty workspace | Stop before state-changing operations. |
| CI pending or failed | Treat as incomplete; do not merge or advance. |
| Merge conflict | Stop and use stack conflict resolution; do not launch downstream work. |
| Release target missing, contradictory, or unresolved | Stop the affected train; do not infer versioning or release artifacts. |

## Safety checklist

Before yielding:

- Every considered milestone has an observed design state: awaiting, `DESIGN GO`, `DESIGN NO-GO`, invalidated, or blocked.
- No product code or code PR began before a current `DESIGN GO`.
- Every material revision merged through a reviewed green docs-only reconciliation PR before implementation.
- Parallel work used isolated worktrees only after serialized design gates and a stable artifact revision.
- Every merged milestone has verified post-merge behavior and recorded downstream reevaluation requirements.
- Every terminal milestone result includes ordered `NEXT STEPS` covering the current action, release-preparation state, next runnable milestone or blocking reason, and `NO-GO` remediation when applicable.
- Every completed release train has observed `RELEASE PREP` state and no early version/changelog work.
- Cleanup removed only branches verified as merged.
