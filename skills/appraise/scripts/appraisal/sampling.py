"""Stratified, deterministic sampling of files and commits.

Required strata come first (entry point, critical path and its tests, design
records, benchmark methodology, CI, security, persistence, concurrency, failure
handling, operations); remaining budget is spread round-robin across
subsystems ordered by candidate-attributed lines, so the sample is neither the
README, the newest commits, nor only the largest files.
"""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import Any

from .history import Commit

CONTENT_SIGNALS: dict[str, re.Pattern[str]] = {
    "security": re.compile(
        r"\b(authn|authz|authenticat\w*|authoriz\w*|secret|password|passwd|credential\w*|encrypt\w*|decrypt\w*|hmac|oauth|csrf|xss|sanitiz\w*|permission\w*|allowlist|denylist|path traversal|shell=True|verify_ssl|cert\w*)\b",
        re.IGNORECASE,
    ),
    "persistence": re.compile(
        r"\b(sqlite\w*|postgres\w*|database|cursor\.execute|commit\(\)|migration|CREATE TABLE|INSERT INTO|redis|transaction|duckdb|orm)\b",
        re.IGNORECASE,
    ),
    "concurrency": re.compile(
        r"(\basync def\b|\bawait\b|\bthreading\b|Thread\(|Lock\(|\basyncio\b|concurrent\.futures|multiprocessing|\bgo func\b|sync\.Mutex|Semaphore|\bspawn\b|Arc<)"
    ),
    "failure_handling": re.compile(
        r"\b(retry|retries|backoff|timeout|fallback|circuit|except\s+\w+|raise\s+\w+Error|errors\.Is|Result<)\b"
    ),
    "operations": re.compile(
        r"\b(logging|logger|metrics|prometheus|opentelemetry|telemetry|healthcheck|tracing|structlog)\b",
        re.IGNORECASE,
    ),
}
_ENTRY_NAMES = {
    "__main__.py",
    "main.py",
    "cli.py",
    "app.py",
    "server.py",
    "main.go",
    "main.rs",
    "lib.rs",
    "index.ts",
    "index.js",
    "main.ts",
    "program.cs",
}
_DESIGN_NAME = re.compile(
    r"(^|[-_.])(adr|design|architecture|rfc|decision|proposal)s?([-_.]|$)",
    re.IGNORECASE,
)
_DESIGN_DIRS = {
    "adr",
    "adrs",
    "rfc",
    "rfcs",
    "design",
    "designs",
    "decisions",
    "architecture",
    "proposals",
}
_BENCH = re.compile(r"(^|/)(bench\w*|evals?|experiments?)/", re.IGNORECASE)
_FIX = re.compile(r"\b(fix|bug|regress|hotfix|patch|crash|leak)\w*", re.IGNORECASE)
_REFACTOR = re.compile(
    r"\b(refactor|restructur|extract|rewrite|simplif|redesign|migrat)\w*", re.IGNORECASE
)
_REVERT = re.compile(r"^revert\b", re.IGNORECASE)

DEPTH_BUDGETS = {
    "quick": {
        "sample_files": 10,
        "sample_commits": 5,
        "blame_files": 1000,
        "host_identity_lookups": 10,
        "read_lines_per_item": 150,
    },
    "standard": {
        "sample_files": 24,
        "sample_commits": 12,
        "blame_files": 2000,
        "host_identity_lookups": 30,
        "read_lines_per_item": 400,
    },
    "deep": {
        "sample_files": 48,
        "sample_commits": 24,
        "blame_files": 0,
        "host_identity_lookups": 60,
        "read_lines_per_item": 1000,
    },
}


def content_signals(text: str) -> list[str]:
    return sorted(
        name
        for name, pattern in CONTENT_SIGNALS.items()
        if len(pattern.findall(text)) >= 2
    )


_PY_IMPORT = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import\s+([\w, ()]+)|import\s+([\w.]+))", re.MULTILINE
)


def python_central_modules(
    texts: dict[str, str], top: int = 5, min_importers: int = 3
) -> set[str]:
    """Python source files imported by the most other files (a cheap structural-centrality proxy)."""
    modules: dict[str, str] = {}
    for path in texts:
        if not path.endswith(".py"):
            continue
        parts = list(PurePosixPath(path).with_suffix("").parts)
        if parts and parts[0] in {"src", "lib"}:
            parts = parts[1:]
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            modules[".".join(parts)] = path
    importers: dict[str, set[str]] = {}
    for path, text in texts.items():
        if not path.endswith(".py"):
            continue
        for m in _PY_IMPORT.finditer(text):
            names = (
                [m.group(3)]
                if m.group(3)
                else [m.group(1)]
                + [f"{m.group(1)}.{n.strip(' ()')}" for n in m.group(2).split(",")]
            )
            for name in names:
                target = modules.get(name)
                if target and target != path:
                    importers.setdefault(target, set()).add(path)
    ranked = sorted(importers.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return {
        path
        for path, who in ranked[:top]
        if len(who) >= min_importers and not path.endswith("__init__.py")
    }


def path_signals(path: str, category: str, entry_modules: set[str]) -> list[str]:
    signals: list[str] = []
    name = PurePosixPath(path).name
    if category == "source" and path in entry_modules:
        signals += ["declared_entry_point", "entry_point"]
    elif category == "source" and (name in _ENTRY_NAMES or path.startswith("cmd/")):
        signals.append("entry_point")
    parts = PurePosixPath(path.lower()).parts
    if category == "docs" and (
        _DESIGN_NAME.search(PurePosixPath(path).stem) or set(parts[:-1]) & _DESIGN_DIRS
    ):
        signals.append("design_record")
    if category in {"docs", "source"} and _BENCH.search(path):
        signals.append("benchmark_methodology")
    return signals


def _score(f: dict[str, Any]) -> float:
    share = f["candidate_lines"] / f["lines"] if f["lines"] else 0.0
    return (0.25 + share) * math.log1p(f["lines"]) * (1 + 0.4 * len(f["signals"]))


MIN_OWNED_LINES = 5


def sample_files(
    repo_id: str, files: list[dict[str, Any]], budget: int, read_lines: int
) -> list[dict[str, Any]]:
    pool = [
        f
        for f in files
        if f["lines"] > 0 and f["category"] in {"source", "test", "docs", "ci", "build"}
    ]
    pool = [
        f
        for f in pool
        if f["category"] != "docs"
        or set(f["signals"]) & {"design_record", "benchmark_methodology"}
        or f["path"].lower().startswith("readme")
    ]
    ranked = sorted(pool, key=lambda f: (-_score(f), f["path"]))
    # Files with at least a few candidate-authored lines; for a minor contributor these are the only files worth reading.
    owned = [f for f in ranked if f["candidate_lines"] >= MIN_OWNED_LINES]
    chosen: dict[str, list[str]] = {}

    def pick(
        pred: Any, reason: str, prefer_candidate: bool = True
    ) -> dict[str, Any] | None:
        options = [f for f in ranked if pred(f) and f["path"] not in chosen]
        if prefer_candidate and any(
            f["candidate_lines"] >= MIN_OWNED_LINES for f in options
        ):
            options = [f for f in options if f["candidate_lines"] >= MIN_OWNED_LINES]
        if not options or len(chosen) >= budget:
            return None
        chosen[options[0]["path"]] = [reason]
        return options[0]

    pick(
        lambda f: "declared_entry_point" in f["signals"],
        "entry point declared in the project manifest",
    ) or pick(lambda f: "entry_point" in f["signals"], "entry point")
    pick(
        lambda f: "central" in f["signals"],
        "most depended-on module (import centrality)",
    )
    pick(
        lambda f: "central" in f["signals"],
        "most depended-on module (import centrality)",
    )
    critical = max(
        (f for f in ranked if f["category"] == "source" and f["path"] not in chosen),
        key=lambda f: (f["candidate_lines"], f["lines"], f["path"]),
        default=None,
    )
    if critical is not None and len(chosen) < budget:
        chosen[critical["path"]] = [
            "critical path: largest candidate-attributed source file"
        ]
        stem = PurePosixPath(critical["path"]).stem
        pick(
            lambda f: f["category"] == "test" and stem in PurePosixPath(f["path"]).stem,
            f"tests for critical path {critical['path']}",
            prefer_candidate=False,
        )
    for signal, reason in (
        ("design_record", "design record"),
        ("benchmark_methodology", "benchmark methodology"),
        ("security", "security / trust boundary"),
        ("persistence", "persistence"),
        ("concurrency", "concurrency"),
        ("failure_handling", "failure handling"),
        ("operations", "operations / observability"),
    ):
        pick(lambda f, s=signal: s in f["signals"], reason)
    pick(
        lambda f: f["category"] == "ci", "CI / release workflow", prefer_candidate=False
    )
    pick(lambda f: f["category"] == "test", "test suite sample")
    pick(lambda f: f["category"] == "test", "test suite sample")

    by_subsystem: dict[str, list[dict[str, Any]]] = {}
    for f in (
        sorted(owned, key=lambda f: (-f["candidate_lines"], f["path"]))
        if owned
        else ranked
    ):
        by_subsystem.setdefault(f["subsystem"], []).append(f)
    order = sorted(
        by_subsystem,
        key=lambda s: (-sum(f["candidate_lines"] for f in by_subsystem[s]), s),
    )
    while len(chosen) < budget:
        progressed = False
        for sub in order:
            nxt = next((f for f in by_subsystem[sub] if f["path"] not in chosen), None)
            if nxt is not None and len(chosen) < budget:
                chosen[nxt["path"]] = [f"subsystem coverage: {sub}"]
                progressed = True
        if not progressed:
            break

    index = {f["path"]: f for f in files}
    items = []
    for n, (path, reasons) in enumerate(chosen.items(), start=1):
        f = index[path]
        extra = [f"signal: {s}" for s in f["signals"] if f"signal: {s}" not in reasons]
        items.append(
            {
                "id": f"S-{repo_id}-{n:03d}",
                "kind": "file",
                "path": path,
                "lines": f["lines"],
                "read_budget": max(1, min(f["lines"], read_lines)),
                "subsystem": f["subsystem"],
                # A file the candidate touched but blame skipped has unknown ownership, not zero.
                "candidate_share": None
                if not f["lines"] or (f["candidate_touched"] and not f["blamed"])
                else round(f["candidate_lines"] / f["lines"], 4),
                "reasons": reasons + extra,
            }
        )
    return items


def sample_commits(
    repo_id: str,
    commits: list[Commit],
    included_paths: set[str],
    budget: int,
    start_index: int,
    read_lines: int,
) -> list[dict[str, Any]]:
    if budget <= 0 or not commits:
        return []
    ordered = sorted(commits, key=lambda c: (c.author_time, c.sha))
    bins = max(1, min(len(ordered), budget // 3 or 1))
    size = math.ceil(len(ordered) / bins)
    picked: dict[str, str] = {}

    def add(c: Commit | None, reason: str) -> None:
        if c is not None and c.sha not in picked and len(picked) < budget:
            picked[c.sha] = reason

    def changed(c: Commit) -> int:
        return c.added(included_paths)

    for b in range(bins):
        chunk = ordered[b * size : (b + 1) * size]
        if not chunk:
            continue
        phase = "early" if b == 0 else ("recent" if b == bins - 1 else "middle")
        add(
            max(chunk, key=lambda c: (changed(c), c.sha)),
            f"{phase} history: largest change",
        )
        add(
            max(
                (c for c in chunk if _FIX.search(c.subject)),
                key=lambda c: (changed(c), c.sha),
                default=None,
            ),
            f"{phase} history: fix / regression",
        )
        add(
            max(
                (c for c in chunk if _REFACTOR.search(c.subject)),
                key=lambda c: (changed(c), c.sha),
                default=None,
            ),
            f"{phase} history: refactor / redesign",
        )
    for c in [c for c in ordered if _REVERT.search(c.subject)][:2]:
        add(c, "revert: rejected or rolled-back approach")
    for c in sorted(ordered, key=lambda c: (-changed(c), c.sha)):
        add(c, "large candidate change")
    items = []
    for n, (sha, reason) in enumerate(
        sorted(
            picked.items(),
            key=lambda kv: next(c.author_time for c in ordered if c.sha == kv[0]),
        ),
        start=start_index,
    ):
        commit = next(c for c in ordered if c.sha == sha)
        items.append(
            {
                "id": f"S-{repo_id}-{n:03d}",
                "kind": "commit",
                "commit": sha,
                "subject": commit.subject[:200],
                "read_budget": max(
                    1,
                    min(
                        read_lines,
                        sum(max(a, 0) + max(d, 0) for _, a, d in commit.files) + 10,
                    ),
                ),
                "reasons": [reason],
            }
        )
    return items
