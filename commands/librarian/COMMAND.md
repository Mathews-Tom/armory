---
name: librarian
type: command
description: 'Slash-command wrapper for the skill-librarian agent. `/librarian capture` records one reusable, privacy-safe observation from a completed task; `/librarian status` reports queue metadata without reading evidence bodies; `/librarian review` selects a bounded batch for human-gated disposition. Triggers on: "/librarian capture", "/librarian review", "/librarian status", "record this skill lesson", "review skill observations", "show librarian backlog". Use this command for explicit reflective capture and review, not automatic transcript monitoring or direct package refinement.'
metadata:
  version: 1.0.0
  category: development
  tags: [skills, reflection, observations, slash-command, privacy]
  difficulty: advanced
  phase: reflect
command:
  syntax: /librarian <capture|status|review> [--source current-task|PATH] [--target PACKAGE] [--limit N]
  handler: inline
  dependencies:
    - skill-librarian
---

# Librarian Command

Thin slash-command entry point for the `skill-librarian` agent. This command owns mode and option parsing only. Observation schema, storage, privacy checks, deduplication, evidence verification, downstream routing, and approval gates remain exclusively in the agent.

## Workflow

1. Parse the first token as exactly `capture`, `status`, or `review`.
2. Validate options against the mode-specific rules below. Reject unknown, repeated, or incompatible options.
3. Normalize `--source current-task` to the most recently completed substantive user task. Preserve an explicit path as one opaque transcript-source value; do not read it in the command wrapper.
4. Validate `--limit` as a base-10 integer from 1 through 100.
5. Load `agents/skill-librarian`, pass the normalized mode and options, and begin that mode at its first step.
6. Return the agent report unchanged. Do not inspect the queue, reproduce its schema, draft package changes, or add another approval layer after handoff.

## Syntax

| Invocation | Mode | Result |
|---|---|---|
| `/librarian capture` | Capture | Capture from the last completed substantive task |
| `/librarian capture --source current-task` | Capture | Explicitly select the current task boundary |
| `/librarian capture --source PATH` | Capture | Pass one transcript path to the agent |
| `/librarian status` | Status | Report full-queue metadata only |
| `/librarian status --target PACKAGE` | Status | Report metadata for one package target |
| `/librarian review` | Review | Select the 10 oldest open observations |
| `/librarian review --target PACKAGE --limit N` | Review | Filter by package, then select at most N oldest observations |

## Argument Rules

| Mode | Allowed options | Defaults | Rejected options |
|---|---|---|---|
| `capture` | `--source VALUE` | `--source current-task` | `--target`, `--limit` |
| `status` | `--target PACKAGE` | all targets | `--source`, `--limit` |
| `review` | `--target PACKAGE`, `--limit N` | all targets, `--limit 10` | `--source` |

Rules:

- A bare `/librarian` invocation lists the three modes and stops. It does not infer a mode from session content.
- Every option takes exactly one non-empty value.
- `--target` accepts one manifest package name. The agent verifies catalog membership.
- `--limit` accepts decimal integers from 1 through 100; reject zero, negatives, decimals, and non-numeric values.
- The order of allowed review options does not change their meaning.
- There is no `apply`, `draft`, `install`, `merge`, or automatic-monitoring mode.

## Output

Return the selected agent-mode report verbatim:

- capture: observation ID or `none`, verdict, target, privacy status, deduplication result, `Package modified: no`, and next action;
- status: aggregate queue counts, oldest unreviewed age, and distinct-target count;
- review: selected and clustered counts plus sanitized dispositions that require explicit approval.

```text
/librarian review --target stacked-prs --limit 10
→ validate review options
→ load agents/skill-librarian with mode=review, target=stacked-prs, limit=10
→ return the bounded review report unchanged
```

## Error Handling

| Problem | Resolution |
|---|---|
| Missing mode | List `capture`, `status`, and `review`; stop |
| Unknown mode | State the three valid modes; stop |
| Unknown or repeated option | Reject the invocation; show mode syntax |
| Option is invalid for the mode | Reject the invocation; show the mode's allowed options |
| Empty `--source` or `--target` | Reject the invocation; do not infer a value |
| Invalid `--limit` | Require an integer from 1 through 100 |
| Agent handoff fails | Return the failure; do not implement agent behavior in the wrapper |

The boundary is deliberate: duplicating storage or privacy behavior in the command would create a second convention that can drift from the agent's authoritative contract.
