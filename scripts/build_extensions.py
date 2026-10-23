#!/usr/bin/env python3
"""Build self-contained native OMP and Claude Code artifacts for registered extensions.

Each artifact is assembled in memory from the feature's canonical source
(pure ``core/``, one host adapter directory and Bun-bundled helpers), checked
for containment, and written under ``<output-dir>/extensions/<feature>/<host>/``
together with an ``armory-extension.json`` content manifest. Identical sources
produce identical bytes regardless of the output root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.extension_metadata import (
    ADAPTER_DIRS,
    CORE_DIR,
    HELPER_SOURCE_DIRS,
    ExtensionMetadata,
    ExtensionMetadataError,
    is_feature_name,
    parse_extension_metadata,
)
from scripts.frontmatter import FrontmatterError, parse_frontmatter
from scripts.package_types import REPO_ROOT, TYPES

EXTENSION_TYPE = TYPES["extension"]
CONTENT_MANIFEST = "armory-extension.json"
CONTENT_MANIFEST_SCHEMA = 1
OMP_ROOT_ENTRY = "index.ts"
CLAUDE_HOOKS_DIR = "hooks"
FILE_MODE = 0o644
_CLAUDE_MODULE_ROOTS = (f"{CORE_DIR}/", f"{CLAUDE_HOOKS_DIR}/")

_SOURCE_SUFFIXES = frozenset({".ts", ".js", ".mjs", ".json", ".md"})
_SCRIPT_SUFFIXES = (".ts", ".js", ".mjs")
# Test-only trees and files stay out of artifacts; they are excluded, not copied.
_TEST_DIR_NAMES = frozenset({"tests", "mod-checks", "fixtures", "__tests__"})
_SKIPPED_DIR_NAMES = frozenset({"node_modules"})
_TEST_FILE = re.compile(r"\.(?:test|spec)\.[cm]?[jt]sx?$")
# Secret- or data-shaped files are refused outright rather than silently dropped.
_FORBIDDEN_FILE = re.compile(
    r"^(?:\.env.*|\.npmrc|id_(?:rsa|dsa|ecdsa|ed25519).*|credentials.*)$"
    r"|\.(?:pem|key|p12|pfx|crt|sqlite3?|db|log|jsonl)$",
    re.IGNORECASE,
)
_OS_NOISE = frozenset({".DS_Store"})


class BuildError(RuntimeError):
    """A native extension artifact cannot be built from its declared inputs."""


class ToolUnavailableError(BuildError):
    """A required pinned build tool is absent or at the wrong version."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Feature discovery
# ---------------------------------------------------------------------------


def registered_features(extensions_root: Path) -> list[str]:
    """Return feature names whose directory carries a definition file."""
    if not extensions_root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in extensions_root.iterdir()
        if is_feature_name(entry.name)
        and not entry.is_symlink()
        and entry.is_dir()
        and (entry / EXTENSION_TYPE.definition_file).is_file()
    )


def resolve_feature_dir(name: str, extensions_root: Path) -> Path:
    """Return the canonical source directory for a feature name."""
    if not is_feature_name(name):
        raise BuildError(f"'{name}' is not a valid kebab-case feature name")
    feature_dir = extensions_root / name
    if feature_dir.is_symlink() or not feature_dir.is_dir():
        raise BuildError(
            f"extension feature '{name}' not found under {extensions_root}"
        )
    return feature_dir


def load_metadata(feature_dir: Path) -> ExtensionMetadata:
    """Parse and validate a registered feature's EXTENSION.md."""
    definition = feature_dir / EXTENSION_TYPE.definition_file
    if definition.is_symlink() or not definition.is_file():
        raise BuildError(
            f"'{feature_dir.name}' is not a registered extension: {EXTENSION_TYPE.definition_file} not found"
        )
    try:
        metadata = parse_extension_metadata(
            parse_frontmatter(definition.read_text(encoding="utf-8"))
        )
    except (FrontmatterError, ExtensionMetadataError) as exc:
        raise BuildError(f"{definition}: {exc}") from exc
    if metadata.name != feature_dir.name:
        raise BuildError(
            f"{definition}: name '{metadata.name}' does not match directory '{feature_dir.name}'"
        )
    return metadata


# ---------------------------------------------------------------------------
# Toolchain
# ---------------------------------------------------------------------------


def pinned_bun_version() -> str:
    """Return the Bun version pinned by the workspace packageManager field."""
    manifest = EXTENSION_TYPE.repo_dir / "package.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"{manifest}: cannot read workspace manifest: {exc}") from exc
    package_manager = data.get("packageManager") if isinstance(data, dict) else None
    match = re.fullmatch(r"bun@(\d+\.\d+\.\d+)", package_manager or "")
    if match is None:
        raise BuildError(
            f"{manifest}: packageManager must pin bun@X.Y.Z, got {package_manager!r}"
        )
    return match.group(1)


def require_bun() -> str:
    """Return the path of the pinned Bun executable or raise."""
    bun = shutil.which("bun")
    if bun is None:
        raise ToolUnavailableError(
            "bun is not on PATH; install the version pinned in extensions/package.json"
        )
    observed = subprocess.run(
        [bun, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    pinned = pinned_bun_version()
    if observed != pinned:
        raise ToolUnavailableError(
            f"bun {observed or 'unknown'} found; extensions/package.json pins bun@{pinned}"
        )
    return bun


# ---------------------------------------------------------------------------
# Source collection and containment
# ---------------------------------------------------------------------------


def collect_source_tree(feature_dir: Path, rel_dir: str) -> dict[str, Path]:
    """Collect distributable files under ``feature_dir/rel_dir`` keyed by feature-relative path.

    Test trees and test files are excluded. Symlinks, special files, hidden
    files, secret/data-shaped files and unsupported file types are refused.
    """
    top = feature_dir / rel_dir
    if top.is_symlink() or not top.is_dir():
        raise BuildError(
            f"{feature_dir.name}: required directory {rel_dir}/ is missing"
        )
    files: dict[str, Path] = {}
    for current, dirnames, filenames in os.walk(top):
        current_path = Path(current)
        kept: list[str] = []
        for dirname in sorted(dirnames):
            path = current_path / dirname
            rel = path.relative_to(feature_dir).as_posix()
            if path.is_symlink():
                raise BuildError(
                    f"{feature_dir.name}/{rel}: symbolic links are not allowed in extension sources"
                )
            if dirname in _TEST_DIR_NAMES or dirname in _SKIPPED_DIR_NAMES:
                continue
            if dirname.startswith("."):
                raise BuildError(
                    f"{feature_dir.name}/{rel}: hidden directories are not distributable"
                )
            kept.append(dirname)
        dirnames[:] = kept
        for filename in sorted(filenames):
            path = current_path / filename
            rel = path.relative_to(feature_dir).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise BuildError(
                    f"{feature_dir.name}/{rel}: symbolic links are not allowed in extension sources"
                )
            if not stat.S_ISREG(mode):
                raise BuildError(
                    f"{feature_dir.name}/{rel}: special files are not allowed in extension sources"
                )
            if filename in _OS_NOISE or _TEST_FILE.search(filename):
                continue
            if _FORBIDDEN_FILE.search(filename):
                raise BuildError(
                    f"{feature_dir.name}/{rel}: secret or data files must not enter native artifacts"
                )
            if filename.startswith("."):
                raise BuildError(
                    f"{feature_dir.name}/{rel}: hidden files are not distributable"
                )
            if path.suffix not in _SOURCE_SUFFIXES:
                raise BuildError(
                    f"{feature_dir.name}/{rel}: unsupported file type '{path.suffix}' "
                    f"(allowed: {', '.join(sorted(_SOURCE_SUFFIXES))})"
                )
            files[rel] = path
    if not files:
        raise BuildError(
            f"{feature_dir.name}: {rel_dir}/ contains no distributable files"
        )
    return files


def _read_source_bytes(feature_dir: Path, relative: str) -> bytes:
    """Read one approved file without following a replaced leaf or ancestor."""
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        directory = os.open(feature_dir, flags | os.O_DIRECTORY)
    except OSError as exc:
        raise BuildError(f"{feature_dir}: unsafe source directory: {exc}") from exc
    try:
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            next_directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        leaf = os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(leaf).st_mode):
                raise BuildError(
                    f"{feature_dir.name}/{relative}: source is not a regular file"
                )
            with os.fdopen(leaf, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(leaf)
    except OSError as exc:
        raise BuildError(
            f"{feature_dir.name}/{relative}: unsafe source input: {exc}"
        ) from exc
    finally:
        os.close(directory)


def _run_source_tool(request: dict[str, Any], bun: str | None = None) -> str:
    """Analyze or bundle immutable inputs using the workspace's pinned parser."""
    tool = EXTENSION_TYPE.repo_dir / "_tooling" / "build-inputs.ts"
    result = subprocess.run(
        [bun or require_bun(), "--no-env-file", "--no-install", str(tool)],
        input=json.dumps(request),
        cwd=tool.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BuildError(f"extension source analysis failed:\n{result.stderr.strip()}")
    return result.stdout


def _analyze_sources(files: dict[str, bytes]) -> dict[str, Any]:
    try:
        scripts = {
            path: data.decode("utf-8")
            for path, data in files.items()
            if path.endswith(_SCRIPT_SUFFIXES)
        }
        if not scripts:
            return {}
        result: dict[str, Any] = json.loads(
            _run_source_tool({"action": "analyze", "files": scripts})
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot analyze extension sources: {exc}") from exc
    return result


def _bare_import_allowed(
    rules: str, specifier: str, type_only: bool, builtin: bool
) -> bool:
    if rules == "core":
        return False
    if rules == "omp":
        host_types = specifier == "@oh-my-pi/pi-coding-agent" or specifier.startswith(
            "@oh-my-pi/pi-coding-agent/"
        )
        return builtin or (type_only and host_types)
    if rules == "claude":
        return specifier == "claude-code"
    return builtin


def check_artifact_imports(files: dict[str, bytes], host: str) -> None:
    """Require every module reference to stay inside the artifact.

    Relative imports must name an existing artifact file. Bare imports are
    limited to runtime builtins and host type packages for OMP, and to the
    ``claude-code`` module for Claude mods. Dynamic loading is refused.
    Claude modules may import only other hook modules and the pure core;
    executable helpers run through explicit host process effects.
    """
    for path, analysis in _analyze_sources(files).items():
        rules = (
            "core"
            if path.startswith("core/")
            else "helper"
            if path.startswith("helpers/")
            else host
        )
        if analysis["forbidden"]:
            raise BuildError(
                f"{host} artifact: {path} uses dynamic import() or require(), "
                f"or another unsupported module load: {analysis['forbidden']}"
            )
        for reference in analysis["imports"]:
            type_only, specifier = reference["typeOnly"], reference["specifier"]
            if specifier.startswith(("./", "../")):
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(path), specifier)
                )
                if (
                    target == ".."
                    or target.startswith("../")
                    or target not in files
                    or (rules == "core" and not target.startswith("core/"))
                ):
                    raise BuildError(
                        f"{host} artifact: {path} imports '{specifier}', which does not resolve "
                        "to a file inside the artifact"
                    )
                if rules == "claude" and not target.startswith(_CLAUDE_MODULE_ROOTS):
                    raise BuildError(
                        f"{host} artifact: {path} imports '{specifier}'; "
                        f"Claude mods may import only {CLAUDE_HOOKS_DIR}/ and {CORE_DIR}/ modules; "
                        "run executable helpers through explicit host process effects"
                    )
            elif not _bare_import_allowed(
                rules, specifier, type_only, reference["runtimeBuiltin"]
            ):
                raise BuildError(
                    f"{host} artifact: {path} imports '{specifier}'; artifacts may not depend on "
                    "packages outside themselves"
                )


def check_claude_permissions(
    files: dict[str, bytes], permissions: tuple[str, ...]
) -> None:
    """Refuse undeclared bound API effects and unresolved capability transfers."""
    hooks = {
        path: data
        for path, data in files.items()
        if path.startswith(f"{CLAUDE_HOOKS_DIR}/") and path.endswith(_SCRIPT_SUFFIXES)
    }
    for path, analysis in sorted(_analyze_sources(hooks).items()):
        claude = analysis["claude"]
        if claude["forbidden"]:
            raise BuildError(
                f"claude artifact: {path} uses unsupported Claude API bindings: "
                f"{'; '.join(claude['forbidden'])}"
            )
        for effect in claude["effects"]:
            permission = effect["permission"]
            if permission not in permissions:
                raise BuildError(
                    f"claude artifact: {path} uses {effect['label']} but extension.permissions "
                    f"does not declare '{permission}'"
                )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _bundle_feature_sources(
    feature_dir: Path, entry: str, bun: str, *, omp_adapter: bool
) -> bytes:
    """Bundle only a validated immutable snapshot of feature-owned inputs."""
    sources: dict[str, Path] = {}
    roots: tuple[str, ...] = (CORE_DIR, *HELPER_SOURCE_DIRS)
    if omp_adapter:
        roots = (*roots, ADAPTER_DIRS["omp"])
    for root in roots:
        top = feature_dir / root
        if root == CORE_DIR or top.exists() or top.is_symlink():
            sources.update(collect_source_tree(feature_dir, root))
    if entry not in sources:
        raise BuildError(f"{feature_dir.name}: bundle entry {entry} is missing")
    # Bun never receives the feature path. Its resolver can only serve these
    # approved bytes, so neither a transitive import nor a concurrent source
    # edit can make it read an unapproved filesystem input.
    snapshot = {path: _read_source_bytes(feature_dir, path) for path in sources}
    if omp_adapter:
        check_artifact_imports(snapshot, "omp")
    try:
        files = {
            path: data.decode("utf-8")
            for path, data in snapshot.items()
            if path.endswith((*_SCRIPT_SUFFIXES, ".json"))
        }
    except UnicodeError as exc:
        raise BuildError(
            f"{feature_dir.name}: bundle inputs must be UTF-8: {exc}"
        ) from exc
    return _run_source_tool(
        {
            "action": "bundle",
            "entry": entry,
            "files": files,
            "ompAdapter": omp_adapter,
        },
        bun,
    ).encode("utf-8")


def bundle_helper(feature_dir: Path, helper: str, bun: str) -> bytes:
    """Bundle an executable helper from its contained core/helper closure."""
    return _bundle_feature_sources(feature_dir, helper, bun, omp_adapter=False)


def bundle_omp_adapter(feature_dir: Path, entry: str, bun: str) -> bytes:
    """Contain the adapter's runtime helpers without resolving host SDK types."""
    bundle = _bundle_feature_sources(feature_dir, entry, bun, omp_adapter=True)
    check_artifact_imports({"omp/index.js": bundle}, "omp")
    return bundle


def core_digest(core_files: dict[str, bytes]) -> str:
    """Digest of the exact shared core: sorted paths bound to content hashes."""
    digest = hashlib.sha256()
    for path in sorted(core_files):
        digest.update(f"{path}\0{_sha256(core_files[path])}\n".encode())
    return digest.hexdigest()


def _plugin_identity() -> dict[str, Any]:
    """Author/licensing fields shared with the catalog's Claude plugin manifest."""
    path = REPO_ROOT / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [
        key
        for key in ("author", "homepage", "repository", "license")
        if key not in data
    ]
    if missing:
        raise BuildError(f"{path}: missing {missing}")
    return {key: data[key] for key in ("author", "homepage", "repository", "license")}


def _add_generated(files: dict[str, bytes], path: str, data: bytes) -> None:
    if path in files:
        raise BuildError(f"source file {path} collides with a generated artifact file")
    files[path] = data


def assemble_artifact(
    feature_dir: Path,
    metadata: ExtensionMetadata,
    host: str,
    helper_bundles: dict[str, bytes],
) -> dict[str, bytes]:
    """Return the complete artifact for one host as relative path -> bytes."""
    if host not in metadata.host_entries:
        raise BuildError(f"{metadata.name} does not declare host '{host}'")
    adapter_dir = ADAPTER_DIRS[host]
    entry = metadata.host_entries[host]
    core = {
        path: _read_source_bytes(feature_dir, path)
        for path in collect_source_tree(feature_dir, CORE_DIR)
    }
    adapter = collect_source_tree(feature_dir, adapter_dir)
    if entry not in adapter:
        raise BuildError(
            f"{metadata.name}: {host} entry {entry} is missing or excluded from the artifact"
        )

    identity = _plugin_identity()
    files: dict[str, bytes] = dict(core)
    entrypoints: dict[str, Any]
    if host == "omp":
        files[entry] = bundle_omp_adapter(feature_dir, entry, require_bun())
        _add_generated(
            files, OMP_ROOT_ENTRY, f'export {{ default }} from "./{entry}";\n'.encode()
        )
        package_manifest = {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "private": True,
            "type": "module",
            "license": identity["license"],
            "omp": {"extensions": [f"./{OMP_ROOT_ENTRY}"]},
        }
        _add_generated(files, "package.json", _json_bytes(package_manifest))
        entrypoints = {
            "package_manifest": "package.json",
            "extensions": [OMP_ROOT_ENTRY],
            "adapter": entry,
        }
    else:
        for path in adapter:
            files[CLAUDE_HOOKS_DIR + path[len(adapter_dir) :]] = _read_source_bytes(
                feature_dir, path
            )
        module = entry[len(adapter_dir) + 1 :]
        hooks_manifest = {
            "description": f"{metadata.name} hooks module",
            "modules": [f"./{module}"],
        }
        _add_generated(
            files, f"{CLAUDE_HOOKS_DIR}/hooks.json", _json_bytes(hooks_manifest)
        )
        plugin_manifest = {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            **identity,
        }
        _add_generated(
            files, ".claude-plugin/plugin.json", _json_bytes(plugin_manifest)
        )
        entrypoints = {
            "plugin_manifest": ".claude-plugin/plugin.json",
            "hooks": f"{CLAUDE_HOOKS_DIR}/hooks.json",
            "module": f"{CLAUDE_HOOKS_DIR}/{module}",
        }

    helper_paths: list[str] = []
    for helper in metadata.helpers:
        path = f"helpers/{PurePosixPath(helper).stem}.js"
        _add_generated(files, path, helper_bundles[helper])
        helper_paths.append(path)
    _add_generated(files, "LICENSE", (REPO_ROOT / "LICENSE").read_bytes())

    check_artifact_imports(files, host)
    if host == "claude":
        check_claude_permissions(files, metadata.permissions)

    manifest = {
        "schema_version": CONTENT_MANIFEST_SCHEMA,
        "feature": metadata.name,
        "version": metadata.version,
        "host": host,
        "extension_schema_version": metadata.schema_version,
        "runtime": metadata.runtime,
        "core": {"version": metadata.core_version, "sha256": core_digest(core)},
        "entrypoints": entrypoints,
        "commands": list(metadata.commands),
        "helpers": helper_paths,
        "storage": metadata.storage,
        "permissions": list(metadata.permissions),
        "exercised_compatibility": [
            {"version": record.version, "surfaces": list(record.surfaces)}
            for record in metadata.exercised.get(host, ())
        ],
        "files": [
            {"path": path, "sha256": _sha256(data), "size": len(data)}
            for path, data in sorted(files.items())
        ],
    }
    _add_generated(files, CONTENT_MANIFEST, _json_bytes(manifest))
    return files


def assemble_feature(
    feature_dir: Path,
) -> tuple[ExtensionMetadata, dict[str, dict[str, bytes]]]:
    """Assemble every declared host artifact in memory before any write."""
    metadata = load_metadata(feature_dir)
    bundles: dict[str, bytes] = {}
    if metadata.helpers:
        bun = require_bun()
        bundles = {
            helper: bundle_helper(feature_dir, helper, bun)
            for helper in metadata.helpers
        }
    artifacts = {
        host: assemble_artifact(feature_dir, metadata, host, bundles)
        for host in metadata.hosts
    }
    return metadata, artifacts


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_tree(files: dict[str, bytes], destination: Path) -> None:
    """Write an artifact file map into a new directory with normalized modes."""
    destination.mkdir(parents=True)
    for rel in sorted(files):
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[rel])
        os.chmod(target, FILE_MODE)


def read_content_manifest(artifact_dir: Path) -> dict[str, Any]:
    """Load an artifact's content manifest."""
    path = artifact_dir / CONTENT_MANIFEST
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise BuildError(f"{artifact_dir}: artifact must be a nonlinked directory")
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise BuildError(f"{path}: cannot read content manifest: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise BuildError(f"{path}: content manifest must be a regular file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"{path}: cannot read content manifest: {exc}") from exc
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != CONTENT_MANIFEST_SCHEMA
    ):
        raise BuildError(f"{path}: unsupported content manifest")
    return data


def verify_artifact_dir(artifact_dir: Path) -> dict[str, Any]:
    """Re-hash an artifact on disk against its content manifest.

    Every listed file must match; any unlisted file, symlink or special file
    is refused. Returns the manifest.
    """
    manifest = read_content_manifest(artifact_dir)
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise BuildError(f"{artifact_dir}: invalid content manifest file list")
    expected: dict[str, str] = {}
    sizes: dict[str, int] = {}
    directories: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
            raise BuildError(f"{artifact_dir}: invalid content manifest file entry")
        rel, digest, size = entry["path"], entry["sha256"], entry["size"]
        if (
            not isinstance(rel, str)
            or not rel
            or PurePosixPath(rel).is_absolute()
            or PurePosixPath(rel).as_posix() != rel
            or any(part in ("", ".", "..") for part in rel.split("/"))
            or "\\" in rel
            or rel == CONTENT_MANIFEST
            or rel in expected
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int
            or size < 0
        ):
            raise BuildError(f"{artifact_dir}: invalid content manifest file entry")
        expected[rel] = digest
        sizes[rel] = size
        directories.update(
            parent.as_posix()
            for parent in PurePosixPath(rel).parents
            if parent.as_posix() != "."
        )
    if directories.intersection(expected):
        raise BuildError(f"{artifact_dir}: conflicting content manifest paths")
    expected[CONTENT_MANIFEST] = ""
    observed: set[str] = set()
    for current, dirnames, filenames in os.walk(artifact_dir):
        for name in dirnames + filenames:
            path = Path(current) / name
            rel = path.relative_to(artifact_dir).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise BuildError(f"{artifact_dir}: {rel} is a symbolic link")
            if stat.S_ISDIR(mode):
                if rel not in directories:
                    raise BuildError(
                        f"{artifact_dir}: {rel} is not listed in {CONTENT_MANIFEST}"
                    )
                continue
            if not stat.S_ISREG(mode):
                raise BuildError(f"{artifact_dir}: {rel} is not a regular file")
            if stat.S_IMODE(mode) != FILE_MODE:
                raise BuildError(
                    f"{artifact_dir}: {rel} has locally modified file permissions"
                )
            if rel not in expected:
                raise BuildError(
                    f"{artifact_dir}: {rel} is not listed in {CONTENT_MANIFEST}"
                )
            if rel != CONTENT_MANIFEST:
                data = path.read_bytes()
                if len(data) != sizes[rel] or _sha256(data) != expected[rel]:
                    raise BuildError(
                        f"{artifact_dir}: {rel} does not match its recorded digest"
                    )
            observed.add(rel)
    missing = sorted(set(expected) - observed)
    if missing:
        raise BuildError(f"{artifact_dir}: missing artifact files {missing}")
    return manifest


def _refuse_canonical_output(output_dir: Path, feature_dir: Path) -> None:
    for protected in (EXTENSION_TYPE.repo_dir.resolve(), feature_dir.resolve()):
        if output_dir == protected or output_dir.is_relative_to(protected):
            raise BuildError(
                f"output directory {output_dir} is inside canonical extension source {protected}"
            )


def _check_output_path(output_dir: Path, path: Path, feature_dir: Path) -> None:
    """Refuse links/special ancestors at every generated output component."""
    current = output_dir
    for part in ("", *path.relative_to(output_dir).parts):
        if part:
            current /= part
        if current.is_symlink():
            raise BuildError(
                f"{current} is a symbolic link; refusing to write through it"
            )
        if current.exists() and not current.is_dir():
            raise BuildError(f"{current} is not a directory")
        _refuse_canonical_output(current.resolve(), feature_dir)


def _check_previous_artifact(destination: Path, feature: str, host: str) -> None:
    if destination.exists() or destination.is_symlink():
        previous = verify_artifact_dir(destination)
        if previous.get("feature") != feature or previous.get("host") != host:
            raise BuildError(
                f"{destination} holds a different artifact; refusing to replace it"
            )


def build_feature(feature_dir: Path, output_dir: Path) -> dict[str, Path]:
    """Stage all host artifacts, then replace them as one rollback-safe operation."""
    if output_dir.is_symlink():
        raise BuildError(
            f"{output_dir} is a symbolic link; refusing to write through it"
        )
    output_dir = output_dir.resolve()
    _refuse_canonical_output(output_dir, feature_dir)
    metadata, artifacts = assemble_feature(feature_dir)
    feature_root = output_dir / "extensions" / metadata.name
    _check_output_path(output_dir, feature_root, feature_dir)
    built = {host: feature_root / host for host in artifacts}
    # Refuse any modified/foreign tree before the first host is changed.
    for host, destination in built.items():
        _check_output_path(output_dir, destination, feature_dir)
        _check_previous_artifact(destination, metadata.name, host)
    feature_root.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=".staging-build-", dir=feature_root))
    retired: list[str] = []
    activated: list[str] = []
    preserve_transaction = False
    try:
        for host, files in artifacts.items():
            write_tree(files, transaction / host)
            verify_artifact_dir(transaction / host)
        for host, destination in built.items():
            _check_output_path(output_dir, destination, feature_dir)
            _check_previous_artifact(destination, metadata.name, host)
            if destination.exists():
                os.rename(destination, transaction / f"retired-{host}")
                retired.append(host)
            os.rename(transaction / host, destination)
            activated.append(host)
    except BaseException as failure:
        try:
            # Keep every preimage until every activation has succeeded. A
            # second-host failure therefore restores the first host too.
            for host in reversed(tuple(built)):
                destination = built[host]
                _check_output_path(output_dir, destination, feature_dir)
                if host in activated:
                    _check_previous_artifact(destination, metadata.name, host)
                    os.rename(destination, transaction / f"failed-{host}")
                if host in retired:
                    _check_previous_artifact(
                        transaction / f"retired-{host}", metadata.name, host
                    )
                    if destination.exists() or destination.is_symlink():
                        raise BuildError(
                            f"{destination} appeared during replacement; "
                            "refusing to overwrite it during rollback"
                        )
                    os.rename(transaction / f"retired-{host}", destination)
        except (OSError, BuildError) as rollback_failure:
            preserve_transaction = True
            raise BuildError(
                f"artifact replacement failed and rollback needs recovery at {transaction}: "
                f"{rollback_failure}"
            ) from failure
        raise
    finally:
        # If restoration itself fails, retain all remaining preimages for
        # recovery rather than deleting the only intact previous output.
        if not preserve_transaction:
            shutil.rmtree(transaction)
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build self-contained native OMP and Claude Code artifacts for registered extensions "
            "into <output-dir>/extensions/<feature>/<host>/."
        )
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--feature", metavar="NAME", help="registered feature under extensions/"
    )
    selection.add_argument(
        "--all", action="store_true", help="build every registered feature"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        metavar="PATH",
        help="dist root outside canonical source",
    )
    args = parser.parse_args(argv)

    extensions_root = EXTENSION_TYPE.repo_dir
    try:
        names = registered_features(extensions_root) if args.all else [args.feature]
        if not names:
            print("No registered extensions to build (0 features carry EXTENSION.md)")
            return 0
        summary: list[dict[str, str]] = []
        for name in names:
            built = build_feature(
                resolve_feature_dir(name, extensions_root), args.output_dir
            )
            for host, path in built.items():
                manifest_bytes = (path / CONTENT_MANIFEST).read_bytes()
                summary.append(
                    {
                        "feature": name,
                        "host": host,
                        "path": str(path),
                        "content_manifest_sha256": _sha256(manifest_bytes),
                    }
                )
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
