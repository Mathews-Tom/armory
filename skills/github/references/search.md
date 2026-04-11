# Search

GitHub search operations via `gh search` — repos, issues, PRs, code, and commits.

## Repositories

```bash
gh search repos "rate limiter language:go" --limit 10 --json fullName,description,stargazersCount \
  --jq '.[] | "\(.stargazersCount) \(.fullName): \(.description)"'
```

## Issues

```bash
gh search issues "memory leak is:open repo:owner/repo" --json number,title,url \
  --jq '.[] | "#\(.number) \(.title)"'
```

## Pull Requests

```bash
gh search prs "review:approved is:merged repo:owner/repo" --json number,title,mergedAt \
  --jq '.[] | "\(.number) \(.mergedAt) \(.title)"'
```

## Code

```bash
gh search code "func RateLimit repo:owner/repo" --json path,repository \
  --jq '.[] | "\(.repository.fullName) \(.path)"'
```

## Commits

```bash
gh search commits "fix timeout repo:owner/repo" --json sha,commit \
  --jq '.[] | "\(.sha[:8]) \(.commit.message | split("\n") | .[0])"'
```
