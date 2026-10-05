"""Explicit local speech-to-text through an isolated WhisperX environment.

WhisperX and its Torch stack live in a separate uv-provisioned Python (see
``setup_speech.py``); this module only shells out to ``whisperx_runner.py``
inside it. If that environment is absent the call fails clearly. It never
installs anything, never touches the network, and never falls back to a cloud
provider. The runner is told to stay offline, so an unwarmed model also fails
instead of silently downloading.
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Final, Mapping, Sequence

from evidence import EvidenceError, Segment, Transcript, empty_transcript
from runtime import diagnostic, run

WHISPERX_VERSION: Final = "3.8.6"
PYTHON_ENV: Final = "WATCH_WHISPERX_PYTHON"
TIMEOUT_ENV: Final = "WATCH_WHISPERX_TIMEOUT"
DEVICE_ENV: Final = "WATCH_WHISPERX_DEVICE"
COMPUTE_TYPE_ENV: Final = "WATCH_WHISPERX_COMPUTE_TYPE"
BATCH_SIZE_ENV: Final = "WATCH_WHISPERX_BATCH_SIZE"

VENV_DIR: Final = Path.home() / ".cache" / "armory" / "watch" / "whisperx-venv"
RUNNER: Final = Path(__file__).resolve().with_name("whisperx_runner.py")
SETUP_COMMAND: Final = "uv run --no-project --python 3.12 python " + shlex.quote(
    str(RUNNER.with_name("setup_speech.py"))
)

MODELS: Final = frozenset(
    {
        "tiny",
        "base",
        "small",
        "medium",
        "turbo",
        "large",
        "large-v1",
        "large-v2",
        "large-v3",
        "large-v3-turbo",
        "tiny.en",
        "base.en",
        "small.en",
        "medium.en",
    }
)
DEVICES: Final = ("cpu", "cuda")
COMPUTE_TYPES: Final = ("int8", "float16", "float32")

AUDIO_NAME: Final = "whisperx-audio.wav"
RESULT_NAME: Final = "whisperx-result.json"
_DEFAULT_TIMEOUT: Final = 7200.0
_LANGUAGE: Final = re.compile(r"[a-z]{2,3}")


def venv_python() -> Path:
    return VENV_DIR / "bin" / "python"


def whisperx_python() -> Path:
    """The interpreter that has WhisperX: the explicit override, else the provisioned venv."""
    override = os.environ.get(PYTHON_ENV, "").strip()
    return Path(override).expanduser() if override else venv_python()


def missing_environment_message(model: str) -> str:
    return (
        f"Local speech-to-text is not provisioned (no WhisperX interpreter at {whisperx_python()}). "
        f"Nothing is installed automatically and no cloud fallback is used. "
        f"To opt in, run: {SETUP_COMMAND} --model {shlex.quote(model)}"
    )


def require_model(model: str) -> None:
    if model not in MODELS:
        raise EvidenceError(
            f"Unsupported WhisperX model {model!r}; choose one of: {', '.join(sorted(MODELS))}."
        )


def _timeout() -> float:
    raw = os.environ.get(TIMEOUT_ENV, "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        raise EvidenceError(f"{TIMEOUT_ENV} must be a positive number of seconds.")
    return value


def runner_command(interpreter: Path) -> list[str]:
    """``-I`` keeps this scripts directory (and its generic module names) off the worker's sys.path."""
    return [str(interpreter), "-I", str(RUNNER)]


def runner_options() -> list[str]:
    """Runner flags from the explicit device/compute/batch environment settings."""
    device = os.environ.get(DEVICE_ENV, "cpu").strip() or "cpu"
    if device not in DEVICES:
        raise EvidenceError(
            f"{DEVICE_ENV} must be one of {', '.join(DEVICES)} (default cpu)."
        )
    compute = os.environ.get(COMPUTE_TYPE_ENV, "").strip() or (
        "float16" if device == "cuda" else "int8"
    )
    if compute not in COMPUTE_TYPES:
        raise EvidenceError(
            f"{COMPUTE_TYPE_ENV} must be one of {', '.join(COMPUTE_TYPES)}."
        )
    batch = os.environ.get(BATCH_SIZE_ENV, "").strip() or "8"
    if not batch.isdecimal() or int(batch) < 1:
        raise EvidenceError(f"{BATCH_SIZE_ENV} must be a positive integer.")
    return [
        "--device",
        device,
        "--compute-type",
        compute,
        "--batch-size",
        str(int(batch)),
    ]


def has_audio_stream(path: Path) -> bool:
    probe = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        timeout=120,
    )
    return bool(probe.stdout.strip())


def extract_audio(path: Path, wav: Path) -> None:
    """16 kHz mono PCM on the media's own timeline.

    ``first_pts=0`` pads leading silence when the audio stream starts late, so
    transcript times equal source-media times. The source file is only read.
    """
    run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            "aresample=async=1:first_pts=0",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ],
        timeout=_timeout(),
    )


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def normalize_segments(raw: Sequence[object]) -> tuple[list[Segment], int]:
    """WhisperX ``start``/``end`` records to ordered ``start``/``duration`` segments.

    Times stay on the transcribed media's timeline. Records with non-finite or
    negative times, ``end <= start``, or empty text are dropped and counted;
    the rest are sorted by start so the timeline is monotonic.
    """
    kept: list[Segment] = []
    dropped = 0
    for item in raw:
        record: Mapping[str, object] = item if isinstance(item, dict) else {}
        start, end = _finite(record.get("start")), _finite(record.get("end"))
        text = record.get("text")
        cleaned = " ".join(text.split()) if isinstance(text, str) else ""
        if start is None or end is None or start < 0 or end <= start or not cleaned:
            dropped += 1
            continue
        kept.append(
            {
                "start": round(start, 3),
                "duration": round(end - start, 3),
                "text": cleaned,
            }
        )
    kept.sort(key=lambda segment: segment["start"])
    return kept, dropped


def _read_result(result_path: Path) -> tuple[list[object], object]:
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvidenceError(
            f"WhisperX produced no readable result at {result_path.name}: {diagnostic(str(exc), 200)}"
        ) from exc
    segments = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(segments, list):
        raise EvidenceError("WhisperX result is not an object with a segments list.")
    return segments, data.get("language")


def transcribe_local(
    path: Path,
    work_dir: Path,
    *,
    language: str | None = None,
    model: str = "small",
) -> Transcript:
    """Transcribe ``path`` with local WhisperX; segment times are source-media seconds.

    Sidecars (``whisperx-audio.wav``, ``whisperx-result.json``) go in ``work_dir``;
    ``path`` is never modified. Raises :class:`EvidenceError` when the environment
    is not provisioned, the model is not warmed, or the runner fails.
    """
    require_model(model)
    if language is not None and not _LANGUAGE.fullmatch(language):
        raise EvidenceError(
            "Spoken language must be a lowercase ISO 639 code such as en or de."
        )
    if not path.is_file():
        raise EvidenceError(
            f"Media file not found for local transcription: {path.name}"
        )
    interpreter = whisperx_python()
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise EvidenceError(missing_environment_message(model))
    options = runner_options()
    timeout = _timeout()
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise EvidenceError("Local transcription needs ffmpeg and ffprobe on PATH.")
    if not has_audio_stream(path):
        return empty_transcript(
            "unavailable", "the media has no audio stream to transcribe"
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    wav, result_path = work_dir / AUDIO_NAME, work_dir / RESULT_NAME
    result_path.unlink(missing_ok=True)
    extract_audio(path, wav)
    command = [
        *runner_command(interpreter),
        "--mode",
        "transcribe",
        "--model",
        model,
        "--audio",
        str(wav),
        "--output",
        str(result_path),
        *options,
    ]
    if language is not None:
        command += ["--language", language]
    try:
        run(command, timeout=timeout)
    except EvidenceError as exc:
        raise EvidenceError(
            f"{exc} If the failure mentions a missing model, warm it with: "
            f"{SETUP_COMMAND} --model {shlex.quote(model)}"
        ) from exc

    raw_segments, reported = _read_result(result_path)
    segments, dropped = normalize_segments(raw_segments)
    detected = (
        reported
        if isinstance(reported, str) and _LANGUAGE.fullmatch(reported)
        else None
    )
    gaps = [
        "WhisperX alignment and diarization are off: segment times are speech-chunk bounds, "
        "with no word timing or speaker labels."
    ]
    if dropped:
        gaps.append(
            f"Dropped {dropped} WhisperX segment(s) with unusable times or empty text."
        )
    if detected is None:
        gaps.append("WhisperX did not report a language for this audio.")
    source = f"whisperx-local:{model}"
    if not segments:
        return {
            "status": "no_speech",
            "segments": [],
            "language": detected,
            "source": source,
            "kind": "asr",
            "gaps": [*gaps, "WhisperX found no speech in the audio."],
        }
    return {
        "status": "available",
        "segments": segments,
        "language": detected,
        "source": source,
        "kind": "asr",
        "gaps": gaps,
    }
