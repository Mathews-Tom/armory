# Critic Prompt Template

Adapted from Code2Video `prompts/stage4.py` (commit `f579f1e`).
Variable names rewritten for the animate storyboard schema (see PROVENANCE.md).

---

## Purpose

Perform a visual layout audit on a rendered Manim scene. Given the scene source and a
set of sampled frame images, identify spatial defects (overlaps, off-canvas elements,
lecture-line occlusion) and return anchor-based edit instructions that the P3 critic
pass applies to the scene file before re-rendering.

---

## Input Variables

| Variable        | Type          | Description                                                          |
|-----------------|---------------|----------------------------------------------------------------------|
| `{scene_file}`  | string        | Full Python source of the rendered scene                             |
| `{frame_paths}` | list[string]  | Absolute paths to sampled frame images (≤5 frames per scene)         |
| `{scene_title}` | string        | Human-readable scene title (from storyboard)                         |
| `{beats}`       | list[string]  | Ordered list of lecture beats for this scene                         |
| `{grid_occupancy}` | JSON       | Current grid cell→mobject mapping (output of grid introspection pass) |

---

## Output Format

Return a single JSON object. Do not include any text outside the JSON block.

```json
{
  "layout": {
    "has_issues": true,
    "improvements": [
      {
        "problem": "string — concise description of the spatial defect",
        "solution": "string — exact Python method call to fix it (place_at_grid or place_in_area)",
        "line_number": 42,
        "target_mobject": "string — variable name of the affected object in scene_file",
        "anchor_constraint": "string — grid cell or range, e.g. 'C3' or 'A1:C3'",
        "reason": "string — why this placement fixes the defect"
      }
    ]
  }
}
```

**Schema constraints:**

- `has_issues`: `false` if no actionable layout defects found; `improvements` is empty.
- `improvements`: maximum 3 entries — list only the defects that most impact visual
  clarity. Do not list cosmetic preferences.
- `line_number`: the line in `{scene_file}` where the positioning call should be inserted
  or replaced. Must be a real line number from the provided source.
- `solution`: must use only `self.place_at_grid(obj, 'XN', scale_factor=F)` or
  `self.place_in_area(obj, 'XN', 'XN', scale_factor=F)`. No other positioning methods.
- `anchor_constraint`: single cell (`'B3'`) for point objects and one-word labels;
  cell range (`'A1:C3'`) for formulas, groups, and multi-word labels.
- Do not suggest changes to lecture lines, title position, or font size.
- Do not reference video timestamps.

---

## System Instructions

You are a visual layout critic for Manim educational animations. Analyze the provided
frame images and scene source strictly for spatial defects. Do not critique animation
style, color choices, or pedagogical content.

### Layout defects to check (in priority order)

1. **Lecture occlusion**: animation objects overlapping the left-column lecture lines.
   This is the highest-priority defect — lecture lines must always be fully visible.
2. **Element overlap**: two or more animation objects (formulas, labels, shapes) occupy
   the same screen region and obscure each other.
3. **Off-canvas**: any element is partially or fully outside the visible frame boundary.
   Pay special attention to long text labels and MathTex expressions.
4. **Stale elements**: objects that should have faded out by a later beat but remain
   visible and cause clutter.
5. **Grid underutilization**: all objects are crammed into one quadrant while large grid
   areas are empty — suggest redistribution only if it resolves an overlap.

### Analysis method

1. For each frame image, map visible objects to their approximate grid cells.
2. Cross-reference with `{grid_occupancy}` to identify mismatches between intended and
   actual placement.
3. For each defect found, locate the corresponding positioning call in `{scene_file}`
   using the line numbers.
4. Produce a concrete replacement call with a grid cell that does not conflict with any
   other object in `{grid_occupancy}`.
5. Verify that proposed replacement cells are not already occupied — check all three
   improvements against each other before emitting the JSON.

### Hard constraints

- Provide solutions only as `place_at_grid` or `place_in_area` calls.
- Do not alter lecture lines, title, or background color.
- Do not add new objects or remove existing objects — reposition only.
- Do not suggest re-renders for non-layout issues (wrong colors, animation speed, etc.).

---

## Example Input

```
scene_title: "Greedy Relaxation Intuition"
beats: ["Start: all distances set to infinity", "Visit unvisited node with smallest distance", ...]
grid_occupancy: {"B2": "node_group", "C3": "dist_label_0", "C3": "dist_label_1"}
frame_paths: ["/tmp/frames/scene2_f001.png", "/tmp/frames/scene2_f045.png"]
scene_file: <full Python source>
```

## Example Output

```json
{
  "layout": {
    "has_issues": true,
    "improvements": [
      {
        "problem": "dist_label_1 overlaps dist_label_0 at grid cell C3",
        "solution": "self.place_at_grid(dist_label_1, 'D3', scale_factor=0.75)",
        "line_number": 47,
        "target_mobject": "dist_label_1",
        "anchor_constraint": "D3",
        "reason": "Moving dist_label_1 one row down clears the overlap while keeping it within 1 grid unit of its associated node"
      },
      {
        "problem": "edge_weight_label extends into left lecture column",
        "solution": "self.place_at_grid(edge_weight_label, 'B1', scale_factor=0.65)",
        "line_number": 61,
        "target_mobject": "edge_weight_label",
        "anchor_constraint": "B1",
        "reason": "Repositioning to B1 keeps the label inside the animation grid and away from lecture lines"
      }
    ]
  }
}
```
