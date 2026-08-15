# Layout, Indexing & Diagram Presets

## Index Ordering Rules

Indices control z-order (stacking). Use this sequence:
```
a1, a2, a3, a4, a5, a6, a7, a8, a9,
aA, aB, aC, aD, aE, aF, aG, aH, aI, aJ, aK, aL, aM,
aN, aO, aP, aQ, aR, aS, aT, aU, aV, aW, aX, aY, aZ,
aa, ab, ac, ... az          ← continue here past aZ; never "a10"
```
- Geo shapes first: `a1` through `aF` (or as many as needed).
- Arrow shapes after: `aG`, `aH`, etc.
- Every shape must have a **unique** index.

---

## Layout Tips

**Spacing — scale with complexity:**

| Diagram complexity | Nodes | Horizontal gap | Vertical gap |
|-------------------|-------|----------------|--------------|
| Simple | ≤5 | 200px | 150px |
| Medium | 6–10 | 280px | 200px |
| Complex | >10 | 350px | 250px |

**Sizing boxes to fit labels (do this up front, not in self-check):** the `draw` font is wide. Compute `w`/`h` from the label so text never clips. Approximate per-character width and line height for the default `draw` font:

| `size` | char width (px) | line height (px) |
|--------|-----------------|------------------|
| `s` | 11 | 18 |
| `m` (default) | 15 | 28 |
| `l` | 22 | 40 |
| `xl` | 32 | 56 |

With `padding = 16` on each side:
- `w = ceil(longest_line_chars * char_width + 2*padding)`, then round up to the next multiple of 10.
- `h = ceil(num_lines * line_height + 2*padding)`, rounded up to a multiple of 10.

Example: a size-`m` box labeled `"API Gateway"` (11 chars, 1 line) → `w ≈ 11*15 + 32 = 197 → 200`, `h ≈ 28 + 32 = 60`. Multi-line labels (with `\n`) count the **longest** line for `w` and the line count for `h`. Err slightly large — extra padding looks fine, a too-narrow box hard-wraps a word mid-letters.

**Why this matters:** if a box is too short for its text, tldraw silently **grows it taller** on render (it sets the shape's `growY`) — so the box ends up bigger than the `h` you wrote and collides with whatever you placed below it. Sizing correctly up front keeps `growY` at 0 and your layout intact. This is the single most common cause of "the diagram looks cramped / boxes overlap" after export.

**Routing corridors:** between shape rows/columns, leave an extra ~80px empty corridor where arrows can route without crossing other shapes. Never place a shape in a gap that arrows need to traverse.

**Grid alignment:** snap all `x`, `y`, `w`, `h` values to **multiples of 10** — this matches tldraw's default `gridSize: 10` and makes manual editing easier.

**General rules:**
- Plan the grid before assigning x/y coordinates — sketch node positions mentally first.
- Group related nodes in the same horizontal or vertical band.
- Place heavily-connected "hub" nodes centrally so arrows radiate outward instead of crossing.
- For wide shapes (like an API Gateway spanning multiple downstream services), set `w` to cover the full span.
- Center-align a child node under its parent (same center x) to avoid diagonal routing.
- **Event bus pattern**: place the bus (hexagon) in the **center of the service row**, not below — services on either side reach it with short horizontal arrows (`normalizedAnchor.x = 1` left side, `0` right side), eliminating crossings.
- Horizontal connections never cross vertical nodes in the same row; use them for peer-to-peer and publish connections.

**Avoiding arrow-shape overlap:**
- Before finalizing coordinates, trace each arrow path mentally — if it must cross an unrelated shape, either move the shape or use `bend` to curve around.
- For tree/hierarchical layouts: assign nodes to layers (rows), connect only between adjacent layers to minimize crossings.
- For star/hub layouts: place the hub center, satellites around it — arrows stay short and radial.

---

## Diagram Type Presets

When the user requests a specific diagram type, apply the matching preset below for shapes, colors, and layout conventions.

### Architecture Diagram

| Element | `geo` | `color` | Notes |
|---------|-------|---------|-------|
| Client (web/mobile) | `rectangle` | `blue` | Top row, label by client type |
| Service / module | `rectangle` | `blue` | Mid rows, group by tier |
| Database | `ellipse` | `green` | Bottom row, one per service |
| Cache | `ellipse` | `yellow` | Sits beside its owning service |
| Queue / event bus | `hexagon` | `orange` | **Center of service row** for hub pattern |
| Gateway / load balancer | `triangle` | `violet` | Above services |
| External API | `cloud` | `red` | Edge of canvas, dashed arrows in |
| Auth / security | `rectangle` | `violet` | Often near gateway |

**Layout:** TB or LR by tier count; ≥4 tiers → TB. Hub nodes centered. Spacing scales with complexity (see table above).

### Flowchart

| Element | `geo` | `color` | Notes |
|---------|-------|---------|-------|
| Start / End | `ellipse` | `green` | Always at top and bottom |
| Process step | `rectangle` | `blue` | Default action box |
| Decision | `diamond` | `yellow` | Always label outgoing arrows (Yes / No) |
| I/O | `rectangle` (with `dash: dashed`) | `orange` | Distinguish from process via dashed border |
| Subprocess | `rectangle` | `violet` | Indicates a callable sub-flow |

**Layout:** TB, ~200px vertical gap. Decisions branch left/right, then merge back to center. Always label decision branches in the arrow's `props.text`.

### Sequence Diagram

tldraw doesn't have native lifeline shapes. Approximate with:

| Element | `geo` | `color` | Notes |
|---------|-------|---------|-------|
| Actor / object header | `rectangle` | `blue` | Top of column |
| Lifeline | `rectangle` (`w: 2`, `fill: solid`, `color: grey`) | `grey` | Thin vertical line under each actor header |
| Sync message | arrow with `arrowheadEnd: arrow` | `black` | Solid horizontal arrow |
| Async message | arrow with `dash: dashed` | `black` | Dashed horizontal arrow |
| Return message | arrow with `dash: dashed`, `color: grey` | `grey` | Grey dashed |

**Layout:** LR for actors (200–280px apart), TB for time. Each message is a horizontal arrow between two lifelines at increasing `y`.

### ML / Deep Learning Model Diagram

For neural network architecture diagrams — useful for paper figures and explainers.

| Element | `geo` | `color` | Notes |
|---------|-------|---------|-------|
| Input / Output | `rectangle` | `green` | Top and bottom of stack |
| Conv / Pooling | `rectangle` | `blue` | Standard layer block |
| Attention / Transformer | `rectangle` | `violet` | Distinct color for self-attention blocks |
| RNN / LSTM / GRU | `rectangle` | `yellow` | Recurrent layers |
| FC / Linear | `rectangle` | `orange` | Dense projection layers |
| Loss / Activation | `rectangle` | `red` | Final loss / softmax / activation |
| Skip connection | arrow with `bend: 30`, `dash: dashed` | `grey` | Curved dashed bypass |

**Tensor shape annotation:** include the dimensions in `props.text` on a second line. tldraw renders `\n` literally inside JSON strings, so use a real newline (the JSON encoder will write `\n`):

```
"text": "Conv2D\n(B, 64, 32, 32)"
```

**Layout:** TB (data flows top → bottom), layers ~150px apart. Skip connections curve around the main stack.

### ER Diagram (ERD)

tldraw lacks native table/row shapes. Approximate each entity as a tall rectangle with multi-line text.

| Element | `geo` | `color` | Notes |
|---------|-------|---------|-------|
| Entity | `rectangle` (`fill: solid`, `color: light-blue`) | `light-blue` | Title + columns as one multi-line text label |
| Column list | embedded in `props.text` with `\n` between rows | — | Mark PK with `*` prefix, FK with `>` |
| Relationship | arrow with `arrowheadStart: arrow`, `arrowheadEnd: arrow` | `black` | Both ends arrowed for many-to-many |
| Optional / weak relationship | arrow with `dash: dashed` | `grey` | Dashed for optional FK |

Label the arrow with cardinality (e.g., `1..*`, `0..1`) via `props.text`.

**Layout:** TB or grid; entities spaced ≥300px apart to leave room for column lists.

### UML Class Diagram

| Element | `geo` | `color` | Notes |
|---------|-------|---------|-------|
| Class | `rectangle` (`fill: solid`, `color: light-blue`) | `light-blue` | Title + attributes + methods as one multi-line `text` |
| Inheritance | arrow with `arrowheadEnd: triangle` | `black` | tldraw renders a filled `triangle` arrowhead — point it at the parent class |
| Composition | arrow with `arrowheadStart: diamond`, `arrowheadEnd: none` | `black` | tldraw renders a filled `diamond` head — put it on the owner (whole) end |
| Aggregation | arrow with `arrowheadStart: diamond` | `black` | Same diamond head; distinguish from composition via a label or note |
| Association | arrow with `arrowheadEnd: arrow` | `black` | Standard arrow |

**Note:** tldraw's `triangle`/`diamond` arrowheads are **filled**, whereas strict UML uses *hollow* triangles (inheritance) and either filled/hollow diamonds (composition/aggregation). The shapes read correctly for sketches and explainers; not a fit for publication-grade UML that requires hollow arrowheads.

**Layout:** TB, classes ~250px apart, interfaces above implementations.

---

