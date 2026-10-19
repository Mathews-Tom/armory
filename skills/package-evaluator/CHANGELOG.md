# Changelog — package-evaluator

## 2.0.0

- BREAKING / MAJOR from `1.3.1`: replace the authored numeric scored-audit/scorecard output contract with evidence-backed, report-v2-aligned findings and coverage. Consumers expecting numeric quality grades or percentage acceptance must use source-backed findings and explicit evidence limits instead.
- Preserve the existing machine interface: static conformance `PASS|FAIL`, live effectiveness `NOT_MEASURED`, and top-level mirrors. This release changes authored audit behavior, not the machine report/schema.
- Separate machine conformance, authored contract review and observed behavior across single-package, multiple-path, catalog, type-filtered and static-only audits; no scored acceptance gate.
- Apply checkable/exhaustive completion, branch coverage, conditional reference loading and environment/configuration discovery criteria while preserving required Armory metadata and harness-specific invocation discovery.
- Complete the same unreleased cutover with missing-frontmatter authored coverage: preserve the observed CRITICAL invalid-YAML static failure, exit 1 and live `NOT_MEASURED` without inventing parsed metadata or execution evidence.
- Add pinned provenance and the verbatim MIT notice for Matt Pocock's writing-for-agents and SKILL-MECHANICS.md at `49dd158d1076134a641b33efb035946536778336`, including attribution for adapted root authoring guidance and a manual-only resync policy.
