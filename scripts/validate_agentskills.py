#!/usr/bin/env python3
"""Validate skill packages against the agentskills.io open standard."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.frontmatter import parse_frontmatter
from scripts.package_types import REPO_ROOT, TYPES

# agentskills.io spec: exactly these 6 top-level frontmatter fields are allowed.
ALLOWED_FIELDS: frozenset[str] = frozenset({
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
})

REQUIRED_FIELDS: frozenset[str] = frozenset({"name", "description"})

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
COMPATIBILITY_MAX_LENGTH = 500


def validate_skill(pkg_dir: Path) -> tuple[list[str], list[str]]:
    """Validate a single skill against agentskills.io spec.

    Returns (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []
    pkg_name = pkg_dir.name

    definition = pkg_dir / "SKILL.md"
    if not definition.exists():
        errors.append(f"{pkg_name}: missing SKILL.md")
        return errors, warnings

    try:
        text = definition.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)
    except (OSError, ValueError) as exc:
        errors.append(f"{pkg_name}: failed to parse frontmatter: {exc}")
        return errors, warnings

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in meta:
            errors.append(f"{pkg_name}: missing required field '{field}'")

    # Name validation
    name_val = meta.get("name")
    if isinstance(name_val, str):
        if len(name_val) > NAME_MAX_LENGTH:
            errors.append(
                f"{pkg_name}: name exceeds {NAME_MAX_LENGTH} chars ({len(name_val)})"
            )
        if not NAME_PATTERN.match(name_val):
            errors.append(
                f"{pkg_name}: name must be lowercase alphanumeric + hyphens, got '{name_val}'"
            )
        if name_val != pkg_name:
            errors.append(
                f"{pkg_name}: name '{name_val}' does not match directory name '{pkg_name}'"
            )

    # Description validation
    desc_val = meta.get("description")
    if isinstance(desc_val, str) and len(desc_val) > DESCRIPTION_MAX_LENGTH:
        errors.append(
            f"{pkg_name}: description exceeds {DESCRIPTION_MAX_LENGTH} chars ({len(desc_val)})"
        )

    # Compatibility length
    compat_val = meta.get("compatibility")
    if isinstance(compat_val, str) and len(compat_val) > COMPATIBILITY_MAX_LENGTH:
        errors.append(
            f"{pkg_name}: compatibility exceeds {COMPATIBILITY_MAX_LENGTH} chars ({len(compat_val)})"
        )

    # Extra fields (Claude Code-specific, not in agentskills.io spec)
    extra = set(meta.keys()) - ALLOWED_FIELDS
    if extra:
        warnings.append(
            f"{pkg_name}: extra fields not in agentskills.io spec: {sorted(extra)}"
        )

    # License recommendation
    if "license" not in meta:
        warnings.append(f"{pkg_name}: 'license' is recommended by the spec")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate skill packages against the agentskills.io open standard."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat extra (non-spec) fields as errors instead of warnings.",
    )
    args = parser.parse_args()

    skill_type = TYPES["skill"]
    skills_dir = skill_type.repo_dir

    if not skills_dir.exists():
        print("No skills/ directory found.", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    all_warnings: list[str] = []
    checked = 0

    for pkg_dir in sorted(skills_dir.iterdir()):
        if not pkg_dir.is_dir():
            continue
        definition = pkg_dir / skill_type.definition_file
        if not definition.exists():
            continue

        errors, warnings = validate_skill(pkg_dir)

        if args.strict:
            # Promote extra-field warnings to errors
            promoted = [w for w in warnings if "extra fields" in w]
            remaining = [w for w in warnings if "extra fields" not in w]
            errors.extend(promoted)
            warnings = remaining

        all_errors.extend(errors)
        all_warnings.extend(warnings)
        checked += 1

    # Summary
    error_count = len(all_errors)
    warning_count = len(all_warnings)
    compliant = checked - len({e.split(":")[0] for e in all_errors})
    warned = len({w.split(":")[0] for w in all_warnings})

    print(f"Checked {checked} skills against agentskills.io spec")
    print(f"  Compliant: {compliant}")
    print(f"  Warnings:  {warned} skill(s)")
    print(f"  Errors:    {error_count}")

    if all_warnings:
        print("\nWarnings:", file=sys.stderr)
        for w in all_warnings:
            print(f"  {w}", file=sys.stderr)

    if all_errors:
        print("\nErrors:", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
