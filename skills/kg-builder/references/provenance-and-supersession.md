# Provenance and Supersession

Every fact in the graph must answer three questions: where did this come from, when was it true,
and what did it replace. A graph that cannot answer them cannot be audited, cannot be safely
merged, and cannot be trusted after its first update.

This is the stage most pipelines defer and none successfully retrofit. Fusion discards the
information provenance is derived from, so provenance added after fusion is reconstruction, not
record.

## Contents

- [The claim model](#the-claim-model)
- [Supersession instead of overwrite](#supersession-instead-of-overwrite)
- [The no-silent-overwrite invariant](#the-no-silent-overwrite-invariant)
- [Contradiction handling](#contradiction-handling)
- [Validity time versus record time](#validity-time-versus-record-time)
- [Audit trail](#audit-trail)
- [Retrieval over a claim ledger](#retrieval-over-a-claim-ledger)

## The claim model

Make the *claim* the atomic unit, not the edge. An edge is the current consensus; a claim is a
specific assertion by a specific source at a specific time. The graph is a projection of the
claim ledger.

| Field            | Purpose                                                             |
| ---------------- | --------------------------------------------------------------------- |
| `claim_id`       | Stable identity; content-addressed so identical claims collapse       |
| `statement`      | The assertion — a typed triple, plus its verbatim evidence quote      |
| `source_id`      | Which document, record, or run asserted it                            |
| `asserted_at`    | When the source made the assertion (record time)                      |
| `effective_from` | When the fact started being true (validity time)                      |
| `effective_to`   | When it stopped, if it has                                            |
| `status`         | `current` / `superseded` / `retracted`                                |
| `supersedes`     | The `claim_id` this replaces — the lineage pointer                    |
| `contradicts`    | A `claim_id` this materially conflicts with                           |
| `confidence`     | Extraction or adjudication confidence                                 |
| `reviewer`       | Who approved it, when a human gate was involved                       |

Two fields do the heavy lifting. `supersedes` makes history reconstructable. `contradicts` makes
disagreement a first-class state rather than a race between writes.

## Supersession instead of overwrite

When new information arrives about an existing fact, **append a new claim and mark the old one
superseded**. Do not edit the old claim in place.

```text
claim_7a2  Jane Doe EMPLOYED_BY Acme     effective_from 2023-01  status superseded
claim_e11  Jane Doe EMPLOYED_BY Globex   effective_from 2025-06  status current
                                          supersedes claim_7a2
```

What this buys, none of which is available from an in-place update:

- **Reconstructable history.** "What did the graph believe on this date" is a query, not an
  archaeology project.
- **Reversible mistakes.** A wrong merge or a bad extraction is undone by re-projecting without
  the offending claims.
- **Attributable disagreement.** Two sources disagreeing produce two claims, not a last-write-wins
  coin flip whose outcome depends on ingest order.
- **Debuggable retrieval.** When an agent answers wrongly, the claim that produced the answer is
  identifiable and its source is one hop away.

Cost is storage and one indirection at query time. Both are cheap. Losing the ability to explain
where an answer came from is not.

## The no-silent-overwrite invariant

State the guarantee as a checkable property, not a convention:

> For every ingest, each claim present before the ingest is, after it, either still `current`,
> or `superseded` by a claim that names it in `supersedes`, or explicitly `retracted` with a
> reason.

A claim that simply disappears violates the invariant. Assert this in code after every ingest and
fail the ingest when it trips. Written as an assertion it is enforced; written as a design note
it is aspirational, and it will be violated by the first fusion bug nobody noticed.

The same invariant makes over-aggressive fusion survivable. Merges that discard claims fail the
check immediately, at ingest, rather than surfacing months later as a query that returns a blend
of two real entities.

## Contradiction handling

When a new claim materially conflicts with a stored one:

1. **Keep both.** Never resolve by deletion.
2. **Link them** with `contradicts` in both directions.
3. **Classify the conflict:**

| Class            | Example                                                    | Resolution                                              |
| ---------------- | ------------------------------------------------------------ | -------------------------------------------------------- |
| Temporal change  | Employer changed                                            | Not a conflict — set `effective_to` on the prior claim   |
| Granularity      | "Berlin" versus "Germany"                                   | Not a conflict — both true; model the hierarchy          |
| Source disagreement | Two filings give different founding years                | Keep both; prefer by source trust at retrieval            |
| Genuine error    | One source is simply wrong                                  | Retract with a reason; retraction is recorded, not deleted |

Most detected "contradictions" are the first two classes. A detector that does not separate
temporal change from real conflict will flood the review queue and get switched off.

**Measure the detector.** If contradiction detection is a model call, compare it against a
prompt-only baseline on a labeled held-out set before relying on it. In a pre-registered
real-model evaluation, an engineered detection loop trailed the prompt-only baseline by 0.28–0.33
on detection and safety across every provider cell tested. The governance machinery — lineage,
reversibility, audit trail — held up under the same evaluation. The *judgment* did not. Ship the
machinery; measure the judgment.

## Validity time versus record time

Keep them separate. Conflating them makes both unusable.

- **Validity time** (`effective_from` / `effective_to`) — when the fact was true in the world.
- **Record time** (`asserted_at`) — when the source said so.

A contract signed in March and ingested in June has validity time March and record time June.
"What was true in April" and "what did we know in April" are different questions, both legitimate,
and only a bitemporal record answers both.

## Audit trail

For graphs whose contents carry consequence:

- **Batch identity.** Every ingest gets a run id; every claim records the run that produced it.
- **Reviewable diff.** Express an ingest as a proposed set of claim additions and supersessions,
  reviewable before it lands.
- **Human gate on irreversible steps.** Place the gate where a mistake is expensive to undo —
  merges above the auto-threshold, retractions, schema changes — not on every write. A gate on
  everything makes the human the bottleneck and gets bypassed.
- **Replay.** The graph is a projection of the ledger, so it must be rebuildable from the ledger
  alone. If it is not, some state lives outside the audit trail and the trail is decorative.

## Retrieval over a claim ledger

Serving reads the projection, not the raw ledger:

1. Default to `status: current`.
2. Prefer higher-trust sources when claims conflict; when trust is equal, prefer the more recent
   `asserted_at`.
3. Filter by validity time when the query is time-scoped ("who owned this in 2024").
4. **Surface unresolved contradictions in the serialized output** rather than silently picking
   one. An agent told two sources disagree can say so; an agent handed one arbitrary side states
   it as fact.
5. Carry `claim_id` and `source_id` into the serialized context so an answer is traceable to the
   assertion that produced it.
