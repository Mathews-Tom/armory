# Changelog

## 2.0.0 — 2026-11-06

### Breaking changes

- Replace the numeric audit score, length/age thresholds, and automatic settings or permission edits with evidence-backed findings and explicit coverage limits.
- Expand setup/instruction-health auditing to Claude Code, OMP, Codex, and other harnesses through discovered configuration, documented precedence, and actual host evidence. Missing `/context` or skill-use inventory no longer blocks a bounded setup audit.
- Remove universal MCP/token-cost estimates, preferred setting defaults, and assumptions that newer rules, newer models, or rarely used skills are better removal/upgrade candidates. Preserve pinned and safety-critical instructions.
- Keep connector/task health report-only; package quality, skill-use measurement, and MCP conversion retain their separate package routes.

### Added

- An independently authored, original standard-library capture/review/check/verify workflow with private create-only artifacts, source/evidence bindings, offline review, exact proposal selection, and separate chat authorization. This is not a vendored implementation or copied external skill.
- Native-tool-only application of exact approved replacements to existing files; the helper never writes audited targets. Verification observes selected and unselected targets and reports drift or partial application without rollback.
- Operator documentation, a synthetic worked example, and behavioral eval cases for coverage gaps, conservative recommendations, review/approval, no-op, failure, and adjacent negative routes.
- Explicit POSIX host prerequisites and an early unsupported-platform refusal before audit file access; Windows remains report-only.
