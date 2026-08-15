# Upstream Provenance

## Source

- Upstream repo: https://github.com/Agents365-ai/tldraw-skill
- Pinned commit: `9f87eb827c81161e4be5e27c05e4823e35b78dda`
- License: MIT, copyright 2026 Agents365-ai
- License text: `LICENSE`
- Runtime dependency `@kitschpatrol/tldraw-cli` (npm, MIT license) is unmodified and installed at runtime — not vendored. Independently verified against the npm registry and `github.com/kitschpatrol/tldraw-cli`: real, actively maintained package (v6.0.2, published 2026-07-23), MIT licensed, `export` subcommand flags (`-f`, `-o`, `--scale`, `--transparent`, `--dark`) match what upstream documented. It is a third-party wrapper, distinct from tldraw.dev's official `create-tldraw` scaffolding CLI.

## What was vendored

- Core workflow, prerequisites, self-check, and review-loop logic from upstream `skills/tldraw-skill/SKILL.md`, adapted into `skills/tldraw/SKILL.md`.
- `.tldr` file format, geo shape record, color palette, and style options into `references/tldr-format.md`.
- Arrow record, connection rules, arrowheads, frame and note shapes into `references/arrows-and-containers.md`.
- Index ordering, layout tips, box-sizing formula, and the six diagram-type presets (architecture, flowchart, sequence, ML, ERD, UML) into `references/diagram-presets.md`.
- Export commands, common-mistakes table, and fallback chain into `references/troubleshooting.md`.

## What was adapted

- Package name changed from `tldraw-skill` to `tldraw` — armory already has a bare-tool-name naming precedent (`tavily`, `github`, `notebooklm`) and the `-skill` suffix was redundant inside a skill definition.
- Frontmatter rewritten to armory's schema (`name`, `description`, `metadata: {version, category, tags, difficulty, complements}`); dropped the upstream `openclaw`/`hermes` platform metadata blob, `license`/`homepage`/`compatibility`/`platforms` fields, none of which armory's manifest consumes.
- `description` and the "When to Use" table were rewritten to resolve a real trigger collision with armory's existing `architecture-diagram` skill: both fired on "architecture diagram". `tldraw`'s triggers now lead with hand-drawn/whiteboard/flowchart/sequence/ERD/UML language and the description explicitly routes polished business/infra diagrams to `architecture-diagram`.
- Cross-references to sibling packages that exist only in the Agents365-ai family (`drawio-skill`, `mermaid-skill`, `excalidraw-skill`, `plantuml-skill`) were removed. Armory's `CONTRIBUTING.md` prohibits references to files/packages that only exist elsewhere. Where upstream pointed to one of those skills as the fix for a limitation, the limitation is now stated as a plain constraint with no package pointer.
- 630-line single-file `SKILL.md` split into a ~150-line core `SKILL.md` plus four `references/` files, matching the structure armory already uses for `architecture-diagram` (which splits icons/layout/connections into `references/`).
- Single real armory cross-reference added: `metadata.complements: [architecture-diagram]`, since both skills solve adjacent "generate a diagram" requests with different aesthetics.

## What was skipped

- `README.md`, `README_CN.md`, `docs/index.html`, `docs/zh.html` — marketing/donation content (WeChat Pay, Alipay, Buy Me a Coffee QR codes) and installer instructions for other platforms (SkillsMP, ClawHub, Claude Code plugin marketplace); armory uses manifest-driven installation.
- `assets/*.png`, `assets/*.tldr` example gallery and `docs/features.md` — illustrative only, not required for the skill to function; the shape/arrow/preset specs in `references/` are self-contained.
- `.github/workflows/sync-365-skills.yml` — upstream's own cross-repo sync automation, not applicable to armory.

## Re-sync policy

Do not auto-sync from upstream. Compare changes against pinned commit `9f87eb827c81161e4be5e27c05e4823e35b78dda`, preserve the MIT license, and re-run armory validation after every update.
