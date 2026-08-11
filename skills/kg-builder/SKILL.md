---
name: kg-builder
description: 'Designs and builds knowledge graphs from documents — ontology modeling with domain/range constraints, entity/relation/event extraction, entity resolution, provenance and supersession, and GraphRAG serving. Use when asked to "build a knowledge graph", "design an ontology", "extract entities and relations", "deduplicate entities", "entity resolution", "add GraphRAG", or "graph memory for an agent". NOT for multi-agent task graphs or agent orchestration, use task-decomposer.'
metadata:
  version: 1.0.0
  category: data
  tags: [knowledge-graph, ontology, entity-resolution, graphrag, provenance]
  difficulty: advanced
  phase: build
---

# KG Builder

A knowledge graph is a product with a schema, not a pile of triples. Quality comes from
pipeline order: model the domain **before** extracting, validate **during** extraction, fuse
**before** storing, and attach provenance to every fact from the first write.

This skill covers the full build — value test, ontology, extraction, quality gate, entity
resolution, serving, and maintenance — plus the boundary question that decides whether the
result is trustworthy: which stages are deterministic code and which are LLM judgment.

**Scope note.** This is about knowledge graphs — what an agent *remembers*. It is not about
task graphs, agent orchestration, or multi-agent topology.

## Reference Files

| File                                       | Contents                                                             | Load When            |
|---|---|---|
| `references/ontology-design.md`            | Competency questions, entity/relation types, domain/range, storage choice | Phase 1              |
| `references/extraction.md`                 | Source routing, NER/RE/EE prompt patterns, validation, failure modes | Phase 2              |
| `references/fusion.md`                     | Blocking, matching layers, merge policy, threshold bands             | Phase 3              |
| `references/serving.md`                    | GraphRAG retrieval, path queries, community summaries, query layer   | Phase 4              |
| `references/provenance-and-supersession.md` | Claim model, append-only updates, contradiction handling, audit trail | Phase 1 and Phase 4  |

## The deterministic / LLM boundary

Decide this before writing code. Code owns control flow, identity, validation, and merges.
The model gets contained judgments behind a typed interface, each with a measured baseline.

| Stage             | Deterministic (code)                              | LLM judgment (measure it)             |
|---|---|---|
| Source routing    | format detection, structured mapping              | —                                     |
| Entity extraction | span capture, type validation, dictionary matching | "what entities are in this text"      |
| Relation extraction | domain/range enforcement, endpoint checks       | "which relation does this sentence assert" |
| Quality gate      | sampling, scoring, thresholds                     | —                                     |
| Blocking          | key generation, candidate pairing                 | —                                     |
| Matching          | string/attribute/structure scoring                | ambiguous middle band only            |
| Merge             | canonical selection, edge union, lineage          | — (never let a model own a merge)     |
| Serving           | traversal, subgraph selection, serialization      | the agent's own reasoning             |

**Measure every LLM surface against a prompt-only baseline before trusting it.** This is not
theoretical caution. In a pre-registered real-model evaluation of an LLM-adjudicated dedup and
contradiction loop, the loop trailed a plain prompt-only baseline by 0.28–0.33 on detection and
safety across every provider cell tested. Adjudication that is not measured is decoration.

## Workflow

### Phase 1 — Design (do not skip)

1. **Value test.** A graph pays off when queries are multi-hop ("who worked with X on projects
   using Y"), when entities recur across documents, or when the relationships *are* the data.
   If every query is a single-hop lookup or an aggregation, use a table and stop here. Write
   the kill criterion down before continuing.
2. **Competency questions.** Write the 10–20 questions the graph must answer. These are the
   ontology's spec and its test suite. Anything you cannot path through the finished schema is
   a missing type or relation.
3. **Ontology.** 5–15 entity types, 10–30 relation types, each relation with explicit domain
   and range. Precise verb names (`ACQUIRED`, `DEPENDS_ON`) — never `RELATED_TO`. Keep it in
   `ontology.yaml` as the single source of truth; every extraction prompt embeds it verbatim.
4. **Storage and identity.** Choose property graph (default), RDF/OWL (interop, description-logic
   reasoning), or typed edges in SQLite (<50K nodes). Decide *now* how time and provenance attach
   to every fact — retrofitting provenance after fusion is effectively impossible.

Validate the schema before extracting anything:

```bash
uv run scripts/validate_ontology.py ontology.yaml
```

### Phase 2 — Extract

5. **Route by source type.** Structured sources (databases, CSVs, APIs) map column → type in
   deterministic code with no model involved. Semi-structured sources (HTML tables, infoboxes)
   get per-layout parsers. Only unstructured text enters the LLM pipeline. Running NLP over
   already-structured data is the classic waste.
6. **Entities.** Dictionaries and exact rules first for closed vocabularies — free,
   deterministic, perfect precision. LLM extraction for open text, with the ontology in the
   prompt. Always capture surface form, canonical guess, type, source pointer, and confidence.
7. **Relations.** Extract only between entities that already passed step 6; never let relation
   extraction invent endpoints. Constrain output to the ontology's relation list and **validate
   domain/range in code**. Require a verbatim evidence quote that *asserts* the relation —
   co-occurrence is not assertion ("Musk discussed Twitter" is not `OWNS`).
8. **Events.** For dynamic domains, extract events as first-class nodes (trigger + typed
   arguments + time), never flattened into pairwise edges — flattening loses which acquisition
   happened at which price.

### Phase 3 — Consolidate

9. **Quality gate.** Sample 50 items and score entity precision and relation precision before
   fusing anything. Target ≥90% precision. Fix the prompt or the rules, then re-run — never
   hand-patch the output. Recall improves with more passes; bad precision poisons the graph
   permanently.
10. **Fusion.** Blocking → matching → merge. Blocking avoids O(n²) comparison; matching scores
    string, attribute, and **structural** evidence (two `J. Smith` nodes sharing three coauthors
    and an affiliation are one person; identical names with disjoint neighborhoods are not);
    merge policy is deterministic code that keeps the canonical name, unions aliases and edges,
    preserves conflicting values with provenance, and records `merged_from` for undo.
    An erroneous merge is far more damaging than a missed one — it silently fuses two entities'
    entire edge sets. Auto-merge only above the high band; queue the middle for review.

Check the blocking strategy against labeled pairs before running it at scale:

```bash
uv run scripts/blocking_report.py candidates.jsonl --labels matches.jsonl
```

### Phase 4 — Serve and maintain

11. **Serving.** Entity-link the query, expand 1–2 hops, serialize the subgraph as compact
    `(head)-[REL {time, source}]->(tail)` lines grouped by head. For multi-hop questions retrieve
    *paths* between the query's entities, not neighborhoods around each — the path is the answer
    skeleton. Cluster and pre-summarize for "what are the themes" questions.
12. **Maintenance.** New facts supersede rather than overwrite: keep the prior claim with
    `status`, `supersedes`, and validity interval. When a new fact contradicts a stored one, keep
    both with time and provenance and prefer the newer at retrieval. Re-run fusion periodically —
    unmaintained memory graphs rot exactly like unfused extractions.

## Output

Deliver these artifacts, in this order:

| Artifact             | Contents                                                             |
|---|---|
| `competency.md`      | The 10–20 questions, each marked answerable or blocked                |
| `ontology.yaml`      | Entity types, relation types with domain/range, event argument schemas |
| `extraction/`        | Per-source-type prompts and deterministic mappings                    |
| `quality-report.md`  | Sampled entity and relation precision, with sample size and method    |
| `fusion-report.md`   | Blocking reduction ratio, pair recall, merge counts per band          |
| The graph            | Nodes and edges, every one carrying `source`, `extracted_at`, confidence |

Report precision as a sampled estimate with its sample size. A precision number without a
stated sampling method is a vibe.

## Working rules

- **Schema first, always.** Extraction without an ontology produces a word cloud with arrows.
  If the user resists schema design, induce a minimal 5-type ontology from three sample
  documents and show it for approval — never skip to extraction.
- **Provenance on every fact.** `source`, `extracted_at`, confidence. Non-negotiable; fusion and
  trust both depend on it.
- **Pilot before scale.** Run 10 documents through all four phases first. The pilot exposes
  ontology gaps at 1% of the cost.
- **Never auto-accept an induced schema.** LLM-proposed ontologies overfit their sample
  documents. Prune to the minimal set that answers the competency questions.
- **The LLM is stage machinery, not the pipeline.** It slots into extraction and the ambiguous
  matching band. The surrounding schema, validation, and merge policy are what make the output
  a knowledge graph rather than a transcript.

## Errors and troubleshooting

| Symptom                              | Cause                                    | Fix                                                        |
|---|---|---|
| Graph full of `Concept`/`Thing` nodes | Extracted without an ontology            | Phase 1 first, then re-extract                              |
| Same person appears as four nodes     | No canonical-form rule; fusion skipped   | Define the rule in `ontology.yaml`; run Phase 3             |
| Confident but wrong relations         | Co-occurrence treated as assertion       | Require evidence quotes; enforce domain/range in code       |
| Events flattened into edge soup       | No event argument schema                 | Promote events to first-class nodes with typed arguments    |
| Precision collapses as sources grow   | One prompt drifting across document types | Per-source-type prompts; run the quality gate per source    |
| Fusion merges two real entities       | Threshold too low; no structural layer   | Raise the auto-merge band; add neighborhood comparison; undo via `merged_from` |
| Multi-hop answers are wrong but fluent | Unfused duplicates break paths          | Re-run fusion; paths cannot cross duplicate boundaries      |
| GraphRAG returns noise                | Hop expansion too wide                   | Cap at 2 hops, or re-rank; retrieve paths, not neighborhoods |
| Retrieval is stale after updates      | Facts overwritten instead of superseded  | Adopt the claim model in `references/provenance-and-supersession.md` |
