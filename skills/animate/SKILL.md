---
name: animate
description: 'Create Manim (Python) animated explainers: algorithm step-throughs, math and equation walkthroughs, pipeline and data-flow diagrams, comparisons and timelines, rendered to MP4, WebM or GIF with optional audio overlay. Includes a template path that renders validated config data with no model call, plus output checks (ffprobe duration, fps, dimensions, full decode, sampled-frame review receipt). Use when asked to "create a video", "animate this", "make an explainer", "manim animation", "animate this algorithm", or "motion graphic". NOT for HTML/CSS/GSAP or Hyperframes video, NOT for React or Remotion video, and NOT for a launch or promo video of the user''s own project, use launch-video.'
metadata:
  version: 2.0.1
  category: visualization
  tags: [video, manim, animation, explainer]
  difficulty: advanced
---

# Animate

Creates animated technical explainers with Manim, a Python animation engine. The scene `.py` file is the editable artifact: the user can read it, ask for changes, and re-render.

## Scope

| Request                                                                  | Handle here? |
| ------------------------------------------------------------------------ | ------------ |
| Algorithm, math, data-structure, pipeline, architecture, timeline, A-vs-B explainers | Yes — Manim |
| Config-driven pipeline, comparison or timeline video                     | Yes — template path, no model call |
| Overlay music or voiceover on a rendered Manim video                     | Yes — `scripts/add_audio.py` |
| HTML, CSS, GSAP or Hyperframes composition                               | No — an HTML-video tool, not this package |
| Explicit Manim request for branded or marketing content                   | Yes — honor the requested engine |
| React components or Remotion; generic branded/social video with no engine | No — default to a Remotion/React tool |
| Static infographic or image                                              | No — not animated video |
| Analyzing an existing video                                              | No — not generation |

Do not stretch Manim to cover HTML or React requests, and do not require those tools to use this one.

## Reference Files

| File                                          | Purpose                                                                 |
| --------------------------------------------- | ----------------------------------------------------------------------- |
| `references/template-config.md`               | Template config schema, bounds, artifacts and what the checks prove      |
| `references/rules/pipeline-flow.md`           | RAG, ETL, CI/CD — sequential stage animations with arrows               |
| `references/rules/architecture-layers.md`     | System stacks, network layers, abstraction hierarchies                  |
| `references/rules/algorithm-stepthrough.md`   | Sorting, search, graph traversal — stateful step-by-step animations     |
| `references/rules/comparison.md`              | Side-by-side A vs B, before/after, trade-off visualizations             |
| `references/rules/agent-interaction.md`       | Multi-agent message passing, distributed systems, pub/sub               |
| `references/rules/math-concept.md`            | Equations, formulas, geometric proofs — LaTeX-free by default           |
| `references/rules/training-loop.md`           | Gradient descent, RL loops, cyclic iterative processes                  |
| `references/rules/transitions.md`             | Fade and wipe transitions between scene sections                        |
| `references/rules/text-animation.md`          | Text replacement, progressive bullet reveal, callouts, emphasis         |
| `references/rules/layout.md`                  | Canvas coordinates, VGroup arrangement, spacing guidelines              |
| `references/rules/audio-overlay.md`           | ffmpeg audio overlay — background music, voiceover, multi-track mixing  |
| `references/rules/voiceover-scaffold.md`      | Timing script generation, TTS handoff, narration best practices         |
| `references/rules/images.md`                  | ImageMobject usage, logo/screenshot patterns, scaling and positioning   |
| `references/rules/subtitles.md`               | SRT generation from scene timing, ffmpeg subtitle burning               |
| `references/rules/multi-scene.md`             | Multiple Scene classes, ffmpeg concat, chapter-based composition        |
| `references/templates/data_flow_template.py`  | Parametric pipeline/data flow animation (config constants at the top)   |
| `references/templates/comparison_template.py` | Parametric side-by-side comparison                                      |
| `references/templates/timeline_template.py`   | Parametric timeline animation                                           |
| `references/code2video/PROVENANCE.md`         | Source, license and pin of the opt-in planner/fixup/critic prompts      |
| `scripts/build_scene.py`                      | Config data → scene → render → checks, no model call                    |
| `scripts/verify_video.py`                     | `check` decode/duration/fps/size, `sample` frames + receipt, `attest`   |
| `scripts/render_video.py`                     | Wrapper around the Manim CLI — quality, format, output path cleanup     |
| `scripts/add_audio.py`                        | ffmpeg wrapper — audio overlay, volume, fade-in/out, trim-to-video      |

## Workflow

```text
Config data ─► build_scene.py ─► scene.py + render + checks ─► review sampled frames
Concept ─► Manim scene (.py) ─► low-quality preview ─► iterate ─► final render
```

1. **Provision** dependencies once (Step 0); rendering never installs anything.
2. **Choose a path** (Step 1): template path when the concept is a pipeline, A-vs-B or timeline and the content is already known; custom scene otherwise.
3. **Render a preview** at `--quality low`, then iterate on the scene or config.
4. **Check** the output and **look at** sampled frames before calling it done.
5. **Export** at final quality; add audio if requested.

## Step 0: Provision dependencies (separate from rendering)

`SKILL_DIR` is the absolute directory containing this file. Python 3.12+ via [uv](https://docs.astral.sh/uv/), ffmpeg (with ffprobe) and, for text rendering, Cairo/Pango are required. Manim runs from one isolated environment; nothing is installed into the user's project or system Python.

```bash
ANIMATE_ENV="${XDG_CACHE_HOME:-$HOME/.cache}/animate/venv"
ANIMATE_PY="$ANIMATE_ENV/bin/python"

# Check first; install only what is missing.
uv --version && ffmpeg -version | head -n 1 && ffprobe -version | head -n 1
"$ANIMATE_PY" -c "import manim; print(manim.__version__)"

# One-time Manim install (Python only, isolated)
uv venv --python 3.12 "$ANIMATE_ENV"
uv pip install --python "$ANIMATE_PY" "manim==0.19.2"
```

System packages need the user's approval; the scripts never run them:

| Platform      | Command                                                              |
| ------------- | -------------------------------------------------------------------- |
| macOS         | `brew install ffmpeg` (add `cairo pango pkg-config` if uv must build manimpango/pycairo) |
| Debian/Ubuntu | `sudo apt-get install ffmpeg libcairo2-dev libpango1.0-dev pkg-config python3-dev` |

The opt-in planner and critic also need the Anthropic SDK in the same environment: `uv pip install --python "$ANIMATE_PY" anthropic`. Every script that is missing a dependency exits with the exact command to run (`build_scene.py` exit code 3).

Run every Manim-touching script with `"$ANIMATE_PY"`; `verify_video.py` and `add_audio.py` need only the standard library and ffmpeg.

## Step 1: Choose a path

| User intent                         | Path                                                                     |
| ----------------------------------- | ------------------------------------------------------------------------ |
| Linear pipeline (A→B→C), 2-5 stages | Template: `data_flow`                                                    |
| Two-option comparison               | Template: `comparison`                                                   |
| Chronology, 2-8 events              | Template: `timeline`                                                     |
| Algorithm step-through              | Custom scene — `references/rules/algorithm-stepthrough.md`               |
| Mathematical concept                | Custom scene — `references/rules/math-concept.md`                        |
| Architecture layers                 | Custom scene — `references/rules/architecture-layers.md`                 |
| Multi-agent / distributed systems   | Custom scene — `references/rules/agent-interaction.md`                   |
| Training / optimization loop        | Custom scene — `references/rules/training-loop.md`                       |
| Images, screenshots, logos          | Custom scene — `references/rules/images.md`                              |
| Subtitles or captions               | `references/rules/subtitles.md`                                          |
| Several chapters                    | `references/rules/multi-scene.md`                                        |
| Audio or voiceover                  | `references/rules/audio-overlay.md`, `scripts/add_audio.py`              |
| Transitions, text reveals, layout   | `references/rules/transitions.md`, `text-animation.md`, `layout.md`      |

### Template path (no model call)

Write the config from the user's content, then run the builder. Schema, bounds and examples are in `references/template-config.md`.

```bash
"$ANIMATE_PY" "$SKILL_DIR/scripts/build_scene.py" config.json --out-dir out --quality low
```

It validates the config (unknown fields, wrong types, empty or multi-line text, color names, counts, `final_hold_seconds`), copies the template with only its config block replaced, renders through `render_video.py` with auto-fix off, and writes `verification.json` plus sampled frames and a review receipt. User text is emitted as Python string literals, so quotes, backslashes and non-Latin text stay exact. A rejected config writes nothing and exits 2; add `--generate-only` to produce `scene.py` and `plan.json` without Manim.

The wrapper disables Manim's runtime PyPI version-notification request, not render warnings or errors. Video exports are MP4, WebM and native GIF; use Manim directly for still images or PNG frame sequences. A render destination must match the selected format and cannot overwrite the editable scene.

To go beyond the config's reach, edit the generated `scene.py` (the config constants at the top, then anything else) and render it with `render_video.py`. Hand-edited scenes are outside the plan's duration guarantee.

### Custom scene

Read the matching rule file before writing code. Core rules:

- **Single file, single Scene class**: one `.py` file with one `class XxxScene(Scene)`.
- **Self-contained**: Manim primitives only unless the user supplies assets.
- **Readable code**: the scene file is the user's artifact. Clear names, a comment per animation beat.
- **Color with intention**: Manim constants or hex, 4-5 colors at most, each encoding meaning.
- **Pacing**: `self.wait()` between sections: 0.5 s for breathing room, 1-2 s after major steps.
- **Legibility**: `font_size=36`+ for body text, `48`+ for titles, content within ±6 horizontal and ±3.5 vertical on the default 14.2×8 canvas.

```python
# DO: group simultaneous effects and stagger related elements
self.play(FadeIn(box), Write(label), run_time=1)
self.play(LaggedStart(*[FadeIn(item) for item in items], lag_ratio=0.2))

# DON'T: add without animation after the first frame, or flash by too fast to read
self.add(box)
self.play(Transform(a, b), run_time=0.3)
```

Scene skeleton:

```python
from manim import *

class ConceptScene(Scene):
    def construct(self):
        title = Text("Concept Name", font_size=56, weight=BOLD)
        self.play(Write(title))
        self.wait(1)
        self.play(FadeOut(title))
        # ... core animation ...
        self.wait(2)
```

A custom scene is arbitrary Python that Manim executes with the user's privileges. It is not sandboxed; run scenes only from sources the user trusts.

## Step 2: Preview, iterate, export

```bash
"$ANIMATE_PY" "$SKILL_DIR/scripts/render_video.py" scene.py ConceptScene --quality low --format mp4
```

| Request                  | Action                                                |
| ------------------------ | ----------------------------------------------------- |
| "Slower/faster"          | Adjust `run_time=` and `self.wait()`; for templates, `final_hold_seconds` |
| "Change colors"          | Update color constants or config `color` fields       |
| "Add a step"             | Add a config entry (within bounds) or insert a new animation block |
| "Different layout"       | Adjust `.shift()`, `.next_to()`, `.arrange()`         |
| "Add labels/annotations" | Add `Text` or `MathTex` objects with `.next_to()`     |

Final export: `--quality high --format mp4`.

| Preset   | Resolution | FPS | Use case             |
| -------- | ---------- | --- | -------------------- |
| `low`    | 854×480    | 15  | Fast preview         |
| `medium` | 1280×720   | 30  | Draft review         |
| `high`   | 1920×1080  | 60  | Final delivery       |
| `4k`     | 3840×2160  | 60  | Presentation quality |

Formats: `mp4` (standard), `webm` (web), `gif` (embeds; silent). Deliver the `.py` scene (or config) together with the rendered video, in the location the user asked for.

## Step 3: Check the output

Metadata checks prove the file is a decodable video of the planned shape; they cannot show that the layout is good.

```bash
# duration / fps / dimensions / decode, against a plan or explicit numbers
python3 "$SKILL_DIR/scripts/verify_video.py" check out/scene.mp4 --plan out/plan.json --quality low
python3 "$SKILL_DIR/scripts/verify_video.py" check clip.mp4 --expect-duration 12 --duration-tolerance 0.5 \
    --expect-fps 30 --expect-width 1280 --expect-height 720

# frames for a person or vision model to inspect, then record the verdict
python3 "$SKILL_DIR/scripts/verify_video.py" sample out/scene.mp4 --count 6 --out-dir out/frames
python3 "$SKILL_DIR/scripts/verify_video.py" attest out/frames/review-receipt.json \
    --reviewer "name" --verdict pass --notes "labels readable, nothing clipped"
```

Open the frames and look for overlap, clipped text, unreadable sizes and off-canvas objects. Report a receipt as reviewed only after `attest`; `review.status: "pending"` means nobody has looked. Template-path timing is exact to one frame per animation call, so a duration failure there is a real defect (missing hold, truncated render, audio shorter than video), not noise.

## Step 4: Optional audio overlay

```bash
# Background music at 25% with fades, trimmed to the video
python3 "$SKILL_DIR/scripts/add_audio.py" final.mp4 music.mp3 --output final_with_audio.mp4 \
    --volume 0.25 --fade-in 2 --fade-out 3 --trim-to-video
```

Or pass `--audio music.mp3 [--audio-volume 0.25]` to `build_scene.py` (mp4 only) so the audio is checked too. Output ends at the shorter stream: audio shorter than the video truncates the result and fails the duration check. For narration scripts read `references/rules/voiceover-scaffold.md`; for subtitles `references/rules/subtitles.md`; for multi-track mixing `references/rules/audio-overlay.md`.

## Error Handling

| Error                                        | Cause                                        | Resolution                                                |
| -------------------------------------------- | -------------------------------------------- | --------------------------------------------------------- |
| "Manim is not importable by this interpreter" | Not provisioned, or wrong python             | Run Step 0; invoke scripts with `"$ANIMATE_PY"`           |
| "ffmpeg was not found on PATH"               | System binary missing                        | Ask the user to install it (Step 0 table)                 |
| `pangocairo` / `manimpango` build error      | uv is compiling from source without headers  | Install the system libraries in Step 0, then retry the uv command |
| `invalid scene config: ...` (exit 2)         | Config breaks the schema or bounds           | Fix the named field; see `references/template-config.md`  |
| `VERIFY FAILED: duration ...`                | Render truncated, hold removed, short audio   | Re-render; compare `verification.json` with `plan.json`   |
| Scene class not found                        | Class name mismatch                          | Verify the class name matches the CLI argument            |
| Overlapping objects, text cut off            | Positions not calculated, text too large     | Use `.next_to()`, `.arrange()`; reduce `font_size`        |
| Slow render                                  | Many objects or complex transformations      | Reduce object count; use lower quality                    |
| `LaTeX Error`                                | LaTeX not installed (for `MathTex`)          | Use `Text` with Unicode math (`"(1/n) Σ xᵢ"`)             |

## Agentic Mode (Opt-In)

Default mode writes the scene directly: no extra model calls. Agentic mode adds model calls for production renders where layout correctness and asset resolution justify the cost. It never runs unless requested, and the template path never uses it.

```text
concept ─► plan_storyboard.py ─► storyboard.json ─► fetch_assets.py (optional)
        ─► coder writes scene.py ─► render_video.py --max-fix-attempts N ─► critic_pass.py --critic ─► final MP4
```

| Script            | Flag                 | Default  | Hard cap | Effect                                                    | Cost impact                              |
| ----------------- | -------------------- | -------- | -------- | --------------------------------------------------------- | ---------------------------------------- |
| `render_video.py` | `--max-fix-attempts` | `0`      | `3`      | Model-assisted auto-fix on render failure; 0 = disabled   | +1 model call per retry                  |
| `critic_pass.py`  | `--critic`           | disabled | —        | Enables the vision critic; no-op without it               | +1 vision call (N image blocks)          |
| `critic_pass.py`  | `--critic-budget`    | `50000`  | —        | Token ceiling; aborts before the call if exceeded         | Prevents runaway spend                   |
| `critic_pass.py`  | `--frames`           | `5`      | `10`     | Frames sampled for the critic                             | More frames, more tokens                 |
| `fetch_assets.py` | `--adapter`          | `none`   | —        | `local`, `iconfinder` or `none`                           | `iconfinder` makes external API calls    |
| `fetch_assets.py` | `--asset-dir`        | —        | —        | Root for `--adapter local`; required with it              | None                                     |

The fixup loop costs one call per failed attempt (up to 3). The critic call carries N PNG blocks, roughly 1 token per 800 base64 bytes each, so high resolutions cost more; `--critic-budget` raises `BudgetExceededError` before the call is made. Model identifiers live in `config.toml`.

```bash
"$ANIMATE_PY" "$SKILL_DIR/scripts/plan_storyboard.py" "explain transformer self-attention" --output storyboard.json
"$ANIMATE_PY" "$SKILL_DIR/scripts/fetch_assets.py" storyboard.json --adapter local --asset-dir ./assets --output resolved.json
# coder writes scene.py from storyboard.json
"$ANIMATE_PY" "$SKILL_DIR/scripts/render_video.py" scene.py AttentionScene --quality high --format mp4 --max-fix-attempts 3 --output final.mp4
"$ANIMATE_PY" "$SKILL_DIR/scripts/critic_pass.py" scene.py final.mp4 --critic --critic-budget 40000 --frames 5
```

The planner, fixup and critic prompts adapt Code2Video (arXiv 2510.01174, MIT); source, pin and license are in `references/code2video/PROVENANCE.md`.

## Limitations

- **Manim and ffmpeg required**; provisioning is explicit (Step 0).
- **Audio is post-render**: Manim renders silent video; GIF output cannot carry audio.
- **LaTeX optional**: `MathTex` needs a LaTeX install; fall back to `Text` with Unicode.
- **2D only**: `ThreeDScene` is unreliable in headless environments.
- **Render time scales with complexity**: a 30-second 1080p scene can take 1-2 minutes.
- **Templates are fixed layouts**: bounded counts and text lengths; richer designs need a custom scene.
- **Checks are not review**: duration, fps and decode checks do not establish that the scene reads well.

## Design anti-patterns

- Walls of text: 3-5 words per label, two lines maximum
- Everything appearing at once: stage with `LaggedStart`
- Uniform timing: vary `run_time` for rhythm
- No visual hierarchy: use size, color and position to direct attention
- Rainbow colors: 3-4 intentional colors
- Ignoring the grid: align with `arrange` and `align`
