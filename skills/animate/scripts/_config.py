"""Load model identifiers for the animate pipeline from config.toml."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "config.toml"


@cache
def _load() -> dict[str, str]:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"config.toml not found at {_CONFIG_PATH}. "
            "The skill directory is missing its model configuration."
        )
    with _CONFIG_PATH.open("rb") as fh:
        data = tomllib.load(fh)
    models = data.get("models")
    if not isinstance(models, dict):
        raise ValueError(f"{_CONFIG_PATH}: [models] section is required")
    return {str(k): str(v) for k, v in models.items()}


def model_for(stage: str) -> str:
    """Return the configured model identifier for a pipeline stage."""
    models = _load()
    if stage not in models:
        raise KeyError(
            f"config.toml: no model configured for stage {stage!r}. "
            f"Configured stages: {sorted(models)}"
        )
    return models[stage]
