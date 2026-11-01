# Error Handling & Silent Failure Analysis

Trace changed failure paths to their caller-visible result. Report concealed failures that violate a contract or prevent required recovery; severity follows the demonstrated impact.

## Non-Negotiable Rules

1. **Failures must remain observable at the appropriate boundary** — propagation to a caller or handling by an outer boundary can be correct; do not require duplicate logging and user messages in every handler.
2. **Feedback must support the current workflow** — missing actionability is blocking only when it prevents required use, diagnosis or recovery.
3. **Fallbacks must be explicit and justified** — falling back without user awareness
   hides problems
4. **Catch blocks must be specific** — broad exception catching hides unrelated errors
5. **Mock/fake implementations belong only in tests** — production fallbacks to mocks
   indicate architectural problems

## Review Process

### 1. Locate All Error Handling Code

Systematically find:

- try-catch/try-except blocks
- Error callbacks and event handlers
- Conditional branches handling error states
- Fallback logic and default values on failure
- Places where errors are logged but execution continues
- Optional chaining or null coalescing that might hide errors

### 2. Scrutinize Each Handler

**Logging quality:**

- Appropriate severity level (error vs warning vs info)
- Sufficient context (operation, relevant IDs, state)
- Correlation or tracking IDs when the current operational contract requires them
- Debuggable 6 months from now by someone without context

**User feedback:**

- Clear, actionable message about what went wrong
- Explains what the user can do to fix or work around it
- Specific enough to be useful, not generic
- Technical details appropriate to the user's context

**Catch block specificity:**

- Catches only expected error types
- Cannot accidentally suppress unrelated errors
- List every unexpected error type that could be hidden
- Should it be multiple catch blocks for different types?

**Fallback behavior:**

- Is fallback explicitly requested or documented?
- Does it mask the underlying problem?
- Would the user be confused about why they see fallback behavior?
- Is it a fallback to a mock/stub outside test code?

**Error propagation:**

- Should this error bubble up to a higher-level handler?
- Is the error being swallowed when it should propagate?
- Does catching prevent proper cleanup or resource management?

### 3. Check for Hidden Failure Patterns

Investigate these patterns; report a finding only after establishing a concrete failing scenario:

- Empty catch blocks
- Catch blocks that only log and continue
- Returning null/undefined/default on error without logging
- Optional chaining (`?.`) silently skipping operations that might fail
- Fallback chains trying multiple approaches without explaining why
- Retry logic exhausting attempts without informing the user
- Bare `except:` or `except Exception:` in Python
- `catch (e) {}` with empty body in JavaScript/TypeScript

## Severity Classification

| Severity | Criteria |
| --- | --- |
| CRITICAL | Concealed failure demonstrably causes severe security, data-loss or availability risk |
| HIGH | Swallowed or misrouted error breaks required behavior or recovery |
| MEDIUM | Optional message/log improvement without a demonstrated required-behavior defect; non-blocking |

## Output Format

For each issue:

```text
**[CRITICAL]** `src/api/client.py:87`
Empty except block swallows ConnectionError, TimeoutError, and any
unexpected exception from the HTTP client.
**Hidden errors:** ConnectionRefusedError, SSLError, ProxyError
**User impact:** Request silently fails; user sees stale data with no
indication that the fetch failed.
**Fix:** Catch specific exceptions, log with context, surface to user.
```
