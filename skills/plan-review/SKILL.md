---
name: plan-review
description: 'Pre-implementation plan audit stress-testing scope, assumptions, risks, and failure modes before code is written. Triggers on: "review this plan", "is this plan solid", "what am I missing", "challenge my assumptions", "stress-test this", "/plan-review".'
metadata:
  version: 1.0.1
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

Ask the user a single question via `AskUserQuestion`:

> Which review lens? (1) Product — scope, user impact, business alignment.
> (2) Engineering — architecture, failure modes, test strategy, performance.
> (3) Combined (default) — both lenses integrated.

Accept the answer and proceed. Do not ask follow-up configuration questions.

Also assess scope size from the plan:

- **Small change** (single file, ~100 lines or fewer): deliver a compressed
  4-section review — Scope, Risks, Missing, Verdict. Skip the full
  multi-section template.
- **Standard change**: execute the full review sequence below.

## Full Review Sequence

### 1. Plan Comprehension

Read the plan end-to-end. Produce a 2–3 sentence summary confirming
understanding. Explicitly list:

- **Stated goals** — what the plan claims to achieve.
- **Non-goals** — what is explicitly out of scope.
- **Constraints** — budget, timeline, compatibility, team size, or
  technology constraints mentioned or implied.

If the summary is wrong, the user corrects it here before the rest of the
review proceeds on a false foundation.

### 2. Assumption Challenge

Extract every implicit assumption. For each one:

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

For each component or subsystem in the plan, fill a failure mode table:

| Component | Failure Mode | Blast Radius | Recovery Strategy |
| --------- | ------------ | ------------ | ----------------- |

Additionally identify **data flow shadow paths** — side effects, async
callbacks, event propagation, or cache invalidation chains that are not on
the happy path but will execute in production.

Use ASCII diagrams to illustrate non-obvious data flow or failure
propagation where the plan involves three or more interacting components.

### 4. Component-by-Component Review (Engineering Lens)

For each major component, assess:

- **Error handling strategy** — Are errors classified and routed through a
  registry, or silently swallowed by catch-all handlers?
- **Data integrity invariants** — What invariants must hold? How are they
  enforced? What happens when they break?
- **Concurrency and race conditions** — Shared state, lock ordering,
  optimistic vs. pessimistic strategies, idempotency guarantees.
- **Performance under load** — Expected throughput, latency budget, resource
  consumption at 10x current scale.
- **Test strategy adequacy** — Unit, integration, and end-to-end coverage
  for the component. What is untestable and why?

This section is language- and framework-agnostic. Reference
`references/project-detection.md` for framework-aware examples when the
user's stack is known.

Skip this section when running product-lens-only mode.

### 5. Scope & Priority Assessment (Product Lens)

- **Needed vs. nice-to-have** — Which features are load-bearing for the
  stated goals? Which are speculative?
- **Deferral candidates** — What can ship in a follow-up without increasing
  risk?
- **Over-engineering indicators** — Abstractions, configurability, or
  extensibility that no current requirement demands.
- **User-facing impact** — Does the complexity produce proportional user
  value?

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

Things the plan does not address that it should:

- Monitoring and observability (metrics, logs, alerts, dashboards)
- Error recovery paths beyond the first retry
- Edge cases outside the stated happy path
- Security considerations (authn, authz, input validation, secrets
  management)
- Load and scale implications (connection pools, queue depth, storage
  growth)
- Operational runbooks for incident response

### 8. Execution Assessment

Evaluate the proposed implementation order:

- **Dependency ordering** — Are prerequisites built before dependents?
- **Parallel work opportunities** — Which tasks have no mutual dependency
  and can proceed simultaneously?
- **Risk-first vs. value-first** — Does the plan tackle the highest-risk
  unknowns early, or defer them?
- **Prototype candidates** — Which components should be spiked before
  committing to the full implementation?

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
3. **Missing** — Gaps worth addressing even at this scale.
4. **Verdict** — Ship / Ship with changes / Rethink / Reject.

## Interaction Protocol

- Use `AskUserQuestion` one issue at a time. Never batch multiple questions
  into a single prompt.
- For HIGH-severity findings, surface them immediately and ask whether to
  continue or pause for discussion before proceeding to the next section.
- This skill is **read-only**. It does not create, modify, or delete any
  files.
- Use ASCII diagrams for data flow and component relationships where they
  clarify failure propagation or integration topology.

## Output Format

Structured review document with:

- Numbered sections matching the sequence above
- Severity tags on every finding: `[HIGH]`, `[MEDIUM]`, `[LOW]`
- Summary table of all findings at the end, grouped by severity
- Final verdict with rationale
