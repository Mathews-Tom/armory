---
name: html-video
description: 'Use when the user wants a video authored as HTML and CSS and rendered with Hyperframes: "html video", "hyperframes", "render html to mp4", "animate html css to video", "title sequence from html", "html caption video", "side by side comparison video in html", "diagram explainer video in html". NOT for React or Remotion compositions, Manim animations, analysing an existing video, ordinary web pages with no video output, or planning a launch video from the current project (use launch-video, which renders through this package).'
metadata:
  version: 1.0.1
  category: visualization
  tags: [video, html, css, hyperframes, mp4, offline, templates]
  difficulty: intermediate
---

# HTML Video

Author a video as plain HTML and CSS, then render it with a **pinned, project-local Hyperframes CLI**. The bundled CSS-only templates use local assets after explicit `bootstrap` provisioning; authoring and static audit need no network. Rendering arbitrary project code is not an offline sandbox: enforce external network isolation when that guarantee is required. Deliver editable HTML, its statically reachable asset closure, provenance and licence records, the verification reports, and the MP4 together.

## When to Use

| Request | Fit |
|---|---|
| Titles, comparison, diagram walk-through or captions rendered to MP4 from HTML/CSS | Use a bundled template |
| Edit or re-render an existing Hyperframes composition | Audit it first, then run the workflow |
| React or Remotion component, Manim scene, existing-video analysis, plain web page | Not this skill |

No cloud rendering, avatar or model generation, publishing, or skill installation is part of this workflow. Do not read or invoke any other package from here.

## Prerequisites

`SKILL_DIR` is the absolute directory containing this file. The scripts need Python 3.12+ and only the standard library. Rendering needs Node (major in `config.toml`), FFmpeg with ffprobe, a Chrome or chrome-headless-shell executable, and **a font file the user may redistribute**. The Hyperframes version is pinned once, in `config.toml`; never state or override it elsewhere.

Never install system binaries yourself, never run Hyperframes through `npx`, and never use `@latest`. If a prerequisite is missing, stop and tell the user what to install.

```bash
python3 "$SKILL_DIR/scripts/html_video.py" --help
python3 "$SKILL_DIR/scripts/html_video.py" init --list
```

## Workflow

1. **Pick and copy a template.** `init TEMPLATE DEST` copies `title-sequence`, `comparison`, `diagram-explainer` or `captioned-sequence`. All are 1920x1080, text-editable and animated by finite CSS keyframes.
2. **Get the font from the user.** Ask for a font file (woff2, woff, ttf or otf), its licence text, SPDX id and source. Never download or assume one; never bundle a system font. `fonts add PROJECT --font-file F --family NAME --license-id ID --license-file L --source S` copies it, records provenance, writes `fonts.css` in the project's assets directory, and updates compiler-visible inline `@font-face` declarations in `index.html`. Templates use the alias `HV Text`; no manual HTML edit is needed. `--family` is only the provenance name; the CSS family is `--alias` (default `HV Text`). Provision a second family, such as a monospace, with its own `--alias "HV Code"` on each of its faces and reference that alias in CSS, or it becomes another face of `HV Text`.
3. **Bootstrap once.** `bootstrap PROJECT --browser-path PATH` pins an existing browser, or `--download-browser` runs the pinned CLI's own `browser ensure`. The package manager comes from the project lockfile (npm for a fresh project). The lock `.html-video/environment.json` records tool paths and actual versions, including the browser's own `--version`. Afterwards `doctor PROJECT` re-verifies offline.
4. **Author.** Edit text and `data-start` / `data-duration` values; see the contract below. Keep the root `data-duration` equal to the last clip end.
5. **Audit.** `audit PROJECT` rejects remote render-critical resources, path and symlink escapes, missing files, case mismatches, cycles, undeclared fonts and invalid timing. Fix every error.
6. **Verify.** `run lint PROJECT`, then `run check PROJECT`, then `run snapshot PROJECT`. Read the coverage table below, then open **every** `.html-video/snapshots/contact-sheet*.jpg` page and judge the frames yourself: layout, legibility, and motion at the sampled boundaries.
7. **Render.** `run render PROJECT` uses the FPS from `config.toml`, renders with strict, non-best-effort, software-browser capture and one worker, removes any previous output first, and checks the MP4 against the composition. Override FPS only by passing the same `--fps N` to **all four** run commands.
8. **Deliver.** `deliver PROJECT --out DIR` requires passing reports for the same source, verified toolchain, config and effective FPS, verifies every recorded artifact, re-audits copied `source/` with provenance required, and writes `RENDER.json` plus `reports/`. Pass `--fps N` here too after an FPS override. Any failed rerun invalidates its prior report.

`plan PROJECT` prints the frame-aligned boundary times used for `check` and snapshots.

## Timing and motion contract

- The root has `data-composition-id`, `data-start="0"`, integer `data-width`/`data-height`, a finite positive `data-duration`, and `data-no-timeline` when no timeline is registered.
- Each clip has a unique `id`, `data-start` (a number, or `otherId [+/- seconds]`) and `data-duration`. Paint order is CSS `z-index`, not track index.
- Motion is **finite CSS keyframes on HTML elements** with `animation-fill-mode: both`. The runtime seeks them to the clip-local time `t - data-start`. SVG child elements are not seeked, CSS transitions are not seeked, and `infinite` iteration is rejected.
- Add no GSAP, no CDN script, no wall-clock timers and no unseeded randomness. Seeking can land on any time in any order.
- Keep each top-level clip single-level (text, or an element without block children) to keep lint clean; caption cues use class `caption-cue` on one track. A zero-height absolutely positioned box can stretch; give shapes real dimensions or use `clip-path`.

## Coverage you must read

`run check` passes `--at` boundary times and then enforces these report fields. A pass without them proves nothing.

| Field | Required | Meaning |
|---|---|---|
| `browserSkipped` | `false` | Browser-backed layout, motion and contrast ran |
| `layout.samples` | every requested time | Boundaries were really sampled |
| `motion.enabled`, `motion.samples` | true, > 0 when animated | Needs the `index.motion.json` sidecar |
| `contrast.checked` | > 0 when text exists | Absent text means no contrast proof |
| `_meta.version` | the pinned version | The pinned CLI produced the report |

`--at-transitions` reads GSAP timelines only, so CSS-animated compositions rely on the explicit `plan` times.

## Limits and network behaviour

- The audit is a static reference audit, **not a sandbox**. It follows supported static HTML/CSS/SVG references, local module imports and import-map addresses, but computed URLs and arbitrary JavaScript remain executable. Recognised runtime loading, wall-clock APIs and unseeked Web Animations produce warnings, not proof of their absence. Review every warning; enforce network isolation outside the tool for a hard guarantee.
- Source-confirmed network paths addressed by the package: telemetry and update checks (forced off), `snapshot --describe` (the vision key is scrubbed and `--describe false` is passed), and compile-time Google Fonts resolution (used named families require compiler-visible inline local `@font-face`). Known unmapped-font or Google Fonts compiler logs fail the run rather than silently falling back.
- The browser is pinned by passing its path through `HYPERFRAMES_BROWSER_PATH` and `PRODUCER_HEADLESS_SHELL_PATH`, so a render cannot silently select or download another build. A failed `--version` or changed version aborts the run.
- Rendering is seek-driven, but no byte-identical output is claimed. Results depend on the recorded Hyperframes, browser, FFmpeg and operating-system versions and on the font files.

## Error Handling

| Symptom | Cause | Fix |
|---|---|---|
| `font_not_declared` | A named family has no local `@font-face` | Run `fonts add`; never let the compiler fetch it |
| `font_face_not_inline`, `font_dynamic`, `font_face_local_source` | Linked-only, scoped-variable or system-dependent font resolution | Run `fonts add`; use a literal provisioned family and inline local font faces, never `local()` |
| `remote_resource`, `path_escape`, `symlink_escape` | Resource not inside the project | Copy the file into the project and reference it relatively |
| `motion_spec_missing` or `motion_unproven` | Animated, no motion sidecar | Add assertions to `index.motion.json` |
| `contrast_unproven` | Text present but no pair checked | Re-run `check` at times where text is visible |
| `report_stale`, `report_*_mismatch` at deliver | Source, toolchain, config or FPS changed after verification | Re-run all four steps with one matching context; re-bootstrap only when intentionally changing the toolchain |
| `not installed`, `changed since bootstrap` | Toolchain differs from the lock | Re-run `bootstrap`; do not fall back to `npx` |
| `render_mismatch` | MP4 size, rate or length differs | Fix `data-duration`/dimensions and re-render |

## Output

Report: the delivery directory, the MP4 path, the `RENDER.json` environment summary (versions, fps, duration), the check coverage numbers you read, which frames you inspected and what you judged, every warning left open, and the font and asset licences declared by the user.

## Reference

- `references/composition-contract.md` for the verified runtime seek contract and authoring rules
- `references/fonts-and-assets.md` for font provisioning, provenance schema and what the audit proves
- `references/verification.md` for command flags, coverage fields and the reproducibility record
- `NOTICE.md` for attribution and terms
