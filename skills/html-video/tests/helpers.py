"""Fixture builders shared by the html-video tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from hv_audit import AuditResult, audit_project
from hv_config import TEMPLATES_DIR
from hv_fonts import add_font

FAKE_WOFF2 = b"wOF2" + b"\x00" * 64
HEAD = '<meta charset="utf-8">'


def write(root: Path, rel: str, content: str | bytes = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def page(
    body: str = "", head: str = "", root_attrs: str = "", duration: str = "4"
) -> str:
    """A minimal valid composition; ``body`` goes inside the root."""
    return (
        f"<!doctype html><html><head>{HEAD}{head}</head><body>"
        f'<div id="root" data-composition-id="main" data-start="0" data-duration="{duration}" '
        f'data-width="1920" data-height="1080" data-no-timeline {root_attrs}>{body}</div></body></html>'
    )


def project(root: Path, html: str, files: dict[str, str | bytes] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    write(root, "index.html", html)
    for rel, content in (files or {}).items():
        write(root, rel, content)
    return root


def codes(result: AuditResult, severity: str | None = None) -> list[str]:
    return [
        f.code for f in result.findings if severity is None or f.severity == severity
    ]


def audit(root: Path, require_provenance: bool = False) -> AuditResult:
    return audit_project(root, require_provenance=require_provenance)


def template_project(tmp_path: Path, name: str, with_font: bool = True) -> Path:
    dest = tmp_path / name
    shutil.copytree(TEMPLATES_DIR / name, dest)
    if with_font:
        provision_font(dest, tmp_path)
    return dest


def provision_font(dest: Path, scratch: Path) -> None:
    font = write(scratch, "src/Test Font.woff2", FAKE_WOFF2)
    licence = write(scratch, "src/OFL.txt", "licence text")
    add_font(
        dest,
        font_file=font,
        family="Test Font",
        license_id="OFL-1.1",
        license_file=licence,
        source="https://example.invalid/test-font",
        weight="100 900",
    )
