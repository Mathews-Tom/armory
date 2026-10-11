#!/usr/bin/env python3
"""Compare a source text and its rewrite for protected structure and literals.

Checks, in order:
  1. Protected blocks (frontmatter, fenced/indented/HTML code, tables, block
     quotes): exact decoded text, in order. Removal,
     addition, change and reordering are reported separately.
  2. Inline protected spans (inline code, link targets and URLs, quoted
     snippets) as a multiset: duplicates count, placement is free.
  3. Prose literals as a multiset: citation markers, technical identifiers
     (camelCase, snake_case, dotted names, paths, flags, hashes, ...) and
     numbers with their sign, currency, unit and qualifier ("at least 5 ms").
  4. Explicit --literal strings (names or qualifiers that cannot be inferred).

Prose order is not locked, so sentences may be merged, split and reordered.
Passing means the checked structure and literals are intact. It does not show
that meaning is unchanged; that remains a reading task. Names and terms are
not detected automatically: pass the ones that matter with --literal.

Exit codes: 0 pass, 1 preservation failures, 2 invalid input.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from prose_markup import (
    ALL_KINDS,
    BLOCK_KINDS,
    chat_artifact_spans,
    code_spans,
    Document,
    InputError,
    detect_line_endings,
    dump_json,
    parse,
    read_source,
)

NOTICE: Final = (
    "Passing means the checked protected structure and literals are intact. It does not show "
    "semantic equivalence. Names and terms are checked only when passed with --literal."
)
ALLOWABLE: Final = ("frontmatter", "table", "quote", "inline_quote", "url")
_PAIR_THRESHOLD: Final = 0.6

# --------------------------------------------------------------------------- literal patterns

_NAME: Final = r"[A-Z][\w'\u2019-]+"
_AUTHOR: Final = rf"{_NAME}(?: et al\.|,? (?:and|&) {_NAME})?"
_YEAR: Final = r"(?:1[5-9]|20)\d{2}[a-z]?"
_ENTRY: Final = rf"{_AUTHOR},? {_YEAR}(?:,? pp?\. ?\d+(?:[-\u2013]\d+)?)?"

CITATION_PATTERNS: Final[tuple[str, ...]] = (
    r"\[\^[\w-]+\]",
    r"\[@[^\]\n]{1,80}\]",
    r"\\cite[tp]?\{[^}\n]+\}",
    r"\[\d{1,4}(?:\s*[,\u2013-]\s*\d{1,4})*\]",
    r"\b10\.\d{4,9}/[^\s\"<>]*[^\s\"<>.,;:)\]]",
    r"\barXiv:\s?\d{4}\.\d{4,5}(?:v\d+)?",
    rf"\({_ENTRY}(?:; {_ENTRY})*\)",
    rf"{_AUTHOR} \({_YEAR}\)",
)


def _not_abbreviation(text: str) -> bool:
    """Dotted names need a segment of 2+ characters ("e.g", "i.e", "U.S" are prose)."""
    return any(len(part) >= 2 for part in text.removesuffix("()").split("."))


IDENTIFIER_PATTERNS: Final[tuple[tuple[str, bool], ...]] = (
    (r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", False),
    (r"(?<![\w/.:])(?:~|\.{1,2})?(?:/[\w.@+-]+){2,}", False),
    (r"(?<![\w/.:])(?:~|\.{1,2})/[\w.@+-]+(?:/[\w.@+-]+)*", False),
    (r"(?<![\w/.:@-])[\w.-]+(?:/[\w.-]+)+\.\w{1,8}\b", False),
    (r"(?<![\w/.:@-])[\w.-]+(?:/[\w.-]+){2,}", False),
    (r"(?<![\w-])--[a-z][\w-]*", False),
    (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", False),
    (r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b", False),
    (r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+(?:\(\))?", True),
    (r"(?<!\w)__[A-Za-z]\w*__(?!\w)", False),
    (r"(?<!\w)[A-Za-z][A-Za-z0-9]*(?:_+[A-Za-z0-9]+)+(?!\w)", False),
    (r"\b[a-z]+(?:[A-Z][a-z0-9]*)+\b", False),
    (r"\b(?:[A-Z]+[a-z0-9]+){2,}\b", False),
    (r"\b[A-Za-z]+\d+[A-Za-z0-9]*(?:\.\d+)*\b", False),
    (r"\b[A-Za-z_]\w*\(\)", False),
    (r"(?<![\w/])#\d+\b|(?<![\w@.])@[A-Za-z][\w-]*", False),
)

_QUALIFIERS: Final[dict[str, str]] = {
    "about": "approx",
    "around": "approx",
    "approximately": "approx",
    "roughly": "approx",
    "~": "approx",
    "\u2248": "approx",
    "over": "gt",
    "more than": "gt",
    "above": "gt",
    ">": "gt",
    "at least": "gte",
    "no less than": "gte",
    "no fewer than": "gte",
    "\u2265": "gte",
    "under": "lt",
    "less than": "lt",
    "fewer than": "lt",
    "below": "lt",
    "<": "lt",
    "at most": "lte",
    "up to": "lte",
    "no more than": "lte",
    "not more than": "lte",
    "not over": "lte",
    "not above": "lte",
    "not less than": "gte",
    "not fewer than": "gte",
    "not under": "gte",
    "not below": "gte",
    "\u2264": "lte",
    "nearly": "almost",
    "almost": "almost",
    "exactly": "exact",
    "\u00b1": "pm",
}
_QUAL_WORDS: Final = "|".join(
    re.escape(w)
    for w in sorted((q for q in _QUALIFIERS if q[0].isalpha()), key=len, reverse=True)
)
_UNIT_SPACED: Final = (
    "ms",
    "\u03bcs",
    "\u00b5s",
    "ns",
    "sec",
    "secs",
    "second",
    "seconds",
    "min",
    "mins",
    "minute",
    "minutes",
    "hour",
    "hours",
    "hr",
    "hrs",
    "day",
    "days",
    "week",
    "weeks",
    "month",
    "months",
    "year",
    "years",
    "yr",
    "yrs",
    "KB",
    "MB",
    "GB",
    "TB",
    "PB",
    "KiB",
    "MiB",
    "GiB",
    "TiB",
    "kB",
    "Kb",
    "Mb",
    "Gb",
    "Tb",
    "byte",
    "bytes",
    "bit",
    "bits",
    "kbps",
    "Kbps",
    "Mbps",
    "Gbps",
    "Hz",
    "kHz",
    "MHz",
    "GHz",
    "px",
    "pt",
    "rem",
    "vh",
    "vw",
    "dpi",
    "fps",
    "rpm",
    "mW",
    "kW",
    "MW",
    "mV",
    "kV",
    "mA",
    "Ah",
    "Wh",
    "kWh",
    "J",
    "kJ",
    "Pa",
    "kPa",
    "MPa",
    "bar",
    "psi",
    "mm",
    "cm",
    "km",
    "mi",
    "mile",
    "miles",
    "ft",
    "feet",
    "inch",
    "inches",
    "kg",
    "mg",
    "lb",
    "lbs",
    "oz",
    "mL",
    "ml",
    "gal",
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CAD",
    "AUD",
    "CHF",
    "INR",
    "CNY",
    "s",
    "m",
    "h",
    "g",
    "thousand",
    "million",
    "billion",
    "trillion",
    "lakh",
    "crore",
)
_UNIT_ATTACHED: Final = (
    "k",
    "K",
    "M",
    "B",
    "T",
    "G",
    "x",
    "X",
    "L",
    "l",
    "bn",
    "mn",
    "V",
    "W",
    "A",
)
_UNIT_ALIASES: Final[dict[str, str]] = {
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "min": "min",
    "mins": "min",
    "minute": "min",
    "minutes": "min",
    "hour": "h",
    "hours": "h",
    "hr": "h",
    "hrs": "h",
    "day": "day",
    "days": "day",
    "week": "week",
    "weeks": "week",
    "month": "month",
    "months": "month",
    "year": "year",
    "years": "year",
    "yr": "year",
    "yrs": "year",
    "byte": "B",
    "bytes": "B",
    "bit": "bit",
    "bits": "bit",
    "mile": "mi",
    "miles": "mi",
    "feet": "ft",
    "inch": "in",
    "inches": "in",
    "lbs": "lb",
    "\u03bcs": "us",
    "\u00b5s": "us",
    "percent": "%",
    "per cent": "%",
    "pct": "%",
}


def _alternation(words: Sequence[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


_SPECIAL_NUMERIC: Final = (
    re.compile(
        r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
    ),
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?(?i:[ap]\.?m\.?))?(?![\w:])"),
    re.compile(r"\bv?\d+(?:\.\d+){2,}(?:[-+][\w.]+)?\b"),
)
_NUMERIC: Final = re.compile(
    rf"(?:(?<![\w])(?P<qw>(?i:{_QUAL_WORDS}))\s+|(?P<qs>[~\u2248<>\u2264\u2265\u00b1])\s?)?"
    r"(?P<sign>(?<![\w.)\]\u2013-])[-+\u2212])?"
    r"(?P<cur>US\$|[$\u20ac\u00a3\u00a5\u20b9])?"
    r"(?P<num>(?<![^\W_])(?:\d{1,3}(?:[,\u00a0\u202f\u2009]\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
    rf"(?P<unit>\s?%|\s(?i:percent|per cent)(?![^\W_])|\s?\u00b0[CF]?|\s?(?:{_alternation(_UNIT_SPACED)})(?![^\W_]|['\u2019])"
    rf"|(?:{_alternation(_UNIT_ATTACHED)})(?![^\W_]|['\u2019]))?"
    r"(?:\s+(?P<post>(?i:or more|or less|or fewer))(?!\w))?"
)
_LIST_NUMBER: Final = re.compile(r"^[ \t]*\d{1,9}[.)](?=[ \t])", re.MULTILINE)

# --------------------------------------------------------------------------- items


@dataclass(frozen=True, slots=True)
class Item:
    category: str
    key: str  # comparison text
    label: str  # text as written
    line: int
    fields: tuple[tuple[str, str], ...] = ()


def _canon_numeric(match: re.Match[str]) -> tuple[str, tuple[tuple[str, str], ...]]:
    qual_raw = match.group("qw") or match.group("qs") or ""
    qual = _QUALIFIERS.get(" ".join(qual_raw.lower().split()), "") if qual_raw else ""
    postfix = (match.group("post") or "").lower()
    postfix_qualifier = {"or more": "gte", "or less": "lte", "or fewer": "lte"}.get(
        postfix, ""
    )
    if postfix_qualifier:
        qual = (
            postfix_qualifier
            if not qual or qual == postfix_qualifier
            else f"{qual};{postfix_qualifier}"
        )
    sign = (match.group("sign") or "").replace("\u2212", "-")
    cur = match.group("cur") or ""
    num = re.sub(r"[,\u00a0\u202f\u2009]", "", match.group("num"))
    unit_raw = " ".join((match.group("unit") or "").split())
    unit = _UNIT_ALIASES.get(unit_raw.lower(), _UNIT_ALIASES.get(unit_raw, unit_raw))
    fields = (
        ("qualifier", qual),
        ("sign", sign),
        ("currency", cur),
        ("number", num),
        ("unit", unit),
    )
    return "|".join(value for _, value in fields), fields


def _consume(
    work: str,
    regex: re.Pattern[str],
    category: str,
    doc: Document,
    items: list[Item],
    *,
    accept: bool = False,
    numeric: bool = False,
) -> str:
    spans: list[tuple[int, int]] = []
    for match in regex.finditer(work):
        label = match.group().strip()
        if accept and not _not_abbreviation(label):
            continue
        if not label:
            continue
        key, fields = (label, ()) if not numeric else _canon_numeric(match)
        if category != "numeric":
            key = label
        items.append(Item(category, key, label, doc.position(match.start())[0], fields))
        spans.append(match.span())
    for start, end in spans:
        work = work[:start] + re.sub(r"[^\r\n]", " ", work[start:end]) + work[end:]
    return work


def extract_literals(doc: Document) -> list[Item]:
    """Citation markers, technical identifiers and numeric literals found in prose."""
    work = doc.masked(ALL_KINDS)
    for first, last in chat_artifact_spans(doc):
        work = work[:first] + " " * (last - first) + work[last:]
    paragraph_starts = {paragraph.start for paragraph in doc.paragraphs}
    previous_marker = False
    for line in doc.lines:
        body = work[line.start : line.end]
        marker = _LIST_NUMBER.match(body)
        if marker is not None and (line.start in paragraph_starts or previous_marker):
            last = line.start + marker.end()
            work = work[: line.start] + " " * marker.end() + work[last:]
            previous_marker = True
        elif body.strip():
            previous_marker = False
    items: list[Item] = []
    for pattern in CITATION_PATTERNS:
        work = _consume(work, re.compile(pattern), "citation", doc, items)
    for regex in _SPECIAL_NUMERIC:
        before = len(items)
        work = _consume(work, regex, "numeric", doc, items)
        items[before:] = [
            Item(
                i.category,
                re.sub(r"\s+", "", i.label),
                i.label,
                i.line,
                (("number", re.sub(r"\s+", "", i.label)),),
            )
            for i in items[before:]
        ]
    for pattern, dotted in IDENTIFIER_PATTERNS:
        work = _consume(
            work, re.compile(pattern), "identifier", doc, items, accept=dotted
        )
    _consume(work, _NUMERIC, "numeric", doc, items, numeric=True)
    return items


def extra_literal_items(doc: Document, literals: Sequence[str]) -> list[Item]:
    prose = doc.masked(ALL_KINDS)
    items: list[Item] = []
    for literal in literals:
        pattern = (
            "(?<!\\w)" if literal[0].isalnum() or literal[0] == "_" else ""
        ) + re.escape(literal)
        pattern += "(?!\\w)" if literal[-1].isalnum() or literal[-1] == "_" else ""
        for match in re.finditer(pattern, prose):
            items.append(
                Item("extra", literal, literal, doc.position(match.start())[0])
            )
    return items


def block_items(doc: Document) -> list[Item]:
    items = []
    for region in doc.regions_of(BLOCK_KINDS):
        text = doc.text[region.start : region.end]
        items.append(Item(region.kind, text, text, doc.position(region.start)[0]))
    return items


def inline_items(doc: Document) -> list[Item]:
    items: list[Item] = []
    artifacts = chat_artifact_spans(doc)
    for region in doc.regions:
        if any(
            first <= region.start and region.end <= last for first, last in artifacts
        ):
            continue
        raw = doc.text[region.start : region.end]
        line = doc.position(region.start)[0]
        if region.kind == "inline_code":
            items.append(Item("inline_code", raw, raw, line))
        elif region.kind in ("link_target", "bare_url"):
            url = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
            items.append(Item("url", url, raw, line))
        elif region.kind == "inline_quote":
            items.append(Item("inline_quote", raw, raw, line))
    return items


def nested_code_items(doc: Document, allowed: set[str]) -> list[Item]:
    """An editable quote or table cannot make its embedded code editable."""
    items: list[Item] = []
    code_kinds = ("fenced_code", "indented_code", "html_code")
    pending: list[tuple[str, int]] = []
    for region in doc.regions:
        if region.kind not in allowed or region.kind not in (
            "quote",
            "table",
            "inline_quote",
        ):
            continue
        raw = doc.text[region.start : region.end]
        if region.kind == "quote":
            raw = re.sub(r"^ {0,3}>[ \t]?", "", raw, flags=re.MULTILINE)
        pending.append((raw, doc.position(region.start)[0]))
    while pending:
        raw, first_line = pending.pop()
        nested = parse(raw)
        blocked = nested.regions_of(code_kinds + ("quote",))
        for region in blocked:
            body = raw[region.start : region.end]
            line = first_line + nested.position(region.start)[0] - 1
            if region.kind == "quote":
                pending.append(
                    (re.sub(r"^ {0,3}>[ \t]?", "", body, flags=re.MULTILINE), line)
                )
            else:
                items.append(Item(region.kind, body, body, line))
        for first, last in code_spans(raw):
            if any(first < region.end and last > region.start for region in blocked):
                continue
            body = raw[first:last]
            items.append(
                Item(
                    "inline_code",
                    body,
                    body,
                    first_line + nested.position(first)[0] - 1,
                )
            )
    return items


# --------------------------------------------------------------------------- diffing


def _excerpt(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _where(item: Item) -> dict[str, object]:
    return {"line": item.line, "text": _excerpt(item.label)}


def _similarity(a: Item, b: Item) -> float:
    fields_a, fields_b = dict(a.fields), dict(b.fields)
    if fields_a.get("number") and fields_a.get("number") == fields_b.get("number"):
        return 1.0
    return difflib.SequenceMatcher(None, a.key, b.key).ratio()


def _pair(
    removed: list[Item], added: list[Item]
) -> tuple[list[tuple[Item, Item]], list[Item], list[Item]]:
    scored = sorted(
        (
            (score, i, j)
            for i, a in enumerate(removed)
            for j, b in enumerate(added)
            if a.category == b.category
            and (score := _similarity(a, b)) >= _PAIR_THRESHOLD
        ),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    used_r: set[int] = set()
    used_a: set[int] = set()
    pairs: list[tuple[Item, Item]] = []
    for _score, i, j in scored:
        if i in used_r or j in used_a:
            continue
        used_r.add(i)
        used_a.add(j)
        pairs.append((removed[i], added[j]))
    pairs.sort(key=lambda p: p[0].line)
    rest_removed = [item for i, item in enumerate(removed) if i not in used_r]
    rest_added = [item for j, item in enumerate(added) if j not in used_a]
    return pairs, rest_removed, rest_added


def _split(
    source: list[Item], draft: list[Item]
) -> tuple[list[Item], list[Item], Counter[tuple[str, str]], Counter[tuple[str, str]]]:
    src_count = Counter((i.category, i.key) for i in source)
    drf_count = Counter((i.category, i.key) for i in draft)
    left = Counter(drf_count)
    removed: list[Item] = []
    for item in source:
        slot = (item.category, item.key)
        if left[slot] > 0:
            left[slot] -= 1
        else:
            removed.append(item)
    left = Counter(src_count)
    added: list[Item] = []
    for item in draft:
        slot = (item.category, item.key)
        if left[slot] > 0:
            left[slot] -= 1
        else:
            added.append(item)
    return removed, added, src_count, drf_count


def multiset_failures(
    check: str, source: list[Item], draft: list[Item], allowed: set[str]
) -> list[dict[str, object]]:
    removed, added, src_count, drf_count = _split(
        [i for i in source if i.category not in allowed],
        [i for i in draft if i.category not in allowed],
    )
    pairs, rest_removed, rest_added = _pair(removed, added)
    failures: list[dict[str, object]] = []
    for before, after in pairs:
        entry: dict[str, object] = {
            "check": check,
            "category": before.category,
            "problem": "changed",
            "source": _where(before),
            "draft": _where(after),
        }
        fields_a, fields_b = dict(before.fields), dict(after.fields)
        differing = [name for name in fields_a if fields_a[name] != fields_b.get(name)]
        if differing:
            entry["changed_parts"] = differing
        failures.append(entry)
    for problem, side, own, other in (
        ("removed", rest_removed, src_count, drf_count),
        ("added", rest_added, drf_count, src_count),
    ):
        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for item in side:
            slot = (item.category, item.key)
            if slot in grouped:
                lines = grouped[slot]["lines"]
                assert isinstance(lines, list)
                lines.append(item.line)
                continue
            grouped[slot] = {
                "check": check,
                "category": item.category,
                "problem": problem,
                "item": _where(item),
                "lines": [item.line],
                "source_count": (own if problem == "removed" else other)[slot],
                "draft_count": (other if problem == "removed" else own)[slot],
            }
        failures.extend(grouped.values())
    return failures


def _longest_increasing(values: list[int]) -> set[int]:
    """Indexes (into ``values``) of one longest strictly increasing subsequence."""
    best: list[list[int]] = []
    for index, value in enumerate(values):
        chain: list[int] = []
        for run in best:
            if values[run[-1]] < value and len(run) > len(chain):
                chain = run
        best.append([*chain, index])
    longest = max(best, key=len) if best else []
    return set(longest)


def block_failures(
    source: list[Item], draft: list[Item], allowed: set[str]
) -> list[dict[str, object]]:
    source = [i for i in source if i.category not in allowed]
    draft = [i for i in draft if i.category not in allowed]
    used: set[int] = set()
    matched: list[tuple[int, int]] = []
    unmatched_source: list[int] = []
    for i, item in enumerate(source):
        for j, other in enumerate(draft):
            if (
                j not in used
                and other.category == item.category
                and other.key == item.key
            ):
                used.add(j)
                matched.append((i, j))
                break
        else:
            unmatched_source.append(i)
    unmatched_draft = [j for j in range(len(draft)) if j not in used]
    failures: list[dict[str, object]] = []
    pairs, rest_removed, rest_added = _pair(
        [source[i] for i in unmatched_source], [draft[j] for j in unmatched_draft]
    )
    for before, after in pairs:
        failures.append(
            {
                "check": "protected_block",
                "category": before.category,
                "problem": "changed",
                "source": _where(before),
                "draft": _where(after),
            }
        )
    for item in rest_removed:
        failures.append(
            {
                "check": "protected_block",
                "category": item.category,
                "problem": "removed",
                "item": _where(item),
            }
        )
    for item in rest_added:
        failures.append(
            {
                "check": "protected_block",
                "category": item.category,
                "problem": "added",
                "item": _where(item),
            }
        )
    in_order = _longest_increasing([j for _, j in matched])
    for position, (i, j) in enumerate(matched):
        if position not in in_order:
            failures.append(
                {
                    "check": "protected_block",
                    "category": source[i].category,
                    "problem": "reordered",
                    "source": _where(source[i]),
                    "draft": _where(draft[j]),
                }
            )
    return failures


# --------------------------------------------------------------------------- CLI


def compare(
    source_text: str, draft_text: str, literals: Sequence[str], allowed: set[str]
) -> dict[str, object]:
    source_doc, draft_doc = parse(source_text), parse(draft_text)
    for literal in literals:
        if not extra_literal_items(source_doc, [literal]):
            raise InputError(
                f"--literal {literal!r} does not occur in the source prose"
            )
    source_blocks, draft_blocks = block_items(source_doc), block_items(draft_doc)
    source_inline = inline_items(source_doc) + nested_code_items(source_doc, allowed)
    draft_inline = inline_items(draft_doc) + nested_code_items(draft_doc, allowed)
    source_lit = extract_literals(source_doc) + extra_literal_items(
        source_doc, literals
    )
    draft_lit = extract_literals(draft_doc) + extra_literal_items(draft_doc, literals)

    failures = block_failures(source_blocks, draft_blocks, allowed)
    failures += multiset_failures(
        "inline_protected", source_inline, draft_inline, allowed
    )
    failures += multiset_failures("literal", source_lit, draft_lit, set())

    warnings: list[str] = []
    source_eol, draft_eol = (
        detect_line_endings(source_text),
        detect_line_endings(draft_text),
    )
    if source_eol != draft_eol and "none" not in (source_eol, draft_eol):
        warnings.append(
            f"line endings differ (source {source_eol}, draft {draft_eol}); protected regions are compared verbatim"
        )
    if not source_blocks and not source_inline and not source_lit:
        warnings.append(
            "the source has no protected content or literals; this check had nothing to compare"
        )
    counts = Counter(item.category for item in source_lit)
    return {
        "tool": "check_preservation",
        "status": "fail" if failures else "pass",
        "checked": {
            "protected_blocks": len(source_blocks),
            "inline_protected": len(source_inline),
            "literals": dict(sorted(counts.items())),
            "explicit_literals": list(literals),
        },
        "allowed_to_change": sorted(allowed),
        "failures": failures,
        "warnings": warnings,
        "notice": NOTICE,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("source", help="original text: UTF-8 file path, or - for stdin")
    parser.add_argument("draft", help="rewritten text: UTF-8 file path, or - for stdin")
    parser.add_argument(
        "--literal",
        action="append",
        default=[],
        metavar="TEXT",
        help="exact name, term or qualifier that must keep its count in the draft; repeatable",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        choices=ALLOWABLE,
        help="permit edits to this kind when the user asked for them; repeatable. Code is never allowable",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.source == "-" and args.draft == "-":
            raise InputError("only one of source and draft can be read from stdin")
        for literal in args.literal:
            if not literal or "\n" in literal or "\r" in literal:
                raise InputError("--literal must be a non-empty single-line string")
        source_text = read_source(args.source)
        draft_text = read_source(args.draft)
        allowed = set(args.allow)
        literals = list(dict.fromkeys(args.literal))
        report = compare(source_text, draft_text, literals, allowed)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report["source"] = args.source
    report["draft"] = args.draft
    print(dump_json(report))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
