# Changelog

## Unreleased — standalone CLI and OMP source adapter

- Add explicit configured-command execution with separate result/applicability/proof semantics and bounded private output.
- Persist private, partitioned, exclusive receipts; recompute scoped freshness and reconcile demonstrably interrupted owners without inventing successful completion or output counters.
- Handle launch failure, timeout, SIGINT/SIGTERM and owned POSIX process-group cancellation; reject malformed schemas and unsafe/foreign storage rather than repairing it.
- Exercise real filesystem/Git/process behavior with 28 core-stage tests and an actual standalone CLI journey.
- Add an OMP source factory with collision-checked session-start literal commands, five explicit string flags and actual host session identity.
- Start one owned asynchronous configured verification per session; expose explicit wait/cancel and await owned cancellation on session switch/shutdown.
- Share reopened freshness projections with the unchanged standalone CLI. Render only safe JSON text and TUI-guarded widgets without model turns, raw output, private paths or exception text.
- Pass all 40 feature behavior tests, including recording-native-API cases backed by real Git/filesystem/process work for cancellation, state ownership, isolation, privacy, freshness and publication failure.
- Diagnose thrown completion-publication failures with a stable sanitized stderr code while retaining durable receipts and releasing task ownership. Record live ACP custom-text delivery as blocked by the inspected host API, not satisfied by session-history replay.
- Exercise installed OMP 18.12.6 RPC against a detached bundle: actual configured success/nonzero execution, new-session reopening, scoped freshness, changed-during-run unknown applicability, durable cancellation with descendant reaping, private artifacts and live safe custom text. Preserve normal authentication/enforcement and verify targeted optional-writer/MCP containment; do not substitute history replay for live output or claim TUI/ACP support.
- Use the existing receipt-test convention for synthetic baseline commit metadata in the disposable native fixture; do not depend on runner-global author configuration or change credentials, signing, hooks or native-host authentication.
- Distinguish the host's missing-default-model startup prerequisite with a stable sanitized unavailable reason; never publish raw startup diagnostics or turn an unavailable native run into success.
- Separate committed-stage credential-free CI from explicit fail-closed local/manual native qualification. Preserve implemented OMP adapter behavior, detached reproducible/import-contained builds and all registered package/static/lifecycle gates; report live-host smoke as not requested, never passed.

This is an unregistered development-prefix delivery, not a released native extension. The exercised OMP RPC surface is distinct from TUI rendering, live ACP responses, Claude integration and registered native packaging/activation. CI requires no authenticated host session and does not certify native compatibility. No root version, release tag, catalog registration or publication is introduced.
