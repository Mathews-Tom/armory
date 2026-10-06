"""Local speech provisioning, timeline alignment, and input ownership."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import stat
import subprocess
import sys
import wave
from pathlib import Path

import pytest

import setup_speech
import speech
from evidence import EvidenceError


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
