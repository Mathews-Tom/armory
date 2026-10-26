# Changelog

## 3.0.1 — 2026-10-26

### Fixed

- Landing, retargeting and cleanup are delegated to `ship-workflow` (`--pr N` for one PR, or `--stack-plan` from a `stacked-prs` stack decision packet), matching the ownership contract in `stacked-prs` and `ship-workflow`. The runner no longer merges or deletes branches by hand, and a missing `ship-workflow` blocks landing. It continues only on `COMPLETE`; `WAITING` resumes the returned run before merged-base checks or dependent work.

## 3.0.0 — 2026-10-26

### BREAKING — Goal-bound execution without process inflation

- New "Stay on the goal" contract: restate GOAL, NON-GOALS and DONE WHEN before each milestone; do only the work acceptance requires; a check that cannot run now (credentials, hosted spend, human-only review) is a follow-up unless the plan or owner named it; do not repeat passing checks without a relevant change; a reviewed, green, merged milestone is done.
- One design check per milestone: `DESIGN GO`, `DESIGN GO — PLAN UPDATE` (small drift fixed in the stack's first commit) or `DESIGN NO-GO` (outcome or acceptance change; ask the owner).
- New resume/status mode rebuilds state from merged PRs, CI and current code rather than checkboxes, replacing per-project plan-completion audits.
- Merge-and-clean requires an explicit merge request; status and CI questions are read-only.
- Review is one pass per PR plus one whole-stack check, by a fresh subagent when available; re-review covers only code changed by fixes. Independent review is no longer a blocking prerequisite.
- Removed: seven-field capsule reconstruction, the history ledger, docs-only reconciliation PRs, opt-in per-PR issue tracking, mandatory independent verification lanes and release-train state machinery. Release handoff to `release-captain` after all of a release's milestones merge is unchanged.
- `SKILL.md` reduced from 5,921 to about 1,440 words.

### Migration

- 2.x prompts still run; capsule fields map to GOAL and DONE WHEN. `ISSUE_TRACKING: on` prompts no longer get automated issue mutations.

## 2.0.0

### BREAKING — Purpose-preserving execution and demonstrated completion

- Every launch and resume now reconstructs and exposes a seven-field purpose capsule from the current authoritative plan. Every implementation lane receives that capsule, inspected source/revision, remaining workflow gaps and verification stage. The capsule is a derived view, not another goal-state file or authority source.
- The existing design gate checks both technical contracts and contribution to the authorized user workflow, including module responsibilities, interfaces, data ownership, preservation and prerequisite consumers. Cold-reader comprehension compares artifacts with independently authorized requirements; readable but off-goal work is not ready. Material revision and predecessor merges invalidate affected capsules and review/design evidence together.
- Replan mappings remain authoritative in `DEVELOPMENT_PLAN.md`; each execution goal cites its applicable dispositions rather than duplicating the complete mapping.
- Prerequisites retain concrete technical, safety and mandatory-rule authority. Optional metadata or process machinery is no longer a blanket implementation/merge blocker. Unknown release fields remain visible and block preparation; they block product implementation/merge only for demonstrated runtime consumers or another actual material gate. No release version or false `none` may be invented.
- Completion requires actual reachable interaction/result and first-use safety evidence at each increment. Final integration additionally needs the comprehensive clean installed workflow; installation/deployment capabilities require clean install/run proof immediately. Green checks, internal dashboards, declared GO and an open PR do not substitute for consumer behavior or post-merge proof.
- Terminal results include actual user progress, interaction/result, remaining shortest-workflow steps, prerequisite-only work's named consumer and literal `NEXT STEPS:`. Canonical ownership, tracked-plan reconciliation, shared-drift stops, review/CI, issue privacy/idempotence, human approval and post-merge requirements remain binding.

### Migration

- Existing prompts with sufficient current authoritative plan evidence do not need a bulk rewrite: reconstruct all seven capsule fields, label the reconstruction, expose its sources and include it in the lane handoff before work. If user purpose, scope, preservation or acceptance is missing, reconcile that bounded gap in both authoritative artifacts; do not recover strategic authority from a conversation or ignored ledger alone.
- Consumers that previously required a known release target for all progress must distinguish ordinary implementation/merge eligibility from preparation. With all applicable merge gates satisfied and no demonstrated release-identity runtime dependency, the explicit output is `GO — RELEASE: unresolved — RELEASE PREP: BLOCKED — REASON: <missing field>`. This is not release completion or permission to publish.
- Re-evaluate old design/review results after material authoritative changes or predecessor merges. Keep existing tracked-plan reviewed/green/external reconciliation and canonical-writer rules; migration does not waive safety or retrospectively certify earlier evidence.
- Update completion consumers to require observed interaction/safety proof and the applicable installed-proof stage, not just CI/PR status. Preserve unavailable or unexercised evidence as such.

### Evaluation specifications

- Extended the focused package-correction case to require the actual incident-log versus grocery trigger decision, and shared-drift coverage to invalidate capsule/review evidence.
- Added package-local complete synthetic inputs and read-only decision cases for resume/handoff, scoped release metadata, authorization/destructive safety, unreachable completion, operator prerequisites, independently detected goal mismatch, old prompts/freshness and staged clean-install proof (S03–S10).
- Fixture documents, rubric assertions and source contracts are authored specifications. They do not establish observed model behavior, actual CI/merge results, skill loading or installed-product qualification.

### Provenance

Purpose transfer and bounded cold-reader/readiness concepts are independently authored adaptations informed by elephant-goldfish revision `b8ebb3d6b00e39fbb6c619faa27f5bb994091d78` and Dave Rensin's explanatory article. No upstream repository or article wording is copied; no package-local MIT notice is needed for this independently authored text. No upstream workflow engine, extra persistent store or mandatory multi-pass review ritual is adopted. Repository-level attribution records the source links and manual resynchronization boundary.
