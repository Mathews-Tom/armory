---
name: stacked-prs
description: 'Manages dependent branch stacks and stacked pull requests using safe Git topology rules. Triggers on: "create stacked PRs", "publish this stack", "sync my PR stack", "rebase this stack", "merge the stack", "retarget child PRs", "split this branch into stacked PRs", "validate this stack", "cleanup stacked branches", or "GitHub native stack". Use when local branches or one source branch need a dependency-ordered PR stack with correct parent bases, validation, synchronization, merge order, cleanup, and optional GitHub-native stack support.'
metadata:
  version: 0.3.1
  category: development
  tags: [git, pull-requests, stacked-prs, github-native, workflow]
  difficulty: advanced
  phase: ship
---

# Stacked PRs

Build, publish, synchronize, validate, merge, and clean up stacked pull requests without corrupting branch topology.

The package identity is provider-neutral. Git is the source of truth for branch ancestry; provider PR metadata is the source of truth for review bases. GitHub through `gh` is the first documented provider adapter.

## Reference Files

| File | Contents | Load When |
| --- | --- | --- |
| `references/stack-model.md` | Stack inference, explicit ordering, and `.stack-prs.yaml` rules | Inspecting, publishing, validating, or cleaning a stack |
| `references/provider-adapters.md` | Provider adapter contract and GitHub `gh` commands | Creating, retargeting, checking, merging, or deleting PRs |
| `references/sync-algorithm.md` | Rebase and force-with-lease synchronization workflow | Syncing a stack after a parent or base moves |
| `references/merge-discipline.md` | Bottom-up merge and branch cleanup rules | Merging or closing out a stack |
| `references/metadata-format.md` | Optional metadata schema and validation rules | `.stack-prs.yaml` exists or inference is ambiguous |
| `references/provenance.md` | Commit-trailer stack identity, stamping, verification, merge-mode coupling | Creating, splitting, syncing, or merging any stack |
| `references/github-native.md` | Native detection, linking eligibility, guarded `merge-async` prefix merge, and manual fallback | A GitHub-native stack is requested or detected |

## When To Use

| Use this skill | Use another package |
| --- | --- |
| Multiple dependent branches need PRs against parent branches | `ship-workflow` for one independent release PR |
| A feature branch must be split into reviewable dependent branches | `task-decomposer` for planning tasks before code exists |
| An existing stack needs rebasing, retargeting, validation, or merge sequencing | `pr-review` for reviewing one PR diff |
| A stack must be cleaned after merge | General Git commands for unrelated branch cleanup |

## Core Rules

- Run `git rev-parse --show-toplevel` before any workflow.
- Run `git status --porcelain` before rebases, pushes, PR creation, PR retargeting, merge, or cleanup.
- Stop on a dirty worktree unless the user explicitly scopes the operation to inspection only.
- Prefer existing PR `baseRefName` values over inferred ancestry.
- Resolve `<base>` from the root PR's `baseRefName` (`gh pr view <root-pr> --json baseRefName --jq .baseRefName`), not from `origin/HEAD`; a stack's trunk need not be the repository's default branch.
- Use explicit branch order or `.stack-prs.yaml` when parent inference is ambiguous.
- Never use plain `git push --force`; use `git push --force-with-lease origin <branch>`.
- Merge from root to leaf. Never merge a child before its parent.
- Do not delete unmerged stack branches without explicit user instruction.
- Stamp `Stack-Id` and `Stack-Position` trailers on every commit the skill creates or splits; copy the ID from `.stack-prs.yaml` or mint it once when absent.
- Verify trailers are present and consistent before merge.
- Probe every open stack PR for native-stack membership during Inspect (`references/stack-model.md` § Native Stack Detection) before merge planning; a detected native stack makes the manual merge path in §5 unavailable, not merely discouraged.
- Detect the provider's squash message policy (`squash_merge_commit_message`) before merging with `--squash`. Fold trailers into the squash body only when the policy is `PR_BODY` or `BLANK`; under `COMMIT_MESSAGES` (GitHub's default) trailers already survive automatically.

## GitHub-native stack mode

GitHub-native stacks are same-repository-only. They enhance manual Armory
stacks; they do not replace provenance trailers, `.stack-prs.yaml`, or the
provider-neutral workflow.

Native-stack membership is a provider-side property of a pull request, not a
mode this skill chooses. Detect it for every stack PR during Inspect, before
any merge planning, whether or not `github-native` mode was requested: read
`.stack` from `GET repos/{owner}/{repo}/pulls/<number>` and the complete
ordered membership from `GET repos/{owner}/{repo}/stacks/<stack-number>`
(`references/github-native.md` § Detecting an already-native stack).

### Creating native state (opt-in)

Converting a manual stack to native with `gh stack link` is a provider
mutation. Use it only after these eligibility checks pass:

1. GitHub CLI plus `gh stack --help` succeeds; install `github/gh-stack` when absent.
2. Native stack support is enabled for the repository; native exit code 9 falls
   back to manual mode.
3. Every proposed head/base branch and pull request belongs to the same GitHub
   repository; reject forks and cross-repository stacks.
4. Existing PR bases, local branch order, and `Stack-Id`/`Stack-Position`
   provenance agree. Stop on disagreement.
5. The user explicitly requests native mode.

### Operating on an already-native stack (mandatory)

Once Inspect finds a PR already native, native mode is not a choice for any
operation that mutates that PR: the provider refuses a plain synchronous merge
mutation (`gh pr merge`, and the underlying `mergePullRequest`/`PUT
.../pulls/{n}/merge`) for a stack member with "must be merged using the
asynchronous merge REST API." There is no manual Armory merge path for an
already-native stack; do not present one as an alternative. Conditions 1-4
above still apply as safety checks; condition 5's user consent does not — the
provider already registered the stack as native.

This section is the manual provider procedure. Native members are never merged
by the ordinary single-PR path or by the manual graph path: no synchronous
merge, no per-member request, and no fallback to either.

When eligible or already native:

- Link existing branches or PRs bottom-to-top with
  `gh stack link --base <base> <branch-or-pr>...`.
- Inspect both Armory provenance and the GitHub-native stack position.
- Sync with `gh stack sync`; re-read `gh stack view` after every non-interactive
  sync and use `gh stack rebase` plus `gh stack push` for non-linear history.
- Merge only an explicitly authorized prefix: require the exact highest
  selected PR number. Never infer a prefix and never widen it implicitly; the
  provider operation includes every open member below the selected PR, so
  refuse when an open lower member is outside the authorization.
- Immediately before dispatch, re-read every member's head, base, checks and
  provenance and the stack base's merge policy. Route on the stack base:
  `merge_action=merge_queue` when it has a merge queue, `merge_action=direct_merge`
  when its policy is fully known without one, and stop as blocked when it
  cannot be read.
- Send exactly one `PUT repos/{owner}/{repo}/pulls/<highest>/merge-async` with
  `sha=<inspected head of <highest>>` and `bypass_rules=false`. `sha` guards
  only the selected head; lower members' heads are not checked by the server.
  A direct merge carries `merge_method`; a queue request omits
  `merge_method`, `commit_title` and `commit_message` (the provider refuses
  them with 422) and the queue rules choose the method.
- Never resend the request. An unknown outcome (timeout, transport failure) is
  reconciled from `GET .../pulls/<highest>/merge-async/<uuid>` and pull request
  states; a 409 returns the existing request, and an immediate 200 can mean
  already merged or already queued. `enqueued` is final for a queue request
  and never means merged; queue members can land in separate merge groups.
- Before choosing `merge_method=squash`, check `gh api repos/{owner}/{repo}
  --jq '.squash_merge_commit_message'`. Trailers survive automatically under
  `COMMIT_MESSAGES` (GitHub's default). Under `PR_BODY` they survive only if
  every PR body already carries them. Under `BLANK` they are always lost and
  Armory sends no `commit_title`/`commit_message` override — change the
  repository's policy first or merge directly with `merge_method=merge` or
  `rebase` instead. Under a merge queue, check the queue's method the same way.
- With `squash_merge_commit_title: COMMIT_OR_PR_TITLE` (GitHub's default), a
  PR squashing a single commit takes that commit's headline as the base-branch
  subject, not the PR title, and this cannot be corrected after merge without
  rewriting pushed history. When the visible subject matters for a
  single-commit PR under a squash, align the commit headline with the PR title
  first (`git commit --amend -m "<pr-title>"`, then force-with-lease push)
  before the merge request.
- Verify every selected member from its own pull request facts: `MERGED`, a landing reachable from the stack base, and a full landing tree equal to the clean three-way application of its reviewed own slice to the canonical-trunk base before that landing. A merged upper member keeps its review base (the lower member's branch); do not treat that as a contradiction or rewrite it.
- Verify every retained open member after GitHub's retarget and rebase: the lowest retained member is based on the stack base; each higher one is based on the retained member immediately below it and contains that member's current head. Verify each full rebased tree and exact own-slice identity against that placement. Then re-fetch and verify the remaining topology, CI and provenance.

Fall back to the manual workflow only when the stack is not yet native: the
creation checks fail, the stack spans a fork, native support is unavailable,
or provider/trailer topology differs. Never silently switch modes mid-stack,
and never attempt the manual merge path once Inspect has found the stack is
already native.

## Workflow

### 1. Inspect

Build a stack model without modifying anything:

```bash
git rev-parse --show-toplevel
git status --porcelain
git branch --show-current
git for-each-ref --format='%(refname:short)' refs/heads
git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'
gh pr list --state open --json number,title,headRefName,baseRefName,state,url
```

Produce a table with one row per stack branch. Run the native-stack probe
(`references/stack-model.md` § Native Stack Detection) for every PR before
recording this table:

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

Rebase each stack branch onto its parent after `<base>` or any parent branch moves:

```bash
git status --porcelain
git fetch origin --prune
git switch <branch>
git rebase <parent-branch>
git push --force-with-lease origin <branch>
```

Start at the first branch above the base and continue toward the leaf. Stop on conflicts, remote lease failures, or a parent PR that closed without merge.

### 4. Validate

Validate the stack as reviewable slices. Run cheap checks on every branch when practical; run expensive full checks on the leaf when branch-by-branch validation is not reasonable. Record exactly what ran in each PR body.

Use the target repository's detected local gate and provider checks. Do not run armory package-evaluation commands when operating on another repository's stack.

For this armory package implementation only, use:

```bash
uv run python scripts/validate_evals.py
uv run python scripts/generate_manifest.py
uv run python scripts/evaluate_package.py --path skills/stacked-prs
```

### 5. Merge

Before merging, confirm the Inspect native-stack probe reported `null` for
this PR. A non-null result means the provider already treats this stack as
native; `gh pr merge` will be rejected outright — stop here and follow the
GitHub-native guarded prefix merge above instead.

Merge root to leaf:

```bash
git log --format='%H %(trailers:key=Stack-Id,valueonly)' <parent>..<branch>
gh api repos/{owner}/{repo} \
  --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'
gh pr list --state open --json number,baseRefName,headRefName \
  --jq '.[] | select(.baseRefName == "<branch-being-merged>")'
gh pr merge <root-pr> --merge
git fetch origin --prune
git switch <child-branch>
git rebase origin/<base>
git push --force-with-lease origin <child-branch>
gh pr edit <child-pr> --base <base>
```

If merge commits are allowed, use `gh pr merge <pr> --merge`. If the
repository squashes and `squash_merge_commit_message` is `PR_BODY` or `BLANK`
(`gh api repos/{owner}/{repo} --jq '.squash_merge_commit_message'`), use the
squash-body path from `references/provenance.md` so the `Stack-Id` and
`Stack-Position` trailers land in the squash commit body. Under
`COMMIT_MESSAGES` (GitHub's default), squash already preserves trailers
automatically.

On GitHub, do not pass `--delete-branch` while any open PR still has the branch being merged as its `baseRefName`. Deleting a parent branch that is still a child PR base can close the child PR unmerged. Repeat for each child. Require trailer verification, parent checks, and provider merge confirmation before moving to the next branch.

### 6. Cleanup

After the stack lands:

```bash
git switch <base>
git pull --ff-only origin <base>
git fetch --prune origin
```

Delete local branches with merge-mode-appropriate proof. For a `--merge`
(merge-commit) landing, ancestry survives:

```bash
git branch --merged <base>
git branch -d <merged-stack-branch>
```

For a `--squash` or `--rebase` landing, the landed commit has no ancestry link
to the local branch: `git branch --merged <base>` never lists it and `git
branch -d` always refuses. Prove content equivalence instead:

```bash
git diff --quiet origin/<base> <merged-stack-branch>
git branch -D <merged-stack-branch>
```

A stale local branch predating a remote rebase can show diffs in files it
never touched; read `git diff --stat` for additions unique to the branch, not
merely for nonzero output, before trusting the comparison. When in doubt, use
`git cherry <base> <merged-stack-branch>` instead: no `+`-prefixed lines means
every commit already landed, and `-D` is safe.

Delete remote stack branches only after every stack PR has landed or been retargeted away from the branch:

```bash
gh pr list --state open --json number,baseRefName,headRefName \
  --jq '.[] | select(.baseRefName == "<merged-stack-branch>")'
git push origin --delete <merged-stack-branch>
```

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
| Closed unmerged child after parent branch deletion | Confirm the head branch and intended commit still exist, recreate the PR against `<base>` or the current merged parent, wait for checks, then continue |
| Rebase or cherry-pick conflict | Stop, report branch and conflicted files, do not continue children |
| Remote branch changed since fetch | Stop; do not retry without a fresh inspect |
| Failed validation | Record the failed command and stop merge or publish |
| Top split branch differs from source | Stop before PR creation and report remaining diff |
| Commit in stack range missing `Stack-Id` trailer | Stop; stamp via provenance backfill before merge |
| Trailer `Stack-Id` differs from `.stack-prs.yaml` | Stop; resolve canonical ID before mutation |
| PR is a detected native-stack member | Stop the manual merge path; use the GitHub-native guarded `merge-async` prefix merge, never `gh pr merge` |
| Squash repo with `PR_BODY`/`BLANK` message policy and trailers not present | Stop; use the squash-body merge path |
| Local branch fails its merge-mode-appropriate proof (unmerged per `git branch --merged <base>` under a merge-commit landing, or shows `+` commits under `git cherry <base> <branch>` for a squash/rebase landing) | Stop; do not force-delete without explicit user instruction |

## Recovery: Deleted Parent Branch Closed A Child PR

Use this only when a provider closed a child PR because its base branch was deleted during stack landing.

1. Confirm the closed PR is unmerged.
2. Confirm the closed PR's base branch was deleted by the parent merge or cleanup command.
3. Confirm the child head branch still exists on `origin`.
4. Confirm the child head commit is the intended stack slice.
5. Recreate the PR against `<base>` or the current merged parent.
6. Wait for required checks on the recreated PR.
7. Continue the root-to-leaf merge sequence.

## Output Format

Report:

1. Stack order with branch, parent, PR number or URL, and state.
2. Mutations performed, including PR creation, base edits, rebases, pushes, merges, or branch deletion.
3. Validation commands and exact pass/fail status.
4. Next safe action, usually merge root PR, fix validation, resolve conflict, or provide explicit branch order.
