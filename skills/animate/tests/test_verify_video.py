"""Output verification and frame-review receipts, using real ffmpeg-made media."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from verify_video import (
    Expectation,
    ProbeError,
    VideoProbe,
    attest,
    check_probe,
    duration_tolerance,
    expectation_from_plan,
    main as verify_main,
    probe_video,
    sample_frames,
    sample_times,
    verify,
)


WIDTH, HEIGHT, FPS, SECONDS = 320, 180, 15, 2


def _make_video(path: Path, source: str, *, audio: bool = False) -> Path:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source]
    if audio:
        cmd += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={SECONDS}",
            "-shortest",
        ]
    cmd += ["-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="module")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _make_video(
        tmp_path_factory.mktemp("media") / "pattern.mp4",
        f"testsrc=size={WIDTH}x{HEIGHT}:rate={FPS}:duration={SECONDS}",
    )


def _expected(**overrides: object) -> Expectation:
    values: dict[str, object] = {
        "duration_s": float(SECONDS),
        "duration_tolerance_s": 0.2,
        "fps": float(FPS),
        "width": WIDTH,
        "height": HEIGHT,
    }
    values.update(overrides)
    return Expectation(**values)  # type: ignore[arg-type]


def test_matching_video_passes_every_check(video: Path) -> None:
    report = verify(video, _expected())
    assert report.ok, report.failures
    assert report.probe is not None
    assert report.probe.frames_decoded == FPS * SECONDS


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"duration_s": 5.0}, "duration"),
        ({"width": 640}, "width"),
        ({"height": 720}, "height"),
        ({"fps": 30.0}, "frame rate"),
        ({"audio": True}, "audio"),
    ],
)
def test_each_mismatch_is_reported(
    video: Path, overrides: dict[str, object], fragment: str
) -> None:
    report = verify(video, _expected(**overrides))
    assert not report.ok
    assert any(fragment in failure for failure in report.failures)


def test_one_frame_of_rounding_drift_is_tolerated_but_a_missing_hold_is_not(
    video: Path,
) -> None:
    tolerance = duration_tolerance(animation_calls=4, fps=float(FPS))
    assert verify(
        video, _expected(duration_s=SECONDS + 1 / FPS, duration_tolerance_s=tolerance)
    ).ok
    assert not verify(
        video, _expected(duration_s=SECONDS + 2.0, duration_tolerance_s=tolerance)
    ).ok


def test_audio_stream_is_detected(tmp_path: Path) -> None:
    with_audio = _make_video(
        tmp_path / "audio.mp4",
        f"testsrc=size={WIDTH}x{HEIGHT}:rate={FPS}:duration={SECONDS}",
        audio=True,
    )
    assert verify(with_audio, _expected(audio=True)).ok


def test_missing_empty_and_corrupt_files_fail_instead_of_raising(
    tmp_path: Path, video: Path
) -> None:
    missing = verify(tmp_path / "nope.mp4", _expected())
    assert not missing.ok and "not found" in missing.failures[0]

    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert "empty" in verify(empty, _expected()).failures[0]

    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"this is not a video" * 100)
    assert not verify(corrupt, _expected()).ok

    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(video.read_bytes()[: video.stat().st_size // 3])
    assert not verify(truncated, _expected()).ok


def test_zero_decoded_frames_is_a_failure() -> None:
    probe = VideoProbe(Path("x.mp4"), 2.0, WIDTH, HEIGHT, float(FPS), 0, "h264", None)
    assert any("0 video frames" in f for f in check_probe(probe, Expectation()))


def test_plan_expectation_rejects_bad_plans_and_qualities() -> None:
    good = {"expected_duration_s": 8.5, "animation_calls": 7}
    expectation = expectation_from_plan(good, "low")
    assert (expectation.width, expectation.height, expectation.fps) == (854, 480, 15.0)
    assert expectation.duration_tolerance_s == pytest.approx(
        duration_tolerance(7, 15.0)
    )
    for bad in (
        {"expected_duration_s": True, "animation_calls": 7},
        {"expected_duration_s": -1, "animation_calls": 7},
        {"expected_duration_s": 8.5, "animation_calls": 7.5},
        {"expected_duration_s": 8.5},
    ):
        with pytest.raises(ValueError):
            expectation_from_plan(bad, "low")
    with pytest.raises(ValueError, match="quality"):
        expectation_from_plan(good, "ultra")


# ── Sampling and receipts ──────────────────────────────────────────────────


def test_sample_times_are_segment_midpoints_never_zero() -> None:
    times = sample_times(10.0, 4)
    assert times == [1.25, 3.75, 6.25, 8.75]
    with pytest.raises(ValueError):
        sample_times(10.0, 0)
    with pytest.raises(ValueError):
        sample_times(10.0, 31)
    with pytest.raises(ValueError):
        sample_times(0.0, 3)


def test_sampling_writes_frames_and_a_pending_receipt(
    video: Path, tmp_path: Path
) -> None:
    result = sample_frames(video, 3, tmp_path / "frames")
    frames = sorted((tmp_path / "frames").glob("frame-*.png"))
    assert len(frames) == 3 and all(f.stat().st_size > 0 for f in frames)
    receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert receipt["review"]["status"] == "pending"
    assert [s["index"] for s in receipt["samples"]] == [0, 1, 2]
    assert (
        0 < receipt["samples"][0]["time_s"] < receipt["samples"][-1]["time_s"] < SECONDS
    )
    assert result.uniform_indices == []  # testsrc is never a flat frame


def test_flat_frames_are_flagged_uniform(tmp_path: Path) -> None:
    black = _make_video(
        tmp_path / "black.mp4",
        f"color=c=black:size={WIDTH}x{HEIGHT}:rate={FPS}:duration={SECONDS}",
    )
    result = sample_frames(black, 2, tmp_path / "frames")
    assert result.uniform_indices == [0, 1]


def test_resampling_removes_stale_frames(video: Path, tmp_path: Path) -> None:
    out = tmp_path / "frames"
    sample_frames(video, 4, out)
    sample_frames(video, 2, out)
    assert len(list(out.glob("frame-*.png"))) == 2


def test_attest_records_verdict_only_for_untampered_evidence(
    video: Path, tmp_path: Path
) -> None:
    out = tmp_path / "frames"
    result = sample_frames(video, 2, out)

    with pytest.raises(ValueError, match="reviewer"):
        attest(result.receipt_path, "  ", "pass", "")
    with pytest.raises(ValueError, match="verdict"):
        attest(result.receipt_path, "me", "maybe", "")

    recorded = attest(result.receipt_path, "reviewer-1", "pass", "labels readable")
    assert recorded["review"]["status"] == "pass"  # type: ignore[index]
    stored = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert stored["review"]["reviewer"] == "reviewer-1"

    (out / "frame-00.png").write_bytes(b"replaced")
    with pytest.raises(ValueError, match="changed since sampling"):
        attest(result.receipt_path, "reviewer-1", "pass", "")


def test_attest_rejects_a_video_that_changed_after_sampling(tmp_path: Path) -> None:
    copy = _make_video(
        tmp_path / "copy.mp4",
        f"testsrc=size={WIDTH}x{HEIGHT}:rate={FPS}:duration={SECONDS}",
    )
    result = sample_frames(copy, 2, tmp_path / "frames")
    copy.write_bytes(copy.read_bytes() + b"\x00")
    with pytest.raises(ValueError, match="changed since sampling"):
        attest(result.receipt_path, "reviewer-1", "fail", "")


def test_probe_error_is_raised_for_unreadable_input(
    tmp_path: Path, video: Path
) -> None:
    with pytest.raises(ProbeError):
        probe_video(tmp_path / "absent.mp4")


@pytest.mark.parametrize(
    "option", ["--expect-duration", "--duration-tolerance", "--expect-fps"]
)
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_expectations_are_invalid(
    video: Path, option: str, value: str
) -> None:
    assert verify_main(["check", str(video), f"{option}={value}"]) == 2


def test_quality_without_plan_checks_requested_geometry(video: Path) -> None:
    assert verify_main(["check", str(video), "--quality", "high"]) == 1


@pytest.mark.parametrize("duration", [float("nan"), float("inf")])
def test_nonfinite_plan_duration_is_invalid(duration: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        expectation_from_plan(
            {"expected_duration_s": duration, "animation_calls": 7}, "low"
        )


def test_failed_resampling_invalidates_previous_pass(
    video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "frames"
    previous = sample_frames(video, 2, out)
    attest(previous.receipt_path, "reviewer-1", "pass", "reviewed")

    def fail_measurement(frame: Path) -> tuple[float, float]:
        raise ProbeError("injected extraction failure")

    monkeypatch.setattr("verify_video._luma_range", fail_measurement)
    with pytest.raises(ProbeError, match="injected"):
        sample_frames(video, 2, out)
    assert not previous.receipt_path.exists()
