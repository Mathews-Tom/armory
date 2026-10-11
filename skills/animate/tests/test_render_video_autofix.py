"""
Tests for the auto-fix loop in render_video.py and _fixup_client.py.

All tests mock subprocess.run — no actual Manim invocations.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Make the scripts directory importable without installing
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from render_video import (  # noqa: E402
    extract_error_class,
    parse_offending_lines,
    run_with_autofix,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MANIM_CMD = [
    "python3",
    "-m",
    "manim",
    "render",
    "-qh",
    "--format=mp4",
    "--media_dir=/tmp",
    "scene.py",
    "MyScene",
]

SAMPLE_TRACEBACK = textwrap.dedent("""\
    Traceback (most recent call last):
      File "/usr/lib/python3.12/subprocess.py", line 1009, in run
        retcode = process.wait(timeout=timeout)
      File "/path/to/scene.py", line 5, in construct
        self.play(undefined_var.animate.shift(UP))
      File "/path/to/manim/animation.py", line 100, in play
        ...
    NameError: name 'undefined_var' is not defined
""")


@pytest.fixture()
def scene_file(tmp_path: Path) -> Path:
    """A minimal Manim scene file in a temp directory."""
    f = tmp_path / "scene.py"
    f.write_text(
        textwrap.dedent("""\
            from manim import *

            class MyScene(Scene):
                def construct(self):
                    circle = Circle()
                    self.play(Create(circle))
        """),
        encoding="utf-8",
    )
    return f


@pytest.fixture()
def coder_prompt_file(tmp_path: Path) -> Path:
    """A minimal stand-in coder.md prompt file."""
    refs = tmp_path / "references" / "code2video"
    refs.mkdir(parents=True)
    prompt = refs / "coder.md"
    prompt.write_text("# Fixup\nFix the Manim scene.", encoding="utf-8")
    return prompt


PATCHED_SCENE = textwrap.dedent("""\
    from manim import *

    class MyScene(Scene):
        def construct(self):
            square = Square()
            self.play(Create(square))
""")

FENCED_RESPONSE = f"Here is the fix:\n\n```python\n{PATCHED_SCENE}```\n"


# ---------------------------------------------------------------------------
# FakeAnthropicClient
# ---------------------------------------------------------------------------


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [SimpleNamespace(text=text)]


class FakeAnthropicClient:
    """Dependency-injected fake — returns canned response, no network."""

    def __init__(self, response_text: str = FENCED_RESPONSE) -> None:
        self.response_text = response_text
        self.messages = self  # mimic client.messages.create(...)
        self.call_count = 0

    def create(self, **kwargs: object) -> FakeMessage:  # noqa: ARG002
        self.call_count += 1
        return FakeMessage(self.response_text)


# ---------------------------------------------------------------------------
# Unit tests: extract_error_class
# ---------------------------------------------------------------------------


def test_extract_error_class_name_error_returns_correct_class() -> None:
    # Arrange
    stderr = SAMPLE_TRACEBACK

    # Act
    result = extract_error_class(stderr)

    # Assert
    assert result == "NameError"


def test_extract_error_class_unknown_stderr_returns_unknown_error() -> None:
    # Arrange
    stderr = "manim exited with some weird output"

    # Act
    result = extract_error_class(stderr)

    # Assert
    assert result == "UnknownError"


def test_extract_error_class_attribute_error_detected() -> None:
    # Arrange
    stderr = "AttributeError: 'NoneType' object has no attribute 'shift'"

    # Act
    result = extract_error_class(stderr)

    # Assert
    assert result == "AttributeError"


# ---------------------------------------------------------------------------
# Unit tests: parse_offending_lines
# ---------------------------------------------------------------------------


def test_parse_offending_lines_extracts_range_from_traceback(scene_file: Path) -> None:
    # Arrange — patch traceback to reference our scene_file
    stderr = SAMPLE_TRACEBACK.replace("/path/to/scene.py", str(scene_file))

    # Act
    result = parse_offending_lines(scene_file, stderr)

    # Assert
    assert result is not None
    start, end = result
    assert start <= 5 <= end  # line 5 must be within the extracted range


def test_parse_offending_lines_returns_none_when_no_match(scene_file: Path) -> None:
    # Arrange — traceback references a different file
    stderr = SAMPLE_TRACEBACK  # uses /path/to/scene.py, not scene_file

    # Act
    result = parse_offending_lines(scene_file, stderr)

    # Assert
    assert result is None


# ---------------------------------------------------------------------------
# Unit tests: _fixup_client.request_patch
# ---------------------------------------------------------------------------


def test_request_patch_returns_patched_scene_content(
    scene_file: Path,
    coder_prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import _fixup_client as fc

    monkeypatch.setattr(fc, "_CODER_PROMPT_PATH", coder_prompt_file)
    fake_client = FakeAnthropicClient()

    # Act
    result = fc.request_patch(scene_file, SAMPLE_TRACEBACK, None, client=fake_client)

    # Assert
    assert "Square" in result  # patched version swaps Circle → Square
    assert fake_client.call_count == 1


def test_request_patch_missing_prompt_file_raises_file_not_found(
    scene_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import _fixup_client as fc

    monkeypatch.setattr(fc, "_CODER_PROMPT_PATH", Path("/nonexistent/coder.md"))
    fake_client = FakeAnthropicClient()

    # Act / Assert
    with pytest.raises(FileNotFoundError):
        fc.request_patch(scene_file, "some error", None, client=fake_client)


def test_request_patch_no_fenced_block_raises_value_error(
    scene_file: Path,
    coder_prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — response has no ```python block
    import _fixup_client as fc

    monkeypatch.setattr(fc, "_CODER_PROMPT_PATH", coder_prompt_file)
    fake_client = FakeAnthropicClient(response_text="I cannot fix this scene.")

    # Act / Assert
    with pytest.raises(ValueError, match="no fenced"):
        fc.request_patch(scene_file, "some error", None, client=fake_client)


def test_request_patch_includes_offending_lines_in_prompt(
    scene_file: Path,
    coder_prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import _fixup_client as fc

    monkeypatch.setattr(fc, "_CODER_PROMPT_PATH", coder_prompt_file)

    captured_messages: list[dict[str, object]] = []

    class CapturingClient:
        def __init__(self) -> None:
            self.messages: CapturingClient = self

        def create(self, **kwargs: object) -> FakeMessage:
            captured_messages.append(dict(kwargs))
            return FakeMessage(FENCED_RESPONSE)

    # Act
    fc.request_patch(scene_file, "err", (3, 5), client=CapturingClient())

    # Assert
    assert captured_messages, "No API call made"
    content = str(captured_messages[0].get("messages", ""))
    assert "3" in content  # offending line range present


# ---------------------------------------------------------------------------
# Integration tests: run_with_autofix
# ---------------------------------------------------------------------------


def test_run_with_autofix_n0_does_not_call_fixup_on_failure(
    scene_file: Path,
) -> None:
    """N=0 must preserve exact current behavior — no fixup, no capture."""
    # Arrange
    failing_result = MagicMock()
    failing_result.returncode = 1

    with patch("render_video.subprocess.run", return_value=failing_result) as mock_run:
        # Act
        result = run_with_autofix(MANIM_CMD, scene_file, max_fix_attempts=0)

    # Assert
    mock_run.assert_called_once_with(MANIM_CMD, capture_output=False, text=True)
    assert result.returncode == 1


def test_run_with_autofix_n0_success_returns_result(scene_file: Path) -> None:
    """N=0 on success passes through the result unchanged."""
    # Arrange
    ok_result = MagicMock()
    ok_result.returncode = 0
    ok_result.stdout = ""

    with patch("render_video.subprocess.run", return_value=ok_result) as mock_run:
        # Act
        result = run_with_autofix(MANIM_CMD, scene_file, max_fix_attempts=0)

    # Assert
    mock_run.assert_called_once_with(MANIM_CMD, capture_output=False, text=True)
    assert result.returncode == 0


def test_run_with_autofix_n1_fixup_called_then_succeeds(
    scene_file: Path,
    coder_prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N=1: first render fails → fixup called → retry succeeds."""
    # Arrange
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = SAMPLE_TRACEBACK.replace("/path/to/scene.py", str(scene_file))
    fail_result.stdout = ""

    ok_result = MagicMock()
    ok_result.returncode = 0
    ok_result.stdout = ""

    import _fixup_client as fc

    monkeypatch.setattr(fc, "_CODER_PROMPT_PATH", coder_prompt_file)
    fake_client = FakeAnthropicClient()
    monkeypatch.setattr(fc, "AnthropicClient", lambda: fake_client)

    subprocess_results = iter([fail_result, ok_result])

    with patch(
        "render_video.subprocess.run",
        side_effect=lambda *a, **kw: next(subprocess_results),
    ):
        # Act
        result = run_with_autofix(MANIM_CMD, scene_file, max_fix_attempts=1)

    # Assert
    assert result.returncode == 0
    assert fake_client.call_count == 1  # fixup was called exactly once


def test_run_with_autofix_n1_backup_created_on_attempt(
    scene_file: Path,
    coder_prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backup file <scene>.bak.1 must exist after one fixup attempt."""
    # Arrange
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = SAMPLE_TRACEBACK.replace("/path/to/scene.py", str(scene_file))
    fail_result.stdout = ""

    ok_result = MagicMock()
    ok_result.returncode = 0
    ok_result.stdout = ""

    import _fixup_client as fc

    monkeypatch.setattr(fc, "_CODER_PROMPT_PATH", coder_prompt_file)
    fake_client = FakeAnthropicClient()
    monkeypatch.setattr(fc, "AnthropicClient", lambda: fake_client)

    subprocess_results = iter([fail_result, ok_result])

    with patch(
        "render_video.subprocess.run",
        side_effect=lambda *a, **kw: next(subprocess_results),
    ):
        run_with_autofix(MANIM_CMD, scene_file, max_fix_attempts=1)

    # Assert
    backup = scene_file.with_suffix(".bak.1")
    assert backup.exists(), f"Expected backup at {backup}"


def test_run_with_autofix_n3_persistent_failure_raises_original_error(
    scene_file: Path,
    coder_prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N=3 with all attempts failing returns original result (exit code != 0)."""
    # Arrange
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = SAMPLE_TRACEBACK.replace("/path/to/scene.py", str(scene_file))
    fail_result.stdout = ""

    import _fixup_client as fc

    monkeypatch.setattr(fc, "_CODER_PROMPT_PATH", coder_prompt_file)
    fake_client = FakeAnthropicClient()
    monkeypatch.setattr(fc, "AnthropicClient", lambda: fake_client)

    # 4 calls total: initial + 3 retries, all fail
    with patch("render_video.subprocess.run", return_value=fail_result):
        result = run_with_autofix(MANIM_CMD, scene_file, max_fix_attempts=3)

    # Assert — original error returned, not swallowed
    assert result.returncode == 1
    assert fake_client.call_count == 3  # tried all 3 patches


def test_run_with_autofix_n3_log_file_has_three_entries(
    scene_file: Path,
    coder_prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Log file must contain exactly 3 JSONL entries after 3 failed attempts."""
    # Arrange
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = SAMPLE_TRACEBACK.replace("/path/to/scene.py", str(scene_file))
    fail_result.stdout = ""

    import _fixup_client as fc

    monkeypatch.setattr(fc, "_CODER_PROMPT_PATH", coder_prompt_file)
    fake_client = FakeAnthropicClient()
    monkeypatch.setattr(fc, "AnthropicClient", lambda: fake_client)

    with patch("render_video.subprocess.run", return_value=fail_result):
        run_with_autofix(MANIM_CMD, scene_file, max_fix_attempts=3)

    # Assert
    log_path = scene_file.with_name(scene_file.stem + ".render-log.jsonl")
    assert log_path.exists(), f"Log file not found at {log_path}"

    entries = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert len(entries) == 3

    for i, entry in enumerate(entries, start=1):
        assert entry["attempt"] == i
        assert "error_class" in entry
        assert "stderr_tail" in entry
        assert "diff_summary" in entry
        assert "timestamp" in entry


def test_run_with_autofix_n3_backups_created_for_each_attempt(
    scene_file: Path,
    coder_prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backup files .bak.1, .bak.2, .bak.3 must all exist after 3 attempts."""
    # Arrange
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = SAMPLE_TRACEBACK.replace("/path/to/scene.py", str(scene_file))
    fail_result.stdout = ""

    import _fixup_client as fc

    monkeypatch.setattr(fc, "_CODER_PROMPT_PATH", coder_prompt_file)
    monkeypatch.setattr(fc, "AnthropicClient", lambda: FakeAnthropicClient())

    with patch("render_video.subprocess.run", return_value=fail_result):
        run_with_autofix(MANIM_CMD, scene_file, max_fix_attempts=3)

    # Assert
    for n in (1, 2, 3):
        backup = scene_file.with_suffix(f".bak.{n}")
        assert backup.exists(), f"Missing backup: {backup}"


def test_run_with_autofix_first_success_skips_fixup(
    scene_file: Path,
) -> None:
    """When initial render succeeds, no fixup is invoked regardless of N."""
    # Arrange
    ok_result = MagicMock()
    ok_result.returncode = 0
    ok_result.stdout = ""

    with patch("render_video.subprocess.run", return_value=ok_result) as mock_run:
        result = run_with_autofix(MANIM_CMD, scene_file, max_fix_attempts=3)

    # Assert
    assert result.returncode == 0
    mock_run.assert_called_once()  # no retry subprocess calls
