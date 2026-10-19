# Upstream Provenance

## Source

- Repository: https://github.com/mattpocock/skills
- Pinned commit: `49dd158d1076134a641b33efb035946536778336`.
- Authoring source: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/writing-for-agents/SKILL.md
- Invocation source: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/writing-for-agents/SKILL-MECHANICS.md
- License: MIT; Copyright (c) 2026 Matt Pocock. The package-root `LICENSE` reproduces the pinned repository's root license verbatim.
- Upstream license: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/LICENSE

## What was adopted

- Context pointers state the condition for loading material and what it supplies; distinct invocation branches matter more than synonymous trigger wording.
- Keep common instructions inline and disclose branch-only reference content conditionally; co-locate a concept's rules and maintain a single source of truth.
- Completion criteria must be checkable and exhaustive, covering every applicable input and promised result rather than a vague understanding or summary.
- Discover mutable commands/configuration from the environment rather than maintaining stale copies of facts the project exposes.
- Treat invocation reach and splitting by independent invocation as explicit design choices with context/cognitive-load costs.

These concepts inform the local evaluator and its rubric and the adapted root CONTRIBUTING.md and NEW_PACKAGE_CHECKLIST.md authoring guidance. This provenance record covers that authoring adaptation; it does not attribute Armory's machine evaluator implementation to upstream.

## What was adapted

- Converted writing guidance into evidence-backed authored review criteria for all seven Armory package types, with single-package, multi-package, catalog, type-filtered and static-report-only scope handling.
- Preserved required Armory descriptions/metadata and current validator limits; actual invocation flags/router behavior must be discovered in the target adapter/harness.
- Added branch-to-case coverage, conditional-reference/configuration adversarial examples, explicit authority/blocker handling and severity-backed findings without numeric quality grades.
- Bound reporting to Armory's existing report-v2 interface: static `PASS|FAIL`, live effectiveness `NOT_MEASURED`, and separate authored/behavioral evidence. No machine report/schema change is part of this adaptation.
- Retained separately authorized behavioral evidence requirements and existing effectiveness roadmap gates; source shortening, wording, schema validity and static PASS do not establish efficacy.
- Version `2.0.0` is a MAJOR release from `1.3.1`: replacing the authored numeric scored-audit/scorecard output with evidence-backed report-v2-aligned findings breaks the prior authored output contract. This major bump does not introduce a new machine schema.

## What was omitted

- No verbatim transplant of the complete upstream authoring reference or its standalone skill/harness metadata.
- No automatic removal of required descriptions, universal `disable-model-invocation` setting or assumption that another harness's router/invocation mechanics work in Armory.
- No cross-package shared-reference dependency in the distributable evaluator package.
- No scoring weights, dimension caps, percentage acceptance threshold or claim that an authored/static pass clears live-effectiveness gates.
- No hosted evaluation, installation, settings change or execution authority granted by an audit or by this attribution.

## Re-sync policy

Manual resync only. Compare proposed upstream changes against this exact pin and review adopted concepts and local compatibility/evidence adaptations before changing the evaluator, rubric or root authoring guidance. Preserve the MIT notice and update the pin, attribution and applicable changelog when a reviewed delta is adopted. Do not auto-sync. Validation and live evaluation remain subject to separate task authority; this record does not claim they ran.
