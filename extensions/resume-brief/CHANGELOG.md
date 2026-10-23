# Changelog

## Unreleased — standalone core prefix

This entry describes implemented prefix behavior. It does not assert that the delivery has been merged, packaged or published, and it is not a native extension release.

- Add the pure Resume Brief core: strict parsers for the `armory.resume-brief.context/v1` and `armory.resume-brief.blockers/v1` artifacts, OMP JSONL session headers (version 3) and handoff file names, and allowlisted Verification Receipts schema-1 reference fields; card construction; approval hold evaluation; field-level discrepancy rules; inert text rendering; and strict snapshot validation. The core has no runtime, filesystem, clock or host imports.
- Add bounded helpers that read only explicitly selected sources: descriptor-pinned `openat` traversal for repository-relative files on macOS/glibc Linux, and absolute OMP session, handoff and receipt files. Refuse special files, oversize content and identity changes during a read; record Git branch, `HEAD` and upstream before and after reading sources. Never run repository-configured fsmonitor, conversion or signature commands; keep repository-wide dirty state unknown and compare selected-plan raw bytes with the raw `HEAD` blob.
- Add the standalone `record`, `reopen`, `show` and `list` CLI with JSON and escaped text output. Reopen re-reads the recorded selection and reports source-linked discrepancies with recorded and current SHA-256 values; it never resumes or executes anything.
- Keep every approval a non-executable hold. Expiry cannot be renewed by a fresh source read, and approvals from another or unknown host, account or session are marked foreign.
- Persist only derived snapshots under an explicit external data root as owned 0700 directories and exclusive 0600 files, preserving earlier snapshots and refusing tampered, linked or foreign state. No plan, handoff, receipt or transcript bodies are stored.
- Accept native OMP version-1 title slots without retaining their contents and preserve all valid shipped Verification Receipts gate references, including 256-character references. Retain recorded source pointers when current selection becomes unavailable; render invisible Unicode tag and variation-selector content visibly escaped.
- Reject prototype-named unexpected snapshot fields, ignore inherited Git repository-location overrides when observing the explicitly selected worktree, and refuse new snapshot publication when the existing directory reaches its listing limit.
- Not included: OMP or Claude Code commands and renderers, `EXTENSION.md`, evals, catalog or release entries, Claude session observation, live pull request state and receipt freshness recomputation.
