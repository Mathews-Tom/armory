# Fusion: Entity Resolution and Merge Policy

Fusion is the stage that decides whether the graph is useful. Skipping it is the single most
common reason a knowledge-graph project produces something nobody uses: an unfused graph answers
multi-hop questions *wrongly and confidently*, because every path breaks at a duplicate boundary.

## Contents

- [What fusion is resolving](#what-fusion-is-resolving)
- [Blocking](#blocking)
- [Matching](#matching)
- [Threshold bands](#threshold-bands)
- [Merge policy](#merge-policy)
- [Ontology matching](#ontology-matching)
- [Measuring fusion](#measuring-fusion)
- [Incremental fusion](#incremental-fusion)

## What fusion is resolving

Every extraction pass produces duplicates, within a source and across sources:

- Surface variation — "SEU", "Southeast University", "东南大学"
- Abbreviation and legal suffix — "Acme Corp", "Acme Corporation", "ACME"
- Genuine ambiguity — "Bob Smith" in document 3 and "Robert Smith" in document 41 may or may not
  be one person, and the text alone does not settle it

The output of fusion is not "fewer nodes". It is **stable identity**: a guarantee that a given
real-world thing has exactly one node, so that a path through it is a real path.

## Blocking

Never compare all pairs. At 100K entities, exhaustive comparison is 5×10⁹ pairs.

Group candidates cheaply first; only pairs inside a block get scored:

| Blocking key                    | Catches                                    | Misses                                  |
| ------------------------------- | ------------------------------------------ | ---------------------------------------- |
| Same type + shared token        | "Acme Corp" / "Acme Corporation"           | "IBM" / "International Business Machines" |
| Normalized key (lowercase, strip punctuation, drop legal suffixes) | Suffix and casing variation | Genuine synonyms                          |
| Acronym expansion               | "SEU" / "Southeast University"             | Non-initialism abbreviations             |
| Embedding neighborhood (top-k)  | Paraphrase and translation                 | Short strings; embedding-model blind spots |
| External identifier             | Anything with a shared id — perfect signal | Entities lacking the identifier          |

Use several keys in union, not one. Each key has a different blind spot; the union's recall is
what matters, and a single key never gets there.

Two numbers characterize a blocking strategy, and you must know both:

- **Reduction ratio** — fraction of all pairs eliminated. Higher is cheaper.
- **Pair recall** — fraction of true matches that survive into some block. Anything blocking
  filters out can never be matched, at any threshold, by any model downstream.

Blocking recall is a hard ceiling on fusion recall. Measure it before scaling:

```bash
uv run scripts/blocking_report.py candidates.jsonl --labels matches.jsonl
```

## Matching

Score surviving pairs on layered evidence. Layers are ordered cheapest-first; the expensive
layers only run on pairs the cheap ones leave undecided.

1. **String layer.** Normalized equality, alias table hit, acronym expansion, edit distance.
   Resolves the large majority of true matches at near-zero cost.
2. **Attribute layer.** Compatible attributes — same founding year, same email domain, same
   external identifier. Attribute *conflict* is strong negative evidence and should be able to
   veto a string match on its own.
3. **Structure layer.** Compare neighborhoods. Two `J. Smith` nodes sharing three coauthors and
   an affiliation are the same person; two with identical names and disjoint neighborhoods are
   not. This is the layer naive deduplication omits and the one that resolves the genuinely hard
   cases, because it uses information the strings do not contain.
4. **Model adjudication — ambiguous middle band only.** Show both nodes' attributes,
   neighborhoods, and evidence quotes, and ask whether they are the same entity.

### Measure the adjudicator before trusting it

A model adjudicator is a claim about decision quality, and claims need baselines. Build a
labeled set of pairs from the middle band and compare the adjudicator against a prompt-only
baseline on the same pairs.

This is not hypothetical. In a pre-registered real-model evaluation of an LLM-adjudicated
dedup-and-contradiction loop over 108 held-out cases across two embedding models and two
generation models, the loop **trailed the prompt-only baseline by 0.28–0.33 on detection and
safety in every provider cell**. The engineered loop lost to the plain prompt. Unmeasured
adjudication is decoration, and it is decoration that costs a model call per pair.

If the adjudicator does not beat the baseline, widen the auto-bands and send the middle to human
review instead. That is a legitimate outcome, not a failure.

## Threshold bands

Three bands, two thresholds, and the bands are not symmetric:

| Band            | Action                          | Sizing principle                                            |
| --------------- | ------------------------------- | ------------------------------------------------------------ |
| Above high      | Auto-merge                      | Set from labeled data so false-merge rate is near zero        |
| Middle          | Adjudicate or queue for a human | Should be small; a large middle band means weak features      |
| Below low       | Auto-reject                     | Generous — a missed merge is recoverable later                |

**Asymmetry is the point.** An erroneous merge silently fuses two entities' entire edge sets, and
every query afterwards returns a blend of two real things with no signal that anything is wrong.
A missed merge leaves two nodes that a later pass can still join. Tune the high threshold for
precision, not for how many merges it produces.

## Merge policy

Deterministic code. Never a model judgment — a model that decides *whether* two nodes match must
still not decide *what the merged node contains*.

| Field                | Policy                                                                       |
| -------------------- | ----------------------------------------------------------------------------- |
| Canonical name       | Apply the ontology's canonical-form rule; longest legal form breaks ties       |
| Aliases              | Union of all surface forms, each retaining its source                          |
| Edges                | Union; deduplicate identical (type, target, time) triples                      |
| Conflicting values   | **Keep both**, each with its provenance — never silently overwrite             |
| Provenance           | Union of source pointers; earliest `extracted_at` retained per claim           |
| `merged_from`        | Record every absorbed node id so the merge is reversible                       |

Conflicting attribute values are signal, not noise. Two sources disagreeing on a founding year
means one is wrong or they mean different events. Overwriting destroys the only evidence that a
question exists. Store both, surface the conflict, and let the retrieval layer prefer by recency
or source trust — see [`provenance-and-supersession.md`](provenance-and-supersession.md).

Every merge must be undoable. `merged_from` plus append-only claims is what makes an
over-aggressive threshold a recoverable mistake instead of permanent corruption.

## Ontology matching

When fusing two *graphs* rather than two instance sets, align the schemas first:

1. Align entity and relation types by name and definition — a reasonable model task.
2. **Verify with instance overlap.** If source A's `Firm` nodes mostly resolve to source B's
   `Company` nodes, the type mapping is confirmed by data rather than by the model's opinion.
3. Translate source B's edges through the confirmed mapping.
4. Only then run instance fusion.

Skipping step 2 is how two graphs get merged under a plausible but wrong type mapping, which is
much harder to detect afterwards than a wrong instance merge.

## Measuring fusion

Report four numbers, each with its method:

| Metric                | How to obtain it                                                          |
| --------------------- | -------------------------------------------------------------------------- |
| Blocking pair recall  | Labeled match set; fraction surviving blocking                              |
| Reduction ratio       | Pairs after blocking ÷ all pairs                                            |
| Merge precision       | Sample 50 auto-merges; how many are correct                                 |
| Merge recall estimate | Sample entities with known duplicates; how many were joined                 |

A duplicate-rate claim ("duplicates ≈ 0 after fusion") is only meaningful against a labeled set.
Re-ingesting the same documents and observing zero new nodes tests idempotence, which is a
useful mechanical property and is *not* evidence that distinct duplicates were resolved.

## Incremental fusion

For graphs that grow continuously — agent memory, ongoing ingests:

1. Block the new facts against the existing graph, not against each other alone.
2. Match and merge with the same machinery and the same thresholds. Divergent thresholds between
   the initial build and the incremental path produce a graph whose identity rules changed
   halfway through and cannot be reasoned about.
3. Re-run full fusion periodically. Entities that were ambiguous when first seen often become
   resolvable once their neighborhoods fill in — the structure layer gets stronger over time.
4. Re-score stale confidences on the same schedule. Unmaintained memory graphs rot exactly like
   unfused extractions.
