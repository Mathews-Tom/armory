from __future__ import annotations

from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def data_path(group: str, name: str) -> Path:
    """Resolve bundled asset or reference data without exposing package layout."""
    if group not in ("assets", "references"):
        raise ValueError(f"unsupported package data group: {group!r}")
    return _PACKAGE_ROOT / group / name
