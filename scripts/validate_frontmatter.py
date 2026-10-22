#!/usr/bin/env python3
"""Validate type-specific frontmatter fields across all packages."""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from scripts.extension_metadata import ExtensionMetadataError, parse_extension_metadata
from scripts.frontmatter import extract_version, parse_frontmatter, validate_version
from scripts.package_types import TYPES, PackageType

VALID_MODELS = {"opus", "sonnet", "haiku"}
NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def validate_name(meta: dict, pkg_dir_name: str, prefix: str) -> list[str]:
    """Validate the name field matches directory name, kebab-case, max 64 chars."""
    errors: list[str] = []
    name = meta.get("name", "")
    if not isinstance(name, str) or not name:
        errors.append(f"{prefix}: name must be a non-empty string")
        return errors
    if name != pkg_dir_name:
        errors.append(f"{prefix}: name '{name}' does not match directory name '{pkg_dir_name}'")
    if not NAME_PATTERN.match(name):
        errors.append(f"{prefix}: name '{name}' must be kebab-case")
    if len(name) > 64:
        errors.append(f"{prefix}: name exceeds 64 characters ({len(name)})")
    return errors


def validate_description(meta: dict, prefix: str) -> list[str]:
    """Validate description is a non-empty string between 50 and 1024 characters."""
    errors: list[str] = []
    desc = meta.get("description", "")
    if not isinstance(desc, str) or not desc:
        errors.append(f"{prefix}: description must be a non-empty string")
        return errors
    if len(desc) < 50:
        errors.append(f"{prefix}: description too short ({len(desc)} chars, minimum 50)")
    if len(desc) > 1024:
        errors.append(f"{prefix}: description too long ({len(desc)} chars, maximum 1024)")
    return errors


def validate_agent(meta: dict, prefix: str) -> list[str]:
    """Validate agent-specific fields."""
    errors: list[str] = []
    model = meta.get("model", "")
    if model not in VALID_MODELS:
        errors.append(f"{prefix}: model must be opus, sonnet, or haiku, got '{model}'")
    color = meta.get("color", "")
    if not isinstance(color, str) or not color:
        errors.append(f"{prefix}: color must be a non-empty string")
    return errors


def validate_hook(meta: dict, prefix: str) -> list[str]:
    """Validate hook-specific fields."""
    errors: list[str] = []
    hook = meta.get("hook")
    if not isinstance(hook, dict):
        errors.append(f"{prefix}: hook must be a dict")
        return errors
    events = hook.get("events")
    if not isinstance(events, list) or len(events) == 0:
        errors.append(f"{prefix}: hook.events must be a non-empty list")
    handler = hook.get("handler")
    if not isinstance(handler, dict):
        errors.append(f"{prefix}: hook.handler must be a dict")
    else:
        if not handler.get("type"):
            errors.append(f"{prefix}: hook.handler.type is required")
        if not handler.get("command"):
            errors.append(f"{prefix}: hook.handler.command is required")
    return errors


def validate_command(meta: dict, prefix: str) -> list[str]:
    """Validate command-specific fields."""
    command = meta.get("command")
    if not isinstance(command, dict):
        return [f"{prefix}: command must be a dict"]
    return []


def validate_utility(meta: dict, prefix: str) -> list[str]:
    """Validate utility-specific fields."""
    errors: list[str] = []
    utility = meta.get("utility")
    if not isinstance(utility, dict):
        errors.append(f"{prefix}: utility must be a dict")
        return errors
    runtime = utility.get("runtime", "")
    if not isinstance(runtime, str) or not runtime:
        errors.append(f"{prefix}: utility.runtime must be a non-empty string")
    return errors


def validate_preset(meta: dict, prefix: str) -> list[str]:
    """Validate preset-specific fields."""
    errors: list[str] = []
    preset = meta.get("preset")
    if not isinstance(preset, dict):
        errors.append(f"{prefix}: preset must be a dict")
        return errors
    packages = preset.get("packages")
    if isinstance(packages, dict):
        # Dict form: {skills: [...], hooks: [...], ...}
        if not any(packages.values()):
            errors.append(f"{prefix}: preset.packages must contain at least one package")
    elif isinstance(packages, list):
        if len(packages) == 0:
            errors.append(f"{prefix}: preset.packages must be a non-empty list")
    else:
        errors.append(f"{prefix}: preset.packages must be a list or dict")
    return errors


def validate_extension(meta: dict[str, object], prefix: str) -> list[str]:
    """Validate native extension metadata (hosts, entrypoints, commands, storage, permissions)."""
    try:
        parse_extension_metadata(meta)
    except ExtensionMetadataError as exc:
        return [f"{prefix}: {exc}"]
    return []


_TYPE_VALIDATORS = {
    "agent": validate_agent,
    "hook": validate_hook,
    "command": validate_command,
    "utility": validate_utility,
    "preset": validate_preset,
    "extension": validate_extension,
}


def validate_package(pkg_dir: Path, pkg_type: PackageType) -> list[str]:
    """Validate frontmatter for a single package."""
    definition = pkg_dir / pkg_type.definition_file
    if not definition.exists():
        return []

    prefix = f"{pkg_type.key}/{pkg_dir.name}"
    errors: list[str] = []

    try:
        text = definition.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)
    except ValueError as e:
        return [f"{prefix}: invalid frontmatter: {e}"]

    # Required fields presence check
    for field in pkg_type.required_frontmatter:
        val = meta.get(field)
        if val is None or (isinstance(val, str) and not val):
            errors.append(f"{prefix}: required field '{field}' is missing or empty")

    # Name validation
    errors.extend(validate_name(meta, pkg_dir.name, prefix))

    # Version validation
    version = extract_version(meta)
    if not version:
        errors.append(f"{prefix}: version is missing")
    elif not validate_version(version):
        errors.append(f"{prefix}: version '{version}' is not valid semver (X.Y.Z)")

    # Description validation
    errors.extend(validate_description(meta, prefix))

    # Type-specific validation
    validator = _TYPE_VALIDATORS.get(pkg_type.key)
    if validator:
        errors.extend(validator(meta, prefix))

    return errors


def main() -> int:
    """Validate frontmatter across all package types."""
    all_errors: list[str] = []
    total = 0
    type_count = 0

    for pkg_type in TYPES.values():
        type_dir = pkg_type.repo_dir
        if not type_dir.exists():
            continue

        validated = 0
        for pkg_dir in sorted(type_dir.iterdir()):
            if not pkg_dir.is_dir():
                continue
            definition = pkg_dir / pkg_type.definition_file
            if not definition.exists():
                continue

            errors = validate_package(pkg_dir, pkg_type)
            all_errors.extend(errors)
            validated += 1

        if validated > 0:
            total += validated
            type_count += 1

    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s):", file=sys.stderr)
        for error in all_errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"Validated {total} packages across {type_count} types — all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
