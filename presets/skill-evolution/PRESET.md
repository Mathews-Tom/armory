---
name: skill-evolution
type: preset
description:
  'Skill generation and co-evolutionary refinement tools. Bundles the test-engineer
  agent (co-evolutionary loop), surrogate-verifier (isolated assertion generation),
  skill-distiller (Opus-to-Haiku conversion), paper-to-skill (research-to-skill
  pipeline), plus supporting skills (package-evaluator, immune, research-critique)
  and the /evolve command. Installs the complete EvoSkills-inspired skill factory.
  Triggers on: "install skill evolution", "set up skill generation", "install evo-skill
  tools", "skill factory preset", "co-evolutionary tools", "install skill refinement
  pipeline". Use this preset when building an autonomous skill generation pipeline or
  when you want to automatically create, test, and refine skill packages.

  '
metadata:
  version: 1.0.1
  category: meta
  tags: [evolution, skill-generation, co-evolutionary, pipeline]
  difficulty: advanced
preset:
  packages:
    skills:
      - { name: surrogate-verifier }
      - { name: skill-distiller }
      - { name: paper-to-skill }
      - { name: package-evaluator }
      - { name: immune }
      - { name: research-critique }
    agents:
      - { name: test-engineer }
    commands:
      - { name: evolve }
  compatibility:
    platforms: [darwin, linux]
---

# Skill Evolution Preset

An autonomous skill factory powered by co-evolutionary refinement. Installs the
complete pipeline from the EvoSkills paper (arXiv 2604.01687): generate skills,
verify them in isolated sessions, test against ground-truth oracles, and refine
until convergence.

## Included Packages

| Type    | Package              | Role                                                      |
| ------- | -------------------- | --------------------------------------------------------- |
| Agent   | test-engineer        | Orchestrates the co-evolutionary generate-verify-refine loop |
| Skill   | surrogate-verifier   | Generates assertions and diagnostics in isolated sessions |
| Skill   | skill-distiller      | Converts Opus skills to Haiku-executable workflows        |
| Skill   | paper-to-skill       | Extracts methodologies from papers into skill specs       |
| Skill   | package-evaluator    | Report-v2 static conformance and separate authored review |
| Skill   | immune               | Adaptive cheatsheet/antibody memory system                |
| Skill   | research-critique    | Critical analysis of research papers                      |
| Command | evolve               | One-shot skill generation via `/evolve <domain>`          |

## Workflow

1. **Create** — `/evolve <domain>` or `/evolve <arxiv-url>` to start skill generation
2. **Generate** — test-engineer produces the initial skill with immune cheatsheet injection
3. **Verify** — surrogate-verifier generates assertions in an isolated session
4. **Test** — Ground-truth oracle executes the skill and checks assertions
5. **Refine** — Diagnostics from failed assertions drive targeted improvements
6. **Distill** — Optional `--distill` flag produces Haiku-compatible version
7. **Finalize** — Final package passes validators, actual report-v2 static conformance is PASS, and no CRITICAL/HIGH authored findings remain. Live effectiveness stays NOT_MEASURED; oracle assertion results are separate evidence, not evaluator scores.

## When to Install

- Building an automated skill generation pipeline
- Converting research papers into reusable skills
- Improving existing skills through systematic refinement
- Creating Haiku-optimized versions of complex skills

## Prerequisites

- Claude Code CLI (`claude`) for oracle execution in `scripts/run_evals.py`
- Python 3.12+ with `uv` for running validation scripts
