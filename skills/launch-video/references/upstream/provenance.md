# Upstream Provenance

## Source

- Repository: https://github.com/latent-spaces/brag
- Pinned commit: `069432cac935ed1895859df201c31436c07fb74e`, obtained with `git rev-parse HEAD` from a fresh clone on 2026-10-17.
- License: MIT — full text in `LICENSE` in this directory, copied verbatim.
- Copyright holder: Copyright (c) 2026 Shunit Haviv Hakimi.

## What was vendored

- `skills/brag/references/tones.md`, copied verbatim as `references/tones.md`.
- Creative direction adapted into `SKILL.md` and the other references: the creative laws, the hook → reveal → highlights → punchline shape, the nine-question inspection rubric and skip list, the private-data rule, the plan and storyboard structure, scene counts per tone, reading-time floors, the "choosing what to show" order, the transition vocabulary, the music and effect volume policy, the per-tone share-copy shapes, and the frame-0 poster bake (from `skills/brag/SKILL.md`, `skills/brag-slim/SKILL.md`, and `skills/brag/references/step-1-inspect.md`, `step-2-plan.md`, `audio.md`, `step-4-deliver.md`).

## What was adapted

- Renamed `brag` to `launch-video` because armory package names expose the triggerable outcome; "/brag" stays as a trigger phrase.
- Replaced the `npx hyperframes` workflow and the five external `hyperframes-*` skills with the `html-video` package, because armory pins the Hyperframes version once, forbids `npx`, and audits every render-critical asset. The pinned `hyperframes@0.8.147` npm package was checked on 2026-10-17 with `npm view` (Apache-2.0).
- Replaced GSAP and runtime-chosen animation with html-video's finite-CSS-keyframe contract, and added a transition-to-keyframe mapping, because html-video seeks only CSS keyframes.
- Replaced the bundled music and sound effects with user-supplied audio declared in `PROVENANCE.json`, because the bundled assets were about 16 MB and html-video ships no media.
- Added a mandatory share-copy credit for `CC-BY-*` assets, enforced by `scripts/launch_video.py finish`. Upstream bundled CC BY 4.0 music (ende.app) and never instructed crediting it in the produced video's share copy; its own `assets/music/README.md` left the licence terms unverified.
- Removed the "If you are Claude Opus 5.5" self-identification dispatch between `/brag` and `/brag-slim`, because routing on the model's self-report is not deterministic. One workflow remains.
- Replaced prose-only gates with executable ones: `finish` verifies the delivery digest, duration window, audio presence, poster time and credits, re-verifies the baked video, and confirms frame 0 matches the poster by PSNR.
- Added guidance for command-line projects (documented terminal output as the product in use, labelled excerpts, legible terminal text) and an explicit stop for projects with no visual surface, instead of inventing UI.
- Rewrote frontmatter for armory metadata, added trigger boundaries against `animate`, `remotion-video` and `html-video`, and wrote the output layout around a single run directory.

## What was skipped

- `skills/brag/assets/` (five MP3 tracks under CC BY 4.0, Kenney and OpenGameArt CC0 effects), the generated cue presets, `sfx-analysis.*`, and `scripts/analyze_music_cues.py` with its librosa `pyproject.toml` and `uv.lock`.
- Website-URL input from `brag-slim`: scraping a live site needs a headless browser and third-party asset rights the user may not hold. Input is the local project only.
- Kokoro voiceover (`--voice`) and `npx hyperframes tts`, which have no html-video equivalent.
- The `/brag-slim` duplicate (`skills/brag/slim.md`) and its sync script, the per-agent symlinks, plugin and marketplace manifests, `docs/` and `examples/` (launch site and demo videos), funding, star-history and letsbrag.app promotion.

## Re-sync policy

Do not auto-sync. Compare future upstream changes against the pinned commit, preserve the license, and re-run armory validation before adopting any change.
