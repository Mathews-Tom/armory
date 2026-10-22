#!/usr/bin/env python3
"""Validate that file references in package definition bodies exist on disk."""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.frontmatter import extract_body
from scripts.package_types import TYPES, PackageType

# Matches references/ and assets/ paths (directories packages actually ship)
_REF_PATTERN = re.compile(r"(?:references|assets)/[a-zA-Z0-9_.-]+")
# Matches ../ followed by a known package directory pattern (actual cross-package refs)
_CROSS_PKG_PATTERN = re.compile(
    r"\.\./(?:" + "|".join(re.escape(t.dir_name) for t in TYPES.values()) + r")/"
)


def _strip_code_blocks(body: str) -> str:
    """Remove fenced code blocks to avoid false positives from examples."""
    return re.sub(r"```[\s\S]*?```", "", body)


def extract_references(body: str) -> list[str]:
    """Extract file references from definition body, excluding code blocks."""
    cleaned = _strip_code_blocks(body)
    return _REF_PATTERN.findall(cleaned)


def validate_pkg_references(pkg_dir: Path, pkg_type: PackageType) -> list[str]:
    """Validate file references for a single package."""
    definition = pkg_dir / pkg_type.definition_file
    if not definition.exists():
        return []

    pkg_name = pkg_dir.name
    errors: list[str] = []

    text = definition.read_text(encoding="utf-8")
    body = extract_body(text)

    # Check for cross-package references (../skills/, ../agents/, etc.)
    if _CROSS_PKG_PATTERN.search(body):
        errors.append(f"{pkg_name}: cross-package reference violates self-containment")

    # Validate each reference exists on disk
    refs = extract_references(body)
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        target = pkg_dir / ref
        if not target.exists():
            errors.append(f"{pkg_name}: {ref} not found")

    return errors


def main() -> int:
    """Validate all file references across package types."""
    all_errors: list[str] = []
    total = 0

    for pkg_type in TYPES.values():
        type_dir = pkg_type.repo_dir
        if not type_dir.exists():
            continue

        for pkg_dir in sorted(type_dir.iterdir()):
            if not pkg_dir.is_dir():
                continue
            definition = pkg_dir / pkg_type.definition_file
            if not definition.exists():
                continue

            errors = validate_pkg_references(pkg_dir, pkg_type)
            all_errors.extend(errors)
            total += 1

    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s):", file=sys.stderr)
        for error in all_errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"Validated {total} packages — all references intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
