# Changelog

## Unreleased — standalone CLI

- Add explicit configured-command execution with separate result/applicability/proof semantics and bounded private output.
- Persist private, partitioned, exclusive receipts; recompute scoped freshness and reconcile demonstrably interrupted owners without inventing successful completion or output counters.
- Handle launch failure, timeout, SIGINT/SIGTERM and owned POSIX process-group cancellation; reject malformed schemas and unsafe/foreign storage rather than repairing it.
- Exercise real filesystem/Git/process behavior with 28 core-stage tests and an actual standalone CLI journey.

This is an unregistered development-prefix delivery, not a released native extension. OMP and Claude integrations, native artifacts and compatibility remain undelivered. No root version, release tag, catalog registration or publication is introduced.
