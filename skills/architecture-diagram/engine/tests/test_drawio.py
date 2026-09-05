"""Structural tests for the deterministic draw.io projection."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path

from engine.drawio import emit_drawio
from engine.icons import IconRef
from engine.pipeline import render
from engine.spec import load_spec


def _icon_lookup(provider: str, service_slug: str) -> IconRef | None:
    del provider
    return IconRef(
        view_box="0 0 100 100",
        body=(
            '<path d="M0,0 L100,100" fill="currentColor"/>'
            f"<title>{service_slug}</title>"
        ),
    )


DRAWIO_SPEC = """
title: Editable projection
provider: generic
sources:
  - id: src-service
    revision: 0123456789abcdef0123456789abcdef01234567
    path: src/service.py
    lines: [1, 2]
zones:
  - id: outer
    label: Outer
    kind: region
  - id: inner
    label: Inner
    parent: outer
    kind: security
nodes:
  - id: public
    label: Public
    service: gateway
  - id: service
    label: Service & API
    sublabel: Private <tier>
    service: database
    zone: inner
    sources: [src-service]
edges:
  - id: egress
    from: public
    to: service
    label: HTTPS & TLS
    type: batch
    sources: [src-service]
"""


def _cells(xml: str) -> dict[str, ElementTree.Element]:
    document = ElementTree.fromstring(xml)
    assert document.tag == "mxfile"
    assert document.attrib == {"host": "app.diagrams.net", "type": "device"}
    diagram = document.find("./diagram")
    assert diagram is not None
    assert diagram.attrib == {
        "id": "architecture-diagram",
        "name": "Architecture Diagram",
    }
    root = document.find("./diagram/mxGraphModel/root")
    assert root is not None
    cells = {cell.attrib["id"]: cell for cell in root.findall("mxCell")}
    assert len(cells) == len(root.findall("mxCell"))
    return cells


def test_projects_every_editable_category_into_independent_cells() -> None:
    spec = load_spec(DRAWIO_SPEC)
    result = render(spec, _icon_lookup)

    cells = _cells(emit_drawio(spec, result))

    assert cells["zone-outer"].attrib["parent"] == "1"
    assert cells["zone-inner"].attrib["parent"] == "zone-outer"
    assert cells["node-service"].attrib["parent"] == "zone-inner"
    assert cells["icon-service"].attrib["parent"] == "node-service"
    assert cells["label-service"].attrib == {
        "id": "label-service",
        "value": "Service & API",
        "style": "text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontColor=#1F2937;",
        "parent": "node-service",
        "vertex": "1",
    }
    assert cells["sublabel-service"].attrib["value"] == "Private <tier>"
    assert cells["edge-egress-0"].attrib["parent"] == "1"
    assert cells["edge-egress-0"].attrib["source"] == "node-public"
    assert cells["edge-egress-0"].attrib["target"] == "node-service"
    assert cells["edge-label-egress-0"].attrib["parent"] == "edge-egress-0"
    assert cells["edge-label-egress-0"].attrib["value"] == "HTTPS & TLS"


def test_projected_references_are_resolvable_and_routes_are_retained() -> None:
    spec = load_spec(DRAWIO_SPEC)
    result = render(spec, _icon_lookup)
    cells = _cells(emit_drawio(spec, result))

    for cell in cells.values():
        parent = cell.attrib.get("parent")
        if parent is not None:
            assert parent in cells
        if cell.attrib.get("edge") == "1":
            assert cell.attrib["source"] in cells
            assert cell.attrib["target"] in cells

    edge_geometry = cells["edge-egress-0"].find("mxGeometry")
    assert edge_geometry is not None
    points = edge_geometry.findall("./Array[@as='points']/mxPoint")
    expected = result.routed_edges[0].points[1:-1]
    assert [
        (float(point.attrib["x"]), float(point.attrib["y"])) for point in points
    ] == list(expected)


def test_projection_is_deterministic_and_self_contained() -> None:
    spec = load_spec(DRAWIO_SPEC)
    first = render(spec, _icon_lookup)
    second = render(spec, _icon_lookup)

    first_xml = emit_drawio(spec, first)
    assert first_xml == emit_drawio(spec, second)
    assert "image=data:image/svg+xml," in first_xml
    assert "http://" not in first_xml
    assert "https://" not in first_xml
    assert "mxgraph." not in first_xml
    assert "<image" not in first_xml
    ElementTree.fromstring(first_xml)


def test_source_badges_are_local_cells_when_requested() -> None:
    spec = load_spec(DRAWIO_SPEC)
    result = render(spec, _icon_lookup, source_badges=True)

    cells = _cells(emit_drawio(spec, result, source_badges=True))

    assert cells["source-badge-node-service"].attrib["parent"] == "node-service"
    assert cells["source-badge-node-service"].attrib["value"] == "VERIFIED SRC 1"
    assert cells["source-badge-edge-egress-0"].attrib["parent"] == "edge-egress-0"
    assert cells["source-badge-edge-egress-0"].attrib["value"] == "VERIFIED SRC 1"


def test_review_fixture_is_the_current_importable_projection() -> None:
    spec_path = Path(__file__).parent / "fixtures" / "drawio-review.yaml"
    expected_path = spec_path.with_suffix(".drawio")
    spec = load_spec(spec_path.read_text())

    projected = emit_drawio(spec, render(spec, _icon_lookup))

    assert projected == expected_path.read_text()
    assert ElementTree.parse(expected_path).getroot().tag == "mxfile"
