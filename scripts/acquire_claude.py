#!/usr/bin/env python3
"""Download the pinned Claude Code binary and verify it against its pinned SHA-256.

The version, URL template and per-platform digests live only in
``extensions/native-hosts.json``. Each digest was reviewed against the
release's GPG-signed ``manifest.json``. Nothing is executed from the
download and no installer script is fetched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
PINS_PATH = _REPO_ROOT / "extensions" / "native-hosts.json"
_PLATFORMS: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "linux-x64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x64",
}
_CHUNK = 1 << 20
_TIMEOUT_SECONDS = 120


class AcquisitionError(RuntimeError):
    """The pinned binary cannot be acquired with verified integrity."""


def current_platform() -> str:
    key = (platform.system(), platform.machine())
    if key not in _PLATFORMS:
        raise AcquisitionError(f"no Claude Code release platform for {key}")
    return _PLATFORMS[key]


def load_pin(platform_name: str) -> tuple[str, str, str]:
    """Return (version, url, sha256) for one platform from the pin file."""
    claude = json.loads(PINS_PATH.read_text(encoding="utf-8"))["claude"]
    digests: dict[str, str] = claude["sha256"]
    if platform_name not in digests:
        raise AcquisitionError(
            f"{PINS_PATH}: no reviewed digest pinned for {platform_name}"
        )
    version: str = claude["version"]
    url = claude["url"].format(version=version, platform=platform_name)
    return version, url, digests[platform_name]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire(dest: Path, platform_name: str) -> Path:
    """Place a verified binary at ``dest/claude`` and return its path."""
    version, url, expected = load_pin(platform_name)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "claude"
    if target.exists():
        if _sha256(target) != expected:
            raise AcquisitionError(
                f"{target} exists and does not match pinned Claude Code {version}"
            )
        return target
    descriptor, temp_name = tempfile.mkstemp(prefix=".claude-download-", dir=dest)
    temp = Path(temp_name)
    try:
        with (
            os.fdopen(descriptor, "wb") as handle,
            urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response,
        ):
            for chunk in iter(lambda: response.read(_CHUNK), b""):
                handle.write(chunk)
        observed = _sha256(temp)
        if observed != expected:
            raise AcquisitionError(
                f"{url}: SHA-256 {observed} does not match pinned {expected}"
            )
        temp.chmod(0o755)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download and verify the pinned Claude Code binary."
    )
    parser.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="directory to place the verified binary in",
    )
    args = parser.parse_args(argv)
    try:
        path = acquire(args.dest, current_platform())
    except (AcquisitionError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
