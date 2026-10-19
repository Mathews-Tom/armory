# Tracker Operations

Use nine operations: 0 ensure schema, 1 create map, 2 create ticket, 3 set type and interaction labels, 4 establish parent-child, 5 add blocker edge, 6 query frontier and state, 7 claim, 8 resolve.

## GitHub native path

```bash
# 0 — idempotent schema bootstrap
gh label create decision-map:map        --force --color 0E8A16 --description "Decision map root"
gh label create decision-map:discussion --force --color 1D76DB
gh label create decision-map:research   --force --color 5319E7
gh label create decision-map:prototype  --force --color FBCA04
gh label create decision-map:unblock    --force --color D93F0B
gh label create decision-map:hitl       --force --color 0052CC
gh label create decision-map:afk        --force --color 006B75

# 1/2/4 — map and children
gh issue create --title "<name>" --label decision-map:map --body-file map.md
gh issue create --title "<question>" --parent <map-number> --label decision-map:discussion --label decision-map:hitl --body-file ticket.md

# 5 — blockers after tickets exist
gh issue edit <child-number> --add-blocked-by <blocker-number>

# 7/8 — visible ownership and closure
gh issue edit <number> --add-assignee @me
gh issue close <number> --reason completed
gh issue close <number> --reason "not planned"
```

Before native reads, probe once with `gh issue view <map-number> --json blockedBy`. On an unknown-field error, choose degraded mode. Native reads request `parent` and `blockedBy`; degraded reads request only portable issue fields, generated children from `## Generated child index`, and body blockers. Do not use GraphQL.

## Degraded path

Use a generated task list in the map for children and `Blocked by: #N` body lines for dependencies. Parse them only with `frontier.py --degraded`. This fallback is for missing capability, not a second source of truth on native GitHub.

## Local path

Store `.docs/decision-maps/<effort>/map.md`, one numbered child file with `Type:`, `Interaction:`, `Status:`, and `Blocked by:` headers, and a `claims/` directory. These local metadata headers are required even though the initial decision content is question-only; use the example in `references/ticket-types.md`. Write resolution pointers back to the map only after closure. Backend selection is: obey `.docs/agents/issue-tracker.md`; otherwise use local markdown. Use GitHub only when the user explicitly selects it and `gh auth status` succeeds; do not infer that choice from a remote or authentication. Report the choice and suggest `project-context-setup` when it should become repo policy.

## Recording evidence without changing tracker state

Evidence is a write to the selected ticket, not a new helper operation or a closure:

- **GitHub (native or degraded):** write the evidence record to a temporary body file and post it with `gh issue comment <number> --body-file <evidence-file>`. Start the comment with `## Evidence`, not `decision-map claim`. Preserve the original issue body, labels, assignees, blocker relationships and existing claim comment. The evidence comment does not release, replace or refresh that claim.
- **Local:** append an unquoted `## Evidence` heading to the existing numbered ticket body, followed by the evidence record. Prefix **every physical evidence line** with `> ` (an empty line becomes `>`), including pasted output, nested headings, code-fence delimiters, and any `Type:`, `Interaction:`, `Status:`, or `Blocked by:` text. A fenced block alone is not safe: the current local scanner reads matching metadata lines anywhere in the file, with the last value winning. Quoting each line keeps evidence out of that metadata namespace. Preserve the original question, headers, their values and the claim lock; later evidence is another quoted append, not a body replacement.

For example, this local append records potentially misleading raw output without changing the ticket's metadata:

```markdown
## Evidence
> Outcome: UNRESOLVED_WITH_EVIDENCE
> Artifact: /tmp/decision-prototype/state.html (temporary; open this file directly)
> Observation: browser unavailable; scenarios not observed.
>
> Captured sample output (not tracker metadata):
> Status: CLOSED
> Type: decision-map:research
> Interaction: decision-map:afk
> Blocked by: #99
> Pending prerequisite: human browser observation and verdict.
> Continuation: same ticket and existing session claim.
```

Record the question/assumptions, artifact access instructions, observations, inferences, verdict and exact pending prerequisite as applicable. An unanswered result leaves `Status: OPEN` locally or the GitHub issue open, with the existing claim held; it adds no resolution pointer and creates no second ticket. Recompute the frontier/state: an otherwise empty frontier with this claimed open ticket is `WAITING`; other actionable tickets still make the map `ACTIVE`. Resume on this ticket by re-verifying the same claim, under the existing 24-hour default stale-claim rule in `references/claim-protocol.md`.
