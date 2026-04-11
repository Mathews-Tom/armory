---
name: engineering-retro
description: 'Git-based engineering retrospective analyzing commits, PRs, and velocity over configurable windows with monorepo path scoping. Triggers on: "retrospective", "sprint retro", "weekly review", "what did we ship", "engineering retro", "dev summary", "commit analysis".'
metadata:
  version: 1.0.1
  category: review
  tags: [retrospective, velocity, git-analysis, sprint]
  difficulty: intermediate
  phase: ship
---

# Engineering Retrospective

Generate a structured, git-based engineering retrospective for a configurable time window. This is a **read-only analysis** — no files are modified except the optional JSON snapshot.

## Arguments

```
/engineering-retro [TIME_WINDOW] [PATH_SCOPE]
```

- **TIME_WINDOW** (optional): `24h`, `7d` (default), `14d`, `30d`
- **PATH_SCOPE** (optional): restrict analysis to a subdirectory (monorepo support), e.g. `services/api`

Examples:

- `/engineering-retro` — last 7 days, full repo
- `/engineering-retro 30d` — last 30 days, full repo
- `/engineering-retro 14d services/api` — last 14 days, scoped to `services/api/`

## Execution Steps

### Step 1: Environment Detection

Detect runtime context before any analysis:

```bash
# Default branch
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
if [ -z "$DEFAULT_BRANCH" ]; then
  DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}')
fi

# System timezone
TZ_NAME=$(date +%Z)

# Time window — convert argument to --since format
# 24h → "24 hours ago", 7d → "7 days ago", 14d → "14 days ago", 30d → "30 days ago"
```

If `DEFAULT_BRANCH` detection fails, abort with an error — do not guess.

### Step 2: Gather Raw Git Data

Collect commits within the time window on the detected default branch:

```bash
# All commits in window (with optional path scope)
git log origin/$DEFAULT_BRANCH --since="$SINCE" --format="%H|%aI|%aN|%s" -- $PATH_SCOPE

# Diff stats for the window
git log origin/$DEFAULT_BRANCH --since="$SINCE" --numstat --format="%H" -- $PATH_SCOPE
```

Capture: commit hash, author date (ISO), author name, subject line, files changed, insertions, deletions.

### Step 3: Compute Aggregate Metrics

From the raw data, compute:

- **Total commits** in window
- **Unique contributors** (distinct author names)
- **Files changed** (unique file paths across all commits)
- **Lines added** (sum of insertions)
- **Lines removed** (sum of deletions)
- **Net delta** (added - removed)
- **Avg commit size** (total lines changed / total commits)

### Step 4: Time Distribution

Analyze commit timestamps (converted to system timezone `$TZ_NAME`):

- **Commits by day of week**: Mon-Sun histogram
- **Commits by hour**: 0-23 histogram
- **Peak day**: day with most commits
- **Peak hours**: hours with most activity

Present as a compact text histogram.

### Step 5: Session Analysis

Group commits into work sessions using a >2 hour gap as a session boundary:

1. Sort commits by author and timestamp
2. For each author, iterate chronologically — if gap between consecutive commits exceeds 2 hours, start a new session
3. Compute per-session: duration (first commit to last commit), commit count
4. Aggregate: total sessions, average session length, longest session, average commits per session

Sessions with a single commit get a default duration of 0 (point-in-time).

### Step 6: Commit Type Classification

Classify each commit using conventional commit prefixes from the subject line:

| Prefix pattern                      | Category |
| ----------------------------------- | -------- |
| `feat:`, `feat(`                    | feature  |
| `fix:`, `fix(`, `bugfix`            | fix      |
| `refactor:`, `refactor(`            | refactor |
| `chore:`, `chore(`, `build:`, `ci:` | chore    |
| `docs:`, `doc:`                     | docs     |
| `test:`, `tests:`                   | test     |
| `perf:`                             | perf     |
| `style:`                            | style    |

For commits without conventional prefixes, apply diff heuristics:

- Primarily new files added → feature
- Primarily deletions → refactor
- Test files only → test
- Config/CI files only → chore
- Documentation files only → docs
- Otherwise → uncategorized

Report counts and percentages per category.

### Step 7: Hotspot Analysis

Identify the **top 10 most-modified files** by number of commits touching them:

```bash
git log origin/$DEFAULT_BRANCH --since="$SINCE" --name-only --format="" -- $PATH_SCOPE | sort | uniq -c | sort -rn | head -20
```

Flag any file modified in **>50% of total commits** as a hotspot. Hotspots indicate:

- Active area of development (expected during feature work)
- Potential coupling issues (if unrelated commits keep touching the same file)
- Possible need for decomposition (if the file is large)

### Step 8: PR Analysis

If the remote is GitHub (check `git remote get-url origin` for `github.com`):

```bash
# Merged PRs in window
gh pr list --state merged --base $DEFAULT_BRANCH --search "merged:>=$SINCE_DATE" --json number,title,author,mergedAt,additions,deletions,changedFiles,reviews
```

Compute:

- **Total merged PRs**
- **Size distribution**: S (<50 lines), M (50-200), L (200-500), XL (>500)
- **Review turnaround**: time from PR creation to first review (median, p90)
- **Merge turnaround**: time from PR creation to merge (median, p90)

If not a GitHub remote or `gh` is unavailable, skip this step and note it in the output.

### Step 9: Focus Score

Compute the ratio of **focused commits** (touching 3 or fewer files) to total commits:

```
focus_score = commits_touching_le_3_files / total_commits
```

Interpretation:

- **>0.8**: highly focused, small incremental changes
- **0.5-0.8**: moderate focus, mix of targeted and broad changes
- **<0.5**: broad changes dominating, may indicate large refactors or low commit discipline

### Step 10: Per-Author Breakdown

For each contributor, report:

- Commit count
- Lines added / removed
- Top 3 most-touched files
- Primary commit types (from Step 6)
- Number of sessions and average session length (from Step 5)

Frame this as **contributor highlights** — recognition of work done, not a ranking or performance metric. Order alphabetically by author name.

### Step 11: Week-over-Week Comparison

Check for a prior snapshot in `.engineering-retros/`:

- Find the most recent `*.json` file
- If it exists and covers the adjacent prior window, compute deltas:
  - Commit count delta (%)
  - Lines changed delta (%)
  - Contributor count delta
  - Focus score delta
  - Category distribution shift

If no prior snapshot exists, note this is the first retrospective and skip comparison.

### Step 12: Save Snapshot

Save a JSON snapshot for future comparisons:

```
.engineering-retros/<YYYY-MM-DD>.json
```

Schema:

```json
{
  "date": "YYYY-MM-DD",
  "window": "7d",
  "path_scope": null,
  "branch": "main",
  "timezone": "PST",
  "metrics": {
    "commits": 0,
    "contributors": 0,
    "files_changed": 0,
    "lines_added": 0,
    "lines_removed": 0,
    "net_delta": 0,
    "focus_score": 0.0
  },
  "categories": {},
  "hotspots": [],
  "sessions": {
    "total": 0,
    "avg_length_minutes": 0
  },
  "authors": {},
  "pr_stats": null
}
```

Create the `.engineering-retros/` directory if it does not exist. Ensure `.engineering-retros/` is in `.gitignore` (add it if missing — this is the one permitted file modification).

### Step 13: Generate Narrative Summary

Produce the final output in this structure:

---

**Engineering Retrospective — [DATE_RANGE] ([TIMEZONE])**
**Branch:** [DEFAULT_BRANCH] | **Scope:** [PATH_SCOPE or "full repo"]

#### Metrics

- Commits: N | Contributors: N | Files changed: N
- Lines: +N / -N (net: +/-N)
- Avg commit size: N lines | Focus score: N.NN

#### Time Patterns

- Peak day: [DAY] | Peak hours: [RANGE]
- [compact histogram]
- Sessions: N total | Avg length: Nm | Longest: Nm

#### Work Breakdown

- [category]: N commits (NN%)
- ...

#### Hotspots

- `path/to/file` — N commits [HOTSPOT if >50%]
- ...

#### Contributor Highlights

- **[Author]**: N commits, +N/-N lines, focused on [top files], primarily [categories]
- ...

#### PR Summary (if available)

- Merged: N | Size dist: S/M/L/XL | Median review turnaround: Xh

#### Week-over-Week (if available)

- Commits: +/-N% | Lines: +/-N% | Focus: +/-N.NN

#### Observations

- [2-4 bullet points identifying patterns, achievements, and areas worth attention]
- Based on data only — no speculation about intent or quality judgments about individuals

---

## Constraints

- **Read-only**: no code modifications, no branch changes, no git operations that alter state
- **No hardcoded timezone**: always detect from `date +%Z`
- **No hardcoded branch**: always detect dynamically via `git symbolic-ref` or `git remote show`
- **No individual performance judgments**: author breakdown is for recognition, not evaluation
- **Path scope respected**: all git commands must include `-- $PATH_SCOPE` when a scope is provided
- **Snapshot storage**: `.engineering-retros/` only, never `.context/retros/`
