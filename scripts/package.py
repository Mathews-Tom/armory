#!/usr/bin/env python3
"""Package any armory directory into a typed archive (.skill, .agent, .hook, etc.)."""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.frontmatter import extract_version, parse_frontmatter, validate_version
from scripts.package_types import (
    TYPES,
    PackageType,
    detect_type_from_path,
    should_exclude,
)


# Archives must be byte-identical for identical content. zipfile.write() stamps each
# entry with the source file's mtime, so a fresh checkout produced a different archive
# from unchanged sources — which defeated checksum-based release syncing and made
# published archives unverifiable. Entries are written with a fixed timestamp and a
# normalized mode instead. 1980-01-01 is the earliest instant the ZIP format encodes.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
MODE_EXECUTABLE = 0o755
MODE_REGULAR = 0o644


def validate_frontmatter(pkg_dir: Path, pkg_type: PackageType) -> dict[str, Any]:
    """Validate frontmatter in the type-specific definition file."""
    definition = pkg_dir / pkg_type.definition_file
    if not definition.exists():
        raise FileNotFoundError(
            f"{pkg_type.definition_file} not found in {pkg_dir}"
        )

    content = definition.read_text(encoding="utf-8")
    meta = parse_frontmatter(content)

    version = extract_version(meta)
    missing: list[str] = []

    for field in pkg_type.required_frontmatter:
        if not meta.get(field):
            missing.append(field)

    if not version:
        missing.append("metadata.version")

    if missing:
        raise ValueError(
            f"{pkg_type.definition_file} missing required fields: {', '.join(missing)}"
        )

    if not validate_version(version):
        raise ValueError(
            f"Invalid version '{version}' — must be semver (e.g. 1.0.0)"
        )

    meta["_resolved_version"] = version
    return meta


def collect_files(pkg_dir: Path) -> tuple[list[Path], list[Path]]:
    """Collect files for packaging, splitting into included/excluded lists."""
    included: list[Path] = []
    excluded: list[Path] = []

    for path in sorted(pkg_dir.rglob("*")):
        if not path.is_file():
            continue
        if should_exclude(path, pkg_dir):
            excluded.append(path)
        else:
            included.append(path)

    return included, excluded


def package(pkg_dir: Path, output_dir: Path, pkg_type: PackageType) -> Path:
    """Package a directory into a typed archive."""
    meta = validate_frontmatter(pkg_dir, pkg_type)
    name: str = meta["name"]
    version: str = meta["_resolved_version"]
    archive_name = f"{name}-{version}{pkg_type.archive_ext}"
    output_path = output_dir / archive_name

    included, excluded = collect_files(pkg_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in included:
            arcname = file_path.relative_to(pkg_dir.parent)
            # Git tracks only the executable bit, so collapsing to 755/644 keeps the
            # archive identical across checkouts with different umasks.
            executable = file_path.stat().st_mode & 0o111
            info = zipfile.ZipInfo(arcname.as_posix(), date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (MODE_EXECUTABLE if executable else MODE_REGULAR) << 16
            zf.writestr(info, file_path.read_bytes())
            print(f"  added: {arcname}")

    for file_path in excluded:
        rel = file_path.relative_to(pkg_dir)
        print(f"  skipped: {rel}")

    return output_path


def package_skill(skill_dir: Path, output_dir: Path) -> Path:
    """Backward-compatible wrapper for packaging skills."""
    return package(skill_dir, output_dir, TYPES["skill"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package a directory into an armory archive"
    )
    parser.add_argument("pkg_dir", type=Path, help="Path to the package directory")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Output directory for archive",
    )
    parser.add_argument(
        "--type",
        dest="pkg_type",
        choices=list(TYPES.keys()),
        default=None,
        help="Package type (auto-detected from path if omitted)",
    )
    args = parser.parse_args()

    pkg_dir: Path = args.pkg_dir.resolve()
    output_dir: Path = args.output_dir.resolve()

    if not pkg_dir.is_dir():
        print(f"ERROR: {pkg_dir} is not a directory", file=sys.stderr)
        return 1

    if args.pkg_type:
        pkg_type = TYPES[args.pkg_type]
    else:
        try:
            pkg_type = detect_type_from_path(pkg_dir)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print(
                "Specify --type explicitly or place the directory under a known type folder.",
                file=sys.stderr,
            )
            return 1

    try:
        output_path = package(pkg_dir, output_dir, pkg_type)
        print(f"Packaged: {output_path}")
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
