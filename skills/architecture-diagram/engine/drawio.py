"""Deterministic, self-contained mxGraph projection for architecture diagrams."""

from __future__ import annotations

from urllib.parse import quote
import xml.etree.ElementTree as ElementTree

from .layout import Box, ICON, icon_box, zone_ancestors
from .model import Node, Spec, Zone
from .pipeline import RenderResult
from .svg import EDGE_COLORS

_MXFILE_ID = "architecture-diagram"
_ROOT_ID = "0"
_DEFAULT_PARENT_ID = "1"


def _number(value: float) -> str:
    """Serialize one computed coordinate without representation drift."""
    return f"{value:g}"


def _cell_id(kind: str, authored_id: str) -> str:
    """Keep every cell addressable through its authored identity."""
    return f"{kind}-{authored_id}"


def _cell(
    cell_id: str,
    value: str,
    style: str,
    parent: str,
    *,
    vertex: bool = False,
    edge: bool = False,
    source: str | None = None,
    target: str | None = None,
) -> ElementTree.Element:
    attributes = {"id": cell_id, "value": value, "style": style, "parent": parent}
    if vertex:
        attributes["vertex"] = "1"
    if edge:
        attributes["edge"] = "1"
    if source is not None:
        attributes["source"] = source
    if target is not None:
        attributes["target"] = target
    return ElementTree.Element("mxCell", attributes)


def _geometry(
    cell: ElementTree.Element,
    box: Box,
    *,
    relative: bool = False,
) -> None:
    attributes = {
        "x": _number(box.x),
        "y": _number(box.y),
        "width": _number(box.w),
        "height": _number(box.h),
        "as": "geometry",
    }
    if relative:
        attributes["relative"] = "1"
    ElementTree.SubElement(cell, "mxGeometry", attributes)


def _relative_box(box: Box, parent: Box | None) -> Box:
    """Translate absolute engine geometry into an mxGraph parent coordinate space."""
    if parent is None:
        return box
    return Box(box.x - parent.x, box.y - parent.y, box.w, box.h)


def _inline_icon_uri(view_box: str, body: str) -> str:
    """Embed a resolved vector icon without a remote image or stencil dependency."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{view_box}" color="#FFFFFF">{body}</svg>'
    )
    return f"data:image/svg+xml,{quote(svg, safe='')}"


def _zone_style(zone: Zone) -> str:
    colors = {
        "generic": ("#F5F3FF", "#7C3AED"),
        "region": ("#EFF6FF", "#2563EB"),
        "security": ("#ECFDF5", "#059669"),
    }
    fill, stroke = colors[zone.kind]
    return (
        "swimlane;horizontal=0;startSize=28;rounded=1;arcSize=8;html=1;"
        f"fillColor={fill};strokeColor={stroke};fontColor={stroke};"
    )


def _node_style(node: Node) -> str:
    return f"rounded=1;arcSize=8;html=1;fillColor=#FFFFFF;strokeColor={node.color};"


def _icon_style(node: Node, icon_uri: str | None) -> str:
    if icon_uri is None:
        return f"shape=ellipse;html=1;fillColor={node.color};strokeColor={node.color};"
    return f"shape=image;imageAspect=0;html=1;image={icon_uri};"


def _text_style(color: str, *, bold: bool = False) -> str:
    weight = "fontStyle=1;" if bold else ""
    return f"text;html=1;align=center;verticalAlign=middle;{weight}fontColor={color};"


def _append_node(
    root: ElementTree.Element,
    node: Node,
    result: RenderResult,
    *,
    source_badges: bool,
) -> None:
    node_box = result.node_boxes[node.id]
    parent_box = result.zone_boxes.get(node.zone) if node.zone is not None else None
    parent_id = (
        _cell_id("zone", node.zone) if node.zone is not None else _DEFAULT_PARENT_ID
    )
    node_id = _cell_id("node", node.id)
    node_cell = _cell(node_id, "", _node_style(node), parent_id, vertex=True)
    _geometry(node_cell, _relative_box(node_box, parent_box))
    root.append(node_cell)

    visible_icon = icon_box(node_box)
    icon = result.icons[node.id]
    icon_uri = None if icon is None else _inline_icon_uri(icon.view_box, icon.body)
    icon_cell = _cell(
        _cell_id("icon", node.id),
        "",
        _icon_style(node, icon_uri),
        node_id,
        vertex=True,
    )
    _geometry(
        icon_cell,
        Box(
            visible_icon.x - node_box.x,
            visible_icon.y - node_box.y,
            visible_icon.w,
            visible_icon.h,
        ),
    )
    root.append(icon_cell)

    label_cell = _cell(
        _cell_id("label", node.id),
        node.label,
        _text_style("#1F2937", bold=True),
        node_id,
        vertex=True,
    )
    _geometry(label_cell, Box(0, ICON + 6, node_box.w, 20))
    root.append(label_cell)

    if node.sublabel:
        sublabel_cell = _cell(
            _cell_id("sublabel", node.id),
            node.sublabel,
            _text_style("#6B7280"),
            node_id,
            vertex=True,
        )
        _geometry(sublabel_cell, Box(0, ICON + 26, node_box.w, 18))
        root.append(sublabel_cell)

    if source_badges and node.sources:
        badge_cell = _cell(
            _cell_id("source-badge-node", node.id),
            f"VERIFIED SRC {len(node.sources)}",
            _text_style("#047857", bold=True),
            node_id,
            vertex=True,
        )
        _geometry(badge_cell, Box(0, node_box.h - 18, node_box.w, 14))
        root.append(badge_cell)


def _append_edge(
    root: ElementTree.Element,
    edge_index: int,
    result: RenderResult,
    *,
    source_badges: bool,
) -> None:
    routed = result.routed_edges[edge_index]
    edge = routed.edge
    semantic_id = edge.id or f"{edge.src}-to-{edge.dst}"
    edge_id = f"{_cell_id('edge', semantic_id)}-{edge_index}"
    color = EDGE_COLORS.get(edge.type, EDGE_COLORS["default"])
    dash = "dashed=1;" if edge.type == "batch" else ""
    edge_cell = _cell(
        edge_id,
        "",
        f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor={color};{dash}",
        _DEFAULT_PARENT_ID,
        edge=True,
        source=_cell_id("node", edge.src),
        target=_cell_id("node", edge.dst),
    )
    geometry = ElementTree.SubElement(
        edge_cell, "mxGeometry", {"relative": "1", "as": "geometry"}
    )
    intermediate = routed.points[1:-1]
    if intermediate:
        points = ElementTree.SubElement(geometry, "Array", {"as": "points"})
        for x, y in intermediate:
            ElementTree.SubElement(
                points, "mxPoint", {"x": _number(x), "y": _number(y)}
            )
    root.append(edge_cell)

    if edge.label:
        label_cell = _cell(
            f"{_cell_id('edge-label', semantic_id)}-{edge_index}",
            edge.label,
            _text_style(color),
            edge_id,
            vertex=True,
        )
        _geometry(label_cell, Box(0, -16, 90, 18), relative=True)
        root.append(label_cell)

    if source_badges and edge.sources:
        badge_cell = _cell(
            f"{_cell_id('source-badge-edge', semantic_id)}-{edge_index}",
            f"VERIFIED SRC {len(edge.sources)}",
            _text_style("#047857", bold=True),
            edge_id,
            vertex=True,
        )
        _geometry(badge_cell, Box(0, 4, 100, 14), relative=True)
        root.append(badge_cell)


def emit_drawio(
    spec: Spec, result: RenderResult, *, source_badges: bool = False
) -> str:
    """Project authored and computed IR into stable, self-contained mxGraph XML."""
    mxfile = ElementTree.Element(
        "mxfile", {"host": "app.diagrams.net", "type": "device"}
    )
    diagram = ElementTree.SubElement(
        mxfile, "diagram", {"id": _MXFILE_ID, "name": "Architecture Diagram"}
    )
    model = ElementTree.SubElement(
        diagram,
        "mxGraphModel",
        {
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "850",
            "pageHeight": "1100",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ElementTree.SubElement(model, "root")
    root.append(ElementTree.Element("mxCell", {"id": _ROOT_ID}))
    root.append(
        ElementTree.Element("mxCell", {"id": _DEFAULT_PARENT_ID, "parent": _ROOT_ID})
    )

    zone_by_id = {zone.id: zone for zone in spec.zones}
    for zone_id in sorted(
        result.zone_boxes,
        key=lambda value: (len(zone_ancestors(spec, value)), value),
    ):
        zone = zone_by_id[zone_id]
        parent_box = (
            result.zone_boxes.get(zone.parent) if zone.parent is not None else None
        )
        parent_id = (
            _cell_id("zone", zone.parent)
            if zone.parent is not None
            else _DEFAULT_PARENT_ID
        )
        zone_cell = _cell(
            _cell_id("zone", zone.id),
            zone.label,
            _zone_style(zone),
            parent_id,
            vertex=True,
        )
        _geometry(zone_cell, _relative_box(result.zone_boxes[zone.id], parent_box))
        root.append(zone_cell)

    for node in spec.nodes:
        _append_node(root, node, result, source_badges=source_badges)
    for edge_index in range(len(result.routed_edges)):
        _append_edge(root, edge_index, result, source_badges=source_badges)

    ElementTree.indent(mxfile, space="  ")
    xml = ElementTree.tostring(mxfile, encoding="unicode", short_empty_elements=True)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n'
