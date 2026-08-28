# Provider Adapters

Package names stay provider-neutral. Provider-specific behavior lives behind an adapter contract.

## Adapter Contract

| Operation | Inputs | Output |
| --- | --- | --- |
| `list_prs` | repository | PR number, title, head branch, base branch, state, URL |
| `create_pr` | head branch, base branch, title, body file | PR URL and number |
| `edit_base` | PR number, base branch | Updated PR metadata |
| `checks` | PR number or branch | Check conclusions |
| `merge_pr` | PR number, merge method | Merged state |
| `delete_remote_branch` | branch | Deletion result |

## GitHub Adapter

Require `gh` to be installed and authenticated before provider mutation.

List open PRs:

```bash
gh pr list --state open --json number,title,headRefName,baseRefName,state,url
```

Create a PR against its parent:

```bash
gh pr create \
  --base <parent-branch> \
  --head <branch> \
  --title "<title>" \
  --body-file <generated-body-file>
```

Retarget a PR:

```bash
gh pr edit <number> --base <parent-branch>
```

View checks:

```bash
gh pr checks <number>
```

Watch current PR checks:

```bash
gh pr checks <number> --watch --fail-fast
```

When using `gh pr view --json statusCheckRollup`, filter results to the current head SHA. Retargeting and rebasing can leave duplicate historical check runs in rollup output.

Find child PRs that still use a branch as their base:

```bash
gh pr list --state open --json number,baseRefName,headRefName \
  --jq '.[] | select(.baseRefName == "<branch-being-merged>")'
```

Merge a root PR:

```bash
gh api repos/{owner}/{repo} \
  --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'
gh pr merge <number> --merge
```

Prefer `--merge` when merge commits are allowed. If the repository squashes and `squash_merge_commit_message` is `PR_BODY` or `BLANK` (`gh api repos/{owner}/{repo} --jq '.squash_merge_commit_message'`), use the squash-body merge path in `references/provenance.md` so `Stack-Id` and `Stack-Position` survive in history. Under `COMMIT_MESSAGES` (GitHub's default), squash already preserves trailers automatically.

Do not use `--delete-branch` while any open PR still has the branch being merged as `baseRefName`. For GitHub stacks, branch deletion can close descendant PRs unmerged when their base branch disappears.

Delete a remote stack branch only after provider-confirmed merge and after no open PR targets it as a base:

```bash
gh pr list --state open --json number,baseRefName,headRefName \
  --jq '.[] | select(.baseRefName == "<merged-stack-branch>")'
git push origin --delete <branch>
```

## PR Body Stack Section

Every generated or updated stack PR body must include:

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

- `uv run pytest tests/parser`: passed
```

Regenerate the stack section after publish, sync, retarget, or merge.

## Provider Stop Conditions

- Provider CLI is missing or not authenticated.
- Existing PR is closed and unmerged.
- Provider rejects changing a PR base.
- Required checks fail.
- Branch protection prevents merge.
- An open child PR still targets a branch selected for deletion.
- Provider reports branch deletion failure after merge.

Do not retry by changing topology. Report the provider error and the exact command that failed.
