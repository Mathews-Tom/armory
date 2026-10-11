"""Typed access to the package-owned pin in ``config.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = SKILL_DIR / "config.toml"
TEMPLATES_DIR = SKILL_DIR / "templates"


class ConfigError(RuntimeError):
    """The package configuration is missing or malformed."""


@dataclass(frozen=True)
class Config:
    package: str
    version: str
    node_min_major: int
    fps: int
    workers: int
    check_timeout_ms: int
    max_check_samples: int
    snapshot_frames: int
    forced_env: dict[str, str]
    scrubbed_env: tuple[str, ...]

    @property
    def spec(self) -> str:
        return f"{self.package}@{self.version}"


def _table(raw: dict[str, object], key: str) -> dict[str, object]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"config.toml: missing [{key}] table")
    return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def _str(table: dict[str, object], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"config.toml: {key} must be a non-empty string")
    return value


def _int(table: dict[str, object], key: str) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"config.toml: {key} must be a positive integer")
    return value


def load_config(path: Path = CONFIG_PATH) -> Config:
    try:
        raw: dict[str, object] = dict(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    hyperframes = _table(raw, "hyperframes")
    runtime = _table(raw, "runtime")
    render = _table(raw, "render")
    check = _table(raw, "check")
    snapshot = _table(raw, "snapshot")
    environment = _table(raw, "environment")
    scrub = _table(raw, "scrub")
    scrub_env = scrub.get("env")
    if not isinstance(scrub_env, list) or not all(
        isinstance(item, str) for item in scrub_env
    ):  # pyright: ignore[reportUnknownVariableType]
        raise ConfigError("config.toml: scrub.env must be a list of strings")
    forced: dict[str, str] = {}
    for key, value in environment.items():
        if not isinstance(value, str):
            raise ConfigError(f"config.toml: environment.{key} must be a string")
        forced[key] = value
    return Config(
        package=_str(hyperframes, "package"),
        version=_str(hyperframes, "version"),
        node_min_major=_int(runtime, "node_min_major"),
        fps=_int(render, "fps"),
        workers=_int(render, "workers"),
        check_timeout_ms=_int(render, "check_timeout_ms"),
        max_check_samples=_int(check, "max_samples"),
        snapshot_frames=_int(snapshot, "max_frames"),
        forced_env=forced,
        scrubbed_env=tuple(str(item) for item in scrub_env),  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    )
