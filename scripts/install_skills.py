#!/usr/bin/env python3
"""TUI installer for armory — copies skills to ~/.claude/skills/."""
from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.prompt import Prompt
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "skills.yaml"
SKILLS_DIR = REPO_ROOT / "skills"
DEFAULT_INSTALL_DIR = Path.home() / ".claude" / "skills"

EXCLUDE_NAMES: set[str] = {
    "__pycache__",
    "node_modules",
    ".DS_Store",
    ".git",
    "evals",
}
EXCLUDE_SUFFIXES: set[str] = {".pyc"}

console = Console()


class InstallAction(Enum):
    INSTALL = "install"
    UPGRADE = "upgrade"
    REINSTALL = "reinstall"
    SKIP = "skip"


@dataclass(frozen=True)
class SkillInfo:
    name: str
    version: str
    description: str
    source_path: Path


@dataclass(frozen=True)
class InstallPlan:
    skill: SkillInfo
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


def parse_frontmatter(content: str) -> dict[str, str]:
    """Parse YAML frontmatter from SKILL.md content."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        raise ValueError("No valid YAML frontmatter found")
    return yaml.safe_load(match.group(1))


def extract_version(meta: dict[str, str]) -> str:
    """Extract version from metadata.version (preferred) or top-level version (legacy)."""
    metadata = meta.get("metadata")
    if isinstance(metadata, dict) and metadata.get("version"):
        return str(metadata["version"])
    return str(meta.get("version", "0.0.0"))


def discover_skills() -> list[SkillInfo]:
    """Discover available skills from manifest or SKILL.md files."""
    if MANIFEST_PATH.exists():
        return _discover_from_manifest()
    return _discover_from_skill_files()


def _discover_from_manifest() -> list[SkillInfo]:
    """Read skills from skills.yaml manifest."""
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    skills: list[SkillInfo] = []

    for entry in manifest.get("skills", []):
        source = REPO_ROOT / entry["path"]
        if not source.is_dir():
            continue
        skills.append(SkillInfo(
            name=entry["name"],
            version=entry.get("version", "0.0.0"),
            description=entry.get("description", ""),
            source_path=source,
        ))

    return skills


def _discover_from_skill_files() -> list[SkillInfo]:
    """Fallback: parse each SKILL.md directly."""
    console.print("[dim]skills.yaml not found — parsing SKILL.md files directly[/dim]")
    skills: list[SkillInfo] = []

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_md.exists():
            continue

        meta = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        name = meta.get("name", "")
        if not name:
            continue

        skills.append(SkillInfo(
            name=name,
            version=extract_version(meta),
            description=meta.get("description", "").strip(),
            source_path=skill_dir,
        ))

    return skills


def get_installed_version(install_dir: Path, skill_name: str) -> str | None:
    """Read version from an installed skill's SKILL.md, or None if not installed."""
    skill_md = install_dir / skill_name / "SKILL.md"
    if not skill_md.exists():
        return None

    content = skill_md.read_text(encoding="utf-8")
    try:
        meta = parse_frontmatter(content)
    except ValueError:
        return "0.0.0"

    return extract_version(meta)


def build_install_plans(
    skills: list[SkillInfo],
    install_dir: Path,
    *,
    reinstall: bool = False,
) -> list[InstallPlan]:
    """Determine install/upgrade/reinstall/skip action for each skill."""
    plans: list[InstallPlan] = []

    for skill in skills:
        target = install_dir / skill.name
        installed_version = get_installed_version(install_dir, skill.name)

        # Symlinks are externally managed — skip
        if target.is_symlink():
            console.print(
                f"[yellow]Skipping {skill.name} — {target} is a symlink (externally managed)[/yellow]"
            )
            continue

        if installed_version is None:
            action = InstallAction.INSTALL
        elif is_newer(skill.version, installed_version):
            action = InstallAction.UPGRADE
        elif reinstall:
            action = InstallAction.REINSTALL
        else:
            action = InstallAction.SKIP

        plans.append(InstallPlan(
            skill=skill,
            action=action,
            installed_version=installed_version,
            target_path=target,
        ))

    return plans


def display_plans(plans: list[InstallPlan]) -> None:
    """Display skill table with color-coded actions."""
    table = Table(title="Available Skills", show_lines=False)
    table.add_column("#", style="bold", width=4)
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

        table.add_row(
            str(i),
            plan.skill.name,
            plan.skill.version,
            installed,
            action_text,
        )

    console.print(table)


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


def should_exclude(path: Path, root: Path) -> bool:
    """Check if a path should be excluded from copying."""
    relative = path.relative_to(root)
    for part in relative.parts:
        if part in EXCLUDE_NAMES:
            return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def copy_skill(source: Path, target: Path) -> int:
    """Copy skill directory, excluding unwanted files. Returns file count."""
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


_ACTION_LABELS: dict[InstallAction, str] = {
    InstallAction.INSTALL: "Installed",
    InstallAction.UPGRADE: "Upgraded",
    InstallAction.REINSTALL: "Reinstalled",
}


def execute_plans(plans: list[InstallPlan], selected: list[int]) -> None:
    """Execute selected installation plans."""
    to_install = [plans[i] for i in selected if plans[i].action != InstallAction.SKIP]

    if not to_install:
        console.print("[dim]Nothing to install — all selected skills are up to date.[/dim]")
        return

    with Progress(console=console) as progress:
        task = progress.add_task("Installing skills...", total=len(to_install))

        for plan in to_install:
            progress.update(task, description=f"Installing {plan.skill.name}...")
            file_count = copy_skill(plan.skill.source_path, plan.target_path)
            progress.advance(task)
            label = _ACTION_LABELS.get(plan.action, "Installed")
            console.print(
                f"  {label} [cyan]{plan.skill.name}[/cyan] "
                f"v{plan.skill.version} ({file_count} files)"
            )

    # Summary
    console.print()
    summary = Table(title="Installation Summary", show_lines=False)
    summary.add_column("Skill", style="cyan")
    summary.add_column("Action")
    summary.add_column("Version")

    for plan in to_install:
        label = _ACTION_LABELS.get(plan.action, "installed").lower()
        if plan.action == InstallAction.UPGRADE:
            ver = f"{plan.installed_version} → {plan.skill.version}"
        else:
            ver = plan.skill.version
        summary.add_row(plan.skill.name, label, ver)

    console.print(summary)
    console.print(
        Panel(
            "Restart Claude Code to load the new skills.",
            title="Done",
            border_style="green",
        )
    )


def main() -> int:
    """Main entry point for the TUI installer."""
    import argparse

    parser = argparse.ArgumentParser(description="Install armory skills to ~/.claude/skills/")
    parser.add_argument(
        "--reinstall",
        action="store_true",
        help="Allow reinstalling skills that are already at the same version",
    )
    args = parser.parse_args()

    console.print(Panel("armory installer", border_style="blue"))

    # Discover
    skills = discover_skills()
    if not skills:
        console.print("[red]No skills found in repository.[/red]")
        return 1

    install_dir = DEFAULT_INSTALL_DIR
    install_dir.mkdir(parents=True, exist_ok=True)

    # Build plans
    plans = build_install_plans(skills, install_dir, reinstall=args.reinstall)
    if not plans:
        console.print("[dim]No installable skills found.[/dim]")
        return 0

    # Display
    display_plans(plans)

    # Count actionable
    actionable = [i for i, p in enumerate(plans) if p.action != InstallAction.SKIP]
    if not actionable:
        console.print("[dim]All skills are up to date. Use --reinstall to force reinstallation.[/dim]")
        return 0

    # Select
    while True:
        raw = Prompt.ask(
            f"\nEnter skill numbers to install ([green]1,3,5-8[/green], [green]all[/green], or [red]q[/red] to quit)"
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
            console.print("[dim]No skills selected.[/dim]")
            continue

        break

    # Filter to actionable selections
    selected_actionable = [i for i in selected if plans[i].action != InstallAction.SKIP]
    if not selected_actionable:
        console.print("[dim]All selected skills are already up to date.[/dim]")
        return 0

    # Confirm
    names = ", ".join(plans[i].skill.name for i in selected_actionable)
    console.print(f"\nWill install/upgrade/reinstall: [cyan]{names}[/cyan]")
    confirm = Prompt.ask("Proceed?", choices=["y", "n"], default="y")
    if confirm != "y":
        console.print("[dim]Cancelled.[/dim]")
        return 0

    # Execute
    execute_plans(plans, selected_actionable)
    return 0


if __name__ == "__main__":
    sys.exit(main())
