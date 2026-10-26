# Changelog

## 3.0.0 — 2026-10-26

### BREAKING — Judicious, size-matched planning

- New "Be judicious" contract: report a size class (small, medium, large) before writing. A change that fits in one PR gets a single ≤200-word `/goal` in chat and no plan files; medium and large plans cap each prompt at 600 words.
- Every check, gate and deliverable must trace to a source, owner constraint or repository rule. Unsourced hardening, qualification runs, paid validation, extra review rounds, benchmarks, dashboards and docs move to `Suggested follow-ups`, never acceptance.
- Acceptance is written as `Done when <user> can <interaction> and sees <result>` plus checks that can run inside the milestone. Optional evidence can no longer leave a milestone `BLOCKED` or pending.
- Removed: the seven-field purpose capsule (replaced by GOAL / PRESERVE / NON-GOALS lines), the `.docs/DEVELOPMENT_PLAN_HISTORY.md` ledger, docs-only reconciliation PRs (small drift is fixed in the stack's first commit; outcome or acceptance changes go to the owner), opt-in per-PR issue tracking, the five-way reality classification table, release-train tables (a release is prepared once after its milestones merge) and the mandatory fresh-context audit (one optional `plan-review` pass).
- `SKILL.md` reduced from 4,488 to about 1,590 words.

### Migration

- Existing 2.x plans and prompts still run. The runner reads GOAL, NON-GOALS and DONE WHEN from them; capsule fields map directly (PRODUCT OUTCOME and DEMONSTRATION → GOAL and DONE WHEN). Existing history ledgers are ignored local files and can be deleted.
- Prompts with `ISSUE_TRACKING: on` lose automated issue synchronization; manage those issues by hand.

## 2.0.0 — 2026-10-25

### BREAKING

- Generated plans now establish an evidence-grounded product contract and five-way current-reality classification before decomposition. Usable vertical slices replace layer/setup-first defaults; minimum setup and focused checks belong inside the first working slice. Prerequisite-only work must name its consumer, evidence, mandatory authority where applicable, and why it cannot be combined.
- Every generated goal and execution lane contract carries seven source-bound purpose fields: PRODUCT OUTCOME; SHORTEST COMPLETE WORKFLOW; THIS MILESTONE'S CONTRIBUTION; WORKING BEHAVIOR AND SAFETY TO PRESERVE; NON-GOALS; DEMONSTRATION AND EXPECTED RESULT; AUTHORITATIVE SOURCE / REVISION. Existing design gates assess technical validity and authorized product contribution, not technical coherence alone.
- Missing release metadata blocks preparation rather than unrelated implementation/merge unless runtime correctness demonstrably depends on release identity. The unresolved GO form preserves the missing field explicitly and requires all applicable merge gates; no invented version or false `none` is permitted.

### Migration

Regenerate goals from the current authoritative plan. Older prompts missing the capsule may be reconstructed only when that plan supplies sufficient user/workflow, scope, preservation and acceptance evidence; expose the source and inspected revision before execution. If that evidence is missing, perform bounded reconciliation of both authoritative artifacts instead of guessing from the original conversation or ignored history. Do not bulk-migrate unrelated projects, create compatibility aliases or add a second goal-state store. Material tracked-plan changes retain the reviewed, green, externally merged reconciliation prerequisite.

### Changed

- Brownfield replans map every old milestone and requirement to an explicit disposition in `DEVELOPMENT_PLAN.md`, preserve completed evidence and retain unresolved historical failures. Each execution goal cites its applicable dispositions.
- Increment verification includes concrete interaction/result and immediate safety checks; comprehensive installed proof belongs at final integration unless installation is itself the increment's outcome.
- Fresh artifact review reconstructs purpose without author rationale and compares against independent authorized requirements. Material revisions invalidate affected evidence; unresolved decisions escalate through bounded critique/readiness rather than indefinite review loops.
- Completion contracts report demonstrated product progress, remaining workflow gaps and prerequisite consumers alongside existing review, CI, merge and literal NEXT STEPS obligations. Issue identity/privacy, canonical ownership and destructive-operation safeguards remain unchanged.
- Added synthetic planner scenario inputs and outcome rubrics for S01, S02, S07, S08, S09 and S10, with capsule consumer expectations. Replaced skeleton-only and blanket unresolved-release expectations.

### Evidence and provenance

Scenario inputs and static specifications are **NOT RUN** behavioral evidence. This authoring change does not claim model behavior success, installed qualification or publication. Product-workflow and fresh-reader concepts are independently authored adaptations; no upstream repository or article wording is copied, so no package-local MIT notice is introduced.
