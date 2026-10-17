from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from launch_video import (
    POSTER_MIN_PSNR_DB,
    Asset,
    FinishError,
    finish,
    missing_credits,
    poster_psnr,
    probe,
    sha256_file,
    start,
)

MUSIC = Asset("assets/music.mp3", "https://example.org/track", "CC-BY-4.0")
FONT = Asset("assets/fonts/brand.woff2", "https://example.org/font", "OFL-1.1")
CREDITED = "Built it. Music: Track by Example, https://example.org/track, CC BY 4.0."


@pytest.mark.parametrize(
    ("share_copy", "uncredited"),
    [
        ("Built it.", [MUSIC]),
        ("Built it. https://example.org/track", [MUSIC]),
        ("Built it. Music under CC BY 4.0", [MUSIC]),
        (CREDITED, []),
        ("Built it. https://example.org/track (cc-by-4.0)", []),
    ],
)
def test_attribution_needs_source_and_licence(
    share_copy: str, uncredited: list[Asset]
) -> None:
    assert missing_credits(share_copy, [MUSIC, FONT]) == uncredited


def test_start_never_reuses_a_run_directory(tmp_path: Path) -> None:
    first = start(tmp_path)
    second = start(tmp_path, now=datetime(2026, 10, 17, 9, 5, 7))
    assert first.name == "launch-output"
    assert second.name == "launch-output-2026-10-17-090507"
    with pytest.raises(FileExistsError):
        start(tmp_path, now=datetime(2026, 10, 17, 9, 5, 7))


def _video(path: Path, seconds: int, audio: bool) -> Path:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi"]
    cmd += ["-i", f"testsrc=size=320x180:rate=15:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="module")
def media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("media")
    return {
        "full": _video(root / "full.mp4", 16, audio=True),
        "silent": _video(root / "silent.mp4", 16, audio=False),
        "short": _video(root / "short.mp4", 10, audio=True),
    }


def _run_dir(
    tmp_path: Path,
    video: Path,
    *,
    audio_clip: bool = True,
    share_copy: str = CREDITED,
) -> Path:
    run = tmp_path / "launch-output"
    delivery = run / "delivery"
    source = delivery / "source"
    source.mkdir(parents=True)
    shutil.copyfile(video, delivery / "launch.mp4")
    clip = '<audio src="assets/music.mp3" data-start="0"></audio>' if audio_clip else ""
    (source / "index.html").write_text(f"<div id='root'>{clip}</div>", encoding="utf-8")
    assets = [
        {"path": a.path, "source": a.source, "license": a.license}
        for a in (MUSIC, FONT)
    ]
    (source / "PROVENANCE.json").write_text(
        json.dumps({"version": 1, "assets": assets}), encoding="utf-8"
    )
    (delivery / "RENDER.json").write_text(
        json.dumps(
            {
                "video": "launch.mp4",
                "files": {"launch.mp4": sha256_file(delivery / "launch.mp4")},
            }
        ),
        encoding="utf-8",
    )
    (run / "share-copy.txt").write_text(share_copy, encoding="utf-8")
    return run


def test_finish_bakes_the_poster_into_frame_zero(
    tmp_path: Path, media: dict[str, Path]
) -> None:
    run = _run_dir(tmp_path, media["full"])

    result = finish(run, poster_at=8.0)

    before, after = probe(media["full"]), probe(run / "launch.mp4")
    assert (after.width, after.height, after.frame_rate, after.video_frames) == (
        before.width,
        before.height,
        before.frame_rate,
        before.video_frames,
    )
    assert after.audio_streams == 1
    poster = run / "poster.jpg"
    assert poster_psnr(media["full"], poster) < POSTER_MIN_PSNR_DB
    assert poster_psnr(run / "launch.mp4", poster) >= POSTER_MIN_PSNR_DB
    record = json.loads((run / "LAUNCH.json").read_text(encoding="utf-8"))
    for name, digest in result.outputs.items():
        assert sha256_file(run / name) == digest
    assert record["credits_required"] == [
        {"path": MUSIC.path, "source": MUSIC.source, "license": MUSIC.license}
    ]
    assert "[credit required]" in (run / "CREDITS.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("clip", "options", "code"),
    [
        ("silent", {}, "audio_missing"),
        ("short", {}, "duration_out_of_range"),
        ("full", {"share_copy": "Built it."}, "credit_missing"),
        ("full", {"poster_at": 16.0}, "poster_out_of_range"),
        ("full", {"tamper": True}, "video_digest_mismatch"),
    ],
)
def test_finish_refuses_without_writing_outputs(
    tmp_path: Path,
    media: dict[str, Path],
    clip: str,
    options: dict[str, object],
    code: str,
) -> None:
    share_copy = options.get("share_copy", CREDITED)
    assert isinstance(share_copy, str)
    run = _run_dir(tmp_path, media[clip], share_copy=share_copy)
    if options.get("tamper"):
        with (run / "delivery" / "launch.mp4").open("ab") as handle:
            handle.write(b"\0")
    poster_at = options.get("poster_at", 2.0)
    assert isinstance(poster_at, float)

    with pytest.raises(FinishError) as caught:
        finish(run, poster_at=poster_at)

    assert caught.value.code == code
    assert sorted(p.name for p in run.iterdir()) == ["delivery", "share-copy.txt"]
