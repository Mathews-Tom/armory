"""Unit tests for critic_pass.py — VLM critic pass for animate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from anthropic.types import TextBlock

import pytest

# Make the scripts directory importable without installing a package
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from critic_pass import (  # noqa: E402
    BudgetExceededError,
    MAX_FRAMES,
    _compute_timestamps,
    _extract_python_block,
    _load_critic_prompt,
    _parse_patch_list,
    _probe_duration,
    _sample_frames,
    main,
    run_critic_pass,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

SCENE_SOURCE = """\
from manim import *

class DemoScene(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
        self.wait()
"""

CRITIC_PROMPT_CONTENT = """\
# Critic Prompt
Review the scene frames and return layout patches as a JSON array followed by
a ```python ... ``` block with the full corrected scene.
"""

PATCH_LIST: list[dict[str, Any]] = [
    {
        "target_mobject": "circle",
        "anchor_constraint": "center",
        "reason": "circle drifts off-canvas",
        "patch_code": "circle.move_to(ORIGIN)",
    }
]

PATCHED_SCENE = """\
from manim import *

class DemoScene(Scene):
    def construct(self):
        circle = Circle()
        circle.move_to(ORIGIN)
        self.play(Create(circle))
        self.wait()
"""

VALID_RESPONSE = json.dumps(PATCH_LIST) + "\n\n```python\n" + PATCHED_SCENE + "```\n"


# ---------------------------------------------------------------------------
# Fake Anthropic client
# ---------------------------------------------------------------------------


class FakeAnthropicClient:
    """Minimal dependency-injection fake; records calls and returns canned responses."""

    def __init__(self, response_text: str = VALID_RESPONSE) -> None:
        self._response_text = response_text
        self.call_count = 0
        self.messages = self  # mirrors anthropic.Anthropic().messages.create(...)

    def create(self, **kwargs: Any) -> MagicMock:
        self.call_count += 1
        msg = MagicMock()
        msg.content = [TextBlock(type="text", text=self._response_text)]
        msg.usage = MagicMock()
        msg.usage.input_tokens = 1000
        msg.usage.output_tokens = 500
        return msg


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def _ffprobe_ok(duration: float = 10.0) -> MagicMock:
    r = MagicMock()
    r.returncode = 0
    r.stdout = f"{duration}\n"
    r.stderr = ""
    return r


def _ffprobe_fail() -> MagicMock:
    r = MagicMock()
    r.returncode = 1
    r.stdout = ""
    r.stderr = "ffprobe: No such file"
    return r


def _ffmpeg_ok_factory(write_png: bool = True) -> Any:
    """Returns a side_effect function for subprocess.run that handles ffprobe + ffmpeg."""

    def _run(cmd: list[str], **kwargs: Any) -> MagicMock:
        if "ffprobe" in cmd[0]:
            return _ffprobe_ok(10.0)
        # ffmpeg — write a minimal PNG so stat() works
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        if write_png:
            out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        return r

    return _run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def scene_file(tmp_path: Path) -> Path:
    p = tmp_path / "demo_scene.py"
    p.write_text(SCENE_SOURCE, encoding="utf-8")
    return p


@pytest.fixture()
def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "demo.mp4"
    p.write_bytes(b"\x00" * 16)
    return p


@pytest.fixture()
def prompt_file(tmp_path: Path) -> Path:
    p = tmp_path / "critic.md"
    p.write_text(CRITIC_PROMPT_CONTENT, encoding="utf-8")
    return p


@pytest.fixture()
def output_file(tmp_path: Path) -> Path:
    return tmp_path / "patched_scene.py"


# ---------------------------------------------------------------------------
# _compute_timestamps
# ---------------------------------------------------------------------------


class TestComputeTimestamps:
    def test_compute_timestamps_single_frame_returns_midpoint(self) -> None:
        # Arrange
        duration = 10.0
        # Act
        result = _compute_timestamps(duration, 1)
        # Assert
        assert result == [5.0]

    def test_compute_timestamps_five_frames_evenly_spaced(self) -> None:
        # Arrange / Act
        result = _compute_timestamps(10.0, 5)
        # Assert
        assert len(result) == 5
        assert result[0] == pytest.approx(1.0)
        assert result[-1] == pytest.approx(9.0)

    def test_compute_timestamps_all_within_duration(self) -> None:
        # Arrange / Act
        result = _compute_timestamps(7.5, 4)
        # Assert
        assert all(0 <= ts < 7.5 for ts in result)


# ---------------------------------------------------------------------------
# _probe_duration
# ---------------------------------------------------------------------------


class TestProbeDuration:
    def test_probe_duration_success_returns_float(self, video_file: Path) -> None:
        # Arrange
        fake = _ffprobe_ok(15.5)
        # Act
        with patch("subprocess.run", return_value=fake):
            result = _probe_duration(video_file)
        # Assert
        assert result == pytest.approx(15.5)

    def test_probe_duration_nonzero_exit_raises_runtime_error(
        self, video_file: Path
    ) -> None:
        # Arrange / Act / Assert
        with patch("subprocess.run", return_value=_ffprobe_fail()):
            with pytest.raises(RuntimeError, match="ffprobe failed"):
                _probe_duration(video_file)

    def test_probe_duration_non_numeric_output_raises_runtime_error(
        self, video_file: Path
    ) -> None:
        # Arrange
        bad = MagicMock()
        bad.returncode = 0
        bad.stdout = "N/A\n"
        bad.stderr = ""
        # Act / Assert
        with patch("subprocess.run", return_value=bad):
            with pytest.raises(RuntimeError, match="non-numeric duration"):
                _probe_duration(video_file)


# ---------------------------------------------------------------------------
# _sample_frames
# ---------------------------------------------------------------------------


class TestSampleFrames:
    def test_sample_frames_creates_expected_paths(
        self, tmp_path: Path, video_file: Path
    ) -> None:
        # Arrange
        frame_dir = tmp_path / "frames"
        frame_dir.mkdir()
        timestamps = [1.0, 5.0, 9.0]

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            out = Path(cmd[-1])
            out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            r = MagicMock()
            r.returncode = 0
            return r

        # Act
        with patch("subprocess.run", side_effect=fake_run):
            paths = _sample_frames(video_file, timestamps, frame_dir)

        # Assert
        assert len(paths) == 3
        assert all(p.exists() for p in paths)

    def test_sample_frames_ffmpeg_failure_raises_runtime_error(
        self, tmp_path: Path, video_file: Path
    ) -> None:
        # Arrange
        frame_dir = tmp_path / "frames"
        frame_dir.mkdir()
        bad = MagicMock()
        bad.returncode = 1
        bad.stderr = "Error: codec not found"
        # Act / Assert
        with patch("subprocess.run", return_value=bad):
            with pytest.raises(RuntimeError, match="ffmpeg failed"):
                _sample_frames(video_file, [1.0], frame_dir)


# ---------------------------------------------------------------------------
# _load_critic_prompt
# ---------------------------------------------------------------------------


class TestLoadCriticPrompt:
    def test_load_critic_prompt_returns_content(self, prompt_file: Path) -> None:
        # Arrange / Act
        result = _load_critic_prompt(prompt_file)
        # Assert
        assert "Critic Prompt" in result

    def test_load_critic_prompt_missing_file_raises_file_not_found(
        self, tmp_path: Path
    ) -> None:
        # Arrange / Act / Assert
        with pytest.raises(FileNotFoundError, match="Critic prompt not found"):
            _load_critic_prompt(tmp_path / "nonexistent.md")


# ---------------------------------------------------------------------------
# _parse_patch_list
# ---------------------------------------------------------------------------


class TestParsePatchList:
    def test_parse_patch_list_valid_json_returns_patches(self) -> None:
        # Arrange
        text = json.dumps(PATCH_LIST) + "\nExtra text"
        # Act
        result = _parse_patch_list(text)
        # Assert
        assert len(result) == 1
        assert result[0]["target_mobject"] == "circle"
        assert result[0]["anchor_constraint"] == "center"

    def test_parse_patch_list_missing_required_field_raises_value_error(self) -> None:
        # Arrange — patch missing 'reason'
        bad = [{"target_mobject": "x", "anchor_constraint": "c", "patch_code": "pass"}]
        # Act / Assert
        with pytest.raises(ValueError, match="missing required field"):
            _parse_patch_list(json.dumps(bad))

    def test_parse_patch_list_malformed_json_raises_value_error(self) -> None:
        # Arrange
        text = "[{bad json here}]"
        # Act / Assert
        with pytest.raises(ValueError, match="Malformed JSON"):
            _parse_patch_list(text)

    def test_parse_patch_list_no_array_in_response_raises_value_error(self) -> None:
        # Arrange
        text = "No JSON array here whatsoever."
        # Act / Assert
        with pytest.raises(ValueError, match="does not contain a JSON array"):
            _parse_patch_list(text)


# ---------------------------------------------------------------------------
# _extract_python_block
# ---------------------------------------------------------------------------


class TestExtractPythonBlock:
    def test_extract_python_block_returns_code_content(self) -> None:
        # Arrange
        text = "Some text\n```python\nprint('hi')\n```\nMore text"
        # Act
        result = _extract_python_block(text)
        # Assert
        assert result.strip() == "print('hi')"

    def test_extract_python_block_missing_block_raises_value_error(self) -> None:
        # Arrange
        text = "No fenced block here."
        # Act / Assert
        with pytest.raises(ValueError, match="fenced block"):
            _extract_python_block(text)


# ---------------------------------------------------------------------------
# run_critic_pass — integration-style tests
# ---------------------------------------------------------------------------


class TestRunCriticPass:
    def _full_run(
        self,
        scene_file: Path,
        video_file: Path,
        output_file: Path,
        prompt_file: Path,
        fake_client: FakeAnthropicClient,
        n_frames: int = 3,
        critic_budget: int = 50_000,
    ) -> tuple[list[Any], int]:
        with patch("subprocess.run", side_effect=_ffmpeg_ok_factory()):
            return run_critic_pass(
                scene_file=scene_file,
                video_file=video_file,
                output_path=output_file,
                n_frames=n_frames,
                critic_budget=critic_budget,
                model="test-model-override",
                prompt_path=prompt_file,
                client=fake_client,  # type: ignore[arg-type]
            )

    def test_run_critic_pass_happy_path_writes_patched_output(
        self,
        scene_file: Path,
        video_file: Path,
        output_file: Path,
        prompt_file: Path,
    ) -> None:
        # Arrange
        fake_client = FakeAnthropicClient(response_text=VALID_RESPONSE)
        # Act
        patches, tokens = self._full_run(
            scene_file, video_file, output_file, prompt_file, fake_client
        )
        # Assert
        assert len(patches) == 1
        assert patches[0]["target_mobject"] == "circle"
        assert tokens == 1500
        assert output_file.exists()
        assert "move_to(ORIGIN)" in output_file.read_text(encoding="utf-8")
        assert fake_client.call_count == 1

    def test_run_critic_pass_scene_file_missing_raises_file_not_found(
        self,
        tmp_path: Path,
        video_file: Path,
        output_file: Path,
        prompt_file: Path,
    ) -> None:
        # Arrange
        fake_client = FakeAnthropicClient()
        # Act / Assert
        with pytest.raises(FileNotFoundError, match="Scene file not found"):
            self._full_run(
                tmp_path / "ghost.py", video_file, output_file, prompt_file, fake_client
            )

    def test_run_critic_pass_video_file_missing_raises_file_not_found(
        self,
        scene_file: Path,
        tmp_path: Path,
        output_file: Path,
        prompt_file: Path,
    ) -> None:
        # Arrange
        fake_client = FakeAnthropicClient()
        # Act / Assert
        with pytest.raises(FileNotFoundError, match="Video file not found"):
            self._full_run(
                scene_file,
                tmp_path / "ghost.mp4",
                output_file,
                prompt_file,
                fake_client,
            )

    def test_run_critic_pass_prompt_missing_raises_file_not_found(
        self,
        scene_file: Path,
        video_file: Path,
        output_file: Path,
        tmp_path: Path,
    ) -> None:
        # Arrange
        fake_client = FakeAnthropicClient()
        # Act / Assert
        with patch("subprocess.run", side_effect=_ffmpeg_ok_factory()):
            with pytest.raises(FileNotFoundError, match="Critic prompt not found"):
                run_critic_pass(
                    scene_file=scene_file,
                    video_file=video_file,
                    output_path=output_file,
                    n_frames=3,
                    prompt_path=tmp_path / "no_critic.md",
                    client=fake_client,  # type: ignore[arg-type]
                )

    def test_run_critic_pass_budget_exceeded_raises_budget_exceeded_error(
        self,
        scene_file: Path,
        video_file: Path,
        output_file: Path,
        prompt_file: Path,
    ) -> None:
        # Arrange — budget of 1 ensures estimation always exceeds it
        fake_client = FakeAnthropicClient()
        # Act / Assert
        with patch("subprocess.run", side_effect=_ffmpeg_ok_factory()):
            with pytest.raises(BudgetExceededError, match="Estimated token count"):
                run_critic_pass(
                    scene_file=scene_file,
                    video_file=video_file,
                    output_path=output_file,
                    n_frames=3,
                    critic_budget=1,
                    prompt_path=prompt_file,
                    client=fake_client,  # type: ignore[arg-type]
                )
        # No API call should be made when budget is exceeded
        assert fake_client.call_count == 0

    def test_run_critic_pass_malformed_json_response_raises_value_error(
        self,
        scene_file: Path,
        video_file: Path,
        output_file: Path,
        prompt_file: Path,
    ) -> None:
        # Arrange
        bad_response = "[{bad json}]\n\n```python\npass\n```"
        fake_client = FakeAnthropicClient(response_text=bad_response)
        # Act / Assert
        with pytest.raises(ValueError, match="Malformed JSON"):
            self._full_run(
                scene_file, video_file, output_file, prompt_file, fake_client
            )

    def test_run_critic_pass_frame_count_clamped_to_max_frames(
        self,
        scene_file: Path,
        video_file: Path,
        output_file: Path,
        prompt_file: Path,
    ) -> None:
        # Arrange
        fake_client = FakeAnthropicClient(response_text=VALID_RESPONSE)
        ffmpeg_calls: list[list[str]] = []

        def counting_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            if "ffprobe" in cmd[0]:
                return _ffprobe_ok(10.0)
            ffmpeg_calls.append(cmd)
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
            r = MagicMock()
            r.returncode = 0
            return r

        # Act — request 20 frames (above MAX_FRAMES=10)
        with patch("subprocess.run", side_effect=counting_run):
            run_critic_pass(
                scene_file=scene_file,
                video_file=video_file,
                output_path=output_file,
                n_frames=20,
                prompt_path=prompt_file,
                client=fake_client,  # type: ignore[arg-type]
            )

        # Assert — exactly MAX_FRAMES ffmpeg invocations
        assert len(ffmpeg_calls) == MAX_FRAMES

    def test_run_critic_pass_ffprobe_failure_raises_runtime_error_no_client_call(
        self,
        scene_file: Path,
        video_file: Path,
        output_file: Path,
        prompt_file: Path,
    ) -> None:
        # Arrange
        fake_client = FakeAnthropicClient()
        # Act / Assert
        with patch("subprocess.run", return_value=_ffprobe_fail()):
            with pytest.raises(RuntimeError, match="ffprobe failed"):
                run_critic_pass(
                    scene_file=scene_file,
                    video_file=video_file,
                    output_path=output_file,
                    n_frames=3,
                    prompt_path=prompt_file,
                    client=fake_client,  # type: ignore[arg-type]
                )
        assert fake_client.call_count == 0


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_cli_without_critic_flag_exits_zero_with_no_client_call(
        self,
        scene_file: Path,
        video_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Arrange — no --critic flag; no client passed
        # Act
        with pytest.raises(SystemExit) as exc_info:
            main([str(scene_file), str(video_file)])
        # Assert
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "critic pass disabled" in captured.err

    def test_cli_without_critic_flag_exits_zero_even_with_nonexistent_files(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Arrange — files don't exist; without --critic the script never reads them
        # Act
        with pytest.raises(SystemExit) as exc_info:
            main([str(tmp_path / "ghost.py"), str(tmp_path / "ghost.mp4")])
        # Assert
        assert exc_info.value.code == 0
        assert "critic pass disabled" in capsys.readouterr().err
