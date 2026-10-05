"""Behavior of the explicit cloud (Gemini) and local (WhisperX) evidence backends.

Gemini runs against a real loopback HTTP server standing in for Google, so the
actual request, streaming-upload, redirect and cleanup code executes. Local
speech runs against a stub interpreter that speaks the runner's CLI contract,
with real ffmpeg for audio extraction.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import threading
import wave
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import gemini
import setup_speech
import speech
from evidence import EvidenceError

KEY = "AIzaSyTestKeyThatMustNeverLeak0123456789"
FILE_NAME = "files/abc123"
YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

ANSWER = {
    "status": "completed",
    "steps": [
        {"type": "processing_call", "id": "c1"},
        {"type": "processing_result", "call_id": "c1"},
        {
            "type": "model_output",
            "content": [{"type": "text", "text": "At 0:05 a slide is SEEN."}],
        },
    ],
    "usage": {"total_tokens": 321},
}


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    body_length: int


@dataclass
class FakeGoogle:
    """Scriptable stand-in for the Gemini Interactions + Files API."""

    base: str = ""
    seen: list[Seen] = field(default_factory=list)
    interaction: tuple[int, bytes] = (200, json.dumps(ANSWER).encode())
    file_states: list[str] = field(default_factory=lambda: ["ACTIVE"])
    delete_status: int = 200
    session_url: str | None = None
    start_redirect: str | None = None

    def hits(self, method: str, path: str) -> list[Seen]:
        return [s for s in self.seen if s.method == method and s.path == path]

    def uploaded_bytes(self) -> int:
        return sum(s.body_length for s in self.hits("POST", "/session/1"))


def _handler_for(fake: FakeGoogle) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            return None

        def _reply(
            self, status: int, body: bytes = b"", headers: dict[str, str] | None = None
        ) -> None:
            self.send_response(status)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            streamed = 0
            body = b""
            if self.path == "/session/1":
                while streamed < length:  # Count without keeping the video.
                    streamed += len(self.rfile.read(min(65536, length - streamed)))
            else:
                body = self.rfile.read(length)
            fake.seen.append(
                Seen(
                    self.command,
                    self.path,
                    {k.lower(): v for k, v in self.headers.items()},
                    body,
                    streamed or len(body),
                )
            )
            if self.command == "POST" and self.path == "/v1beta/interactions":
                status, payload = fake.interaction
                if status in (301, 302, 307):
                    self._reply(status, headers={"Location": payload.decode()})
                else:
                    self._reply(status, payload)
            elif self.command == "POST" and self.path == "/upload/v1beta/files":
                if fake.start_redirect:
                    self._reply(307, headers={"Location": fake.start_redirect})
                else:
                    self._reply(
                        200,
                        b"{}",
                        {
                            "X-Goog-Upload-URL": fake.session_url
                            or f"{fake.base}/session/1"
                        },
                    )
            elif self.command == "POST" and self.path == "/session/1":
                state = fake.file_states[0]
                info = {
                    "name": FILE_NAME,
                    "uri": f"{fake.base}/v1beta/{FILE_NAME}",
                    "state": state,
                    "mimeType": "video/mp4",
                }
                self._reply(200, json.dumps({"file": info}).encode())
            elif self.command == "GET" and self.path == f"/v1beta/{FILE_NAME}":
                state = (
                    fake.file_states.pop(0)
                    if len(fake.file_states) > 1
                    else fake.file_states[0]
                )
                info = {
                    "name": FILE_NAME,
                    "uri": f"{fake.base}/v1beta/{FILE_NAME}",
                    "state": state,
                    "mimeType": "video/mp4",
                }
                self._reply(200, json.dumps(info).encode())
            elif self.command == "DELETE" and self.path == f"/v1beta/{FILE_NAME}":
                self._reply(
                    fake.delete_status,
                    b"{}"
                    if fake.delete_status < 400
                    else b'{"error":{"message":"nope"}}',
                )
            else:
                self._reply(404, b"{}")

        do_GET = do_POST = do_DELETE = _handle  # noqa: N815

    return Handler


def _serve() -> Iterator[FakeGoogle]:
    fake = FakeGoogle()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(fake))
    fake.base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def google() -> Iterator[FakeGoogle]:
    yield from _serve()


@pytest.fixture
def elsewhere() -> Iterator[FakeGoogle]:
    """A second origin that must never receive the API key or any traffic."""
    yield from _serve()


@pytest.fixture
def cloud(google: FakeGoogle, monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv("WATCH_GEMINI_API_BASE", google.base)
    monkeypatch.setattr(gemini, "POLL_INTERVAL_SECONDS", 0.0)
    return google


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(os.urandom(300_000))
    return path


def _interaction_input(fake: FakeGoogle) -> list[dict[str, object]]:
    (call,) = fake.hits("POST", "/v1beta/interactions")
    inputs: list[dict[str, object]] = json.loads(call.body)["input"]
    return inputs


# --- Gemini: consent and credentials -------------------------------------------------


def test_cloud_without_consent_fails_before_key_file_or_network(
    cloud: FakeGoogle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(EvidenceError, match="explicitly allowed"):
        gemini.analyze_video(str(tmp_path / "missing.mp4"), "q")
    with pytest.raises(EvidenceError, match="explicitly allowed"):
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=False)
    assert cloud.seen == []


def test_key_in_environment_never_authorizes_cloud(cloud: FakeGoogle) -> None:
    with pytest.raises(EvidenceError, match="explicitly allowed"):
        gemini.analyze_video(YOUTUBE, None)
    assert cloud.seen == []


def test_missing_key_fails_before_network(
    cloud: FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(EvidenceError, match="GEMINI_API_KEY"):
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=True)
    assert cloud.seen == []


@pytest.mark.parametrize(
    "base",
    [
        "https://example.com",
        "http://example.com:80",
        "http://127.0.0.1",
        "http://user@127.0.0.1:9",
        "ftp://127.0.0.1:9",
    ],
)
def test_api_base_override_is_loopback_http_only(
    base: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv("WATCH_GEMINI_API_BASE", base)
    with pytest.raises(EvidenceError) as caught:
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=True)
    assert KEY not in str(caught.value)
    assert "loopback" in str(caught.value)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"start": -1.0}, "start offset"),
        ({"start": 10.0, "end": 10.0}, "end offset"),
        ({"end": math.nan}, "end offset"),
    ],
)
def test_invalid_interval_is_rejected_before_network(
    cloud: FakeGoogle, kwargs: dict[str, float], message: str
) -> None:
    with pytest.raises(EvidenceError, match=message):
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=True, **kwargs)
    assert cloud.seen == []


@pytest.mark.parametrize(
    "source", ["https://example.com/video.mp4", "/no/such/file.mp4", "dQw4w9WgXcQ"]
)
def test_unusable_sources_fail_without_network(cloud: FakeGoogle, source: str) -> None:
    with pytest.raises(EvidenceError):
        gemini.analyze_video(source, "q", allow_cloud=True)
    assert cloud.seen == []


# --- Gemini: YouTube and processing honesty ------------------------------------------


def test_youtube_url_is_referenced_directly_and_key_travels_in_header(
    cloud: FakeGoogle,
) -> None:
    answer = gemini.analyze_video(
        "https://youtu.be/dQw4w9WgXcQ?t=30&list=x", "What happens?", allow_cloud=True
    )

    (call,) = cloud.hits("POST", "/v1beta/interactions")
    assert call.headers["x-goog-api-key"] == KEY
    assert KEY.encode() not in call.body
    video_input, text_input = _interaction_input(cloud)
    assert video_input["uri"] == YOUTUBE
    assert video_input["processing"] == "agentic"
    assert "What happens?" in str(text_input["text"])
    assert not cloud.hits("POST", "/upload/v1beta/files")
    assert not cloud.hits("DELETE", f"/v1beta/{FILE_NAME}")
    assert answer["text"] == "At 0:05 a slide is SEEN."
    assert answer["total_tokens"] == 321
    assert answer["cleanup_warning"] is None
    assert "1 navigation" in answer["processing"]


def test_agentic_claim_is_not_made_when_no_navigation_was_observed(
    cloud: FakeGoogle,
) -> None:
    body = {
        "status": "completed",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": "x"}]}],
    }
    cloud.interaction = (200, json.dumps(body).encode())
    answer = gemini.analyze_video(YOUTUBE, "q", allow_cloud=True)
    assert "no navigation" in answer["processing"]
    assert answer["total_tokens"] is None


def test_interval_uses_static_offsets_and_says_so(cloud: FakeGoogle) -> None:
    answer = gemini.analyze_video(YOUTUBE, "q", allow_cloud=True, start=30.5, end=60.0)
    video_input, _ = _interaction_input(cloud)
    assert video_input["processing"] == {
        "type": "static",
        "start_offset": "30.5s",
        "end_offset": "60s",
    }
    assert "not agentic" in answer["processing"]


def test_open_ended_interval_sets_only_the_start_offset(cloud: FakeGoogle) -> None:
    gemini.analyze_video(YOUTUBE, "q", allow_cloud=True, start=90.0)
    video_input, _ = _interaction_input(cloud)
    assert video_input["processing"] == {"type": "static", "start_offset": "90s"}


# --- Gemini: provider errors and redaction -------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "category"),
    [
        (401, {"error": {"message": "unauthenticated"}}, "auth"),
        (403, [{"error": {"message": "forbidden"}}], "auth"),
        (
            400,
            {"error": {"message": "API key not valid. Please pass a valid API key."}},
            "auth",
        ),
        (429, {"error": {"message": "quota exceeded"}}, "quota"),
        (503, {"error": {"message": "overloaded"}}, "service"),
        (400, {"error": {"message": "bad request"}}, "rejected"),
    ],
)
def test_http_errors_are_categorized(
    cloud: FakeGoogle, status: int, body: object, category: str
) -> None:
    cloud.interaction = (status, json.dumps(body).encode())
    with pytest.raises(EvidenceError) as caught:
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=True)
    message = str(caught.value)
    assert message.startswith(f"Gemini {category}:")
    assert "No local fallback" in message


def test_key_and_unrelated_provider_body_never_reach_the_error(
    cloud: FakeGoogle,
) -> None:
    body = {
        "error": {
            "message": f"invalid key {KEY} and AIzaSyAnotherKeyShapedSecret0000000000"
        },
        "debug": "INTERNAL-PROVIDER-DETAIL",
    }
    cloud.interaction = (403, json.dumps(body).encode())
    with pytest.raises(EvidenceError) as caught:
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=True)
    message = str(caught.value)
    assert KEY not in message
    assert "AIzaSyAnother" not in message
    assert "INTERNAL-PROVIDER-DETAIL" not in message
    assert "[redacted]" in message


def test_non_json_error_body_is_not_echoed(cloud: FakeGoogle) -> None:
    cloud.interaction = (500, b"<html>SECRET-STACK-TRACE</html>")
    with pytest.raises(EvidenceError) as caught:
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=True)
    assert "SECRET-STACK-TRACE" not in str(caught.value)
    assert str(caught.value).startswith("Gemini service:")


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        json.dumps({"status": "completed", "steps": []}).encode(),
        json.dumps(
            {
                "status": "completed",
                "steps": [
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": "  "}],
                    }
                ],
            }
        ).encode(),
        json.dumps({"status": "failed", "steps": ANSWER["steps"]}).encode(),
        json.dumps({"status": "incomplete", "steps": ANSWER["steps"]}).encode(),
    ],
)
def test_invalid_or_unfinished_interactions_are_errors(
    cloud: FakeGoogle, body: bytes
) -> None:
    cloud.interaction = (200, body)
    with pytest.raises(EvidenceError, match="Gemini response"):
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=True)


def test_network_failure_names_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv(
        "WATCH_GEMINI_API_BASE", "http://127.0.0.1:9"
    )  # Discard port: refused.
    with pytest.raises(EvidenceError) as caught:
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=True)
    assert str(caught.value).startswith("Gemini network:")
    assert KEY not in str(caught.value)


def test_redirects_are_not_followed_so_the_key_stays_on_origin(
    cloud: FakeGoogle, elsewhere: FakeGoogle
) -> None:
    cloud.interaction = (307, f"{elsewhere.base}/v1beta/interactions".encode())
    with pytest.raises(EvidenceError):
        gemini.analyze_video(YOUTUBE, "q", allow_cloud=True)
    assert elsewhere.seen == []


def test_upload_session_url_on_another_origin_is_refused(
    cloud: FakeGoogle, elsewhere: FakeGoogle, video: Path
) -> None:
    cloud.session_url = f"{elsewhere.base}/session/1"
    with pytest.raises(EvidenceError, match="outside the API origin"):
        gemini.analyze_video(str(video), "q", allow_cloud=True)
    assert elsewhere.seen == []


def test_upload_start_redirect_is_not_followed(
    cloud: FakeGoogle, elsewhere: FakeGoogle, video: Path
) -> None:
    cloud.start_redirect = f"{elsewhere.base}/upload/v1beta/files"
    with pytest.raises(EvidenceError):
        gemini.analyze_video(str(video), "q", allow_cloud=True)
    assert elsewhere.seen == []


# --- Gemini: Files API upload and cleanup --------------------------------------------


def test_local_video_streams_to_files_api_then_is_deleted(
    cloud: FakeGoogle, video: Path
) -> None:
    cloud.file_states = ["PROCESSING", "PROCESSING", "ACTIVE"]
    answer = gemini.analyze_video(str(video), "q", allow_cloud=True)

    assert cloud.uploaded_bytes() == video.stat().st_size
    (start,) = cloud.hits("POST", "/upload/v1beta/files")
    assert start.headers["x-goog-upload-header-content-length"] == str(
        video.stat().st_size
    )
    assert start.headers["x-goog-api-key"] == KEY
    video_input, _ = _interaction_input(cloud)
    assert video_input["uri"] == f"{cloud.base}/v1beta/{FILE_NAME}"
    assert video_input["mime_type"] == "video/mp4"
    assert len(cloud.hits("DELETE", f"/v1beta/{FILE_NAME}")) == 1
    assert answer["cleanup_warning"] is None
    assert answer["text"]


def test_upload_is_deleted_when_the_interaction_fails(
    cloud: FakeGoogle, video: Path
) -> None:
    cloud.interaction = (500, b'{"error":{"message":"boom"}}')
    with pytest.raises(EvidenceError, match="Gemini service"):
        gemini.analyze_video(str(video), "q", allow_cloud=True)
    assert len(cloud.hits("DELETE", f"/v1beta/{FILE_NAME}")) == 1


def test_upload_is_deleted_when_processing_fails(
    cloud: FakeGoogle, video: Path
) -> None:
    cloud.file_states = ["PROCESSING", "FAILED"]
    with pytest.raises(EvidenceError, match="FAILED"):
        gemini.analyze_video(str(video), "q", allow_cloud=True)
    assert len(cloud.hits("DELETE", f"/v1beta/{FILE_NAME}")) == 1
    assert not cloud.hits("POST", "/v1beta/interactions")


def test_processing_wait_is_bounded_and_cleans_up(
    cloud: FakeGoogle, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cloud.file_states = ["PROCESSING"]
    monkeypatch.setattr(gemini, "PROCESSING_DEADLINE_SECONDS", 0.05)
    monkeypatch.setattr(gemini, "POLL_INTERVAL_SECONDS", 0.01)
    with pytest.raises(EvidenceError, match="still processing"):
        gemini.analyze_video(str(video), "q", allow_cloud=True)
    assert len(cloud.hits("DELETE", f"/v1beta/{FILE_NAME}")) == 1


def test_failed_cleanup_after_success_is_reported_not_hidden(
    cloud: FakeGoogle, video: Path
) -> None:
    cloud.delete_status = 500
    answer = gemini.analyze_video(str(video), "q", allow_cloud=True)
    warning = answer["cleanup_warning"]
    assert warning is not None
    assert FILE_NAME in warning
    assert "48 hours" in warning
    assert KEY not in warning
    assert answer["text"]


def test_failed_cleanup_after_error_is_appended_to_the_error(
    cloud: FakeGoogle, video: Path
) -> None:
    cloud.interaction = (429, b'{"error":{"message":"slow down"}}')
    cloud.delete_status = 500
    with pytest.raises(EvidenceError) as caught:
        gemini.analyze_video(str(video), "q", allow_cloud=True)
    message = str(caught.value)
    assert message.startswith("Gemini quota:")
    assert "Could not delete uploaded files/abc123" in message


def test_empty_video_is_not_uploaded(cloud: FakeGoogle, tmp_path: Path) -> None:
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(EvidenceError, match="empty"):
        gemini.analyze_video(str(empty), "q", allow_cloud=True)
    assert not cloud.hits("POST", "/session/1")
    assert not cloud.hits("DELETE", f"/v1beta/{FILE_NAME}")


# --- Local speech ---------------------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        assert (handle.getnchannels(), handle.getframerate()) == (1, 16000)
        return handle.getnframes() / handle.getframerate()


@pytest.fixture
def talking_video(tmp_path: Path) -> Path:
    """5 s of video whose 3 s audio track starts 2 s in."""
    path = tmp_path / "late-audio.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=5:size=64x64:rate=10",
        "-itsoffset",
        "2",
        "-f",
        "lavfi",
        "-i",
        "sine=duration=3",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "mpeg4",
        "-c:a",
        "aac",
        str(path),
    )
    return path


@pytest.fixture
def silent_video(tmp_path: Path) -> Path:
    path = tmp_path / "no-audio.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=64x64:rate=10",
        "-c:v",
        "mpeg4",
        str(path),
    )
    return path


def _stub_interpreter(tmp_path: Path, behavior: str) -> Path:
    """An executable that speaks the runner CLI: ``<exe> -I <runner> --mode ... --output ...``."""
    script = tmp_path / "stub-python"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, wave\n"
        "argv = sys.argv[3:]\n"
        "opt = {argv[i]: argv[i + 1] for i in range(0, len(argv) - 1, 2)}\n"
        "open(opt['--output'] + '.called', 'w').close()\n"
        f"{behavior}\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


SUCCESS = (
    "with wave.open(opt['--audio']) as w:\n"
    "    assert (w.getnchannels(), w.getframerate()) == (1, 16000)\n"
    "json.dump({'language': None, 'segments': [\n"
    "    {'start': 2.5, 'end': 3.0, 'text': ' second  line '},\n"
    "    {'start': 0.0, 'end': 2.5, 'text': 'first'},\n"
    "    {'start': 4.0, 'end': 4.0, 'text': 'zero length'},\n"
    "    {'start': None, 'end': 5.0, 'text': 'no start'},\n"
    "]}, open(opt['--output'], 'w'))\n"
)


def test_normalize_segments_orders_converts_and_drops_unusable() -> None:
    raw: list[object] = [
        {"start": 5.0, "end": 7.25, "text": "later"},
        {"start": 0.0, "end": 2.0, "text": "  first\n line "},
        {"start": math.nan, "end": 3.0, "text": "nan start"},
        {"start": 1.0, "end": math.inf, "text": "inf end"},
        {"start": -1.0, "end": 1.0, "text": "negative"},
        {"start": 3.0, "end": 3.0, "text": "empty interval"},
        {"start": 3.0, "end": 4.0, "text": "   "},
        {"start": True, "end": 4.0, "text": "bool start"},
        "not a record",
    ]
    segments, dropped = speech.normalize_segments(raw)
    assert segments == [
        {"start": 0.0, "duration": 2.0, "text": "first line"},
        {"start": 5.0, "duration": 2.25, "text": "later"},
    ]
    assert dropped == 7
    starts = [s["start"] for s in segments]
    assert starts == sorted(starts)


def test_transcription_without_provisioned_environment_fails_clearly_and_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "in.mp4"
    media.write_bytes(b"not read")
    monkeypatch.setenv("WATCH_WHISPERX_PYTHON", str(tmp_path / "absent" / "python"))
    monkeypatch.setenv("GEMINI_API_KEY", KEY)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no subprocess may run when speech is not provisioned")

    monkeypatch.setattr(speech, "run", forbidden)
    work = tmp_path / "work"
    with pytest.raises(EvidenceError) as caught:
        speech.transcribe_local(media, work, model="tiny")
    message = str(caught.value)
    assert "not provisioned" in message
    assert "setup_speech.py --model tiny" in message
    assert "no cloud fallback" in message.lower()
    assert not work.exists()


def test_default_environment_is_the_cached_venv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WATCH_WHISPERX_PYTHON", raising=False)
    assert (
        speech.whisperx_python()
        == Path.home() / ".cache/armory/watch/whisperx-venv/bin/python"
    )


@pytest.mark.parametrize(
    ("model", "language"), [("gigantic", None), ("tiny", "English"), ("tiny", "../x")]
)
def test_invalid_model_or_language_is_rejected(
    tmp_path: Path, model: str, language: str | None
) -> None:
    media = tmp_path / "in.mp4"
    media.write_bytes(b"x")
    with pytest.raises(EvidenceError):
        speech.transcribe_local(media, tmp_path / "w", language=language, model=model)


@needs_ffmpeg
def test_audio_extraction_keeps_the_media_timeline(
    talking_video: Path, tmp_path: Path
) -> None:
    wav = tmp_path / "audio.wav"
    speech.extract_audio(talking_video, wav)
    # The audio stream starts 2 s into a 5 s video; leading silence keeps times aligned.
    assert _wav_seconds(wav) == pytest.approx(5.0, abs=0.15)


@needs_ffmpeg
def test_transcription_returns_normalized_source_timeline_and_preserves_inputs(
    talking_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "WATCH_WHISPERX_PYTHON", str(_stub_interpreter(tmp_path, SUCCESS))
    )
    before = hashlib.sha256(talking_video.read_bytes()).hexdigest()
    work = tmp_path / "nested" / "work"

    transcript = speech.transcribe_local(talking_video, work, model="tiny")

    assert transcript["status"] == "available"
    assert transcript["segments"] == [
        {"start": 0.0, "duration": 2.5, "text": "first"},
        {"start": 2.5, "duration": 0.5, "text": "second line"},
    ]
    assert transcript["source"] == "whisperx-local:tiny"
    assert transcript["language"] is None
    assert any("language" in gap for gap in transcript["gaps"])
    assert any("Dropped 2" in gap for gap in transcript["gaps"])
    assert _wav_seconds(work / speech.AUDIO_NAME) == pytest.approx(5.0, abs=0.15)
    assert hashlib.sha256(talking_video.read_bytes()).hexdigest() == before


@needs_ffmpeg
def test_media_without_audio_is_unavailable_and_never_reaches_the_runner(
    silent_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "WATCH_WHISPERX_PYTHON", str(_stub_interpreter(tmp_path, SUCCESS))
    )
    work = tmp_path / "work"
    transcript = speech.transcribe_local(silent_video, work, model="tiny")
    assert transcript["status"] == "unavailable"
    assert transcript["segments"] == []
    assert "audio" in transcript["gaps"][0]
    assert not work.exists()


@needs_ffmpeg
def test_silence_is_reported_as_no_speech(
    talking_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _stub_interpreter(
        tmp_path,
        "json.dump({'language': 'en', 'segments': []}, open(opt['--output'], 'w'))",
    )
    monkeypatch.setenv("WATCH_WHISPERX_PYTHON", str(stub))
    transcript = speech.transcribe_local(talking_video, tmp_path / "w")
    assert transcript["status"] == "no_speech"
    assert transcript["language"] == "en"
    assert transcript["segments"] == []


@needs_ffmpeg
def test_runner_failure_surfaces_diagnostic_and_setup_hint_without_fallback(
    talking_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _stub_interpreter(
        tmp_path,
        "sys.stderr.write('LocalEntryNotFoundError: model small is not cached\\n')\nsys.exit(2)",
    )
    monkeypatch.setenv("WATCH_WHISPERX_PYTHON", str(stub))
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    with pytest.raises(EvidenceError) as caught:
        speech.transcribe_local(talking_video, tmp_path / "w", model="small")
    message = str(caught.value)
    assert "LocalEntryNotFoundError" in message
    assert "setup_speech.py --model small" in message


@needs_ffmpeg
@pytest.mark.parametrize(
    "behavior",
    [
        "pass",
        "open(opt['--output'], 'w').write('{broken')",
        "json.dump({'segments': 3}, open(opt['--output'], 'w'))",
    ],
)
def test_missing_or_malformed_runner_output_is_an_error(
    talking_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, behavior: str
) -> None:
    monkeypatch.setenv(
        "WATCH_WHISPERX_PYTHON", str(_stub_interpreter(tmp_path, behavior))
    )
    with pytest.raises(EvidenceError, match="WhisperX"):
        speech.transcribe_local(talking_video, tmp_path / "w")


@needs_ffmpeg
def test_stale_result_from_an_earlier_run_is_not_reused(
    talking_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "w"
    work.mkdir()
    (work / speech.RESULT_NAME).write_text(
        json.dumps({"segments": [{"start": 0, "end": 1, "text": "stale"}]})
    )
    monkeypatch.setenv(
        "WATCH_WHISPERX_PYTHON", str(_stub_interpreter(tmp_path, "pass"))
    )
    with pytest.raises(EvidenceError, match="WhisperX"):
        speech.transcribe_local(talking_video, work)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("WATCH_WHISPERX_DEVICE", "mps"),
        ("WATCH_WHISPERX_COMPUTE_TYPE", "int4"),
        ("WATCH_WHISPERX_BATCH_SIZE", "0"),
    ],
)
def test_invalid_runner_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(EvidenceError, match=variable):
        speech.runner_options()


def test_setup_without_uv_fails_before_touching_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(EvidenceError, match="uv is required"):
        setup_speech.provision("tiny")
