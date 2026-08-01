---
name: pr-swarm
description: 'Parallelizes two or more independent "own PR to green" loops for a single repository using isolated git worktrees and separate headless Claude Code sessions per PR — resolving merge conflicts, clearing review feedback, and watching CI to completion without one PR''s diff or feedback leaking into another''s context. Triggers on: "parallelize these PRs", "drive PR #123 and #456 to green in parallel", "own-PR-to-green fleet", "run these PRs concurrently", "isolated worktree loops for my PRs", "pr-swarm". Use this skill when a user has two or more already-open, file-disjoint pull requests in the same repository that each need conflict resolution, review-feedback triage, and CI monitoring, and wants them driven to merge-ready at the same time instead of one after another.'
metadata:
  version: 1.0.0
  category: operations
  tags: [git-worktree, parallel-execution, pull-requests, headless-cli, ci-monitoring]
  difficulty: advanced
  phase: ship
---

# PR Swarm — Parallel Own-PR-to-Green Loops

## Problem

A repository checkout can only have one branch active at a time. A user with N independent, already-open pull requests — disjoint branches, disjoint changed files, no real relationship between them — that each need conflict resolution, review-feedback triage, and CI watching wastes wall-clock time driving them one after another when nothing about them actually depends on each other.

## Root cause

`git worktree` removes the one-checkout constraint: N branches can be checked out simultaneously, each in its own directory, sharing one `.git` object store. Combined with N independent headless Claude Code sessions (own process, own context window, own token budget — not subagents sharing this session's budget), the PRs can be driven to green concurrently with zero cross-talk.

## Reference Files

|File|Contents|Load When|
|---|---|---|
|`references/launch-mechanics.md`|`claude -p` flags, detached background launch pattern, watchdog/liveness checks, exit-code capture|Phase 5 (Launch)|
|`references/verification-gates.md`|GitHub API correctness pitfalls: stale `mergeStateStatus`, body-only bot reviews, stale `statusCheckRollup` entries, review-thread pagination|Phase 6 (Monitor & Verify)|
|`references/lane-prompt-template.md`|The literal per-lane task prompt (termination conditions, orientation, conflict resolution, watch loop)|Phase 4 (Lane Prompt)|

## Scope boundary

This skill drives PRs that are **already open**. It does not create PRs from issues, does not decide whether unrelated PRs are safe to parallelize (that's Phase 2, and it's a hard stop on any real overlap, not a judgment call this skill makes silently), and does not resolve PRs closed by a maintainer for policy reasons — see "Mid-loop external closure" in Phase 6.

## Workflow

### Phase 1 — Resolve each PR

For every requested PR number `N`:

```bash
gh pr view N --json number,state,headRefName,baseRefName,author,url,isCrossRepository
```

- `state != OPEN` → drop this PR from the swarm and report why; do not silently skip it.
- `isCrossRepository == true` (PR from an unrelated fork, not the user's own) → flag for confirmation before proceeding; this skill assumes the invoker's own fork/branch setup.
- Author check: `gh api user --jq .login` vs. `author.login`. Mismatch is a warning, not a stop — co-driving a teammate's PR is legitimate, but the invoker should see it flagged.

### Phase 2 — Independence check (mandatory, not optional)

Do this before creating any worktree. A user asserting "these are unrelated" is not proof — verify the actual changed files:

```bash
for N in "${PRS[@]}"; do
  base="$(gh pr view "$N" --json baseRefName -q .baseRefName)"
  head="$(gh pr view "$N" --json headRefName -q .headRefName)"
  git fetch origin "$head:refs/remotes/origin/$head" --quiet
  merge_base="$(git merge-base "origin/$base" "origin/$head")"
  files["$N"]="$(git diff --name-only "$merge_base" "origin/$head")"
done
```

Pairwise-intersect `files[N]` against `files[M]` for every pair in the requested set. Any non-empty intersection → **stop**, report exactly which files and which two PRs collide, and ask before proceeding — running two lanes that touch the same file concurrently is exactly the failure mode this skill exists to prevent, not something to wave through because the user said it was fine.

### Phase 3 — Worktree and branch naming (inferred, never asked for)

Short name derivation from each `headRefName`:

```bash
raw="$head"                                   # e.g. feat/status-line-token-count
short="${raw#*/}"                             # strip one leading "<type>/" segment if present
short="$(echo "$short" | tr '[:upper:]_' '[:lower:]-' | tr -s '/' '-')"
[[ -n "${used[$short]:-}" ]] && short="${short}-${N}"   # disambiguate collisions with the PR number
used["$short"]=1
```

Worktree directory convention: check `bunfig.toml` / lockfile config / `.gitignore` for an existing `.worktrees/**` or `.wt/**` pattern first — that is the project's own sanctioned convention if present. Default to `.worktrees/<short>/` when nothing is declared. Free the main checkout first if it currently holds one of the target branches (`git switch main` or another branch outside the set — a branch can be checked out in only one worktree).

```bash
git worktree add ".worktrees/$short" "$head"
```

**Per-worktree install is mandatory under a hoisted linker** (check `bunfig.toml` for `linker = "hoisted"`, or npm/yarn without workspaces hoisting): `node_modules` is not shareable across worktrees since each can have a different lockfile state. Run installs for all lanes in parallel, not serially.

**Gitignored build artifacts don't come back with a fresh worktree checkout** — native addons, generated code, compiled binaries. If the repo has any (check for `*.node`, `.wasm`, generated protobuf/codegen output, or a documented build step), rebuild or relink them per worktree before running tests; a lane that skips this fails with a confusing "module not found" that looks unrelated to its actual task.

### Phase 4 — Lane prompt

Render `references/lane-prompt-template.md` per PR, substituting `{PR_NUMBER}`, `{REPO}` (`owner/name`), `{WORKTREE_PATH}`, and `{OTHER_PR_NUMBERS}` (the rest of the swarm, so the lane's own COI instruction is concrete, not abstract). Write each rendered prompt to a file in the worktree (`$WORKTREE/.pr-swarm-prompt.md`) rather than passing it inline — a multi-hundred-word prompt through shell quoting is a real failure mode, a file path is not.

### Phase 5 — Launch

See `references/launch-mechanics.md` for the exact `claude -p` invocation, detachment pattern, and liveness-check mechanics. One lane per PR, launched independently — never chain multiple launches in a single tool call (each launch needs its own call so a launch failure for lane 2 doesn't silently ride on lane 1's success).

### Phase 6 — Monitor and verify

Poll every ~60-120s with jitter: tail each lane's log, check liveness (see `references/launch-mechanics.md` for the zombie-PID trap). **Never treat a lane's own self-reported completion as the gate.** After a lane's process exits, independently re-verify via the checks in `references/verification-gates.md` — merge state, CI conclusion, unresolved review threads (including body-only bot reviews), and current `state` (a maintainer-closed PR looks identical to a healthy one on every other field).

### Phase 7 — Report

Per PR: final `state`/`mergeStateStatus`, CI conclusion, unresolved-thread count (including the body-only-review scan), worktree clean/dirty, lane process exit code. A lane that exited non-zero, or whose PR isn't independently confirmed clean by the checks above, is reported unresolved — a lane's own "done" message is never sufficient on its own.

### Phase 8 — Teardown

Only after every lane is externally confirmed clean:

```bash
git worktree remove ".worktrees/$short"
```

Leave any unresolved PR's worktree in place for continued work. Removing a worktree just because the batch finished, while that one PR is still dirty, destroys debugging context for no benefit.

## Output

Report structure, filled in per swarm run:

```text
## Resolution
#{N}: {short-name} — {state}, author={login}{, author mismatch flagged if applicable}
...

## Independence check
PASS — no changed-file overlap across {PRS}
  (or)
STOP — #{N} and #{M} both touch {path}; resolve before proceeding

## Worktrees
#{N} → .worktrees/{short-name} (branch {headRefName})
...

## Fleet status
| PR | state | mergeStateStatus | CI | unresolved threads | worktree | exit code |
|---|---|---|---|---|---|---|

## Teardown
#{N}: removed / left in place (reason)
```

A PR missing from the "Fleet status" table (dropped in resolution or blocked by the independence check) must still appear in "Resolution" with the reason — never silently omitted from the report.

## Single-PR invocation

`pr-swarm` with exactly one PR still runs the full worktree-and-own-session path — no fast path that skips isolation. The value being delivered (own session, own context/budget, no shared state with the invoking conversation) doesn't depend on fan-out width; collapsing back to inline execution for N=1 would silently drop the one guarantee that was asked for.

## Capacity sanity check

- N concurrent `bun`/`npm`/test-suite runs is the real resource cost, not git or the GitHub API. Confirm core/RAM headroom before fanning out wide; on constrained machines, have lanes run targeted tests per iteration and reserve full suites for the final gate.
- GitHub's REST/GraphQL rate limit (5000/hr authenticated) is nowhere near the ceiling at a 60-120s polling cadence for any realistic swarm size.
- Disk: each worktree needs its own `node_modules` (or equivalent) under a hoisted linker. Budget accordingly — this is the correct tradeoff for true isolation, not a shortcut to avoid.
- Lane wall-clock is asymmetric: a PR that's already mergeable can self-verify and exit in minutes; a PR needing real conflict resolution plus a native rebuild can run for hours with all-green CI. Don't read one lane's fast exit as a signal the others are stuck.

## Error Handling

| Problem | Resolution |
|---|---|
| PR number not found / no read access | Drop from swarm, report, continue with the rest |
| PR `state != OPEN` | Drop from swarm, report why, do not attempt to reopen |
| Two or more PRs share a changed file (Phase 2) | Stop before creating any worktree; report the exact overlap and ask |
| Branch already checked out in the main worktree | `git switch` it away before `git worktree add` |
| Worktree directory already exists from a prior run | Reuse it if the branch matches; otherwise stop and ask (don't silently overwrite) |
| Hoisted-linker install fails in one lane | That lane's setup fails independently; other lanes proceed unaffected |
| `gh` not authenticated, or missing `repo`/`workflow` scopes | Stop before Phase 1 — nothing downstream can function without it |

## Verification

- [ ] Every reported-clean PR was checked with the current `state`, not a cached read from earlier in the run
- [ ] Independence check (Phase 2) ran and passed before any worktree was created
- [ ] Every unresolved-thread count includes the body-only-review scan (`references/verification-gates.md`), not just `reviewThreads`
- [ ] Every lane's exit code was captured, not inferred from log tail alone
- [ ] Teardown only ran for lanes independently confirmed clean

## Red Flags

- Trusting a lane's final log line ("PR is ready to merge") without an independent `gh pr view` re-check
- Skipping Phase 2 because "the user said they're unrelated"
- Removing a worktree for a lane whose PR isn't confirmed clean, because the batch as a whole finished
- Counting `reviewThreads.isResolved == false` as the complete unresolved-feedback signal without also scanning review bodies
