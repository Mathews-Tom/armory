---
name: estimate-calibrator
description: 'Produces calibrated three-point PERT estimates (best/likely/worst) with confidence intervals, unknowns, and assumptions. Triggers on: "estimate this", "how long will this take", "effort estimate", "confidence interval", "story points", "t-shirt sizing". NOT for task decomposition, use task-decomposer.'
metadata:
  version: 1.1.1
  category: development
  tags: [estimation, pert, confidence-interval, planning]
  difficulty: intermediate
  phase: plan
---

# Estimate Calibrator

Replaces single-point guesses with structured three-point estimates: decomposes work
into atomic units, estimates best/likely/worst case for each, identifies unknowns and
assumptions, calculates aggregate ranges using PERT, and assigns confidence levels with
explicit rationale.

## Reference Files

| File                               | Contents                                                                  | Load When              |
| ---------------------------------- | ------------------------------------------------------------------------- | ---------------------- |
| `references/estimation-methods.md` | PERT formula, three-point estimation, Monte Carlo basics                  | Always                 |
| `references/unknown-categories.md` | Technical, scope, external, and organizational uncertainty types          | Unknown identification |
| `references/calibration-tips.md`   | Cognitive biases in estimation, historical calibration, buffer strategies | Always                 |
| `references/sizing-heuristics.md`  | Common task size patterns, complexity indicators, reference class data    | Quick sizing needed    |

## Prerequisites

- Work item description (feature, task, project)
- Decomposed tasks (or use task-decomposer skill first)
- Context: team familiarity, tech stack, existing codebase

## Workflow

### Phase 1: Decompose Work

If the work item is not already decomposed into atomic units:

1. **Break into tasks** — Each task should be estimable independently.
2. **Right granularity** — Tasks should be 1 hour to 3 days. Larger tasks have higher
   uncertainty; break them down further.
3. **Identify dependencies** — Tasks on the critical path determine the minimum duration.

### Phase 2: Three-Point Estimate

For each task, estimate three scenarios:

| Scenario    | Definition                              | Mindset                                       |
| ----------- | --------------------------------------- | --------------------------------------------- |
| Best case   | Everything goes right. No surprises.    | "If I've done this exact thing before"        |
| Likely case | Normal friction. Some minor obstacles.  | "Realistic expectation with typical setbacks" |
| Worst case  | Significant problems. Not catastrophic. | "Murphy's law but not a disaster"             |

**Key rule:** Worst case is NOT "everything goes wrong." It's the realistic bad scenario
(90th percentile), not the apocalyptic one (99th percentile).

### Phase 3: Identify Unknowns

Categorize unknowns that affect estimates:

| Category       | Example                               | Impact                                       |
| -------------- | ------------------------------------- | -------------------------------------------- |
| Technical      | "Never used this library before"      | Likely case inflated, worst case much higher |
| Scope          | "Requirements may change"             | All estimates may shift                      |
| External       | "Depends on API access from partner"  | Blocking risk — could delay entirely         |
| Integration    | "Haven't tested with production data" | Hidden complexity at integration             |
| Organizational | "Need design approval"                | Calendar time, not effort time               |

### Phase 4: Calculate Ranges

For individual tasks, use the PERT formula:

```text
Expected = (Best + 4 × Likely + Worst) / 6
Std Dev = (Worst - Best) / 6
```

For aggregate (project) estimates:

- **Sum of expected values** for total expected duration
- **Root sum of squares of std devs** for aggregate uncertainty

### Phase 5: Assign Confidence

| Confidence | Meaning                          | When                                          |
| ---------- | -------------------------------- | --------------------------------------------- |
| High       | Likely case within ±20%          | Well-understood task, team has done it before |
| Medium     | Likely case within ±50%          | Some unknowns, moderate familiarity           |
| Low        | Likely case within ±100% or more | Significant unknowns, new technology          |

## Output Format

```text
## Estimate: {Work Item}

### Summary
| Scenario | Duration |
|----------|----------|
| Best case | {time} |
| Likely case | {time} |
| Worst case | {time} |
| **PERT expected** | **{time}** |
| **Confidence** | **{High/Medium/Low}** |

### Task-Level Estimates

| # | Task | Best | Likely | Worst | PERT | Unknowns |
|---|------|------|--------|-------|------|----------|
| 1 | {task} | {time} | {time} | {time} | {time} | {key unknown or "None"} |
| 2 | {task} | {time} | {time} | {time} | {time} | {key unknown} |
| | **Total** | **{sum}** | **{sum}** | **{sum}** | **{pert}** | |

### Key Unknowns

| # | Unknown | Category | Impact on Estimate | Mitigation |
|---|---------|----------|-------------------|------------|
| 1 | {unknown} | {Technical/Scope/External} | +{time} if realized | {spike, prototype, early test} |

### Assumptions
- {Assumption 1 — what must be true for this estimate to hold}
- {Assumption 2}

### Risk Factors
- {Risk}: If realized, adds {time}. Likelihood: {High/Medium/Low}.

### Confidence Rationale
**{High/Medium/Low}** because:
- {Specific reason — e.g., "Team has built 3 similar features"}
- {Specific reason — e.g., "External API is a new integration"}

### Recommendation
{Commit to PERT expected with {X}% buffer, or spike the top unknown first.}
```

## Calibration Rules

1. **Three points, not one.** Single-point estimates are always wrong. Three points
   communicate uncertainty — the most important part of any estimate.
2. **Worst case is the 90th percentile, not the 99th.** "Asteroid hits the office" is
   not a useful worst case. "The API documentation is wrong and we need to reverse-engineer
   the protocol" is realistic worst case.
3. **Unknowns inflate estimates more than known difficulty.** A hard but well-understood
   task is more predictable than an easy but novel one.
4. **Estimates are not commitments.** Communicate ranges, not deadlines. If stakeholders
   need a single number, give the PERT expected plus a buffer for confidence level.
5. **Spike unknowns early.** If a single unknown dominates the estimate range, invest
   1-2 days spiking it before estimating the rest.

## Error Handling

| Problem                               | Resolution                                                                                          |
| ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Work item not decomposed              | Decompose into 3-8 tasks first (or suggest task-decomposer skill).                                  |
| No historical reference               | Estimate relative to a known task: "This is about 2x the auth feature."                             |
| Stakeholder wants a single number     | Provide PERT expected with buffer matching confidence level (High: +20%, Medium: +50%, Low: +100%). |
| Estimate seems too large              | Check for scope creep in task list. Remove non-essential tasks. Identify what can be deferred.      |
| Team has never done this type of work | Mark confidence as Low. Recommend a spike before committing to an estimate.                         |

## When NOT to Estimate

Push back if:

- The work is exploratory (research, spikes) — timebox instead of estimating
- Requirements are completely undefined — define scope first
- The user wants precision (hours) for a large project — provide ranges, not false precision
- The estimate will be used as a commitment without acknowledging uncertainty
