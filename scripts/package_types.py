#!/usr/bin/env python3
"""Package type registry — single source of truth for all armory package types."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hosts with a native plugin lifecycle (scripts/extension_lifecycle.py). The
# legacy copy installer targets Claude Code's ~/.claude tree only.
NATIVE_HOSTS: tuple[str, ...] = ("omp", "claude")
NATIVE_ACTIONS: tuple[str, ...] = ("install", "update", "disable", "remove")


class UnsupportedInstallError(ValueError):
    """A package type has no installation mechanism for the requested host."""


@dataclass(frozen=True)
class PackageType:
    """Metadata for a package type (skill, agent, hook, etc.).

    ``claude_subdir`` names the ~/.claude subdirectory the legacy copy
    installer writes to; it is None for types without a copy installation.
    ``native_hosts`` lists hosts that load the type as a native plugin
    through an explicit per-host lifecycle. Native types are never part of
    default, profile, preset or "all" installs.
    """

    key: str
    dir_name: str
    definition_file: str
    claude_subdir: str | None
    archive_ext: str
    required_frontmatter: tuple[str, ...]
    manifest_section: str
    native_hosts: tuple[str, ...] = ()

    @property
    def repo_dir(self) -> Path:
        return REPO_ROOT / self.dir_name

    @property
    def native(self) -> bool:
        return bool(self.native_hosts)

    def claude_install_dir(self, claude_dir: Path) -> Path:
        """Return the legacy copy-install directory, refusing native types."""
        if self.claude_subdir is None:
            raise UnsupportedInstallError(
                f"{self.key} packages have no ~/.claude copy installation; "
                f"use --type {self.key} --platform <{'|'.join(self.native_hosts)}> "
                "with an explicit --action and --target-root"
            )
        return claude_dir / self.claude_subdir


TYPES: dict[str, PackageType] = {
    "skill": PackageType(
        key="skill",
        dir_name="skills",
        definition_file="SKILL.md",
        claude_subdir="skills",
        archive_ext=".skill",
        required_frontmatter=("name", "description"),
        manifest_section="skills",
    ),
    "agent": PackageType(
        key="agent",
        dir_name="agents",
        definition_file="AGENT.md",
        claude_subdir="agents",
        archive_ext=".agent",
        required_frontmatter=("name", "description", "model", "color"),
        manifest_section="agents",
    ),
    "hook": PackageType(
        key="hook",
        dir_name="hooks",
        definition_file="HOOK.md",
        claude_subdir="hooks",
        archive_ext=".hook",
        required_frontmatter=("name", "description", "hook"),
        manifest_section="hooks",
    ),
    "rule": PackageType(
        key="rule",
        dir_name="rules",
        definition_file="RULE.md",
        claude_subdir="rules",
        archive_ext=".rule",
        required_frontmatter=("name", "description"),
        manifest_section="rules",
    ),
    "command": PackageType(
        key="command",
        dir_name="commands",
        definition_file="COMMAND.md",
        claude_subdir="commands",
        archive_ext=".command",
        required_frontmatter=("name", "description"),
        manifest_section="commands",
    ),
    "utility": PackageType(
        key="utility",
        dir_name="utilities",
        definition_file="UTILITY.md",
        claude_subdir="utilities",
        archive_ext=".utility",
        required_frontmatter=("name", "description", "utility"),
        manifest_section="utilities",
    ),
    "preset": PackageType(
        key="preset",
        dir_name="presets",
        definition_file="PRESET.md",
        claude_subdir="presets",
        archive_ext=".preset",
        required_frontmatter=("name", "description", "preset"),
        manifest_section="presets",
    ),
    "extension": PackageType(
        key="extension",
        dir_name="extensions",
        definition_file="EXTENSION.md",
        claude_subdir=None,
        archive_ext=".extension",
        required_frontmatter=("name", "description", "extension"),
        manifest_section="extensions",
        native_hosts=NATIVE_HOSTS,
    ),
}

MANIFEST_PATH = REPO_ROOT / "manifest.yaml"

EXCLUDE_NAMES: frozenset[str] = frozenset({
    "__pycache__", "node_modules", ".DS_Store", ".git", "evals",
})
EXCLUDE_SUFFIXES: frozenset[str] = frozenset({".pyc"})


def detect_type_from_path(pkg_path: Path) -> PackageType:
    """Auto-detect package type from directory path."""
    resolved = pkg_path.resolve()
    for pkg_type in TYPES.values():
        if pkg_type.repo_dir == resolved.parent or resolved.is_relative_to(pkg_type.repo_dir):
            return pkg_type
    msg = f"Cannot detect package type from path: {pkg_path}"
    raise ValueError(msg)


def should_exclude(path: Path, root: Path) -> bool:
    """Check if a path should be excluded from copying/packaging."""
    relative = path.relative_to(root)
    for part in relative.parts:
        if part in EXCLUDE_NAMES:
            return True
    return path.suffix in EXCLUDE_SUFFIXES
