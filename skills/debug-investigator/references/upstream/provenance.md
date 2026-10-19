# Upstream Provenance

## Source

- Repository: https://github.com/mattpocock/skills
- Pinned commit: `49dd158d1076134a641b33efb035946536778336`.
- Source: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/engineering/diagnosing-bugs/SKILL.md
- Primary adopted passage: lines 114–138, “Phase 5: Fix + regression test” and “Phase 6: Cleanup.”
- License: MIT; Copyright (c) 2026 Matt Pocock. The package-root `LICENSE` reproduces the pinned repository's root license verbatim.
- Upstream license: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/LICENSE

## What was adopted

- A regression test must reach the real bug pattern through a correct seam; shallow tests that omit required callers or interactions provide false confidence.
- Select the seam before fixing the defect, capture defect-specific red/green evidence, and report the absence of a correct seam as a finding rather than fabricating coverage.
- Confirm an intentional forced-red mutation actually changed the exercised source/fixture before interpreting the result.
- Rerun the original, unminimized scenario and remove temporary instrumentation and throwaway debugging artifacts before declaring resolution.

## What was adapted

- Integrated the regression capability into debug-investigator's existing symptom, evidence, hypothesis, bisection and investigation workflow rather than replacing it with the upstream phase layout.
- Made caller/shared-state/ordering coverage explicit, including a shared-cache example and checks against mocks that replace the defective boundary.
- Distinguished an architectural absence of a usable seam from missing tools, fixtures, permission or environment access; retained explicit unobserved/blocked outcomes.
- Extended forced-red guidance with preservation of the actual current content, invalid-mutation handling, exact restoration and restored-run evidence. Mutation remains conditional, not a universal requirement.
- Added environment-command discovery, explicit execution authority and resolution evidence fields; these are Armory adaptations, not claims of observed effectiveness.
- Version `1.2.0` is a MINOR release from `1.1.1`: the real-boundary regression capability extends the existing debugging contract without removing its investigation paths.

## What was omitted

- No wholesale replacement of the existing debug-investigator workflow, reference library or output template.
- No upstream human-in-the-loop shell template, foreign helper dependency, harness metadata or automatic infrastructure/setup behavior.
- No requirement to mutate every fix, make a commit/PR, or run checks without task authorization.
- No claim that authored cases, static conformance or these prose changes measure live effectiveness.

## Re-sync policy

Manual resync only. Compare a proposed upstream revision against this exact pin, review the adopted passages and Armory adaptations deliberately, and preserve the upstream MIT notice. Update the pin, attribution and package changelog only when a reviewed delta is adopted. Do not auto-sync or overwrite the local workflow. Validation or behavioral evaluation requires separate task authority; no execution is implied by this provenance record.
