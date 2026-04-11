---
name: prompt-lab
description: 'LLM prompt engineering: analyzes failure modes, generates variants (direct, few-shot, CoT), designs rubrics, produces test suites. Triggers on: "prompt engineering", "generate prompt variants", "A/B test prompts", "optimize prompt", "improve this prompt". NOT for SKILL.md files, use skill-evaluator.'
metadata:
  version: 1.1.1
  category: development
  tags: [prompt-engineering, evaluation, few-shot, chain-of-thought]
  difficulty: intermediate
  phase: build
---

# Prompt Lab

Replaces trial-and-error prompt engineering with structured methodology: objective
definition, current prompt analysis, variant generation (instruction clarity, example
strategies, output format specification), evaluation rubric design, test case creation,
and failure mode identification.

## Reference Files

| File                               | Contents                                                                       | Load When                  |
| ---------------------------------- | ------------------------------------------------------------------------------ | -------------------------- |
| `references/prompt-patterns.md`    | Prompt structure catalog: zero-shot, few-shot, CoT, persona, structured output | Always                     |
| `references/evaluation-metrics.md` | Quality metrics (accuracy, format compliance, completeness), rubric design     | Evaluation needed          |
| `references/failure-modes.md`      | Common prompt failure taxonomy, detection strategies, mitigations              | Failure analysis requested |
| `references/output-constraints.md` | Techniques for constraining LLM output format, JSON mode, schema enforcement   | Format control needed      |

## Prerequisites

- Clear objective: what should the prompt accomplish?
- Target model (GPT-4, Claude, open-source) — prompting techniques vary by model
- Current prompt (if improving) or task description (if creating)

## Workflow

### Phase 1: Define Objective

1. **Task specification** — What should the LLM produce? Be specific: "Classify customer
   support tickets into 5 categories" not "Handle support tickets."
2. **Success criteria** — How do you know the output is correct? Define measurable criteria
   before writing any prompt.
3. **Failure modes** — What does a bad output look like? Missing information? Wrong format?
   Hallucinated content? Refusal to answer?

### Phase 2: Analyze Current Prompt

If an existing prompt is provided:

1. **Structure assessment** — Is the instruction clear? Are examples provided? Is the
   output format specified?
2. **Ambiguity detection** — Where could the model misinterpret the instruction?
3. **Missing components** — What's not specified that should be? (output format, tone,
   length constraints, edge case handling)
4. **Failure mode mapping** — Which known failure patterns (see `references/failure-modes.md`)
   apply to this prompt?

### Phase 3: Generate Variants

Create 2-4 prompt variants, each testing a different hypothesis:

| Variant Type       | Hypothesis                           | When to Use                      |
| ------------------ | ------------------------------------ | -------------------------------- |
| Direct instruction | Clear instruction is sufficient      | Simple tasks, capable models     |
| Few-shot           | Examples improve output consistency  | Pattern-following tasks          |
| Chain-of-thought   | Reasoning improves accuracy          | Multi-step logic, math, analysis |
| Persona/role       | Role framing improves tone/expertise | Domain-specific tasks            |
| Structured output  | Format specification prevents errors | JSON, CSV, specific templates    |

For each variant:

- State the hypothesis (why this variant might work)
- Identify the risk (what could go wrong)
- Provide the complete prompt text

### Phase 4: Design Evaluation

1. **Rubric** — Define weighted criteria:

   | Criterion         | What It Measures               | Typical Weight |
   | ----------------- | ------------------------------ | -------------- |
   | Correctness       | Output matches expected answer | 30-50%         |
   | Format compliance | Follows specified structure    | 15-25%         |
   | Completeness      | All required elements present  | 15-25%         |
   | Conciseness       | No unnecessary content         | 5-15%          |
   | Tone/style        | Matches requested voice        | 5-10%          |

2. **Test cases** — Minimum 5 cases covering:
   - Happy path (standard input)
   - Edge cases (unusual but valid input)
   - Adversarial cases (inputs designed to confuse)
   - Boundary cases (minimum/maximum input)

### Phase 5: Output

Present variants, rubric, and test cases in a structured format ready for execution.

## Output Format

```text
## Prompt Lab: {Task Name}

### Objective
{What the prompt should achieve — specific and measurable}

### Success Criteria
- [ ] {Criterion 1 — measurable}
- [ ] {Criterion 2 — measurable}

### Current Prompt Analysis
{If existing prompt provided}
- **Strengths:** {what works}
- **Weaknesses:** {what fails or is ambiguous}
- **Missing:** {what's not specified}

### Variants

#### Variant A: {Strategy Name}
```

{Complete prompt text}

```text
**Hypothesis:** {Why this approach might work}
**Risk:** {What could go wrong}

#### Variant B: {Strategy Name}
```

{Complete prompt text}

```text
**Hypothesis:** {Why this approach might work}
**Risk:** {What could go wrong}

#### Variant C: {Strategy Name}
```

{Complete prompt text}

```text
**Hypothesis:** {Why this approach might work}
**Risk:** {What could go wrong}

### Evaluation Rubric

| Criterion | Weight | Scoring |
|-----------|--------|---------|
| {criterion} | {%} | {how to score: 0-3 scale or pass/fail} |

### Test Cases

| # | Input | Expected Output | Tests Criteria |
|---|-------|-----------------|---------------|
| 1 | {standard input} | {expected} | Correctness, Format |
| 2 | {edge case} | {expected} | Completeness |
| 3 | {adversarial} | {expected} | Robustness |

### Failure Modes to Monitor
- {Failure mode 1}: {detection method}
- {Failure mode 2}: {detection method}

### Recommended Next Steps
1. Run all variants against the test suite
2. Score using the rubric
3. Select the highest-scoring variant
4. Iterate on the winner with targeted improvements
```

## Calibration Rules

1. **One variable per variant.** Each variant should change ONE thing from the baseline.
   Changing instruction style AND examples AND format simultaneously makes results
   uninterpretable.
2. **Test before declaring success.** A prompt that works on 3 examples may fail on the
   4th. Minimum 5 diverse test cases before concluding a variant works.
3. **Failure modes are more valuable than successes.** Understanding WHY a prompt fails
   guides improvement more than confirming it works.
4. **Model-specific optimization.** A prompt optimized for GPT-4 may not work for Claude
   or Llama. Always note the target model.
5. **Simplest effective prompt wins.** If a zero-shot prompt scores as well as a few-shot
   prompt, use the zero-shot. Fewer tokens = lower cost + latency.

## Error Handling

| Problem                                               | Resolution                                                                                    |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| No clear objective                                    | Ask the user to define what "good output" looks like with 2-3 examples.                       |
| Prompt is for a task LLMs are bad at (math, counting) | Flag the limitation. Suggest tool-augmented approaches or pre/post-processing.                |
| Too many variables to test                            | Focus on the highest-impact variable first. Iterative refinement beats combinatorial testing. |
| No existing prompt to analyze                         | Start with the simplest possible prompt. The first variant IS the baseline.                   |
| Output format requirements are strict                 | Use structured output mode (JSON mode, function calling) instead of prompt-only constraints.  |

## When NOT to Use

Push back if:

- The task doesn't need an LLM (deterministic rules, regex, SQL) — use the right tool
- The user wants prompt execution, not design — this skill designs and evaluates, it doesn't run prompts
- The prompt is for safety-critical decisions without human review — LLM output should not be the sole input
