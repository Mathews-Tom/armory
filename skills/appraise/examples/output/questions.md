# Interview questions: Alice Doe

Questions test independent understanding of decisions in the analysed work, not trivia. Answers are recorded as self-reports: they can raise confidence or reveal a disagreement, but cannot raise a level band on their own.

## Q-01

claim() guards the update with state = 'queued' even though it already holds a lock. What failure did that second guard protect against, and when would it matter?

- Targets: system_design, problem_solving
- Grounded in: [E-002](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L31-L43)
- Could change: system_design confidence; whether the guard is deliberate or incidental

## Q-02

The worker declares MAX_ATTEMPTS but never enforces it. Was bounded retry deferred on purpose, and how would you stop a poison job from blocking the queue?

- Targets: operations
- Grounded in: [E-006](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/worker.py#L7-L20)
- Could change: operations from 2 to 3 if a credible design and its absence are explained

## Q-03

Walk through upgrading a populated v1 store to v2. What happens to in-flight 'running' jobs during the migration?

- Targets: architecture
- Grounded in: [E-001](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/src/queuebox/store.py#L20-L29), [E-008](https://github.com/example-org/queuebox/commit/7d09825ba17df52ed7b047398e32a74b9e8d4d81)
- Could change: architecture confidence from medium to high

## Q-04

The ADR rejects Postgres for operational reasons. What measurement would tell you it is time to revisit that decision?

- Targets: engineering_judgment
- Grounded in: [E-004](https://github.com/example-org/queuebox/blob/5d820b5a5e0f095e017ccaaab67b5d16dd001545/docs/adr/001-sqlite-wal.md#L1-L14)
- Could change: engineering_judgment confidence

## Q-05

How have you worked with the contributor who owns the HTTP module, for example through reviews, shared decisions or disagreements?

- Targets: collaboration
- Grounded in: —
- Could change: collaboration from not observable to observed if it points to verifiable reviews
