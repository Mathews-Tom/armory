---
name: ship-workflow
description: 'Resumable shipping lifecycle: reconciles current Git and GitHub facts from any entry (dirty default or feature branch, local commits, published branch, open PR, existing manual or native stack, merged work), commits dirty work as lossless logical commits, publishes or reuses the PR, requires current CI and review evidence, lands it through the supported path and cleans up only proven-stale branches and worktrees. Stops at the requested endpoint and never bumps versions, edits changelogs, tags or publishes. Triggers on: "ship it", "ship this", "open a PR", "push and PR", "land this PR", "merge PR and clean up", "check CI on my PR", "resume the ship run", "/ship-workflow".'
metadata:
  version: 2.0.0
  category: review
  tags: [shipping, pull-request, ci-cd, merge, cleanup]
  difficulty: intermediate
  phase: ship
---

# Ship Workflow

Take work from whatever state it is in to the authorized endpoint, and no further. An executable controller owns every established Git and provider mechanic: inventory, commits, pushes, PR deduplication, gates, merges, landing proofs, cleanup, receipts and resumption. The assistant owns only bounded judgment: change grouping and messages, source-backed applicability decisions, stack topology, diagnosis of unfamiliar failures and scope questions. Never replace an executable step with hand-run `git`/`gh` mutations.

## Reference Files

| File | Contents | Load When |
| --- | --- | --- |
| `references/commit-planning.md` | Inventory fields, gate packet, grouping draft, commit plan, placement, execution and recovery | Local changes exist or new commits are needed |
| `references/lifecycle-contract.md` | Applicability decision packets (schema 1 and 2), publication, gates, output, receipts, cleanup proofs, stack graph packets and native stack limits | Authoring a `--policy` or `--stack-plan` packet, interpreting a result, resuming, or explaining cleanup |
| `references/project-detection.md` | Test-command, package-manager, monorepo and CI detection tables | Locating candidate gate sources only; its version and changelog tables are not shipping instructions |

## 1. Resolve Authority

Map the request to exactly one endpoint before any mutation. Take the narrowest endpoint the request supports; never widen it, and never treat a resume as permission to widen a saved endpoint.

| Request | Endpoint | Invocation |
| --- | --- | --- |
| Explicit full ship: `/ship`, "ship it", "finish PR 12 and clean up" | `clean` (default) | Execution without `--until` |
| "Merge it", "land PR 12 but keep the branch" | `merged` | `--until merged` |
| "Open a PR", "push and PR", "publish this branch" | `pr` | `--until pr` |
| "Check CI", "is PR 12 green", "wait for the checks", "what blocks it" | Inspection | `--until pr --dry-run` only (§6) |
| "What would ship do", `--dry-run` | Inspection | `--dry-run` |
| Choose or edit a version/changelog, create a tag/release, publish a package, deploy | Not this skill's authority | Name the authorized owner (for example `release-captain`). Accept changes that owner already prepared, including uncommitted release artifacts, as their own logical commit group; never choose or alter their contents. A release-preparation handoff explicitly ends at `pr`. |

`pr` means a provider-confirmed created or reused PR and never merges or deletes. `merged` adds provider-confirmed landing, landing reachability and the decided post-merge commands, without deleting feature work. `clean` adds proof-based cleanup.

Select one target: `--pr N`, `--branch NAME`, an explicit stack (§5), a saved run (`--resume [RUN_ID]`), or otherwise the current branch when it resolves to exactly one target. Multiple candidate PRs, an unknown intended base, detached work without an identifiable target or contradictory metadata need a bounded target decision from the user. Never choose by branch name, recent activity or PR number. `--repo [HOST/]OWNER/REPO` names the PR base repository; `--head-repo OWNER/REPO` names a fork head namespace.

Before the first mutation state the resolved target, endpoint and cleanup scope (the target's feature branch, its remote head under an expected-old lease, its clean linked worktree, and other proven-stale feature branches of this repository; protected, active, dirty, unmerged and unknown work is retained). Inside an authorized endpoint, do not ask again at each routine stage.

## 2. Resolve The Executable

`<skill-dir>` is this skill's absolute base directory as reported by the client when the skill loaded; never a path relative to the current directory or an Armory checkout. Every invocation runs from a checkout of the target repository:

```bash
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" <arguments>
```

A Python 3.12 or newer interpreter may run `<skill-dir>/scripts/ship.py` directly instead. Git and an authenticated `gh` are required. A missing interpreter, `scripts/ship.py`, Git or `gh` is `BLOCKED` naming the missing prerequisite; never fall back to a hand-run lifecycle.

Prefer literal argv lists. In a shell, quote every resolved path and repository-controlled argument separately; a loaded skill directory or body path can contain spaces, Unicode or shell metacharacters. Pass option-like values in an unambiguous form such as `--title="$title"`; never concatenate repository text into shell code.

Write every packet, plan and PR body to a private temporary directory outside the repository (for example from `mktemp -d`) and pass absolute paths. A packet inside the working tree becomes untracked work in the inventory. Packets never contain tokens, secret arguments or raw source.

## 3. Observe Read-Only

Start every invocation from current facts, never from memory of an earlier run:

```bash
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --inventory
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --pr 12 --dry-run
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --branch feat/parser --dry-run
```

`--inventory` lists every staged, unstaged, untracked and deleted path with its concerns and blockers. `--dry-run` returns `PLANNED` with the observed revisions, gate decision and next action. Neither writes, fetches, prunes, locks or records anything. Add `--until` to a dry run to preview that endpoint.

## 4. Route By Entry Condition

| Entry condition | Next work |
| --- | --- |
| Dirty default, base or detached checkout | Inventory, grouping draft with `placement.mode: new`, plan execution on a new feature branch |
| Dirty feature branch | Same, with `placement.mode: current`, or `new` with an explicit base when the branch is unrelated to the work |
| Local commits without a matching remote head | `--branch NAME` publication with an explicit-head schema 2 decision |
| Published branch without a PR | Deduplicated PR creation (`--title`, `--body-file`) |
| Open PR | Current gates, in-scope remediation, guarded landing |
| Open PR with new local changes | Inventory and plan first; the run publishes the new head before gates |
| Existing manual or native stack | Stack decision packet (§5) |
| Merged work | Landing verification, post-merge commands and cleanup |
| Endpoint already achieved | Evidence-backed no-op |

Dirty and default-branch starts are supported: never stash, reset, `git add -A`, clean or discard work to make a precondition true. An item that should not ship is excluded with a reason and stays exactly as found.

### Commits

Follow `references/commit-planning.md`:

1. Author the `--gates` packet from the repository's actual sources. `sources` cite file and line (`justfile:34 test target`, `.github/workflows/tests.yml:41`); `gates` are argv lists that those sources run; `secret_scan` is mandatory. A missing gate tool is a blocker, never a weaker substitute.
2. Author the grouping draft. Group by reviewable concern: behavior with its required callers and regression proof together, independent concerns separately even within one file, one coherent unit never split for a commit count. Follow repository commit conventions, or Conventional Commits when none exist. Every item gets exactly one disposition; concerns are acknowledged explicitly; secrets are never included.
3. Compile it. This writes Git objects only and prints the validated plan and its `plan_identity`:

   ```bash
   uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --draft /tmp/ship.X/draft.json --gates /tmp/ship.X/gates.json
   ```

4. Save the printed `plan` object as the plan file and execute it with the publication arguments below. Each new commit is validated in an isolated clean clone before the branch moves.

Preserve reasonable existing commits; never rewrite published history for cosmetic grouping. A repository squash policy may later collapse the commits on the base; report that consequence.

### Publication And Landing

```bash
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --repo owner/repo --plan /tmp/ship.X/plan.json --gates /tmp/ship.X/gates.json --policy /tmp/ship.X/decision.json --title "feat(parser): add arrays" --body-file /tmp/ship.X/body.md --until pr
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --pr 12 --repo owner/repo --policy /tmp/ship.X/decision.json
```

`--title` and `--body-file` are given together and only when the run may create a PR. The body states the actual changes, the verification actually exercised, applicable issue references and stack metadata. An existing matching PR is reused, never duplicated.

### Applicability Decision

Execution beyond `pr` needs an explicit `--policy` packet; without one the run returns `NEEDS_JUDGMENT` listing the required decision, the required and observed checks, the current head/base and the repository's allowed merge methods. Build it only from evidence, with exactly the fields in `references/lifecycle-contract.md` § Source-backed decisions:

- `sources`: the workflow, configuration and contributor-guide lines the decision rests on.
- `expected_checks`: every job those workflows run for this PR's event and base, and at least every provider-required check. An empty list needs `ci_free: true`, which records a deliberately CI-free repository and is never a fallback for missing, disabled or unreadable CI.
- `merge_method`: one of the allowed methods that the repository's conventions select.
- `post_merge_commands`: argv lists the repository documents for post-merge acceptance, or `[]` with the source showing none apply.
- Optional `allowed_skips`, `head_only_checks` and `protected_refs` only where a cited source establishes them.

Bind it with schema 1 (`head_sha`/`base_sha` copied from the current inspection) for an existing PR, or schema 2 for publication: `{"plan": "<plan_identity>"}` for commits this run creates, or `{"head": "<oid>", "base": {"ref": "main", "oid": "<oid>"}}` for existing local commits. A changed head or base invalidates the decision; refresh it from current facts instead of reusing it.

## 5. Existing Stacks

Stack topology, parent selection, provenance and native-membership policy belong to the `stacked-prs` skill. When the target is an existing stack, load the registered `stacked-prs` skill; if the client has no such skill, stop `BLOCKED` naming `stacked-prs`. With its inspection, author one stack decision packet per `references/lifecycle-contract.md` § Stack decision packet:

- `select: true` exactly for the PRs the user authorized (`--stack 11 12 13` selects those three). Every ancestor of a selected node appears in the packet; an open ancestor the user did not select stops the run for a scope decision rather than being added silently.
- Siblings, children and open members above a native selection appear as unselected context and are not directly landed or deleted by this controller. A native provider can rebase retained upper members as part of the selected prefix operation; disclose that effect before dispatch and require the controller's complete-tree and own-slice preservation proofs. These are content proofs, not a proof of provider-rewritten author/message/trailer bytes; inspect retained provenance through `stacked-prs` when that preservation is required.
- Each selected node carries its revision-free `decision` and `provenance: {"disposition": "preserve", "sources": [...]}` citing what was inspected.

```bash
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --stack-plan /tmp/ship.X/stack.json --dry-run
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --stack-plan /tmp/ship.X/stack.json --until merged
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --resume RUN_ID --stack-plan /tmp/ship.X/refreshed.json
```

The controller lands manual nodes parent-first with slice-preserving promotion and lands a native selection with exactly one guarded async request on its highest selected member. That request's `sha` guards only the highest selected head, not every lower head or the membership atomically. Native members never receive an ordinary merge or a manual fallback, and an accepted, unknown or `enqueued` request is never resent or treated as merged. `--stack-plan` excludes `--pr`, `--branch`, `--plan`, `--policy`, `--gates`, `--head-repo`, `--title` and `--body-file`.

## 6. Narrow CI Requests

A CI question is inspection, not landing authority:

```bash
uv run --no-project --python 3.12 python "<skill-dir>/scripts/ship.py" --pr 12 --until pr --dry-run --policy /tmp/ship.X/decision.json
```

Report the `gate` status (`READY`, `WAITING`, `NEEDS_JUDGMENT` or `BLOCKED`), its reason and details. Without a decision packet the gate names the required and observed checks instead. For an explicit request to wait, run the native read-only watcher once under the client's finite subprocess deadline, rather than spending assistant turns on polling:

```bash
gh pr checks 12 --repo owner/repo --watch --interval 10 --fail-fast
```

Watch every applicable check, not only `--required`. Record the actual external deadline; the watcher has no timeout flag. Deadline expiry or pending checks remain `WAITING`, and failure requires scoped diagnosis. After the watcher, repeat the controller's read-only inspection with the current source-backed decision: only `gate: READY` for the current head/base establishes GREEN. The watcher alone cannot establish applicability, base association or review policy. The executable has no monitor-only mutation mode: never use `--until merged` or `clean`, a merge command or a deletion to wait for CI.

## 7. Act On The Result

Relay the actual result shape; never invent absent fields. Execution receipts report the saved `run_id`, target/endpoint, observed revisions, confirmed facts, cleanup, `blocker` and `next_action`. Plans and pre-receipt errors can omit them. An observation failure can return only `{"schema_version": 1, "status": "WAITING", "error": "..."}` (exit 3) or a `BLOCKED` error (exit 2 or 5), without a resumable run. Interpret the status, available fields and invocation type, never the exit code alone:

| Exit | Status | Action |
| --- | --- | --- |
| 0 | `PLANNED` (inspection) | Report the plan; nothing was mutated |
| 0 | `COMPLETE` (execution) | Report the achieved endpoint |
| 3 | `WAITING` | Report the actual pending state. Resume with `--resume RUN_ID` only if a saved run was returned; it opens a new bounded window. An inspection without a run/receipt is repeated with the same read-only selector after fresh evidence is available, not resumed. |
| 4 | `NEEDS_JUDGMENT` | Resolve the named decision within the authorized scope; resume a saved run when present, otherwise repeat the original scoped invocation with the resolved input |
| 2 or 5 | `BLOCKED` | Report the actual prerequisite/error and confirmed facts; do not work around it or invent a saved run |
| 2 | Parse/invalid input | Relay the diagnostic and correct the arguments or packet; do not infer an attempted/completed mutation from the exit code |
| 130 | Cancelled | Report the saved receipt/run when present; an interruption before any receipt does not create a resume identifier |

Judgment stays bounded:

- A change-owned CI failure is diagnosed from its logs, fixed in the working tree, committed through a new inventory and plan on the PR (`--pr N --plan ... --gates ... --policy` with a plan-bound decision) and monitored on the new head. Earlier GREEN never carries over.
- An inherited, permission, credential, protection or upstream failure stays `BLOCKED`. Never weaken tests, skip or remove jobs, bypass protection, use admin merges or edit repository settings to obtain GREEN.
- Required reviews are provider evidence for the current head. An assistant review or comment never substitutes for them. Never solicit reviewer bots.
- A merged PR whose post-merge command or required cleanup failed is merged-but-incomplete, never complete. Resume continues from the confirmed merge without another merge.
- An unknown push, creation, merge or deletion outcome is reconciled from current facts by resuming; never resend it.

## 8. Report

Name the achieved endpoint, PR URLs, confirmed commits and merges, the gates actually exercised, removed, retained and failed cleanup targets with reasons, the usable checkout and the exact remaining action. A waiting queue, partial stack or incomplete cleanup is never summarized as success. Ordinary shipping never changes versions, changelogs, tags or package publication.
