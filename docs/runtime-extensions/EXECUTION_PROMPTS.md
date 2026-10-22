# Execution Prompts — Native Runtime Extensions

## Extension campaign entry

This campaign delivers five optional, self-contained native extension packages in armory: Verification Receipts (M9), Resume Brief (M10), Delivery Radar (M11), Run Preflight (M12), and Impact Journal (M13). Execution is authorized through implementation, native/local checks, ordinary coding sessions, configured reviews, fresh CI, externally observed merges, merged-base proof and verified task-owned cleanup, within the boundaries below. Creating or reading these documents does not itself execute product work.

**Authoritative path override:** `PLAN` means `docs/runtime-extensions/DEVELOPMENT_PLAN.md`; `PROMPTS` means `docs/runtime-extensions/EXECUTION_PROMPTS.md`. Both paths are repository-relative committed files. Every design gate, reconciliation, implementation lane and release check must load their current committed revisions, overriding milestone-runner's default authoritative paths. No ignored document is authoritative. Architecture references §17.1–§17.9 and milestone references §6 Section E resolve within PLAN.

**Entry prerequisite:** the docs-only `docs(plan): define native extension milestones` bootstrap PR containing this pair must be reviewed for privacy and contract parity, pass applicable checks, and be externally merged before M9 product work. Reload the merged pair, verify a clean canonical checkout, inspect current code and bootstrap/provider evidence, and perform M9's design gate. The bootstrap is outside the twelve product PRs. Never execute unrelated campaigns.

### Scoped global rules for M9–M13

These rules apply only to M9–M13. Existing benchmark/study approvals and refusal boundaries remain unchanged; this campaign does not authorize unrelated work. `ISSUE_TRACKING: off`.

- Bootstrap first: a clean isolated worktree creates the two public-safe extension-only documents under `docs/runtime-extensions/`, with all M9–M13 requirements/scenarios/DAG/trains and no private source/evidence references. Review privacy and source-contract parity, open `docs(plan): define native extension milestones`, require applicable green checks and external merge, then reload the committed pair. Commit only the public extension contracts; never publish the ignored history or private inputs. Bootstrap is a prerequisite, not a product PR in M9's four-PR estimate.
- Explicit authoritative paths apply to every design gate, reconciliation PR and lane. Only the canonical owner writes `.docs/DEVELOPMENT_PLAN_HISTORY.md`, with `runtime-extensions/M#` namespace; rebuild missing evidence from committed artifacts/provider CI/current source. Keep this the only history and verify it is ignored.
- Before branches, gather current design evidence in isolated read-only lanes when available. The canonical owner decides/records the verdict and updates both authoritative artifacts plus every affected descendant; material changes require a docs-only reviewed/green/externally merged reconciliation PR. A revision diagnosis does not authorize code; repeat the gate after reconciliation.
- Use `stacked-prs`, Conventional Commits, atomic attribution-free commits and root-to-leaf promotion. Each child starts on the preceding PR branch, not main. Canonical owner alone changes topology, merges, cleans branches or appends ledger evidence. An implementation lane never creates/edits issues or the authoritative pair and must report an additional PR requirement before branching it.
- Default sequential M9 → M10 → M11 → M12 → M13; graph dependencies are M9 → each descendant, not a false chain. Shared catalog/CI edits prohibit concurrent implementation without an explicit isolation/conflict design. A genuine downstream external blocker does not block other current-DESIGN-GO independent descendants.
- The current execution authorization permits continuing through implementation, native/local checks, ordinary coding sessions, configured reviews, CI, verified merges and task-owned cleanup without per-milestone confirmation. No experiments, model probes, benchmark campaigns, account switching, persistent owner install, live-owner-vault mutation, tags or manually published release. Human trust/policy and out-of-envelope prerequisites remain real stops; never bypass them to achieve unattended execution.
- Each feature is optional, self-contained and native only for actually exercised hosts/surfaces. Shared pure rules do not flatten permissions/cancellation/authority. Default/full legacy profiles and all-in-one plugin do not auto-enable extensions.
- Apply §17.7 common gates plus the goal's scenarios. Every new command is a planned interface M9 must implement, not an existing passing gate. Missing native tools, trust, test data or executed cases fail the affected check; never skip-green. Native host runtime smoke is distinct from mocked native tests and static conformance. No live evals/model probes are required for product acceptance.
- Prefix rollout uses PLAN's explicit stage matrix. PR-1 infrastructure has fixture-backed packaging tests; core-only feature prefixes run `check_extensions.py --feature <name> --stage core`; M9 OMP prefix runs `--stage omp`. These certify only implemented stages with `feature_complete=false`. Omit definition/catalog/marketplace/install/release entries until each feature's final package-bearing PR. Default full/native-smoke remains nonzero until both adapters/package exist; full cumulative gates remain required for milestone GO.
- Every feature's docs/CHANGELOG/catalog/evals/tests/native artifacts ship in its milestone. Package `1.0.0` metadata is source-traceable new-package policy; no root version bump. Each train has required preparation artifacts `none`; no release-captain PR or tag is needed. Existing main workflow may update rolling latest after an authorized merge; observe that existing effect rather than publish again.
- Keep frozen seven-type benchmark sample/treatments/tasks/pins/results intact. Classify new native packages as excluded, and replace only validator coupling between current taxonomy and historical eligibility with explicit registered historical types. Prove unchanged frozen identities.
- Per-PR reviews plus whole-stack review and an independent external gate verifier are mandatory. Missing subagent isolation is reported; do not mislabel self-review independent. Check current head/base and fresh applicable CI after promotion, including main-only packaging. No external/bot review solicitation or reviewer mentions.
- LANE DONE means the complete, exercised, reviewed/current-green stack plus exact evidence/verdict returned to canonical owner. It excludes merging, ledger writes, release preparation and cleanup. CANONICAL OWNER COMPLETION means observed root-to-leaf external merge, merged-base smoke, history append, train disposition, cleanup and automatic continuation to next ready milestone.
- Every terminal result prints a design verdict before exactly one release-aware merge verdict, then literal `NEXT STEPS:` with current disposition, release state, next runnable independent milestone and NO-GO remediation/retry gate. Pending checks, missing review and incomplete native proof are not GO.

## Native runtime extension goals

Each block is paste-ready and incorporates the scoped rules above and all referenced PLAN contracts. M9 has no feature predecessor; M10–M13 each depend only on externally merged M9. Default execution order remains M9 → M10 → M11 → M12 → M13, with independent descendants runnable around a genuine affected-scope external blocker.

### M9 — Ship native packaging with cross-harness Verification Receipts

```text
/goal Deliver M9 as a reviewed stack of four PRs, establishing usable native packages and Verification Receipts in OMP and Claude Code.

CONTEXT: PLAN §6 Section E, M9, and §17 complete runtime architecture/record/lifecycle/verification contracts. Prerequisite: public-safe docs bootstrap externally merged. No dependency on any live study. Repo uses Python 3.12/uv; M9 adds feature-owned TS/Bun tooling.
OBJECTIVE: Both detached native artifacts run configured real local verification, preserve successful/failed/cancelled results and detect scoped source drift; full owned install/update/disable/remove lifecycle works without affecting existing packages/data.
RELEASE TRAIN: target=unversioned verification-receipts; included milestones=M9; preparation trigger=M9 externally merged; required artifacts=none at train preparation; package definition 1.0.0/CHANGELOG/catalog ship with implementation; release verification=merged-base check_extensions.py --feature verification-receipts --native-smoke plus common gates; publication=existing main rolling latest only, no tag/new registry/manual publish.
ISSUE_TRACKING: off.

PRE-IMPLEMENTATION DESIGN GATE:
1. Read PLAN M9, source map, this exact committed prompt revision, and canonical .docs/DEVELOPMENT_PLAN_HISTORY.md when present; reconstruct absent history from committed/provider/current-code evidence.
2. Inspect current registry/install/adapter/evaluator/package/workflow consumers, actual native CLI/types, historical benchmark eligibility/pins, and bootstrap PR checks/merge. No fabricated predecessor evidence for root M9.
3. Revalidate all acceptance/scenarios, verification commands, trust/cancellation/storage/permission boundaries and release fields; review downstream M10,M11,M12,M13 on shared contract changes.
4. Canonical owner appends timestamp, runtime-extensions/M9, verdict, trigger, citations, inspected revisions, changed sections, descendant impact and implementation authorization to the one ignored history.
5. No mismatch: DESIGN GO — PLAN REVISION: none. Material mismatch: revise both authoritative files and all affected descendants/DAG/trains, record DESIGN GO — PLAN REVISION: <entry IDs>, but block code until reconciliation merges and a fresh gate says no revision. Unestablished validity: DESIGN NO-GO — REASON: <evidence>; stop affected closure.

RECONCILIATION RULE: docs(plan): reconcile M9 design is a separate docs-only prerequisite, reviewed/green/externally merged before code; repeat the design gate afterward.
PLANNED STACK:
0. Conditional prerequisite docs(plan): reconcile M9 design — public authoritative pair only; never the ignored history or private inputs.
1. PR-1 feat(extensions): add host-aware native package support — registry/metadata, complete consumer migration, Bun TS gates, build/check CLI, explicit historical benchmark eligibility and excluded classifications. Independently green; do not advertise incomplete receipts or activate new packages in legacy profiles.
   Verification: uv run python -m pytest tests/test_extensions_packaging.py tests/test_package_types.py tests/test_install_skills.py tests/test_generate_adapters.py tests/test_validate_skillsbench.py -q; fictional complete native fixtures only, no real feature catalog registration.
2. PR-2 feat(receipts): record scoped command verification — pure schema/state rules, bounded argv execution/helper/storage, scope fingerprints, interruption/concurrency/cancellation, real local command scenarios; base PR-1.
   Verification: uv run python scripts/check_extensions.py --feature verification-receipts --stage core; emit feature_complete=false, keep feature unregistered.
3. PR-3 feat(receipts): add native OMP commands — actual installed factory/command/widget/text integration and native isolated host proof; base PR-2.
   Verification: uv run python scripts/check_extensions.py --feature verification-receipts --stage omp; real detached OMP smoke, no cross-host compatibility/catalog activation.
4. PR-4 feat(receipts): add Claude mod and detached lifecycle proof — static explicit effects/relative pure imports, native validation/test, real command smoke, two-host detached install/update/disable/remove, reproducible distribution, EXTENSION.md/evals/docs/CHANGELOG/manifest/compatibility; base PR-3.
   Verification: full milestone commands plus uv run python scripts/check_extensions.py --all --catalog. First real feature definition/catalog/release entry activates only here, alongside complete native artifacts.
CONSTRAINTS: All scoped global rules. No generic framework, daemon, arbitrary shell interpolation, automatic command interception or permission bypass. No Node/Bun APIs inside Claude mod; bundled helper only through explicit host effects. Data outside install tree, private by default. Preserve seven frozen study definitions/treatments/digests and existing study authority.
VERIFICATION (must pass): PLAN common gates; uv run python -m pytest tests/test_package_types.py tests/test_install_skills.py tests/test_generate_adapters.py tests/test_validate_skillsbench.py -q; uv run python scripts/check_extensions.py --feature verification-receipts --native-smoke. V1-V5 and S1: real successful/failed child, covered/unrelated changes, input mutation during execution, cancellation with descendant cleanup, re-opened receipts, nonclobber concurrent writes, exact-owned lifecycle rollback, byte-identical rebuilds and foreign data preservation. Run real detached host paths, not only stubs.
REVIEW:
Per PR: scope and consumer contracts, meaningful boundary tests, private data safety, cancellation/resource limits, manifest/eval/CI parity, atomic conventional commits, and exact current-revision check output.
Whole stack: valid bases, two exercised native artifacts, no untested advertised surface, benchmark population/pins unchanged, explicit profile opt-in, complete lifecycle and merged-base verification plan. Independent verifier re-derives provider/CI/native evidence.
FINAL VERDICTS:
- Print design verdict first.
- GO — RELEASE: unversioned verification-receipts — RELEASE PREP: not-required only after complete acceptance and every stack PR reviewed/current-green/correctly based.
- Otherwise NO-GO — RELEASE: unversioned verification-receipts — REASON: <exact pending/failed/unobserved gate>.
NEXT STEPS:
1. Current milestone: merge reviewed stack (canonical owner only), already merged, or stop on NO-GO.
2. Release: not-required preparation; package-local artifacts already in stack; observe existing rolling assets after authorized merge.
3. Next milestone: M10 only after externally observed M9 merge and repeated design gate; if M9 blocked, NO NEXT MILESTONE — all extension descendants depend on M9.
4. On NO-GO name exact remediation/retry gate; otherwise not applicable.
DONE: Implementation lane returns complete stack/evidence/verdict; canonical owner externally merges, runs merged-base smoke, appends canonical evidence, cleans only task-owned verified branches and continues.
```

### M10 — Ship freshness-checked Resume Brief

```text
/goal Deliver M10 Resume Brief for selected projects in both native hosts as a reviewed two-PR stack.

CONTEXT: PLAN M10 and runtime feature/identity/privacy/verification contracts; M9 externally merged with observed predecessor PR/diffs/CI/verification. Use only the explicit committed PLAN/PROMPTS paths.
OBJECTIVE: /armory-brief presents objective/plan revision, last verified evidence, branch/worktree/PR, blockers/next action and retained approval boundaries; changed branch/plan/blocker facts produce source-linked discrepancies, never automatic resume authority.
RELEASE TRAIN: target=unversioned resume-brief; included milestones=M10; preparation trigger=M10 externally merged; required artifacts=none at train preparation; package-local definition/version/CHANGELOG/catalog included in stack; release verification=merged-base check_extensions.py --feature resume-brief --native-smoke plus common gates; publication=existing rolling latest only.
ISSUE_TRACKING: off.

PRE-IMPLEMENTATION DESIGN GATE:
1. Read PLAN M10/source map/current prompt and .docs/DEVELOPMENT_PLAN_HISTORY.md when present; reconstruct absent evidence.
2. Inspect merged M9 diffs, native package/storage/command contracts, predecessor PR/CI/smoke evidence, actual native session/handoff formats and bounded discovery.
3. Revalidate objective/interfaces/acceptance/verification/risks/release; shared identity/storage changes require review of M11,M12,M13, not invented feature dependencies.
4. Canonical owner appends timestamp, namespace, verdict, exact revision/evidence, changed sections and descendant authorization to sole ignored ledger.
5. DESIGN GO — PLAN REVISION: none authorizes code. A material mismatch updates both authoritative files and every affected descendant/DAG/trains; DESIGN GO — PLAN REVISION: <entry IDs> blocks code pending reviewed/green/merged reconciliation and repeated no-revision gate. DESIGN NO-GO — REASON: <evidence> stops affected closure.
RECONCILIATION RULE: docs(plan): reconcile M10 design is a separate docs-only prerequisite, externally merged before product work.
PLANNED STACK:
0. Conditional prerequisite docs(plan): reconcile M10 design.
1. PR-1 feat(brief): compare selected project evidence — typed normalized card, explicit repository/artifact scope, native bounded source readers, current/recorded discrepancy rules and authorization non-transfer; functional local CLI/helper scenarios.
   Verification: uv run python scripts/check_extensions.py --feature resume-brief --stage core; no package definition/catalog/release entry yet.
2. PR-2 feat(brief): add cross-host resume views — native literal commands/text/widget renderers, detached two-host stale-card proof, standalone package/evals/catalog/compatibility/docs/CHANGELOG; base PR-1.
   Verification: full milestone native-smoke plus uv run python scripts/check_extensions.py --all --catalog; atomically activate complete package here.
CONSTRAINTS: Scoped global rules. No transcript bulk scan, arbitrary instruction execution, automatic mutations or secondary authoritative plan/memory/receipt ledger. Old approvals never become host-portable grants; unknown input remains unknown.
VERIFICATION (must pass): PLAN common gates; uv run python scripts/check_extensions.py --feature resume-brief --native-smoke. B1/S1 and relevant V3/V5: real temporary project plus native session/handoff, record/reopen, mutate branch/plan/blocker, inspect exact discrepancy/current source, missing/unreadable source and expired/cross-host approvals, detached install/reload with preserved project files.
REVIEW:
Per PR: exact scope, source identity/provenance, native schema errors, containment/injection/privacy, meaningful discrepancy/refusal tests, package parity and current command output.
Whole stack: reviewed/current-green parent-based PRs, no competing authority/store, actual two-host behavior including headless text, fresh independent external verification and complete contract.
FINAL VERDICTS:
- Design verdict precedes merge verdict.
- GO — RELEASE: unversioned resume-brief — RELEASE PREP: not-required requires complete acceptance, reviews/current CI/verification and topology.
- Otherwise NO-GO — RELEASE: unversioned resume-brief — REASON: <blocking gate>.
NEXT STEPS:
1. Current: canonical owner merges reviewed stack, records already merged, or stops affected milestone on NO-GO.
2. Release: no separate preparation/publication; observe rolling package only after authorized merge.
3. Next: M11 after a current design gate on merged M9; on M10-only blocker, SKIP M10 FOR NOW; RUN M11 — independent of M10.
4. NO-GO: concrete remediation and exact retry gate; otherwise not applicable.
DONE: Lane returns reviewed green stack/evidence; canonical owner verifies external merge, re-runs native acceptance, appends history, performs task-owned cleanup and continues.
```

### M11 — Ship selected-stack Delivery Radar

```text
/goal Deliver M11 read-only Delivery Radar in both hosts as a reviewed two-PR stack.

CONTEXT: PLAN M11 and delivery/native/verification contracts; M9 externally merged. M10 is not a dependency. Inspect current GitHub CLI/API fields and actual configured read permissions.
OBJECTIVE: /armory-delivery separates implementation, verification, review, merge and publication; binds state to observed head/base/time; identifies agent work/external wait/owner decision without false green or remote mutations.
RELEASE TRAIN: target=unversioned delivery-radar; included milestones=M11; preparation trigger=M11 externally merged; required artifacts=none at train preparation; package-local metadata/CHANGELOG/catalog in stack; release verification=merged-base check_extensions.py --feature delivery-radar --native-smoke plus common gates; publication=existing rolling latest only.
ISSUE_TRACKING: off.

PRE-IMPLEMENTATION DESIGN GATE:
1. Read PLAN M11/source map/current prompt and .docs/DEVELOPMENT_PLAN_HISTORY.md when present; reconstruct missing evidence.
2. Inspect M9 merged code/diffs/provider outcomes/CI/native verification and actual GitHub check/review/base/required-policy observability.
3. Revalidate scope/interfaces/acceptance/verification/risks/release and rate-limit/cancellation semantics; common identity/lifecycle changes require M10,M12,M13 review.
4. Canonical owner appends namespace/timestamp/revision/verdict/citations/changes/descendant authorization to sole ignored history.
5. Report DESIGN GO — PLAN REVISION: none; or revise both public authoritative files and affected descendants/DAG/trains, report DESIGN GO — PLAN REVISION: <entry IDs> and block code pending reconciliation/repeated gate; or DESIGN NO-GO — REASON: <blocking evidence>.
RECONCILIATION RULE: docs(plan): reconcile M11 design must be docs-only, reviewed/green/externally merged before changed implementation.
PLANNED STACK:
0. Conditional prerequisite docs(plan): reconcile M11 design.
1. PR-1 feat(delivery): derive source-bound stack readiness — paginated read-only GitHub CLI adapter, normalized independent states, head/base/review/required-check provenance, missing/error states, transition deduplication and local protocol-faithful scenarios.
   Verification: uv run python scripts/check_extensions.py --feature delivery-radar --stage core; no package definition/catalog/release entry yet.
2. PR-2 feat(delivery): add native read-only radar views — selected repository/stack commands, session/worktree correlation only when observed, bounded session refresh/disposal, real read-only public-PR two-host proof, package/evals/catalog/compatibility/docs/CHANGELOG; base PR-1.
   Verification: full milestone native-smoke plus uv run python scripts/check_extensions.py --all --catalog; atomically activate complete package here.
CONSTRAINTS: Scoped global rules. No merge/review solicitation/mention/thread-resolution/cleanup/publication API. Unknown state is not success, task count is not progress, cached green is not current CI. No global feeds/daemon; escape repo-controlled strings.
VERIFICATION (must pass): PLAN common gates; uv run python scripts/check_extensions.py --feature delivery-radar --native-smoke. D1/S1 and relevant V3/V5: paginated fixtures with old/new head and unchanged-head/new-base, dismissed review/unresolved thread, missing required policy, pending/unavailable checks/rate limits; actual selected public PR read in both hosts with exact observed IDs; no remote mutations and timer stops on unload/cancel.
REVIEW:
Per PR: complete read pagination/provenance, unknown precedence, no false merge-ready state, no write operations, bounded resource use, package parity and meaningful behavioral checks.
Whole stack: correct bases/current-green CI, independent external review/verification, native surfaces observed, current head/base binding and no unmeasured claims.
FINAL VERDICTS:
- Print current design verdict first.
- GO — RELEASE: unversioned delivery-radar — RELEASE PREP: not-required only with complete acceptance and reviews/current checks/topology.
- Otherwise NO-GO — RELEASE: unversioned delivery-radar — REASON: <specific gate>.
NEXT STEPS:
1. Current: canonical owner merges reviewed stack, records merged, or stops on NO-GO.
2. Release: no separate preparation; observe existing rolling assets.
3. Next: M12 after current design gate on M9; M11-only blocker permits SKIP M11 FOR NOW; RUN M12 — independent of M11.
4. NO-GO: exact remediation/retry gate; otherwise not applicable.
DONE: Lane returns complete reviewed green stack and exact evidence; canonical owner observes merges, re-runs merged-base proof, appends history, cleans verified task branches and continues.
```

### M12 — Ship Run Preflight for one existing managed runner boundary

```text
/goal Deliver M12 Run Preflight with a concrete OMP SkillsBench dispatch admission boundary as a reviewed two-PR stack, without making a provider call.

CONTEXT: PLAN M12 and complete preflight/source/authorization contracts; M9 externally merged. Inspect scripts/omp_skillsbench.py and scripts/omp_skillsbench_dispatch.py:dispatch_cell. Existing CLI remains preflight-only. Existing live-study holds are neither implementation dependencies nor cleared authority.
OBJECTIVE: /armory-preflight reports ready/blocked/unknown for a declared managed run; missing, expired or drifted prerequisites refuse the actual owned spawn boundary; fresh synthetic bounded authority admits exactly one local sentinel.
RELEASE TRAIN: target=unversioned run-preflight; included milestones=M12; preparation trigger=M12 externally merged; required artifacts=none at train preparation; package-local metadata/CHANGELOG/catalog in stack; release verification=merged-base check_extensions.py --feature run-preflight --native-smoke plus common/OMP no-cost preflights; publication=existing rolling latest only.
ISSUE_TRACKING: off.

PRE-IMPLEMENTATION DESIGN GATE:
1. Read PLAN M12/source map/current prompt and .docs/DEVELOPMENT_PLAN_HISTORY.md when present; reconstruct absent evidence.
2. Inspect M9 merged diffs/PR/CI/native smoke, frozen existing OMP contracts/dispatch boundary and independently observable profile/quota/cap/checkpoint fields.
3. Revalidate admission race, required-versus-advisory facts, missing quota, current authorizations, existing enforceable limits, source/cell binding and all acceptance/release fields. Shared contract drift requires M10,M11,M13 review. Never invent financial enforcement or a new campaign.
4. Canonical owner appends timestamp/namespace/inspected revision/verdict/citations/changes/downstream authorization to ignored canonical history.
5. DESIGN GO — PLAN REVISION: none authorizes feature code, not a paid run. Material changes revise both artifacts and affected descendants/DAG/trains, produce DESIGN GO — PLAN REVISION: <entry IDs> and block implementation until reconciliation/repeated gate. Unresolved safety/information yields DESIGN NO-GO — REASON: <evidence>.
RECONCILIATION RULE: docs(plan): reconcile M12 design is a separate reviewed/green/externally merged docs-only prerequisite.
PLANNED STACK:
0. Conditional prerequisite docs(plan): reconcile M12 design.
1. PR-1 feat(preflight): bind run prerequisites to managed admission — feature-owned schemas/rules and explicit versioned project-local OMP dispatch integration, identity/freshness validation immediately before actual managed spawn, preserve runner enforcement and no-live CLI policy; local sentinel positive/negative proof.
   Verification: uv run python scripts/check_extensions.py --feature run-preflight --stage core; real local sentinel, no package definition/catalog/release entry yet.
2. PR-2 feat(preflight): add native campaign readiness commands — two host adapters/views, configured nonsecret observations, explicit unknown quota and scope limits, no-cost detached native proof, package/evals/catalog/compatibility/docs/CHANGELOG; base PR-1.
   Verification: full milestone native-smoke plus uv run python scripts/check_extensions.py --all --catalog; atomically activate complete package here.
CONSTRAINTS: Scoped global rules. No live benchmark cell, new study, pricing claim, automatic quota assumption/account switch, universal guard or spend cap the runner cannot enforce. Distributed extension imports no Armory checkout scripts. Existing injected-runner boundary remains the integration seam; real sentinel process is not a provider stand-in result or completed campaign.
VERIFICATION (must pass): PLAN common gates; uv run python -m pytest tests/test_omp_skillsbench.py tests/test_omp_skillsbench_dispatch.py -q; uv run python scripts/omp_skillsbench.py --preflight; uv run python scripts/omp_skillsbench_dispatch.py --preflight; uv run python scripts/check_extensions.py --feature run-preflight --native-smoke. P1/S1: missing/expired/stale source/config/data/account/cell/cap/checkpoint blocks before spawn, unsupported cap fails, quota unknown retained, explicitly bounded fresh synthetic authority spawns one harmless real child, immediate source drift refuses. Assert zero hosted calls and unchanged frozen study identities.
REVIEW:
Per PR: managed spawn boundary actually consumes admission, no boolean-only admission, exact required inputs/expiry/cap semantics, existing live-study holds unchanged, no credential output, meaningful race/refusal tests and current gates.
Whole stack: read-only readiness except explicit synthetic managed child, complete real two-host path, runner-owned caps and documented unobserved bypass scope, independent external verification and green parent-based PRs.
FINAL VERDICTS:
- Design verdict first.
- GO — RELEASE: unversioned run-preflight — RELEASE PREP: not-required requires complete product acceptance, reviews/checks/topology, not a paid-run result.
- Otherwise NO-GO — RELEASE: unversioned run-preflight — REASON: <specific gate>.
NEXT STEPS:
1. Current: canonical owner merges reviewed stack, records merged, or stops affected goal on NO-GO.
2. Release: no separate preparation; observe rolling distribution.
3. Next: M13 after a current M9-based design gate; M12-only blocker permits SKIP M12 FOR NOW; RUN M13 — independent of M12.
4. NO-GO: exact missing prerequisite/remediation/retry gate; otherwise not applicable. Preserve existing study holds in either outcome.
DONE: Lane returns exercised complete stack/evidence; canonical owner verifies external merge, reruns no-cost merged-base/native checks, appends history, cleans task-owned verified branches and continues.
```

### M13 — Ship opt-in Impact Journal using Tessera

```text
/goal Deliver M13 reviewed initiative-linked Impact Journal using existing Tessera project captures as a reviewed two-PR stack.

CONTEXT: PLAN M13 and complete journal/privacy/native contracts; M9 externally merged. Resolve current real Tessera capture/list/read transport for both hosts and establish an isolated test vault/principal; no live-owner-vault writes or daemon/schema changes.
OBJECTIVE: /armory-impact queues evidence-first drafts at opted-in meaningful boundaries, groups sources by initiative, preserves unknown outcomes, allows correction/discard and saves only exact explicitly reviewed content through Tessera with linked correction/outcome records.
RELEASE TRAIN: target=unversioned impact-journal; included milestones=M13; preparation trigger=M13 externally merged; required artifacts=none at train preparation; package-local metadata/CHANGELOG/catalog in stack; release verification=merged-base check_extensions.py --feature impact-journal --native-smoke plus common gates; publication=existing rolling latest only.
ISSUE_TRACKING: off.

PRE-IMPLEMENTATION DESIGN GATE:
1. Read PLAN M13/source map/current prompt and .docs/DEVELOPMENT_PLAN_HISTORY.md when present; reconstruct missing evidence.
2. Inspect M9 merged diffs/PR/CI/native verification; inspect actual Tessera capture/list/read schema, context/principal permission/deduplication and installed transport each host can invoke. Establish current service availability and actual test transport without treating source/schema inspection as runtime proof.
3. Revalidate private queue/claim provenance/human-review/linked correction semantics, exact selected test principal and no-exfiltration policy, all acceptance/verification/release fields. Common identity/lifecycle drift requires M10,M11,M12 review.
4. Canonical owner appends namespace/timestamp/inspected revision/verdict/citations/changed sections/downstream authorization to sole ignored history.
5. DESIGN GO — PLAN REVISION: none authorizes feature work with isolated test data, not owner-vault writes. Material drift updates both artifacts/affected descendants/DAG/trains and produces DESIGN GO — PLAN REVISION: <entry IDs>, blocking code until docs reconciliation merges and repeated gate passes. Missing real storage/transport/trust yields DESIGN NO-GO — REASON: <evidence>; finish other independent authorized goals without replacing Tessera.
RECONCILIATION RULE: docs(plan): reconcile M13 design is separate docs-only, reviewed/current-green/externally merged before implementation.
PLANNED STACK:
0. Conditional prerequisite docs(plan): reconcile M13 design.
1. PR-1 feat(impact): queue reviewed initiative evidence — contribution envelope, deterministic boundary opt-in, initiative/source deduplication, private draft editing/discard, selected-principal existing Tessera transport, exact-content save and linked correction/reconciliation; real isolated storage proof.
   Verification: uv run python scripts/check_extensions.py --feature impact-journal --stage core; real isolated test storage, no package definition/catalog/release entry yet.
2. PR-2 feat(impact): add native contribution review flows — OMP/Claude commands/text/UI, headless queue-only behavior, deferred follow-up date on next invocation, both-host detached queue/review/save/correct/401 proof, package/evals/catalog/compatibility/docs/CHANGELOG; base PR-1.
   Verification: full milestone native-smoke plus uv run python scripts/check_extensions.py --all --catalog; atomically activate complete package here.
CONSTRAINTS: Scoped global rules. No productivity score, activity-as-impact, inferred authorship/business savings, per-turn interruption, automatic model calls, annual compiler, scheduler/daemon or parallel journal database. Project facets only, not agent retrospectives. Credentials stay in supported host/client secret handling. Never silently retry ambiguous capture or use metadata-only duplicate capture as an update.
VERIFICATION (must pass): PLAN common gates; uv run python scripts/check_extensions.py --feature impact-journal --native-smoke. I1/S1 and relevant V3/V5: two source sessions one initiative, exact draft/source/role/outcome assertions, edit/discard, headless queues, reviewed exact-content real capture/read in isolated principal/vault, linked correction/outcome, lost-write-response reconciliation, offline/401 unsaved state and explicit context separation. No owner-vault mutation or fake successful storage.
REVIEW:
Per PR: consent/principal/privacy, contribution/evidence distinctions, dedup/ambiguous-write handling, actual transport availability, meaningful correction/refusal tests, package parity and current gate output.
Whole stack: complete two-host real storage/review path, no competing authoritative store, no unsupported impact claim, independent external verification, current-green correctly based PRs and full contract.
FINAL VERDICTS:
- Print design verdict before merge verdict.
- GO — RELEASE: unversioned impact-journal — RELEASE PREP: not-required only after full acceptance/review/current checks/topology.
- Otherwise NO-GO — RELEASE: unversioned impact-journal — REASON: <specific gate>; real storage/trust failure cannot be skipped into GO.
NEXT STEPS:
1. Current: canonical owner merges reviewed stack, records merged, or stops M13 on NO-GO.
2. Release: no separate preparation; observe existing rolling distribution after authorized merge.
3. Next: earliest unresolved dependency-ready goal among M10–M12 after fresh gate; otherwise none when M9–M13 all externally merged/verified. Report blocked goals rather than call campaign complete.
4. NO-GO: exact service/principal/trust/transport remediation and retry gate; otherwise not applicable.
DONE: Lane returns reviewed green stack/evidence; canonical owner externally merges, runs merged-base native proof, appends canonical evidence, cleans task-owned verified branches and reports complete only when every M9–M13 acceptance gate is observed.
```
