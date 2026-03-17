# /library use <name>

Install a skill from the armory catalog into `~/.claude/skills/`.

## Inputs

- `<name>`: skill name to install
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

### Step 2: Match skill name

Parse `/tmp/armory-catalog.yaml` and search for the `<name>` argument:

1. **Exact match** on the `name` field.
2. **Fuzzy fallback**: if no exact match, search description keywords for `<name>`.
3. If multiple fuzzy matches, list them and ask the user to pick one.

### Step 3: No match

If no match found, report: "Skill `<name>` not found in catalog. Use `/library search <keyword>` to browse available skills."

Stop here.

### Step 4: Check installed version

If a match is found, check whether `~/.claude/skills/<name>/SKILL.md` exists.

```bash
if [ -f ~/.claude/skills/<name>/SKILL.md ]; then
    installed_version=$(grep -A1 '^metadata:' ~/.claude/skills/<name>/SKILL.md | grep 'version:' | awk '{print $2}')
    catalog_version=<version from catalog entry>
fi
```

- If installed and `installed_version == catalog_version`, report: "Skill `<name>` is already at latest version (`<version>`). Use `--force` to reinstall."
- If the user passed `--force`, proceed to Step 5 regardless.
- If not installed or version differs, proceed to Step 5.

### Step 5: Fetch skill files

Use a 3-tier fallback chain. All operations use absolute paths — never `cd` into temp dirs.

**Tier 1: Sparse checkout** (preferred, requires `git` v2.25+):

```bash
tmp_dir=$(mktemp -d)
git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/{ARMORY_REPO}.git "$tmp_dir"
git -C "$tmp_dir" sparse-checkout set "skills/<name>"
```

If sparse checkout fails (git version too old, network error, etc.), proceed to Tier 2.

**Tier 2: `gh api`** (requires `gh` with auth):

```bash
mkdir -p ~/.claude/skills/<name>
gh api repos/{ARMORY_REPO}/contents/skills/<name> \
    --jq '.[].download_url' | while read url; do
    curl -sL "$url" -o ~/.claude/skills/<name>/$(basename "$url")
done
```

If `gh` is not available or the API call fails, proceed to Tier 3.

**Tier 3: `curl`** (unauthenticated, public repos only):

```bash
base="https://raw.githubusercontent.com/{ARMORY_REPO}/main/skills/<name>"
mkdir -p ~/.claude/skills/<name>
curl -sL "$base/SKILL.md" -o ~/.claude/skills/<name>/SKILL.md
```

If all three tiers fail, report: "Failed to fetch skill `<name>`. Verify network connectivity and that the skill exists in the armory."

Stop here.

### Step 6: Copy to install directory

If fetched via sparse checkout (Tier 1), copy files from the temp dir to the install location:

```bash
mkdir -p ~/.claude/skills/<name>
rsync -a --exclude='evals/' --exclude='__pycache__' --exclude='.DS_Store' \
    "$tmp_dir/skills/<name>/" ~/.claude/skills/<name>/
```

Tier 2 and Tier 3 write directly to the install dir, so no copy step is needed — but still verify that `evals/`, `__pycache__`, and `.DS_Store` are excluded. Remove them if present:

```bash
rm -rf ~/.claude/skills/<name>/evals \
       ~/.claude/skills/<name>/__pycache__ \
       ~/.claude/skills/<name>/.DS_Store
```

### Step 7: Clean up temp dir

```bash
if [ -n "$tmp_dir" ] && [ -d "$tmp_dir" ]; then
    rm -rf "$tmp_dir"
fi
```

### Step 8: Report

Output:

- **Skill**: `<name>`
- **Version**: `<version>`
- **Files**: `<count>` files installed
- **Path**: `~/.claude/skills/<name>/`

Get file count:

```bash
file_count=$(find ~/.claude/skills/<name> -type f | wc -l | tr -d ' ')
```

### Step 9: Complementary skills

If the catalog entry for this skill has a `complements` field, display:

> Complementary skills: X, Y. Use `/library use <name>` to install.

List each complementary skill name from the `complements` array.
