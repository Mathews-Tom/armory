# Template config and output checks

`scripts/build_scene.py` turns one config file into a Manim scene, a render and deterministic checks. It makes no model call and needs no network. Config is `.json` or `.toml`. Unknown fields, wrong types, duplicate JSON keys, out-of-range values and control characters in text are rejected before anything is written.

## Common fields

| Field                | Type   | Required | Notes                                                  |
| -------------------- | ------ | -------- | ------------------------------------------------------ |
| `template`           | string | yes      | `data_flow`, `comparison` or `timeline`                |
| `title`              | string | yes      | 1-48 characters, single line                           |
| `final_hold_seconds` | number | no       | 0.5-30, default 2.0; seconds the last frame is held    |

Colors are one of `BLUE TEAL GREEN YELLOW GOLD ORANGE RED MAROON PURPLE PINK WHITE GREY` (exact upper-case names) or `#RRGGBB`. Omitted colors cycle through BLUE, TEAL, GREEN, YELLOW, ORANGE, RED (stages/events) or BLUE/GREEN (comparison sides).

All text is single-line: tabs, newlines and other control characters are rejected. Quotes, backslashes, braces, `%`, `#` and non-Latin text pass through unchanged.

## `data_flow`

| Field         | Type  | Bounds        |
| ------------- | ----- | ------------- |
| `stages`      | list  | 2-5 entries   |
| `stages[].name`  | string | 1-16 characters |
| `stages[].color` | color  | optional      |
| `arrow_color` | color | optional, default `WHITE` |

```json
{
  "template": "data_flow",
  "title": "RAG Pipeline",
  "stages": [
    {"name": "Ingest", "color": "BLUE"},
    {"name": "Embed"},
    {"name": "Retrieve", "color": "#FFAA00"}
  ]
}
```

## `comparison`

| Field          | Type   | Bounds                    |
| -------------- | ------ | ------------------------- |
| `left`, `right`| object | both required             |
| `.label`       | string | 1-24 characters           |
| `.items`       | list   | 1-6 strings of 1-36 characters |
| `.color`       | color  | optional                  |

```toml
template = "comparison"
title = "Monolith vs Microservices"

[left]
label = "Monolith"
items = ["Single deployable unit", "Simple local dev"]

[right]
label = "Microservices"
color = "GREEN"
items = ["Independent deployments", "Complex local dev"]
```

## `timeline`

| Field                  | Type   | Bounds            |
| ---------------------- | ------ | ----------------- |
| `events`               | list   | 2-8 entries       |
| `events[].label`       | string | 1-12 characters   |
| `events[].description` | string | 1-40 characters   |
| `events[].color`       | color  | optional          |

```json
{
  "template": "timeline",
  "title": "Language Models",
  "events": [
    {"label": "2017", "description": "Transformer architecture"},
    {"label": "2018", "description": "BERT pretraining"}
  ]
}
```

The bounds come from each template's fixed layout. Text is scaled only when it exceeds the available width; timeline labels also respect per-event spacing. These limits prevent obvious overflow, not poor wording or unreadable glyphs.

At the accepted maximum counts and wide-glyph lengths, fitting text can make labels too small to read, especially in the low-quality preview. Shorten text or reduce event density, then inspect the samples; width containment is not a legibility guarantee.

## Running it

```bash
ANIMATE_PY="$ANIMATE_ENV/bin/python"   # provisioned in SKILL.md, step 0
"$ANIMATE_PY" "$SKILL_DIR/scripts/build_scene.py" config.json --out-dir out --quality low
"$ANIMATE_PY" "$SKILL_DIR/scripts/build_scene.py" config.json --out-dir out --generate-only
```

`--generate-only` needs neither Manim nor ffmpeg. `--format webm` is available; `--audio FILE` (MP4 only, with a finite positive `--audio-volume`) overlays audio through `add_audio.py --trim-to-video`. `--samples N` accepts 0–30 (default 5); `0` skips sampling and produces no frame-review receipt.

The render wrapper disables the pinned Manim CLI's version-notification HTTP request. It resolves the output by input-file stem, requested quality and actual Manim version, including Manim's version-suffixed native GIF filename; unrelated cached renders are never selected as a fallback.

Exit codes: `0` metadata checks passed, `1` render/audio/verification failed, `2` bad config or arguments, `3` a dependency is missing. A metadata pass is not visual approval.

## Artifacts

| File                                | Content                                                                       |
| ----------------------------------- | ----------------------------------------------------------------------------- |
| `scene.py`                          | Generated scene: the template with only its config block replaced              |
| `plan.json`                         | Template, scene class, expected duration, animation-call count, SHA-256 of config and source |
| `scene.<fmt>` / `scene-with-audio.mp4` | The render                                                                 |
| `verification.json`                 | Measured vs expected duration, fps, width, height, decoded frame count, audio |
| `frames/frame-NN.png`               | Frames at the midpoints of N equal segments                                    |
| `frames/review-receipt.json`        | Frame hashes bound to the video hash, luma range per frame, `review.status`    |

## What the checks prove

`verification.json` records full decode checks (`ffprobe -count_frames`), frame count, planned duration, FPS and geometry. Every template fixes each `run_time` and `wait`, so planned duration allows one frame of rounding per animation call: `(calls + 1) / fps + 0.05` seconds. Preset geometry: low 854x480 at 15 FPS, medium 1280x720 at 30, high 1920x1080 at 60, 4k 3840x2160 at 60. When overlaying audio, first verify the silent render against the plan, then require the final video's duration to match that **measured** baseline within `1 / fps + 0.05` seconds; the broader planning tolerance cannot excuse truncation.

Metadata cannot prove readable labels, unclipped layout or meaningful colours. A `uniform` luma flag requires inspection, not automatic rejection. Sampling and attestation work without a hosted model:

```bash
"$ANIMATE_PY" "$SKILL_DIR/scripts/verify_video.py" check out/scene.mp4 --plan out/plan.json --quality low
"$ANIMATE_PY" "$SKILL_DIR/scripts/verify_video.py" sample out/scene.mp4 --count 6 --out-dir out/frames
# open out/frames/frame-*.png (person or vision model), then record the outcome:
"$ANIMATE_PY" "$SKILL_DIR/scripts/verify_video.py" attest out/frames/review-receipt.json \
    --reviewer "name" --verdict pass --notes "labels readable, nothing clipped"
```

`attest` refuses when the video or any sampled frame has changed. `review.status: "pending"` means no visual verdict is recorded. Resampling invalidates a prior receipt before extraction; rebuilding invalidates prior verification and review records. Record a pass only after inspecting every listed frame.
