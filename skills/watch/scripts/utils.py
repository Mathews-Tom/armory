"""Source identifiers, timestamp validation, and transcript presentation."""

from __future__ import annotations

import math
import re
from typing import TypedDict
from urllib.parse import parse_qs, urlparse

from evidence import Segment


class Chunk(TypedDict):
    start: float
    end: float
    text: str


def parse_youtube_url(url: str) -> str | None:
    value = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        return None
    candidate: str | None = None
    if parsed.hostname in ("youtu.be", "www.youtu.be"):
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif parsed.hostname in (
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    ):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            match = re.fullmatch(r"/(?:shorts|embed|v|live)/([^/]+)/?", parsed.path)
            if match:
                candidate = match.group(1)
    return (
        candidate
        if candidate and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate)
        else None
    )


def parse_time(value: str) -> float:
    parts = value.split(":")
    if not 1 <= len(parts) <= 3 or any(not p or p.startswith("-") for p in parts):
        raise ValueError("Use nonnegative seconds, MM:SS, or HH:MM:SS")
    try:
        numbers = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    if any(not math.isfinite(n) or n < 0 for n in numbers):
        raise ValueError("Timestamp must be finite and nonnegative")
    if len(numbers) > 1:
        if any(n >= 60 for n in numbers[1:]) or any(
            not n.is_integer() for n in numbers[:-1]
        ):
            raise ValueError(
                "Minutes/seconds must be below 60; only seconds may be fractional"
            )
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60.0 + number
    return seconds


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def chunk_transcript(segments: list[Segment], chunk_minutes: int = 5) -> list[Chunk]:
    if chunk_minutes < 1:
        raise ValueError("Chunk duration must be positive")
    chunks: list[Chunk] = []
    for segment in segments:
        if not chunks or segment["start"] >= chunks[-1]["start"] + chunk_minutes * 60:
            chunks.append(
                {"start": segment["start"], "end": segment["start"], "text": ""}
            )
        chunk = chunks[-1]
        chunk["end"] = max(chunk["end"], segment["start"] + segment["duration"])
        chunk["text"] = (chunk["text"] + " " + segment["text"]).strip()
    return chunks


def inline_code(value: str) -> str:
    """Keep untrusted metadata and paths inside one padded CommonMark code span."""
    cleaned = "".join(c for c in value if ord(c) >= 32 and ord(c) != 127)
    fence = "`" * (max((len(m) for m in re.findall(r"`+", cleaned)), default=0) + 1)
    return f"{fence} {cleaned} {fence}"
