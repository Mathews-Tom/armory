# Changelog

## Unreleased

### Added

- Integration-branch existing-PR inspection with structured gate decisions and side-effect-free `--dry-run`.
- Revision-bound validation decisions, actual base-ref rechecks, current checkout/parent evidence, required check publishers, current human approvals, and fail-closed incomplete-policy handling.
- Real-Git safety regressions and scoped lint, formatting, and strict type gates.
- Guarded existing-PR execution with private atomic common-dir receipts, cooperative mutation locks, bounded monitoring, cancellation, and current-fact recovery without blind mutation retries.
- Commit-bound post-merge acceptance, full-head/content cleanup proofs, local CAS and remote deletion leases, safe worktree retention, scoped tracking cleanup, and verified completed no-ops.
- Current GitHub REST/GraphQL landing evidence, distinct fork head/base namespaces, and semantic-whitespace/default-ref/uncertain-outcome regression guards.
- Read-only byte-exact change inventory (`--inventory`) covering staged, unstaged, untracked, deleted, intent-to-add, link, mode and submodule states with explicit concerns and blockers.
- Source-provenanced gate decision packets, a grouping-draft compiler (`--draft`) and versioned snapshot-bound commit plans with exact per-group trees, prior-only dependencies, ordered HEAD/index/working-tree line-occurrence provenance with exact terminators, preservation of staged content before a later deletion, and final-tree equality.
- Lossless commit execution: hooks honored in an isolated checkout of each planned tree with effective source identity and signing configuration, per-commit gates and outgoing secret scan in fresh clean clones, journaled index-then-branch publication, named-base ancestry proof, and locked case/Unicode/ref-path collision refusal before rewriting staging.
- Receipt schema 2 with a typed confirmed-PR target, changeset journal and retained-work checkpoint; confirmation and every recovery path require clean committed paths and the original retained-state proof. Schema 1 receipts migrate exactly; historical missing checkpoints remain unknown.

The advertised skill and command remain unchanged until the complete lifecycle cutover. Release preparation for `2.0.0` remains deferred until the full train is qualified.
