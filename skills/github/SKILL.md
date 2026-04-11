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

## Prerequisites and Auth

### Installation

| Platform      | Command                     |
| ------------- | --------------------------- |
| macOS         | `brew install gh`           |
| Debian/Ubuntu | `sudo apt install gh`       |
| Windows       | `winget install GitHub.cli` |

### Authentication

```bash
gh auth login           # interactive OAuth login
gh auth status          # check current auth and active account
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

## Reference Routing

| User intent                                                     | Load                                 |
| --------------------------------------------------------------- | ------------------------------------ |
| Create/list/view/edit/close issues, add comments                | `references/issues.md`               |
| Create/list/view/review/merge/edit/close pull requests          | `references/pull-requests.md`        |
| List runs, view logs, trigger/rerun/watch workflows, artifacts  | `references/ci-actions.md`           |
| Create/fork/clone/view/edit/archive/delete repositories         | `references/repos.md`                |
| Create/list/view/edit/upload/delete releases                    | `references/releases.md`             |
| Search repos, issues, PRs, code, commits                        | `references/search.md`               |
| Raw REST/GraphQL via `gh api`, pagination, rate limit           | `references/api.md`                  |
| GraphQL cost model, bulk queries, mutations, rate limits        | `references/graphql-queries.md`      |
| Multi-step workflow recipes (PR lifecycle, CI triage, releases) | `references/automation-workflows.md` |
| Create/list/view/edit/delete gists                              | `references/gists.md`                |
| List orgs, teams, members                                       | `references/orgs.md`                 |

## Workflow Pattern

1. Identify user intent from the routing table above.
2. Load the matching `references/<file>.md` for command syntax and examples.
3. Execute the `gh` command with `--repo owner/repo` and `--json`/`--jq` as needed.
4. On error, consult the Error Handling table below.

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

## Calibration Rules

1. **Prefer `--json` over parsing text output.** Text output formats are unstable across `gh` versions. Always use `--json field1,field2` to get machine-readable output.
2. **Use `--jq` to minimize output before processing.** Filter at the source rather than piping large JSON blobs to external tools. `--jq` runs server-side and reduces data transferred.
3. **Prefer higher-level commands over raw API.** Use `gh issue create` instead of `gh api repos/.../issues -X POST`. High-level commands handle auth, pagination, and error formatting automatically.
4. **Use `--repo` consistently when outside a git directory.** Never rely on implicit repo detection in scripts or CI environments. Always pass `--repo owner/repo` explicitly.
5. **Use GraphQL only for nested or bulk data.** For single-resource fetches and mutations with simple payloads, REST is faster to write, easier to debug, and predictable under rate limits.

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
