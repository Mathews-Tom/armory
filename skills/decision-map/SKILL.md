---
name: decision-map
description: 'Maps the unresolved architecture, policy, and scope decisions that must be answered before planning can start: one durable decision ticket per question on the issue tracker, typed and blocker-linked under a parent map, with fog-of-war, out-of-scope, a computed frontier, and one decision resolved per invocation. Triggers on: "map the decisions", "what do we need to decide", "identify the unknowns", "not ready to plan yet", "decision map", "chart this effort", "work the next decision ticket", "wayfinder". Use when the destination is still uncertain. NOT for implementation slices of a known feature, use task-decomposer. NOT for milestone plans, use plan-prompts.'
metadata:
  version: 1.0.1
  category: development
  tags: [planning, issue-tracker, decisions, discovery, frontier, pre-planning]
  difficulty: advanced
  phase: define
  complements:
    - plan-prompts
    - task-decomposer
    - project-context-setup
    - adr-writer
    - plan-review
---

# Decision Map

## Scope and Trigger Boundary

Ask one discriminator before creating anything: **Do we know what should be built?** If no, map unresolved decisions. If yes, route known design into milestones with `plan-prompts` or implementation-sized work with `task-decomposer`. A decision map produces decisions and evidence, never implementation deliverables.

| Situation | Package |
|---|---|
| Destination or design still unclear; decisions would have to be invented | `decision-map` |
| Design known; needs milestones and execution prompts | `plan-prompts` |
| Feature specified; needs implementation slices, tests, risks | `task-decomposer` |
| Plan exists; needs a pre-implementation audit | `plan-review` |
| Plan approved; needs execution across sessions | `milestone-runner` |
| Repo audit needs standalone remediation plans, optionally as issues | `codebase-advisor --issues` |
| One decision needs a durable record | `adr-writer` |
| Session state must survive a handoff | `handoff` |

Do not turn vague hopes into implementation tasks merely to make progress appear orderly. A sharp but currently unanswered question is a ticket. A question that cannot yet be stated sharply is fog.

## Data Model

A map is one parent tracker item with five sections: `Destination`, `Notes`, `Decisions so far`, `Not yet specified`, and `Out of scope`. It is an index, not a duplicate store. A decision exists in exactly one ticket; the map holds only resolution pointers and scope boundaries.

A ticket holds one question, exactly one type label, exactly one interaction label, blockers, visible owner, session claim, and closure state. Refer to maps and tickets by linked title, never a bare identifier. Type labels are `decision-map:discussion`, `decision-map:research`, `decision-map:prototype`, and `decision-map:unblock`. Interaction labels are authoritative: exactly one of `decision-map:hitl` or `decision-map:afk`; ticket bodies must not restate the interaction mode.

## Prerequisites

Use `gh --version` and require `gh` 2.96.0 or newer only when the user explicitly selects GitHub as the tracker. Verify authentication with `gh auth status` before that path. `frontier.py` requires Python 3.12 and only the standard library. `.docs/agents/issue-tracker.md`, when present, is the authoritative backend choice. Otherwise store maps locally in `.docs/decision-maps/<effort>/`; select GitHub only when the user expressly asks for it. Do not infer GitHub selection from a remote or authentication. Report the selected backend once and mention `project-context-setup` when the choice should be persisted.
Probe GitHub capability before using native relationships. When older GitHub Enterprise or an older CLI rejects `blockedBy`, take the degraded path: generated child links in the map and `Blocked by: #N` lines in ticket bodies. The degraded index exists only to emulate absent tracker relationships.

## Workflow

### Mode A — Chart the Map

1. Name the destination before discussing its route. Use one concrete either-or question at a time and reuse the effort's vocabulary.
2. Sweep breadth-first for policy, architecture, scope, evidence, access, and design questions. If no fog surfaces, stop: the effort needs no decision map.
3. Ensure labels and the selected backend schema exist. Create the map with all five sections.
4. Create every question already sharp enough to ticket. Give every ticket exactly one type label and exactly one interaction label.
5. Wire blocker edges only after ticket creation, because the backend needs ticket identifiers before it can connect them.
6. Put the remaining unformulated uncertainty in `Not yet specified`; record conscious exclusions with a reason in `Out of scope`.
7. Compute the frontier and map state with `frontier.py`; report created topology and stop.

Charting resolves nothing, runs no research, implements nothing, and never collapses uncertainty to look tidy. Report the AFK-ready frontier separately: those tickets may be advanced by that many independent `work` invocations, each resolving at most one ticket.

### Mode B — Work Through the Map

1. Load only the map body, select the requested frontier ticket or the first item returned by `frontier.py`, and establish visible ownership.
2. Acquire and verify the session claim before substantive work. Follow `references/claim-protocol.md`; do not infer exclusivity from assignment.
3. Resolve exactly one ticket by its type. A HITL ticket requires the human's judgment; an agent answering it alone has broken the ticket.
4. Record one closure path: `RESOLVED`, `OUT_OF_SCOPE`, or `INVALIDATED`. Write the decision or evidence in the ticket, close it with the matching backend path, and add only a pointer in `Decisions so far` or `Out of scope`.
5. Create newly surfaced sharp questions, graduate them out of fog, and remove only the graduated fog patch. Recompute frontier and state.
6. Report and stop without selecting another ticket.

`unblock` work is restricted to evidence, access, measurement, setup, or a minimal experiment that makes a decision answerable. It never implements a product feature.

## Output

### Chart Output

Report map title and identifier, tickets with type and interaction labels, blocker edges, current frontier, remaining fog, computed map state, and the stop condition. Include the AFK-ready frontier count and state that each item requires a separate `work` invocation.

### Work Output

Report the resolved ticket, closure path, recorded decision or evidence, new tickets, changed blocker edges, resulting frontier, state, and stop condition. When the state is `COMPLETE`, recommend `plan-prompts` for implementation planning. Do not create an inline plan.

## Claim Protocol

Visible ownership and session claim are separate requirements. On GitHub, a claim comment begins with `decision-map claim`, includes `session:` and `claimed-at:`, and is re-read before work. The lowest non-stale database comment identifier, encoded in the issue-comment URL, wins. A loser withdraws, removes its assignee if it added one, recomputes the frontier, and selects another ticket. A claim older than the map's configured TTL, default 24 hours, can be preempted with a recorded reason.

Local maps use an exclusive claims lock. See `references/claim-protocol.md` for exact arbitration, stale-claim, and release rules.

## Map States

An empty frontier does not mean completion. Evaluate the ordered ladder: actionable unclaimed ticket means `ACTIVE`; otherwise any claimed open ticket means `WAITING`; otherwise any open ticket means `BLOCKED`; otherwise non-empty fog means `FOGGY`; otherwise no open tickets, no fog, and no `Unresolved contradiction:` entry in `Notes` means `COMPLETE`.

## Error Handling and Troubleshooting

| Failure | Diagnose | Corrective action |
|---|---|---|
| Tracker document absent | inspect `.docs/agents/issue-tracker.md` | use the local `.docs/decision-maps/` backend unless the user selected GitHub |
| Native relationship unsupported | `gh issue view <map> --json blockedBy` | use degraded generated links and body blockers |
| Label schema absent | `gh label list` | bootstrap labels idempotently before ticket creation |
| Two sessions claim one ticket | re-read comments and database comment identifiers | lowest fresh identifier wins; loser withdraws |
| Claim belongs to dead session | compare timestamp to map TTL | record preemption, then claim |
| Empty frontier with open tickets | run `frontier.py` | report `WAITING` or `BLOCKED`, never complete |
| Map and tickets drift | inspect map pointers and backend graph | repair generated degraded index or resolution pointers |
| Malformed local claim lock | inspect the lock contents | stop; preserve it for diagnosis rather than overwriting it |

Fail loudly when the map label is absent, a ticket has missing or multiple type or interaction labels, the capability probe is ambiguous, or claim verification fails. Do not silently create a replacement map.

## Rationalizations

Reject these statements:

- “I'll resolve two; they are small.” One invocation resolves one ticket.
- “I'll pre-slice fog while I am here.” Fog is deliberately not a task list.
- “I know the answer, so no human is needed.” That violates a HITL ticket.
- “I'll just build it; it is faster.” Implementation is outside this package.
- “The frontier is empty, so we are done.” The state ladder decides that.

## Red Flags

Bare issue numbers in narration, maps that repeat ticket content, sharp questions left in fog, closed tickets without resolution comments, scope boundaries listed as decisions, or substantive work before claim verification all signal a broken map.

## Verification

Confirm all five map sections exist; every open ticket is a child of the map and has exactly one type and interaction label; every blocker edge is native or documented as degraded; ownership and claim were verified before substantive action; each closure used one valid path and reached the correct map section; and the reported state matches `frontier.py`.

```bash
uv run python skills/decision-map/scripts/frontier.py --map 42
uv run python skills/decision-map/scripts/frontier.py --map 42 --degraded
uv run python skills/decision-map/scripts/frontier.py --local .docs/decision-maps/billing
```

## References

| Reference | Purpose |
|---|---|
| `references/map-format.md` | Map schema, template, and index rules |
| `references/ticket-types.md` | Types, labels, and closure boundaries |
| `references/claim-protocol.md` | GitHub arbitration and local exclusion |
| `references/map-states.md` | Ordered state ladder |
| `references/tracker-operations.md` | GitHub, degraded, and local backend operations |
| `references/elicitation.md` | Discovery questions and vocabulary discipline |
| `references/research-resolution.md` | Self-contained AFK research protocol |
| `scripts/frontier.py` | Normalized frontier and state computation |
