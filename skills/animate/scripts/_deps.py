"""Explicit dependency checks for the animate scripts.

Nothing here installs anything. Every helper either returns or raises
``MissingDependencyError`` with the exact command a person can run.
"""

from __future__ import annotations

import importlib.util
import shutil

MANIM_REQUIREMENT = "manim==0.19.2"

MANIM_INSTALL_HINT = (
    "Manim is not importable by this interpreter. Provision it once, in an "
    "isolated environment, then run the animate scripts with that environment's python:\n"
    '  ANIMATE_ENV="${XDG_CACHE_HOME:-$HOME/.cache}/animate/venv"\n'
    '  uv venv --python 3.12 "$ANIMATE_ENV"\n'
    f'  uv pip install --python "$ANIMATE_ENV/bin/python" "{MANIM_REQUIREMENT}"\n'
    "If uv has to build manimpango/pycairo from source, install the system "
    "libraries first (macOS: brew install cairo pango pkg-config; Debian/Ubuntu: "
    "sudo apt-get install libcairo2-dev libpango1.0-dev pkg-config python3-dev). "
    "These scripts never install packages themselves."
)

_BINARY_HINTS: dict[str, str] = {
    "ffmpeg": (
        "ffmpeg is required. Install it yourself or ask the user to "
        "(macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt-get install ffmpeg). "
        "These scripts never install system packages."
    ),
    "ffprobe": (
        "ffprobe ships with ffmpeg and is required. Install ffmpeg yourself or ask "
        "the user to (macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt-get install ffmpeg). "
        "These scripts never install system packages."
    ),
}


class MissingDependencyError(RuntimeError):
    """A required tool or package is absent; the message says how to provide it."""


def require_binary(name: str) -> str:
    """Return the resolved path of *name* or raise MissingDependencyError."""
    found = shutil.which(name)
    if found is None:
        hint = _BINARY_HINTS.get(name, f"Install {name} and make sure it is on PATH.")
        raise MissingDependencyError(f"{name} was not found on PATH. {hint}")
    return found


def require_manim() -> None:
    """Raise MissingDependencyError unless manim can be imported (without importing it)."""
    if importlib.util.find_spec("manim") is None:
        raise MissingDependencyError(MANIM_INSTALL_HINT)
