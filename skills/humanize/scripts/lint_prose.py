#!/usr/bin/env python3
"""Deterministic prose scanner and explicit mechanical cleanup for humanize.

Subcommands:
  scan      report findings as JSON (stable rule IDs, exact offsets, evidence)
  fix       delete explicitly selected, well-defined chat artifacts into a new file
  rules     list rule IDs, confidence and whether a mechanical fix exists
  patterns  print selected sections of references/detection-patterns.md

Findings are review candidates, never evidence of AI authorship, and a scan
with zero findings does not show that a text is semantically or stylistically
clean. Protected regions (code, frontmatter, tables, block quotes, link targets,
URLs, quoted evidence) are never scanned and never edited, except that
HUM002 reads URLs and, only with --strip-tracking, removes one tracking
parameter from an unsigned URL.

Exit codes: 0 ok, 1 findings present with --fail-on-findings, 2 invalid input
or unsupported request, 3 internal safety check refused to write.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from prose_markup import (
    ALL_KINDS,
    BLOCK_KINDS,
    chat_artifact_spans,
    Document,
    InputError,
    detect_line_endings,
    dump_json,
    parse,
    read_source,
)

NOTICE: Final = (
    "Findings are review candidates, not evidence of AI authorship. A scan with "
    "zero findings does not show that the text is semantically or stylistically clean."
)
REFERENCE_PATH: Final = (
    Path(__file__).resolve().parent.parent / "references" / "detection-patterns.md"
)


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    name: str
    confidence: (
        str  # "mechanical" (artifact residue) or "candidate" (lexical/structural cue)
    )
    fixable: bool
    pattern: str  # name of the guidance section in references/detection-patterns.md
    message: str


RULES: Final[dict[str, Rule]] = {
    rule.id: rule
    for rule in (
        Rule(
            "HUM001",
            "citation-artifact",
            "mechanical",
            True,
            "Mechanical Chat Residue",
            "Citation or tool marker leaked from a chat interface.",
        ),
        Rule(
            "HUM002",
            "ai-tracking-parameter",
            "mechanical",
            True,
            "Mechanical Chat Residue",
            "URL carries a utm_source added by an AI chat tool. Reported only; removal needs --strip-tracking.",
        ),
        Rule(
            "HUM003",
            "placeholder-text",
            "mechanical",
            False,
            "Mechanical Chat Residue",
            "Placeholder or draft marker in prose. Fill it from real information or flag it; never invent.",
        ),
        Rule(
            "HUM004",
            "skipped-heading-level",
            "mechanical",
            False,
            "Mechanical Chat Residue",
            "Heading level jumps by more than one.",
        ),
        Rule(
            "HUM005",
            "chat-wrapper",
            "mechanical",
            True,
            "Chatbot Wrappers and Sycophancy",
            "Closed-list chat opener or closer at a paragraph edge.",
        ),
        Rule(
            "HUM006",
            "chat-lead-in",
            "candidate",
            False,
            "Staged Run-Up",
            "Announces or stages the point instead of making it.",
        ),
        Rule(
            "HUM007",
            "negative-parallelism",
            "candidate",
            False,
            "Negative Parallelism",
            "Contrast built from a denial nobody made.",
        ),
        Rule(
            "HUM008",
            "dramatic-closer",
            "candidate",
            False,
            "One-Line Closers and Dramatic Fragments",
            "One-line paragraph that asks the reader to pause instead of adding a fact.",
        ),
        Rule(
            "HUM009",
            "heading-echo",
            "candidate",
            False,
            "Heading Echoed in the First Sentence",
            "First sentence restates the heading above it.",
        ),
        Rule(
            "HUM010",
            "heading-decoration",
            "candidate",
            False,
            "Decorative Headings",
            "Heading begins with an emoji or arrow.",
        ),
        Rule(
            "HUM011",
            "model-disclaimer",
            "candidate",
            False,
            "Knowledge-Cutoff Disclaimers and Unsupported Guesses",
            "Model self-reference or knowledge-limit disclaimer.",
        ),
    )
}

_APOS: Final = "['\u2019]"


def _apos(pattern: str) -> str:
    return pattern.replace("'", _APOS)


@dataclass(slots=True)
class Finding:
    rule: Rule
    start: int
    end: int
    evidence: str
    fix_range: tuple[int, int] | None = None
    unfixable_reason: str | None = None
    requires: tuple[str, ...] = ()
    details: dict[str, object] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.rule.id}:{self.start}"

    @property
    def fixable(self) -> bool:
        return (
            self.rule.fixable
            and self.fix_range is not None
            and self.unfixable_reason is None
        )


# --------------------------------------------------------------------------- rules

_TRACKING: Final = re.compile(
    r"(?<=[?&])utm_source=(?:chatgpt\.com|chatgpt|openai(?:\.com)?|claude(?:\.ai)?|"
    r"perplexity(?:\.ai)?|copilot(?:\.microsoft\.com|\.com)?|gemini|bard)(?=[&#>]|$)",
    re.IGNORECASE,
)
_SIGNED: Final = re.compile(
    r"[?&;](?:x-amz-signature|x-amz-credential|x-goog-signature|x-goog-credential|signature|sig|sv|se|sp|sr|st|"
    r"token|access_token|expires|policy|key-pair-id|hmac|hash|auth)=",
    re.IGNORECASE,
)
_PLACEHOLDER: Final = re.compile(
    r"(?i:\[(?:insert|add|enter|describe|your|company|client|recipient|name|date|link|url|todo|tbd|placeholder)\b"
    r"[^\]\n]{0,60}\](?!\(|:|\[))|\b(?:TODO|FIXME|TBD)\b:?|(?i:\blorem ipsum\b)",
)
_WRAPPER_PATTERNS: Final = (
    r"(?:great|good|excellent|fantastic|wonderful|interesting|fair|sharp) (?:question|point)[!.]",
    r"(?:certainly|absolutely|of course|sure)!",
    r"i'd be (?:happy|glad|delighted) to (?:help|assist)[^.!?\r\n]{0,80}[.!]",
    r"i (?:would|will) be (?:happy|glad|delighted) to (?:help|assist)[^.!?\r\n]{0,80}[.!]",
    r"i hope (?:this|that) helps[^.!?\r\n]{0,40}[.!]",
    r"i hope this (?:email|message|note) finds you well[.!]",
    r"(?:please )?(?:feel free to|don't hesitate to|do not hesitate to) (?:reach out|ask|contact me|let me know)[^.!?\r\n]{0,80}[.!]",
    r"let me know if (?:you|there)[^.!?\r\n]{0,100}[.!?]",
    r"thank(?:s| you) for (?:asking|your question|reaching out)[^.!?\r\n]{0,60}[.!]",
    r"happy (?:writing|coding|reading)[!.]",
)
_WRAPPER: Final = re.compile(
    "(?:" + "|".join(_apos(p) for p in _WRAPPER_PATTERNS) + r")(?=\s|$)", re.IGNORECASE
)
_CANDIDATES: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    "HUM006": tuple(
        re.compile(_apos(p), re.IGNORECASE)
        for p in (
            r"\bwelcome to (?:this|our|the|my) (?:comprehensive |complete |ultimate |quick )?"
            r"(?:guide|article|post|tutorial|blog|newsletter|overview)\b",
            r"\bin this (?:article|guide|post|tutorial|section),? (?:we'll|we will|i'll|i will|you'll|you will) "
            r"(?:explore|dive|look|cover|walk|learn|discover|delve)\b",
            r"\blet(?:'s| us) (?:dive in|dive into|dig in|explore|break (?:this|it|that) down|get started)\b",
            r"\bwithout further ado\b",
            r"\bhere(?:'s| is) (?:a|an) (?:quick |brief |comprehensive |detailed |complete )?"
            r"(?:overview|breakdown|summary|rundown)\b",
            r"\bhere(?:'s| is) the (?:thing|kicker|catch|truth)\s*[:.]",
        )
    ),
    "HUM007": tuple(
        re.compile(_apos(p), re.IGNORECASE)
        for p in (
            r"\b(?:isn't|aren't|wasn't|weren't|is not|are not|was not|were not|not)\s+(?:just|only|merely|simply)\b"
            r"[^.!?\n]{0,140}?(?:[,;:\u2014\u2013]|\s-{1,2}\s)\s*(?:but|it's|it is|they're|they are|that's|rather|also)\b",
            r"\bnot (?:just|merely|simply)\b[^.!?\n]{0,120}?\bbut\b",
            r"\bnot only\b[^.!?\n]{0,160}?\bbut (?:also )?",
            r"\b(?:doesn't|does not|isn't|is not) mean\b[^.!?\n]{0,100}[.!]\s+(?:it|this|that) (?:means|is)\b",
        )
    ),
    "HUM011": tuple(
        re.compile(_apos(p), re.IGNORECASE)
        for p in (
            r"\bas of my (?:last|latest|most recent) (?:knowledge |training )?(?:update|cutoff|training)\b",
            r"\bas an ai(?: language model| assistant)?\b",
            r"\bi (?:don't|do not|can't|cannot) (?:have access to |browse )?(?:real-time|current|the internet|browse)\b",
            r"\bmy (?:knowledge|training) (?:cutoff|data)\b",
            r"\bwhile (?:specific )?details[^.!?\n]{0,80}\b(?:are|is) limited(?: in available sources)?\b",
        )
    ),
}
_DRAMATIC: Final = re.compile(
    _apos(
        r"^(?:and )?(?:that's the (?:real |whole |entire )?(?:win|point|magic|difference|takeaway|kicker)"
        r"|read that again|let that sink in|that changes everything|make no mistake|full stop)[.!]?$"
    ),
    re.IGNORECASE,
)
_HEADING_EMOJI: Final = re.compile(
    r"^( {0,3}#{1,6}[ \t]+(?:[*_]{1,2})?)((?:[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2190-\u21FF]\ufe0f?[ \t]*)+)"
)
_HEADING_STRIP: Final = re.compile(r"[*_`#]|[.:!?]+$")


def _deletion_range(doc: Document, start: int, end: int) -> tuple[int, int]:
    """Range to delete for a sentence so no stray space or blank line is left."""
    text = doc.text
    first, last = start, end
    while last < len(text) and text[last] in " \t":
        last += 1
    line = doc.line_at(start)
    end_line = doc.line_at(max(start, end - 1))
    at_line_start = text[line.start : first].strip(" \t") == ""
    at_line_end = last >= end_line.end

    def blank(index: int) -> bool:
        return text[doc.lines[index].start : doc.lines[index].end].strip(" \t") == ""

    if at_line_start and at_line_end:
        first, last = line.start, end_line.next
        if line.number == 1 or blank(line.number - 2):
            nxt = end_line.number
            while nxt < len(doc.lines) and blank(nxt):
                last = doc.lines[nxt].next
                nxt += 1
        if last >= len(text) and first > 0:
            prev = line.number - 2
            while prev >= 0 and blank(prev):
                first = doc.lines[prev].start
                prev -= 1
    elif at_line_end:
        while first > line.start and text[first - 1] in " \t":
            first -= 1
    return first, last


def _make(
    rule_id: str,
    doc: Document,
    start: int,
    end: int,
    *,
    fix: tuple[int, int] | None = None,
    **details: object,
) -> Finding:
    return Finding(
        RULES[rule_id],
        start,
        end,
        doc.text[start:end],
        fix_range=fix,
        details=dict(details),
    )


def _regex_findings(rule_id: str, doc: Document, masked: str) -> list[Finding]:
    found: list[Finding] = []
    for pattern in _CANDIDATES[rule_id]:
        for match in pattern.finditer(masked):
            found.append(_make(rule_id, doc, match.start(), match.end()))
    return _drop_overlaps(found)


def _drop_overlaps(findings: list[Finding]) -> list[Finding]:
    kept: list[Finding] = []
    for finding in sorted(findings, key=lambda f: (f.start, -f.end)):
        if kept and finding.start < kept[-1].end:
            continue
        kept.append(finding)
    return kept


def _tail_is_wrappers(masked: str, pos: int) -> bool:
    while True:
        while pos < len(masked) and masked[pos].isspace():
            pos += 1
        if pos >= len(masked):
            return True
        match = _WRAPPER.match(masked, pos)
        if match is None:
            return False
        pos = match.end()


def _scan_residue(doc: Document, enabled: set[str]) -> list[Finding]:
    found: list[Finding] = []
    text = doc.text
    if "HUM001" in enabled:
        for start, end in chat_artifact_spans(doc):
            fix_start = start
            after = text[end] if end < len(text) else "\n"
            if (
                start > 0
                and text[start - 1] in " \t"
                and (after in " \t\r\n" or after in ".,;:!?)")
            ):
                fix_start = start - 1
            found.append(_make("HUM001", doc, start, end, fix=(fix_start, end)))
    if "HUM002" in enabled:
        for region in doc.regions_of(("link_target", "bare_url")):
            url = text[region.start : region.end]
            for match in _TRACKING.finditer(url):
                start, end = region.start + match.start(), region.start + match.end()
                finding = _make("HUM002", doc, start, end, url=url)
                finding.requires = ("--strip-tracking",)
                if _SIGNED.search(url):
                    finding.unfixable_reason = "signed URL must stay exact"
                    finding.details["signed_url"] = True
                else:
                    before = text[start - 1]
                    nxt = text[end] if end < region.end else ""
                    if before == "?" and nxt == "&":
                        finding.fix_range = (start, end + 1)
                    else:
                        finding.fix_range = (start - 1, end)
                found.append(finding)
    if "HUM003" in enabled:
        masked = doc.masked(ALL_KINDS)
        for match in _PLACEHOLDER.finditer(masked):
            found.append(_make("HUM003", doc, match.start(), match.end()))
    return found


def _scan_headings(doc: Document, enabled: set[str], masked: str) -> list[Finding]:
    found: list[Finding] = []
    previous = 0
    paragraphs = doc.paragraphs
    for index, paragraph in enumerate(paragraphs):
        if paragraph.heading_level == 0:
            continue
        line_text = doc.text[paragraph.start : paragraph.end]
        if "HUM004" in enabled and previous and paragraph.heading_level > previous + 1:
            found.append(
                _make(
                    "HUM004",
                    doc,
                    paragraph.start,
                    paragraph.end,
                    level=paragraph.heading_level,
                    previous_level=previous,
                )
            )
        previous = paragraph.heading_level
        if "HUM010" in enabled:
            emoji = _HEADING_EMOJI.match(line_text)
            if emoji is not None:
                start = paragraph.start + len(emoji.group(1))
                found.append(
                    _make(
                        "HUM010", doc, start, start + len(emoji.group(2).rstrip(" \t"))
                    )
                )
        if "HUM009" in enabled and index + 1 < len(paragraphs):
            nxt = paragraphs[index + 1]
            words = _HEADING_STRIP.sub("", paragraph.heading_text).split()
            if (
                nxt.heading_level == 0
                and 0 < len(words) <= 6
                and not doc.overlapping(paragraph.end, nxt.start, BLOCK_KINDS)
            ):
                echo = re.compile(
                    r"^\W*"
                    + r"\s+".join(re.escape(w) for w in words)
                    + r"\s+(?:is|are|was|were|plays?|remains?|has|have|refers? to|can be)\b",
                    re.IGNORECASE,
                )
                match = echo.match(masked[nxt.start : nxt.end])
                if match is not None:
                    found.append(
                        _make(
                            "HUM009",
                            doc,
                            nxt.start,
                            nxt.start + match.end(),
                            heading=paragraph.heading_text,
                        )
                    )
    return found


def _scan_wrappers(doc: Document, masked: str) -> list[Finding]:
    found: list[Finding] = []
    for paragraph in doc.paragraphs:
        if paragraph.heading_level:
            continue
        local = masked[paragraph.start : paragraph.end]
        openers: set[int] = set()
        pos = len(local) - len(local.lstrip())
        while True:
            match = _WRAPPER.match(local, pos)
            if match is None:
                break
            openers.add(match.start())
            start, end = paragraph.start + match.start(), paragraph.start + match.end()
            found.append(
                _make(
                    "HUM005",
                    doc,
                    start,
                    end,
                    fix=_deletion_range(doc, start, end),
                    role="opener",
                )
            )
            pos = match.end()
            while pos < len(local) and local[pos].isspace():
                pos += 1
        for match in _WRAPPER.finditer(local):
            if match.start() in openers or not _tail_is_wrappers(local, match.end()):
                continue
            if re.search(r"[.!?][\"'\u2019)\]]*\s+$", local[: match.start()]) is None:
                continue
            start, end = paragraph.start + match.start(), paragraph.start + match.end()
            found.append(
                _make(
                    "HUM005",
                    doc,
                    start,
                    end,
                    fix=_deletion_range(doc, start, end),
                    role="closer",
                )
            )
    for finding in found:
        if finding.fix_range is None:
            continue
        first, last = finding.fix_range
        if any(first < region.end and last > region.start for region in doc.regions):
            finding.fix_range = None
            finding.unfixable_reason = "wrapper contains protected content"
    return found


def _scan_dramatic(doc: Document, masked: str) -> list[Finding]:
    found: list[Finding] = []
    for index, paragraph in enumerate(doc.paragraphs):
        if paragraph.heading_level or index == 0:
            continue
        stripped = masked[paragraph.start : paragraph.end].strip()
        if stripped and _DRAMATIC.match(stripped) is not None:
            found.append(_make("HUM008", doc, paragraph.start, paragraph.end))
    return found


def scan(doc: Document, enabled: set[str] | None = None) -> list[Finding]:
    """All findings, ordered by offset. ``enabled`` restricts the rule IDs."""
    active = set(RULES) if enabled is None else set(enabled)
    masked = doc.masked(ALL_KINDS)
    found = _scan_residue(doc, active)
    found += _scan_headings(doc, active, masked)
    if "HUM005" in active:
        found += _scan_wrappers(doc, masked)
    if "HUM008" in active:
        found += _scan_dramatic(doc, masked)
    for rule_id in ("HUM006", "HUM007", "HUM011"):
        if rule_id in active:
            found += _regex_findings(rule_id, doc, masked)
    return sorted(found, key=lambda f: (f.start, f.rule.id))


# --------------------------------------------------------------------------- line ranges


def parse_line_ranges(spec: str, line_count: int) -> list[tuple[int, int]]:
    """Parse ``3-7,10`` into merged 1-based inclusive ranges; invalid input raises."""
    if line_count == 0:
        raise InputError("--lines given but the input has no lines")
    ranges: list[tuple[int, int]] = []
    for token in spec.split(","):
        token = token.strip()
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", token)
        if match is None:
            raise InputError(
                f"invalid --lines range {token!r}; use N or N-M, comma separated"
            )
        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) is not None else first
        if first < 1 or last < first:
            raise InputError(f"invalid --lines range {token!r}; need 1 <= start <= end")
        if last > line_count:
            raise InputError(
                f"--lines range {token!r} exceeds the input length ({line_count} lines)"
            )
        ranges.append((first, last))
    return _merge(ranges)


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for first, last in sorted(ranges):
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    return merged


def context_ranges(
    doc: Document, requested: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Requested ranges widened to every paragraph they touch."""
    widened = list(requested)
    for paragraph in doc.paragraphs:
        for first, last in requested:
            if paragraph.first_line <= last and paragraph.last_line >= first:
                widened.append((paragraph.first_line, paragraph.last_line))
                break
    return _merge(widened)


def _touches(ranges: list[tuple[int, int]], first: int, last: int) -> bool:
    return any(first <= hi and last >= lo for lo, hi in ranges)


# --------------------------------------------------------------------------- reporting


def _finding_dict(
    doc: Document, finding: Finding, requested: list[tuple[int, int]] | None
) -> dict[str, object]:
    line, column = doc.position(finding.start)
    end_line, end_col = doc.position(finding.end - 1)
    paragraph = doc.paragraph_at(finding.start)
    entry: dict[str, object] = {
        "id": finding.id,
        "rule": finding.rule.id,
        "name": finding.rule.name,
        "confidence": finding.rule.confidence,
        "pattern": finding.rule.pattern,
        "message": finding.rule.message,
        "start": finding.start,
        "end": finding.end,
        "line": line,
        "column": column,
        "end_line": end_line,
        "end_column": end_col + 1,
        "evidence": finding.evidence,
        "fixable": finding.fixable,
        "paragraph_lines": [paragraph.first_line, paragraph.last_line]
        if paragraph
        else None,
    }
    if finding.requires:
        entry["fix_requires"] = list(finding.requires)
    if finding.unfixable_reason:
        entry["unfixable_reason"] = finding.unfixable_reason
    if finding.details:
        entry["details"] = finding.details
    if requested is not None:
        entry["in_requested_lines"] = _touches(requested, line, end_line)
    return entry


def _windowed(
    doc: Document, findings: list[Finding], requested: list[tuple[int, int]] | None
) -> tuple[list[Finding], list[tuple[int, int]] | None]:
    if requested is None:
        return findings, None
    window = context_ranges(doc, requested)
    kept = [
        f
        for f in findings
        if _touches(window, doc.position(f.start)[0], doc.position(f.end - 1)[0])
    ]
    return kept, window


def _parse_rule_filter(value: str | None) -> set[str] | None:
    if value is None:
        return None
    ids = {token.strip().upper() for token in value.split(",") if token.strip()}
    unknown = sorted(ids - set(RULES))
    if unknown or not ids:
        raise InputError(
            f"unknown rule ID(s): {', '.join(unknown) or '(none given)'}; run `rules` to list them"
        )
    return ids


def cmd_scan(args: argparse.Namespace) -> int:
    text = read_source(args.input)
    doc = parse(text)
    requested = (
        parse_line_ranges(args.lines, len(doc.lines))
        if args.lines is not None
        else None
    )
    findings, window = _windowed(
        doc, scan(doc, _parse_rule_filter(args.rules)), requested
    )
    by_rule: dict[str, int] = {}
    for finding in findings:
        by_rule[finding.rule.id] = by_rule.get(finding.rule.id, 0) + 1
    by_kind: dict[str, int] = {}
    for region in doc.regions:
        by_kind[region.kind] = by_kind.get(region.kind, 0) + 1
    report: dict[str, object] = {
        "tool": "lint_prose",
        "source": args.input,
        "offset_unit": "unicode_code_points",
        "line_endings": detect_line_endings(text),
        "line_count": len(doc.lines),
        "selected_lines": None
        if requested is None or window is None
        else {
            "requested": [list(r) for r in requested],
            "with_paragraph_context": [list(r) for r in window],
        },
        "protected_regions": by_kind,
        "findings": [_finding_dict(doc, f, requested) for f in findings],
        "summary": {"total": len(findings), "by_rule": by_rule},
        "notice": NOTICE,
    }
    if args.show_regions:
        report["regions"] = [
            {
                "kind": r.kind,
                "start": r.start,
                "end": r.end,
                "line": doc.position(r.start)[0],
            }
            for r in doc.regions
        ]
    print(dump_json(report))
    return 1 if args.fail_on_findings and findings else 0


def cmd_rules(args: argparse.Namespace) -> int:
    del args
    print(
        dump_json(
            [
                {
                    "rule": r.id,
                    "name": r.name,
                    "confidence": r.confidence,
                    "mechanical_fix": r.fixable,
                    "pattern": r.pattern,
                }
                for r in RULES.values()
            ]
        )
    )
    return 0


# --------------------------------------------------------------------------- fix

_FINDING_ID: Final = re.compile(r"(HUM\d{3}):(\d+)")


def _same_file(a: Path, b: Path) -> bool:
    if a.exists() and b.exists():
        return os.path.samefile(a, b)
    return a.resolve() == b.resolve()


def _select_fixes(
    findings: list[Finding],
    tokens: list[str],
    requested: list[tuple[int, int]] | None,
    doc: Document,
    strip_tracking: bool,
) -> tuple[list[Finding], list[dict[str, object]]]:
    selected: dict[str, Finding] = {}
    skipped: list[dict[str, object]] = []
    for token in tokens:
        explicit = _FINDING_ID.fullmatch(token.upper())
        rule_id = explicit.group(1) if explicit else token.upper()
        if rule_id not in RULES:
            raise InputError(
                f"unknown rule or finding ID {token!r}; run `rules` to list rule IDs"
            )
        rule = RULES[rule_id]
        if not rule.fixable:
            raise InputError(
                f"{rule_id} ({rule.name}) is review-only; no mechanical fix is supported"
            )
        if rule_id == "HUM002" and not strip_tracking:
            raise InputError(
                "HUM002 edits URLs; pass --strip-tracking to request it explicitly"
            )
        if explicit:
            match = next((f for f in findings if f.id == token.upper()), None)
            if match is None:
                raise InputError(
                    f"no finding {token!r} in this input; scan again and copy an ID"
                )
            if not match.fixable:
                raise InputError(
                    f"{match.id} cannot be fixed: {match.unfixable_reason or 'no safe fix range'}"
                )
            selected[match.id] = match
            continue
        for finding in findings:
            if finding.rule.id != rule_id:
                continue
            if requested is not None:
                line, _ = doc.position(finding.start)
                end_line, _ = doc.position(finding.end - 1)
                if not _touches(requested, line, end_line):
                    continue
            if finding.fixable:
                selected[finding.id] = finding
            else:
                skipped.append(
                    {
                        "id": finding.id,
                        "reason": finding.unfixable_reason or "no safe fix range",
                    }
                )
    return sorted(selected.values(), key=lambda f: f.start), skipped


def _apply_deletions(text: str, ranges: list[tuple[int, int]]) -> str:
    merged: list[tuple[int, int]] = []
    for first, last in sorted(ranges):
        if merged and first <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    out: list[str] = []
    pos = 0
    for first, last in merged:
        out.append(text[pos:first])
        pos = last
    out.append(text[pos:])
    return "".join(out)


def _protected_signature(doc: Document, urls_edited: bool) -> list[tuple[str, str]]:
    kinds = (
        BLOCK_KINDS
        + ("inline_code", "inline_quote")
        + (() if urls_edited else ("link_target", "bare_url"))
    )
    artifacts = chat_artifact_spans(doc)
    return [
        (r.kind, doc.text[r.start : r.end])
        for r in doc.regions
        if r.kind in kinds
        and not any(a <= r.start and r.end <= b for a, b in artifacts)
    ]


def cmd_fix(args: argparse.Namespace) -> int:
    if args.output == "-":
        raise InputError("--output must be a file path; stdout carries the JSON report")
    output = Path(args.output)
    if args.input != "-" and _same_file(Path(args.input), output):
        raise InputError(
            "--output must differ from the input; in-place edits are not supported"
        )
    if output.exists() and not args.force:
        raise InputError(f"{output} already exists; pass --force to overwrite it")
    text = read_source(args.input)
    doc = parse(text)
    requested = (
        parse_line_ranges(args.lines, len(doc.lines))
        if args.lines is not None
        else None
    )
    tokens = [t.strip() for t in args.select.split(",") if t.strip()]
    if not tokens:
        raise InputError("--select needs at least one rule or finding ID")
    findings = scan(doc)
    chosen, skipped = _select_fixes(
        findings, tokens, requested, doc, args.strip_tracking
    )
    report: dict[str, object] = {
        "tool": "lint_prose",
        "action": "fix",
        "source": args.input,
        "output": str(output),
        "offset_unit": "unicode_code_points",
        "skipped": skipped,
        "notice": NOTICE,
    }
    if not chosen:
        report.update({"status": "no_changes", "applied": [], "output_written": False})
        print(dump_json(report))
        return 0
    ranges = [f.fix_range for f in chosen if f.fix_range is not None]
    result = _apply_deletions(text, ranges)
    after = parse(result)
    urls_edited = any(f.rule.id == "HUM002" for f in chosen)
    if _protected_signature(doc, urls_edited) != _protected_signature(
        after, urls_edited
    ):
        print(
            "error: the requested fixes would alter protected content; nothing written",
            file=sys.stderr,
        )
        return 3
    try:
        output.write_bytes(result.encode("utf-8"))
    except OSError as exc:
        raise InputError(
            f"cannot write {output}: {exc.strerror or type(exc).__name__}"
        ) from exc
    report.update(
        {
            "status": "ok",
            "output_written": True,
            "applied": [
                {
                    "id": f.id,
                    "rule": f.rule.id,
                    "line": doc.position(f.start)[0],
                    "column": doc.position(f.start)[1],
                    "evidence": f.evidence,
                    "deleted": text[f.fix_range[0] : f.fix_range[1]]
                    if f.fix_range
                    else "",
                }
                for f in chosen
            ],
        }
    )
    print(dump_json(report))
    return 0


# --------------------------------------------------------------------------- patterns


@dataclass(frozen=True, slots=True)
class PatternSection:
    group: str  # class letter, or "" for the guards section
    group_title: str
    name: str
    body: str


def load_patterns(path: Path = REFERENCE_PATH) -> list[PatternSection]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InputError(
            f"cannot read pattern reference {path}: {exc.strerror or type(exc).__name__}"
        ) from exc
    sections: list[PatternSection] = []
    group, group_title = "", ""
    current: tuple[str, str, str] | None = None
    body: list[str] = []

    def close() -> None:
        nonlocal current
        if current is not None:
            sections.append(
                PatternSection(
                    current[0], current[1], current[2], "\n".join(body).strip()
                )
            )
        current = None
        body.clear()

    for line in lines:
        class_match = re.match(r"^## Class ([A-E]) [\u2014-] (.+)$", line)
        pattern_match = re.match(r"^### Pattern \d+: (.+)$", line)
        if class_match:
            close()
            group, group_title = class_match.group(1), class_match.group(2)
        elif pattern_match:
            close()
            current = (group, group_title, pattern_match.group(1).strip())
        elif line.startswith("## "):
            close()
            if line.strip() == "## False-Positive Guards":
                current = ("", "", "False-Positive Guards")
        elif current is not None and line.strip() != "---":
            body.append(line)
    close()
    if not any(s.group for s in sections):
        raise InputError(
            f"no pattern sections found in {path}; the reference format changed"
        )
    return sections


def cmd_patterns(args: argparse.Namespace) -> int:
    sections = load_patterns()
    picked: list[PatternSection] = []
    selectors = 0
    if args.classes:
        selectors += 1
        letters = {c.strip().upper() for c in args.classes.split(",") if c.strip()}
        if not letters <= set("ABCDE") or not letters:
            raise InputError("--class takes letters A-E, comma separated")
        picked += [s for s in sections if s.group in letters]
    for needle in args.name or []:
        selectors += 1
        hits = [s for s in sections if needle.lower() in s.name.lower()]
        if not hits:
            raise InputError(f"no pattern section matches --name {needle!r}")
        picked += hits
    if args.rules:
        selectors += 1
        for rule_id in sorted(_parse_rule_filter(args.rules) or ()):
            hits = [
                s for s in sections if RULES[rule_id].pattern.lower() in s.name.lower()
            ]
            if not hits:
                raise InputError(
                    f"{rule_id}: guidance section {RULES[rule_id].pattern!r} not found in the reference"
                )
            picked += hits
    if args.guards:
        selectors += 1
        picked += [s for s in sections if s.name == "False-Positive Guards"]
    if args.list:
        selectors += 1
        picked = [s for s in sections]
    if selectors == 0:
        raise InputError(
            "select guidance with --list, --class, --name, --rules or --guards"
        )
    unique = list(dict.fromkeys(picked))
    if not unique:
        raise InputError("selection matched no pattern sections")
    if args.format == "json":
        print(
            dump_json(
                {
                    "source": str(REFERENCE_PATH),
                    "sections": [
                        {
                            "class": s.group,
                            "name": s.name,
                            **({} if args.list else {"text": s.body}),
                        }
                        for s in unique
                    ],
                }
            )
        )
    elif args.list:
        for section in unique:
            print(f"{section.group or '-'}\t{section.name}")
    else:
        for section in unique:
            title = (
                f"Class {section.group}: {section.group_title}"
                if section.group
                else "Guards"
            )
            print(f"### {section.name}  ({title})\n\n{section.body}\n")
    return 0


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="report findings as JSON")
    scan_p.add_argument("input", help="UTF-8 file path, or - for stdin")
    scan_p.add_argument(
        "--lines",
        help="changed 1-based line ranges, e.g. 3-7,12; findings keep paragraph context",
    )
    scan_p.add_argument(
        "--rules", help="comma-separated rule IDs to run (default: all)"
    )
    scan_p.add_argument(
        "--show-regions", action="store_true", help="include every protected region"
    )
    scan_p.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="exit 1 when any finding is reported",
    )
    scan_p.set_defaults(func=cmd_scan)

    fix_p = sub.add_parser(
        "fix", help="delete explicitly selected artifacts into a new file"
    )
    fix_p.add_argument("input", help="UTF-8 file path, or - for stdin")
    fix_p.add_argument(
        "--select",
        required=True,
        help="comma-separated rule IDs (HUM001) or finding IDs (HUM001:812)",
    )
    fix_p.add_argument(
        "--output", required=True, help="new file to write; never the input"
    )
    fix_p.add_argument(
        "--lines",
        help="limit rule-wide selections to findings touching these changed lines",
    )
    fix_p.add_argument(
        "--strip-tracking",
        action="store_true",
        help="allow HUM002 to remove utm_source from unsigned URLs",
    )
    fix_p.add_argument(
        "--force", action="store_true", help="overwrite an existing output file"
    )
    fix_p.set_defaults(func=cmd_fix)

    rules_p = sub.add_parser("rules", help="list rule IDs")
    rules_p.set_defaults(func=cmd_rules)

    pat_p = sub.add_parser("patterns", help="print selected pattern guidance")
    pat_p.add_argument(
        "--list", action="store_true", help="list class and pattern names only"
    )
    pat_p.add_argument(
        "--class", dest="classes", help="class letters A-E, comma separated"
    )
    pat_p.add_argument(
        "--name", action="append", help="pattern name substring; repeatable"
    )
    pat_p.add_argument("--rules", help="rule IDs whose guidance sections to print")
    pat_p.add_argument(
        "--guards", action="store_true", help="include the false-positive guards"
    )
    pat_p.add_argument("--format", choices=("text", "json"), default="text")
    pat_p.set_defaults(func=cmd_patterns)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
