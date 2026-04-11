---
name: code-refiner
description: 'Deep code simplification and refactoring preserving behavior across Python, Go, TypeScript, Rust. Targets complexity, anti-patterns, readability debt. Triggers on: "simplify this code", "refactor for clarity", "reduce complexity", "make this more readable", "tech debt cleanup", "too much nesting".'
metadata:
  version: 1.1.1
  category: review
  tags: [refactoring, code-quality, simplification, readability]
  difficulty: intermediate
  phase: review
---

# Code Refiner

A structured, multi-pass code refinement skill that transforms complex, verbose, or tangled code
into clean, idiomatic, maintainable implementations — without changing what the code does.

## Philosophy

The goal is **not** fewer lines. The goal is code that a tired engineer at 2am can read, understand,
and safely modify. Every change must pass three tests:

1. **Behavioral equivalence** — identical inputs produce identical outputs, side effects, and errors
2. **Cognitive load reduction** — a reader unfamiliar with the code understands it faster after the change
3. **Maintenance leverage** — the change makes future modifications easier, not harder

When clarity and brevity conflict, clarity wins. When idiom and explicitness conflict, consider the
team's experience level. When DRY and locality conflict, prefer locality for code read more than modified.

## Prerequisites

- **git** — used in Phase 1 for scope detection (`git diff`) when the user doesn't specify target files
- **Python 3.10+** — required to run `scripts/complexity_report.py` for quantitative complexity metrics

## Workflow

Follow this sequence. Each phase builds on the previous one. Do not skip phases, but adapt depth
to the scope of the request (a single function gets a lighter pass than a full module).

### Phase 1: Reconnaissance

Before touching anything, build a mental model:

1. **Identify scope** — What files/functions are in play? If the user hasn't specified, check recent
   git modifications: `git diff --name-only HEAD~5` or `git diff --staged --name-only`
2. **Detect language and ecosystem** — Read file extensions, imports, config files (package.json,
   pyproject.toml, go.mod, Cargo.toml). Load the appropriate language reference from
   `references/` if needed for idiom-specific guidance
3. **Read project conventions** — Check for CLAUDE.md, .editorconfig, linter configs (eslint,
   ruff, golangci-lint, clippy). These override generic idiom preferences
4. **Understand test coverage** — Locate test files. If tests exist, note the test runner so you
   can verify behavioral equivalence after changes
5. **Baseline complexity snapshot** — For each target function/method, mentally note:
   - Nesting depth (max indentation levels)
   - Number of branches (if/else/match/switch arms)
   - Number of early returns vs single-exit
   - Parameter count
   - Lines of code
   - Number of responsibilities (does it do more than one thing?)

### Phase 2: Structural Analysis

Identify what's actually wrong before reaching for solutions. Categorize issues by severity:

**Critical** (always fix):

- Dead code (unreachable branches, unused variables/imports)
- Redundant operations (double-checking the same condition, re-computing cached values)
- Logic that can be replaced by a stdlib/language built-in
- Mutation of shared state that could be avoided

**High** (fix unless there's a clear reason not to):

- Functions with >3 levels of nesting
- Functions with >5 parameters
- God functions (>40 lines or >3 responsibilities)
- Repeated code blocks (3+ occurrences of similar logic)
- Inverted or confusing boolean logic
- Stringly-typed enumerations

**Medium** (fix when it improves clarity without adding risk):

- Unclear variable/function names
- Missing or misleading type annotations
- Unnecessary intermediate variables
- Over-abstraction (wrappers that add no value)
- Comments that restate the code instead of explaining _why_

**Low** (fix only in a dedicated cleanup pass):

- Inconsistent formatting (defer to linter)
- Import ordering
- Trailing whitespace, line length

### Phase 3: Refactoring Execution

Apply changes using these tactics, ordered by impact-to-risk ratio:

#### 3a. Eliminate Dead Weight

Remove before restructuring. Less code = less to think about.

- Delete unused imports, variables, functions
- Remove unreachable branches (but verify they're truly unreachable)
- Strip comments that restate the obvious (keep comments that explain _why_)
- Remove no-op wrapper functions that just forward calls

#### 3b. Flatten Structure

Reduce nesting and cognitive load:

- **Guard clauses**: Convert deep `if` nesting to early returns
- **Extract conditions**: Name complex boolean expressions (`is_valid_order = ...`)
- **Decompose loops**: If a loop does filter + transform + accumulate, break it apart
  (or use language-appropriate constructs: list comprehensions, iterators, streams)
- **Invert conditionals**: When the `else` branch is the "happy path", flip it

#### 3c. Consolidate and Name

Make the code's intent visible:

- **Extract functions** for repeated logic or distinct responsibilities
  - Name by _what it accomplishes_, not _how it works_
  - Functions should do one thing at one level of abstraction
- **Replace magic values** with named constants
- **Rename for intent**: `data` → `user_records`, `process` → `validate_and_enqueue`
- **Group related parameters** into a config/options struct when count > 3

#### 3d. Leverage Language Idioms

Apply language-specific patterns (consult `references/<language>.md` for details):

- Python: comprehensions, context managers, dataclasses, structural pattern matching
- Go: table-driven tests, error wrapping, functional options, interface satisfaction
- TypeScript: discriminated unions, branded types, const assertions, satisfies
- Rust: iterator chains, `?` operator, From/Into, newtype pattern

#### 3e. Tighten Types

Types are documentation that the compiler checks:

- Add return type annotations to public functions
- Replace stringly-typed parameters with enums/unions
- Narrow `any`/`interface{}` to specific types where possible
- Use branded/newtype patterns for identifiers that shouldn't be confused

### Phase 4: Verification

**Never skip this phase.** Simplification that breaks behavior is not simplification.

1. **Run existing tests** — If a test suite exists, run it. Report pass/fail.
2. **Run linter/type checker** — If configured, run it. Fix new violations your changes introduced.
3. **Manual trace** — For each refactored function, mentally trace one happy-path and one
   error-path input through the old and new code. Confirm identical behavior.
4. **Side effect audit** — If the original code had side effects (I/O, mutation, logging),
   verify the new code preserves them in the same order and conditions.

If tests fail or behavior diverges: revert the specific change, don't try to fix the test.

### Phase 5: Report

Present changes as a structured summary. This is important — the developer needs to understand
and trust what changed before committing.

For each file modified, provide:

```text
## <filename>

### Changes
- [Critical] Removed unreachable error branch in `parse_config` (dead code after L42 guard)
- [High] Extracted `validate_credentials()` from 60-line `handle_login()` (was 3 responsibilities)
- [Medium] Renamed `d` → `document`, `proc` → `process_batch`

### Complexity Delta
- `handle_login`: 4 levels nesting → 2, 8 branches → 5
- `parse_config`: removed 12 lines of dead code

### Risk Assessment
- Low risk: all changes are structural, no logic modifications
- Tests: 47/47 passing
```

Adjust verbosity to scope. Single-function cleanup gets a one-liner. Multi-file refactor gets the full report.

## Behavioral Constraints

These are hard rules. Do not violate them regardless of how much cleaner the code would look:

1. **Never change observable behavior** — This includes error messages, log output, return values,
   side effect ordering, and exception types
2. **Never remove error handling** — Even if it looks redundant. Defensive code often exists
   for a reason you can't see from the code alone
3. **Never introduce new dependencies** — Simplification adds nothing to the dependency tree
4. **Never refactor code outside the specified scope** — Unless the user explicitly asks for a
   broader pass. Resist the urge to "fix one more thing"
5. **Preserve public API surfaces** — Function signatures, export names, and type definitions
   visible to consumers do not change without explicit user approval
6. **Respect existing tests** — If a test asserts specific behavior, that behavior is a requirement,
   even if it seems wrong. Flag it in the report, don't change it

## Configuring Scope and Aggressiveness

The user may specify different modes. If they don't, default to **standard**.

| Mode       | Scope                          | Severity Threshold       | Test Requirement             |
| ---------- | ------------------------------ | ------------------------ | ---------------------------- |
| `quick`    | Single file or function        | Critical + High only     | Tests recommended            |
| `standard` | Recent git changes             | Critical + High + Medium | Tests required if they exist |
| `deep`     | Entire module/package          | All severities           | Tests mandatory              |
| `surgical` | User-specified lines/functions | All severities           | Manual trace sufficient      |

The user can specify mode by saying things like "just do a quick pass" or "deep clean this module".

## When NOT to Refine

Push back (politely) if:

- The code has no tests and the user wants a deep refactor → suggest writing tests first
- The code is auto-generated (protobuf, OpenAPI, ORM models) → suggest modifying the generator
- The request is really a feature change disguised as "cleanup" → clarify intent
- The code is in a hot path and "simplification" would introduce allocation/copies → flag the tradeoff

## Language References

For language-specific idiom guidance, read the appropriate reference file:

- `references/python.md` — Python-specific patterns, anti-patterns, and stdlib alternatives
- `references/go.md` — Go idioms, error handling patterns, and interface design
- `references/typescript.md` — TypeScript/JavaScript patterns, type narrowing, and module design
- `references/rust.md` — Rust idioms, ownership patterns, and iterator usage

Only load the reference file for the language(s) in the current scope. These provide detailed
pattern catalogs that supplement the general methodology above.

## Rationalizations

| Rationalization | Reality |
|---|---|
| "It's readable enough" | "Enough" is not a standard — if the next developer needs to re-read a function 3 times, it's not readable |
| "Refactoring risks regressions" | Not refactoring risks accumulating debt — run the test suite before and after, that's what tests are for |
| "This is how the codebase has always done it" | Consistency with a bad pattern is still bad — improve incrementally, don't preserve anti-patterns |
| "The performance might get worse" | Benchmark before and after — most readability refactors have zero performance impact; premature optimization is the root of all evil |
| "It's not broken, don't fix it" | Refining isn't fixing — it's making working code maintainable, testable, and understandable for the next person |
| "I'll refactor the whole module later" | Incremental refinement works; big-bang rewrites fail — improve what you touch now |

## Red Flags

- Changing behavior while claiming "just a refactor" — refining must preserve all existing behavior
- Touching code outside the declared scope without justification
- Removing error handling or validation during simplification
- Introducing new abstractions for one-time operations
- Refactoring without running the test suite before and after
- Making style changes to code that wasn't part of the original task

## Verification

- [ ] All existing tests pass before and after refinement
- [ ] No behavioral changes — output/side-effects identical for all inputs
- [ ] Changes stay within declared scope — no drive-by edits to unrelated code
- [ ] Cyclomatic complexity reduced or unchanged — never increased
- [ ] No new abstractions introduced for single-use cases
- [ ] Linter and type checker pass: `ruff check` + `mypy --strict` or `tsc --noEmit` + `eslint`
