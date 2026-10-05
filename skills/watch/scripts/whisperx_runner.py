"""WhisperX worker. Runs only inside the dedicated WhisperX environment.

This is the only file that imports WhisperX/Torch; the rest of Watch invokes it
as a subprocess. Two modes:

* ``warm``: download the chosen model once (the only network access, requested
  explicitly by ``setup_speech.py``).
* ``transcribe``: forced offline; a model that was never warmed fails loudly
  instead of downloading.

Alignment and diarization are not used, so segment times are speech-chunk
bounds. The language comes from the library result, not the CLI wrapper whose
``--no_align`` path overwrites it.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from importlib import import_module, metadata
from pathlib import Path

SAMPLE_RATE = 16000


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["warm", "transcribe"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument(
        "--compute-type", choices=["int8", "float16", "float32"], default="int8"
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--language", default=None)
    parser.add_argument("--audio", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    if args.mode == "transcribe" and (args.audio is None or args.output is None):
        parser.error("--mode transcribe requires --audio and --output")
    return args


def configure_environment(mode: str) -> None:
    """Set before importing WhisperX/huggingface_hub, which read these at import time."""
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    if mode == "transcribe":
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


def finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    configure_environment(args.mode)
    whisperx = import_module(
        "whisperx"
    )  # Heavy; deferred until the environment flags above are set.

    pipeline = whisperx.load_model(
        args.model,
        args.device,
        compute_type=args.compute_type,
        language=args.language,
        local_files_only=args.mode == "transcribe",
        threads=min(8, os.cpu_count() or 4),
    )
    if args.mode == "warm":
        print(
            f"whisperx {metadata.version('whisperx')} model {args.model} cached",
            file=sys.stderr,
        )
        return 0

    audio = whisperx.load_audio(str(args.audio), SAMPLE_RATE)
    result = pipeline.transcribe(
        audio, batch_size=args.batch_size, language=args.language
    )
    segments = [
        {
            "start": finite_float(item.get("start")),
            "end": finite_float(item.get("end")),
            "text": item.get("text", ""),
        }
        for item in result.get("segments", [])
    ]
    reported = result.get("language")
    payload = {
        "whisperx_version": metadata.version("whisperx"),
        "model": args.model,
        "language": args.language or (reported if isinstance(reported, str) else None),
        "language_source": "explicit"
        if args.language
        else ("detected" if isinstance(reported, str) else "unreported"),
        "segments": segments,
    }
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
