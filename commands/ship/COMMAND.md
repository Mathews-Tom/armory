---
name: ship
type: command
description: 'Slash-command wrapper for the ship-workflow skill. `/ship` takes the current branch, an explicit `--pr`, `--branch`, `--stack` or saved `--resume` target from its current state to the requested `--until pr|merged|clean` endpoint (default `clean`), or previews it read-only with `--dry-run`. Triggers on: "/ship", "/ship --pr 123", "/ship --until pr", "/ship --dry-run", "/ship --resume". Use this command when a user wants a concise argument surface for the resumable shipping lifecycle while delegating every Git, provider, gate, landing and cleanup decision to skills/ship-workflow.'
metadata:
  version: 0.1.0
  category: development
  tags: [git, pull-requests, shipping, slash-command]
  difficulty: intermediate
  phase: ship
command:
  syntax: /ship [--pr N | --branch NAME | --stack PR [PR ...] | --stack-plan PATH] [--resume [RUN_ID]] [--until pr|merged|clean] [--repo [HOST/]OWNER/REPO] [--head-repo OWNER/REPO] [--wait-timeout SECONDS] [--dry-run]
  handler: inline
  dependencies:
    - skills/ship-workflow
---

# Ship Command

Thin slash-command entry point for the `ship-workflow` skill. This command parses arguments, resolves the installed skill and relays its structured result. The skill and its executable own target reconciliation, commits, publication, gates, landing, cleanup and resumption; this command has no lifecycle algorithm of its own.

## Workflow

1. Parse the arguments (§ Argument Rules). Reject an unsupported or contradictory argument with the diagnostic below before loading anything.
2. Load the registered `ship-workflow` skill through the client's skill mechanism. If the client has no `ship-workflow` skill, stop with `BLOCKED: required package skills/ship-workflow is not installed`. Do not search the current directory or an Armory checkout for it, do not install anything, and do not continue by hand.
3. Use the absolute base directory the client reports for the loaded skill as the skill's `<skill-dir>`. Never assume a path relative to this command, the current directory or a source checkout.
4. For `--stack` or `--stack-plan`, also load the registered `stacked-prs` skill; if it is missing, stop with `BLOCKED: required package skills/stacked-prs is not installed`. Other targets do not need it.
5. Hand the parsed target, endpoint and options to the skill's workflow. Before the first mutation, state the resolved target, endpoint and cleanup scope.
6. Relay the skill's result (§ Output).

## Syntax

```text
/ship
/ship --pr 123
/ship --pr 123 --until merged
/ship --branch feat/parser --until pr
/ship --stack 123 124 125
/ship --dry-run
/ship --resume
/ship --resume <saved-run-id> --wait-timeout 3600
```

## Argument Rules

| Argument | Meaning |
| --- | --- |
| `--pr N` | That PR is the target |
| `--branch NAME` | That local branch is the target |
| `--stack PR [PR ...]` | Exactly these PRs of one existing stack are selected; the skill authors the stack decision packet with `stacked-prs` |
| `--stack-plan PATH` | An existing stack decision packet, passed through unchanged |
| none of the above | The current branch or worktree, only when it resolves to one unambiguous target |
| `--resume [RUN_ID]` | A saved run; without an id, only the single unambiguous saved run |
| `--until pr\|merged\|clean` | Endpoint; default `clean`, or the saved endpoint on resume |
| `--repo [HOST/]OWNER/REPO` | The PR base repository |
| `--head-repo OWNER/REPO` | A fork head namespace |
| `--wait-timeout SECONDS` | Positive monitoring window for this invocation only; default 1800 |
| `--dry-run` | Read-only inspection: no write, fetch, prune, lock, receipt or provider mutation |

- `--pr`, `--branch`, `--stack` and `--stack-plan` are mutually exclusive. `--head-repo` does not combine with a stack target. A resume keeps its saved target; a contradicting selector is rejected by the executable, never reinterpreted.
- `--until` and `--wait-timeout` never change authority beyond the named endpoint, and a resume never widens a saved endpoint.
- Without arguments, a natural-language request keeps its own authority: opening a PR is `pr`, checking or waiting for CI is `--until pr --dry-run` inspection only, and only an explicit full ship or "finish and clean up" request is `clean`.
- Unsupported arguments produce `unsupported argument <arg>: /ship accepts only the syntax above` and stop. This includes any stage override (`--from`), merge or protection overrides (`--admin`, `--delete-branch`, `--force`), skipped gates, and version, changelog, tag or publication requests, which belong to a release owner.
- A non-positive or non-numeric PR number or wait timeout is a parse error.

## Error Handling

| Problem | Resolution |
| --- | --- |
| Unsupported or contradictory arguments | Print the diagnostic and supported syntax; run nothing |
| `ship-workflow` not installed | `BLOCKED` naming `skills/ship-workflow`; no fallback |
| `stacked-prs` not installed for a stack target | `BLOCKED` naming `skills/stacked-prs` |
| Target ambiguous | Relay the skill's bounded target decision; never pick by name, recency or number |
| Executable reports invalid input (exit 2) | Relay the actual diagnostic; do not infer mutation state from the exit code |

## Output

Relay the skill's structured result without reinterpreting it:

1. Actual `status` (`PLANNED`, `COMPLETE`, `WAITING`, `NEEDS_JUDGMENT` or `BLOCKED`) and `run_id` only when returned.
2. Target, requested endpoint and the endpoint actually achieved.
3. PR URLs, confirmed commits and confirmed merges.
4. Gates exercised and their evidence.
5. Cleanup: removed, retained (with reasons) and failed targets, and the usable checkout.
6. Actual blocker, diagnostic or judgment packet and next action. Give `--resume RUN_ID` only for a returned saved run; a receipt-free inspection is repeated with the same read-only selector after fresh evidence is available.

Pre-receipt errors can contain only `schema_version`, `status` and `error`, with no target or run identifier. `WAITING` observation errors use exit 3; `BLOCKED` can use exit 2 or 5. Relay that shape and name missing fields as unreported rather than constructing them. Parse errors can be diagnostics on stderr instead of JSON.

Only `COMPLETE` is endpoint success; `PLANNED` from `--dry-run` is a plan, not a mutation. A waiting group, partial stack or incomplete cleanup is never summarized as success.
