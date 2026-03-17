# /library info \<name\>

Show full detail for a single skill by name.

## Arguments

- `name` — exact skill name (e.g., `architecture-reviewer`)

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

### Step 2 — Look up skill in catalog

Search `/tmp/armory-catalog.yaml` for an entry where `name` matches the argument exactly. Extract: `name`, `version`, `description`, `path`, and `complements` (if present).

If the skill is not found in the catalog, proceed to Step 3 to check local installation. If not found anywhere, report: `Skill "<name>" not found in catalog or locally.`

### Step 3 — Check local installation

Check whether `~/.claude/skills/<name>/SKILL.md` exists.

```bash
INSTALL_DIR="$HOME/.claude/skills"
SKILL_NAME="<name>"
SKILL_FILE="$INSTALL_DIR/$SKILL_NAME/SKILL.md"

if [ -f "$SKILL_FILE" ]; then
  INSTALLED_VERSION="$(awk '/^---$/{n++; next} n==1 && /version:/{print $2; exit}' "$SKILL_FILE")"
  FILE_COUNT="$(find "$INSTALL_DIR/$SKILL_NAME" -type f | wc -l | tr -d ' ')"
  DIR_SIZE="$(du -sh "$INSTALL_DIR/$SKILL_NAME" | cut -f1)"
fi
```

If the skill exists locally but not in the catalog, report it as **local-only** (not tracked by armory).

### Step 4 — Determine install status

- **not installed** — not in `~/.claude/skills/`
- **current** — installed version matches catalog version
- **update available** — installed version is lower than catalog version
- **local-only** — installed but not in catalog

### Step 5 — Display detail card

Render the following fields:

```text
## <name>

**Version (catalog):** 1.1.0
**Version (installed):** 1.0.0
**Status:** update available
**Install path:** ~/.claude/skills/<name>/
**Files:** 3
**Size:** 12K

### Description

<full description text from catalog or local SKILL.md>
```

If catalog version is not available (local-only skill), omit the catalog version line.

If not installed, omit the installed version, install path, files, and size lines.

### Step 6 — Show complementary skills

If the catalog entry contains a `complements` field (list of skill names), display them:

```
### Complements

These skills work well together with <name>:

- **architecture-diagram** — `/library use architecture-diagram`
- **code-refiner** — `/library use code-refiner`
```

If there is no `complements` field, skip this section.
