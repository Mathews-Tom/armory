#!/usr/bin/env python3
"""CLI search command for discovering armory packages from manifest.yaml."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse

import yaml
from rich.console import Console
from rich.table import Table

from scripts.package_types import MANIFEST_PATH, TYPES

SECTION_TYPES: dict[str, str] = {t.manifest_section: t.key for t in TYPES.values()}
DEFAULT_LIMIT = 20

console = Console()


def load_packages() -> list[dict[str, str | list[str]]]:
    """Load all packages from manifest.yaml, tagging each with its type."""
    with open(MANIFEST_PATH) as f:
        data = yaml.safe_load(f)

    packages_section = data.get("packages", {})
    results: list[dict[str, str | list[str]]] = []

    for section, pkg_type in SECTION_TYPES.items():
        for entry in packages_section.get(section, []) or []:
            entry["type"] = pkg_type
            results.append(entry)

    return results


def score_package(pkg: dict[str, str | list[str]], query: str) -> int:
    """Score a package against a search query."""
    q = query.lower()
    total = 0

    name = str(pkg.get("name", "")).lower()
    if name == q:
        total += 10
    elif q in name or name in q:
        total += 1

    tags = pkg.get("tags", []) or []
    if isinstance(tags, str):
        tags = [tags]
    for tag in tags:
        if str(tag).lower() == q:
            total += 5
            break

    category = str(pkg.get("category", "")).lower()
    if category == q:
        total += 4

    description = str(pkg.get("description", "")).lower()
    if q in description:
        total += 2

    return total


def filter_packages(
    packages: list[dict[str, str | list[str]]],
    *,
    pkg_type: str | None = None,
    category: str | None = None,
    tag: str | None = None,
) -> list[dict[str, str | list[str]]]:
    """Apply type/category/tag filters."""
    results = packages
    if pkg_type:
        results = [p for p in results if p.get("type") == pkg_type]
    if category:
        cat_lower = category.lower()
        results = [p for p in results if str(p.get("category", "")).lower() == cat_lower]
    if tag:
        tag_lower = tag.lower()
        filtered: list[dict[str, str | list[str]]] = []
        for p in results:
            tags = p.get("tags", []) or []
            if isinstance(tags, str):
                tags = [tags]
            if any(str(t).lower() == tag_lower for t in tags):
                filtered.append(p)
        results = filtered
    return results


def truncate(text: str, length: int = 60) -> str:
    """Truncate text to length, appending ellipsis if needed."""
    if len(text) <= length:
        return text
    return text[: length - 3] + "..."


def print_results(
    packages: list[dict[str, str | list[str]]],
    query: str,
    limit: int,
) -> int:
    """Score, sort, and print search results. Returns exit code."""
    scored: list[tuple[int, str, dict[str, str | list[str]]]] = []
    for pkg in packages:
        s = score_package(pkg, query)
        if s > 0:
            scored.append((s, str(pkg.get("name", "")), pkg))

    scored.sort(key=lambda x: (-x[0], x[1]))
    scored = scored[:limit]

    if not scored:
        console.print(f'No results for "{query}".', style="bold red")
        return 1

    console.print(
        f'\nSearch results for "{query}" ({len(scored)} matches):\n',
        style="bold",
    )

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Type", width=8)
    table.add_column("Name", width=24)
    table.add_column("Version", width=8)
    table.add_column("Category", width=14)
    table.add_column("Score", justify="right", width=5)
    table.add_column("Description", width=60)

    for i, (s, _, pkg) in enumerate(scored, 1):
        table.add_row(
            str(i),
            str(pkg.get("type", "")),
            str(pkg.get("name", "")),
            str(pkg.get("version", "")),
            str(pkg.get("category", "")),
            str(s),
            truncate(str(pkg.get("description", ""))),
        )

    console.print(table)
    return 0


def list_categories(packages: list[dict[str, str | list[str]]]) -> int:
    """Print all categories with counts."""
    counts: Counter[str] = Counter()
    for pkg in packages:
        cat = str(pkg.get("category", "")).strip()
        if cat:
            counts[cat] += 1

    if not counts:
        console.print("No categories found in manifest.", style="bold red")
        return 1

    console.print("\nCategories:", style="bold")
    for cat, count in sorted(counts.items()):
        console.print(f"  {cat:<20} ({count:>3} packages)")
    console.print()
    return 0


def list_tags(packages: list[dict[str, str | list[str]]]) -> int:
    """Print all tags with counts, sorted by count descending."""
    counts: Counter[str] = Counter()
    for pkg in packages:
        tags = pkg.get("tags", []) or []
        if isinstance(tags, str):
            tags = [tags]
        for tag in tags:
            t = str(tag).strip()
            if t:
                counts[t] += 1

    if not counts:
        console.print("No tags found in manifest.", style="bold red")
        return 1

    console.print("\nTags:", style="bold")
    for tag, count in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        console.print(f"  {tag:<20} ({count:>3} packages)")
    console.print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="armory-search",
        description="Search armory packages from manifest.yaml",
    )
    parser.add_argument("query", nargs="?", default=None, help="Search keyword")
    parser.add_argument("--type", dest="pkg_type", choices=list(TYPES.keys()), help="Filter by package type")
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--tag", help="Filter by tag")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max results (default: 20)")
    parser.add_argument("--list-categories", action="store_true", help="Show all categories with counts")
    parser.add_argument("--list-tags", action="store_true", help="Show all tags with counts")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    packages = load_packages()

    if args.list_categories:
        sys.exit(list_categories(packages))

    if args.list_tags:
        sys.exit(list_tags(packages))

    if not args.query:
        parser.error("a search query is required (or use --list-categories / --list-tags)")

    filtered = filter_packages(
        packages,
        pkg_type=args.pkg_type,
        category=args.category,
        tag=args.tag,
    )

    sys.exit(print_results(filtered, args.query, args.limit))


if __name__ == "__main__":
    main()
