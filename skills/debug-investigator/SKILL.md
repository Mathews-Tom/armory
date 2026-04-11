---
name: debug-investigator
description: 'Hypothesis-driven debugging with ranked hypotheses, git bisect strategy, instrumentation planning, and minimal reproduction design. Triggers on: "debug this systematically", "root cause analysis", "bisect this bug", "rank hypotheses", "isolate this issue", "minimal reproduction". NOT for general reasoning.'
metadata:
  version: 1.1.1
  category: development
  tags: [debugging, root-cause, hypothesis, bisect]
  difficulty: intermediate
  phase: build
---

# Debug Investigator

Structured debugging methodology that replaces ad-hoc exploration with hypothesis-driven
investigation. Captures symptoms, analyzes evidence (stacktraces, logs, state), generates
ranked hypotheses, designs bisection strategies, identifies instrumentation points, and
produces minimal reproductions — documenting every step so dead ends are never revisited.

> **When to use this skill vs native debugging:** The base model handles straightforward
> debugging (clear stacktraces, obvious errors) natively. Use this skill for non-obvious bugs
> requiring systematic investigation: intermittent failures, bugs with no clear stacktrace,
> performance regressions, or issues requiring git bisection and hypothesis ranking.

## Reference Files

| File                                   | Contents                                                                      | Load When                       |
| -------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------- |
| `references/stacktrace-patterns.md`    | Exception taxonomy, traceback reading, common Python/JS error signatures      | Stacktrace or exception present |
| `references/hypothesis-templates.md`   | Bug category catalog, probability ranking, confirmation/refutation tests      | Always                          |
| `references/bisection-guide.md`        | git bisect workflow, binary search debugging, narrowing techniques            | Bug appeared after a change     |
| `references/log-analysis.md`           | Log pattern extraction, anomaly detection, timeline correlation               | Log output available            |
| `references/instrumentation-points.md` | Strategic logging placement, breakpoint strategy, state inspection techniques | Investigation plan needed       |

## Prerequisites

- **git** — for bisection and history analysis
- **Access to source code** — cannot debug opaque binaries
- **Reproducible environment** — or at minimum, error output (stacktrace, logs)

## Workflow

### Phase 1: Symptom Capture

Before touching code, document the observable problem:

1. **What is happening?** — Describe the observed behavior precisely. "It crashes" is
   insufficient. "Raises `KeyError('user_id')` on line 42 of `auth.py` when calling
   `get_current_user()` with a valid session token" is actionable.
2. **What should happen?** — Define the expected behavior. If unknown, state that.
3. **Reproducibility** — Always, intermittent (with frequency), or one-time? Intermittent
   bugs require different strategies than deterministic ones.
4. **Recency** — When did this start? Correlate with recent changes: `git log --oneline -20`.
   If the bug appeared after a specific commit, bisection is the fastest path.
5. **Environment** — Python version, OS, dependency versions, configuration differences
   between working and broken environments.

### Phase 2: Evidence Analysis

Examine all available evidence before forming hypotheses:

1. **Stacktrace interpretation** — If a traceback exists, read it bottom-up. The last
   frame is where the error manifested, but the cause is often several frames up. Identify:
   - Exception type and message
   - The frame where the error originated vs. where it was raised
   - Any familiar patterns (see `references/stacktrace-patterns.md`)

2. **Log pattern extraction** — Search logs for:
   - Temporal anomalies (timestamps out of sequence, gaps)
   - Repeated errors (same error appearing in bursts)
   - State transitions that didn't complete
   - Correlation with external events (deploys, config changes)

3. **State inspection** — If the system is running, inspect:
   - Variable values at the failure point
   - Database state (missing rows, unexpected values)
   - Configuration values (environment variables, config files)
   - External dependency status (API availability, DB connectivity)

4. **Code diff analysis** — If the bug is recent:
   - `git diff HEAD~5` — what changed?
   - Focus on files touched by the error's call chain
   - Look for typos, wrong variable names, missing null checks

### Phase 3: Hypothesis Generation

Generate ranked hypotheses — never start fixing without a hypothesis:

1. **List 3-5 hypotheses** ranked by likelihood. Each hypothesis must include:
   - A concrete claim about what is wrong
   - What evidence supports it
   - What evidence would confirm it (a test you can run)
   - What evidence would refute it

2. **Rank by likelihood** using:
   - Proximity to recent changes (most bugs are in new code)
   - Simplicity (typos before race conditions)
   - Evidence fit (does the hypothesis explain ALL symptoms?)

3. **Common bug categories** (see `references/hypothesis-templates.md`):
   - State bugs: wrong value, missing initialization, stale cache
   - Logic bugs: off-by-one, wrong operator, inverted condition
   - Integration bugs: API contract mismatch, serialization error
   - Concurrency bugs: race condition, deadlock, resource starvation
   - Environment bugs: missing dependency, wrong config, version mismatch

### Phase 4: Investigation Plan

Design specific steps to test each hypothesis:

1. **Test H1 first** — Always test the most likely hypothesis first. Design a single
   action that will confirm or refute it.
2. **Bisection** — If the bug appeared after a change and H1 fails:
   - Identify the known-good and known-bad commits
   - Run `git bisect start <bad> <good>`
   - Define the test command for each commit
   - See `references/bisection-guide.md` for workflow
3. **Isolation** — Remove variables one at a time:
   - Simplify input data
   - Disable features/plugins
   - Replace external calls with hardcoded values
   - Run in a clean environment
4. **Instrumentation** — Add targeted logging/breakpoints:
   - At function entry/exit points in the call chain
   - Before and after state mutations
   - At decision points (if/else branches)
   - See `references/instrumentation-points.md`

### Phase 5: Execution

Execute the investigation plan, updating hypotheses as evidence arrives:

1. **Test one variable at a time** — Changing multiple things simultaneously makes
   results uninterpretable.
2. **Record results** — Document what each test revealed, even negative results.
   Dead-end documentation prevents revisiting failed paths.
3. **Update probabilities** — After each test, re-rank hypotheses. If H1 is refuted,
   H2 becomes the new priority.
4. **Know when to escalate** — If all hypotheses are exhausted, the bug is in a
   category you haven't considered. Step back and re-examine assumptions.

### Phase 6: Resolution Documentation

After finding the root cause:

1. **Root cause** — What was actually wrong, precisely.
2. **Fix** — What was changed and why.
3. **Prevention** — How to prevent recurrence (test, lint rule, type check, etc.).
4. **Lessons** — What was learned that applies beyond this specific bug.

## Output Format

````
## Debug Investigation: {Brief Description}

### Symptom
**Observed:** {What is happening — precise description}
**Expected:** {What should happen}
**Reproducibility:** {Always | Intermittent (~N% of attempts) | Once}
**First noticed:** {Date/time or triggering event}
**Environment:** {Relevant versions and configuration}

### Evidence Analysis

#### Stacktrace
- **Exception:** {type}: {message}
- **Origin:** {file}:{line} in {function}
- **Call chain:** {caller} → {caller} → {failure point}
- **Key insight:** {What the traceback reveals about the cause}

#### Logs
- **Anomaly:** {What is unusual}
- **Timeline:** {When the anomaly started}
- **Correlation:** {Related events}

#### Code Changes
- **Recent commits:** {relevant commits since last known-good state}
- **Files in error path:** {which changed files appear in the traceback}

### Hypotheses

| # | Hypothesis | Likelihood | Confirming Test | Refuting Test |
|---|------------|------------|-----------------|---------------|
| H1 | {Specific claim} | High | {What to check} | {What would disprove} |
| H2 | {Specific claim} | Medium | {What to check} | {What would disprove} |
| H3 | {Specific claim} | Low | {What to check} | {What would disprove} |

### Investigation Plan

#### Step 1: Test H1 — {action}
- **Command/action:** {specific step}
- **If confirmed:** {next action — fix}
- **If refuted:** proceed to Step 2

#### Step 2: Bisection
- **Good commit:** {hash}
- **Bad commit:** {hash}
- **Test:** {command to verify each commit}
- **Command:** `git bisect start {bad} {good}`

#### Step 3: Isolation
- **Remove:** {variable to eliminate}
- **Expected change:** {what should happen}

### Instrumentation Points
1. {file}:{line} — log {variable/state} to observe {what}
2. {file}:{line} — breakpoint to inspect {what}

### Minimal Reproduction
```{language}
# Minimal code that triggers the bug
{code}
````

### Resolution

**Root cause:** {What was wrong}
**Fix:** {What was changed — file:line, diff summary}
**Prevention:** {Test added, lint rule, type annotation, etc.}
**Lessons:** {What generalizes beyond this bug}

```text

## Configuring Scope

| Mode | Scope | Depth | When to Use |
|------|-------|-------|-------------|
| `quick` | Single error | H1 test + fix | Clear stacktrace, obvious cause |
| `standard` | Full investigation | 3 hypotheses + bisection plan | Default for non-obvious bugs |
| `deep` | Systemic analysis | 5+ hypotheses + instrumentation + reproduction | Intermittent bugs, no stacktrace, production issues |

## Calibration Rules

1. **Hypotheses before code changes.** Never start modifying code without at least one
   explicit hypothesis. "Let me try this" is not debugging — it's guessing.
2. **One variable at a time.** Each investigation step should change exactly one thing.
   If you change two things and the bug disappears, you don't know which fixed it.
3. **Document dead ends.** Failed hypotheses are valuable — they narrow the search space.
   Record what was tested and what was learned.
4. **Simplest explanation first.** Test typos, wrong variable names, and missing imports
   before considering race conditions, compiler bugs, or cosmic rays.
5. **Reproduce before fixing.** If you cannot reproduce the bug in a controlled environment,
   any fix is speculative. Invest in reproduction first.
6. **Root cause, not symptoms.** A fix that addresses the symptom (adding a null check)
   without understanding the root cause (why was it null?) leaves the real bug alive.

## Error Handling

| Problem | Resolution |
|---------|------------|
| No stacktrace available | Focus on log analysis and state inspection. Use instrumentation to generate diagnostic output. |
| Bug is intermittent | Add persistent logging at key decision points. Run under stress (high load, concurrent requests) to increase reproduction rate. |
| Cannot reproduce locally | Compare environments systematically: versions, config, data, timing. Use `docker` or VM to mirror production. |
| Multiple hypotheses equally likely | Design a single test that distinguishes between them. Binary decision: "If X, then H1; if Y, then H2." |
| Fix attempted but bug persists | The hypothesis was wrong. Revert the fix, update hypothesis rankings, and proceed to the next hypothesis. Do not stack fixes. |
| Bug is in a dependency | Confirm with a minimal reproduction that uses only the dependency. Check issue trackers. Pin to last known-good version while awaiting upstream fix. |

## When NOT to Investigate

Push back if:
- The error message already contains the fix ("missing module X" → install X)
- The issue is a known environment setup problem (wrong Python version, missing env var)
- The "bug" is actually a feature request or design disagreement — redirect to ADR or discussion
- The code is not under the user's control (third-party SaaS, managed service) — file a support ticket instead
- The user wants to debug generated/minified code — debug the source, not the output
```
