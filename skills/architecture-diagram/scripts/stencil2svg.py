#!/usr/bin/env python3
"""Convert mxGraph stencil XML (draw.io, Apache-2.0) into inline-ready SVG markup.

draw.io ships official AWS and GCP architecture icons as vector `mxgraph.*`
stencils — plain geometric primitives (`move`/`line`/`curve`/`arc`/`rect`/
`ellipse`) with no embedded raster images. This module reads one `<shape>`
element and emits the equivalent SVG body: a sequence of `<path>`/`<rect>`/
`<ellipse>` elements using `currentColor` for the default fill so a caller can
recolor per node.

Primitive semantics are grounded in draw.io's real renderer
(`javascript/src/js/shape/mxStencil.js` and
`javascript/src/js/util/mxAbstractCanvas2D.js` in the `mxgraph` npm package,
Apache-2.0), not guessed from the XML shape alone. Two behaviors that are easy
to get wrong from reading the XML in isolation:

- `alpha`, `fillalpha`, and `strokealpha` are three XML spellings for the same
  canvas operation (`canvas.setAlpha`) — they all set one unified opacity that
  applies to both fill and stroke, not independent fill/stroke alpha.
- `save`/`restore` clone and pop the *entire* paint state (fill color, stroke
  color, stroke width, alpha, dashed). Skipping this makes alpha set inside a
  `save` block leak into every primitive drawn after the matching `restore` —
  this is a common pattern (122 save/restore pairs in the GCP stencil set
  alone) that silently produces near-invisible icon glyphs if unhandled.

Unsupported primitives (`text`, `image`, `include-shape`, `rounded` path
corners, gradients) are skipped and recorded as warnings rather than
misrendered — none of the four provider stencil files this module targets use
them, so an appearance means the source moved and the geometry may be
incomplete.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, replace

UNSUPPORTED_TAGS = frozenset(
    {
        "text",
        "image",
        "include-shape",
        "gradientcolor",
        "shadow",
        "linkedin",
        "fontcolor",
    }
)


@dataclass(frozen=True)
class _State:
    fill: str = "currentColor"
    stroke: str = "none"
    stroke_width: float = 1.0
    alpha: float = 1.0
    dashed: bool = False


def _num(el: ET.Element, name: str, default: float = 0.0) -> float:
    v = el.get(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _path_d(path_el: ET.Element) -> str:
    """Build an SVG path `d` string from a stencil `<path>`'s move/line/curve/arc/close children."""
    d: list[str] = []
    for el in path_el:
        t = el.tag
        if t == "move":
            d.append("M{:g},{:g}".format(_num(el, "x"), _num(el, "y")))
        elif t == "line":
            d.append("L{:g},{:g}".format(_num(el, "x"), _num(el, "y")))
        elif t == "curve":
            d.append(
                "C{:g},{:g} {:g},{:g} {:g},{:g}".format(
                    _num(el, "x1"),
                    _num(el, "y1"),
                    _num(el, "x2"),
                    _num(el, "y2"),
                    _num(el, "x3"),
                    _num(el, "y3"),
                )
            )
        elif t == "quad":
            d.append(
                "Q{:g},{:g} {:g},{:g}".format(
                    _num(el, "x1"), _num(el, "y1"), _num(el, "x2"), _num(el, "y2")
                )
            )
        elif t == "arc":
            rx, ry = _num(el, "rx"), _num(el, "ry")
            rot = _num(el, "x-axis-rotation")
            laf, sf = int(_num(el, "large-arc-flag")), int(_num(el, "sweep-flag"))
            x, y = _num(el, "x"), _num(el, "y")
            d.append(f"A{rx:g},{ry:g} {rot:g} {laf},{sf} {x:g},{y:g}")
        elif t == "close":
            d.append("Z")
        # `rounded="1"` corner-smoothing on `<path>` and any other child tag is
        # intentionally unhandled here — see module docstring. Callers get a
        # warning from `convert_body` when a shape used `rounded`.
    return " ".join(d)


def _paint_attrs(state: _State, do_fill: bool, do_stroke: bool) -> str:
    parts = [f'fill="{state.fill if do_fill else "none"}"']
    parts.append(f'stroke="{state.stroke if do_stroke else "none"}"')
    if do_stroke:
        parts.append(f'stroke-width="{state.stroke_width:g}"')
        if state.dashed:
            parts.append('stroke-dasharray="4 3"')
    if state.alpha != 1.0:
        parts.append(f'opacity="{state.alpha:g}"')
    return " ".join(parts)


def convert_body(shape: ET.Element) -> tuple[str, str, list[str]]:
    """Convert one `<shape>` element to (viewBox, svg_body_markup, warnings)."""
    w, h = _num(shape, "w", 100.0), _num(shape, "h", 100.0)
    fg = shape.find("foreground")
    if fg is None:
        return f"0 0 {w:g} {h:g}", "", ["no <foreground> element"]

    elements: list[str] = []
    warnings: list[str] = []
    state = _State()
    stack: list[_State] = []
    pending: tuple[str, str] | None = None  # (kind, geometry-attrs-or-d)

    for el in fg:
        t = el.tag
        if t == "save":
            stack.append(state)
        elif t == "restore":
            if stack:
                state = stack.pop()
            else:
                warnings.append("restore with no matching save")
        elif t == "path":
            pending = ("path", _path_d(el))
        elif t == "rect":
            x, y, rw, rh = _num(el, "x"), _num(el, "y"), _num(el, "w"), _num(el, "h")
            pending = ("rect", f'x="{x:g}" y="{y:g}" width="{rw:g}" height="{rh:g}"')
        elif t == "roundrect":
            x, y, rw, rh = _num(el, "x"), _num(el, "y"), _num(el, "w"), _num(el, "h")
            arcsize = _num(el, "arcsize", 0.0)
            factor = (arcsize or 15.0) / 100.0
            r = min(rw, rh) * factor
            pending = (
                "rect",
                f'x="{x:g}" y="{y:g}" width="{rw:g}" height="{rh:g}" rx="{r:g}"',
            )
        elif t == "ellipse":
            x, y, ew, eh = _num(el, "x"), _num(el, "y"), _num(el, "w"), _num(el, "h")
            pending = (
                "ellipse",
                f'cx="{x + ew / 2:g}" cy="{y + eh / 2:g}" rx="{ew / 2:g}" ry="{eh / 2:g}"',
            )
        elif t == "fillcolor":
            state = replace(state, fill=el.get("color", "currentColor"))
        elif t == "strokecolor":
            color = el.get("color", "none")
            state = replace(state, stroke="none" if color == "none" else color)
        elif t == "strokewidth":
            raw = el.get("width", "1")
            state = replace(state, stroke_width=1.0 if raw == "inherit" else float(raw))
        elif t in ("alpha", "fillalpha", "strokealpha"):
            # All three set the same unified canvas alpha — see module docstring.
            state = replace(state, alpha=_num(el, "alpha", 1.0))
        elif t == "dashed":
            state = replace(state, dashed=el.get("dashed") == "1")
        elif t in ("linecap", "linejoin", "miterlimit"):
            pass  # cosmetic stroke joins/caps — not load-bearing for icon shape
        elif t in ("fill", "stroke", "fillstroke"):
            if pending is None:
                warnings.append(f"{t} with no preceding geometry")
                continue
            kind, geom = pending
            do_fill = t in ("fill", "fillstroke")
            do_stroke = t in ("stroke", "fillstroke")
            attrs = _paint_attrs(state, do_fill, do_stroke)
            if kind == "path":
                elements.append(f'<path d="{geom}" {attrs}/>')
            else:
                elements.append(f"<{kind} {geom} {attrs}/>")
            pending = None
        elif t in UNSUPPORTED_TAGS:
            warnings.append(f"unsupported primitive: <{t}>")
        else:
            warnings.append(f"unrecognized primitive: <{t}>")

    return f"0 0 {w:g} {h:g}", "".join(elements), warnings


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def iter_shapes(root: ET.Element) -> Iterable[ET.Element]:
    return root.iter("shape")


def load_shapes(path: str) -> dict[str, ET.Element]:
    root = ET.parse(path).getroot()
    return {s.get("name", ""): s for s in iter_shapes(root)}
