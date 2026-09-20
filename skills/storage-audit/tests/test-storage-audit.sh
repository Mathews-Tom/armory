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
assert_contains 'Use the storage-audit skill to run a fresh strict scan' "$AUDIT_MARKDOWN"
assert_contains 'render—but do not save or execute—a cleanup script for cleanup-eligible candidates A-001, A-002.' "$AUDIT_MARKDOWN"
assert_not_contains '<selected IDs>' "$AUDIT_MARKDOWN"

assert_contains '"cleanup_eligible":true' "$REPO_JSON"

FAKE_BIN="$TMP_ROOT/fake-bin"
RM_CALLED="$TMP_ROOT/rm-called"
mkdir -p "$FAKE_BIN"
printf '#!/usr/bin/env bash\nprintf called > %q\nexit 99\n' "$RM_CALLED" > "$FAKE_BIN/rm"
chmod +x "$FAKE_BIN/rm"
PLAN_SCRIPT="$TMP_ROOT/cleanup.sh"
PATH="$FAKE_BIN:$PATH" "$SCRIPT" plan --root "$ROOT" --candidate A-001 > "$PLAN_SCRIPT"
[ ! -e "$RM_CALLED" ] || fail "plan executed rm"
bash -n "$PLAN_SCRIPT"
assert_contains '#!/usr/bin/env bash' "$PLAN_SCRIPT"
assert_contains 'Preview only.' "$PLAN_SCRIPT"
assert_contains '--execute' "$PLAN_SCRIPT"
PREVIEW_OUT="$TMP_ROOT/preview.txt"
PATH="$FAKE_BIN:$PATH" bash "$PLAN_SCRIPT" > "$PREVIEW_OUT"
[ ! -e "$RM_CALLED" ] || fail "preview executed rm"
assert_contains "$ROOT/rust/target" "$PREVIEW_OUT"

TAMPERED_SCRIPT="$TMP_ROOT/tampered.sh"
"$SCRIPT" plan --root "$ROOT" --candidate A-001 --candidate A-002 > "$TAMPERED_SCRIPT"
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
"$SCRIPT" plan --root "$ROOT" --candidate P-001 > "$TMP_ROOT/protected.txt" 2>&1
PROTECTED_STATUS=$?
set -e
[ "$PROTECTED_STATUS" -ne 0 ] || fail "plan accepted protected local data"
assert_contains 'not cleanup-eligible' "$TMP_ROOT/protected.txt"

printf 'PASS: storage audit safety contract\n'
