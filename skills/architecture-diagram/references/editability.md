# Why the output is "completely editable" — and what that actually means

"Editable SVG" is easy to claim and easy to get wrong in ways that only surface once someone tries to actually edit the file. This document is the design rationale behind `scripts/render.py`'s output contract, and the concrete, checkable definition `check_editability()` enforces on every render.

## The three ways an SVG can quietly fail to be editable

**1. Raster icons wrapped in an SVG shell.** The most common failure mode among "SVG diagram" tools: the outer file is `.svg`, but each icon is `<image href="data:image/png;base64,...">` or `<image href="./icons/lambda.png">`. Opening it in Illustrator/Figma/Inkscape gives you an image object you can move and resize, not a shape you can recolor, reshape, or edit a node of. This skill's icon pipeline (`scripts/stencil2svg.py`, `scripts/svg_inline.py`) exists specifically to avoid this — every icon is real vector geometry (`<path>`, `<rect>`, `<ellipse>`) converted or extracted from the source, never a raster reference.

**2. `<use>` clones instead of inlined geometry.** The obvious way to avoid repeating the same icon's markup for every node that uses it is `<defs><symbol id="lambda">...</symbol></defs>` plus `<use href="#lambda">` per node — smaller file, same icon defined once. This looks editable (Figma imports it, Inkscape shows it in the Symbols dialog) but isn't, fully: both Inkscape's and the SVG spec's own semantics treat a `<use>` clone's contents as **not independently editable** — you can move, scale, or recolor the whole clone, but you cannot select and reshape one path inside it without first unlinking it ("Symbol to Group" in Inkscape) back into real geometry. `render.py` inlines each icon's body directly into every node's `<g>` instead. The cost is a larger file (each copy of an icon repeats its full path data); the benefit is that every single icon instance, on every node, is independently, fully editable the moment the file opens — no unlink step required.

**3. Text converted to outlines.** Exporting text as paths ("convert to outlines") guarantees pixel-identical rendering regardless of font availability, which is why some diagram tools do it by default. It also means the text is no longer text — you cannot select it, search it, or retype it; it's just more vector shapes. `render.py` never does this. Every label is a real `<text>` element with the actual string content. Reopening the SVG anywhere shows real, selectable, retypeable, searchable text — the tradeoff is that a viewer without the referenced font falls back to their system default, which is an acceptable cost for keeping the text real.

## What `check_editability()` actually verifies

Run automatically at the end of every `render()` call, not as an optional lint step:

```python
_FORBIDDEN_MARKERS = ("<image", "base64,", "<use ", "<use>")
```

Plus a check for any `href="http..."` or `xlink:href="http..."` — an external reference the file depends on network access to resolve, which breaks the moment the SVG is moved, emailed, or committed somewhere the referenced URL isn't reachable.

If any of these appear in a candidate, `validate` and `deliver` exit with status 1 and report an `editability` diagnostic. `deliver` never replaces an existing SVG when that happens — treat it as a renderer bug, not something to route around by hand-editing the SVG afterward. It should not happen; the icon pipeline was built specifically to avoid every one of these failure modes, and the tests in `tests/test_render.py::TestEditabilityCheck` and the end-to-end assertions in `TestEndToEndRender` exist to catch a regression.

## What this buys, concretely

Open any diagram this skill produces in:

- **Figma / Illustrator** — every icon and every zone box is a real, independently editable vector layer; every label is real, retypeable text.
- **Inkscape** — same; nothing needs "Symbol to Group" unlinking first.
- **A text editor** — the file is plain, readable SVG/XML; grep it, diff it, hand-edit a color if you want to.
- **A browser or `<img>` tag** — renders correctly with zero external dependencies; the file is fully self-contained.
- **GitHub / a Markdown viewer** — renders inline in a README exactly as it would locally.

None of that is true of a PNG, and only some of it is true of an SVG that took a shortcut on any of the three failure modes above.
