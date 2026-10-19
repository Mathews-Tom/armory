---
name: skill-inventory
description: 'Locates or installs the armory skill-inventory utility, then hands off to its operator guide to measure installed skill descriptions, observed reads and unused managed skills from local OMP, Claude Code and Codex logs. Use when you ask "audit my skill inventory", "how much do skill descriptions cost?", "find unused skills", "which skills were read?", "set up skill-inventory" or "run the skill inventory utility". Verifies the release checksum, asks before downloading and never replaces an existing install. NOT for context-window audits (usage-audit) or catalog installs (skill-library).'
metadata:
  version: 1.0.1
  category: operations
  tags: [skills, inventory, utility, installer, exposure]
  difficulty: beginner
---

# Skill inventory

Make the `skill-inventory` utility available to this agent and hand off to its own documentation. This skill and the utility share a name: the utility is an offline Python tool that ships as an armory utility package, which the Skills CLI and the Claude Code plugin marketplace do not install. This skill is the installable entry point that bridges that gap, without copying the utility's code or measurement rules.

## When to use

|Use when|Use instead|
|---|---|
|Auditing installed skill descriptions, observed reads or unused managed skills|—|
|The utility is not installed, or you do not know where it is|—|
|Diagnosing what fills the current context window|usage-audit|
|Searching or installing armory packages|skill-library|
|Static conformance report or authored package audit; live effectiveness `NOT_MEASURED`|package-evaluator|

Triggers group into inventory audits ("audit my skill inventory", "find unused skills", "which skills were read?"), cost questions ("how much do skill descriptions cost?") and setup ("set up skill-inventory", "run the skill inventory utility").

## Prerequisites

macOS or Linux with `bash`, `curl`, `unzip`, `shasum` or `sha256sum`, Python 3.12+ and [uv](https://docs.astral.sh/uv/). Installing needs network access to GitHub once; measurement afterwards runs offline.

## Workflow

1. Locate an existing install. Run `scripts/ensure-utility.sh` from this skill's directory. It checks `~/.claude/utilities/skill-inventory` (the armory profile installer's location) and `${XDG_DATA_HOME:-~/.local/share}/armory/utilities/skill-inventory`. Exit `0` prints `UTILITY_ROOT=` and `VERSION=`; exit `3` means it is not installed.
2. On exit `3`, ask the owner before installing. Installing downloads and later runs code from the armory rolling `latest` release. With approval, run `scripts/ensure-utility.sh --install`, or `--install DEST` for another location outside every Git repository; a relative `DEST` is resolved against the current directory.
3. Export the printed root: `export UTILITY_ROOT=...`.
4. Bootstrap the pinned dependency once: `uv run --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py" --help`.
5. Read the utility's `UTILITY.md` and its operator guide (`operator-guide.md` in the utility's references folder), then follow them. They own the commands, private output rules, approval gates and interpretation of results; this skill does not restate them.
6. Start with the read-only `measure --aggregate-only` run the guide describes. `recommend` writes only a private proposal. `archive` and `restore --apply` move files and need the owner's separate, explicit authorization.

## Install behavior

`ensure-utility.sh --install` does the following, and stops with nothing installed if any step fails:

1. Downloads `checksums.txt` from the armory `latest` release and finds exactly one `skill-inventory-X.Y.Z.utility` entry.
2. Downloads that archive and compares its SHA-256 with the listed value.
3. Unpacks it into a hidden temporary directory beside the destination and checks it contains `UTILITY.md` and `scripts/skill_inventory.py`.
4. Renames it to the destination only if nothing exists there, so an interrupted install never leaves a partial copy in place.

The checksum guards against a corrupted or truncated download. It comes from the same release, so it does not prove who published the archive.

The script never upgrades or overwrites an existing install. To upgrade, have the owner compare the installed `VERSION` with the release, move the old directory aside, then install again.

## Worked example

```bash
SKILL_DIR="$HOME/.claude/skills/skill-inventory"      # where this skill was installed
"$SKILL_DIR/scripts/ensure-utility.sh"                    # exit 3: not installed
# Owner approves the download.
"$SKILL_DIR/scripts/ensure-utility.sh" --install
# UTILITY_ROOT=$HOME/.local/share/armory/utilities/skill-inventory (expanded)
# VERSION=1.0.0
export UTILITY_ROOT="$HOME/.local/share/armory/utilities/skill-inventory"
uv run --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py" --help
# Next: follow $UTILITY_ROOT/references/operator-guide.md for the measure run.
```

## Output

Report the utility root and version, whether anything was installed, and then the utility's own output as its guide describes. Stdout from the utility is anonymous aggregate JSON; exit `2` means incomplete or refused, not an empty result.

## Troubleshooting

|Symptom|Action|
|---|---|
|Exit `3`|Not installed. Ask the owner, then rerun with `--install`.|
|`could not download ...`|Network or GitHub failure; nothing was installed. Rerun later.|
|`checksum mismatch`|Stop. Do not retry blindly or bypass the check; report it to the owner.|
|`... exists but is not a skill-inventory utility`|The destination holds something else. Inspect it with the owner; never delete it to make room.|
|`uv` or Python 3.12 missing|Install uv; `uv run` provisions the pinned PyYAML on first use.|
|Utility exits `2`|Look up each diagnostic code in the utility's `measurement.md` diagnostic table; do not patch logs or relax checks.|

## Files

|File|Purpose|
|---|---|
|[scripts/ensure-utility.sh](scripts/ensure-utility.sh)|Locate the utility, or install the released archive after checksum verification|
