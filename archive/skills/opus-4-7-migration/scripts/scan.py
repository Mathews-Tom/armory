#!/usr/bin/env python3
"""Opus 4.7 migration scanner.

Walks a repository and flags patterns that break or degrade on Claude Opus 4.7:
fixed-budget Extended Thinking parameters, retired model ID aliases, hardcoded
model references outside config, and heuristic signals for verbosity-assuming
prompts and non-explicit parallel sub-agent dispatch.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

_CODE_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
)
_CONFIG_EXTENSIONS: frozenset[str] = frozenset(
    {".toml", ".yaml", ".yml", ".json", ".env"}
)
_DOC_EXTENSIONS: frozenset[str] = frozenset({".md", ".mdx", ".rst"})
_SCANNABLE_EXTENSIONS: frozenset[str] = (
    _CODE_EXTENSIONS | _CONFIG_EXTENSIONS | _DOC_EXTENSIONS
)

_DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
)

_CATEGORY_A_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bbudget_tokens\b\s*="),
    re.compile(r'"budget_tokens"\s*:'),
    re.compile(r"'budget_tokens'\s*:"),
    re.compile(r"\.thinking\.budget_tokens\b"),
)

_CATEGORY_B_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclaude-opus-4-[0-6]\b"),
    re.compile(r"\bclaude-sonnet-4-[0-5]\b"),
    re.compile(r"\bclaude-haiku-4-[0-4]\b"),
    re.compile(r"\bclaude-[a-z]+-\d+-\d{8}\b"),
    re.compile(r"\bclaude-3(?:-[a-z0-9-]+)?\b"),
)

_CATEGORY_C_PATTERN: re.Pattern[str] = re.compile(
    r'["\'](claude-(?:opus|sonnet|haiku)-4-\d+)["\']'
)
_TEST_SENTINEL_PATTERN: re.Pattern[str] = re.compile(r"test[-_]model[-_]?\w*")

_CATEGORY_D_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:explain|walk\s+me\s+through|describe|summari[sz]e)\b.*\bin\s+detail\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bbe\s+(?:verbose|thorough|comprehensive|exhaustive)\b", re.IGNORECASE
    ),
    re.compile(r"\bprovide\s+a\s+(?:detailed|thorough|comprehensive)\b", re.IGNORECASE),
)

_CATEGORY_E_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bspawn\b.*\bparallel\b", re.IGNORECASE),
    re.compile(
        r"\bin\s+parallel\b(?!.*single\s+(?:assistant\s+)?message)", re.IGNORECASE
    ),
)

_CATEGORY_E_NEGATIVE: re.Pattern[str] = re.compile(
    r"single\s+(?:assistant\s+)?message|independent", re.IGNORECASE
)


@dataclass
class Finding:
    category: str
    path: Path
    line_number: int
    matched_text: str


@dataclass
class ScanReport:
    root: Path
    findings: dict[str, list[Finding]] = field(default_factory=dict)

    def add(self, finding: Finding) -> None:
        self.findings.setdefault(finding.category, []).append(finding)

    def total(self) -> int:
        return sum(len(items) for items in self.findings.values())

    def deterministic_total(self) -> int:
        return sum(len(self.findings.get(cat, [])) for cat in ("A", "B", "C"))


def _iter_files(root: Path, excludes: Iterable[str]) -> Iterable[Path]:
    exclude_parts = {part for part in excludes}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _SCANNABLE_EXTENSIONS:
            continue
        if any(part in exclude_parts for part in path.parts):
            continue
        yield path


def _scan_line(
    line: str,
    line_number: int,
    path: Path,
    categories: frozenset[str],
    report: ScanReport,
) -> None:
    if "A" in categories:
        for pattern in _CATEGORY_A_PATTERNS:
            match = pattern.search(line)
            if match is not None:
                report.add(Finding("A", path, line_number, match.group(0)))
                break

    if "B" in categories:
        for pattern in _CATEGORY_B_PATTERNS:
            match = pattern.search(line)
            if match is not None:
                report.add(Finding("B", path, line_number, match.group(0)))
                break

    if "C" in categories and path.suffix.lower() in _CODE_EXTENSIONS:
        match = _CATEGORY_C_PATTERN.search(line)
        if match is not None and not _TEST_SENTINEL_PATTERN.search(line):
            report.add(Finding("C", path, line_number, match.group(1)))

    if "D" in categories:
        for pattern in _CATEGORY_D_PATTERNS:
            match = pattern.search(line)
            if match is not None:
                report.add(Finding("D", path, line_number, match.group(0)))
                break

    if "E" in categories:
        for pattern in _CATEGORY_E_PATTERNS:
            match = pattern.search(line)
            if match is not None and _CATEGORY_E_NEGATIVE.search(line) is None:
                report.add(Finding("E", path, line_number, match.group(0)))
                break


def scan_repository(
    root: Path,
    categories: frozenset[str],
    excludes: Iterable[str],
) -> ScanReport:
    if not root.exists():
        raise FileNotFoundError(f"Repository path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    report = ScanReport(root=root)
    for path in _iter_files(root, excludes):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            _scan_line(line, line_number, path, categories, report)
    return report


_CATEGORY_LABELS: dict[str, str] = {
    "A": "Fixed-budget Extended Thinking",
    "B": "Retired model ID aliases",
    "C": "Hardcoded model refs outside config",
    "D": "Verbosity-assuming prompts",
    "E": "Non-explicit parallel dispatch",
}

_HEURISTIC_CATEGORIES: frozenset[str] = frozenset({"D", "E"})


def format_text_report(report: ScanReport, requested: frozenset[str]) -> str:
    lines: list[str] = []
    lines.append(f"Opus 4.7 Migration Scan — {report.root}")
    lines.append("")
    for category in ("A", "B", "C", "D", "E"):
        label = _CATEGORY_LABELS[category]
        header = f"Category {category}: {label}"
        if category not in requested:
            lines.append(f"{header:<55}skipped")
            continue
        findings = report.findings.get(category, [])
        heuristic_marker = " (heuristic)" if category in _HEURISTIC_CATEGORIES else ""
        lines.append(f"{header:<55}{len(findings)} findings{heuristic_marker}")
        for finding in findings:
            rel = finding.path.relative_to(report.root)
            lines.append(f"  {rel}:{finding.line_number}  {finding.matched_text}")
        lines.append("")

    lines.append(
        f"Total: {report.deterministic_total()} deterministic findings across A/B/C."
    )
    if _HEURISTIC_CATEGORIES & requested:
        heuristic_total = sum(
            len(report.findings.get(cat, []))
            for cat in _HEURISTIC_CATEGORIES & requested
        )
        lines.append(
            f"Heuristic: {heuristic_total} candidates in D/E (review required)."
        )
    return "\n".join(lines)


def format_json_report(report: ScanReport, requested: frozenset[str]) -> str:
    payload: dict[str, object] = {
        "root": str(report.root),
        "requested_categories": sorted(requested),
        "findings": {
            category: [
                {
                    "path": str(finding.path.relative_to(report.root)),
                    "line": finding.line_number,
                    "matched": finding.matched_text,
                }
                for finding in report.findings.get(category, [])
            ]
            for category in sorted(requested)
        },
        "totals": {
            "deterministic": report.deterministic_total(),
            "all_requested": sum(
                len(report.findings.get(cat, [])) for cat in requested
            ),
        },
    }
    return json.dumps(payload, indent=2)


def _parse_categories(raw: str) -> frozenset[str]:
    requested = {c.strip().upper() for c in raw.split(",") if c.strip()}
    invalid = requested - set(_CATEGORY_LABELS)
    if invalid:
        raise ValueError(f"Unknown categories: {sorted(invalid)}. Valid: A,B,C,D,E")
    return frozenset(requested)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan a repository for Opus 4.7 migration candidates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("root", type=Path, help="Repository root path to scan")
    parser.add_argument(
        "--categories",
        default="A,B,C,D,E",
        help="Comma-separated categories to scan (default: A,B,C,D,E)",
    )
    parser.add_argument(
        "--exclude",
        default=",".join(_DEFAULT_EXCLUDES),
        help="Comma-separated path parts to exclude (default: %(default)s)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit 1 if any deterministic findings (A/B/C) are present",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    categories = _parse_categories(args.categories)
    excludes = [part.strip() for part in args.exclude.split(",") if part.strip()]

    report = scan_repository(args.root, categories, excludes)

    if args.format == "json":
        sys.stdout.write(format_json_report(report, categories) + "\n")
    else:
        sys.stdout.write(format_text_report(report, categories) + "\n")

    if args.exit_code and report.deterministic_total() > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
