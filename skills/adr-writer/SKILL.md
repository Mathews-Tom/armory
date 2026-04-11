---
name: adr-writer
description: 'Generates Architecture Decision Records capturing context, rationale, alternatives, and consequences in numbered status-tracked format. Triggers on: "write an ADR", "document this decision", "architecture decision record", "decision record", "design decision", "ADR for".'
metadata:
  version: 1.1.1
  category: operations
  tags: [architecture, decision-record, documentation, adr]
  difficulty: intermediate
  phase: plan
---

# ADR Writer

Captures architecture decisions in a lightweight, structured format that preserves
context, rationale, alternatives, and consequences. Produces numbered ADR documents with
proper status lifecycle — preventing the "why did we do it this way?" problem when
revisiting decisions months later.

## Reference Files

| File                                  | Contents                                                       | Load When                             |
| ------------------------------------- | -------------------------------------------------------------- | ------------------------------------- |
| `references/adr-template.md`          | Standard ADR template with field explanations and examples     | Always                                |
| `references/status-lifecycle.md`      | Status transitions, supersession rules, deprecation process    | ADR references existing decisions     |
| `references/context-capture.md`       | Techniques for eliciting and documenting decision context      | Complex or multi-stakeholder decision |
| `references/alternatives-analysis.md` | Framework for evaluating and documenting rejected alternatives | Multiple options being considered     |

## Prerequisites

- A decisions directory (typically `docs/adr/` or `docs/decisions/`)
- Understanding of the decision being made (may require clarifying questions)

## Workflow

### Phase 1: Identify the Decision

1. **What choice was made?** — Extract the core architectural decision. If the user
   describes a problem, help them articulate the decision that resolves it.
2. **Is this decision-worthy?** — ADRs are for decisions that:
   - Affect system structure (component boundaries, data flow, API design)
   - Are hard to reverse (technology choice, database schema, protocol)
   - Have non-obvious tradeoffs (multiple viable alternatives)
   - Will be questioned later (the "why" will be forgotten)
3. **What triggered this decision?** — New requirement, performance issue, scaling
   concern, security audit finding, tech debt, team growth.

### Phase 2: Capture Context

Document the forces that shaped this decision:

1. **Requirements** — What functional or non-functional requirements drive this?
2. **Constraints** — What limits the solution space? (budget, timeline, team expertise,
   existing infrastructure, regulatory requirements)
3. **Current state** — What exists today? What is the pain point?
4. **Stakeholders** — Who is affected by this decision? Who needs to agree?

### Phase 3: Enumerate Alternatives

For each alternative considered:

1. **Name it clearly** — "PostgreSQL" not "Option A"
2. **List concrete pros** — Specific, measurable benefits
3. **List concrete cons** — Specific, measurable drawbacks
4. **State the rejection reason** — Why this alternative was not chosen. Be specific:
   "Does not support our required throughput of 10K ops/sec" not "Too slow."

### Phase 4: Document the Decision

State the chosen option and why it was selected given the context and constraints.
The decision should follow logically from the context + alternatives analysis.

### Phase 5: Project Consequences

Document what this decision makes easier and harder:

1. **Positive consequences** — What improves?
2. **Negative consequences** — What tradeoffs are accepted? What tech debt is incurred?
3. **Neutral consequences** — Side effects that are neither good nor bad.

### Phase 6: Assign Metadata

1. **Number** — Sequential: ADR-001, ADR-002, etc. Check existing ADRs for the next number.
2. **Status** — Initial status is usually "Proposed" or "Accepted"
3. **Date** — Date the ADR was written
4. **Author** — Who authored this ADR
5. **Supersedes/Superseded-by** — Link to related ADRs if this replaces an earlier decision

## Output Format

```text
# ADR-{NNN}: {Descriptive Title}

**Status:** {Proposed | Accepted | Deprecated | Superseded by ADR-XXX}
**Date:** {YYYY-MM-DD}
**Author:** {name}
**Supersedes:** {ADR-XXX (if applicable)}

## Context

{What situation requires a decision? What constraints exist? What forces are at play?
Write in present tense — describe the situation as it exists at decision time.}

## Decision

{State the decision clearly and concisely. "We will use X for Y because Z."
One to three sentences. The reader should understand the decision without reading
the rest of the document.}

## Alternatives Considered

### {Alternative 1 Name}
- **Pros:** {specific benefits}
- **Cons:** {specific drawbacks}
- **Rejected because:** {concrete, specific reason tied to context}

### {Alternative 2 Name}
- **Pros:** {specific benefits}
- **Cons:** {specific drawbacks}
- **Rejected because:** {concrete, specific reason tied to context}

## Consequences

### Positive
- {Concrete benefit 1}
- {Concrete benefit 2}

### Negative
- {Concrete tradeoff 1 — acknowledged and accepted}
- {Technical debt incurred — with plan to address if applicable}

### Neutral
- {Side effect that is neither positive nor negative}

## References

- {Link to related issue, discussion, document, or prior ADR}
```

## Calibration Rules

1. **Context is king.** The Context section is the most important part. A decision
   without context is just an assertion. Future readers need to understand WHY, not
   just WHAT.
2. **Specific rejection reasons.** "Not suitable" is not a rejection reason. "Does not
   support transactions across partitions, which we need for order processing" is.
3. **Honest consequences.** Every decision has downsides. If the Negative section is
   empty, the analysis is incomplete. Push the user to articulate tradeoffs.
4. **Present tense for context.** Write the Context section in present tense — it
   captures the world as it was when the decision was made.
5. **One decision per ADR.** If multiple decisions are interrelated, write separate ADRs
   and cross-reference them. Do not bundle unrelated decisions.
6. **Immutable after acceptance.** Accepted ADRs are not edited. If a decision changes,
   write a new ADR that supersedes the old one. This preserves the historical record.

## Error Handling

| Problem                                      | Resolution                                                                                                |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| User cannot articulate alternatives          | Help them brainstorm by asking: "What else could you have done? What did you consider and reject?"        |
| Decision is trivial (no real alternatives)   | Suggest it doesn't need an ADR. ADRs are for non-obvious decisions with tradeoffs.                        |
| Decision already made, no context remembered | Reconstruct context from code, PRs, commit history. Note reconstructed context as "best available."       |
| Existing ADR numbering scheme unknown        | Check `docs/adr/` or `docs/decisions/`. If no directory exists, suggest creating one and starting at 001. |
| Decision scope is too broad                  | Split into multiple focused ADRs. One for the database choice, one for the caching strategy, etc.         |

## When NOT to Write an ADR

Push back if:

- The decision is easily reversible (library version, code formatting rules) — use a comment or config instead
- The decision is a standard practice with no alternatives (use HTTPS, validate input) — not decision-worthy
- The user wants to document implementation details — ADRs are for WHY decisions, not HOW implementations
- The decision has already been superseded — write the new ADR, not the old one
