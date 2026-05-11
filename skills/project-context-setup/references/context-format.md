# Domain Context Format

Use domain context files to define project-specific language for agents. The goal is shared
vocabulary, not implementation documentation.

## Single-Context Repo

Use one root `CONTEXT.md`:

```markdown
# Project Context

One or two sentences describing the business or product context.

## Language

**Order**:
A customer request to buy one or more products.
_Avoid_: purchase, transaction

**Customer**:
The person or organization that owns an order.
_Avoid_: user, account

## Relationships

- A **Customer** can have many **Orders**
- An **Order** belongs to exactly one **Customer**

## Example Dialogue

> **Dev:** "Can an **Order** exist without a **Customer**?"
> **Domain expert:** "No. Guest checkout still creates a lightweight **Customer**."

## Flagged Ambiguities

- "account" was used for both **Customer** and auth **User**. Use **Customer** for commerce ownership and **User** for login identity.
```

## Multi-Context Repo

Use a root `CONTEXT-MAP.md` that points to context-local glossaries:

```markdown
# Context Map

## Contexts

- [Ordering](./src/ordering/CONTEXT.md) - receives and tracks customer orders
- [Billing](./src/billing/CONTEXT.md) - invoices and payment collection

## Relationships

- **Ordering -> Billing**: Ordering emits `OrderPlaced`; Billing consumes it to create invoices
```

## Rules

- Include only project-specific domain terms.
- Keep definitions to one sentence.
- Prefer the canonical term and list ambiguous synonyms under `_Avoid_`.
- Record relationships with cardinality where it clarifies behavior.
- Add flagged ambiguities when a term has been overloaded or corrected.
- Do not define generic engineering terms such as timeout, route, service, enum, or cache.
- Update context files when planning, debugging, TDD, or architecture work resolves new terminology.
