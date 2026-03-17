# /library list

List all skills from the armory catalog with installed status and version comparison.

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

### Step 2 — Parse catalog entries

Read `/tmp/armory-catalog.yaml`. Each entry under `skills:` has `name`, `version`, `description`, and `path`. Collect all entries into a list of `(name, catalog_version)` pairs.

### Step 3 — Scan installed skills

For each directory in `~/.claude/skills/*/SKILL.md`, parse the YAML frontmatter (between the opening `---` and closing `---`) and extract `metadata.version`. Build a map of `installed_name → installed_version`.

```bash
INSTALL_DIR="$HOME/.claude/skills"
for SKILL_FILE in "$INSTALL_DIR"/*/SKILL.md; do
  [ -f "$SKILL_FILE" ] || continue
  SKILL_NAME="$(basename "$(dirname "$SKILL_FILE")")"
  INSTALLED_VERSION="$(awk '/^---$/{n++; next} n==1 && /version:/{print $2; exit}' "$SKILL_FILE")"
  echo "$SKILL_NAME $INSTALLED_VERSION"
done
```

### Step 4 — Cross-reference and determine status

For each catalog entry, determine status:

- **not installed** — skill name not found in `~/.claude/skills/`
- **current** — installed version matches catalog version exactly
- **update available** — installed version is lower than catalog version

### Step 5 — Display table

Render a numbered markdown table with columns: `#`, `Skill`, `Catalog`, `Installed`, `Status`.

- Use `—` for the Installed column when a skill is not installed.
- Sort alphabetically by skill name.

```text
| # | Skill                  | Catalog | Installed | Status           |
|---|------------------------|---------|-----------|------------------|
| 1 | architecture-reviewer  | 1.1.0   | 1.0.0     | update available |
| 2 | code-refiner           | 1.1.0   | 1.1.0     | current          |
| 3 | concept-to-video       | 1.1.0   | —         | not installed    |
```

After the table, print a summary line:

```
X installed, Y updates available, Z total in catalog
```
