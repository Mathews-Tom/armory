# Comment Quality Analysis Methodology

Protect codebases from comment rot. Every comment must earn its place by providing
clear, lasting value. Analyze through the lens of a developer encountering the code
months later without original context.

## Analysis Dimensions

### 1. Factual Accuracy

Cross-reference every claim against the actual code:

- Function signatures match documented parameters and return types
- Described behavior aligns with actual code logic
- Referenced types, functions, and variables exist and are used correctly
- Edge cases mentioned are actually handled
- Performance or complexity claims are accurate

### 2. Completeness

Evaluate whether comments provide sufficient context:

- Critical assumptions or preconditions documented
- Non-obvious side effects mentioned
- Important error conditions described
- Complex algorithms have their approach explained
- Business logic rationale captured when not self-evident

### 3. Long-term Value

Consider the comment's utility over the codebase's lifetime:

- Flag comments that merely restate obvious code
- "Why" comments are more valuable than "what" comments
- Comments likely to become outdated with code changes should be reconsidered
- Comments should target the least experienced future maintainer
- Avoid references to temporary states or transitional implementations

### 4. Misleading Elements

Search for ways comments could be misinterpreted:

- Ambiguous language with multiple meanings
- Outdated references to refactored code
- Assumptions that may no longer hold true
- Examples that don't match current implementation
- TODOs or FIXMEs that have already been addressed

## Output Format

```text
## Comment Analysis

### Summary
Brief overview of scope and findings.

### Blocking Issues (misleading contracts with a concrete failing use)
- `file:line` — Issue description. Suggested rewrite.

### Improvement Opportunities
- `file:line` — Current state. How to improve.

### Recommended Removals
- `file:line` — Rationale (restates obvious code, outdated, etc.)

### Positive Findings
- Well-written comments that serve as good examples.
```

This analysis is read-only. Apply impact-based severity: misleading usage or safety contracts can block, but ordinary wording, removal and completeness suggestions remain optional. Omit optional polish unless useful or requested; do not create another fix/review cycle for it.
