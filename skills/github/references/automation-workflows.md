# Automation Workflows

Multi-step recipes combining `gh` commands for common GitHub operations.

---

## 1. CI Triage

Diagnose and resolve failed CI runs.

**Step 1** — List recent failed runs on the default branch:

```bash
gh run list --repo owner/repo --branch main --status failure --limit 5
```

**Step 2** — View the failed run to identify which jobs failed:

```bash
gh run view 123456789 --repo owner/repo
```

**Step 3** — Pull logs for failed steps only:

```bash
gh run view 123456789 --repo owner/repo --log-failed
```

**Step 4** — Based on the failure, either rerun the failed jobs or create an issue:

Rerun failed jobs (for flaky tests or transient infra issues):

```bash
gh run rerun 123456789 --repo owner/repo --failed
```

Create an issue for a real failure:

```bash
gh issue create --repo owner/repo \
  --title "CI failure: timeout in integration test suite" \
  --body "Run 123456789 failed on main. Logs show connection timeout in test_database_integration. See: https://github.com/owner/repo/actions/runs/123456789" \
  --label "bug,ci"
```

**Step 5** — Watch the rerun to confirm it passes:

```bash
gh run watch 123456789 --repo owner/repo
```

---

## 2. Full PR Lifecycle

From branch creation through merge and issue closure.

**Step 1** — Create a draft PR:

```bash
gh pr create --repo owner/repo \
  --title "Add request validation middleware" \
  --body "Validates incoming JSON payloads against schema before handler execution. Closes #42." \
  --draft \
  --label "enhancement"
```

**Step 2** — Add reviewers:

```bash
gh pr edit 88 --repo owner/repo --add-reviewer "reviewer1,reviewer2"
```

**Step 3** — Watch CI checks:

```bash
gh pr checks 88 --repo owner/repo --watch
```

**Step 4** — Mark the PR as ready for review once CI passes:

```bash
gh pr ready 88 --repo owner/repo
```

**Step 5** — After receiving approval, squash merge and delete the branch:

```bash
gh pr merge 88 --repo owner/repo --squash --delete-branch
```

**Step 6** — Verify the linked issue was closed:

```bash
gh issue view 42 --repo owner/repo --json state --jq '.state'
```

---

## 3. Release Publishing

Tag, release, and attach binary artifacts.

**Step 1** — Ensure you are on the correct commit (the one to release):

```bash
gh api repos/owner/repo/git/ref/heads/main --jq '.object.sha'
```

**Step 2** — Create a release with auto-generated notes and binary uploads:

```bash
gh release create v1.3.0 --repo owner/repo \
  --title "v1.3.0" \
  --generate-notes \
  ./dist/app-linux-amd64 ./dist/app-darwin-arm64 ./dist/app-windows-amd64.exe
```

**Step 3** — Verify the release was created:

```bash
gh release view v1.3.0 --repo owner/repo
```

**Step 4** — Upload additional assets after the fact (e.g., checksums):

```bash
gh release upload v1.3.0 --repo owner/repo ./dist/checksums.txt
```

**Step 5** — If the release was created as a draft, publish it:

```bash
gh release edit v1.3.0 --repo owner/repo --draft=false
```

---

## 4. Issue Triage Batch

Label, assign, and close issues in bulk.

**Step 1** — Find unlabeled open issues:

```bash
gh issue list --repo owner/repo --state open --json number,title,labels \
  --jq '.[] | select(.labels | length == 0) | "\(.number) \(.title)"'
```

**Step 2** — Label issues in a loop (example: label issues 10, 11, 12 as "needs-triage"):

```bash
for issue_num in 10 11 12; do
  gh issue edit "$issue_num" --repo owner/repo --add-label "needs-triage"
done
```

**Step 3** — Assign a milestone to triaged issues:

```bash
for issue_num in 10 11 12; do
  gh issue edit "$issue_num" --repo owner/repo --milestone "v2.1"
done
```

**Step 4** — Find and close stale issues (no update in 90 days):

```bash
gh issue list --repo owner/repo --state open --json number,updatedAt \
  --jq '[.[] | select(.updatedAt < "2025-11-24T00:00:00Z")] | .[].number' \
  | while read -r issue_num; do
      gh issue close "$issue_num" --repo owner/repo --comment "Closing due to inactivity. Reopen if still relevant."
    done
```

---

## 5. Repo Bootstrap

Create a repository and configure it for team use.

**Step 1** — Create the repository:

```bash
gh repo create owner/new-service --public \
  --description "Webhook processing service" \
  --clone
```

**Step 2** — Create standard labels:

```bash
for label_spec in "bug:d73a4a" "enhancement:a2eeef" "documentation:0075ca" "priority:high:b60205" "priority:low:e4e669"; do
  name="${label_spec%%:*}"
  color="${label_spec##*:}"
  gh label create "$name" --repo owner/new-service --color "$color" 2>/dev/null || true
done
```

**Step 3** — Set branch protection on main via REST API:

```bash
gh api repos/owner/new-service/branches/main/protection -X PUT \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["ci/test", "ci/lint"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true
  },
  "restrictions": null
}
EOF
```

**Step 4** — Verify branch protection was applied:

```bash
gh api repos/owner/new-service/branches/main/protection --jq '{
  status_checks: .required_status_checks.contexts,
  required_reviews: .required_pull_request_reviews.required_approving_review_count,
  enforce_admins: .enforce_admins.enabled
}'
```

**Step 5** — Verify CI is configured by checking for workflow files:

```bash
gh api repos/owner/new-service/contents/.github/workflows --jq '.[].name'
```

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

See above in this file for the full lifecycle with label management and reviewer rotation.

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

See above in this file for batch triage across multiple branches and failure pattern analysis.
