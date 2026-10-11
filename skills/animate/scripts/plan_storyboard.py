"""Planner stage: concept text → storyboard JSON via Anthropic Messages API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import anthropic
from anthropic.types import TextBlock

from _config import model_for

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Asset = dict[str, Any]
Beat = str
Scene = dict[str, Any]
Storyboard = dict[str, Any]

# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

_VALID_ASSET_KINDS: frozenset[str] = frozenset({"icon", "image", "text"})


def _validate_asset(asset: Any, path: str) -> None:
    if not isinstance(asset, dict):
        raise ValueError(f"{path}: expected object, got {type(asset).__name__}")
    for field in ("kind", "query", "required"):
        if field not in asset:
            raise ValueError(f"{path}.{field}: required field missing")
    if asset["kind"] not in _VALID_ASSET_KINDS:
        raise ValueError(
            f"{path}.kind: must be one of {sorted(_VALID_ASSET_KINDS)!r}, "
            f"got {asset['kind']!r}"
        )
    if not isinstance(asset["query"], str) or not asset["query"].strip():
        raise ValueError(f"{path}.query: must be a non-empty string")
    if not isinstance(asset["required"], bool):
        raise ValueError(f"{path}.required: must be a boolean")


def _validate_scene(scene: Any, path: str) -> None:
    if not isinstance(scene, dict):
        raise ValueError(f"{path}: expected object, got {type(scene).__name__}")
    for field in ("index", "title", "duration_seconds", "beats", "assets"):
        if field not in scene:
            raise ValueError(f"{path}.{field}: required field missing")
    if not isinstance(scene["index"], int):
        raise ValueError(f"{path}.index: must be an integer")
    if not isinstance(scene["title"], str) or not scene["title"].strip():
        raise ValueError(f"{path}.title: must be a non-empty string")
    if (
        not isinstance(scene["duration_seconds"], int | float)
        or scene["duration_seconds"] <= 0
    ):
        raise ValueError(f"{path}.duration_seconds: must be a positive number")
    if not isinstance(scene["beats"], list) or len(scene["beats"]) == 0:
        raise ValueError(f"{path}.beats: must be a non-empty list")
    for i, beat in enumerate(scene["beats"]):
        if not isinstance(beat, str):
            raise ValueError(f"{path}.beats[{i}]: must be a string")
    if not isinstance(scene["assets"], list):
        raise ValueError(f"{path}.assets: must be a list")
    for i, asset in enumerate(scene["assets"]):
        _validate_asset(asset, f"{path}.assets[{i}]")


def validate_storyboard(data: Any) -> Storyboard:
    """Validate a parsed storyboard dict.  Raises ValueError with field path on violation."""
    if not isinstance(data, dict):
        raise ValueError(f"root: expected object, got {type(data).__name__}")
    for field in ("concept", "duration_estimate_seconds", "scenes"):
        if field not in data:
            raise ValueError(f"root.{field}: required field missing")
    if not isinstance(data["concept"], str) or not data["concept"].strip():
        raise ValueError("root.concept: must be a non-empty string")
    if (
        not isinstance(data["duration_estimate_seconds"], int | float)
        or data["duration_estimate_seconds"] <= 0
    ):
        raise ValueError("root.duration_estimate_seconds: must be a positive number")
    if not isinstance(data["scenes"], list) or len(data["scenes"]) == 0:
        raise ValueError("root.scenes: must be a non-empty list")
    for i, scene in enumerate(data["scenes"]):
        _validate_scene(scene, f"root.scenes[{i}]")
    return data


# ---------------------------------------------------------------------------
# Core planner
# ---------------------------------------------------------------------------

DEFAULT_MODEL = model_for("planner")
_PROMPT_PATH = Path(__file__).parent.parent / "references" / "code2video" / "planner.md"


class StoryboardPlanner:
    """Wraps the Anthropic client to produce storyboard JSON from a concept."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str = DEFAULT_MODEL,
        prompt_path: Path = _PROMPT_PATH,
    ) -> None:
        self._client = client
        self._model = model
        self._prompt_path = prompt_path

    def _load_prompt(self, concept: str) -> str:
        if not self._prompt_path.exists():
            raise FileNotFoundError(
                f"Planner prompt not found: {self._prompt_path}. "
                "Run worker-p0 first to vendor the prompt templates."
            )
        template = self._prompt_path.read_text(encoding="utf-8")
        return template.replace("{concept}", concept)

    def plan(self, concept: str) -> Storyboard:
        """Call the model and return a validated storyboard dict."""
        prompt = self._load_prompt(concept)
        message = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        first_block = message.content[0]
        if not isinstance(first_block, TextBlock):
            raise ValueError(
                f"Expected TextBlock from model, got {type(first_block).__name__}"
            )
        raw: str = first_block.text
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Model returned non-JSON output. Parse error: {exc}\n\nRaw output:\n{raw}"
            ) from exc
        return validate_storyboard(data)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a storyboard JSON from a concept string.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("concept", help="Concept text to storyboard")
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write storyboard JSON to this file (default: stdout)",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        default=DEFAULT_MODEL,
        help=f"Anthropic model ID (default: {DEFAULT_MODEL})",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    client = anthropic.Anthropic()
    planner = StoryboardPlanner(client=client, model=args.model)
    storyboard = planner.plan(args.concept)
    serialized = json.dumps(storyboard, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    else:
        sys.stdout.write(serialized + "\n")


if __name__ == "__main__":
    main()
