---
name: ship-workflow
description: 'Resumable shipping lifecycle: reconciles current Git and GitHub facts from any entry (dirty default or feature branch, local commits, published branch, open PR, existing manual or native stack, merged work), commits dirty work as lossless logical commits, publishes or reuses the PR, requires current CI and review evidence, lands it through the supported path and cleans up only proven-stale branches and worktrees. Stops at the requested endpoint and never bumps versions, edits changelogs, tags or publishes. Triggers on: "ship it", "ship this", "open a PR", "push and PR", "land this PR", "merge PR and clean up", "check CI on my PR", "resume the ship run", "/ship-workflow".'
metadata:
  version: 2.2.0
  category: review
  tags: [shipping, pull-request, ci-cd, merge, cleanup]
  difficulty: intermediate
  phase: ship
---

# Ship Workflow

Ship through the authorized endpoint using the repository's current checks, required reviews, branch protections and merge policy. Routine shipping is the default. The executable owns Git/provider mutations, journals, reconciliation and cleanup; the assistant owns scope, logical change grouping, repository conventions and unfamiliar failure diagnosis.

## Reference Files

| File | Contents | Load When |
|---|---|---|
| `references/commit-planning.md` | Inventory, logical commit plans and local gate packets | Creating commits or requesting local/per-commit validation |
| `references/lifecycle-contract.md` | Explicit policy, assurance, publication, stack packets, journals and recovery | Supplying `--policy` or `--stack-plan`, resuming, or interpreting a blocker |
| `references/project-detection.md` | Repository gate-source detection | Locating local test commands; version/changelog tables do not authorize release work |

## Workflow

### 1. Resolve scope

Choose exactly one target: `--pr N`, `--branch NAME`, an explicit stack, a saved run, or the current branch when it identifies exactly one target. Resolve ambiguous targets or bases from provider/Git facts; ask only when those facts cannot decide. `--repo [HOST/]OWNER/REPO` names the PR base repository, and `--head-repo OWNER/REPO` names a fork head namespace.

| Request | Endpoint |
|---|---|
| "Ship it", `/ship`, "finish PR 12 and clean up" | `clean` (default) |
| "Merge it", "land PR 12 but keep the branch" | `--until merged` |
| "Open a PR", "push and PR" | `--until pr` |
| "Check CI", "what blocks PR 12" | `--until pr --dry-run` (inspection only) |
| Version, changelog, tag, release, package publication or deployment | Separate release authority, not this skill |

State the target, endpoint and cleanup scope before mutation. A resume preserves the saved authority. `pr` confirms publication only; `merged` adds confirmed landing and applicable post-merge acceptance; `clean` adds proof-based cleanup. Keep active, dirty, protected/default/release, unmerged, open-PR-dependent and unknown work. Never widen a stack selection or resume endpoint implicitly.

### 2. Inspect through the executable

Resolve `<skill-dir>` from the loaded skill's absolute client-reported directory. Run from a checkout of the target repository:

```bash
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --pr 12 --dry-run
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --inventory
```

Python 3.12+, Git and authenticated `gh` are required. Missing prerequisites are `BLOCKED`; there is no hand-run lifecycle fallback. Inspection writes no objects, refs, hooks, locks or journals and does not fetch or prune. Use literal argv lists, quote paths and repository-controlled values, and place packets and PR bodies in a private temporary directory outside the repository.

### 3. Execute routine shipping

For an existing PR with unambiguous provider merge policy:

```bash
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --pr 12 --until merged
```

Provider-required checks/publishers, repository mandates, current-head human approvals and protections remain blocking. Unclassified observed jobs also stay strict: pending or failed evidence stops landing. Only exact, source-backed `advisory_checks` identities in `--policy` or a stack node's decision may report pending/failure without veto; the controller surfaces their state separately. Never infer advisory status from slowness, inherited failure, bot identity or a display-name pattern. Missing/inaccessible required evidence is not GREEN, and advisory declarations never weaken strict current-base gates. Repeated display names are normal: workflow, event, publisher, job and current attempt identify evidence; push results do not substitute for PR merge-context results. Provider-current job IDs preserve distinct carried jobs in partial reruns. Do not rename jobs or change workflows to satisfy this controller.

An explicit `--policy` resolves actual ambiguity: repository merge-method conventions, blocking expected-job inventory, exact advisory CI classification, justified skips/head-only checks, documented post-merge commands, protected refs, or a deliberately CI-free repository. Bind it to the current head/base (schema 1) or publication (schema 2), as specified in the lifecycle reference. Empty CI requires a sourced `ci_free` decision; it is never inferred from absent jobs.

Routine assurance does not require checkout-log attestation or immutable action pins. Use `assurance: "high"` in an explicit policy, or a selected stack node's decision, only when requested. That option requires the stronger checkout/commit-parent evidence described in the lifecycle reference. Never silently lower a saved run's assurance; a legacy run or incompatible source update must stop for an explicit migration/policy decision.

Use one primary review per PR. A stack receives one cumulative integration check, not another full review of every slice. After fixes, re-review changed code and affected boundaries; after three unsuccessful fix rounds, escalate the unresolved defects instead of looping or merging them. Provider-required reviews and code-owner protections remain authoritative. Formal changes requested veto only with verified repository review authority; advisory bot comments/reviews do not gain authority from their label. A write-capable bot's formal change request is not automatically advisory, and bot approvals do not satisfy required human approval.

### 4. Validate local work before push

For dirty work, follow the commit-planning reference: inventory every disposition, author a logical grouping draft, compile it with `--draft` and `--gates`, save the printed plan, then execute `--plan`. Preserve reasonable existing commits and retained work; never stash, reset, blindly add or discard work to satisfy a precondition.

For publication, give `--title` and `--body-file` together when a PR may be created. Resolve its named base through the plan or a schema 2 binding. Reuse the exact matching PR instead of creating a duplicate. A release-preparation handoff ends at `pr`.

Requested local gates run in isolated clean checkouts before push, with their own deadlines. Use `--gates` for publication and stack replay, and `per_commit: true` in the gate packet when every outgoing/replayed commit must pass. Existing repository hooks still run normally. Do not install or override a pre-push hook, run long validation inside push, or introduce a stop/validate/resume protocol.

Layer checks by risk and purpose: fast changed-scope local checks, stable PR correctness/security gates, integration-candidate checks on the actual combined tree (`merge_group` where configured), mainline acceptance, and expensive scheduled audits. Keep every provider-required and repository-mandated gate. Reuse evidence only when relevant code, dependencies, configuration, toolchain, head/base and execution context match; a required new provider report still runs. Do not rerun unchanged historical slice reviews as a substitute for integration evidence.

The controller freezes and verifies replay proposals before publication. After a definite refusal, unchanged inputs reuse the exact proposed commit objects and renew validation before another guarded push. Callers do not seed `GIT_COMMITTER_DATE`. Unknown outcomes stay pending and reconcile from current facts before any further mutation.

### 5. Ship existing stacks parent-first

Load the registered `stacked-prs` companion and inspect topology, slice boundaries, provenance and native membership. Missing companion skills are `BLOCKED`. Author one explicit `--stack-plan` packet: select exactly the authorized PRs; include every ancestor and relevant dependent as context; cite unchanged provenance and each selected node's merge policy. Use routine node assurance unless high assurance was requested.

```bash
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --stack-plan /tmp/ship.X/stack.json --dry-run
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --stack-plan /tmp/ship.X/stack.json --gates /tmp/ship.X/gates.json --until merged
```

The controller proves each own slice, preserves author/message/trailer bytes, publishes restacks with an exact expected-old force-with-lease, retargets only after confirmed parent landing and requires renewed checks for the new context. An open unselected ancestor stops for a scope decision. Cleanup follows confirmed landing, never a submitted merge request.

GitHub-native selections use one guarded asynchronous request on the highest selected member, never manual merges or fallback promotion. The provider can rebase retained upper members; disclose that effect and require the controller's tree/slice proofs. Queue enrollment is not landing; the request guards only the highest selected head, not every lower member atomically.

## Error Handling And Recovery

| Result | Action |
|---|---|
| `PLANNED` | Report inspection; nothing mutated |
| `COMPLETE` | Report only the achieved endpoint |
| `WAITING` | Report pending facts; resume a returned saved run, otherwise repeat read-only inspection |
| `NEEDS_JUDGMENT` | Resolve the named policy, scope, provenance or failure-ownership decision |
| `BLOCKED` | Report the actual prerequisite, protection or failure; preserve confirmed facts |

Resume only a returned `run_id` using `--resume RUN_ID`; never invent one. Reconcile uncertain pushes, PR creation, retargets, merges and deletions before retrying. A failed post-merge command or required cleanup is merged-but-incomplete, not success. Repair change-owned CI failures within scope; inherited, permission and protection failures remain blockers. Never bypass protection, use an admin merge, weaken checks or solicit reviewer bots.

On a mainline or post-merge failure, contain impact first: use an authorized revert or a focused repair with normal review and gates. Preserve merged-but-incomplete facts and report the recovery owner/action. Never reinterpret a failing gate as advisory, disable a protection or weaken quality to make main green.

Explain waits using `last_gate.reason` or the sanitized `diagnostic` when a transport-level blocker contains only an operation identifier. Name the finite monitoring deadline and any minimum dispatch window. A publication preview with an unresolved named base is a `resolve-base` action with `NEEDS_JUDGMENT` blockers, not an executable push/PR plan.

CI questions remain read-only. For an explicit wait, run `gh pr checks N --repo owner/repo --watch --interval 10 --fail-fast` under a finite external deadline, then repeat controller inspection. The watcher alone does not prove applicability, current base, review policy or GREEN.

## Output

Relay the actual receipt fields: endpoint, PR URLs, confirmed commits/merges, checks and local gates actually exercised, removed/retained/failed cleanup targets with reasons, usable checkout, blocker and exact remaining action. Exit codes are 0 for `PLANNED`/`COMPLETE`, 3 for `WAITING`, 4 for `NEEDS_JUDGMENT`, and 2 or 5 for blocked/input errors. Parse or pre-journal errors can omit a run and other receipt fields. A partial stack, pending queue or incomplete cleanup is not success. Ordinary shipping does not change versions, changelogs, tags or publication.
