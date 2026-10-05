"""JSON-serializable evidence shared by Watch's acquisition backends."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class EvidenceError(RuntimeError):
    """An acquisition boundary failed; its message is safe to display."""


class Segment(TypedDict):
    start: float
    duration: float
    text: str


class Transcript(TypedDict):
    status: Literal["available", "unavailable", "failed", "disabled", "no_speech"]
    segments: list[Segment]
    language: str | None
    source: str
    kind: str
    gaps: list[str]


class SourceInfo(TypedDict):
    title: str
    channel: str | None
    duration_seconds: float | None
    upload_date: str | None
    description: str
    video_id: str | None


class MediaInfo(TypedDict):
    duration_seconds: float
    width: int
    height: int
    has_audio: bool
    has_video: bool


class Frame(TypedDict):
    timestamp_seconds: float
    path: str
    reason: str
    requested_seconds: NotRequired[float]


class CloudAnswer(TypedDict):
    text: str
    model: str
    processing: str
    total_tokens: int | None
    cleanup_warning: str | None


def empty_transcript(
    status: Literal["unavailable", "failed", "disabled", "no_speech"],
    message: str,
) -> Transcript:
    return {
        "status": status,
        "segments": [],
        "language": None,
        "source": "none",
        "kind": "none",
        "gaps": [message],
    }
