# Serving the Graph to Agents

A graph nobody queries is a data-modelling exercise. Serving is where the pipeline either pays
for itself or does not — and it must be measured against the boring baseline it claims to beat.

## Contents

- [Retrieval strategy by question type](#retrieval-strategy-by-question-type)
- [Path retrieval](#path-retrieval)
- [Serialization](#serialization)
- [Community summaries](#community-summaries)
- [The agent-facing surface](#the-agent-facing-surface)
- [Graph as agent memory](#graph-as-agent-memory)
- [Proving the graph earns its cost](#proving-the-graph-earns-its-cost)

## Retrieval strategy by question type

Route by question shape. Most real question sets contain a large fraction that the graph should
not serve at all, and pretending otherwise is how graph retrieval acquires a reputation for being
slower and worse than vector search.

| Question type                              | Strategy                                     | Should the graph serve it? |
| ------------------------------------------ | ---------------------------------------------- | -------------------------- |
| "What is X?"                                | Entity lookup, return node plus 1 hop         | Yes, cheaply               |
| "How are X and Y connected?"                | Path retrieval between the two entities       | Yes — this is the point    |
| "Who did X with Y on Z?"                    | Multi-hop constrained traversal               | Yes — this is the point    |
| "What are the themes in this corpus?"       | Precomputed community summaries               | Yes, offline               |
| "Summarize this document"                   | Return the source document                    | No — use the document store |
| "Find passages about X"                     | Vector search over source text                | No — use the vector index  |
| "Total spend by region"                     | Aggregate query                               | No — use the warehouse     |

Say out loud which questions do not need the graph. A retrieval layer that routes everything
through traversal will lose to plain vector search on the majority of a realistic question set.

## Path retrieval

For multi-hop questions, retrieve the **paths between** the query's entities, not the
neighborhoods around each one.

Neighborhood expansion around two entities returns two clouds and asks the model to find the
connection inside them. Path retrieval returns the connection itself. The path is the answer
skeleton; the model's job reduces to narrating it.

Practical constraints:

- Cap path length at 3–4 hops. Longer paths are almost always spurious.
- Rank paths by shortest first, then by aggregate edge confidence.
- Return at most a handful. Twenty paths between two entities means the graph has a hub node
  that should be excluded from traversal.
- Exclude hub nodes explicitly. A node with 10,000 edges connects everything to everything and
  makes every path meaningless.

## Serialization

Serialize the retrieved subgraph as compact typed lines grouped by head entity:

```text
Jane Doe (Person)
  -[CONTRIBUTED_TO {since: 2024-03, src: doc/onboarding.md}]-> payments-api (Service)
  -[REPORTS_TO {src: hr/roster.csv}]-> A. Kowalski (Person)

INC-4012 (Incident)
  -[AFFECTED {severity: high, src: incidents/4012.md}]-> payments-api (Service)
```

Rules that matter:

- **Triples beat prose.** A model can quote an exact fact from a triple table; it paraphrases
  prose summaries and the paraphrase is where fabrication enters.
- **Carry provenance inline.** The source pointer is what makes the answer checkable. Without
  it, a graph-grounded answer is indistinguishable from a confident guess.
- **Carry time inline.** "Works at X" without a validity interval is a fact that quietly expires.
- **Deduplicate before serializing.** The same edge reached by two paths must appear once.
- **Budget the context.** Cap the serialized subgraph. Truncate by dropping lowest-confidence
  edges first, and say in the output that truncation happened.

## Community summaries

For corpus-level questions ("what are the main themes", "what does this codebase do"):

1. Cluster the graph offline — connected components, label propagation, or modularity-based
   clustering.
2. Summarize each cluster once, storing the summary as a node with edges to its members.
3. At query time retrieve summaries, not members.

This is precomputation, so its cost is amortized and its staleness is real. Re-cluster when the
graph grows materially, and stamp each summary with the graph revision it was built from so a
stale summary is detectable rather than silently wrong.

## The agent-facing surface

Expose deterministic, parameterized traversals. Do not hand a model raw query-language access to
the store.

| Surface                            | Why                                                                          |
| ---------------------------------- | ------------------------------------------------------------------------------ |
| `find_entities(name, type)`        | Entity linking entry point; bounded result set                                  |
| `get_entity(id, hops=1)`           | Node plus neighborhood, hop-capped in code                                      |
| `find_paths(from, to, max_hops=3)` | The multi-hop primitive                                                         |
| `list_summaries(cluster?)`         | Corpus-level questions without loading members                                  |

Parameterized traversals are testable, cacheable, hop-capped, and cannot be talked into scanning
the entire store. Generated query-language strings are none of those things: they fail in ways
that depend on the phrasing of the prompt, which makes regressions unreproducible.

Be honest about the boundary this does and does not create. Exposing only traversal tools shapes
what the graph offers; it does not prevent a host agent that also has filesystem or database
tools from reading around the surface. Only a sandboxed serving boundary enforces that.

## Graph as agent memory

For agents accumulating knowledge across sessions:

1. **Write path.** After a session, run extraction over the new information with the same
   ontology, then fuse into the existing graph with the same thresholds. Memory writes are not a
   separate pipeline; reusing the build pipeline is what keeps identity rules consistent.
2. **Read path.** At session start, retrieve via traversal rather than dumping the graph into
   context. The whole point of the structure is that it lets you load a minimal relevant set.
3. **Supersession, not overwrite.** New facts supersede prior claims and keep them addressable.
   See [`provenance-and-supersession.md`](provenance-and-supersession.md).
4. **Contradiction.** Keep both claims with time and provenance; prefer the newer at retrieval;
   surface the conflict when both are recent. Facts change — the graph should record the change,
   not fight it.
5. **Hygiene.** Re-run fusion and re-score confidences periodically.

## Proving the graph earns its cost

Build the evaluation set **before** either system runs, or the comparison is unfalsifiable.

1. Write 30 questions spanning the question types above, including the ones the graph should not
   serve. Write the answer key first.
2. Build a **vector-only baseline over the same source text**. Same corpus, same generator, same
   token budget.
3. Report per question type, not in aggregate. An aggregate number hides the actual finding,
   which is nearly always: the graph wins on multi-hop and connection questions and loses
   elsewhere.
4. Report tokens and latency alongside accuracy. A graph that wins on accuracy while costing five
   times the tokens and three times the latency has not necessarily won.
5. State what the numbers are measured on. Results from a deterministic or toy retrieval stand-in
   verify mechanics only; they are not evidence of real-model retrieval quality, and reporting
   them as if they were is how a project acquires a claim it cannot defend.

If the graph does not win on multi-hop questions against the vector baseline, it is not earning
its maintenance cost. That is a real possible outcome and the correct response is to narrow the
graph's role to the queries it wins, not to widen the claim.
