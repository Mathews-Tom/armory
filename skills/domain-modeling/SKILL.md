---
name: domain-modeling
description: Use when domain terms or entity relationships are ambiguous, existing definitions conflict with a concrete business scenario, or code contradicts an agreed domain model. Not for reading an unchanged glossary, scaffolding generic project context, implementing a fix, or writing an ADR.
metadata:
  version: 1.0.0
  category: development
  tags: [domain-modeling, vocabulary, bounded-contexts, cardinality]
  difficulty: intermediate
  phase: define
---

# Domain Modeling

Challenge the model with the user, not just its wording. Capture agreed project-specific language as it crystallizes; keep disagreement visible instead of turning a plausible interpretation into fact.

## Collaboration contract

- Bound the session to the user's named business question, terms and contexts. Establish the desired outcome (for example, distinguish cancellation from refund for an ordering change); ask for a boundary only when it is missing. Adjacent questions may be deferred explicitly rather than expanding the session.
- Use repository evidence for what can be inspected. Ask the user or domain owner for business intent that the repository cannot settle. Present one material ambiguity and a concrete discriminating scenario at a time; offer precise alternatives without presuming consent.
- Read context and relevant code; edit only agreed domain entries and necessary lookup pointers when authorized. This skill grants no implementation, migration, tracker, installation or ADR-writing authority. A read-only session returns exact proposed changes instead.
- Finish when every in-scope term, relationship and discovered contradiction is either agreed and captured, or explicitly unresolved/deferred with the question, affected behavior and needed authority/evidence. An unanswered question is not a resolved model.

## References

| Load when | Local reference | Supplies |
| --- | --- | --- |
| Locating, creating or editing domain context | [Context format](references/context-format.md) | Existing-layout discovery, lazy writes and canonical vocabulary format |
| A term is overloaded, a relationship is uncertain, or code disagrees | [Scenario review](references/scenario-review.md) | Concrete cardinality probes and a worked ordering/billing disagreement |
| An implementation choice arises during modeling | [Decision boundary](references/decision-boundary.md) | All-three ADR-candidate gate and authorized handoff |

For source attribution or deliberate upstream updates, read [provenance](references/upstream/provenance.md). Licensing is in the package's LICENSE file. No external package file is required to use this skill.

## 1. Locate the model and bound the evidence

Read the context-format reference before choosing a destination. Inspect actual repository instructions and `docs/agents/domain.md`, then the declared `CONTEXT.md` or `CONTEXT-MAP.md` and relevant context-local files. Follow existing routes and ADR lookup conventions rather than guessing directory names or copying an unrelated project's layout. A legacy or conflicting route needs an explicit destination decision, not a second glossary.

Inventory the in-scope terms, their current definitions and ownership, and the relevant source paths. Read only the implementations, schemas, callers and tests needed to test the disputed rule; use repository navigation/configuration to discover those paths. Code is evidence of current behavior, not automatically the domain authority. If code is unavailable, name the missing source and leave implementation agreement unverified while continuing vocabulary work.

**Complete when:** the session boundary, authoritative context destinations, edit authority and available/missing evidence are explicit. If a context route is ambiguous, pause only the affected writes and continue independent reasoning.

## 2. Challenge terms and relationships

Load scenario review for this branch. Start from an actual usage, not a list of generic definitions. Compare it with the current model and immediately surface a conflict: “Ordering defines cancellation as ending the whole order; does cancelling one unit of a three-unit line end the order too?”

For every ambiguous in-scope term, contrast the competing meanings with a specific example and propose a canonical name for each distinct concept. For every disputed relationship, probe both directions, zero/one/many, identity/ownership and relevant lifecycle limits. Distinguish units from lines, requests from completed effects, and context-local meanings from supposed global synonyms. Challenge only applicable boundaries; record which examples determine the rule.

Where a user statement disagrees with code, give the source location and observed rule, the claimed domain rule and the smallest scenario where they diverge. Ask whether the domain model is stale, the implementation is wrong, or the concepts differ. Do not silently choose code or conversation as the winner. Record the disposition; implementation repair remains separate work.

**Complete when:** each in-scope ambiguity and relationship has discriminating examples and either an agreed definition/cardinality or a precise unanswered question. Each contradiction has an evidence-backed disposition or an explicit unresolved status; code inspection alone is not an execution claim.

## 3. Capture each agreement inline

As soon as a definition is agreed, read its destination afresh and make a narrow edit before moving to the next ambiguity. Use the local context-format reference: one-sentence canonical terms under `Language`, applicable `_Avoid_` synonyms, cardinalities under `Relationships`, and domain disagreements or corrections under `Flagged Ambiguities`. Keep scenario evidence in `Example Dialogue` when it adds a boundary the definition alone cannot express.

Preserve human prose, annotations, existing definitions outside the agreement, and unrelated sections byte-for-byte. If fresh content conflicts with the agreement, reconcile that conflict with the user instead of overwriting it. Create a context file only after its first agreed project-specific term; create a context map only for confirmed separate contexts; create/update `docs/agents/domain.md` only when a real lookup route needs recording. Do not scaffold empty files or reformat a document wholesale.

Record unresolved questions in an existing appropriate `Flagged Ambiguities` section when authorized; if no domain artifact exists yet, keep them in the session response rather than creating an empty glossary. Keep implementation details and repair proposals outside canonical vocabulary. If an implementation decision arises, read the decision-boundary reference: it may qualify for a candidate handoff, never an ADR written here.

**Complete when:** every agreement reached so far is captured in its correct context (or provided as a clearly unapplied patch in a read-only session), all affected context links remain coherent, and existing human content survives. Unagreed proposals are labeled as such, not inserted as canonical definitions.

## 4. Close with an accounted model

Return the scoped terms/relationships with their resolved or unresolved status, discriminating scenarios and confirmed cardinalities; list changed context paths or unapplied patches. Account for every code/model contradiction with its source and disposition. Include deferred questions and exact missing evidence/authority; identify follow-on implementation work without performing it. Surface an ADR candidate only if the decision-boundary gate passes, separately from the domain definitions.

A glossary scaffold or terminology summary without challenge, cardinality and contradiction accounting is not completion. Authored examples and inspected code are not proof of executed behavior or fresh-model effectiveness.
