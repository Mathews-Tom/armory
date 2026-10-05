"""Explicit Gemini cloud analysis through Google's native Interactions API.

Nothing here runs unless the caller passes ``allow_cloud=True``. The API key is
read only from the process environment, never logged, and is sent only to the
configured API origin. There is no local fallback and no provider switch: every
failure surfaces as an :class:`EvidenceError` whose message is safe to display.

API shape (https://ai.google.dev/gemini-api/docs/video-understanding):
``POST /v1beta/interactions`` with a ``video`` input carrying ``processing``
(``"agentic"`` or a ``static`` object with ``start_offset``/``end_offset``
strings such as ``"10.5s"``), answered by ``steps[type=model_output]``. Local
videos go through the resumable Files API and are deleted afterwards.
"""

from __future__ import annotations

import http.client
import json
import math
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import IO, BinaryIO, Final, Mapping
from urllib.parse import urlparse

from evidence import CloudAnswer, EvidenceError
from runtime import diagnostic
from utils import format_timestamp, parse_youtube_url

DEFAULT_MODEL: Final = "gemini-3.7-flash"
API_HOST: Final = "https://generativelanguage.googleapis.com"
API_BASE_ENV: Final = "WATCH_GEMINI_API_BASE"
API_KEY_ENV: Final = "GEMINI_API_KEY"

# Seconds between Files API state polls and the total time an upload may stay
# PROCESSING. Module attributes so offline tests can shrink them.
POLL_INTERVAL_SECONDS: float = 2.0
PROCESSING_DEADLINE_SECONDS: float = 900.0

_KEY_SHAPE: Final = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_FILE_NAME: Final = re.compile(r"files/[A-Za-z0-9_-]+")
_LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})
_MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024
_FALLBACK_NOTE: Final = "No local fallback or provider switch was attempted."

_HINTS: Final[Mapping[str, str]] = {
    "auth": "the API key was rejected; check GEMINI_API_KEY",
    "quota": "rate limit or quota exhausted; wait and retry, or check the plan",
    "service": "Google reported a server-side failure; retry later",
    "rejected": "Google rejected the request",
    "network": "could not reach Google",
    "response": "Google returned an unusable answer",
    "upload": "the video upload to the Files API failed",
}

DEFAULT_QUESTION: Final = (
    "Give a thorough summary of this video: what is shown, any on-screen text or code, "
    "and what is said, in chronological order."
)
_PROMPT_RULES: Final = (
    "\n\nRules for the answer:\n"
    "- Give an MM:SS (or H:MM:SS) timestamp for every claim about a specific moment.\n"
    "- Label each claim as SEEN (visible on screen), HEARD (spoken or audible), or "
    "INFERRED (your conclusion, not directly shown or said).\n"
    "- If the video does not show or say something needed to answer, say so plainly "
    "instead of guessing."
)


def build_prompt(question: str | None, start: float, end: float | None) -> str:
    prompt = (question or "").strip() or DEFAULT_QUESTION
    prompt += _PROMPT_RULES
    if start > 0 or end is not None:
        span = f"{format_timestamp(start)} to {format_timestamp(end) if end is not None else 'the end'}"
        prompt += (
            f"\n- Only the interval {span} of the original video is provided. "
            "Report timestamps on the original video's timeline, and say so if you cannot."
        )
    return prompt


def _api_base() -> str:
    """The origin that may receive the API key: Google, or loopback HTTP for offline smoke."""
    override = os.environ.get(API_BASE_ENV, "").strip()
    if not override:
        return API_HOST
    parsed = urlparse(override)
    try:
        port = parsed.port
    except ValueError:
        port = None
    loopback = (
        parsed.scheme == "http"
        and parsed.hostname in _LOOPBACK_HOSTS
        and port is not None
        and parsed.username is None
        and parsed.path in ("", "/")
        and not (parsed.params or parsed.query or parsed.fragment)
    )
    if not loopback:
        raise EvidenceError(
            f"{API_BASE_ENV} may only be an explicit-port http loopback address "
            "(for offline smoke tests); the API key is never sent to other hosts."
        )
    host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{host}:{port}"


def _read_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise EvidenceError(
            f"Gemini analysis needs {API_KEY_ENV} in the process environment."
        )
    if not key.isprintable() or any(ch.isspace() for ch in key):
        raise EvidenceError(f"{API_KEY_ENV} contains whitespace or control characters.")
    return key


class _CloudError(EvidenceError):
    """Display-safe Gemini failure that keeps its redacted detail for reuse."""

    def __init__(self, message: str, detail: str) -> None:
        super().__init__(message)
        self.detail = detail


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects would forward the API key header to another origin; refuse them."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> None:
        return None


@dataclass
class _Upload:
    """Remote file created for this run; ``name`` is set as soon as Google reports it."""

    name: str | None = None


class _Gateway:
    def __init__(self, base: str, key: str, timeout: float) -> None:
        self.base = base
        self._key = key
        self._timeout = timeout
        handlers: list[urllib.request.BaseHandler] = [_NoRedirect()]
        if base != API_HOST:
            handlers.append(urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)

    def redact(self, text: str, limit: int = 400) -> str:
        cleaned = diagnostic(text.replace(self._key, "[redacted]"), 20_000)
        return _KEY_SHAPE.sub("[redacted]", cleaned)[:limit]

    def fail(self, category: str, detail: str) -> _CloudError:
        shown = self.redact(detail) or "none"
        return _CloudError(
            f"Gemini {category}: {_HINTS[category]}. Detail: {shown}. {_FALLBACK_NOTE}",
            shown,
        )

    def same_origin(self, url: str) -> bool:
        parsed, base = urlparse(url), urlparse(self.base)
        return (parsed.scheme, parsed.netloc) == (base.scheme, base.netloc)

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | BinaryIO | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[http.client.HTTPMessage, bytes]:
        if not self.same_origin(url):
            raise self.fail(
                "response",
                "Google returned a URL outside the API origin; refusing to send the key",
            )
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={"x-goog-api-key": self._key, **(headers or {})},
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                payload: bytes = response.read(_MAX_RESPONSE_BYTES + 1)
                reply_headers: http.client.HTTPMessage = response.headers
        except urllib.error.HTTPError as exc:
            message = _provider_message(exc.read(_MAX_RESPONSE_BYTES))
            category = (
                "auth"
                if exc.code in (401, 403) or "api key" in message.lower()
                else "quota"
                if exc.code == 429
                else "service"
                if exc.code >= 500
                else "rejected"
            )
            raise self.fail(category, f"HTTP {exc.code}: {message}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            # TimeoutError is an OSError. URLError.reason carries the useful part.
            reason = getattr(exc, "reason", exc)
            raise self.fail("network", f"{type(exc).__name__}: {reason}") from None
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise self.fail("response", "answer exceeded the size limit")
        return reply_headers, payload

    def json_request(
        self, method: str, url: str, what: str, *, payload: object | None = None
    ) -> dict[str, object]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else None
        _, raw = self.request(method, url, body=body, headers=headers)
        return self.parse_object(raw, what)

    def parse_object(self, raw: bytes, what: str) -> dict[str, object]:
        try:
            data = json.loads(raw)
        except ValueError:
            raise self.fail("response", f"{what} was not valid JSON") from None
        if not isinstance(data, dict):
            raise self.fail("response", f"{what} was not a JSON object")
        return data


def _provider_message(body: bytes) -> str:
    """Only Google's own error message is surfaced; other body content never is."""
    try:
        data = json.loads(body)
    except ValueError:
        return "unreadable provider error body"
    if (
        isinstance(data, list) and data
    ):  # Auth failures can arrive as a one-element array.
        data = data[0]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message: object = error.get("message")
            if isinstance(message, str):
                return message
    return "no provider error message"


def _seconds(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") + "s"


def _video_input(
    uri: str, mime_type: str | None, start: float, end: float | None
) -> tuple[dict[str, object], str]:
    """The ``video`` input and an honest description of how Google will process it."""
    video: dict[str, object] = {"type": "video", "uri": uri}
    if mime_type:
        video["mime_type"] = mime_type
    if start <= 0 and end is None:
        video["processing"] = "agentic"
        return video, "agentic (requested)"
    processing: dict[str, object] = {"type": "static", "start_offset": _seconds(start)}
    if end is not None:
        processing["end_offset"] = _seconds(end)
    video["processing"] = processing
    span = f"{format_timestamp(start)}-{format_timestamp(end) if end is not None else 'end'}"
    return (
        video,
        f"static clip {span} (fixed-rate sampling of the interval; not agentic)",
    )


def _answer_text(steps: object) -> tuple[str, int]:
    """Concatenated model_output text, and the number of agentic navigation calls seen."""
    if not isinstance(steps, list):
        return "", 0
    parts: list[str] = []
    calls = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "processing_call":
            calls += 1
        elif step.get("type") == "model_output":
            content = step.get("content")
            for part in content if isinstance(content, list) else []:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
    return "\n".join(parts), calls


def _interact(
    gateway: _Gateway,
    model: str,
    video: dict[str, object],
    prompt: str,
    processing: str,
) -> CloudAnswer:
    data = gateway.json_request(
        "POST",
        f"{gateway.base}/v1beta/interactions",
        "the interaction response",
        payload={
            "model": model,
            "store": False,
            "input": [video, {"type": "text", "text": prompt}],
        },
    )
    status = data.get("status")
    if status not in (None, "completed"):
        raise gateway.fail("response", f"interaction ended with status {status!r}")
    text, calls = _answer_text(data.get("steps"))
    if not text:
        raise gateway.fail("response", "the interaction contained no answer text")
    if processing.startswith("agentic"):
        processing = (
            f"agentic (requested; {calls} navigation call{'s' if calls != 1 else ''} observed)"
            if calls
            else "agentic (requested; the response showed no navigation steps)"
        )
    usage = data.get("usage")
    tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    return {
        "text": text,
        "model": model,
        "processing": processing,
        "total_tokens": tokens
        if isinstance(tokens, int) and not isinstance(tokens, bool)
        else None,
        "cleanup_warning": None,
    }


def _upload(gateway: _Gateway, path: Path, upload: _Upload) -> tuple[str, str]:
    """Stream ``path`` to the Files API; returns (file uri, mime type) once ACTIVE."""
    size = path.stat().st_size
    if size == 0:
        raise gateway.fail("upload", f"{path.name} is empty")
    guessed = mimetypes.guess_type(path.name)[0] or ""
    mime = guessed if guessed.startswith("video/") else "video/mp4"
    headers, _ = gateway.request(
        "POST",
        f"{gateway.base}/upload/v1beta/files",
        body=json.dumps({"file": {"display_name": "watch-upload"}}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime,
        },
    )
    session = headers.get("x-goog-upload-url")
    if not session:
        raise gateway.fail(
            "upload", "the Files API did not return an upload session URL"
        )
    with path.open("rb") as stream:  # Streamed in blocks; never held in memory.
        _, reply = gateway.request(
            "POST",
            session,
            body=stream,
            headers={
                "Content-Length": str(size),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
        )
    info = _file_info(gateway, gateway.parse_object(reply, "the upload reply"))
    upload.name = _file_name(gateway, info)
    deadline = time.monotonic() + PROCESSING_DEADLINE_SECONDS
    while info.get("state") == "PROCESSING":
        if time.monotonic() >= deadline:
            raise gateway.fail(
                "upload",
                f"file still processing after {PROCESSING_DEADLINE_SECONDS:g}s",
            )
        time.sleep(POLL_INTERVAL_SECONDS)
        info = gateway.json_request(
            "GET", f"{gateway.base}/v1beta/{upload.name}", "the file status"
        )
    if info.get("state") != "ACTIVE":
        raise gateway.fail("upload", f"file ended in state {info.get('state')!r}")
    uri = info.get("uri")
    if not isinstance(uri, str) or not uri:
        raise gateway.fail("upload", "the active file has no uri")
    reported = info.get("mimeType")
    return uri, reported if isinstance(reported, str) and reported else mime


def _file_info(gateway: _Gateway, reply: dict[str, object]) -> dict[str, object]:
    info = reply.get("file")
    if not isinstance(info, dict):
        raise gateway.fail("upload", "the upload reply carried no file record")
    return info


def _file_name(gateway: _Gateway, info: dict[str, object]) -> str:
    name = info.get("name")
    if not isinstance(name, str) or not _FILE_NAME.fullmatch(name):
        raise gateway.fail("upload", "the file record had an unexpected name")
    return name


def _discard(gateway: _Gateway, upload: _Upload) -> str | None:
    """Delete the remote file. Returns a warning when it could not be removed."""
    if upload.name is None:
        return None
    try:
        gateway.request("DELETE", f"{gateway.base}/v1beta/{upload.name}")
    except _CloudError as exc:
        return (
            f"Could not delete uploaded {upload.name} from Google ({exc.detail}); "
            "it expires on its own within 48 hours."
        )
    return None


def _resolve_source(source: str) -> str | Path:
    """A normalized public YouTube URI (str) or an existing local video file (Path)."""
    if source.lower().startswith(("http://", "https://")):
        video_id = parse_youtube_url(source)
        if video_id is None:
            raise EvidenceError(
                "Gemini analysis takes a public YouTube URL or a local video file; "
                "download other URLs first."
            )
        return f"https://www.youtube.com/watch?v={video_id}"
    path = Path(source).expanduser()
    if not path.is_file():
        raise EvidenceError(
            f"Video file not found for Gemini upload: {path.name or source}"
        )
    return path


def analyze_video(
    source: str,
    question: str | None,
    *,
    allow_cloud: bool = False,
    model: str = DEFAULT_MODEL,
    start: float = 0.0,
    end: float | None = None,
    timeout: float = 600.0,
) -> CloudAnswer:
    """Ask Gemini about ``source`` (public YouTube URL or local video path).

    Raises :class:`EvidenceError` before any credential read, file read, or
    network access unless ``allow_cloud`` is true.
    """
    if not allow_cloud:
        raise EvidenceError(
            "Gemini analysis uploads or references the video in Google's cloud; "
            "it runs only when the cloud option is explicitly allowed."
        )
    if not model or not all(ch.isalnum() or ch in "-._" for ch in model):
        raise EvidenceError(f"Invalid Gemini model name: {diagnostic(model, 60)!r}")
    if not math.isfinite(start) or start < 0:
        raise EvidenceError(
            "Gemini start offset must be a finite number of seconds >= 0."
        )
    if end is not None and (not math.isfinite(end) or end <= start):
        raise EvidenceError(
            "Gemini end offset must be finite and greater than the start offset."
        )
    if not math.isfinite(timeout) or timeout <= 0:
        raise EvidenceError("Gemini timeout must be a positive number of seconds.")
    base = _api_base()
    key = _read_key()
    resolved = _resolve_source(source)

    gateway = _Gateway(base, key, timeout)
    prompt = build_prompt(question, start, end)
    upload = _Upload()
    try:
        if isinstance(resolved, Path):
            uri, mime = _upload(gateway, resolved, upload)
        else:
            uri, mime = resolved, None
        video, processing = _video_input(uri, mime, start, end)
        answer = _interact(gateway, model, video, prompt, processing)
    except EvidenceError as exc:
        warning = _discard(gateway, upload)
        if warning:
            raise EvidenceError(f"{exc} {warning}") from exc
        raise
    except BaseException:
        _discard(gateway, upload)
        raise
    answer["cleanup_warning"] = _discard(gateway, upload)
    return answer
