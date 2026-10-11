#!/usr/bin/env python3
"""verify_video.py — deterministic output checks and a frame-review receipt.

Subcommands (ffmpeg and ffprobe required; no model, no network):

    verify_video.py check VIDEO --plan plan.json --quality low
    verify_video.py check VIDEO --expect-duration 8.5 --duration-tolerance 0.4 \\
        --expect-fps 15 --expect-width 854 --expect-height 480
    verify_video.py sample VIDEO --count 5 --out-dir frames/
    verify_video.py attest frames/review-receipt.json --reviewer "name" \\
        --verdict pass --notes "labels readable, nothing clipped"

``check`` decodes every frame (ffprobe -count_frames) and compares duration,
frame rate, dimensions and decoded-frame count with the expectation. Passing
proves the file is a decodable video of the expected shape. It does NOT prove
the layout is readable: that needs a person or vision model to look at the
frames written by ``sample`` and record the verdict with ``attest``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Final, NamedTuple

from _deps import MissingDependencyError, require_binary

RECEIPT_SCHEMA: Final = "animate.frame-review/1"
RECEIPT_LIMITS: Final = (
    "The receipt binds extracted frames to exact video bytes and records a "
    "reviewer's verdict. Metadata and luma statistics do not prove layout, text "
    "legibility or meaning. The recorded review is limited to sampled frames "
    "and is not proof of complete visual or semantic correctness."
)
MAX_SAMPLES: Final = 30
FPS_TOLERANCE: Final = 0.01


class Geometry(NamedTuple):
    width: int
    height: int
    fps: int


# Manim quality presets (render_video.py QUALITY_MAP keys).
QUALITY_GEOMETRY: Final[dict[str, Geometry]] = {
    "low": Geometry(854, 480, 15),
    "medium": Geometry(1280, 720, 30),
    "high": Geometry(1920, 1080, 60),
    "4k": Geometry(3840, 2160, 60),
}


class ProbeError(RuntimeError):
    """ffprobe/ffmpeg could not read or decode the file."""


@dataclass(frozen=True)
class VideoProbe:
    path: Path
    container_duration_s: float
    width: int
    height: int
    fps: float
    frames_decoded: int
    video_codec: str
    audio_codec: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "container_duration_s": self.container_duration_s,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "frames_decoded": self.frames_decoded,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
        }


@dataclass(frozen=True)
class Expectation:
    duration_s: float | None = None
    duration_tolerance_s: float = 0.0
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    audio: bool = False

    def __post_init__(self) -> None:
        for name, value in (("duration_s", self.duration_s), ("fps", self.fps)):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
        if (
            not math.isfinite(self.duration_tolerance_s)
            or self.duration_tolerance_s < 0
        ):
            raise ValueError("duration_tolerance_s must be finite and non-negative")
        for name, size in (("width", self.width), ("height", self.height)):
            if size is not None and (
                isinstance(size, bool) or not isinstance(size, int) or size <= 0
            ):
                raise ValueError(f"{name} must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "duration_s": self.duration_s,
            "duration_tolerance_s": self.duration_tolerance_s,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "audio": self.audio,
        }


def duration_tolerance(animation_calls: int, fps: float) -> float:
    """Worst-case drift: Manim rounds every play/wait to a whole frame, plus container slack."""
    return (animation_calls + 1) / fps + 0.05


def expectation_from_plan(
    plan: Mapping[str, object], quality: str, *, audio: bool = False
) -> Expectation:
    """Expectation for a build_scene plan.json rendered at *quality*."""
    if quality not in QUALITY_GEOMETRY:
        raise ValueError(
            f"quality must be one of {sorted(QUALITY_GEOMETRY)}, got {quality!r}"
        )
    duration = plan.get("expected_duration_s")
    calls = plan.get("animation_calls")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or duration <= 0
    ):
        raise ValueError("plan.expected_duration_s must be a positive number")
    if isinstance(calls, bool) or not isinstance(calls, int) or calls < 0:
        raise ValueError("plan.animation_calls must be a non-negative integer")
    geometry = QUALITY_GEOMETRY[quality]
    return Expectation(
        duration_s=float(duration),
        duration_tolerance_s=duration_tolerance(calls, geometry.fps),
        fps=float(geometry.fps),
        width=geometry.width,
        height=geometry.height,
        audio=audio,
    )


# ── Probing ────────────────────────────────────────────────────────────────


def _parse_rate(value: object) -> float:
    if not isinstance(value, str) or "/" not in value:
        return 0.0
    num, _, den = value.partition("/")
    try:
        fraction = Fraction(int(num), int(den))
    except (ValueError, ZeroDivisionError):
        return 0.0
    return float(fraction)


def _as_int(value: object, what: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    raise ProbeError(f"ffprobe returned no usable {what}: {value!r}")


def probe_video(path: Path) -> VideoProbe:
    """Decode *path* completely and return its measured properties."""
    require_binary("ffprobe")
    if not path.is_file():
        raise ProbeError(f"video not found: {path}")
    if path.stat().st_size == 0:
        raise ProbeError(f"video is empty (0 bytes): {path}")
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,nb_read_frames"
            ":format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or result.stderr.strip():
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise ProbeError(f"ffprobe could not fully decode {path}: {detail[:500]}")
    try:
        data: object = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe produced invalid JSON for {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProbeError(f"ffprobe produced unexpected output for {path}")

    streams_raw = data.get("streams")
    streams = (
        [s for s in streams_raw if isinstance(s, dict)]
        if isinstance(streams_raw, list)
        else []
    )
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError(f"no video stream in {path}")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    fmt = data.get("format")
    raw_duration = fmt.get("duration") if isinstance(fmt, dict) else None
    try:
        duration = float(str(raw_duration))
    except ValueError as exc:
        raise ProbeError(
            f"container duration unavailable for {path}: {raw_duration!r}"
        ) from exc

    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(
        video.get("r_frame_rate")
    )
    return VideoProbe(
        path=path,
        container_duration_s=duration,
        width=_as_int(video.get("width"), "width"),
        height=_as_int(video.get("height"), "height"),
        fps=fps,
        frames_decoded=_as_int(video.get("nb_read_frames"), "decoded frame count"),
        video_codec=str(video.get("codec_name", "unknown")),
        audio_codec=str(audio.get("codec_name", "unknown"))
        if audio is not None
        else None,
    )


def check_probe(probe: VideoProbe, expected: Expectation) -> list[str]:
    """Return human-readable failures; an empty list means every check passed."""
    failures: list[str] = []
    if probe.frames_decoded <= 0:
        failures.append("decoded 0 video frames")
    if expected.width is not None and probe.width != expected.width:
        failures.append(f"width {probe.width} != expected {expected.width}")
    if expected.height is not None and probe.height != expected.height:
        failures.append(f"height {probe.height} != expected {expected.height}")
    if expected.fps is not None and abs(probe.fps - expected.fps) > FPS_TOLERANCE:
        failures.append(f"frame rate {probe.fps:g} != expected {expected.fps:g}")
    if expected.duration_s is not None:
        drift = probe.container_duration_s - expected.duration_s
        if abs(drift) > expected.duration_tolerance_s:
            failures.append(
                f"duration {probe.container_duration_s:.3f}s differs from expected "
                f"{expected.duration_s:.3f}s by {drift:+.3f}s "
                f"(tolerance {expected.duration_tolerance_s:.3f}s)"
            )
        if probe.fps > 0:
            expected_frames = expected.duration_s * probe.fps
            allowed = expected.duration_tolerance_s * probe.fps + 1
            if abs(probe.frames_decoded - expected_frames) > allowed:
                failures.append(
                    f"decoded {probe.frames_decoded} frames, expected about "
                    f"{expected_frames:.0f} (+/-{allowed:.0f})"
                )
    if expected.audio and probe.audio_codec is None:
        failures.append("expected an audio stream but none was found")
    return failures


@dataclass(frozen=True)
class Report:
    ok: bool
    failures: list[str]
    probe: VideoProbe | None
    expected: Expectation

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "failures": self.failures,
            "probe": self.probe.to_dict() if self.probe is not None else None,
            "expected": self.expected.to_dict(),
        }


@dataclass(frozen=True)
class SampleResult:
    receipt_path: Path
    receipt: dict[str, object]
    uniform_indices: list[int]


def verify(path: Path, expected: Expectation) -> Report:
    """Probe *path* and compare it with *expected*; a ProbeError becomes a failure."""
    try:
        probe = probe_video(path)
    except ProbeError as exc:
        return Report(ok=False, failures=[str(exc)], probe=None, expected=expected)
    failures = check_probe(probe, expected)
    return Report(ok=not failures, failures=failures, probe=probe, expected=expected)


# ── Frame sampling and review receipt ──────────────────────────────────────

_LUMA_RE: Final = {
    name: re.compile(rf"lavfi\.signalstats\.{name}=(\d+(?:\.\d+)?)")
    for name in ("YMIN", "YMAX")
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sample_times(duration_s: float, count: int) -> list[float]:
    """Midpoints of *count* equal segments; never t=0, which is usually a blank first frame."""
    if not 1 <= count <= MAX_SAMPLES:
        raise ValueError(
            f"sample count must be between 1 and {MAX_SAMPLES}, got {count}"
        )
    if duration_s <= 0:
        raise ValueError(f"duration must be positive, got {duration_s}")
    return [round(duration_s * (i + 0.5) / count, 3) for i in range(count)]


def _luma_range(frame: Path) -> tuple[float, float]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(frame),
            "-vf",
            "signalstats,metadata=mode=print:file=-",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    values: list[float] = []
    for name in ("YMIN", "YMAX"):
        match = _LUMA_RE[name].search(result.stdout)
        if result.returncode != 0 or match is None:
            raise ProbeError(
                f"could not measure luma of {frame}: {result.stderr.strip()[:300]}"
            )
        values.append(float(match.group(1)))
    return values[0], values[1]


def sample_frames(video: Path, count: int, out_dir: Path) -> SampleResult:
    """Extract *count* PNG frames and write ``review-receipt.json`` next to them."""
    require_binary("ffmpeg")
    probe = probe_video(video)
    times = sample_times(probe.container_duration_s, count)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = out_dir / "review-receipt.json"
    receipt_path.unlink(missing_ok=True)
    for stale in out_dir.glob("frame-*.png"):
        stale.unlink()

    samples: list[dict[str, object]] = []
    for index, time_s in enumerate(times):
        frame = out_dir / f"frame-{index:02d}.png"
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                f"{time_s:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                str(frame),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not frame.is_file() or frame.stat().st_size == 0:
            raise ProbeError(
                f"could not extract a frame at {time_s:.3f}s from {video}: "
                f"{result.stderr.strip()[:300]}"
            )
        luma_min, luma_max = _luma_range(frame)
        samples.append(
            {
                "index": index,
                "time_s": time_s,
                "path": os.path.relpath(frame, out_dir),
                "sha256": sha256_file(frame),
                "bytes": frame.stat().st_size,
                "luma_min": luma_min,
                "luma_max": luma_max,
                "uniform": luma_min == luma_max,
            }
        )

    receipt: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "video": {
            "path": str(video.resolve()),
            "sha256": sha256_file(video),
            "bytes": video.stat().st_size,
        },
        "probe": probe.to_dict(),
        "samples": samples,
        "review": {
            "status": "pending",
            "reviewer": None,
            "notes": None,
            "reviewed_at": None,
        },
        "limits": RECEIPT_LIMITS,
    }
    _write_json_atomic(receipt_path, receipt)
    return SampleResult(
        receipt_path=receipt_path,
        receipt=receipt,
        uniform_indices=[i for i, s in enumerate(samples) if s["uniform"]],
    )


def _write_json_atomic(path: Path, data: Mapping[str, object]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _object(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"receipt {what} is not an object")
    return {str(k): v for k, v in value.items()}


def attest(
    receipt_path: Path, reviewer: str, verdict: str, notes: str
) -> dict[str, object]:
    """Record a review verdict after proving the receipt still matches the files on disk."""
    if verdict not in ("pass", "fail"):
        raise ValueError(f"verdict must be 'pass' or 'fail', got {verdict!r}")
    if not reviewer.strip():
        raise ValueError(
            "reviewer must name the person or model that inspected the frames"
        )
    try:
        loaded: object = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read receipt {receipt_path}: {exc}") from exc
    receipt = _object(loaded, "root")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError(f"receipt schema must be {RECEIPT_SCHEMA!r}")

    video = _object(receipt.get("video"), "video")
    video_path = Path(str(video.get("path")))
    if not video_path.is_file() or sha256_file(video_path) != video.get("sha256"):
        raise ValueError(
            f"video {video_path} is missing or changed since sampling; re-run sample"
        )
    samples = receipt.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("receipt has no samples")
    for raw in samples:
        sample = _object(raw, "sample")
        frame = receipt_path.parent / str(sample.get("path"))
        if not frame.is_file() or sha256_file(frame) != sample.get("sha256"):
            raise ValueError(
                f"frame {frame} is missing or changed since sampling; re-run sample"
            )

    receipt["review"] = {
        "status": verdict,
        "reviewer": reviewer,
        "notes": notes,
        "reviewed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _write_json_atomic(receipt_path, receipt)
    return receipt


# ── CLI ────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check", help="decode a video and compare it with expectations"
    )
    check.add_argument("video", type=Path)
    check.add_argument("--plan", type=Path, help="plan.json written by build_scene.py")
    check.add_argument(
        "--quality", choices=sorted(QUALITY_GEOMETRY), help="required with --plan"
    )
    check.add_argument("--expect-duration", type=float)
    check.add_argument("--duration-tolerance", type=float)
    check.add_argument("--expect-fps", type=float)
    check.add_argument("--expect-width", type=int)
    check.add_argument("--expect-height", type=int)
    check.add_argument("--expect-audio", action="store_true")
    check.add_argument("--report", type=Path, help="also write the JSON report here")

    sample = sub.add_parser(
        "sample", help="extract evenly spaced frames and a review receipt"
    )
    sample.add_argument("video", type=Path)
    sample.add_argument("--count", type=int, default=5)
    sample.add_argument("--out-dir", type=Path, required=True)

    att = sub.add_parser("attest", help="record a frame-review verdict in a receipt")
    att.add_argument("receipt", type=Path)
    att.add_argument("--reviewer", required=True)
    att.add_argument("--verdict", choices=("pass", "fail"), required=True)
    att.add_argument("--notes", default="")
    return parser


def _expectation_from_args(args: argparse.Namespace) -> Expectation:
    base = Expectation(audio=bool(args.expect_audio))
    if args.plan is not None:
        if args.quality is None:
            raise ValueError("--plan requires --quality")
        plan_raw: object = json.loads(args.plan.read_text(encoding="utf-8"))
        base = expectation_from_plan(
            _object(plan_raw, "plan"), args.quality, audio=base.audio
        )
    elif args.quality is not None:
        geometry = QUALITY_GEOMETRY[args.quality]
        base = Expectation(
            fps=geometry.fps,
            width=geometry.width,
            height=geometry.height,
            audio=base.audio,
        )
    duration = (
        args.expect_duration if args.expect_duration is not None else base.duration_s
    )
    tolerance = (
        args.duration_tolerance
        if args.duration_tolerance is not None
        else base.duration_tolerance_s
    )
    return Expectation(
        duration_s=duration,
        duration_tolerance_s=tolerance,
        fps=args.expect_fps if args.expect_fps is not None else base.fps,
        width=args.expect_width if args.expect_width is not None else base.width,
        height=args.expect_height if args.expect_height is not None else base.height,
        audio=base.audio,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "check":
            report = verify(args.video, _expectation_from_args(args))
            text = json.dumps(report.to_dict(), indent=2)
            print(text)
            if args.report is not None:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(text + "\n", encoding="utf-8")
            return 0 if report.ok else 1
        if args.command == "sample":
            result = sample_frames(args.video, args.count, args.out_dir)
            print(json.dumps(result.receipt, indent=2))
            print(
                f"\nReview the {args.count} frames in {args.out_dir}, then record the verdict with "
                "`verify_video.py attest`. Until then review.status is 'pending'.",
                file=sys.stderr,
            )
            return 0
        receipt = attest(args.receipt, args.reviewer, args.verdict, args.notes)
        print(json.dumps(receipt["review"], indent=2))
        return 0 if args.verdict == "pass" else 1
    except MissingDependencyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except (ProbeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
