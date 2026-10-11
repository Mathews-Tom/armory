"""Shared Markdown/prose region parser for the humanize scripts (stdlib only).

Offsets are Unicode code-point indexes into the text exactly as decoded from
UTF-8 (no newline translation, a leading BOM stays at offset 0). Lines and
columns are 1-based; columns count code points.

The parser is deliberately conservative: it marks text that a prose edit must
not touch (code, frontmatter, tables, block quotes, link targets, URLs, quoted
evidence). It is not a full CommonMark implementation, and it prefers
over-protecting ambiguous input to exposing code or data to a rewrite.
"""

from __future__ import annotations

import bisect
import json
import re
import sys
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Final

BLOCK_KINDS: Final[tuple[str, ...]] = (
    "frontmatter",
    "fenced_code",
    "indented_code",
    "html_code",
    "table",
    "quote",
)
INLINE_KINDS: Final[tuple[str, ...]] = (
    "inline_code",
    "link_target",
    "bare_url",
    "inline_quote",
)
ALL_KINDS: Final[tuple[str, ...]] = BLOCK_KINDS + INLINE_KINDS

_SENTINEL: Final = "\x01"
_EOL: Final = re.compile(r"\r\n|\n|\r")
_FENCE_OPEN: Final = re.compile(r"([ \t]*)(`{3,}|~{3,})(.*)$")
_TABLE_DELIM: Final = re.compile(
    r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$"
)
_QUOTE_LINE: Final = re.compile(r"^ {0,3}>")
_HTML_OPEN: Final = re.compile(r"^ {0,3}<(pre|script|style)\b", re.IGNORECASE)
_LIST_MARKER: Final = re.compile(r"^[ \t]*(?:[-+*]|\d{1,9}[.)])(?:[ \t]+|$)")
_HEADING: Final = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_HEADING_CLOSER: Final = re.compile(r"[ \t]+#+$")
_FRONTMATTER_KEY: Final = re.compile(r"^(?:[\w.\"'-]+[ \t]*[:=]|#|-[ \t])")
_REF_DEF: Final = re.compile(
    r"^ {0,3}\[[^\]\n]+\]:[ \t]*(<[^>\n]*>|[^\s\x01]+)", re.MULTILINE
)
_AUTOLINK: Final = re.compile(r"<((?:https?|ftp|mailto):[^\s<>\x01]+)>")
_BARE_URL: Final = re.compile(r"(?<![\w@])(?:(?:https?|ftp)://|www\.)[^\s<>\[\]\x01]+")
_CURLY_QUOTE: Final = re.compile(r"\u201c([^\u201c\u201d]*)\u201d")
_QUOTE_OPENER_PREV: Final = " \t\r\n([{\u2014\u2013-:;,"

CHAT_CITATION: Final = re.compile(
    r":?contentReference\[oaicite:\d+\]\{index=\d+\}"
    r"|\[(?:cite_start|cite_end)\]"
    r"|\[cite:\s*\d+(?:\s*,\s*\d+)*\]"
    r"|\[span_\d+\]\((?:start|end)_span\)"
    r"|\ue200[^\ue201\n]{0,200}\ue201"
    r"|(?<![\w])(?:cite)?(?:turn\d+(?:search|view|news|image|file|forecast|finance|product|calc)\d+)+(?![\w])"
)


class InputError(Exception):
    """Raised for unreadable or invalid input; the CLIs report it and exit 2."""


@dataclass(frozen=True, slots=True)
class Region:
    """A protected span, ``[start, end)`` in code points."""

    kind: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Line:
    number: int
    start: int
    end: int  # exclusive; excludes the line terminator
    next: int  # start of the following line (== end when there is no terminator)


@dataclass(frozen=True, slots=True)
class Paragraph:
    """A run of prose lines between blank lines or protected blocks.

    ATX headings are always single-line paragraphs with ``heading_level`` > 0.
    """

    start: int
    end: int
    first_line: int
    last_line: int
    heading_level: int
    heading_text: str


def read_source(source: str) -> str:
    """Read UTF-8 text from a path or ``-`` (stdin) without newline translation."""
    if source == "-":
        label = "<stdin>"
        data = sys.stdin.buffer.read()
    else:
        label = source
        try:
            data = Path(source).read_bytes()
        except OSError as exc:
            reason = exc.strerror or type(exc).__name__
            raise InputError(f"cannot read {source}: {reason}") from exc
    if b"\x00" in data:
        raise InputError(f"{label}: contains NUL bytes; expected UTF-8 text")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(
            f"{label}: not valid UTF-8 (byte {exc.start}: {exc.reason})"
        ) from exc


def detect_line_endings(text: str) -> str:
    """Return ``none``, ``lf``, ``crlf``, ``cr`` or ``mixed``."""
    kinds = {m.group() for m in _EOL.finditer(text)}
    if not kinds:
        return "none"
    if len(kinds) > 1:
        return "mixed"
    return {"\n": "lf", "\r\n": "crlf", "\r": "cr"}[next(iter(kinds))]


def dump_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def split_lines(text: str) -> tuple[Line, ...]:
    lines: list[Line] = []
    pos = 0
    for match in _EOL.finditer(text):
        lines.append(Line(len(lines) + 1, pos, match.start(), match.end()))
        pos = match.end()
    if pos < len(text):
        lines.append(Line(len(lines) + 1, pos, len(text), len(text)))
    return tuple(lines)


def _is_blank(content: str) -> bool:
    return content.strip(" \t") == ""


def _indent_width(content: str) -> int:
    width = 0
    for char in content:
        if char == " ":
            width += 1
        elif char == "\t":
            width += 4 - width % 4
        else:
            break
    return width


def _blank(value: str, start: int, end: int) -> str:
    return value[:start] + _SENTINEL * (end - start) + value[end:]


def _frontmatter_end(text: str, lines: tuple[Line, ...]) -> int | None:
    """Index of the closing delimiter line when the document opens with frontmatter."""
    if not lines:
        return None
    first = text[lines[0].start : lines[0].end].lstrip("\ufeff").rstrip(" \t")
    if first not in ("---", "+++"):
        return None
    closers = ("---", "...") if first == "---" else ("+++",)
    for idx in range(1, len(lines)):
        content = text[lines[idx].start : lines[idx].end]
        if content.rstrip(" \t") in closers:
            inner = [
                text[lines[k].start : lines[k].end]
                for k in range(1, idx)
                if not _is_blank(text[lines[k].start : lines[k].end])
            ]
            if not inner or _FRONTMATTER_KEY.match(inner[0].lstrip(" \t")) is not None:
                return idx
            return None
    return None


def _find_blocks(text: str, lines: tuple[Line, ...]) -> tuple[list[Region], list[bool]]:
    count = len(lines)
    covered = [False] * count
    regions: list[Region] = []

    def content(index: int) -> str:
        line = lines[index]
        value = text[line.start : line.end]
        return value.lstrip("\ufeff") if index == 0 else value

    def take(kind: str, first: int, last: int) -> None:
        regions.append(Region(kind, lines[first].start, lines[last].end))
        for k in range(first, last + 1):
            covered[k] = True

    index = 0
    fm_end = _frontmatter_end(text, lines)
    if fm_end is not None:
        take("frontmatter", 0, fm_end)
        index = fm_end + 1

    prev_blank = True
    list_indent: int | None = None
    while index < count:
        line_text = content(index)
        if _is_blank(line_text):
            prev_blank = True
            index += 1
            continue
        indent = _indent_width(line_text)
        list_marker = _LIST_MARKER.match(line_text)
        if indent == 0 and list_marker is None:
            list_indent = None

        fence = _FENCE_OPEN.match(line_text)
        if fence is not None and (indent <= 3 or list_indent is not None):
            marker, info = fence.group(2), fence.group(3)
            if not (marker[0] == "`" and "`" in info):
                closer = re.compile(
                    rf"[ \t]*{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$"
                )
                end = index + 1
                while end < count and closer.match(content(end)) is None:
                    end += 1
                last = end if end < count else count - 1
                take("fenced_code", index, last)
                index = last + 1
                prev_blank = True
                continue

        html = _HTML_OPEN.match(line_text)
        if html is not None:
            close_tag = re.compile(rf"</{html.group(1)}\s*>", re.IGNORECASE)
            end = index
            while end < count and close_tag.search(content(end)) is None:
                end += 1
            last = end if end < count else count - 1
            take("html_code", index, last)
            index = last + 1
            prev_blank = True
            continue

        if (
            "|" in line_text
            and indent <= 3
            and index + 1 < count
            and "|" in content(index + 1)
            and _TABLE_DELIM.match(content(index + 1)) is not None
        ):
            end = index + 2
            while end < count and not _is_blank(content(end)) and "|" in content(end):
                end += 1
            take("table", index, end - 1)
            index = end
            prev_blank = True
            continue

        if _QUOTE_LINE.match(line_text) is not None:
            end = index + 1
            while end < count:
                candidate = content(end)
                if _QUOTE_LINE.match(candidate) is not None:
                    end += 1
                    continue
                if (
                    _is_blank(candidate)
                    or _FENCE_OPEN.match(candidate)
                    or _HEADING.match(candidate)
                    or _LIST_MARKER.match(candidate)
                    or _HTML_OPEN.match(candidate)
                ):
                    break
                end += 1
            take("quote", index, end - 1)
            index = end
            prev_blank = True
            continue

        code_indent = 4 + (list_indent or 0)
        if indent >= code_indent and prev_blank:
            last = index
            end = index
            while end < count:
                candidate = content(end)
                if _is_blank(candidate):
                    end += 1
                    continue
                if _indent_width(candidate) < code_indent:
                    break
                last = end
                end += 1
            take("indented_code", index, last)
            index = last + 1
            prev_blank = True
            continue

        if list_marker is not None:
            list_indent = len(list_marker.group().expandtabs(4))
        prev_blank = False
        index += 1
    return regions, covered


def _build_paragraphs(
    text: str, lines: tuple[Line, ...], covered: list[bool]
) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    run: list[int] = []

    def flush() -> None:
        if run:
            first, last = run[0], run[-1]
            paragraphs.append(
                Paragraph(
                    lines[first].start, lines[last].end, first + 1, last + 1, 0, ""
                )
            )
            run.clear()

    for index, line in enumerate(lines):
        if covered[index]:
            flush()
            continue
        content = text[line.start : line.end]
        if index == 0:
            content = content.lstrip("\ufeff")
        if _is_blank(content):
            flush()
            continue
        heading = _HEADING.match(content)
        if heading is not None:
            flush()
            title = _HEADING_CLOSER.sub("", heading.group(2) or "").strip()
            paragraphs.append(
                Paragraph(
                    line.start,
                    line.end,
                    line.number,
                    line.number,
                    len(heading.group(1)),
                    title,
                )
            )
            continue
        run.append(index)
    flush()
    return paragraphs


def code_spans(par: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    length = len(par)
    i = 0
    while i < length:
        char = par[i]
        if char == "\\":
            i += 2
            continue
        if char != "`":
            i += 1
            continue
        j = i
        while j < length and par[j] == "`":
            j += 1
        width = j - i
        k = j
        found = -1
        while k < length:
            if par[k] == "`":
                m = k
                while m < length and par[m] == "`":
                    m += 1
                if m - k == width:
                    found = k
                    break
                k = m
            else:
                k += 1
        if found >= 0:
            spans.append((i, found + width))
            i = found + width
        else:
            i = j
    return spans


def _link_destinations(par: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    length = len(par)
    for match in re.finditer(r"\]\(", par):
        pos = match.end()
        while pos < length and par[pos] in " \t\r\n":
            pos += 1
        if pos >= length:
            continue
        if par[pos] == "<":
            close = par.find(">", pos)
            newline = par.find("\n", pos)
            if close == -1 or (newline != -1 and newline < close):
                continue
            spans.append((pos, close + 1))
            continue
        depth = 0
        k = pos
        while k < length:
            char = par[k]
            if char in " \t\r\n" or char == _SENTINEL:
                break
            if char == "\\":
                k += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            k += 1
        k = min(k, length)
        if k > pos:
            spans.append((pos, k))
    return spans


def _trim_url(url: str) -> str:
    while url:
        last = url[-1]
        if last in ".,;:!?'\"*_~":
            url = url[:-1]
        elif last == ")" and url.count(")") > url.count("("):
            url = url[:-1]
        elif last == "]" and url.count("]") > url.count("["):
            url = url[:-1]
        else:
            break
    return url


def _scan_inline(text: str, start: int, end: int) -> list[Region]:
    working = text[start:end]
    found: list[Region] = []

    def claim(kind: str, a: int, b: int) -> None:
        nonlocal working
        if kind == "inline_quote":
            found[:] = [
                region
                for region in found
                if not (start + a <= region.start and region.end <= start + b)
            ]
        found.append(Region(kind, start + a, start + b))
        working = _blank(working, a, b)

    for a, b in code_spans(working):
        claim("inline_code", a, b)
    for match in _CURLY_QUOTE.finditer(working):
        claim("inline_quote", match.start(), match.end())
    opener: int | None = None
    for match in re.finditer('"', working):
        position = match.start()
        if working[position] != '"':
            continue
        backslashes = 0
        cursor = position - 1
        while cursor >= 0 and working[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            continue
        if opener is None:
            if position == 0 or working[position - 1] in _QUOTE_OPENER_PREV:
                opener = position
        elif position + 1 == len(working) or not working[position + 1].isalnum():
            claim("inline_quote", opener, position + 1)
            opener = None
    if opener is not None:
        claim("inline_quote", opener, len(working))
    for a, b in _link_destinations(working):
        if _SENTINEL not in working[a:b]:
            claim("link_target", a, b)
    for match in _REF_DEF.finditer(working):
        a, b = match.span(1)
        if _SENTINEL not in working[a:b]:
            claim("link_target", a, b)
    for match in _AUTOLINK.finditer(working):
        a, b = match.span(1)
        claim("bare_url", a, b)
    for match in _BARE_URL.finditer(working):
        trimmed = _trim_url(match.group())
        body = trimmed.split("//", 1)[1] if "//" in trimmed else trimmed[4:]
        if not re.search(r"\w", body):
            continue
        claim("bare_url", match.start(), match.start() + len(trimmed))
    return found


class Document:
    """Parsed text with disjoint, offset-sorted protected regions."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = split_lines(text)
        self._line_starts = [line.start for line in self.lines]
        blocks, covered = _find_blocks(text, self.lines)
        self.paragraphs = tuple(_build_paragraphs(text, self.lines, covered))
        inline: list[Region] = []
        for paragraph in self.paragraphs:
            if paragraph.heading_level == 0 or paragraph.heading_text:
                inline.extend(_scan_inline(text, paragraph.start, paragraph.end))
        self.regions = tuple(sorted(blocks + inline, key=lambda region: region.start))
        self._region_starts = [region.start for region in self.regions]
        self._paragraph_starts = [paragraph.start for paragraph in self.paragraphs]

    def line_at(self, offset: int) -> Line:
        if not self.lines:
            return Line(1, 0, 0, 0)
        index = bisect.bisect_right(self._line_starts, offset) - 1
        return self.lines[max(index, 0)]

    def position(self, offset: int) -> tuple[int, int]:
        """1-based ``(line, column)`` of an offset."""
        line = self.line_at(offset)
        return line.number, offset - line.start + 1

    def paragraph_at(self, offset: int) -> Paragraph | None:
        index = bisect.bisect_right(self._paragraph_starts, offset) - 1
        if index < 0:
            return None
        paragraph = self.paragraphs[index]
        return paragraph if offset <= paragraph.end else None

    def overlapping(
        self, start: int, end: int, kinds: Collection[str] | None = None
    ) -> list[Region]:
        """Regions intersecting ``[start, end)`` (a point when ``end <= start``)."""
        stop = max(end, start + 1)
        index = max(bisect.bisect_right(self._region_starts, start) - 1, 0)
        hits: list[Region] = []
        while index < len(self.regions) and self.regions[index].start < stop:
            region = self.regions[index]
            if region.end > start and (kinds is None or region.kind in kinds):
                hits.append(region)
            index += 1
        return hits

    def masked(self, kinds: Collection[str] | None = None) -> str:
        """Text with protected regions replaced by spaces (line breaks and offsets kept)."""
        out: list[str] = []
        pos = 0
        for region in self.regions:
            if kinds is not None and region.kind not in kinds:
                continue
            out.append(self.text[pos : region.start])
            out.append(re.sub(r"[^\r\n]", " ", self.text[region.start : region.end]))
            pos = region.end
        out.append(self.text[pos:])
        return "".join(out)

    def regions_of(self, kinds: Collection[str]) -> list[Region]:
        return [region for region in self.regions if region.kind in kinds]


def parse(text: str) -> Document:
    return Document(text)


def chat_artifact_spans(doc: Document) -> list[tuple[int, int]]:
    """Recognize removable chat markers without interpreting real URL contents."""
    work = doc.masked(BLOCK_KINDS + ("inline_code", "inline_quote"))
    urls = doc.regions_of(("link_target", "bare_url"))
    spans: list[tuple[int, int]] = []
    for match in CHAT_CITATION.finditer(work):
        first, last = match.span()
        overlapping = [
            region for region in urls if first < region.end and last > region.start
        ]
        if all(
            region.kind == "link_target"
            and first <= region.start
            and region.end <= last
            and match.group().startswith("[span_")
            for region in overlapping
        ):
            spans.append((first, last))
    return spans
