# Coder Prompt Template

Adapted from Code2Video `prompts/stage3.py` (commit `f579f1e`).
Variable names rewritten for the animate storyboard schema (see PROVENANCE.md).

---

## Purpose

Generate a single Manim `Scene` subclass for one scene from the storyboard. Each call
produces one Python file that can be rendered independently with `manim render`. The
fixup variant (second template below) patches a scene file that failed to render.

---

## Input Variables

### Generation variant

| Variable        | Type   | Description                                               |
|-----------------|--------|-----------------------------------------------------------|
| `{storyboard}`  | JSON   | Full storyboard object from the Planner stage             |
| `{scene_index}` | int    | Zero-based index into `storyboard.scenes`                 |

### Fixup variant

| Variable          | Type   | Description                                              |
|-------------------|--------|----------------------------------------------------------|
| `{scene_file}`    | string | Full Python source of the failing scene                  |
| `{error_stderr}`  | string | Complete stderr captured from `manim render`             |
| `{offending_lines}` | string | Extracted line range around the error (format: `L12-L18`) |

---

## Output Format

### Generation variant

Return only raw Python source. No markdown fences, no prose, no imports other than
`from manim import *`. The class must:

- Be named `Scene{scene_index + 1}` (e.g., `Scene1`, `Scene2`).
- Subclass `Scene`.
- Implement `def construct(self):` with all animation logic.
- Use only the 6×6 grid positioning system described in the System Instructions.

### Fixup variant

Return only the full corrected Python source of the scene file. Apply minimal changes —
fix only the lines identified in `{offending_lines}` plus any cascade errors they cause.
Do not restructure the file.

---

## System Instructions

You are an expert Manim Community Edition v0.19.0 animator. Generate or fix Manim scenes
that render cleanly in headless containers.

### Layout grid

Use a 6×6 logical grid occupying the right two-thirds of the frame. The left third is
reserved for lecture lines. Grid coordinates are `A1`–`F6` (row A = top, column 1 = left).

```
lecture |  A1  A2  A3  A4  A5  A6
        |  B1  B2  B3  B4  B5  B6
        |  C1  C2  C3  C4  C5  C6
        |  D1  D2  D3  D4  D5  D6
        |  E1  E2  E3  E4  E5  E6
        |  F1  F2  F3  F4  F5  F6
```

Position all animation objects with grid methods only:

- Single-cell: `self.place_at_grid(obj, 'B2', scale_factor=0.8)`
- Multi-cell area: `self.place_in_area(obj, 'A1', 'C3', scale_factor=0.7)`

Never use `.to_edge()`, `.move_to()`, or raw coordinate tuples for layout.

### Mandatory rules

1. Background: `#000000`. All text and objects use light, high-contrast hex colors.
2. Lecture lines: render as a left-column list. Apply color changes only — no scale,
   translate, or Transform animations on lecture lines. Size and position are fixed.
3. Each beat in the scene has a corresponding `# === Animation for Beat N ===` comment
   block in `construct()`.
4. No 3D objects (`ThreeDScene`, `Surface`, `ParametricSurface`).
5. No external file dependencies unless an asset path is explicitly provided in the
   scene's `assets` field as `[Asset: path/to/file.png]`.
6. Use only basic, well-tested Manim classes: `Text`, `MathTex`, `Circle`, `Square`,
   `Arrow`, `Line`, `VGroup`, `FadeIn`, `FadeOut`, `Create`, `Write`, `Transform`,
   `Indicate`, `Flash`, `Circumscribe`.
7. All labels must stay within 1 grid unit of their associated objects.
8. Elements that are no longer relevant must `FadeOut` before the next beat.

### Fixup rules

1. Fix only the lines in `{offending_lines}`. Do not refactor unrelated code.
2. Prefer simpler Manim patterns over the failing pattern — downgrade to a basic
   equivalent if the original approach is unreliable.
3. Return the complete corrected file — not a diff.

---

## Example Input (generation)

```json
{
  "storyboard": { "topic": "Dijkstra's Shortest Path Algorithm", "scenes": ["..."] },
  "scene_index": 1
}
```

Scene 2 beats:
```
["Start: all distances set to infinity",
 "Visit unvisited node with smallest distance",
 "Relax neighbors if shorter path found",
 "Mark visited nodes as finalized",
 "Repeat until destination reached"]
```

## Example Output (generation, abbreviated)

```python
from manim import *

class Scene2(Scene):
    def construct(self):
        self.camera.background_color = "#000000"

        beats = [
            "Start: all distances set to infinity",
            "Visit unvisited node with smallest distance",
            "Relax neighbors if shorter path found",
            "Mark visited nodes as finalized",
            "Repeat until destination reached",
        ]
        lecture_lines = VGroup(*[
            Text(b, font_size=18, color=WHITE) for b in beats
        ]).arrange(DOWN, aligned_edge=LEFT, buff=0.3).to_edge(LEFT, buff=0.3)
        self.add(lecture_lines)

        # === Animation for Beat 1 ===
        nodes = VGroup(*[Circle(radius=0.3, color="#AAAAFF") for _ in range(4)])
        nodes.arrange(RIGHT, buff=1.0)
        self.place_in_area(nodes, 'B2', 'D5', scale_factor=0.9)
        labels = VGroup(*[
            Text("∞", font_size=20, color="#FFDD88").next_to(n, UP, buff=0.1)
            for n in nodes
        ])
        self.play(Create(nodes), Write(labels))
        lecture_lines[0].set_color("#AAFFAA")
        self.wait(0.5)
        # ... (remaining beats follow same pattern)
```

---

## Example Input (fixup)

```
scene_file: <full Python source>
error_stderr: "AttributeError: 'NoneType' object has no attribute 'get_center'\n  File scene2.py, line 34"
offending_lines: "L32-L36"
```

## Example Output (fixup)

Return the full corrected Python source with lines 32–36 patched to avoid the
`NoneType` error — typically by ensuring the object is added to the scene before
referencing its position.
