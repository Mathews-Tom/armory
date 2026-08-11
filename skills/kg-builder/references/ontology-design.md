# Ontology Design and Storage Choice

The schema is the product. Everything downstream — extraction prompts, validation, fusion
thresholds, query shape — is derived from it. Design it before touching data.

## Contents

- [The value test](#the-value-test)
- [Competency questions](#competency-questions)
- [Building the type system](#building-the-type-system)
- [Schema design rules](#schema-design-rules)
- [Storage and representation](#storage-and-representation)
- [The ontology file](#the-ontology-file)
- [Ontology induction](#ontology-induction)

## The value test

A graph earns its maintenance cost under three conditions:

1. **Multi-hop queries.** "Which engineers contributed to services that had incidents last
   quarter" traverses three types. A table would need three joins written by hand per question.
2. **Entities recur across documents.** The same supplier appears in 400 contracts under six
   spellings. Resolution is the value; the graph is where resolved identity lives.
3. **Relationships are the data.** Dependency chains, citation networks, ownership structures —
   the edges carry the meaning, not the nodes.

Counter-indications, each of which should stop the project:

- Every query is a single-hop lookup by key. Use a table.
- Every query is an aggregation ("total spend by region"). Use a warehouse; graphs are bad at
  aggregation.
- The corpus is small and static and one person answers questions from it. Use search.

Write the kill criterion into `competency.md` before proceeding, so the decision is auditable
later when someone asks why this exists.

## Competency questions

Write 10–20 real questions in the user's own words. They serve three jobs at once: they are the
ontology's specification, its test suite, and the acceptance criteria for the finished graph.

Rules:

- Real questions from real users, not questions invented to fit a schema you already imagined.
- Include at least three multi-hop questions. If you cannot write three, revisit the value test.
- Mark each question with the answer shape it needs: single node, list, path, subgraph, or
  aggregate. Aggregates are a signal that part of this belongs in a database.

Walk every question through the finished schema on paper. Any question you cannot path through
is a missing entity type or a missing relation — not a query problem.

## Building the type system

1. **Entity types** — extract the nouns the competency questions turn on. Start with 5–15. Each
   type needs a one-line definition and 2–3 real examples from the corpus. If you cannot produce
   two real examples, the type is speculative; drop it.
2. **Relation types** — extract the verbs. Start with 10–30. Every relation carries an explicit
   **domain** and **range**: `EMPLOYED_BY: Person → Organization`. Note cardinality where it
   constrains extraction (a Person has one birthplace; a Person has many employers over time).
3. **Attributes versus entities** — if it has its own relationships, it is an entity ("City" has
   a country and a population). If it is a value you filter or sort on, it is an attribute
   ("founding year").
4. **Event types** — for dynamic domains, define per-event-type argument schemas:
   `Acquisition: {acquirer, target, price, date}`. Events are nodes, not edges.
5. **Type hierarchy only where queries need it.** `Company ⊂ Organization` is worth having if
   some questions span all organizations. Otherwise stay flat — flat schemas are easier to
   extract against and easier to validate.

## Schema design rules

- **Precise verb names.** `ACQUIRED`, `CITES`, `DEPENDS_ON`. Never `RELATED_TO`, `HAS_LINK`,
  `ASSOCIATED_WITH`. A vague relation makes every downstream query ambiguous and makes
  domain/range validation useless.
- **Merge types that are always queried together.** Two types that never appear apart in a
  competency question are one type with an attribute.
- **Split a type that needs disambiguating qualifiers.** If `CONTRIBUTED_TO` keeps needing
  `role: "author" | "editor"`, make two relation types instead.
- **Define the canonical-form rule at modeling time.** Full legal name? Lowercased? Which
  language? Fusion enforces whatever rule is stated here, so an unstated rule means fusion has
  nothing to enforce.
- **Every fact carries time and provenance.** Decide the mechanism now — see
  [`provenance-and-supersession.md`](provenance-and-supersession.md). In property graphs these
  are edge properties; in RDF use RDF-star or reification; in SQLite they are columns. Adding
  them after fusion is effectively impossible because the merges have already discarded the
  information.

## Storage and representation

| Representation                          | Choose when                                                                            | Cost                                                                 |
| --------------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| **Property graph** (Neo4j, Kùzu, Memgraph) | Default for products and agent memory. Arbitrary key-value properties on nodes and edges. | No formal semantics; consistency is your code's job.                  |
| **RDF / OWL**                           | Interop with published ontologies, standards compliance, description-logic reasoning (subsumption, consistency checking). | Verbose; edge properties need RDF-star or reification; heavier tooling. |
| **Typed edges in SQLite or JSON**       | Under ~50K nodes, single application, agent-local memory.                               | Query power capped; migrate when multi-hop queries get slow or frequent. |

### The query layer is part of the design

Choosing a store is not choosing a query strategy. Decide, before extraction:

- **Which traversals are hot.** Index the entry points those traversals start from — usually
  canonical name and external identifier.
- **How deep traversals may go.** Set a hop cap in code. Unbounded traversal over a graph with
  one hub node returns the whole graph.
- **What the agent-facing surface is.** Deterministic, parameterized traversals beat handing a
  model raw query-language access: they are testable, cacheable, and cannot be prompt-injected
  into scanning the whole store.
- **Where the embedding index lives.** If fusion or retrieval uses vector similarity, the index
  is derived state. It must be rebuildable from the graph, and rebuild must be cheap enough to
  run after every ingest.

### On graph reasoning and embeddings

Representation learning (TransE and its successors) and rule-based reasoning are real parts of
the knowledge-graph field, and they are largely **not** what an agent memory graph needs. Link
prediction answers "which edges are probably missing" — a research question. Agent memory needs
"which facts do I actually have, and where did they come from." Reach for embeddings for
*blocking* during fusion and for entity linking at query time. Reach for rule-based reasoning
(transitive closure, type inference) when the ontology has a real hierarchy and the queries need
it. Do not add either because the literature features them.

## The ontology file

Keep one `ontology.yaml` as the single source of truth. Every extraction prompt embeds it
verbatim; the validator checks it; the fusion merge policy reads the canonical-form rules from it.

```yaml
canonical_form:
  Person: "full name as first written, title stripped"
  Organization: "full legal name, no suffix normalization"

entities:
  Person:
    desc: an individual engineer, manager, or author
    examples: [Jane Doe, A. Kowalski]
  Service:
    desc: a deployable software unit with an owner
    examples: [payments-api, billing-worker]
  Incident:
    desc: a production failure with a start time
    examples: [INC-4012]

relations:
  CONTRIBUTED_TO:
    domain: Person
    range: Service
  AFFECTED:
    domain: Incident
    range: Service
    attrs: [severity]

events:
  Incident:
    trigger: outage or alert
    args: [service, start_time, resolved_time, severity]
```

Three entity types, two relations, one event type fully answer "which engineers contributed to
services that had incidents last quarter." Resist adding a type until a competency question
demands it.

Validate it before extracting:

```bash
uv run scripts/validate_ontology.py ontology.yaml
```

The validator rejects relations whose domain or range names an undeclared entity type, vague
relation names, event argument schemas with no trigger, and entity types with no examples.

## Ontology induction

Semi-automatic schema induction is useful as a *draft generator*, never as a decision:

1. Give a model 3–5 representative documents.
2. Ask it to propose entity and relation types **with a verbatim evidence quote for each**.
3. Prune manually to the minimal set that answers the competency questions.

Induced ontologies overfit their sample documents — they mint a type for whatever the first five
documents happened to emphasize. The evidence-quote requirement makes the overfit visible: a
proposed type supported by one quote from one document is not a type.
