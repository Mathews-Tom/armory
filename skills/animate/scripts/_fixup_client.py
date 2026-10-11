"""
_fixup_client.py — LLM-based Manim scene fixup helper.

Sends a failing scene file + stderr to the LLM using the coder fixup prompt
and returns the patched scene contents as a string.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

import anthropic

from _config import model_for

_FENCED_PYTHON_RE = re.compile(
    r"```python\s*\n(.*?)```",
    re.DOTALL,
)

_DEFAULT_FIXUP_MODEL = model_for("fixup")

_CODER_PROMPT_PATH = (
    Path(__file__).parent.parent / "references" / "code2video" / "coder.md"
)

# ---------------------------------------------------------------------------
# Structural protocol — allows dependency injection of fakes in tests
# without weakening the production type to Any.
# ---------------------------------------------------------------------------


@runtime_checkable
class _MessagesAPI(Protocol):
    def create(self, **kwargs: Any) -> Any:  # noqa: ANN401
        ...


@runtime_checkable
class ClientProtocol(Protocol):
    """Structural type accepted by request_patch for DI."""

    @property
    def messages(self) -> _MessagesAPI: ...


# The concrete real type — exported for callers that want to hint explicitly.
AnthropicClient = anthropic.Anthropic


def _load_fixup_prompt() -> str:
    """Load the coder fixup prompt from the vendored reference file."""
    if not _CODER_PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Coder fixup prompt not found: {_CODER_PROMPT_PATH}. "
            "Ensure worker-p0 has created references/code2video/coder.md."
        )
    return _CODER_PROMPT_PATH.read_text(encoding="utf-8")


def request_patch(
    scene_path: Path,
    stderr: str,
    offending_lines: tuple[int, int] | None,
    *,
    client: ClientProtocol | None = None,
    model: str = _DEFAULT_FIXUP_MODEL,
) -> str:
    """
    Send scene source + stderr to the LLM and return the patched scene content.

    Args:
        scene_path: Absolute path to the Manim scene .py file.
        stderr: Full stderr captured from the failed manim render call.
        offending_lines: Optional (start, end) 1-indexed line range extracted
            from the traceback. If None, the full file is provided to the LLM.
        client: Injected client for testing. Pass None to build a real one.
        model: Model identifier string.

    Returns:
        New scene file contents as a plain string (no fences).

    Raises:
        FileNotFoundError: If the coder prompt file is missing.
        ValueError: If the LLM response contains no fenced ```python block.
    """
    fixup_prompt = _load_fixup_prompt()
    scene_source = scene_path.read_text(encoding="utf-8")

    if offending_lines is not None:
        lines = scene_source.splitlines()
        start = max(0, offending_lines[0] - 1)
        end = min(len(lines), offending_lines[1])
        excerpt = "\n".join(lines[start:end])
        scope_note = (
            f"Offending lines {offending_lines[0]}–{offending_lines[1]}:\n"
            f"```python\n{excerpt}\n```\n\n"
        )
    else:
        scope_note = ""

    user_message = (
        f"{fixup_prompt}\n\n"
        f"## Scene file: {scene_path.name}\n\n"
        f"```python\n{scene_source}\n```\n\n"
        f"## Render error (stderr)\n\n"
        f"```\n{stderr}\n```\n\n"
        f"{scope_note}"
        "Return the complete corrected scene file inside a single fenced "
        "```python ... ``` block. Do not truncate or omit any part of the file."
    )

    resolved_client: ClientProtocol = (
        client if client is not None else cast(ClientProtocol, AnthropicClient())
    )

    response = resolved_client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{"role": "user", "content": user_message}],
    )

    raw: str = response.content[0].text

    match = _FENCED_PYTHON_RE.search(raw)
    if match is None:
        raise ValueError(
            f"LLM response contained no fenced ```python block.\n\nRaw response:\n{raw}"
        )

    return match.group(1)
