"""Editable SVG emission and output editability validation."""

from __future__ import annotations

from .diagnostics import Diagnostic, SEVERITY_ERROR
from .icons import IconRef
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
    icon_box,
    text_width,
    zone_ancestors,
)
from .model import Node, Spec, Zone
from .routing import RoutedEdge

EDGE_COLORS = {
    "realtime": "#2563EB",
    "batch": "#DC2626",
    "event": "#16A34A",
    "control": "#D97706",
    "default": "#5A6C86",
}

_FORBIDDEN_MARKERS = ("<image", "base64,", "<use ", "<use>")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
        supported_fixes=("shorten the text", "move the detail into `sublabel`"),
    )


def _icon_not_found(node: Node) -> Diagnostic:
    fixes = ["use the exact slug from that provider's reference service map"]
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


def _source_attributes(source_ids: tuple[str, ...]) -> str:
    if not source_ids:
        return ">"
    joined = ",".join(sorted(source_ids))
    return f' data-source-ids="{_escape(joined)}"><title>{_escape(joined)}</title>'


def _source_badge(source_ids: tuple[str, ...], x: float, y: float) -> str:
    if not source_ids:
        return ""
    return (
        f'<text x="{x:g}" y="{y:g}" font-size="8" font-weight="700" '
        f'text-anchor="middle" fill="#047857">VERIFIED SRC {len(source_ids)}</text>'
    )


def _node_svg(
    node: Node,
    box: Box,
    icon: IconRef | None,
    diagnostics: list[Diagnostic],
    source_badges: bool,
) -> str:
    source_ids = node.sources if source_badges else ()
    parts = [f'<g id="node-{_escape(node.id)}"{_source_attributes(source_ids)}']
    icon_position = icon_box(box)
    parts.append(
        f'<rect x="{icon_position.x:g}" y="{icon_position.y:g}" width="{ICON:g}" height="{ICON:g}" rx="10" fill="{node.color}"/>'
    )
    if icon is not None:
        inset = 9
        parts.append(
            f'<svg x="{icon_position.x + inset:g}" y="{icon_position.y + inset:g}" width="{ICON - inset * 2:g}" '
            f'height="{ICON - inset * 2:g}" viewBox="{icon.view_box}" color="#FFFFFF">{icon.body}</svg>'
        )
    else:
        if node.service:
            diagnostics.append(_icon_not_found(node))
        center_x, center_y = (
            icon_position.x + ICON / 2,
            icon_position.y + ICON / 2,
        )
        initial = _escape(node.label[:1].upper() or "?")
        parts.append(
            f'<text x="{center_x:g}" y="{center_y + 6:g}" font-size="22" font-weight="700" text-anchor="middle" fill="#FFFFFF">{initial}</text>'
        )
    label_y = box.y + ICON + 18
    label_font_size = _fitted_node_font_size(node.label, NODE_LABEL_FONT_SIZE, box)
    if label_font_size is None:
        diagnostics.append(
            _label_overflow(node.id, "label", node.label, NODE_LABEL_FONT_SIZE, box)
        )
        label_font_size = MIN_NODE_TEXT_FONT_SIZE
    parts.append(
        f'<text x="{box.x + box.w / 2:g}" y="{label_y:g}" font-size="{label_font_size:g}" font-weight="600" '
        f'text-anchor="middle" fill="#1F2937">{_escape(node.label)}</text>'
    )
    if node.sublabel:
        sublabel_font_size = _fitted_node_font_size(
            node.sublabel, NODE_SUBLABEL_FONT_SIZE, box
        )
        if sublabel_font_size is None:
            diagnostics.append(
                _label_overflow(
                    node.id,
                    "sublabel",
                    node.sublabel,
                    NODE_SUBLABEL_FONT_SIZE,
                    box,
                )
            )
            sublabel_font_size = MIN_NODE_TEXT_FONT_SIZE
        parts.append(
            f'<text x="{box.x + box.w / 2:g}" y="{label_y + 15:g}" font-size="{sublabel_font_size:g}" '
            f'text-anchor="middle" fill="#6B7280">{_escape(node.sublabel)}</text>'
        )
    parts.append(_source_badge(source_ids, box.x + box.w / 2, box.y + box.h - 8))
    parts.append("</g>")
    return "".join(parts)


def _zone_svg(zone: Zone, box: Box) -> str:
    return (
        f'<g id="zone-{_escape(zone.id)}">'
        f'<rect x="{box.x:g}" y="{box.y:g}" width="{box.w:g}" height="{box.h:g}" rx="8" '
        f'fill="none" stroke="#8C4FFF" stroke-width="1.5" stroke-dasharray="6 4"/>'
        f'<text x="{box.x + 12:g}" y="{box.y + 18:g}" font-size="11" font-weight="600" fill="#8C4FFF">{_escape(zone.label)}</text>'
        "</g>"
    )


def _edge_svg(routed: RoutedEdge, source_badges: bool) -> str:
    edge = routed.edge
    color = EDGE_COLORS.get(edge.type, EDGE_COLORS["default"])
    dash = ' stroke-dasharray="6 4"' if edge.type == "batch" else ""
    marker = f'marker-end="url(#arrow-{edge.type})"'
    source_ids = edge.sources if source_badges else ()
    parts = [
        f'<g id="edge-{_escape(edge.src)}-{_escape(edge.dst)}"{_source_attributes(source_ids)}'
    ]
    parts.append(
        f'<path d="{routed.path_d}" fill="none" stroke="{color}" stroke-width="1.8"{dash} {marker}/>'
    )
    if edge.label:
        x, y = routed.label_pos
        parts.append(
            f'<text x="{x:g}" y="{y:g}" font-size="{EDGE_LABEL_FONT_SIZE:g}" fill="{color}">{_escape(edge.label)}</text>'
        )
    x, y = routed.label_pos
    parts.append(_source_badge(source_ids, x, y + 14))
    parts.append("</g>")
    return "".join(parts)


def _legend_svg(edge_types: set[str], x: float, y: float) -> str:
    parts = ['<g id="legend">']
    for index, edge_type in enumerate(sorted(edge_types)):
        color = EDGE_COLORS.get(edge_type, EDGE_COLORS["default"])
        label_y = y + index * 18
        parts.append(
            f'<line x1="{x:g}" y1="{label_y:g}" x2="{x + 24:g}" y2="{label_y:g}" stroke="{color}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x + 30:g}" y="{label_y + 4:g}" font-size="10" fill="#374151">{_escape(edge_type)}</text>'
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
    source_badges: bool = False,
) -> str:
    """Emit standalone editable SVG markup from computed layout and icons."""
    zone_by_id = {zone.id: zone for zone in spec.zones}
    all_extents = [*node_boxes.values(), *zone_boxes.values()]
    width = max((box.x2 for box in all_extents), default=NODE_W) + MARGIN
    height = max((box.y2 for box in all_extents), default=NODE_H) + MARGIN

    edge_types = {edge.type for edge in spec.edges}
    show_legend = len(edge_types) > 1
    legend_height = 12 + len(edge_types) * 18 if show_legend else 0
    height += legend_height

    svg_open = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
        f'viewBox="0 0 {width:g} {height:g}" font-family="Segoe UI, system-ui, sans-serif">'
    )
    parts = [
        svg_open,
        f'<rect width="{width:g}" height="{height:g}" fill="#FAFAF8"/>',
        "<defs>",
    ]
    for edge_type, color in EDGE_COLORS.items():
        parts.append(
            f'<marker id="arrow-{edge_type}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>'
        )
    parts.append("</defs>")

    if spec.title:
        parts.append(
            f'<text x="{MARGIN:g}" y="{MARGIN + 14:g}" font-size="17" font-weight="700" fill="#1F2937">{_escape(spec.title)}</text>'
        )

    for zone_id in sorted(
        zone_boxes, key=lambda value: len(zone_ancestors(spec, value))
    ):
        parts.append(_zone_svg(zone_by_id[zone_id], zone_boxes[zone_id]))
    for routed in routed_edges:
        parts.append(_edge_svg(routed, source_badges))
    for node in spec.nodes:
        parts.append(
            _node_svg(
                node,
                node_boxes[node.id],
                icons.get(node.id),
                diagnostics,
                source_badges,
            )
        )
    if show_legend:
        parts.append(_legend_svg(edge_types, MARGIN, height - legend_height + 6))

    parts.append("</svg>")
    return "".join(parts)


def check_editability(svg_text: str) -> list[Diagnostic]:
    """Reject raster, clone, and remote-reference output markup."""
    findings: list[Diagnostic] = []
    for marker in _FORBIDDEN_MARKERS:
        if marker in svg_text:
            findings.append(
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
            findings.append(
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
    return findings
