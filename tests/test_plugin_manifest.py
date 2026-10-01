"""Tests that .claude-plugin/plugin.json lists every agent and command.

Claude Code does not expand globs in plugin.json, so each package is listed
explicitly and a new one must be added here by hand.
"""
from __future__ import annotations

import json

from scripts.package_types import REPO_ROOT, TYPES

PLUGIN = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())


def _definitions(type_key: str) -> dict[str, str]:
    pkg_type = TYPES[type_key]
    return {
        path.parent.name: f"./{path.relative_to(REPO_ROOT).as_posix()}"
        for path in sorted(pkg_type.repo_dir.glob(f"*/{pkg_type.definition_file}"))
    }


def test_agents_listed() -> None:
    assert sorted(PLUGIN["agents"]) == sorted(_definitions("agent").values())


def test_commands_listed() -> None:
    commands = {name: entry["source"] for name, entry in PLUGIN["commands"].items()}
    assert commands == _definitions("command")
