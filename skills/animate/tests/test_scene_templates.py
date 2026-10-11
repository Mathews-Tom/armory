"""Config validation, source generation and timing plan for the no-model template path.

The generated source is executed against a stub ``manim`` module, so these tests
need neither Manim nor ffmpeg.
"""

from __future__ import annotations

import math
import sys
import types
from pathlib import Path

import pytest

from scene_templates import (
    NAMED_COLORS,
    ConfigError,
    build_plan,
    load_config,
)


def _data_flow(**overrides: object) -> dict[str, object]:
    cfg: dict[str, object] = {
        "template": "data_flow",
        "title": "Pipeline",
        "stages": [{"name": "Ingest"}, {"name": "Embed", "color": "TEAL"}],
    }
    cfg.update(overrides)
    return cfg


def _comparison(**overrides: object) -> dict[str, object]:
    cfg: dict[str, object] = {
        "template": "comparison",
        "title": "A vs B",
        "left": {"label": "A", "items": ["fast"]},
        "right": {"label": "B", "items": ["small"], "color": "#FF8800"},
    }
    cfg.update(overrides)
    return cfg


def _timeline(**overrides: object) -> dict[str, object]:
    cfg: dict[str, object] = {
        "template": "timeline",
        "title": "History",
        "events": [
            {"label": "2017", "description": "Transformer"},
            {"label": "2018", "description": "BERT"},
        ],
    }
    cfg.update(overrides)
    return cfg


def _exec_generated(source: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Run generated source against a stub manim; returns the module namespace."""
    stub = types.ModuleType("manim")
    setattr(stub, "Scene", object)
    setattr(stub, "ManimColor", lambda value: ("hex", value))
    for name in NAMED_COLORS:
        setattr(stub, name, ("named", name))
    monkeypatch.setitem(sys.modules, "manim", stub)
    namespace: dict[str, object] = {"__name__": "generated_scene"}
    exec(compile(source, "scene.py", "exec"), namespace)  # noqa: S102
    return namespace


# ── Rejection of bad data ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cfg", "fragment"),
    [
        (_data_flow(colour="RED"), "unknown field"),
        (
            _data_flow(stages=[{"name": "A", "colour": "RED"}, {"name": "B"}]),
            "stages[0]",
        ),
        (_comparison(left={"label": "A", "items": ["x"], "extra": 1}), "left"),
        (
            _timeline(events=[{"label": "1", "description": "d", "when": 1}] * 2),
            "events[0]",
        ),
        ({"template": "pie"}, "template"),
        (_data_flow(title=None), "title"),
    ],
)
def test_unknown_or_malformed_fields_are_rejected(
    cfg: dict[str, object], fragment: str
) -> None:
    with pytest.raises(
        ConfigError, match=fragment.replace("[", r"\[").replace("]", r"\]")
    ):
        build_plan(cfg)


@pytest.mark.parametrize("count", [0, 1, 6])
def test_data_flow_stage_count_out_of_bounds(count: int) -> None:
    cfg = _data_flow(stages=[{"name": f"S{i}"} for i in range(count)])
    with pytest.raises(ConfigError, match="supports 2-5"):
        build_plan(cfg)


def test_timeline_single_event_would_divide_by_zero_so_is_rejected() -> None:
    with pytest.raises(ConfigError, match="supports 2-8"):
        build_plan(_timeline(events=[{"label": "2017", "description": "only"}]))


def test_comparison_item_bounds() -> None:
    with pytest.raises(ConfigError, match="supports 1-6"):
        build_plan(_comparison(left={"label": "A", "items": []}))
    with pytest.raises(ConfigError, match="supports 1-6"):
        build_plan(_comparison(left={"label": "A", "items": ["x"] * 7}))


@pytest.mark.parametrize(
    "bad",
    [0.1, 31, -2, 10**400, math.nan, math.inf, True, "2", None, [2]],
)
def test_final_hold_must_be_a_finite_number_in_range(bad: object) -> None:
    with pytest.raises(ConfigError, match="final_hold_seconds"):
        build_plan(_data_flow(final_hold_seconds=bad))


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "line\nbreak", "tab\there", "x" * 49, 7, ["Pipeline"]],
)
def test_title_must_be_short_single_line_text(bad: object) -> None:
    with pytest.raises(ConfigError, match="title"):
        build_plan(_data_flow(title=bad))


@pytest.mark.parametrize(
    "bad", ["blue", "#12345", "#GGGGGG", "#FF8800\n", "rgb(1,2,3)", 5, None]
)
def test_colors_must_be_named_constants_or_hex(bad: object) -> None:
    with pytest.raises(ConfigError, match="color"):
        build_plan(_data_flow(stages=[{"name": "A", "color": bad}, {"name": "B"}]))


def test_load_config_rejects_duplicate_keys_and_unknown_suffix(tmp_path: Path) -> None:
    dup = tmp_path / "dup.json"
    dup.write_text(
        '{"template": "data_flow", "template": "timeline"}', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="duplicate key"):
        load_config(dup)
    other = tmp_path / "scene.yaml"
    other.write_text("template: data_flow", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"\.json or \.toml"):
        load_config(other)


def test_load_config_reads_toml_arrays_of_tables(tmp_path: Path) -> None:
    path = tmp_path / "scene.toml"
    path.write_text(
        'template = "data_flow"\ntitle = "T"\n'
        '[[stages]]\nname = "A"\n[[stages]]\nname = "B"\ncolor = "#00FF00"\n',
        encoding="utf-8",
    )
    plan = build_plan(load_config(path))
    assert plan.template == "data_flow"


# ── Source fidelity ────────────────────────────────────────────────────────

HOSTILE = [
    'He said "hi" and it\'s fine',
    "back\\slash and \\n literal",
    "braces {x} {{y}} and %s %d",
    "triple ''' and \"\"\" quotes",
    "naïve café — 数据 流 ✓",
    "# not a comment; import os",
]


def test_user_text_survives_generation_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    titles = HOSTILE[:]
    for text in titles:
        cfg = _data_flow(title=text[:48], stages=[{"name": text[:16]}, {"name": "B"}])
        namespace = _exec_generated(build_plan(cfg).source, monkeypatch)
        assert namespace["TITLE"] == text[:48]
        stages = namespace["STAGES"]
        assert isinstance(stages, list)
        assert stages[0][0] == text[:16]


def test_hostile_text_in_comparison_and_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [t[:36] for t in HOSTILE]
    label = HOSTILE[0][:24]
    comparison = build_plan(
        _comparison(
            left={"label": label, "items": items}, right={"label": "B", "items": items}
        )
    )
    ns = _exec_generated(comparison.source, monkeypatch)
    assert ns["LEFT_LABEL"] == label
    assert ns["LEFT_ITEMS"] == items

    events = [{"label": "L", "description": t[:40]} for t in HOSTILE]
    timeline = build_plan(_timeline(events=events))
    ns = _exec_generated(timeline.source, monkeypatch)
    generated_events = ns["EVENTS"]
    assert isinstance(generated_events, list)
    assert [e[1] for e in generated_events] == [t[:40] for t in HOSTILE]


def test_named_and_hex_colors_are_emitted_distinctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ns = _exec_generated(build_plan(_comparison()).source, monkeypatch)
    assert ns["LEFT_COLOR"] == ("named", "BLUE")  # default
    assert ns["RIGHT_COLOR"] == ("hex", "#FF8800")


# ── Timing plan ────────────────────────────────────────────────────────────


def test_final_hold_and_size_drive_expected_duration() -> None:
    base = build_plan(_data_flow(final_hold_seconds=1.0))
    longer_hold = build_plan(_data_flow(final_hold_seconds=4.0))
    more_stages = build_plan(
        _data_flow(stages=[{"name": str(i)} for i in range(3)], final_hold_seconds=1.0)
    )
    assert longer_hold.expected_duration_s - base.expected_duration_s == pytest.approx(
        3.0
    )
    assert more_stages.expected_duration_s > base.expected_duration_s
    assert more_stages.animation_calls > base.animation_calls
    assert base.final_hold_s == 1.0


def test_comparison_duration_does_not_depend_on_item_count() -> None:
    short = build_plan(_comparison())
    long = build_plan(_comparison(left={"label": "A", "items": ["x"] * 6}))
    assert short.expected_duration_s == long.expected_duration_s


def test_manifest_hashes_config_and_source() -> None:
    a = build_plan(_data_flow(title="One"))
    b = build_plan(_data_flow(title="Two"))
    assert a.config_sha256 != b.config_sha256
    assert a.manifest()["source_sha256"] != b.manifest()["source_sha256"]


def test_non_utf8_config_is_an_explicit_config_error(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_bytes('{"template":"data_flow","title":"T"}'.encode("utf-16"))
    with pytest.raises(ConfigError, match="UTF-8"):
        load_config(config)
