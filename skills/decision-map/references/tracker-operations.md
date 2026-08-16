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

Store `.scratch/<effort>/map.md`, one numbered child file with `Type:`, `Interaction:`, `Status:`, and `Blocked by:` headers, and a `claims/` directory. Write resolution pointers back to the map. Backend selection is: obey `docs/agents/issue-tracker.md`; otherwise GitHub remote plus working `gh auth`; otherwise local markdown. Report the choice and suggest `project-context-setup` when it should become repo policy.
