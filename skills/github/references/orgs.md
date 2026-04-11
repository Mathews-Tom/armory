# Organizations and Teams

GitHub org and team operations via `gh org` and `gh api` — list orgs, members, teams.

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
