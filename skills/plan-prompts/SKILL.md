---
name: plan-prompts
description: 'Use when asked to "create a development plan", "generate execution prompts", "replan a milestone", "update DEVELOPMENT_PLAN.md", "start M5", or "adapt future milestones" after predecessor work changes the current repository design. Not for discovering an uncertain destination or unresolved decisions; use decision-map. Not for auditing an existing plan; use plan-review. Not for executing a stack; use stacked-prs.'
metadata:
  version: 3.1.0
  category: development
  tags: [planning, execution-prompts, milestones, adaptive-planning, stacked-prs, release-management, docs]
  difficulty: advanced
  phase: plan
  complements:
    - milestone-runner
    - stacked-prs
    - plan-review
    - task-decomposer
    - decision-map
---

# Development Plan and Execution Prompts

Turn source documents and repository reality into the smallest plan that gets a user to a working result:

- `.docs/DEVELOPMENT_PLAN.md` — project destination, near-term commitments and a lightweight future roadmap.
- `.docs/EXECUTION_PROMPTS.md` — short `/goal` blocks for actionable milestones only.

This skill plans only. Do not implement code, create issues or branches, open PRs, or run the prompts.

## Scope Boundary

| Situation | Package |
|---|---|
| Destination or the decisions needed to define it remain uncertain | `decision-map` |
| Existing plan needs a challenge before implementation | `plan-review` |
| Approved plan needs execution | `milestone-runner` |

## Be judicious

A plan is a cost the executor pays on every milestone. Every sentence you write becomes work, a check or a stop condition for a later session. Write only what changes what the executor does.

1. **Size the plan to the work first.** Report the size class and its reason before writing anything.

   | Size | Signal | Output |
   | --- | --- | --- |
   | Small | Fits in one PR | No plan files. Return one `/goal` prompt of ≤200 words in chat. |
   | Medium | A few PRs, one milestone or two | Plan of ≤2 pages; ≤600 words per active prompt. |
   | Large | Several milestones with real dependencies | Rolling-wave plan; ≤600 words per active prompt. |

2. **Source-backed does not mean necessary now.** Include an enabler or architecture change only if a current acceptance criterion, safety/current correctness need, mandatory rule or irreversible constraint requires it now. Name the consumer or constraint, why a simpler solution fails and the cost of waiting. Otherwise defer it with a concrete revisit condition, even when it supports the long-term vision. Preserve affordable change with clear boundaries and ordinary maintainable code, not universal future abstractions.
3. **Acceptance is what the user can do.** Write each active milestone's acceptance as `Done when <user/operator> can <interaction> and sees <result>`, plus runnable checks. Required provider checks and repository mandates remain gates; unavailable optional evidence is a follow-up, not permanent `BLOCKED` or `pending qualification`. Do not add hardening, paid validation, extra reviews, benchmarks, telemetry or docs merely for confidence.
4. **Prefer fewer, usable milestones.** Each commitment delivers a working vertical slice. A prerequisite-only milestone needs a necessary-now reason and named consumer, and explains why they cannot be combined. Separate the destination from this commitment: distant roadmap items describe outcomes, dependencies and unresolved constraints, not speculative files, PRs or checks.
5. **Omit empty sections.** No requirement-ID catalogues, scenario suites, evidence tiers or traceability matrices unless the source uses them. One table beats three paragraphs.
6. **Before saving, cut.** For every sentence ask: would deleting it change what the executor does? If not, delete it.

## Inputs

| Input | Meaning | Default |
| --- | --- | --- |
| Folder path, explicit file list or request | Source requirements; with a file list, the first file is primary. A small request needs no source file. | Required |
| `REPO_CONTEXT` | Target repo; inspect tooling, CI, conventions, partial implementation and release practice. | Greenfield |
| `GLOBAL_CONSTRAINTS` | Constraints absent from the sources. | None |
| `STACK_DEPTH_HINT` | Upper bound when a stack is justified, not a target. | One cohesive PR; shallow stack only for a real review, integration or dependency benefit. |

For large source sets, read documents and the repository through read-only subagents that return cited findings, then confirm load-bearing citations yourself. Decomposition and writing stay in this session. Skip delegation when the input is small.

## Workflow

### Phase 0 — Ground

1. List the capabilities, interfaces, data and constraints the sources require, with source references.
2. Inspect the repository: package manager, test/lint/type/CI commands, conventions, what already works, known defects, version source and `CHANGELOG.md`.
3. Write the product contract in five lines: user and problem; north-star workflow (trigger → interactions → result); done-when demonstration; non-goals; working behavior and safety to preserve. Distinguish the project destination from the next usable contribution.
4. Record `> ASSUMPTION:` for defensible defaults and `> GAP:` for missing or contradictory requirements. A contradiction about architecture, data, security or acceptance blocks only the milestones it affects.
5. For a replan, read the existing plan and prompts first. Map every old milestone to keep, combine, defer or drop with a one-line reason. Keep unresolved historical failures visible. Drop optional work explicitly rather than carrying it forward.

Summarize Phase 0 in chat only.

### Phase 1 — Write the plan (medium and large)

```markdown
# Development Plan — <System>

## 1. Goal
<Five-line product contract and near-term commitment. For replans: completed evidence and the old-milestone mapping table.>

## 2. Assumptions & Gaps
<`> ASSUMPTION:` / `> GAP:` entries, or "None.">

## 3. Active milestones
#### M1 — <title and contribution to the destination>
| Field | Value |
| --- | --- |
| Outcome | What the user/operator can do after this milestone. |
| Scope / Non-goals | Explicit boundaries. |
| Depends on | `none`, or IDs with the consumed output or safety reason; predecessors merged unless the owner or approved plan explicitly authorizes a stable unmerged interface dependency. |
| Acceptance | `Done when …` rows; binary and runnable now. |
| Verification | Repository-defined local preflight and runtime interaction with expected result; CI policy stays with the repo and `ship-workflow`. |
| Release | Named version, `unversioned` or `none`; only when the source or repo defines releases. |
| Risks & rollback | Main failure modes and smallest safe rollback unit. |
| PR shape | One cohesive PR; justify any shallow stack and respect `STACK_DEPTH_HINT`. |

## 4. Future roadmap
<Distant outcomes, dependencies and unresolved constraints only; no execution prompts or invented acceptance/check detail. Omit if none.>

## 5. Dependency Graph
<Mermaid graph only when there are three or more milestones.>

## 6. Suggested follow-ups
<Deferred optional work with concrete revisit conditions; omit if none.>
```

Rules:

- Use vertical slices, not layers. In greenfield work, put minimum setup and checks inside the first usable slice; no skeleton-only M1.
- Rolling wave: detail only the next dependency-ready milestones with feasible verification. Future items stay roadmap-only. When one becomes ready, the runner may render its prompt, express the approved outcome as binary `Done when` acceptance and choose routine implementation/check detail from repo conventions. This needs no owner round-trip unless it adds or changes an authorized outcome/acceptance requirement or encounters an unresolved owner decision.
- Releases: when the source names a version, assign milestones to it and prepare the release once, after all its milestones merge. Never invent a version; a missing release decision blocks release preparation only.
- Use Markdown tables and Mermaid only. Validate Mermaid when tooling is available.

### Phase 2 — Write execution prompts

Write a `/goal` only when the milestone is actionable; distant roadmap items have no placeholder prompts. Keep each active prompt ≤600 words and traced to the plan, with a concise project destination and this milestone's contribution rather than copied plan prose.

For the small size class, return one `/goal` of ≤200 words traced to the request and repository rules. Use the block below without the file header, global rules or plan reference; `CONTEXT` names the request and repo. The supplied prompt is a valid direct handoff to `milestone-runner`: no synthetic plan files or regeneration cycle.

```markdown
# Execution Prompts — <System>

## Global rules
- Conventional Commits; no attribution. Default one cohesive PR; use `stacked-prs` only for a justified shallow stack.
- Check the plan against the repo before code. Routine drift/detail stays in the first implementation commit; outcome or acceptance changes require the owner.
- Do only necessary-now acceptance work. Defer extras with revisit conditions. CI classification and landing belong to repo policy and `ship-workflow`; required checks stay required, advisory checks must be explicit.

### M1 — <title>
```text
/goal Deliver M1 (<title>) from .docs/DEVELOPMENT_PLAN.md as <one reviewed PR | justified shallow stack>.

PROJECT: <north-star user workflow and destination>
GOAL: <this milestone's contribution: user can interact and sees result>
PRESERVE: <working behavior and safety invariants>
NON-GOALS: <exclusions>
CONTEXT: Plan §3 M1. Preconditions: <none | Mx merged | explicitly authorized stable unmerged dependency and authority>. Repo: <tooling>.

PR SHAPE: one cohesive PR <or justified shallow stack with purpose and scope per PR>.

DONE WHEN:
- <acceptance rows from the plan>
VERIFICATION: <repo local preflight + runtime interaction/expected output; apply repo/ship-workflow CI policy>
REVIEW: one substantive review per PR; for stacks, one cumulative integration check, not duplicate full reviews. Target changed code after fixes; after three unsuccessful fix rounds, escalate without merging defects.

FINAL REPORT: design verdict; observed outcome; check results including explicit advisory failures; review and landing state; PR URLs.
NEXT STEPS:
1. Current milestone: <merge | merged | fix: specific remediation>
2. Release: <deferred | prepare now | not-required>
3. Next milestone: <M# | none — reason>
```
```

For milestones that run destructive operations, add:

```text
HUMAN REVIEW GATE: Do not merge or run destructive paths unattended until a human reviews dry-run output, rollback notes, and audit/tombstone logging.
```

## Quality gates

Before yielding, check and fix:

- The size class is stated and the output matches it.
- Every source requirement maps to a milestone, a `> GAP:` or an explicit deferral; a replan maps every old milestone.
- Every active milestone passes necessary-now, has a user-observable outcome, runnable `Done when` acceptance and verification; future roadmap items need only outcome, dependencies and unresolved constraints.
- Source-backed optional work has a concrete revisit condition, not invented acceptance. Checks, gates and deliverables trace to a source, owner constraint or repository rule; required repository/provider gates remain intact.
- The dependency graph is acyclic; every edge has a reason and any stable unmerged exception has explicit authority.
- Each actionable prompt fits its limit and carries project destination, contribution, DONE WHEN, VERIFICATION and `NEXT STEPS:`. No prompt is required for distant or unready roadmap items.
- Write only the two requested plan files (none for small work); if the request is roadmap-only with nothing actionable, omit the execution file rather than manufacture prompts.

Optionally get one `plan-review` pass; fix substantive findings, do not loop on wording.

## Error handling

| Problem | Resolution |
| --- | --- |
| No readable requirements or a listed path is missing | Report the missing input; a complete small request needs no source/plan files. |
| Sources contradict on architecture, data, security or acceptance | Emit a blocking `> GAP:` for the affected milestones; plan the rest. |
| Repo tooling is absent | Put minimum setup and checks inside the first usable slice. |
| Release policy is absent | Record `> GAP:`; block release preparation only. Never invent a version. |
| Plan files already exist | Read them first; overwrite only on requested regeneration. |

## Output and chat response

Report size class, Phase 0 summary, paths written (or the small `/goal`), active versus roadmap-only scope, quality-gate result, destructive gates and unresolved gaps. Do not paste generated files unless requested.
