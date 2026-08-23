#!/usr/bin/env python3
"""Report static package conformance without claiming live effectiveness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


import yaml  # noqa: E402

from scripts.frontmatter import extract_version, parse_frontmatter, validate_version  # noqa: E402
from scripts.package_types import REPO_ROOT, TYPES, PackageType, detect_type_from_path  # noqa: E402

REPORT_VERSION = 2
EFFECTIVENESS_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "skill": ("routing", "task outcome"),
    "agent": ("routing", "task outcome"),
    "hook": ("event handling", "observable side effect"),
    "rule": ("routing", "constraint adherence"),
    "command": ("command invocation", "task outcome"),
    "utility": ("utility invocation", "task outcome"),
    "preset": ("preset loading", "configuration effect"),
}


def _is_kebab_case(name: str) -> bool:
    """Return whether a package directory name has the required format."""
    return all(
        part and part.replace("-", "").isalnum() and part == part.lower()
        for part in name.split("-")
    )


def _finding(severity: str, message: str) -> dict[str, str]:
    """Create a machine-readable conformance finding."""
    return {"severity": severity, "message": message}


def evaluate_package(pkg_dir: Path, pkg_type: PackageType) -> dict[str, object]:
    """Report type-specific static conformance for one package.

    Static checks establish installable package integrity only. They do not
    estimate activation quality or instruction effectiveness; those are
    measured by ``scripts.run_evals`` against declared cases.
    """
    name = pkg_dir.name
    definition = pkg_dir / pkg_type.definition_file
    findings: list[dict[str, str]] = []
    requirements = [
        "definition file",
        "valid YAML frontmatter",
        "type-required frontmatter",
        "matching package name",
        "kebab-case package directory",
    ]
    meta: dict[str, object] | None = None

    if not definition.exists():
        findings.append(
            _finding("CRITICAL", f"Missing definition file {pkg_type.definition_file}")
        )
    else:
        try:
            parsed = parse_frontmatter(definition.read_text(encoding="utf-8"))
        except (ValueError, yaml.YAMLError) as exc:
            findings.append(_finding("CRITICAL", f"Invalid YAML frontmatter: {exc}"))
        else:
            if isinstance(parsed, dict):
                meta = parsed
            else:
                findings.append(_finding("CRITICAL", "Frontmatter must be a mapping"))

    if meta is not None:
        for field in pkg_type.required_frontmatter:
            if not meta.get(field):
                findings.append(
                    _finding("CRITICAL", f"Missing required frontmatter field: {field}")
                )

        frontmatter_name = str(meta.get("name", ""))
        if frontmatter_name != name:
            findings.append(
                _finding(
                    "CRITICAL",
                    f"Frontmatter name '{frontmatter_name}' does not match directory '{name}'",
                )
            )

        version = extract_version(meta)
        if version and not validate_version(version):
            findings.append(_finding("CRITICAL", f"Invalid package version: {version}"))

    if not _is_kebab_case(name):
        findings.append(
            _finding("CRITICAL", f"Package directory '{name}' is not kebab-case")
        )

    status = "FAIL" if findings else "PASS"
    return {
        "report_version": REPORT_VERSION,
        "name": name,
        "type": pkg_type.key,
        "static_conformance": {
            "status": status,
            "requirements": requirements,
            "findings": findings,
        },
        "live_effectiveness": {
            "status": "NOT_MEASURED",
            "runner": "scripts/run_evals.py",
            "dimensions": list(EFFECTIVENESS_DIMENSIONS[pkg_type.key]),
        },
        "status": status,
        "findings": findings,
    }


def _package_directories() -> list[tuple[Path, PackageType]]:
    """Return every active package definition with its type contract."""
    packages: list[tuple[Path, PackageType]] = []
    for pkg_type in TYPES.values():
        if not pkg_type.repo_dir.exists():
            continue
        for pkg_dir in sorted(pkg_type.repo_dir.iterdir()):
            if not pkg_dir.is_dir() or pkg_dir.name.startswith("."):
                continue
            if (pkg_dir / pkg_type.definition_file).exists():
                packages.append((pkg_dir, pkg_type))
    return packages


def evaluate_all() -> list[dict[str, object]]:
    """Report static conformance for every active package."""
    return [
        evaluate_package(pkg_dir, pkg_type)
        for pkg_dir, pkg_type in _package_directories()
    ]


def evaluate_single(path: str) -> list[dict[str, object]]:
    """Report static conformance for a single package path."""
    pkg_dir = Path(path).resolve()
    if not pkg_dir.is_dir():
        pkg_dir = REPO_ROOT / path
    if not pkg_dir.is_dir():
        msg = f"Error: path '{path}' is not a valid directory"
        raise ValueError(msg)
    return [evaluate_package(pkg_dir, detect_type_from_path(pkg_dir))]


def print_text(results: list[dict[str, object]]) -> None:
    """Print static conformance and live-effectiveness status distinctly."""
    for result in results:
        conformance = cast(dict[str, object], result["static_conformance"])
        effectiveness = cast(dict[str, object], result["live_effectiveness"])
        dimensions = cast(list[str], effectiveness["dimensions"])
        findings = cast(list[dict[str, str]], conformance["findings"])
        print(f"Package: {result['name']} ({result['type']})")
        print(f"  Static conformance: {conformance['status']}")
        print(f"  Live effectiveness: {effectiveness['status']}")
        print(f"  Effectiveness dimensions: {', '.join(dimensions)}")
        for finding in findings:
            print(f"    [{finding['severity']}] {finding['message']}")
        print()

    passed = sum(1 for result in results if result["status"] == "PASS")
    print(
        f"Summary: {len(results)} packages evaluated, {passed} conformant, {len(results) - passed} failed"
    )


def main() -> int:
    """Run the static conformance report."""
    parser = argparse.ArgumentParser(description="Report static package conformance")
    parser.add_argument("--path", type=str, help="Evaluate a single package by path")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output JSON instead of text",
    )
    args = parser.parse_args()

    try:
        results = evaluate_single(args.path) if args.path else evaluate_all()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(results, indent=2))
    else:
        print_text(results)

    return 1 if any(result["status"] == "FAIL" for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
