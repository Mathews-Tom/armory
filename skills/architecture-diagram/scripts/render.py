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
# Shared-side ports must stay away from the icon corners and remain legible as
# fan-out grows. A 64px icon leaves a 32px usable span after 16px gutters:
# five ports therefore land 8px apart without one endpoint covering another.
PORT_GUTTER = 16.0
PORT_MAX_SPACING = 14.0
# Rejoin a lone source/destination pair when their spread ports are nearly
# aligned. This keeps short hops straight without collapsing a shared side.
FACING_PORT_ALIGNMENT_DELTA = 16.0
# Orthogonal detours leave a real 24px endpoint stub. Centered channel offsets
# span at most +/-16px, so even their nearest first segment is at least 8px.
ROUTE_ENDPOINT_STUB = 24.0
ROUTE_CHANNEL_HALF_SPREAD = 16.0
ARROW_HEAD_LENGTH = 6.0
# Route rhythm failures are composition findings: every segment needs 8px and
# a segment between two turns needs 16px to remain visually distinguishable.
MIN_ROUTE_SEGMENT = 8.0
MIN_INTERIOR_ROUTE_SEGMENT = 16.0


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


# --- diagnostics -------------------------------------------------------------

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
_SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING)

QUALITY_STANDARD = "standard"
QUALITY_SHOWCASE = "showcase"
QUALITY_PROFILES = (QUALITY_STANDARD, QUALITY_SHOWCASE)

# Codes in this namespace describe how the drawing reads rather than whether
# the spec is answerable: two routes crossing, a label sitting on a route.
# They are warnings under the standard profile and errors under showcase, so
# stricter geometry rules can ship without breaking specs that already render.
PROFILE_SENSITIVE_NAMESPACE = "composition/"

DIAGNOSTIC_SCHEMA_VERSION = 1


@dataclass
class Diagnostic:
    """One machine-readable finding.

    The predecessor of this type was `list[str]` of English prose printed to
    stderr, which forced the calling agent to regex sentences and left it to
    invent its own repair — usually by editing the SVG, which is exactly the
    move that destroys the reproducibility this renderer exists to provide.
    `code` is the stable identity, `subject` says what the finding is about,
    `evidence` carries the numbers needed to locate it, and
    `supported_fixes` bounds the repair to changes an author can make in the
    spec.
    """

    code: str
    severity: str
    message: str
    subject: dict[str, object] = field(default_factory=dict)
    evidence: dict[str, object] = field(default_factory=dict)
    supported_fixes: tuple[str, ...] = ()
    # Codes this finding makes redundant. A derived diagnostic reported
    # alongside its cause sends the agent chasing symptoms.
    suppresses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITIES:
            raise ValueError(
                f"diagnostic {self.code!r} has unknown severity {self.severity!r}; "
                f"expected one of {_SEVERITIES}"
            )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "subject": dict(self.subject),
            "evidence": dict(self.evidence),
            "supported_fixes": list(self.supported_fixes),
        }
        if self.suppresses:
            payload["suppresses"] = list(self.suppresses)
        return payload


def apply_quality_profile(
    diagnostics: list[Diagnostic], quality: str
) -> list[Diagnostic]:
    """Raise profile-sensitive findings to errors under the showcase profile."""
    if quality not in QUALITY_PROFILES:
        raise ValueError(
            f"unknown quality profile {quality!r}; expected one of {QUALITY_PROFILES}"
        )
    if quality != QUALITY_SHOWCASE:
        return list(diagnostics)
    out = []
    for d in diagnostics:
        if (
            d.code.startswith(PROFILE_SENSITIVE_NAMESPACE)
            and d.severity != SEVERITY_ERROR
        ):
            out.append(
                Diagnostic(
                    code=d.code,
                    severity=SEVERITY_ERROR,
                    message=d.message,
                    subject=d.subject,
                    evidence=d.evidence,
                    supported_fixes=d.supported_fixes,
                    suppresses=d.suppresses,
                )
            )
        else:
            out.append(d)
    return out


def suppress_derived(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Drop findings a reported cause makes redundant.

    Suppression is one level deep and keyed on `code`: a record is dropped
    when any record in the input names its code, and a dropped record still
    suppresses. Resolving chains instead has no well-founded answer — if A
    suppresses B and C suppresses A, then removing B leaves it hidden with
    no visible cause, while keeping B oscillates on the next pass, and a
    mutual pair has no defensible winner at all. Every emitter must
    therefore declare `suppresses` only for a code it directly explains,
    never for one that suppresses something else in turn.
    """
    suppressed = {code for d in diagnostics for code in d.suppresses}
    return [d for d in diagnostics if d.code not in suppressed]


def count_by_severity(diagnostics: list[Diagnostic]) -> dict[str, int]:
    return {
        "errors": sum(1 for d in diagnostics if d.severity == SEVERITY_ERROR),
        "warnings": sum(1 for d in diagnostics if d.severity == SEVERITY_WARNING),
    }


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
    """A spec the renderer cannot answer.

    Carries the `Diagnostic` so callers get the same coded record they get
    for every other finding; the exception message stays human-readable for
    tracebacks.
    """

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _spec_error(
    code: str,
    message: str,
    subject: dict[str, object] | None = None,
    evidence: dict[str, object] | None = None,
    supported_fixes: tuple[str, ...] = (),
) -> SpecError:
    return SpecError(
        Diagnostic(
            code=code,
            severity=SEVERITY_ERROR,
            message=message,
            subject=subject or {},
            evidence=evidence or {},
            supported_fixes=supported_fixes,
        )
    )


def load_spec(text: str) -> Spec:
    data = yaml.safe_load(text) or {}
    if "nodes" not in data or not data["nodes"]:
        raise _spec_error(
            "spec/no-nodes",
            "spec has no nodes",
            supported_fixes=("add at least one entry under `nodes`",),
        )

    provider = data.get("provider", "generic")
    node_ids = set()
    nodes = []
    for raw in data["nodes"]:
        if "id" not in raw:
            raise _spec_error(
                "spec/node-missing-id",
                f"node missing id: {raw}",
                evidence={"node": raw},
                supported_fixes=("give the node a unique `id`",),
            )
        if raw["id"] in node_ids:
            raise _spec_error(
                "spec/duplicate-node-id",
                f"duplicate node id: {raw['id']}",
                subject={"node": raw["id"]},
                supported_fixes=(
                    "rename one of the nodes so every `id` is unique",
                    "delete the duplicate node entry",
                ),
            )
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
            raise _spec_error(
                "spec/zone-missing-id",
                f"zone missing id: {raw}",
                evidence={"zone": raw},
                supported_fixes=("give the zone a unique `id`",),
            )
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
            raise _spec_error(
                "spec/unknown-zone",
                f"node {n.id!r} references unknown zone {n.zone!r}",
                subject={"node": n.id},
                evidence={"zone": n.zone, "known_zones": sorted(zone_ids)},
                supported_fixes=(
                    "declare the zone under `zones`",
                    "point the node's `zone` at an existing zone id",
                    "drop the node's `zone` field",
                ),
            )
    for z in zones:
        if z.parent is not None and z.parent not in zone_ids:
            raise _spec_error(
                "spec/unknown-zone-parent",
                f"zone {z.id!r} references unknown parent {z.parent!r}",
                subject={"zone": z.id},
                evidence={"parent": z.parent, "known_zones": sorted(zone_ids)},
                supported_fixes=(
                    "declare the parent zone under `zones`",
                    "point `parent` at an existing zone id",
                    "drop `parent` to make this a top-level zone",
                ),
            )
        if z.parent == z.id:
            raise _spec_error(
                "spec/zone-self-parent",
                f"zone {z.id!r} cannot be its own parent",
                subject={"zone": z.id},
                supported_fixes=(
                    "drop `parent` to make this a top-level zone",
                    "point `parent` at the enclosing zone",
                ),
            )

    edges = []
    for raw in data.get("edges", []) or []:
        if raw.get("from") not in node_ids or raw.get("to") not in node_ids:
            raise _spec_error(
                "spec/unknown-edge-node",
                f"edge references unknown node: {raw}",
                evidence={"edge": raw, "known_nodes": sorted(node_ids)},
                supported_fixes=(
                    "point `from` and `to` at existing node ids",
                    "declare the missing node under `nodes`",
                ),
            )
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


def icon_box(box: Box) -> Box:
    """The node's *visible icon square* — 64x64, horizontally centered
    within the wider label-reserving node box, flush against its top edge
    (icon on top, label lines below).

    `Box` (NODE_W x NODE_H) exists to reserve room for label text that's
    almost always wider than the 64px icon; it is correct for layout
    spacing (compute_zone_boxes, node-overlap checks) but was previously
    also used directly for label centering and edge-routing anchor points.
    Since the icon isn't centered within that wider box by default, those
    anchors landed off the icon's true center — edges rode along the
    icon's bottom edge in LR diagrams and its right side in TB diagrams
    instead of passing through its middle, and labels centered ~28px to
    the right of their own icon. Every caller that needs "where does this
    node visually connect" — routing, label centering, the no-icon
    placeholder glyph — must go through this helper instead of `Box`
    directly."""
    return Box(box.x + (NODE_W - ICON) / 2, box.y, ICON, ICON)


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
            raise _spec_error(
                "spec/zone-cycle",
                f"zone cycle detected at {zone_id!r}",
                subject={"zone": zone_id},
                evidence={"chain": sorted(stack)},
                supported_fixes=(
                    "break the cycle so every zone's `parent` chain ends at a top-level zone",
                ),
            )
        parts = [node_boxes[nid] for nid in members[zone_id]]
        parts += [resolve(cid, stack | {zone_id}) for cid in children[zone_id]]
        if not parts:
            raise _spec_error(
                "spec/empty-zone",
                f"zone {zone_id!r} has no member nodes or child zones",
                subject={"zone": zone_id},
                supported_fixes=(
                    "assign at least one node to the zone via that node's `zone` field",
                    "nest a child zone under it",
                    "delete the zone",
                ),
            )
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
    points: tuple[tuple[float, float], ...]
    label_pos: tuple[float, float]

    @property
    def path_d(self) -> str:
        start, *rest = self.points
        return " ".join(
            [f"M{start[0]:g},{start[1]:g}"] + [f"L{x:g},{y:g}" for x, y in rest]
        )


def _centered_offsets(count: int, maximum: float) -> list[float]:
    if count == 1:
        return [0.0]
    spacing = min(maximum, 2 * maximum / (count - 1))
    return [spacing * (index - (count - 1) / 2) for index in range(count)]


def _dedupe_route_points(
    points: list[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """Remove zero-length or straight-through turns before measuring rhythm."""
    deduped: list[tuple[float, float]] = []
    for point in points:
        if not deduped or point != deduped[-1]:
            deduped.append(point)

    changed = True
    while changed:
        changed = False
        kept = [deduped[0]]
        for index, point in enumerate(deduped[1:-1], start=1):
            previous = kept[-1]
            following = deduped[index + 1]
            if (previous[0] == point[0] == following[0]) or (
                previous[1] == point[1] == following[1]
            ):
                changed = True
                continue
            kept.append(point)
        kept.append(deduped[-1])
        deduped = kept
    return tuple(deduped)


def _edge_sort_key(
    spec: Spec,
    node_boxes: dict[str, Box],
    edge_index: int,
    source_endpoint: bool,
) -> tuple[float, str, str, str, str]:
    edge = spec.edges[edge_index]
    counterpart_id = edge.dst if source_endpoint else edge.src
    counterpart = icon_box(node_boxes[counterpart_id])
    counterpart_center = (
        counterpart.x + counterpart.w / 2
        if spec.direction == "TB"
        else counterpart.y + counterpart.h / 2
    )
    return (counterpart_center, counterpart_id, edge.src, edge.dst, edge.label)


def _port_axes(
    spec: Spec, node_boxes: dict[str, Box]
) -> tuple[
    dict[tuple[int, bool], float], dict[tuple[str, str], list[tuple[int, bool]]]
]:
    """Allocate distinct attachment points on each used icon side."""
    groups: dict[tuple[str, str], list[tuple[int, bool]]] = {}
    source_side, destination_side = (
        ("bottom", "top") if spec.direction == "TB" else ("right", "left")
    )
    for index, edge in enumerate(spec.edges):
        groups.setdefault((edge.src, source_side), []).append((index, True))
        groups.setdefault((edge.dst, destination_side), []).append((index, False))

    axes: dict[tuple[int, bool], float] = {}
    for (node_id, side), endpoints in groups.items():
        icon = icon_box(node_boxes[node_id])
        extent = icon.w if side in ("top", "bottom") else icon.h
        usable = max(0.0, extent - 2 * PORT_GUTTER)
        ordered = sorted(
            endpoints,
            key=lambda endpoint: _edge_sort_key(
                spec, node_boxes, endpoint[0], endpoint[1]
            ),
        )
        if len(ordered) == 1:
            offsets = [0.0]
        else:
            spacing = min(PORT_MAX_SPACING, usable / (len(ordered) - 1))
            offsets = [
                spacing * (index - (len(ordered) - 1) / 2)
                for index in range(len(ordered))
            ]
        center = (
            icon.x + icon.w / 2 if side in ("top", "bottom") else icon.y + icon.h / 2
        )
        for endpoint, offset in zip(ordered, offsets, strict=True):
            axes[endpoint] = center + offset
    return axes, groups


def _route_points(
    source: tuple[float, float],
    destination: tuple[float, float],
    direction: str,
    channel_offset: float,
) -> tuple[tuple[float, float], ...]:
    sx, sy = source
    dx, dy = destination
    if direction == "TB":
        if sx == dx:
            return ((sx, sy), (dx, dy - ARROW_HEAD_LENGTH))
        channel = sy + ROUTE_ENDPOINT_STUB + channel_offset
        if abs(sx - dx) < MIN_INTERIOR_ROUTE_SEGMENT:
            bridge_x = (
                sx - MIN_INTERIOR_ROUTE_SEGMENT
                if dx >= sx
                else sx + MIN_INTERIOR_ROUTE_SEGMENT
            )
            return _dedupe_route_points(
                [
                    (sx, sy),
                    (sx, channel),
                    (bridge_x, channel),
                    (bridge_x, channel + ROUTE_CHANNEL_HALF_SPREAD),
                    (dx, channel + ROUTE_CHANNEL_HALF_SPREAD),
                    (dx, dy - ARROW_HEAD_LENGTH),
                ]
            )
        return _dedupe_route_points(
            [(sx, sy), (sx, channel), (dx, channel), (dx, dy - ARROW_HEAD_LENGTH)]
        )
    if sy == dy:
        return ((sx, sy), (dx - ARROW_HEAD_LENGTH, dy))
    channel = sx + ROUTE_ENDPOINT_STUB + channel_offset
    if abs(sy - dy) < MIN_INTERIOR_ROUTE_SEGMENT:
        bridge_y = (
            sy - MIN_INTERIOR_ROUTE_SEGMENT
            if dy >= sy
            else sy + MIN_INTERIOR_ROUTE_SEGMENT
        )
        return _dedupe_route_points(
            [
                (sx, sy),
                (channel, sy),
                (channel, bridge_y),
                (channel + ROUTE_CHANNEL_HALF_SPREAD, bridge_y),
                (channel + ROUTE_CHANNEL_HALF_SPREAD, dy),
                (dx - ARROW_HEAD_LENGTH, dy),
            ]
        )
    return _dedupe_route_points(
        [(sx, sy), (channel, sy), (channel, dy), (dx - ARROW_HEAD_LENGTH, dy)]
    )


def route_edges(spec: Spec, node_boxes: dict[str, Box]) -> list[RoutedEdge]:
    """Spread shared ports and use bounded channels in the layout gaps."""
    axes, groups = _port_axes(spec, node_boxes)
    source_side, destination_side = (
        ("bottom", "top") if spec.direction == "TB" else ("right", "left")
    )
    source_axes = {index: axes[index, True] for index in range(len(spec.edges))}
    destination_axes = {index: axes[index, False] for index in range(len(spec.edges))}

    for index, edge in enumerate(spec.edges):
        source_shared = len(groups[edge.src, source_side]) > 1
        destination_shared = len(groups[edge.dst, destination_side]) > 1
        if (
            not source_shared
            and not destination_shared
            and abs(source_axes[index] - destination_axes[index])
            <= FACING_PORT_ALIGNMENT_DELTA
        ):
            merged_axis = (source_axes[index] + destination_axes[index]) / 2
            source_axes[index] = merged_axis
            destination_axes[index] = merged_axis

    corridors: dict[tuple[float, str], list[int]] = {}
    for index, edge in enumerate(spec.edges):
        source = icon_box(node_boxes[edge.src])
        source_axis, destination_axis = source_axes[index], destination_axes[index]
        if abs(source_axis - destination_axis) < 1:
            continue
        key = (source.y2, "h") if spec.direction == "TB" else (source.x2, "v")
        corridors.setdefault(key, []).append(index)

    channel_offsets: dict[int, float] = {}
    for indices in corridors.values():
        ordered = sorted(
            indices, key=lambda index: _edge_sort_key(spec, node_boxes, index, True)
        )
        for index, offset in zip(
            ordered,
            _centered_offsets(len(ordered), ROUTE_CHANNEL_HALF_SPREAD),
            strict=True,
        ):
            channel_offsets[index] = offset

    routed: list[RoutedEdge] = []
    for index, edge in enumerate(spec.edges):
        source = icon_box(node_boxes[edge.src])
        destination = icon_box(node_boxes[edge.dst])
        if spec.direction == "TB":
            start = (source_axes[index], source.y2)
            end = (destination_axes[index], destination.y)
        else:
            start = (source.x2, source_axes[index])
            end = (destination.x, destination_axes[index])
        points = _route_points(
            start, end, spec.direction, channel_offsets.get(index, 0.0)
        )
        if spec.direction == "TB":
            mx, my = (
                (points[0][0] + points[-1][0]) / 2,
                points[min(1, len(points) - 1)][1] - 6,
            )
        else:
            mx, my = (
                points[min(1, len(points) - 1)][0] + 6,
                (points[0][1] + points[-1][1]) / 2,
            )
        routed.append(RoutedEdge(edge=edge, points=points, label_pos=(mx, my)))
    return routed


def _segment_length(start: tuple[float, float], end: tuple[float, float]) -> float:
    return abs(end[0] - start[0]) + abs(end[1] - start[1])


def check_route_rhythm(routed_edges: list[RoutedEdge]) -> list[Diagnostic]:
    """Report paths whose short orthogonal runs cannot read as separate lines."""
    out: list[Diagnostic] = []
    for routed in routed_edges:
        edge = routed.edge
        segments = list(zip(routed.points, routed.points[1:]))
        for index, (start, end) in enumerate(segments):
            length = _segment_length(start, end)
            evidence = {
                "segment_index": index,
                "start": list(start),
                "end": list(end),
                "length": length,
            }
            subject = {"from": edge.src, "to": edge.dst, "label": edge.label}
            if length < MIN_ROUTE_SEGMENT:
                out.append(
                    Diagnostic(
                        code="composition/micro-segment",
                        severity=SEVERITY_WARNING,
                        message=(
                            f"edge {edge.src!r}->{edge.dst!r} segment {index} is "
                            f"{length:g}px; routes need at least {MIN_ROUTE_SEGMENT:g}px"
                        ),
                        subject=subject,
                        evidence={**evidence, "minimum": MIN_ROUTE_SEGMENT},
                        supported_fixes=(
                            "remove the redundant connection",
                            "split the nodes into separate ranks with an intermediate node",
                        ),
                    )
                )
            if 0 < index < len(segments) - 1 and length < MIN_INTERIOR_ROUTE_SEGMENT:
                out.append(
                    Diagnostic(
                        code="composition/short-interior-segment",
                        severity=SEVERITY_WARNING,
                        message=(
                            f"edge {edge.src!r}->{edge.dst!r} interior segment {index} "
                            f"is {length:g}px; turns need at least "
                            f"{MIN_INTERIOR_ROUTE_SEGMENT:g}px"
                        ),
                        subject=subject,
                        evidence={
                            **evidence,
                            "minimum": MIN_INTERIOR_ROUTE_SEGMENT,
                        },
                        supported_fixes=(
                            "remove the redundant connection",
                            "split the nodes into separate ranks with an intermediate node",
                        ),
                    )
                )
    return out


def check_layout(
    spec: Spec, node_boxes: dict[str, Box], zone_boxes: dict[str, Box]
) -> list[Diagnostic]:
    """Hard assertions replacing the prose self-check rules prior art in this
    space asks the model to apply by eye ("no edge crosses an unrelated
    icon", "no two edges overlap")."""
    out: list[Diagnostic] = []
    ids = list(node_boxes)
    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1 :]:
            if node_boxes[a_id].overlaps(node_boxes[b_id]):
                out.append(
                    Diagnostic(
                        code="layout/node-overlap",
                        severity=SEVERITY_ERROR,
                        message=f"node overlap: {a_id!r} and {b_id!r}",
                        subject={"nodes": [a_id, b_id]},
                        evidence={
                            a_id: _box_evidence(node_boxes[a_id]),
                            b_id: _box_evidence(node_boxes[b_id]),
                        },
                        supported_fixes=(
                            "split the two nodes across different ranks by adding an edge between them",
                            "remove one of the duplicated nodes",
                        ),
                    )
                )
    zids = list(zone_boxes)
    for i, a_id in enumerate(zids):
        for b_id in zids[i + 1 :]:
            a_parent_chain = _zone_ancestors(spec, a_id)
            if b_id in a_parent_chain or a_id in _zone_ancestors(spec, b_id):
                continue  # nested zones are expected to overlap their ancestor
            if zone_boxes[a_id].overlaps(zone_boxes[b_id]):
                out.append(
                    Diagnostic(
                        code="layout/zone-overlap",
                        severity=SEVERITY_ERROR,
                        message=f"zone overlap: {a_id!r} and {b_id!r}",
                        subject={"zones": [a_id, b_id]},
                        evidence={
                            a_id: _box_evidence(zone_boxes[a_id]),
                            b_id: _box_evidence(zone_boxes[b_id]),
                        },
                        supported_fixes=(
                            "list each zone's member nodes contiguously in `nodes`",
                            "correct the `zone` field on the interleaved nodes",
                            "nest one zone inside the other via `parent` if containment was intended",
                        ),
                    )
                )
    return out


def _box_evidence(box: Box) -> dict[str, float]:
    return {"x": box.x, "y": box.y, "width": box.w, "height": box.h}


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


def _label_overflow(
    node_id: str, field_name: str, text: str, font_size: float, available: float
) -> Diagnostic:
    return Diagnostic(
        code="layout/label-overflow",
        severity=SEVERITY_WARNING,
        message=f"{field_name} may overflow its node box: {text!r} on {node_id!r}",
        subject={"node": node_id, "field": field_name},
        evidence={
            "text": text,
            "estimated_width": round(_text_width(text, font_size), 2),
            "available_width": available,
        },
        supported_fixes=(
            "shorten the text",
            "move the detail into `sublabel`",
        ),
    )


def _icon_not_found(node: Node) -> Diagnostic:
    fixes = ["use the exact slug from that provider's reference service map"]
    # The generic set is bundled in the package, so telling the author to
    # fetch a cache for it would send them after a cache that never exists.
    if node.provider != "generic":
        fixes.insert(
            0, f"warm the icon cache: fetch_icons.py --provider {node.provider}"
        )
    fixes.append(
        "drop the node's `service` field to render the labeled placeholder deliberately"
    )
    return Diagnostic(
        code="icon/not-found",
        severity=SEVERITY_ERROR,
        message=(
            f"no icon for node {node.id!r} "
            f"(service={node.service!r}, provider={node.provider!r})"
        ),
        subject={"node": node.id},
        evidence={"service": node.service, "provider": node.provider},
        supported_fixes=tuple(fixes),
    )


def _node_svg(
    node: Node, box: Box, icon: IconRef | None, diagnostics: list[Diagnostic]
) -> str:
    parts = [f'<g id="node-{_escape(node.id)}">']
    icon_pos = icon_box(box)
    parts.append(
        f'<rect x="{icon_pos.x:g}" y="{icon_pos.y:g}" width="{ICON:g}" height="{ICON:g}" rx="10" fill="{node.color}"/>'
    )
    if icon is not None:
        inset = 9
        parts.append(
            f'<svg x="{icon_pos.x + inset:g}" y="{icon_pos.y + inset:g}" width="{ICON - inset * 2:g}" '
            f'height="{ICON - inset * 2:g}" viewBox="{icon.view_box}" color="#FFFFFF">{icon.body}</svg>'
        )
    else:
        if node.service:
            diagnostics.append(_icon_not_found(node))
        cx, cy = icon_pos.x + ICON / 2, icon_pos.y + ICON / 2
        initial = _escape(node.label[:1].upper() or "?")
        parts.append(
            f'<text x="{cx:g}" y="{cy + 6:g}" font-size="22" font-weight="700" text-anchor="middle" fill="#FFFFFF">{initial}</text>'
        )
    label_y = box.y + ICON + 18
    label_font_size = 12.0
    if _text_width(node.label, label_font_size) > box.w - 8:
        diagnostics.append(
            _label_overflow(node.id, "label", node.label, label_font_size, box.w - 8)
        )
    parts.append(
        f'<text x="{box.x + box.w / 2:g}" y="{label_y:g}" font-size="{label_font_size:g}" font-weight="600" '
        f'text-anchor="middle" fill="#1F2937">{_escape(node.label)}</text>'
    )
    if node.sublabel:
        sub_font_size = 10.5
        if _text_width(node.sublabel, sub_font_size) > box.w - 8:
            diagnostics.append(
                _label_overflow(
                    node.id, "sublabel", node.sublabel, sub_font_size, box.w - 8
                )
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
    diagnostics: list[Diagnostic],
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
        parts.append(_node_svg(n, node_boxes[n.id], icons.get(n.id), diagnostics))

    if show_legend:
        parts.append(_legend_svg(edge_types, MARGIN, height - legend_h + 6))

    parts.append("</svg>")
    return "".join(parts)


# --- editability check --------------------------------------------------------

_FORBIDDEN_MARKERS = ("<image", "base64,", "<use ", "<use>")


def check_editability(svg_text: str) -> list[Diagnostic]:
    """Enforce the output contract this rewrite exists to deliver: no raster
    fallback, no `<use>` clones (Inkscape/MDN both document that clone nodes
    aren't independently node-editable — see `references/editability.md`),
    no external references. A regression here means a future change quietly
    reintroduced one of the failure modes the whole design avoids."""
    out: list[Diagnostic] = []
    for marker in _FORBIDDEN_MARKERS:
        if marker in svg_text:
            out.append(
                Diagnostic(
                    code="editability/forbidden-markup",
                    severity=SEVERITY_ERROR,
                    message=f"editability violation: found {marker!r}",
                    evidence={"marker": marker},
                    supported_fixes=(
                        "file this as a renderer bug: the spec cannot introduce this markup",
                    ),
                )
            )
    for marker in ('href="http', 'xlink:href="http'):
        if marker in svg_text:
            out.append(
                Diagnostic(
                    code="editability/external-reference",
                    severity=SEVERITY_ERROR,
                    message=f"editability violation: external reference ({marker!r})",
                    evidence={"marker": marker},
                    supported_fixes=(
                        "file this as a renderer bug: the output must stay self-contained",
                    ),
                )
            )
    return out


# --- top-level render ----------------------------------------------------------


@dataclass
class RenderResult:
    svg: str
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == SEVERITY_ERROR]

    @property
    def ok(self) -> bool:
        return not self.errors


def render(
    spec: Spec, icon_lookup: IconLookup, quality: str = QUALITY_STANDARD
) -> RenderResult:
    diagnostics: list[Diagnostic] = []
    rank = assign_ranks(spec)
    order = order_within_ranks(spec, rank)
    node_boxes = compute_positions(spec, rank, order)
    zone_boxes = compute_zone_boxes(spec, node_boxes) if spec.zones else {}
    diagnostics += check_layout(spec, node_boxes, zone_boxes)
    routed_edges = route_edges(spec, node_boxes)
    diagnostics += check_route_rhythm(routed_edges)

    icons: dict[str, IconRef | None] = {}
    for n in spec.nodes:
        icons[n.id] = icon_lookup(n.provider, n.service) if n.service else None

    svg = emit_svg(spec, node_boxes, zone_boxes, routed_edges, icons, diagnostics)
    diagnostics += check_editability(svg)
    diagnostics = apply_quality_profile(suppress_derived(diagnostics), quality)
    return RenderResult(svg=svg, diagnostics=diagnostics)


EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2


def _envelope(
    ok: bool,
    quality: str,
    diagnostics: list[Diagnostic],
    output: Path | None = None,
    artifact_bytes: int | None = None,
) -> dict[str, object]:
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "ok": ok,
        "quality": quality,
        "output": str(output) if output is not None else None,
        "written": artifact_bytes is not None,
        "artifact_bytes": artifact_bytes,
        "counts": count_by_severity(diagnostics),
        "diagnostics": [d.to_dict() for d in diagnostics],
    }


def _report(
    envelope: dict[str, object], as_json: bool, diagnostics: list[Diagnostic]
) -> None:
    """Under --json, stdout carries the envelope and nothing else, so a
    caller can parse it without stripping human lines."""
    if as_json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return
    if envelope["written"]:
        print(f"wrote {envelope['output']} ({envelope['artifact_bytes']} bytes)")
    for d in diagnostics:
        print(f"{d.severity}: [{d.code}] {d.message}", file=sys.stderr)
        for fix in d.supported_fixes:
            print(f"  fix: {fix}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="path to a YAML spec")
    parser.add_argument("-o", "--output", type=Path, default=Path("diagram.svg"))
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--sha", default=None)
    parser.add_argument(
        "--quality",
        choices=QUALITY_PROFILES,
        default=QUALITY_STANDARD,
        help="showcase raises composition findings from warnings to errors",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="print the diagnostic envelope to stdout and nothing else",
    )
    args = parser.parse_args(argv)

    try:
        spec_text = args.spec.read_text()
    except OSError as exc:
        unreadable = Diagnostic(
            code="usage/spec-unreadable",
            severity=SEVERITY_ERROR,
            message=f"cannot read spec {str(args.spec)!r}: {exc.strerror or exc}",
            subject={"path": str(args.spec)},
            supported_fixes=("pass the path to an existing, readable YAML spec",),
        )
        envelope = _envelope(False, args.quality, [unreadable], args.output)
        _report(envelope, args.as_json, [unreadable])
        return EXIT_USAGE

    import fetch_icons  # local import: keeps render.py importable without pulling in networking deps for pure-layout tests

    cache_dir = args.cache_dir or fetch_icons.default_cache_dir()
    sha = args.sha or fetch_icons.DRAWIO_SHA
    lookup = CompositeIconLookup(
        [CacheIconLookup(cache_dir=cache_dir, sha=sha), BundledGenericIconLookup()]
    )

    try:
        spec = load_spec(spec_text)
    except SpecError as exc:
        envelope = _envelope(False, args.quality, [exc.diagnostic], args.output)
        _report(envelope, args.as_json, [exc.diagnostic])
        return EXIT_FAILURE

    result = render(spec, lookup, quality=args.quality)
    args.output.write_text(result.svg)
    envelope = _envelope(
        result.ok,
        args.quality,
        result.diagnostics,
        args.output,
        artifact_bytes=len(result.svg),
    )
    _report(envelope, args.as_json, result.diagnostics)
    return EXIT_OK if result.ok else EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
