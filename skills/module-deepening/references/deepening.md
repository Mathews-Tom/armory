# Deepening

Load when classifying a candidate's dependencies, placing a seam or deciding what happens to existing tests. Uses the terms in `references/vocabulary.md`.

## Dependency categories

Classify every dependency the deepened module would have. The category decides how the module is tested across its seam and becomes the candidate's tag in the scan report.

| Category | Examples | Deepening approach | How tests cross the seam |
|---|---|---|---|
| **in-process** | Pure computation, in-memory state, no I/O | Always deepenable: merge the modules and expose one interface. No adapter needed. | Call the new interface directly |
| **local-substitutable** | Postgres with PGLite, filesystem with an in-memory filesystem | Deepenable when the local stand-in exists. The seam is internal; no port at the module's external interface. | Run the stand-in inside the test suite |
| **ports & adapters** | Your own services across a network: internal HTTP/gRPC APIs, queues | Define a **port** (interface) at the seam. The deep module owns the logic; the transport is injected as an **adapter**. | In-memory adapter in tests; HTTP/gRPC/queue adapter in production |
| **true external (mock)** | Third-party services you do not control: Stripe, Twilio | The deepened module takes the external dependency as an injected port. | A mock adapter supplied by the test |

Recommendation shape for the ports & adapters case: "Define a port at the seam, implement an HTTP adapter for production and an in-memory adapter for tests, so the logic sits in one deep module even though it is deployed across a network."

When a candidate has dependencies in several categories, tag it with the one that decides the seam (usually the furthest-out category) and mention the others in the card's solution line.

## Seam discipline

1. **One adapter means a hypothetical seam; two adapters mean a real one.** Introduce a port only when at least two adapters are justified, typically production plus test. A single-adapter seam is just indirection; say so when a candidate proposes one.
2. **Internal seams stay internal.** A deep module may keep private seams for its own tests. Do not widen the external interface to expose them.
3. **Place the seam where behaviour varies,** not where the code happens to be split today. The seam question is separate from what sits behind it: decide placement first, then contents.

## Testing strategy: replace, don't layer

1. Write new tests at the deepened module's interface. The interface is the test surface.
2. Assert on observable outcomes through the interface, not on internal state or call choreography.
3. Delete the old unit tests on the shallow modules once interface tests cover their behaviour; keeping both layers doubles maintenance and pins the old shape.
4. Tests should survive internal refactors. A test that must change when only the implementation changes is testing past the interface.

The decision summary names which existing test files are replaced and which behaviours the new interface tests must cover. Writing those tests is implementation work for `/tdd` or the plan `codebase-advisor` produces, not for this skill.
