# Code Review Methodology

Review code against project guidelines (CLAUDE.md) with high precision. Minimize false
positives — quality over quantity.

## Review Scope

Default: unstaged changes from `git diff`. User may specify different scope (staged
changes, specific files, PR diff).

## Responsibilities

**Project Guidelines Compliance**

- Import patterns and module structure
- Framework conventions and language-specific style
- Function declarations and naming conventions
- Error handling and logging patterns
- Testing practices and platform compatibility

**Bug Detection**

- Logic errors and off-by-one mistakes
- Null/undefined handling gaps
- Race conditions and concurrency issues
- Memory leaks and resource management
- Security vulnerabilities (injection, XSS, auth bypass)
- Performance regressions (N+1 queries, unbounded loops)

**Code Quality**

- Significant duplication
- Missing critical error handling
- Accessibility problems (if frontend)
- Inadequate test coverage for new code paths

## Confidence Scoring

Rate confidence 0–100 and report only issues scoring >=80. Confidence measures whether the scenario is supported, not the severity of its consequence. Apply the skill's impact-based Critical / Important / Suggestion classification.

| Range | Meaning |
| --- | --- |
| 80–100 | Concrete scenario supported by code, a contract or observed evidence |
| Below 80 | Uncertain claim; investigate further or omit |

## Output Format

Start by listing files under review. For each issue:

```text
**[IMPORTANT]** (confidence: 95) `src/auth.py:42`
Scenario and consumer-visible consequence.
Rule: [project rule or bug class]
Fix: Smallest correction covering the bug class in this diff.
```

Group by impact, not confidence. Blocking findings need a demonstrated defect, required behavior gap or evidenced maintainability problem. Optional polish and hypothetical future features do not block. A clean review is valid; no minimum finding count applies. On a fix pass, inspect changed code and affected contracts rather than restarting the review of unchanged code.
