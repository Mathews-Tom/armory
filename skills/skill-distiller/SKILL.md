---
name: skill-distiller
description: 'Converts Opus-quality skills into deterministic Haiku-executable workflows via trace-driven distillation and cross-model validation. Triggers on: "distill this skill", "make this skill work on Haiku", "cross-model optimization", "optimize skill for cost". NOT for code simplification, use code-refiner.'
metadata:
  version: 1.0.1
  category: development
  tags: [distillation, cross-model, optimization, haiku, deterministic]
  difficulty: advanced
  phase: build
---

# Skill Distiller

Transform skills authored for high-capability models (Opus) into deterministic workflows
that execute reliably on lower-cost models (Sonnet, Haiku). The core insight from
EvoSkills: skills encode reusable task structure, not model-specific artifacts. A skill
evolved on Opus transfers with +35-45pp gains to other models — but only when the
instructions are sufficiently deterministic that lower-capability models can follow them
without improvising.

## Reference Files

| File                                   | Contents                                           | Load When                            |
| -------------------------------------- | -------------------------------------------------- | ------------------------------------ |
| `references/distillation-patterns.md`  | Pattern catalog for converting reasoning to rules  | Always                               |

## Prerequisites

- The source skill must exist and pass `package-evaluator` at >= 70%
- Access to both the source model (Opus) and target model (Haiku/Sonnet) for validation
- The `surrogate-verifier` skill for cross-model assertion checking

## Workflow

### Phase 1: Complexity Analysis

Score each section of the source SKILL.md for reasoning difficulty:

| Complexity Signal                     | Score | Distillation Action                          |
| ------------------------------------- | ----- | -------------------------------------------- |
| Decision tree with 3+ branches        | HIGH  | Convert to explicit if/then lookup table     |
| "Use judgment" or "consider context"  | HIGH  | Replace with concrete heuristic rules        |
| Multi-step inference chain            | HIGH  | Break into numbered atomic steps             |
| Reference to domain expertise         | MED   | Add explicit reference file with knowledge   |
| Clear enumerated steps                | LOW   | Keep as-is                                   |
| Concrete examples with expected output| LOW   | Keep as-is                                   |

Produce a complexity map: section name -> complexity score -> planned action.

### Phase 2: Trace Collection

Execute the source skill with Opus on 5 representative tasks:

1. Select tasks from `evals/cases.yaml` (positive cases) or generate new ones
2. For each task, capture the full execution trace:
   - Tool calls made (which tools, in what order)
   - Intermediate reasoning visible in output
   - Final output structure and content
   - Time taken and token usage
3. Store traces as structured data for pattern extraction

### Phase 3: Pattern Extraction

From the collected traces, extract deterministic patterns:

1. **Decision paths** — For each HIGH-complexity section, find the actual decisions Opus made across
   the 5 tasks. If Opus chose the same path in 4/5 cases, that path becomes the default rule
2. **Lookup tables** — Where Opus applied domain knowledge, build explicit lookup tables
   (e.g., "if input contains SQL, use these patterns; if input contains Python, use those")
3. **Concrete examples** — Extract representative input/output pairs from traces to serve as
   few-shot examples in the distilled skill
4. **Tool sequences** — Identify the common tool invocation pattern and make it explicit
   ("Step 1: Read the file. Step 2: Grep for pattern X. Step 3: Write output.")

### Phase 4: Distilled Rewrite

Rewrite the SKILL.md applying all distillation actions from Phase 1:

| Source Pattern                         | Distilled Replacement                                        |
| -------------------------------------- | ------------------------------------------------------------ |
| "Analyze the code and determine..."    | "Check for these 5 specific patterns: [list]"                |
| "Use appropriate formatting"           | "Output as a markdown table with columns: [A, B, C]"        |
| "Consider the context to decide..."    | "If [condition A]: do X. If [condition B]: do Y. Default: Z" |
| "Apply best practices for..."          | Reference file with explicit best practices enumerated       |
| Multi-paragraph reasoning instruction  | Numbered step list with single-sentence steps                |

Rules for the rewrite:
- Every instruction must be actionable by a model with no domain expertise
- No step should require inference — each step's input and output must be explicit
- Replace all "consider", "analyze", "determine" verbs with "check", "count", "list", "output"
- Add concrete examples for any step that could be ambiguous
- Keep the SKILL.md under 500 lines (distillation should reduce, not expand)

### Phase 5: Target Model Validation

Run the distilled skill on the target model (Haiku or Sonnet):

1. Execute the same 5 tasks from Phase 2 with the distilled skill loaded
2. Use the `surrogate-verifier` to generate assertions for each task output
3. Compare pass rates:

| Metric                          | Source (Opus + original) | Target (Haiku + distilled) | Delta |
| ------------------------------- | ------------------------ | -------------------------- | ----- |
| Assertions passed               | N/M                      | N/M                        | ±     |
| Weighted score                  | X.XX                     | X.XX                       | ±     |
| Output completeness             | %                        | %                          | ±     |
| Format compliance               | %                        | %                          | ±     |

4. If target model score < 80% of source model score, iterate:
   - Identify which assertions the target model fails
   - Add more explicit instructions for those specific failure points
   - Re-run validation (max 3 iterations)

### Phase 6: Cross-Model Report

Produce the final comparison:

```markdown
# Skill Distillation Report: <skill-name>

## Complexity Reduction
- Sections distilled: N/M (HIGH → LOW)
- Instruction word count: original X → distilled Y (Z% reduction)
- Decision points replaced with lookup tables: N

## Cross-Model Performance
| Model   | Assertions Passed | Weighted Score | Format Compliance |
|---------|-------------------|----------------|-------------------|
| Opus    | 7/7               | 1.00           | 100%              |
| Sonnet  | 6/7               | 0.92           | 100%              |
| Haiku   | 5/7               | 0.85           | 85%               |

## Changes Made
1. [Section] "Analyze complexity" → explicit 5-item checklist
2. [Section] "Apply formatting" → fixed markdown table template
...

## Recommendation
[SHIP | ITERATE | MANUAL_REVIEW_NEEDED]
```

## Error Handling

| Error                               | Resolution                                                    |
| ----------------------------------- | ------------------------------------------------------------- |
| Source skill scores below 70%       | Refuse distillation; recommend evolution via test-engineer     |
| No execution traces available       | Generate synthetic tasks and collect traces before proceeding  |
| Target model fails all assertions   | Skill may be too complex for target model; report with detail  |
| Distilled skill longer than source  | Review distillation; patterns may need consolidation           |

## Limitations

- Cannot distill skills that rely on extended thinking or multi-turn reasoning
- Visual/interactive skills (HTML generation, browser automation) may not distill well
- Distillation optimizes for determinism, not creativity — skills requiring open-ended generation
  (writing, brainstorming) are poor candidates
- Trace collection requires actual model execution, incurring API costs
