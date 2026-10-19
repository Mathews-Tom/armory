# Upstream provenance: learning-workspace

## Source and license

Adapted from Matt Pocock's `teach` skill and its format documents in
[mattpocock/skills](https://github.com/mattpocock/skills), pinned to
**49dd158d1076134a641b33efb035946536778336** (2026-10-09). Source files were read as
data from the pinned checkout; no upstream scripts were executed.

- [teach/SKILL.md](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/teach/SKILL.md)
- [MISSION-FORMAT.md](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/teach/MISSION-FORMAT.md)
- [RESOURCES-FORMAT.md](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/teach/RESOURCES-FORMAT.md)
- [LEARNING-RECORD-FORMAT.md](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/teach/LEARNING-RECORD-FORMAT.md)
- [GLOSSARY-FORMAT.md](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/teach/GLOSSARY-FORMAT.md)
- [Upstream MIT license](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/LICENSE)

The package-local `LICENSE` preserves the MIT notice, copyright 2026 Matt Pocock.
These links document provenance; the installed package does not fetch them at
runtime and all required workflow references are local.

## Retained and adapted

| Upstream idea | Armory adaptation |
| --- | --- |
| Mission grounds each lesson in a real outcome | Explicit confirmed mission with stable success criteria and revision history |
| Mission/resources/lessons/learning-records persist across sessions | User-authorized separate root, lazy substantive files, canonical-path/symlink boundary and version-1 formats |
| Records steer the learner's next challenge | Mandatory evidence class, observed criterion/result/support, scoped projection and evidence-dependent next-task choice |
| Prior knowledge and corrections matter | Self-report stays distinct from inspected work; covered material stays distinct from both; correction history uses linked supersession |
| Trusted contextual resources | Inspect available local sources, annotate access and limits, record gaps, and keep offline synthetic teaching viable |
| Tight practice-feedback loop | Realistic mission task, returned learner evidence, criterion-based feedback and retry rather than automatic answer-key success |
| Retrieval, spacing and interleaving | Context-dependent tools tied to prior exposure, elapsed time and task choices, without claiming measured retention or mastery |
| Reference documents/glossary | Optional reusable Markdown references; definitions help vocabulary but do not certify learner understanding |

## Deliberate omissions and boundaries

- No implicit current-directory root, writes into the repository being studied,
  global learner memory, agent-settings mutations or automatically created course
  skeleton. Saved content cannot authorize new destinations.
- No copied Claude-specific invocation flags or `/teach` path semantics. Armory's
  discoverable description names ongoing human learning and adjacent boundaries.
- No mandatory resource search, subscription, network access, community referral,
  outreach, purchase or external runtime before teaching. Unavailable knowledge
  is explicitly bounded rather than guessed or disguised as an inspected source.
- No claim that one correct response establishes long-term storage, mastery or a
  universally suitable challenge level. A teacher explanation or learner's
  confidence does not prove a corrected misconception.
- No equal-character/word answer rule. Distractors and formatting should be clear
  and non-cueing; artificial answer-length equality is not a correctness criterion.
- No HTML-only lessons, mandatory stylesheets/components, automatic browser opening
  or premature asset library. Markdown is preferred; HTML must earn its complexity
  with meaningful accessible offline interaction and an equivalent text task.
- No generic `NOTES.md` for unbounded personal information. Persist only relevant,
  authorized preferences in their existing local owner or mission constraints.
- No assumption that writing a glossary demonstrates comprehension. Learner
  evidence and misconception history remain in the record schema.
- No ingestion of the upstream frozen `misc/scaffold-exercises` workflow,
  repository-specific scaffolding, dependency defaults or commits.

## Manual resync policy

This is a deliberate adaptation, not a mirror. To resync, select a new exact
upstream commit, read the five payloads and license delta as data, then compare
changes against the local authority, evidence, portability and source-access
contracts. Keep or explicitly revise each adaptation/omission; never overwrite
local files wholesale. Update the pin, affected local formats/evals and package
version together under normal repository review. Report any unexercised behavior
rather than presenting authored examples as measured effectiveness.

## Evidence limits

The local formats, two-session fixture and eval cases are authored specifications.
They are not recorded live learning sessions, runtime proof, or measured routing
and task effectiveness. No checks, formatter, model/harness session, network call
or behavioral smoke was run while authoring this package. Static conformance and
live effectiveness must be reported separately when independently assessed.
