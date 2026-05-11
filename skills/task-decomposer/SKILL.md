---
name: task-decomposer
description: 'Produces phased task boards from feature requests: dependency-mapped work items, parallelization flags, risk flags, edge cases, test matrices. Triggers on: "decompose this feature", "task breakdown with dependencies", "phased implementation plan", "work breakdown structure". NOT for effort estimates, use estimate-calibrator.'
metadata:
  version: 1.1.1
  category: development
  tags: [task-breakdown, dependencies, planning, phased]
  difficulty: intermediate
  phase: plan
---

# Task Decomposer

Transforms ambiguous feature requests into concrete, implementable task sequences:
identifies acceptance criteria, decomposes into tracer-bullet vertical slices with effort
sizing, maps dependencies and parallelization, enumerates edge cases, plans testing, labels
HITL/AFK readiness, and flags risks — producing a ready-to-execute task board.

> **When to use this skill vs native decomposition:** The base model decomposes features
> well in an ad-hoc format. Use this skill specifically when you need the structured output:
> phased task tables with dependency mapping, parallelization flags, risk flags, and
> integrated test strategy. If you just need a quick list of steps, ask directly without
> invoking this skill.

## Reference Files

| File                                   | Contents                                                        | Load When                       |
| -------------------------------------- | --------------------------------------------------------------- | ------------------------------- |
| `references/decomposition-patterns.md` | Feature → task decomposition strategies, granularity guidelines | Always                          |
| `references/edge-case-checklist.md`    | Common edge case categories by domain (web, API, data, CLI)     | Edge case identification needed |
| `references/dependency-mapping.md`     | Dependency graph construction, critical path identification     | Multi-task breakdown            |
| `references/sizing-guide.md`           | Effort estimation guidance (S/M/L), complexity indicators       | Effort sizing needed            |

## Prerequisites

- Feature description or requirements (can be vague — the skill handles ambiguity)
- Project context (tech stack, existing architecture, team size)

## Project Context

Before decomposing, check for repo-local agent context:

- `docs/agents/domain.md` for `CONTEXT.md`, `CONTEXT-MAP.md`, and ADR lookup rules
- `docs/agents/triage-labels.md` for readiness labels when tasks become issues
- `CONTEXT.md` or relevant context-local glossary for task titles and acceptance criteria
- `.out-of-scope/` for durable rejections that may affect scope

Continue if these files are absent, but state that the plan is using inferred vocabulary.

## Workflow

### Phase 1: Understand the Feature

1. **Extract the user-facing goal** — What does this feature enable the user to do?
   If unclear, state assumptions explicitly.
2. **Define acceptance criteria** — What must be true for this feature to be "done"?
   Express as testable statements: "User can X", "System does Y when Z."
3. **Identify non-functional requirements** — Performance, security, accessibility,
   backwards compatibility constraints.
4. **Clarify scope boundaries** — What is explicitly out of scope? State this to
   prevent scope creep during implementation.

### Phase 2: Decompose into Vertical Slices

Break the feature into tracer-bullet slices first, then split oversized slices into tasks.
Each slice should deliver a narrow but complete path through the affected layers. Avoid
horizontal breakdowns where one issue only creates schema, another only creates API, and
another only creates UI unless the work is pure infrastructure.

| Granularity | Size                                           | Example                      |
| ----------- | ---------------------------------------------- | ---------------------------- |
| Too coarse  | "Build the search feature"                     | Not actionable               |
| Right level | "Exact-match product search returns results end-to-end" | Single PR, testable |
| Too fine    | "Import the search library"                    | Not independently meaningful |

**Right granularity test:** Each task should be completable in a single PR, testable
in isolation, and deliverable independently. A completed vertical slice should be demoable
or verifiable without waiting for unrelated slices.

Group tasks into phases:

| Phase | Purpose | Contains |
| ----- | ------- | -------- |
| Setup | Shared contracts or migrations that unblock slices | Types, schemas, fixtures |
| Slice 1 | First end-to-end behavior | Minimal data, logic, API, UI/CLI path |
| Slice N | Incremental capability | One user-visible behavior or operational capability |
| Hardening | Cross-slice edge cases and quality gates | Performance, security, docs, cleanup |

Label each slice:

- **AFK** — an agent can implement it from the issue brief with no further human context.
- **HITL** — requires human judgment, external access, product approval, design review, or release authority.

### Phase 3: Identify Edge Cases

For each task, enumerate edge cases:

1. **Input boundaries** — Empty, null, maximum size, special characters
2. **State transitions** — Concurrent modification, interrupted operations
3. **Error conditions** — Network failures, invalid data, permission denied
4. **Backwards compatibility** — Existing data, existing API consumers

### Phase 4: Plan Testing

For each task, identify what to test:

| Test Level  | What to Test                          | Who Writes              |
| ----------- | ------------------------------------- | ----------------------- |
| Unit        | Individual functions, pure logic      | During implementation   |
| Integration | Component interactions, API endpoints | After integration phase |
| Manual      | User flows, visual correctness        | After polish phase      |

### Phase 5: Map Dependencies

Identify which tasks depend on others:

1. **Hard dependencies** — Task B requires Task A's output (database table must exist
   before writing queries)
2. **Soft dependencies** — Task B benefits from Task A but could use a stub
3. **No dependency** — Tasks can be done in parallel

### Phase 6: Flag Risks

For each risk, identify mitigation:

| Risk Type           | Example                             | Mitigation                                      |
| ------------------- | ----------------------------------- | ----------------------------------------------- |
| Technical unknown   | "Never used WebSockets before"      | Spike/prototype first                           |
| External dependency | "Requires API access we don't have" | Request early, use mocks                        |
| Scope uncertainty   | "Requirements may change"           | Implement core first, defer edge cases          |
| Performance risk    | "May be slow with 1M rows"          | Add benchmark task, define acceptable threshold |

## Output Format

```text
## Task Decomposition: {Feature Name}

### Feature Summary
{One paragraph describing what this feature does and why}

### Acceptance Criteria
- [ ] {Testable statement 1}
- [ ] {Testable statement 2}
- [ ] {Testable statement 3}

### Scope
- **In scope:** {what's included}
- **Out of scope:** {what's excluded}

### Task Breakdown

#### Phase 1: Foundation
| # | Slice / Task | Type | Effort | Dependencies | Parallel |
|---|--------------|------|--------|--------------|----------|
| 1.1 | {task description} | {AFK/HITL} | {S/M/L} | None | Yes |
| 1.2 | {task description} | {AFK/HITL} | {S/M/L} | 1.1 | No |

#### Phase 2: Vertical Slices
| # | Slice / Task | Type | Effort | Dependencies | Parallel |
|---|--------------|------|--------|--------------|----------|
| 2.1 | {end-to-end behavior} | {AFK/HITL} | {S/M/L} | 1.x | Yes |
| 2.2 | {end-to-end behavior} | {AFK/HITL} | {S/M/L} | 1.x | Yes |

#### Phase 3: Hardening
| # | Task | Type | Effort | Dependencies | Parallel |
|---|------|------|--------|--------------|----------|
| 3.1 | {cross-slice quality gate} | {AFK/HITL} | {S/M/L} | 2.x | No |

### Edge Cases

| # | Edge Case | Handling | Phase |
|---|-----------|----------|-------|
| 1 | {edge case} | {how to handle} | {which phase} |

### Test Strategy

#### Unit Tests
- {Component}: {what to test}

#### Integration Tests
- {Flow}: {what to test}

#### Manual Verification
- {Scenario}: {what to check}

### Risk Flags
- {Risk}: {mitigation strategy}

### Agent Brief Notes
- {Any interface contracts, acceptance criteria, or out-of-scope boundaries that should be copied into ready-for-agent issues}
```

## Calibration Rules

1. **Right granularity.** Each slice should be 1-3 days of work and each implementation task
   should fit in one PR. Larger → decompose further. Smaller → merge into a parent slice.
2. **Testable acceptance criteria.** "Make search work" is not testable. "Search returns
   relevant results within 200ms for queries up to 100 characters" is testable.
3. **Dependencies are sacred.** If Task B truly depends on Task A, mark it. False
   dependencies slow teams down; missing dependencies cause integration failures.
4. **Edge cases are not optional.** Every feature has edge cases. If the edge case list
   is empty, the analysis is incomplete.
5. **Parallel = velocity.** Maximize parallel tasks. If 4 tasks can be done simultaneously,
   the phase takes the duration of the longest, not the sum.
6. **Vertical first.** Prefer end-to-end slices over layer-only tasks. Use horizontal tasks
   only for shared contracts, migrations, or infrastructure that genuinely unblocks slices.
7. **Ready-for-agent requires a brief.** AFK slices need desired behavior, key interfaces,
   acceptance criteria, and out-of-scope boundaries clear enough for a fresh agent.

## Error Handling

| Problem                          | Resolution                                                                                             |
| -------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Feature description is vague     | State assumptions, decompose what's known, mark uncertain tasks with "pending clarification."          |
| Feature is too large (20+ tasks) | Split into multiple features. A feature that takes months is a project, not a feature.                 |
| No clear acceptance criteria     | Help the user define them: "What does done look like? What would you demo?"                            |
| Technical stack unknown          | Decompose at the logical level (data model, business logic, API, UI) without implementation specifics. |

## When NOT to Decompose

Push back if:

- The task is already atomic (single function, single file change) — just do it
- The user wants time estimates, not task breakdown — use estimate-calibrator instead
- The feature is exploratory (research, prototype) — decomposition assumes known scope
