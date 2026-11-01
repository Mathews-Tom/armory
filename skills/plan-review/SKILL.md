---
name: plan-review
description: 'Pre-implementation plan audit stress-testing scope, assumptions, risks, and failure modes before code is written. Triggers on: "review this plan", "is this plan solid", "what am I missing", "challenge my assumptions", "stress-test this", "/plan-review".'
metadata:
  version: 1.1.0
  category: review
  tags: [plan-audit, scope, risk-assessment, assumptions]
  difficulty: intermediate
---

# Plan Review Skill

## Purpose

Execute a structured pre-implementation audit of a technical plan, proposal,
or design document. The goal is to surface risks, bad assumptions, missing
pieces, and scope problems _before_ any code is written — when course
corrections are cheapest.

This skill is read-only. It never modifies code. It produces a
severity-tagged review document with a final ship/rethink/reject verdict.

## Step 0 — Mode Selection

Use the requested lens: Product, Engineering, or Combined. When none is specified, use Combined without a configuration question. Resolve facts from the plan and repository; ask only for a material decision the evidence cannot settle.

Also assess scope size from the plan:

- **Small change** (single file, ~100 lines or fewer): deliver a compressed
  4-section review — Scope, Risks, Missing, Verdict. Skip the full
  multi-section template.
- **Standard change**: execute the full review sequence below.

## Full Review Sequence

### 1. Plan Comprehension

Read the plan and its authoritative project goal. Summarize the intended user workflow, the next useful outcome, non-goals and constraints in 2–3 sentences. Identify a mismatch between project value and technically coherent milestones before reviewing implementation detail. Do not pause for confirmation unless an unresolved contradiction changes the outcome or safety.

### 2. Assumption Challenge

Extract material assumptions that could change the next outcome or its safety. For each one:

| Assumption | If wrong? | Supporting evidence | What falsifies it? |
| ---------- | --------- | ------------------- | ------------------ |

Common assumption categories to probe:

- Data availability and shape
- Third-party API stability and rate limits
- Team familiarity with chosen tools
- Performance characteristics of dependencies
- Backward compatibility requirements
- Deployment environment capabilities

### 3. Risk & Failure Mapping

For components on the next delivery path, identify demonstrated failure risks:

| Component | Failure Mode | Blast Radius | Recovery Strategy |
| --------- | ------------ | ------------ | ----------------- |

Additionally identify **data flow shadow paths** — side effects, async
callbacks, event propagation, or cache invalidation chains that are not on
the happy path but will execute in production.

Use ASCII diagrams to illustrate non-obvious data flow or failure
propagation where the plan involves three or more interacting components.

### 4. Component-by-Component Review (Engineering Lens)

For each major component, assess:

- **Error handling strategy** — Are current failures explicit and recoverable where required? Do not prescribe a registry or retry framework without a consumer.
- **Data integrity invariants** — What invariants must hold? How are they
  enforced? What happens when they break?
- **Concurrency and race conditions** — Shared state, lock ordering,
  optimistic vs. pessimistic strategies, idempotency guarantees.
- **Performance under load** — Does the design meet evidenced workload and latency constraints? Hypothetical 10x capacity is not a gate without a source requirement.
- **Test strategy adequacy** — Do focused tests and an observed interaction cover the promised behavior and affected contracts? Separate fast local/PR feedback, integration-candidate checks and broad mainline/release coverage.

This section is language- and framework-agnostic. Reference
`references/project-detection.md` for framework-aware examples when the
user's stack is known.

Skip this section when running product-lens-only mode.

### 5. Scope & Priority Assessment (Product Lens)

- **Necessary now vs. eventually useful** — Does each milestone advance the next useful project outcome? For prerequisites and architectural expansion, name the consumer and concrete cost or risk of deferral.
- **Deferral candidates** — Defer optional capability with a revisit condition. Preserve correctness, security, data integrity and expensive-to-reverse constraints of the current capability.
- **Changeability vs. speculative extensibility** — Favor clear boundaries and affordable refactoring over unused frameworks, providers or deployment machinery.
- **Planning horizon** — Detail actionable milestones; keep distant outcomes provisional. Missing distant execution prompts are not defects.
- **Delivery cost** — Prefer one cohesive PR unless a split improves review or safe integration; examine stack depth and repeated CI/review waits.

Skip this section when running engineering-lens-only mode.

### 6. Integration Review

How components connect to each other and to the outside world:

- **API contracts** — Request/response shapes, versioning, error codes
  between modules.
- **State management across boundaries** — Who owns state? How is it
  synchronized? What happens during partial failure?
- **Migration and deployment ordering** — Which components must deploy
  first? Are there intermediate states where the system is inconsistent?
- **Rollback compatibility** — Can each deployment step be reversed
  independently? What data is irreversible?

### 7. What's Missing

Report a missing element only when a source requirement or concrete failing scenario makes it necessary for the current outcome. Consider security, data integrity, recovery, workload and operational needs at that boundary; do not turn this list into mandatory dashboards, runbooks, retries, benchmarks or extra qualification. Put optional improvements under non-blocking follow-ups, or omit them.

### 8. Execution Assessment

Evaluate the proposed implementation order:

- **Dependency ordering** — Are prerequisites built before dependents?
- **Parallel work opportunities** — Which tasks have no mutual dependency
  and can proceed simultaneously?
- **Risk-first vs. value-first** — Address an unknown early only when it threatens the next useful outcome or an expensive-to-reverse decision.
- **Bounded experiments** — Recommend a focused spike only when it can resolve that unknown more cheaply than implementation; state its decision and stop condition.
- **Integration readiness** — Keep required checks before merge against the actual integration candidate. Local checks and broad post-merge coverage complement rather than replace that safeguard.

### 9. Verdict

Deliver exactly one of:

| Verdict               | Meaning                                                                         |
| --------------------- | ------------------------------------------------------------------------------- |
| **Ship**              | Plan is solid. Proceed as written.                                              |
| **Ship with changes** | Viable, but specific modifications listed below are required before proceeding. |
| **Rethink**           | Fundamental structural issues require re-planning. Itemize what must change.    |
| **Reject**            | Plan is not viable. Explain why and what alternative direction to consider.     |

Include a one-paragraph rationale for the verdict.

## Compressed Review (Small Changes)

For small-scope changes (single file, ~100 lines), deliver four sections
only:

1. **Scope** — What the change does and its boundaries.
2. **Risks** — Failure modes and blast radius (brief table).
3. **Missing** — Only material gaps required by this outcome.
4. **Verdict** — Ship / Ship with changes / Rethink / Reject.

## Interaction Protocol

- Batch related material decisions; finish the reachable review rather than pausing after each finding.
- Distinguish blocking defects from optional improvements. A plausible long-term benefit alone is not a blocker.
- This skill is **read-only**. It does not create, modify, or delete files.
- Use a diagram only when it clarifies a non-obvious dependency or failure.

## Output Format

Return only applicable sections, severity-tagged findings with evidence and consequence, and a final verdict with rationale. Separate blocking changes from optional follow-ups. Omit empty sections and do not repeat findings in a second summary table. No finding is a valid result; do not invent work to fill a template.
