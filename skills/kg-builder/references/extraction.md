# Extraction: Sources, Entities, Relations, Events

Extraction is where cost is spent and where precision is won or lost. The ontology constrains
every step; validation runs in code, not in the prompt.

## Contents

- [Route by source type](#route-by-source-type)
- [Entity extraction](#entity-extraction)
- [Relation extraction](#relation-extraction)
- [Event extraction](#event-extraction)
- [Prompt patterns](#prompt-patterns)
- [Chunking](#chunking)
- [The quality gate](#the-quality-gate)
- [Failure modes](#failure-modes)

## Route by source type

Match the method to the structure of the source. Running a language model over data that is
already structured is the most common and most expensive mistake in this pipeline.

| Source                                              | Method                                                                      | Model involved      |
| --------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------- |
| Structured — databases, CSVs, APIs                   | Direct mapping: column → ontology type, written once per source              | No                  |
| Semi-structured — HTML tables, infoboxes, wikis, JSON | Parser per layout family                                                     | Only for messy cells |
| Unstructured — prose, transcripts, PDFs, tickets     | Entity → relation → event passes                                             | Yes                 |

Write the structured mappings first. They are cheap, perfectly precise, and they populate the
canonical entity set that unstructured extraction will later link against — which measurably
improves the unstructured pass, because most of its entities are now dictionary hits.

## Entity extraction

Two mechanisms, in this order:

1. **Dictionaries and exact rules** for closed vocabularies you already possess: product names,
   team roster, ticker symbols, ontology enum values, anything from the structured pass. Exact
   match beats any model — free, deterministic, perfect precision.
2. **LLM extraction** for open-ended text, with the ontology's types, definitions, and examples
   in the prompt.

Always capture, per mention:

| Field       | Why                                                        |
| ----------- | ----------------------------------------------------------- |
| `surface`   | The literal string as written — needed for alias building   |
| `canonical` | Best-guess normalized form under the ontology's rule        |
| `type`      | Must be an ontology type; anything else is rejected         |
| `source`    | Document id plus character span or sentence index           |
| `evidence`  | Verbatim sentence containing the mention                    |
| `confidence`| high / medium / low — drives the quality gate sample         |

Two classical error classes survive into the LLM era and cause most of the damage:

- **Nested and discontinuous mentions.** "University of California, Berkeley professor John
  Smith" contains an organization inside a person context. Models routinely emit one span
  covering both.
- **Type ambiguity.** "Apple", "Mercury", "Ford" — the type depends entirely on context.

Both are mitigated by the same requirement: make the model quote the evidence sentence. Quoting
forces the model to attend to the disambiguating context rather than the string alone.

## Relation extraction

Three constraints, each of which removes a whole class of error:

1. **Only between entities that passed the entity pass.** Never let relation extraction invent
   an endpoint. This single rule stops compounding errors — a hallucinated entity that acquires
   three hallucinated relations becomes four wrong facts instead of one.
2. **Constrained to the ontology's relation list, validated in code.** An `EMPLOYED_BY` edge
   from Organization → Organization is rejected by the domain/range check without a model
   round-trip. Do the check in code; a prompt instruction is not a validation.
3. **Evidence must assert, not merely co-occur.** Models happily assert whatever the prior
   suggests when two entities appear in one sentence. "Musk discussed Twitter" is not `OWNS`.
   Require a verbatim quote and reject any edge whose quote does not state the relation.

Keep a `candidate_relations` side-list for repeated relations the ontology does not model.
Review it weekly and promote real ones into the ontology — forcing them into an existing wrong
type is how a schema silently degrades into `RELATED_TO`.

## Event extraction

Use when the domain is dynamic: news, incidents, transactions, funding rounds, deployments.

An event is a **trigger** (the word or phrase signalling it) plus **typed arguments**
(participants, time, place, values) plus an **event type** from the ontology.

Events are first-class nodes with edges to their arguments. Never flatten a four-argument event
into six pairwise edges — the flattening loses which acquisition happened at which price, and
the information cannot be recovered afterwards.

Reject any event missing its trigger evidence. A trigger-less event is an inference the model
made, not a fact the source stated.

**Event-to-event edges.** When the question is "what leads to what" rather than "what is related
to what", model causal, temporal, and conditional edges between event nodes. Distinguish
*reported as causing* from *observed to co-occur* with separate relation types — the source
asserting causation is itself a fact with provenance.

## Prompt patterns

One pass per stage. A single mega-prompt that extracts entities, relations, and events together
produces worse output at every stage and makes failures impossible to attribute.

```text
You are extracting knowledge for a graph with this ontology:
<ontology>          # verbatim contents of ontology.yaml

From the text below, extract every entity matching the ontology types.
For each, emit: {surface, canonical, type, evidence, confidence}

Rules:
- Only types declared in the ontology. Recurring concepts with no matching
  type go in a separate "candidates" list — do not force them into a type.
- evidence must be a verbatim quote from the text containing the mention.
- Do not merge distinct mentions; deduplication happens in a later stage.

<text>
```

The relation pass adds the recognized-entity list, the relation inventory with domain and range,
and one additional rule: *assert only relations the evidence sentence states directly.*

The event pass adds the per-event-type argument schemas and the rule: *reject any event whose
trigger you cannot quote.*

## Chunking

- Overlap chunks by 10–15% so entities on sentence boundaries survive.
- Extract per chunk; do not attempt cross-chunk resolution here. Fusion reconciles.
- Keep the chunk's document id and offset on every extracted item — the source pointer must
  survive chunking or provenance is lost at the first step.
- Chunk on structural boundaries (sections, tickets, messages) when they exist. Fixed-size
  chunking over structured prose splits facts across boundaries for no benefit.

## The quality gate

Run before fusion, never after. Fusion over bad extractions produces a confidently wrong graph
that is expensive to unwind.

1. Sample 50 extracted items, stratified across source types and confidence bands.
2. Score **entity precision**: is the entity real, and is its type correct?
3. Score **relation precision**: does the quoted sentence actually assert this edge?
4. Target ≥90% precision before proceeding.
5. When precision misses, fix the prompt or the rules and re-run the pass. Never hand-correct
   the output — hand-correction hides the defect and it returns at scale.

Recall improves with more passes and more sources. Precision does not: bad precision poisons the
graph permanently, because fusion propagates wrong facts into merged entities where they are no
longer traceable to the extraction that produced them.

Report the number with its sample size and stratification. Precision without a stated sampling
method is not a measurement.

## Failure modes

| Symptom                                       | Cause                                              | Fix                                                                |
| --------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------- |
| Graph full of `Concept` / `Thing` nodes        | Extracted with no ontology                          | Design the ontology, then re-extract                                |
| Same person appears as four nodes              | No canonical-form rule; fusion not run              | Declare the rule in `ontology.yaml`; run fusion                     |
| Confident, fluent, wrong relations             | Co-occurrence treated as assertion                  | Evidence-quote requirement plus domain/range validation in code     |
| Events flattened into edge soup                | No per-event argument schema                        | Promote events to nodes with typed arguments                        |
| Precision collapses as sources are added       | One prompt drifting across document types           | Per-source-type prompts; run the quality gate per source            |
| Entities with no source pointer                | Provenance dropped during chunking                  | Carry document id and offset through the chunker                    |
| Extraction cost grows superlinearly            | Structured sources routed through the model         | Move them to deterministic mappings                                 |
| Model invents plausible entities not in text   | No evidence requirement, or evidence not checked    | Require verbatim quotes and verify the quote appears in the source  |
