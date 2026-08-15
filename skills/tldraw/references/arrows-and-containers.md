# Arrows, Frames & Notes

## Arrow Record

```json
{
  "id": "shape:a1",
  "typeName": "shape",
  "type": "arrow",
  "parentId": "page:page1",
  "index": "aG",
  "x": 0,
  "y": 0,
  "rotation": 0,
  "isLocked": false,
  "opacity": 1,
  "meta": {},
  "props": {
    "dash": "draw",
    "size": "m",
    "fill": "none",
    "color": "black",
    "labelColor": "black",
    "bend": 0,
    "start": {
      "type": "binding",
      "boundShapeId": "shape:s1",
      "normalizedAnchor": {"x": 0.5, "y": 1},
      "isExact": false
    },
    "end": {
      "type": "binding",
      "boundShapeId": "shape:s2",
      "normalizedAnchor": {"x": 0.5, "y": 0},
      "isExact": false
    },
    "arrowheadStart": "none",
    "arrowheadEnd": "arrow",
    "text": "",
    "font": "draw"
  }
}
```

### Arrow Connection Rules

- Arrow record `x` and `y` are always `0, 0`.
- Use `"type": "binding"` with `boundShapeId` to connect to a specific shape.
- `normalizedAnchor` specifies WHERE on the target shape the arrow connects (0–1 range):
  - `{x: 0.5, y: 0}` = top center
  - `{x: 0.5, y: 1}` = bottom center
  - `{x: 0, y: 0.5}` = left center
  - `{x: 1, y: 0.5}` = right center
  - `{x: 0.5, y: 0.5}` = center
- Add `"text": "label"` in arrow props for labeled connections.
- Use `"bend": 20` (or `-20`) for slight curves to avoid overlap with other arrows.
- For dashed/dotted arrows (e.g., async flows, optional links), set `"dash": "dashed"` or `"dotted"`.
- Set `"spline": "cubic"` for a smooth curved arrow (default `"line"` is straight/elbow). Useful for skip connections and back-edges.

### Arrowheads

`arrowheadStart` and `arrowheadEnd` each accept any of these 9 values (all render in `@kitschpatrol/tldraw-cli`):

| Value | Looks like | Use for |
|-------|-----------|---------|
| `none` | (no head) | start of a one-way arrow |
| `arrow` | open V | default flow direction |
| `triangle` | filled ▶ | UML inheritance / "is-a" |
| `diamond` | filled ◆ | UML composition / aggregation (on the owner end) |
| `dot` | ● | sequence-diagram message endpoints |
| `square` | ■ | terminal / fixed endpoint |
| `bar` | \| | "stop" / boundary marker |
| `pipe` | \|\| | alternative boundary marker |
| `inverted` | hollow V | de-emphasized direction |

Default arrows use `"arrowheadStart": "none"`, `"arrowheadEnd": "arrow"`. For bidirectional links set both ends to `"arrow"`.

### Distributing Arrows on a Shape

When multiple arrows connect to the same shape, assign different `normalizedAnchor` points to prevent stacking:

| Position | x | y | Use when |
|----------|---|---|----------|
| Top center | 0.5 | 0 | connecting to node above |
| Top-left | 0.25 | 0 | 2nd connection from top |
| Top-right | 0.75 | 0 | 3rd connection from top |
| Right center | 1 | 0.5 | connecting to node on right |
| Bottom center | 0.5 | 1 | connecting to node below |
| Left center | 0 | 0.5 | connecting to node on left |

**Rule:** if a shape has N connections on one side, space them evenly (e.g., 3 connections on bottom → x = 0.25, 0.5, 0.75).

### Multiple Arrows Between the Same Two Nodes

The anchor-distribution rule above spreads arrows going to *different* nodes. When **N arrows connect the same pair** (e.g., bidirectional request/response, or several relationships A↔B), anchors can't separate them — instead spread the `bend` values symmetrically so the arrows fan out into distinct arcs:

- Pick a max bend `amount` (≈ 30–60; larger for nodes that are far apart).
- Assign the N arrows bends evenly spaced from `−amount` to `+amount`:
  - **2 arrows** → `bend: -amount`, `bend: +amount`
  - **3 arrows** → `bend: -amount`, `0`, `+amount`
  - General: `bend[i] = -amount + i * (2*amount / (N-1))` for `i = 0..N-1`
- A straight arrow plus a single curved one (`bend: 0` and `bend: 40`) reads cleanly for a request/response pair.

---

## Container & Annotation Shapes

Beyond `geo` and `arrow`, two more shape types are useful for technical diagrams.

### Frame (labeled container — tiers, subsystems, swimlanes)

A `frame` is a native rectangular container with a title. Use it to group a tier or subsystem with a visible boundary; stack several frames to approximate swimlanes.

```json
{
  "id": "shape:frame1", "typeName": "shape", "type": "frame",
  "parentId": "page:page1", "index": "a1",
  "x": 60, "y": 60, "rotation": 0, "isLocked": false, "opacity": 1, "meta": {},
  "props": { "w": 360, "h": 220, "name": "Backend Tier", "color": "black" }
}
```

- `props.name` is the title shown at the frame's top-left.
- **Child shapes set `"parentId": "shape:frame1"`** (not `page:page1`), and their `x`/`y` are **relative to the frame's top-left corner**, not the page. A child at `x: 40, y: 60` sits 40px in and 60px down from the frame's origin.
- Frames render as a clean (non-hand-drawn) rectangle — good for structural grouping. Arrows can still bind across frames normally.

### Note (sticky-note annotation / callout)

A `note` is a sticky note — ideal for TODOs, callouts, and comments layered onto a diagram.

```json
{
  "id": "shape:n1", "typeName": "shape", "type": "note",
  "parentId": "page:page1", "index": "a4",
  "x": 480, "y": 80, "rotation": 0, "isLocked": false, "opacity": 1, "meta": {},
  "props": { "color": "yellow", "size": "m", "text": "TODO: add retry\nlogic here",
    "font": "draw", "align": "middle", "verticalAlign": "middle",
    "growY": 0, "fontSizeAdjustment": 0, "url": "", "scale": 1, "labelColor": "black" }
}
```

- A note has **no `w`/`h`** — it's a fixed square (~200px) that auto-grows for longer text. Don't add `w`/`h`.
- `yellow` is the classic sticky color; any palette color works.
- Use notes sparingly — for annotations *about* the diagram, not as primary nodes (use `geo` for those).

---

