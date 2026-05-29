#!/usr/bin/env python3
"""Generate platform-specific adapter output from armory package definitions.

Transforms Claude Code-native packages (SKILL.md, AGENT.md, RULE.md, COMMAND.md)
into platform-specific formats for Cursor, Codex, and Gemini CLI.

Usage:
    uv run scripts/generate_adapters.py                           # All platforms
    uv run scripts/generate_adapters.py --platform cursor         # Cursor only
    uv run scripts/generate_adapters.py --platform codex          # Codex only
    uv run scripts/generate_adapters.py --platform gemini         # Gemini only
    uv run scripts/generate_adapters.py --platform cursor --type rules --type skills
    uv run scripts/generate_adapters.py --dry-run                 # Preview only
"""

from __future__ import annotations

import argparse
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path for direct script execution.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml

from scripts.frontmatter import extract_body, parse_frontmatter
from scripts.package_types import REPO_ROOT, TYPES

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PackageContent:
    """Parsed package with frontmatter and body separated."""

    name: str
    pkg_type: str
    frontmatter: dict[str, Any]
    body: str
    path: Path
    references: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Language → glob mapping
# ---------------------------------------------------------------------------

_LANGUAGE_GLOBS: dict[str, str] = {
    "python": "**/*.py",
    "typescript": "**/*.{ts,tsx}",
    "javascript": "**/*.{js,jsx}",
    "go": "**/*.go",
    "rust": "**/*.rs",
    "java": "**/*.java",
    "ruby": "**/*.rb",
    "c": "**/*.{c,h}",
    "cpp": "**/*.{cpp,hpp,cc,hh}",
    "csharp": "**/*.cs",
    "swift": "**/*.swift",
    "kotlin": "**/*.{kt,kts}",
    "shell": "**/*.{sh,bash,zsh}",
    "sql": "**/*.sql",
    "html": "**/*.{html,htm}",
    "css": "**/*.{css,scss,less}",
    "yaml": "**/*.{yaml,yml}",
    "json": "**/*.json",
    "markdown": "**/*.md",
    "toml": "**/*.toml",
}


def language_to_globs(languages: list[str]) -> list[str]:
    """Map language identifiers to glob patterns.

    Returns empty list for wildcard or unrecognized languages.
    """
    if not languages or languages == ["*"]:
        return []
    globs: list[str] = []
    for lang in languages:
        normalized = lang.lower().strip().lstrip("*.")
        pattern = _LANGUAGE_GLOBS.get(normalized)
        if pattern:
            globs.append(pattern)
    return globs


def truncate_description(description: str, max_chars: int = 200) -> str:
    """Truncate description to max_chars, preserving word boundaries."""
    description = description.strip()
    if len(description) <= max_chars:
        return description
    if max_chars <= 3:
        return "." * max_chars
    truncated = description[: max_chars - 3].rsplit(" ", 1)[0]
    return truncated.rstrip(".,;:") + "..."


# ---------------------------------------------------------------------------
# Package loading
# ---------------------------------------------------------------------------


def _load_references(pkg_dir: Path) -> dict[str, str]:
    """Load all reference markdown files from a package's references/ directory."""
    refs_dir = pkg_dir / "references"
    if not refs_dir.is_dir():
        return {}
    refs: dict[str, str] = {}
    for ref_file in sorted(refs_dir.iterdir()):
        if ref_file.suffix == ".md" and ref_file.is_file():
            refs[ref_file.name] = ref_file.read_text(encoding="utf-8")
    return refs


def load_packages(
    type_filter: list[str] | None = None,
) -> dict[str, list[PackageContent]]:
    """Load all packages, grouped by type key.

    Args:
        type_filter: If set, only load these package types (e.g. ["skill", "rule"]).
    """
    packages: dict[str, list[PackageContent]] = {}

    for type_key, pkg_type in TYPES.items():
        if type_filter and type_key not in type_filter:
            continue

        if not pkg_type.repo_dir.is_dir():
            continue

        type_packages: list[PackageContent] = []
        for pkg_dir in sorted(pkg_type.repo_dir.iterdir()):
            def_file = pkg_dir / pkg_type.definition_file
            if not pkg_dir.is_dir() or not def_file.exists():
                continue

            content = def_file.read_text(encoding="utf-8")
            try:
                fm = parse_frontmatter(content)
            except ValueError:
                print(
                    f"WARNING: {def_file} has invalid frontmatter, skipping",
                    file=sys.stderr,
                )
                continue

            name = fm.get("name", "")
            if not name:
                continue

            body = extract_body(content)
            references = _load_references(pkg_dir)

            type_packages.append(
                PackageContent(
                    name=name,
                    pkg_type=type_key,
                    frontmatter=fm,
                    body=body,
                    path=pkg_dir,
                    references=references,
                )
            )

        if type_packages:
            packages[type_key] = type_packages

    return packages


def inline_references(pkg: PackageContent) -> str:
    """Combine package body with all reference file contents."""
    parts = [pkg.body]
    for ref_name, ref_content in pkg.references.items():
        parts.append(
            f"\n\n---\n\n## Reference: {ref_name.removesuffix('.md')}\n\n{ref_content}"
        )
    return "\n".join(parts)


def extract_language_targets(fm: dict[str, Any]) -> list[str]:
    """Extract language targets from frontmatter metadata."""
    metadata = fm.get("metadata", {})
    if isinstance(metadata, dict):
        targets = metadata.get("language_targets")
        if isinstance(targets, list):
            return targets
        applies_to = metadata.get("applies_to")
        if isinstance(applies_to, dict):
            langs = applies_to.get("languages")
            if isinstance(langs, list):
                return langs
    return []


# ---------------------------------------------------------------------------
# Base adapter
# ---------------------------------------------------------------------------


class AdapterGenerator(ABC):
    """Base class for platform-specific adapters."""

    platform: str

    def __init__(self, output_dir: Path, *, dry_run: bool = False) -> None:
        self.output_dir = output_dir
        self.dry_run = dry_run
        self._files_written: list[Path] = []

    def _write(self, path: Path, content: str) -> None:
        """Write content to path (or log in dry-run mode)."""
        self._files_written.append(path)
        if self.dry_run:
            print(f"  [dry-run] {path.relative_to(REPO_ROOT)}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _copy_dir(self, src: Path, dst: Path) -> None:
        """Copy directory tree (or log in dry-run mode)."""
        if self.dry_run:
            print(
                f"  [dry-run] copy {src.relative_to(REPO_ROOT)} → {dst.relative_to(REPO_ROOT)}"
            )
            return
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    @abstractmethod
    def generate(self, packages: dict[str, list[PackageContent]]) -> None:
        """Generate platform-specific output from loaded packages."""

    def report(self) -> str:
        """Return summary of files written."""
        return f"{self.platform}: {len(self._files_written)} files"

    def validate(self) -> list[str]:
        """Validate generated output. Returns list of error messages."""
        return []


# ---------------------------------------------------------------------------
# Cursor adapter
# ---------------------------------------------------------------------------


class CursorAdapter(AdapterGenerator):
    """Generate .cursor/rules/*.mdc and .cursor/commands/*.md."""

    platform = "cursor"

    def generate(self, packages: dict[str, list[PackageContent]]) -> None:
        rules_dir = self.output_dir / ".cursor" / "rules"
        commands_dir = self.output_dir / ".cursor" / "commands"

        # Skills → individual .mdc rules (alwaysApply: false)
        for pkg in packages.get("skill", []):
            content = self._build_mdc(pkg, always_apply=False)
            self._write(rules_dir / f"{pkg.name}.mdc", content)

        # Agents → individual .mdc rules (alwaysApply: false)
        for pkg in packages.get("agent", []):
            content = self._build_mdc(pkg, always_apply=False)
            self._write(rules_dir / f"{pkg.name}.mdc", content)

        # Rules → individual .mdc rules (alwaysApply: true)
        for pkg in packages.get("rule", []):
            content = self._build_mdc(pkg, always_apply=True)
            self._write(rules_dir / f"{pkg.name}.mdc", content)

        # Commands → .cursor/commands/*.md
        for pkg in packages.get("command", []):
            self._write(commands_dir / f"{pkg.name}.md", pkg.body)

        # Hooks, utilities, presets → skipped (no Cursor equivalent)
        for skipped_type in ("hook", "utility", "preset"):
            count = len(packages.get(skipped_type, []))
            if count:
                print(
                    f"  cursor: skipped {count} {skipped_type}(s) (no equivalent)",
                    file=sys.stderr,
                )

    def _build_mdc(self, pkg: PackageContent, *, always_apply: bool) -> str:
        """Build .mdc file content with YAML frontmatter + body."""
        description = truncate_description(pkg.frontmatter.get("description", ""))
        globs = language_to_globs(extract_language_targets(pkg.frontmatter))

        # Build frontmatter
        fm_parts: list[str] = [
            "---",
            f"description: {description}",
        ]
        if globs:
            fm_parts.append(f"globs: {', '.join(globs)}")
        fm_parts.append(f"alwaysApply: {'true' if always_apply else 'false'}")
        fm_parts.append("---")

        # Body: inline references for self-contained .mdc
        body = inline_references(pkg)

        return "\n".join(fm_parts) + "\n\n" + body

    def validate(self) -> list[str]:
        errors: list[str] = []
        for path in self._files_written:
            if not path.exists() or path.suffix != ".mdc":
                continue
            content = path.read_text(encoding="utf-8")
            if not content.startswith("---"):
                errors.append(f"cursor: {path.name} missing YAML frontmatter")
                continue
            # Check alwaysApply is present and boolean-valued
            if "alwaysApply:" not in content:
                errors.append(f"cursor: {path.name} missing alwaysApply field")
        return errors


# ---------------------------------------------------------------------------
# Codex adapter
# ---------------------------------------------------------------------------


class CodexAdapter(AdapterGenerator):
    """Generate AGENTS.md with hierarchical discovery for large package sets.

    Codex supports hierarchical AGENTS.md discovery: files in subdirectories are
    loaded when CWD matches. The root AGENTS.md stays under 32 KiB with condensed
    references; full content lives in per-package files under subdirectories.
    """

    platform = "codex"
    SIZE_BUDGET_BYTES = 32 * 1024  # 32 KiB default
    ROOT_DESCRIPTION_MAX_CHARS = 200

    def generate(self, packages: dict[str, list[PackageContent]]) -> None:
        # Root AGENTS.md: condensed index referencing subdirectory files
        root_sections: list[str] = []

        # Rules → condensed in root, full body in standards/AGENTS.md
        rules = packages.get("rule", [])
        if rules:
            root_sections.append("# Project Standards\n")
            root_sections.append("Full standards in `standards/AGENTS.md`.\n")
            for pkg in rules:
                description = truncate_description(
                    pkg.frontmatter.get("description", ""),
                    self.ROOT_DESCRIPTION_MAX_CHARS,
                )
                root_sections.append(f"- **{_title_case(pkg.name)}**: {description}")
            root_sections.append("")

            # Full standards file
            std_parts = ["# Project Standards\n"]
            for pkg in rules:
                std_parts.append(f"## {_title_case(pkg.name)}\n")
                std_parts.append(pkg.body)
                std_parts.append("")
            self._write(
                self.output_dir / "standards" / "AGENTS.md", "\n".join(std_parts)
            )

        # Agents → condensed in root, full body in agents/AGENTS.md
        agents = packages.get("agent", [])
        if agents:
            root_sections.append("# Agents\n")
            root_sections.append("Full agent instructions in `agents/AGENTS.md`.\n")
            for pkg in agents:
                description = truncate_description(
                    pkg.frontmatter.get("description", ""),
                    self.ROOT_DESCRIPTION_MAX_CHARS,
                )
                root_sections.append(f"- **{_title_case(pkg.name)}**: {description}")
            root_sections.append("")

            # Full agents file
            agent_parts = ["# Agent Instructions\n"]
            for pkg in agents:
                agent_parts.append(f"## {_title_case(pkg.name)}\n")
                agent_parts.append(pkg.body)
                agent_parts.append("")
            self._write(
                self.output_dir / "agents" / "AGENTS.md", "\n".join(agent_parts)
            )

        # Commands → condensed in root, full body in workflows/AGENTS.md
        commands = packages.get("command", [])
        if commands:
            root_sections.append("# Workflows\n")
            root_sections.append(
                "Full workflow instructions in `workflows/AGENTS.md`.\n"
            )
            for pkg in commands:
                description = truncate_description(
                    pkg.frontmatter.get("description", ""),
                    self.ROOT_DESCRIPTION_MAX_CHARS,
                )
                root_sections.append(f"- **{_title_case(pkg.name)}**: {description}")
            root_sections.append("")

            # Full workflows file
            wf_parts = ["# Workflow Instructions\n"]
            for pkg in commands:
                wf_parts.append(f"## {_title_case(pkg.name)}\n")
                wf_parts.append(pkg.body)
                wf_parts.append("")
            self._write(
                self.output_dir / "workflows" / "AGENTS.md", "\n".join(wf_parts)
            )

        # Skills → condensed in root, full body in skills/AGENTS.md
        skills = packages.get("skill", [])
        if skills:
            root_sections.append("# Skills Reference\n")
            root_sections.append("Full skill instructions in `skills/AGENTS.md`.\n")
            for pkg in skills:
                description = truncate_description(
                    pkg.frontmatter.get("description", ""),
                    self.ROOT_DESCRIPTION_MAX_CHARS,
                )
                root_sections.append(f"- **{_title_case(pkg.name)}**: {description}")
            root_sections.append("")

            # Full skills file
            skill_parts = ["# Skill Instructions\n"]
            for pkg in skills:
                skill_parts.append(f"## {_title_case(pkg.name)}\n")
                skill_parts.append(pkg.body)
                skill_parts.append("")
            self._write(
                self.output_dir / "skills" / "AGENTS.md", "\n".join(skill_parts)
            )

        # Hooks, utilities, presets → skipped
        for skipped_type in ("hook", "utility", "preset"):
            count = len(packages.get(skipped_type, []))
            if count:
                print(
                    f"  codex: skipped {count} {skipped_type}(s) (no equivalent)",
                    file=sys.stderr,
                )

        root_content = "\n".join(root_sections)
        size = len(root_content.encode("utf-8"))
        pct = (size / self.SIZE_BUDGET_BYTES) * 100
        if size > self.SIZE_BUDGET_BYTES:
            print(
                f"  codex: root AGENTS.md is {size:,} bytes ({pct:.0f}% of 32 KiB budget)",
                file=sys.stderr,
            )
        else:
            print(
                f"  codex: root AGENTS.md is {size:,} bytes ({pct:.0f}% of 32 KiB budget)",
                file=sys.stderr,
            )

        self._write(self.output_dir / "AGENTS.md", root_content)

    def validate(self) -> list[str]:
        errors: list[str] = []
        root = self.output_dir / "AGENTS.md"
        if root.exists():
            size = len(root.read_bytes())
            if size > self.SIZE_BUDGET_BYTES:
                errors.append(
                    f"codex: root AGENTS.md exceeds 32 KiB budget ({size:,} bytes)"
                )
        # Verify subdirectory files exist
        for subdir in ("standards", "agents", "workflows", "skills"):
            sub_file = self.output_dir / subdir / "AGENTS.md"
            if not sub_file.exists() and root.exists():
                # Only flag if root references it
                root_text = root.read_text(encoding="utf-8") if root.exists() else ""
                if f"`{subdir}/AGENTS.md`" in root_text:
                    errors.append(f"codex: {subdir}/AGENTS.md referenced but not found")
        return errors


# ---------------------------------------------------------------------------
# Gemini adapter
# ---------------------------------------------------------------------------


class GeminiAdapter(AdapterGenerator):
    """Generate .gemini/ structure: GEMINI.md, skills/, commands/, agents/."""

    platform = "gemini"

    def generate(self, packages: dict[str, list[PackageContent]]) -> None:
        gemini_dir = self.output_dir / ".gemini"

        # Skills → .gemini/skills/{name}/SKILL.md (near 1:1 copy)
        for pkg in packages.get("skill", []):
            self._generate_skill(gemini_dir / "skills" / pkg.name, pkg)

        # Agents → .gemini/agents/{name}.md
        agents = packages.get("agent", [])
        if agents:
            for pkg in agents:
                content = self._build_agent_md(pkg)
                self._write(gemini_dir / "agents" / f"{pkg.name}.md", content)

        # Rules → sections in GEMINI.md
        rules = packages.get("rule", [])
        gemini_md_parts: list[str] = []
        if rules:
            gemini_md_parts.append("# Project Standards\n")
            for pkg in rules:
                gemini_md_parts.append(pkg.body)
                gemini_md_parts.append("")

        if gemini_md_parts:
            self._write(gemini_dir / "GEMINI.md", "\n".join(gemini_md_parts))

        # Commands → .gemini/commands/workflow/{name}.toml
        for pkg in packages.get("command", []):
            content = self._build_command_toml(pkg)
            self._write(
                gemini_dir / "commands" / "workflow" / f"{pkg.name}.toml", content
            )

        # Hooks → documented as manual setup
        hooks = packages.get("hook", [])
        if hooks:
            print(
                f"  gemini: skipped {len(hooks)} hook(s) (different event model)",
                file=sys.stderr,
            )

        # Utilities → wrap as skills
        for pkg in packages.get("utility", []):
            self._generate_skill(gemini_dir / "skills" / pkg.name, pkg)

        # Presets → skipped
        presets = packages.get("preset", [])
        if presets:
            print(
                f"  gemini: skipped {len(presets)} preset(s) (no equivalent)",
                file=sys.stderr,
            )

    def _generate_skill(self, skill_dir: Path, pkg: PackageContent) -> None:
        """Generate a Gemini skill directory (SKILL.md + references/)."""
        # Build cleaned frontmatter (remove Claude-specific fields)
        clean_fm = self._clean_skill_frontmatter(pkg.frontmatter)
        fm_yaml = yaml.dump(
            clean_fm, default_flow_style=False, sort_keys=False, width=120
        ).strip()
        content = f"---\n{fm_yaml}\n---\n\n{pkg.body}"
        self._write(skill_dir / "SKILL.md", content)

        # Copy references directory if present
        refs_src = pkg.path / "references"
        if refs_src.is_dir() and any(refs_src.iterdir()):
            refs_dst = skill_dir / "references"
            self._copy_dir(refs_src, refs_dst)

        # Copy scripts directory if present
        scripts_src = pkg.path / "scripts"
        if scripts_src.is_dir() and any(scripts_src.iterdir()):
            scripts_dst = skill_dir / "scripts"
            self._copy_dir(scripts_src, scripts_dst)

        # Copy assets directory if present
        assets_src = pkg.path / "assets"
        if assets_src.is_dir() and any(assets_src.iterdir()):
            assets_dst = skill_dir / "assets"
            self._copy_dir(assets_src, assets_dst)

    def _clean_skill_frontmatter(self, fm: dict[str, Any]) -> dict[str, Any]:
        """Remove Claude-specific fields from skill frontmatter."""
        clean: dict[str, Any] = {}
        # Keep universal fields
        for key in ("name", "description"):
            if key in fm:
                clean[key] = fm[key]
        # Keep metadata but strip Claude-specific sub-fields
        metadata = fm.get("metadata")
        if isinstance(metadata, dict):
            clean_meta: dict[str, Any] = {}
            for k, v in metadata.items():
                if k not in ("execution_phase", "priority", "enabled"):
                    clean_meta[k] = v
            if clean_meta:
                clean["metadata"] = clean_meta
        return clean

    def _build_agent_md(self, pkg: PackageContent) -> str:
        """Build a Gemini agent markdown file."""
        description = pkg.frontmatter.get("description", "").strip()
        fm = {"name": pkg.name, "description": description}
        fm_yaml = yaml.dump(
            fm, default_flow_style=False, sort_keys=False, width=120
        ).strip()
        return f"---\n{fm_yaml}\n---\n\n{pkg.body}"

    def _build_command_toml(self, pkg: PackageContent) -> str:
        """Build a Gemini TOML command file."""
        description = truncate_description(
            pkg.frontmatter.get("description", "").strip()
        )
        body_escaped = pkg.body.replace('"""', '\\"\\"\\"')
        lines = [
            "[command]",
            f'description = "{description}"',
            "",
            "[command.steps]",
            'prompt = """',
            body_escaped,
            '"""',
            "",
        ]
        return "\n".join(lines)

    def validate(self) -> list[str]:
        errors: list[str] = []
        claude_fields = {
            "type",
            "model",
            "color",
            "hook",
            "command",
            "utility",
            "preset",
        }
        gemini_dir = self.output_dir / ".gemini"
        skills_dir = gemini_dir / "skills"
        if not skills_dir.is_dir():
            return errors
        for skill_dir in sorted(skills_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            content = skill_md.read_text(encoding="utf-8")
            try:
                fm = parse_frontmatter(content)
            except (ValueError, Exception):
                errors.append(
                    f"gemini: {skill_dir.name}/SKILL.md has invalid frontmatter"
                )
                continue
            if isinstance(fm, dict):
                leaked = claude_fields & set(fm.keys())
                if leaked:
                    errors.append(
                        f"gemini: {skill_dir.name}/SKILL.md has Claude-specific fields: {leaked}"
                    )
        return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _title_case(name: str) -> str:
    """Convert kebab-case to title case: 'code-reviewer' → 'Code Reviewer'."""
    return name.replace("-", " ").title()


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[AdapterGenerator]] = {
    "cursor": CursorAdapter,
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate platform-specific adapter output from armory packages.",
    )
    parser.add_argument(
        "--platform",
        choices=list(_ADAPTERS.keys()),
        help="Target platform (default: all)",
    )
    parser.add_argument(
        "--type",
        dest="types",
        action="append",
        choices=list(TYPES.keys()),
        help="Package types to include (default: all). Repeatable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without writing files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "adapters",
        help="Output root directory (default: adapters/)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate generated output after generation.",
    )
    args = parser.parse_args()

    # Load packages
    packages = load_packages(type_filter=args.types)
    total = sum(len(pkgs) for pkgs in packages.values())
    if total == 0:
        print("ERROR: No packages found", file=sys.stderr)
        return 1

    counts = ", ".join(f"{len(v)} {k}(s)" for k, v in packages.items())
    print(f"Loaded {total} packages: {counts}")

    # Determine which adapters to run
    platforms = [args.platform] if args.platform else list(_ADAPTERS.keys())

    # Generate
    adapters: list[AdapterGenerator] = []
    for platform in platforms:
        adapter_cls = _ADAPTERS[platform]
        platform_dir = args.output_dir / platform
        adapter = adapter_cls(platform_dir, dry_run=args.dry_run)
        print(f"\n{'[dry-run] ' if args.dry_run else ''}Generating {platform}...")
        adapter.generate(packages)
        print(f"  {adapter.report()}")
        adapters.append(adapter)

    # Validate
    if args.validate and not args.dry_run:
        all_errors: list[str] = []
        for adapter in adapters:
            all_errors.extend(adapter.validate())
        if all_errors:
            print(f"\nValidation FAILED: {len(all_errors)} error(s):", file=sys.stderr)
            for err in all_errors:
                print(f"  {err}", file=sys.stderr)
            return 1
        print(f"\nValidation passed for {len(adapters)} platform(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
