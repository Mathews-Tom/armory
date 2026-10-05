"""Opt-in provisioning of the local WhisperX speech environment.

Run explicitly; Watch never does this on its own::

    uv run --python 3.12 python scripts/setup_speech.py --model small

What it does (and the only things it downloads):

1. creates a uv Python 3.12 venv at ``~/.cache/armory/watch/whisperx-venv``
   (uv may fetch Python 3.12 if missing);
2. installs ``whisperx==3.8.6`` and its dependencies, including Torch, from
   PyPI with uv, a multi-GB download on first use;
3. downloads the chosen Whisper model (from Hugging Face, via faster-whisper)
   into the standard Hugging Face cache;
4. proves readiness by transcribing two seconds of silence in forced-offline
   mode (HF_HUB_OFFLINE), so a model that is not actually cached fails here, not later.

Telemetry flags for Hugging Face are disabled in the worker. Nothing is
uploaded: no audio or media leaves the machine.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path

from evidence import EvidenceError
from runtime import run
from speech import (
    MODELS,
    PYTHON_ENV,
    RESULT_NAME,
    VENV_DIR,
    WHISPERX_VERSION,
    runner_command,
    runner_options,
    venv_python,
)

_INSTALL_TIMEOUT = 3600.0
_MODEL_TIMEOUT = 3600.0
_VERIFY_TIMEOUT = 600.0


def step(message: str) -> None:
    print(f"[setup-speech] {message}", flush=True)


def installed_whisperx(python: Path, uv: str) -> str | None:
    listing = run(
        [uv, "pip", "list", "--python", str(python), "--format", "json"], timeout=300
    )
    try:
        packages = json.loads(listing.stdout)
    except ValueError as exc:
        raise EvidenceError("uv pip list returned unreadable output") from exc
    for package in packages:
        if isinstance(package, dict) and package.get("name") == "whisperx":
            version = package.get("version")
            return version if isinstance(version, str) else None
    return None


def write_silence(path: Path, seconds: int = 2, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * rate * seconds)


def provision(model: str) -> Path:
    uv = shutil.which("uv")
    if uv is None:
        raise EvidenceError(
            "uv is required (https://docs.astral.sh/uv/); install it and rerun."
        )
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise EvidenceError(
            f"Local transcription needs {', '.join(missing)} on PATH; install ffmpeg first."
        )
    python = venv_python()
    if not python.is_file():
        step(f"creating Python 3.12 environment at {VENV_DIR}")
        run([uv, "venv", "--python", "3.12", str(VENV_DIR)], timeout=_INSTALL_TIMEOUT)
    if installed_whisperx(python, uv) != WHISPERX_VERSION:
        step(
            f"installing whisperx=={WHISPERX_VERSION} (large download: Torch and dependencies)"
        )
        run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                f"whisperx=={WHISPERX_VERSION}",
            ],
            timeout=_INSTALL_TIMEOUT,
        )
        if installed_whisperx(python, uv) != WHISPERX_VERSION:
            raise EvidenceError(
                f"whisperx=={WHISPERX_VERSION} is not installed after the uv install step."
            )
    options = runner_options()
    step(f"downloading Whisper model {model!r} (cached for offline use)")
    run(
        [*runner_command(python), "--mode", "warm", "--model", model, *options],
        timeout=_MODEL_TIMEOUT,
    )
    step("verifying offline transcription on silence")
    with tempfile.TemporaryDirectory(prefix="watch-speech-") as scratch:
        wav, result = Path(scratch) / "silence.wav", Path(scratch) / RESULT_NAME
        write_silence(wav)
        run(
            [
                *runner_command(python),
                "--mode",
                "transcribe",
                "--model",
                model,
                "--audio",
                str(wav),
                "--output",
                str(result),
                *options,
            ],
            timeout=_VERIFY_TIMEOUT,
        )
        try:
            payload = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EvidenceError(
                "The offline verification run wrote no readable result."
            ) from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("segments"), list
        ):
            raise EvidenceError(
                "The offline verification result had an unexpected shape."
            )
    return python


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Provision local WhisperX speech-to-text for Watch."
    )
    parser.add_argument(
        "--model",
        choices=sorted(MODELS),
        default="small",
        help="Whisper model to download",
    )
    args = parser.parse_args(argv)
    try:
        python = provision(args.model)
    except EvidenceError as exc:
        print(f"[setup-speech] failed: {exc}", file=sys.stderr)
        return 1
    step(
        f"ready: whisperx {WHISPERX_VERSION}, model {args.model!r}, interpreter {python}"
    )
    if PYTHON_ENV in os.environ:
        step(
            f"note: {PYTHON_ENV} is set and overrides this environment at transcription time"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
