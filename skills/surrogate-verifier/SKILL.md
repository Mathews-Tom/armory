---
name: surrogate-verifier
description: 'Generates structured test assertions and failure diagnostics for skill packages from a definition and task prompt. Triggers on: "verify this skill", "generate assertions", "surrogate verification", "diagnose skill failure". NOT for code review, use pr-review.'
metadata:
  version: 1.0.1
  category: review
  tags: [verification, assertions, testing, co-evolution, diagnostics, eval]
  difficulty: advanced
  phase: verify
---

# Surrogate Verifier

Generate structured test assertions and failure diagnostics for skill packages through
information-isolated verification. The verifier operates without access to the skill
generator's reasoning — it sees only the skill definition, a task prompt, and the
output artifacts. This isolation prevents confirmation bias and is the single largest
contributor to skill quality in co-evolutionary generation (+30pp per EvoSkills).

## Reference Files

| File                                | Contents                                                         | Load When                      |
| ----------------------------------- | ---------------------------------------------------------------- | ------------------------------ |
| `references/assertion-patterns.md`  | Assertion catalog by skill category with weight guidance          | Always                         |
| `references/diagnostic-templates.md`| Failure diagnostic templates with root-cause categories           | When producing failure reports  |

## Information Isolation Protocol

This is the most critical constraint. Violating isolation degrades verification quality.

**The verifier MUST NOT access:**
- The generator's conversation history or reasoning chain
- Prior evolution iterations or refinement context
- The generator's internal notes or decision rationale
- Any context beyond what is explicitly listed below

**The verifier receives ONLY:**
1. The skill's `SKILL.md` content (the definition file)
2. One or more task prompts representing intended use
3. The skill's output (when diagnosing failures)
4. The assertion results from `scripts/eval_assertions.py` (when diagnosing)

**Implementation:** When invoked by the `test-engineer` agent, this skill MUST be loaded
into a **separate Agent spawn** using `isolation: "worktree"` or at minimum a fresh session
with no shared context. The invoking agent passes artifacts as explicit text, not as
conversation references.

## Workflow

### Mode 1: Assertion Generation

Generate assertions for a skill given its definition and task prompts.

#### Phase 1: Skill Analysis

Read the `SKILL.md` definition and extract:

1. **Stated capabilities** — what the skill claims to do (from description + workflow sections)
2. **Output format** — expected structure of the skill's output (markdown, JSON, tables, etc.)
3. **Error handling** — documented failure modes and recovery paths
4. **Prerequisites** — required tools, dependencies, or context
5. **Trigger boundaries** — what the skill does NOT handle (negative scope)

#### Phase 2: Assertion Design

For each task prompt, generate 5-10 assertions covering these dimensions:

| Dimension             | Assertion Types to Use          | Purpose                                    |
| --------------------- | ------------------------------- | ------------------------------------------ |
| Output completeness   | `contains`, `matches_regex`     | All claimed sections/components present    |
| Format compliance     | `output_format`, `contains`     | Output matches declared structure          |
| Factual signals       | `contains`, `not_contains`      | Key domain terms present, hallmarks absent |
| Tool usage            | `calls_tool`                    | Expected tools were invoked                |
| Negative constraints  | `not_contains`                  | Forbidden patterns absent                  |

**Weight assignment:**
- Output completeness assertions: weight 1.0 (must have)
- Format compliance: weight 0.8 (structural correctness)
- Factual signals: weight 0.6 (content quality)
- Tool usage: weight 0.5 (method verification)
- Negative constraints: weight 0.3 (absence checks are weaker signals)

See `references/assertion-patterns.md` for category-specific assertion catalogs.

#### Phase 3: Output

Produce assertions in the `evals/cases.yaml` schema format:

```yaml
assertions:
  - type: contains
    target: "## Scalability"
    weight: 1.0
  - type: output_format
    target: markdown_table
    weight: 0.8
  - type: not_contains
    target: "TODO"
    weight: 0.3
  - type: calls_tool
    target: Read
    weight: 0.5
```

**Context cap:** Do not consume more than 70% of the available context window. If the
skill definition is very long, focus assertion generation on the workflow phases and
output format sections. Summarize rather than quote verbatim.

### Mode 2: Failure Diagnostics

When an oracle returns `fail`, produce a structured diagnostic explaining why.

#### Input

- The skill's `SKILL.md` (same as Mode 1)
- The task prompt that was executed
- The output that failed
- The assertion results: which passed, which failed, with details

#### Phase 1: Failure Classification

Categorize each failed assertion into a root-cause category:

| Category              | Signal                                                         | Severity   |
| --------------------- | -------------------------------------------------------------- | ---------- |
| Missing capability    | `contains` assertion failed for a claimed feature              | HIGH       |
| Format mismatch       | `output_format` assertion failed                               | HIGH       |
| Incomplete output     | Multiple `contains` assertions failed in the same section      | MEDIUM     |
| Hallucinated content  | `not_contains` assertion failed (forbidden pattern present)    | HIGH       |
| Wrong tool usage      | `calls_tool` assertion failed                                  | MEDIUM     |
| Partial success       | Some assertions in a group pass, others fail                   | LOW        |

#### Phase 2: Root-Cause Analysis

For each failed assertion:
1. Identify the specific section of `SKILL.md` that promises the missing capability
2. Compare what the skill definition instructs vs. what the output actually contains
3. Hypothesize why the gap exists (missing workflow step, ambiguous instruction, wrong tool choice)

#### Phase 3: Remediation Suggestions

For each root cause, produce a concrete, actionable fix:
- **Missing capability:** "Add a workflow step between Phase 2 and Phase 3 that explicitly generates [X]"
- **Format mismatch:** "Change the output format instruction from 'produce a summary' to 'produce a markdown table with columns: [A, B, C]'"
- **Hallucinated content:** "Add a negative constraint in the workflow: 'Do NOT include [X] unless [condition]'"
- **Wrong tool usage:** "Replace 'use Bash to read the file' with 'use the Read tool for file contents'"

#### Phase 4: Diagnostic Output

Produce a structured diagnostic string:

```
DIAGNOSTIC: [skill-name] failed on [task-prompt-summary]

FAILED ASSERTIONS (N/M):
  1. [SEVERITY] type=contains target="..." — Missing capability: [explanation]
  2. [SEVERITY] type=output_format target="..." — Format mismatch: [explanation]

ROOT CAUSES:
  - [category]: [specific explanation with SKILL.md section reference]

REMEDIATION:
  1. [Concrete change to SKILL.md with exact section and wording]
  2. [Concrete change to workflow with step numbers]
```

See `references/diagnostic-templates.md` for worked examples per root-cause category.

## Budget Parameters

Per EvoSkills Algorithm 1:
- **Context cap:** 0.7 (70% of available context window)
- **Max surrogate retries:** 15 per oracle round
- **Max oracle rounds:** 5 (enforced by the orchestrating agent, not the verifier)

The verifier does not track its own budget — the `test-engineer` agent manages iteration limits.

## Limitations

- **No execution capability:** The verifier generates assertions but does not execute them. Execution
  is handled by `scripts/run_evals.py` (the oracle).
- **Text-only verification:** Cannot verify visual outputs, interactive behaviors, or side effects.
  Assertions operate on the textual output only.
- **Single-turn scope:** Each verification is independent. The verifier does not remember prior
  rounds (the orchestrating agent feeds context as needed).
- **Assertion granularity:** The 5 assertion types cover common patterns but not all possible
  verification needs. Custom assertion types require extending `scripts/eval_assertions.py`.

## Error Handling

| Error                         | Resolution                                                      |
| ----------------------------- | --------------------------------------------------------------- |
| Skill definition too large    | Summarize to workflow phases + output format sections only       |
| No assertions generatable     | Return empty assertions list with warning; skill may be too vague |
| Ambiguous output format       | Default to `contains` assertions; avoid `output_format` checks  |
| Context cap exceeded          | Truncate diagnostic detail; preserve failed assertion list       |
