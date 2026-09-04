"""Deterministic geometry diagnostics for routed architecture diagrams."""

from __future__ import annotations

from math import hypot

from .diagnostics import Diagnostic, SEVERITY_ERROR, SEVERITY_WARNING
from .layout import Box, EDGE_LABEL_FONT_SIZE, box_evidence, text_width, zone_ancestors
from .model import Edge, Spec
from .routing import MIN_INTERIOR_ROUTE_SEGMENT, RoutedEdge

MIN_ROUTE_SEGMENT = 8.0
NODE_ROUTE_CLEARANCE = 2.0
PROPER_CROSSING_EPSILON = 1e-4
MIN_AMBIGUOUS_CORRIDOR = 8.0
LABEL_ROUTE_CLEARANCE = 4.0


def _segment_length(start: tuple[float, float], end: tuple[float, float]) -> float:
    return abs(end[0] - start[0]) + abs(end[1] - start[1])


def check_route_rhythm(routed_edges: list[RoutedEdge]) -> list[Diagnostic]:
    """Report paths whose short orthogonal runs cannot read as separate lines."""
    findings: list[Diagnostic] = []
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
            subject: dict[str, object] = {
                "from": edge.src,
                "to": edge.dst,
                "label": edge.label,
            }
            if length < MIN_ROUTE_SEGMENT:
                findings.append(
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
                findings.append(
                    Diagnostic(
                        code="composition/short-interior-segment",
                        severity=SEVERITY_WARNING,
                        message=(
                            f"edge {edge.src!r}->{edge.dst!r} interior segment {index} "
                            f"is {length:g}px; turns need at least "
                            f"{MIN_INTERIOR_ROUTE_SEGMENT:g}px"
                        ),
                        subject=subject,
                        evidence={**evidence, "minimum": MIN_INTERIOR_ROUTE_SEGMENT},
                        supported_fixes=(
                            "remove the redundant connection",
                            "split the nodes into separate ranks with an intermediate node",
                        ),
                    )
                )
    return findings


def _expanded_box(box: Box, clearance: float) -> Box:
    return Box(
        box.x - clearance,
        box.y - clearance,
        box.w + 2 * clearance,
        box.h + 2 * clearance,
    )


def _segment_intersects_box(
    start: tuple[float, float], end: tuple[float, float], box: Box
) -> bool:
    x0, y0 = start
    x1, y1 = end
    if x0 == x1:
        return box.x <= x0 <= box.x2 and max(min(y0, y1), box.y) <= min(
            max(y0, y1), box.y2
        )
    if y0 == y1:
        return box.y <= y0 <= box.y2 and max(min(x0, x1), box.x) <= min(
            max(x0, x1), box.x2
        )
    raise ValueError("route segments must be orthogonal")


def check_edge_through_node(
    node_boxes: dict[str, Box], routed_edges: list[RoutedEdge]
) -> list[Diagnostic]:
    """Detect an unrelated node that touches a route or its 2px clearance."""
    findings: list[Diagnostic] = []
    for routed in routed_edges:
        edge = routed.edge
        for node_id, node_box in node_boxes.items():
            if node_id in (edge.src, edge.dst):
                continue
            expanded = _expanded_box(node_box, NODE_ROUTE_CLEARANCE)
            for segment_index, (start, end) in enumerate(
                zip(routed.points, routed.points[1:])
            ):
                if not _segment_intersects_box(start, end, expanded):
                    continue
                findings.append(
                    Diagnostic(
                        code="composition/edge-through-node",
                        severity=SEVERITY_WARNING,
                        message=(
                            f"edge {edge.src!r}->{edge.dst!r} crosses the "
                            f"clearance around unrelated node {node_id!r}"
                        ),
                        subject={"from": edge.src, "to": edge.dst, "node": node_id},
                        evidence={
                            "segment_index": segment_index,
                            "start": list(start),
                            "end": list(end),
                            "clearance": NODE_ROUTE_CLEARANCE,
                            "node_box": box_evidence(node_box),
                        },
                        supported_fixes=(
                            "split the flow into separate ranks with an intermediate node",
                            "remove the unrelated connection",
                        ),
                    )
                )
    return findings


def _cross_product(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (
        point[0] - start[0]
    )


def _properly_crosses(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    first_a = _cross_product(first_start, first_end, second_start)
    first_b = _cross_product(first_start, first_end, second_end)
    second_a = _cross_product(second_start, second_end, first_start)
    second_b = _cross_product(second_start, second_end, first_end)
    return (
        (first_a > PROPER_CROSSING_EPSILON and first_b < -PROPER_CROSSING_EPSILON)
        or (first_a < -PROPER_CROSSING_EPSILON and first_b > PROPER_CROSSING_EPSILON)
    ) and (
        (second_a > PROPER_CROSSING_EPSILON and second_b < -PROPER_CROSSING_EPSILON)
        or (second_a < -PROPER_CROSSING_EPSILON and second_b > PROPER_CROSSING_EPSILON)
    )


def _related_edges(first: Edge, second: Edge) -> bool:
    return bool({first.src, first.dst} & {second.src, second.dst})


def check_proper_crossings(routed_edges: list[RoutedEdge]) -> list[Diagnostic]:
    """Find interior X crossings between relationships with no shared node."""
    findings: list[Diagnostic] = []
    for first_index, first in enumerate(routed_edges):
        for second in routed_edges[first_index + 1 :]:
            if _related_edges(first.edge, second.edge):
                continue
            for first_segment, (first_start, first_end) in enumerate(
                zip(first.points, first.points[1:])
            ):
                for second_segment, (second_start, second_end) in enumerate(
                    zip(second.points, second.points[1:])
                ):
                    if not _properly_crosses(
                        first_start, first_end, second_start, second_end
                    ):
                        continue
                    findings.append(
                        Diagnostic(
                            code="composition/proper-crossing",
                            severity=SEVERITY_WARNING,
                            message=(
                                f"unrelated edges {first.edge.src!r}->{first.edge.dst!r} "
                                f"and {second.edge.src!r}->{second.edge.dst!r} cross"
                            ),
                            subject={
                                "edges": [
                                    {"from": first.edge.src, "to": first.edge.dst},
                                    {"from": second.edge.src, "to": second.edge.dst},
                                ]
                            },
                            evidence={
                                "first_segment": first_segment,
                                "second_segment": second_segment,
                                "epsilon": PROPER_CROSSING_EPSILON,
                            },
                            supported_fixes=(
                                "reorder the affected nodes within their ranks",
                                "split one relationship through an intermediate node",
                            ),
                        )
                    )
    return findings


def _collinear_overlap(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> float:
    if first_start[1] == first_end[1] == second_start[1] == second_end[1]:
        return max(
            0.0,
            min(max(first_start[0], first_end[0]), max(second_start[0], second_end[0]))
            - max(
                min(first_start[0], first_end[0]), min(second_start[0], second_end[0])
            ),
        )
    if first_start[0] == first_end[0] == second_start[0] == second_end[0]:
        return max(
            0.0,
            min(max(first_start[1], first_end[1]), max(second_start[1], second_end[1]))
            - max(
                min(first_start[1], first_end[1]), min(second_start[1], second_end[1])
            ),
        )
    return 0.0


def check_ambiguous_corridors(routed_edges: list[RoutedEdge]) -> list[Diagnostic]:
    """Find long collinear overlaps between relationships with no shared node."""
    findings: list[Diagnostic] = []
    for first_index, first in enumerate(routed_edges):
        for second in routed_edges[first_index + 1 :]:
            if _related_edges(first.edge, second.edge):
                continue
            for first_segment, (first_start, first_end) in enumerate(
                zip(first.points, first.points[1:])
            ):
                for second_segment, (second_start, second_end) in enumerate(
                    zip(second.points, second.points[1:])
                ):
                    overlap = _collinear_overlap(
                        first_start, first_end, second_start, second_end
                    )
                    if overlap < MIN_AMBIGUOUS_CORRIDOR:
                        continue
                    findings.append(
                        Diagnostic(
                            code="composition/ambiguous-corridor",
                            severity=SEVERITY_WARNING,
                            message=(
                                f"unrelated edges {first.edge.src!r}->{first.edge.dst!r} "
                                f"and {second.edge.src!r}->{second.edge.dst!r} share "
                                f"{overlap:g}px of route"
                            ),
                            subject={
                                "edges": [
                                    {"from": first.edge.src, "to": first.edge.dst},
                                    {"from": second.edge.src, "to": second.edge.dst},
                                ]
                            },
                            evidence={
                                "first_segment": first_segment,
                                "second_segment": second_segment,
                                "overlap": overlap,
                                "minimum": MIN_AMBIGUOUS_CORRIDOR,
                            },
                            supported_fixes=(
                                "reorder the affected nodes within their ranks",
                                "split one relationship through an intermediate node",
                            ),
                        )
                    )
    return findings


def edge_label_box(routed: RoutedEdge) -> Box:
    """Return the text mask occupied by an emitted edge label."""
    x, baseline = routed.label_pos
    return Box(
        x,
        baseline - EDGE_LABEL_FONT_SIZE,
        text_width(routed.edge.label, EDGE_LABEL_FONT_SIZE),
        EDGE_LABEL_FONT_SIZE,
    )


def _segment_box(start: tuple[float, float], end: tuple[float, float]) -> Box:
    return Box(
        min(start[0], end[0]),
        min(start[1], end[1]),
        abs(end[0] - start[0]),
        abs(end[1] - start[1]),
    )


def _box_clearance(first: Box, second: Box) -> float:
    horizontal = max(first.x - second.x2, second.x - first.x2, 0.0)
    vertical = max(first.y - second.y2, second.y - first.y2, 0.0)
    return hypot(horizontal, vertical)


def check_label_route_clearance(routed_edges: list[RoutedEdge]) -> list[Diagnostic]:
    """Detect a label mask that sits too close to a different relationship."""
    findings: list[Diagnostic] = []
    for label_index, labeled in enumerate(routed_edges):
        if not labeled.edge.label:
            continue
        label_box = edge_label_box(labeled)
        for route_index, routed in enumerate(routed_edges):
            if route_index == label_index:
                continue
            for segment_index, (start, end) in enumerate(
                zip(routed.points, routed.points[1:])
            ):
                clearance = _box_clearance(label_box, _segment_box(start, end))
                if clearance >= LABEL_ROUTE_CLEARANCE:
                    continue
                findings.append(
                    Diagnostic(
                        code="composition/label-route-clearance",
                        severity=SEVERITY_WARNING,
                        message=(
                            f"label on edge {labeled.edge.src!r}->{labeled.edge.dst!r} "
                            f"is {clearance:g}px from route "
                            f"{routed.edge.src!r}->{routed.edge.dst!r}"
                        ),
                        subject={
                            "label_edge": {
                                "from": labeled.edge.src,
                                "to": labeled.edge.dst,
                            },
                            "route_edge": {
                                "from": routed.edge.src,
                                "to": routed.edge.dst,
                            },
                        },
                        evidence={
                            "label_box": box_evidence(label_box),
                            "route_segment": segment_index,
                            "clearance": clearance,
                            "minimum": LABEL_ROUTE_CLEARANCE,
                        },
                        supported_fixes=(
                            "reorder the affected nodes within their ranks",
                            "shorten the edge label",
                        ),
                    )
                )
    return findings


def check_layout(
    spec: Spec, node_boxes: dict[str, Box], zone_boxes: dict[str, Box]
) -> list[Diagnostic]:
    """Report node and non-nested zone overlaps."""
    findings: list[Diagnostic] = []
    node_ids = list(node_boxes)
    for index, first_id in enumerate(node_ids):
        for second_id in node_ids[index + 1 :]:
            if node_boxes[first_id].overlaps(node_boxes[second_id]):
                findings.append(
                    Diagnostic(
                        code="layout/node-overlap",
                        severity=SEVERITY_ERROR,
                        message=f"node overlap: {first_id!r} and {second_id!r}",
                        subject={"nodes": [first_id, second_id]},
                        evidence={
                            first_id: box_evidence(node_boxes[first_id]),
                            second_id: box_evidence(node_boxes[second_id]),
                        },
                        supported_fixes=(
                            "split the two nodes across different ranks by adding an edge between them",
                            "remove one of the duplicated nodes",
                        ),
                    )
                )
    zone_ids = list(zone_boxes)
    for index, first_id in enumerate(zone_ids):
        for second_id in zone_ids[index + 1 :]:
            first_ancestors = zone_ancestors(spec, first_id)
            if second_id in first_ancestors or first_id in zone_ancestors(
                spec, second_id
            ):
                continue
            if zone_boxes[first_id].overlaps(zone_boxes[second_id]):
                findings.append(
                    Diagnostic(
                        code="layout/zone-overlap",
                        severity=SEVERITY_ERROR,
                        message=f"zone overlap: {first_id!r} and {second_id!r}",
                        subject={"zones": [first_id, second_id]},
                        evidence={
                            first_id: box_evidence(zone_boxes[first_id]),
                            second_id: box_evidence(zone_boxes[second_id]),
                        },
                        supported_fixes=(
                            "list each zone's member nodes contiguously in `nodes`",
                            "correct the `zone` field on the interleaved nodes",
                            "nest one zone inside the other via `parent` if containment was intended",
                        ),
                    )
                )
    return findings
