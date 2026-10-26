# Module deepening provenance

## Source

- Repository: https://github.com/mattpocock/skills
- Commit read: `5beb35b040e3de97e54fa9e386d7e42d15c295c2` (fresh clone, 2026-10-26).
- Sources:
  - `skills/engineering/improve-codebase-architecture/SKILL.md` and `HTML-REPORT.md`
  - `skills/engineering/codebase-design/SKILL.md`, `DEEPENING.md` and `DESIGN-IT-TWICE.md`
- Source trees: https://github.com/mattpocock/skills/tree/5beb35b040e3de97e54fa9e386d7e42d15c295c2/skills/engineering/improve-codebase-architecture and https://github.com/mattpocock/skills/tree/5beb35b040e3de97e54fa9e386d7e42d15c295c2/skills/engineering/codebase-design
- Delta against Armory's earlier pin `49dd158d1076134a641b33efb035946536778336`: `git diff --stat 49dd158 5beb35b` over both folders (and the sibling `domain-modeling` and `prototype` folders) is empty, so the files are byte-identical to the revision other Armory packages already adapt. No upstream changes needed accepting or omitting.
- License: MIT, Copyright (c) 2026 Matt Pocock. The verbatim notice is this package's `LICENSE` (compared byte-for-byte with upstream's `LICENSE` using `cmp`).

## What was vendored

| Upstream | Armory |
|---|---|
| `improve-codebase-architecture/SKILL.md` (explore, report, grilling loop) | `SKILL.md` scan mode, interaction contract, decision handoffs |
| `improve-codebase-architecture/HTML-REPORT.md` | `references/report-format.md` |
| `codebase-design/SKILL.md` (glossary, principles, relationships, rejected framings, testability) | `references/vocabulary.md` |
| `codebase-design/DEEPENING.md` | `references/deepening.md` |
| `codebase-design/DESIGN-IT-TWICE.md` | `references/design-it-twice.md` and `SKILL.md` design mode |

## What was adapted

- **Renamed `improve-codebase-architecture` to `module-deepening`.** The skill covers module depth, seam placement and testability only; "improve codebase architecture" overpromises and collides with `architecture-reviewer` ("review architecture") and `codebase-advisor` ("what should we improve next").
- **Merged `codebase-design` into this package** instead of shipping it as a standalone vocabulary package. Armory bans cross-package file reads, so a vocabulary-only package could not be consulted by other packages; the vocabulary lives where it is used.
- **Two explicit modes.** Upstream's single flow becomes scan (find candidates, write the report, ask for a pick) and design (frame, design it twice, recommend), so a user with a module already in mind skips the scan.
- **Report is fully offline.** Upstream loads Tailwind and Mermaid from CDNs and initializes Mermaid with `securityLevel: "loose"` while rendering repository-derived labels. The adaptation uses inline CSS and inline SVG only, a Content-Security-Policy meta tag that blocks scripts and network fetches, and mandatory HTML escaping of repository strings. Mermaid diagram guidance became equivalent inline-SVG patterns. Upstream's temp-directory location, timestamped filename, open-and-print-path behaviour, card fields, strength badges, dependency tags, ADR callout rule, top recommendation and tone rules are kept.
- **Domain conventions.** Upstream's `GLOSSARY.md` and `docs/adr/` assumptions are replaced with Armory's `docs/agents/domain.md` → `CONTEXT.md` / `CONTEXT-MAP.md` routing and the repository's discovered ADR route.
- **Inline questioning.** Upstream's "call the Skill tool with grilling" becomes an in-package interaction contract: one question at a time, recommended answer included, stop at an agreed decision.
- **Term updates handed off.** Upstream edits `GLOSSARY.md` inline via its domain-modeling skill. Here, proposed terms go to the `domain-modeling` package by name; this skill never edits `CONTEXT.md`.
- **ADR offers gated.** Upstream offers an ADR when a rejection reason is load-bearing. Here the offer requires `domain-modeling`'s conjunctive ADR-candidate test (hard to reverse, surprising without context, real trade-off), restated inline, and then hands off to `adr-writer` by name.
- **No implementation.** After the decision the skill hands off to `codebase-advisor` (plan) or the `/tdd` command; it never edits code.
- **Design-it-twice fallback.** Added a sequential path for harnesses without sub-agents (independent designs written in order, no back-revision, labelled as such), and briefs carry pasted glossary definitions because sub-agents cannot be assumed to read package files.
- **Scan scoping made concrete.** Upstream's "walk back a good stretch of the commit history" becomes a sourced `git log --oneline -n 200 --name-only` starting point, widened when history is short or scattered.

## What was skipped

- `agents/openai.yaml` in both upstream folders (non-Armory harness metadata).
- Upstream frontmatter `disable-model-invocation: true`; Armory packages route by description.
- Tailwind CDN, Mermaid CDN and `securityLevel: "loose"`.
- Cross-skill calls (`codebase-design`, `grilling`, `domain-modeling` via a Skill tool).
- Writing `GLOSSARY.md` or ADR files from this skill.

## Re-sync policy

Manual only. Do not auto-sync. Compare upstream changes against `5beb35b040e3de97e54fa9e386d7e42d15c295c2` for the five source files above, review them against the offline-report, read-only and handoff boundaries recorded here, record the new pin with accepted and omitted changes, and run Armory validation before adopting anything.
