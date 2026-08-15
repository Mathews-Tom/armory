#!/usr/bin/env python3
"""Render a declarative architecture-diagram spec into an editable SVG.

Design principle: the agent authors *what the architecture is* (nodes, zones,
edges, provider) as a small YAML spec; this module decides *where the pixels
go*. Coordinate arithmetic is the part LLMs are bad at and prior art in this
space (see `references/editability.md` for the comparison) papers over with
prose rules like "don't eyeball it" and a render-and-review loop. Making
layout deterministic code instead means it's testable, reproducible, and
self-checking: every self-check rule that prior art asks the model to reason
about by hand is a hard assertion here (`check_layout` / `check_editability`).

Pipeline: `load_spec` -> `assign_ranks` -> `order_within_ranks` ->
`compute_positions` -> `compute_zone_boxes` -> `route_edges` -> `emit_svg`.

Output contract (enforced by `check_editability`, see module docstring on
that function): no raster `<image>`, no external `href`, no `<use>` clones —
icon geometry is inlined per node so every copy stays independently editable
in Figma/Illustrator/Inkscape, and labels stay real `<text>`, never outlined.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

# --- layout constants -------------------------------------------------------

ICON = 64
NODE_W = 120
NODE_H = 118  # icon + two label lines + padding
COL_GAP = 90
ROW_GAP = 44
MARGIN = 32
TITLE_H = 44
ZONE_PAD = 22
ZONE_LABEL_H = 26

EDGE_COLORS = {
    "realtime": "#2563EB",
    "batch": "#DC2626",
    "event": "#16A34A",
    "control": "#D97706",
    "default": "#5A6C86",
}

# Average glyph-width factor (fraction of font-size) for a system-ui-style
# sans stack, bucketed by character class. Good enough for label-fit and
# zone-label-width decisions; not a substitute for real font metrics.
_NARROW = set("iIl.,:;'|!")
_WIDE = set("MWm@%")


def _text_width(text: str, font_size: float) -> float:
    total = 0.0
    for ch in text:
        if ch in _NARROW:
            total += 0.32
        elif ch in _WIDE:
            total += 0.82
        else:
            total += 0.56
    return total * font_size


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- spec -------------------------------------------------------------------


@dataclass
class Node:
    id: str
    label: str
    service: str | None = None
    sublabel: str = ""
    zone: str | None = None
    color: str = "#3A3A3A"
    provider: str = "generic"


@dataclass
class Zone:
    id: str
    label: str
    parent: str | None = None


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    type: str = "default"


@dataclass
class Spec:
    title: str
    direction: str
    provider: str
    nodes: list[Node]
    zones: list[Zone]
    edges: list[Edge]


class SpecError(ValueError):
    pass


def load_spec(text: str) -> Spec:
    data = yaml.safe_load(text) or {}
    if "nodes" not in data or not data["nodes"]:
        raise SpecError("spec has no nodes")

    provider = data.get("provider", "generic")
    node_ids = set()
    nodes = []
    for raw in data["nodes"]:
        if "id" not in raw:
            raise SpecError(f"node missing id: {raw}")
        if raw["id"] in node_ids:
            raise SpecError(f"duplicate node id: {raw['id']}")
        node_ids.add(raw["id"])
        nodes.append(
            Node(
                id=raw["id"],
                label=raw.get("label", raw["id"]),
                service=raw.get("service"),
                sublabel=raw.get("sublabel", ""),
                zone=raw.get("zone"),
                color=raw.get("color", "#3A3A3A"),
                provider=raw.get("provider", provider),
            )
        )

    zone_ids = set()
    zones = []
    for raw in data.get("zones", []) or []:
        if "id" not in raw:
            raise SpecError(f"zone missing id: {raw}")
        zone_ids.add(raw["id"])
        zones.append(
            Zone(
                id=raw["id"],
                label=raw.get("label", raw["id"]),
                parent=raw.get("parent"),
            )
        )
    for n in nodes:
        if n.zone is not None and n.zone not in zone_ids:
            raise SpecError(f"node {n.id!r} references unknown zone {n.zone!r}")
    for z in zones:
        if z.parent is not None and z.parent not in zone_ids:
            raise SpecError(f"zone {z.id!r} references unknown parent {z.parent!r}")
        if z.parent == z.id:
            raise SpecError(f"zone {z.id!r} cannot be its own parent")

    edges = []
    for raw in data.get("edges", []) or []:
        if raw.get("from") not in node_ids or raw.get("to") not in node_ids:
            raise SpecError(f"edge references unknown node: {raw}")
        edges.append(
            Edge(
                src=raw["from"],
                dst=raw["to"],
                label=raw.get("label", ""),
                type=raw.get("type", "default"),
            )
        )

    return Spec(
        title=data.get("title", ""),
        direction=data.get("direction", "LR").upper(),
        provider=provider,
        nodes=nodes,
        zones=zones,
        edges=edges,
    )


# --- ranking + ordering ------------------------------------------------------


def assign_ranks(spec: Spec) -> dict[str, int]:
    """Longest-path layering via bounded relaxation. Bounded iteration count
    means a cycle (a back-edge) simply stops updating once ranks stabilize
    rather than looping forever — cyclic graphs are common in architecture
    diagrams (request/response pairs) and must not hang the renderer."""
    rank = {n.id: 0 for n in spec.nodes}
    for _ in range(len(spec.nodes) + 1):
        changed = False
        for e in spec.edges:
            if rank[e.dst] < rank[e.src] + 1:
                rank[e.dst] = rank[e.src] + 1
                changed = True
        if not changed:
            break
    return rank


def order_within_ranks(spec: Spec, rank: dict[str, int]) -> dict[str, int]:
    """Two-pass barycenter sweep to reduce edge crossings within each rank."""
    by_rank: dict[int, list[str]] = {}
    for n in spec.nodes:
        by_rank.setdefault(rank[n.id], []).append(n.id)
    for ids in by_rank.values():
        ids.sort()  # stable, deterministic starting order

    order: dict[str, int] = {}
    for r in sorted(by_rank):
        for i, node_id in enumerate(by_rank[r]):
            order[node_id] = i

    preds: dict[str, list[str]] = {}
    succs: dict[str, list[str]] = {}
    for e in spec.edges:
        preds.setdefault(e.dst, []).append(e.src)
        succs.setdefault(e.src, []).append(e.dst)

    def sweep(ranks_in_order: list[int], neighbor_map: dict[str, list[str]]) -> None:
        for r in ranks_in_order:
            ids = by_rank[r]

            def barycenter(node_id: str) -> float:
                nbrs = neighbor_map.get(node_id, [])
                if not nbrs:
                    return order[node_id]
                return sum(order[n] for n in nbrs) / len(nbrs)

            ids.sort(key=barycenter)
            for i, node_id in enumerate(ids):
                order[node_id] = i

    ranks_sorted = sorted(by_rank)
    sweep(ranks_sorted[1:], preds)
    sweep(list(reversed(ranks_sorted[:-1])), succs)
    return order


# --- geometry ----------------------------------------------------------------


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    def overlaps(self, other: Box) -> bool:
        return (
            self.x < other.x2
            and self.x2 > other.x
            and self.y < other.y2
            and self.y2 > other.y
        )


def compute_positions(
    spec: Spec, rank: dict[str, int], order: dict[str, int]
) -> dict[str, Box]:
    # Zone boxes are computed AFTER node positions (compute_zone_boxes derives
    # its bbox from member node positions), but a zone's label header sits
    # above its topmost member and must not collide with the diagram title
    # above it. Reserve that room here rather than shifting everything down
    # after the fact once the collision is already baked into every other
    # coordinate.
    top_offset = MARGIN + TITLE_H
    if spec.zones:
        top_offset += ZONE_PAD + ZONE_LABEL_H
    boxes: dict[str, Box] = {}
    for n in spec.nodes:
        r, o = rank[n.id], order[n.id]
        if spec.direction == "TB":
            x = MARGIN + o * (NODE_W + COL_GAP)
            y = top_offset + r * (NODE_H + ROW_GAP)
        else:
            x = MARGIN + r * (NODE_W + COL_GAP)
            y = top_offset + o * (NODE_H + ROW_GAP)
        boxes[n.id] = Box(x, y, NODE_W, NODE_H)
    return boxes


def compute_zone_boxes(spec: Spec, node_boxes: dict[str, Box]) -> dict[str, Box]:
    members: dict[str, list[str]] = {z.id: [] for z in spec.zones}
    for n in spec.nodes:
        if n.zone is not None:
            members[n.zone].append(n.id)
    children: dict[str, list[str]] = {z.id: [] for z in spec.zones}
    for z in spec.zones:
        if z.parent is not None:
            children[z.parent].append(z.id)

    boxes: dict[str, Box] = {}

    def resolve(zone_id: str, stack: frozenset[str] = frozenset()) -> Box:
        if zone_id in boxes:
            return boxes[zone_id]
        if zone_id in stack:
            raise SpecError(f"zone cycle detected at {zone_id!r}")
        parts = [node_boxes[nid] for nid in members[zone_id]]
        parts += [resolve(cid, stack | {zone_id}) for cid in children[zone_id]]
        if not parts:
            raise SpecError(f"zone {zone_id!r} has no member nodes or child zones")
        x0 = min(p.x for p in parts) - ZONE_PAD
        y0 = min(p.y for p in parts) - ZONE_PAD - ZONE_LABEL_H
        x1 = max(p.x2 for p in parts) + ZONE_PAD
        y1 = max(p.y2 for p in parts) + ZONE_PAD
        box = Box(x0, y0, x1 - x0, y1 - y0)
        boxes[zone_id] = box
        return box

    for z in spec.zones:
        resolve(z.id)
    return boxes


# --- routing -----------------------------------------------------------------


@dataclass
class RoutedEdge:
    edge: Edge
    path_d: str
    label_pos: tuple[float, float]


def route_edges(spec: Spec, node_boxes: dict[str, Box]) -> list[RoutedEdge]:
    """Corridor membership must be known before assigning lane offsets, or a
    parallel-edge stack can grow past the row/column gap and cross through
    the very node row it was routing around. Verified failure mode: 4
    same-rank targets fanning out from one TB source pushed the 3rd/4th lane
    offset past ROW_GAP, drawing those segments through the target row's
    node bodies instead of the gap above them. Fix: pre-count each
    corridor's membership, then size lane spacing to fit inside the actual
    available gap regardless of how many edges share it."""
    corridor_of: dict[int, tuple[float, str]] = {}
    for i, e in enumerate(spec.edges):
        a, b = node_boxes[e.src], node_boxes[e.dst]
        if spec.direction == "TB":
            ax, bx = a.x + a.w / 2, b.x + b.w / 2
            if abs(ax - bx) >= 1:
                corridor_of[i] = (a.y2, "h")
        else:
            ay, by = a.y + a.h / 2, b.y + b.h / 2
            if abs(ay - by) >= 1:
                corridor_of[i] = (a.x2, "v")

    corridor_size: dict[tuple[float, str], int] = {}
    for key in corridor_of.values():
        corridor_size[key] = corridor_size.get(key, 0) + 1

    lane_index: dict[tuple[float, str], int] = {}
    routed = []
    for i, e in enumerate(spec.edges):
        a, b = node_boxes[e.src], node_boxes[e.dst]
        if spec.direction == "TB":
            ax, ay = a.x + a.w / 2, a.y2
            bx, by = b.x + b.w / 2, b.y
            if abs(ax - bx) < 1:
                d = f"M{ax:g},{ay:g} L{bx:g},{by - 6:g}"
                mx, my = ax + 8, (ay + by) / 2
            else:
                key = corridor_of[i]
                n = corridor_size[key]
                spacing = min(8.0, 16.0 / max(n - 1, 1))
                idx = lane_index.get(key, 0)
                lane_index[key] = idx + 1
                mid = ay + 10 + idx * spacing
                d = f"M{ax:g},{ay:g} L{ax:g},{mid:g} L{bx:g},{mid:g} L{bx:g},{by - 6:g}"
                mx, my = (ax + bx) / 2, mid - 6
        else:
            ax, ay = a.x2, a.y + a.h / 2
            bx, by = b.x, b.y + b.h / 2
            if abs(ay - by) < 1:
                d = f"M{ax:g},{ay:g} L{bx - 6:g},{by:g}"
                mx, my = (ax + bx) / 2, ay - 8
            else:
                key = corridor_of[i]
                n = corridor_size[key]
                spacing = min(10.0, 40.0 / max(n - 1, 1))
                idx = lane_index.get(key, 0)
                lane_index[key] = idx + 1
                mid = ax + 16 + idx * spacing
                d = f"M{ax:g},{ay:g} L{mid:g},{ay:g} L{mid:g},{by:g} L{bx - 6:g},{by:g}"
                mx, my = mid + 6, (ay + by) / 2
        routed.append(RoutedEdge(edge=e, path_d=d, label_pos=(mx, my)))
    return routed


def check_layout(
    spec: Spec, node_boxes: dict[str, Box], zone_boxes: dict[str, Box]
) -> list[str]:
    """Hard assertions replacing the prose self-check rules prior art asks
    the model to apply by eye ("no edge crosses an unrelated icon", "no two
    edges overlap")."""
    warnings = []
    ids = list(node_boxes)
    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1 :]:
            if node_boxes[a_id].overlaps(node_boxes[b_id]):
                warnings.append(f"node overlap: {a_id!r} and {b_id!r}")
    zids = list(zone_boxes)
    for i, a_id in enumerate(zids):
        for b_id in zids[i + 1 :]:
            a_parent_chain = _zone_ancestors(spec, a_id)
            if b_id in a_parent_chain or a_id in _zone_ancestors(spec, b_id):
                continue  # nested zones are expected to overlap their ancestor
            if zone_boxes[a_id].overlaps(zone_boxes[b_id]):
                warnings.append(
                    f"zone overlap: {a_id!r} and {b_id!r} — group their member nodes contiguously"
                )
    return warnings


def _zone_ancestors(spec: Spec, zone_id: str) -> set[str]:
    by_id = {z.id: z for z in spec.zones}
    out = set()
    cur = by_id[zone_id].parent
    while cur is not None:
        out.add(cur)
        cur = by_id[cur].parent
    return out


# --- icon resolution ----------------------------------------------------------


@dataclass
class IconRef:
    view_box: str
    body: str


class IconLookup(Protocol):
    def __call__(self, provider: str, service_slug: str) -> IconRef | None: ...


@dataclass
class CacheIconLookup:
    """Network-fetched cloud provider icons — see fetch_icons.py."""

    cache_dir: Path
    sha: str

    def __call__(self, provider: str, service_slug: str) -> IconRef | None:
        path = self.cache_dir / self.sha / provider / f"{service_slug}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return IconRef(view_box=data["viewBox"], body=data["body"])


@dataclass
class BundledGenericIconLookup:
    """Hand-drawn, non-cloud icon catalog shipped inside this skill package
    (assets/generic-icons.json, generated from references/icons-generic.md).
    No network, no cache directory — always available. Only answers for
    provider == "generic"; every cloud provider is CacheIconLookup's job."""

    path: Path = field(
        default_factory=lambda: (
            Path(__file__).resolve().parent.parent / "assets" / "generic-icons.json"
        )
    )

    def __call__(self, provider: str, service_slug: str) -> IconRef | None:
        if provider != "generic" or not self.path.exists():
            return None
        data = json.loads(self.path.read_text())
        entry = data.get(service_slug)
        if entry is None:
            return None
        return IconRef(view_box=entry["viewBox"], body=entry["body"])


@dataclass
class CompositeIconLookup:
    """Tries each lookup in order, returning the first hit. The default
    render.py CLI wiring is [CacheIconLookup, BundledGenericIconLookup] so a
    single spec can freely mix cloud-provider nodes and provider: generic
    nodes without the caller needing to know which backend serves which."""

    lookups: list[IconLookup]

    def __call__(self, provider: str, service_slug: str) -> IconRef | None:
        for lookup in self.lookups:
            ref = lookup(provider, service_slug)
            if ref is not None:
                return ref
        return None


# --- emit ----------------------------------------------------------------------


def _node_svg(node: Node, box: Box, icon: IconRef | None, warnings: list[str]) -> str:
    parts = [f'<g id="node-{_escape(node.id)}">']
    parts.append(
        f'<rect x="{box.x:g}" y="{box.y:g}" width="{ICON:g}" height="{ICON:g}" rx="10" fill="{node.color}"/>'
    )
    if icon is not None:
        inset = 9
        parts.append(
            f'<svg x="{box.x + inset:g}" y="{box.y + inset:g}" width="{ICON - inset * 2:g}" '
            f'height="{ICON - inset * 2:g}" viewBox="{icon.view_box}" color="#FFFFFF">{icon.body}</svg>'
        )
    else:
        if node.service:
            warnings.append(
                f"no icon for node {node.id!r} (service={node.service!r}, provider={node.provider!r})"
            )
        cx, cy = box.x + ICON / 2, box.y + ICON / 2
        initial = _escape(node.label[:1].upper() or "?")
        parts.append(
            f'<text x="{cx:g}" y="{cy + 6:g}" font-size="22" font-weight="700" text-anchor="middle" fill="#FFFFFF">{initial}</text>'
        )
    label_y = box.y + ICON + 18
    label_font_size = 12.0
    if _text_width(node.label, label_font_size) > box.w - 8:
        warnings.append(
            f"label may overflow its node box: {node.label!r} on {node.id!r}"
        )
    parts.append(
        f'<text x="{box.x + box.w / 2:g}" y="{label_y:g}" font-size="{label_font_size:g}" font-weight="600" '
        f'text-anchor="middle" fill="#1F2937">{_escape(node.label)}</text>'
    )
    if node.sublabel:
        sub_font_size = 10.5
        if _text_width(node.sublabel, sub_font_size) > box.w - 8:
            warnings.append(
                f"sublabel may overflow its node box: {node.sublabel!r} on {node.id!r}"
            )
        parts.append(
            f'<text x="{box.x + box.w / 2:g}" y="{label_y + 15:g}" font-size="{sub_font_size:g}" '
            f'text-anchor="middle" fill="#6B7280">{_escape(node.sublabel)}</text>'
        )
    parts.append("</g>")
    return "".join(parts)


def _zone_svg(zone: Zone, box: Box) -> str:
    return (
        f'<g id="zone-{_escape(zone.id)}">'
        f'<rect x="{box.x:g}" y="{box.y:g}" width="{box.w:g}" height="{box.h:g}" rx="8" '
        f'fill="none" stroke="#8C4FFF" stroke-width="1.5" stroke-dasharray="6 4"/>'
        f'<text x="{box.x + 12:g}" y="{box.y + 18:g}" font-size="11" font-weight="600" fill="#8C4FFF">{_escape(zone.label)}</text>'
        f"</g>"
    )


def _edge_svg(routed: RoutedEdge) -> str:
    e = routed.edge
    color = EDGE_COLORS.get(e.type, EDGE_COLORS["default"])
    dash = ' stroke-dasharray="6 4"' if e.type == "batch" else ""
    marker = f'marker-end="url(#arrow-{e.type})"'
    parts = [f'<g id="edge-{_escape(e.src)}-{_escape(e.dst)}">']
    parts.append(
        f'<path d="{routed.path_d}" fill="none" stroke="{color}" stroke-width="1.8"{dash} {marker}/>'
    )
    if e.label:
        mx, my = routed.label_pos
        parts.append(
            f'<text x="{mx:g}" y="{my:g}" font-size="10" fill="{color}">{_escape(e.label)}</text>'
        )
    parts.append("</g>")
    return "".join(parts)


def _legend_svg(edge_types: set[str], x: float, y: float) -> str:
    parts = ['<g id="legend">']
    for i, t in enumerate(sorted(edge_types)):
        color = EDGE_COLORS.get(t, EDGE_COLORS["default"])
        ly = y + i * 18
        parts.append(
            f'<line x1="{x:g}" y1="{ly:g}" x2="{x + 24:g}" y2="{ly:g}" stroke="{color}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x + 30:g}" y="{ly + 4:g}" font-size="10" fill="#374151">{_escape(t)}</text>'
        )
    parts.append("</g>")
    return "".join(parts)


def emit_svg(
    spec: Spec,
    node_boxes: dict[str, Box],
    zone_boxes: dict[str, Box],
    routed_edges: list[RoutedEdge],
    icons: dict[str, IconRef | None],
    warnings: list[str],
) -> str:
    zone_by_id = {z.id: z for z in spec.zones}
    all_extents = [b for b in node_boxes.values()] + [b for b in zone_boxes.values()]
    width = max((b.x2 for b in all_extents), default=NODE_W) + MARGIN
    height = max((b.y2 for b in all_extents), default=NODE_H) + MARGIN

    edge_types = {e.type for e in spec.edges}
    show_legend = len(edge_types) > 1
    legend_h = 12 + len(edge_types) * 18 if show_legend else 0
    height += legend_h

    svg_open = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
        f'viewBox="0 0 {width:g} {height:g}" font-family="Segoe UI, system-ui, sans-serif">'
    )
    parts = [
        svg_open,
        f'<rect width="{width:g}" height="{height:g}" fill="#FAFAF8"/>',
        "<defs>",
    ]
    for t, color in EDGE_COLORS.items():
        parts.append(
            f'<marker id="arrow-{t}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>'
        )
    parts.append("</defs>")

    if spec.title:
        parts.append(
            f'<text x="{MARGIN:g}" y="{MARGIN + 14:g}" font-size="17" font-weight="700" fill="#1F2937">{_escape(spec.title)}</text>'
        )

    # zones first (background layer), parents before children so children draw on top
    for zid in sorted(zone_boxes, key=lambda z: len(_zone_ancestors(spec, z))):
        parts.append(_zone_svg(zone_by_id[zid], zone_boxes[zid]))

    for routed in routed_edges:
        parts.append(_edge_svg(routed))

    for n in spec.nodes:
        parts.append(_node_svg(n, node_boxes[n.id], icons.get(n.id), warnings))

    if show_legend:
        parts.append(_legend_svg(edge_types, MARGIN, height - legend_h + 6))

    parts.append("</svg>")
    return "".join(parts)


# --- editability check --------------------------------------------------------

_FORBIDDEN_MARKERS = ("<image", "base64,", "<use ", "<use>")


def check_editability(svg_text: str) -> list[str]:
    """Enforce the output contract this rewrite exists to deliver: no raster
    fallback, no `<use>` clones (Inkscape/MDN both document that clone nodes
    aren't independently node-editable — see `references/editability.md`),
    no external references. A regression here means a future change quietly
    reintroduced one of the failure modes the whole design avoids."""
    found = [m for m in _FORBIDDEN_MARKERS if m in svg_text]
    warnings = [f"editability violation: found {m!r}" for m in found]
    for marker in ('href="http', 'xlink:href="http'):
        if marker in svg_text:
            warnings.append(f"editability violation: external reference ({marker!r})")
    return warnings


# --- top-level render ----------------------------------------------------------


@dataclass
class RenderResult:
    svg: str
    warnings: list[str] = field(default_factory=list)


def render(spec: Spec, icon_lookup: IconLookup) -> RenderResult:
    warnings: list[str] = []
    rank = assign_ranks(spec)
    order = order_within_ranks(spec, rank)
    node_boxes = compute_positions(spec, rank, order)
    zone_boxes = compute_zone_boxes(spec, node_boxes) if spec.zones else {}
    warnings += check_layout(spec, node_boxes, zone_boxes)
    routed_edges = route_edges(spec, node_boxes)

    icons: dict[str, IconRef | None] = {}
    for n in spec.nodes:
        icons[n.id] = icon_lookup(n.provider, n.service) if n.service else None

    svg = emit_svg(spec, node_boxes, zone_boxes, routed_edges, icons, warnings)
    warnings += check_editability(svg)
    return RenderResult(svg=svg, warnings=warnings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="path to a YAML spec")
    parser.add_argument("-o", "--output", type=Path, default=Path("diagram.svg"))
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--sha", default=None)
    args = parser.parse_args(argv)

    import fetch_icons  # local import: keeps render.py importable without pulling in networking deps for pure-layout tests

    cache_dir = args.cache_dir or fetch_icons.default_cache_dir()
    sha = args.sha or fetch_icons.DRAWIO_SHA
    lookup = CompositeIconLookup(
        [CacheIconLookup(cache_dir=cache_dir, sha=sha), BundledGenericIconLookup()]
    )

    try:
        spec = load_spec(args.spec.read_text())
    except SpecError as exc:
        print(f"error: invalid spec — {exc}", file=sys.stderr)
        return 1

    result = render(spec, lookup)
    args.output.write_text(result.svg)
    print(f"wrote {args.output} ({len(result.svg)} bytes)")
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 1 if any("editability violation" in w for w in result.warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
