"""Source acquisition: metadata, captions and media for YouTube and http(s) URLs.

Captions come from captions already published for the video, never from speech
recognition.  YouTube videos try ``youtube-transcript-api`` first and fall back
to one exact ``yt-dlp`` caption track; other http(s) URLs use ``yt-dlp`` only.
No credentials, cookies, browser sessions or TLS overrides are used.  Passing
``--ignore-config`` keeps a user's ambient yt-dlp configuration (cookies,
downloader choices, proxies) from leaking in; opt-in authentication is
deliberately not supported here.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast
from urllib.parse import ParseResult, parse_qs, urlparse

from evidence import EvidenceError, Segment, SourceInfo, Transcript, empty_transcript
from runtime import diagnostic, run
from utils import parse_youtube_url

if TYPE_CHECKING:
    import subprocess

    import requests

_API_SOURCE = "youtube-transcript-api"
_YTDLP_SOURCE = "yt-dlp"

_HTTP_TIMEOUT = 30.0
_METADATA_TIMEOUT = 120.0
_CAPTION_TIMEOUT = 120.0
_DOWNLOAD_TIMEOUT = 1800.0
_MAX_URL_LENGTH = 2048
_MAX_CAPTION_BYTES = 8 * 1024 * 1024
_MAX_MEDIA_BYTES = 256 * 1024 * 1024
_MAX_MEDIA_HEIGHT = 720

_YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
_VTT_WORD_TIME = re.compile(r"<\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}>")
_TAG = re.compile(r"</?[A-Za-z][^<>]*>|" + _VTT_WORD_TIME.pattern)
_SPACE = re.compile(r"\s+")
_VTT_TIMING = re.compile(
    r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s+-->\s+(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"
)
# Never an acceptable downloaded media file, whatever yt-dlp reports.
_NON_MEDIA_SUFFIXES = frozenset(
    {
        ".part",
        ".ytdl",
        ".temp",
        ".tmp",
        ".json",
        ".json3",
        ".vtt",
        ".srt",
        ".ass",
        ".ttml",
        ".srv1",
        ".srv2",
        ".srv3",
        ".lrc",
        ".description",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }
)

_YTDLP_COMMON = [
    "yt-dlp",
    "--ignore-config",
    "--no-playlist",
    "--no-progress",
    "--no-cache-dir",
    "--no-warnings",
    "--socket-timeout",
    "30",
    "--retries",
    "3",
]


# ---------------------------------------------------------------- source parsing


@dataclass(frozen=True)
class _Source:
    kind: Literal["youtube", "http", "local"]
    url: str  # canonical single-video URL for remote sources, "" for local files
    video_id: str | None


def _classify(source: str) -> _Source:
    text = source.strip()
    if not text or any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise EvidenceError(
            "Source must be a YouTube URL/ID, an http(s) URL, or an existing local file"
        )
    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    if scheme in ("http", "https"):
        return _classify_url(text, parsed)
    if "://" in text:
        raise EvidenceError(
            f"Unsupported URL scheme '{scheme}': only http and https are accepted"
        )
    if Path(text).expanduser().exists():
        return _Source("local", "", None)
    video_id = parse_youtube_url(text)
    if video_id is not None and video_id == text:
        return _Source("youtube", _youtube_url(video_id), video_id)
    raise EvidenceError(
        f"'{diagnostic(text, 120)}' is not a YouTube URL/ID, an http(s) URL, or an existing local file"
    )


def _classify_url(text: str, parsed: ParseResult) -> _Source:
    if len(text) > _MAX_URL_LENGTH:
        raise EvidenceError(f"URL exceeds {_MAX_URL_LENGTH} characters")
    hostname = parsed.hostname
    if not hostname:
        raise EvidenceError("URL has no host")
    if parsed.username is not None or parsed.password is not None:
        raise EvidenceError("URLs with embedded credentials are not supported")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise EvidenceError("URL has an invalid port") from exc
    if hostname in _YOUTUBE_HOSTS:
        video_id = parse_youtube_url(text)
        if video_id is None:
            raise EvidenceError(
                "YouTube URL does not identify a single video (playlists and channels are not supported)"
            )
        return _Source("youtube", _youtube_url(video_id), video_id)
    return _Source("http", text, None)


def _youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# ---------------------------------------------------------------- JSON boundary


def _as_object(value: object) -> dict[str, object] | None:
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return cast("dict[str, object]", value)
    return None


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _seconds(value: object) -> float | None:
    """A finite, nonnegative number of seconds; booleans and strings are not timestamps."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {_SPACE.sub(' ', diagnostic(str(exc), 400))}"


# ---------------------------------------------------------------- yt-dlp


def _ytdlp(args: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return run([*_YTDLP_COMMON, *args], timeout=timeout)
    except EvidenceError as exc:
        if str(exc).startswith("Missing executable"):
            raise EvidenceError(
                f"{exc}. Install yt-dlp (for example `uv tool install yt-dlp`) and retry."
            ) from exc
        raise


def _ytdlp_metadata(url: str) -> dict[str, object]:
    result = _ytdlp(
        ["--skip-download", "--dump-single-json", "--", url], timeout=_METADATA_TIMEOUT
    )
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise EvidenceError(
            f"yt-dlp returned unparseable metadata: {diagnostic(result.stdout, 200)}"
        ) from exc
    info = _as_object(payload)
    if info is None:
        raise EvidenceError("yt-dlp metadata was not a JSON object")
    if info.get("_type", "video") != "video":
        raise EvidenceError(
            "URL resolves to a playlist or multi-video page; supply a single video URL"
        )
    return info


def source_info(source: str) -> SourceInfo:
    """Title/channel/duration/date/description for a YouTube or http(s) source via yt-dlp.

    ``upload_date`` is ISO ``YYYY-MM-DD`` when yt-dlp reports a valid date.
    Raises :class:`EvidenceError` when metadata cannot be obtained or has no title.
    """
    src = _classify(source)
    if src.kind == "local":
        raise EvidenceError(
            "Local files have no remote metadata; probe them with ffprobe"
        )
    info = _ytdlp_metadata(src.url)
    title = _text(info.get("title"))
    if title is None:
        raise EvidenceError("yt-dlp metadata has no title")
    duration = _seconds(info.get("duration"))
    raw_date = info.get("upload_date")
    upload_date: str | None = None
    if isinstance(raw_date, str) and re.fullmatch(r"\d{8}", raw_date):
        upload_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    raw_id = info.get("id")
    video_id = src.video_id or (raw_id if isinstance(raw_id, str) and raw_id else None)
    description = info.get("description")
    return {
        "title": title,
        "channel": _text(info.get("channel")) or _text(info.get("uploader")),
        "duration_seconds": duration,
        "upload_date": upload_date,
        "description": description if isinstance(description, str) else "",
        "video_id": video_id,
    }


# ---------------------------------------------------------------- cue normalization

_RawCue = tuple[object, object, object]


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    stripped = _TAG.sub("", value).replace("\u200b", "").replace("\ufeff", "")
    return _SPACE.sub(" ", stripped).strip()


def _word_overlap(previous: list[str], current: list[str]) -> int:
    """Longest k such that the last k words of ``previous`` equal the first k of ``current``."""
    for count in range(min(len(previous), len(current)), 0, -1):
        if previous[-count:] == current[:count]:
            return count
    return 0


def _drop_rolling_overlap(
    cues: list[tuple[float, float, str]], *, rolling_vtt: bool = False
) -> list[Segment]:
    """Remove text a rolling caption repeats from its predecessor.

    A cue is treated as rolling when it overlaps the previous cue in time
    and repeats its text. Word-timed autogenerated VTT also emits touching
    display-hold cues of about 10ms; merge those transitions, not ordinary
    adjacent repeated speech.
    """
    segments: list[Segment] = []
    previous_words: list[str] = []
    previous_end = -1.0
    previous_duration = math.inf
    for start, duration, text in cues:
        words = [word.casefold() for word in text.split(" ")]
        end = start + duration
        touching_hold = (
            rolling_vtt
            and start <= previous_end
            and (duration <= 0.02 or previous_duration <= 0.02)
        )
        previous_duration = duration
        if segments and (start < previous_end or touching_hold):
            overlap = _word_overlap(previous_words, words)
            if overlap == len(words) and (overlap >= 2 or previous_words == words):
                last = segments[-1]
                last["duration"] = max(last["duration"], end - last["start"])
                previous_end = max(previous_end, end)
                continue
            if overlap >= 2:
                text = " ".join(text.split(" ")[overlap:])
        segments.append({"start": start, "duration": duration, "text": text})
        previous_words = words
        previous_end = end
    return segments


def _normalize_cues(
    raw: Iterable[_RawCue], *, rolling_vtt: bool = False
) -> tuple[list[Segment], list[str]]:
    """Validate timing, strip markup, order by start and drop rolling-caption overlap."""
    gaps: list[str] = []
    malformed = 0
    cues: list[tuple[float, float, str]] = []
    for raw_start, raw_duration, raw_text in raw:
        text = _clean_text(raw_text)
        if not text:
            continue
        start = _seconds(raw_start)
        duration = _seconds(raw_duration)
        if start is None or duration is None:
            malformed += 1
            continue
        cues.append((start, duration, text))
    if malformed:
        gaps.append(f"Dropped {malformed} caption cue(s) with invalid timestamps")
    if any(later[0] < earlier[0] for earlier, later in pairwise(cues)):
        cues.sort(key=lambda cue: cue[0])
        gaps.append("Reordered out-of-sequence caption cues")
    return _drop_rolling_overlap(cues, rolling_vtt=rolling_vtt), gaps


def _millis(value: object) -> object:
    """Milliseconds to seconds; non-numbers are passed through to fail validation."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return value / 1000


def _json3_cues(payload: object) -> list[_RawCue]:
    data = _as_object(payload)
    events = data.get("events") if data is not None else None
    if not isinstance(events, list):
        raise EvidenceError("JSON3 captions have no events list")
    cues: list[_RawCue] = []
    for event in events:
        fields = _as_object(event)
        segs = fields.get("segs") if fields is not None else None
        if fields is None or not isinstance(segs, list):
            continue
        parts: list[str] = []
        for seg in segs:
            seg_fields = _as_object(seg)
            utf8 = seg_fields.get("utf8") if seg_fields is not None else None
            if isinstance(utf8, str):
                parts.append(utf8)
        cues.append(
            (
                _millis(fields.get("tStartMs")),
                _millis(fields.get("dDurationMs", 0)),
                "".join(parts),
            )
        )
    return cues


def _vtt_seconds(hours: str | None, minutes: str, seconds: str, millis: str) -> float:
    return (
        int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000
    )


def _vtt_cues(text: str) -> list[_RawCue]:
    cues: list[_RawCue] = []
    normalized = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n{2,}", normalized):
        lines = [line.rstrip() for line in block.strip().splitlines()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        body = " ".join(lines[timing_index + 1 :])
        match = _VTT_TIMING.match(lines[timing_index])
        if match is None:
            cues.append((None, None, body))
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = match.groups()
        start = _vtt_seconds(h1, m1, s1, ms1)
        cues.append((start, _vtt_seconds(h2, m2, s2, ms2) - start, body))
    return cues


# ---------------------------------------------------------------- transcripts


def _empty(
    status: Literal["unavailable", "failed"], source: str, message: str
) -> Transcript:
    transcript = empty_transcript(status, message)
    transcript["source"] = source
    return transcript


def _wanted(language: str) -> tuple[str, str]:
    wanted = language.casefold()
    return wanted, wanted.split("-")[0]


class _CaptionTrack(Protocol):
    @property
    def language_code(self) -> str: ...

    @property
    def is_generated(self) -> bool: ...


def _pick_api_track[T: _CaptionTrack](tracks: Sequence[T], language: str) -> T | None:
    """Requested language (manual first), then same base language, then any track (manual first)."""
    wanted, base = _wanted(language)
    tiers: tuple[Callable[[str], bool], ...] = (
        lambda code: code == wanted,
        lambda code: code.split("-")[0] == base,
        lambda code: True,
    )
    for matches in tiers:
        for generated in (False, True):
            for track in tracks:
                if track.is_generated == generated and matches(
                    track.language_code.casefold()
                ):
                    return track
    return None


def _bounded_session() -> requests.Session:
    """A requests session whose calls always have a timeout (the library sets none)."""
    import requests

    class _Bounded(requests.Session):
        def request(
            self, method: str | bytes, url: str | bytes, *args: Any, **kwargs: Any
        ) -> requests.Response:
            kwargs.setdefault("timeout", _HTTP_TIMEOUT)
            return super().request(method, url, *args, **kwargs)

    return _Bounded()


def _finish(
    raw: Iterable[_RawCue],
    *,
    language: str,
    requested: str,
    source: str,
    kind: str,
    label: str,
    rolling_vtt: bool = False,
) -> Transcript:
    segments, gaps = _normalize_cues(raw, rolling_vtt=rolling_vtt)
    if not segments:
        return _empty(
            "failed",
            source,
            f"{label} contained no usable caption text"
            + (f" ({'; '.join(gaps)})" if gaps else ""),
        )
    if language.casefold() != requested.casefold():
        gaps.insert(
            0,
            f"Requested caption language '{requested}' unavailable; used '{language}'",
        )
    if kind == "translation":
        gaps.append("Captions are a machine translation of another language's captions")
    elif kind == "unknown":
        gaps.append("Could not determine whether captions are manual or auto-generated")
    return {
        "status": "available",
        "segments": segments,
        "language": language,
        "source": source,
        "kind": kind,
        "gaps": gaps,
    }


def _api_captions(video_id: str, language: str) -> Transcript:
    try:
        from youtube_transcript_api import (
            TranscriptsDisabled,
            YouTubeTranscriptApi,
            YouTubeTranscriptApiException,
        )

        session = _bounded_session()
    except ImportError as exc:
        return _empty(
            "failed",
            _API_SOURCE,
            f"youtube-transcript-api or its requests dependency is not installed ({_describe(exc)}); "
            "run with `uv run --with youtube-transcript-api ...`",
        )
    try:
        tracks = list(YouTubeTranscriptApi(http_client=session).list(video_id))
    except TranscriptsDisabled:
        return _empty(
            "unavailable", _API_SOURCE, "Captions are disabled for this video"
        )
    except (YouTubeTranscriptApiException, OSError, ValueError) as exc:
        return _empty(
            "failed", _API_SOURCE, f"Listing caption tracks failed: {_describe(exc)}"
        )
    track = _pick_api_track(tracks, language)
    if track is None:
        return _empty("unavailable", _API_SOURCE, "The video has no caption tracks")
    try:
        fetched = track.fetch()
        raw: list[_RawCue] = [(s.start, s.duration, s.text) for s in fetched.snippets]
    except (YouTubeTranscriptApiException, OSError, ValueError) as exc:
        return _empty(
            "failed",
            _API_SOURCE,
            f"Fetching '{track.language_code}' captions failed: {_describe(exc)}",
        )
    return _finish(
        raw,
        language=track.language_code,
        requested=language,
        source=_API_SOURCE,
        kind="auto-generated" if track.is_generated else "manual",
        label=f"The '{track.language_code}' caption track",
    )


@dataclass(frozen=True)
class _YtdlpTrack:
    language: str
    kind: Literal["manual", "auto-generated", "translation", "unknown"]
    ext: Literal["json3", "vtt"]


def _ytdlp_tracks(info: dict[str, object]) -> list[_YtdlpTrack]:
    tracks: list[_YtdlpTrack] = []
    for field, manual in (("subtitles", True), ("automatic_captions", False)):
        table = _as_object(info.get(field))
        for language, formats in (table or {}).items():
            if not _LANGUAGE.fullmatch(language) or not isinstance(formats, list):
                continue
            offered: dict[str, str | None] = {}
            for fmt in formats:
                fields = _as_object(fmt)
                ext = fields.get("ext") if fields is not None else None
                url = fields.get("url") if fields is not None else None
                if isinstance(ext, str):
                    offered.setdefault(ext, url if isinstance(url, str) else None)
            selected: Literal["json3", "vtt"] | None = (
                "json3" if "json3" in offered else "vtt" if "vtt" in offered else None
            )
            if selected is None:
                continue
            url = offered[selected]
            kind: Literal["manual", "auto-generated", "translation", "unknown"]
            if manual:
                kind = "manual"
            elif url is None:
                kind = "unknown"
            elif "tlang" in parse_qs(urlparse(url).query):
                kind = "translation"
            else:
                kind = "auto-generated"
            tracks.append(_YtdlpTrack(language, kind, selected))
    return tracks


def _select_ytdlp_track(info: dict[str, object], language: str) -> _YtdlpTrack | None:
    """One track: requested language, same base language, the video's declared language, any manual,
    and only then a machine translation of the requested language."""
    tracks = _ytdlp_tracks(info)
    wanted, base = _wanted(language)
    declared = _text(info.get("language"))
    declared_code = declared.casefold() if declared else None
    original_kinds = ("manual", "auto-generated", "unknown")
    matchers: list[Callable[[str], bool]] = [
        lambda code: code == wanted,
        lambda code: code.split("-")[0] == base,
    ]
    if declared_code is not None:
        matchers.append(lambda code: code == declared_code)
    for matches in matchers:
        for kind in original_kinds:
            for track in tracks:
                if track.kind == kind and matches(track.language.casefold()):
                    return track
    for track in tracks:
        if track.kind == "manual":
            return track
    for track in tracks:
        if track.kind == "translation" and track.language.casefold() == wanted:
            return track
    return None


def _read_caption_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(
            f"yt-dlp did not write the expected caption file {path.name}"
        )
    if path.stat().st_size > _MAX_CAPTION_BYTES:
        raise EvidenceError(f"Caption file exceeds {_MAX_CAPTION_BYTES} bytes")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceError(f"Cannot read caption file: {_describe(exc)}") from exc


def _ytdlp_captions(url: str, work_dir: Path, language: str) -> Transcript:
    try:
        info = _ytdlp_metadata(url)
    except EvidenceError as exc:
        return _empty("failed", _YTDLP_SOURCE, f"Reading metadata failed: {exc}")
    track = _select_ytdlp_track(info, language)
    if track is None:
        return _empty(
            "unavailable",
            _YTDLP_SOURCE,
            "yt-dlp lists no usable caption track for this video",
        )
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix="captions-", dir=work_dir)).resolve()
    except OSError as exc:
        return _empty(
            "failed",
            _YTDLP_SOURCE,
            f"Cannot create caption scratch directory: {_describe(exc)}",
        )
    label = f"The yt-dlp '{track.language}' {track.kind} caption track"
    try:
        _ytdlp(
            [
                "--skip-download",
                "--write-subs" if track.kind == "manual" else "--write-auto-subs",
                "--sub-langs",
                re.escape(track.language),
                "--sub-format",
                track.ext,
                "-P",
                f"subtitle:{scratch}",
                "-o",
                "subtitle:captions.%(ext)s",
                "--",
                url,
            ],
            timeout=_CAPTION_TIMEOUT,
        )
        body = _read_caption_file(scratch / f"captions.{track.language}.{track.ext}")
        raw = _json3_cues(json.loads(body)) if track.ext == "json3" else _vtt_cues(body)
    except (EvidenceError, ValueError) as exc:
        return _empty("failed", _YTDLP_SOURCE, f"{label} could not be fetched: {exc}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return _finish(
        raw,
        language=track.language,
        requested=language,
        source=_YTDLP_SOURCE,
        kind=track.kind,
        label=label,
        rolling_vtt=(
            track.kind == "auto-generated"
            and track.ext == "vtt"
            and bool(_VTT_WORD_TIME.search(body))
        ),
    )


def get_captions(source: str, work_dir: Path, language: str = "en") -> Transcript:
    """Published captions for ``source`` with honest provenance; never runs speech recognition.

    Status is ``available`` (segments + ``language``/``kind``/``source``), ``unavailable``
    (conclusively no captions, or a local file the caller must handle), or ``failed``
    (inconclusive; ``gaps`` carry diagnostics).  Falling back to another language is
    recorded in ``gaps`` and ``language``.  ``work_dir`` is only touched by the yt-dlp path.
    """
    if not _LANGUAGE.fullmatch(language):
        return _empty(
            "failed",
            "none",
            f"Invalid caption language code '{diagnostic(language, 40)}'",
        )
    try:
        src = _classify(source)
    except EvidenceError as exc:
        return _empty("failed", "none", str(exc))
    if src.kind == "local":
        return _empty("unavailable", "none", "Local files carry no platform captions")
    if src.kind == "http" or src.video_id is None:
        return _ytdlp_captions(src.url, work_dir, language)
    api = _api_captions(src.video_id, language)
    if api["status"] != "failed":
        return api
    fallback = _ytdlp_captions(src.url, work_dir, language)
    gaps = [*api["gaps"], *fallback["gaps"]]
    available = fallback["status"] == "available"
    return {
        "status": fallback["status"],
        "segments": fallback["segments"],
        "language": fallback["language"],
        "source": fallback["source"]
        if available
        else f"{_API_SOURCE}, {_YTDLP_SOURCE}",
        "kind": fallback["kind"],
        "gaps": [f"{_API_SOURCE} failed; used {_YTDLP_SOURCE}", *gaps]
        if available
        else gaps,
    }


# ---------------------------------------------------------------- media download


def _checked_media(printed: str, box: Path) -> Path:
    """The single completed media file yt-dlp reported, proven to be a real file directly inside ``box``."""
    lines = [line for line in printed.splitlines() if line.strip()]
    if not lines:
        raise EvidenceError(
            f"yt-dlp finished without a media file (no format at or below {_MAX_MEDIA_HEIGHT}p, "
            f"or it exceeds {_MAX_MEDIA_BYTES // (1024 * 1024)} MiB)"
        )
    if len(lines) != 1:
        raise EvidenceError(
            f"yt-dlp reported {len(lines)} output files; expected exactly one"
        )
    reported = Path(lines[0])
    if reported.is_symlink():
        raise EvidenceError("Downloaded media path is a symlink")
    try:
        resolved = reported.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError(
            f"Downloaded media does not exist: {_describe(exc)}"
        ) from exc
    if resolved.parent != box:
        raise EvidenceError("Downloaded media is outside the work directory")
    if not resolved.is_file():
        raise EvidenceError("Downloaded media is not a regular file")
    if resolved.stem != "media" or resolved.suffix.lower() in _NON_MEDIA_SUFFIXES:
        raise EvidenceError(f"Downloaded file {resolved.name} is not completed media")
    extras = sorted(
        entry.name for entry in box.iterdir() if entry.name != resolved.name
    )
    if extras:
        raise EvidenceError(
            f"yt-dlp left unexpected output files: {', '.join(extras[:5])}"
        )
    size = resolved.stat().st_size
    if size == 0:
        raise EvidenceError("Downloaded media is empty")
    if size > _MAX_MEDIA_BYTES:
        raise EvidenceError(
            f"Downloaded media exceeds {_MAX_MEDIA_BYTES // (1024 * 1024)} MiB"
        )
    return resolved


def download_media(source: str, work_dir: Path, *, audio_only: bool = False) -> Path:
    """Download one video (at most 720p) or audio-only stream into a fresh directory under ``work_dir``.

    Returns the path of the single completed media file.  Local files are never
    downloaded or copied; the caller reads them in place.
    """
    src = _classify(source)
    if src.kind == "local":
        raise EvidenceError("Local files are used in place and are never downloaded")
    _ytdlp_metadata(src.url)  # rejects playlists before anything is written
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        box = Path(tempfile.mkdtemp(prefix="download-", dir=work_dir)).resolve()
    except OSError as exc:
        raise EvidenceError(
            f"Cannot create download directory under {work_dir}: {_describe(exc)}"
        ) from exc
    selector = (
        "ba"
        if audio_only
        else f"bv*[height<=?{_MAX_MEDIA_HEIGHT}]+ba/b[height<=?{_MAX_MEDIA_HEIGHT}]"
    )
    try:
        # --max-downloads is deliberately absent: yt-dlp exits 101 *after a successful* download when it
        # is set.  Single-video metadata is validated above and --playlist-items 1 is passed regardless.
        result = _ytdlp(
            [
                "--playlist-items",
                "1",
                "--max-filesize",
                str(_MAX_MEDIA_BYTES),
                "-f",
                selector,
                *([] if audio_only else ["--merge-output-format", "mp4"]),
                "--no-mtime",
                "-P",
                str(box),
                "-o",
                "media.%(ext)s",
                "--no-simulate",
                "--print",
                "after_move:filepath",
                "--",
                src.url,
            ],
            timeout=_DOWNLOAD_TIMEOUT,
        )
        return _checked_media(result.stdout, box)
    except BaseException:
        shutil.rmtree(box, ignore_errors=True)
        raise
