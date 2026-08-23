#!/usr/bin/env python3
"""Validate declared model-fit targets without making a model request.

A dry run resolves package definitions selected by a profile. It records only
installed discovery metadata, never package body content or a claim that a
package was injected into a turn.
"""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import json
import subprocess
import signal
import sys
import time
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


class ModelFitCaptureError(RuntimeError):
    """Raised when a live client response cannot supply declared evidence."""


def _probe_command(target: ModelFitTarget) -> list[str]:
    return [
        "claude",
        "-p",
        "Reply with exactly READY.",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        target.model,
        "--effort",
        target.effort,
        "--strict-mcp-config",
        "--no-session-persistence",
        "--tools",
        ",".join(target.tool_surface),
    ]


def _require_event_mapping(value: JsonValue, location: str) -> RawMapping:
    if not isinstance(value, dict):
        raise ModelFitCaptureError(
            f"malformed client disclosure: {location} must be a mapping",
        )
    return value


def _parse_stream_events(stdout: str) -> tuple[RawMapping, ...]:
    events: list[RawMapping] = []
    for line_number, line in enumerate(stdout.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = cast(JsonValue, json.loads(line))
        except json.JSONDecodeError as exc:
            raise ModelFitCaptureError(
                f"malformed stream-json at line {line_number}: {exc.msg}",
            ) from exc
        events.append(
            _require_event_mapping(value, f"stream event at line {line_number}")
        )
    if not events:
        raise ModelFitCaptureError("client emitted no stream-json events")
    return tuple(events)


def _required_int(value: JsonValue, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ModelFitCaptureError(f"required telemetry missing: {field}")
    return value


def _capture_from_events(
    events: tuple[RawMapping, ...],
    target: ModelFitTarget,
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    models: set[str] = set()
    terminal_events: list[RawMapping] = []
    for event in events:
        event_type = event.get("type")
        if event_type == "assistant":
            message = _require_event_mapping(event.get("message"), "assistant.message")
            model = message.get("model")
            if isinstance(model, str) and model:
                models.add(model)
        elif event_type == "result":
            terminal_events.append(event)

    if not models:
        raise ModelFitCaptureError(
            "required telemetry missing: model (assistant.message.model)",
        )
    if len(models) != 1:
        raise ModelFitCaptureError(
            "model disclosure changed: assistant messages reported multiple model values",
        )
    observed_model = next(iter(models))
    if not observed_model.startswith(target.expected_model_prefix):
        raise ModelFitCaptureError(
            f"observed model {observed_model!r} does not match expected prefix "
            f"{target.expected_model_prefix!r}",
        )
    if len(terminal_events) != 1:
        raise ModelFitCaptureError(
            f"expected exactly one terminal result event, found {len(terminal_events)}",
        )

    terminal = terminal_events[0]
    if terminal.get("is_error") is not False:
        raise ModelFitCaptureError("terminal result does not declare is_error: false")
    usage = _require_event_mapping(terminal.get("usage"), "result.usage")
    observed_usage: dict[str, JsonValue] = {}
    for field in target.required_telemetry:
        if field == "usage.input_tokens":
            observed_usage["input_tokens"] = _required_int(
                usage.get("input_tokens"),
                "usage.input_tokens (result.usage.input_tokens)",
            )
        elif field == "usage.output_tokens":
            observed_usage["output_tokens"] = _required_int(
                usage.get("output_tokens"),
                "usage.output_tokens (result.usage.output_tokens)",
            )

    terminal_metadata: dict[str, JsonValue] = {}
    for field in ("subtype", "stop_reason"):
        value = terminal.get(field)
        if isinstance(value, str) and value:
            terminal_metadata[field] = value
    return (
        {
            "model": observed_model,
            "usage": observed_usage,
        },
        terminal_metadata,
    )


def live_probe(
    target: ModelFitTarget,
    profiles: tuple[str, ...],
    timeout_seconds: int,
) -> dict[str, JsonValue]:
    """Invoke an explicitly requested live probe and retain derived fields only."""
    if timeout_seconds <= 0:
        raise ModelFitConfigError("timeout_seconds must be greater than zero")
    declaration = dry_run(target, profiles)
    started = time.monotonic_ns()
    try:
        process = subprocess.Popen(
            _probe_command(target),
            cwd=_REPO_ROOT,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            start_new_session=True,
            text=True,
        )
        stdout, _stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise ModelFitCaptureError(
            f"live probe timed out after {timeout_seconds} seconds",
        ) from exc
    except OSError as exc:
        raise ModelFitCaptureError(f"cannot execute Claude Code probe: {exc}") from exc
    wall_time_ms = (time.monotonic_ns() - started) // 1_000_000
    if process.returncode != 0:
        raise ModelFitCaptureError(
            f"Claude Code probe exited with status {process.returncode}; no receipt was written",
        )
    events = _parse_stream_events(stdout)
    observed, terminal_metadata = _capture_from_events(events, target)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "live",
        "model_request_made": True,
        "raw_receipt_retention": "derived-only",
        "target": declaration["target"],
        "client_version": declaration["client_version"],
        "profile_manifests": declaration["profile_manifests"],
        "package_content_observation": "not-observed",
        "tool_surface": {
            "declared": list(target.tool_surface),
            "observed": "not-disclosed",
        },
        "observed": observed,
        "terminal_metadata": terminal_metadata,
        "wall_time_ms": wall_time_ms,
        "stream_event_count": len(events),
    }


def write_receipt(path: Path, receipt: dict[str, JsonValue]) -> None:
    """Persist a derived receipt; raw prompts, text, and stream events are excluded."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--target", required=True, help="Declared target id")
    parser.add_argument(
        "--profile",
        action="append",
        help="Declared target profile to validate; repeat to select multiple",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate declarations without invoking a model",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="Invoke the declared model and write a derived receipt",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Required receipt path for --live; raw events are never written",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="External wall-clock deadline for --live (default: 120)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        config = load_model_fit_config(args.config)
        target = select_target(config, args.target)
        profiles = (
            tuple(dict.fromkeys(args.profile)) if args.profile else target.profiles
        )
        if args.dry_run:
            result = dry_run(target, profiles)
        else:
            if args.output is None:
                parser.error("--output is required with --live")
            result = live_probe(target, profiles, args.timeout_seconds)
            write_receipt(args.output, result)
    except (ModelFitCaptureError, ModelFitConfigError) as exc:
        print(f"model-fit validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
