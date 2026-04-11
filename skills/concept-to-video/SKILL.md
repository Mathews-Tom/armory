---
name: concept-to-video
description: 'Turn concepts into animated explainer videos using Manim (Python) with MP4/GIF output, audio overlay, multi-scene composition. Triggers on: "create a video", "animate this", "make an explainer", "manim animation", "motion graphic". NOT for React video, use remotion-video.'
metadata:
  version: 1.2.0
  category: visualization
  tags: [video, manim, animation, explainer]
  difficulty: advanced
---

# Concept to Video

Creates animated explainer videos from concepts using Manim (Python) as a programmatic animation engine.

## Reference Files

| File                                          | Purpose                                                                 |
| --------------------------------------------- | ----------------------------------------------------------------------- |
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
| `references/templates/data_flow_template.py`  | Parametric pipeline/data flow animation (config-driven STAGES list)     |
| `references/templates/comparison_template.py` | Parametric side-by-side comparison (config-driven LEFT/RIGHT items)     |
| `references/templates/timeline_template.py`   | Parametric timeline animation (config-driven EVENTS list)               |
| `scripts/render_video.py`                     | Wrapper around Manim CLI — handles quality, format, output path cleanup |
| `scripts/add_audio.py`                        | ffmpeg wrapper — audio overlay, volume, fade-in/out, trim-to-video      |

## Why Manim as the engine

Manim is the "SVG of video" — you write Python code that describes animations declaratively, and it renders to MP4/GIF at any resolution. The Python scene file IS the editable intermediate: the user can see the code, request changes ("make the arrows red", "add a third step", "slow down the transition"), and only do a final high-quality render once satisfied. This makes the workflow iterative and controllable, exactly like concept-to-image uses HTML as an intermediate.

## Workflow

```text
Concept → Manim scene (.py) → Preview (low-quality) → Iterate → Final render (MP4/GIF)
```

1. **Interpret** the user's concept — determine the best animation approach
2. **Design** a self-contained Manim scene file — one file, one Scene class
3. **Preview** by rendering at low quality (`-ql`) for fast iteration
4. **Iterate** on the scene based on user feedback
5. **Export** final video at high quality using `scripts/render_video.py`

## Step 0: Ensure dependencies

Before writing any scene, ensure Manim is installed:

```bash
# System deps (usually pre-installed)
apt-get install -y libpango1.0-dev libcairo2-dev ffmpeg 2>/dev/null

# Python package
pip install manim --break-system-packages -q
```

Verify with: `python3 -c "import manim; print(manim.__version__)"`

## Step 1: Interpret the concept

Determine the best animation pattern, then read the matching rule file before writing any code.

| User intent                     | Rule file to read                           | Key Manim primitives                          |
| ------------------------------- | ------------------------------------------- | --------------------------------------------- |
| Explain a pipeline/flow         | `references/rules/pipeline-flow.md`         | Arrow, Rectangle, Text, AnimationGroup        |
| Show architecture layers        | `references/rules/architecture-layers.md`   | VGroup, Arrange, FadeIn with shift            |
| Algorithm step-through          | `references/rules/algorithm-stepthrough.md` | Transform, ReplacementTransform, Indicate     |
| Compare approaches              | `references/rules/comparison.md`            | Split screen VGroups, simultaneous animations |
| Mathematical concept            | `references/rules/math-concept.md`          | MathTex, geometric shapes, Rotate, Scale      |
| Agent/multi-system interaction  | `references/rules/agent-interaction.md`     | Arrows between entities, Create/FadeOut       |
| Training/optimization loop      | `references/rules/training-loop.md`         | Loop with Transform, ValueTracker, plots      |
| Timeline/history                | `references/templates/timeline_template.py` | NumberLine, sequential Indicate               |
| Embed images or screenshots     | `references/rules/images.md`                | ImageMobject, SVGMobject                      |
| Add subtitles or captions       | `references/rules/subtitles.md`             | SRT generation, ffmpeg subtitle burn          |
| Multiple distinct chapters      | `references/rules/multi-scene.md`           | Multiple Scene classes, ffmpeg concat         |
| Add audio or voiceover          | `references/rules/audio-overlay.md`         | ffmpeg, scripts/add_audio.py                  |
| Transition between sections     | `references/rules/transitions.md`           | FadeOut all, shift off-screen                 |
| Text reveal, callouts, emphasis | `references/rules/text-animation.md`        | ReplacementTransform, LaggedStart, Indicate   |
| Positioning, spacing, layout    | `references/rules/layout.md`                | next_to, arrange, to_edge, move_to            |

## Step 2: Design the Manim scene

### Template-first vs from-scratch

Check whether a parametric template covers the concept before writing a scene from scratch:

| If the concept is...        | Start with template                                                              |
| --------------------------- | -------------------------------------------------------------------------------- |
| A linear pipeline (A→B→C→D) | `references/templates/data_flow_template.py` — edit `STAGES`                     |
| A two-option comparison     | `references/templates/comparison_template.py` — edit `LEFT_ITEMS`, `RIGHT_ITEMS` |
| A chronological timeline    | `references/templates/timeline_template.py` — edit `EVENTS`                      |
| Anything else               | Write from scratch using the relevant rule file                                  |

When using a template: copy it to the working directory, edit the config constants at the top, do not restructure the class.

Core rules:

- **Single file, single Scene class**: Everything in one `.py` file with one `class XxxScene(Scene)`.
- **Self-contained**: No external assets unless absolutely necessary. Use Manim primitives for everything.
- **Readable code**: The scene file IS the user's artifact. Use clear variable names, comments for each animation beat.
- **Color with intention**: Use Manim's color constants (BLUE, RED, GREEN, YELLOW, etc.) or hex colors. Max 4-5 colors. Every color should encode meaning.
- **Pacing**: Include `self.wait()` calls between logical sections. 0.5s for breathing room, 1-2s for major transitions.
- **Text legibility**: Use `font_size=36` minimum for body text, `font_size=48+` for titles. Test at target resolution.
- **Scene dimensions**: Default Manim canvas is 14.2 × 8 units (16:9). Keep content within ±6 horizontal, ±3.5 vertical.

### Animation best practices

```python
# DO: Use animation groups for simultaneous effects
self.play(FadeIn(box), Write(label), run_time=1)

# DO: Use .animate syntax for property changes
self.play(box.animate.shift(RIGHT * 2).set_color(GREEN))

# DO: Stagger related elements
self.play(LaggedStart(*[FadeIn(item) for item in items], lag_ratio=0.2))

# DON'T: Add/remove without animation (jarring)
self.add(box)  # Only for setup before first frame

# DON'T: Make animations too fast
self.play(Transform(a, b), run_time=0.3)  # Too fast to read
```

### Structure template

```python
from manim import *

class ConceptScene(Scene):
    def construct(self):
        # === Section 1: Title / Setup ===
        title = Text("Concept Name", font_size=56, weight=BOLD)
        self.play(Write(title))
        self.wait(1)
        self.play(FadeOut(title))

        # === Section 2: Core animation ===
        # ... main content here ...

        # === Section 3: Summary / Conclusion ===
        # ... wrap-up animation ...
        self.wait(2)
```

## Step 3: Preview render

Use low quality for fast iteration:

```bash
python3 scripts/render_video.py scene.py ConceptScene --quality low --format mp4
```

This renders at 480p/15fps — fast enough for previewing timing and layout. Present the video to the user.

## Step 4: Iterate

Common refinement requests and how to handle them:

| Request                  | Action                                                |
| ------------------------ | ----------------------------------------------------- |
| "Slower/faster"          | Adjust `run_time=` params and `self.wait()` durations |
| "Change colors"          | Update color constants                                |
| "Add a step"             | Insert new animation block between sections           |
| "Reorder"                | Move code blocks around                               |
| "Different layout"       | Adjust `.shift()`, `.next_to()`, `.arrange()` calls   |
| "Add labels/annotations" | Add `Text` or `MathTex` objects with `.next_to()`     |
| "Make it loop"           | Add matching intro/outro states                       |

## Step 5: Final export

Once the user is satisfied:

```bash
python3 scripts/render_video.py scene.py ConceptScene --quality high --format mp4
```

### Quality presets

| Preset   | Resolution | FPS | Flag  | Use case             |
| -------- | ---------- | --- | ----- | -------------------- |
| `low`    | 480p       | 15  | `-ql` | Fast preview         |
| `medium` | 720p       | 30  | `-qm` | Draft review         |
| `high`   | 1080p      | 60  | `-qh` | Final delivery       |
| `4k`     | 2160p      | 60  | `-qk` | Presentation quality |

### Format options

| Format | Flag            | Use case                   |
| ------ | --------------- | -------------------------- |
| `mp4`  | `--format mp4`  | Standard video delivery    |
| `gif`  | `--format gif`  | Embeddable in docs, social |
| `webm` | `--format webm` | Web-optimized              |

### Delivering the output

Present both:

1. The `.py` scene file (for future editing)
2. The rendered video file (final output)

Copy the final video to `/mnt/user-data/outputs/` and present it.

## Step 5.5: Optional audio overlay

If the user provides audio (music or voiceover), or requests it:

```bash
# Background music at 25% volume with fade-in/out
python3 scripts/add_audio.py final.mp4 music.mp3 \
    --output final_with_audio.mp4 \
    --volume 0.25 --fade-in 2 --fade-out 3 --trim-to-video

# Voiceover at full volume, trimmed to video length
python3 scripts/add_audio.py final.mp4 voiceover.mp3 \
    --output final_narrated.mp4 --trim-to-video
```

For voiceover scripting before recording, read `references/rules/voiceover-scaffold.md`.
For subtitles/captions, read `references/rules/subtitles.md`.
For advanced multi-track mixing, read `references/rules/audio-overlay.md`.

## Error Handling

| Error                        | Cause                                       | Resolution                                                |
| ---------------------------- | ------------------------------------------- | --------------------------------------------------------- |
| `ModuleNotFoundError: manim` | Manim not installed                         | Run Step 0 setup commands                                 |
| `pangocairo` build error     | Missing system dev headers                  | `apt-get install -y libpango1.0-dev`                      |
| `FileNotFoundError: ffmpeg`  | ffmpeg not installed                        | `apt-get install -y ffmpeg`                               |
| Scene class not found        | Class name mismatch                         | Verify class name matches CLI argument                    |
| Overlapping objects          | Positions not calculated                    | Use `.next_to()`, `.arrange()`, explicit `.shift()` calls |
| Text cut off                 | Text too large or positioned near edge      | Reduce `font_size` or adjust position within ±6,±3.5      |
| Slow render                  | Too many objects or complex transformations | Reduce object count, simplify paths, use lower quality    |
| `LaTeX Error`                | LaTeX not installed (for MathTex)           | Use `Text` instead, or install `texlive-latex-base`       |

### LaTeX fallback

If LaTeX is not available, avoid `MathTex` and `Tex`. Use `Text` with Unicode math symbols instead:

```python
# Instead of: MathTex(r"\frac{1}{n} \sum_{i=1}^{n} x_i")
# Use:        Text("(1/n) Σ xᵢ", font_size=36)
```

## Agentic Mode (Opt-In)

Single-shot mode (default) is fast and cheap — the coder writes scene.py directly from a concept. Use agentic mode for production-quality renders where layout correctness and asset resolution matter enough to justify additional LLM and VLM calls.

### Pipeline

```
concept
  └─► plan_storyboard.py ──► storyboard.json
            │
            ▼
      fetch_assets.py (optional)
            │
            ▼
      coder writes scene.py
            │
            ▼
      render_video.py --max-fix-attempts N
            │  ▲
            │  └─ LLM fixup loop (on failure, up to N retries)
            ▼
      critic_pass.py --critic
            │  ▲
            │  └─ VLM layout patch (1 call with M image blocks)
            ▼
       final MP4
```

### Flag Reference

| Script            | Flag                  | Default     | Hard cap | Effect                                                        | Cost impact                                    |
| ----------------- | --------------------- | ----------- | -------- | ------------------------------------------------------------- | ---------------------------------------------- |
| `render_video.py` | `--max-fix-attempts`  | `0`         | `3`      | LLM-assisted auto-fix on render failure; 0 = disabled         | +1 LLM call per retry                          |
| `critic_pass.py`  | `--critic`            | disabled    | —        | Enable the VLM critic pass; noop without this flag            | +1 VLM call (N image blocks)                   |
| `critic_pass.py`  | `--critic-budget`     | `50000`     | —        | Token budget for critic call; aborts loudly if exceeded       | Sets ceiling; use to prevent runaway spend     |
| `critic_pass.py`  | `--frames`            | `5`         | `10`     | Frames sampled from the rendered video for the critic         | More frames → higher token cost per critic run |
| `fetch_assets.py` | `--adapter`           | `none`      | —        | Asset backend: `local`, `iconfinder`, `none`                  | `iconfinder` adds external API calls           |
| `fetch_assets.py` | `--asset-dir`         | —           | —        | Root directory for `--adapter=local`; required with local     | None                                           |

### Cost Tradeoffs

The fixup loop adds one LLM call per failed render attempt — with `--max-fix-attempts 3` you may pay up to 3 extra calls before the loop exhausts or succeeds. The critic pass adds one VLM call containing N PNG image blocks (default 5, max 10); each frame adds roughly 1 token per 800 bytes of base64-encoded PNG, so complex scenes at high resolution are materially more expensive. Setting `--critic-budget` to a conservative token ceiling (e.g. `20000`) causes `BudgetExceededError` before the API call is made, so you never pay for an accidentally oversized request — the error is loud and non-recoverable by design.

### Invocation Example

```bash
# 1. Plan
python3 scripts/plan_storyboard.py "explain transformer self-attention" \
    --output storyboard.json

# 2. (Optional) Fetch assets
python3 scripts/fetch_assets.py storyboard.json \
    --adapter local --asset-dir ./assets --output resolved.json

# 3. Coder writes scene.py (Claude writes this from storyboard.json)

# 4. Render with auto-fix
python3 scripts/render_video.py scene.py AttentionScene \
    --quality high --format mp4 --max-fix-attempts 3 \
    --output final.mp4

# 5. Critic pass
python3 scripts/critic_pass.py scene.py final.mp4 \
    --critic --critic-budget 40000 --frames 5
```

### Attribution

Agentic pipeline design (storyboard planner, auto-fix loop, VLM critic) is adapted from Code2Video (arXiv 2510.01174, MIT). See [`references/code2video/ATTRIBUTION.md`](references/code2video/ATTRIBUTION.md) for vendoring details and re-sync policy.

## Limitations

- **Manim + ffmpeg required** — cannot render without these dependencies.
- **Audio is post-render only** — Manim renders silent MP4s. Use `scripts/add_audio.py` to overlay audio after export.
- **LaTeX optional** — MathTex requires a LaTeX installation. Fall back to Text with Unicode for math.
- **Render time scales with complexity** — a 30-second 1080p scene with many objects can take 1-2 minutes to render.
- **3D scenes require OpenGL** — ThreeDScene may not work in headless containers. Stick to 2D Scene class.
- **No interactivity** — output is a static video file, not an interactive widget.
- **GIF output is silent** — audio overlay only works with MP4/WEBM output formats.

## Design anti-patterns to avoid

- Walls of text on screen — keep to 3-5 words per label, max 2 lines
- Everything appearing at once — use staged animations with LaggedStart
- Uniform timing — vary run_time to create rhythm (fast for simple, slow for important)
- No visual hierarchy — use size, color, and position to guide attention
- Rainbow colors — 3-4 intentional colors max
- Ignoring the grid — align objects to consistent positions using arrange/align
