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
mkdir -p "$ROOT/rust/target" "$ROOT/python/.venv" "$ROOT/data" "$ROOT/linked-target"

(
    cd "$ROOT/rust"
    git init -q
    printf '[package]\nname = "fixture"\nversion = "0.1.0"\n' > Cargo.toml
    printf 'target/\n' > .gitignore
    dd if=/dev/zero of=target/cache.bin bs=1024 count=16 status=none
    mkdir -p .worktrees/active
)
(
    cd "$ROOT/python"
    git init -q
    printf '[project]\nname = "fixture"\nversion = "0.1.0"\n' > pyproject.toml
    printf 'version = 1\n' > uv.lock
    printf '.venv/\n' > .gitignore
    printf 'environment\n' > .venv/marker
)
printf 'local corpus\n' > "$ROOT/data/corpus.jsonl"
ln -s "$ROOT/rust/target" "$ROOT/linked-target/target-link"
ROOT=$(cd -P "$ROOT" && pwd -P)

SENTINEL="$ROOT/data/corpus.jsonl"
SENTINEL_HASH_BEFORE=$(shasum -a 256 "$SENTINEL" | cut -d ' ' -f 1)
AUDIT_JSON="$TMP_ROOT/audit.json"
"$SCRIPT" audit --root "$ROOT" --scope workspace --strict --format json > "$AUDIT_JSON"
python3 -c 'import json, pathlib, sys; json.loads(pathlib.Path(sys.argv[1]).read_text())' "$AUDIT_JSON"
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
assert_contains '"cleanup_eligible":true' "$REPO_JSON"

FAKE_BIN="$TMP_ROOT/fake-bin"
RM_CALLED="$TMP_ROOT/rm-called"
mkdir -p "$FAKE_BIN"
printf '#!/usr/bin/env bash\nprintf called > %q\nexit 99\n' "$RM_CALLED" > "$FAKE_BIN/rm"
chmod +x "$FAKE_BIN/rm"
PLAN_OUT="$TMP_ROOT/plan.txt"
PATH="$FAKE_BIN:$PATH" "$SCRIPT" plan --root "$ROOT" --candidate A-001 > "$PLAN_OUT"
[ ! -e "$RM_CALLED" ] || fail "plan executed rm"
assert_contains "rm -rf -- '$ROOT/rust/target'" "$PLAN_OUT"
assert_contains 'cargo build' "$PLAN_OUT"

set +e
"$SCRIPT" plan --root "$ROOT" --candidate P-001 > "$TMP_ROOT/protected.txt" 2>&1
PROTECTED_STATUS=$?
set -e
[ "$PROTECTED_STATUS" -ne 0 ] || fail "plan accepted protected local data"
assert_contains 'not cleanup-eligible' "$TMP_ROOT/protected.txt"

printf 'PASS: storage audit safety contract\n'
