---
name: pr-review
description: 'Diff-based PR review across code quality, test coverage, silent failures, type design, and comment quality with severity-ranked findings. Triggers on: "review my PR", "review this code", "check my changes", "audit this PR", "code review". NOT for pre-landing gate, use pre-landing-review.'
metadata:
  version: 1.2.0
  category: review
  tags: [code-review, pull-request, quality, diff-analysis]
  difficulty: intermediate
  phase: review
---

# PR Review

Diff-based code review across five dimensions. Reads the changed files, selects
applicable review methodologies, and produces an aggregated report with severity-ranked
findings.

> **Native alternative:** Claude Code's `/ultrareview` runs a lightweight native bug-focused review (three free per month on Pro/Max plans at Opus 4.7's launch). Use this skill for five-dimension severity-ranked analysis (code quality + tests + error handling + types + comments) with file:line references; use `/ultrareview` for a quick bug-hunting pass on a diff.

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

Review the changed behavior and affected contracts using the applicable methodologies:

1. **Code review** — report demonstrated bugs and explicit rule violations at confidence >= 80.
2. **Test analysis** — identify plausible consumer-visible regressions that required behavior does not cover.
3. **Error handling** — trace failures and their caller-visible consequences.
4. **Type design** — assess current invariants and actual consumers; speculative extensibility is not a defect.
5. **Comment quality** — report misleading contracts that affect correct use; ordinary polish is optional.

Read enough surrounding implementation and call sites to prove each scenario. Review changed source rather than generated copies. On fixes, review the changed code and affected interactions; repeat a broader review only when a changed contract or base invalidates the earlier assessment.

### Phase 4: Aggregate

Merge all findings into a single report, deduplicated and severity-ranked.

**Deduplication rules:**

- If two dimensions flag the same file:line, keep the higher-severity finding
- If code-review and error-handling both flag an empty catch block, merge into one
  finding with the error-handling severity (it's the specialist)

**Severity is impact, not confidence or a design score.**

| Severity | Evidence and consequence |
| --- | --- |
| Critical | Demonstrated severe security, data-loss, availability or equivalent consumer risk; blocks merge. |
| Important | Concrete regression, broken contract, required behavior gap or evidenced maintainability defect; blocks until resolved or an authorized decision addresses it. |
| Suggestion | Optional polish or future capability; non-blocking and omitted unless useful or requested. |

Use confidence to filter uncertain claims, not to promote a certain nit into a Critical finding. Respect repository-specific severity labels and provider-required review policy.

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

## Recommended Action
1. Resolve demonstrated blocking issues, batching fixes by bug class.
2. Re-review changed code and affected interactions only.
3. Leave optional suggestions non-blocking; do not expand the PR to obtain reviewer silence.
4. After three unsuccessful fix/re-review rounds, report the recurring findings for an owner decision. The cap never authorizes merging known defects.
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
5. **Progress over perfection.** Approve when required behavior and code health meet the repository standard; no finding quota and no mandatory polish. A clean review is a valid result.
6. **Code-refiner handles simplification.** This skill reviews and reports. It does not
   refactor or simplify — that's the `code-refiner` skill's job. Keep the roles separate.

## Rationalizations

| Rationalization | Reality |
|---|---|
| "Tests pass, so the code is fine" | Tests are necessary but insufficient — they miss architecture, security, readability, and maintainability concerns |
| "It's a small diff, no real review needed" | Small changes cause most production incidents; a 3-line auth bypass is worse than a 300-line refactor |
| "We'll clean it up later" | Fix demonstrated current defects now; defer optional capability and polish without weakening current correctness |
| "The author is senior, I trust them" | Seniority doesn't prevent mistakes; fresh eyes catch what familiarity blinds |
| "I already reviewed similar code recently" | Each diff has unique context — assumptions from past reviews cause missed issues |
| "This is just a refactor, nothing can break" | Refactors change behavior in subtle ways — verify with tests and trace call sites |

## Red Flags

- Approving without reading the changed behavior and enough surrounding context to verify affected contracts
- No file:line references in findings — vague feedback is not actionable
- Skipping a review dimension because "it looks fine"
- Reporting only style issues while ignoring logic, security, or architecture
- Reviewing generated code (migrations, protobuf stubs) with the same rigor as hand-written code
- Merging findings from different dimensions without deduplication

## Verification

- [ ] Changed behavior and affected contracts reviewed with sufficient surrounding context
- [ ] Applicable dimensions covered; irrelevant dimensions omitted
- [ ] Every finding includes file:line, concrete scenario, consequence and bug class
- [ ] Severity reflects impact, not confidence, a score or a target finding count
- [ ] Blocking and non-blocking feedback distinguished; provider-required reviews preserved
- [ ] Re-review is scoped to changed code and affected interactions; recurring failures stop after three rounds
