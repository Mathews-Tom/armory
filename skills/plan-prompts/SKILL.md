---
name: plan-prompts
description: 'Use when asked to "create a development plan", "generate execution prompts", "replan a milestone", "update DEVELOPMENT_PLAN.md", "start M5", or "adapt future milestones" after predecessor work changes the current repository design. Not for discovering an uncertain destination or unresolved decisions; use decision-map. Not for auditing an existing plan; use plan-review. Not for executing a stack; use stacked-prs.'
metadata:
  version: 3.0.0
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

- `.docs/DEVELOPMENT_PLAN.md` — milestones with outcome, scope, dependencies, acceptance and verification.
- `.docs/EXECUTION_PROMPTS.md` — one short `/goal` block per milestone.

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
   | Medium | A few PRs, one milestone or two | Plan of ≤2 pages; ≤600 words per prompt. |
   | Large | Several milestones with real dependencies | Full plan; ≤600 words per prompt. |

2. **Plan from the source, not from imagination.** Every requirement, check and gate must trace to a source document, an owner constraint or a repository rule. Do not add hardening, qualification runs, paid validation, extra review rounds, compliance work, benchmarks, telemetry, dashboards or documentation that no source asks for. List worthwhile extras once under `Suggested follow-ups`, never as acceptance.
3. **Acceptance is what the user can do.** Write each acceptance row as `Done when <user/operator> can <interaction> and sees <result>`, plus the runnable checks. A check that cannot run inside the milestone (unavailable credentials, hosted spend, human-only review) is either an explicit owner-requested gate or a follow-up. Never leave a milestone permanently `BLOCKED` or `pending qualification` on optional evidence.
4. **Prefer fewer, usable milestones.** Each milestone delivers a working vertical slice. A prerequisite-only milestone needs a named consumer and a reason it cannot be combined with that consumer.
5. **Omit empty sections.** No requirement-ID catalogues, scenario suites, evidence tiers or traceability matrices unless the source uses them. One table beats three paragraphs.
6. **Before saving, cut.** For every sentence ask: would deleting it change what the executor does? If not, delete it.

## Inputs

| Input | Meaning | Default |
| --- | --- | --- |
| Folder path or explicit file list | Source documents; with a file list, the first file is the primary source of truth. | Required |
| `REPO_CONTEXT` | Target repo; inspect its structure, tooling, CI, conventions, partial implementation and release practice. | Greenfield |
| `GLOBAL_CONSTRAINTS` | Constraints absent from the sources. | None |
| `STACK_DEPTH_HINT` | Maximum PRs per milestone. | 6 |

For large source sets, read documents and the repository through read-only subagents that return cited findings, then confirm load-bearing citations yourself. Decomposition and writing stay in this session. Skip delegation when the input is small.

## Workflow

### Phase 0 — Ground

1. List the capabilities, interfaces, data and constraints the sources require, with source references.
2. Inspect the repository: package manager, test/lint/type/CI commands, conventions, what already works, known defects, version source and `CHANGELOG.md`.
3. Write the product contract in five lines: user and problem; shortest workflow (trigger → interactions → result); done-when demonstration; non-goals; working behavior and safety to preserve.
4. Record `> ASSUMPTION:` for defensible defaults and `> GAP:` for missing or contradictory requirements. A contradiction about architecture, data, security or acceptance blocks only the milestones it affects.
5. For a replan, read the existing plan and prompts first. Map every old milestone to keep, combine, defer or drop with a one-line reason. Keep unresolved historical failures visible. Drop optional work explicitly rather than carrying it forward.

Summarize Phase 0 in chat only.

### Phase 1 — Write the plan (medium and large)

```markdown
# Development Plan — <System>

## 1. Goal
<Five-line product contract. For replans: completed work with evidence and the old-milestone mapping table.>

## 2. Assumptions & Gaps
<`> ASSUMPTION:` / `> GAP:` entries, or "None.">

## 3. Milestones
#### M1 — <title>
| Field | Value |
| --- | --- |
| Outcome | What the user/operator can do after this milestone. |
| Scope / Non-goals | Explicit boundaries. |
| Depends on | `none`, or IDs with the consumed output or safety reason. |
| Acceptance | `Done when …` rows; binary and runnable now. |
| Verification | Exact commands and the manual interaction with expected result. |
| Release | Named version, `unversioned` or `none`; only when the source or repo defines releases. |
| Risks & rollback | Main failure modes; the stack is the rollback unit. |
| Est. PRs | Integer ≤ `STACK_DEPTH_HINT`. |

## 4. Dependency Graph
<Mermaid graph only when there are three or more milestones.>

## 5. Suggested follow-ups
<Optional extras not in scope, or omit the section.>
```

Rules:

- Use vertical slices, not layers. In greenfield work, put minimum setup and checks inside the first usable slice; no skeleton-only M1.
- Releases: when the source names a version, assign milestones to it and prepare the release once, after all its milestones merge. Never invent a version; a missing release decision blocks release preparation only.
- Use Markdown tables and Mermaid only. Validate Mermaid when tooling is available.

### Phase 2 — Write execution prompts

One `/goal` per milestone, ≤600 words, traced to the plan. Do not copy plan prose into the prompt.

For the small size class there is no plan: write one `/goal` of ≤200 words traced to the request and repository rules. Use the milestone block below without the file header, global rules or any plan-file reference; `CONTEXT` names the request and the repo, and the `/goal` line states the change in one PR.

```markdown
# Execution Prompts — <System>

## Global rules
- Use `stacked-prs`; Conventional Commits; no attribution; independently reviewable PRs.
- Before changing code, check the plan still matches the repository. Small drift: update the plan and prompt in the stack's first commit. A change to the outcome or acceptance: stop and ask the owner.
- Do not add work beyond this goal's acceptance. Put extras in the final report as suggested follow-ups.

### M1 — <title>
```text
/goal Deliver M1 (<title>) from .docs/DEVELOPMENT_PLAN.md as a reviewed stack of PRs.

GOAL: <user> can <interaction> and sees <result>. This milestone adds <contribution>.
PRESERVE: <working behavior and safety invariants>
NON-GOALS: <exclusions>
CONTEXT: Plan §3 M1. Preconditions: <none | Mx merged>. Repo: <language, package manager, check commands>.

PLANNED STACK:
1. PR-1 <purpose> — scope: <areas>
2. PR-2 <purpose, on PR-1> — scope: <areas>

DONE WHEN:
- <acceptance rows from the plan>
VERIFICATION: <exact commands + manual interaction and expected output>
REVIEW: one review per PR for scope, contracts, tests and failure handling; one whole-stack check that bases, CI and cumulative acceptance hold. Re-review only code changed by fixes.

FINAL REPORT: design check result; GO or NO-GO with the failing check; what the user can now do (observed); PR URLs.
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
- Every milestone has a user-observable outcome, `Done when` acceptance that can run now and exact verification.
- No check, gate or deliverable lacks a source; extras sit under `Suggested follow-ups`.
- The dependency graph is acyclic and every edge names its reason.
- Each prompt is within its word limit and carries GOAL, DONE WHEN, VERIFICATION and `NEXT STEPS:`.
- Only the two plan files were written (none for the small class).

Optionally get one `plan-review` pass; fix substantive findings, do not loop on wording.

## Error handling

| Problem | Resolution |
| --- | --- |
| No readable docs or a listed path is missing | Stop and report the missing input. |
| Sources contradict on architecture, data, security or acceptance | Emit a blocking `> GAP:` for the affected milestones; plan the rest. |
| Repo tooling is absent | Put minimum setup and checks inside the first usable slice. |
| Release policy is absent | Record `> GAP:`; block release preparation only. Never invent a version. |
| Plan files already exist | Read them first; overwrite only on requested regeneration. |

## Output and chat response

Report the size class, Phase 0 summary, paths written, quality-gate result, destructive gates and unresolved gaps. Do not paste the generated files unless requested.
