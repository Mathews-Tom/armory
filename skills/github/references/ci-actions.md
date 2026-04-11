# CI / Actions

GitHub Actions operations via `gh run` and `gh workflow` — list runs, view logs, trigger, rerun, watch, and download artifacts.

## List Workflow Runs

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

## View Run Details

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

## Trigger and Rerun

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

## Watch a Run

Stream live status updates until the run completes:

```bash
gh run watch 123456789 --repo owner/repo
```

## Enable and Disable Workflows

```bash
gh workflow disable "Nightly Build" --repo owner/repo
gh workflow enable "Nightly Build" --repo owner/repo
```

## Download Artifacts

```bash
gh run download 123456789 --repo owner/repo --name "build-output"
```

Download all artifacts from a run:

```bash
gh run download 123456789 --repo owner/repo
```
