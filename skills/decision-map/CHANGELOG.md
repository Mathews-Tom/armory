# Changelog

## 2.0.1 — 2026-10-26

- Work mode checks for the `prototype` package when a prototype ticket is selected, before taking visible ownership or a claim, so a missing package leaves the ticket untouched. A continuation that already holds the claim keeps it and follows the unresolved path.

## 2.0.0 — 2026-10-26

- BREAKING: prototype tickets now require the `prototype` package, which builds and observes the logic/state or UI artifact. Without it, prototype work stops with `BLOCKED: install prototype` before claiming the ticket.
- Reduce `references/prototyping.md` to the ticket wrapper: package and claim preconditions, HITL verdict ownership, evidence record format, `UNRESOLVED_WITH_EVIDENCE` path, frontier recompute and stop.
- Remove the moved artifact-building protocol and `references/upstream/prototype-provenance.md`; that attribution now lives in the `prototype` package. The original wayfinder provenance and LICENSE are unchanged.
- Route standalone prototype requests outside a decision map to `prototype`; add eval cases for the missing-package stop and the standalone route.

## 1.1.0 — 2026-10-19

- Add a bounded prototype resolution path: one shareable logic/state HTML or structurally different UI variants, scratch-only artifacts, observed browser evidence and a ticket-governed verdict.
- Preserve local tickets' required metadata headers while keeping GitHub labels out of bodies; define concrete comment/quoted-append evidence writes that cannot clobber local metadata.
- Add separate prototype provenance and a package-root MIT notice while preserving the original wayfinder pin and attribution unchanged.
- Add an explicit unresolved-with-evidence outcome and same-claim continuation under existing stale rules, without false closure, a new ownership API or engine changes.
- Add behavioral local/GitHub fixtures for held unresolved claims, stale continuation, and evidence lines resembling tracker metadata.
