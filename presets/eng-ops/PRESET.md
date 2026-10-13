---
name: eng-ops
type: preset
description:
  "DEPRECATED: Superseded by the ship-workflow skill and the release-captain and
  full-stack-builder agents. ship-workflow ships work through PR, gates, merge, and cleanup.
  release-captain prepares explicitly authorized version and changelog changes with quality
  gates and opens the release PR. full-stack-builder handles implementation with
  test-harness, code-refiner, and api-docs-generator. Use these instead."
metadata:
  version: 1.1.1
  status: deprecated
  category: review
  tags: [engineering, operations, ci-cd, release]
  difficulty: intermediate
preset:
  packages:
    skills:
      - { name: ship-workflow }
      - { name: qa-systematic }
      - { name: test-harness }
      - { name: benchmark-runner }
      - { name: migration-risk-analyzer }
      - { name: estimate-calibrator }
      - { name: engineering-retro }
      - { name: debug-investigator }
  compatibility:
    platforms: [darwin, linux]
---

# Eng Ops

> **DEPRECATED** — The `ship-workflow` skill and the `release-captain` and `full-stack-builder`
> agents supersede this preset. `ship-workflow` (or `/ship`) ships work through PR, current
> gates, merge, and cleanup without changing versions. `release-captain` prepares explicitly
> authorized version and changelog changes with quality gates and stops at the release PR.
> `full-stack-builder` handles implementation with testing, documentation, and code
> refinement. Install these instead.

End-to-end engineering operations toolkit spanning the plan-build-test-ship-reflect lifecycle.

## Included Skills

| Skill                   | Purpose                                        | Phase   |
| ----------------------- | ---------------------------------------------- | ------- |
| ship-workflow           | Ship work from changes to merged and cleaned   | ship    |
| qa-systematic           | Systematic test planning and QA strategy       | plan    |
| test-harness            | Test scaffolding and generation                | test    |
| benchmark-runner        | Performance benchmarking and regression checks | test    |
| migration-risk-analyzer | Migration safety and rollback analysis         | build   |
| estimate-calibrator     | Effort estimation calibration and tracking     | plan    |
| engineering-retro       | Structured engineering retrospectives          | reflect |
| debug-investigator      | Root cause analysis and debugging              | build   |

## Workflow

1. **Plan** — use `estimate-calibrator` to size work and `qa-systematic` to define the
   test strategy before writing code.
2. **Build** — invoke `debug-investigator` for root cause analysis when issues arise.
   Run `migration-risk-analyzer` before applying schema or infrastructure changes.
3. **Test** — generate test scaffolding with `test-harness`. Validate performance
   characteristics with `benchmark-runner`.
4. **Ship** — take work through PR, gates, merge, and cleanup with `ship-workflow`; it never
   changes versions or changelogs.
5. **Reflect** — run `engineering-retro` after a milestone or incident to capture
   lessons learned and action items.

## Choosing the Right Skill

| Situation                                          | Skill                   |
| -------------------------------------------------- | ----------------------- |
| Need to estimate story points or delivery timeline | estimate-calibrator     |
| Designing a test plan for a feature or service     | qa-systematic           |
| Generating test files, fixtures, or boilerplate    | test-harness            |
| Measuring latency, throughput, or memory usage     | benchmark-runner        |
| Evaluating risk of a database or infra migration   | migration-risk-analyzer |
| Tracking down a bug or production incident         | debug-investigator      |
| Shipping a change through PR, merge, and cleanup   | ship-workflow           |
| Running a sprint retro or post-incident review     | engineering-retro       |

## When to Use

- Setting up or improving an engineering team's operational workflow.
- Projects entering a shipping phase that need release coordination.
- Teams adopting structured test planning and QA practices.
- Performance-sensitive services requiring benchmark regression gates.
- Database or infrastructure migrations requiring risk assessment.
- Sprint planning sessions needing calibrated effort estimates.
- Post-incident or post-milestone retrospectives.
- Debugging complex production issues across multiple services.
