"""Deterministically compose a validated spec into editable SVG."""

from __future__ import annotations

from dataclasses import dataclass, field

from .diagnostics import (
    QUALITY_STANDARD,
    SEVERITY_ERROR,
    Diagnostic,
    apply_quality_profile,
    suppress_derived,
)
from .geometry_checks import (
    check_ambiguous_corridors,
    check_edge_through_node,
    check_label_route_clearance,
    check_layout,
    check_proper_crossings,
    check_route_rhythm,
)
from .icons import IconCacheError, IconLookup, IconRef
from .layout import (
    Box,
    assign_ranks,
    compute_positions,
    compute_zone_boxes,
    order_within_ranks,
)
from .model import Spec
from .profile import check_deployment_profile
from .routing import RoutedEdge, route_edges
from .svg import check_editability, emit_svg


@dataclass
class RenderResult:
    svg: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    node_boxes: dict[str, Box] = field(default_factory=dict)
    zone_boxes: dict[str, Box] = field(default_factory=dict)
    routed_edges: list[RoutedEdge] = field(default_factory=list)
    icons: dict[str, IconRef | None] = field(default_factory=dict)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == SEVERITY_ERROR]

    @property
    def ok(self) -> bool:
        return not self.errors


def render(
    spec: Spec,
    icon_lookup: IconLookup,
    quality: str = QUALITY_STANDARD,
    source_badges: bool = False,
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
    for node in spec.nodes:
        if not node.service:
            icons[node.id] = None
            continue
        try:
            icons[node.id] = icon_lookup(node.provider, node.service)
        except IconCacheError as exc:
            diagnostics.append(exc.diagnostic)
            icons[node.id] = None

    svg = emit_svg(
        spec,
        node_boxes,
        zone_boxes,
        routed_edges,
        icons,
        diagnostics,
        source_badges,
    )
    diagnostics += check_editability(svg)
    diagnostics = apply_quality_profile(suppress_derived(diagnostics), quality)
    return RenderResult(
        svg=svg,
        diagnostics=diagnostics,
        node_boxes=node_boxes,
        zone_boxes=zone_boxes,
        routed_edges=routed_edges,
        icons=icons,
    )
