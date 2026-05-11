---
name: tdd
type: command
description: 'Test-driven development workflow for functions, modules, or features.
  Guides Claude through the red-green-refactor cycle: understand requirements, write
  a failing test first, implement minimal code to pass, refactor, repeat. Enforces
  test-first discipline with rules for naming, assertion specificity, edge case generation,
  and cycle termination. Triggers on: "/tdd", "test-driven", "write tests first",
  "red green refactor", "TDD workflow", "test first development". Use this command
  when starting implementation work where tests should drive the design.

  '
metadata:
  version: 1.0.0
  category: development
  tags: [tdd, testing, red-green-refactor, test-first]
  difficulty: intermediate
  phase: build
command:
  syntax: /tdd [function-or-module]
  handler: inline
  dependencies: []
---
# TDD — Test-Driven Development Workflow

When the user invokes `/tdd [target]`, execute this workflow exactly.

## Step 1: Understand Requirements

1. Identify the target function, class, or module from the argument.
2. If the argument is ambiguous, search the codebase for matching symbols.
3. Check repo-local agent context before naming tests or interfaces:
   - `docs/agents/domain.md` for domain doc layout
   - `CONTEXT.md` or the relevant context-local glossary for project vocabulary
   - ADRs in the touched area for decisions the tests must respect
4. If the target does not exist yet, ask the user for:
   - Input types and expected output types.
   - One concrete example of expected behavior.
   - Any known constraints or invariants.
5. If the target exists, read its signature, docstring, and callers to infer requirements.
6. State the requirements back in a numbered list. Do not proceed until the user confirms.

## Step 2: Pick One Vertical Slice

Choose one behavior that cuts through the real public interface. Do not write every planned
test first. Each cycle is one tracer bullet:

```text
RED: one behavior test -> GREEN: minimal implementation -> repeat
```

Prefer behavior that proves the path end-to-end before edge cases. Test names should use the
project's domain terms when a glossary exists.

## Step 3: Write One Failing Test (RED)

1. Create the test file if it does not exist. Follow project conventions:
   - Python: `tests/test_{module}.py` or `tests/{module}/test_{name}.py`.
   - TypeScript/JavaScript: `{name}.test.ts` or `__tests__/{name}.test.ts`.
2. Write exactly one test for the current behavior slice.
3. Test naming convention: `test_{behavior}_when_{condition}_returns_{outcome}` (Python) or
   `it('should {behavior} when {condition}')` (JS/TS).
4. Test public behavior, not private implementation. Do not mock internal collaborators.
5. Each assertion tests one behavior. No multi-assertion tests unless testing a composite result.
6. Run the test. Confirm it fails. If it passes before implementation, it is testing
   the wrong thing — delete and rewrite.

## Step 4: Implement Minimal Code (GREEN)

1. Write the minimum code to make all failing tests pass.
2. Do not add functionality beyond what the tests require.
3. Do not optimize. Do not refactor. Do not add error handling the tests do not exercise.
4. Run all tests. Every test must pass.
5. If a test fails, fix the implementation — not the test — unless the test has a specification error.

## Step 5: Refactor

1. With all tests green, refactor the implementation:
   - Extract repeated logic into helpers.
   - Simplify conditionals.
   - Improve naming.
   - Remove dead code.
2. After each refactoring step, re-run all tests. If any test breaks, revert the refactoring step.
3. Do not change test assertions during refactoring. Tests are the specification.

## Step 6: Next Cycle Decision

1. Review the requirements list from Step 1.
2. If uncovered requirements remain, return to Step 2 with the next behavior slice.
3. If all requirements are covered, assess:
   - Are there integration points not yet tested?
   - Are there concurrency or timing edge cases?
   - Are there security-relevant inputs (injection, overflow, traversal)?
4. If additional cycles are warranted, continue. Otherwise, proceed to output.

## Termination Criteria

Stop the TDD cycle when:
- All stated requirements have corresponding passing tests.
- Edge cases for each public function are covered.
- No test is redundant (each tests a unique behavior).
- Coverage of the target module is >= 90% line coverage.

## Output Format

```
## TDD Summary

**Target:** `{function_or_module}`
**Cycles completed:** {N}
**Tests written:** {count}
  - Happy path: {count}
  - Edge cases: {count}
  - Error conditions: {count}
**Test file:** `{path}`
**Implementation file:** `{path}`
**All tests passing:** yes/no

### Remaining gaps
- {any untested scenarios or deferred items}
```

## Rules

- Never write implementation before a failing test exists for that behavior.
- Never batch all tests up front. Use vertical red-green-refactor slices.
- Never modify a test to make it pass — modify the implementation.
- Tests must be deterministic. No randomness, no network calls, no filesystem side effects
  without explicit fixtures or mocks.
- Mock external dependencies at the boundary. Do not mock the unit under test.
- Each cycle should take 2-5 minutes of wall time. If a cycle exceeds this, the scope
  is too large — break the target into smaller units.
