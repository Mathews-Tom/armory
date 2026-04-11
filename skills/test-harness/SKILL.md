---
name: test-harness
description: 'Generates pytest test suites with happy path, edge cases, error conditions, fixture scaffolding, mocks, async patterns. Triggers on: "generate tests", "write tests for", "test this function", "create test suite", "pytest for", "unit tests for", "mock strategy for".'
metadata:
  version: 1.1.1
  category: development
  tags: [testing, pytest, test-generation, python]
  difficulty: intermediate
  phase: build
---

# Test Harness

Systematic test suite generation that transforms source code into comprehensive, runnable
pytest files. Analyzes function signatures, dependency graphs, and complexity hotspots to
produce tests covering happy paths, boundary conditions, error states, and async flows —
with properly scoped fixtures and focused mocks.

## Reference Files

| File                             | Contents                                                               | Load When                        |
| -------------------------------- | ---------------------------------------------------------------------- | -------------------------------- |
| `references/pytest-patterns.md`  | Fixture scopes, parametrize, marks, conftest layout, built-in fixtures | Always                           |
| `references/mock-strategies.md`  | Mock decision tree, patch boundaries, assertions, anti-patterns        | Target has external dependencies |
| `references/async-testing.md`    | pytest-asyncio modes, event loop fixtures, async mocking               | Target contains async code       |
| `references/fixture-design.md`   | Factory fixtures, yield teardown, scope selection, composition         | Test requires non-trivial setup  |
| `references/coverage-targets.md` | Threshold table, branch vs line, pytest-cov config, exclusion patterns | Coverage assessment requested    |

## Prerequisites

- **pytest** >= 7.0
- **Python** >= 3.10
- **pytest-asyncio** — required only when generating async tests
- **pytest-mock** — optional, provides `mocker` fixture as alternative to `unittest.mock`

## Workflow

### Phase 1: Reconnaissance

Before writing a single test, build a model of the target code:

1. **Identify scope** — What functions, classes, or modules need tests? If unspecified,
   check for recent modifications: `git diff --name-only HEAD~5`
2. **Read function signatures** — Parameters, types, return types, defaults. Every parameter
   is a test dimension.
3. **Map dependencies** — Which calls go to external systems (DB, API, filesystem, clock)?
   These are mock candidates.
4. **Detect complexity hotspots** — Functions with high branch counts, deep nesting, or
   multiple return paths need more test cases.
5. **Check existing tests** — If tests already exist, understand what they cover. Do not
   duplicate; extend.
6. **Read project conventions** — Check CLAUDE.md, conftest.py, pytest.ini/pyproject.toml
   for fixtures, markers, and test organization patterns already in use.

### Phase 2: Test Case Enumeration

For each function under test, enumerate cases across four categories:

| Category   | What to Test                                   | Example                                     |
| ---------- | ---------------------------------------------- | ------------------------------------------- |
| Happy path | Expected inputs produce expected outputs       | `add(2, 3)` returns `5`                     |
| Boundary   | Edge values at limits of valid input           | Empty string, zero, max int, single element |
| Error      | Invalid inputs trigger proper exceptions       | `None` where `str` expected, negative index |
| State      | State transitions produce correct side effects | Object moves from `pending` to `active`     |

For each case, note:

- Input values (concrete, not abstract)
- Expected output or exception
- Required setup (fixtures)
- Required mocks (external calls to suppress)

Parametrize cases that share the same test logic but differ only in input/output values.

### Phase 3: Fixture Design

1. **Identify shared setup** — If 3+ tests need the same object, extract a fixture.
2. **Select scope** — Use the narrowest scope that avoids redundant setup:

   | Scope      | Use When                                   | Example                      |
   | ---------- | ------------------------------------------ | ---------------------------- |
   | `function` | Default. Each test gets fresh state        | Most unit tests              |
   | `class`    | Tests within a class share expensive setup | DB connection per test class |
   | `module`   | All tests in a file share setup            | Loaded config file           |
   | `session`  | Entire test run shares setup               | Docker container startup     |

3. **Design teardown** — Use `yield` fixtures when cleanup is needed. Never leave
   side effects (temp files, DB rows, monkey-patches) after a test.
4. **Identify conftest candidates** — Fixtures used across multiple test files belong
   in `conftest.py`. Fixtures used in one file stay in that file.

### Phase 4: Mock Strategy

1. **Decide what to mock** — Mock external dependencies only:
   - Network calls (API, database, message queues)
   - Filesystem operations (when testing logic, not I/O)
   - Time-dependent behavior (`datetime.now`, `time.sleep`)
   - Random/non-deterministic behavior

2. **Decide what NOT to mock** — Never mock:
   - The function under test
   - Pure functions called by the target (test them through the target)
   - Data structures and value objects

3. **Choose mock level** — Patch at the import boundary of the module under test,
   not at the definition site. `@patch('mymodule.requests.get')`, not
   `@patch('requests.get')`.

4. **Add mock assertions** — Every mock should assert it was called with expected
   arguments and the expected number of times. Mocks without assertions are coverage
   holes.

### Phase 5: Output

Generate the test file following this structure:

1. Imports (pytest, mocks, target module)
2. Constants and test data
3. Fixtures (ordered by scope: session > module > class > function)
4. Test classes or functions grouped by target function
5. Parametrized tests where applicable

## Output Format

```text
# tests/test_{module}.py

import pytest
from unittest.mock import Mock, patch, MagicMock

from {module} import {target_function, TargetClass}


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def valid_input():
    """Standard valid input for happy path tests."""
    return {concrete values}


@pytest.fixture
def mock_database():
    """Mock database connection."""
    with patch("{module}.db_connection") as mock_db:
        mock_db.query.return_value = [{expected data}]
        yield mock_db


# ============================================================
# {target_function} Tests
# ============================================================

class TestTargetFunction:
    """Tests for {target_function}."""

    def test_happy_path(self, valid_input):
        """Returns expected result for valid input."""
        result = target_function(valid_input)
        assert result == {expected}

    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ({boundary_1}, {expected_1}),
            ({boundary_2}, {expected_2}),
            ({boundary_3}, {expected_3}),
        ],
        ids=["empty", "single", "maximum"],
    )
    def test_boundary_conditions(self, input_val, expected):
        """Handles boundary inputs correctly."""
        assert target_function(input_val) == expected

    def test_invalid_input_raises(self):
        """Raises TypeError for invalid input."""
        with pytest.raises(TypeError, match="expected str"):
            target_function(None)

    def test_external_call(self, mock_database):
        """Calls database with correct query."""
        target_function("lookup_key")
        mock_database.query.assert_called_once_with("SELECT * FROM t WHERE key = %s", ("lookup_key",))
```

## Configuring Scope

| Mode            | Scope             | Depth                                        | When to Use                          |
| --------------- | ----------------- | -------------------------------------------- | ------------------------------------ |
| `quick`         | Single function   | Happy path + 1 error case                    | Rapid iteration, TDD red-green cycle |
| `standard`      | File or class     | Happy + boundary + error + mocks             | Default for most requests            |
| `comprehensive` | Module or package | All categories + async + parametrized matrix | Pre-release, critical path code      |

## Calibration Rules

1. **Test isolation is non-negotiable.** Every test must pass when run alone and in any order.
   No test may depend on the side effects of another test.
2. **Mock discipline.** Mock external dependencies, not internal logic. Over-mocking produces
   tests that pass when the code is broken. Under-mocking produces tests that fail when the
   network is down.
3. **Concrete over abstract.** Test data must be concrete values, not placeholders. `"alice@example.com"`
   not `"test_email"`. `42` not `"some_number"`. Concrete values catch type mismatches that
   abstract placeholders mask.
4. **One assertion focus per test.** A test should verify one behavior. Multiple assertions
   are acceptable when they verify different aspects of the same behavior (e.g., return value
   AND side effect), but not when they verify unrelated behaviors.
5. **Parametrize, don't duplicate.** If two tests differ only in input/output values, combine
   them with `@pytest.mark.parametrize`. Use `ids` for readable test names.
6. **Match project conventions.** If the project uses `conftest.py` fixtures, class-based tests,
   or specific markers, follow those patterns. Do not introduce a conflicting test style.

## Error Handling

| Problem                                                         | Resolution                                                                                                            |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Target function has no type hints                               | Infer types from usage patterns, default values, and docstrings. Note uncertainty in test docstring.                  |
| Target has deeply nested dependencies                           | Mock at the nearest boundary to the function under test. Do not mock transitive dependencies individually.            |
| No existing test infrastructure (no conftest, no pytest config) | Generate a minimal `conftest.py` alongside the test file. Note the addition in output.                                |
| Target code is untestable (global state, hidden dependencies)   | Flag the design issue in the output. Generate tests for what is testable. Suggest refactoring to improve testability. |
| Async code detected but pytest-asyncio not installed            | Note the dependency requirement. Generate async test stubs with `@pytest.mark.asyncio` and instruct user to install.  |
| Target module cannot be imported                                | Report the import error. Do not generate tests for unimportable code.                                                 |

## When NOT to Generate Tests

Push back if:

- The code is auto-generated (protobuf, OpenAPI client, ORM models) — test the generator or the schema, not the output
- The request is for UI/E2E tests — this skill generates unit and integration tests only
- The code has no clear behavior to test (pure configuration, constant definitions)
- The user wants tests for third-party library code — test your usage of the library, not the library itself

## Rationalizations

| Rationalization | Reality |
|---|---|
| "Manual testing is sufficient" | Manual testing doesn't run in CI, doesn't catch regressions, and doesn't scale with the codebase |
| "This code is too simple to test" | Simple code becomes complex code — tests document expected behavior and catch regressions from future changes |
| "I'll add tests later" | Tests are specifications; without them, code behavior is undefined and later never comes |
| "Mocking everything makes the test fast" | Over-mocked tests pass when the real system fails — mock at boundaries, not deep in the call chain |
| "100% coverage means the code is correct" | Coverage measures execution, not correctness — a test that runs code without meaningful assertions adds no value |
| "The happy path test is enough" | Edge cases and error paths cause most production incidents — happy-path-only testing is false confidence |

## Red Flags

- Tests that only cover the happy path with no edge cases or error paths
- Test names that describe implementation ("test_calls_function") instead of behavior ("test_returns_404_when_not_found")
- More than two mocks per test — indicates the unit under test is too coupled
- Tests that depend on execution order or shared mutable state
- Assertions on implementation details (mock call counts) instead of observable behavior
- Skipping integration tests because "unit tests cover it"

## Verification

- [ ] Tests follow Arrange-Act-Assert structure with clear phase separation
- [ ] Test names describe behavior: `test_<unit>_<scenario>_<expected_outcome>`
- [ ] Edge cases covered: empty input, boundary values, error paths, null/None
- [ ] Coverage meets thresholds: 80% overall, 90% new code, 95% critical paths
- [ ] All tests pass: `pytest` / `npm test` exits 0 with output captured
- [ ] No test depends on execution order — can run in any sequence
- [ ] Mocks used only at boundaries (external APIs, system clock, filesystem in unit tests)
