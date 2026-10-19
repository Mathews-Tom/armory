# Domain context format and destinations

Load before locating or editing a model. These conventions match Armory's project-context setup; this local reference is sufficient without installing that package.

## Discover rather than scaffold

1. Read the repository's instructions and `docs/agents/domain.md` when present. That file describes single-context or multi-context layout and ADR lookup routes. Read any declared domain source rather than assuming root files are authoritative.
2. If `CONTEXT-MAP.md` exists, follow its relevant context links. Resolve a term inside the owning context; the same word can have distinct explicit meanings in different contexts. Read the map's cross-context relationship before assuming shared identity or cardinality.
3. Otherwise use an existing root `CONTEXT.md` if consistent with the repository's domain instructions. If root and mapped glossaries coexist, respect the recorded purpose of each; ask about conflicting ownership before writing.
4. A missing mapped target or stale pointer is a concrete route problem. Confirm the intended destination; do not invent a replacement layout. A legacy `GLOSSARY.md` route is existing human content, not permission to rename or duplicate it. Agree any migration separately.
5. With no established model, use one root `CONTEXT.md` only after the first project-specific term is agreed. Introduce context-local files and a map only when distinct business contexts are confirmed and there is agreed content for the destinations being added. Do not create empty contexts.

Record the selected paths and their routing evidence. Missing code does not block an agreed vocabulary entry, but code/model consistency stays unverified. Missing write authority produces an unapplied change in the response, not a filesystem write.

## Vocabulary structure

Use the existing heading structure where possible. For a newly warranted single-context file, this is a concrete example, not a scaffold to copy before agreement:

```markdown
# Ordering Context

Ordering records customers' requests for goods and the remaining quantity to fulfill.

## Language

**Order**:
A customer's request for one or more quantities of products.
_Avoid_: transaction, invoice

**Line Cancellation**:
An accepted reduction in the quantity still requested on one order line.
_Avoid_: refund, void invoice

## Relationships

- An **Order** contains one or more **Order Lines**.
- Each **Order Line** belongs to exactly one **Order**.
- A **Line Cancellation** concerns exactly one **Order Line** and a positive quantity no greater than its remaining requested quantity.
- An **Order Line** may have zero or more **Line Cancellations** over its lifetime.

## Example Dialogue

> **Dev:** "An unfulfilled line requests three units; one is cancelled. Is the order cancelled?"
> **Domain owner:** "No. Two units remain requested; no refund is implied."

## Flagged Ambiguities

- "Cancellation" previously conflated a line-quantity reduction with ending the entire order. Use **Line Cancellation** for the former; whether ending an entire order is a separate operation remains unresolved.
```

Every definition is one sentence describing a project-specific concept, not a method or database table. `_Avoid_` lists context-specific ambiguous synonyms, not words banned in every business context. Include generic engineering terms only elsewhere, not in this vocabulary. Cardinalities express business limits; storage mechanisms, API flags and migration plans do not belong here.

## Multi-context routes

A map points to real context-local definitions and records actual context relationships. For a confirmed ordering/billing split:

```markdown
# Context Map

## Contexts

- [Ordering](./src/ordering/CONTEXT.md) - owns requested and remaining order quantities
- [Billing](./src/billing/CONTEXT.md) - owns invoicing and amounts owed

## Relationships

- **Ordering -> Billing**: Ordering communicates accepted line cancellations; Billing determines any invoice adjustment under its own rules.
```

Use the repository's actual locations rather than creating these example paths by default. An order-line cancellation and an invoice adjustment need not be the same object or share a one-to-one relationship. Establish such constraints with scenarios and agreement.

## Domain lookup note

If a new route must be recorded and no existing lookup note supplies it, create or extend only the relevant content in `docs/agents/domain.md` after agreement. A concrete multi-context note could be:

```markdown
# Domain Docs

Use the root CONTEXT-MAP.md to find Ordering and Billing vocabulary and their relationship. Edit canonical terms only in their owning context's CONTEXT.md.

## ADR Lookup

Global architecture decisions are in docs/adr/. Consult a context's local docs/adr/ only where it already exists or the repository declares it. Domain modeling does not create or write ADRs.
```

Single-context notes instead point to the root `CONTEXT.md`. Discover and preserve existing ADR paths; do not create ADR directories to make the note true. Updating instruction files, issue-tracker setup and triage conventions is outside this skill.

## Preservation and unresolved work

Fresh-read before each edit. Replace only the agreed term, affected relationship, relevant ambiguity or necessary link. Preserve neighboring human notes, order, comments and formatting. If another edit changes a relevant claim, stop that write and reconcile; do not regenerate the file from this example.

Keep unresolved business questions in `Flagged Ambiguities` of an existing suitable context, with the alternative meanings and discriminating scenario. Do not insert a proposed definition into `Language` until accepted. If no context file exists and nothing has been agreed, return the unresolved question in chat and leave the filesystem unchanged. Implementation contradictions may be summarized as unresolved domain questions there, but source-level repair plans and architecture decisions remain in the session/handoff, not canonical language.
