---
name: skill-library
description: >
  Agent-native catalog and installer for armory skills. Browse, search, install,
  update, sync, and remove skills from the armory collection without leaving your
  agent session. Triggers on: "list available skills", "install skill", "pull skill",
  "what skills are available", "update my skills", "search skills for",
  "skill catalog", "armory list", "armory install", "armory search",
  "remove skill", "uninstall skill", "/library list", "/library use",
  "/library remove", "show me armory skills", "get the architecture-reviewer
  skill", "do I have the latest skills". Use this skill when the user wants to
  discover, install, update, or remove armory skills from within an agent session.
metadata:
  version: 1.0.0
---

# Skill Library

Agent-native catalog and installer for armory skills. Provides browsing, searching, installing, updating, syncing, and removing skills directly within an agent session.

## Variables

- **ARMORY_REPO**: `Mathews-Tom/armory`
- **ARMORY_BRANCH**: `main`
- **ARMORY_CATALOG_URL**: `https://raw.githubusercontent.com/{ARMORY_REPO}/{ARMORY_BRANCH}/skills.yaml`
- **DEFAULT_INSTALL_DIR**: `~/.claude/skills/`
- **CATALOG_CACHE_PATH**: `/tmp/armory-catalog.yaml`
- **CATALOG_CACHE_TTL**: `600` (seconds)

## Command Reference

| Command                     | Cookbook             | Purpose                                                               |
| --------------------------- | -------------------- | --------------------------------------------------------------------- |
| `/library list`             | `cookbook/list.md`   | Show all skills with version, installed status, update available      |
| `/library use <name>`       | `cookbook/use.md`    | Pull a skill from armory into `~/.claude/skills/`                     |
| `/library search <keyword>` | `cookbook/search.md` | Keyword search across skill names and descriptions                    |
| `/library sync`             | `cookbook/sync.md`   | Re-pull all installed skills that have updates                        |
| `/library info <name>`      | `cookbook/info.md`   | Show full detail for a skill                                          |
| `/library update`           | `cookbook/update.md` | Check all installed skills for available version bumps (dry-run sync) |
| `/library remove <name>`    | `cookbook/remove.md` | Remove an installed skill from `~/.claude/skills/`                    |

## Cookbook Dispatch

User commands are routed to the corresponding cookbook file based on the subcommand. When a `/library` command is received, extract the subcommand (the first token after `/library`) and load the matching cookbook file from the `cookbook/` directory relative to this skill. The cookbook file contains the full execution procedure for that operation.

For example, `/library use commit-standards` dispatches to `cookbook/use.md` with `commit-standards` as the skill name argument. `/library list` dispatches to `cookbook/list.md` with no arguments.

If the subcommand does not match any known cookbook, report the error and list the valid subcommands from the table above.

## Behavioral Notes

- All bash operations must use absolute paths. Never `cd` into temp dirs.
- Fetch uses a 3-tier fallback chain: sparse checkout, then `gh api`, then `curl`. Attempt each in order; proceed to the next only on failure.
- Cache lives in `/tmp/` with a 10-minute TTL. A missing cache file is treated as expired (triggers a re-fetch), not as an error.
- The catalog is read from `skills.yaml` on GitHub (at `ARMORY_CATALOG_URL`), not from a separate catalog file. This is the same manifest format used by the armory repository.
