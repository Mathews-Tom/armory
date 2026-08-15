---
name: tldraw
description: 'Generate hand-drawn whiteboard-style diagrams (.tldr) from natural language and export to PNG/SVG via tldraw-cli, with vision-based self-check and an iterative review loop. Covers flowcharts, sequence diagrams, ERDs, UML sketches, and ML model diagrams. Triggers on: "whiteboard diagram", "sketch this out", "tldraw diagram", "hand-drawn diagram", "flowchart", "sequence diagram", "ERD diagram", "UML sketch", "ML model diagram", "draw a diagram". NOT for polished business/infra diagrams, use architecture-diagram.'
metadata:
  version: 1.0.0
  category: visualization
  tags: [diagram, whiteboard, tldraw, flowchart, sequence-diagram, erd, uml, visualization]
  difficulty: intermediate
  complements:
    - architecture-diagram
---

# tldraw Whiteboard Diagrams

## Overview

Generate hand-drawn whiteboard-style diagrams as `.tldr` JSON files and export to PNG/SVG using `@kitschpatrol/tldraw-cli`. tldraw produces a hand-drawn aesthetic with rich shape libraries and smooth arrow routing — well-suited for casual, sketch-style visualizations rather than polished business diagrams.

**Format:** `.tldr` JSON
**Export:** PNG, SVG (via `@kitschpatrol/tldraw-cli`)
**Aesthetic:** Hand-drawn whiteboard style by default; switchable to clean fonts via `font` prop.

## When to Use

| User need | Use `tldraw` | Use instead |
|---|---:|---|
| Whiteboard / hand-drawn-style flowchart, sequence, ERD, or UML sketch | Yes | — |
| ML / deep-learning model diagram with tensor-shape annotations | Yes | — |
| Freehand or figurative sketching (the `draw` shape) | Yes | — |
| Polished business/infra/deployment architecture diagram | No | `architecture-diagram` |
| Logos, solid-color graphics, or filled icons | No | tldraw has no opaque fill (`solid` = light tint); use the original vector source |
| Interactive HTML dashboard or infographic | No | `static-web-artifacts-builder` |
| Data charts, plots, sparklines | No | `chart-clarity` |

**Proactive triggers:** explaining a system with 3+ interacting components, describing a multi-step process or data flow, showing relationships between services/modules, decision trees, or ML model layers.

**Skip when:** a simple list or table suffices, or the user is in a quick Q&A flow.

**Known constraints** (route elsewhere or set expectations if these matter):
- No opaque fill — `solid` renders as a light tint, so white-on-dark artwork can't be reproduced.
- Manual coordinates only — no automatic layout of many nodes.
- Arrowheads are filled triangles/diamonds, not the hollow heads strict UML notation uses.
- PDF export isn't supported by `tldraw-cli` (PNG/SVG only).

## Prerequisites

Uses `@kitschpatrol/tldraw-cli` — a third-party, MIT-licensed export tool maintained independently of the tldraw.dev project. It is not the official `create-tldraw` project-scaffolding CLI; don't confuse the two. It renders `.tldr` files to PNG/SVG via a headless Chrome instance (puppeteer).

```bash
# Install tldraw-cli
npm install -g @kitschpatrol/tldraw-cli

# Verify
tldraw --version
```

Works identically on macOS, Windows, and Linux.

**First-export note:** `tldraw export` renders through a pinned Chrome build via puppeteer. The first export can fail with `Could not find Chrome (ver. <x>)`. The error names the exact version it needs — install it once, then exports work:

```bash
# The error message names the version; substitute it here
npx puppeteer browsers install chrome@<version-from-error>
```

(Installs to `~/.cache/puppeteer`; only needed once per CLI version.)

## Workflow

Before starting, assess whether the user's request is specific enough. If key details are missing, ask 1-3 focused questions:
- **Diagram type** — which preset? (Architecture, Flowchart, Sequence, ML/DL, ERD, UML, or general)
- **Output format** — PNG (default), SVG?
- **Output location** — default is the user's working dir; honor any explicit path the user gives (e.g. "put it in `./artifacts/`"). Don't ask if they didn't mention one.
- **Scope/fidelity** — how many components? Any specific technologies or labels?

Skip clarification if the request already specifies these details or is clearly simple (e.g., "draw a flowchart of X").

1. **Check deps** — verify `tldraw --version` succeeds; if missing, run `npm install -g @kitschpatrol/tldraw-cli`.
2. **Plan** — identify shapes (geo type per node), connections (arrows with source/target), and layout (TB or LR, group by tier/role). Sketch a coordinate grid before writing JSON. See `references/diagram-presets.md` for layout rules, index ordering, and per-diagram-type shape/color conventions.
3. **Generate** — write the `.tldr` JSON file using the record formats in `references/tldr-format.md` (shapes) and `references/arrows-and-containers.md` (arrows, frames, notes). Default output dir is the user's working dir; if the user specified a path or directory (e.g. `./artifacts/`), `mkdir -p` it first and write there. Apply the same dir choice to PNG/SVG exports in steps 4 and 7.
4. **Export draft** — run CLI to produce a PNG for preview. See `references/troubleshooting.md` for export command syntax.
5. **Self-check** — use the agent's built-in vision capability to read the exported PNG, catch obvious issues, auto-fix before showing the user (requires a vision-enabled model such as Claude Sonnet/Opus). If vision is unavailable, skip this step.
6. **Review loop** — show image to user, collect feedback, apply targeted JSON edits, re-export, repeat until approved.
7. **Final export** — export the approved version to all requested formats; report file paths for both the `.tldr` source and exported image(s).

### Step 5: Self-Check

After exporting the draft PNG, use the agent's vision capability (e.g., Claude's image input) to read the image and check for these issues before showing the user. If the agent does not support vision, skip self-check and show the PNG directly.

tldraw's own AI agent flags exactly three structural defects — **text overflow** (a box too small for its label), **overlapping text**, and **friendless arrows** (an arrow with an unbound end). The first three rows below target those; size boxes correctly up front (see the sizing formula in `references/diagram-presets.md`) and they rarely occur.

| Check | What to look for | Auto-fix action |
|-------|-----------------|-----------------|
| Text overflow | Label spills past the shape's border, or the box looks taller than you set (tldraw auto-grows an undersized box) | Increase `w`/`h` to fit the label — see the sizing formula in `references/diagram-presets.md` |
| Overlapping text | Two text-bearing shapes' labels touch or overlap, hurting legibility | Shift shapes apart by ≥200px |
| Friendless arrow | An arrow with one end not connected to a shape (floats loose) | Bind both ends: every arrow's `start` and `end` need a `boundShapeId` matching an existing shape |
| Off-canvas shapes | Shapes at negative coordinates or far from the main group | Move to positive coordinates near the cluster |
| Arrow-shape overlap | An arrow visually crosses through an unrelated shape | Adjust `bend` value or move endpoints to a different `normalizedAnchor` side |
| Stacked arrows | Multiple arrows overlap each other on the same path | Distribute `normalizedAnchor` across the shape perimeter (use different x/y values) |

- Max **2 self-check rounds** — if issues remain after 2 fixes, show the user anyway.
- Re-export after each fix and re-read the new PNG.

### Step 6: Review Loop

After self-check, show the exported image and ask the user for feedback.

**Targeted edit rules** — for each type of feedback, apply the minimal JSON change:

| User request | JSON edit action |
|-------------|-----------------|
| Change color of X | Find shape by `props.text` matching X, update `props.color` |
| Add a new node | Append a new shape record with next available index, position near related nodes |
| Remove a node | Delete the shape record and any arrow records bound to it |
| Move shape X | Update the shape's `x`/`y` fields |
| Resize shape X | Update `props.w`/`props.h` |
| Add arrow from A to B | Append a new arrow record binding to A and B's shape ids |
| Change label text | Update `props.text` on the matching shape or arrow |
| Change layout direction | **Full regeneration** — replan the grid and rebuild |

**Rules:**
- For single-element changes: edit the existing JSON in place — preserves layout tuning from prior iterations.
- For layout-wide changes (e.g., swap LR↔TB, "start over"): regenerate full JSON.
- Overwrite the same `{name}.png` each iteration — do not create `v1`, `v2`, `v3` files.
- After applying edits, re-export and show the updated image.
- Loop continues until user says approved / done / LGTM.
- **Safety valve:** after 5 iteration rounds, suggest the user open the `.tldr` file in tldraw.com or the desktop app for fine-grained adjustments.

## References

- `references/tldr-format.md` — `.tldr` file skeleton, geo shape record, geo types, color palette, style options
- `references/arrows-and-containers.md` — arrow record, connection rules, arrowheads, distributing arrows, frames, notes
- `references/diagram-presets.md` — index ordering, layout tips, box-sizing formula, per-diagram-type shape/color presets (architecture, flowchart, sequence, ML, ERD, UML)
- `references/troubleshooting.md` — export commands, common mistakes, fallback chain when tools/vision are unavailable
- `references/upstream/provenance.md` — upstream source, pinned commit, what was vendored/adapted/skipped

This skill adapts Agents365-ai's MIT-licensed `tldraw-skill` into armory as `tldraw`.
