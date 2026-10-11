"""User-declared provenance for every non-document asset in a project.

``PROVENANCE.json`` records what the user (or ``fonts add``) states about an
asset. Nothing here verifies that a stated licence is true; the audit only
checks that a declaration exists, is well formed, and matches the file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PROVENANCE_FILE = "PROVENANCE.json"
SCHEMA_VERSION = 1
FONT_EXTENSIONS = (".woff2", ".woff", ".ttf", ".otf")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9 _-]{0,63}")
_WEIGHT = re.compile(r"([1-9]00)(?: ([1-9]00))?")
_STYLES = ("normal", "italic", "oblique")
FONT_FORMATS = {"woff2": "woff2", "woff": "woff", "ttf": "truetype", "otf": "opentype"}


@dataclass(frozen=True)
class FontMeta:
    alias: str
    weight: str
    style: str
    format: str
    family: str


@dataclass(frozen=True)
class Entry:
    path: str
    source: str
    license: str
    license_file: str | None = None
    sha256: str | None = None
    font: FontMeta | None = None


def safe_project_path(root: Path, value: str) -> Path:
    """Validate a canonical relative asset path before any read, write or unlink."""
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError(f"path {value!r} must be a canonical project-relative path")
    target = root / value
    try:
        contained = target.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"path {value!r} cannot be resolved safely: {exc}") from exc
    if not contained:
        raise ValueError(f"path {value!r} escapes outside the project")
    return target


def font_metadata_error(font: FontMeta) -> str | None:
    """Validate saved and newly supplied font metadata using one contract."""
    if not _ALIAS.fullmatch(font.alias):
        return "alias must start with a letter and use only letters, digits, space, '_' or '-'"
    weights = _WEIGHT.fullmatch(font.weight)
    if weights is None or (
        weights.group(2) and int(weights.group(2)) <= int(weights.group(1))
    ):
        return 'weight must be a CSS weight such as "400" or an ascending range such as "100 900"'
    if font.style not in _STYLES:
        return f"style must be one of {', '.join(_STYLES)}"
    if font.format not in FONT_FORMATS:
        return f"format must be one of {', '.join(FONT_FORMATS)}"
    if not font.family.strip():
        return "family must name the real font family"
    return None


def _text(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _font(raw: object, where: str, problems: list[str]) -> FontMeta | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append(f"{where}: font must be an object")
        return None
    data = {str(k): v for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    fields = [
        _text(data, key) for key in ("alias", "weight", "style", "format", "family")
    ]
    if any(field is None for field in fields):
        problems.append(f"{where}: font needs alias, weight, style, format and family")
        return None
    alias, weight, style, fmt, family = (str(field) for field in fields)
    font = FontMeta(alias, weight, style, fmt, family)
    problem = font_metadata_error(font)
    if problem:
        problems.append(f"{where}: {problem}")
        return None
    return font


def read_provenance(root: Path) -> tuple[list[Entry], list[str]]:
    """Return entries and a list of human-readable problems. Missing file is empty."""
    try:
        path = safe_project_path(root, PROVENANCE_FILE)
    except ValueError as exc:
        return [], [f"{PROVENANCE_FILE}: {exc}"]
    if not path.exists():
        return [], []
    try:
        document: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], [f"{PROVENANCE_FILE}: cannot parse ({exc})"]
    if not isinstance(document, dict):
        return [], [f"{PROVENANCE_FILE}: top level must be an object"]
    top = {str(k): v for k, v in document.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if top.get("version") != SCHEMA_VERSION:
        return [], [f"{PROVENANCE_FILE}: version must be {SCHEMA_VERSION}"]
    items = top.get("assets")
    if not isinstance(items, list):
        return [], [f"{PROVENANCE_FILE}: assets must be a list"]
    entries: list[Entry] = []
    problems: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        where = f"{PROVENANCE_FILE} assets[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: must be an object")
            continue
        raw = {str(k): v for k, v in item.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        path_value, source, licence = (
            _text(raw, "path"),
            _text(raw, "source"),
            _text(raw, "license"),
        )
        if path_value is None or source is None or licence is None:
            problems.append(
                f"{where}: path, source and license are required non-empty strings"
            )
            continue
        if path_value in seen:
            problems.append(f"{where}: duplicate declaration for {path_value}")
            continue
        seen.add(path_value)
        digest = raw.get("sha256")
        if digest is not None and not (
            isinstance(digest, str) and _SHA256.fullmatch(digest)
        ):
            problems.append(f"{where}: sha256 must be 64 lowercase hex characters")
            continue
        license_file = raw.get("license_file")
        if license_file is not None and not isinstance(license_file, str):
            problems.append(f"{where}: license_file must be a string")
            continue
        try:
            safe_project_path(root, path_value)
            if license_file is not None:
                safe_project_path(root, license_file)
        except ValueError as exc:
            problems.append(f"{where}: {exc}")
            continue
        entries.append(
            Entry(
                path=path_value,
                source=source,
                license=licence,
                license_file=license_file,
                sha256=digest,
                font=_font(raw.get("font"), where, problems),
            )
        )
    return entries, problems


def write_provenance(root: Path, entries: list[Entry]) -> None:
    target = safe_project_path(root, PROVENANCE_FILE)
    for entry in entries:
        safe_project_path(root, entry.path)
        if entry.license_file is not None:
            safe_project_path(root, entry.license_file)
        if entry.font is not None:
            problem = font_metadata_error(entry.font)
            if problem:
                raise ValueError(f"{entry.path}: {problem}")
    assets: list[dict[str, object]] = []
    for entry in sorted(entries, key=lambda e: e.path):
        item: dict[str, object] = {
            "path": entry.path,
            "source": entry.source,
            "license": entry.license,
        }
        if entry.license_file is not None:
            item["license_file"] = entry.license_file
        if entry.sha256 is not None:
            item["sha256"] = entry.sha256
        if entry.font is not None:
            item["font"] = {
                "alias": entry.font.alias,
                "weight": entry.font.weight,
                "style": entry.font.style,
                "format": entry.font.format,
                "family": entry.font.family,
            }
        assets.append(item)
    document = {"version": SCHEMA_VERSION, "assets": assets}
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
