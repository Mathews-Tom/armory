# Upstream Provenance

## Source

- Upstream repo: https://github.com/caylent/tufte-data-viz
- Pinned commit: `ae7ca0de7819db83241b24a2618810d5f1171145`
- License: MIT, copyright 2026 Caylent
- License text: `LICENSE`

## What was vendored

- Core chart guidance from upstream `SKILL.md`, adapted into `skills/chart-clarity/SKILL.md`.
- Library rule files from upstream `rules/`, copied into `references/rules/`.
- Working examples from upstream `examples/`, copied into `references/examples/`.
- Interactive demo from upstream `docs/index.html`, copied into `references/interactive-demo.html` as a reference-only CDN-backed demo.
- Showcase images from upstream `_docs/*.png` and `_docs/*.gif`, copied into `assets/showcase/`.

## What was adapted

- Package name changed from `tufte-data-viz` to `chart-clarity` for broader user-facing discoverability.
- Frontmatter rewritten for armory metadata, trigger coverage, categories, tags, and complements.
- Internal paths changed from upstream `rules/` and `examples/` references to local `references/...` paths.
- Recharts and ECharts TypeScript examples were tightened to avoid `any`.
- Example chart titles were changed from axis descriptions to insight-bearing findings.
- Armory eval cases were added under `evals/cases.yaml`.

## What was skipped

- `_docs/generate_showcase.py` was not vendored. It writes to an upstream contributor's machine-local absolute path and is only needed to regenerate showcase images.
- Upstream README installation instructions were not vendored into the skill body because armory uses manifest-driven installation.

## Re-sync policy

Do not auto-sync from upstream. Compare changes against pinned commit `ae7ca0de7819db83241b24a2618810d5f1171145`, preserve the MIT license, and re-run armory validation after every update.
