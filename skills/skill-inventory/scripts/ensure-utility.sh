#!/usr/bin/env bash
# Locate an installed armory skill-inventory utility, or install the released one
# when explicitly asked. Prints UTILITY_ROOT=... and VERSION=... on success.
#
# Exit codes: 0 found or installed, 3 not installed (rerun with --install),
# 1 download/verification/placement failure, 64 usage error.
set -euo pipefail

readonly RELEASE_URL="https://github.com/Mathews-Tom/armory/releases/download/latest"
readonly DEFAULT_DEST="${XDG_DATA_HOME:-$HOME/.local/share}/armory/utilities/skill-inventory"
readonly CANDIDATES=("$HOME/.claude/utilities/skill-inventory" "$DEFAULT_DEST")

usage() {
  echo "usage: ensure-utility.sh [--install [DEST]]" >&2
  exit 64
}

fail() {
  echo "ensure-utility: $*" >&2
  exit 1
}

version_of() {
  awk '/^---$/ { fence++; next } fence == 1 && $1 == "version:" { print $2; exit }' "$1/UTILITY.md"
}

report() {
  echo "UTILITY_ROOT=$1"
  echo "VERSION=$(version_of "$1")"
}

is_utility() {
  [ -f "$1/UTILITY.md" ] && [ -f "$1/scripts/skill_inventory.py" ]
}

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{ print $1 }'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{ print $1 }'
  else
    fail "need shasum or sha256sum to verify the download"
  fi
}

install=false
dest="$DEFAULT_DEST"
case "$#" in
  0) ;;
  1 | 2)
    [ "$1" = "--install" ] || usage
    install=true
    if [ "$#" -eq 2 ]; then
      [ -n "$2" ] || usage
      case "$2" in
        /*) dest="$2" ;;
        *) dest="$PWD/$2" ;;
      esac
    fi
    ;;
  *) usage ;;
esac

for candidate in "${CANDIDATES[@]}" "$dest"; do
  if is_utility "$candidate"; then
    report "$candidate"
    exit 0
  fi
done

if [ "$install" = false ]; then
  echo "ensure-utility: skill-inventory is not installed; rerun with --install after owner approval" >&2
  exit 3
fi

[ ! -e "$dest" ] || fail "$dest exists but is not a skill-inventory utility; inspect it before installing"
for tool in curl unzip; do
  command -v "$tool" >/dev/null 2>&1 || fail "missing required tool: $tool"
done

# Stage beside the destination so the final move is a same-filesystem rename.
mkdir -p "$(dirname "$dest")"
work="$(mktemp -d "$(dirname "$dest")/.skill-inventory.XXXXXX")"
trap 'rm -rf "$work"' EXIT

curl -fsSL --retry 3 --retry-delay 2 --max-time 120 -o "$work/checksums.txt" "$RELEASE_URL/checksums.txt" ||
  fail "could not download the release checksum list"
asset="$(awk '$2 ~ /^skill-inventory-[0-9]+\.[0-9]+\.[0-9]+\.utility$/ { print $2 }' "$work/checksums.txt")"
[ -n "$asset" ] && [ "$(printf '%s\n' "$asset" | wc -l | tr -d ' ')" = 1 ] ||
  fail "expected exactly one skill-inventory asset in the release checksum list"
expected="$(awk -v name="$asset" '$2 == name { print $1 }' "$work/checksums.txt")"

curl -fsSL --retry 3 --retry-delay 2 --max-time 300 -o "$work/$asset" "$RELEASE_URL/$asset" || fail "could not download $asset"
actual="$(sha256_of "$work/$asset")"
[ "$actual" = "$expected" ] || fail "checksum mismatch for $asset; nothing was installed"

unzip -q "$work/$asset" -d "$work/unpacked" || fail "could not unpack $asset"
is_utility "$work/unpacked/skill-inventory" || fail "$asset does not contain a skill-inventory utility"

mv "$work/unpacked/skill-inventory" "$dest"
report "$dest"
