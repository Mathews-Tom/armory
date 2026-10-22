#!/usr/bin/env python3
"""TUI installer for armory.

Copy-installable types go to ~/.claude/{type}/. Native extensions are never
part of interactive, profile, preset or "all" installs; they use an explicit
host lifecycle: --type extension --platform <omp|claude> --name <feature>
--action <install|update|disable|remove> --target-root <host root> --yes.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from scripts.build_extensions import BuildError
from scripts.frontmatter import (
    FrontmatterError,
    extract_body,
    extract_version,
    parse_frontmatter,
    validate_version,
)
from scripts.hooks_installer import install_hook as _install_hook_to_settings
from scripts.package_types import (
    MANIFEST_PATH,
    NATIVE_ACTIONS,
    NATIVE_HOSTS,
    REPO_ROOT,
    TYPES,
    PackageType,
    should_exclude,
)

DEFAULT_CLAUDE_DIR = Path.home() / ".claude"
PROFILES_PATH = REPO_ROOT / "profiles.yaml"

# Types that install as body-only .md files (frontmatter stripped)
BODY_ONLY_TYPES: frozenset[str] = frozenset({"rule", "command"})

# Type display colors for TUI
TYPE_COLORS: dict[str, str] = {
    "skill": "cyan",
    "agent": "magenta",
    "hook": "yellow",
    "rule": "green",
    "command": "blue",
    "utility": "red",
    "preset": "bright_black",
    "extension": "bright_cyan",
}

console = Console()


class InstallInputError(ValueError):
    """Package or profile declarations cannot support a complete installation."""


class InstallAction(Enum):
    INSTALL = "install"
    UPGRADE = "upgrade"
    REINSTALL = "reinstall"
    SKIP = "skip"


@dataclass(frozen=True)
class PackageInfo:
    name: str
    version: str
    description: str
    source_path: Path
    pkg_type: PackageType


@dataclass(frozen=True)
class InstallPlan:
    package: PackageInfo
    action: InstallAction
    installed_version: str | None
    target_path: Path


def parse_version(v: str) -> tuple[int, int, int]:
    """Parse semver string into comparable tuple."""
    parts = v.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version: {v}")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def is_newer(repo: str, installed: str) -> bool:
    """Return True if repo version is strictly newer than installed."""
    return parse_version(repo) > parse_version(installed)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_packages(pkg_type: PackageType | None = None) -> list[PackageInfo]:
    """Discover available packages from manifest or definition files.

    If pkg_type is None, discover all types.
    """
    types_to_scan = [pkg_type] if pkg_type else list(TYPES.values())

    if MANIFEST_PATH.exists():
        return _discover_from_manifest(types_to_scan)
    return _discover_from_definition_files(types_to_scan)


def _require_str(value: object, where: str, field: str, *, optional: bool = False) -> str:
    if not isinstance(value, str):
        raise InstallInputError(f"{where}: '{field}' must be a string, got {value!r}")
    if not optional and not value.strip():
        raise InstallInputError(f"{where}: '{field}' must be a non-empty string")
    return value


def _discover_from_manifest(types_to_scan: list[PackageType]) -> list[PackageInfo]:
    """Read packages from manifest.yaml (new format: packages.skills, packages.agents, etc.)."""
    try:
        manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise InstallInputError(f"{MANIFEST_PATH}: malformed YAML: {exc}") from exc
    if not isinstance(manifest, dict):
        raise InstallInputError(f"{MANIFEST_PATH}: root must be a mapping, got {type(manifest).__name__}")
    packages_section = manifest.get("packages")
    if not isinstance(packages_section, dict):
        raise InstallInputError(
            f"{MANIFEST_PATH}: 'packages' must be a mapping, got {type(packages_section).__name__}"
        )
    packages: list[PackageInfo] = []

    for pt in types_to_scan:
        entries = packages_section.get(pt.manifest_section, [])
        if not isinstance(entries, list):
            raise InstallInputError(
                f"{MANIFEST_PATH}: packages.{pt.manifest_section} must be a list, "
                f"got {type(entries).__name__}"
            )
        for idx, entry in enumerate(entries):
            where = f"{MANIFEST_PATH}: packages.{pt.manifest_section}[{idx}]"
            if not isinstance(entry, dict):
                raise InstallInputError(f"{where}: entry must be a mapping, got {type(entry).__name__}")
            name = _require_str(entry.get("name"), where, "name")
            where = f"{where} ({name})"
            rel_path = _require_str(entry.get("path"), where, "path")
            version = entry.get("version", "0.0.0")
            if not isinstance(version, str) or not validate_version(version):
                raise InstallInputError(f"{where}: 'version' must have the form X.Y.Z, got {version!r}")
            description = _require_str(entry.get("description", ""), where, "description", optional=True)
            source = REPO_ROOT / rel_path
            if not source.is_dir():
                raise InstallInputError(f"{where}: declared source directory does not exist: {source}")
            packages.append(PackageInfo(
                name=name,
                version=version,
                description=description,
                source_path=source,
                pkg_type=pt,
            ))

    return packages


def _discover_from_definition_files(types_to_scan: list[PackageType]) -> list[PackageInfo]:
    """Fallback: parse definition files directly from type directories."""
    console.print("[dim]No manifest found — parsing definition files directly[/dim]")
    packages: list[PackageInfo] = []

    for pt in types_to_scan:
        repo_dir = pt.repo_dir
        if not repo_dir.is_dir():
            continue

        for pkg_dir in sorted(repo_dir.iterdir()):
            def_file = pkg_dir / pt.definition_file
            if not pkg_dir.is_dir() or not def_file.exists():
                continue

            content = def_file.read_text(encoding="utf-8")
            try:
                meta = parse_frontmatter(content)
            except ValueError as exc:
                raise InstallInputError(f"{def_file}: invalid frontmatter: {exc}") from exc

            name = _require_str(meta.get("name"), str(def_file), "name")
            version = extract_version(meta) or "0.0.0"
            if not validate_version(version):
                raise InstallInputError(f"{def_file}: version must have the form X.Y.Z, got {version!r}")
            description = meta.get("description", "")
            if not isinstance(description, str):
                raise InstallInputError(f"{def_file}: 'description' must be a string")
            packages.append(PackageInfo(
                name=name,
                version=version,
                description=description.strip(),
                source_path=pkg_dir,
                pkg_type=pt,
            ))

    return packages


# ---------------------------------------------------------------------------
# Installed version detection
# ---------------------------------------------------------------------------


def get_installed_version(
    install_dir: Path, pkg_name: str, pkg_type: PackageType,
) -> str | None:
    """Read version from an installed package's definition file, or None if not installed."""
    if pkg_type.key in BODY_ONLY_TYPES:
        # Body-only types are single .md files, not directories
        installed_file = install_dir / f"{pkg_name}.md"
        if not installed_file.exists():
            return None
        content = installed_file.read_text(encoding="utf-8")
        try:
            meta = parse_frontmatter(content)
        except ValueError:
            return "0.0.0"
        return extract_version(meta) or "0.0.0"

    def_file = install_dir / pkg_name / pkg_type.definition_file
    if not def_file.exists():
        return None

    content = def_file.read_text(encoding="utf-8")
    try:
        meta = parse_frontmatter(content)
    except ValueError:
        return "0.0.0"

    return extract_version(meta) or "0.0.0"


# ---------------------------------------------------------------------------
# Install plan building
# ---------------------------------------------------------------------------


def build_install_plans(
    packages: list[PackageInfo],
    claude_dir: Path,
    *,
    reinstall: bool = False,
) -> list[InstallPlan]:
    """Determine install/upgrade/reinstall/skip action for each package."""
    plans: list[InstallPlan] = []

    for pkg in packages:
        install_dir = pkg.pkg_type.claude_install_dir(claude_dir)
        if pkg.pkg_type.key in BODY_ONLY_TYPES:
            target = install_dir / f"{pkg.name}.md"
        else:
            target = install_dir / pkg.name

        installed_version = get_installed_version(install_dir, pkg.name, pkg.pkg_type)

        # Symlinks are externally managed — skip (only for directory-based types)
        if pkg.pkg_type.key not in BODY_ONLY_TYPES and target.is_symlink():
            console.print(
                f"[yellow]Skipping {pkg.name} — {target} is a symlink (externally managed)[/yellow]"
            )
            continue

        if installed_version is None:
            action = InstallAction.INSTALL
        elif is_newer(pkg.version, installed_version):
            action = InstallAction.UPGRADE
        elif reinstall:
            action = InstallAction.REINSTALL
        else:
            action = InstallAction.SKIP

        plans.append(InstallPlan(
            package=pkg,
            action=action,
            installed_version=installed_version,
            target_path=target,
        ))

    return plans


# ---------------------------------------------------------------------------
# TUI display
# ---------------------------------------------------------------------------


def display_plans(plans: list[InstallPlan]) -> None:
    """Display package table with color-coded actions, grouped by type."""
    table = Table(title="Available Packages", show_lines=False)
    table.add_column("#", style="bold", width=4)
    table.add_column("Type", justify="center")
    table.add_column("Name", style="cyan")
    table.add_column("Repo Version", justify="center")
    table.add_column("Installed", justify="center")
    table.add_column("Action", justify="center")

    action_styles = {
        InstallAction.INSTALL: "[green]install[/green]",
        InstallAction.UPGRADE: "[yellow]upgrade[/yellow]",
        InstallAction.REINSTALL: "[blue]reinstall[/blue]",
        InstallAction.SKIP: "[dim]skip[/dim]",
    }

    for i, plan in enumerate(plans, 1):
        installed = plan.installed_version or "—"
        action_text = action_styles[plan.action]
        type_color = TYPE_COLORS.get(plan.package.pkg_type.key, "white")
        type_label = f"[{type_color}]{plan.package.pkg_type.key}[/{type_color}]"

        table.add_row(
            str(i),
            type_label,
            plan.package.name,
            plan.package.version,
            installed,
            action_text,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Selection parsing
# ---------------------------------------------------------------------------


def parse_selection(raw: str, total: int) -> list[int]:
    """Parse user selection string into list of 0-based indices.

    Accepts: '1,3,5-8,all' or 'q' to quit.
    """
    raw = raw.strip().lower()
    if raw in ("q", "quit", "exit"):
        return []
    if raw == "all":
        return list(range(total))

    indices: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start = int(start_str)
            end = int(end_str)
            if start < 1 or end > total or start > end:
                raise ValueError(f"Range {part} out of bounds (1-{total})")
            indices.extend(range(start - 1, end))
        else:
            num = int(part)
            if num < 1 or num > total:
                raise ValueError(f"Number {num} out of bounds (1-{total})")
            indices.append(num - 1)

    return sorted(set(indices))


# ---------------------------------------------------------------------------
# Package installation
# ---------------------------------------------------------------------------


def copy_package(source: Path, target: Path) -> int:
    """Copy package directory, excluding unwanted files. Returns file count."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    count = 0
    for src_file in sorted(source.rglob("*")):
        if not src_file.is_file():
            continue
        if should_exclude(src_file, source):
            continue

        rel = src_file.relative_to(source)
        dst_file = target / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        count += 1

    return count


def install_body_only(source_path: Path, target_path: Path, pkg_type: PackageType) -> int:
    """Install a body-only package (rules, commands) — extract body, write single .md file."""
    def_file = source_path / pkg_type.definition_file
    content = def_file.read_text(encoding="utf-8")
    body = extract_body(content)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(body, encoding="utf-8")
    return 1


def install_utility(source: Path, target: Path, pkg_type: PackageType) -> int:
    """Install a utility package — copy directory and chmod +x entry_point."""
    count = copy_package(source, target)

    # Read definition file for entry_point
    def_file = source / pkg_type.definition_file
    if def_file.exists():
        content = def_file.read_text(encoding="utf-8")
        try:
            meta = parse_frontmatter(content)
        except ValueError:
            return count
        utility_meta = meta.get("utility", {})
        if isinstance(utility_meta, dict):
            entry_point = utility_meta.get("entry_point")
            if entry_point:
                ep_path = target / entry_point
                if ep_path.exists():
                    current = ep_path.stat().st_mode
                    ep_path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return count


def install_hook(source: Path, target: Path, claude_dir: Path) -> int:
    """Install a hook package — copy files and register in settings.json."""
    _install_hook_to_settings(source, claude_dir)
    # Count handler files that were copied (HOOK.md excluded by hooks_installer)
    target_dir = claude_dir / "hooks" / target.name
    return sum(1 for f in target_dir.rglob("*") if f.is_file()) if target_dir.exists() else 0


def resolve_preset_packages(
    source_path: Path, pkg_type: PackageType,
) -> dict[str, list[str]]:
    """Read a preset's PRESET.md and return {type_key: [package_names]}.

    The preset frontmatter has:
      preset:
        packages:
          skills: [{name: x}, ...]
          hooks: [{name: y}, ...]
    """
    def_file = source_path / pkg_type.definition_file
    content = def_file.read_text(encoding="utf-8")
    meta = parse_frontmatter(content)
    preset_meta = meta.get("preset", {})
    packages_meta = preset_meta.get("packages", {})

    result: dict[str, list[str]] = {}
    for section, entries in packages_meta.items():
        # section is e.g. "skills", "hooks" — map to type key
        type_key = _section_to_type_key(section)
        if type_key is not None and TYPES[type_key].native:
            raise InstallInputError(
                f"{def_file}: presets cannot bundle native {section}; install them explicitly "
                "with --type extension --platform <host> --action install"
            )
        if type_key and isinstance(entries, list):
            names = [e["name"] for e in entries if isinstance(e, dict) and "name" in e]
            if names:
                result[type_key] = names
    return result


def install_preset(
    plan: InstallPlan, claude_dir: Path,
) -> tuple[int, list[str]]:
    """Validate bundled package discovery, then copy and install the preset.

    Returns (file_count, list of sub-package install messages).
    """
    pkg = plan.package
    messages: list[str] = []

    # Resolve bundled packages
    bundled = resolve_preset_packages(pkg.source_path, pkg.pkg_type)
    if not bundled:
        return copy_package(pkg.source_path, plan.target_path), messages

    # Discover all available packages for resolution
    all_packages = discover_packages()
    pkg_index: dict[tuple[str, str], PackageInfo] = {
        (p.pkg_type.key, p.name): p for p in all_packages
    }
    file_count = copy_package(pkg.source_path, plan.target_path)

    for type_key, names in bundled.items():
        for name in names:
            sub_pkg = pkg_index.get((type_key, name))
            if sub_pkg is None:
                messages.append(
                    f"  [yellow]Warning: preset references {type_key}/{name} but it was not found[/yellow]"
                )
                continue

            install_dir = sub_pkg.pkg_type.claude_install_dir(claude_dir)
            if sub_pkg.pkg_type.key in BODY_ONLY_TYPES:
                target = install_dir / f"{name}.md"
            else:
                target = install_dir / name

            # Skip symlinked packages (externally managed)
            if sub_pkg.pkg_type.key not in BODY_ONLY_TYPES and target.is_symlink():
                messages.append(
                    f"  [dim]{type_key}/{name} is a symlink (externally managed), skipping[/dim]"
                )
                continue

            installed_ver = get_installed_version(install_dir, name, sub_pkg.pkg_type)

            # Skip if already at same or newer version
            if installed_ver is not None and not is_newer(sub_pkg.version, installed_ver):
                messages.append(
                    f"  [dim]{type_key}/{name} v{installed_ver} already installed[/dim]"
                )
                continue

            sub_plan = InstallPlan(
                package=sub_pkg,
                action=InstallAction.UPGRADE if installed_ver else InstallAction.INSTALL,
                installed_version=installed_ver,
                target_path=target,
            )
            sub_count = install_package(sub_plan, claude_dir)
            file_count += sub_count
            action_word = "Upgraded" if installed_ver else "Installed"
            type_color = TYPE_COLORS.get(type_key, "white")
            messages.append(
                f"  {action_word} [{type_color}]{type_key}[/] "
                f"[cyan]{name}[/cyan] v{sub_pkg.version} ({sub_count} files)"
            )

    return file_count, messages


def install_package(plan: InstallPlan, claude_dir: Path | None = None) -> int:
    """Install a single package according to its type. Returns file count."""
    pkg = plan.package
    key = pkg.pkg_type.key

    if key in BODY_ONLY_TYPES:
        return install_body_only(pkg.source_path, plan.target_path, pkg.pkg_type)
    if key == "utility":
        return install_utility(pkg.source_path, plan.target_path, pkg.pkg_type)
    if key == "hook" and claude_dir is not None:
        return install_hook(pkg.source_path, plan.target_path, claude_dir)
    # skill, agent, preset (without resolution) — copy full directory
    return copy_package(pkg.source_path, plan.target_path)


_ACTION_LABELS: dict[InstallAction, str] = {
    InstallAction.INSTALL: "Installed",
    InstallAction.UPGRADE: "Upgraded",
    InstallAction.REINSTALL: "Reinstalled",
}


def execute_plans(
    plans: list[InstallPlan], selected: list[int], claude_dir: Path | None = None,
) -> None:
    """Execute selected installation plans."""
    if claude_dir is None:
        claude_dir = DEFAULT_CLAUDE_DIR

    to_install = [plans[i] for i in selected if plans[i].action != InstallAction.SKIP]

    if not to_install:
        console.print("[dim]Nothing to install — all selected packages are up to date.[/dim]")
        return

    with Progress(console=console) as progress:
        task = progress.add_task("Installing packages...", total=len(to_install))

        for plan in to_install:
            progress.update(task, description=f"Installing {plan.package.name}...")

            if plan.package.pkg_type.key == "preset":
                file_count, sub_messages = install_preset(plan, claude_dir)
            else:
                file_count = install_package(plan, claude_dir)
                sub_messages = []

            progress.advance(task)
            label = _ACTION_LABELS.get(plan.action, "Installed")
            console.print(
                f"  {label} [{TYPE_COLORS.get(plan.package.pkg_type.key, 'white')}]"
                f"{plan.package.pkg_type.key}[/] "
                f"[cyan]{plan.package.name}[/cyan] "
                f"v{plan.package.version} ({file_count} files)"
            )
            for msg in sub_messages:
                console.print(msg)

    # Summary
    console.print()
    summary = Table(title="Installation Summary", show_lines=False)
    summary.add_column("Type")
    summary.add_column("Package", style="cyan")
    summary.add_column("Action")
    summary.add_column("Version")

    for plan in to_install:
        label = _ACTION_LABELS.get(plan.action, "installed").lower()
        type_color = TYPE_COLORS.get(plan.package.pkg_type.key, "white")
        if plan.action == InstallAction.UPGRADE:
            ver = f"{plan.installed_version} -> {plan.package.version}"
        else:
            ver = plan.package.version
        summary.add_row(
            f"[{type_color}]{plan.package.pkg_type.key}[/{type_color}]",
            plan.package.name,
            label,
            ver,
        )

    console.print(summary)
    console.print(
        Panel(
            "Restart Claude Code to load the new packages.",
            title="Done",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Profile support
# ---------------------------------------------------------------------------


def load_profiles() -> dict[str, dict[str, Any]]:
    """Load profiles from profiles.yaml."""
    if not PROFILES_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(PROFILES_PATH.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise InstallInputError(f"{PROFILES_PATH}: malformed YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise InstallInputError(f"{PROFILES_PATH}: root must be a mapping, got {type(data).__name__}")
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise InstallInputError(f"{PROFILES_PATH}: 'profiles' must be a mapping")
    for pname, profile in profiles.items():
        if not isinstance(profile, dict):
            raise InstallInputError(f"{PROFILES_PATH}: profile '{pname}' must be a mapping")
    return profiles


def resolve_profile_packages(
    profile_name: str,
    profiles: dict[str, dict[str, Any]],
    visited: set[str] | None = None,
) -> dict[str, set[str]]:
    """Resolve a profile into {type_key: {pkg_names}} with include-chain expansion.

    Returns a dict mapping package type keys to sets of package names.
    If the profile has 'all: true', returns an empty dict (caller treats as all packages).
    """
    if visited is None:
        visited = set()
    if profile_name in visited:
        return {}
    visited.add(profile_name)

    profile = profiles.get(profile_name)
    if profile is None:
        raise InstallInputError(f"Unknown profile: {profile_name}")

    if profile.get("all", False):
        return {}  # sentinel: caller installs everything

    result: dict[str, set[str]] = {}

    # Resolve includes first
    for included in profile.get("includes", []):
        included_pkgs = resolve_profile_packages(included, profiles, visited)
        if not included_pkgs and profiles.get(included, {}).get("all", False):
            return {}  # included profile is "all"
        for type_key, names in included_pkgs.items():
            result.setdefault(type_key, set()).update(names)

    # Add this profile's packages
    packages_spec = profile.get("packages", {})
    if not isinstance(packages_spec, dict):
        raise InstallInputError(f"Profile '{profile_name}': 'packages' must be a mapping")
    for type_key, names in packages_spec.items():
        # type_key in profiles.yaml matches manifest_section (e.g., "skills", "agents")
        # Map to PackageType key
        pkg_type_key = _section_to_type_key(type_key)
        if pkg_type_key is None:
            raise InstallInputError(f"Profile '{profile_name}': unknown package type section '{type_key}'")
        if TYPES[pkg_type_key].native:
            raise InstallInputError(
                f"Profile '{profile_name}': profiles cannot include native {type_key}; install them "
                "explicitly with --type extension --platform <host> --action install"
            )
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise InstallInputError(
                f"Profile '{profile_name}': packages.{type_key} must be a list of names"
            )
        result.setdefault(pkg_type_key, set()).update(names)

    return result


def _section_to_type_key(section: str) -> str | None:
    """Map manifest section name to PackageType key."""
    for pt in TYPES.values():
        if pt.manifest_section == section:
            return pt.key
    return None


def filter_by_profile(
    packages: list[PackageInfo], profile_name: str,
) -> list[PackageInfo]:
    """Filter packages to those matching a profile."""
    profiles = load_profiles()
    resolved = resolve_profile_packages(profile_name, profiles)

    # Empty dict from an "all: true" profile means install everything
    profile_data = profiles.get(profile_name, {})
    if profile_data.get("all", False) or (
        not resolved
        and any(
            profiles.get(inc, {}).get("all", False)
            for inc in profile_data.get("includes", [])
        )
    ):
        return packages

    known = {(p.pkg_type.key, p.name) for p in packages}
    missing = sorted(
        f"{type_key}:{name}"
        for type_key, names in resolved.items()
        for name in names
        if (type_key, name) not in known
    )
    if missing:
        raise InstallInputError(
            f"Profile '{profile_name}' references unknown packages: {', '.join(missing)}"
        )

    return [
        pkg for pkg in packages
        if pkg.pkg_type.key in resolved and pkg.name in resolved[pkg.pkg_type.key]
    ]


# ---------------------------------------------------------------------------
# Platform adapter installation
# ---------------------------------------------------------------------------

_PLATFORM_COPY_MAP: dict[str, str] = {
    "cursor": ".cursor",
    "gemini": ".gemini",
}


def install_to_platform(target: str, project_dir: Path) -> int:
    """Generate adapter output and copy to project directory for non-Claude targets."""
    from scripts.generate_adapters import _ADAPTERS, load_packages

    try:
        packages = load_packages()
    except FrontmatterError as exc:
        raise InstallInputError(str(exc)) from exc
    total = sum(len(pkgs) for pkgs in packages.values())
    if total == 0:
        console.print("[red]No packages found.[/red]")
        return 1

    adapter_cls = _ADAPTERS[target]
    tmp_dir = tempfile.mkdtemp(prefix="armory-adapter-")
    tmp_path = Path(tmp_dir)

    try:
        adapter = adapter_cls(tmp_path, dry_run=False)
        adapter.generate(packages)

        if target in _PLATFORM_COPY_MAP:
            src = tmp_path / _PLATFORM_COPY_MAP[target]
            dst = project_dir / _PLATFORM_COPY_MAP[target]
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        elif target == "codex":
            # Copy AGENTS.md and subdirectories to project root
            for item in tmp_path.iterdir():
                dst = project_dir / item.name
                if item.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(item, dst)
                else:
                    shutil.copy2(item, dst)

        console.print(f"[green]Installed {target} adapter to {project_dir}[/green]")
        console.print(f"  {adapter.report()}")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _validate_extension_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Require the complete explicit lifecycle flag set for native extensions only."""
    lifecycle = {
        "--platform": args.platform,
        "--name": args.name,
        "--action": args.action,
        "--target-root": args.target_root,
        "--yes": args.yes,
    }
    if args.pkg_type != "extension":
        given = [flag for flag, value in lifecycle.items() if value]
        if given:
            parser.error(f"{', '.join(given)} apply only to --type extension")
        return
    missing = [flag for flag, value in lifecycle.items() if not value]
    if missing:
        parser.error(
            f"--type extension requires {', '.join(missing)}; native extensions are never "
            "installed interactively, by profile or as part of 'all'"
        )
    legacy = {
        "--profile": args.profile,
        "--reinstall": args.reinstall,
        "--list-profiles": args.list_profiles,
        "--target": args.target,
        "--project-dir": args.project_dir,
    }
    conflicting = [flag for flag, value in legacy.items() if value]
    if conflicting:
        parser.error(f"{', '.join(conflicting)} cannot be combined with --type extension")


def run_extension_action(args: argparse.Namespace) -> int:
    """Run one explicit native extension lifecycle action."""
    if os.name != "posix":
        console.print(
            Text(
                "Native extension lifecycle requires a POSIX host; "
                "legacy installation remains available.",
                style="red",
            )
        )
        return 1
    from scripts.extension_lifecycle import LifecycleError, run_action

    try:
        message = run_action(args.action, args.platform, args.name, args.target_root, TYPES["extension"].repo_dir)
    except (BuildError, LifecycleError) as exc:
        console.print(Text(f"Error: {exc}", style="red"))
        return 1
    console.print(Text(message))
    return 0


def main() -> int:
    """Main entry point for the TUI installer."""
    parser = argparse.ArgumentParser(description="Install armory packages to ~/.claude/")
    parser.add_argument(
        "--reinstall",
        action="store_true",
        help="Allow reinstalling packages that are already at the same version",
    )
    parser.add_argument(
        "--type",
        dest="pkg_type",
        choices=list(TYPES.keys()),
        help="Filter to a single package type",
    )
    parser.add_argument(
        "--profile",
        help="Install packages matching a profile from profiles.yaml",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="Show available install profiles and exit",
    )
    parser.add_argument(
        "--target",
        choices=["claude", "cursor", "codex", "gemini"],
        help="Target platform for copy/adapter installs (default: claude)",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        help="Project directory for non-Claude targets (default: current directory)",
    )
    parser.add_argument(
        "--platform",
        choices=list(NATIVE_HOSTS),
        help="Native host for an --type extension lifecycle action",
    )
    parser.add_argument("--name", help="Registered extension feature name (with --type extension)")
    parser.add_argument(
        "--action",
        choices=list(NATIVE_ACTIONS),
        help="Extension lifecycle action (with --type extension)",
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        help=(
            "Host configuration root to install into: the OMP agent directory or the Claude Code "
            "configuration directory (with --type extension)"
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm a noninteractive extension lifecycle mutation",
    )
    args = parser.parse_args()
    _validate_extension_args(parser, args)
    if args.pkg_type == "extension":
        return run_extension_action(args)

    if args.list_profiles:
        try:
            profiles = load_profiles()
        except InstallInputError as exc:
            console.print(Text(f"Error: {exc}", style="red"))
            return 1
        if not profiles:
            console.print("[red]No profiles found in profiles.yaml[/red]")
            return 1
        table = Table(title="Install Profiles", show_lines=False)
        table.add_column("Profile", style="cyan")
        table.add_column("Description")
        table.add_column("Includes", style="dim")
        for name, profile in profiles.items():
            includes = ", ".join(profile.get("includes", []))
            desc = profile.get("description", "")
            if profile.get("all"):
                desc += " [bold](all packages)[/bold]"
            table.add_row(name, desc, includes or "—")
        console.print(table)
        return 0

    target = args.target or "claude"
    if target != "claude":
        try:
            return install_to_platform(target, args.project_dir or Path.cwd())
        except InstallInputError as exc:
            console.print(Text(f"Error: {exc}", style="red"))
            return 1

    console.print(Panel("armory installer", border_style="blue"))

    # Discover
    type_filter = TYPES.get(args.pkg_type) if args.pkg_type else None
    try:
        # Profiles and presets resolve packages across types before any writes.
        packages = discover_packages(
            None if args.profile or args.pkg_type == "preset" else type_filter
        )
        # Native extensions only ever install through the explicit lifecycle above.
        packages = [p for p in packages if not p.pkg_type.native]
        if args.profile:
            packages = filter_by_profile(packages, args.profile)
        if type_filter:
            packages = [p for p in packages if p.pkg_type == type_filter]
    except InstallInputError as exc:
        console.print(Text(f"Error: {exc}", style="red"))
        return 1

    if not packages:
        console.print("[red]No packages found.[/red]")
        return 1

    # Sort by type then name for grouped display
    packages.sort(key=lambda p: (p.pkg_type.key, p.name))

    claude_dir = DEFAULT_CLAUDE_DIR
    claude_dir.mkdir(parents=True, exist_ok=True)

    # Build plans
    plans = build_install_plans(packages, claude_dir, reinstall=args.reinstall)
    if not plans:
        console.print("[dim]No installable packages found.[/dim]")
        return 0

    # Display
    display_plans(plans)

    # Count actionable
    actionable = [i for i, p in enumerate(plans) if p.action != InstallAction.SKIP]
    if not actionable:
        console.print("[dim]All packages are up to date. Use --reinstall to force reinstallation.[/dim]")
        return 0

    # Select
    while True:
        raw = Prompt.ask(
            f"\nEnter package numbers to install ([green]1,3,5-8[/green], [green]all[/green], or [red]q[/red] to quit)"
        )
        if raw.strip().lower() in ("q", "quit", "exit"):
            console.print("[dim]Cancelled.[/dim]")
            return 0

        try:
            selected = parse_selection(raw, len(plans))
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            continue

        if not selected:
            console.print("[dim]No packages selected.[/dim]")
            continue

        break

    # Filter to actionable selections
    selected_actionable = [i for i in selected if plans[i].action != InstallAction.SKIP]
    if not selected_actionable:
        console.print("[dim]All selected packages are already up to date.[/dim]")
        return 0

    # Confirm
    names = ", ".join(plans[i].package.name for i in selected_actionable)
    console.print(f"\nWill install/upgrade/reinstall: [cyan]{names}[/cyan]")
    confirm = Prompt.ask("Proceed?", choices=["y", "n"], default="y")
    if confirm != "y":
        console.print("[dim]Cancelled.[/dim]")
        return 0

    # Execute
    execute_plans(plans, selected_actionable, claude_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
