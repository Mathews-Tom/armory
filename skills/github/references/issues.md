# Issues

GitHub issue operations via `gh issue` — create, list, view, edit, close, and comment.

## Create

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

## List and Filter

```bash
gh issue list --repo owner/repo --state open --label "bug" --assignee "@me" --limit 20
```

Structured output with JSON:

```bash
gh issue list --repo owner/repo --json number,title,labels,assignees \
  --jq '.[] | "\(.number) [\(.labels | map(.name) | join(","))] \(.title)"'
```

## View, Edit, Close

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

## Comments

Add a comment to an issue:

```bash
gh issue comment 42 --repo owner/repo --body "Reproduced on v2.0.3. Stack trace attached."
```
