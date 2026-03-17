# /library sync

Re-pull all installed skills that have updates available in the armory catalog.

## Inputs

- No arguments.
- Variables from SKILL.md: `ARMORY_REPO`, `ARMORY_BRANCH`, `ARMORY_CATALOG_URL`, `DEFAULT_INSTALL_DIR`, `CATALOG_CACHE_PATH`, `CATALOG_CACHE_TTL`

## Procedure

### Step 1: Fetch catalog

Check for a cached catalog at `CATALOG_CACHE_PATH` (`/tmp/armory-catalog.yaml`).

```bash
if [ -f /tmp/armory-catalog.yaml ]; then
    age=$(( $(date +%s) - $(stat -f %m /tmp/armory-catalog.yaml) ))
    if [ "$age" -ge 600 ]; then
        curl -sL "{ARMORY_CATALOG_URL}" -o /tmp/armory-catalog.yaml
    fi
else
    curl -sL "{ARMORY_CATALOG_URL}" -o /tmp/armory-catalog.yaml
fi
```

If the fetch fails, report the error and stop.

### Step 2: Scan installed skills

List all installed skill directories:

```bash
ls -1 ~/.claude/skills/
```

For each directory that contains a `SKILL.md`, extract the local version:

```bash
for skill_dir in ~/.claude/skills/*/; do
    name=$(basename "$skill_dir")
    if [ -f "$skill_dir/SKILL.md" ]; then
        local_version=$(grep -A1 '^metadata:' "$skill_dir/SKILL.md" | grep 'version:' | awk '{print $2}')
        echo "$name: $local_version"
    fi
done
```

### Step 3: Compare versions

For each installed skill, look up its entry in the catalog (`/tmp/armory-catalog.yaml`). Compare `metadata.version` from the local `SKILL.md` against the catalog version.

Skip any installed skill that does not exist in the catalog (locally-created skills).

### Step 4: Build update plan

Collect all skills where the local version differs from the catalog version. Build a table:

| Skill    | Installed         | Available           |
| -------- | ----------------- | ------------------- |
| `<name>` | `<local_version>` | `<catalog_version>` |

If no updates are available, report: "All installed skills are up to date." Stop here.

### Step 5: Confirm

Display the update plan table and ask: "Update these skills? This will overwrite local copies with the latest from the armory."

Wait for explicit confirmation before proceeding. If the user declines, stop.

### Step 6: Fetch and install updates

For each skill in the update plan, fetch using the 3-tier fallback chain. All operations use absolute paths — never `cd` into temp dirs.

**Tier 1: Sparse checkout** (preferred, requires `git` v2.25+):

```bash
tmp_dir=$(mktemp -d)
git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/{ARMORY_REPO}.git "$tmp_dir"
git -C "$tmp_dir" sparse-checkout set "skills/<name>"
mkdir -p ~/.claude/skills/<name>
rsync -a --exclude='evals/' --exclude='__pycache__' --exclude='.DS_Store' \
    "$tmp_dir/skills/<name>/" ~/.claude/skills/<name>/
rm -rf "$tmp_dir"
```

If updating multiple skills via sparse checkout, set all paths in a single clone to reduce network calls:

```bash
tmp_dir=$(mktemp -d)
git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/{ARMORY_REPO}.git "$tmp_dir"
git -C "$tmp_dir" sparse-checkout set "skills/skill-a" "skills/skill-b" "skills/skill-c"
for name in skill-a skill-b skill-c; do
    mkdir -p ~/.claude/skills/$name
    rsync -a --exclude='evals/' --exclude='__pycache__' --exclude='.DS_Store' \
        "$tmp_dir/skills/$name/" ~/.claude/skills/$name/
done
rm -rf "$tmp_dir"
```

If sparse checkout fails, fall back per-skill:

**Tier 2: `gh api`** (requires `gh` with auth):

```bash
mkdir -p ~/.claude/skills/<name>
gh api repos/{ARMORY_REPO}/contents/skills/<name> \
    --jq '.[].download_url' | while read url; do
    curl -sL "$url" -o ~/.claude/skills/<name>/$(basename "$url")
done
rm -rf ~/.claude/skills/<name>/evals \
       ~/.claude/skills/<name>/__pycache__ \
       ~/.claude/skills/<name>/.DS_Store
```

**Tier 3: `curl`** (unauthenticated, public repos only):

```bash
base="https://raw.githubusercontent.com/{ARMORY_REPO}/main/skills/<name>"
mkdir -p ~/.claude/skills/<name>
curl -sL "$base/SKILL.md" -o ~/.claude/skills/<name>/SKILL.md
```

If all three tiers fail for a skill, log the failure and continue with the remaining skills.

### Step 7: Report summary

Display a summary table:

| Skill    | Old Version | New Version | Status  |
| -------- | ----------- | ----------- | ------- |
| `<name>` | `<old>`     | `<new>`     | Updated |
| `<name>` | `<old>`     | `<new>`     | Failed  |

Include counts: `N updated, M failed, K skipped (up to date)`.
