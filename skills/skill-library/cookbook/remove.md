# /library remove <name>

Remove an installed skill from `~/.claude/skills/`.

## Inputs

- `<name>`: skill name to remove
- Variables from SKILL.md: `DEFAULT_INSTALL_DIR`

## Procedure

### Step 1: Check installation

Verify the skill directory exists:

```bash
if [ ! -d ~/.claude/skills/<name> ]; then
    echo "Skill '<name>' is not installed."
fi
```

If not installed, report: "Skill `<name>` is not installed. Nothing to remove."

Stop here.

### Step 2: Display skill info

Read the installed skill's metadata before removal:

```bash
skill_version=$(grep -A1 '^metadata:' ~/.claude/skills/<name>/SKILL.md | grep 'version:' | awk '{print $2}')
```

Display:

- **Skill**: `<name>`
- **Version**: `<skill_version>`
- **Path**: `~/.claude/skills/<name>/`

### Step 3: Confirm removal

Ask the user: "Remove skill `<name>` (version `<skill_version>`) from `~/.claude/skills/<name>/`? This deletes all files in that directory."

Wait for explicit confirmation before proceeding. If the user declines, stop.

### Step 4: Remove

```bash
rm -rf ~/.claude/skills/<name>/
```

### Step 5: Report

Output: "Skill `<name>` removed. Use `/library use <name>` to reinstall."
