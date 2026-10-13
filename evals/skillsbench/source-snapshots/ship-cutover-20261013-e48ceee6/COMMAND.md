---
name: stack-pr
type: command
description: 'Slash-command wrapper for the stacked-prs skill. Triggers on: "/stack-pr inspect", "/stack-pr split", "/stack-pr publish", "/stack-pr sync", "/stack-pr validate", "/stack-pr merge", "/stack-pr cleanup", "stack-pr publish", "stack-pr split". Use this command when a user wants a concise command surface for inspecting, creating, publishing, synchronizing, validating, merging, or cleaning up stacked pull requests while delegating topology decisions to skills/stacked-prs.'
metadata:
  version: 0.1.0
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

Thin slash-command entry point for `skills/stacked-prs`. This command defines command syntax and dispatch rules only. The skill owns stack inference, provider adapters, safety checks, split discipline, validation, merge order, and cleanup.

## Workflow

1. Parse the subcommand.
2. Load `skills/stacked-prs`.
3. Pass the raw arguments to the matching skill workflow.
4. Preserve provider-neutral language in user-facing output.
5. Report the exact `git`, provider CLI, and validation commands executed.

## Operations

| Command | Delegates To | Behavior |
| --- | --- | --- |
| `/stack-pr inspect` | Inspect workflow | Build a stack table without mutation |
| `/stack-pr publish` | Publish workflow | Create missing PRs and retarget wrong bases |
| `/stack-pr sync` | Sync workflow | Rebase branches parent-to-child and push with lease |
| `/stack-pr validate` | Validate workflow | Validate stack slices and record results |
| `/stack-pr merge` | Merge workflow | Merge root to leaf and retarget children |
| `/stack-pr cleanup` | Cleanup workflow | Delete only confirmed merged stack branches |
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

Merge an existing stack:

```text
/stack-pr merge --base main feat/parser-core feat/parser-cache feat/parser-cli
```

## Argument Rules

- Accept branch names positionally after options.
- Treat positional branch order as authoritative for parent order.
- `--base <branch>` sets the root parent; default branch detection is allowed when omitted.
- `--source <branch>` is required for `split`.
- Do not require `.stack-prs.yaml` for one-off command use.
- Stop when command arguments conflict with provider PR base metadata.

## Error Handling

| Problem | Resolution |
| --- | --- |
| Unknown subcommand | List supported subcommands and stop |
| Missing branch arguments for publish, sync, merge, or cleanup | Run inspect only when the skill can infer an unambiguous stack |
| Missing `--source` for split | Stop and request source branch |
| Dirty worktree before mutation | Stop through `skills/stacked-prs` safety rules |
| Provider CLI unavailable | Stop unless the requested operation is inspect-only and local-only |

## Output

Return the delegated skill result:

1. Stack table.
2. Commands executed.
3. PR URLs or numbers changed.
4. Validation results.
5. Next safe action.
