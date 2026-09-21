#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

PACKAGE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
SCRIPT="$PACKAGE_DIR/scripts/storage-audit.sh"

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

assert_contains() {
    local needle=$1
    local file=$2
    case $(cat "$file") in
        *"$needle"*) ;;
        *) fail "expected '$needle' in $file" ;;
    esac
}

assert_not_contains() {
    local needle=$1
    local file=$2
    case $(cat "$file") in
        *"$needle"*) fail "did not expect '$needle' in $file" ;;
        *) ;;
    esac
}

assert_equals() {
    local expected=$1
    local actual=$2
    local message=$3
    [ "$expected" = "$actual" ] || fail "$message: expected '$expected', got '$actual'"
}

[ -f "$SCRIPT" ] || fail "missing implementation: $SCRIPT"
bash -n "$SCRIPT"

TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/storage-audit.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT
ROOT="$TMP_ROOT/workspace"
mkdir -p "$ROOT/rust/target" "$ROOT/python/.venv" "$ROOT/data" "$ROOT/container" "$ROOT/broken-container/stale-worktree" "$ROOT/linked-target"

(
    cd "$ROOT/rust"
    git init -q
    printf '[package]\nname = "fixture"\nversion = "0.1.0"\n' > Cargo.toml
    printf 'target/\n' > .gitignore
    dd if=/dev/zero of=target/cache.bin bs=1024 count=16 status=none
    mkdir -p .worktrees/active
    git add Cargo.toml .gitignore
    git -c user.name=Fixture -c user.email=fixture@example.invalid commit -qm 'add fixture'
    git worktree add --detach -q "$ROOT/container/rust-worktree"
)
(
    cd "$ROOT/python"
    git init -q
    printf '[project]\nname = "fixture"\nversion = "0.1.0"\n' > pyproject.toml
    printf 'version = 1\n' > uv.lock
    printf '.venv/\n' > .gitignore
    printf 'environment\n' > .venv/marker
)
printf 'gitdir: /missing/worktree/metadata\n' > "$ROOT/broken-container/stale-worktree/.git"
printf 'local corpus\n' > "$ROOT/data/corpus.jsonl"
ln -s "$ROOT/rust/target" "$ROOT/linked-target/target-link"
ROOT=$(cd -P "$ROOT" && pwd -P)

SENTINEL="$ROOT/data/corpus.jsonl"
SENTINEL_HASH_BEFORE=$(shasum -a 256 "$SENTINEL" | cut -d ' ' -f 1)
AUDIT_JSON="$TMP_ROOT/audit.json"
"$SCRIPT" audit --root "$ROOT" --scope workspace --strict --format json > "$AUDIT_JSON"
python3 -c 'import json, pathlib, sys; json.loads(pathlib.Path(sys.argv[1]).read_text())' "$AUDIT_JSON"
python3 -c 'import json, pathlib, sys; projects = {row["path"]: row for row in json.loads(pathlib.Path(sys.argv[1]).read_text())["projects"]}; container = projects[sys.argv[2]]; worktree = projects[sys.argv[3]]; assert container["project_type"] == "repository-container"; assert container["nested_repo_count"] == 1; assert worktree["project_type"] == "repository"' \
    "$AUDIT_JSON" "$ROOT/container" "$ROOT/container/rust-worktree"
python3 -c 'import json, pathlib, sys; projects = {row["path"]: row for row in json.loads(pathlib.Path(sys.argv[1]).read_text())["projects"]}; container = projects[sys.argv[2]]; stale = projects[sys.argv[3]]; assert container["project_type"] == "repository-container"; assert container["nested_repo_count"] == 1; assert stale["project_type"] == "invalid-repository"; assert stale["git_status"] == "invalid-repository"' \
    "$AUDIT_JSON" "$ROOT/broken-container" "$ROOT/broken-container/stale-worktree"
SENTINEL_HASH_AFTER=$(shasum -a 256 "$SENTINEL" | cut -d ' ' -f 1)
assert_equals "$SENTINEL_HASH_BEFORE" "$SENTINEL_HASH_AFTER" "audit changed fixture content"
assert_contains '"status":"stable"' "$AUDIT_JSON"
assert_contains '"id":"A-001"' "$AUDIT_JSON"
assert_contains "$ROOT/rust/target" "$AUDIT_JSON"
assert_contains '"class":"rebuildable"' "$AUDIT_JSON"
assert_contains "$ROOT/python/.venv" "$AUDIT_JSON"
assert_contains '"class":"local-data"' "$AUDIT_JSON"
assert_contains '"git_status":"dirty"' "$AUDIT_JSON"
assert_contains "$ROOT/rust/.worktrees" "$AUDIT_JSON"
assert_contains '"class":"git-protected"' "$AUDIT_JSON"
assert_contains "$ROOT/data" "$AUDIT_JSON"
assert_not_contains 'target-link' "$AUDIT_JSON"
REPO_JSON="$TMP_ROOT/repo.json"
"$SCRIPT" audit --root "$ROOT/rust" --scope repo --strict --format json > "$REPO_JSON"
assert_contains "$ROOT/rust/target" "$REPO_JSON"
AUDIT_MARKDOWN="$TMP_ROOT/audit.md"
"$SCRIPT" audit --root "$ROOT" --scope workspace --strict --format markdown > "$AUDIT_MARKDOWN"
assert_contains 'Reply `render all` to render a preview-only cleanup script for every actionable candidate from this audit.' "$AUDIT_MARKDOWN"
assert_not_contains 'fresh strict scan' "$AUDIT_MARKDOWN"
assert_not_contains '<selected IDs>' "$AUDIT_MARKDOWN"

assert_contains '"cleanup_eligible":true' "$REPO_JSON"

FAKE_BIN="$TMP_ROOT/fake-bin"
RM_CALLED="$TMP_ROOT/rm-called"
mkdir -p "$FAKE_BIN"
printf '#!/usr/bin/env bash\nprintf called > %q\nexit 99\n' "$RM_CALLED" > "$FAKE_BIN/rm"
chmod +x "$FAKE_BIN/rm"
PLAN_SCRIPT="$TMP_ROOT/cleanup.sh"
PATH="$FAKE_BIN:$PATH" "$SCRIPT" plan --root "$ROOT" --candidate A-001 --expected-path "$ROOT/rust/target" > "$PLAN_SCRIPT"
[ ! -e "$RM_CALLED" ] || fail "plan executed rm"
bash -n "$PLAN_SCRIPT"
assert_contains '#!/usr/bin/env bash' "$PLAN_SCRIPT"
assert_contains 'Preview only.' "$PLAN_SCRIPT"
assert_contains '--execute' "$PLAN_SCRIPT"
PREVIEW_OUT="$TMP_ROOT/preview.txt"
PATH="$FAKE_BIN:$PATH" bash "$PLAN_SCRIPT" > "$PREVIEW_OUT"
[ ! -e "$RM_CALLED" ] || fail "preview executed rm"
assert_contains "$ROOT/rust/target" "$PREVIEW_OUT"


set +e
"$SCRIPT" plan --root "$ROOT" --candidate A-001 > "$TMP_ROOT/missing-binding.txt" 2>&1
MISSING_BINDING_STATUS=$?
set -e
[ "$MISSING_BINDING_STATUS" -ne 0 ] || fail "plan accepted an unbound candidate"
assert_contains 'requires one --expected-path per --candidate' "$TMP_ROOT/missing-binding.txt"
set +e
"$SCRIPT" plan --root "$ROOT" --candidate A-001 --expected-path "$ROOT/python/.venv" > "$TMP_ROOT/mismatched-binding.txt" 2>&1
MISMATCHED_BINDING_STATUS=$?
set -e
[ "$MISMATCHED_BINDING_STATUS" -ne 0 ] || fail "plan accepted a remapped candidate"
assert_contains 'no longer matches the selected path' "$TMP_ROOT/mismatched-binding.txt"

ALL_PLAN_SCRIPT="$TMP_ROOT/all-cleanup.sh"
"$SCRIPT" plan --root "$ROOT" --scope workspace --all > "$ALL_PLAN_SCRIPT"
bash -n "$ALL_PLAN_SCRIPT"
assert_contains "$ROOT/rust/target" "$ALL_PLAN_SCRIPT"
assert_contains "$ROOT/python/.venv" "$ALL_PLAN_SCRIPT"

DRIFT_STATE="$TMP_ROOT/drift-state"
cat > "$FAKE_BIN/du" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-skx" ] && [ "$2" = "$DRIFT_ROOT" ]; then
    if [ ! -e "$DRIFT_STATE" ]; then
        printf 'first\n' > "$DRIFT_STATE"
        printf '100\t%s\n' "$DRIFT_ROOT"
    else
        printf '101\t%s\n' "$DRIFT_ROOT"
    fi
    exit 0
fi
exec /usr/bin/du "$@"
EOF
chmod +x "$FAKE_BIN/du"
DRIFTING_PLAN_SCRIPT="$TMP_ROOT/drifting-cleanup.sh"
PATH="$FAKE_BIN:$PATH" DRIFT_ROOT="$ROOT" DRIFT_STATE="$DRIFT_STATE" \
    "$SCRIPT" plan --root "$ROOT" --candidate A-001 --expected-path "$ROOT/rust/target" > "$DRIFTING_PLAN_SCRIPT"
bash -n "$DRIFTING_PLAN_SCRIPT"
assert_contains "$ROOT/rust/target" "$DRIFTING_PLAN_SCRIPT"

set +e
"$SCRIPT" plan --root "$ROOT" --scope workspace --all --candidate A-001 --expected-path "$ROOT/rust/target" > "$TMP_ROOT/conflicting-selection.txt" 2>&1
CONFLICTING_SELECTION_STATUS=$?
set -e
[ "$CONFLICTING_SELECTION_STATUS" -ne 0 ] || fail "plan accepted --all with explicit candidates"
assert_contains 'cannot combine --all with explicit candidates' "$TMP_ROOT/conflicting-selection.txt"
TAMPERED_SCRIPT="$TMP_ROOT/tampered.sh"
"$SCRIPT" plan --root "$ROOT" --candidate A-001 --expected-path "$ROOT/rust/target" --candidate A-002 --expected-path "$ROOT/python/.venv" > "$TAMPERED_SCRIPT"
mkdir -p "$TMP_ROOT/outside"
python3 -c 'import pathlib, sys; path = pathlib.Path(sys.argv[1]); path.write_text(path.read_text().replace(sys.argv[2], sys.argv[3], 1))' \
    "$TAMPERED_SCRIPT" "$ROOT/rust/target" "$TMP_ROOT/outside"
set +e
bash "$TAMPERED_SCRIPT" --execute > "$TMP_ROOT/tampered.txt" 2>&1
TAMPERED_STATUS=$?
set -e
[ "$TAMPERED_STATUS" -ne 0 ] || fail "tampered plan accepted out-of-root target"
assert_contains 'Refusing path outside audit root' "$TMP_ROOT/tampered.txt"
[ -d "$ROOT/rust/target" ] || fail "tampered plan removed a valid target"
[ -d "$ROOT/python/.venv" ] || fail "tampered plan removed a valid target"

bash "$PLAN_SCRIPT" --execute
[ ! -d "$ROOT/rust/target" ] || fail "execute did not remove selected target"
[ -f "$SENTINEL" ] || fail "execute removed local data"
SENTINEL_HASH_AFTER_PLAN=$(shasum -a 256 "$SENTINEL" | cut -d ' ' -f 1)
assert_equals "$SENTINEL_HASH_BEFORE" "$SENTINEL_HASH_AFTER_PLAN" "cleanup changed local data"

set +e
"$SCRIPT" plan --root "$ROOT" --candidate P-001 --expected-path "$ROOT/data" > "$TMP_ROOT/protected.txt" 2>&1
PROTECTED_STATUS=$?
set -e
[ "$PROTECTED_STATUS" -ne 0 ] || fail "plan accepted protected local data"
assert_contains 'not cleanup-eligible' "$TMP_ROOT/protected.txt"

printf 'PASS: storage audit safety contract\n'
