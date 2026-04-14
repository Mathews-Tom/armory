#!/usr/bin/env python3
"""Hook package installer — merges hook config into Claude Code settings.json."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.frontmatter import parse_frontmatter


def _resolve_hook_command(command: str, hook_dir: Path) -> str:
    """Rewrite relative script references in a hook command to absolute paths.

    Handles patterns like ``bash handler.sh`` or ``bash helper.sh`` where the
    script is a bare filename (no slashes, no ``~``).  Already-absolute paths
    and paths containing ``~`` or ``/`` are left untouched.
    """
    import re

    def _replace(m: re.Match[str]) -> str:
        prefix, script = m.group(1), m.group(2)
        return f"{prefix}{hook_dir / script}"

    # Match: <word-boundary>bash <bare-script.sh> — only bare filenames
    return re.sub(r"(bash\s+)([A-Za-z0-9_.-]+\.sh)\b", _replace, command)


def install_hook(hook_dir: Path, claude_dir: Path) -> None:
    """Install a hook package.

    1. Copy handler files to claude_dir/hooks/{name}/
    2. Read HOOK.md frontmatter for event/matcher/handler config
    3. Merge hook entry into settings.json
    """
    hook_md = hook_dir / "HOOK.md"
    content = hook_md.read_text(encoding="utf-8")
    meta = parse_frontmatter(content)

    name = meta["name"]
    hook_config = meta["hook"]

    # Copy handler files
    target_dir = claude_dir / "hooks" / name
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for src_file in sorted(hook_dir.iterdir()):
        if src_file.is_file() and src_file.name not in ("HOOK.md",):
            shutil.copy2(src_file, target_dir / src_file.name)

    # Merge into settings.json
    settings_path = claude_dir / "settings.json"
    settings: dict[str, Any] = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))

    settings = merge_hook_config(settings, name, hook_config, claude_dir)
    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )


def uninstall_hook(name: str, claude_dir: Path) -> None:
    """Remove hook from settings.json and delete handler files."""
    # Remove handler files
    target_dir = claude_dir / "hooks" / name
    if target_dir.exists():
        shutil.rmtree(target_dir)

    # Remove from settings.json
    settings_path = claude_dir / "settings.json"
    if not settings_path.exists():
        return

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings = remove_hook_config(settings, name)
    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )


def merge_hook_config(
    settings: dict[str, Any],
    hook_name: str,
    hook_meta: dict[str, Any],
    claude_dir: Path | None = None,
) -> dict[str, Any]:
    """Add hook configuration to settings dict. Returns modified settings.

    Structure in settings.json:
    {
      "hooks": {
        "PreToolUse": [
          {"matcher": "Bash", "hooks": [{"type": "command", "command": "..."}]}
        ]
      }
    }

    Each hook package gets its own matcher entry tagged with _hook_name for
    tracking which package owns it.

    When *claude_dir* is provided, relative script references (e.g.
    ``bash handler.sh``) are rewritten to absolute paths pointing at the
    installed hook directory so the command works regardless of CWD.
    """
    hooks_section = settings.setdefault("hooks", {})
    events = hook_meta.get("events", [])
    matcher = hook_meta.get("matcher", "")
    handler = hook_meta.get("handler", {})

    hook_entry = dict(handler)
    hook_entry["_hook_name"] = hook_name

    # Rewrite relative script paths to absolute installed paths
    if claude_dir is not None:
        cmd = hook_entry.get("command", "")
        if cmd:
            hook_dir = claude_dir / "hooks" / hook_name
            hook_entry["command"] = _resolve_hook_command(cmd, hook_dir)

    for event in events:
        event_list: list[dict[str, Any]] = hooks_section.setdefault(event, [])

        # Find existing matcher group or create one
        matcher_group = None
        for group in event_list:
            if group.get("matcher") == matcher:
                matcher_group = group
                break

        if matcher_group is None:
            matcher_group = {"matcher": matcher, "hooks": []}
            event_list.append(matcher_group)

        # Remove existing entries by hook name OR by command to prevent duplicates.
        # Command deduplication cleans up legacy entries that predate _hook_name tracking.
        new_command = hook_entry.get("command", "")
        matcher_group["hooks"] = [
            h for h in matcher_group["hooks"]
            if h.get("_hook_name") != hook_name
            and (not new_command or h.get("command") != new_command)
        ]
        matcher_group["hooks"].append(hook_entry)

    return settings


def remove_hook_config(settings: dict[str, Any], hook_name: str) -> dict[str, Any]:
    """Remove a hook's entries from settings dict."""
    hooks_section = settings.get("hooks")
    if not isinstance(hooks_section, dict):
        return settings

    events_to_delete: list[str] = []

    for event, event_list in hooks_section.items():
        if not isinstance(event_list, list):
            continue

        groups_to_delete: list[int] = []
        for i, group in enumerate(event_list):
            if not isinstance(group, dict):
                continue
            hooks_list = group.get("hooks", [])
            group["hooks"] = [
                h for h in hooks_list if h.get("_hook_name") != hook_name
            ]
            if not group["hooks"]:
                groups_to_delete.append(i)

        for idx in reversed(groups_to_delete):
            event_list.pop(idx)

        if not event_list:
            events_to_delete.append(event)

    for event in events_to_delete:
        del hooks_section[event]

    if not hooks_section:
        del settings["hooks"]

    return settings
