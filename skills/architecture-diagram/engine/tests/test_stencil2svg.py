"""Tests for stencil2svg.py — mxGraph stencil DSL to SVG conversion."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from engine.stencil2svg import convert_body, load_shapes, slug

FIXTURES = Path(__file__).parent / "fixtures"


def _shape(inner_foreground_xml: str, w: float = 10, h: float = 10) -> ET.Element:
    xml = f'<shape w="{w}" h="{h}"><foreground>{inner_foreground_xml}</foreground></shape>'
    return ET.fromstring(xml)


class TestBasicPrimitives:
    def test_simple_path_fill(self) -> None:
        shape = _shape(
            "<path><move x='0' y='0'/><line x='10' y='0'/><close/></path><fill/>"
        )
        vb, body, warnings = convert_body(shape)
        assert vb == "0 0 10 10"
        assert warnings == []
        assert '<path d="M0,0 L10,0 Z" fill="currentColor" stroke="none"/>' == body

    def test_stroke_only_omits_fill(self) -> None:
        shape = _shape(
            "<strokecolor color='#ff0000'/><path><move x='0' y='0'/><line x='5' y='5'/></path><stroke/>"
        )
        _, body, _ = convert_body(shape)
        assert 'fill="none"' in body
        assert 'stroke="#ff0000"' in body
        assert 'stroke-width="1"' in body

    def test_fillstroke_emits_both(self) -> None:
        shape = _shape(
            "<fillcolor color='#00ff00'/><strokecolor color='#000000'/>"
            "<path><move x='0' y='0'/><line x='5' y='5'/></path><fillstroke/>"
        )
        _, body, _ = convert_body(shape)
        assert 'fill="#00ff00"' in body
        assert 'stroke="#000000"' in body

    def test_rect_primitive(self) -> None:
        shape = _shape("<rect x='1' y='2' w='3' h='4'/><fill/>")
        _, body, warnings = convert_body(shape)
        assert warnings == []
        assert "<rect " in body
        assert 'x="1"' in body and 'width="3"' in body and 'height="4"' in body

    def test_bare_rect_is_degenerate_not_a_crash(self) -> None:
        """A bare <rect/> with no x/y/w/h is real mxGraph behavior (verified against
        mxStencil.js drawNode): Number(null) defaults every attr to 0, producing a
        zero-area rect. It is a documented no-op in the source data, not a bug to
        paper over with an invented 'full bounds' default."""
        shape = _shape("<rect/><stroke/>")
        _, body, warnings = convert_body(shape)
        assert warnings == []
        assert 'width="0"' in body and 'height="0"' in body

    def test_ellipse_primitive(self) -> None:
        shape = _shape("<ellipse x='0' y='0' w='10' h='10'/><fill/>")
        _, body, _ = convert_body(shape)
        assert "<ellipse " in body
        assert 'cx="5"' in body and 'rx="5"' in body

    def test_arc_primitive(self) -> None:
        shape = _shape(
            "<path><move x='0' y='0'/>"
            "<arc rx='5' ry='5' x-axis-rotation='0' large-arc-flag='1' sweep-flag='0' x='10' y='10'/>"
            "</path><fill/>"
        )
        _, body, _ = convert_body(shape)
        assert "A5,5 0 1,0 10,10" in body

    def test_dashed_stroke(self) -> None:
        shape = _shape(
            "<strokecolor color='#000'/><dashed dashed='1'/>"
            "<path><move x='0' y='0'/><line x='1' y='1'/></path><stroke/>"
        )
        _, body, _ = convert_body(shape)
        assert "stroke-dasharray" in body


class TestAlphaAndStateStack:
    """Regression coverage for the save/restore + unified-alpha bug found while
    grounding this converter against mxAbstractCanvas2D.js: alpha/fillalpha/
    strokealpha all set ONE canvas alpha (not independent fill/stroke alpha),
    and save/restore must clone/pop the whole paint state or alpha leaks past
    its intended scope."""

    def test_alpha_applies_as_unified_opacity(self) -> None:
        shape = _shape(
            "<fillalpha alpha='0.5'/><path><move x='0' y='0'/><line x='1' y='1'/></path><fill/>"
        )
        _, body, _ = convert_body(shape)
        assert 'opacity="0.5"' in body

    def test_alpha_does_not_leak_past_restore(self) -> None:
        xml = (
            "<save/><fillalpha alpha='0.07'/>"
            "<path><move x='0' y='0'/><line x='1' y='1'/></path><fill/>"
            "<restore/>"
            "<path><move x='2' y='2'/><line x='3' y='3'/></path><fill/>"
        )
        shape = _shape(xml)
        _, body, warnings = convert_body(shape)
        assert warnings == []
        paths = body.split("<path ")[1:]
        assert len(paths) == 2
        assert 'opacity="0.07"' in paths[0]
        assert "opacity" not in paths[1], "alpha leaked past restore()"

    def test_fillcolor_does_not_leak_past_restore(self) -> None:
        xml = (
            "<save/><fillcolor color='#111111'/>"
            "<path><move x='0' y='0'/><line x='1' y='1'/></path><fill/>"
            "<restore/>"
            "<path><move x='2' y='2'/><line x='3' y='3'/></path><fill/>"
        )
        shape = _shape(xml)
        _, body, _ = convert_body(shape)
        paths = body.split("<path ")[1:]
        assert 'fill="#111111"' in paths[0]
        assert 'fill="currentColor"' in paths[1]

    def test_restore_without_save_warns_not_crashes(self) -> None:
        shape = _shape("<restore/><path><move x='0' y='0'/></path><fill/>")
        _, _, warnings = convert_body(shape)
        assert any("restore" in w for w in warnings)

    def test_nested_save_restore(self) -> None:
        xml = (
            "<fillcolor color='#aaa'/>"
            "<save/>"
            "<fillcolor color='#bbb'/>"
            "<save/><fillcolor color='#ccc'/><path><move x='0' y='0'/></path><fill/><restore/>"
            "<path><move x='1' y='1'/></path><fill/>"
            "<restore/>"
            "<path><move x='2' y='2'/></path><fill/>"
        )
        shape = _shape(xml)
        _, body, warnings = convert_body(shape)
        assert warnings == []
        paths = body.split("<path ")[1:]
        assert 'fill="#ccc"' in paths[0]
        assert 'fill="#bbb"' in paths[1]
        assert 'fill="#aaa"' in paths[2]


class TestUnsupportedPrimitives:
    def test_unsupported_tag_warns_and_skips(self) -> None:
        shape = _shape(
            "<text str='hi' x='0' y='0'/><path><move x='0' y='0'/></path><fill/>"
        )
        _, body, warnings = convert_body(shape)
        assert any("text" in w for w in warnings)
        assert "hi" not in body

    def test_unknown_tag_warns(self) -> None:
        shape = _shape("<gradient/><path><move x='0' y='0'/></path><fill/>")
        _, _, warnings = convert_body(shape)
        assert any("gradient" in w for w in warnings)

    def test_paint_with_no_geometry_warns_not_crashes(self) -> None:
        shape = _shape("<fill/>")
        _, body, warnings = convert_body(shape)
        assert body == ""
        assert any("no preceding geometry" in w for w in warnings)

    def test_missing_foreground_warns(self) -> None:
        shape = ET.fromstring('<shape w="10" h="10"></shape>')
        _, body, warnings = convert_body(shape)
        assert body == ""
        assert "no <foreground>" in warnings[0]


class TestSlug:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("api gateway", "api-gateway"),
            ("EC2 Instance", "ec2-instance"),
            ("S3", "s3"),
            ("Cloud Run", "cloud-run"),
            ("a  b   c", "a-b-c"),
        ],
    )
    def test_slug_normalizes(self, name: str, expected: str) -> None:
        assert slug(name) == expected


class TestRealFixtures:
    """Convert real, verbatim-extracted AWS and GCP stencil shapes (draw.io,
    Apache-2.0, pinned in fixtures/real_shapes.xml) end to end."""

    def test_loads_named_shapes(self) -> None:
        shapes = load_shapes(str(FIXTURES / "real_shapes.xml"))
        assert set(shapes) == {"lambda", "BigQuery"}

    def test_lambda_converts_cleanly(self) -> None:
        shapes = load_shapes(str(FIXTURES / "real_shapes.xml"))
        vb, body, warnings = convert_body(shapes["lambda"])
        assert warnings == []
        assert vb == "0 0 54.05 56"
        assert (
            body.count("<path ") == 1
        )  # all 4 subpaths compose into one <path> d string
        assert body.count("M") == 4  # 4 disjoint move-to subpaths form the lambda glyph
        assert 'fill="currentColor"' in body

    def test_bigquery_multi_color_converts_and_does_not_leak_alpha(self) -> None:
        """BigQuery is the exact shape that exposed the alpha-leak bug: a shadow
        triangle drawn at fillalpha=0.07 inside save/restore, followed by a
        white glyph on top that must render fully opaque."""
        shapes = load_shapes(str(FIXTURES / "real_shapes.xml"))
        _vb, body, warnings = convert_body(shapes["BigQuery"])
        assert warnings == []
        paths = body.split("<path ")[1:]
        assert len(paths) >= 3
        shadow = next(p for p in paths if 'fill="#000000"' in p)
        assert 'opacity="0.07"' in shadow
        glyph = next(p for p in paths if 'fill="#ffffff"' in p)
        assert "opacity" not in glyph, (
            "BigQuery glyph incorrectly inherited shadow alpha"
        )
