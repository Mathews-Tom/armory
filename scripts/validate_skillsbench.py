#!/usr/bin/env python3
"""Validate the frozen SkillsBench package strata declaration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml  # type: ignore[import-untyped]  # noqa: E402

from scripts.install import discover_packages  # noqa: E402
from scripts.package_types import TYPES  # noqa: E402
from scripts.validate_evals import is_deprecated  # noqa: E402

_DEFAULT_STRATA_PATH = _REPO_ROOT / "evals" / "skillsbench" / "package_strata.yaml"


def _mapping(value: object, location: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{location}: expected a mapping")
    return cast(dict[str, object], value)


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{location}: expected a non-empty string")
    return value


def _entries(value: object, location: str) -> set[tuple[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"{location}: expected a list")
    entries: set[tuple[str, str]] = set()
    for index, raw in enumerate(value):
        entry = _mapping(raw, f"{location}[{index}]")
        package_type = _string(
            entry.get("package_type"), f"{location}[{index}].package_type"
        )
        name = _string(entry.get("name"), f"{location}[{index}].name")
        _string(entry.get("rationale"), f"{location}[{index}].rationale")
        key = (package_type, name)
        if key in entries:
            raise ValueError(f"{location}: duplicate package classification {key}")
        entries.add(key)
    return entries


def validate_strata(path: Path = _DEFAULT_STRATA_PATH) -> tuple[int, int]:
    """Require every discovered package to have one explicit classification."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{path}: cannot read package strata: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: cannot parse package strata YAML: {exc}") from exc
    document = _mapping(raw, str(path))
    if document.get("schema_version") != 1:
        raise ValueError(f"{path}: schema_version must be 1")

    included = _entries(document.get("included"), f"{path}.included")
    excluded = _entries(document.get("excluded"), f"{path}.excluded")
    if included & excluded:
        raise ValueError(f"{path}: a package cannot be both included and excluded")

    packages = discover_packages()
    expected = {(package.pkg_type.key, package.name) for package in packages}
    observed = included | excluded
    if observed != expected:
        missing = sorted(expected - observed)
        undeclared = sorted(observed - expected)
        raise ValueError(
            f"{path}: classifications differ from inventory; missing={missing}, undeclared={undeclared}"
        )
    if {package_type for package_type, _ in included} != set(TYPES):
        raise ValueError(f"{path}: included sample must cover every package type")
    if len(included) != len(TYPES):
        raise ValueError(
            f"{path}: included sample must contain exactly one package per type"
        )

    by_key = {(package.pkg_type.key, package.name): package for package in packages}
    for key in included:
        package = by_key[key]
        if is_deprecated(package.source_path, package.pkg_type):
            raise ValueError(f"{path}: included package {key} is deprecated")
    return len(included), len(excluded)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strata", type=Path, default=_DEFAULT_STRATA_PATH)
    args = parser.parse_args()
    try:
        included, excluded = validate_strata(args.strata)
    except ValueError as exc:
        print(f"SkillsBench strata validation failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"Validated {included} included and {excluded} excluded package classifications"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
