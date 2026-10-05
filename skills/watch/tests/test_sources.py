"""Behavior of caption/metadata/media acquisition at its trust boundaries.

Third-party boundaries (youtube-transcript-api, requests, yt-dlp) are replaced
by small fakes so that parsing, provenance, failure states and path safety run
through the public API without network access.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

import sources
from evidence import EvidenceError, Transcript

VIDEO_ID = "dQw4w9WgXcQ"
YOUTUBE_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
EXTERNAL_URL = "https://media.example.org/v/1"

Cue = tuple[object, object, str]


# ---------------------------------------------------------------- fakes


class ApiError(Exception):
    """Base of the fake library's exception hierarchy."""


class Disabled(ApiError):
    pass


class Blocked(ApiError):
    pass


@dataclass
class FakeTrack:
    language_code: str
    is_generated: bool
    cues: list[Cue] = field(default_factory=list)
    error: Exception | None = None

    def fetch(self) -> SimpleNamespace:
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            snippets=[
                SimpleNamespace(start=start, duration=duration, text=text)
                for start, duration, text in self.cues
            ]
        )


def install_api(
    monkeypatch: pytest.MonkeyPatch,
    tracks: list[FakeTrack] | None = None,
    *,
    list_error: Exception | None = None,
) -> None:
    """Install fake youtube_transcript_api and requests modules."""
    api = types.ModuleType("youtube_transcript_api")

    class FakeApi:
        def __init__(self, http_client: object = None) -> None:
            self.http_client = http_client

        def list(self, video_id: str) -> list[FakeTrack]:
            assert video_id == VIDEO_ID
            if list_error is not None:
                raise list_error
            return list(tracks or [])

    setattr(api, "YouTubeTranscriptApi", FakeApi)
    setattr(api, "TranscriptsDisabled", Disabled)
    setattr(api, "YouTubeTranscriptApiException", ApiError)
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", api)

    requests = types.ModuleType("requests")

    class Session:
        def request(
            self, method: object, url: object, *args: object, **kwargs: object
        ) -> None:
            return None

    setattr(requests, "Session", Session)
    setattr(requests, "Response", object)
    monkeypatch.setitem(sys.modules, "requests", requests)


def option(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def patch_run(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[list[str]], str]
) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(
        command: list[str], *, timeout: float = 300.0
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, handler(command), "")

    monkeypatch.setattr(sources, "run", fake_run)
    return calls


def no_commands(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    def handler(command: list[str]) -> str:
        raise AssertionError(f"unexpected subprocess: {command}")

    return patch_run(monkeypatch, handler)


def track_entry(
    ext: str = "json3", *, translation: bool = False
) -> list[dict[str, str]]:
    url = "https://www.youtube.com/api/timedtext?v=x&lang=l" + (
        "&tlang=de" if translation else ""
    )
    return [{"ext": "srv3", "url": url}, {"ext": ext, "url": url}]


def captioned(
    info: dict[str, object], files: dict[str, str]
) -> Callable[[list[str]], str]:
    """yt-dlp stand-in: serves ``info`` as metadata and writes ``files[language]`` for caption requests."""

    def handler(command: list[str]) -> str:
        if "--dump-single-json" in command:
            return json.dumps({"_type": "video", "title": "Talk", **info})
        language = re.sub(r"\\(.)", r"\1", option(command, "--sub-langs"))
        scratch = Path(option(command, "-P").removeprefix("subtitle:"))
        ext = option(command, "--sub-format")
        (scratch / f"captions.{language}.{ext}").write_text(
            files[language], encoding="utf-8"
        )
        return ""

    return handler


def json3(*events: dict[str, object]) -> str:
    return json.dumps({"events": list(events)})


def event(start: object, duration: object, text: str) -> dict[str, object]:
    return {"tStartMs": start, "dDurationMs": duration, "segs": [{"utf8": text}]}


def texts(transcript: Transcript) -> list[str]:
    return [segment["text"] for segment in transcript["segments"]]


# ---------------------------------------------------------------- normalization


def test_rolling_overlap_is_removed_but_repeated_speech_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cues: list[Cue] = [
        (0.0, 4.0, "we are going to"),
        (2.0, 4.0, "going to build a parser"),  # rolling: repeats "going to"
        (5.0, 2.0, "build a parser"),  # rolling: wholly repeated
        (10.0, 1.0, "no"),
        (12.0, 1.0, "no"),  # independent repeated speech, no time overlap
        (20.0, 1.0, "I know"),
        (21.5, 1.0, "I know"),
    ]
    install_api(monkeypatch, [FakeTrack("en", False, cues)])
    no_commands(monkeypatch)

    transcript = sources.get_captions(YOUTUBE_URL, tmp_path)

    assert transcript["status"] == "available"
    assert texts(transcript) == [
        "we are going to",
        "build a parser",
        "no",
        "no",
        "I know",
        "I know",
    ]
    assert [segment["start"] for segment in transcript["segments"]] == [
        0.0,
        2.0,
        10.0,
        12.0,
        20.0,
        21.5,
    ]
    assert (
        transcript["segments"][1]["duration"] == 5.0
    )  # still covers the dropped duplicate


def test_overlapping_identical_cue_is_one_utterance_but_single_shared_word_is_not_a_duplicate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cues: list[Cue] = [
        (0.0, 3.0, "hello there"),
        (1.0, 3.0, "hello there"),
        (10.0, 3.0, "I think so"),
        (11.0, 3.0, "so what"),
    ]
    install_api(monkeypatch, [FakeTrack("en", False, cues)])

    transcript = sources.get_captions(VIDEO_ID, tmp_path)

    assert texts(transcript) == ["hello there", "I think so", "so what"]


def test_malformed_timestamps_are_dropped_and_order_is_repaired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cues: list[Cue] = [
        (8.0, 1.0, "<i>later</i>  cue"),
        (math.nan, 1.0, "nan start"),
        (-1.0, 1.0, "negative start"),
        ("3", 1.0, "string start"),
        (True, 1.0, "bool start"),
        (5.0, math.inf, "infinite duration"),
        (2.0, 1.0, "first <00:00:02.500><c>cue</c>"),
        (1.0, 1.0, "x < y and y > z"),
        (math.nan, 1.0, "   "),  # nothing to say, so nothing malformed to report
    ]
    install_api(monkeypatch, [FakeTrack("en", False, cues)])

    transcript = sources.get_captions(VIDEO_ID, tmp_path)

    assert transcript["status"] == "available"
    assert texts(transcript) == ["x < y and y > z", "first cue", "later cue"]
    starts = [segment["start"] for segment in transcript["segments"]]
    assert starts == sorted(starts) and all(math.isfinite(s) and s >= 0 for s in starts)
    assert any("Dropped 5" in gap for gap in transcript["gaps"])
    assert any("Reordered" in gap for gap in transcript["gaps"])


# ---------------------------------------------------------------- language provenance


def test_manual_track_in_requested_language_beats_generated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_api(
        monkeypatch,
        [
            FakeTrack("en", True, [(0.0, 1.0, "auto")]),
            FakeTrack("en", False, [(0.0, 1.0, "manual")]),
        ],
    )

    transcript = sources.get_captions(VIDEO_ID, tmp_path, "en")

    assert (transcript["kind"], transcript["language"], texts(transcript)) == (
        "manual",
        "en",
        ["manual"],
    )
    assert transcript["source"] == "youtube-transcript-api"
    assert transcript["gaps"] == []


def test_generated_track_in_requested_language_beats_manual_in_another(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_api(
        monkeypatch,
        [
            FakeTrack("de", False, [(0.0, 1.0, "deutsch")]),
            FakeTrack("en", True, [(0.0, 1.0, "english")]),
        ],
    )

    transcript = sources.get_captions(VIDEO_ID, tmp_path, "en")

    assert (transcript["kind"], transcript["language"]) == ("auto-generated", "en")
    assert transcript["gaps"] == []


@pytest.mark.parametrize(("available", "requested"), [("fr", "en"), ("en-US", "en")])
def test_fallback_language_is_recorded_not_claimed_as_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, available: str, requested: str
) -> None:
    install_api(monkeypatch, [FakeTrack(available, False, [(0.0, 1.0, "bonjour")])])

    transcript = sources.get_captions(VIDEO_ID, tmp_path, requested)

    assert transcript["language"] == available
    assert transcript["kind"] == "manual"
    assert any(requested in gap and available in gap for gap in transcript["gaps"])


# ---------------------------------------------------------------- failure states


def test_disabled_captions_are_unavailable_and_nothing_is_downloaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_api(monkeypatch, list_error=Disabled("subtitles are disabled"))
    calls = no_commands(monkeypatch)

    transcript = sources.get_captions(VIDEO_ID, tmp_path)

    assert transcript["status"] == "unavailable"
    assert transcript["segments"] == [] and transcript["language"] is None
    assert calls == []


def test_video_without_tracks_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_api(monkeypatch, [])
    calls = no_commands(monkeypatch)

    assert sources.get_captions(VIDEO_ID, tmp_path)["status"] == "unavailable"
    assert calls == []


def test_every_backend_failing_reports_failed_with_each_diagnostic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_api(monkeypatch, list_error=Blocked("IP blocked by YouTube"))

    def handler(command: list[str]) -> str:
        raise EvidenceError("Missing executable: yt-dlp")

    patch_run(monkeypatch, handler)

    transcript = sources.get_captions(VIDEO_ID, tmp_path)

    assert transcript["status"] == "failed"
    assert transcript["segments"] == []
    joined = " ".join(transcript["gaps"])
    assert "Blocked" in joined and "IP blocked" in joined
    assert "Missing executable: yt-dlp" in joined and "Install yt-dlp" in joined


def test_unusable_api_track_is_reported_when_ytdlp_finds_no_alternative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_api(
        monkeypatch, [FakeTrack("en", False, [(math.nan, 1.0, "only bad timing")])]
    )
    patch_run(monkeypatch, captioned({}, {}))

    transcript = sources.get_captions(VIDEO_ID, tmp_path)

    # API produced nothing usable, yt-dlp then found no track at all.
    assert transcript["status"] == "unavailable"
    assert any("no usable caption text" in gap for gap in transcript["gaps"])


def test_missing_caption_library_is_reported_and_ytdlp_is_tried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)
    files = {"en": json3(event(0, 1000, "from the fallback"))}
    patch_run(monkeypatch, captioned({"subtitles": {"en": track_entry()}}, files))

    transcript = sources.get_captions(VIDEO_ID, tmp_path)

    assert transcript["status"] == "available"
    assert transcript["source"] == "yt-dlp"
    assert any("not installed" in gap for gap in transcript["gaps"])


def test_failed_caption_fetch_does_not_become_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_api(monkeypatch, [FakeTrack("en", False, error=Blocked("HTTP 429"))])

    def handler(command: list[str]) -> str:
        raise EvidenceError("yt-dlp failed (1): network down")

    patch_run(monkeypatch, handler)

    transcript = sources.get_captions(VIDEO_ID, tmp_path)

    assert transcript["status"] == "failed"
    assert "HTTP 429" in " ".join(transcript["gaps"])
    assert "network down" in " ".join(transcript["gaps"])


@pytest.mark.parametrize(
    "source",
    [
        "ftp://example.org/v.mp4",
        "file:///etc/passwd",
        "https://user:secret@example.org/v.mp4",
        "https://www.youtube.com/playlist?list=PL1234567890",
        "not a source at all",
        "",
    ],
)
def test_unsupported_sources_fail_at_the_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str
) -> None:
    calls = no_commands(monkeypatch)

    transcript = sources.get_captions(source, tmp_path)

    assert transcript["status"] == "failed"
    with pytest.raises(EvidenceError):
        sources.source_info(source)
    with pytest.raises(EvidenceError):
        sources.download_media(source, tmp_path)
    assert calls == []


def test_invalid_language_code_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = no_commands(monkeypatch)

    assert sources.get_captions(YOUTUBE_URL, tmp_path, "all,en.*")["status"] == "failed"
    assert calls == []


def test_local_file_captions_are_unavailable_without_any_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    local = tmp_path / "talk.mp4"
    local.write_bytes(b"x")
    calls = no_commands(monkeypatch)

    transcript = sources.get_captions(str(local), tmp_path)

    assert transcript["status"] == "unavailable"
    assert calls == []
    assert local.read_bytes() == b"x"


# ---------------------------------------------------------------- yt-dlp captions


def test_ytdlp_fallback_requests_one_exact_track_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_api(monkeypatch, list_error=Blocked("IP blocked"))
    info: dict[str, object] = {
        "subtitles": {"en": track_entry(), "fr": track_entry()},
        "automatic_captions": {
            "en": track_entry(),
            "de": track_entry(translation=True),
        },
    }
    files = {
        "en": json3(
            {
                "tStartMs": 0,
                "dDurationMs": 2000,
                "segs": [{"utf8": "Hello "}, {"utf8": "world"}],
            },
            event(2000, 1000, "\n"),
            event("soon", 10, "bad timing"),
            event(3000, 1000, "again"),
        )
    }
    calls = patch_run(monkeypatch, captioned(info, files))

    transcript = sources.get_captions(YOUTUBE_URL, tmp_path)

    assert transcript["status"] == "available"
    assert (transcript["source"], transcript["kind"], transcript["language"]) == (
        "yt-dlp",
        "manual",
        "en",
    )
    assert texts(transcript) == ["Hello world", "again"]
    assert [segment["start"] for segment in transcript["segments"]] == [0.0, 3.0]
    gaps = " ".join(transcript["gaps"])
    assert "Blocked" in gaps and "Dropped 1" in gaps
    (caption_call,) = [call for call in calls if "--sub-langs" in call]
    pattern = re.sub(r"\\(.)", r"\1", option(caption_call, "--sub-langs"))
    assert pattern == "en"  # one exact language, no glob/list
    assert "--skip-download" in caption_call
    assert list(tmp_path.iterdir()) == []


def test_ytdlp_uses_generated_track_when_no_manual_one_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info: dict[str, object] = {
        "subtitles": {},
        "automatic_captions": {"en": track_entry()},
    }
    patch_run(monkeypatch, captioned(info, {"en": json3(event(0, 1000, "auto words"))}))

    transcript = sources.get_captions(EXTERNAL_URL, tmp_path)

    assert (transcript["status"], transcript["kind"]) == ("available", "auto-generated")
    assert transcript["gaps"] == []


def test_ytdlp_does_not_prefer_machine_translation_over_original_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info: dict[str, object] = {
        "language": "en",
        "subtitles": {},
        "automatic_captions": {
            "en": track_entry(),
            "de": track_entry(translation=True),
        },
    }
    patch_run(monkeypatch, captioned(info, {"en": json3(event(0, 1000, "original"))}))

    transcript = sources.get_captions(EXTERNAL_URL, tmp_path, "de")

    assert (transcript["kind"], transcript["language"], texts(transcript)) == (
        "auto-generated",
        "en",
        ["original"],
    )
    assert any("'de'" in gap and "'en'" in gap for gap in transcript["gaps"])


def test_ytdlp_reports_a_translation_track_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info: dict[str, object] = {
        "subtitles": {},
        "automatic_captions": {"de": track_entry(translation=True)},
    }
    patch_run(monkeypatch, captioned(info, {"de": json3(event(0, 1000, "übersetzt"))}))

    transcript = sources.get_captions(EXTERNAL_URL, tmp_path, "de")

    assert (transcript["kind"], transcript["language"]) == ("translation", "de")
    assert any("machine translation" in gap for gap in transcript["gaps"])


def test_ytdlp_vtt_track_is_parsed_with_markup_stripped_and_rolling_overlap_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vtt = (
        "WEBVTT\nKind: captions\n\n"
        "00:00:00.000 --> 00:00:02.000 align:start position:0%\nso <c>we</c> will see\n\n"
        "00:00:01.500 --> 00:00:03.000\nwe will see what\n\n"
        "00:00:5.000 --> 00:00:06.000\nbad timing\n\n"
        "01:00:07.000 --> 01:00:08.000\nan hour in\n"
    )
    info: dict[str, object] = {
        "subtitles": {"en": [{"ext": "vtt", "url": "https://media.example.org/en.vtt"}]}
    }
    patch_run(monkeypatch, captioned(info, {"en": vtt}))

    transcript = sources.get_captions(EXTERNAL_URL, tmp_path)

    assert texts(transcript) == ["so we will see", "what", "an hour in"]
    assert transcript["segments"][2]["start"] == 3600 + 7.0
    assert any("Dropped 1" in gap for gap in transcript["gaps"])


def test_video_without_caption_tracks_is_unavailable_and_downloads_no_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = patch_run(
        monkeypatch, captioned({"subtitles": {}, "automatic_captions": {}}, {})
    )

    transcript = sources.get_captions(EXTERNAL_URL, tmp_path)

    assert transcript["status"] == "unavailable"
    assert all("--print" not in call and "-f" not in call for call in calls)
    assert list(tmp_path.iterdir()) == []


def test_missing_ytdlp_is_failed_with_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(command: list[str]) -> str:
        raise EvidenceError("Missing executable: yt-dlp")

    patch_run(monkeypatch, handler)

    transcript = sources.get_captions(EXTERNAL_URL, tmp_path)

    assert transcript["status"] == "failed"
    assert "Install yt-dlp" in " ".join(transcript["gaps"])


def test_caption_file_not_written_is_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(command: list[str]) -> str:
        if "--dump-single-json" in command:
            return json.dumps(
                {"_type": "video", "title": "t", "subtitles": {"en": track_entry()}}
            )
        return ""

    patch_run(monkeypatch, handler)

    transcript = sources.get_captions(EXTERNAL_URL, tmp_path)

    assert transcript["status"] == "failed"
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- source_info


def test_source_info_normalizes_metadata_without_inventing_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "_type": "video",
        "id": "abc",
        "title": "  A talk ",
        "uploader": "Uploader",
        "duration": math.nan,
        "upload_date": "20240131",
        "description": None,
    }
    patch_run(monkeypatch, lambda command: json.dumps(payload))

    info = sources.source_info(EXTERNAL_URL)

    assert info == {
        "title": "A talk",
        "channel": "Uploader",
        "duration_seconds": None,
        "upload_date": "2024-01-31",
        "description": "",
        "video_id": "abc",
    }


def test_source_info_without_title_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_run(monkeypatch, lambda command: json.dumps({"_type": "video", "id": "x"}))

    with pytest.raises(EvidenceError, match="title"):
        sources.source_info(YOUTUBE_URL)


def test_source_info_rejects_unparseable_and_playlist_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_run(monkeypatch, lambda command: "<html>")
    with pytest.raises(EvidenceError, match="unparseable"):
        sources.source_info(EXTERNAL_URL)
    patch_run(
        monkeypatch, lambda command: json.dumps({"_type": "playlist", "title": "p"})
    )
    with pytest.raises(EvidenceError, match="playlist"):
        sources.source_info(EXTERNAL_URL)


# ---------------------------------------------------------------- media download


def downloader(write: Callable[[Path], str]) -> Callable[[list[str]], str]:
    """yt-dlp stand-in: ``write(box)`` creates files and returns what --print would output."""

    def handler(command: list[str]) -> str:
        if "--dump-single-json" in command:
            return json.dumps({"_type": "video", "title": "t"})
        return write(Path(option(command, "-P")))

    return handler


def test_completed_media_is_returned_from_inside_the_work_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(box: Path) -> str:
        (box / "media.mp4").write_bytes(b"video")
        return f"{box / 'media.mp4'}\n"

    patch_run(monkeypatch, downloader(write))
    work = tmp_path / "work"

    path = sources.download_media(EXTERNAL_URL, work)

    assert path.read_bytes() == b"video"
    assert path.resolve().is_relative_to(work.resolve())


def test_audio_only_never_requests_video_and_video_is_height_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(box: Path) -> str:
        (box / "media.m4a").write_bytes(b"a")
        return f"{box / 'media.m4a'}\n"

    calls = patch_run(monkeypatch, downloader(write))

    sources.download_media(EXTERNAL_URL, tmp_path / "audio", audio_only=True)
    sources.download_media(EXTERNAL_URL, tmp_path / "video")

    audio_call = next(
        c for c in calls if "-f" in c and "--merge-output-format" not in c
    )
    video_call = next(c for c in calls if "--merge-output-format" in c)
    assert "bv" not in option(audio_call, "-f") and "height" not in option(
        audio_call, "-f"
    )
    assert "height<=?720" in option(video_call, "-f")
    assert int(option(video_call, "--max-filesize")) <= 256 * 1024 * 1024


def test_playlist_is_rejected_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = patch_run(
        monkeypatch, lambda command: json.dumps({"_type": "playlist", "title": "p"})
    )

    with pytest.raises(EvidenceError, match="playlist"):
        sources.download_media(EXTERNAL_URL, tmp_path / "work")

    assert len(calls) == 1
    assert not (tmp_path / "work").exists()


def test_local_source_is_never_downloaded_or_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "mine.mp4"
    local.write_bytes(b"precious")
    calls = no_commands(monkeypatch)

    with pytest.raises(EvidenceError, match="never downloaded"):
        sources.download_media(str(local), tmp_path)

    assert calls == []
    assert local.read_bytes() == b"precious"
    assert [p.name for p in tmp_path.iterdir()] == ["mine.mp4"]


def assert_rejected_and_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write: Callable[[Path], str],
    match: str,
) -> None:
    patch_run(monkeypatch, downloader(write))
    work = tmp_path / "work"

    with pytest.raises(EvidenceError, match=match):
        sources.download_media(EXTERNAL_URL, work)

    assert list(work.iterdir()) == []


def test_media_outside_the_work_directory_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    def write(box: Path) -> str:
        (outside / "media.mp4").write_bytes(b"secret")
        return f"{outside / 'media.mp4'}\n"

    assert_rejected_and_cleaned(tmp_path, monkeypatch, write, "outside")
    assert (outside / "media.mp4").read_bytes() == b"secret"


def test_media_reached_through_a_symlinked_directory_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "media.mp4").write_bytes(b"secret")

    def write(box: Path) -> str:
        (box / "link").symlink_to(outside, target_is_directory=True)
        return f"{box / 'link' / 'media.mp4'}\n"

    assert_rejected_and_cleaned(tmp_path, monkeypatch, write, "outside")
    assert (outside / "media.mp4").read_bytes() == b"secret"


def test_symlinked_media_file_is_rejected_and_target_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "user-video.mp4"
    target.write_bytes(b"user data")

    def write(box: Path) -> str:
        (box / "media.mp4").symlink_to(target)
        return f"{box / 'media.mp4'}\n"

    assert_rejected_and_cleaned(tmp_path, monkeypatch, write, "symlink")
    assert target.read_bytes() == b"user data"


@pytest.mark.parametrize(
    "name",
    [
        "media.mp4.part",
        "media.f137.mp4",
        "media.en.vtt",
        "media.json",
        "media.json3",
        "media.ytdl",
    ],
)
def test_partial_subtitle_and_metadata_files_are_not_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    def write(box: Path) -> str:
        (box / name).write_bytes(b"data")
        return f"{box / name}\n"

    assert_rejected_and_cleaned(tmp_path, monkeypatch, write, "not completed media")


def test_unexpected_extra_outputs_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(box: Path) -> str:
        (box / "media.mp4").write_bytes(b"video")
        (box / "media.en.vtt").write_text("WEBVTT")
        return f"{box / 'media.mp4'}\n"

    assert_rejected_and_cleaned(tmp_path, monkeypatch, write, "unexpected output")


def test_more_than_one_reported_file_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(box: Path) -> str:
        (box / "media.mp4").write_bytes(b"video")
        return f"{box / 'media.mp4'}\n{box / 'media.mp4'}\n"

    assert_rejected_and_cleaned(tmp_path, monkeypatch, write, "exactly one")


def test_no_reported_file_explains_the_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_rejected_and_cleaned(tmp_path, monkeypatch, lambda box: "", "720p")


def test_reported_file_that_does_not_exist_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_rejected_and_cleaned(
        tmp_path, monkeypatch, lambda box: f"{box / 'media.mp4'}\n", "does not exist"
    )


def test_empty_media_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(box: Path) -> str:
        (box / "media.mp4").write_bytes(b"")
        return f"{box / 'media.mp4'}\n"

    assert_rejected_and_cleaned(tmp_path, monkeypatch, write, "empty")


def test_media_over_the_byte_cap_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(box: Path) -> str:
        with (box / "media.mp4").open("wb") as handle:
            handle.truncate(256 * 1024 * 1024 + 1)  # sparse
        return f"{box / 'media.mp4'}\n"

    assert_rejected_and_cleaned(tmp_path, monkeypatch, write, "MiB")


def test_downloader_failure_leaves_no_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(command: list[str]) -> str:
        if "--dump-single-json" in command:
            return json.dumps({"_type": "video", "title": "t"})
        (Path(option(command, "-P")) / "media.mp4.part").write_bytes(b"half")
        raise EvidenceError("yt-dlp failed (1): connection reset")

    patch_run(monkeypatch, handler)
    work = tmp_path / "work"

    with pytest.raises(EvidenceError, match="connection reset"):
        sources.download_media(EXTERNAL_URL, work)

    assert list(work.iterdir()) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_vtt_space_only_payload_line_does_not_terminate_cue(
    newline: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vtt = newline.join(
        [
            "WEBVTT",
            "",
            "00:00:00.080 --> 00:00:02.869 align:start position:0%",
            " ",
            "First<00:00:00.400><c> sentence</c>.",
            "",
        ]
    )
    info: dict[str, object] = {
        "subtitles": {"en": [{"ext": "vtt", "url": "https://media.example.org/en.vtt"}]}
    }
    patch_run(monkeypatch, captioned(info, {"en": vtt}))
    transcript = sources.get_captions(EXTERNAL_URL, tmp_path)
    assert texts(transcript) == ["First sentence."]
    assert transcript["segments"][0]["start"] == 0.080


def test_word_timed_auto_vtt_merges_touching_hold_and_rolling_display_cues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.080 --> 00:00:02.869\n"
        "Let's<00:00:00.400><c> start</c> with the YouTube.\n\n"
        "00:00:02.869 --> 00:00:02.879\n"
        "Let's start with the YouTube.\n\n"
        "00:00:02.879 --> 00:00:05.749\n"
        "Let's start with the YouTube.\n"
        "We<00:00:03.000><c> learn</c> next.\n"
    )
    info: dict[str, object] = {
        "automatic_captions": {
            "en": [{"ext": "vtt", "url": "https://media.example.org/en.vtt"}]
        }
    }
    patch_run(monkeypatch, captioned(info, {"en": vtt}))
    transcript = sources.get_captions(EXTERNAL_URL, tmp_path)
    assert texts(transcript) == ["Let's start with the YouTube.", "We learn next."]
    assert [cue["start"] for cue in transcript["segments"]] == [0.080, 2.879]


def test_touching_plain_caption_cues_remain_independent_repeated_speech(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_api(
        monkeypatch,
        [FakeTrack("en", True, [(0.0, 1.0, "hello there"), (1.0, 1.0, "hello there")])],
    )
    no_commands(monkeypatch)
    transcript = sources.get_captions(YOUTUBE_URL, tmp_path)
    assert texts(transcript) == ["hello there", "hello there"]
    assert [cue["start"] for cue in transcript["segments"]] == [0.0, 1.0]


def test_word_timed_auto_vtt_repeated_speech_without_display_hold_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\n"
        "hello<00:00:00.400><c> there</c>\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "hello<00:00:01.400><c> there</c>\n"
    )
    info: dict[str, object] = {
        "automatic_captions": {
            "en": [{"ext": "vtt", "url": "https://media.example.org/en.vtt"}]
        }
    }
    patch_run(monkeypatch, captioned(info, {"en": vtt}))
    transcript = sources.get_captions(EXTERNAL_URL, tmp_path)
    assert texts(transcript) == ["hello there", "hello there"]
    assert [cue["start"] for cue in transcript["segments"]] == [0.0, 1.0]
