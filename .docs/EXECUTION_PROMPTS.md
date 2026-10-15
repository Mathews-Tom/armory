# Execution Prompts — Armory Package Effectiveness and Skill Inventory

Revision `REV-20261015-skill-inventory`: DESIGN GO — PLAN REVISION: REV-20261015-skill-inventory. The owner approved build and the recommended R0 publication/green-CI landing followed by M6 measurement. Live archives remain withheld; regression and spend remain deferred. No product branch before R0 lands; show real M6 aggregate output and stop for acceptance before M7. DEVELOPMENT_PLAN.md §§9–16 contain the contracts.

## Global execution rules (apply to every goal)

- Read the matching plan, sources, current code, merged predecessor diffs/checks and `.docs/DEVELOPMENT_PLAN_HISTORY.md` when available. Every history-read instruction below has this availability qualifier; reconstruct from provider/committed evidence when an isolated worktree lacks the ignored ledger. R0 commits the two authoritative artifacts; historical local-only overrides apply only to revisions they name.
- Before branches or product edits, record exactly one `DESIGN GO — PLAN REVISION: none`, `DESIGN GO — PLAN REVISION: REV-<id>` or `DESIGN NO-GO — REASON: <evidence>`. A material revision updates both artifacts, every affected descendant, DAG, critical path and release trains. Diagnosis is not implementation authorization.
- RECONCILIATION RULE: after user approval (1), and only with separate publication/merge authority, create `docs(plan): reconcile skill inventory design` as the docs-only prerequisite. Force-add exactly DEVELOPMENT_PLAN.md and EXECUTION_PROMPTS.md because `.docs/` is ignored; keep the history ledger local. Require review, applicable green checks and external merge before product branches. Do not reuse historical local-only exemptions.
- Use worktree-isolated `stacked-prs`, Conventional Commit titles/commits, and parent-based PRs until parents merge. Preserve Stack-Id/Stack-Position provenance. Subagents edit disjoint paths only and skip gates/formatters; the owner runs them once per phase. Run exact current-revision checks; no bot-review solicitation. Publish and merge only as separately authorized.
- All new utility measurement/recommendation/archive logic is local, deterministic and offline, with no LLM calls or network. Do not execute anything derived from logs. No real log text, identifiers, paths or names enter repository/fixtures/PRs; anonymous aggregate counts and schema key names only in the review packet.
- Approval (1) builds only the utility. Show M6 aggregates and STOP for owner acceptance before M7. Approval (2) covers exact reviewed generated-only archive items. Regression (3) separates 3a no-cost preregistration, 3b pilot money, 3c sentinel cap and 3d continuation cap; no stage implies another or inherits prior spend authority.
- Existing M2 live telemetry and M4 pilot/isolation/privacy/authorization gates remain binding. Preflight is not a live result. M5's proposal surface depends on M3, not mandatory completion of M4. M8 cannot block M6/M7 distribution.
- Verification is DEVELOPMENT_PLAN.md §14 plus each milestone's concrete acceptance scenarios; package conformance is PASS/FAIL and live effectiveness remains NOT_MEASURED absent empirical evidence. Never fabricate the obsolete 70% rubric. No root version/changelog/tag invention; package SemVer and package CHANGELOG follow the declared train.
- REVIEW: Per PR: verify scope, contracts, consumer-visible tests, privacy, failure behavior, rollback, manifest parity on every frontmatter change, focused conventional history and exact gate evidence. Whole stack: verify topology/provenance, cumulative acceptance, no lost changes, applicable fresh CI including promoted main-only jobs, and no authorization leakage.
- FINAL VERDICTS: report design verdict before merge verdict. Use `GO — RELEASE: <target> — RELEASE PREP: <pending|not-required>` only when acceptance and review/checks are complete; otherwise `NO-GO — RELEASE: <target> — REASON: <exact gate>`. Awaiting human review, publication, approval or merge is a terminal manual gate, not a polling task.
- NEXT STEPS: include current milestone disposition, release disposition, next dependency-ready milestone and every NO-GO remediation/retry gate. New utility work also gives quarantine end date or not-started, exact re-measurement command and regression status. DONE: required artifacts and evidence complete for the authorized scope; stop at every human gate.

### M1 — Replace static proxy gates with type-valid effectiveness evidence

```text
/goal Maintain M1's merged evaluation integrity contract; do not reopen completed work without new evidence.
CONTEXT: DEVELOPMENT_PLAN.md §6 M1; PRs #107–#108 merged. Historical baseline 141 definitions/133 active/8 deprecated is not a fixed future count.
OBJECTIVE: Preserve type-valid static conformance, negative routing assertions and active-package coverage.
RELEASE TRAIN: target=unversioned existing catalog; members=M1,M2,M3,M5; package versions only for actual package edits; no root release; existing rolling latest after authorized merges.
PRE-IMPLEMENTATION DESIGN GATE: Apply global rules, read DEVELOPMENT_PLAN_HISTORY.md, inspect merged evidence and review M2–M8 if semantics change. DESIGN GO — PLAN REVISION: none requires separate implementation authority; DESIGN NO-GO — REASON blocks action.
RECONCILIATION RULE: Material changes need reviewed/green/externally merged docs(plan): reconcile M1 design before new code.
PLANNED STACK (historical, not new authorization):
0. Conditional prerequisite docs(plan): reconcile M1 design.
1. PR-1 refactor(evals): separate conformance from effectiveness — merged #107.
2. PR-2 feat(evals): require active package coverage — merged #108.
CONSTRAINTS: No unrelated package-body rewrite or effectiveness inference from structure.
VERIFICATION (must pass): uv run python scripts/validate_evals.py; uv run python -m pytest tests/test_run_evals_history.py tests/test_package_types.py tests/test_evaluation_contracts.py tests/test_validate_evals.py; missing-case fixtures fail.
REVIEW: Per PR: global review rules. Whole stack: current coverage, negative behavior and machine-readable report compatibility.
FINAL VERDICTS: Apply global design/merge verdicts; never convert historical success into current live effectiveness.
NEXT STEPS: Preserve M1; M2 implementation already merged; release only through existing catalog policy; remediate any changed integrity contract before dependent work.
DONE: Observed integrity evidence and explicit disposition, not another infrastructure PR by default.
```

### M2 — Build a declared model-fit and runtime-disclosure probe

```text
/goal Preserve M2's merged model-fit contract and refresh observations before any new live study.
CONTEXT: DEVELOPMENT_PLAN.md §6 M2; M1 merged; PRs #109–#110 merged; model_fit.yaml is declaration, not current observed identity.
OBJECTIVE: Require client/model/effort/profile/tools/discovery and actual telemetry; no missing-field estimates in live evidence.
RELEASE TRAIN: target=unversioned existing catalog; members=M1,M2,M3,M5; package-local versions only; rolling latest; no new tag authorized.
PRE-IMPLEMENTATION DESIGN GATE: Apply global rules, read DEVELOPMENT_PLAN_HISTORY.md and current target evidence; reevaluate M3–M8 on schema/runtime changes. DESIGN GO — PLAN REVISION: none does not authorize paid probes; DESIGN NO-GO — REASON names missing evidence.
RECONCILIATION RULE: Material changes require docs(plan): reconcile M2 design, reviewed/green/externally merged before code.
PLANNED STACK (historical):
0. Conditional prerequisite docs(plan): reconcile M2 design.
1. PR-1 feat(model-fit): declare runtime target matrix — merged #109.
2. PR-2 feat(model-fit): capture disclosure evidence — merged #110.
CONSTRAINTS: No model request in a dry run; no inferred body disclosure or substituted telemetry.
VERIFICATION (must pass): uv run python -m pytest tests/test_model_fit.py; uv run python scripts/model_fit.py --target claude-code-opus-xhigh --profile core --dry-run; uv run python scripts/model_fit.py --target claude-code-opus-xhigh --profile full --dry-run; incomplete-target fixture fails.
REVIEW: Per PR: global review rules. Whole stack: disclosed versus declared identity and privacy boundary.
FINAL VERDICTS: Apply global rules; live-model approval remains independent.
NEXT STEPS: M3 already merged; M6 may use offline schema contract after approval/reconciliation; M8 needs refreshed actual runtime declaration.
DONE: Explicit declaration/observation distinction and no fabricated telemetry.
```

### M3 — Register a representative benchmark corpus and package strata

```text
/goal Preserve M3's registered artifact-aware corpus; do not silently repurpose it for inventory regression.
CONTEXT: DEVELOPMENT_PLAN.md §6 M3; M2 merged; PRs #111–#112 merged; 50 registered tasks and 450 cells, separate from M4's 900 cells.
OBJECTIVE: Frozen tasks, conditions, strata, exclusions, repetition and executable artifact criteria.
RELEASE TRAIN: target=unversioned existing catalog; members=M1,M2,M3,M5; existing rolling latest; no root release.
PRE-IMPLEMENTATION DESIGN GATE: Apply global rules, read DEVELOPMENT_PLAN_HISTORY.md and source epoch; review M4/M5/M8 when eligibility changes. DESIGN GO — PLAN REVISION: none requires exact source hashes; DESIGN NO-GO — REASON rejects drift.
RECONCILIATION RULE: Material changes need reviewed/green/externally merged docs(plan): reconcile M3 design.
PLANNED STACK (historical):
0. Conditional prerequisite docs(plan): reconcile M3 design.
1. PR-1 feat(skillsbench): register comparison matrix — merged #111.
2. PR-2 feat(skillsbench): add artifact-aware criteria — merged #112.
CONSTRAINTS: No paid calls, post-result task selection, unrecorded exclusions or source-pinned artifact edits.
VERIFICATION (must pass): uv run python scripts/run_skillsbench.py --validate-manifest; uv run python scripts/validate_skillsbench.py; uv run python scripts/run_skillsbench.py --dry-run; undeclared-cell/prose-only-artifact fixtures fail.
REVIEW: Per PR: global review rules. Whole stack: frozen population and executable oracle validity.
FINAL VERDICTS: Apply global rules; dry-run success is not benchmark success.
NEXT STEPS: M5 proposals independent of optional M4; M8 owns a separate approved study manifest and cannot change this corpus.
DONE: Registered corpus integrity preserved.
```

### M4 — Execute the approved current-model comparative pilot

```text
/goal Run only an explicitly authorized, named decision-scoped M4 recertification pilot; otherwise stop without live calls.
CONTEXT: DEVELOPMENT_PLAN.md §6 M4 and §§10,12,14; M3 merged; #113–#116 merged infrastructure, not pilot results. Historical ambient-isolation NO-GO remains uncleared.
OBJECTIVE: Resolve a named package decision with immutable, complete, target-scoped receipts; preserve current M2 declaration, isolation, mechanism and spend/privacy/retention gates.
RELEASE TRAIN: target=none empirical recertification; members=M4; artifacts=immutable derived evidence; no release/publication authorized.
PRE-IMPLEMENTATION DESIGN GATE: Apply global rules, read DEVELOPMENT_PLAN_HISTORY.md and all latest runtime/source/auth/isolation evidence. Do not extend old unlimited/subscription/local-only overrides to a new study. Reevaluate M8 on changes. DESIGN GO — PLAN REVISION: none requires cleared gates; DESIGN NO-GO — REASON names each unresolved blocker.
RECONCILIATION RULE: Material changes require reviewed/green/externally merged docs(plan): reconcile M4 design before new implementation.
PLANNED STACK (remaining decision-scoped work; historical infrastructure excluded):
0. Conditional prerequisite docs(plan): reconcile M4 design.
1. PR-1 test(model-fit): record approved decision-scoped pilot — scope: only a separately approved named study, cleared isolation and validated derived report. Do not invent a study to finish this row.
CONSTRAINTS: No automatic900-cell launch, ambient context/MCP/approval discovery, hidden fallback, missing telemetry, cross-model pooling or inherited spend. A separate M4 pilot must complete before every M8 live call, including its pilot; this does not block M5 proposals or M7 distribution.
VERIFICATION (must pass): uv run python scripts/omp_skillsbench.py --preflight; uv run python scripts/omp_skillsbench_results.py --preflight; uv run python scripts/omp_skillsbench_dispatch.py --preflight; declared study eligibility/identity/complete-cell/aggregation checks. Existing preflight alone is insufficient to launch.
REVIEW: Per PR: global rules and exact authorization. Whole stack: complete cells, arm engagement, controlled tool/discovery surface and valid current receipts.
FINAL VERDICTS: Apply global rules; no pilot result means NO-GO for the empirical result, not a completed benchmark.
NEXT STEPS: Clear model/isolation and approve the specific capped pilot; preserve M5's M3-only proposal dependency; keep M8 blocked until this live gate is satisfied.
DONE: Valid report or exact blocked prerequisites, with no unapproved execution.
```

### M5 — Classify and optimize the portfolio only where evidence warrants it

```text
/goal Use the merged proposal-only package-optimizer for an approved bounded scope; do not rewrite a portfolio from inventory read counts.
CONTEXT: DEVELOPMENT_PLAN.md §6 M5 and §9; M3 merged; #118 merged proposal surface. No approved applying revision is inferred.
OBJECTIVE: Evidence-linked retain/simplify/strengthen/retire/inconclusive proposals; explicit approval before every applying workflow.
RELEASE TRAIN: target=unversioned existing catalog; members=M1,M2,M3,M5; package-local SemVer only on approved changes; rolling latest; no root release.
PRE-IMPLEMENTATION DESIGN GATE: Apply global rules, read DEVELOPMENT_PLAN_HISTORY.md, selected family/evaluator/profile evidence and approval boundary. M6/M7 descriptive evidence cannot prove utility. DESIGN GO — PLAN REVISION: none requires comparable evidence; DESIGN NO-GO — REASON blocks unapproved/stale scope.
RECONCILIATION RULE: Material changes need reviewed/green/externally merged docs(plan): reconcile M5 design.
PLANNED STACK (one merged surface, one conditional applying revision):
0. Conditional prerequisite docs(plan): reconcile M5 design.
1. PR-1 feat(optimizer): propose evidence-gated package revisions — merged #118.
2. PR-2 fix(optimizer): apply approved bounded package revision — only a named approved family; no automatic new archive/merge scope.
CONSTRAINTS: M4 optional for proposal operation; no blanket shortening, static-size retirement, user inventory mutation or evidence-free benefit claims.
VERIFICATION (must pass): uv run python scripts/evaluate_package.py --path skills/package-optimizer --json; uv run python scripts/run_evals.py --package skills/package-optimizer --dry-run; approved downstream package evaluator/evals plus §14 applicable gates; refusal fixtures cover stale/missing/incomparable/unapproved evidence.
REVIEW: Per PR: global rules. Whole stack: before/after preservation and original load-bearing contracts.
FINAL VERDICTS: Apply global rules; proposal availability is not a completed portfolio optimization.
NEXT STEPS: Select an explicitly approved family only; inventory utility is M6/M7, separate from this applying workflow.
DONE: Bounded evidence-backed proposal or approved revision; no inferred portfolio-wide completion.
```

### M6 — Measure installed inventories and observed skill events locally

```text
/goal Deliver M6 measurement first; show real aggregate output and stop before recommendations.
CONTEXT: DEVELOPMENT_PLAN.md §6 M6 and §§9,10,14,15; M2 merged; approval (1) and externally merged docs reconciliation required. No product branch before these prerequisites.
OBJECTIVE: Deterministic offline OMP-first measurement, then Claude Code and actual Codex surface; installed versus disclosed versus loaded versus invoked, explicit unavailable exposure and labeled chars/4 estimates.
RELEASE TRAIN: target=skill-inventory 1.0.0; members=M6,M7; final package declaration/CHANGELOG/manifest/README in M7 PR-3 after complete reviewed train; no root version/tag. M6 alone is runnable measurement, not a catalog-release claim.
PRE-IMPLEMENTATION DESIGN GATE: Apply global rules, read DEVELOPMENT_PLAN_HISTORY.md, pin observed input versions/fields and owner roots from metadata-only evidence. Review M7/M8 on every counting/schema change. DESIGN GO — PLAN REVISION: none needs approved unchanged design; DESIGN NO-GO — REASON names schema/privacy/authorization gaps.
RECONCILIATION RULE: R0 docs(plan): reconcile skill inventory design must be reviewed/green/externally merged before code; later material changes use docs(plan): reconcile M6 design and update M7/M8 too.
PLANNED STACK:
0. Conditional prerequisite docs(plan): reconcile skill inventory design — required R0 for this revision.
1. PR-1 feat(skill-inventory): measure OMP skill exposure and reads — package-local engine/tests/schema docs, runnable measure, 2+ positive/2+ negative eval cases and CI lint/type gate. Cover URI/direct reads, custom skill-prompt loads and autoload reference protection. No installable definition, recommendation/archive placeholders or real fixtures.
2. PR-2 feat(skill-inventory): add Claude Code and Codex observations — exact §10 version/field pairs; capped initial/noninitial Claude skill_listing, streamed deduplication, Codex skills_instructions snapshots and explicit unavailable read/invoke counts, aggregate real smoke. Base PR-1.
CONSTRAINTS: No network, models, raw-log export, conversation printing, silent zero/fallback, user-root mutation or repo scripts imports. Freeze inputs and as-of. Unknown schema fails anonymously; known absent exposure is unavailable. Commit the reproducible method and synthetic fixtures only after approval.
OMP RUNTIME ALLOWLIST: optional init runtime version accepts exactly `18.11.0` and `18.11.1` (no ranges; actual parsed identity preserved; schema-v3 unchanged; non-material compatibility metadata; no M7 authorization or DAG change); any other value fails closed.
NATIVE-SOURCE PRECISION: Model-dependent Claude listing budgets can downgrade descriptions to names; no universal ~30k threshold. Keep initial/dynamic monthly/latest exposure separate. Preserve Codex compacted.replacement_history developer input_text skill blocks as a separate physical source; retain repeated/fork token telemetry, separate last sums/cumulative maxima, and never relabel as requests/billing. Native Codex read/invoke values and dates remain null/unavailable in private output too. Catalogs are approved installed-file views, not enabled/disclosed inventory: Claude registry-v2 custom resources supplement default skills; Codex manifest-backed cache versions are protected, including disabled/stale views, remote marker schema1, no hidden staging scan. Unknown metadata or missing declared resources fail closed. These implement §10's existing coverage/compaction/privacy requirements; no DAG, train, PR-count, M7/M8 or authority change.
CODEX KNOWN-ABSENCE BOUNDARY: Summary-only compactions require string message but absent/null replacement_history is valid with no invented disclosure. Plugin skill names use the manifest namespace; absent/empty resource lists fall back to optional ./skills, explicit lists replace it, malformed values/paths fail closed. Alternate manifest layouts are incomplete, not successful zeros; generated command-skill roots outside approved file views remain unmeasured.
VERIFICATION (must pass): §14 applicable Ruff → format → strict mypy → targeted pytest; schema/cohort/privacy fixtures; after explicit PEP-723 bootstrap, package-local checkout `uv run --offline --no-project --script` measurement on real logs, explicit incomplete status for malformed input, fixed-snapshot comparison and applicable CI. Unpacked archive/evaluator/packaging gates begin with final M7's UTILITY.md, not M6. Owner runs gates; subagents edit only.
REVIEW: Per PR: exact field/identity/coverage semantics and no dependency on repository-installed libraries; PEP-723 dependency bootstrap opens no logs. Whole stack: no private fixtures/output, no inferred request-level transport/cache attribution, protected symlink targets deduplicated.
FINAL VERDICTS: DESIGN GO plus passing measurement does not authorize M7; report NO-GO — RELEASE: skill-inventory 1.0.0 — REASON: awaiting owner measurement review when that is the sole remaining gate.
NEXT STEPS: Show verbatim anonymous aggregate output; ask owner to accept measurement before M7. Quarantine not started; re-measure command from §13; regression blocked on approval (3), eligibility, M2/M4.
DONE: Functional verified measurement and owner-visible aggregates; stop at this checkpoint.
```

### M7 — Propose inventory actions and support reversible managed-only quarantine

```text
/goal Deliver M7 utility only after the owner accepts M6's actual measurement output.
CONTEXT: DEVELOPMENT_PLAN.md §6 M7 and §§9–11,13–15; M6 implementation/measurement accepted; approval (1) required. Approval (2) is separate and is not a package-build prerequisite.
OBJECTIVE: Conservative keep/archive/merge proposals and crash-recoverable, human-approved OMP managed-only archive/restore; ship self-contained utility, not an auto-loaded skill.
RELEASE TRAIN: target=skill-inventory 1.0.0; members=M6,M7; preparation=complete reviewed merged train; artifacts=UTILITY.md version, package CHANGELOG, evals, manifest, README count/catalog; distribution=existing rolling latest only after separate publish/merge authority.
PRE-IMPLEMENTATION DESIGN GATE: Apply global rules, read DEVELOPMENT_PLAN_HISTORY.md and accepted M6 snapshot/schema evidence; validate ownership/coverage/protection defaults. Review M8 if population changes. DESIGN GO — PLAN REVISION: none requires approved unchanged design; DESIGN NO-GO — REASON blocks missing measurement acceptance or unsafe ownership.
RECONCILIATION RULE: Material changes need reviewed/green/externally merged docs(plan): reconcile M7 design; propagate to M8 and release train.
PLANNED STACK:
0. Conditional prerequisite docs(plan): reconcile M7 design.
1. PR-1 feat(skill-inventory): propose conservative inventory actions — mandatory private pins/high-risk/reference inputs, per-item generated-only attestations, conservative 90-day/20-opportunity eligibility and versioned similarity; no mutation.
2. PR-2 feat(skill-inventory): archive and restore managed OMP skills — fixed private manifest, per-item/list restore, same-filesystem journal, source-root listing/hash/quiescence attestations, refusal on links/tampering/recreation/conflicts; synthetic roots only. Base PR-1.
3. PR-3 feat(skill-inventory): publish self-contained utility package — UTILITY.md 1.0.0, package CHANGELOG, completed evals, manifest, README count/catalog, maintained CI gates, Cursor/Codex skip and Gemini skill-wrapper proof, PEP-723 bootstrap plus unpacked offline fresh-context verification. Base PR-2.
CONSTRAINTS: No auto body merge/deletion or user/Claude/plugin/Codex mutation. Unknown ownership stays keep until exact generated-only attestation; no root-location shortcut. Require private pins/risk/reference inputs and resolved symlink protection. Operator disables auto-learning and stops writers during approved windows; the tool never changes config. Approval (2) applies only to reviewed item digests. Batch≤10, ≥7-day/20-session dwell, 21-day per-batch quarantine, per-item restore/conflict handling and cohort deadline per §13.
VERIFICATION (must pass): §14 final gates; §15 temporary-root measure/recommend/archive/crash/restore-list/item-restore; protected roots/restored bytes and modes; coverage/pin/high-risk/dependent/ownership/quiescence refusal and unstable listing guard; independent unpacked real-target read-only validation, aggregate smoke and fresh applicable CI.
REVIEW: Per PR: global rules and reversible failure behavior. Whole stack: no repo imports, manifest on frontmatter-changing PR, current Gemini utility-as-skill wrapping and Cursor/Codex skips correctly validated; no false zero-overhead claim for Gemini.
FINAL VERDICTS: Apply global design/merge verdicts. Utility may complete without live dogfood or M8; those remain separately blocked, not claimed done.
NEXT STEPS: If archive approval absent, quarantine not started and no end date. If approved and executed, record final-move+21-day date, private manifest, exact §13 re-measurement command and coverage watch/restore triggers. Regression stays blocked pending approval (3) and M2/M4 gates.
DONE: Verified installable utility and complete evidence for approved scope; live inventory unchanged unless separately authorized.
```

### M8 — Test marginal utility only under separately authorized live gates

```text
/goal Run a narrow preregistered utility regression only after separate study and spend authorization.
CONTEXT: DEVELOPMENT_PLAN.md §6 M8 and §12; depends on M6,M3,M4; current M2 runtime declaration and M4 isolation/live-pilot gates required. No new study work under package approval alone.
OBJECTIVE: Freeze full K managed OMP ≥20 deduplicated historical skill-URI-read-attempt stratum and its public-repo eligibility before outcomes; top-20 sentinel kill first, then frozen remainder only if surviving and separately capped. ≥10 tasks per skill, 3 paired repetitions; no private ranking or task export.
RELEASE TRAIN: target=none marginal-utility study; members=M8; artifacts=frozen protocol and private immutable derived receipts; no package or publication release.
PRE-IMPLEMENTATION DESIGN GATE: Apply global rules, read DEVELOPMENT_PLAN_HISTORY.md, accepted M6 cutoff/private ranking and M3/M4 prerequisites. No-cost PR-1 needs3a, not money approval. Every live call needs completed separate M4 pilot, current M2/isolation/privacy/auth evidence and stage3b/3c/3d cap. DESIGN GO — PLAN REVISION: none does not spend; DESIGN NO-GO — REASON names infeasibility or missing authority.
RECONCILIATION RULE: Material changes need reviewed/green/externally merged docs(plan): reconcile M8 design; no post-result skill/task/SESOI replacement.
PLANNED STACK:
0. Conditional prerequisite docs(plan): reconcile M8 design.
1. PR-1 test(skill-utility): preregister paired replay protocol — private ranking through M6 at accepted closed cutoff, dedup(session identity, toolCallId), managed-only full-history URI attempts. Ambiguous/excluded records that could change ≥20 membership or which skills fall in the top 20 (rank-20/21 boundary) mean INFEASIBLE. Public protocol/salted commitment, ≥10 confirmatory tasks each plus separate pilot tasks/skills; null/large-effect simulations, fixed 10pp/10% margins and 2K two-sided family. Only add tasks before outcomes; no dropping/reranking/truncating skills. Approval 3a only.
2. PR-2 test(skill-utility): record authorized paired replay evidence — code plus anonymous crossing totals/verdict; private receipts/report outside repo, no identities/per-skill rows. After completed separate M4 pilot,3b caps40 A/A+feasibility episodes at$50, then3c exact sentinel cap and3d exact continuation cap. Base PR-1.
CONSTRAINTS: No money under(1)/(2)/(3a), inherited budget or automatic continuation. Withheld cannot access selected body; other context/tools/budgets/order/cache symmetric. Private body hashes; hard reservation/token/time limits, one attempt/cell, no retries or M3/M4 matrix edits. No-cost method fixesK; prior~32 is not a committed-method result.
VERIFICATION (must pass): Full-K eligibility, ≥10 confirmatory tasks each excluding pilots, frozen private cells/commitment; declared interval/family simulations show false continue≤0.05 under null and probability≥0.80 of≥3 crossings under declared30pp/30% effects with pilot uncertainty. Unattainable crossing at proposedN is INFEASIBLE or requires pre-outcome largerN/cap approval. Current M2, completed separate M4, explicit3b/3c/3d, complete engaged-arm receipts and repo-aware analysis; no invalid cells as zero.
REVIEW: Per PR: global rules, privacy and authority. Whole stack: repetitions not tasks, allK fixed before sentinel, no private metadata committed, gross carry overhead not task utility and no high-read-to-rare-description inference.
FINAL VERDICTS: A skill counts if either endpoint's simultaneous interval lies wholly beyond either signed margin; harm counts toward3,5pp quality check gates benefit labels only. Fewer than3/20 kills regression; pruning remains. Mechanical-only survival is SURVIVED-MECHANICAL-ONLY: named owner decision, no automatic continuation. Other survival still needs3d. Infeasibility drops study without null claim; invalid/incomplete is NO-GO. Apply global merge verdicts.
NEXT STEPS: Report regression blocked/running/killed/completed with exact gate and spend disposition; never delay M7 catalog release because M8 is unfunded. Include quarantine state and §13 re-measurement command.
DONE: Authorized complete evidence or exact manual/empirical stop; no scope expansion or general n=1 claim.
```
