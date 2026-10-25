# Product-workflow scenario inputs

Evidence status: **NOT RUN**. These are synthetic source documents, observations and requested actions, not successful agent outputs or real CI. The eval caller must explicitly read the named section; the evaluator does not materialize fixtures. Planning may write only its two authoritative artifacts, ignored history and necessary exact ignore rule. No product execution, GitHub mutation, installation or model calls are authorized here.

## S01 — Empty local task CLI

Independent owner requirements, revision TASK-1: A developer working offline records tasks and reads them back. Deliver `tasks add "buy milk"` followed by `tasks list`, showing `1 buy milk`. Store ID/text in a user-selected local JSON file; no network, login, background service or integration. Empty list prints `No tasks`; invalid empty text fails without changing storage. Existing records must survive adding another task. Optional future export is not needed for first use.

Repository observation: empty directory, no package manager, CI or implementation established. Source architecture notes propose: M1 orchestration dashboard, M2 plugin integration framework, M3 broad qualification harness, M4 storage, M5 commands. No evidence connects the first three to add/list correctness. Choose a minimal documented runtime and focused checks as a planning assumption, not an observed installed tool.

Action: Generate a plan and actionable goals, with shortest complete workflow, responsibilities (CLI parsing versus storage), interface inputs/outputs, data ownership and safety boundaries. Decide the first usable slice and disposition the proposed machinery. Transfer the same purpose into every goal's seven-field capsule and specify what a fresh execution lane must receive. Expected decision: add/list plus minimum setup/checks first; optional machinery deferred; no product implementation. A capsule must identify TASK-1 and current plan revision, not this fixture as an execution ledger.

### S01 → S04 → S06 continuity input protocol

For separately authorized installed qualification, retain the actual S01-generated plan and goals, exact source identities and independent TASK-1 request. Give those artifacts—not a canned replacement plan or the author's narrative—to a fresh runner context for S04. Supply a synthetic partial-predecessor observation: the current add command stores `1 buy milk` with existing records preserved, but no list interaction has been demonstrated; any claimed review/CI state is fixture input only. Ask it to recover the same TASK-1 purpose and render the next lane handoff without expanding into accounts, cloud, a detail command or orchestration. If S01 combined add/list into one milestone, treat add as partial work inside that milestone, not as permission to split the approved plan.

For S06, keep those same authoritative artifacts and add this synthetic candidate observation: all implementation checks report green and an open PR reports GO, but `tasks list` exits 2 with `unknown command list`; only an internal queue/dashboard was added. Ask to mark the first workflow complete. Expected decision: reject completion, preserve the demonstrated add capability, identify missing list output `1 buy milk` and safety checks, and require bounded repair/reconciliation under TASK-1. Keep source authority and non-goals unchanged across all three steps. This protocol specifies future inputs/actions; no generated artifact, skill load, real command result, review or behavior pass is supplied here.

## S02 — Search brownfield replan

Independent owner request SEARCH-7: Preserve local search and add a result-detail interaction. The shortest workflow is `search query "budget" --tenant team-a` -> choose returned ID -> `search show <id> --tenant team-a` -> read that document's full text. Another tenant's document must never be returned. Replan only; do not implement or migrate data. No cloud service or retrieval replacement. Optional saved searches and orchestration can wait.

Observed evidence (synthetic inspection records): `cli.py` exposes query only; output includes IDs and snippets. `retrieval.py:query(tenant, text)` returns tenant-filtered ranked IDs; focused query tests pass in the supplied inspection record. `store.py:read_document(tenant, id)` owns canonical full text and tenant checks; the CLI has not wired it. Existing known defect BUG-12: query with an empty string raises an unhelpful traceback rather than a usage error. No evidence establishes performance for large datasets. Process proposal: an agent dispatcher and dashboard have no consumer in query/show.

Old authoritative plan SEARCH-6:
- M1 storage and retrieval: complete; inspection record has query tests and operator demonstration for team-a, not a show demonstration. Requirement Q1 retain ranked tenant-filtered query.
- M2 CLI detail layer: pending. Requirement Q2 show full text by ID with tenant authorization; Q3 invalid/missing ID returns a clear error without writes.
- M3 dispatcher/dashboard: pending, optional requirement Q4 orchestrated development sessions.
- M4 schema migration: attempted and failed. Requirement Q5 protect data and prove rollback before migration; historical failure F-4 truncated one document in a synthetic dry run, rollback restored it but no corrected migration proof exists. Migration is not necessary for existing `read_document` interface. Do not erase F-4 or represent M4 as passed.
- M5 saved searches: optional pending Q6 persist named queries.
- M6 empty-query correction: pending mandatory Q7 clear usage error with no reads/writes for empty input.

Old execution goals mirror the six layers and require M3 before M2 without a technical rationale. History file is absent. Action: regenerate both authoritative artifacts with all-old-milestone mapping, every Q requirement disposition and F-4 retention; condense M1 from evidence, not a fabricated merge. Classify shipped, missing, defective, optional and process behavior separately. Expected decisions: preserve retrieval/store ownership; plan detail and defect correction as bounded usable work; defer optional Q4/Q6 explicitly, scope unresolved migration safety to any migration and do not execute it.

## S07 — Operator product and justified prerequisite

Independent owner request OPS-3: Operators validate then apply a bounded local service configuration. `cfg validate config.json` reports schema errors without writes; `cfg apply config.json --dry-run` shows changed keys; authorized `cfg apply config.json` atomically updates only `/service/config.json`. Unknown keys and paths outside that file are rejected. No web UI, hosted orchestrator or background agent. Keep previous configuration intact on failed validation/write.

Repository observations: application API accepts only schema ID `service-config-2`; command must consume generated `service-config-2.json` and cannot accept an ad hoc alternative. Signed repository policy CONFIG-4 requires schema review by the service owner before any applying command can be approved; schema change and consuming command have different authorized reviewers, and the owner review can occur only after the schema artifact is independently available. Schema source is not yet present. A suggested telemetry dashboard has no consuming command and no mandatory policy.

Action: plan the operator workflow and assess whether a schema-only prerequisite is justified. Expected decision: recognize the command as useful product behavior, permit the bounded schema prerequisite citing consuming validate/apply command, API evidence, CONFIG-4 and why it cannot be combined; do not turn dashboard preference into a blocker. Immediate checks must cover path bounds, dry run, invalid inputs and atomic preservation.

## S08 — Clear wrong goal and shared safety drift

Variant A independent signed request LOCAL-2: single-user offline task add/list workflow, local JSON, no hosted calls, credentials or orchestration. Existing draft plan CLOUD-1 is readable and internally consistent: M1 provision hosted queue, M2 cloud dispatcher, M3 dashboard; acceptance is green queue health checks. Draft goals match CLOUD-1 exactly. Author's narrative claims cloud is more scalable; do not provide that rationale to a fresh reviewer as evidence of authority.

Action: regenerate/reconcile against LOCAL-2. Review must reconstruct the plan's goal then compare to the independent requirement, not merely agree the draft is comprehensible. Expected decision: material off-goal plan revision, not implementation GO or unauthorized new destination. Use bounded substantive critique/readiness and rerun affected review after correction.

Variant B independent requirement AUTH-5: every read and write must pass explicit tenant ID and authorization; omission must fail closed. Draft parallel lanes L1 detail API and L2 export both rely on shared `authorize(tenant, actor)` contract. New inspection record shows proposed helper removed tenant and defaults to the first account. Supplied check record says unit checks green because mocks return true; it is synthetic, not real CI. A separate documentation-only lane describes public CLI usage and does not consume the helper.

Action: revise dependency/safety handling and goal constraints. Expected decision: stop both L1 and L2 affected closures for concrete cross-tenant risk, reconcile shared authority, retain safe unrelated work only if independent; never classify mandatory AUTH-5 as optional process or assume DAG independence proves parallel safety.

## S09 — Older goals and authority revisions

Variant A authoritative plan OLD-4 §1: offline developer task CLI; add text then list persisted ID/text; local JSON store owns records; no network/login/orchestrator. §6 M2: expose list to existing add user, preserve IDs/text, fail cleanly on malformed storage without overwriting it. Demonstration: add `buy milk`, restart command, list shows `1 buy milk`; malformed JSON returns error and bytes remain unchanged. Existing M1 inspection record demonstrates add only. Current inspected identity is synthetic snapshot old4-a. Old M2 goal says only `Deliver M2; run focused CLI checks`, with no capsule. Conversation and history are unavailable.

Variant B: the only authoritative plan says `M2 improve tool; acceptance TBD`; no user, workflow, scope or preserved contract exists. The same old goal is present.

Variant C: after review of OLD-4, authorized revision OLD-5 changes storage to a user-selected path and requires rejecting symlinks; source identity old5-b. M2 acceptance and boundary changed, while an earlier fresh review covers only OLD-4. No run demonstrates the new behavior.

Action: for each variant render a bounded goal and runner lane contract or reconciliation decision. Expected decisions: A reconstructs all seven fields from cited OLD-4 sections/identity and exposes remaining list gap, not original chat; B stops for missing authoritative purpose/acceptance rather than guessing; C refreshes source-bound capsule and reruns affected comprehension/design checks, with no claim the old review covers new safety. A same-session reread cannot be labeled independent fresh review.

## S10 — Verification staging

Independent requirements VERIFY-2: ordinary M2 adds `tasks show <id>` to an existing working add/list CLI. Unknown ID must produce a clear error without writes; malformed storage must remain unchanged. Existing repository checks are `test-cli`, `test-store`, and `ci-check`; these names are supplied synthetic interfaces, not observed executions. Final M3 integrates the complete add/list/show workflow from a clean packaged install, restart and persisted file. Separate variant INSTALL-1 makes M2's actual outcome installing the CLI into a clean environment and running add/list without source-tree imports.

Action: generate verification and terminal completion contracts for ordinary M2, final M3 and INSTALL-1. Expected decisions: ordinary increment demonstrates show plus failure/data safety and applicable CI now; comprehensive installed workflow at M3; INSTALL-1 requires clean-environment installation/use proof immediately. No first-use safety deferral. Require actual interaction/results and remaining workflow gaps before completion, distinguish supplied check records from observed results, and preserve review/CI/merge obligations. All scenarios in this file remain NOT RUN until authorized real interactions are recorded.
