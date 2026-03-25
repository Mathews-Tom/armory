---
name: eng-ops
type: preset
description: "DEPRECATED: Superseded by the release-captain and full-stack-builder agents. release-captain orchestrates ship-workflow, changelog-composer, pre-landing-review, dependency-audit with quality gates. full-stack-builder handles implementation with test-harness, code-refiner, and api-docs-generator. Use these agents instead."
metadata:
  version: 1.1.0
  status: deprecated
preset:
  packages:
    skills:
      - name: ship-workflow
      - name: qa-systematic
      - name: test-harness
      - name: benchmark-runner
      - name: migration-risk-analyzer
      - name: estimate-calibrator
      - name: engineering-retro
      - name: debug-investigator
  compatibility:
    platforms: [darwin, linux]
---

# Eng Ops

> **DEPRECATED** — The `release-captain` and `full-stack-builder` agents supersede this
> preset. `release-captain` manages the ship lifecycle with quality gates (secret scanning,
> pre-landing review, changelog generation, PR creation). `full-stack-builder` handles
> implementation with testing, documentation, and code refinement. Install these agents
> instead.

End-to-end engineering operations toolkit spanning the plan-build-test-ship-reflect lifecycle.

## Included Skills

| Skill                    | Purpose                                        | Phase   |
| ------------------------ | ---------------------------------------------- | ------- |
| ship-workflow            | Orchestrate end-to-end shipping pipeline       | ship    |
| qa-systematic            | Systematic test planning and QA strategy       | plan    |
| test-harness             | Test scaffolding and generation                | test    |
| benchmark-runner         | Performance benchmarking and regression checks | test    |
| migration-risk-analyzer  | Migration safety and rollback analysis         | build   |
| estimate-calibrator      | Effort estimation calibration and tracking     | plan    |
| engineering-retro        | Structured engineering retrospectives          | reflect |
| debug-investigator       | Root cause analysis and debugging              | build   |

## Workflow

1. **Plan** — use `estimate-calibrator` to size work and `qa-systematic` to define the
   test strategy before writing code.
2. **Build** — invoke `debug-investigator` for root cause analysis when issues arise.
   Run `migration-risk-analyzer` before applying schema or infrastructure changes.
3. **Test** — generate test scaffolding with `test-harness`. Validate performance
   characteristics with `benchmark-runner`.
4. **Ship** — orchestrate the release pipeline end-to-end with `ship-workflow`.
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
| Cutting a release or coordinating deploy steps     | ship-workflow           |
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
