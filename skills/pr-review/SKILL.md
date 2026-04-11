---
name: pr-review
description: 'Diff-based PR review across code quality, test coverage, silent failures, type design, and comment quality with severity-ranked findings. Triggers on: "review my PR", "review this code", "check my changes", "audit this PR", "code review". NOT for pre-landing gate, use pre-landing-review.'
metadata:
  version: 1.1.1
  category: review
  tags: [code-review, pull-request, quality, diff-analysis]
  difficulty: intermediate
  phase: review
---

# PR Review

Diff-based code review across five dimensions. Reads the changed files, selects
applicable review methodologies, and produces an aggregated report with severity-ranked
findings.

## Reference Files

| File                            | Contents                                                | Load When                       |
| ------------------------------- | ------------------------------------------------------- | ------------------------------- |
| `references/code-review.md`     | Guideline compliance, bug detection, confidence scoring | Always                          |
| `references/test-analysis.md`   | Behavioral test coverage, criticality rating            | Test files changed              |
| `references/error-handling.md`  | Silent failure patterns, catch block analysis           | Error handling changed          |
| `references/type-design.md`     | Invariant analysis, 4-dimension rating rubric           | Type definitions added/modified |
| `references/comment-quality.md` | Comment accuracy, long-term value, rot detection        | Comments/docstrings added       |

---

## Workflow

### Phase 1: Scope

1. Determine the review target:
   - Default: `git diff` (unstaged changes)
   - If user specifies a PR: `git diff main...HEAD` or `gh pr diff <number>`
   - If user specifies files: review those files directly
2. List all changed files with `git diff --name-only`
3. Read the project's CLAUDE.md (if present) for project-specific rules

### Phase 2: Route

Classify changed files and select applicable dimensions:

| Condition                                                                    | Dimension       | Reference to Load               |
| ---------------------------------------------------------------------------- | --------------- | ------------------------------- |
| Always                                                                       | Code review     | `references/code-review.md`     |
| Files matching `*test*`, `*spec*`, `*_test.*`, `test_*`                      | Test analysis   | `references/test-analysis.md`   |
| Files containing try/catch, except, .catch, Result, error callbacks          | Error handling  | `references/error-handling.md`  |
| Files containing class, interface, type, struct, enum, dataclass definitions | Type design     | `references/type-design.md`     |
| Files with new/modified docstrings, JSDoc, or block comments                 | Comment quality | `references/comment-quality.md` |

Load only the reference files that apply. Skip dimensions with no matching files.

### Phase 3: Review

For each applicable dimension, analyze the diff using the loaded methodology:

1. **Code review** — scan every changed file for guideline violations and bugs.
   Apply confidence scoring (0-100). Only report issues >= 80.
2. **Test analysis** — map test coverage to changed code paths. Rate gaps 1-10.
   Only report gaps >= 5.
3. **Error handling** — examine every error handler in the diff for silent failures.
   Classify CRITICAL/HIGH/MEDIUM.
4. **Type design** — evaluate new or modified types on 4 dimensions (encapsulation,
   invariant expression, usefulness, enforcement). Rate each 1-10.
5. **Comment quality** — verify accuracy, assess long-term value, flag comment rot.

### Phase 4: Aggregate

Merge all findings into a single report, deduplicated and severity-ranked.

**Deduplication rules:**

- If two dimensions flag the same file:line, keep the higher-severity finding
- If code-review and error-handling both flag an empty catch block, merge into one
  finding with the error-handling severity (it's the specialist)

**Severity mapping across dimensions:**

| Dimension       | Maps to Critical    | Maps to Important        | Maps to Suggestion    |
| --------------- | ------------------- | ------------------------ | --------------------- |
| Code review     | Confidence 90-100   | Confidence 80-89         | —                     |
| Test analysis   | Rating 9-10         | Rating 7-8               | Rating 5-6            |
| Error handling  | CRITICAL            | HIGH                     | MEDIUM                |
| Type design     | Any rating <= 3/10  | Any rating 4-6/10        | Rating 7-8/10         |
| Comment quality | Factually incorrect | Misleading or incomplete | Restates obvious code |

---

## Output Format

```text
# PR Review Summary

**Scope:** [X files changed, Y dimensions applied]
**Dimensions:** [list of active dimensions]

## Critical Issues (must fix before merge)
- **[dimension]** `file:line` — Description. Fix suggestion.

## Important Issues (should fix)
- **[dimension]** `file:line` — Description. Fix suggestion.

## Suggestions (consider)
- **[dimension]** `file:line` — Description.

## Strengths
- What's well-done in this changeset.

## Recommended Action
1. Fix critical issues
2. Address important issues
3. Consider suggestions
4. Re-run review after fixes
```

If no issues are found at any severity level, confirm the code meets standards with
a brief summary of what was reviewed and which dimensions were applied.

---

## Aspect Selection

Users can request specific dimensions instead of running all:

| User Says                                       | Dimensions Applied       |
| ----------------------------------------------- | ------------------------ |
| "review my PR" / "check my changes"             | All applicable (default) |
| "review the code" / "check code quality"        | Code review only         |
| "check the tests" / "is test coverage good"     | Test analysis only       |
| "check error handling" / "find silent failures" | Error handling only      |
| "review the types" / "check type design"        | Type design only         |
| "check the comments" / "review documentation"   | Comment quality only     |

When a specific aspect is requested, load only that reference file and skip routing.

---

## Error Handling

| Problem                     | Resolution                                                                    |
| --------------------------- | ----------------------------------------------------------------------------- |
| No git diff available       | Ask user to specify files or scope                                            |
| CLAUDE.md not found         | Review against general best practices; note the absence                       |
| No test files in diff       | Skip test analysis dimension; note in output                                  |
| Diff is empty               | Report "no changes to review" and stop                                        |
| Diff exceeds context limits | Focus on files the user is most likely to care about; summarize skipped files |

---

## Calibration Rules

1. **Precision over recall.** A false positive erodes trust in the review. Only report
   issues at >= 80 confidence (code review) or >= 5 criticality (tests). Silence is
   better than noise.
2. **File:line references are mandatory.** Every finding must include a specific location.
   Vague findings ("consider improving error handling") are not actionable.
3. **Project rules override general rules.** If CLAUDE.md says "use arrow functions",
   do not flag arrow functions even if conventional style prefers `function` declarations.
4. **Deduplication is mandatory.** If two dimensions flag the same issue, merge them.
   Never report the same problem twice.
5. **Acknowledge strengths.** A review that only lists problems is demoralizing. Note
   what's done well, even briefly.
6. **Code-refiner handles simplification.** This skill reviews and reports. It does not
   refactor or simplify — that's the `code-refiner` skill's job. Keep the roles separate.

## Rationalizations

| Rationalization | Reality |
|---|---|
| "Tests pass, so the code is fine" | Tests are necessary but insufficient — they miss architecture, security, readability, and maintainability concerns |
| "It's a small diff, no real review needed" | Small changes cause most production incidents; a 3-line auth bypass is worse than a 300-line refactor |
| "We'll clean it up later" | Later never comes — the review IS the quality gate before code becomes legacy |
| "The author is senior, I trust them" | Seniority doesn't prevent mistakes; fresh eyes catch what familiarity blinds |
| "I already reviewed similar code recently" | Each diff has unique context — assumptions from past reviews cause missed issues |
| "This is just a refactor, nothing can break" | Refactors change behavior in subtle ways — verify with tests and trace call sites |

## Red Flags

- Approving without reading every changed file in full (not just diff hunks)
- No file:line references in findings — vague feedback is not actionable
- Skipping a review dimension because "it looks fine"
- Reporting only style issues while ignoring logic, security, or architecture
- Reviewing generated code (migrations, protobuf stubs) with the same rigor as hand-written code
- Merging findings from different dimensions without deduplication

## Verification

- [ ] Every changed file read in full, not just diff hunks
- [ ] Each review dimension scored: correctness, security, performance, readability, architecture
- [ ] Every finding includes a file:line reference
- [ ] At least one actionable finding per 100 lines changed, or explicit "no issues found" with justification
- [ ] Review summary includes risk level (LOW/MEDIUM/HIGH/CRITICAL) and blocking vs. non-blocking classification
- [ ] Strengths acknowledged — review is not 100% negative
