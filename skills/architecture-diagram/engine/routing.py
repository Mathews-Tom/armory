"""Deterministic orthogonal routing with distinct visible-icon ports."""

from __future__ import annotations

from dataclasses import dataclass

from .layout import Box, icon_box
from .model import Edge, Spec

PORT_GUTTER = 16.0
PORT_MAX_SPACING = 14.0
FACING_PORT_ALIGNMENT_DELTA = 16.0
ROUTE_ENDPOINT_STUB = 24.0
ROUTE_CHANNEL_HALF_SPREAD = 16.0
ARROW_HEAD_LENGTH = 6.0
MIN_INTERIOR_ROUTE_SEGMENT = 16.0


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
