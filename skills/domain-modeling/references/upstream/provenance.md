# Domain modeling provenance

## Pinned upstream

- Repository: https://github.com/mattpocock/skills
- Commit: `49dd158d1076134a641b33efb035946536778336` (2026-10-09).
- Skill source: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/engineering/domain-modeling/SKILL.md
- Glossary source: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/engineering/domain-modeling/GLOSSARY-FORMAT.md
- Decision-boundary source: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/engineering/domain-modeling/ADR-FORMAT.md
- License source: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/LICENSE
- Upstream license: MIT, Copyright (c) 2026 Matt Pocock. The full notice is retained in this package's LICENSE file.

## Adapted behavior

Retained the active discipline of challenging overloaded terms, probing edge-case business scenarios, checking claims against code, capturing agreements immediately, creating files lazily and keeping canonical vocabulary free of implementation details. Retained the conjunctive ADR-candidate test: meaningful reversal cost, surprise to a future reader without context, and genuine alternatives weighed/chosen for specific reasons.

Adapted upstream's GLOSSARY.md/GLOSSARY-MAP.md layout to Armory's existing CONTEXT.md/CONTEXT-MAP.md and docs/agents/domain.md conventions. The local context-format reference incorporates the checked-in project-context-setup context format and definition as read on 2026-10-19, including single-sentence definitions, Language/Relationships/Example Dialogue/Flagged Ambiguities sections, cardinalities, lazy first-term creation and existing-human-content preservation. This is a standalone local adaptation, not a filesystem dependency or a synchronized template claim.

Added an explicit bounded collaboration/edit-authority contract; agreement versus unresolved status; both-direction cardinality and quantity probes; code/model disagreement dispositions; read-only and missing-source outcomes; stale/legacy route handling; and a worked synthetic ordering/billing partial-cancellation example. Added authored eval cases for those branches, all-three and each missing ADR condition, unknown evidence and adjacent negative requests.

## Intentional omissions and differences

- No generic glossary scaffold, automatic whole-repository modeling or generic programming glossary.
- No bulk migration or rename of an existing glossary; existing routes and human edits are preserved pending an authorized destination decision.
- No ADR-writing workflow, ADR template, numbering, directory creation or authoring permission. A fully qualified candidate is a separate handoff to an authorized adr-writer; any missing condition means no candidate.
- No implementation, refactor, migration, tracker operations, source-script execution or global installation authority.
- No upstream agent profile copied. Package metadata and invocation boundaries follow Armory conventions.
- No claim that authored cases, a worked example or static conformance prove fresh-model activation or task effectiveness.

## Manual resynchronization only

This is a selective adaptation, not an auto-synced vendor copy. A future update must deliberately compare the pinned upstream files with the proposed new commit, review behavior and licensing deltas, reconcile Armory's context conventions and authority boundaries, update local references/evals as needed, and record the new exact pin and accepted/omitted changes here. Do not replace the package with latest upstream or execute upstream installation/setup scripts. Existing user-authored target-repository context remains independent of upstream updates.
