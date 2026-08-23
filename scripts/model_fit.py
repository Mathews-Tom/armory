#!/usr/bin/env python3
"""Validate declared model-fit targets without making a model request.

A dry run resolves package definitions selected by a profile. It records only
installed discovery metadata, never package body content or a claim that a
package was injected into a turn.
"""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

_REPO_ROOT: Final = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml  # type: ignore[import-untyped]  # noqa: E402

from scripts.install import (
    PackageInfo,
    discover_packages,
    load_profiles,
    resolve_profile_packages,
)  # noqa: E402

DEFAULT_CONFIG_PATH: Final = _REPO_ROOT / "model_fit.yaml"
SCHEMA_VERSION: Final = 1
SUPPORTED_CLIENTS: Final = frozenset({"claude-code"})
SUPPORTED_EFFORTS: Final = frozenset({"low", "medium", "high", "xhigh", "max"})
SUPPORTED_TELEMETRY: Final = frozenset(
    {"model", "usage.input_tokens", "usage.output_tokens"}
)
RAW_RECEIPT_RETENTION: Final = frozenset({"derived-only"})


JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
RawMapping: TypeAlias = dict[str, JsonValue]


class ModelFitConfigError(ValueError):
    """Raised when a model-fit declaration cannot support reproducible evidence."""


@dataclass(frozen=True)
class ModelFitTarget:
    """One declared client, model, profile, and telemetry contract."""

    id: str
    client: Literal["claude-code"]
    model: str
    expected_model_prefix: str
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    profiles: tuple[str, ...]
    tool_surface: tuple[str, ...]
    required_telemetry: tuple[str, ...]


@dataclass(frozen=True)
class ModelFitConfig:
    """Validated top-level probe configuration."""

    schema_version: int
    raw_receipt_retention: Literal["derived-only"]
    targets: tuple[ModelFitTarget, ...]


@dataclass(frozen=True)
class PackageReference:
    """Discovery metadata for one package selected by a profile."""

    name: str
    package_type: str
    version: str
    source_path: str


@dataclass(frozen=True)
class ProfileManifest:
    """Resolved definitions for a profile; this does not represent loaded content."""

    profile: str
    packages: tuple[PackageReference, ...]


def _require_mapping(value: JsonValue, location: str) -> RawMapping:
    if not isinstance(value, dict):
        raise ModelFitConfigError(f"{location} must be a mapping")
    return value


def _require_string(value: JsonValue, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ModelFitConfigError(f"{location} must be a non-empty string")
    return value


def _require_strings(value: JsonValue, location: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ModelFitConfigError(f"{location} must be a non-empty list of strings")
    strings = tuple(
        _require_string(item, f"{location}[{index}]")
        for index, item in enumerate(value)
    )
    if len(strings) != len(set(strings)):
        raise ModelFitConfigError(f"{location} must not contain duplicates")
    return strings


def _optional_strings(value: JsonValue, location: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ModelFitConfigError(f"{location} must be a list of strings")
    strings = tuple(
        _require_string(item, f"{location}[{index}]")
        for index, item in enumerate(value)
    )
    if len(strings) != len(set(strings)):
        raise ModelFitConfigError(f"{location} must not contain duplicates")
    return strings


def _load_yaml(path: Path) -> RawMapping:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ModelFitConfigError(f"cannot read configuration {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ModelFitConfigError(f"cannot parse configuration {path}: {exc}") from exc
    return _require_mapping(data, "configuration")


def _parse_target(raw_target: JsonValue, index: int) -> ModelFitTarget:
    location = f"targets[{index}]"
    target = _require_mapping(raw_target, location)
    target_id = _require_string(target.get("id"), f"{location}.id")
    client = _require_string(target.get("client"), f"{location}.client")
    if client not in SUPPORTED_CLIENTS:
        raise ModelFitConfigError(f"{location}.client has unsupported value {client!r}")
    effort = _require_string(target.get("effort"), f"{location}.effort")
    if effort not in SUPPORTED_EFFORTS:
        raise ModelFitConfigError(f"{location}.effort has unsupported value {effort!r}")
    required_telemetry = _require_strings(
        target.get("required_telemetry"),
        f"{location}.required_telemetry",
    )
    unsupported_telemetry = sorted(set(required_telemetry) - SUPPORTED_TELEMETRY)
    if unsupported_telemetry:
        values = ", ".join(unsupported_telemetry)
        raise ModelFitConfigError(
            f"{location}.required_telemetry has unsupported field(s): {values}"
        )
    if "model" not in required_telemetry:
        raise ModelFitConfigError(
            f"{location}.required_telemetry must include 'model'",
        )
    return ModelFitTarget(
        id=target_id,
        client=cast(Literal["claude-code"], client),
        model=_require_string(target.get("model"), f"{location}.model"),
        expected_model_prefix=_require_string(
            target.get("expected_model_prefix"),
            f"{location}.expected_model_prefix",
        ),
        effort=cast(Literal["low", "medium", "high", "xhigh", "max"], effort),
        profiles=_require_strings(target.get("profiles"), f"{location}.profiles"),
        tool_surface=_optional_strings(
            target.get("tool_surface", []), f"{location}.tool_surface"
        ),
        required_telemetry=required_telemetry,
    )


def load_model_fit_config(path: Path = DEFAULT_CONFIG_PATH) -> ModelFitConfig:
    """Load and validate a declared model-fit target configuration."""
    raw = _load_yaml(path)
    schema_version = raw.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != SCHEMA_VERSION:
        raise ModelFitConfigError(
            f"schema_version must be {SCHEMA_VERSION}, got {schema_version!r}",
        )
    retention = _require_string(
        raw.get("raw_receipt_retention"), "raw_receipt_retention"
    )
    if retention not in RAW_RECEIPT_RETENTION:
        raise ModelFitConfigError(
            "raw_receipt_retention must be 'derived-only' until an approved retention policy exists",
        )
    raw_targets = raw.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ModelFitConfigError("targets must be a non-empty list")
    targets = tuple(
        _parse_target(raw_target, index) for index, raw_target in enumerate(raw_targets)
    )
    ids = tuple(target.id for target in targets)
    if len(ids) != len(set(ids)):
        raise ModelFitConfigError("targets must not contain duplicate id values")
    return ModelFitConfig(
        schema_version=SCHEMA_VERSION,
        raw_receipt_retention=cast(Literal["derived-only"], retention),
        targets=targets,
    )


def select_target(config: ModelFitConfig, target_id: str) -> ModelFitTarget:
    """Return one declared target or fail loudly when it was not declared."""
    for target in config.targets:
        if target.id == target_id:
            return target
    raise ModelFitConfigError(f"undeclared target: {target_id}")


def _resolved_packages(profile: str, packages: list[PackageInfo]) -> list[PackageInfo]:
    profiles = load_profiles()
    if profile not in profiles:
        raise ModelFitConfigError(f"undeclared profile: {profile}")
    profile_data = profiles[profile]
    resolved = resolve_profile_packages(profile, profiles)
    if profile_data.get("all", False):
        return packages
    inventory = {(package.pkg_type.key, package.name): package for package in packages}
    missing = sorted(
        f"{package_type}/{name}"
        for package_type, names in resolved.items()
        for name in names
        if (package_type, name) not in inventory
    )
    if missing:
        raise ModelFitConfigError(
            f"profile {profile!r} references missing package definition(s): {', '.join(missing)}",
        )
    return [
        inventory[(package_type, name)]
        for package_type, names in sorted(resolved.items())
        for name in sorted(names)
    ]


def resolve_profile_manifest(profile: str) -> ProfileManifest:
    """Resolve a profile to repository definitions without reading package bodies."""
    packages = _resolved_packages(profile, discover_packages())
    references = tuple(
        PackageReference(
            name=package.name,
            package_type=package.pkg_type.key,
            version=package.version,
            source_path=str(package.source_path.relative_to(_REPO_ROOT)),
        )
        for package in sorted(
            packages, key=lambda package: (package.pkg_type.key, package.name)
        )
    )
    return ProfileManifest(profile=profile, packages=references)


def probe_client_version() -> str:
    """Read the local client version without invoking a model."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as exc:
        raise ModelFitConfigError(f"cannot execute claude --version: {exc}") from exc
    version = result.stdout.strip()
    if result.returncode != 0 or not version:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise ModelFitConfigError(f"claude --version failed: {detail}")
    return version


def _target_json(target: ModelFitTarget) -> dict[str, JsonValue]:
    return {
        "id": target.id,
        "client": target.client,
        "model": target.model,
        "expected_model_prefix": target.expected_model_prefix,
        "effort": target.effort,
        "profiles": list(target.profiles),
        "tool_surface": list(target.tool_surface),
        "required_telemetry": list(target.required_telemetry),
    }


def _profile_manifest_json(manifest: ProfileManifest) -> dict[str, JsonValue]:
    return {
        "profile": manifest.profile,
        "packages": [
            {
                "name": package.name,
                "package_type": package.package_type,
                "version": package.version,
                "source_path": package.source_path,
            }
            for package in manifest.packages
        ],
    }


def dry_run(target: ModelFitTarget, profiles: tuple[str, ...]) -> dict[str, JsonValue]:
    """Validate one declared target and resolve selected profile definitions."""
    undeclared_profiles = sorted(set(profiles) - set(target.profiles))
    if undeclared_profiles:
        raise ModelFitConfigError(
            f"target {target.id!r} does not declare profile(s): {', '.join(undeclared_profiles)}",
        )
    manifests: list[JsonValue] = []
    for profile in profiles:
        manifests.append(_profile_manifest_json(resolve_profile_manifest(profile)))
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "dry-run",
        "model_request_made": False,
        "target": _target_json(target),
        "client_version": probe_client_version(),
        "profile_manifests": manifests,
        "package_content_observation": "not-loaded",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--target", required=True, help="Declared target id")
    parser.add_argument(
        "--profile",
        action="append",
        help="Declared target profile to validate; repeat to select multiple",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate declarations without invoking a model",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run dry-run validation for one declared target."""
    args = _parser().parse_args(argv)
    if not args.dry_run:
        print(
            "live probe execution is not available in this command version",
            file=sys.stderr,
        )
        return 2
    try:
        config = load_model_fit_config(args.config)
        target = select_target(config, args.target)
        profiles = tuple(args.profile) if args.profile else target.profiles
        result = dry_run(target, profiles)
    except ModelFitConfigError as exc:
        print(f"model-fit validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
