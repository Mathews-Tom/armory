#!/usr/bin/env python3
"""Generate skills.yaml manifest from SKILL.md frontmatter files."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
MANIFEST_PATH = REPO_ROOT / "skills.yaml"


def parse_frontmatter(content: str) -> dict[str, str]:
    """Parse YAML frontmatter from SKILL.md content.

    Reuses the same regex-free approach: split on '---' delimiters.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        raise ValueError("No valid YAML frontmatter found")
    return yaml.safe_load(match.group(1))


def extract_version(meta: dict[str, str]) -> str:
    """Extract version from metadata.version (preferred) or top-level version (legacy)."""
    metadata = meta.get("metadata")
    if isinstance(metadata, dict) and metadata.get("version"):
        return str(metadata["version"])
    return str(meta.get("version", ""))


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


def collect_skills(repo: str) -> list[dict[str, str | list[str]]]:
    """Walk skills/*/SKILL.md and build manifest entries."""
    entries: list[dict[str, str | list[str]]] = []

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_md.exists():
            continue

        content = skill_md.read_text(encoding="utf-8")
        meta = parse_frontmatter(content)

        name = meta.get("name", "")
        version = extract_version(meta)
        description = meta.get("description", "")

        if not name:
            print(f"WARNING: {skill_md} missing 'name' field, skipping", file=sys.stderr)
            continue

        if not version:
            print(f"WARNING: {skill_md} missing 'version' field, skipping", file=sys.stderr)
            continue

        path = str(skill_dir.relative_to(REPO_ROOT))
        source = f"https://github.com/{repo}/blob/main/{path}/SKILL.md"

        entry: dict[str, str | list[str]] = {
            "name": name,
            "version": version,
            "description": description.strip() if description else "",
            "path": path,
            "source": source,
        }

        # Read optional complements from metadata
        metadata = meta.get("metadata")
        if isinstance(metadata, dict):
            complements = metadata.get("complements")
            if isinstance(complements, list) and complements:
                entry["complements"] = complements

        entries.append(entry)

    return entries


def enforce_bidirectional_complements(
    entries: list[dict[str, str | list[str]]],
) -> None:
    """Ensure complements are bidirectional in the manifest output.

    If skill A lists B in complements, B's complements will include A in the
    manifest output. This does NOT modify SKILL.md source files — only the
    in-memory entries used for skills.yaml generation.
    """
    name_to_entry: dict[str, dict[str, str | list[str]]] = {
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


def write_manifest(entries: list[dict[str, str | list[str]]]) -> None:
    """Write skills.yaml manifest file."""
    manifest = {"skills": entries}
    header = "# Auto-generated by scripts/generate_manifest.py — do not edit manually.\n"

    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.dump(
            manifest,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )

    print(f"Generated {MANIFEST_PATH} with {len(entries)} skills")


def main() -> int:
    """Generate skills.yaml from SKILL.md frontmatter.

    Adds source URLs derived from the GitHub remote (or --repo flag) and
    copies complements from SKILL.md metadata. Complements are enforced as
    bidirectional in the manifest output: if A lists B, B will also list A.
    This auto-mirroring affects skills.yaml only, not SKILL.md source files.
    """
    parser = argparse.ArgumentParser(
        description="Generate skills.yaml manifest from SKILL.md frontmatter.",
    )
    parser.add_argument(
        "--repo",
        help="GitHub owner/name (e.g. 'Mathews-Tom/armory'). "
        "Default: derived from git remote origin. "
        "Required if no git remote is configured.",
    )
    args = parser.parse_args()

    repo = resolve_repo(args.repo)
    entries = collect_skills(repo)
    if not entries:
        print("ERROR: No skills found", file=sys.stderr)
        return 1

    enforce_bidirectional_complements(entries)
    write_manifest(entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
