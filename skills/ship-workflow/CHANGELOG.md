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
- Publication of local work as one exact PR: `--plan`, `--branch`, `--head-repo`, `--title`/`--body-file` and no-selector entry, guarded expected-old pushes with forward-history proof and outgoing gate/secret-scan validation, exact paginated PR reuse, journaled never-retried PR creation, fork head namespaces, and continuation through the existing lifecycle for `pr`, `merged` and `clean`.
- Schema 2 decision packets bound to a commit plan or explicit head/base instead of literal revisions, and receipt schema 3 with a typed publication journal; schema 1 and 2 receipts migrate exactly.
- Unknown push and PR-creation outcomes are reconciled before advancing local work; an unlisted PR creation stays pending and is never sent again, however old. Same-namespace foreign intent checks run under the push and creation locks, including saved-publication resumes.
- Publication refuses invalid titles and stale policy bindings before dispatch, rejects closed unmerged PRs as completed targets, and requires an explicit retained-work disposition before a wider endpoint would publish work it cannot safely land or clean.
- Same-run compare-and-swap preservation during foreign-intent scans, immutable confirmed PR identities, and merged-head reuse without resurrecting deleted branches.
- Separate named-base placement proof from current PR applicability; plan-bound publication follows the actual confirmed base while explicit revision packets require a refresh before publication. Missing creation inputs stop before creating local commits or publication intents.
- Pending CI checkout proof remains `WAITING` while the actual job runs, including beside tolerated unverified head-only checks; completed but unprovable integration checkout evidence remains `NEEDS_JUDGMENT`.
- Selected-PR placement and plan-packet admission before local mutation, plus base-ref retarget invalidation on direct lifecycle resumption.
- Applicable reviewed source-version recovery before adoption, retained admitted-decision authority across further source changes and publication-to-lifecycle interruptions, validation-authority invalidation under compare-and-swap, and pending publication settlement before advancing new work.
- Explicit and unambiguous automatic `--pr` selection of a confirmed creation interrupted before target binding, including exact-head merged reuse without restoring deleted refs; unconfirmed and wrong selectors preserve the saved journal.

The advertised skill and command remain unchanged until the complete lifecycle cutover. Release preparation for `2.0.0` remains deferred until the full train is qualified.
