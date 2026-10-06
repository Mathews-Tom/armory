"""Consumer-visible acquisition boundaries and evidence preservation."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

import watch
from evidence import EvidenceError, SourceInfo, Transcript
from utils import inline_code, parse_time


def captions() -> Transcript:
    return {
        "status": "available",
        "segments": [
            {
                "start": 10.0,
                "duration": 2.0,
                "text": "Speech before the selected window",
            }
        ],
        "language": "en",
        "source": "manual-caption",
        "kind": "manual",
        "gaps": [],
    }


def metadata(source: str) -> SourceInfo:
    return {
        "title": "Lecture",
        "channel": "Speaker",
        "duration_seconds": 120.0,
        "upload_date": None,
        "description": "",
        "video_id": "Bgtr1Ue40Jo",
    }


def forbidden(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError(
        "This request must not download media, probe it, or contact a provider"
    )


@pytest.mark.parametrize("engine", ["gemini", "unknown"])
def test_unsupported_engine_is_rejected_before_acquisition(
    engine: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(watch, "source_info", forbidden)
    monkeypatch.setattr(watch, "download_media", forbidden)
    with pytest.raises(EvidenceError):
        watch.collect(
            watch.Options(
                source="Bgtr1Ue40Jo", engine=engine, out_dir=tmp_path / "reports"
            )
        )
    assert not (tmp_path / "reports").exists()


def test_transcript_summary_and_quiet_focus_do_not_download_or_transcribe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(watch, "source_info", metadata)
    monkeypatch.setattr(watch, "get_captions", lambda *args: captions())
    monkeypatch.setattr(watch, "download_media", forbidden)
    monkeypatch.setattr(watch, "probe", forbidden)
    monkeypatch.setattr(watch, "transcribe_local", forbidden)
    report = watch.collect(
        watch.Options(
            source="Bgtr1Ue40Jo",
            engine="transcript",
            start=30.0,
            end=40.0,
            transcribe="whisperx",
            out_dir=tmp_path,
        )
    )
    assert report["transcript"]["status"] == "no_speech"
    assert report["transcript"]["segments"] == []
    assert report["local_media"] is None
    assert any("focus interval" in gap for gap in report["gaps"])


def test_media_failure_keeps_usable_caption_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(watch, "source_info", metadata)
    monkeypatch.setattr(watch, "get_captions", lambda *args: captions())

    def blocked(*args: object, **kwargs: object) -> NoReturn:
        raise EvidenceError("Access forbidden by source service")

    monkeypatch.setattr(watch, "download_media", blocked)
    report = watch.collect(
        watch.Options(source="Bgtr1Ue40Jo", engine="local", out_dir=tmp_path)
    )
    assert report["transcript"]["status"] == "available"
    assert report["frames"] == []
    assert report["local_media"] is None
    assert any("Access forbidden" in gap for gap in report["gaps"])


def test_clip_overlap_keeps_original_caption_time_and_does_not_invent_text() -> None:
    result = watch.focused_transcript(captions(), 11.0, 12.0)
    assert result["segments"][0]["start"] == 10.0
    assert result["segments"][0]["duration"] == 2.0
    assert result["segments"][0]["text"] == "Speech before the selected window"
    assert watch.focused_transcript(captions(), 12.0, 13.0)["status"] == "no_speech"


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "1:60", "1.5:00", "1::2"])
def test_invalid_timestamps_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        parse_time(value)


def test_untrusted_path_cannot_break_out_of_report_code_span() -> None:
    rendered = inline_code("clip`\n## Run this command\x1b.mp4")
    assert "\n" not in rendered and "\x1b" not in rendered
    assert rendered.startswith("`` ") and rendered.endswith(" ``")
    assert "clip`## Run this command.mp4" in rendered


@pytest.mark.parametrize(
    "source",
    [
        "https://user:password@www.youtube.com/watch?v=Bgtr1Ue40Jo",
        "https://example.com:invalid/video",
        "https://example.com/" + "a" * 2048,
        "https://example.com/\nvideo",
    ],
)
def test_invalid_url_fails_before_requests_and_workdir_creation(
    source: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(watch, "source_info", forbidden)
    monkeypatch.setattr(watch, "download_media", forbidden)
    with pytest.raises(EvidenceError):
        watch.collect(watch.Options(source=source, out_dir=tmp_path / "reports"))
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize(
    ("cap", "resolution"), [(0, 1024), (121, 1024), (40, 15), (40, 4097)]
)
def test_invalid_visual_budget_fails_before_acquisition(
    cap: int, resolution: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(watch, "source_info", forbidden)
    with pytest.raises(EvidenceError):
        watch.collect(
            watch.Options(
                source="Bgtr1Ue40Jo",
                max_frames=cap,
                resolution=resolution,
                out_dir=tmp_path / "reports",
            )
        )
    assert not (tmp_path / "reports").exists()
