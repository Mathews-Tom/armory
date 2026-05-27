---
name: intent-discipline
type: rule
description: >
  Behavioral guardrails keeping coding agents honest about intent, scope,
  and verifiability. Forces explicit assumption surfacing on ambiguous
  requests, minimum-viable code over speculative abstractions, surgical
  diffs that trace every changed line to the request, and conversion of
  imperative tasks ("fix it", "make it faster") into verifiable success
  criteria the agent can loop against. Counters silent assumption-running,
  bloated abstractions, drive-by refactors, and weak success criteria.
  Use on non-trivial dev, refactor, or review work where scope creep or
  misinterpreted intent would be costly. Triggers on: "intent discipline",
  "surface assumptions", "stop overengineering", "scope creep", "surgical
  changes", "minimum viable code", "goal-driven", "verifiable success
  criteria", "stay surgical", "no drive-by refactor", "ambiguous request",
  "multiple interpretations", "push back when warranted", "Karpathy
  guidelines".
metadata:
  version: 1.0.0
  scope: global
  applies_to:
    languages: ["*"]
  category: development
  tags: [intent, scope, simplicity, surgical-edits, verifiability, karpathy]
  difficulty: beginner
---

# Intent Discipline

Behavioral guardrails for coding agents to honor user intent over agent ambition. Counters four failure modes documented in [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM coding pitfalls: silent assumption-running, bloated abstractions, drive-by refactors, and weak success criteria.

**Tradeoff:** This rule biases toward caution over speed. For trivial tasks (typo fixes, one-line tweaks, obvious renames), apply judgment — not every change needs the full rigor. See [When NOT to Apply](#when-not-to-apply).

## When to Use This Rule vs Related Rules

| Concern                                  | Use this rule         | Use instead                                       |
| ---------------------------------------- | --------------------- | ------------------------------------------------- |
| Scope creep, drive-by refactors          | intent-discipline §3  | —                                                 |
| Ambiguous user request                   | intent-discipline §1  | —                                                 |
| Premature abstraction                    | intent-discipline §2  | —                                                 |
| Test-first execution mechanics           | intent-discipline §4  | `test-standards` (coverage thresholds, fixtures)  |
| Diff traceability in commit message      | intent-discipline §3  | `commit-standards` (message format, footers)      |
| Token-efficient tool calls               | —                     | `token-efficiency`                                |
| Reasoning depth control                  | —                     | `adaptive-thinking-control`                       |

## 1. Surface Intent Before Implementation

**Don't assume. Don't hide confusion. Don't pick silently.**

Before writing or modifying code:

- **State assumptions explicitly.** If a request leaves a decision implicit (scope, format, target, edge cases), name the assumption you would otherwise run with.
- **Present multiple interpretations.** When a request admits more than one reasonable reading, list them with the tradeoff for each — do not pick one silently.
- **Push back when warranted.** If a simpler approach exists, propose it before implementing the requested one. The user can still choose the original.
- **Stop when confused.** Name what is unclear and ask. A 30-second clarifying question is cheaper than a 30-minute wrong implementation.

```
# wrong — silent assumption
User: "Add a feature to export users"
Agent: <writes export_all_users_to_csv_file()>

# right — surfaces assumptions
Agent: "Before implementing:
  - Scope: all users, or filtered subset? (privacy implications)
  - Format: file download, background job, or API endpoint?
  - Fields: which user fields are safe to include?
  - Volume: rough scale — affects pagination vs streaming.
  Default I'd pick: paginated JSON API endpoint, opt-in fields.
  Confirm or correct?"
```

**Test:** Could a senior reviewer say "you guessed wrong on X"? If yes, the assumption was implicit — surface it before coding.

## 2. Minimum Viable Implementation

**Write the smallest code that solves the stated problem. Nothing speculative.**

- **No features beyond what was asked.** Adjacent features the user did not request stay unimplemented.
- **No abstractions for single-use code.** Base classes, strategy patterns, config objects, and protocols for one call site are noise — inline instead. Refactor when the second call site appears, not before.
- **No "flexibility" or "configurability" not requested.** Parameters with default values that no caller sets are dead surface area.
- **No error handling for impossible scenarios.** Validate at system boundaries (user input, external APIs). Internal calls trust contracts.
- **200 → 50 line test.** If the implementation runs 200 lines and could plausibly be 50, rewrite it before reporting done.

```python
# wrong — overengineered for a single use case
class DiscountStrategy(ABC): ...
class PercentageDiscount(DiscountStrategy): ...
class DiscountCalculator:
    def __init__(self, config: DiscountConfig): ...
# 50+ lines for a multiplication.

# right — solves the actual request
def calculate_discount(amount: float, percent: float) -> float:
    return amount * (percent / 100)
```

**Test:** Would a senior engineer say this is overcomplicated? If yes, simplify before submitting.

## 3. Surgical Changes

**Touch only what the request requires. Clean up only your own mess.**

When editing existing code:

- **No "improvement" of adjacent code, comments, or formatting.** Match the file's existing style even when it diverges from your preference.
- **No refactoring of code that isn't broken.** If you notice unrelated dead code, weak validation, or outdated comments, mention them in the response — do not include them in the diff.
- **No quote-style, type-hint, docstring-format, or whitespace drift.** Conventions follow the file, not global defaults.

When your changes create orphans:

- **Remove imports/variables/functions that YOUR changes made unused.** Pre-existing dead code stays unless explicitly asked.
- **A pre-refactor cleanup is a separate commit, stated in advance.**

**Test:** Every added, removed, or modified line in the diff traces directly to the user's request. If a line does not, it does not ship.

This rule pairs with `commit-standards` (one logical change per commit) — surgical diffs make conventional commit messages honest.

## 4. Verifiable Goals Over Imperatives

**Convert imperative tasks into success criteria. Loop until the criteria are met.**

Strong success criteria let the agent execute independently. Weak criteria ("make it work", "fix it") force re-clarification mid-execution.

| Instead of...        | Convert to...                                                          |
| -------------------- | ---------------------------------------------------------------------- |
| "Add validation"     | "Write tests for invalid inputs (empty, oversized, malformed), then make them pass" |
| "Fix the bug"        | "Write a test that reproduces the bug, then make it pass"              |
| "Refactor X"         | "Confirm tests pass before and after; no public API change"            |
| "Make it faster"     | "Reduce p95 latency on benchmark Y from N ms to ≤M ms"                 |
| "Clean this up"      | "Reduce file LOC by ≥X% while keeping all tests green"                 |

For multi-step tasks, state a brief plan with explicit verification per step:

```
1. <step>     → verify: <check that proves the step succeeded>
2. <step>     → verify: <check>
3. <step>     → verify: <check>
```

The verify column is non-optional. A step without verification is a step that cannot be looped on.

This rule defines the framing; `test-standards` defines the test-quality bar (naming, AAA structure, coverage thresholds) and `tdd` skill defines the red-green-refactor mechanics.

## When NOT to Apply

Apply judgment, not the full rigor, for:

- **Typo fixes, one-line tweaks, obvious renames** — surfacing assumptions is overhead with no payoff.
- **Local exploratory edits the user will review immediately** — interactive iteration replaces upfront clarification.
- **Throwaway scripts with no second reader** — speculative-feature checks still apply, but interpretation checks can relax.

The rule applies when: the change is non-trivial, will be reviewed asynchronously, touches production code paths, or is delegated to an autonomous agent loop.

## Rationalizations to Reject

| Excuse                                                | Rebuttal                                                                                  |
| ----------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| "I added the abstraction to make future changes easier." | Future changes have not happened. Inline now; refactor when the second call site appears. |
| "I cleaned up the adjacent code while I was there."   | The diff is now untraceable. Move the cleanup to a separate commit or revert it.          |
| "The user probably meant X."                          | Probably is not certainty. State the assumption explicitly; let the user confirm.         |
| "It's only 50 extra lines."                           | Fifty lines are fifty more to review, test, and maintain. Cut them.                       |
| "I added error handling defensively."                 | Defensively against what? If the failure mode is impossible, the handler hides bugs.      |
| "Tests are obvious; the change is small."             | Then writing the tests is also small. Goal-driven execution needs a verification anchor.  |

## Red Flags

Observable patterns that indicate this rule is being violated:

- Diff includes file changes the user did not name and the agent did not surface.
- Initial response is a code block with no clarifying questions on an ambiguous request.
- Pull request description says "also refactored X for clarity" but X was not in the scope.
- Implementation introduces a base class, factory, or strategy pattern with one concrete implementation.
- Task is reported "done" but the verification step is "looks good" or "should work" — no executable check.
- Comments include "for future flexibility", "in case we need it", or "TODO: extend later".

## Attribution

The four principles distilled here are derived from Andrej Karpathy's [public observations](https://x.com/karpathy/status/2015883857489522876) on common LLM coding failure modes. The framework was first packaged for Claude Code by [forrestchang/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (MIT). This armory rule adapts the principles into armory's `RULE.md` format, cross-references existing armory rules to avoid duplication, adds explicit "when NOT to apply" guidance, and tightens the rationalization and red-flag inventories.
