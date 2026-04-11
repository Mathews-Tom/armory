---
name: changelog-composer
description: 'Generates structured changelogs and release notes from git history and PRs, classifying breaking changes, features, fixes, performance, docs. Triggers on: "generate changelog", "write release notes", "what changed since", "prepare release", "release notes for", "diff since tag".'
metadata:
  version: 1.1.1
  category: content
  tags: [changelog, release-notes, git-history, versioning]
  difficulty: intermediate
  phase: ship
---

# Changelog Composer

Transforms raw git history and PR descriptions into polished, audience-appropriate
changelogs. Parses conventional commits, classifies changes by impact category, filters
internal-only modifications, and produces structured release notes with PR links —
following Keep a Changelog conventions.

## Reference Files

| File                                 | Contents                                                           | Load When                            |
| ------------------------------------ | ------------------------------------------------------------------ | ------------------------------------ |
| `references/conventional-commits.md` | Commit type parsing, scope extraction, breaking change indicators  | Repository uses conventional commits |
| `references/categorization-rules.md` | Change classification logic, audience filtering, severity ordering | Always                               |
| `references/audience-filter.md`      | User-facing vs internal change detection, exclusion patterns       | Always                               |
| `references/changelog-formats.md`    | Keep a Changelog, GitHub Releases, announcement copy templates     | Format selection needed              |

## Prerequisites

- **git** — access to the repository history
- **gh** (optional) — GitHub CLI for PR description extraction
- A tagging strategy (semver tags) for identifying release boundaries

## Workflow

### Phase 1: Gather Raw Changes

Collect all changes between the previous release and the current state:

1. **Identify boundaries** — Find the last release tag: `git describe --tags --abbrev=0`.
   If no tags exist, use the initial commit or a user-specified starting point.
2. **Extract commits** — `git log <last-tag>..HEAD --oneline --no-merges`
3. **Extract PR titles** — `gh pr list --state merged --base main --search "merged:>YYYY-MM-DD"`
   or parse merge commit messages.
4. **Parse conventional commits** — If the repository follows conventional commits
   (`feat:`, `fix:`, `docs:`, etc.), extract type, scope, and description. See
   `references/conventional-commits.md`.
5. **Collect breaking change indicators** — Look for `BREAKING CHANGE:` in commit
   bodies, `!` after type (`feat!:`), or explicit annotations in PR descriptions.

### Phase 2: Classify Changes

Categorize each change by its impact:

| Category         | Conventional Commit Type                        | Indicators                                     |
| ---------------- | ----------------------------------------------- | ---------------------------------------------- |
| Breaking Changes | `feat!:`, `BREAKING CHANGE:`                    | API removal, signature change, behavior change |
| Features         | `feat:`                                         | New capability, new endpoint, new command      |
| Fixes            | `fix:`                                          | Bug correction, error handling improvement     |
| Performance      | `perf:`                                         | Speed improvement, memory reduction            |
| Documentation    | `docs:`                                         | README, API docs, guides                       |
| Internal         | `chore:`, `ci:`, `refactor:`, `test:`, `build:` | No user-facing impact                          |

For repositories without conventional commits, classify by reading the commit message
and changed files. Code changes to public API → Feature or Fix. Test-only changes → Internal.

### Phase 3: Filter for Audience

1. **Exclude internal changes** by default:
   - CI/CD configuration changes
   - Test additions/modifications
   - Dependency bumps (unless security-relevant)
   - Code refactoring with no behavior change
   - Build system changes

2. **Include internal changes** only when:
   - They represent significant architecture shifts users should know about
   - They affect development workflow (contributing guide changes)
   - The changelog targets developers, not end-users

3. **Highlight breaking changes** prominently — always at the top, always with migration
   guidance.

### Phase 4: Compose Entries

For each included change, write a human-readable description:

1. **Lead with the impact** — "Users can now..." or "Fixed issue where..."
2. **Be specific** — "Reduced memory usage by 40% for large file processing" not
   "Performance improvements"
3. **Include migration guidance** for breaking changes — what the user must change
4. **Link to source** — PR number, issue number, or commit hash

### Phase 5: Output

Assemble the changelog in the requested format, ordered by severity:

1. Breaking Changes (always first)
2. Features
3. Fixes
4. Performance
5. Documentation

## Output Format

```text
## [{version}] - {YYYY-MM-DD}

### Breaking Changes
- **`function_name` parameter renamed** — `old_param` is now `new_param`.
  Migration: find/replace `old_param=` with `new_param=` in all call sites. ([#{pr}]({url}))

### Features
- **{Feature name}** — {What it enables and why it matters}. ([#{pr}]({url}))

### Fixes
- Fixed {symptom} when {condition}. ([#{pr}]({url}))

### Performance
- {Operation} is now {X}x faster / uses {X}% less memory. ([#{pr}]({url}))

### Documentation
- Added {guide/reference} for {topic}. ([#{pr}]({url}))
```

## Configuring Scope

| Mode      | Input                      | Output                   | When to Use                   |
| --------- | -------------------------- | ------------------------ | ----------------------------- |
| `release` | Tag-to-HEAD                | Full changelog entry     | Preparing a versioned release |
| `sprint`  | Date range or commit range | Summary of changes       | Sprint review, status update  |
| `pr`      | Single PR                  | One-line changelog entry | PR description template       |

## Calibration Rules

1. **User impact first.** Every entry should answer "what does this mean for the user?"
   not "what did the developer do?"
2. **Breaking changes are non-negotiable.** Never omit or bury breaking changes. They
   go first, with migration guidance.
3. **Specific over vague.** "Fixed login timeout on slow connections" beats "Fixed bug."
   "Added CSV export for reports" beats "New feature."
4. **Link everything.** Every entry links to its source PR or issue. Users who want
   details can follow the link.
5. **Exclude noise.** Internal refactoring, dependency bumps, and CI changes do not
   belong in user-facing changelogs unless they have user-visible impact.

## Error Handling

| Problem                                     | Resolution                                                                                         |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| No tags exist in repository                 | Ask for a starting commit or date. Default to the initial commit if the repository is small.       |
| Repository doesn't use conventional commits | Classify by reading commit messages and changed files. Note reduced classification accuracy.       |
| PR descriptions are empty or low-quality    | Fall back to commit messages. Flag entries that may need manual review.                            |
| Ambiguous change classification             | Default to "Features" for additions, "Fixes" for modifications. Mark uncertain entries for review. |
| Too many changes for a single release       | Group by component/module. Consider whether the release should be split.                           |
| Merge commits obscure individual changes    | Use `--no-merges` to skip merge commits. Parse individual commits within merged PRs.               |

## When NOT to Compose

Push back if:

- The user wants to auto-publish release notes without review — changelogs require human judgment
- The repository has no meaningful commit history (single "initial commit" with everything)
- The request is for marketing copy, not technical release notes — different skill
- The changes are not yet merged — changelog is for shipped changes, not in-progress work
