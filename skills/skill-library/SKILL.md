---
name: skill-library
description: 'Agent-native armory catalog for eight package types and installer for seven legacy types. Native extensions require the explicit per-host lifecycle CLI. Triggers on: "list available packages", "install skill", "armory install", "armory search", "/library list", "package catalog".'
metadata:
  version: 2.0.3
  category: operations
  tags: [armory, catalog, install, package-management, discovery]
  difficulty: beginner
---

# Package Library

Browse and search all armory package types within an agent session. Install, update, sync and remove the seven legacy package types through their existing procedures; native extensions use the separate explicit per-host lifecycle.

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
| extension | Explicit per-host root | Native lifecycle CLI only |

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

## Native Extension Boundary

This boundary takes precedence over the legacy cookbook procedures.

- Identify the type from the matching manifest section before inspecting an installed path or fetching package files. Catalog inspection may fetch the manifest; it must not fetch or copy a native extension payload.
- For native catalog queries, read `packages.extensions` and show catalog metadata. Do not derive native installed status from `~/.claude/skills/`, the legacy plugin inventory or any other prompt-package directory; report that native installation status was not inspected.
- Refuse `/library use`, sync, update or remove filesystem operations on an `extension`. Never copy native artifacts into skills, agents or other legacy directories, never enable one implicitly, and never treat a profile or preset as native-install authority.
- After the user explicitly confirms the native host, lifecycle action and target root, hand off to `uv run python scripts/install.py` in an existing Armory checkout with every native flag explicit: `--type extension --platform <omp|claude> --name <name> --action <install|update|disable|remove> --target-root <explicit-root> --yes`. Never supply `--yes` before that confirmation. Do not select a host or persistent root on the user's behalf, or execute the handoff as part of a legacy library operation.
- Native entries remain discoverable in the catalog but never contribute to legacy profile membership or package counts. For bulk legacy operations, exclude `packages.extensions` before expanding the selection.

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
