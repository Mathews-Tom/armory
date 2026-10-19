# Upstream provenance

## Source and license

- Repository: https://github.com/mattpocock/skills
- Pinned commit: `49dd158d1076134a641b33efb035946536778336`.
- Adapted source: [skills/productivity/to-questionnaire/SKILL.md](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/to-questionnaire/SKILL.md).
- License source: [LICENSE at the pinned commit](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/LICENSE).
- License: MIT; Copyright (c) 2026 Matt Pocock. The full notice is preserved in the package-local `LICENSE`.
- Local source inspected as data on 2026-10-19; no upstream scripts were executed. The pinned identity is supplied by the implementation plan's source-checkout checkpoint, not a new verification claim by this package author.

## Adaptations

- Renamed `to-questionnaire` to `intake`, retaining an explicit asynchronous external-recipient boundary rather than a generic onboarding or interview meaning. Before authoring, the checked-in manifest search found no `intake`, `ask-sheet` or `questionnaire` entry and directory discovery found no existing `skills/intake/` package. No alias was added.
- Kept the upstream distinction between asking the sender who the recipient is/what is needed and asking the recipient for domain knowledge. Added separate missing-metadata and ready-to-draft branches, role-only recipients and nonblocking unknown sender/logistics.
- Retained context, purpose, from/to, answer use, most-important-first one-idea questions, answer stubs and permission for partial or uncertain replies. Made deadline and effort conditional on supplied facts rather than requiring invented estimates.
- Extracted the recipient layout into a local template and added a local question-design/coverage reference. Added a sender-only outcome-to-question matrix covering every input decision or fact without forwarding internal sender rationale.
- Added explicit handling of compound outcomes and recipient expertise limits, preserving every requested outcome without fabricating answers or silently widening the audience.
- Scoped delivery to one local Markdown draft with filesystem prerequisite handling, preservation of existing files and a separate sender-facing handoff. Added prohibitions on sending, trackers, external calls and analytics.
- Replaced upstream frontmatter with standalone Armory 1.0.0 metadata and added branch/adjacent-negative eval scenarios. Cases are authored specifications, not evidence of measured routing or task success.

## Deliberate omissions

- Omitted the upstream option to fill the questionnaire out together in a meeting: live interrogation is outside this package's async contract.
- Omitted `disable-model-invocation: true`: Armory's required description exposes the task boundary without assuming an upstream harness flag is portable.
- Did not import upstream installer, companion agents, promotional content or dependencies on other skills. This package needs only ordinary local Markdown reading/writing capabilities.
- No response collection, reminders, delivery integrations, survey analysis or repository tutoring was added.

## Manual resynchronization

Do not auto-sync. For a proposed refresh, compare the source and license against this exact pin, then review each delta against the asynchronous one-recipient contract. Preserve the license notice, local templates, exhaustive sender-only coverage and explicit branch/negative cases. Update this provenance with the adopted pin, changes and deliberate omissions. Repository validation and any separately authorized behavior exercises belong to the integration owner; an authored case or static PASS must not be reported as measured effectiveness.
