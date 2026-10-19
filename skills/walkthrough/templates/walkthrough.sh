#!/usr/bin/env bash
# Bash 3.2-compatible launcher. Keep the sibling Python helper when copying.
# Invoke with bash; no executable permission or shell sourcing is needed.
set +x
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'STATE failed: Python 3.9+ is required.' >&2
  exit 1
fi
exec python3 "$SCRIPT_DIR/walkthrough.py" "$@"
