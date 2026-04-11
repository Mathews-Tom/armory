---
name: github
description: 'GitHub CLI operations via `gh` for issues, PRs, Actions, releases, and REST/GraphQL API with `--json`/`--jq` parsing. Triggers on: "create an issue", "submit a PR", "check CI status", "why did CI fail", "merge a PR", or pasted GitHub URLs.'
metadata:
  version: 1.1.1
  category: review
  tags: [github, cli, issues, pull-requests]
  difficulty: intermediate
---

# GitHub

All GitHub operations use the `gh` CLI. Prefer `--json` with `--jq` for structured,
parseable output. Use `--repo owner/repo` when not inside a git repository with a
configured remote. Use `--web` to open any resource in the browser.

| Reference File                       | Purpose                                                                      |
| ------------------------------------ | ---------------------------------------------------------------------------- |
| `references/graphql-queries.md`      | GraphQL query patterns, cost model, mutations, rate limit inspection         |
| `references/automation-workflows.md` | Multi-step workflow recipes for CI triage, PR lifecycle, releases, batch ops |

---

## Prerequisites and Auth

### Installation

| Platform      | Command                     |
| ------------- | --------------------------- |
| macOS         | `brew install gh`           |
| Debian/Ubuntu | `sudo apt install gh`       |
| Windows       | `winget install GitHub.cli` |

### Authentication

Log in interactively (opens browser for OAuth):

```bash
gh auth login
```

Check current auth status and active account:

```bash
gh auth status
```

### Required OAuth Scopes

| Scope         | Grants Access To                             |
| ------------- | -------------------------------------------- |
| `repo`        | Private repos, issues, PRs, commits, status  |
| `read:org`    | Org membership, team listing                 |
| `workflow`    | Trigger and manage GitHub Actions workflows  |
| `gist`        | Create and manage gists                      |
| `delete_repo` | Delete repositories (not granted by default) |
| `admin:org`   | Manage org settings, teams, members          |
| `project`     | Read/write access to ProjectV2 boards        |

Add missing scopes without re-authenticating from scratch:

```bash
gh auth refresh --scopes repo,read:org,workflow
```

---

## Issues

### Create

```bash
gh issue create --repo owner/repo --title "Login timeout on slow connections" --body "Users on 3G see a 504 after 8 seconds"
```

Create with labels, assignees, and milestone:

```bash
gh issue create --repo owner/repo \
  --title "Add rate limiting to /api/upload" \
  --body "Current endpoint has no throttle. Target: 100 req/min per user." \
  --label "enhancement,backend" \
  --assignee "username1,username2" \
  --milestone "v2.1"
```

| Flag          | Purpose                                      |
| ------------- | -------------------------------------------- |
| `--title`     | Issue title (required unless `--fill` used)  |
| `--body`      | Issue body in markdown                       |
| `--label`     | Comma-separated label names                  |
| `--assignee`  | Comma-separated GitHub usernames             |
| `--milestone` | Milestone name                               |
| `--project`   | Project board name                           |
| `--web`       | Open the new issue in browser after creation |

### List and Filter

```bash
gh issue list --repo owner/repo --state open --label "bug" --assignee "@me" --limit 20
```

Structured output with JSON:

```bash
gh issue list --repo owner/repo --json number,title,labels,assignees \
  --jq '.[] | "\(.number) [\(.labels | map(.name) | join(","))] \(.title)"'
```

### View, Edit, Close

View issue details:

```bash
gh issue view 42 --repo owner/repo
```

View with comments:

```bash
gh issue view 42 --repo owner/repo --comments
```

Edit an existing issue:

```bash
gh issue edit 42 --repo owner/repo --add-label "priority:high" --add-assignee "username"
```

Close an issue with a comment:

```bash
gh issue close 42 --repo owner/repo --comment "Fixed in PR #87"
```

### Comments

Add a comment to an issue:

```bash
gh issue comment 42 --repo owner/repo --body "Reproduced on v2.0.3. Stack trace attached."
```

---

## Pull Requests

### Create

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

### List and Filter

```bash
gh pr list --repo owner/repo --state open --author "@me" --label "needs-review"
```

JSON output with review status:

```bash
gh pr list --repo owner/repo --json number,title,reviewDecision,statusCheckRollup \
  --jq '.[] | "\(.number) \(.reviewDecision // "PENDING") \(.title)"'
```

### View and Review

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

### Merge

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

### CI Status

Check CI status on a PR:

```bash
gh pr checks 55 --repo owner/repo
```

Watch CI and block until all checks complete:

```bash
gh pr checks 55 --repo owner/repo --watch
```

### Edit, Ready, Close

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

---

## CI / Actions

### List Workflow Runs

```bash
gh run list --repo owner/repo --limit 10
```

Filter by workflow name and branch:

```bash
gh run list --repo owner/repo --workflow "CI" --branch main --status failure --limit 5
```

JSON output:

```bash
gh run list --repo owner/repo --json databaseId,status,conclusion,headBranch,name \
  --jq '.[] | "\(.databaseId) \(.status) \(.conclusion // "running") \(.headBranch)"'
```

### View Run Details

```bash
gh run view 123456789 --repo owner/repo
```

View logs for failed steps only:

```bash
gh run view 123456789 --repo owner/repo --log-failed
```

View full logs:

```bash
gh run view 123456789 --repo owner/repo --log
```

### Trigger and Rerun

Trigger a workflow manually:

```bash
gh workflow run deploy.yml --repo owner/repo --ref main -f environment=staging
```

Rerun only the failed jobs in a run:

```bash
gh run rerun 123456789 --repo owner/repo --failed
```

Rerun the entire run:

```bash
gh run rerun 123456789 --repo owner/repo
```

### Watch a Run

Stream live status updates until the run completes:

```bash
gh run watch 123456789 --repo owner/repo
```

### Enable and Disable Workflows

```bash
gh workflow disable "Nightly Build" --repo owner/repo
gh workflow enable "Nightly Build" --repo owner/repo
```

### Download Artifacts

```bash
gh run download 123456789 --repo owner/repo --name "build-output"
```

Download all artifacts from a run:

```bash
gh run download 123456789 --repo owner/repo
```

---

## Repositories

### Create

Create a new public repository:

```bash
gh repo create owner/new-repo --public --description "Service for handling webhooks"
```

Create from a template:

```bash
gh repo create owner/new-service --template owner/service-template --public --clone
```

### Fork and Clone

```bash
gh repo fork owner/repo --clone
gh repo clone owner/repo
```

### View and List

```bash
gh repo view owner/repo
gh repo view owner/repo --json name,description,defaultBranchRef --jq '.defaultBranchRef.name'
```

List repos in an org:

```bash
gh repo list some-org --limit 50 --json name,isArchived \
  --jq '.[] | select(.isArchived == false) | .name'
```

### Edit Settings

```bash
gh repo edit owner/repo --description "Updated description" --enable-issues --enable-wiki=false
```

### Archive and Delete

```bash
gh repo archive owner/repo --yes
gh repo delete owner/repo --yes
```

---

## Releases

### Create

Create a release with auto-generated notes:

```bash
gh release create v1.2.0 --repo owner/repo --generate-notes
```

Create with title, notes, and binary assets:

```bash
gh release create v1.2.0 --repo owner/repo \
  --title "v1.2.0 — Rate Limiter" \
  --notes "Adds token bucket rate limiting to all API endpoints" \
  ./dist/app-linux-amd64 ./dist/app-darwin-arm64
```

Create a prerelease:

```bash
gh release create v2.0.0-rc1 --repo owner/repo --prerelease --generate-notes
```

### List and View

```bash
gh release list --repo owner/repo --limit 5
gh release view v1.2.0 --repo owner/repo
```

### Edit and Upload Assets

```bash
gh release edit v1.2.0 --repo owner/repo --draft=false --prerelease=false
```

Upload additional assets to an existing release:

```bash
gh release upload v1.2.0 --repo owner/repo ./dist/app-windows-amd64.exe
```

### Delete

```bash
gh release delete v1.0.0-beta --repo owner/repo --yes
```

---

## Search

### Repositories

```bash
gh search repos "rate limiter language:go" --limit 10 --json fullName,description,stargazersCount \
  --jq '.[] | "\(.stargazersCount) \(.fullName): \(.description)"'
```

### Issues

```bash
gh search issues "memory leak is:open repo:owner/repo" --json number,title,url \
  --jq '.[] | "#\(.number) \(.title)"'
```

### Pull Requests

```bash
gh search prs "review:approved is:merged repo:owner/repo" --json number,title,mergedAt \
  --jq '.[] | "\(.number) \(.mergedAt) \(.title)"'
```

### Code

```bash
gh search code "func RateLimit repo:owner/repo" --json path,repository \
  --jq '.[] | "\(.repository.fullName) \(.path)"'
```

### Commits

```bash
gh search commits "fix timeout repo:owner/repo" --json sha,commit \
  --jq '.[] | "\(.sha[:8]) \(.commit.message | split("\n") | .[0])"'
```

---

## API: REST and GraphQL

### REST: GET

```bash
gh api repos/owner/repo/pulls/55 --jq '{title: .title, state: .state, author: .user.login}'
```

### REST: POST

```bash
gh api repos/owner/repo/issues/42/comments -f body="Automated comment from CI triage"
```

### REST: PATCH

```bash
gh api repos/owner/repo/issues/42 -X PATCH -f state="closed"
```

### Pagination

Paginate through all results automatically:

```bash
gh api repos/owner/repo/issues --paginate --jq '.[].number'
```

### Rate Limit Check

```bash
gh api rate_limit --jq '{core: .resources.core, graphql: .resources.graphql}'
```

### GraphQL Queries

Inline GraphQL query:

```bash
gh api graphql -f query='
  query {
    repository(owner: "owner", name: "repo") {
      issues(first: 5, states: OPEN) {
        nodes {
          number
          title
        }
      }
    }
  }
' --jq '.data.repository.issues.nodes[] | "\(.number) \(.title)"'
```

See `references/graphql-queries.md` for cost model, bulk queries, mutations, and rate
limit management patterns.

### REST vs GraphQL Decision Table

| Scenario                                       | Use             | Reason                                                  |
| ---------------------------------------------- | --------------- | ------------------------------------------------------- |
| Fetch a single resource (one PR, one issue)    | REST (`gh api`) | Simple, predictable, low overhead                       |
| Fetch nested or related data in one round-trip | GraphQL         | Avoids N+1 requests; select only needed fields          |
| Bulk operations across many resources          | GraphQL         | Query complexity points are cheaper than REST calls     |
| Creating or updating a resource (mutation)     | Either          | REST: `-X POST/PATCH`; GraphQL: `mutation {}` block     |
| Rate-limit-sensitive pipeline or script        | REST            | REST has a simple 5000 req/hr counter; easier to budget |
| ProjectV2 board operations                     | GraphQL         | ProjectV2 has no REST API; GraphQL only                 |

---

## Inline Workflow Examples

### PR Lifecycle

```bash
# 1. Create a draft PR from the current branch
gh pr create --repo owner/repo --title "Add rate limiter" --body "Token bucket at 100 req/min" --draft

# 2. Check CI status on the PR
gh pr checks 55 --repo owner/repo --watch

# 3. Mark ready once CI passes
gh pr ready 55 --repo owner/repo

# 4. Approve the PR
gh pr review 55 --repo owner/repo --approve --body "LGTM"

# 5. Squash-merge and delete branch
gh pr merge 55 --repo owner/repo --squash --delete-branch
```

See `references/automation-workflows.md` for the full lifecycle with label management and reviewer rotation.

### CI Triage

```bash
# 1. Find the latest failed run on main
gh run list --repo owner/repo --branch main --status failure --limit 1 --json databaseId --jq '.[0].databaseId'

# 2. View failed step logs (substitute run ID from step 1)
gh run view 123456789 --repo owner/repo --log-failed

# 3. Rerun only failed jobs
gh run rerun 123456789 --repo owner/repo --failed

# 4. Watch until complete
gh run watch 123456789 --repo owner/repo
```

See `references/automation-workflows.md` for batch triage across multiple branches and failure pattern analysis.

---

## Error Handling

| Error                         | Cause                                                                     | Resolution                                                                        |
| ----------------------------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| HTTP 401 Unauthorized         | Token expired or revoked                                                  | Run `gh auth login` to re-authenticate                                            |
| HTTP 403 Forbidden            | Insufficient permissions or rate limited                                  | Check `gh auth status` for scopes; check `gh api rate_limit`                      |
| HTTP 404 Not Found            | Repo does not exist, is private without `repo` scope, or resource deleted | Verify repo name; run `gh auth refresh --scopes repo`                             |
| HTTP 422 Unprocessable Entity | Invalid payload — missing required field, validation error                | Check request body fields match API schema                                        |
| HTTP 429 Too Many Requests    | REST rate limit exceeded (5000 req/hr authenticated)                      | Wait for `X-RateLimit-Reset` timestamp; reduce request frequency                  |
| GraphQL rate limit exceeded   | Used more than 5000 points/hr                                             | Reduce query complexity or wait; see `references/graphql-queries.md`              |
| "no git remotes found"        | Running `gh` outside a git repo without `--repo`                          | Add `--repo owner/repo` to the command                                            |
| Insufficient OAuth scopes     | Token lacks required scope for the operation                              | Run `gh auth refresh --scopes scope1,scope2`                                      |
| Duplicate issue/PR title      | Not a real error — GitHub allows duplicates, but check before creating    | Search with `gh issue list` or `gh pr list` first                                 |
| Archived repo blocks writes   | Repo is archived; all write operations fail                               | Unarchive with `gh repo edit owner/repo --archived=false` or use a different repo |

Enable debug logging to see raw HTTP requests and responses:

```bash
GH_DEBUG=api gh pr list --repo owner/repo
```

---

## Gists

### Create

Create a public gist from a file:

```bash
gh gist create --public --desc "Rate limiter implementation" rate_limiter.py
```

Create from stdin:

```bash
echo '{"key": "value"}' | gh gist create --filename config.json
```

### List, View, Edit, Delete

```bash
gh gist list --limit 10
gh gist view abc123def456
gh gist edit abc123def456 --add new_file.py
gh gist delete abc123def456
```

## Organizations and Teams

List orgs for the authenticated user:

```bash
gh org list
```

List org members with pagination:

```bash
gh api orgs/some-org/members --paginate --jq '.[].login'
```

List teams in an org:

```bash
gh api orgs/some-org/teams --paginate --jq '.[] | "\(.slug): \(.description)"'
```

List members of a specific team:

```bash
gh api orgs/some-org/teams/backend-team/members --paginate --jq '.[].login'
```

---

## Limitations

- **Network required** — all `gh` commands require internet access; no offline mode.
- **GraphQL point budget** — 5000 points/hr for authenticated users. Complex queries with
  high `first`/`last` values consume points faster. See `references/graphql-queries.md`.
- **Secrets are write-only** — `gh secret set` works, but there is no `gh secret get`.
  Secret values cannot be retrieved after creation.
- **Org admin operations** — managing org settings, teams, and SAML requires the `admin:org`
  scope, which is not granted by default.
- **Artifact retention** — workflow artifacts are retained for 90 days by default. Expired
  artifacts cannot be downloaded.

---

## Calibration Rules

1. **Prefer `--json` over parsing text output.** Text output formats are unstable across `gh` versions. Always use `--json field1,field2` to get machine-readable output.
2. **Use `--jq` to minimize output before processing.** Filter at the source rather than piping large JSON blobs to external tools. `--jq` runs server-side and reduces data transferred.
3. **Prefer higher-level commands over raw API.** Use `gh issue create` instead of `gh api repos/.../issues -X POST`. High-level commands handle auth, pagination, and error formatting automatically.
4. **Use `--repo` consistently when outside a git directory.** Never rely on implicit repo detection in scripts or CI environments. Always pass `--repo owner/repo` explicitly.
5. **Use GraphQL only for nested or bulk data.** For single-resource fetches and mutations with simple payloads, REST is faster to write, easier to debug, and predictable under rate limits.
