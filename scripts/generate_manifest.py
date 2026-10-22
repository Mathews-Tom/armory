#!/usr/bin/env python3
"""Generate manifest.yaml from package definition frontmatter files."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path for direct script execution.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml

from scripts.frontmatter import extract_version, parse_frontmatter
from scripts.package_types import (
    MANIFEST_PATH,
    REPO_ROOT,
    TYPES,
    PackageType,
)

# Type-specific metadata extractors keyed by PackageType.key.
# Each callable receives the parsed frontmatter dict and returns a dict of
# extra fields to merge into the manifest entry.
_TYPE_EXTRACTORS: dict[str, Any] = {
    "agent": lambda m: _pick(m, model=("model",), category=("category",), execution_phase=("execution_phase",)),
    "hook": lambda m: _pick_nested(m, events=("hook", "events")),
    "rule": lambda m: _pick_nested(m, scope=("metadata", "scope")),
    "utility": lambda m: _pick_nested(m, runtime=("utility", "runtime")),
    "preset": lambda m: _count_nested(m, package_count=("preset", "packages")),
    "extension": lambda m: _extension_fields(m),
}


def _extension_fields(meta: dict[str, Any]) -> dict[str, Any]:
    """Catalog fields for a native extension: hosts, runtime and literal commands."""
    block = meta.get("extension")
    if not isinstance(block, dict):
        return {}
    hosts = block.get("hosts")
    return {
        "hosts": sorted(hosts) if isinstance(hosts, dict) else [],
        "runtime": block.get("runtime"),
        "commands": block.get("commands", []),
    }


def _pick(meta: dict[str, Any], **fields: tuple[str, ...]) -> dict[str, Any]:
    """Extract top-level fields from frontmatter."""
    result: dict[str, Any] = {}
    for out_key, (fm_key,) in fields.items():
        val = meta.get(fm_key)
        if val is not None:
            result[out_key] = val
    return result


def _pick_nested(meta: dict[str, Any], **fields: tuple[str, str]) -> dict[str, Any]:
    """Extract nested fields (two levels) from frontmatter."""
    result: dict[str, Any] = {}
    for out_key, (parent_key, child_key) in fields.items():
        parent = meta.get(parent_key)
        if isinstance(parent, dict):
            val = parent.get(child_key)
            if val is not None:
                result[out_key] = val
    return result


def _count_nested(meta: dict[str, Any], **fields: tuple[str, str]) -> dict[str, Any]:
    """Count items in a nested list field."""
    result: dict[str, Any] = {}
    for out_key, (parent_key, child_key) in fields.items():
        parent = meta.get(parent_key)
        if isinstance(parent, dict):
            val = parent.get(child_key)
            if isinstance(val, list):
                result[out_key] = len(val)
    return result


def resolve_repo(repo_flag: str | None) -> str:
    """Resolve the GitHub owner/name from --repo flag or git remote.

    Returns owner/name string (e.g. 'Mathews-Tom/armory').
    Fails explicitly if neither source is available.
    """
    if repo_flag:
        return repo_flag

    try:
        remote_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(
            "ERROR: No git remote found. Pass --repo owner/name explicitly.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Handle SSH: git@github.com:owner/name.git
    ssh_match = re.match(r"git@github\.com:(.+?)(?:\.git)?$", remote_url)
    if ssh_match:
        return ssh_match.group(1)

    # Handle HTTPS: https://github.com/owner/name.git
    https_match = re.match(r"https://github\.com/(.+?)(?:\.git)?$", remote_url)
    if https_match:
        return https_match.group(1)

    print(
        f"ERROR: Cannot parse GitHub owner/name from remote URL: {remote_url}\n"
        "Pass --repo owner/name explicitly.",
        file=sys.stderr,
    )
    sys.exit(1)


def collect_packages(pkg_type: PackageType, repo: str) -> list[dict[str, Any]]:
    """Walk {pkg_type.repo_dir}/*/definition_file and build manifest entries."""
    entries: list[dict[str, Any]] = []

    if not pkg_type.repo_dir.is_dir():
        return entries

    for pkg_dir in sorted(pkg_type.repo_dir.iterdir()):
        def_file = pkg_dir / pkg_type.definition_file
        if not pkg_dir.is_dir() or not def_file.exists():
            continue

        content = def_file.read_text(encoding="utf-8")
        meta = parse_frontmatter(content)

        name = meta.get("name", "")
        version = extract_version(meta)
        description = meta.get("description", "")

        if not name:
            print(f"WARNING: {def_file} missing 'name' field, skipping", file=sys.stderr)
            continue

        if not version:
            print(f"WARNING: {def_file} missing 'version' field, skipping", file=sys.stderr)
            continue

        path = str(pkg_dir.relative_to(REPO_ROOT))
        source = f"https://github.com/{repo}/blob/main/{path}/{pkg_type.definition_file}"

        entry: dict[str, Any] = {
            "name": name,
            "version": version,
            "description": description.strip() if description else "",
            "path": path,
            "source": source,
        }

        # Type-specific metadata
        extractor = _TYPE_EXTRACTORS.get(pkg_type.key)
        if extractor:
            entry.update(extractor(meta))

        # Optional metadata fields: complements, tags, category, difficulty
        metadata = meta.get("metadata")
        if isinstance(metadata, dict):
            complements = metadata.get("complements")
            if isinstance(complements, list) and complements:
                entry["complements"] = complements
            tags = metadata.get("tags")
            if isinstance(tags, list) and tags:
                entry["tags"] = tags
            category = metadata.get("category")
            if isinstance(category, str) and category:
                entry["category"] = category
            difficulty = metadata.get("difficulty")
            if isinstance(difficulty, str) and difficulty:
                entry["difficulty"] = difficulty
            phase = metadata.get("phase")
            if isinstance(phase, str) and phase:
                entry["phase"] = phase

        entries.append(entry)

    return entries


def enforce_bidirectional_complements(
    entries: list[dict[str, Any]],
) -> None:
    """Ensure complements are bidirectional within a type section.

    If package A lists B in complements, B's complements will include A in the
    manifest output. This does NOT modify source files -- only in-memory entries.
    """
    name_to_entry: dict[str, dict[str, Any]] = {
        str(e["name"]): e for e in entries
    }

    for entry in entries:
        complements = entry.get("complements")
        if not isinstance(complements, list):
            continue

        name = str(entry["name"])
        for comp in complements:
            peer = name_to_entry.get(comp)
            if peer is None:
                continue

            peer_complements = peer.get("complements")
            if not isinstance(peer_complements, list):
                peer["complements"] = [name]
            elif name not in peer_complements:
                peer_complements.append(name)


def write_manifest(all_packages: dict[str, list[dict[str, Any]]]) -> None:
    """Write manifest.yaml (all types)."""
    header = "# Auto-generated by scripts/generate_manifest.py — do not edit manually.\n"
    dump_kwargs: dict[str, Any] = {
        "default_flow_style": False,
        "sort_keys": False,
        "allow_unicode": True,
        "width": 120,
    }

    manifest: dict[str, Any] = {"packages": all_packages}
    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.dump(manifest, f, **dump_kwargs)


def main() -> int:
    """Generate manifest.yaml from package definition frontmatter.

    Scans all package type directories, builds manifest entries, enforces
    bidirectional complements within each type, and writes manifest.yaml.
    """
    parser = argparse.ArgumentParser(
        description="Generate manifest.yaml from package definition frontmatter.",
    )
    parser.add_argument(
        "--repo",
        help="GitHub owner/name (e.g. 'Mathews-Tom/armory'). "
        "Default: derived from git remote origin. "
        "Required if no git remote is configured.",
    )
    args = parser.parse_args()

    repo = resolve_repo(args.repo)

    all_packages: dict[str, list[dict[str, Any]]] = {}
    total = 0

    for pkg_type in TYPES.values():
        entries = collect_packages(pkg_type, repo)
        if not entries:
            continue
        enforce_bidirectional_complements(entries)
        all_packages[pkg_type.manifest_section] = entries
        total += len(entries)

    if total == 0:
        print("ERROR: No packages found", file=sys.stderr)
        return 1

    write_manifest(all_packages)

    counts = ", ".join(f"{len(v)} {k}" for k, v in all_packages.items())
    print(f"Generated {MANIFEST_PATH} with {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
