"""Unit tests for plan_storyboard.py — Planner stage."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from anthropic.types import TextBlock

# Make the scripts directory importable without installing
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from plan_storyboard import StoryboardPlanner, validate_storyboard  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_valid_storyboard(concept: str = "Test concept") -> dict[str, Any]:
    return {
        "concept": concept,
        "duration_estimate_seconds": 60,
        "scenes": [
            {
                "index": 0,
                "title": "Intro",
                "duration_seconds": 15,
                "beats": ["Show title", "Introduce concept"],
                "assets": [
                    {"kind": "icon", "query": "lightbulb", "required": True},
                    {"kind": "text", "query": "Hello World", "required": False},
                ],
            }
        ],
    }


def _fake_client(response_text: str) -> MagicMock:
    """Return a minimal fake Anthropic client that returns response_text from messages.create."""
    content_block = TextBlock(type="text", text=response_text)
    message = MagicMock()
    message.content = [content_block]
    client = MagicMock()
    client.messages.create.return_value = message
    return client


@pytest.fixture()
def prompt_file(tmp_path: Path) -> Path:
    """Write a minimal planner prompt template and return its path."""
    p = tmp_path / "planner.md"
    p.write_text("Plan this concept: {concept}", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# validate_storyboard — happy path
# ---------------------------------------------------------------------------


def test_validate_storyboard_valid_input_returns_dict() -> None:
    # Arrange
    data = _make_valid_storyboard()

    # Act
    result = validate_storyboard(data)

    # Assert
    assert result["concept"] == "Test concept"
    assert len(result["scenes"]) == 1


# ---------------------------------------------------------------------------
# validate_storyboard — schema violations
# ---------------------------------------------------------------------------


def test_validate_storyboard_missing_concept_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    del data["concept"]

    # Act / Assert
    with pytest.raises(ValueError, match="root.concept"):
        validate_storyboard(data)


def test_validate_storyboard_missing_duration_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    del data["duration_estimate_seconds"]

    # Act / Assert
    with pytest.raises(ValueError, match="root.duration_estimate_seconds"):
        validate_storyboard(data)


def test_validate_storyboard_empty_scenes_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    data["scenes"] = []

    # Act / Assert
    with pytest.raises(ValueError, match="root.scenes"):
        validate_storyboard(data)


def test_validate_storyboard_scenes_not_list_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    data["scenes"] = "not a list"

    # Act / Assert
    with pytest.raises(ValueError, match="root.scenes"):
        validate_storyboard(data)


def test_validate_storyboard_scene_missing_title_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    del data["scenes"][0]["title"]

    # Act / Assert
    with pytest.raises(ValueError, match=r"root\.scenes\[0\]\.title"):
        validate_storyboard(data)


def test_validate_storyboard_scene_missing_beats_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    del data["scenes"][0]["beats"]

    # Act / Assert
    with pytest.raises(ValueError, match=r"root\.scenes\[0\]\.beats"):
        validate_storyboard(data)


def test_validate_storyboard_scene_empty_beats_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    data["scenes"][0]["beats"] = []

    # Act / Assert
    with pytest.raises(ValueError, match=r"root\.scenes\[0\]\.beats"):
        validate_storyboard(data)


def test_validate_storyboard_asset_invalid_kind_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    data["scenes"][0]["assets"][0]["kind"] = "video"

    # Act / Assert
    with pytest.raises(ValueError, match=r"root\.scenes\[0\]\.assets\[0\]\.kind"):
        validate_storyboard(data)


def test_validate_storyboard_asset_missing_query_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    del data["scenes"][0]["assets"][0]["query"]

    # Act / Assert
    with pytest.raises(ValueError, match=r"root\.scenes\[0\]\.assets\[0\]\.query"):
        validate_storyboard(data)


def test_validate_storyboard_asset_required_not_bool_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    data["scenes"][0]["assets"][0]["required"] = "yes"

    # Act / Assert
    with pytest.raises(ValueError, match=r"root\.scenes\[0\]\.assets\[0\]\.required"):
        validate_storyboard(data)


def test_validate_storyboard_negative_duration_raises_value_error() -> None:
    # Arrange
    data = _make_valid_storyboard()
    data["duration_estimate_seconds"] = -5

    # Act / Assert
    with pytest.raises(ValueError, match="root.duration_estimate_seconds"):
        validate_storyboard(data)


def test_validate_storyboard_root_not_dict_raises_value_error() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="root"):
        validate_storyboard("not a dict")


# ---------------------------------------------------------------------------
# StoryboardPlanner.plan — happy path
# ---------------------------------------------------------------------------


def test_plan_valid_concept_returns_storyboard(prompt_file: Path) -> None:
    # Arrange
    storyboard = _make_valid_storyboard("Binary search algorithm")
    storyboard["concept"] = "Binary search algorithm"
    client = _fake_client(json.dumps(storyboard))
    planner = StoryboardPlanner(client=client, prompt_path=prompt_file)

    # Act
    result = planner.plan("Binary search algorithm")

    # Assert
    assert result["concept"] == "Binary search algorithm"
    assert result["scenes"][0]["index"] == 0
    client.messages.create.assert_called_once()


def test_plan_substitutes_concept_into_prompt(prompt_file: Path) -> None:
    # Arrange
    storyboard = _make_valid_storyboard("Fourier transform")
    storyboard["concept"] = "Fourier transform"
    client = _fake_client(json.dumps(storyboard))
    planner = StoryboardPlanner(client=client, prompt_path=prompt_file)

    # Act
    planner.plan("Fourier transform")

    # Assert — the prompt sent to the API contains the concept text
    call_kwargs = client.messages.create.call_args
    messages = call_kwargs.kwargs["messages"]
    assert "Fourier transform" in messages[0]["content"]


# ---------------------------------------------------------------------------
# StoryboardPlanner.plan — JSON parse failure
# ---------------------------------------------------------------------------


def test_plan_non_json_response_raises_value_error_with_raw_output(
    prompt_file: Path,
) -> None:
    # Arrange
    raw = "Sorry, I cannot generate a storyboard right now."
    client = _fake_client(raw)
    planner = StoryboardPlanner(client=client, prompt_path=prompt_file)

    # Act / Assert
    with pytest.raises(ValueError, match="non-JSON") as exc_info:
        planner.plan("some concept")
    assert raw in str(exc_info.value)


def test_plan_partial_json_raises_value_error(prompt_file: Path) -> None:
    # Arrange
    client = _fake_client('{"concept": "x"')  # truncated JSON
    planner = StoryboardPlanner(client=client, prompt_path=prompt_file)

    # Act / Assert
    with pytest.raises(ValueError, match="non-JSON"):
        planner.plan("some concept")


# ---------------------------------------------------------------------------
# StoryboardPlanner — prompt file loading
# ---------------------------------------------------------------------------


def test_plan_missing_prompt_file_raises_file_not_found_error() -> None:
    # Arrange
    client = _fake_client("{}")
    missing = Path("/tmp/does_not_exist_planner_prompt.md")
    planner = StoryboardPlanner(client=client, prompt_path=missing)

    # Act / Assert
    with pytest.raises(FileNotFoundError, match="Planner prompt not found"):
        planner.plan("any concept")


def test_plan_prompt_file_path_included_in_error_message() -> None:
    # Arrange
    client = _fake_client("{}")
    missing = Path("/tmp/no_such_prompt_xyz.md")
    planner = StoryboardPlanner(client=client, prompt_path=missing)

    # Act / Assert
    with pytest.raises(FileNotFoundError, match=str(missing)):
        planner.plan("any concept")


# ---------------------------------------------------------------------------
# StoryboardPlanner — model override
# ---------------------------------------------------------------------------


def test_plan_uses_custom_model_when_provided(prompt_file: Path) -> None:
    # Arrange
    storyboard = _make_valid_storyboard()
    client = _fake_client(json.dumps(storyboard))
    planner = StoryboardPlanner(
        client=client, model="test-model-override", prompt_path=prompt_file
    )

    # Act
    planner.plan("test concept")

    # Assert
    call_kwargs = client.messages.create.call_args
    assert call_kwargs.kwargs["model"] == "test-model-override"
