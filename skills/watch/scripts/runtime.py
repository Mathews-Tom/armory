"""Bounded subprocess execution and display-safe diagnostics."""

from __future__ import annotations

import re
import subprocess

from evidence import EvidenceError


_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def diagnostic(text: str, limit: int = 1200) -> str:
    cleaned = _ANSI.sub("", text)
    cleaned = "".join(c for c in cleaned if c in "\n\t" or ord(c) >= 32)
    return cleaned.strip()[-limit:]


def run(
    command: list[str], *, timeout: float = 300.0
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        raise EvidenceError(f"Missing executable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise EvidenceError(f"{command[0]} exceeded its {timeout:g}s deadline") from exc
    except OSError as exc:
        raise EvidenceError(f"Cannot run {command[0]}: {diagnostic(str(exc))}") from exc
    if result.returncode:
        raise EvidenceError(
            f"{command[0]} failed ({result.returncode}): {diagnostic(result.stderr)}"
        )
    return result
