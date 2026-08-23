#!/usr/bin/env python3
"""Validate eval cases.yaml files across all package types."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml  # noqa: E402

from scripts.frontmatter import parse_frontmatter  # noqa: E402
from scripts.package_types import TYPES, PackageType  # noqa: E402

REQUIRED_CASE_FIELDS = {"id", "prompt", "rubric", "trigger_expected"}
OPTIONAL_CASE_FIELDS = {"fixtures", "assertions", "oracle_verdict", "diagnostics"}
VALID_ASSERTION_TYPES = {
    "contains",
    "not_contains",
    "matches_regex",
    "output_format",
    "calls_tool",
}
VALID_ORACLE_VERDICTS = {None, "pass", "fail"}


def is_deprecated(pkg_dir: Path, pkg_type: PackageType) -> bool:
    """Check if a package is deprecated by reading its definition file frontmatter."""
    definition = pkg_dir / pkg_type.definition_file
    if not definition.exists():
        return False
    try:
        text = definition.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)
        return (
            isinstance(meta, dict)
            and meta.get("metadata", {}).get("status") == "deprecated"
        )
    except (ValueError, yaml.YAMLError):
        return False


def validate_case(case: dict, pkg_name: str, idx: int) -> list[str]:
    """Validate a single eval case and return errors."""
    errors: list[str] = []
    prefix = f"{pkg_name} case #{idx}"

    missing = REQUIRED_CASE_FIELDS - set(case.keys())
    if missing:
        errors.append(f"{prefix}: missing required fields: {missing}")
        return errors

    if not isinstance(case["id"], str) or not case["id"]:
        errors.append(f"{prefix}: 'id' must be a non-empty string")

    if not isinstance(case["prompt"], str) or not case["prompt"].strip():
        errors.append(f"{prefix}: 'prompt' must be a non-empty string")

    if not isinstance(case["trigger_expected"], bool):
        errors.append(f"{prefix}: 'trigger_expected' must be a boolean")

    if not isinstance(case["rubric"], list) or len(case["rubric"]) == 0:
        errors.append(f"{prefix}: 'rubric' must be a non-empty list")

    # Validate optional assertions field (EvoSkills structured assertions)
    if "assertions" in case:
        assertions = case["assertions"]
        if not isinstance(assertions, list):
            errors.append(f"{prefix}: 'assertions' must be a list")
        else:
            for j, assertion in enumerate(assertions, 1):
                a_prefix = f"{prefix} assertion #{j}"
                if not isinstance(assertion, dict):
                    errors.append(f"{a_prefix}: must be a dict")
                    continue
                if "type" not in assertion:
                    errors.append(f"{a_prefix}: missing required 'type' field")
                elif assertion["type"] not in VALID_ASSERTION_TYPES:
                    errors.append(
                        f"{a_prefix}: invalid type '{assertion['type']}', "
                        f"must be one of {sorted(VALID_ASSERTION_TYPES)}"
                    )
                if "target" not in assertion:
                    errors.append(f"{a_prefix}: missing required 'target' field")
                elif not isinstance(assertion["target"], str):
                    errors.append(f"{a_prefix}: 'target' must be a string")
                if "weight" in assertion:
                    weight = assertion["weight"]
                    if not isinstance(weight, (int, float)) or weight < 0 or weight > 1:
                        errors.append(
                            f"{a_prefix}: 'weight' must be a number between 0 and 1"
                        )

    # Validate optional oracle_verdict field
    if "oracle_verdict" in case:
        verdict = case["oracle_verdict"]
        if verdict not in VALID_ORACLE_VERDICTS:
            errors.append(
                f"{prefix}: 'oracle_verdict' must be null, 'pass', or 'fail', "
                f"got '{verdict}'"
            )

    # Validate optional diagnostics field
    if "diagnostics" in case:
        diag = case["diagnostics"]
        if diag is not None and not isinstance(diag, str):
            errors.append(f"{prefix}: 'diagnostics' must be null or a string")

    return errors


def validate_pkg_evals(pkg_dir: Path, pkg_type: PackageType) -> list[str]:
    """Validate evals/cases.yaml for a single package."""
    cases_file = pkg_dir / "evals" / "cases.yaml"
    if not cases_file.exists():
        if is_deprecated(pkg_dir, pkg_type):
            return []
        return [f"{pkg_dir.name}: missing required evals/cases.yaml"]

    pkg_name = pkg_dir.name
    deprecated = is_deprecated(pkg_dir, pkg_type)
    errors: list[str] = []

    try:
        data = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return [f"{pkg_name}: invalid YAML in cases.yaml: {e}"]

    if not isinstance(data, dict) or "cases" not in data:
        return [f"{pkg_name}: cases.yaml must have a top-level 'cases' key"]

    cases = data["cases"]
    if not isinstance(cases, list) or len(cases) == 0:
        return [f"{pkg_name}: 'cases' must be a non-empty list"]

    ids: set[str] = set()
    positive_count = 0
    negative_count = 0

    for i, case in enumerate(cases, 1):
        errors.extend(validate_case(case, pkg_name, i))

        case_id = case.get("id", "")
        if case_id in ids:
            errors.append(f"{pkg_name} case #{i}: duplicate id '{case_id}'")
        ids.add(case_id)

        if case.get("trigger_expected") is True:
            positive_count += 1
        elif case.get("trigger_expected") is False:
            negative_count += 1

    if deprecated:
        if positive_count > 0:
            errors.append(
                f"{pkg_name}: deprecated {pkg_type.key} must have 0 positive cases, found {positive_count}"
            )
    else:
        if positive_count == 0:
            errors.append(
                f"{pkg_name}: must have at least 1 positive case (trigger_expected: true)"
            )

    if negative_count < 2:
        errors.append(
            f"{pkg_name}: must have at least 2 negative cases (trigger_expected: false), found {negative_count}"
        )

    return errors


def main() -> int:
    """Validate all eval cases across package types."""
    all_errors: list[str] = []
    counts: dict[str, int] = {}

    for pkg_type in TYPES.values():
        type_dir = pkg_type.repo_dir
        if not type_dir.exists():
            continue

        validated = 0
        for pkg_dir in sorted(type_dir.iterdir()):
            if not pkg_dir.is_dir():
                continue
            if is_deprecated(pkg_dir, pkg_type):
                continue

            errors = validate_pkg_evals(pkg_dir, pkg_type)
            all_errors.extend(errors)
            validated += 1

        if validated > 0:
            counts[pkg_type.manifest_section] = validated

    total = sum(counts.values())

    if all_errors:
        print(
            f"FAILED: {len(all_errors)} error(s) in {total} eval file(s):",
            file=sys.stderr,
        )
        for error in all_errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    parts = [f"{count} {label}" for label, count in counts.items()]
    summary = ", ".join(parts) if parts else "0 packages"
    print(f"Validated {summary} — all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
