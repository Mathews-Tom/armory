---
name: decision-map
type: command
description: 'Slash-command wrapper for the decision-map skill. `/decision-map chart` plus a loose idea opens a decision map for an effort too big for one session; `/decision-map work` plus an optional map reference claims and resolves exactly one frontier ticket, then stops. Triggers on: "/decision-map", "decision-map chart", "decision-map work", "chart this effort as a map", "work the next decision ticket", "what is on the frontier", "wayfinder". Use this command when a user wants a two-mode argument surface over a tracker-backed decision map, delegating map format, ticket typing, claim arbitration, and tracker operations to skills/decision-map.'
metadata:
  version: 1.0.0
  category: development
  tags: [planning, issue-tracker, decisions, slash-command, discovery]
  difficulty: advanced
  phase: define
command:
  syntax: /decision-map chart IDEA | /decision-map work [MAP]
  handler: inline
  dependencies:
    - skills/decision-map
---

# Decision Map Command

Thin slash-command entry point for the `decision-map` skill. This command owns argument parsing and reference resolution only. Map format, tracker selection, labels, claim arbitration, frontier computation, resolution, fog graduation, and state reporting remain exclusively in the skill.

## Workflow

1. Parse the first token as the mode. `chart` sends the remaining text as a loose idea to Mode A. `work` selects Mode B.
2. For a bare invocation, treat a map URL or `#N` as `work`; treat free text as `chart`; when neither exists, ask which mode the user intends.
3. In work mode, resolve the reference with `gh issue view N --json number,title,url,labels,state`. Require the `decision-map:map` label before handing off.
4. When work mode has no reference, locate open maps. If exactly one open `decision-map:map` issue exists, use it. If several exist, list their linked titles and stop; never select one silently.
5. Load `skills/decision-map`, hand it the resolved mode and map identity, then begin that mode at step 1.
6. Return the skill's report unchanged. Do not add a second selection, a plan, tracker calls, or claim logic after handoff.

`chart` creates topology only: it never resolves a ticket. `work` resolves at most one ticket, including when a second frontier ticket is immediately available. The command does not turn an unlabeled issue into a new map because that hides an input error and creates a duplicate map.

## Syntax

| Invocation | Mode | Result |
|---|---|---|
| `/decision-map chart IDEA` | Chart | Pass the loose effort description to Mode A |
| `/decision-map work MAP` | Work | Resolve the labeled map and pass it to Mode B |
| `/decision-map #N` | Work | Resolve issue `#N` only when it is a map |
| `/decision-map MAP-URL` | Work | Resolve the referenced map URL |
| `/decision-map IDEA` | Chart | Treat non-reference text as the loose idea |

A `MAP` is a GitHub issue number, `#N`, or issue URL. Tracker selection after handoff follows the skill's documented backend ladder. The command does not provide a separate local-file argument: local map selection is part of the skill's tracker-backed workflow, not a rival command contract.

## Argument Rules

| Input | Rule | Failure |
|---|---|---|
| `chart` with empty idea | Ask for the destination or unresolved effort | Do not create a blank map |
| `work` with unlabeled issue | Reject the reference | Do not silently create a map |
| `work` with no map and one open map | Use the one map | Report the selected linked title |
| `work` with several open maps | List all linked titles | Stop for selection |
| Bare command with no argument | Ask for `chart` or `work` | Do not infer intent |

Use `gh issue view` to resolve explicit GitHub references. When the skill's configured backend is local, the handoff resolves the local map using its documented selection process. This command never duplicates the tracker capability probe or degraded-path parsing.

## Output

Return the skill report verbatim. Chart output contains map identity, created ticket topology, blockers, frontier, remaining fog, state, AFK-ready count, and the stop condition. Work output contains the one resolved ticket, closure path, decision or evidence, topology changes, frontier, state, and stop condition. A `COMPLETE` report recommends `plan-prompts`; it never emits implementation milestones or tasks.

```text
/decision-map work #482
→ resolve #482; verify its decision-map:map label
→ load skills/decision-map in work mode
→ return exactly one work report
```

## Error Handling

| Problem | Resolution |
|---|---|
| Unknown mode | State the valid `chart` and `work` modes and stop |
| Missing chart idea | Ask for the loose effort description |
| Explicit issue is not labeled `decision-map:map` | Reject it; do not create a replacement map |
| No open map for bare work | Report that no map exists and stop |
| Multiple open maps | List linked titles and require selection |
| GitHub lookup fails | Return the `gh` failure; do not fall back to a new map |
| Skill handoff fails | Return the failure; do not reproduce tracker or claim logic |

The error boundary is deliberate. A command parser that reconstructs the skill's operational behavior will drift from the single source of truth and can violate the one-ticket rule.
