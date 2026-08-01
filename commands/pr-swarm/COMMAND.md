---
name: pr-swarm
type: command
description: 'Slash-command wrapper for the pr-swarm skill. `/pr-swarm #123 #456` (or bare numbers, space- or comma-separated) drives that many already-open pull requests to merge-ready at the same time, each in its own isolated git worktree and its own headless Claude Code session. Triggers on: "/pr-swarm", "pr-swarm #123 #456", "parallelize these PRs", "drive PR #123 and #456 to green in parallel", "own-PR-to-green fleet", "isolated worktree loops for my PRs". Use this command when a user wants a concise argument surface for parallelizing two or more of their own open pull requests while delegating independence checks, worktree naming, launch mechanics, and verification gates to skills/pr-swarm.'
metadata:
  version: 1.0.0
  category: development
  tags: [git, pull-requests, worktree, slash-command, parallel-execution]
  difficulty: advanced
  phase: ship
command:
  syntax: /pr-swarm <PR#> [PR# ...]
  handler: inline
  dependencies:
    - skills/pr-swarm
---

# PR Swarm Command

Thin slash-command entry point for `skills/pr-swarm`. This command parses arguments and resolves PR numbers only. The skill owns independence checking, worktree/branch naming, lane launch mechanics, monitoring, verification gates, and teardown.

## Workflow

1. Parse every `#N` or bare `N` token from the argument string (space- or comma-separated). Deduplicate. Require at least one.
2. For each number, resolve it against the current repository with `gh pr view N --json number,state,headRefName,baseRefName,author,url,isCrossRepository`.
3. Load `skills/pr-swarm`.
4. Hand off the full resolved PR list (including any dropped/flagged entries from step 2) to the skill's Phase 1 onward.
5. Return the skill's per-PR report and fleet summary unchanged.

## Syntax

```text
/pr-swarm #482 #491
/pr-swarm 482, 491, 503
/pr-swarm #482
```

A single PR number is valid — it still runs through the skill's full isolated-worktree-and-own-session path (see "Single-PR invocation" in `skills/pr-swarm/SKILL.md`); this command never collapses that to inline execution.

## Argument Rules

- Accept PR numbers with or without a leading `#`, separated by whitespace and/or commas.
- Order is not significant — the swarm has no dependency ordering between lanes (contrast with `/stack-pr`, where positional order is the stack's parent chain).
- A token that isn't a valid integer after stripping `#` is a parse error, not a silently-dropped argument.
- Numbers are resolved against the repository of the current working directory; this command does not accept cross-repository `owner/repo#N` references.

## Error Handling

| Problem | Resolution |
|---|---|
| No PR numbers provided | Report the required syntax and stop |
| A token isn't a valid PR number after parsing | Report the invalid token and stop before resolving any PR |
| `gh pr view` fails for a given number (not found, no access) | Drop that PR from the swarm, report why, continue with the rest |
| Fewer than 1 PR remains after resolution | Stop — there is nothing to swarm |
| `gh` not authenticated | Stop before resolving any PR |
| Not inside a git repository | Stop and report |

## Output

Return the delegated skill result exactly:

1. Per-PR resolution notes (dropped/flagged entries and why).
2. Independence-check result (pass, or the exact file/PR overlap that blocked the swarm).
3. Worktree paths and branch names used.
4. Final per-PR status table: `state`, `mergeStateStatus`, CI conclusion, unresolved-thread count, worktree clean/dirty, lane exit code.
5. Teardown decision per PR.

## Worked Example

`/pr-swarm #482 #491` against a repo where #482 touches `src/status-line.ts` and #491 touches `src/mcp/autocomplete.ts`:

1. Resolution: both `state: OPEN`, both authored by the invoking user, `isCrossRepository: false` for both — nothing dropped or flagged.
2. Independence check (delegated to the skill): `git diff --name-only` on each PR's merge-base shows disjoint file sets — no overlap, proceed.
3. Worktree/branch inference: `#482` → `feat/status-line-token-count` → short name `status-line-token-count` → `.worktrees/status-line-token-count`; `#491` → `feat/mcp-name-autocomplete` → `.worktrees/mcp-name-autocomplete`. Neither name collides, so no PR-number suffix is needed.
4. Two lanes launch independently, each with its own `claude -p` process, own worktree, own log file. Neither lane's prompt mentions the other PR's number beyond the isolation instruction.
5. The command returns the skill's fleet-status table once both lanes exit and are independently re-verified via `gh pr view` — not on either lane's self-reported "done".

If step 2 instead found both PRs editing `src/shared/types.ts`, the command would stop right there and surface the overlap instead of creating either worktree — the independence check runs before any git state is mutated, not after.
