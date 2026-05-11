# Deep Module Analysis

Use this reference during Structural Integrity review when assessing module boundaries,
testability, and AI navigability.

## Vocabulary

| Term | Meaning |
| ---- | ------- |
| Module | Anything with an interface and implementation: function, class, package, service, workflow |
| Interface | Everything callers must know: types, invariants, errors, ordering, config, side effects |
| Implementation | Code hidden behind the interface |
| Deep module | Small interface hiding substantial behavior |
| Shallow module | Interface nearly as complex as its implementation |
| Seam | A place where behavior can change without editing callers |
| Adapter | Concrete implementation behind a seam |
| Locality | Bugs, changes, and knowledge concentrated in one module |
| Leverage | Amount of useful behavior gained through a small interface |

## Signals Of Shallow Modules

- Pass-through wrappers that rename or forward calls without hiding complexity.
- Callers that must know internal ordering, retries, lifecycle, or data-shaping rules.
- Many small helper functions extracted only for tests while real bugs live in call choreography.
- Interfaces that expose implementation details such as storage layout, HTTP mechanics, cache keys, or framework internals.
- One adapter behind an abstract seam with no realistic second implementation.

## Deletion Test

For a suspected shallow module, ask:

- If deleted, does complexity disappear or simply move into callers?
- Would callers become simpler, unchanged, or more complex?
- Does the module concentrate policy or merely distribute it?

If deleting the module makes the system easier to understand without duplicating real policy, the module is not earning its interface.

## Finding Shape

Use this shape for actionable recommendations:

```markdown
**Finding:** `<module>` is shallow: callers must understand `<leaked concept>` to use it safely.

**Impact:** Low locality. Changes to `<behavior>` require edits across `<callers>`, and tests must mock implementation choreography instead of stable behavior.

**Recommendation:** Deepen `<module>` around `<domain concept>`. Move `<policy>` behind the interface, expose `<small contract>`, and test behavior through that interface.
```

## Guardrails

- Do not recommend abstractions only because code is duplicated.
- Do not introduce a seam unless there is a real second adapter, a testing need at a stable boundary, or a volatile external dependency.
- Prefer domain-named modules from `CONTEXT.md` when project context exists.
- Respect ADRs. If a deepening recommendation contradicts an ADR, call out the conflict and justify reopening the decision.
