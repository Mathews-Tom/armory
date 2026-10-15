---
name: stacked-prs
description: 'Manages dependent branch stacks and stacked pull requests using safe Git topology rules. Triggers on: "create stacked PRs", "publish this stack", "sync my PR stack", "rebase this stack", "merge the stack", "retarget child PRs", "split this branch into stacked PRs", "validate this stack", "cleanup stacked branches", or "GitHub native stack". Use when local branches or one source branch need a dependency-ordered PR stack with correct parent bases, validation, synchronization and optional GitHub-native stack support, or when an existing stack needs its topology, provenance and native membership resolved before its landing and cleanup are delegated to the ship-workflow lifecycle.'
metadata:
  version: 0.5.0
  category: development
  tags: [git, pull-requests, stacked-prs, github-native, workflow]
  difficulty: advanced
  phase: ship
---

# Stacked PRs

Build, publish, synchronize and validate stacked pull requests without corrupting branch topology, and decide the topology, provenance and native membership that landing an existing stack depends on.

The package identity is provider-neutral. Git is the source of truth for branch ancestry; provider PR metadata is the source of truth for review bases. GitHub through `gh` is the first documented provider adapter.

Landing, post-landing promotion and retargeting, and cleanup of an existing manual or GitHub-native stack have one executable owner: the `ship-workflow` skill's stack graph run. This skill authors its explicit stack decision packet and delegates to it once (§5); it has no hand-run landing or cleanup procedure of its own.

## Reference Files

| File | Contents | Load When |
| --- | --- | --- |
| `references/stack-model.md` | Stack inference, explicit ordering, native detection and the explicit stack decision packet | Inspecting, publishing, validating, or delegating a stack |
| `references/provider-adapters.md` | Provider adapter contract and GitHub `gh` commands for listing, creating, retargeting and checking PRs | Creating, retargeting or checking PRs |
| `references/sync-algorithm.md` | Slice proof, expected-old leases and the standalone restack procedure | Syncing a stack after a parent or base moves |
| `references/merge-discipline.md` | Parent-first landing rules, landing proofs, retention and endpoints the delegated run enforces | Deciding what to select and what an outcome means |
| `references/metadata-format.md` | Optional metadata schema and validation rules | `.stack-prs.yaml` exists or inference is ambiguous |
| `references/provenance.md` | Commit-trailer stack identity, stamping, verification, merge-mode coupling | Creating, splitting, syncing, or choosing a merge method |
| `references/github-native.md` | Native detection, linking eligibility, native sync and the native prefix policy | A GitHub-native stack is requested or detected |

## When To Use

| Use this skill | Use another package |
| --- | --- |
| Multiple dependent branches need PRs against parent branches | `ship-workflow` for one independent PR |
| A feature branch must be split into reviewable dependent branches | `task-decomposer` for planning tasks before code exists |
| An existing stack needs rebasing, retargeting to correct parents, validation, or a landing scope decision | `pr-review` for reviewing one PR diff |
| An existing stack must be landed or cleaned after landing (delegated in §5) | General Git commands for unrelated branch cleanup |

## Core Rules

- Run `git rev-parse --show-toplevel` before any workflow.
- Run `git status --porcelain` before rebases, pushes, PR creation and PR retargeting.
- Stop on a dirty worktree unless the user explicitly scopes the operation to inspection only.
- Prefer existing PR `baseRefName` values over inferred ancestry.
- Resolve `<base>` from the root PR's `baseRefName` (`gh pr view <root-pr> --json baseRefName --jq .baseRefName`), not from `origin/HEAD`; a stack's trunk need not be the repository's default branch.
- Use explicit branch order or `.stack-prs.yaml` when parent inference is ambiguous.
- Never use plain `git push --force` or a bare `--force-with-lease`; push rewritten heads with `--force-with-lease=refs/heads/<branch>:<expected-old-oid>`.
- Never delete stack branches by hand; proof-based cleanup belongs to the delegated run (§5).
- Stamp `Stack-Id` and `Stack-Position` trailers on every commit the skill creates or splits; copy the ID from `.stack-prs.yaml` or mint it once when absent.
- Verify trailers are present and consistent before delegating a landing of a stack the skill created.
- Probe every open stack PR for native-stack membership during Inspect (`references/stack-model.md` § Native Stack Detection) before any landing decision.
- Detect the provider's squash message policy (`squash_merge_commit_message`) before choosing `squash` as a node's merge method (`references/provenance.md` § Merge Mode Coupling).

## GitHub-native stack mode

GitHub-native stacks are same-repository-only. They enhance manual Armory stacks; they do not replace provenance trailers, `.stack-prs.yaml`, or the provider-neutral workflow.

Native-stack membership is a provider-side property of a pull request, not a mode this skill chooses. Detect it for every stack PR during Inspect, before any landing decision, whether or not `github-native` mode was requested: read `.stack` from `GET repos/{owner}/{repo}/pulls/<number>` and the complete ordered membership from `GET repos/{owner}/{repo}/stacks/<stack-number>` (`references/github-native.md` § Detecting an already-native stack).

### Creating native state (opt-in)

Converting a manual stack to native with `gh stack link` is a provider mutation. Use it only after these eligibility checks pass:

1. GitHub CLI plus `gh stack --help` succeeds; install `github/gh-stack` when absent.
2. Native stack support is enabled for the repository; native exit code 9 means the stack stays manual.
3. Every proposed head/base branch and pull request belongs to the same GitHub repository; reject forks and cross-repository stacks.
4. Existing PR bases, local branch order, and `Stack-Id`/`Stack-Position` provenance agree. Stop on disagreement.
5. The user explicitly requests native mode.

When the checks fail the stack stays manual. Never convert in either direction automatically or mid-stack.

### Operating on an already-native stack (mandatory)

Once Inspect finds a PR already native, native handling is not a choice: the provider refuses a synchronous merge for a stack member, and the delegated run lands native members only through one guarded asynchronous request on the highest selected member. Conditions 1-4 above still apply as safety checks; condition 5's consent does not, because the provider already registered the stack.

- Link and sync with `gh stack link`, `gh stack sync`, `gh stack rebase` and `gh stack push` (`references/github-native.md`); re-read `gh stack view` after every non-interactive sync.
- To land, require the exact highest PR the user authorized and select every open member below it in the stack decision packet. The provider merges the whole open prefix up to that PR, so an open lower member outside the authorization is a scope question for the user, never an implicit widening. Open members above it are unselected packet nodes.
- Choose each selected member's merge method from the trailer-survival policy (`references/github-native.md` § Choosing a merge method for trailer survival). Under a merge queue the queue's rules choose the method and the packet's method is not sent.
- Delegate the landing (§5). There is no per-member request, no ordinary merge and no manual fallback for a native member, and the guarded request covers only the highest selected head (`references/github-native.md` § Landing policy).
- With `squash_merge_commit_title: COMMIT_OR_PR_TITLE` (GitHub's default), a PR squashing a single commit takes that commit's headline as the base-branch subject, not the PR title, and this cannot be corrected after merge without rewriting pushed history. When the visible subject matters, align an unmerged commit headline with the PR title before delegating (`git commit --amend -m "<pr-title>"`, then `git push --force-with-lease=refs/heads/<branch>:<old-head> origin <branch>`), and record the new head in the packet.

## Workflow

### 1. Inspect

Build a stack model without modifying anything:

```bash
git rev-parse --show-toplevel
git status --porcelain
git branch --show-current
git for-each-ref --format='%(refname:short)' refs/heads
git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'
gh pr list --state open --json number,title,headRefName,headRefOid,baseRefName,state,url
```

Produce a table with one row per stack branch. Run the native-stack probe (`references/stack-model.md` § Native Stack Detection) for every PR before recording this table:

| Order | Branch | Parent | PR | State | Checks | Native |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `feat/parser-core` | `main` | `#101` | open | pending | no |
| 2 | `feat/parser-cache` | `feat/parser-core` | `#102` | open | pending | no |

Stop when no provider adapter is available, no local branches match the requested stack, or parent order cannot be inferred from PR bases, explicit order, or metadata.

### 2. Publish

Create missing PRs and retarget wrong bases:

```bash
git status --porcelain
git push -u origin <branch>
gh pr create \
  --base <parent-branch> \
  --head <branch> \
  --title "<title>" \
  --body-file <generated-body-file>
gh pr edit <number> --base <parent-branch>
```

Generated PR bodies must include the stack order and validation state:

```markdown
## Stack

Stack-Id: `auth-refactor-a1b2c3`
Base: `main`
Position: 1/3

1. `feat/parser-core` -> this PR
2. `feat/parser-cache` -> #102
3. `feat/parser-cli` -> #103

Depends on: (none - root)
Upstack: #102

## Validation

- Pending: commands not run yet
```

For non-root PRs, `Depends on:` lists the parent PR number. `Upstack:` lists the immediate child PR number when known.

Stop when a branch has no commits beyond its parent, an existing PR is closed and unmerged, or the provider rejects base retargeting.

### 3. Sync

Restack open branches after `<base>` or a parent branch moves, before anything lands, with the standalone procedure in `references/sync-algorithm.md`: record each child's old head `C` and fork point `F`, replay `F..C` onto the new tip `L` in a detached scratch worktree, prove the result and publish it with an explicit expected-old lease.

```bash
git status --porcelain
git fetch origin
git merge-tree --write-tree --merge-base=<F> <L> <C>
git push --force-with-lease=refs/heads/<branch>:<C> origin <N>:refs/heads/<branch>
```

Start at the first branch above the base and continue toward the leaf. Stop on conflicts, remote lease failures, or a parent PR that closed without merge. Promoting and retargeting children after their parent landed is part of the delegated lifecycle (§5), not this step.

### 4. Validate

Validate the stack as reviewable slices. Run cheap checks on every branch when practical; run expensive full checks on the leaf when branch-by-branch validation is not reasonable. Record exactly what ran in each PR body.

Use the target repository's detected local gate and provider checks. Do not run armory package-evaluation commands when operating on another repository's stack.

For this armory package implementation only, use:

```bash
uv run python scripts/validate_evals.py
uv run python scripts/generate_manifest.py
uv run python scripts/evaluate_package.py --path skills/stacked-prs
```

### 5. Land And Clean Up (delegated)

Landing, post-landing promotion and retargeting, post-merge acceptance and cleanup of an existing manual or native stack run once, through the `ship-workflow` skill's explicit stack graph contract:

1. Inspect (§1), including native membership, and verify provenance (`references/provenance.md` § Verifying Trailers).
2. Author one stack decision packet (`references/stack-model.md` § Explicit Stack Decision Packet): `select: true` for exactly the PRs the user authorized, every ancestor of a selected node and every other relevant member as unselected context, each selected node's revision-free `decision` with its cited sources and merge method, and `provenance: {"disposition": "preserve", ...}` naming what was inspected. Write it to a private temporary file outside the repository.
3. Load the registered `ship-workflow` skill. If the client has no such skill, stop `BLOCKED` naming `ship-workflow`; never fall back to hand-run merges, retargets, promotion pushes or deletions.
4. From a checkout of the target repository, run its executable from the loaded skill's absolute base directory, first read-only, then with the authorized endpoint:

   ```bash
   uv run --no-project --python 3.12 python "<ship-workflow-dir>/scripts/ship.py" --stack-plan "/tmp/stack.X/stack.json" --dry-run
   uv run --no-project --python 3.12 python "<ship-workflow-dir>/scripts/ship.py" --stack-plan "/tmp/stack.X/stack.json" --gates "/tmp/stack.X/gates.json" --until merged
   ```

   "Merge the stack" is `--until merged`; "merge and clean up" is the default `clean`. "Clean up" alone selects only nodes the provider already reports merged, so the run verifies and cleans them without landing anything new.
5. Resume with `--resume RUN_ID` only when the controller returned a saved run; add a refreshed packet of the same topology only for a resolved decision. A pre-journal admission or inspection stop can have `run_id: null` or no id: resolve its bounded input and repeat the original explicitly scoped invocation, never invent an id or select an unrelated run with bare `--resume`.
6. Relay the run's status, confirmed merges, retained dependents, cleanup dispositions and next action. `NEEDS_JUDGMENT` names a topology, provenance, scope or gate decision that belongs back here; `BLOCKED` names a missing prerequisite.

The run enforces parent-first order, slice-preserving promotion, expected-old leases, fresh gates per node, open-base retention and landing proofs (`references/merge-discipline.md`), and lands a native selection with one guarded request (`references/github-native.md` § Landing policy).

Routine delegated shipping uses the repository's current provider checks, reviews, protections and merge policy. A selected node can request `assurance: "high"` explicitly; routine nodes do not need pinned checkout logs or renamed CI jobs. Supply `--gates` when local validation is requested; use `per_commit: true` for every replayed commit and each gate's own timeout. Validation precedes push and preserves existing hooks. Definite refusals with unchanged inputs reuse the exact verified replay objects; uncertain mutations reconcile before retry. Saved assurance and validation survive resume; incompatible legacy authority stops for an explicit decision.

## Splitting One Branch Into A Stack

Use split mode when one source branch contains a feature that needs reviewable dependent PRs. Require the source branch, base branch, and target branch order from the user or from unambiguous commit names.

Inspect first:

```bash
git status --porcelain
git fetch origin --prune
git merge-base <base> <source-branch>
git log --oneline --reverse <base>..<source-branch>
git diff --stat <base>...<source-branch>
git diff --name-status <base>...<source-branch>
```

Select the safest split mode:

| Mode | Use When | Behavior |
| --- | --- | --- |
| Commit-range split | Contiguous commits map cleanly to slices | Create dependent branches and cherry-pick ranges |
| Commit-list split | Non-contiguous commits map cleanly to slices | Cherry-pick explicit commit lists in stack order |
| Patch-guided split | File or hunk boundaries are clear but commits are mixed | Stop for user-approved split map before mutation |
| Refuse automatic split | Changes are tangled across required boundaries | Report why the split is unsafe |

After creating branches, compare the leaf with the source branch before publishing:

```bash
git commit --amend --no-edit \
  --trailer "Stack-Id: <stack-id>" \
  --trailer "Stack-Position: <n>/<total>"
git diff --stat <source-branch>...<leaf-branch>
git diff --exit-code <source-branch>...<leaf-branch>
```

Stamp trailers on each slice's commits per `references/provenance.md` before publishing. Stamping amends commit messages but does not change tree content, so the leaf-vs-source comparison remains a tree comparison with `git diff` and must still pass.

Do not publish if the leaf differs from the source branch.

## Error Handling

| Condition | Action |
| --- | --- |
| Dirty worktree before mutation | Stop and report changed paths |
| Ambiguous parent order | Request explicit branch order or `.stack-prs.yaml` |
| Existing closed unmerged PR | Stop before creating replacements |
| Closed unmerged child after parent branch deletion | Follow `references/merge-discipline.md` § Recovery, then delegate the remaining landing |
| Rebase or cherry-pick conflict | Stop, report branch and conflicted files, do not continue children |
| Remote branch changed since fetch | Stop; do not retry without a fresh inspect |
| Failed validation | Record the failed command and stop publish or delegation |
| Top split branch differs from source | Stop before PR creation and report remaining diff |
| Commit in a created stack missing `Stack-Id` trailer | Stop; stamp unpublished commits per `references/provenance.md` before delegating |
| Trailer `Stack-Id` differs from `.stack-prs.yaml` | Stop; resolve canonical ID before mutation |
| An open lower native member is outside the authorized prefix | Ask for a scope decision; never widen the selection |
| `ship-workflow` is not installed when landing or cleanup is requested | Stop `BLOCKED` naming `ship-workflow` |
| Delegation returns `NEEDS_JUDGMENT` or `BLOCKED` | Relay actual confirmed facts and resolve the named topology/provenance/scope input here. Resume only its returned saved run; if none exists, repeat the original scoped invocation with the resolved packet, never bare `--resume`. |

## Output Format

Report:

1. Stack order with branch, parent, PR number or URL, state and native membership.
2. Mutations this skill performed, including PR creation, base edits, rebases and pushes.
3. Validation commands and exact pass/fail status.
4. For delegated landing or cleanup, the actual status, confirmed merges, retained dependents, cleanup dispositions and next action; include `run_id` only when returned and non-null.
5. Next safe action: fix validation, resolve a conflict, provide explicit branch order/scope, or resume its returned saved run. Receipt-free stops repeat the original scoped invocation after resolution.
