# Pull Requests

GitHub pull request operations via `gh pr` — create, list, view, review, merge, and edit.

## Create

Standard PR from current branch:

```bash
gh pr create --repo owner/repo --title "Add rate limiter middleware" --body "Implements token bucket at 100 req/min"
```

Draft PR with reviewers:

```bash
gh pr create --repo owner/repo \
  --title "Refactor auth module" \
  --body "Splits monolithic auth into JWT and session submodules" \
  --draft \
  --reviewer "reviewer1,reviewer2" \
  --label "refactor"
```

Auto-fill title and body from commit messages:

```bash
gh pr create --repo owner/repo --fill
```

Create PR targeting a specific base branch:

```bash
gh pr create --repo owner/repo --base develop --head feature/rate-limiter --fill
```

## List and Filter

```bash
gh pr list --repo owner/repo --state open --author "@me" --label "needs-review"
```

JSON output with review status:

```bash
gh pr list --repo owner/repo --json number,title,reviewDecision,statusCheckRollup \
  --jq '.[] | "\(.number) \(.reviewDecision // "PENDING") \(.title)"'
```

## View and Review

View PR details including diff stats:

```bash
gh pr view 55 --repo owner/repo
```

View the diff:

```bash
gh pr diff 55 --repo owner/repo
```

Approve a PR:

```bash
gh pr review 55 --repo owner/repo --approve --body "LGTM — tests pass, no security concerns"
```

Request changes:

```bash
gh pr review 55 --repo owner/repo --request-changes --body "Missing input validation on the upload handler"
```

Add a review comment without approving or requesting changes:

```bash
gh pr review 55 --repo owner/repo --comment --body "Consider caching the config lookup"
```

## Merge

Merge with default strategy:

```bash
gh pr merge 55 --repo owner/repo
```

Squash merge and delete branch:

```bash
gh pr merge 55 --repo owner/repo --squash --delete-branch
```

Rebase merge:

```bash
gh pr merge 55 --repo owner/repo --rebase
```

Auto-merge when CI passes:

```bash
gh pr merge 55 --repo owner/repo --auto --squash
```

## CI Status

Check CI status on a PR:

```bash
gh pr checks 55 --repo owner/repo
```

Watch CI and block until all checks complete:

```bash
gh pr checks 55 --repo owner/repo --watch
```

## Edit, Ready, Close

Mark a draft PR as ready for review:

```bash
gh pr ready 55 --repo owner/repo
```

Edit PR metadata:

```bash
gh pr edit 55 --repo owner/repo --add-reviewer "reviewer3" --add-label "urgent"
```

Close a PR without merging:

```bash
gh pr close 55 --repo owner/repo --comment "Superseded by #60"
```
