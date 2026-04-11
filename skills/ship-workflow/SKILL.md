---
name: ship-workflow
description: 'Automated release pipeline: merges main, runs tests, pre-landing review, version bump, changelog, bisectable commits, and PR creation. Triggers on: "ship it", "release this", "prepare for release", "open a PR", "push and PR", "land this", "/ship-workflow".'
metadata:
  version: 1.0.1
  category: review
  tags: [release, ci-cd, pull-request, changelog]
  difficulty: intermediate
  phase: ship
---

# Ship Workflow

Automated release pipeline that takes a feature branch from working state to
merged PR. Executes a deterministic sequence of pre-flight checks, testing,
review, versioning, and PR creation — stopping immediately on any failure with
specific remediation instructions.

## Pipeline Overview

```
pre-flight → merge main → test → review → version bump → changelog → bisectable commits → push → PR
```

Each step has explicit stop conditions. The pipeline never auto-resolves ambiguity.

---

## Step 1: Pre-flight Checks

Run all three checks before proceeding:

1. **Not on default branch** — detect the default branch dynamically:

   ```bash
   git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'
   ```

   If the current branch matches: STOP. Instruct the user to create a feature branch.

2. **Clean working tree** — `git status --porcelain` must produce no output.
   If dirty: STOP. List the uncommitted files and instruct the user to commit or stash.

3. **Up-to-date with remote** — `git fetch origin` then compare local HEAD with
   `origin/<current-branch>`. If the remote is ahead: STOP. Instruct the user to
   pull or rebase.

If any check fails, STOP with the specific remediation instruction. Do not proceed.

---

## Step 2: Merge Default Branch

```bash
git fetch origin
git merge origin/<default-branch>
```

- If merge conflicts occur: STOP. Report the conflicting files. Do not auto-resolve.
- If clean: proceed.

---

## Step 3: Run Tests

Detect the test command from project configuration using `references/project-detection.md`:

| Indicator                           | Test Command                         |
| ----------------------------------- | ------------------------------------ |
| `Makefile` with `test` target       | `make test`                          |
| `package.json` with `test` script   | `<detected-pkg-manager> run test`    |
| `pyproject.toml` with pytest config | `uv run pytest` (or detected runner) |
| `Cargo.toml`                        | `cargo test`                         |
| `go.mod`                            | `go test ./...`                      |
| `Gemfile` + `Rakefile`              | `bundle exec rake test`              |

Detection order: check each indicator top-to-bottom; use the first match.

- If tests fail: STOP. Report the failure output. Do not proceed.
- If no test command detected: warn the user and ask whether to proceed without tests.

---

## Step 4: Pre-Landing Review

Invoke the `pre-landing-review` skill if available. Otherwise, perform a lightweight
diff review against the default branch:

```bash
git diff origin/<default-branch>...HEAD
```

Review the diff for:

- Obvious bugs or logic errors
- Security concerns (credentials, injection vectors)
- Missing error handling on new code paths

Classification:

- **CRITICAL** findings: STOP. Resolve before proceeding.
- **INFORMATIONAL** findings: note them for inclusion in the PR description. Proceed.

---

## Step 5: Version Bump

Detect the version strategy from project configuration using `references/project-detection.md`:

| Indicator                        | Version Location              |
| -------------------------------- | ----------------------------- |
| `VERSION` file                   | Update file contents directly |
| `package.json` `version` field   | Update the field              |
| `pyproject.toml` `version` field | Update the field              |
| `Cargo.toml` `version` field     | Update the field              |
| Git tags only                    | Create tag at push time       |

Default bump level: **PATCH**.

- For **MINOR** or **MAJOR** bumps: STOP. Confirm with the user before proceeding.
- If no version strategy detected: skip the version bump entirely. Note the skip in
  the PR description.

---

## Step 6: Update Changelog

- If `CHANGELOG.md` exists: prepend an entry in [Keep a Changelog](https://keepachangelog.com/) format.
- If no changelog file exists: skip.

Auto-generate the entry from commit messages since the last tag or release. Group
entries by conventional commit type:

```markdown
## [<new-version>] - <date>

### Added

- feat: ...

### Fixed

- fix: ...

### Changed

- refactor: ...
```

---

## Step 7: Create Bisectable Commits

Organize staged changes into logical, bisectable commit groups in this order:

1. **Infrastructure / config changes** — build files, CI config, dependencies
2. **Models / services / core logic** — domain layer, business rules
3. **Controllers / views / API endpoints** — presentation and routing
4. **Version bump + changelog** — always last

Each commit uses a descriptive conventional commit message. Each commit should pass
tests independently when possible (verify if CI turnaround allows it; otherwise trust
the ordering).

If all changes are already committed in a reasonable structure, skip reorganization.

---

## Step 8: Push and Create PR

```bash
git push -u origin <current-branch>
```

Create the PR:

```bash
gh pr create \
  --title "<conventional-format-title>" \
  --body "<generated-body>"
```

PR body includes:

- Summary of changes (grouped by commit)
- Test results (pass confirmation)
- Version bump details (old → new, or "skipped")
- Any INFORMATIONAL findings from Step 4

Output the PR URL as the final result.

---

## Stop Conditions

The pipeline halts immediately and reports when any of these occur:

| Condition                | Step | Action                                     |
| ------------------------ | ---- | ------------------------------------------ |
| On default branch        | 1    | Stop, instruct to create feature branch    |
| Dirty working tree       | 1    | Stop, list files, instruct to commit/stash |
| Behind remote            | 1    | Stop, instruct to pull/rebase              |
| Merge conflicts          | 2    | Stop, report conflicting files             |
| Test failures            | 3    | Stop, report failure output                |
| Critical review findings | 4    | Stop, resolve before proceeding            |
| MINOR/MAJOR version bump | 5    | Stop, confirm with user                    |

---

## Important Notes

- This skill **modifies the repository**: it creates commits, pushes code, and opens PRs.
- All branch names and test commands are **detected dynamically** — nothing is hardcoded.
- The version strategy is **inferred from project files**, not assumed.
- If the `pre-landing-review` skill is not available, the review step degrades to a
  lightweight diff scan rather than skipping entirely.
