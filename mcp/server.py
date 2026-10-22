#!/usr/bin/env python3
"""MCP server for armory package discovery.

Exposes 4 tools via Model Context Protocol (stdio transport):
  - search_packages: weighted search across all packages
  - get_package: retrieve full metadata for a single package
  - recommend_packages: context-aware package recommendations
  - list_categories: category names with package counts

Run from repo root:
    python mcp/server.py
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Import FastMCP from the installed mcp SDK.
#
# This file lives at mcp/server.py which shadows `mcp.server` from the
# installed package. We resolve this by loading the installed package's
# server subpackage directly from its file path.
# ---------------------------------------------------------------------------

_this_dir = Path(__file__).resolve().parent
_repo_root = _this_dir.parent
# Appended, not prepended: the repository's own mcp/ package must not shadow
# the installed SDK any further than the loader below already handles.
if str(_repo_root) not in sys.path:
    sys.path.append(str(_repo_root))

from scripts.package_types import TYPES


def _import_fastmcp() -> type:
    """Import FastMCP from the installed mcp SDK, bypassing local shadow."""
    for entry in sys.path:
        candidate = Path(entry).resolve() / "mcp"
        if str(candidate) == str(_this_dir):
            continue
        fastmcp_init = candidate / "server" / "fastmcp" / "__init__.py"
        if fastmcp_init.exists():
            spec = importlib.util.spec_from_file_location(
                "mcp.server.fastmcp",
                str(fastmcp_init),
                submodule_search_locations=[str(candidate / "server" / "fastmcp")],
            )
            if spec is None or spec.loader is None:
                continue
            # Ensure mcp.server is importable first (needed by fastmcp internals).
            server_init = candidate / "server" / "__init__.py"
            if server_init.exists():
                server_spec = importlib.util.spec_from_file_location(
                    "mcp.server",
                    str(server_init),
                    submodule_search_locations=[str(candidate / "server")],
                )
                if server_spec and server_spec.loader:
                    server_mod = importlib.util.module_from_spec(server_spec)
                    sys.modules["mcp.server"] = server_mod
                    server_spec.loader.exec_module(server_mod)

            mod = importlib.util.module_from_spec(spec)
            sys.modules["mcp.server.fastmcp"] = mod
            spec.loader.exec_module(mod)
            return mod.FastMCP  # type: ignore[attr-defined]

    msg = "Could not find installed mcp SDK with FastMCP"
    raise ImportError(msg)


FastMCP = _import_fastmcp()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_PATH = _repo_root / "manifest.yaml"

SECTION_TYPES: dict[str, str] = {t.manifest_section: t.key for t in TYPES.values()}

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_packages: list[dict[str, str | list[str]]] = []


def _load_packages() -> list[dict[str, str | list[str]]]:
    """Load all packages from manifest.yaml, tagging each with its type."""
    with open(MANIFEST_PATH) as f:
        data = yaml.safe_load(f)

    packages_section: dict[str, list[dict[str, str | list[str]]]] = data.get("packages", {})
    results: list[dict[str, str | list[str]]] = []

    for section, pkg_type in SECTION_TYPES.items():
        for entry in packages_section.get(section, []) or []:
            entry["type"] = pkg_type
            results.append(entry)

    return results


def _get_packages() -> list[dict[str, str | list[str]]]:
    """Return cached package list, loading on first access."""
    global _packages  # noqa: PLW0603
    if not _packages:
        _packages = _load_packages()
    return _packages


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _tags_list(pkg: dict[str, str | list[str]]) -> list[str]:
    """Normalize tags field to a list of lowercase strings."""
    tags = pkg.get("tags", []) or []
    if isinstance(tags, str):
        tags = [tags]
    return [str(t).lower() for t in tags]


def _score_package(pkg: dict[str, str | list[str]], query: str) -> int:
    """Score a package against a search query using weighted matching."""
    q = query.lower()
    total = 0

    name = str(pkg.get("name", "")).lower()
    if name == q:
        total += 10
    elif q in name or name in q:
        total += 1

    for tag in _tags_list(pkg):
        if tag == q:
            total += 5
            break

    category = str(pkg.get("category", "")).lower()
    if category == q:
        total += 4

    description = str(pkg.get("description", "")).lower()
    if q in description:
        total += 2

    return total


def _filter_packages(
    packages: list[dict[str, str | list[str]]],
    *,
    pkg_type: str | None = None,
    category: str | None = None,
    tag: str | None = None,
) -> list[dict[str, str | list[str]]]:
    """Apply type/category/tag filters."""
    results = packages
    if pkg_type:
        t = pkg_type.lower()
        results = [p for p in results if str(p.get("type", "")).lower() == t]
    if category:
        cat = category.lower()
        results = [p for p in results if str(p.get("category", "")).lower() == cat]
    if tag:
        tag_lower = tag.lower()
        results = [
            p for p in results if tag_lower in _tags_list(p)
        ]
    return results


def _package_summary(pkg: dict[str, str | list[str]]) -> dict[str, str | list[str] | int]:
    """Extract a clean metadata dict for JSON output."""
    return {
        "name": str(pkg.get("name", "")),
        "type": str(pkg.get("type", "")),
        "version": str(pkg.get("version", "")),
        "description": str(pkg.get("description", "")),
        "tags": _tags_list(pkg),
        "category": str(pkg.get("category", "")),
        "difficulty": str(pkg.get("difficulty", "")),
        "path": str(pkg.get("path", "")),
        "source": str(pkg.get("source", "")),
    }


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp_server = FastMCP(
    "armory",
    instructions=(
        "Armory package discovery server. Search, browse, and get recommendations "
        "for Claude Code skills, agents, hooks, rules, commands, utilities, and presets, "
        "plus optional native OMP/Claude Code extensions (installed only explicitly)."
    ),
)


@mcp_server.tool(
    name="search_packages",
    description=(
        "Search armory packages by keyword with optional type, category, and tag filters. "
        "Returns scored results sorted by relevance."
    ),
)
def search_packages(
    query: str,
    type: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    limit: int = 10,
) -> str:
    """Search packages using weighted scoring."""
    packages = _filter_packages(
        _get_packages(),
        pkg_type=type,
        category=category,
        tag=tag,
    )

    scored: list[tuple[int, str, dict[str, str | list[str]]]] = []
    for pkg in packages:
        s = _score_package(pkg, query)
        if s > 0:
            scored.append((s, str(pkg.get("name", "")), pkg))

    scored.sort(key=lambda x: (-x[0], x[1]))
    scored = scored[:limit]

    results = [
        {**_package_summary(pkg), "score": s}
        for s, _, pkg in scored
    ]
    return json.dumps(results, indent=2)


@mcp_server.tool(
    name="get_package",
    description="Get full metadata for a single package by exact name.",
)
def get_package(name: str) -> str:
    """Return full metadata for a package, or an error if not found."""
    name_lower = name.lower()
    for pkg in _get_packages():
        if str(pkg.get("name", "")).lower() == name_lower:
            return json.dumps(_package_summary(pkg), indent=2)
    return json.dumps({"error": f"Package '{name}' not found"})


@mcp_server.tool(
    name="recommend_packages",
    description=(
        "Get package recommendations based on languages, frameworks, or task description. "
        "Scores packages by relevance to the provided context and returns the top 10."
    ),
)
def recommend_packages(
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    task: str | None = None,
) -> str:
    """Recommend packages based on development context."""
    packages = _get_packages()
    scores: dict[str, int] = {}
    pkg_map: dict[str, dict[str, str | list[str]]] = {}

    for pkg in packages:
        pkg_name = str(pkg.get("name", ""))
        pkg_map[pkg_name] = pkg
        total = 0

        tags = _tags_list(pkg)
        description = str(pkg.get("description", "")).lower()

        if languages:
            for lang in languages:
                lang_lower = lang.lower()
                if lang_lower in tags:
                    total += 5
                if lang_lower in description:
                    total += 2

        if frameworks:
            for fw in frameworks:
                fw_lower = fw.lower()
                if fw_lower in tags:
                    total += 5
                if fw_lower in description:
                    total += 2

        if task:
            total += _score_package(pkg, task)

        if total > 0:
            scores[pkg_name] = total

    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:10]
    results = [
        {**_package_summary(pkg_map[name]), "score": score}
        for name, score in ranked
    ]
    return json.dumps(results, indent=2)


@mcp_server.tool(
    name="list_categories",
    description="List all package categories with their package counts.",
)
def list_categories() -> str:
    """Return a JSON object mapping category names to package counts."""
    counts: Counter[str] = Counter()
    for pkg in _get_packages():
        cat = str(pkg.get("category", "")).strip()
        if cat:
            counts[cat] += 1
    return json.dumps(dict(sorted(counts.items())), indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp_server.run(transport="stdio")
