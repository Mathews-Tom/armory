"""Tests for render.py — spec parsing, layout, routing, and SVG emission."""

from __future__ import annotations

import re

import pytest
import render
from render import (
    Box,
    Edge,
    IconRef,
    Node,
    Spec,
    SpecError,
    assign_ranks,
    check_editability,
    check_layout,
    compute_positions,
    compute_zone_boxes,
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
        warnings = check_layout(spec, boxes, {})
        assert not any("overlap" in w for w in warnings)


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


class TestEditabilityCheck:
    def test_clean_svg_has_no_violations(self) -> None:
        svg = '<svg><g><rect fill="#fff"/><text>hi</text></g></svg>'
        assert check_editability(svg) == []

    def test_detects_raster_image(self) -> None:
        svg = '<svg><image href="data:image/png;base64,abc"/></svg>'
        warnings = check_editability(svg)
        assert any("image" in w for w in warnings)

    def test_detects_use_clone(self) -> None:
        svg = '<svg><defs><symbol id="x"/></defs><use href="#x"/></svg>'
        warnings = check_editability(svg)
        assert any("use" in w for w in warnings)

    def test_detects_external_href(self) -> None:
        svg = '<svg><a href="http://example.com/icon.svg"/></svg>'
        warnings = check_editability(svg)
        assert any("external" in w for w in warnings)


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

    def test_missing_icon_falls_back_without_crashing_and_warns(self) -> None:
        spec_text = "nodes:\n  - id: a\n    label: A\n    service: missing\n"
        spec = load_spec(spec_text)
        result = do_render(spec, _icon_lookup)
        assert "no icon for node" in " ".join(result.warnings)
        assert result.svg.startswith("<svg")

    def test_node_without_service_renders_placeholder_no_warning(self) -> None:
        spec = load_spec("nodes:\n  - id: a\n    label: A\n")
        result = do_render(spec, _icon_lookup)
        assert not any("no icon" in w for w in result.warnings)

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

    def test_overflowing_label_warns(self) -> None:
        spec_text = (
            'nodes:\n  - id: a\n    label: "This Is A Genuinely Very Long Label Text"\n'
        )
        spec = load_spec(spec_text)
        result = do_render(spec, _icon_lookup)
        assert any("overflow" in w for w in result.warnings)

    def test_svg_has_valid_viewbox_matching_dimensions(self) -> None:
        spec = load_spec(LINEAR_SPEC)
        result = do_render(spec, _icon_lookup)
        width_m = re.search(r'width="([\d.]+)"', result.svg)
        vb_m = re.search(r'viewBox="0 0 ([\d.]+) ', result.svg)
        assert width_m and vb_m
        assert float(width_m.group(1)) == pytest.approx(float(vb_m.group(1)))


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
        warnings = check_layout(spec, node_boxes, zone_boxes)
        assert any("zone overlap" in w for w in warnings)


class TestRealIconCacheIntegration:
    def test_cache_icon_lookup_reads_real_fixture_style_entry(
        self, tmp_path: object
    ) -> None:
        import json
        from pathlib import Path

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
        from pathlib import Path

        lookup = render.CacheIconLookup(cache_dir=Path(str(tmp_path)), sha="deadbeef")
        assert lookup("aws", "does-not-exist") is None
