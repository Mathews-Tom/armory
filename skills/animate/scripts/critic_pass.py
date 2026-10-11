"""VLM critic pass: sample frames from a rendered video and apply layout patches."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import anthropic
from anthropic.types import (
    Base64ImageSourceParam,
    ImageBlockParam,
    MessageParam,
    TextBlock,
    TextBlockParam,
)

from _config import model_for

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = model_for("critic")
DEFAULT_FRAMES = 5
MAX_FRAMES = 10
DEFAULT_CRITIC_BUDGET = 50_000
_CRITIC_PROMPT_PATH = (
    Path(__file__).parent.parent / "references" / "code2video" / "critic.md"
)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class BudgetExceededError(RuntimeError):
    """Raised when the estimated token count for the critic call exceeds the budget."""


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Patch = dict[str, Any]


# ---------------------------------------------------------------------------
# Video utilities
# ---------------------------------------------------------------------------


def _probe_duration(video_path: Path) -> float:
    """Return video duration in seconds via ffprobe.  Raises RuntimeError on failure."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed (exit {result.returncode}) for {video_path}:\n"
            f"{result.stderr.strip()}"
        )
    raw = result.stdout.strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"ffprobe returned non-numeric duration {raw!r} for {video_path}"
        ) from exc


def _sample_frames(
    video_path: Path,
    timestamps: list[float],
    output_dir: Path,
) -> list[Path]:
    """Extract one PNG frame per timestamp using ffmpeg.  Returns sorted frame paths."""
    frame_paths: list[Path] = []
    for i, ts in enumerate(timestamps):
        out_path = output_dir / f"frame_{i:03d}.png"
        result = subprocess.run(
            [
                "ffmpeg",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(out_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed (exit {result.returncode}) extracting frame at {ts:.3f}s "
                f"from {video_path}:\n{result.stderr.strip()}"
            )
        frame_paths.append(out_path)
    return frame_paths


def _compute_timestamps(duration: float, n_frames: int) -> list[float]:
    """Return n_frames evenly-spaced timestamps within [0, duration)."""
    if n_frames == 1:
        return [duration / 2.0]
    step = duration / n_frames
    return [step * i + step / 2.0 for i in range(n_frames)]


# ---------------------------------------------------------------------------
# Prompt and request construction
# ---------------------------------------------------------------------------


def _load_critic_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Critic prompt not found: {prompt_path}. "
            "Ensure worker-p0 has vendored the prompt templates."
        )
    return prompt_path.read_text(encoding="utf-8")


def _encode_frame(frame_path: Path) -> str:
    return base64.standard_b64encode(frame_path.read_bytes()).decode("ascii")


def _build_message_content(
    scene_source: str,
    frame_paths: list[Path],
    critic_prompt: str,
) -> list[TextBlockParam | ImageBlockParam]:
    """Build the multi-modal content list for the Anthropic Messages API."""
    content: list[TextBlockParam | ImageBlockParam] = [
        TextBlockParam(
            type="text",
            text=(f"## Scene Source\n\n```python\n{scene_source}\n```\n\n"),
        )
    ]
    for i, fp in enumerate(frame_paths):
        source: Base64ImageSourceParam = Base64ImageSourceParam(
            type="base64",
            media_type="image/png",
            data=_encode_frame(fp),
        )
        content.append(ImageBlockParam(type="image", source=source))
        content.append(
            TextBlockParam(type="text", text=f"(frame {i + 1} of {len(frame_paths)})")
        )

    content.append(TextBlockParam(type="text", text=critic_prompt))
    return content


# ---------------------------------------------------------------------------
# Token budget estimation
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN_ESTIMATE = 4
_BYTES_PER_IMAGE_TOKEN_ESTIMATE = 800  # rough: ~1 token per 800 bytes of base64


def _estimate_tokens(
    scene_source: str, frame_paths: list[Path], critic_prompt: str
) -> int:
    """Rough token estimate to check against budget before making the API call."""
    text_chars = len(scene_source) + len(critic_prompt)
    text_tokens = text_chars // _CHARS_PER_TOKEN_ESTIMATE
    image_tokens = sum(
        fp.stat().st_size // _BYTES_PER_IMAGE_TOKEN_ESTIMATE for fp in frame_paths
    )
    return text_tokens + image_tokens


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _extract_python_block(text: str) -> str:
    """Extract content of the first ```python ... ``` fenced block."""
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if not match:
        raise ValueError(
            "Model response did not contain a ```python ... ``` fenced block. "
            f"Raw response:\n{text[:500]}"
        )
    return match.group(1)


def _parse_patch_list(text: str) -> list[Patch]:
    """Parse the JSON patch list from the response.

    Expected schema per patch:
    {
      "target_mobject": str,
      "anchor_constraint": str,
      "reason": str,
      "patch_code": str
    }
    """
    # Look for a JSON array in the response
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if not match:
        raise ValueError(
            f"Model response does not contain a JSON array of patches.\n"
            f"Raw response:\n{text[:500]}"
        )
    raw_json = match.group(0)
    try:
        patches = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Malformed JSON in model response: {exc}\n\nRaw JSON:\n{raw_json}"
        ) from exc
    if not isinstance(patches, list):
        raise ValueError(
            f"Expected JSON array of patches, got {type(patches).__name__}"
        )
    for i, patch in enumerate(patches):
        for field in ("target_mobject", "anchor_constraint", "reason", "patch_code"):
            if field not in patch:
                raise ValueError(
                    f"Patch [{i}] missing required field {field!r}. "
                    f"Patch content: {patch!r}"
                )
    return patches


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------


def run_critic_pass(
    scene_file: Path,
    video_file: Path,
    output_path: Path,
    *,
    n_frames: int = DEFAULT_FRAMES,
    critic_budget: int = DEFAULT_CRITIC_BUDGET,
    model: str = DEFAULT_MODEL,
    prompt_path: Path = _CRITIC_PROMPT_PATH,
    client: anthropic.Anthropic | None = None,
) -> tuple[list[Patch], int]:
    """Run the VLM critic pass.

    Samples frames from video_file, queries the model with the scene source
    and frames, parses the layout patches, writes the patched scene to
    output_path.

    Returns (patches, tokens_used).
    Raises BudgetExceededError if estimated tokens exceed critic_budget.
    Raises FileNotFoundError if scene_file or prompt_path is missing.
    Raises RuntimeError on ffprobe/ffmpeg failure.
    Raises ValueError on malformed model response.
    """
    if not scene_file.exists():
        raise FileNotFoundError(f"Scene file not found: {scene_file}")
    if not video_file.exists():
        raise FileNotFoundError(f"Video file not found: {video_file}")

    n_frames = min(n_frames, MAX_FRAMES)
    scene_source = scene_file.read_text(encoding="utf-8")
    critic_prompt = _load_critic_prompt(prompt_path)

    duration = _probe_duration(video_file)
    timestamps = _compute_timestamps(duration, n_frames)

    actual_client = client if client is not None else anthropic.Anthropic()

    with tempfile.TemporaryDirectory(prefix="critic_frames_") as tmp_dir:
        frame_paths = _sample_frames(video_file, timestamps, Path(tmp_dir))

        estimated = _estimate_tokens(scene_source, frame_paths, critic_prompt)
        if estimated > critic_budget:
            raise BudgetExceededError(
                f"Estimated token count {estimated} exceeds critic budget {critic_budget}. "
                "Increase --critic-budget or reduce --frames."
            )

        content = _build_message_content(scene_source, frame_paths, critic_prompt)
        messages: list[MessageParam] = [MessageParam(role="user", content=content)]
        response = actual_client.messages.create(
            model=model,
            max_tokens=4096,
            messages=messages,
        )

    first_block = response.content[0]
    if not isinstance(first_block, TextBlock):
        raise ValueError(
            f"Unexpected first content block type {type(first_block).__name__!r}; "
            "expected a text block."
        )
    response_text: str = first_block.text
    tokens_used: int = response.usage.input_tokens + response.usage.output_tokens

    patches = _parse_patch_list(response_text)
    patched_source = _extract_python_block(response_text)

    output_path.write_text(patched_source, encoding="utf-8")
    return patches, tokens_used


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "VLM critic pass: sample frames from a rendered Manim video, "
            "query a vision model for layout defects, and apply patches."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("scene_file", type=Path, help="Path to the scene Python file")
    parser.add_argument("rendered_video", type=Path, help="Path to the rendered MP4")
    parser.add_argument(
        "--frames",
        type=int,
        default=DEFAULT_FRAMES,
        metavar="N",
        help=f"Number of frames to sample (default: {DEFAULT_FRAMES}, max: {MAX_FRAMES})",
    )
    parser.add_argument(
        "--critic",
        action="store_true",
        default=False,
        help="Enable the critic pass (default: disabled)",
    )
    parser.add_argument(
        "--critic-budget",
        type=int,
        default=DEFAULT_CRITIC_BUDGET,
        metavar="TOKENS",
        help=f"Maximum token budget for the critic call (default: {DEFAULT_CRITIC_BUDGET})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        metavar="MODEL",
        help=f"Anthropic model ID (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write patched scene to this path (default: overwrite scene_file)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if not args.critic:
        print("critic pass disabled", file=sys.stderr)
        sys.exit(0)

    output_path: Path = args.output if args.output is not None else args.scene_file

    patches, tokens_used = run_critic_pass(
        scene_file=args.scene_file,
        video_file=args.rendered_video,
        output_path=output_path,
        n_frames=args.frames,
        critic_budget=args.critic_budget,
        model=args.model,
    )
    print(
        f"critic applied {len(patches)} patches, tokens used: {tokens_used}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
