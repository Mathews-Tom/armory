"""Bounded, timestamp-honest frame extraction with ffmpeg/ffprobe.

Every returned frame carries the source-relative presentation time of the
decoded picture written to its JPEG. Times are read back from ffmpeg's
``showinfo`` filter (integer pts x the filter graph's time base) and
normalised by the container's start time, so a stream that starts at 1.4 s
(MPEG-TS) or 3 s (remuxed MKV) still reports source-relative times. Seek
offsets only decide where decoding begins; they are never used as labels.
In-filter range selection plus a post-decode check guarantee that every frame
lies in ``[start, end)``.

Detail levels
    transcript  cue frames only (``timestamps``); nothing is sampled.
    efficient   keyframes (decoder skips non-key frames) with a bounded
                uniform fallback when a clip has too few of them.
    balanced    scene changes plus a uniform sample, from one full decode.

Budget: ``max_frames`` caps the returned list including cue frames. Cue
frames are reserved first; a request with more cues than ``max_frames`` is
an error rather than a silent omission. Candidate pools are bounded by
duration-aware minimum gaps, so temporary JPEG storage never exceeds
``POOL_FACTOR * max_frames`` frames per branch (``POOL_CAP`` at most).

Near-duplicate suppression (``dedup``) applies to sampled frames only. A frame
is dropped when, against the last kept frame, no 12x12-pixel cell of a 96x96
grayscale thumbnail changes by more than ``_CELL_DIFF`` mean gray levels. The
first sampled frame is always kept, and the last is kept when it is at least
10% of the range later than the last kept frame, so a static clip still shows
both ends. Limits: an edit smaller than roughly 1.5% of the frame area at
moderate contrast (a one-word change in small code) can fall under the
threshold and merge with its predecessor; use ``dedup=False`` to keep every
sampled frame, or cue timestamps to force specific moments.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any, Final, Sequence

from evidence import EvidenceError, Frame, MediaInfo
from runtime import run

DETAILS: Final = ("transcript", "efficient", "balanced")
MAX_FRAMES_LIMIT: Final = 120
MIN_RESOLUTION: Final = 16
MAX_RESOLUTION: Final = 4096
POOL_FACTOR: Final = 4
POOL_CAP: Final = 240

_END_TOLERANCE: Final = 0.5  # requested end may overshoot a rounded duration
_EPS: Final = 1e-6  # select-boundary slack, far below any frame interval
_VERIFY_EPS: Final = 1e-5
_SCENE_THRESHOLD: Final = 0.15
_EFFICIENT_MIN: Final = 8
_TAIL_GAP_FRACTION: Final = 0.1
_THUMB: Final = 96
_CELL: Final = 12
_CELLS: Final = _THUMB // _CELL
_CELL_DIFF: Final = 2.5
_SEEK_MARGINS: Final = (0.0, 2.0, 8.0, 30.0, 120.0)
_EVENT_REASONS: Final = frozenset({"scene", "keyframe"})

_SHOWINFO = re.compile(
    r"\[showinfo@(\w+) @ [^\]]+\] n:\s*\d+ pts:\s*(-?\d+) pts_time:(\S+)"
)
_SHOWINFO_TB = re.compile(
    r"\[showinfo@(\w+) @ [^\]]+\] config in time_base: (\d+)/(\d+)"
)
_DURATION_TAG = re.compile(r"(\d+):(\d+):(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class _Media:
    path: Path
    info: MediaInfo
    stream_index: int
    time_base: Fraction
    origin: Fraction  # container start time = source time zero
    fps: float


@dataclass(frozen=True)
class _Candidate:
    ts: float
    path: Path
    thumb: bytes
    reason: str
    requested: float | None = None


@dataclass(frozen=True)
class _Branch:
    label: str
    select: str
    reason: str


class _Landing:
    """Remembers how far before a target ffmpeg must seek to decode it.

    Some demuxers (MPEG-TS) land on the first keyframe at or after the seek
    target, silently skipping frames in between. Seeking earlier by a growing
    margin recovers them; the margin that worked is reused for later targets.
    """

    def __init__(self) -> None:
        self.level = 0

    def seek(self, target: float) -> float:
        return max(0.0, target - _SEEK_MARGINS[self.level])


@dataclass
class _Job:
    media: _Media
    tmp: Path
    start: float
    end: float
    resolution: int
    landing: _Landing
    counter: "itertools.count[int]"

    @property
    def tolerance(self) -> float:
        return max(0.25, 3.0 / self.media.fps)


# --------------------------------------------------------------------------
# probing


def probe(path: Path) -> MediaInfo:
    """Container facts needed to bound extraction; raises EvidenceError."""
    return _inspect(path).info


def _inspect(path: Path) -> _Media:
    if not path.is_file():
        raise EvidenceError(f"Media file not found: {path.name}")
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=60,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise EvidenceError("ffprobe returned unreadable output") from exc
    if not isinstance(data, dict):
        raise EvidenceError("ffprobe returned unreadable output")
    streams: list[dict[str, Any]] = [
        s for s in data.get("streams", []) if isinstance(s, dict)
    ]
    fmt: dict[str, Any] = (
        data.get("format", {}) if isinstance(data.get("format"), dict) else {}
    )
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    origin = _fraction(fmt.get("start_time")) or Fraction(0)
    claimed = _claimed_duration(fmt, video)

    if video is None:
        if claimed is None:
            raise EvidenceError("Cannot determine media duration")
        info = MediaInfo(
            duration_seconds=claimed,
            width=0,
            height=0,
            has_audio=has_audio,
            has_video=False,
        )
        return _Media(path, info, -1, Fraction(1, 1000), origin, 25.0)

    fps = _frame_rate(video)
    index = int(video["index"])
    duration = _video_duration(path, index, origin, claimed, fps)
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if _rotation(video) % 180 == 90:
        width, height = height, width
    if width <= 0 or height <= 0:
        raise EvidenceError("Video stream has no usable dimensions")
    time_base = _fraction(video.get("time_base")) or Fraction(1, 1000)
    info = MediaInfo(
        duration_seconds=duration,
        width=width,
        height=height,
        has_audio=has_audio,
        has_video=True,
    )
    return _Media(path, info, index, time_base, origin, fps)


def _fraction(value: object) -> Fraction | None:
    if not isinstance(value, str) or not value or value == "N/A":
        return None
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None


def _claimed_duration(
    fmt: dict[str, Any], video: dict[str, Any] | None
) -> float | None:
    candidates: list[float | None] = [_float(fmt.get("duration"))]
    if video is not None:
        candidates.append(_float(video.get("duration")))
        tags = video.get("tags") or {}
        tag = tags.get("DURATION") or tags.get("DURATION-eng")
        if isinstance(tag, str):
            match = _DURATION_TAG.fullmatch(tag.strip()[:20]) or _DURATION_TAG.match(
                tag.strip()
            )
            if match:
                h, m, s = match.groups()
                candidates.append(int(h) * 3600 + int(m) * 60 + float(s))
    for value in candidates:
        if value is not None and value > 0:
            return value
    return None


def _float(value: object) -> float | None:
    try:
        number = float(str(value))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _frame_rate(video: dict[str, Any]) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        rate = _fraction(video.get(key))
        if rate is not None and rate > 0:
            return min(float(rate), 1000.0)
    return 25.0


def _rotation(video: dict[str, Any]) -> int:
    for item in video.get("side_data_list") or []:
        if isinstance(item, dict) and "rotation" in item:
            value = _float(item["rotation"])
            if value is not None:
                return int(round(abs(value))) % 360
    value = _float((video.get("tags") or {}).get("rotate"))
    return int(round(abs(value))) % 360 if value is not None else 0


def _video_duration(
    path: Path, index: int, origin: Fraction, claimed: float | None, fps: float
) -> float:
    """Length of the video stream on the source-relative timeline.

    Container-level durations are unreliable when a stream starts late (some
    muxers write end time instead of length), so the tail packets are read and
    the real end of the video stream is measured.
    """
    end = _last_packet_end(path, index, origin, claimed, fps)
    if end is None:
        if claimed is None:
            raise EvidenceError("Cannot determine video duration")
        return claimed
    duration = float(end - origin)
    if duration <= 0:
        raise EvidenceError("Video stream has no decodable duration")
    return duration


def _last_packet_end(
    path: Path, index: int, origin: Fraction, claimed: float | None, fps: float
) -> Fraction | None:
    base = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        str(index),
        "-show_entries",
        "packet=pts_time,duration_time",
        "-of",
        "csv=p=0",
    ]
    attempts: list[list[str]] = []
    if claimed is not None:
        window = max(float(origin) + claimed - 10.0, 0.0)
        attempts.append([*base, "-read_intervals", f"{window:.3f}%", str(path)])
    attempts.append([*base, str(path)])  # full scan when the tail seek misses
    for command in attempts:
        end = _max_packet_end(run(command, timeout=300).stdout, fps)
        if end is not None:
            return end
    return None


def _max_packet_end(output: str, fps: float) -> Fraction | None:
    best: Fraction | None = None
    fallback = Fraction(1, max(1, round(fps)))
    for line in output.splitlines():
        fields = line.split(",")
        pts = _fraction(fields[0].strip()) if fields else None
        if pts is None:
            continue
        length = _fraction(fields[1].strip()) if len(fields) > 1 else None
        end = pts + (length if length is not None and length > 0 else fallback)
        if best is None or end > best:
            best = end
    return best


# --------------------------------------------------------------------------
# public entry point


def extract_frames(
    path: Path,
    work_dir: Path,
    *,
    start: float = 0.0,
    end: float | None = None,
    detail: str = "balanced",
    max_frames: int = 40,
    resolution: int = 1024,
    timestamps: list[float] | None = None,
    dedup: bool = True,
) -> list[Frame]:
    """Write JPEG frames under ``work_dir/frames`` and return them by time.

    ``timestamps`` are cue times in source seconds. Each cue yields the first
    decodable frame at or after it inside ``[start, end)``; the frame's own
    time is ``timestamp_seconds`` and the cue is ``requested_seconds``. Cues
    whose frames coincide collapse into one frame (earliest cue kept).
    """
    _check_controls(start, end, detail, max_frames, resolution)
    cues = _check_cues(timestamps)
    if len(cues) > max_frames:
        raise EvidenceError(
            f"{len(cues)} cue timestamps exceed max_frames={max_frames}; "
            "raise max_frames or request fewer cues"
        )
    if detail == "transcript" and not cues:
        return []

    media = _inspect(path)
    if not media.info["has_video"]:
        raise EvidenceError("Media has no video stream to extract frames from")
    begin, finish = _resolve_range(media.info["duration_seconds"], start, end)
    outside = [t for t in cues if not begin <= t < finish]
    if outside:
        shown = ", ".join(f"{t:g}" for t in outside[:5])
        raise EvidenceError(
            f"Cue timestamps outside the selected range [{begin:g}, {finish:g}): {shown}"
        )

    frames_dir = work_dir.resolve() / "frames"
    if frames_dir == path.resolve().parent or frames_dir in path.resolve().parents:
        raise EvidenceError("Source media must not live inside the frames directory")
    frames_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".candidates-", dir=frames_dir))
    try:
        job = _Job(media, tmp, begin, finish, resolution, _Landing(), itertools.count())
        return _collect(job, frames_dir, cues, detail, max_frames, dedup)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _collect(
    job: _Job,
    frames_dir: Path,
    cues: list[float],
    detail: str,
    max_frames: int,
    dedup: bool,
) -> list[Frame]:
    cue_frames: list[_Candidate] = []
    for cue in cues:
        found = _grab(job, cue, "cue")
        if found is None:
            raise EvidenceError(
                f"No decodable frame at or after cue {cue:g}s inside "
                f"[{job.start:g}, {job.end:g})"
            )
        cue_frames.append(replace(found, requested=cue))

    n_auto = max_frames - len(cues)
    pool: list[_Candidate] = []
    if detail != "transcript" and n_auto > 0:
        pool = _sample(job, detail, n_auto)

    cue_times = {_key(c.ts) for c in cue_frames}
    pool = [c for c in pool if _key(c.ts) not in cue_times]
    # Cues that landed on one frame keep the earliest request only.
    seen: set[int] = set()
    unique_cues: list[_Candidate] = []
    for cue_frame in cue_frames:
        if _key(cue_frame.ts) not in seen:
            seen.add(_key(cue_frame.ts))
            unique_cues.append(cue_frame)

    merged = sorted([*unique_cues, *pool], key=lambda c: c.ts)
    if dedup:
        merged = _dedup(merged, job.end - job.start)
    sampled = _thin([c for c in merged if c.reason != "cue"], n_auto)
    chosen = sorted(
        [c for c in merged if c.reason == "cue"] + sampled, key=lambda c: c.ts
    )
    if not chosen:
        raise EvidenceError(
            f"No decodable video frames in [{job.start:g}, {job.end:g})"
        )
    return _finalize(chosen, frames_dir)


def _sample(job: _Job, detail: str, n_auto: int) -> list[_Candidate]:
    span = job.end - job.start
    pool_cap = min(POOL_CAP, POOL_FACTOR * n_auto)
    gap = span / pool_cap
    rng = _range_expr(job, job.start)
    _land(job)
    seek = job.landing.seek(job.start)

    if detail == "balanced":
        event = (
            f"{rng}*(isnan(prev_selected_t)+gt(scene,{_SCENE_THRESHOLD})"
            f"*gte(t-prev_selected_t,{gap:.6f}))"
        )
        uniform = (
            f"{rng}*(isnan(prev_selected_t)+gte(t-prev_selected_t,{span / n_auto:.6f}))"
        )
        branches = [_Branch("ev", event, "scene"), _Branch("un", uniform, "uniform")]
        found = _run_pass(job, branches, seek=seek, nokey=False)
        merged: dict[int, _Candidate] = {}
        for branch in branches:
            items = found[branch.label]
            for position, cand in enumerate(items):
                # The first frame of a branch is chosen only for being first.
                cand = replace(cand, reason="start") if position == 0 else cand
                current = merged.get(_key(cand.ts))
                if current is None or (
                    current.reason == "uniform" and cand.reason == "scene"
                ):
                    merged[_key(cand.ts)] = cand
        return sorted(merged.values(), key=lambda c: c.ts)

    keyframe = f"{rng}*(isnan(prev_selected_t)+gte(t-prev_selected_t,{gap:.6f}))"
    pool = _run_pass(job, [_Branch("kf", keyframe, "keyframe")], seek=seek, nokey=True)[
        "kf"
    ]
    need = min(n_auto, _EFFICIENT_MIN)
    if len(pool) < need:
        last = max(job.start, job.end - 1.5 / job.media.fps)
        for target in _linspace(job.start, last, need):
            found_one = _grab(job, target, "uniform")
            if found_one is not None:
                pool.append(found_one)
        by_time: dict[int, _Candidate] = {}
        for cand in pool:
            by_time.setdefault(_key(cand.ts), cand)
        pool = sorted(by_time.values(), key=lambda c: c.ts)
    return pool


def _linspace(first: float, last: float, count: int) -> list[float]:
    if count <= 1 or last <= first:
        return [first]
    step = (last - first) / (count - 1)
    return [first + step * i for i in range(count)]


def _key(ts: float) -> int:
    return round(ts * 1_000_000)


# --------------------------------------------------------------------------
# validation


def _check_controls(
    start: float, end: float | None, detail: str, max_frames: int, resolution: int
) -> None:
    if detail not in DETAILS:
        raise EvidenceError(
            f"detail must be one of {', '.join(DETAILS)}; got {detail!r}"
        )
    if not isinstance(max_frames, int) or isinstance(max_frames, bool):
        raise EvidenceError("max_frames must be an integer")
    if not 1 <= max_frames <= MAX_FRAMES_LIMIT:
        raise EvidenceError(f"max_frames must be between 1 and {MAX_FRAMES_LIMIT}")
    if not isinstance(resolution, int) or isinstance(resolution, bool):
        raise EvidenceError("resolution must be an integer")
    if not MIN_RESOLUTION <= resolution <= MAX_RESOLUTION:
        raise EvidenceError(
            f"resolution must be between {MIN_RESOLUTION} and {MAX_RESOLUTION} pixels"
        )
    if not math.isfinite(start) or start < 0:
        raise EvidenceError("start must be a finite number of seconds >= 0")
    if end is not None and (not math.isfinite(end) or end <= start):
        raise EvidenceError("end must be a finite number of seconds greater than start")


def _check_cues(timestamps: list[float] | None) -> list[float]:
    if not timestamps:
        return []
    for value in timestamps:
        if not math.isfinite(value) or value < 0:
            raise EvidenceError(
                f"Cue timestamps must be finite seconds >= 0; got {value!r}"
            )
    ordered = sorted(timestamps)
    unique: list[float] = []
    for value in ordered:
        if not unique or value - unique[-1] > _EPS:
            unique.append(value)
    return unique


def _resolve_range(
    duration: float, start: float, end: float | None
) -> tuple[float, float]:
    if start >= duration:
        raise EvidenceError(f"start {start:g}s is not inside the {duration:.3f}s video")
    if end is None:
        return start, duration
    if end > duration + _END_TOLERANCE:
        raise EvidenceError(f"end {end:g}s is past the {duration:.3f}s video")
    return start, min(end, duration)


# --------------------------------------------------------------------------
# ffmpeg passes


def _range_expr(job: _Job, lower: float) -> str:
    origin = float(job.media.origin)
    low = origin + max(lower, job.start) - _EPS
    high = origin + job.end - _EPS
    return f"gte(t,{low:.6f})*lt(t,{high:.6f})"


def _land(job: _Job) -> None:
    """Find the seek margin that decodes from ``start`` (no frame is kept)."""
    if job.start <= 0:
        return
    found = _grab(job, job.start, "uniform")
    if found is None:
        raise EvidenceError(
            f"No decodable frame at or after start {job.start:g}s inside "
            f"[{job.start:g}, {job.end:g})"
        )


def _grab(job: _Job, target: float, reason: str) -> _Candidate | None:
    """First frame at/after ``target`` in range, seeking earlier if needed."""
    best: _Candidate | None = None
    for level in range(job.landing.level, len(_SEEK_MARGINS)):
        seek = max(0.0, target - _SEEK_MARGINS[level])
        select = _range_expr(job, target)
        branch = _Branch("g", select, reason)
        found = _run_pass(job, [branch], seek=seek, nokey=False, frames=1)["g"]
        if found:
            best = found[0]
            if best.ts - target <= job.tolerance:
                job.landing.level = level
                return best
        job.landing.level = level
        if seek == 0.0:
            break
    return best


def _run_pass(
    job: _Job,
    branches: Sequence[_Branch],
    *,
    seek: float,
    nokey: bool,
    frames: int | None = None,
) -> dict[str, list[_Candidate]]:
    media = job.media
    prefix = f"p{next(job.counter):03d}"
    scale = (
        f"scale=w='min({job.resolution},iw)':h='min({job.resolution},ih)'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    count = len(branches)
    heads = "".join(f"[s{i}]" for i in range(count))
    parts = [
        f"[0:{media.stream_index}]{scale}"
        + (f",split={count}{heads}" if count > 1 else "[s0]")
    ]
    for i, branch in enumerate(branches):
        parts.append(
            f"[s{i}]select='{branch.select}',showinfo@{branch.label},split=2[j{i}][t{i}]"
        )
        parts.append(f"[j{i}]format=yuvj420p[oj{i}]")
        parts.append(f"[t{i}]scale={_THUMB}:{_THUMB}:flags=area,format=gray[ot{i}]")

    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-nostats"]
    if nokey:
        command += ["-skip_frame", "nokey"]
    # Bound every read, including a single-frame select that never matches.
    # The margin covers B-frame reordering past the requested end.
    command += ["-ss", f"{seek:.6f}", "-copyts", "-t", f"{job.end - seek + 2.0:.6f}"]
    command += ["-i", str(media.path), "-filter_complex", ";".join(parts)]
    limit = ["-frames:v", str(frames)] if frames is not None else []
    for i, branch in enumerate(branches):
        command += [
            "-map",
            f"[oj{i}]",
            *limit,
            "-fps_mode",
            "passthrough",
            "-q:v",
            "3",
            "-f",
            "image2",
            str(job.tmp / f"{prefix}{branch.label}_%05d.jpg"),
            "-map",
            f"[ot{i}]",
            *limit,
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            str(job.tmp / f"{prefix}{branch.label}.raw"),
        ]
    timeout = 120.0 if frames is not None else min(3600.0, 300.0 + (job.end - seek) / 2)
    stderr = run(command, timeout=timeout).stderr
    return {
        branch.label: _read_outputs(job, prefix, branch, stderr, frames)
        for branch in branches
    }


def _read_outputs(
    job: _Job, prefix: str, branch: _Branch, stderr: str, frames: int | None
) -> list[_Candidate]:
    media = job.media
    time_base = media.time_base
    for tag, num, den in _SHOWINFO_TB.findall(stderr):
        if tag == branch.label and int(num) > 0 and int(den) > 0:
            time_base = Fraction(int(num), int(den))
            break
    times: list[float] = []
    for tag, pts, shown in _SHOWINFO.findall(stderr):
        if tag != branch.label:
            continue
        absolute = Fraction(int(pts)) * time_base
        reported = _float(shown)
        if reported is None or abs(float(absolute) - reported) > max(
            1e-5, 1e-5 * abs(reported)
        ):
            raise EvidenceError("ffmpeg reported inconsistent frame timestamps")
        times.append(round(float(absolute - media.origin), 6))

    if frames is not None:
        # The filter may inspect frames past the output cap before ffmpeg stops.
        times = times[:frames]
    jpegs = sorted(job.tmp.glob(f"{prefix}{branch.label}_*.jpg"))
    raw_path = job.tmp / f"{prefix}{branch.label}.raw"
    raw = raw_path.read_bytes() if raw_path.exists() else b""
    size = _THUMB * _THUMB
    if not (len(times) == len(jpegs) and len(raw) == size * len(jpegs)):
        raise EvidenceError(
            f"ffmpeg decode produced inconsistent output "
            f"({len(times)} timestamps, {len(jpegs)} images, {len(raw) // size} thumbnails)"
        )
    out: list[_Candidate] = []
    for i, (ts, jpeg) in enumerate(zip(times, jpegs)):
        if not job.start - _VERIFY_EPS <= ts < job.end:
            raise EvidenceError(
                f"Decoder produced a frame at {ts:.3f}s outside the requested "
                f"range [{job.start:g}, {job.end:g})"
            )
        out.append(_Candidate(ts, jpeg, raw[i * size : (i + 1) * size], branch.reason))
    return out


# --------------------------------------------------------------------------
# selection


def _similar(a: bytes, b: bytes) -> bool:
    """True when no thumbnail cell differs by more than ``_CELL_DIFF`` mean."""
    if len(a) != len(b) or len(a) != _THUMB * _THUMB:
        return False
    limit = _CELL_DIFF * _CELL * _CELL
    for band in range(_CELLS):
        sums = [0] * _CELLS
        for row in range(band * _CELL, (band + 1) * _CELL):
            base = row * _THUMB
            diff = [
                abs(x - y)
                for x, y in zip(a[base : base + _THUMB], b[base : base + _THUMB])
            ]
            for cell in range(_CELLS):
                sums[cell] += sum(diff[cell * _CELL : (cell + 1) * _CELL])
        if max(sums) > limit:
            return False
    return True


def _dedup(items: list[_Candidate], span: float) -> list[_Candidate]:
    sampled = [i for i, c in enumerate(items) if c.reason != "cue"]
    if not sampled:
        return items
    first, last = sampled[0], sampled[-1]
    kept: list[_Candidate] = []
    for i, cand in enumerate(items):
        ref = kept[-1] if kept else None
        if cand.reason == "cue" or i == first or ref is None:
            kept.append(cand)
        elif not _similar(ref.thumb, cand.thumb):
            kept.append(cand)
        elif i == last and cand.ts - ref.ts >= span * _TAIL_GAP_FRACTION:
            kept.append(cand)
    return kept


def _thin(items: list[_Candidate], limit: int) -> list[_Candidate]:
    """Drop interior frames with the smallest time neighbourhood until it fits.

    Scene/keyframe picks count double, so evenly spread uniform samples go
    first; the first and last candidates always survive.
    """
    if limit <= 0:
        return []
    kept = list(items)
    if len(kept) <= limit:
        return kept
    if limit == 1:
        return kept[:1]
    while len(kept) > limit:
        victim = min(
            range(1, len(kept) - 1),
            key=lambda i: (kept[i + 1].ts - kept[i - 1].ts)
            * (2.0 if kept[i].reason in _EVENT_REASONS else 1.0),
        )
        del kept[victim]
    return kept


def _finalize(chosen: list[_Candidate], frames_dir: Path) -> list[Frame]:
    for stale in frames_dir.glob("frame_*.jpg"):
        stale.unlink()
    frames: list[Frame] = []
    for index, cand in enumerate(chosen, start=1):
        ms = round(cand.ts * 1000)
        final = frames_dir / f"frame_{index:03d}_t{ms:09d}ms.jpg"
        os.replace(cand.path, final)
        frame = Frame(timestamp_seconds=cand.ts, path=str(final), reason=cand.reason)
        if cand.requested is not None:
            frame["requested_seconds"] = cand.requested
        frames.append(frame)
    return frames
