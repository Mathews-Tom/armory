---
name: pre-landing-review
description: 'Gate-oriented safety audit for code changes before landing, using a checklist with two-pass severity triage. Triggers on: "is this safe to land", "pre-landing review", "safety check before merge", "gate check", "/pre-landing-review". NOT for diff review, use pr-review.'
metadata:
  version: 1.0.1
  category: review
  tags: [pre-merge, safety-gate, code-review, checklist]
  difficulty: intermediate
  phase: review
---

# Pre-Landing Review

Gate-oriented safety audit for code changes before landing. Uses a structured checklist with two-pass severity triage and blocking/non-blocking classification.

**Distinct from `pr-review`**: pr-review is a multi-dimension code quality review. This skill is a **gate-oriented safety audit** — it uses an external checklist with two-pass severity triage and a blocking/non-blocking classification.

## Workflow

### 1. Determine Diff

Identify the changes to review:

- If on a feature branch: diff against the default branch (`git symbolic-ref refs/remotes/origin/HEAD`)
- If given a PR number: fetch that PR's diff
- If given specific files: review those files

### 2. Load Checklist

Read `references/checklist.md`. This is mandatory — if the checklist is unreadable, STOP and report the error.

### 3. Pass 1 — CRITICAL (blocking)

Review the diff against critical safety categories. These are potential ship-blockers.

#### SQL & Data Safety

- Raw SQL without parameterization
- Schema changes without migration safety (lock timeout, reversibility)
- Bulk updates/deletes without WHERE clause verification
- Direct column updates bypassing model validations/callbacks

#### Race Conditions & Concurrency

- Read-then-write without locking
- Unique constraint reliance without database-level enforcement
- Shared mutable state without synchronization
- Queue/background job idempotency

#### Trust Boundaries

- LLM/AI output used in SQL, shell commands, or rendered HTML without sanitization
- User input reaching privileged operations without validation
- External API responses used without schema validation
- Deserialization of untrusted data

For each CRITICAL finding:

1. Cite exact file and line
2. Explain the specific risk
3. Use `AskUserQuestion` with exactly three options: **Fix now** / **Acknowledge risk** / **False positive**
4. If "Fix now": make the fix, then re-check
5. If "Acknowledge": record acknowledgment, continue
6. If "False positive": record, continue

### 4. Pass 2 — INFORMATIONAL (non-blocking)

Review against remaining categories:

**Conditional Side Effects** — side effects hidden in conditional branches, callbacks triggered by state changes, error handlers silently swallowing failures.

**Magic Numbers** — unexplained numeric literals, hardcoded thresholds without constants, timeout values without rationale.

**Dead Code** — unreachable branches, unused imports, commented-out code without explanation.

**Test Gaps** — new code paths without test coverage, modified behavior without updated tests, missing edge case and error path tests.

**Crypto & Entropy** — weak random sources for security contexts, hardcoded secrets, missing TLS/encryption for sensitive data in transit.

**Time Window Safety** — timezone-naive comparisons, daylight saving edge cases, cron expressions not accounting for clock skew.

**Type Coercion** — implicit type conversions that could lose data, numeric precision loss across boundaries, implicit string encoding at I/O boundaries.

Present all informational findings in a single summary table (file, line, category, description).

### 5. Gate Classification

- All Pass 1 issues resolved (fixed or acknowledged) → **CLEAR TO LAND**
- Any unresolved Pass 1 issue → **BLOCKED**
- Pass 2 issues are advisory — they don't block landing

### 6. Suppressions

Do NOT flag:

- Test files using test fixtures/factories
- Migration files following framework conventions
- Comments explaining why a pattern is intentional
- Configuration files with documented values
- Type stubs or interface definitions

## Output

Gate verdict (CLEAR TO LAND / BLOCKED), critical issues summary with resolution status, informational findings table.

**This skill is read-only by default** — only modifies code when user explicitly chooses "Fix now" on a critical issue.
