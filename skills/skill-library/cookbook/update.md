# /library update

Dry-run check for available version bumps across all installed skills. Does not modify any files.

## Procedure

### Step 1 — Fetch catalog with cache

Check whether the cached catalog exists and is fresh (under 600 seconds old). If missing or stale, re-fetch. A missing cache file is an expired cache, not an error.

```bash
CACHE_PATH="/tmp/armory-catalog.yaml"
CACHE_TTL=600
ARMORY_REPO="Mathews-Tom/armory"
ARMORY_BRANCH="main"

REFETCH=false
if [ ! -f "$CACHE_PATH" ]; then
  REFETCH=true
else
  FILE_AGE=$(( $(date +%s) - $(stat -f %m "$CACHE_PATH") ))
  if [ "$FILE_AGE" -gt "$CACHE_TTL" ]; then
    REFETCH=true
  fi
fi

if [ "$REFETCH" = true ]; then
  curl -sL "https://raw.githubusercontent.com/${ARMORY_REPO}/${ARMORY_BRANCH}/skills.yaml" > "$CACHE_PATH"
fi
```

### Step 2 — Scan installed skills

Enumerate all installed skills by reading frontmatter from each `SKILL.md` in `~/.claude/skills/`.

```bash
INSTALL_DIR="$HOME/.claude/skills"
for SKILL_FILE in "$INSTALL_DIR"/*/SKILL.md; do
  [ -f "$SKILL_FILE" ] || continue
  SKILL_NAME="$(basename "$(dirname "$SKILL_FILE")")"
  INSTALLED_VERSION="$(awk '/^---$/{n++; next} n==1 && /version:/{print $2; exit}' "$SKILL_FILE")"
  echo "$SKILL_NAME $INSTALLED_VERSION"
done
```

### Step 3 — Compare versions

For each installed skill, look up its entry in the catalog. Compare `metadata.version` (installed) against `version` (catalog) using semantic version comparison.

Classify each skill into one of:

- **update available** — catalog version is higher than installed version
- **current** — versions match
- **local-only** — installed but not present in the catalog (no update path)

### Step 4 — Build and display update plan

If updates are available, render a table:

```text
## Update Plan

| Skill                 | Installed | Available | Delta   |
|-----------------------|-----------|-----------|---------|
| architecture-reviewer | 1.0.0     | 1.1.0     | +minor  |
| commit-standards      | 1.0.0     | 1.2.0     | +minor  |
```

Delta values: `+major`, `+minor`, `+patch` based on which semver component changed (use the highest changed component).

Below the table, print a summary:

```text
X skill(s) have updates available. Y skill(s) are current.
```

If any installed skills are local-only (not in catalog), list them separately:

```text
### Local-only skills (not in catalog)

- custom-skill-a
- custom-skill-b
```

### Step 5 — Suggest sync

Do not execute any updates. Print:

```text
Run `/library sync` to apply all available updates.
```

### Step 6 — No updates available

If all installed skills are current, print:

```text
All installed skills are up to date.
```
