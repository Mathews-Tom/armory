"""Validated config data -> Manim scene source, with a deterministic duration model.

This module never imports Manim. It reads one of the packaged templates in
``references/templates/``, replaces only the marked config block with constants
generated from validated data, and reports the duration that template will
produce. User text reaches the generated source only through ``repr()`` of a
validated ``str``, so quotes, backslashes and unicode stay literal.

The duration model mirrors the pinned ``run_time`` / ``wait`` values in the
templates. When a template's timings change, update the matching ``_*_timing``
function in the same commit.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

TEMPLATE_DIR: Final[Path] = (
    Path(__file__).resolve().parent.parent / "references" / "templates"
)

TEMPLATE_FILES: Final[dict[str, str]] = {
    "data_flow": "data_flow_template.py",
    "comparison": "comparison_template.py",
    "timeline": "timeline_template.py",
}

SCENE_CLASSES: Final[dict[str, str]] = {
    "data_flow": "DataFlowScene",
    "comparison": "ComparisonScene",
    "timeline": "TimelineScene",
}

NAMED_COLORS: Final[frozenset[str]] = frozenset(
    {
        "BLUE",
        "TEAL",
        "GREEN",
        "YELLOW",
        "GOLD",
        "ORANGE",
        "RED",
        "MAROON",
        "PURPLE",
        "PINK",
        "WHITE",
        "GREY",
    }
)
DEFAULT_PALETTE: Final[tuple[str, ...]] = (
    "BLUE",
    "TEAL",
    "GREEN",
    "YELLOW",
    "ORANGE",
    "RED",
)
_HEX_COLOR: Final = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Bounds derived from each template's fixed layout constants (box width, panel
# width, timeline spacing). They stop obvious overflow; they do not prove layout.
TITLE_MAX_CHARS: Final = 48
STAGE_COUNT: Final = (2, 5)
STAGE_NAME_MAX_CHARS: Final = 16
COMPARISON_ITEM_COUNT: Final = (1, 6)
COMPARISON_ITEM_MAX_CHARS: Final = 36
COMPARISON_LABEL_MAX_CHARS: Final = 24
EVENT_COUNT: Final = (2, 8)
EVENT_LABEL_MAX_CHARS: Final = 12
EVENT_DESCRIPTION_MAX_CHARS: Final = 40
FINAL_HOLD_RANGE: Final = (0.5, 30.0)
DEFAULT_FINAL_HOLD: Final = 2.0

_CONFIG_BEGIN: Final = "# ── Config"
_CONFIG_END: Final = re.compile(r"^# ─{10,}$")


class ConfigError(ValueError):
    """Scene config is malformed, out of bounds, or names an unknown field."""


@dataclass(frozen=True)
class ScenePlan:
    template: str
    scene_class: str
    source: str
    expected_duration_s: float
    animation_calls: int
    final_hold_s: float
    config_sha256: str

    def manifest(self) -> dict[str, object]:
        """JSON-serialisable plan record (everything except the source text)."""
        return {
            "template": self.template,
            "scene_class": self.scene_class,
            "expected_duration_s": self.expected_duration_s,
            "animation_calls": self.animation_calls,
            "final_hold_s": self.final_hold_s,
            "config_sha256": self.config_sha256,
            "source_sha256": hashlib.sha256(self.source.encode("utf-8")).hexdigest(),
        }


@dataclass(frozen=True)
class _Rendered:
    block: str
    duration_s: float
    calls: int
    final_hold_s: float


# ── Loading ────────────────────────────────────────────────────────────────


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ConfigError(f"duplicate key {key!r} in config")
        out[key] = value
    return out


def load_config(path: Path) -> dict[str, object]:
    """Read a ``.json`` or ``.toml`` scene config; reject any other suffix."""
    suffix = path.suffix.lower()
    if suffix not in (".json", ".toml"):
        raise ConfigError(f"{path}: config must be .json or .toml, got {suffix!r}")
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read config as UTF-8 ({exc})") from exc
    try:
        if suffix == ".json":
            parsed: object = json.loads(raw, object_pairs_hook=_reject_duplicates)
        else:
            parsed = tomllib.loads(raw)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: invalid {suffix[1:].upper()} ({exc})") from exc
    return _mapping(parsed, str(path))


# ── Field validators ───────────────────────────────────────────────────────


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: expected an object, got {type(value).__name__}")
    out: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ConfigError(f"{path}: object keys must be strings")
        out[key] = item
    return out


def _fields(
    mapping: Mapping[str, object],
    path: str,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    unknown = sorted(set(mapping) - required - optional)
    if unknown:
        raise ConfigError(
            f"{path}: unknown field(s) {unknown}; allowed: {sorted(required | optional)}"
        )
    missing = sorted(required - set(mapping))
    if missing:
        raise ConfigError(f"{path}: missing required field(s) {missing}")


def _text(value: object, path: str, *, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{path}: expected a string, got {type(value).__name__}")
    if not value.strip():
        raise ConfigError(f"{path}: text must not be empty or whitespace-only")
    if len(value) > max_chars:
        raise ConfigError(
            f"{path}: {len(value)} characters exceeds the {max_chars}-character "
            "limit of this template's layout"
        )
    for char in value:
        if unicodedata.category(char) in ("Cc", "Cs"):
            raise ConfigError(
                f"{path}: control or surrogate character U+{ord(char):04X} is not "
                "allowed; use plain single-line text"
            )
    return value


def _color(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(
            f"{path}: expected a color string, got {type(value).__name__}"
        )
    if value in NAMED_COLORS or _HEX_COLOR.fullmatch(value):
        return value
    raise ConfigError(
        f"{path}: {value!r} is not a supported color; use one of "
        f"{sorted(NAMED_COLORS)} or a #RRGGBB hex value"
    )


def _seconds(value: object, path: str, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"{path}: expected a number of seconds, got {type(value).__name__}"
        )
    try:
        seconds = float(value)
    except OverflowError as exc:
        raise ConfigError(
            f"{path}: value is outside the allowed {low}-{high} seconds"
        ) from exc
    if not math.isfinite(seconds) or not low <= seconds <= high:
        raise ConfigError(
            f"{path}: {value!r} is outside the allowed {low}-{high} seconds"
        )
    return seconds


def _sequence(
    value: object, path: str, *, bounds: tuple[int, int], noun: str
) -> list[object]:
    if not isinstance(value, list):
        raise ConfigError(f"{path}: expected a list, got {type(value).__name__}")
    low, high = bounds
    if not low <= len(value) <= high:
        raise ConfigError(
            f"{path}: {len(value)} {noun} given; this template supports {low}-{high}"
        )
    return list(value)


def _color_expr(color: str) -> str:
    return color if color in NAMED_COLORS else f"ManimColor({color!r})"


def _final_hold(cfg: Mapping[str, object]) -> float:
    if "final_hold_seconds" not in cfg:
        return DEFAULT_FINAL_HOLD
    return _seconds(
        cfg["final_hold_seconds"],
        "final_hold_seconds",
        low=FINAL_HOLD_RANGE[0],
        high=FINAL_HOLD_RANGE[1],
    )


def _color_or_default(entry: Mapping[str, object], path: str, index: int) -> str:
    if "color" in entry:
        return _color(entry["color"], f"{path}.color")
    return DEFAULT_PALETTE[index % len(DEFAULT_PALETTE)]


# ── Duration models (mirror the pinned run_time/wait values in templates) ──


def _data_flow_timing(stages: int, hold: float) -> tuple[float, int]:
    # title write 1 + wait 0.5 + title shift 1; per stage fade 0.45;
    # per arrow 0.3; wait 1; replay 0.35 + 0.2 per stage; final hold.
    duration = 3.5 + 0.45 * stages + 0.3 * (stages - 1) + 0.55 * stages + hold
    return duration, 4 * stages + 4


def _comparison_timing(hold: float) -> tuple[float, int]:
    # title write 1 + wait 0.5 + shift 1 + divider 1 + labels 1 + items 2; hold.
    return 6.5 + hold, 7


def _timeline_timing(events: int, hold: float) -> tuple[float, int]:
    # title write 1 + wait 0.5 + shift 1 + axis 0.8; 1.0 per event; hold.
    return 3.3 + events + hold, 2 * events + 5


# ── Per-template config blocks ─────────────────────────────────────────────

_HEADER = (
    "# Generated by build_scene.py from validated config; edit via the config file.\n"
)


def _render_data_flow(cfg: Mapping[str, object]) -> _Rendered:
    _fields(
        cfg,
        "config",
        required=frozenset({"template", "title", "stages"}),
        optional=frozenset({"arrow_color", "final_hold_seconds"}),
    )
    title = _text(cfg["title"], "title", max_chars=TITLE_MAX_CHARS)
    arrow = _color(cfg.get("arrow_color", "WHITE"), "arrow_color")
    hold = _final_hold(cfg)
    rows: list[str] = []
    for i, raw in enumerate(
        _sequence(cfg["stages"], "stages", bounds=STAGE_COUNT, noun="stages")
    ):
        path = f"stages[{i}]"
        entry = _mapping(raw, path)
        _fields(
            entry, path, required=frozenset({"name"}), optional=frozenset({"color"})
        )
        name = _text(entry["name"], f"{path}.name", max_chars=STAGE_NAME_MAX_CHARS)
        color = _color_or_default(entry, path, i)
        rows.append(f"    ({name!r}, {_color_expr(color)}),\n")
    block = (
        f"{_HEADER}TITLE = {title!r}\n\n"
        f"STAGES: list[tuple[str, ManimColor]] = [\n{''.join(rows)}]\n\n"
        f"ARROW_COLOR = {_color_expr(arrow)}\n"
        f"FINAL_HOLD = {hold!r}\n"
    )
    duration, calls = _data_flow_timing(len(rows), hold)
    return _Rendered(block, duration, calls, hold)


def _comparison_side(
    value: object, path: str, default_color: str
) -> tuple[str, str, list[str]]:
    side = _mapping(value, path)
    _fields(
        side,
        path,
        required=frozenset({"label", "items"}),
        optional=frozenset({"color"}),
    )
    label = _text(side["label"], f"{path}.label", max_chars=COMPARISON_LABEL_MAX_CHARS)
    color = _color(side["color"], f"{path}.color") if "color" in side else default_color
    items = [
        _text(item, f"{path}.items[{i}]", max_chars=COMPARISON_ITEM_MAX_CHARS)
        for i, item in enumerate(
            _sequence(
                side["items"],
                f"{path}.items",
                bounds=COMPARISON_ITEM_COUNT,
                noun="items",
            )
        )
    ]
    return label, color, items


def _render_comparison(cfg: Mapping[str, object]) -> _Rendered:
    _fields(
        cfg,
        "config",
        required=frozenset({"template", "title", "left", "right"}),
        optional=frozenset({"final_hold_seconds"}),
    )
    title = _text(cfg["title"], "title", max_chars=TITLE_MAX_CHARS)
    hold = _final_hold(cfg)
    left_label, left_color, left_items = _comparison_side(cfg["left"], "left", "BLUE")
    right_label, right_color, right_items = _comparison_side(
        cfg["right"], "right", "GREEN"
    )

    def items_literal(items: list[str]) -> str:
        return "[\n" + "".join(f"    {item!r},\n" for item in items) + "]"

    block = (
        f"{_HEADER}TITLE = {title!r}\n\n"
        f"LEFT_LABEL = {left_label!r}\n"
        f"LEFT_COLOR = {_color_expr(left_color)}\n"
        f"LEFT_ITEMS = {items_literal(left_items)}\n\n"
        f"RIGHT_LABEL = {right_label!r}\n"
        f"RIGHT_COLOR = {_color_expr(right_color)}\n"
        f"RIGHT_ITEMS = {items_literal(right_items)}\n\n"
        f"FINAL_HOLD = {hold!r}\n"
    )
    duration, calls = _comparison_timing(hold)
    return _Rendered(block, duration, calls, hold)


def _render_timeline(cfg: Mapping[str, object]) -> _Rendered:
    _fields(
        cfg,
        "config",
        required=frozenset({"template", "title", "events"}),
        optional=frozenset({"final_hold_seconds"}),
    )
    title = _text(cfg["title"], "title", max_chars=TITLE_MAX_CHARS)
    hold = _final_hold(cfg)
    rows: list[str] = []
    for i, raw in enumerate(
        _sequence(cfg["events"], "events", bounds=EVENT_COUNT, noun="events")
    ):
        path = f"events[{i}]"
        entry = _mapping(raw, path)
        _fields(
            entry,
            path,
            required=frozenset({"label", "description"}),
            optional=frozenset({"color"}),
        )
        label = _text(entry["label"], f"{path}.label", max_chars=EVENT_LABEL_MAX_CHARS)
        description = _text(
            entry["description"],
            f"{path}.description",
            max_chars=EVENT_DESCRIPTION_MAX_CHARS,
        )
        color = _color_or_default(entry, path, i)
        rows.append(f"    ({label!r}, {description!r}, {_color_expr(color)}),\n")
    block = (
        f"{_HEADER}TITLE = {title!r}\n\n"
        f"EVENTS: list[tuple[str, str, ManimColor]] = [\n{''.join(rows)}]\n\n"
        f"FINAL_HOLD = {hold!r}\n"
    )
    duration, calls = _timeline_timing(len(rows), hold)
    return _Rendered(block, duration, calls, hold)


_RENDERERS: Final[dict[str, Callable[[Mapping[str, object]], _Rendered]]] = {
    "data_flow": _render_data_flow,
    "comparison": _render_comparison,
    "timeline": _render_timeline,
}


# ── Source assembly ────────────────────────────────────────────────────────


def _replace_config_block(template_source: str, block: str, template: str) -> str:
    lines = template_source.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.startswith(_CONFIG_BEGIN)]
    if len(begins) != 1:
        raise ConfigError(
            f"template {template!r}: expected exactly one '{_CONFIG_BEGIN}' marker, "
            f"found {len(begins)}"
        )
    begin = begins[0]
    end = next(
        (
            i
            for i in range(begin + 1, len(lines))
            if _CONFIG_END.match(lines[i].rstrip("\r\n"))
        ),
        None,
    )
    if end is None:
        raise ConfigError(
            f"template {template!r}: config block has no closing rule line"
        )
    return "".join(lines[: begin + 1]) + block + "".join(lines[end:])


def _canonical_sha256(cfg: Mapping[str, object]) -> str:
    canonical = json.dumps(
        cfg, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_plan(
    cfg: Mapping[str, object], template_dir: Path = TEMPLATE_DIR
) -> ScenePlan:
    """Validate *cfg* and return generated scene source plus its timing plan."""
    name = cfg.get("template")
    if not isinstance(name, str) or name not in TEMPLATE_FILES:
        raise ConfigError(
            f"template: expected one of {sorted(TEMPLATE_FILES)}, got {name!r}"
        )
    rendered = _RENDERERS[name](cfg)
    template_path = template_dir / TEMPLATE_FILES[name]
    try:
        template_source = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read template {template_path}: {exc}") from exc
    source = _replace_config_block(template_source, rendered.block, name)
    return ScenePlan(
        template=name,
        scene_class=SCENE_CLASSES[name],
        source=source,
        expected_duration_s=round(rendered.duration_s, 6),
        animation_calls=rendered.calls,
        final_hold_s=rendered.final_hold_s,
        config_sha256=_canonical_sha256(cfg),
    )
