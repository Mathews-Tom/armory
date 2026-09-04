"""Tests for render.py — spec parsing, layout, routing, and SVG emission."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import render
from render import (
    COL_GAP,
    ICON,
    ROW_GAP,
    Box,
    Edge,
    IconRef,
    Node,
    RoutedEdge,
    Spec,
    SpecError,
    assign_ranks,
    check_editability,
    check_layout,
    check_edge_through_node,
    check_ambiguous_corridors,
    check_label_route_clearance,
    check_route_rhythm,
    check_proper_crossings,
    compute_positions,
    compute_zone_boxes,
    icon_box,
    load_spec,
    order_within_ranks,
    route_edges,
)
from render import (
    render as do_render,
)


def _icon_lookup(provider: str, service: str) -> IconRef | None:
    if service == "missing":
        return None
    return IconRef(
        view_box="0 0 100 100", body='<path d="M0,0 L100,100" fill="currentColor"/>'
    )


LINEAR_SPEC = """
title: Linear Flow
provider: aws
nodes:
  - id: a
    label: A
    service: svc-a
  - id: b
    label: B
    service: svc-b
  - id: c
    label: C
    service: svc-c
edges:
  - from: a
    to: b
  - from: b
    to: c
"""

ZONED_SPEC = """
title: Zoned
provider: aws
zones:
  - id: vpc
    label: VPC
nodes:
  - id: outside
    label: Outside
    service: svc
  - id: inside1
    label: Inside 1
    service: svc
    zone: vpc
  - id: inside2
    label: Inside 2
    service: svc
    zone: vpc
edges:
  - from: outside
    to: inside1
"""


class TestLoadSpec:
    def test_parses_minimal_spec(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        assert spec.title == "Linear Flow"
        assert spec.direction == "LR"
        assert len(spec.nodes) == 3
        assert len(spec.edges) == 2

    def test_defaults_direction_to_lr(self) -> None:
        spec = load_spec("nodes:\n  - id: a\n")
        assert spec.direction == "LR"

    def test_direction_case_insensitive(self) -> None:
        spec = load_spec("direction: tb\nnodes:\n  - id: a\n")
        assert spec.direction == "TB"

    def test_no_nodes_raises(self) -> None:
        with pytest.raises(SpecError, match="no nodes"):
            load_spec("title: empty\n")

    def test_duplicate_node_id_raises(self) -> None:
        with pytest.raises(SpecError, match="duplicate"):
            load_spec("nodes:\n  - id: a\n  - id: a\n")

    def test_node_missing_id_raises(self) -> None:
        with pytest.raises(SpecError, match="missing id"):
            load_spec("nodes:\n  - label: no id\n")

    def test_edge_to_unknown_node_raises(self) -> None:
        with pytest.raises(SpecError, match="unknown node"):
            load_spec("nodes:\n  - id: a\nedges:\n  - from: a\n    to: ghost\n")

    def test_node_zone_reference_unknown_raises(self) -> None:
        with pytest.raises(SpecError, match="unknown zone"):
            load_spec("nodes:\n  - id: a\n    zone: ghost\n")

    def test_zone_parent_unknown_raises(self) -> None:
        spec_text = (
            "zones:\n  - id: z1\n    parent: ghost\nnodes:\n  - id: a\n    zone: z1\n"
        )
        with pytest.raises(SpecError, match="unknown parent"):
            load_spec(spec_text)

    def test_zone_self_parent_raises(self) -> None:
        spec_text = (
            "zones:\n  - id: z1\n    parent: z1\nnodes:\n  - id: a\n    zone: z1\n"
        )
        with pytest.raises(SpecError, match="own parent"):
            load_spec(spec_text)

    def test_label_defaults_to_id(self) -> None:
        spec = load_spec("nodes:\n  - id: my-node\n")
        assert spec.nodes[0].label == "my-node"

    def test_edge_type_defaults(self) -> None:
        spec = load_spec(
            "nodes:\n  - id: a\n  - id: b\nedges:\n  - from: a\n    to: b\n"
        )
        assert spec.edges[0].type == "default"


class TestRanking:
    def test_linear_chain_gets_increasing_ranks(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        rank = assign_ranks(spec)
        assert rank["a"] == 0
        assert rank["b"] == 1
        assert rank["c"] == 2

    def test_disconnected_node_stays_at_rank_zero(self) -> None:
        spec = load_spec("nodes:\n  - id: a\n  - id: b\n")
        rank = assign_ranks(spec)
        assert rank == {"a": 0, "b": 0}

    def test_fan_out_shares_source_rank_plus_one(self) -> None:
        spec_text = "nodes:\n  - id: a\n  - id: b\n  - id: c\nedges:\n  - from: a\n    to: b\n  - from: a\n    to: c\n"
        spec = load_spec(spec_text)
        rank = assign_ranks(spec)
        assert rank["a"] == 0
        assert rank["b"] == 1
        assert rank["c"] == 1

    def test_cycle_does_not_hang_and_terminates(self) -> None:
        spec_text = "nodes:\n  - id: a\n  - id: b\nedges:\n  - from: a\n    to: b\n  - from: b\n    to: a\n"
        spec = load_spec(spec_text)
        rank = assign_ranks(spec)  # must return, not loop forever
        assert set(rank) == {"a", "b"}

    def test_longest_path_wins_over_shorter_path(self) -> None:
        # a->c direct (rank 1) and a->b->c (rank 2) — c must take the longer path's rank
        spec_text = (
            "nodes:\n  - id: a\n  - id: b\n  - id: c\n"
            "edges:\n  - from: a\n    to: b\n  - from: b\n    to: c\n  - from: a\n    to: c\n"
        )
        spec = load_spec(spec_text)
        rank = assign_ranks(spec)
        assert rank["c"] == 2


class TestOrdering:
    def test_single_rank_gets_sequential_orders(self) -> None:
        spec = load_spec("nodes:\n  - id: a\n  - id: b\n  - id: c\n")
        rank = assign_ranks(spec)
        order = order_within_ranks(spec, rank)
        assert sorted(order.values()) == [0, 1, 2]

    def test_deterministic_across_runs(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        rank = assign_ranks(spec)
        o1 = order_within_ranks(spec, rank)
        o2 = order_within_ranks(spec, rank)
        assert o1 == o2


class TestPositions:
    def test_lr_increases_x_with_rank(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        rank = assign_ranks(spec)
        order = order_within_ranks(spec, rank)
        boxes = compute_positions(spec, rank, order)
        assert boxes["a"].x < boxes["b"].x < boxes["c"].x

    def test_tb_increases_y_with_rank(self) -> None:
        spec = load_spec(
            LINEAR_SPEC.replace("provider: aws", "provider: aws\ndirection: TB")
        )
        rank = assign_ranks(spec)
        order = order_within_ranks(spec, rank)
        boxes = compute_positions(spec, rank, order)
        assert boxes["a"].y < boxes["b"].y < boxes["c"].y

    def test_no_two_nodes_overlap_in_a_fan_out(self) -> None:
        spec_text = "nodes:\n  - id: a\n  - id: b\n  - id: c\n  - id: d\nedges:\n  - from: a\n    to: b\n  - from: a\n    to: c\n  - from: a\n    to: d\n"
        spec = load_spec(spec_text)
        rank = assign_ranks(spec)
        order = order_within_ranks(spec, rank)
        boxes = compute_positions(spec, rank, order)
        assert check_layout(spec, boxes, {}) == []


class TestZoneBoxes:
    def test_zone_bbox_contains_all_members(self) -> None:
        spec = load_spec(ZONED_SPEC)
        rank = assign_ranks(spec)
        order = order_within_ranks(spec, rank)
        node_boxes = compute_positions(spec, rank, order)
        zone_boxes = compute_zone_boxes(spec, node_boxes)
        vpc = zone_boxes["vpc"]
        for nid in ("inside1", "inside2"):
            b = node_boxes[nid]
            assert vpc.x <= b.x and b.x2 <= vpc.x2
            assert vpc.y <= b.y and b.y2 <= vpc.y2

    def test_empty_zone_raises(self) -> None:
        spec = load_spec("zones:\n  - id: z\nnodes:\n  - id: a\n")
        rank = assign_ranks(spec)
        order = order_within_ranks(spec, rank)
        node_boxes = compute_positions(spec, rank, order)
        with pytest.raises(SpecError, match="no member nodes"):
            compute_zone_boxes(spec, node_boxes)

    def test_nested_zone_bbox_contains_child_zone(self) -> None:
        spec_text = (
            "zones:\n  - id: outer\n  - id: inner\n    parent: outer\n"
            "nodes:\n  - id: a\n    zone: inner\n"
        )
        spec = load_spec(spec_text)
        rank = assign_ranks(spec)
        order = order_within_ranks(spec, rank)
        node_boxes = compute_positions(spec, rank, order)
        zone_boxes = compute_zone_boxes(spec, node_boxes)
        outer, inner = zone_boxes["outer"], zone_boxes["inner"]
        assert outer.x <= inner.x and inner.x2 <= outer.x2
        assert outer.y <= inner.y and inner.y2 <= outer.y2


class TestBox:
    def test_overlap_detection(self) -> None:
        a = Box(0, 0, 10, 10)
        b = Box(5, 5, 10, 10)
        c = Box(20, 20, 10, 10)
        assert a.overlaps(b)
        assert not a.overlaps(c)

    def test_touching_edges_do_not_overlap(self) -> None:
        a = Box(0, 0, 10, 10)
        b = Box(10, 0, 10, 10)
        assert not a.overlaps(b)


class TestRouting:
    def test_same_rank_edge_is_straight(self) -> None:
        boxes = {"a": Box(0, 0, 120, 118), "b": Box(200, 0, 120, 118)}
        spec2 = Spec(
            title="",
            direction="LR",
            provider="generic",
            nodes=[Node("a", "A"), Node("b", "B")],
            zones=[],
            edges=[Edge("a", "b")],
        )
        routed = route_edges(spec2, boxes)
        assert routed[0].path_d.count("L") == 1  # one segment, no bend

    def test_different_rank_edge_has_one_bend(self) -> None:
        boxes = {"a": Box(0, 0, 120, 118), "b": Box(200, 200, 120, 118)}
        spec2 = Spec(
            title="",
            direction="LR",
            provider="generic",
            nodes=[Node("a", "A"), Node("b", "B")],
            zones=[],
            edges=[Edge("a", "b")],
        )
        routed = route_edges(spec2, boxes)
        assert routed[0].path_d.count("L") == 3  # exactly one bend: 3 segments

    def test_parallel_edges_get_offset_lanes(self) -> None:
        boxes = {
            "a": Box(0, 0, 120, 118),
            "b": Box(200, 200, 120, 118),
            "c": Box(0, 400, 120, 118),
            "d": Box(200, 600, 120, 118),
        }
        spec2 = Spec(
            title="",
            direction="LR",
            provider="generic",
            nodes=[Node("a", "A"), Node("b", "B"), Node("c", "C"), Node("d", "D")],
            zones=[],
            edges=[Edge("a", "b"), Edge("c", "d")],
        )
        routed = route_edges(spec2, boxes)
        assert routed[0].path_d != routed[1].path_d

    def test_dense_fan_out_corridor_stays_within_the_gap_tb(self) -> None:
        """Regression test for a real bug found while showcasing the tool:
        one TB source fanning out to 4 same-rank targets pushed the 3rd/4th
        parallel lane offset past ROW_GAP, drawing those horizontal jog
        segments through the target row's node bodies instead of the gap
        above them (verified visually — the 'query'/'fetch secrets' labels
        rendered on top of unrelated icons). Every corridor's horizontal
        segment must sit strictly above the target row's top edge."""
        source = Box(1000, 0, 120, 118)  # deliberately x-misaligned with every target
        targets = {
            "b": Box(0, ROW_GAP + 118, 120, 118),
            "c": Box(140, ROW_GAP + 118, 120, 118),
            "d": Box(280, ROW_GAP + 118, 120, 118),
            "e": Box(420, ROW_GAP + 118, 120, 118),
        }
        boxes = {"a": source, **targets}
        spec2 = Spec(
            title="",
            direction="TB",
            provider="generic",
            nodes=[Node("a", "A"), *(Node(k, k.upper()) for k in targets)],
            zones=[],
            edges=[Edge("a", k) for k in targets],
        )
        routed = route_edges(spec2, boxes)
        target_row_top = min(b.y for b in targets.values())
        for r in routed:
            points = [
                tuple(float(v) for v in tok.split(","))
                for tok in r.path_d.replace("M", "L").split("L")
                if tok.strip()
            ]
            assert len(points) == 4, f"expected a bent 4-point path, got {r.path_d}"
            corridor_y = points[1][1]  # the horizontal jog's height
            assert corridor_y < target_row_top, (
                f"edge {r.edge.src}->{r.edge.dst} corridor (y={corridor_y}) reaches into the "
                f"target row (top={target_row_top}): {r.path_d}"
            )

    def test_dense_fan_out_corridor_stays_within_the_gap_lr(self) -> None:
        """Same regression, LR direction: corridor x-offsets must sit
        strictly left of the target column."""
        source = Box(0, 1000, 120, 118)  # deliberately y-misaligned with every target
        targets = {
            k: Box(COL_GAP + 120, i * 140, 120, 118)
            for i, k in enumerate("bcdefghi")  # 8 targets: guarantees overflow
        }  # against COL_GAP even under the old unclamped-lane-offset formula
        boxes = {"a": source, **targets}
        spec2 = Spec(
            title="",
            direction="LR",
            provider="generic",
            nodes=[Node("a", "A"), *(Node(k, k.upper()) for k in targets)],
            zones=[],
            edges=[Edge("a", k) for k in targets],
        )
        routed = route_edges(spec2, boxes)
        target_col_left = min(b.x for b in targets.values())
        for r in routed:
            points = [
                tuple(float(v) for v in tok.split(","))
                for tok in r.path_d.replace("M", "L").split("L")
                if tok.strip()
            ]
            assert len(points) == 4, f"expected a bent 4-point path, got {r.path_d}"
            corridor_x = points[1][0]  # the vertical jog's position
            assert corridor_x < target_col_left, (
                f"edge {r.edge.src}->{r.edge.dst} corridor (x={corridor_x}) reaches into the "
                f"target column (left={target_col_left}): {r.path_d}"
            )

    def test_lr_edge_anchors_at_icon_vertical_center_not_full_box_center(
        self,
    ) -> None:
        """Regression test for a real bug found while building showcase
        diagrams: the icon is drawn 64x64 flush against the top of its
        wider 120x118 node box (icon + two label lines below it), but
        route_edges anchored on the *full* box's vertical center
        (box.y + box.h/2), which sits 27px below the icon's true center —
        on the icon's bottom edge, not through its middle. Edges must
        anchor on the icon's own center, derived via `icon_box`."""
        boxes = {"a": Box(0, 0, 120, 118), "b": Box(200, 0, 120, 118)}
        spec2 = Spec(
            title="",
            direction="LR",
            provider="generic",
            nodes=[Node("a", "A"), Node("b", "B")],
            zones=[],
            edges=[Edge("a", "b")],
        )
        routed = route_edges(spec2, boxes)
        expected_y = icon_box(boxes["a"]).y + ICON / 2
        assert expected_y == icon_box(boxes["b"]).y + ICON / 2
        for tok in routed[0].path_d.replace("M", "L").split("L"):
            if not tok.strip():
                continue
            y = float(tok.split(",")[1])
            assert y == pytest.approx(expected_y), (
                f"edge should ride through the icon's vertical center "
                f"({expected_y}), not the full box's ({boxes['a'].y + boxes['a'].h / 2}): {routed[0].path_d}"
            )

    def test_tb_edge_anchors_at_icon_horizontal_center_not_full_box_center(
        self,
    ) -> None:
        """TB counterpart: the icon is horizontally centered within the
        wider node box (to match its centered label), so edges must anchor
        on that centered x, which happens to coincide with the full box's
        center too — assert route_edges uses `icon_box`'s x, confirming
        the LR/TB anchor logic is symmetric on the axis each direction
        actually needs to get right."""
        boxes = {"a": Box(0, 0, 120, 118), "b": Box(0, 200, 120, 118)}
        spec2 = Spec(
            title="",
            direction="TB",
            provider="generic",
            nodes=[Node("a", "A"), Node("b", "B")],
            zones=[],
            edges=[Edge("a", "b")],
        )
        routed = route_edges(spec2, boxes)
        expected_x = icon_box(boxes["a"]).x + ICON / 2
        for tok in routed[0].path_d.replace("M", "L").split("L"):
            if not tok.strip():
                continue
            x = float(tok.split(",")[0])
            assert x == pytest.approx(expected_x)

    def test_five_way_fan_out_uses_distinct_spaced_source_ports(self) -> None:
        boxes = {
            "a": Box(0, 0, 120, 118),
            **{
                node_id: Box(240, index * 140, 120, 118)
                for index, node_id in enumerate("bcdef")
            },
        }
        spec2 = Spec(
            title="",
            direction="LR",
            provider="generic",
            nodes=[
                Node("a", "A"),
                *(Node(node_id, node_id.upper()) for node_id in "bcdef"),
            ],
            zones=[],
            edges=[Edge("a", node_id) for node_id in "bcdef"],
        )

        routed = route_edges(spec2, boxes)

        starts = [route.points[0] for route in routed]
        assert len(set(starts)) == 5
        assert sorted(y for _, y in starts) == [16, 24, 32, 40, 48]

    def test_facing_lone_ports_remerge_into_a_straight_hop(self) -> None:
        boxes = {"a": Box(0, 0, 120, 118), "b": Box(200, 8, 120, 118)}
        spec2 = Spec(
            title="",
            direction="LR",
            provider="generic",
            nodes=[Node("a", "A"), Node("b", "B")],
            zones=[],
            edges=[Edge("a", "b")],
        )

        route = route_edges(spec2, boxes)[0]

        assert route.points == ((92, 36), (222, 36))

    def test_small_shared_port_delta_uses_a_rhythm_bridge(self) -> None:
        boxes = {
            "a": Box(0, 0, 120, 118),
            "b": Box(200, 7.5, 120, 118),
            "c": Box(200, 200, 120, 118),
        }
        spec2 = Spec(
            title="",
            direction="LR",
            provider="generic",
            nodes=[Node("a", "A"), Node("b", "B"), Node("c", "C")],
            zones=[],
            edges=[Edge("a", "b"), Edge("a", "c")],
        )

        route = route_edges(spec2, boxes)[0]

        assert len(route.points) == 6
        assert check_route_rhythm([route]) == []

    def test_same_spec_renders_byte_identically_across_runs(self) -> None:
        spec = load_spec(
            "nodes:\n  - id: a\n  - id: b\n  - id: c\n"
            "edges:\n  - from: a\n    to: b\n  - from: a\n    to: c\n"
        )

        first = do_render(spec, _icon_lookup)
        second = do_render(spec, _icon_lookup)

        assert first.svg == second.svg


class TestEdgeThroughNode:
    def _route(self) -> RoutedEdge:
        return RoutedEdge(
            edge=Edge("a", "b"),
            points=((0, 10), (40, 10)),
            label_pos=(0, 0),
        )

    def test_reports_unrelated_node_within_clearance(self) -> None:
        node_boxes = {
            "a": Box(-10, 0, 10, 20),
            "b": Box(40, 0, 10, 20),
            "c": Box(15, 5, 10, 10),
        }

        findings = check_edge_through_node(node_boxes, [self._route()])

        assert [d.code for d in findings] == ["composition/edge-through-node"]
        assert findings[0].subject == {"from": "a", "to": "b", "node": "c"}

    def test_clearance_boundary_and_endpoint_exemption(self) -> None:
        route = self._route()
        at_clearance = {
            "a": Box(-10, 0, 10, 20),
            "b": Box(40, 0, 10, 20),
            "c": Box(15, 12, 10, 10),
        }
        beyond_clearance = {
            "a": Box(-10, 0, 10, 20),
            "b": Box(40, 0, 10, 20),
            "c": Box(15, 12.01, 10, 10),
        }

        assert [d.code for d in check_edge_through_node(at_clearance, [route])] == [
            "composition/edge-through-node"
        ]
        assert check_edge_through_node(beyond_clearance, [route]) == []

    def test_quality_profiles_change_edge_through_node_severity(self) -> None:
        node_boxes = {
            "a": Box(-10, 0, 10, 20),
            "b": Box(40, 0, 10, 20),
            "c": Box(15, 5, 10, 10),
        }
        findings = check_edge_through_node(node_boxes, [self._route()])

        standard = render.apply_quality_profile(findings, "standard")
        showcase = render.apply_quality_profile(findings, "showcase")

        assert [d.severity for d in standard] == ["warning"]
        assert [d.severity for d in showcase] == ["error"]


class TestProperCrossing:
    def _crossing_routes(self) -> list[RoutedEdge]:
        return [
            RoutedEdge(Edge("a", "b"), ((0, 0), (20, 0)), (0, 0)),
            RoutedEdge(Edge("c", "d"), ((10, -10), (10, 10)), (0, 0)),
        ]

    def test_reports_interior_crossing_between_unrelated_edges(self) -> None:
        findings = check_proper_crossings(self._crossing_routes())

        assert [d.code for d in findings] == ["composition/proper-crossing"]
        assert findings[0].subject["edges"] == [
            {"from": "a", "to": "b"},
            {"from": "c", "to": "d"},
        ]

    def test_shared_endpoint_and_touch_are_exempt(self) -> None:
        shared_endpoint = [
            RoutedEdge(Edge("a", "b"), ((0, 0), (20, 0)), (0, 0)),
            RoutedEdge(Edge("b", "c"), ((20, -10), (20, 10)), (0, 0)),
        ]
        endpoint_touch = [
            RoutedEdge(Edge("a", "b"), ((0, 0), (20, 0)), (0, 0)),
            RoutedEdge(Edge("c", "d"), ((20, -10), (20, 10)), (0, 0)),
        ]

        assert check_proper_crossings(shared_endpoint) == []
        assert check_proper_crossings(endpoint_touch) == []

    def test_quality_profiles_change_crossing_severity(self) -> None:
        findings = check_proper_crossings(self._crossing_routes())

        standard = render.apply_quality_profile(findings, "standard")
        showcase = render.apply_quality_profile(findings, "showcase")

        assert [d.severity for d in standard] == ["warning"]
        assert [d.severity for d in showcase] == ["error"]


class TestAmbiguousCorridor:
    def _routes(self, second_start: float) -> list[RoutedEdge]:
        return [
            RoutedEdge(Edge("a", "b"), ((0, 0), (20, 0)), (0, 0)),
            RoutedEdge(Edge("c", "d"), ((second_start, 0), (30, 0)), (0, 0)),
        ]

    def test_reports_collinear_overlap_at_threshold(self) -> None:
        findings = check_ambiguous_corridors(self._routes(12))

        assert [d.code for d in findings] == ["composition/ambiguous-corridor"]
        assert findings[0].evidence["overlap"] == 8

    def test_shorter_overlap_and_shared_endpoint_are_exempt(self) -> None:
        shared_endpoint = [
            RoutedEdge(Edge("a", "b"), ((0, 0), (20, 0)), (0, 0)),
            RoutedEdge(Edge("b", "c"), ((12, 0), (30, 0)), (0, 0)),
        ]

        assert check_ambiguous_corridors(self._routes(12.01)) == []
        assert check_ambiguous_corridors(shared_endpoint) == []

    def test_quality_profiles_change_corridor_severity(self) -> None:
        findings = check_ambiguous_corridors(self._routes(12))

        standard = render.apply_quality_profile(findings, "standard")
        showcase = render.apply_quality_profile(findings, "showcase")

        assert [d.severity for d in standard] == ["warning"]
        assert [d.severity for d in showcase] == ["error"]


class TestLabelRouteClearance:
    def _routes(self, route_y: float) -> list[RoutedEdge]:
        return [
            RoutedEdge(Edge("a", "b", label="X"), ((0, 0), (20, 0)), (0, 10)),
            RoutedEdge(Edge("c", "d"), ((0, route_y), (20, route_y)), (0, 0)),
        ]

    def test_reports_other_route_inside_label_clearance(self) -> None:
        findings = check_label_route_clearance(self._routes(13.99))

        assert [d.code for d in findings] == ["composition/label-route-clearance"]
        assert findings[0].subject["label_edge"] == {"from": "a", "to": "b"}
        assert findings[0].subject["route_edge"] == {"from": "c", "to": "d"}

    def test_clearance_boundary_and_own_route_are_exempt(self) -> None:
        own_label_only = [
            RoutedEdge(Edge("a", "b", label="X"), ((0, 0), (20, 0)), (0, 10))
        ]

        assert check_label_route_clearance(self._routes(14)) == []
        assert check_label_route_clearance(own_label_only) == []

    def test_quality_profiles_change_label_clearance_severity(self) -> None:
        findings = check_label_route_clearance(self._routes(13.99))

        standard = render.apply_quality_profile(findings, "standard")
        showcase = render.apply_quality_profile(findings, "showcase")

        assert [d.severity for d in standard] == ["warning"]
        assert [d.severity for d in showcase] == ["error"]


class TestEditabilityCheck:
    def test_clean_svg_has_no_violations(self) -> None:
        svg = '<svg><g><rect fill="#fff"/><text>hi</text></g></svg>'
        assert check_editability(svg) == []

    def test_detects_raster_image(self) -> None:
        svg = '<svg><image href="data:image/png;base64,abc"/></svg>'
        codes = [d.code for d in check_editability(svg)]
        assert codes == ["editability/forbidden-markup"] * 2

    def test_detects_use_clone(self) -> None:
        svg = '<svg><defs><symbol id="x"/></defs><use href="#x"/></svg>'
        found = check_editability(svg)
        assert [d.code for d in found] == ["editability/forbidden-markup"]
        assert found[0].evidence["marker"] == "<use "

    def test_detects_external_href(self) -> None:
        svg = '<svg><a href="http://example.com/icon.svg"/></svg>'
        found = check_editability(svg)
        assert [d.code for d in found] == ["editability/external-reference"]
        assert all(d.severity == "error" for d in found)


class TestEndToEndRender:
    def test_linear_spec_renders_clean_svg(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        result = do_render(spec, _icon_lookup)
        assert result.svg.startswith("<svg")
        assert result.svg.endswith("</svg>")
        assert check_editability(result.svg) == []

    def test_every_node_has_real_text_label(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        result = do_render(spec, _icon_lookup)
        for label in ("A", "B", "C"):
            assert f">{label}<" in result.svg

    def test_missing_icon_falls_back_without_crashing_and_reports(self) -> None:
        spec_text = "nodes:\n  - id: a\n    label: A\n    service: missing\n"
        spec = load_spec(spec_text)
        result = do_render(spec, _icon_lookup)
        found = [d for d in result.diagnostics if d.code == "icon/not-found"]
        assert [d.subject["node"] for d in found] == ["a"]
        assert found[0].severity == "error"
        assert not result.ok
        assert result.svg.startswith("<svg")

    def test_node_without_service_renders_placeholder_without_diagnostic(self) -> None:
        spec = load_spec("nodes:\n  - id: a\n    label: A\n")
        result = do_render(spec, _icon_lookup)
        assert result.diagnostics == []
        assert result.ok

    def test_zoned_spec_renders_zone_rect(self) -> None:
        spec = load_spec(ZONED_SPEC)
        result = do_render(spec, _icon_lookup)
        assert 'id="zone-vpc"' in result.svg
        assert "VPC" in result.svg

    def test_legend_appears_only_with_multiple_edge_types(self) -> None:
        spec_text = "nodes:\n  - id: a\n  - id: b\n  - id: c\nedges:\n  - from: a\n    to: b\n    type: realtime\n  - from: b\n    to: c\n    type: batch\n"
        spec = load_spec(spec_text)
        result = do_render(spec, _icon_lookup)
        assert 'id="legend"' in result.svg

    def test_no_legend_with_single_edge_type(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        result = do_render(spec, _icon_lookup)
        assert 'id="legend"' not in result.svg

    def test_icon_body_is_inlined_not_referenced(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        result = do_render(spec, _icon_lookup)
        assert (
            result.svg.count('d="M0,0 L100,100"') == 3
        )  # once per node, inlined each time

    def test_edge_labels_render_as_real_text(self) -> None:
        spec_text = "nodes:\n  - id: a\n  - id: b\nedges:\n  - from: a\n    to: b\n    label: HTTPS\n"
        spec = load_spec(spec_text)
        result = do_render(spec, _icon_lookup)
        assert ">HTTPS<" in result.svg

    def test_dashed_batch_edges_get_dasharray(self) -> None:
        spec_text = "nodes:\n  - id: a\n  - id: b\nedges:\n  - from: a\n    to: b\n    type: batch\n"
        spec = load_spec(spec_text)
        result = do_render(spec, _icon_lookup)
        assert "stroke-dasharray" in result.svg

    def test_unfittable_label_blocks_rendering(self) -> None:
        spec_text = (
            'nodes:\n  - id: a\n    label: "This Is A Genuinely Very Long Label Text"\n'
        )
        spec = load_spec(spec_text)
        result = do_render(spec, _icon_lookup, quality="showcase")

        found = [d for d in result.diagnostics if d.code == "layout/label-overflow"]

        assert [d.subject for d in found] == [{"node": "a", "field": "label"}]
        assert found[0].severity == "error"
        assert not result.ok

    def test_long_label_shrinks_inside_its_node_box(self) -> None:
        label = "XXXXXXXXXXXXXXXXXXXX"
        spec = load_spec(f'nodes:\n  - id: a\n    label: "{label}"\n')
        result = do_render(spec, _icon_lookup)
        font_match = re.search(
            rf'<text x="[^"]+" y="[^"]+" font-size="([\d.]+)" font-weight="600" '
            rf'text-anchor="middle" fill="#1F2937">{label}</text>',
            result.svg,
        )

        assert font_match
        fitted_size = float(font_match.group(1))
        assert 6 <= fitted_size < 12
        assert render._text_width(label, fitted_size) <= render.NODE_W - 8 + 1e-6
        assert result.ok

    def test_svg_has_valid_viewbox_matching_dimensions(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        result = do_render(spec, _icon_lookup)
        width_m = re.search(r'width="([\d.]+)"', result.svg)
        vb_m = re.search(r'viewBox="0 0 ([\d.]+) ', result.svg)
        assert width_m and vb_m
        assert float(width_m.group(1)) == pytest.approx(float(vb_m.group(1)))

    def test_node_icon_and_label_share_the_same_horizontal_center(self) -> None:
        """Regression test for a real bug found while showcasing the
        tool: the icon rect was drawn flush at the node box's left edge
        while the label text centered on the full (wider) box, so every
        label rendered ~28px right of its own icon. Extract the icon
        rect's true center and the label's x from real SVG output — not
        just internal layout structs — to catch this even if a future
        change reintroduces the mismatch through a different code path."""
        spec = load_spec("nodes:\n  - id: a\n    label: A\n")
        result = do_render(spec, _icon_lookup)
        rect_m = re.search(
            r'<rect x="([\d.]+)" y="([\d.]+)" width="64" height="64" rx="10"',
            result.svg,
        )
        label_m = re.search(
            r'<text x="([\d.]+)"[^>]*font-weight="600"[^>]*>A<', result.svg
        )
        assert rect_m and label_m
        icon_center_x = float(rect_m.group(1)) + 32
        label_x = float(label_m.group(1))
        assert label_x == pytest.approx(icon_center_x)


class TestZoneOverlapAssertion:
    def test_sibling_zones_scattered_across_columns_are_flagged(self) -> None:
        # a,c in zone1; b,d in zone2 but interleaved in rank/order so the
        # zone bboxes end up overlapping — this must be caught, not silently shipped.
        spec_text = (
            "zones:\n  - id: z1\n  - id: z2\n"
            "nodes:\n"
            "  - id: a\n    zone: z1\n"
            "  - id: b\n    zone: z2\n"
            "  - id: c\n    zone: z1\n"
            "  - id: d\n    zone: z2\n"
            "edges:\n"
            "  - from: a\n    to: b\n"
            "  - from: b\n    to: c\n"
            "  - from: c\n    to: d\n"
        )
        spec = load_spec(spec_text)
        rank = assign_ranks(spec)
        order = order_within_ranks(spec, rank)
        node_boxes = compute_positions(spec, rank, order)
        zone_boxes = compute_zone_boxes(spec, node_boxes)
        found = check_layout(spec, node_boxes, zone_boxes)
        assert [d.code for d in found] == ["layout/zone-overlap"]
        assert sorted(found[0].subject["zones"]) == ["z1", "z2"]
        assert found[0].severity == "error"


class TestRealIconCacheIntegration:
    def test_cache_icon_lookup_reads_real_fixture_style_entry(
        self, tmp_path: object
    ) -> None:
        cache_dir = Path(str(tmp_path))
        sha = "deadbeef"
        provider_dir = cache_dir / sha / "aws"
        provider_dir.mkdir(parents=True)
        (provider_dir / "lambda.json").write_text(
            json.dumps(
                {
                    "viewBox": "0 0 54 56",
                    "body": "<path/>",
                    "name": "lambda",
                    "slug": "lambda",
                    "source": "x",
                    "warnings": [],
                }
            )
        )
        lookup = render.CacheIconLookup(cache_dir=cache_dir, sha=sha)
        icon = lookup("aws", "lambda")
        assert icon is not None
        assert icon.view_box == "0 0 54 56"

    def test_cache_miss_returns_none(self, tmp_path: object) -> None:
        lookup = render.CacheIconLookup(cache_dir=Path(str(tmp_path)), sha="deadbeef")
        assert lookup("aws", "does-not-exist") is None


class TestBundledGenericIconLookup:
    def test_resolves_a_real_catalog_entry(self) -> None:
        lookup = render.BundledGenericIconLookup()
        icon = lookup("generic", "database")
        assert icon is not None
        assert icon.view_box == "0 0 64 64"
        assert "<" in icon.body

    def test_ignores_non_generic_provider(self) -> None:
        lookup = render.BundledGenericIconLookup()
        assert lookup("aws", "database") is None

    def test_unknown_slug_returns_none(self) -> None:
        lookup = render.BundledGenericIconLookup()
        assert lookup("generic", "not-a-real-icon") is None

    def test_every_documented_slug_in_icons_generic_md_resolves(self) -> None:
        """references/icons-generic.md documents a `service: <slug>` line per
        icon for the agent to copy. If that slug doesn't actually resolve,
        the documentation is lying — this is the same class of drift
        test_service_maps.py guards against for the cloud provider tables."""

        doc = (
            Path(__file__).parent.parent / "references" / "icons-generic.md"
        ).read_text()
        slugs = re.findall(r"`service: ([a-z0-9-]+)`", doc)
        assert len(slugs) >= 20
        lookup = render.BundledGenericIconLookup()
        missing = [s for s in slugs if lookup("generic", s) is None]
        assert not missing, (
            f"icons-generic.md documents slugs with no catalog entry: {missing}"
        )


class TestCompositeIconLookup:
    def test_falls_through_to_second_lookup_on_miss(self) -> None:
        first = render.CacheIconLookup(cache_dir=Path("/nonexistent"), sha="x")
        second = render.BundledGenericIconLookup()
        composite = render.CompositeIconLookup([first, second])
        icon = composite("generic", "database")
        assert icon is not None

    def test_first_hit_wins(self) -> None:
        def always_a(provider: str, slug: str) -> IconRef | None:
            return IconRef(view_box="A", body="a")

        def always_b(provider: str, slug: str) -> IconRef | None:
            return IconRef(view_box="B", body="b")

        composite = render.CompositeIconLookup([always_a, always_b])
        icon = composite("generic", "anything")
        assert icon is not None
        assert icon.view_box == "A"

    def test_none_when_every_lookup_misses(self) -> None:
        def always_none(provider: str, slug: str) -> IconRef | None:
            return None

        composite = render.CompositeIconLookup([always_none, always_none])
        assert composite("aws", "anything") is None


class TestDiagnosticEnvelope:
    def test_unknown_severity_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown severity"):
            render.Diagnostic(code="spec/x", severity="fatal", message="m")

    def test_empty_suppresses_is_omitted_from_the_payload(self) -> None:
        payload = render.Diagnostic(
            code="layout/node-overlap", severity="error", message="m"
        ).to_dict()
        assert "suppresses" not in payload
        assert payload["supported_fixes"] == []

    def test_suppresses_is_carried_when_set(self) -> None:
        payload = render.Diagnostic(
            code="composition/a",
            severity="warning",
            message="m",
            suppresses=("composition/b",),
        ).to_dict()
        assert payload["suppresses"] == ["composition/b"]

    def test_counts_split_by_severity(self) -> None:
        diags = [
            render.Diagnostic(code="a/x", severity="error", message="m"),
            render.Diagnostic(code="b/y", severity="warning", message="m"),
            render.Diagnostic(code="c/z", severity="warning", message="m"),
        ]
        assert render.count_by_severity(diags) == {"errors": 1, "warnings": 2}


class TestRouteRhythm:
    def _route(self, points: tuple[tuple[float, float], ...]) -> RoutedEdge:
        return RoutedEdge(edge=Edge("a", "b"), points=points, label_pos=(0, 0))

    def test_micro_segment_boundary_is_strict(self) -> None:
        too_short = self._route(((0, 0), (7.99, 0)))
        at_floor = self._route(((0, 0), (8, 0)))

        assert [d.code for d in check_route_rhythm([too_short])] == [
            "composition/micro-segment"
        ]
        assert check_route_rhythm([at_floor]) == []

    def test_interior_segment_boundary_is_strict(self) -> None:
        too_short = self._route(((0, 0), (20, 0), (20, 15.99), (40, 15.99)))
        at_floor = self._route(((0, 0), (20, 0), (20, 16), (40, 16)))

        assert [d.code for d in check_route_rhythm([too_short])] == [
            "composition/short-interior-segment"
        ]
        assert check_route_rhythm([at_floor]) == []

    def test_quality_profiles_change_route_rhythm_severity(self) -> None:
        route = self._route(((0, 0), (7.99, 0)))
        findings = check_route_rhythm([route])

        standard = render.apply_quality_profile(findings, "standard")
        showcase = render.apply_quality_profile(findings, "showcase")

        assert [d.severity for d in standard] == ["warning"]
        assert [d.severity for d in showcase] == ["error"]


class TestQualityProfiles:
    def _composition_warning(self) -> render.Diagnostic:
        return render.Diagnostic(
            code="composition/micro-segment", severity="warning", message="m"
        )

    def test_standard_leaves_composition_findings_as_warnings(self) -> None:
        out = render.apply_quality_profile([self._composition_warning()], "standard")
        assert [d.severity for d in out] == ["warning"]

    def test_showcase_raises_composition_findings_to_errors(self) -> None:
        out = render.apply_quality_profile([self._composition_warning()], "showcase")
        assert [d.severity for d in out] == ["error"]
        assert out[0].code == "composition/micro-segment"

    def test_showcase_leaves_other_namespaces_alone(self) -> None:
        warning = render.Diagnostic(
            code="layout/label-overflow", severity="warning", message="m"
        )
        out = render.apply_quality_profile([warning], "showcase")
        assert [d.severity for d in out] == ["warning"]

    def test_unknown_profile_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown quality profile"):
            render.apply_quality_profile([], "pretty")


class TestDerivedSuppression:
    def test_a_cause_removes_its_derivative(self) -> None:
        cause = render.Diagnostic(
            code="composition/cause",
            severity="error",
            message="m",
            suppresses=("composition/derived",),
        )
        derived = render.Diagnostic(
            code="composition/derived", severity="warning", message="m"
        )
        assert render.suppress_derived([cause, derived]) == [cause]

    def test_unrelated_findings_survive(self) -> None:
        a = render.Diagnostic(code="layout/node-overlap", severity="error", message="m")
        b = render.Diagnostic(code="icon/not-found", severity="error", message="m")
        assert render.suppress_derived([a, b]) == [a, b]

    def test_suppression_is_one_level_and_does_not_resolve_chains(self) -> None:
        # Documented semantics: a dropped record still suppresses, so a
        # chain removes everything below the top. Emitters must therefore
        # declare `suppresses` only for a code they directly explain.
        top = render.Diagnostic(
            code="composition/top",
            severity="error",
            message="m",
            suppresses=("composition/middle",),
        )
        middle = render.Diagnostic(
            code="composition/middle",
            severity="warning",
            message="m",
            suppresses=("composition/leaf",),
        )
        leaf = render.Diagnostic(
            code="composition/leaf", severity="warning", message="m"
        )
        assert render.suppress_derived([top, middle, leaf]) == [top]


class TestSpecErrorCodes:
    @pytest.mark.parametrize(
        ("spec_text", "code"),
        [
            ("title: empty\n", "spec/no-nodes"),
            ("nodes:\n  - label: no id\n", "spec/node-missing-id"),
            ("nodes:\n  - id: a\n  - id: a\n", "spec/duplicate-node-id"),
            ("zones:\n  - label: z\nnodes:\n  - id: a\n", "spec/zone-missing-id"),
            ("nodes:\n  - id: a\n    zone: ghost\n", "spec/unknown-zone"),
            (
                "zones:\n  - id: z\n    parent: ghost\nnodes:\n  - id: a\n    zone: z\n",
                "spec/unknown-zone-parent",
            ),
            (
                "zones:\n  - id: z\n    parent: z\nnodes:\n  - id: a\n    zone: z\n",
                "spec/zone-self-parent",
            ),
            (
                "nodes:\n  - id: a\nedges:\n  - from: a\n    to: ghost\n",
                "spec/unknown-edge-node",
            ),
        ],
    )
    def test_each_rejection_carries_its_own_code(
        self, spec_text: str, code: str
    ) -> None:
        with pytest.raises(SpecError) as exc:
            load_spec(spec_text)
        assert exc.value.diagnostic.code == code
        assert exc.value.diagnostic.severity == "error"
        assert exc.value.diagnostic.supported_fixes

    def test_empty_zone_is_coded_at_geometry_time(self) -> None:
        spec = load_spec("zones:\n  - id: z\nnodes:\n  - id: a\n")
        rank = assign_ranks(spec)
        order = order_within_ranks(spec, rank)
        node_boxes = compute_positions(spec, rank, order)
        with pytest.raises(SpecError) as exc:
            compute_zone_boxes(spec, node_boxes)
        assert exc.value.diagnostic.code == "spec/empty-zone"
        assert exc.value.diagnostic.subject == {"zone": "z"}

    def test_message_stays_human_readable(self) -> None:
        with pytest.raises(SpecError, match="spec has no nodes"):
            load_spec("title: empty\n")


class TestCliContract:
    def _run(
        self, capsys: pytest.CaptureFixture[str], *argv: str
    ) -> tuple[int, dict[str, object], str]:
        code = render.main(list(argv))
        captured = capsys.readouterr()
        payload = json.loads(captured.out) if "--json" in argv else {}
        return code, payload, captured.err

    def test_validate_returns_a_parsable_receipt_without_an_artifact(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        spec = tmp_path / "s.yaml"
        spec.write_text("nodes:\n  - id: a\n    label: A\n")
        code, payload, _ = self._run(
            capsys, "validate", str(spec), "--cache-dir", str(tmp_path), "--json"
        )

        assert code == render.EXIT_OK
        assert payload["ok"] is True
        assert payload["command"] == "validate"
        assert payload["input"]["path"] == str(spec)
        assert payload["input"]["bytes"] == len(spec.read_bytes())
        assert payload["artifact"]["bytes"] > 0
        assert payload["output"] == {"path": None, "written": False}
        assert payload["validation"] == {
            "checks_passed": 10,
            "checks_total": 10,
            "quality": "standard",
            "composition_status": "passed",
            "errors": 0,
            "warnings": 0,
        }
        assert payload["diagnostics"] == []
        assert payload["schema_version"] == render.RECEIPT_SCHEMA_VERSION

    def test_deliver_commits_the_validated_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        spec = tmp_path / "s.yaml"
        spec.write_text("nodes:\n  - id: a\n    label: A\n")
        out = tmp_path / "d.svg"
        code, payload, _ = self._run(
            capsys,
            "deliver",
            str(spec),
            "-o",
            str(out),
            "--cache-dir",
            str(tmp_path),
            "--json",
        )

        assert code == render.EXIT_OK
        assert payload["ok"] is True
        assert payload["command"] == "deliver"
        assert payload["output"] == {"path": str(out), "written": True}
        assert payload["artifact"]["bytes"] == len(out.read_bytes())
        assert payload["artifact"]["sha256"] == render._sha256(out.read_bytes())

    def test_json_mode_puts_nothing_but_json_on_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        spec = tmp_path / "s.yaml"
        spec.write_text("nodes:\n  - id: a\n    label: A\n    service: ghost\n")
        code, payload, _ = self._run(
            capsys,
            "validate",
            str(spec),
            "--cache-dir",
            str(tmp_path),
            "--json",
        )
        # A finding is present, so this also proves diagnostics do not leak to
        # stdout as prose alongside the receipt.
        assert code == render.EXIT_FAILURE
        assert [d["code"] for d in payload["diagnostics"]] == ["icon/not-found"]

    def test_missing_icon_is_an_operational_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        spec = tmp_path / "s.yaml"
        spec.write_text("nodes:\n  - id: a\n    label: A\n    service: ghost\n")
        out = tmp_path / "d.svg"
        code, payload, err = self._run(
            capsys,
            "deliver",
            str(spec),
            "-o",
            str(out),
            "--cache-dir",
            str(tmp_path),
            "--json",
        )
        assert code == render.EXIT_FAILURE
        assert payload["delivery_stage"] == "check"
        assert payload["output"]["written"] is False
        assert not out.exists()
        assert err == ""

    def test_failed_showcase_delivery_preserves_the_last_good_artifact(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        good_spec = tmp_path / "good.yaml"
        good_spec.write_text("nodes:\n  - id: a\n    label: A\n")
        bad_spec = tmp_path / "bad.yaml"
        bad_spec.write_text(
            'nodes:\n  - id: a\n    label: "This Is A Genuinely Very Long Label Text"\n'
        )
        out = tmp_path / "diagram.svg"

        good_code, _, _ = self._run(
            capsys,
            "deliver",
            str(good_spec),
            "-o",
            str(out),
            "--cache-dir",
            str(tmp_path),
            "--quality",
            "showcase",
            "--json",
        )
        last_good = out.read_bytes()
        bad_code, payload, _ = self._run(
            capsys,
            "deliver",
            str(bad_spec),
            "-o",
            str(out),
            "--cache-dir",
            str(tmp_path),
            "--quality",
            "showcase",
            "--json",
        )

        assert good_code == render.EXIT_OK
        assert bad_code == render.EXIT_FAILURE
        assert payload["delivery_stage"] == "check"
        assert [d["code"] for d in payload["diagnostics"]] == ["layout/label-overflow"]
        assert out.read_bytes() == last_good

    def test_invalid_spec_is_an_operational_failure_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        spec = tmp_path / "s.yaml"
        spec.write_text("title: empty\n")
        out = tmp_path / "d.svg"
        code, payload, _ = self._run(
            capsys,
            "deliver",
            str(spec),
            "-o",
            str(out),
            "--cache-dir",
            str(tmp_path),
            "--json",
        )
        assert code == render.EXIT_FAILURE
        assert payload["output"]["written"] is False
        assert payload["delivery_stage"] == "render"
        assert [d["code"] for d in payload["diagnostics"]] == ["spec/no-nodes"]
        assert not out.exists()

    def test_unreadable_spec_path_is_a_usage_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, payload, _ = self._run(
            capsys,
            "deliver",
            str(tmp_path / "nope.yaml"),
            "-o",
            str(tmp_path / "d.svg"),
            "--json",
        )
        assert code == render.EXIT_USAGE
        assert payload["delivery_stage"] == "input"
        assert [d["code"] for d in payload["diagnostics"]] == ["usage/spec-unreadable"]

    def test_script_entrypoint_runs_validate(self, tmp_path: Path) -> None:
        spec = tmp_path / "s.yaml"
        spec.write_text("nodes:\n  - id: a\n    label: A\n")
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(render.__file__).resolve()),
                "validate",
                str(spec),
                "--cache-dir",
                str(tmp_path),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        assert completed.returncode == render.EXIT_OK
        assert json.loads(completed.stdout)["command"] == "validate"
        assert completed.stderr == ""

    def test_legacy_cli_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            render.main([str(tmp_path / "s.yaml"), "-o", str(tmp_path / "d.svg")])
        assert exc.value.code == render.EXIT_USAGE

    def test_unknown_quality_profile_is_a_usage_error(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            render.main(["validate", str(tmp_path / "s.yaml"), "--quality", "pretty"])
        assert exc.value.code == render.EXIT_USAGE
