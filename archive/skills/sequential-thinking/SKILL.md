---
name: sequential-thinking
description:
  "DEPRECATED: Opus 4.7's adaptive thinking covers most cases natively. Structured,
  reflective problem-solving through sequential chain-of-thought reasoning that replaced
  the Sequential Thinking MCP server. Retained as a reference pattern when deterministic,
  reviewable reasoning traces are required regardless of the model's adaptive-thinking
  choice.

  "
metadata:
  version: 1.1.1
  status: deprecated
  category: development
  tags: [reasoning, chain-of-thought, analysis, problem-solving]
  difficulty: intermediate
---

> **DEPRECATED** — Opus 4.7 uses adaptive thinking (optional at each step) and Sonnet 4.6
> handles structured chain-of-thought natively. For most tasks, prompting "Think carefully
> and step-by-step; this is harder than it looks" elicits the required depth. This
> methodology is retained as a reference pattern when deterministic, reviewable reasoning
> traces are required (audits, proofs, post-hoc analysis) regardless of the model's
> adaptive-thinking choice.

# Sequential Thinking

Structured, reflective problem-solving methodology that replaces the Sequential Thinking
MCP server's `sequentialthinking` tool with zero-cost instructional prompting.

Replaces: `@modelcontextprotocol/server-sequential-thinking` (1 tool, ~1,800 tokens/turn saved)

## Quick Reference

| Capability               | Old MCP Tool                                              | New Approach                    |
| ------------------------ | --------------------------------------------------------- | ------------------------------- |
| Step-by-step reasoning   | `sequentialthinking(thought, thoughtNumber, ...)`         | Follow methodology below        |
| Thought revision         | `sequentialthinking(isRevision=true, revisesThought=N)`   | Inline revision protocol        |
| Branch exploration       | `sequentialthinking(branchFromThought=N, branchId=...)`   | Branch labeling protocol        |
| Dynamic scope adjustment | `sequentialthinking(needsMoreThoughts=true)`              | Scope reassessment checkpoints  |
| Hypothesis verification  | `sequentialthinking` loop until `nextThoughtNeeded=false` | Verify-before-conclude protocol |

## Prerequisites

None. This skill is pure methodology — no CLI tools, APIs, or authentication required.

## Core Methodology

### Structured Problem Solving Protocol

When facing a complex, multi-step problem, follow this protocol. The key behaviors
that the MCP tool enforced mechanically are now expressed as explicit steps.

#### 1. Scope Assessment

Before diving in, estimate the problem's complexity and declare it explicitly.

> "This requires approximately N steps. Here's my decomposition: ..."

Map the problem into 3–7 sub-goals. If you can't decompose it, that's a signal
the problem needs clarification first — ask before proceeding.

#### 2. Numbered Step Execution

Work through each step with explicit structure:

- **Step N of M** — State the sub-goal for this step
- Show the reasoning or work
- State the intermediate conclusion
- Explicitly connect to the next step: "This means for step N+1, we need to..."

Do not skip ahead. Each step must produce a concrete, verifiable intermediate result.

#### 3. Revision Checkpoints

After every 3–4 steps, perform a mandatory self-check:

> **Checkpoint:** Am I still on the right track?
>
> - Do earlier conclusions still hold given what I've learned?
> - Has the problem scope changed?
> - Are my assumptions still valid?

If revision is needed, be explicit:

> **Revising Step N:** My earlier conclusion that [X] was wrong because [Y].
> The corrected conclusion is [Z]. This affects steps [list downstream impacts].

This replaces the MCP's `isRevision` and `revisesThought` parameters. The key
behavior is: name what changed, why, and what it invalidates downstream.

#### 4. Branch Exploration

When multiple viable approaches exist, don't silently pick one. Make the fork visible:

> **Branch Point** (from Step N):
>
> **Approach A — [Label]:** [Brief description and likely outcome]
> **Approach B — [Label]:** [Brief description and likely outcome]
>
> Evaluating: [1–2 sentence comparison on key trade-off]
> **Committing to Approach [X]** because [rationale].

This replaces the MCP's `branchFromThought` and `branchId` parameters. The value
is making the decision point and rationale explicit, not the mechanical branching.

For especially consequential forks, briefly explore both branches (2–3 steps each)
before committing, rather than choosing upfront.

#### 5. Dynamic Scope Adjustment

If you realize mid-analysis that the problem is larger or smaller than estimated:

> **Scope Update:** Originally estimated N steps, now estimating M because [reason].

This replaces `needsMoreThoughts` and `totalThoughts` adjustment. Don't artificially
compress reasoning to fit an initial estimate — accuracy matters more than prediction.

#### 6. Verification and Conclusion

Before presenting a final answer, always:

1. **Restate** the original problem in your own words
2. **Trace** the solution path: "Steps 1→3→5 established [X], steps 4→6 established [Y]"
3. **Verify** against all stated constraints and requirements
4. **Flag** remaining uncertainties or assumptions
5. **Conclude** only when all constraints are satisfied

> **Verification:** Does this solution satisfy all requirements?
>
> - [Requirement 1]: ✓ Satisfied by [step reference]
> - [Requirement 2]: ✓ Satisfied by [step reference]
> - [Requirement 3]: ⚠ Partially — [explain gap and mitigation]

This replaces the `nextThoughtNeeded=false` terminal condition. The MCP required
explicit signaling that thinking was complete; the methodology achieves this through
the verification checklist.

## Output Format

A sequential thinking session produces output with the following structure:

- **Numbered thoughts** — each labeled `Step N of M` with a sub-goal statement, reasoning, and intermediate conclusion
- **Revision markers** — inline `Revising Step N:` blocks that name what changed, why, and which downstream steps are affected
- **Branch indicators** — `Branch Point (from Step N):` blocks listing approaches with a commitment statement and rationale
- **Scope updates** — `Scope Update:` lines when the estimated step count changes mid-analysis
- **Verification block** — a final checklist confirming each requirement is satisfied, with step references; flags unresolved uncertainties before concluding

## Calibration Rules

- **Match depth to complexity:** Simple problems (single decision, clear constraints) warrant 3-5 thoughts. Moderate problems (multi-step with trade-offs) warrant 5-10. Complex problems (architecture, debugging cascading failures, formal reasoning) warrant 10 or more — do not compress artificially.
- **Revisions signal quality:** A thinking session that revises earlier steps is more reliable than one that proceeds linearly without self-correction. Revision is not failure; it is the methodology working as intended.
- **Prefer depth over breadth:** Explore fewer branches more thoroughly rather than listing many options shallowly. A branch is worth exploring only if the choice between approaches materially changes the outcome.
- **Scope honesty:** If the initial step estimate was wrong, update it explicitly. An accurate mid-course correction is better than forcing conclusions to fit an outdated estimate.

## Common Workflows

### Deep Debugging

When diagnosing a complex bug or system issue:

1. **Reproduce** — State the observed vs expected behavior precisely
2. **Hypothesize** — Generate 2–3 candidate root causes, ranked by likelihood
3. **Narrow** — For the top hypothesis, identify the minimal test that would confirm or refute it
4. **Test** — Execute the test, observe the result
5. **Iterate** — If refuted, move to next hypothesis. If confirmed, trace to root cause
6. **Verify fix** — Confirm the fix addresses the root cause without regression

Use **Branch Exploration** at step 2 to make competing hypotheses explicit.

### Architectural Decision Making

For system design or technology choices:

1. **Frame** — State the decision, constraints, and evaluation criteria with weights
2. **Enumerate** — List viable options (aim for 3–5)
3. **Evaluate** — Score each option against criteria; use a decision matrix
4. **Stress-test** — For the top 1–2 options, probe failure modes and edge cases
5. **Decide** — Commit with explicit rationale and documented trade-offs
6. **Record** — State what would cause you to revisit this decision

### Mathematical / Formal Reasoning

For proofs, derivations, or formal verification:

1. **State** the claim or goal precisely
2. **Identify** the proof strategy (direct, contradiction, induction, construction)
3. **Execute** step by step, with each step justified by a named rule or lemma
4. **Check** each step's validity before proceeding
5. **Verify** the proof is complete (all cases covered, no gaps)

Use **Revision Checkpoints** aggressively — formal reasoning has high cascading-error risk.

## Error Handling

| Problem                                | Cause                                  | Fix                                                                            |
| -------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------ |
| Reasoning goes in circles              | Missing revision checkpoint            | Force a checkpoint: restate goal, check if any step repeated prior conclusions |
| Scope keeps expanding                  | Problem underspecified                 | Pause and decompose into independent sub-problems; solve smallest first        |
| Can't choose between branches          | Evaluation criteria unclear            | Make criteria explicit and weighted before comparing options                   |
| Conclusion doesn't satisfy constraints | Skipped verification step              | Run full verification checklist before presenting answer                       |
| Earlier step invalidated               | New information contradicts assumption | Explicit revision: name the step, the error, and all downstream impacts        |

## Limitations

- **No persistent state across conversations.** The MCP server maintained a thought history
  within a session. This methodology relies on the conversation context window instead,
  which is equivalent within a single conversation but doesn't persist across sessions.
- **No programmatic thought graph.** The MCP returned structured JSON for each thought step,
  which could theoretically be consumed by other tools. The methodology produces natural
  language instead. In practice, the MCP's JSON output was rarely consumed programmatically.
- **Self-discipline required.** The MCP mechanically enforced step numbering and checkpoint
  structure. The methodology relies on Claude following the protocol. In practice, explicit
  instructions are as reliable as tool-call enforcement for reasoning patterns.

## Token Savings Analysis

| Metric               | MCP (per turn)         | Skill (per turn)            | Savings            |
| -------------------- | ---------------------- | --------------------------- | ------------------ |
| Schema overhead      | ~1,800 tokens          | 0 tokens (loaded on demand) | ~1,800 tokens/turn |
| 20-turn conversation | ~36,000 tokens         | ~300 tokens (one-time load) | ~35,700 tokens     |
| Tool call overhead   | ~200 tokens/invocation | 0 (native reasoning)        | ~200 tokens/call   |

The Sequential Thinking MCP is one of the highest-ROI conversions because it consumes
substantial schema tokens on every turn while providing functionality that Claude can
replicate natively through prompting.
