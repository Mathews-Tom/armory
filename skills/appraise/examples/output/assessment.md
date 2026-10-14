# Candidate review: Alice Doe

Generated 2026-10-14T00:00:00Z by appraise 1.0.0 · rubric `software_engineering` 1.0.0 · assessment `6cf03dda3db22c82` · mode `review`

> Levels below are generic capability anchors from the rubric, not an organization's official title, and not a hiring decision.

## Scope and limitations

| Repo | Locator | Revision | Candidate role | Surviving-line share | Attribution confidence | Lineage | Sample coverage |
|---|---|---|---|---|---|---|---|
| R1 | https://github.com/example-org/queuebox | `5d820b5a5e0f` | primary_author | 92% | high | original (no declared upstream) | 64% |

- **host_metadata_unavailable** (lineage) — R1: Host metadata unavailable: offline run: host metadata, pull requests and reviews not collected. Fork/template status could not be checked with the host.
- **ai_assistance_undeclared** (attribution) — R1: No candidate commit carries an AI co-author trailer. AI assistance is undeclared, not shown to be absent; scores rest on the decisions visible in the code either way.
- **evidence_rejected** (verification) — 1 cited item(s) failed verification and were excluded: E-010

## Result

| Recommended level | Technical capability | Scope / influence | Plausible range | Confidence |
|---|---|---|---|---|
| **Mid-level** | Mid-level | Mid-level (partial: no influence evidence) | Mid-level – Senior | medium |

**Determination (engine):** Mid-level. Every Mid-level requirement is met by verified, attributable evidence. Senior is not reached: Testing is 2 (medium confidence); Senior needs 3 or more.

Confidence factors: attribution high, evidence medium, coverage medium, range width 1. Overall confidence is medium. It is the weakest of four checks: attribution is high, evidence is medium, sample coverage is medium, and the level is not settled: the evidence allows Mid-level to Senior. 7 supporting evidence items across 11 observed competencies; mean sample coverage 63.6%.

**Assessor summary** (model-written; the level above is computed by the engine and is not restated or overridden here):

Alice built queuebox's durable core: a SQLite job store with forward-version-guarded migrations (E-001), a lock-serialised claim path that guards the state transition in SQL (E-002), and an ADR that records the rejected Postgres option and the throughput ceiling the design accepts (E-004). The migration refactor (E-008) shows the store evolving without breaking existing files. The weak points are concrete: test_worker_runs never calls the worker, so the worker's failure path is untested (E-005), and the worker declares MAX_ATTEMPTS but never enforces it, contradicting its 'bounded retries' docstring (E-006). Collaboration and technical leadership have no evidence in this repository even though another contributor was present; the HTTP module is theirs and is not credited (E-009). Security was not exercised by any inspected code.

## Competencies

| Competency | Score | Status | Confidence | Supporting evidence | Counterevidence | Engine adjustments |
|---|---|---|---|---|---|---|
| Problem solving | 3 | observed | medium | [E-002](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L31-L43) | [E-006](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/worker.py#L7-L20) | — |
| Code quality | 3 | observed | medium | [E-001](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L20-L29), [E-002](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L31-L43) | — | — |
| Architecture | 4 | observed | medium | [E-001](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L20-L29), [E-004](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/docs/adr/001-sqlite-wal.md#L1-L14), [E-008](https://github.com/example-org/queuebox/commit/7d09825ba17df52ed7b047398e32a74b9e8d4d81) | — | E-009 cannot support a score (attribution unlikely, status downgraded) |
| System design | 3 | observed | medium | [E-002](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L31-L43), [E-004](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/docs/adr/001-sqlite-wal.md#L1-L14) | — | cited E-010 dropped: line_end 130 beyond end of file (48 lines) |
| Testing | 2 | observed | medium | [E-007](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/.github/workflows/ci.yml#L1-L9) | [E-005](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/tests/test_store.py#L14-L17) | — |
| Security | N/O | N/O (no_evidence) | low | — | — | — |
| Operations | 2 | observed | low | [E-007](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/.github/workflows/ci.yml#L1-L9) | [E-006](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/worker.py#L7-L20) | — |
| Technical depth | 3 | observed | medium | [E-003](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L14-L18) | — | — |
| Engineering judgment | 4 | observed | medium | [E-004](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/docs/adr/001-sqlite-wal.md#L1-L14), [E-001](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L20-L29) | — | — |
| Learning | 3 | observed | low | [E-008](https://github.com/example-org/queuebox/commit/7d09825ba17df52ed7b047398e32a74b9e8d4d81) | — | — |
| Ownership | 3 | observed | medium | [E-008](https://github.com/example-org/queuebox/commit/7d09825ba17df52ed7b047398e32a74b9e8d4d81), [E-004](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/docs/adr/001-sqlite-wal.md#L1-L14) | — | — |
| Product thinking | 2 | observed | low | [E-011](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/README.md#L1-L3) | — | — |
| Collaboration | N/O | N/O (no_evidence) | low | — | — | — |
| Technical leadership | N/O | N/O (no_evidence) | low | — | — | — |

N/O means not observable: it is never a zero. `no_opportunity` means the analysed work offered no chance to show the competency.

## Decision trace

- **Junior — technical: pass**
  - pass: 9 of the 10 technical competencies score 1 or more; Junior needs 2.
- **Mid-level — technical: pass**
  - pass: 7 of the 10 technical competencies score 3 or more; Mid-level needs 3.
  - pass: Mid-level needs one of problem solving or code quality at 3 or more. Currently problem solving is 3 (medium confidence); code quality is 3 (medium confidence).
  - pass: No observed technical competency score is below 1.
- **Senior — technical: fail**
  - pass: 7 of the 10 technical competencies score 3 or more; Senior needs 5.
  - pass: Senior needs one of architecture or system design at 4 or more. Currently architecture is 4 (medium confidence); system design is 3 (medium confidence).
  - pass: Engineering judgment is 4 (medium confidence); Senior needs 3 or more.
  - fail: Testing is 2 (medium confidence); Senior needs 3 or more.
  - pass: Senior needs one of operations or security or system design at 3 or more. Currently operations is 2 (low confidence); security wasn't shown by anything inspected; system design is 3 (medium confidence).
  - pass: Ownership is 3 (medium confidence); Senior needs 3 or more.
  - pass: No observed code quality / testing / engineering judgment / architecture score is below 2.
- **Junior — scope: pass** (informational: this level does not require scope)
  - pass: Junior needs one of ownership or collaboration or technical leadership at 1 or more. Currently ownership is 3 (medium confidence); collaboration wasn't shown by anything inspected; technical leadership wasn't shown by anything inspected.
- **Mid-level — scope: pass** (informational: this level does not require scope)
  - pass: Mid-level needs one of ownership or collaboration or technical leadership at 3 or more. Currently ownership is 3 (medium confidence); collaboration wasn't shown by anything inspected; technical leadership wasn't shown by anything inspected.
- **Senior — scope: fail** (informational: this level does not require scope)
  - unknown: Senior needs 2 of ownership, collaboration, technical leadership, product thinking at 3 or more. Currently ownership is 3 (medium confidence); collaboration wasn't shown by anything inspected; technical leadership wasn't shown by anything inspected; product thinking is 2 (low confidence).
  - fail: Ownership is 3 (medium confidence); Senior needs 4 or more.

What keeps it from the next level:

- Testing is 2 (medium confidence); Senior needs 3 or more.

## Strengths

- Designs persisted state for evolution: versioned migrations with forward-version refusal. — [E-001](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L20-L29), [E-008](https://github.com/example-org/queuebox/commit/7d09825ba17df52ed7b047398e32a74b9e8d4d81)
- Records tradeoffs with a rejected alternative and an explicit revisit trigger. — [E-004](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/docs/adr/001-sqlite-wal.md#L1-L14)

## Confirmed weaknesses

- Worker failure recovery is not implemented although documented: jobs that fail stay 'running'. — [E-006](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/worker.py#L7-L20)
- Test suite overstates coverage: the worker path has no test oracle. — [E-005](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/tests/test_store.py#L14-L17)

## Potential risks

- Throughput ceiling from a process-wide lock if more than one worker is deployed. — [E-004](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/docs/adr/001-sqlite-wal.md#L1-L14), [E-002](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L31-L43)

## Evidence gaps

- **security** — no_evidence: Nothing inspected demonstrated this competency. Evidence that would resolve it: source_code, ci_config, documentation.
- **collaboration** — no_evidence: Nothing inspected demonstrated this competency. Evidence that would resolve it: review, pull_request, issue.
- **technical_leadership** — no_evidence: Nothing inspected demonstrated this competency. Evidence that would resolve it: design_doc, documentation, review, pull_request, external_artifact.

## Development plan

| ID | Priority | Category | Action | Success criterion | Effort | Horizon | Source |
|---|---|---|---|---|---|---|---|
| P-01 | P1 | confirmed_weakness | **Make retries real** — Enforce MAX_ATTEMPTS using the attempts column; move exhausted jobs to a 'failed' state; requeue on transient errors. | A test that injects a failing handler observes attempts == MAX_ATTEMPTS and state == 'failed'. | S | 14d | [E-006](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/worker.py#L7-L20) |
| P-02 | P1 | confirmed_weakness | **Test the worker, not just the store** — Add worker tests for success, handler exception and empty queue; rename or remove test_worker_runs. | Coverage of worker.py at 100% of branches, enforced in CI. | S | 30d | [E-005](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/tests/test_store.py#L14-L17), [E-007](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/.github/workflows/ci.yml#L1-L9) |
| P-03 | P2 | evidence_gap | **Make collaboration visible** — Review the other contributor's HTTP changes through pull requests and document a contribution guide for the store API. | At least five substantive reviews and one merged guide authored by the candidate. | M | 90d | — |
| P-04 | P2 | next_level_opportunity | **Design the multi-worker path** — Write ADR 002 comparing row-level leasing in SQLite vs. Postgres SKIP LOCKED with a measured benchmark. | ADR with a reproducible benchmark showing claims/sec for 1, 2 and 4 workers. | M | 60d | [E-004](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/docs/adr/001-sqlite-wal.md#L1-L14) |

## Evidence register

| ID | Kind | Location | Attribution | Verification | Status | Observation |
|---|---|---|---|---|---|---|
| E-001 | source_code | [src/queuebox/store.py:20-29](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L20-L29) | verified | directly_inspected | verified | Migrations are keyed on PRAGMA user_version; a store written by a newer version is refused instead of being silently downgraded. |
| E-002 | source_code | [src/queuebox/store.py:31-43](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L31-L43) | verified | directly_inspected | verified | claim() selects the oldest queued job and updates it with a state = 'queued' guard inside a lock, then commits. |
| E-003 | source_code | [src/queuebox/store.py:14-18](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L14-L18) | verified | directly_inspected | verified | Connection opened with check_same_thread=False and WAL mode, paired with an explicit threading.Lock. |
| E-004 | design_doc | [docs/adr/001-sqlite-wal.md:1-14](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/docs/adr/001-sqlite-wal.md#L1-L14) | verified | directly_inspected | verified | ADR states context, rejects Postgres for an operational-dependency reason, and records the single-host throughput ceiling as a consequence. |
| E-005 | test_code | [tests/test_store.py:14-17](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/tests/test_store.py#L14-L17) | verified | directly_inspected | verified | test_worker_runs only calls store.claim(); the worker module is never imported or exercised. |
| E-006 | source_code | [src/queuebox/worker.py:7-20](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/worker.py#L7-L20) | verified | directly_inspected | verified | MAX_ATTEMPTS is declared but never read; on failure the worker sleeps 0.1s and re-raises, so a failing job stays 'running' forever. |
| E-007 | ci_config | [.github/workflows/ci.yml:1-9](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/.github/workflows/ci.yml#L1-L9) | verified | directly_inspected | verified | CI installs the package and runs pytest on push and pull request. |
| E-008 | commit | [7d09825ba17d](https://github.com/example-org/queuebox/commit/7d09825ba17df52ed7b047398e32a74b9e8d4d81) | verified | directly_inspected | verified | Adds a v2 migration (attempt counting) on top of the existing schema rather than recreating the table. |
| E-009 | source_code | [src/queuebox/web.py:1-10](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/web.py#L1-L10) | unlikely | directly_inspected | downgraded | Minimal HTTP health endpoint. |
| E-011 | documentation | [README.md:1-3](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/README.md#L1-L3) | verified | repository_claimed | verified | README describes the product as a durable single-host job queue. |

Rejected by verification:

- E-010: line_end 130 beyond end of file (48 lines)

## How to contest

Any evidence item or attribution can be challenged. Add an entry to `challenges` (claim `not_authored`, `misinterpreted`, `outdated` or `other`) or answer the questions as `self_reports`, then rerun `assess --previous` on this assessment. Verified-identity authorship survives a `not_authored` challenge but is marked contested; self-reports are kept beside the evidence they dispute and never raise a level on their own.
