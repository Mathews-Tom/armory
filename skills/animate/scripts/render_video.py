#!/usr/bin/env python3
"""
render_video.py — Render Manim scenes to video files with simplified CLI.

Wraps the Manim CLI to handle quality presets, output format, and file path
management (Manim's default output nesting is deep and unintuitive).

Usage:
    python3 render_video.py scene.py SceneName --quality high --format mp4
    python3 render_video.py scene.py SceneName --quality low --format gif --output /path/to/output.gif
    python3 render_video.py scene.py SceneName --max-fix-attempts 3
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _deps import require_binary, require_manim

QUALITY_MAP = {
    "low": ("-ql", "480p15"),
    "medium": ("-qm", "720p30"),
    "high": ("-qh", "1080p60"),
    "4k": ("-qk", "2160p60"),
}

FORMAT_MAP = {
    "mp4": "--format=mp4",
    "gif": "--format=gif",
    "webm": "--format=webm",
}

_MAX_FIX_ATTEMPTS_HARD_CAP = 3

# Match lines like:  File "/path/to/file.py", line 42, in ...
_TRACEBACK_LINE_RE = re.compile(r'File "([^"]+)", line (\d+)')

# Match the exception class on the last non-blank line of stderr
_EXCEPTION_CLASS_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning|Interrupt|KeyboardInterrupt|GeneratorExit|StopIteration|SystemExit))\s*(?::.*)?$",
    re.MULTILINE,
)


def find_rendered_file(
    media_dir: Path,
    scene_name: str,
    quality_dir: str,
    fmt: str,
    *,
    source_stem: str,
    manim_version: str,
) -> Path | None:
    """Locate only the requested source, quality and native output filename."""
    filename = (
        f"{scene_name}_ManimCE_v{manim_version}.gif"
        if fmt == "gif"
        else f"{scene_name}.{fmt}"
    )
    candidate = media_dir / "videos" / source_stem / quality_dir / filename
    return candidate if candidate.is_file() else None


def get_manim_version() -> str:
    """Return the actual version, preserving import and execution diagnostics."""
    require_manim()
    result = subprocess.run(
        [sys.executable, "-c", "import manim; print(manim.__version__)"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Manim import failed:\n{result.stderr or result.stdout}")
    version = result.stdout.strip()
    if not version:
        raise RuntimeError("Manim import returned no version")
    print(f"Manim version: {version}")
    return version


def parse_offending_lines(
    scene_path: Path,
    stderr: str,
) -> tuple[int, int] | None:
    """
    Extract an offending line range from a Manim traceback.

    Scans all ``File "...", line N`` entries that reference scene_path and
    returns a (start, end) tuple covering all of them with ±5 lines of
    context.  Returns None when no matching entry is found.
    """
    scene_str = str(scene_path)
    line_numbers: list[int] = []
    for m in _TRACEBACK_LINE_RE.finditer(stderr):
        if scene_str in m.group(1):
            line_numbers.append(int(m.group(2)))

    if not line_numbers:
        return None

    source_lines = len(scene_path.read_text(encoding="utf-8").splitlines())
    start = max(1, min(line_numbers) - 5)
    end = min(source_lines, max(line_numbers) + 5)
    return (start, end)


def extract_error_class(stderr: str) -> str:
    """
    Return the exception class name from stderr, or 'UnknownError'.
    """
    # Walk lines in reverse; the exception line is usually near the bottom
    for line in reversed(stderr.splitlines()):
        line = line.strip()
        if not line:
            continue
        m = _EXCEPTION_CLASS_RE.match(line)
        if m:
            return m.group(1)
    return "UnknownError"


def _diff_summary(original: str, patched: str) -> str:
    """Return a compact unified-diff summary (first 20 lines)."""
    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile="original",
            tofile="patched",
            n=1,
        )
    )
    summary = "".join(diff_lines[:20])
    if len(diff_lines) > 20:
        summary += f"\n... ({len(diff_lines) - 20} more diff lines)"
    return summary or "(no changes)"


def run_with_autofix(
    cmd: list[str],
    scene_path: Path,
    max_fix_attempts: int,
) -> subprocess.CompletedProcess[str]:
    """
    Run *cmd* and, on failure, invoke the LLM fixup loop up to
    *max_fix_attempts* times.

    When max_fix_attempts == 0 the function degrades exactly to a single
    ``subprocess.run`` call with ``capture_output=False`` — identical to the
    pre-autofix behaviour.

    On exhausting attempts without success the original subprocess result
    (first failure) is returned so that callers can inspect the exit code and
    raise accordingly.
    """
    if max_fix_attempts == 0:
        return subprocess.run(cmd, capture_output=False, text=True)

    # First attempt — capture stderr so we can feed it to the fixup client
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        # Print captured output now that we know it succeeded
        if result.stdout:
            print(result.stdout, end="")
        return result

    original_result = result
    log_path = scene_path.with_suffix("").with_name(
        scene_path.stem + ".render-log.jsonl"
    )

    # Deferred import — only needed when autofix is active
    from _fixup_client import request_patch  # noqa: PLC0415

    for attempt in range(1, max_fix_attempts + 1):
        stderr_text: str = result.stderr or ""
        error_class = extract_error_class(stderr_text)
        offending = parse_offending_lines(scene_path, stderr_text)

        print(
            f"\n[autofix] attempt {attempt}/{max_fix_attempts} — {error_class}",
            file=sys.stderr,
        )

        original_source = scene_path.read_text(encoding="utf-8")

        # Backup before patching
        backup_path = scene_path.with_suffix(f".bak.{attempt}")
        backup_path.write_text(original_source, encoding="utf-8")

        patched_source = request_patch(scene_path, stderr_text, offending)
        scene_path.write_text(patched_source, encoding="utf-8")

        # Log the attempt
        log_entry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "attempt": attempt,
            "error_class": error_class,
            "stderr_tail": stderr_text[-500:],
            "diff_summary": _diff_summary(original_source, patched_source),
        }
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(json.dumps(log_entry) + "\n")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[autofix] render succeeded on attempt {attempt}", file=sys.stderr)
            if result.stdout:
                print(result.stdout, end="")
            return result

    # All attempts exhausted — return first failure for the caller to handle
    return original_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Manim scene to video")
    parser.add_argument(
        "scene_file", help="Path to the .py file containing the Scene class"
    )
    parser.add_argument("scene_name", help="Name of the Scene class to render")
    parser.add_argument(
        "--quality",
        choices=QUALITY_MAP.keys(),
        default="high",
        help="Render quality preset (default: high)",
    )
    parser.add_argument(
        "--format",
        dest="fmt",
        choices=FORMAT_MAP.keys(),
        default="mp4",
        help="Output format (default: mp4)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path. If not specified, outputs next to scene file.",
    )
    parser.add_argument(
        "--media-dir",
        type=str,
        default=None,
        help="Custom media directory for Manim output",
    )
    parser.add_argument(
        "--max-fix-attempts",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Number of LLM-assisted auto-fix attempts on render failure "
            f"(0 = disabled, max {_MAX_FIX_ATTEMPTS_HARD_CAP}; default: 0)"
        ),
    )

    args = parser.parse_args()

    if args.max_fix_attempts < 0 or args.max_fix_attempts > _MAX_FIX_ATTEMPTS_HARD_CAP:
        parser.error(
            f"--max-fix-attempts must be between 0 and {_MAX_FIX_ATTEMPTS_HARD_CAP}"
        )

    scene_path = Path(args.scene_file).resolve()
    if not scene_path.exists():
        print(f"ERROR: Scene file not found: {scene_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).resolve() if args.output else None
    if output_path is not None and (
        output_path == scene_path
        or output_path.is_dir()
        or output_path.suffix.lower() != f".{args.fmt}"
    ):
        parser.error("output must be a matching-format file distinct from the scene")

    try:
        manim_version = get_manim_version()
        require_binary("ffmpeg")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    quality_flag, quality_dir = QUALITY_MAP[args.quality]
    format_flag = FORMAT_MAP[args.fmt]

    # Build manim command
    media_dir = Path(args.media_dir) if args.media_dir else scene_path.parent / "media"

    cmd = [
        sys.executable,
        "-m",
        "manim",
        "render",
        "--silent",  # Disable only Manim's PyPI version-notification request.
        quality_flag,
        format_flag,
        f"--media_dir={media_dir}",
        str(scene_path),
        args.scene_name,
    ]

    print(f"Rendering: {args.scene_name} @ {args.quality} quality ({args.fmt})")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = run_with_autofix(cmd, scene_path, args.max_fix_attempts)

    if result.returncode != 0:
        print(
            f"\nERROR: Manim render failed with exit code {result.returncode}",
            file=sys.stderr,
        )
        sys.exit(result.returncode)

    # Find the rendered file
    rendered = find_rendered_file(
        media_dir,
        args.scene_name,
        quality_dir,
        args.fmt,
        source_stem=scene_path.stem,
        manim_version=manim_version,
    )

    if not rendered:
        print(
            f"\nWARNING: Could not locate rendered file. Check {media_dir} manually.",
            file=sys.stderr,
        )
        # List what's there for debugging
        print("Contents of media dir:", file=sys.stderr)
        for p in sorted(media_dir.rglob("*")):
            if p.is_file():
                print(f"  {p} ({p.stat().st_size:,} bytes)", file=sys.stderr)
        sys.exit(1)

    # Copy to output location if specified
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path != rendered.resolve():
            shutil.copy2(rendered, output_path)
        final_path = output_path
    else:
        final_path = rendered

    size = final_path.stat().st_size
    print(f"\nRendered: {final_path}")
    print(f"  Quality:   {args.quality} ({quality_dir})")
    print(f"  Format:    {args.fmt}")
    print(f"  File size: {size:,} bytes ({size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
