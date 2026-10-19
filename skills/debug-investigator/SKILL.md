---
name: debug-investigator
description: 'Use when investigating non-obvious bugs, intermittent failures, regressions requiring bisection, or whether a regression test reaches the real shared failure boundary. Not for abstract trade-offs, feature design, or an error whose message already supplies the fix.'
metadata:
  version: 1.2.0
  category: development
  tags: [debugging, root-cause, hypothesis, bisect]
  difficulty: intermediate
  phase: build
---

# Debug Investigator

Structured debugging methodology that replaces ad-hoc exploration with hypothesis-driven
investigation. Captures symptoms, builds a deterministic feedback loop, analyzes evidence
(stacktraces, logs, state), generates ranked hypotheses, designs bisection strategies,
identifies instrumentation points, and produces minimal reproductions — documenting every
step so dead ends are never revisited.

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
| `references/upstream/provenance.md`     | Source pin, adaptation boundaries, MIT notice and manual resync policy         | Attribution/license review or deliberate upstream resync |

## Prerequisites

- **git** — for bisection and history analysis
- **Access to source code** — cannot debug opaque binaries
- **Reproducible environment** — or at minimum, error output (stacktrace, logs)

Discover reproduction and test commands from project scripts, test configuration, and installed
tool help before selecting invocations; record their source and relevant environment settings.
Run only checks and mutations authorized by the task. If access, tools, or execution authority
are missing, record the affected evidence as unobserved and complete independent analysis.

## Project Context

Before deep investigation, check for repo-local agent context:

- `docs/agents/domain.md` for `CONTEXT.md`, `CONTEXT-MAP.md`, and ADR lookup rules
- `CONTEXT.md` or relevant context-local glossary for domain vocabulary
- `docs/adr/` and context-local ADRs for decisions near the failing area

Use the project glossary in hypotheses, repro names, and prevention recommendations. If the
repo lacks these files, continue normally; do not block debugging on context setup.

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

Keep the original input, setup, caller sequence, and expected outcome available separately from
any later minimized reproduction; these define the final original-scenario check.

### Phase 2: Build a Feedback Loop

Create a fast, deterministic pass/fail signal for the reported bug before ranking hypotheses
or changing production code. The loop must reproduce the user's symptom, not a nearby failure.

Try these seams in order:

1. Failing test at the smallest public interface that reaches the complete bug pattern,
   including interactions between callers when relevant.
2. CLI or script invocation with fixture input and asserted output.
3. Curl or HTTP request against a local server with asserted response, logs, or state.
4. Browser automation for UI bugs with DOM, console, and network assertions.
5. Replayed trace, event payload, HAR, or log fixture through the real code path.
6. Throwaway harness that boots the minimal subsystem needed to trigger the path.
7. Property, fuzz, or stress loop for intermittent failures.
8. `git bisect run` harness when the bug appeared between known good and bad revisions.

Improve the loop before moving on:

- Make it faster by narrowing setup and caching expensive fixtures.
- Make it sharper by asserting the exact symptom.
- Make it more deterministic by pinning time, seeds, filesystem paths, and network access.
- For intermittent bugs, raise reproduction rate with repeated runs, concurrency, stress, or
  timing probes until the failure is frequent enough to debug.

If no credible loop can be built, stop and state what was tried. Request the missing artifact:
environment access, captured payloads, logs, screen recording with timestamps, or permission
for temporary instrumentation. Do not proceed to speculative fixes.

### Phase 3: Evidence Analysis

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

### Phase 4: Hypothesis Generation

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

### Phase 5: Investigation Plan

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

### Phase 6: Execution

Execute the investigation plan, updating hypotheses as evidence arrives:

1. **Test one variable at a time** — Changing multiple things simultaneously makes
   results uninterpretable.
2. **Record results** — Document what each test revealed, even negative results.
   Dead-end documentation prevents revisiting failed paths.
3. **Update probabilities** — After each test, re-rank hypotheses. If H1 is refuted,
   H2 becomes the new priority.
4. **Know when to escalate** — If all hypotheses are exhausted, the bug is in a
   category you haven't considered. Step back and re-examine assumptions.

### Phase 7: Fix and Regression Proof

Once evidence identifies the cause, select the regression boundary **before the fix**:

1. **Trace the real interaction.** Record the affected callers, shared state or dependency,
   and ordering/concurrency that triggers the defect. Choose a seam that executes that
   interaction through the real implementation, not merely the nearest callable function.
   For example, if preview and submit callers share a cache with an incomplete key, exercise
   both callers against the same cache and assert each caller's correct result. A fresh-cache
   test of preview alone cannot prove that the shared-cache bug is covered.
2. **Assess candidate seams.** Check whether each candidate preserves those callers, state,
   and sequence. Reject a shallow single-caller test or a mock that replaces the defective
   boundary. Keep the smallest seam that reproduces the actual pattern, not the smallest test
   at any cost.
3. **If a correct seam exists, prove red then green.** Turn the minimized reproduction into
   a regression test before changing the implementation. Run it on the defective source and
   capture the actual failure: expected/actual values or state must identify this defect.
   Import errors, setup failures, arbitrary exceptions, test names, or execution alone are
   not red evidence. Fix the causal boundary and rerun the same defect-specific assertions;
   record the observed pass. Exercise every implicated caller, including unaffected/control
   behavior needed to distinguish the defect from a blanket workaround.
4. **If no correct seam exists, report that finding.** List the candidate seams attempted,
   the interaction each cannot reach, and the architectural or access limitation. Distinguish
   an architecture with no usable seam from a seam whose execution is blocked by missing
   tools, fixtures, permission, or environment access. Do not invent a shallow regression
   test or claim regression protection. With a credible Phase 2 loop and established cause,
   a fix may still be evaluated through that loop; absence of a regression seam remains an
   explicit limitation, not an excuse for speculative success.

**Conditional forced-red check:** A natural pre-fix red needs no mutation. If intentionally
reintroducing a defect or mutating a fixture to assess test sensitivity, preserve a pristine
pre-mutation copy of the actual current source/fixture (including unrelated edits). Compare
the mutated content against that copy **before interpreting any test outcome**, and identify
the intended changed lines and exercised path. A no-op replacement, changed unused file, or
unrelated difference is invalid mutation evidence, even when a test passes or fails. Repair
the mutation and establish the comparison before retrying, or report sensitivity unproven.
A valid mutation must fail on the defect-specific assertion, not a syntax/setup error.
Restore the exact pre-mutation content afterward, including after interruption or failure;
compare against the preserved copy and rerun the restored test. Report any restoration or
execution block explicitly. Mutation supplements, rather than substitutes for, natural
pre-fix red/green evidence; do not require it for every fix.

### Phase 8: Original Scenario, Cleanup and Resolution

Before declaring the bug resolved:

1. **Original scenario** — Rerun the saved, unminimized Phase 2 scenario with its original
   caller sequence and relevant environment, asserting the Phase 1 expected outcome.
   A passing minimized/unit test alone is insufficient. If this cannot run, state the
   missing prerequisite and mark original-scenario resolution unverified.
2. **Cleanup** — Remove temporary diagnostic logging, breakpoints, probes and throwaway
   harnesses. Inspect the touched paths for the instrumentation identifiers used; preserve
   unrelated/user instrumentation. Keep the permanent regression test and necessary fixtures.
   After cleanup, rerun the regression (when a seam exists) and original scenario against the
   final source so temporary instrumentation cannot be the reason they passed.
3. **Resolution evidence** — State the confirmed cause, causal fix, regression boundary and
   observed red/green results (or explicit no-seam/blocked finding), original-scenario outcome,
   and cleanup/restoration status. Separate executed evidence from proposed commands and
   inferred outcomes. Never report an unrun or invalid check as success.
4. **Prevention and lessons** — Explain how recurrence is covered or what architectural
   limitation prevents coverage, and what was learned beyond this specific bug.

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
```

### Resolution

**Root cause:** {What was wrong}
**Fix:** {What was changed — file:line, diff summary}
**Regression boundary:** {Callers, shared state, trigger sequence, and why this seam reaches them; or attempted seams and explicit limitation}
**Red / green:** {Observed defect-specific pre-fix failure and post-fix result; or blocked/unobserved}
**Forced mutation, if used:** {Pristine comparison, exercised change, assertion outcome, restoration comparison and restored result}
**Original scenario:** {Unminimized invocation, expected/actual outcome on final source; or missing prerequisite}
**Cleanup:** {Temporary instrumentation/harness removal and final-source rerun results}
**Prevention:** {Permanent regression coverage or documented no-seam limit}
**Lessons:** {What generalizes beyond this bug}
````

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
5. **Feedback loop before hypotheses.** If you cannot reproduce the bug with a controlled
   pass/fail signal, any fix is speculative. Invest in the loop first.
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
