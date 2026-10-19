---
name: evolve
type: command
description:
  'Co-evolutionary skill generation command. Given a task domain or research paper,
  generates a complete skill package through automated generate-verify-refine loops.
  Wraps the test-engineer agent for one-shot skill creation. Supports paper-to-skill
  conversion via arXiv URLs and optional Haiku distillation. Triggers on: "/evolve",
  "evolve a skill", "generate skill from paper", "auto-generate skill", "create skill
  via evolution", "evo-skill command". Use this command for streamlined skill creation
  rather than invoking the full test-engineer agent workflow manually. NOT for running
  application tests (use /tdd). NOT for security scanning (use /security-scan).

  '
metadata:
  version: 1.0.1
  category: meta
  tags: [evolution, skill-generation, co-evolutionary, command]
  difficulty: intermediate
command:
  syntax: /evolve <domain-or-paper-url> [--budget N] [--distill] [--dry-run]
  handler: inline
  dependencies: [test-engineer]
---

# Evolve — Co-Evolutionary Skill Generation

When the user invokes `/evolve <target>`, execute this workflow.

## Step 1: Parse Target

Determine the target type from the argument:

| Argument Pattern                       | Target Type  | Route To                            |
| -------------------------------------- | ------------ | ----------------------------------- |
| arXiv ID (e.g., `2604.01687`)          | Paper        | Paper-to-skill pipeline (Step 2A)   |
| arXiv URL (`arxiv.org/abs/...`)        | Paper        | Paper-to-skill pipeline (Step 2A)   |
| URL ending in `.pdf`                   | Paper        | Paper-to-skill pipeline (Step 2A)   |
| Natural language domain description    | Domain       | Direct evolution (Step 2B)          |
| Path to existing skill (`skills/...`)  | Existing     | Improvement evolution (Step 2C)     |

Parse optional flags:
- `--budget N` — Override max oracle rounds (default: 5)
- `--distill` — Run skill-distiller after evolution to produce Haiku-compatible version
- `--dry-run` — Generate the skill specification only; do not run the evolution loop

## Step 2A: Paper Route

If the target is a paper:

1. Invoke the `paper-to-skill` skill with the paper URL/ID
2. The skill handles: paper intake → critical analysis → specification extraction → test-engineer handoff
3. Skip to Step 3

## Step 2B: Domain Route

If the target is a domain description:

1. Invoke the `test-engineer` agent with:
   - Task domain: the user's description
   - Budget: from `--budget` flag or default
2. The agent runs the full co-evolutionary loop
3. Skip to Step 3

## Step 2C: Improvement Route

If the target is an existing skill path:

1. Verify the skill exists and read its current SKILL.md
2. Invoke the `test-engineer` agent with:
   - Existing skill path: the provided path
   - Budget: from `--budget` flag or default
3. The agent reads the existing skill as v0 and improves it
4. Skip to Step 3

## Step 3: Post-Evolution

After the test-engineer completes:

1. Report the results:
   - Package path
   - Actual report-v2 static conformance and evidence, separate authored findings/resolutions, and live effectiveness NOT_MEASURED (package-evaluator 2.0.0 contract)
   - Oracle verdict and number of evolution rounds
   - Key improvements made
   - Missing evaluator/review prerequisites or unresolved CRITICAL/HIGH findings block acceptance; do not substitute oracle scores or invent evaluator scores
2. If `--distill` was specified:
   - Invoke the `skill-distiller` skill on the generated package
   - Report the cross-model comparison
3. If `--dry-run` was specified:
   - Output the skill specification only
   - Do not write files or run the evolution loop

## Step 4: Validation

Run the standard validation suite on the generated skill:

```bash
uv run python scripts/validate_evals.py
uv run python scripts/validate_frontmatter.py
uv run python scripts/validate_references.py
uv run python scripts/generate_manifest.py
```

Report any validation failures to the user.

## Termination Criteria

The command completes when:
- The skill passes all validation checks, has actual report-v2 static PASS AND no unresolved CRITICAL/HIGH authored findings, and the independent oracle accepts it, OR
- The evolution budget is exhausted (report best-scoring iteration), OR
- `--dry-run` mode outputs the specification

## Rules

1. Always confirm the target type with the user before starting evolution
2. For paper targets, show the extracted specification before proceeding to generation
3. Never skip validation (Step 4) even if the oracle passes
4. If the evolution budget is exhausted, clearly communicate that manual review is recommended
5. The `--distill` flag adds a post-processing step; it does not change the evolution loop
