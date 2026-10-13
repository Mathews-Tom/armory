---
name: stack-pr
type: command
description: 'Slash-command wrapper for the stacked-prs skill. Triggers on: "/stack-pr inspect", "/stack-pr split", "/stack-pr publish", "/stack-pr sync", "/stack-pr validate", "/stack-pr merge", "/stack-pr cleanup", "stack-pr publish", "stack-pr split". Use this command when a user wants a concise command surface for inspecting, creating, publishing, synchronizing, validating, merging, or cleaning up stacked pull requests while delegating topology decisions to skills/stacked-prs and stack landing and cleanup to its ship-workflow lifecycle delegation.'
metadata:
  version: 0.2.0
  category: development
  tags: [git, pull-requests, stacked-prs, slash-command]
  difficulty: advanced
  phase: ship
command:
  syntax: /stack-pr <inspect|split|publish|sync|validate|merge|cleanup> [args]
  handler: inline
  dependencies:
    - skills/stacked-prs
---

# Stack PR Command

Thin slash-command entry point for `skills/stacked-prs`. This command defines command syntax and dispatch rules only. The skill owns stack inference, provider adapters, safety checks, split discipline, validation and the stack decision packet; landing and cleanup run once through the `ship-workflow` stack lifecycle that the skill delegates to.

## Workflow

1. Parse the subcommand.
2. Load the registered `stacked-prs` skill. If the client has no such skill, stop with `BLOCKED: required package skills/stacked-prs is not installed`; do not search a source checkout or continue by hand.
3. For `merge` and `cleanup` only, also require the registered `ship-workflow` skill; if it is missing, stop with `BLOCKED: required package skills/ship-workflow is not installed` before any mutation. Other subcommands do not need it.
4. Pass the raw arguments to the matching skill workflow.
5. Preserve provider-neutral language in user-facing output.
6. Report the exact `git`, provider CLI, delegated run and validation commands executed.

This command never references a file beside itself: installed, it is a single flattened Markdown file, and every executable it reaches belongs to a loaded skill's own base directory.

## Operations

| Command | Delegates To | Behavior |
| --- | --- | --- |
| `/stack-pr inspect` | Inspect workflow | Build a stack table, including native membership, without mutation |
| `/stack-pr publish` | Publish workflow | Create missing PRs and retarget wrong bases to their parents |
| `/stack-pr sync` | Sync workflow | Restack open branches parent-to-child and push with explicit expected-old leases |
| `/stack-pr validate` | Validate workflow | Validate stack slices and record results |
| `/stack-pr merge` | Land and clean up workflow | Author the stack decision packet and run the delegated lifecycle to `merged` |
| `/stack-pr cleanup` | Land and clean up workflow | Select only provider-confirmed merged nodes and run the delegated lifecycle to `clean` |
| `/stack-pr split` | Split workflow | Convert one source branch into ordered stack branches |

## Syntax

Publish an explicit stack:

```text
/stack-pr publish --base main feat/parser-core feat/parser-cache feat/parser-cli
```

Split one source branch:

```text
/stack-pr split \
  --source feat/parser-system \
  --base main \
  feat/parser-core feat/parser-cache feat/parser-cli
```

Sync an existing stack:

```text
/stack-pr sync --base main feat/parser-core feat/parser-cache feat/parser-cli
```

Merge an existing stack, or preview the merge read-only:

```text
/stack-pr merge --base main feat/parser-core feat/parser-cache feat/parser-cli
/stack-pr merge --dry-run --base main feat/parser-core feat/parser-cache
```

## Argument Rules

- Accept branch names positionally after options.
- Treat positional branch order as authoritative for parent order.
- `--base <branch>` sets the root parent; default branch detection is allowed when omitted.
- `--source <branch>` is required for `split`.
- For `merge`, the positional branches are the authorized selection; the skill never adds an unlisted open ancestor or native lower member without a scope decision. `merge` lands without deleting branches; deleting them needs `cleanup` or a full-lifecycle request.
- `--dry-run` with `merge` or `cleanup` runs only the delegated read-only preview.
- Do not require `.stack-prs.yaml` for one-off command use.
- Stop when command arguments conflict with provider PR base metadata.

## Error Handling

| Problem | Resolution |
| --- | --- |
| Unknown subcommand | List supported subcommands and stop |
| Missing branch arguments for publish, sync, merge, or cleanup | Run inspect only when the skill can infer an unambiguous stack |
| Missing `--source` for split | Stop and request source branch |
| `stacked-prs` not installed | `BLOCKED` naming `skills/stacked-prs` |
| `ship-workflow` not installed for merge or cleanup | `BLOCKED` naming `skills/ship-workflow`; no hand-run fallback |
| Dirty worktree before mutation | Stop through `skills/stacked-prs` safety rules |
| Provider CLI unavailable | Stop unless the requested operation is inspect-only and local-only |

## Output

Return the delegated skill result:

1. Stack table.
2. Commands executed.
3. PR URLs or numbers changed.
4. Validation results.
5. For merge or cleanup, actual status, confirmed merges, retained dependents and cleanup dispositions; include the delegated saved `run_id` only when returned and non-null. A pre-journal stop repeats the original scoped invocation after resolving its input, never a guessed or bare resume.
6. Next safe action.
