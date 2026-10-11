#!/usr/bin/env python3
"""build_scene.py — config data -> Manim scene -> rendered, checked video. No model calls.

    build_scene.py config.json --out-dir out/ --quality low
    build_scene.py config.toml --out-dir out/ --generate-only
    build_scene.py config.json --out-dir out/ --quality high --audio music.mp3 --audio-volume 0.3

Config schema, bounds and examples: references/template-config.md.

Outputs in --out-dir:
    scene.py             generated Manim scene (the editable artifact)
    plan.json            template, expected duration, animation-call count, hashes
    scene.<fmt>          silent render (or scene-with-audio.mp4 with --audio)
    verification.json    decode/duration/fps/dimension report
    frames/              sampled PNG frames + review-receipt.json (status "pending")

Rendering delegates to render_video.py (max-fix-attempts 0) and audio to add_audio.py.
Metadata checks prove a decodable video of the planned shape, not that the layout
reads well: review the sampled frames, then record the verdict with verify_video.py attest.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from _deps import MissingDependencyError, require_binary, require_manim
from scene_templates import ConfigError, ScenePlan, build_plan, load_config
from verify_video import (
    MAX_SAMPLES,
    Expectation,
    QUALITY_GEOMETRY,
    ProbeError,
    expectation_from_plan,
    sample_frames,
    verify,
)

_SCRIPTS_DIR = Path(__file__).resolve().parent
_FORMATS = ("mp4", "webm")
_DEFAULT_SAMPLES = 5


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _run(label: str, cmd: Sequence[str]) -> int:
    print(f"[{label}] {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(list(cmd), check=False).returncode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate, render and check a Manim scene from validated config data (no model calls)."
    )
    parser.add_argument("config", type=Path, help="scene config (.json or .toml)")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--quality",
        choices=sorted(QUALITY_GEOMETRY),
        default="low",
        help="render preset (default: low, a fast preview)",
    )
    parser.add_argument("--format", dest="fmt", choices=_FORMATS, default="mp4")
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="write scene.py and plan.json, then stop (no Manim or ffmpeg needed)",
    )
    parser.add_argument("--audio", type=Path, help="audio file to overlay (mp4 only)")
    parser.add_argument("--audio-volume", type=float, default=1.0)
    parser.add_argument(
        "--samples",
        type=int,
        default=_DEFAULT_SAMPLES,
        help=f"frames to review, 0-{MAX_SAMPLES} (default {_DEFAULT_SAMPLES}; 0 skips sampling)",
    )
    return parser


def _write_scene(
    out_dir: Path, plan: ScenePlan, quality: str, fmt: str
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "frames" / "review-receipt.json").unlink(missing_ok=True)
    (out_dir / "verification.json").unlink(missing_ok=True)
    scene_path = out_dir / "scene.py"
    plan_path = out_dir / "plan.json"
    scene_path.write_text(plan.source, encoding="utf-8")
    _write_json(plan_path, {**plan.manifest(), "quality": quality, "format": fmt})
    return scene_path, plan_path


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.audio is not None and args.fmt != "mp4":
        print("ERROR: --audio supports mp4 output only", file=sys.stderr)
        return 2
    if args.audio is not None and (
        not math.isfinite(args.audio_volume) or args.audio_volume <= 0
    ):
        print("ERROR: --audio-volume must be finite and > 0", file=sys.stderr)
        return 2
    if not 0 <= args.samples <= MAX_SAMPLES:
        print(f"ERROR: --samples must be between 0 and {MAX_SAMPLES}", file=sys.stderr)
        return 2

    try:
        plan = build_plan(load_config(args.config))
    except ConfigError as exc:
        print(f"ERROR: invalid scene config: {exc}", file=sys.stderr)
        return 2

    out_dir: Path = args.out_dir
    scene_path, plan_path = _write_scene(out_dir, plan, args.quality, args.fmt)
    summary: dict[str, object] = {
        "scene": str(scene_path),
        "plan": str(plan_path),
        "expected_duration_s": plan.expected_duration_s,
    }
    if args.generate_only:
        print(json.dumps(summary, indent=2))
        return 0

    try:
        require_manim()
        require_binary("ffmpeg")
        require_binary("ffprobe")
        if args.audio is not None and not args.audio.is_file():
            print(f"ERROR: audio file not found: {args.audio}", file=sys.stderr)
            return 2
    except MissingDependencyError as exc:
        print(
            f"ERROR: {exc}\nThe scene was still written to {scene_path}.",
            file=sys.stderr,
        )
        return 3

    video_path = out_dir / f"scene.{args.fmt}"
    code = _run(
        "render",
        [
            sys.executable,
            str(_SCRIPTS_DIR / "render_video.py"),
            str(scene_path),
            plan.scene_class,
            "--quality",
            args.quality,
            "--format",
            args.fmt,
            "--output",
            str(video_path),
            "--media-dir",
            str(out_dir / "media"),
            "--max-fix-attempts",
            "0",
        ],
    )
    if code != 0:
        print(f"ERROR: render failed with exit code {code}", file=sys.stderr)
        return 1

    expected = expectation_from_plan(
        json.loads(plan_path.read_text(encoding="utf-8")), args.quality
    )
    silent_report = verify(video_path, expected)
    report_path = out_dir / "verification.json"
    if not silent_report.ok or silent_report.probe is None:
        _write_json(report_path, silent_report.to_dict())
        print(json.dumps(silent_report.to_dict(), indent=2))
        return 1

    final_path = video_path
    if args.audio is not None:
        final_path = out_dir / "scene-with-audio.mp4"
        code = _run(
            "audio",
            [
                sys.executable,
                str(_SCRIPTS_DIR / "add_audio.py"),
                str(video_path),
                str(args.audio),
                "--output",
                str(final_path),
                "--volume",
                str(args.audio_volume),
                "--trim-to-video",
            ],
        )
        if code != 0:
            print(f"ERROR: audio overlay failed with exit code {code}", file=sys.stderr)
            return 1

    if args.audio is not None:
        silent = silent_report.probe
        expected = Expectation(
            duration_s=silent.container_duration_s,
            duration_tolerance_s=1 / silent.fps + 0.05,
            fps=silent.fps,
            width=silent.width,
            height=silent.height,
            audio=True,
        )
        report = verify(final_path, expected)
        _write_json(
            report_path, {**report.to_dict(), "silent_render": silent_report.to_dict()}
        )
    else:
        report = silent_report
        _write_json(report_path, report.to_dict())
    failures = list(report.failures)
    summary.update(
        {
            "video": str(final_path),
            "verification": str(report_path),
            "verification_ok": report.ok,
        }
    )

    if args.samples > 0:
        try:
            sampled = sample_frames(final_path, args.samples, out_dir / "frames")
        except ProbeError as exc:
            failures.append(f"frame sampling failed: {exc}")
            summary["frame_review"] = "sampling failed"
        else:
            summary["review_receipt"] = str(sampled.receipt_path)
            summary["frame_review"] = "pending"
            if sampled.uniform_indices:
                summary["uniform_frame_indices"] = sampled.uniform_indices

    print(json.dumps(summary, indent=2))
    if failures:
        for failure in failures:
            print(f"VERIFY FAILED: {failure}", file=sys.stderr)
        return 1
    if args.samples:
        print(
            "Metadata checks passed. Layout is NOT verified: inspect every sampled frame, "
            "then run verify_video.py attest on the receipt.",
            file=sys.stderr,
        )
    else:
        print(
            "Metadata checks passed. Sampling was skipped; no frame-review receipt exists. "
            "Run verify_video.py sample and inspect every listed frame before attesting.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
