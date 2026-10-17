# Changelog — Animate

## 2.0.1

- Route launch or promo videos of the user's own project to `launch-video`.

## 2.0.0

- BREAKING: rename the package from `concept-to-video` to `animate`. There is no alias, shim or old folder; routing, profiles, evaluation registration and generated catalogs move to the new name.
- Scope is stated explicitly: Manim technical explainers (algorithms, math, pipelines, architecture, comparisons, timelines) with MP4/WebM/GIF output, templates, audio overlay and the opt-in planner, fixup and critic. HTML/CSS/GSAP/Hyperframes compositions and React/Remotion video are excluded, and neither is required to use this package.
- Add a template path that needs no model call: `scripts/build_scene.py` validates `.json`/`.toml` config for the `data_flow`, `comparison` and `timeline` templates, replaces only each template's config block, renders through `render_video.py` with auto-fix off, and writes `scene.py`, `plan.json`, `verification.json`, sampled frames and a review receipt. Unknown fields, wrong types, duplicate keys, multi-line or control-character text, bad colors, out-of-range counts and bad durations are rejected with the offending path before any file is written. User text is emitted as Python string literals, so quotes, backslashes and non-Latin text stay exact.
- Templates pin every `run_time` and `wait`, take `FINAL_HOLD`, shrink over-wide text to its box, and document their duration formula, so the planned duration is deterministic.
- Add `scripts/verify_video.py`: `check` fully decodes the output with ffprobe and compares duration, frame rate, dimensions, decoded-frame count and audio stream with the plan or explicit numbers; `sample` extracts midpoint frames and writes a hash-bound review receipt with `review.status: "pending"` and per-frame luma ranges; `attest` records a reviewer verdict only if the video and frames are unchanged. Works without any model. Metadata checks are documented as not proving layout.
- Invalidate verification and review records before rebuilding or resampling, reject nonfinite verification inputs and oversized duration integers cleanly, enforce quality geometry without a plan, and bind audio duration to the measured silent baseline.
- Locate native version-suffixed GIFs by source stem, requested quality and actual Manim version; never select another source, quality or legacy output as a fallback. Disable Manim's runtime PyPI version-notification request without suppressing render diagnostics, and reject destinations that overwrite the editable scene.
- Remove the broken PNG choice from the video wrapper; native Manim remains available directly for still images and PNG frame sequences.
- Replace the Linux-only `apt-get` and `pip --break-system-packages` guidance with macOS and Linux instructions and an isolated uv environment (`manim==0.19.2`). Provisioning is separate from rendering; scripts never install anything and fail with the exact command when Manim, ffmpeg or ffprobe is missing.
- Move Code2Video source, license and pin into `references/code2video/PROVENANCE.md`; the package no longer links to a repository-root attribution file.
- Keep auto-fix at 0 attempts and the critic off by default. Arbitrary user-authored Manim Python is still executed as written and is not sandboxed.
- Add regression tests for config validation, source fidelity, timing plans, decode and duration mismatches, receipt tampering, and an optional real-render check, plus evaluation cases for the no-model path, rejection of bad config, model-free output review, isolated setup and HTML/React routing boundaries.

## 1.2.0 and earlier (as `concept-to-video`)

- Manim scene workflow with quality presets, templates, rule files, audio overlay, subtitles and multi-scene composition.
- Opt-in agentic mode: storyboard planner, asset resolution, bounded auto-fix loop and budgeted vision critic.
