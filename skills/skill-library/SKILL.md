---
name: skill-library
description: 'Agent-native catalog and installer for armory packages across all 7 types. Browse, search, install, update, and remove without leaving session. Triggers on: "list available packages", "install skill", "armory install", "armory search", "/library list", "package catalog".'
metadata:
  version: 2.0.1
  category: operations
  tags: [armory, catalog, install, package-management, discovery]
  difficulty: beginner
---

# Package Library

Agent-native catalog and installer for all armory package types. Provides browsing, searching, installing, updating, syncing, and removing packages directly within an agent session.

## Variables

- **ARMORY_REPO**: `Mathews-Tom/armory`
- **ARMORY_BRANCH**: `main`
- **ARMORY_CATALOG_URL**: `https://raw.githubusercontent.com/{ARMORY_REPO}/{ARMORY_BRANCH}/manifest.yaml`
- **DEFAULT_INSTALL_DIR**: `~/.claude/`
- **CATALOG_CACHE_PATH**: `/tmp/armory-manifest.yaml`
- **CATALOG_CACHE_TTL**: `600` (seconds)

## Supported Package Types

| Type    | Install Target         | Method          |
| ------- | ---------------------- | --------------- |
| skill   | `~/.claude/skills/`    | Copy directory  |
| agent   | `~/.claude/agents/`    | Copy directory  |
| hook    | `~/.claude/hooks/`     | Copy directory  |
| rule    | `~/.claude/rules/`     | Body-only file  |
| command | `~/.claude/commands/`  | Body-only file  |
| utility | `~/.claude/utilities/` | Copy + chmod +x |
| preset  | `~/.claude/presets/`   | Copy directory  |

## Command Reference

| Command                             | Cookbook               | Purpose                                                                  |
| ----------------------------------- | ---------------------- | ------------------------------------------------------------------------ |
| `/library list`                     | `cookbook/list.md`     | Show all packages with type, version, installed status, update available |
| `/library list --type <type>`       | `cookbook/list.md`     | Filter listing by package type (skill, agent, hook, rule, etc.)          |
| `/library use <name>`               | `cookbook/use.md`      | Pull a package from armory (auto-detects type from manifest)             |
| `/library search <keyword>`         | `cookbook/search.md`   | Keyword search across all package types, names, and descriptions         |
| `/library search --category <name>` | `cookbook/search.md`   | Filter search by category (development, review, security, etc.)          |
| `/library sync`                     | `cookbook/sync.md`     | Re-pull all installed packages that have updates                         |
| `/library info <name>`              | `cookbook/info.md`     | Show full detail for a package (type, version, tags, category)           |
| `/library update`                   | `cookbook/update.md`   | Check all installed packages for version bumps (dry-run sync)            |
| `/library remove <name>`            | `cookbook/remove.md`   | Remove an installed package                                              |
| `/library profiles`                 | `cookbook/profiles.md` | Show available install profiles with package counts                      |

## Cookbook Dispatch

User commands are routed to the corresponding cookbook file based on the subcommand. When a `/library` command is received, extract the subcommand (the first token after `/library`) and load the matching cookbook file from the `cookbook/` directory relative to this skill. The cookbook file contains the full execution procedure for that operation.

For example, `/library use commit-standards` dispatches to `cookbook/use.md` with `commit-standards` as the package name argument. `/library list --type agent` dispatches to `cookbook/list.md` with `--type agent` as the filter.

If the subcommand does not match any known cookbook, report the error and list the valid subcommands from the table above.

## Type Detection

When `/library use <name>` is called, determine the package type by searching all sections of the manifest (`packages.skills`, `packages.agents`, `packages.hooks`, etc.). The first section containing a matching `name` entry determines the type. Use the type to:

1. Resolve the correct source path: `{type_dir}/{name}/`
2. Determine the install target: `~/.claude/{install_subdir}/`
3. Choose the install method: directory copy or body-only extraction

## Behavioral Notes

- All bash operations must use absolute paths. Never `cd` into temp dirs.
- Fetch uses a 3-tier fallback chain: sparse checkout, then `gh api`, then `curl`. Attempt each in order; proceed to the next only on failure.
- Cache lives in `/tmp/` with a 10-minute TTL. A missing cache file is treated as expired (triggers a re-fetch), not as an error.
- The catalog is read from `manifest.yaml` on GitHub (at `ARMORY_CATALOG_URL`), not from a separate catalog file. This is the same manifest format used by the armory repository.
- All package type sections share the same entry format: `name`, `version`, `description`, `path`, `source`, plus optional `tags`, `category`, `difficulty`.
