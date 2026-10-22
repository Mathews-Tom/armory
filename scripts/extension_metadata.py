"""Parse and validate native extension metadata from EXTENSION.md frontmatter.

The ``extension`` frontmatter block declares everything a native build needs:
runtime, shared-core identity, per-host entrypoints, literal commands,
bundled helpers, storage scope, effect permissions and the exact host
versions/surfaces that were actually exercised. Parsing is pure; callers
own every filesystem effect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from scripts.frontmatter import extract_version, validate_version
from scripts.package_types import NATIVE_HOSTS

EXTENSION_SCHEMA_VERSION = 1
SUPPORTED_RUNTIMES: tuple[str, ...] = ("bun",)
STORAGE_SCOPES: tuple[str, ...] = ("none", "user-private")
PERMISSIONS: tuple[str, ...] = ("fs.read", "fs.write", "process.spawn", "network")

# Canonical source layout inside extensions/<feature>/. Each host adapter owns
# one directory; the pure shared core and bundled helpers have fixed homes.
ADAPTER_DIRS: dict[str, str] = {"omp": "omp", "claude": "claude-code"}
CORE_DIR = "core"
HELPERS_DIR = "helpers"
HELPER_SOURCE_DIRS = (HELPERS_DIR, "runner")

_FEATURE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_COMMAND_NAME = re.compile(r"^armory-[a-z0-9](?:[a-z0-9-]{0,55}[a-z0-9])?$")
_ENTRY_SUFFIXES: tuple[str, ...] = (".ts", ".js")
_ALLOWED_KEYS = frozenset(
    {
        "schema_version",
        "runtime",
        "core",
        "hosts",
        "commands",
        "helpers",
        "storage",
        "permissions",
        "tested",
    }
)


class ExtensionMetadataError(ValueError):
    """EXTENSION.md frontmatter does not satisfy the extension schema."""


@dataclass(frozen=True)
class ExercisedHost:
    """One host version and the surfaces actually exercised against it."""

    version: str
    surfaces: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionMetadata:
    """Validated extension declaration for one feature."""

    name: str
    description: str
    version: str
    schema_version: int
    runtime: str
    core_version: str
    host_entries: dict[str, str]
    commands: tuple[str, ...]
    helpers: tuple[str, ...]
    storage: str
    permissions: tuple[str, ...]
    exercised: dict[str, tuple[ExercisedHost, ...]]

    @property
    def hosts(self) -> tuple[str, ...]:
        """Declared hosts in registry order."""
        return tuple(host for host in NATIVE_HOSTS if host in self.host_entries)


def is_feature_name(name: str) -> bool:
    """Return whether ``name`` is a valid kebab-case feature directory name."""
    return bool(_FEATURE_NAME.match(name))


def safe_relative_path(value: object, where: str) -> str:
    """Return a normalized POSIX relative path, refusing escapes."""
    if not isinstance(value, str) or not value:
        raise ExtensionMetadataError(f"{where}: expected a non-empty relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ExtensionMetadataError(
            f"{where}: '{value}' must be a plain relative path without '.' or '..'"
        )
    return path.as_posix()


def _require_mapping(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExtensionMetadataError(f"{where}: expected a mapping")
    return value


def _require_str(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtensionMetadataError(f"{where}: expected a non-empty string")
    return value


def _require_semver(value: object, where: str) -> str:
    text = _require_str(value, where)
    if not validate_version(text):
        raise ExtensionMetadataError(f"{where}: '{text}' must have the form X.Y.Z")
    return text


def _unique_strings(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ExtensionMetadataError(f"{where}: expected a list")
    items = tuple(
        _require_str(item, f"{where}[{index}]") for index, item in enumerate(value)
    )
    if len(set(items)) != len(items):
        raise ExtensionMetadataError(f"{where}: entries must be unique")
    return items


def _parse_hosts(value: object) -> dict[str, str]:
    hosts = _require_mapping(value, "extension.hosts")
    if not hosts:
        raise ExtensionMetadataError(
            "extension.hosts: declare at least one native host"
        )
    entries: dict[str, str] = {}
    for host, raw in hosts.items():
        if host not in NATIVE_HOSTS:
            raise ExtensionMetadataError(
                f"extension.hosts: unsupported host '{host}' (supported: {', '.join(NATIVE_HOSTS)})"
            )
        declaration = _require_mapping(raw, f"extension.hosts.{host}")
        if set(declaration) != {"entry"}:
            raise ExtensionMetadataError(
                f"extension.hosts.{host}: expected exactly one key 'entry'"
            )
        entry = safe_relative_path(
            declaration["entry"], f"extension.hosts.{host}.entry"
        )
        adapter_dir = ADAPTER_DIRS[host]
        if not entry.startswith(f"{adapter_dir}/") or not entry.endswith(
            _ENTRY_SUFFIXES
        ):
            raise ExtensionMetadataError(
                f"extension.hosts.{host}.entry: '{entry}' must be a .ts or .js file under {adapter_dir}/"
            )
        entries[host] = entry
    return entries


def _parse_helpers(value: object) -> tuple[str, ...]:
    helpers = _unique_strings(value, "extension.helpers")
    for index, helper in enumerate(helpers):
        path = safe_relative_path(helper, f"extension.helpers[{index}]")
        if PurePosixPath(
            path
        ).parent.as_posix() not in HELPER_SOURCE_DIRS or not path.endswith(".ts"):
            raise ExtensionMetadataError(
                f"extension.helpers[{index}]: '{path}' must be a .ts file directly under "
                f"{' or '.join(root + '/' for root in HELPER_SOURCE_DIRS)}"
            )
    stems = [PurePosixPath(helper).stem for helper in helpers]
    if len(set(stems)) != len(stems):
        raise ExtensionMetadataError(
            "extension.helpers: helper file stems must be unique"
        )
    return helpers


def _parse_exercised(
    value: object, hosts: dict[str, str]
) -> dict[str, tuple[ExercisedHost, ...]]:
    tested = _require_mapping(value, "extension.tested")
    exercised: dict[str, tuple[ExercisedHost, ...]] = {}
    for host, records in tested.items():
        if host not in hosts:
            raise ExtensionMetadataError(
                f"extension.tested: '{host}' is not a declared host"
            )
        if not isinstance(records, list) or not records:
            raise ExtensionMetadataError(
                f"extension.tested.{host}: expected a non-empty list"
            )
        parsed: list[ExercisedHost] = []
        for index, raw in enumerate(records):
            where = f"extension.tested.{host}[{index}]"
            record = _require_mapping(raw, where)
            if set(record) != {"version", "surfaces"}:
                raise ExtensionMetadataError(
                    f"{where}: expected exactly 'version' and 'surfaces'"
                )
            parsed.append(
                ExercisedHost(
                    version=_require_str(record["version"], f"{where}.version"),
                    surfaces=_unique_strings(record["surfaces"], f"{where}.surfaces"),
                )
            )
        exercised[host] = tuple(parsed)
    return exercised


def parse_extension_metadata(meta: dict[str, Any]) -> ExtensionMetadata:
    """Validate parsed EXTENSION.md frontmatter and return its declaration."""
    name = _require_str(meta.get("name"), "name")
    if not is_feature_name(name):
        raise ExtensionMetadataError(
            f"name: '{name}' must be kebab-case, at most 64 characters"
        )
    description = _require_str(meta.get("description"), "description")
    version = extract_version(meta)
    if not validate_version(version):
        raise ExtensionMetadataError(
            f"metadata.version: '{version}' must have the form X.Y.Z"
        )

    block = _require_mapping(meta.get("extension"), "extension")
    unknown = sorted(set(block) - _ALLOWED_KEYS)
    if unknown:
        raise ExtensionMetadataError(f"extension: unknown keys {unknown}")

    schema_version = block.get("schema_version")
    if type(schema_version) is not int or schema_version != EXTENSION_SCHEMA_VERSION:
        raise ExtensionMetadataError(
            f"extension.schema_version: expected {EXTENSION_SCHEMA_VERSION}, got {schema_version!r}"
        )
    runtime = _require_str(block.get("runtime"), "extension.runtime")
    if runtime not in SUPPORTED_RUNTIMES:
        raise ExtensionMetadataError(
            f"extension.runtime: unsupported runtime '{runtime}' (supported: {', '.join(SUPPORTED_RUNTIMES)})"
        )
    core = _require_mapping(block.get("core"), "extension.core")
    if set(core) != {"version"}:
        raise ExtensionMetadataError(
            "extension.core: expected exactly one key 'version'"
        )
    core_version = _require_semver(core["version"], "extension.core.version")

    host_entries = _parse_hosts(block.get("hosts"))

    commands = _unique_strings(block.get("commands"), "extension.commands")
    if not commands:
        raise ExtensionMetadataError(
            "extension.commands: declare at least one literal command"
        )
    for command in commands:
        if not _COMMAND_NAME.match(command):
            raise ExtensionMetadataError(
                f"extension.commands: '{command}' must be 'armory-' followed by kebab-case, at most 64 characters"
            )

    helpers = _parse_helpers(block.get("helpers", []))

    storage = _require_str(block.get("storage"), "extension.storage")
    if storage not in STORAGE_SCOPES:
        raise ExtensionMetadataError(
            f"extension.storage: '{storage}' is not one of {', '.join(STORAGE_SCOPES)}"
        )

    permissions = _unique_strings(block.get("permissions"), "extension.permissions")
    unknown_permissions = sorted(set(permissions) - set(PERMISSIONS))
    if unknown_permissions:
        raise ExtensionMetadataError(
            f"extension.permissions: unknown {unknown_permissions} (allowed: {', '.join(PERMISSIONS)})"
        )
    if storage == "user-private" and "fs.write" not in permissions:
        raise ExtensionMetadataError(
            "extension.permissions: user-private storage requires 'fs.write'"
        )

    exercised = _parse_exercised(block.get("tested", {}), host_entries)

    return ExtensionMetadata(
        name=name,
        description=description.strip(),
        version=version,
        schema_version=schema_version,
        runtime=runtime,
        core_version=core_version,
        host_entries=host_entries,
        commands=commands,
        helpers=helpers,
        storage=storage,
        permissions=tuple(sorted(permissions)),
        exercised=exercised,
    )
