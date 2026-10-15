# Changelog

## Unreleased

### Changed

- Routine shipping uses current GitHub checks, required reviews, branch protections and merge policy; checkout-log attestation and immutable action pins are explicit `assurance: "high"` policy instead of default repository prerequisites.
- Ordinary PRs can use a provider-derived policy when the merge method is unambiguous. Minimal routine packets select a merge method without enumerating CI; explicit inventories, justified skips and deliberately CI-free decisions remain authoritative.
- Check evidence is qualified by workflow, event, publisher, job and current run/attempt. Provider-current job IDs preserve same-named carried jobs across partial reruns instead of collapsing them by name. Push-only strict repositories use provider-proven inclusion of the current base in the checked head, while observed PR-context checks remain independently authoritative.
- Requested stack/publication gates run before push in isolated clean checkouts, with independent per-gate timeouts and optional `per_commit` validation. Repository hooks are preserved; validation does not consume the CI monitoring window.
- Receipt schema 4 and graph journal schema 2 record assurance explicitly. Graph journals retain local gate packets; incompatible or historical assurance requires an explicit decision, never a silent downgrade. Endpoint authority and pending intents remain intact.
- Condense the skill's standard path and refresh stacked-PR delegation, local-gate and recovery references.

### Fixed

- Freeze and reuse exact verified replay commit objects after definite push refusal with unchanged inputs; no caller-seeded committer date or temporary pre-push validation protocol.
- Renew local gates and the outgoing secret scan after a refused or reconciled not-applied ordinary publication; validation cache hits cannot skip a requested retry check. Push diagnostics describe observed publication failure without misattributing local hooks or transport errors to the remote.
- Recheck trunk/member inputs after local validation before dispatching a stack push or native request, and validate refreshed native heads rather than old journal members.
- Invalidate pre-retarget CI by its original workflow trigger, including reruns and automatic base changes; newer runs or attempts with missing job evidence cannot inherit older success.
- Preserve omitted routine check inventories when freezing graph plans, so minimal routine packets remain resumable. Completed runs do not record unexercised gates.
- Publication previews expose an unresolved named base before planning pushes or PR creation.

### Tests

- Cover reviews on later API pages superseding earlier approvals through dismissals, change requests, and stale-head approvals; the regression detects loss of later-page evidence.

## 2.0.0

### Changed

- BREAKING: explicit full shipping requests now default to the complete `clean` lifecycle. Explicit PR-only and CI-inspection requests retain their narrower endpoint; resuming a saved run does not expand its authority.
- BREAKING: ordinary shipping no longer chooses versions, writes changelogs or prepares releases. `release-captain` owns explicitly authorized release artifacts and hands shipping off at `pr`; tags and publication require their own authorization.
- Established Git and provider mechanics are owned by one resumable executable controller. The assistant supplies bounded change grouping, substantive review, source-backed applicability decisions and unfamiliar diagnosis rather than a second hand-run lifecycle.

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
- Manual stack graph continuation (`--stack-plan`): an explicit bounded decision packet with per-node revision-free gate decisions and `preserve` provenance continues linear and branching graphs parent-first through the existing per-PR lifecycle, including already-merged parents and selected siblings, while unselected siblings, children and active parent bases are retained untouched and changes outside the selected ancestry are reported without stopping; native members never take the ordinary merge and scope never widens.
- Proof-based child promotion after a parent lands: fork capture before the parent merge, the clean three-way expected tree, plumbing replay preserving author and message bytes, explicit expected-old rewrite pushes, journaled retargets, compare-and-swap local branch advance and renewed gates; a dirty invoking checkout stops pushes and retargets, and conflicts, unprovable boundaries, emptied commits, signed slice commits and configured commit signing need judgment.
- Graph journals under `<git-common-dir>/armory/ship/graphs/` with a frozen plan topology, preassigned per-node receipts and `capture`/`rewrite-push`/`retarget`/`advance-local` intents reconciled from current facts on resume and never resent; receipt-first `--resume` routing; a write-free `--dry-run` that previews the three-way tree in an isolated temporary repository, observation-only `pr`, deferred `clean` cleanup while open PRs use a parent branch, and verified completed no-ops.
- `GitHub.retarget_pr`: a prechecked, never-retried base-only edit with authoritative pre- and post-reads and uncertain-outcome classification; GitHub documents no atomic head/base guard for it.
- Stacked-PR stack model, sync, merge-discipline, provenance and metadata references describe the explicit packet, promotion proof, retention and preserved provenance of the executable manual graph path.
- Native stack execution through `--stack-plan`: a selection of members of one GitHub-native stack is landed by exactly one never-resent `merge-async` request for the highest selected member, after refusing an implicitly broader prefix (an open unselected lower member), unknown stack identity, more than one stack, mixed manual/native selections, an unknown trunk policy and a direct method the trunk does not allow, all before any write. Queue requests send no merge method; direct requests send the decided method; the result states that the server guards only the selected head.
- Native journal records: frozen member heads, review bases, trees and own-slice identities and the request state (`PLANNED`, `DISPATCHING`, `ACCEPTED`, `REJECTED`, `UNKNOWN`) journaled before dispatch; exact-option adoption of an in-flight request; unknown outcomes need judgment and are reconciled from pull request facts only; a request the client never sent (too short a window, missing `gh`) stays `PLANNED`. A manual run blocks a selected node that becomes a native member before its next graph mutation.
- Native landing proofs from pull request facts, not request status (`enqueued` is never a landing; queue groups land independently): each landing reachable from the trunk tip, in member order, with the clean three-way tree of its own slice over the trunk before it, including multi-commit rebase landings; failed requests keep proved landings; retained members are verified as rebased by the provider with their exact tree and own slice, or as untouched where they already sit on the trunk or the member below, once, before any per-node post-merge acceptance and cleanup through the lifecycle's native landing context. Native `--dry-run` and `--until pr` write nothing.
- `lifecycle.NativeLanding` and `lifecycle.execute(..., native=...)`: post-merge acceptance and cleanup of one provider-MERGED native member on its stack trunk while its receipt keeps the review base; `lifecycle.evaluate(..., native_stack=True)` evaluates a native member's gates under the ordinary rules.
- `GitRepository.merge_base` (the single best common ancestor of two commits, or none when absent or ambiguous), `commit_tree`, `first_parent`, `slice_identity` (the exact net own-slice delta identity) and `landing_bases` (the trunk commits before a squash, merge or multi-commit rebase landing).
- `NativeMergeResult` carries the echoed `merge_action`, `merge_method` and `bypass_rules`, and `matches()` decides exact-option equality, also for the request named by `NativeMergeInProgress`. Behaviour change: an accepted request sent without a method is now uncertain unless GitHub echoes `merge_method: "default"`; an omitted echo was accepted before.
- The controller code identity now covers `native_stack.py`: editing it invalidates saved receipts and graph journals for resumption until a refreshed packet is supplied.
- Read-only native previews check the strict ancestry chain between every locally available selected and retained head, report a still-`PLANNED` request whose prefix an external actor already landed, and distinguish a refused request that landed externally (`NEEDS_JUDGMENT`) from one that merged nothing (`BLOCKED`), matching execution's stop without fetching or writing.
- A thin `/ship` command with explicit target, endpoint, dry-run and saved-run arguments; installed dispatch resolves the client-reported skill directory and fails clearly when a required workflow or stack companion is missing.
- Coherent release, milestone and stacked-PR caller cutover, routing and preset integration that preserve each caller's prior authorization and keep stack topology/provenance judgment under `stacked-prs`.
- Real hard-process-death regressions using fsync-backed native journal intents, SIGKILL and a cross-process dispatch witness: safe pre-dispatch recovery and uncertain post-dispatch recovery without duplicate native requests.
- Temporary archive/installed-client and separate provider qualification across ordinary dirty/existing-PR clean workflows, fork source adoption, partial manual stacks and native/direct-queue merged endpoints. Native requests guard only the highest selected head, not every member atomically; queue enrollment is not a confirmed landing.

