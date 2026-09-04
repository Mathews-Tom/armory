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
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


from . import fetch_icons
from .data import data_path

from .compare import compare_specs
from .diagnostics import (
    QUALITY_PROFILES,
    QUALITY_STANDARD,
    SEVERITY_ERROR,
    Diagnostic,
    apply_quality_profile,
    count_by_severity,
    suppress_derived,
)
from .model import Node, Spec, Zone
from .spec import SpecError, load_spec
from .geometry_checks import (
    check_ambiguous_corridors,
    check_edge_through_node,
    check_label_route_clearance,
    check_layout,
    check_proper_crossings,
    check_route_rhythm,
    edge_label_box,
)
from .layout import (
    EDGE_LABEL_FONT_SIZE,
    ICON,
    MARGIN,
    MIN_NODE_TEXT_FONT_SIZE,
    NODE_H,
    NODE_LABEL_FONT_SIZE,
    NODE_SUBLABEL_FONT_SIZE,
    NODE_TEXT_PADDING,
    NODE_W,
    Box,
    assign_ranks,
    box_evidence,
    compute_positions,
    compute_zone_boxes,
    icon_box,
    order_within_ranks,
    text_width,
    zone_ancestors,
)
from .profile import check_deployment_profile
from .routing import RoutedEdge, route_edges

# --- layout constants -------------------------------------------------------

# Shared-side ports must stay away from the icon corners and remain legible as
# fan-out grows. A 64px icon leaves a 32px usable span after 16px gutters:
# five ports therefore land 8px apart without one endpoint covering another.
# Rejoin a lone source/destination pair when their spread ports are nearly
# aligned. This keeps short hops straight without collapsing a shared side.
# Orthogonal detours leave a real 24px endpoint stub. Centered channel offsets
# span at most +/-16px, so even their nearest first segment is at least 8px.
# Route rhythm failures are composition findings: every segment needs 8px and
# a segment between two turns needs 16px to remain visually distinguishable.
# A route passing within two pixels of an unrelated node visually reads as
# entering it. Expand every unrelated node by this clearance before testing.
# Cross-product signs closer than this are endpoint touches or collinear runs,
# not an interior X that makes two unrelated relationships ambiguous.
# Unrelated collinear paths sharing eight pixels or more read as one ambiguous
# corridor rather than distinct connections.
# Edge labels use the same glyph estimator as nodes. A route closer than four
# pixels to the label mask makes the connection annotation unreadable.
# Node labels stay readable at no smaller than 6px. Their estimated width at
# that floor must remain within the node plus 8px tolerance, while normal
# fitted text remains inside the 8px-padded node box.


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


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- diagnostics -------------------------------------------------------------


# Codes in this namespace describe how the drawing reads rather than whether
# the spec is answerable: two routes crossing, a label sitting on a route.
# They are warnings under the standard profile and errors under showcase, so
# stricter geometry rules can ship without breaking specs that already render.


# --- spec -------------------------------------------------------------------


# --- ranking + ordering ------------------------------------------------------


# --- geometry ----------------------------------------------------------------


# --- routing -----------------------------------------------------------------


# --- icon resolution ----------------------------------------------------------


@dataclass
class IconRef:
    view_box: str
    body: str


class IconLookup(Protocol):
    def __call__(self, provider: str, service_slug: str) -> IconRef | None: ...


class IconCacheError(RuntimeError):
    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


@dataclass
class CacheIconLookup:
    """Verified local cloud-provider icon cache — see fetch_icons.py."""

    cache_dir: Path
    sha: str

    def _error(
        self,
        code: str,
        message: str,
        provider: str,
        service_slug: str,
        evidence: dict[str, object],
    ) -> IconCacheError:
        return IconCacheError(
            Diagnostic(
                code=code,
                severity=SEVERITY_ERROR,
                message=message,
                subject={"provider": provider, "service": service_slug},
                evidence=evidence,
                supported_fixes=(
                    f"rebuild the {provider} icon cache: "
                    f"fetch_icons.py --provider {provider} --force",
                ),
                suppresses=("icon/not-found",),
            )
        )

    def __call__(self, provider: str, service_slug: str) -> IconRef | None:
        cache_root = self.cache_dir / self.sha
        path = cache_root / provider / f"{service_slug}.json"
        if not path.exists():
            return None
        manifest_path = cache_root / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text())
            payload = path.read_bytes()
        except (OSError, json.JSONDecodeError) as exc:
            raise self._error(
                "icon/cache-unverified",
                f"icon cache entry {path} has no readable integrity manifest",
                provider,
                service_slug,
                {"path": str(path), "error": str(exc)},
            ) from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("format_version") != fetch_icons.CACHE_MANIFEST_VERSION
            or manifest.get("sha") != self.sha
            or not isinstance(manifest.get("providers"), dict)
        ):
            raise self._error(
                "icon/cache-unverified",
                f"icon cache entry {path} has an unsupported integrity manifest",
                provider,
                service_slug,
                {"path": str(path)},
            )
        provider_stats = manifest["providers"].get(provider)
        if not isinstance(provider_stats, dict) or not isinstance(
            provider_stats.get("icons"), dict
        ):
            raise self._error(
                "icon/cache-unverified",
                f"icon cache entry {path} is absent from its integrity manifest",
                provider,
                service_slug,
                {"path": str(path)},
            )
        record = provider_stats["icons"].get(path.name)
        expected_digest = record.get("sha256") if isinstance(record, dict) else None
        actual_digest = hashlib.sha256(payload).hexdigest()
        if not isinstance(expected_digest, str):
            raise self._error(
                "icon/cache-unverified",
                f"icon cache entry {path} has no recorded content digest",
                provider,
                service_slug,
                {"path": str(path)},
            )
        if actual_digest != expected_digest:
            raise self._error(
                "icon/digest-mismatch",
                f"icon cache entry {path} does not match its recorded digest",
                provider,
                service_slug,
                {
                    "path": str(path),
                    "expected_sha256": expected_digest,
                    "actual_sha256": actual_digest,
                },
            )
        try:
            data = json.loads(payload)
            return IconRef(view_box=data["viewBox"], body=data["body"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise self._error(
                "icon/cache-unverified",
                f"verified icon cache entry {path} is not a usable icon",
                provider,
                service_slug,
                {"path": str(path), "error": str(exc)},
            ) from exc


@dataclass
class BundledGenericIconLookup:
    """Hand-drawn, non-cloud icon catalog shipped inside this skill package
    (assets/generic-icons.json, generated from references/icons-generic.md).
    No network, no cache directory — always available. Only answers for
    provider == "generic"; every cloud provider is CacheIconLookup's job."""

    path: Path = field(
        default_factory=lambda: data_path("assets", "generic-icons.json")
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


def _fitted_node_font_size(text: str, preferred_size: float, box: Box) -> float | None:
    """Return a readable fitted size, or None when the label cannot fit safely."""
    available = box.w - NODE_TEXT_PADDING
    projected_minimum_width = text_width(text, MIN_NODE_TEXT_FONT_SIZE)
    if projected_minimum_width > box.w + NODE_TEXT_PADDING:
        return None
    unit_width = text_width(text, 1.0)
    if unit_width == 0:
        return preferred_size
    fitted_size = min(preferred_size, available / unit_width)
    return fitted_size if fitted_size >= MIN_NODE_TEXT_FONT_SIZE else None


def _label_overflow(
    node_id: str, field_name: str, text: str, preferred_size: float, box: Box
) -> Diagnostic:
    return Diagnostic(
        code="layout/label-overflow",
        severity=SEVERITY_ERROR,
        message=f"{field_name} cannot fit inside its node box: {text!r} on {node_id!r}",
        subject={"node": node_id, "field": field_name},
        evidence={
            "text": text,
            "estimated_width": round(text_width(text, preferred_size), 2),
            "available_width": box.w - NODE_TEXT_PADDING,
            "projected_minimum_width": round(
                text_width(text, MIN_NODE_TEXT_FONT_SIZE), 2
            ),
            "minimum_font_size": MIN_NODE_TEXT_FONT_SIZE,
            "maximum_projected_width": box.w + NODE_TEXT_PADDING,
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
    label_font_size = _fitted_node_font_size(node.label, NODE_LABEL_FONT_SIZE, box)
    if label_font_size is None:
        diagnostics.append(
            _label_overflow(
                node.id,
                "label",
                node.label,
                NODE_LABEL_FONT_SIZE,
                box,
            )
        )
        label_font_size = MIN_NODE_TEXT_FONT_SIZE
    parts.append(
        f'<text x="{box.x + box.w / 2:g}" y="{label_y:g}" font-size="{label_font_size:g}" font-weight="600" '
        f'text-anchor="middle" fill="#1F2937">{_escape(node.label)}</text>'
    )
    if node.sublabel:
        sub_font_size = _fitted_node_font_size(
            node.sublabel, NODE_SUBLABEL_FONT_SIZE, box
        )
        if sub_font_size is None:
            diagnostics.append(
                _label_overflow(
                    node.id,
                    "sublabel",
                    node.sublabel,
                    NODE_SUBLABEL_FONT_SIZE,
                    box,
                )
            )
            sub_font_size = MIN_NODE_TEXT_FONT_SIZE
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
            f'<text x="{mx:g}" y="{my:g}" font-size="{EDGE_LABEL_FONT_SIZE:g}" fill="{color}">{_escape(e.label)}</text>'
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
    for zid in sorted(zone_boxes, key=lambda z: len(zone_ancestors(spec, z))):
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
    node_boxes: dict[str, Box] = field(default_factory=dict)
    zone_boxes: dict[str, Box] = field(default_factory=dict)
    routed_edges: list[RoutedEdge] = field(default_factory=list)

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
    diagnostics += check_deployment_profile(spec)
    rank = assign_ranks(spec)
    order = order_within_ranks(spec, rank)
    node_boxes = compute_positions(spec, rank, order)
    zone_boxes = compute_zone_boxes(spec, node_boxes) if spec.zones else {}
    diagnostics += check_layout(spec, node_boxes, zone_boxes)
    routed_edges = route_edges(spec, node_boxes)
    diagnostics += check_route_rhythm(routed_edges)
    diagnostics += check_edge_through_node(node_boxes, routed_edges)
    diagnostics += check_proper_crossings(routed_edges)
    diagnostics += check_ambiguous_corridors(routed_edges)
    diagnostics += check_label_route_clearance(routed_edges)

    icons: dict[str, IconRef | None] = {}
    for n in spec.nodes:
        if not n.service:
            icons[n.id] = None
            continue
        try:
            icons[n.id] = icon_lookup(n.provider, n.service)
        except IconCacheError as exc:
            diagnostics.append(exc.diagnostic)
            icons[n.id] = None

    svg = emit_svg(spec, node_boxes, zone_boxes, routed_edges, icons, diagnostics)
    diagnostics += check_editability(svg)
    diagnostics = apply_quality_profile(suppress_derived(diagnostics), quality)
    return RenderResult(
        svg=svg,
        diagnostics=diagnostics,
        node_boxes=node_boxes,
        zone_boxes=zone_boxes,
        routed_edges=routed_edges,
    )


EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

RECEIPT_SCHEMA_VERSION = 1
COMPARISON_LIMITATIONS = "Authored specification only; no runtime impact, causality, risk, or merge safety is inferred."


def _comparison_receipt(
    base_path: Path,
    base_bytes: bytes | None,
    head_path: Path,
    head_bytes: bytes | None,
    diagnostics: list[Diagnostic],
    comparison: dict[str, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "ok": not any(d.severity == SEVERITY_ERROR for d in diagnostics),
        "command": "compare",
        "type": "architecture-diagram",
        "base": {
            "path": str(base_path),
            "sha256": _sha256(base_bytes) if base_bytes is not None else None,
            "bytes": len(base_bytes) if base_bytes is not None else None,
        },
        "head": {
            "path": str(head_path),
            "sha256": _sha256(head_bytes) if head_bytes is not None else None,
            "bytes": len(head_bytes) if head_bytes is not None else None,
        },
        "comparison": comparison or {"nodes": [], "edges": []},
        "limitations": COMPARISON_LIMITATIONS,
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
    }


_VALIDATION_CHECKS = (
    "spec",
    "layout",
    "route-rhythm",
    "edge-through-node",
    "proper-crossing",
    "ambiguous-corridor",
    "label-route-clearance",
    "icons",
    "labels",
    "editability",
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _check_name(diagnostic: Diagnostic) -> str:
    code = diagnostic.code
    if code.startswith("spec/"):
        return "spec"
    if code.startswith("profile/"):
        return "profile"
    if code in ("layout/node-overlap", "layout/zone-overlap"):
        return "layout"
    if code == "layout/label-overflow":
        return "labels"
    if code.startswith("composition/micro-segment") or code.startswith(
        "composition/short-interior-segment"
    ):
        return "route-rhythm"
    if code == "composition/edge-through-node":
        return "edge-through-node"
    if code == "composition/proper-crossing":
        return "proper-crossing"
    if code == "composition/ambiguous-corridor":
        return "ambiguous-corridor"
    if code == "composition/label-route-clearance":
        return "label-route-clearance"
    if code.startswith("icon/"):
        return "icons"
    return "editability"


def _validation_receipt(
    diagnostics: list[Diagnostic], quality: str, profile_active: bool = False
) -> dict[str, object]:
    checks = _VALIDATION_CHECKS + (("profile",) if profile_active else ())
    counts = count_by_severity(diagnostics)
    composition = [d for d in diagnostics if d.code.startswith("composition/")]
    if any(d.severity == SEVERITY_ERROR for d in composition):
        composition_status = "failed"
    elif composition:
        composition_status = "warnings"
    else:
        composition_status = "passed"
    failed_checks = {
        _check_name(d) for d in diagnostics if d.severity == SEVERITY_ERROR
    }
    return {
        "checks_passed": len(checks) - len(failed_checks),
        "checks_total": len(checks),
        "quality": quality,
        "composition_status": composition_status,
        "errors": counts["errors"],
        "warnings": counts["warnings"],
    }


def _receipt(
    command: str,
    input_path: Path,
    input_bytes: bytes | None,
    artifact_bytes: bytes | None,
    diagnostics: list[Diagnostic],
    quality: str,
    output: Path | None = None,
    written: bool = False,
    delivery_stage: str | None = None,
    profile_active: bool = False,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "ok": not any(d.severity == SEVERITY_ERROR for d in diagnostics),
        "command": command,
        "type": "architecture-diagram",
        "input": {
            "path": str(input_path),
            "sha256": _sha256(input_bytes) if input_bytes is not None else None,
            "bytes": len(input_bytes) if input_bytes is not None else None,
        },
        "artifact": {
            "sha256": _sha256(artifact_bytes) if artifact_bytes is not None else None,
            "bytes": len(artifact_bytes) if artifact_bytes is not None else None,
        },
        "output": {
            "path": str(output) if output is not None else None,
            "written": written,
        },
        "validation": _validation_receipt(diagnostics, quality, profile_active),
        "diagnostics": [d.to_dict() for d in diagnostics],
    }
    if delivery_stage is not None:
        receipt["delivery_stage"] = delivery_stage
    return receipt


def _layout_report(spec: Spec, result: RenderResult) -> dict[str, object]:
    """Expose the exact boxes and waypoints used by SVG emission."""
    return {
        "nodes": [
            {"id": node.id, "box": box_evidence(result.node_boxes[node.id])}
            for node in spec.nodes
        ],
        "zones": [
            {
                "id": zone.id,
                "label": zone.label,
                "parent": zone.parent,
                "members": [node.id for node in spec.nodes if node.zone == zone.id],
                "box": box_evidence(result.zone_boxes[zone.id]),
            }
            for zone in spec.zones
        ],
        "edges": [
            {
                "from": routed.edge.src,
                "to": routed.edge.dst,
                "label": routed.edge.label,
                "type": routed.edge.type,
                "points": [{"x": x, "y": y} for x, y in routed.points],
                "label_position": {
                    "x": routed.label_pos[0],
                    "y": routed.label_pos[1],
                },
            }
            for routed in result.routed_edges
        ],
        "labels": [
            {
                "edge": {"from": routed.edge.src, "to": routed.edge.dst},
                "text": routed.edge.label,
                "box": box_evidence(edge_label_box(routed)),
            }
            for routed in result.routed_edges
            if routed.edge.label
        ],
    }


def _report(
    receipt: dict[str, object], as_json: bool, diagnostics: list[Diagnostic]
) -> None:
    """Under --json, stdout carries the receipt and nothing else."""
    if as_json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return
    output = receipt["output"]
    assert isinstance(output, dict)
    if output["written"]:
        artifact = receipt["artifact"]
        assert isinstance(artifact, dict)
        print(f"wrote {output['path']} ({artifact['bytes']} bytes)")
    for d in diagnostics:
        print(f"{d.severity}: [{d.code}] {d.message}", file=sys.stderr)
        for fix in d.supported_fixes:
            print(f"  fix: {fix}", file=sys.stderr)


def _input_failure(
    command: str, spec_path: Path, output: Path | None, quality: str, exc: Exception
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    diagnostic = Diagnostic(
        code="usage/spec-unreadable",
        severity=SEVERITY_ERROR,
        message=f"cannot read spec {str(spec_path)!r}: {exc}",
        subject={"path": str(spec_path)},
        supported_fixes=("pass the path to an existing UTF-8 YAML spec",),
    )
    return (
        EXIT_USAGE,
        _receipt(
            command,
            spec_path,
            None,
            None,
            [diagnostic],
            quality,
            output=output,
            delivery_stage="input",
        ),
        [diagnostic],
    )


def _read_spec(
    command: str, spec_path: Path, output: Path | None, quality: str
) -> tuple[bytes, str] | tuple[int, dict[str, object], list[Diagnostic]]:
    try:
        source = spec_path.read_bytes()
        return source, source.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _input_failure(command, spec_path, output, quality, exc)


def _read_comparison_spec(
    side: str, path: Path
) -> tuple[bytes | None, Spec | None, Diagnostic | None]:
    try:
        source = path.read_bytes()
        text = source.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return (
            None,
            None,
            Diagnostic(
                code=f"compare/{side}-unreadable",
                severity=SEVERITY_ERROR,
                message=f"cannot read {side} specification {str(path)!r}: {exc}",
                subject={"path": str(path)},
                supported_fixes=("pass an existing UTF-8 YAML specification",),
            ),
        )
    try:
        return source, load_spec(text), None
    except SpecError as exc:
        return source, None, exc.diagnostic


def _compare(
    base_path: Path, head_path: Path
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    base_bytes, base_spec, base_error = _read_comparison_spec("base", base_path)
    head_bytes, head_spec, head_error = _read_comparison_spec("head", head_path)
    diagnostics = [error for error in (base_error, head_error) if error is not None]
    if diagnostics:
        return (
            EXIT_FAILURE,
            _comparison_receipt(
                base_path, base_bytes, head_path, head_bytes, diagnostics
            ),
            diagnostics,
        )

    assert base_spec is not None
    assert head_spec is not None
    try:
        comparison = compare_specs(base_spec, head_spec)
    except SpecError as exc:
        diagnostics = [exc.diagnostic]
        return (
            EXIT_FAILURE,
            _comparison_receipt(
                base_path, base_bytes, head_path, head_bytes, diagnostics
            ),
            diagnostics,
        )
    return (
        EXIT_OK,
        _comparison_receipt(
            base_path, base_bytes, head_path, head_bytes, [], comparison
        ),
        [],
    )


def _icon_lookup(cache_dir: Path | None, sha: str | None) -> IconLookup:
    selected_cache_dir = cache_dir or fetch_icons.default_cache_dir()
    selected_sha = sha or fetch_icons.DRAWIO_SHA
    return CompositeIconLookup(
        [
            CacheIconLookup(cache_dir=selected_cache_dir, sha=selected_sha),
            BundledGenericIconLookup(),
        ]
    )


def _render_candidate(
    spec_text: str, lookup: IconLookup, quality: str
) -> tuple[Spec | None, RenderResult | None, bytes | None, list[Diagnostic]]:
    try:
        spec = load_spec(spec_text)
    except SpecError as exc:
        return None, None, None, [exc.diagnostic]
    result = render(spec, lookup, quality=quality)
    return spec, result, result.svg.encode("utf-8"), result.diagnostics


def _validate(
    spec_path: Path,
    cache_dir: Path | None,
    sha: str | None,
    quality: str,
    layout_json: bool,
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    loaded = _read_spec("validate", spec_path, None, quality)
    if len(loaded) == 3:
        return loaded
    spec_bytes, spec_text = loaded
    spec, result, artifact_bytes, diagnostics = _render_candidate(
        spec_text, _icon_lookup(cache_dir, sha), quality
    )
    if artifact_bytes is not None:
        with tempfile.TemporaryDirectory(
            prefix=".architecture-diagram-validate-"
        ) as path:
            candidate = Path(path) / "candidate.svg"
            candidate.write_bytes(artifact_bytes)
            artifact_bytes = candidate.read_bytes()
    receipt = _receipt(
        "validate",
        spec_path,
        spec_bytes,
        artifact_bytes,
        diagnostics,
        quality,
        delivery_stage="check" if result is not None and not result.ok else None,
        profile_active=spec is not None and spec.profile is not None,
    )
    if layout_json and spec is not None and result is not None:
        receipt["layout"] = _layout_report(spec, result)
    return (EXIT_OK if receipt["ok"] else EXIT_FAILURE), receipt, diagnostics


def _delivery_failure(
    spec_path: Path,
    spec_bytes: bytes | None,
    artifact_bytes: bytes | None,
    output: Path,
    quality: str,
    stage: str,
    exc: Exception,
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    diagnostic = Diagnostic(
        code=f"delivery/{stage}-failed",
        severity=SEVERITY_ERROR,
        message=f"delivery {stage} failed: {exc}",
        subject={"output": str(output)},
        supported_fixes=(
            "correct the output path or filesystem permissions and rerun delivery",
        ),
    )
    return (
        EXIT_FAILURE,
        _receipt(
            "deliver",
            spec_path,
            spec_bytes,
            artifact_bytes,
            [diagnostic],
            quality,
            output=output,
            delivery_stage=stage,
        ),
        [diagnostic],
    )


def _deliver(
    spec_path: Path,
    output: Path,
    cache_dir: Path | None,
    sha: str | None,
    quality: str,
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    loaded = _read_spec("deliver", spec_path, output, quality)
    if len(loaded) == 3:
        return loaded
    spec_bytes, spec_text = loaded
    output_parent = output.parent
    try:
        if not output_parent.is_dir():
            raise OSError(f"output directory does not exist: {output_parent}")
        with tempfile.TemporaryDirectory(
            prefix=".architecture-diagram-delivery-", dir=output_parent
        ) as stage_name:
            stage_dir = Path(stage_name)
            if os.stat(stage_dir).st_dev != os.stat(output_parent).st_dev:
                raise OSError("staging directory is not on the output filesystem")
            (stage_dir / "specification.yaml").write_bytes(spec_bytes)
            spec, result, artifact_bytes, diagnostics = _render_candidate(
                spec_text, _icon_lookup(cache_dir, sha), quality
            )
            if artifact_bytes is None:
                receipt = _receipt(
                    "deliver",
                    spec_path,
                    spec_bytes,
                    None,
                    diagnostics,
                    quality,
                    output=output,
                    delivery_stage="render",
                    profile_active=spec is not None and spec.profile is not None,
                )
                return EXIT_FAILURE, receipt, diagnostics
            candidate = stage_dir / "candidate.svg"
            candidate.write_bytes(artifact_bytes)
            if os.stat(candidate).st_dev != os.stat(output_parent).st_dev:
                raise OSError("candidate artifact is not on the output filesystem")
            if result is None or not result.ok:
                receipt = _receipt(
                    "deliver",
                    spec_path,
                    spec_bytes,
                    artifact_bytes,
                    diagnostics,
                    quality,
                    output=output,
                    delivery_stage="check",
                    profile_active=spec is not None and spec.profile is not None,
                )
                return EXIT_FAILURE, receipt, diagnostics
            receipt = _receipt(
                "deliver",
                spec_path,
                spec_bytes,
                artifact_bytes,
                diagnostics,
                quality,
                output=output,
                written=True,
                delivery_stage="commit",
                profile_active=spec is not None and spec.profile is not None,
            )
            try:
                (stage_dir / "receipt.json").write_text(
                    json.dumps(receipt, indent=2, sort_keys=True)
                )
            except OSError as exc:
                return _delivery_failure(
                    spec_path,
                    spec_bytes,
                    artifact_bytes,
                    output,
                    quality,
                    "receipt",
                    exc,
                )
            try:
                os.replace(candidate, output)
            except OSError as exc:
                return _delivery_failure(
                    spec_path,
                    spec_bytes,
                    artifact_bytes,
                    output,
                    quality,
                    "commit",
                    exc,
                )
            return EXIT_OK, receipt, diagnostics
    except OSError as exc:
        return _delivery_failure(
            spec_path, spec_bytes, None, output, quality, "prepare", exc
        )


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("spec", type=Path, help="path to a UTF-8 YAML spec")
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
        help="print the machine-readable receipt to stdout and nothing else",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate_parser = commands.add_parser(
        "validate", help="render and validate without writing an output artifact"
    )
    _add_common_arguments(validate_parser)
    validate_parser.add_argument(
        "--layout-json",
        action="store_true",
        help="print the exact emitted layout geometry without writing an SVG",
    )
    deliver_parser = commands.add_parser(
        "deliver", help="validate, stage, and atomically commit an SVG artifact"
    )
    _add_common_arguments(deliver_parser)
    deliver_parser.add_argument(
        "-o", "--output", type=Path, required=True, help="target SVG path"
    )
    compare_parser = commands.add_parser(
        "compare", help="compare two authored specifications into a JSON receipt"
    )
    compare_parser.add_argument("base", type=Path, help="baseline UTF-8 YAML spec")
    compare_parser.add_argument("head", type=Path, help="changed UTF-8 YAML spec")

    args = parser.parse_args(argv)

    if args.command == "compare":
        code, receipt, diagnostics = _compare(args.base, args.head)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return code
    if args.command == "validate":
        code, receipt, diagnostics = _validate(
            args.spec, args.cache_dir, args.sha, args.quality, args.layout_json
        )
    else:
        code, receipt, diagnostics = _deliver(
            args.spec, args.output, args.cache_dir, args.sha, args.quality
        )
    _report(receipt, args.as_json or getattr(args, "layout_json", False), diagnostics)
    return code


if __name__ == "__main__":
    sys.exit(main())
