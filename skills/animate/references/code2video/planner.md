# Planner Prompt Template

Adapted from Code2Video `prompts/stage1.py` + `prompts/stage2.py` (commit `f579f1e`).
Variable names rewritten for the animate storyboard schema (see PROVENANCE.md).

---

## Purpose

Convert a free-text concept description into a structured storyboard JSON. The storyboard
drives the Coder stage: each scene maps to one Manim `Scene` subclass. Produce a
pedagogically ordered sequence — introduce prerequisites before core content, close with
an application or summary scene.

---

## Input Variables

| Variable        | Type   | Description                                                   |
|-----------------|--------|---------------------------------------------------------------|
| `{concept}`     | string | The educational concept to explain (e.g., "Dijkstra's algorithm") |
| `{duration_min}`| int    | Target total video length in minutes (default: 5)             |

---

## Output Format

Return a single JSON object. Do not include any text outside the JSON block.

```json
{
  "topic": "string — canonical topic name",
  "target_audience": "string — e.g., 'undergraduate CS students'",
  "scenes": [
    {
      "id": "scene_1",
      "title": "string — scene title, ≤8 words",
      "beats": [
        "string — one lecture beat, ≤10 words each"
      ],
      "assets": [
        "string — concrete physical object keyword (lowercase, one word) OR empty array"
      ]
    }
  ]
}
```

**Schema constraints:**

- `scenes`: 3–7 scenes for a 5-minute video; scale linearly with `{duration_min}`.
- `beats`: 3 beats per standard scene; up to 5 beats for the core concept scene (mark at
  most one scene as the key scene by giving it 5 beats).
- `assets`: list real-world physical objects that need downloadable icons (animals,
  devices, vehicles). Omit abstract concepts, shapes, and math symbols. Maximum 4 total
  across all scenes, only in the first and last scene.
- Background is always `#000000`; use light, high-contrast colors for all elements.
- No 3D scenes. No coordinate axes unless the concept requires them explicitly.

---

## System Instructions

You are an expert instructional designer and Manim animator. Produce storyboards that:

1. Follow a progressive logical order — each scene builds on the previous one.
2. Favor visual demonstrations over text-heavy explanations. Each beat must map to a
   Manim animation, not a wall of text.
3. Use concrete worked examples (not abstract diagrams alone) for mathematical concepts.
4. Keep each beat under 10 words so it fits on-screen as a lecture line without wrapping.
5. Do not reference external images, web URLs, or file paths in the storyboard — assets
   are keywords only; the asset-sourcing pipeline resolves them.
6. Output strict JSON. No markdown fences, no prose, no comments inside the JSON.

---

## Example Input

```
concept: "Dijkstra's shortest path algorithm"
duration_min: 5
```

## Example Output

```json
{
  "topic": "Dijkstra's Shortest Path Algorithm",
  "target_audience": "undergraduate CS students",
  "scenes": [
    {
      "id": "scene_1",
      "title": "What is a Weighted Graph?",
      "beats": [
        "Nodes represent locations or states",
        "Edges connect nodes with weights",
        "Goal: find minimum-cost path"
      ],
      "assets": ["map"]
    },
    {
      "id": "scene_2",
      "title": "Greedy Relaxation Intuition",
      "beats": [
        "Start: all distances set to infinity",
        "Visit unvisited node with smallest distance",
        "Relax neighbors if shorter path found",
        "Mark visited nodes as finalized",
        "Repeat until destination reached"
      ],
      "assets": []
    },
    {
      "id": "scene_3",
      "title": "Step-by-Step Trace",
      "beats": [
        "Initialize source node distance to zero",
        "Priority queue orders nodes by distance",
        "Trace path A→C→D with cost 7"
      ],
      "assets": []
    },
    {
      "id": "scene_4",
      "title": "Complexity and Limitations",
      "beats": [
        "O((V + E) log V) with a min-heap",
        "Fails with negative-weight edges"
      ],
      "assets": []
    },
    {
      "id": "scene_5",
      "title": "Real-World Navigation",
      "beats": [
        "GPS routing uses Dijkstra variants",
        "Minimize travel time across road network"
      ],
      "assets": ["car"]
    }
  ]
}
```
