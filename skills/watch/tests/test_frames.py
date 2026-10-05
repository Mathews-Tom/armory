"""Frame extraction boundaries, timestamps, and failure modes on real video.

Fixtures are generated with ffmpeg. The stepped clip is 160x90 at 10 fps for
20 s and its luma depends only on the source time: a new level every 4 s.
A frame labelled ``t`` therefore must show level ``floor(t / 4)``; the tests
compare levels pairwise instead of against absolute values so they do not
depend on JPEG or range conversion details.
"""

from __future__ import annotations

import hashlib
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from evidence import EvidenceError, Frame
from frames import extract_frames, probe


def _encoders() -> str:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return ""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


pytestmark = pytest.mark.skipif(
    "libx264" not in _encoders(), reason="ffmpeg/ffprobe with libx264 is not installed"
)

SEGMENT = 4.0
CONTAINERS = ["mp4", "ts", "mkv"]  # start times 0, 1.6 and 3.0 seconds


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
        capture_output=True,
    )


def _luma(image: str | Path) -> int:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(image),
            "-vf",
            "scale=1:1:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout[0]


def _gray(image: str | Path, width: int, height: int) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(image),
            "-vf",
            f"scale={width}:{height},format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout


def _size(image: str | Path) -> tuple[int, int]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(image),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    width, height = out.split("x")
    return int(width), int(height)


def _start_time(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=start_time",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


@pytest.fixture(scope="module")
def clips(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("clips")
    base = root / "steps.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=black:s=160x90:r=10:d=20,format=yuv420p,"
        f"geq=lum='30+40*floor(T/{SEGMENT:g})':cb=128:cr=128",
        "-c:v",
        "libx264",
        "-g",
        "1000",
        "-sc_threshold",
        "0",
        "-force_key_frames",
        "0,4,8,12,16",
        str(base),
    )
    ts = root / "steps.ts"
    _ffmpeg("-i", str(base), "-c", "copy", str(ts))
    mkv = root / "steps.mkv"
    _ffmpeg("-i", str(base), "-c", "copy", "-output_ts_offset", "3", str(mkv))
    clips = {"mp4": base, "ts": ts, "mkv": mkv}
    assert _start_time(ts) > 1 and _start_time(mkv) > 2  # fixtures really start late
    return clips


@pytest.fixture(scope="module")
def static_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("static") / "static.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=gray:s=160x90:r=10:d=20,format=yuv420p",
        "-c:v",
        "libx264",
        "-g",
        "1000",
        "-sc_threshold",
        "0",
        str(path),
    )
    return path


@pytest.fixture(scope="module")
def box_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Static gray frame; a small white box appears at 12 s and stays."""
    path = tmp_path_factory.mktemp("box") / "box.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=gray:s=160x90:r=10:d=20,format=yuv420p,"
        "drawbox=x=100:y=40:w=20:h=20:color=white:t=fill:enable='gte(t,12)'",
        "-c:v",
        "libx264",
        "-g",
        "1000",
        "-sc_threshold",
        "0",
        str(path),
    )
    return path


def _assert_pixels_match_times(frames: list[Frame]) -> None:
    """Frame levels must agree with the segment implied by their labels."""
    labelled = [
        (math.floor(f["timestamp_seconds"] / SEGMENT), _luma(f["path"])) for f in frames
    ]
    assert len({seg for seg, _ in labelled}) >= 2, "sample must straddle segments"
    for seg_a, luma_a in labelled:
        for seg_b, luma_b in labelled:
            if seg_a == seg_b:
                assert abs(luma_a - luma_b) < 12
            else:
                assert abs(luma_a - luma_b) > 25
                assert (seg_a < seg_b) == (luma_a < luma_b)


def _assert_in_range(frames: list[Frame], start: float, end: float) -> None:
    for frame in frames:
        assert start - 1e-3 <= frame["timestamp_seconds"] < end
        assert Path(frame["path"]).is_file()
    stamps = [f["timestamp_seconds"] for f in frames]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)


@pytest.mark.parametrize("container", CONTAINERS)
def test_probe_reports_source_relative_duration(
    clips: dict[str, Path], container: str
) -> None:
    info = probe(clips[container])
    assert info["duration_seconds"] == pytest.approx(20.0, abs=0.15)
    assert (info["width"], info["height"]) == (160, 90)
    assert info["has_video"] and not info["has_audio"]


@pytest.mark.parametrize("container", CONTAINERS)
def test_efficient_focus_range_uses_keyframes_with_true_times(
    clips: dict[str, Path], tmp_path: Path, container: str
) -> None:
    frames = extract_frames(
        clips[container], tmp_path, start=6.0, end=14.0, detail="efficient"
    )
    _assert_in_range(frames, 6.0, 14.0)
    keyframes = [f["timestamp_seconds"] for f in frames if f["reason"] == "keyframe"]
    assert keyframes == [pytest.approx(8.0, abs=1e-3), pytest.approx(12.0, abs=1e-3)]
    _assert_pixels_match_times(frames)


@pytest.mark.parametrize("container", CONTAINERS)
@pytest.mark.parametrize("window", [(6.0, 14.0), (2.0, 18.0)])
def test_balanced_scene_frames_sit_on_the_change_in_pixels_and_time(
    clips: dict[str, Path], tmp_path: Path, container: str, window: tuple[float, float]
) -> None:
    start, end = window
    frames = extract_frames(
        clips[container], tmp_path, start=start, end=end, detail="balanced"
    )
    _assert_in_range(frames, start, end)
    assert frames[0]["timestamp_seconds"] < start + 0.15  # decoding began at start
    scenes = [f["timestamp_seconds"] for f in frames if f["reason"] == "scene"]
    expected = [b for b in (4.0, 8.0, 12.0, 16.0) if start < b < end]
    assert len(scenes) == len(expected)
    for actual, boundary in zip(scenes, expected):
        assert boundary <= actual < boundary + 0.15
    _assert_pixels_match_times(frames)


@pytest.mark.parametrize("container", CONTAINERS)
def test_cues_are_reserved_and_report_requested_time(
    clips: dict[str, Path], tmp_path: Path, container: str
) -> None:
    frames = extract_frames(
        clips[container],
        tmp_path,
        detail="balanced",
        max_frames=3,
        timestamps=[9.05, 5.3],
    )
    assert len(frames) <= 3
    cues = [f for f in frames if "requested_seconds" in f]
    assert [f["requested_seconds"] for f in cues] == [5.3, 9.05]
    for frame in cues:
        delay = frame["timestamp_seconds"] - frame["requested_seconds"]
        assert 0 <= delay < 0.25 and frame["reason"] == "cue"
    _assert_pixels_match_times(frames)


def test_transcript_detail_returns_only_cue_frames(
    clips: dict[str, Path], tmp_path: Path
) -> None:
    frames = extract_frames(
        clips["mp4"], tmp_path, detail="transcript", timestamps=[1.0, 10.0]
    )
    assert [f["reason"] for f in frames] == ["cue", "cue"]
    assert extract_frames(clips["mp4"], tmp_path, detail="transcript") == []


def test_cue_budget_overflow_is_an_error_not_an_omission(
    clips: dict[str, Path], tmp_path: Path
) -> None:
    with pytest.raises(EvidenceError, match="max_frames"):
        extract_frames(
            clips["mp4"], tmp_path, max_frames=3, timestamps=[1.0, 2.0, 3.0, 4.0]
        )
    assert not (tmp_path / "frames").exists()


@pytest.mark.parametrize("cue", [5.0, 14.0, 19.0, 99.0, math.nan, math.inf, -1.0])
def test_cues_outside_the_range_are_rejected(
    clips: dict[str, Path], tmp_path: Path, cue: float
) -> None:
    with pytest.raises(EvidenceError):
        extract_frames(
            clips["ts"], tmp_path, start=6.0, end=14.0, timestamps=[8.0, cue]
        )


@pytest.mark.parametrize("detail", ["efficient", "balanced"])
def test_static_video_still_supplies_evidence(
    static_clip: Path, tmp_path: Path, detail: str
) -> None:
    frames = extract_frames(static_clip, tmp_path, detail=detail)
    stamps = [f["timestamp_seconds"] for f in frames]
    assert len(frames) >= 2
    assert stamps[0] < 1.0 and stamps[-1] > 15.0  # both ends of the clip
    assert len(frames) < 10  # near-duplicates were merged


def test_disabling_dedup_keeps_an_even_uniform_spread(
    static_clip: Path, tmp_path: Path
) -> None:
    frames = extract_frames(
        static_clip, tmp_path, detail="balanced", max_frames=10, dedup=False
    )
    stamps = [f["timestamp_seconds"] for f in frames]
    assert 8 <= len(frames) <= 10
    assert stamps[0] < 0.5 and stamps[-1] > 16.0
    assert max(b - a for a, b in zip(stamps, stamps[1:])) < 3.0


def test_dedup_keeps_a_small_known_change(box_clip: Path, tmp_path: Path) -> None:
    frames = extract_frames(box_clip, tmp_path, detail="balanced")

    def box_visible(frame: Frame) -> bool:
        pixels = _gray(frame["path"], 160, 90)
        return pixels[50 * 160 + 110] > 200

    before = [f for f in frames if f["timestamp_seconds"] < 12.0]
    after = [f for f in frames if f["timestamp_seconds"] >= 12.0]
    assert before and after
    assert not any(box_visible(f) for f in before)
    assert box_visible(after[0])
    assert len(frames) <= 4  # but the unchanged samples were dropped


@pytest.mark.parametrize(("width", "height"), [(160, 90), (90, 160)])
def test_frames_are_bounded_in_both_dimensions_and_never_upscaled(
    tmp_path: Path, width: int, height: int
) -> None:
    clip = tmp_path / "shape.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=gray:s={width}x{height}:r=5:d=3,format=yuv420p",
        "-c:v",
        "libx264",
        str(clip),
    )
    small = extract_frames(clip, tmp_path / "small", resolution=64, max_frames=2)
    assert all(max(_size(f["path"])) <= 64 for f in small)
    native = extract_frames(clip, tmp_path / "native", resolution=1024, max_frames=2)
    assert all(_size(f["path"]) == (width, height) for f in native)


def test_source_is_never_modified_and_workdir_holds_only_returned_frames(
    clips: dict[str, Path], tmp_path: Path
) -> None:
    source = tmp_path / "source.mp4"
    shutil.copy(clips["mp4"], source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    first = extract_frames(source, tmp_path, timestamps=[3.0], max_frames=4)
    second = extract_frames(source, tmp_path, timestamps=[15.0], max_frames=4)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    on_disk = sorted(p.name for p in (tmp_path / "frames").iterdir())
    assert on_disk == sorted(Path(f["path"]).name for f in second)
    assert not any(Path(f["path"]).exists() for f in first if f not in second)


def test_source_inside_the_frames_directory_is_refused(
    clips: dict[str, Path], tmp_path: Path
) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    source = frames_dir / "frame_001_source.jpg.mp4"
    shutil.copy(clips["mp4"], source)
    with pytest.raises(EvidenceError, match="frames directory"):
        extract_frames(source, tmp_path)
    assert source.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_frames": 0},
        {"max_frames": 100_000},
        {"resolution": 0},
        {"resolution": 100_000},
        {"detail": "all"},
        {"start": -1.0},
        {"start": math.nan},
        {"start": 25.0},
        {"start": 5.0, "end": 5.0},
        {"end": math.inf},
        {"end": 40.0},
    ],
)
def test_invalid_controls_fail_clearly(
    clips: dict[str, Path], tmp_path: Path, kwargs: dict[str, object]
) -> None:
    with pytest.raises(EvidenceError):
        extract_frames(clips["mp4"], tmp_path, **kwargs)  # type: ignore[arg-type]


def test_probe_and_extract_report_unusable_media(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(b"not a video" * 50)
    with pytest.raises(EvidenceError):
        probe(garbage)
    with pytest.raises(EvidenceError):
        extract_frames(garbage, tmp_path / "w")
    with pytest.raises(EvidenceError):
        probe(tmp_path / "missing.mp4")

    audio = tmp_path / "tone.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(audio))
    info = probe(audio)
    assert info["has_audio"] and not info["has_video"]
    assert info["duration_seconds"] == pytest.approx(2.0, abs=0.1)
    with pytest.raises(EvidenceError, match="no video"):
        extract_frames(audio, tmp_path / "w2")
