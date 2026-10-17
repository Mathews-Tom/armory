"""Installed-skill catalog read from approved local roots only.

Names, descriptions and identities come from installed ``SKILL.md`` files. A name
seen in a log is never resolved to a file here; matching a historical name to a
current file is unverified provenance. Paths named by logs are never opened: the
catalog only records which approved paths map to which installed file.

``Inventory.coverage`` holds fixed literal codes with integer counts. Codes in
``BLOCKING_COVERAGE`` mean the inventory may be incomplete or unreliable; the rest
are informational.
"""

from __future__ import annotations

import os
import re
import stat
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

import yaml
from inventory_io import (
    CHUNK_BYTES,
    keyed_digest,
    keyed_hasher,
    open_directory,
    open_regular,
)
from inventory_types import Harness, InstalledSkill, Inventory, SchemaError, as_object

OWNERSHIP_MANAGED = "managed"
OWNERSHIP_USER = "user"
OWNERSHIP_PROTECTED = "protected"
OWNERSHIP_UNKNOWN = "unknown"

BLOCKING_COVERAGE = frozenset(
    {
        "alias_escape",
        "default_roots_unavailable",
        "frontmatter_invalid",
        "reference_invalid",
        "reference_unreadable",
        "skill_file_oversize",
        "skill_file_unusable",
        "skill_root_unusable",
        "skill_roots_unavailable",
    }
)

MAX_SKILL_BYTES = 2 << 20
MAX_REFERENCE_BYTES = 1 << 20
_MIN_KEY_BYTES = 16
_MAX_NODES = 100_000
_MAX_DEPTH = 64
# Lower is stronger: only a root that is purely managed is ever a mutation candidate.
_STRENGTH = {
    OWNERSHIP_USER: 0,
    OWNERSHIP_PROTECTED: 1,
    OWNERSHIP_UNKNOWN: 2,
    OWNERSHIP_MANAGED: 3,
}
_SKILL_URI = re.compile(r"skill://([\w%-]+(?:\.[\w%-]+)*)")
_SKILL_SLASH = re.compile(r"(?<![\w/:.-])/skill:([A-Za-z0-9][\w-]*)")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_REFERENCE_SUFFIXES = frozenset({".yaml", ".yml", ".json"})


@dataclass(frozen=True)
class _ConfiguredRoot:
    lexical: Path
    ownership: str
    visible: bool


@dataclass
class _ApprovedRoot:
    resolved: Path
    ownership: str
    visible: bool
    lexicals: set[str]


@dataclass(frozen=True)
class _Sighting:
    root: Path
    name: str
    link: bool


@dataclass(frozen=True)
class _FileRead:
    data: bytes | None
    size: int
    digest: str
    born: float | None


def _stronger(first: str, second: str) -> str:
    return first if _STRENGTH[first] <= _STRENGTH[second] else second


def _lexical(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _configured_roots(
    harness: Harness, skill_roots: Sequence[Path] | None, coverage: Counter[str]
) -> list[_ConfiguredRoot]:
    """Explicit roots replace defaults; only OMP has defaults until Claude/Codex adapters land."""
    if skill_roots is not None:
        return [
            _ConfiguredRoot(_lexical(root), OWNERSHIP_UNKNOWN, True)
            for root in skill_roots
        ]
    if harness == "omp":
        agent = Path.home() / ".omp" / "agent"
        return [
            _ConfiguredRoot(agent / "managed-skills", OWNERSHIP_MANAGED, True),
            _ConfiguredRoot(agent / "skills", OWNERSHIP_USER, True),
            # Shared skills are protected alias targets, not assumed visible to OMP.
            _ConfiguredRoot(
                Path.home() / ".agents" / "skills", OWNERSHIP_PROTECTED, False
            ),
        ]
    coverage["default_roots_unavailable"] += 1
    return []


def _approve_roots(
    configured: Sequence[_ConfiguredRoot], coverage: Counter[str], evidence: list[str]
) -> dict[Path, _ApprovedRoot]:
    """Resolve each root link once and merge roots that resolve to the same directory."""
    approved: dict[Path, _ApprovedRoot] = {}
    for root in configured:
        resolved = Path(os.path.realpath(root.lexical))
        try:
            state = "dir" if stat.S_ISDIR(os.stat(resolved).st_mode) else "unusable"
        except FileNotFoundError:
            state = "missing"
        except OSError:
            state = "unusable"
        evidence.append(
            f"root|{root.lexical}|{resolved}|{root.ownership}|{int(root.visible)}|{state}"
        )
        if state == "missing":
            if root.visible:
                coverage["skill_root_missing"] += 1
            continue
        if state == "unusable":
            coverage["skill_root_unusable"] += 1
            continue
        existing = approved.get(resolved)
        if existing is None:
            approved[resolved] = _ApprovedRoot(
                resolved,
                root.ownership,
                root.visible,
                {str(root.lexical), str(resolved)},
            )
            continue
        coverage["duplicate_root"] += 1
        existing.ownership = _stronger(existing.ownership, root.ownership)
        existing.visible = existing.visible or root.visible
        existing.lexicals.add(str(root.lexical))
    return approved


def _entry_kind(entry: os.DirEntry[str]) -> str:
    if entry.is_symlink():
        return "link"
    if entry.is_dir(follow_symlinks=False):
        return "dir"
    if entry.is_file(follow_symlinks=False):
        return "file"
    return "other"


def _scan_root(
    root: _ApprovedRoot,
    approved: Sequence[Path],
    coverage: Counter[str],
    evidence: list[str],
    found: dict[Path, list[_Sighting]],
) -> None:
    """One directory level; resolve aliases only inside explicitly approved roots."""
    try:
        directory_fd = open_directory(root.resolved)
    except OSError:
        coverage["skill_root_unusable"] += 1
        evidence.append(f"listing|{root.resolved}|unreadable")
        return
    try:
        with os.scandir(directory_fd) as scan:
            entries = sorted(scan, key=lambda item: item.name)
        for entry in entries:
            kind = _entry_kind(entry)
            entry_path = root.resolved / entry.name
            target = os.path.realpath(entry_path) if kind == "link" else ""
            evidence.append(f"entry|{root.resolved}|{entry.name}|{kind}|{target}")
            if entry.name.startswith("."):
                coverage["hidden_entry_skipped"] += 1
                continue
            if kind not in ("dir", "link"):
                continue
            skill_file = entry_path / "SKILL.md"
            try:
                os.lstat(skill_file)
            except FileNotFoundError:
                coverage["non_skill_entry"] += 1
                continue
            except OSError:
                coverage["skill_file_unusable"] += 1
                evidence.append(f"file|{skill_file}|unreadable")
                continue
            real = Path(os.path.realpath(skill_file))
            if not any(real.is_relative_to(base) for base in approved):
                coverage["alias_escape"] += 1
                continue
            try:
                regular = stat.S_ISREG(os.lstat(real).st_mode)
            except OSError:
                regular = False
            if not regular:
                coverage["skill_file_unusable"] += 1
                continue
            found.setdefault(real, []).append(
                _Sighting(root.resolved, entry.name, kind == "link")
            )
    except OSError:
        coverage["skill_root_unusable"] += 1
        evidence.append(f"listing|{root.resolved}|unreadable")
    finally:
        os.close(directory_fd)


def _birth(info: os.stat_result) -> float | None:
    value = getattr(info, "st_birthtime", None)
    if isinstance(value, int | float) and value > 0:
        return float(value)
    return None


def _read_file(path: Path, key: bytes, label: str, limit: int) -> _FileRead | None:
    """Keyed digest of the whole file; content is kept only when within the limit."""
    try:
        fd, info = open_regular(path)
    except OSError:
        return None
    hasher = keyed_hasher(key, label)
    parts: list[bytes] = []
    size = 0
    try:
        with os.fdopen(fd, "rb") as handle:
            while chunk := handle.read(CHUNK_BYTES):
                size += len(chunk)
                hasher.update(chunk)
                if size <= limit:
                    parts.append(chunk)
    except OSError:
        return None
    return _FileRead(
        b"".join(parts) if size <= limit else None,
        size,
        hasher.hexdigest(),
        _birth(info),
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, object] | None, str, str]:
    """Split a leading ``---`` block and load it with PyYAML; returns (mapping, body, status)."""
    lines = text.removeprefix("\ufeff").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text, "missing"
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            block = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            break
    else:
        return None, text, "invalid"
    try:
        loaded = yaml.safe_load(block)
        mapping: dict[str, object] = {} if loaded is None else as_object(loaded)
    except (yaml.YAMLError, SchemaError, RecursionError, ValueError):
        return None, body, "invalid"
    return mapping, body, "ok"


def _headings(body: str) -> tuple[str, ...]:
    """ATX headings outside fenced code blocks."""
    headings: list[str] = []
    fence: str | None = None
    for line in body.splitlines():
        opener = _FENCE.match(line)
        if opener:
            marker = opener.group(1)
            if fence is None:
                fence = marker
            elif (
                marker[0] == fence[0]
                and len(marker) >= len(fence)
                and not line.strip().strip(marker[0])
            ):
                fence = None
            continue
        if fence is None and (heading := _HEADING.match(line)):
            headings.append(heading.group(1).strip())
    return tuple(headings)


def _installed_at(info: _FileRead, directory: Path) -> datetime | None:
    """Earliest filesystem birth time: install evidence only, never authored creation."""
    born = [info.born]
    try:
        born.append(_birth(os.stat(directory)))
    except OSError:
        pass
    known = [value for value in born if value is not None]
    if not known:
        return None
    try:
        return datetime.fromtimestamp(min(known), UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _text_names(text: str) -> set[str]:
    """Names from explicit ``skill://`` URIs and ``/skill:`` tokens: first segment only."""
    names = {unquote(match) for match in _SKILL_URI.findall(text)}
    names.update(_SKILL_SLASH.findall(text))
    names.discard("")
    return names


def _autoload_names(value: object) -> set[str] | None:
    if value is None:
        return set()
    if not isinstance(value, list):
        return None
    names: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return None
        text = item.strip()
        plain = (
            {text} if text and "://" not in text and not text.startswith("/") else set()
        )
        found = _text_names(text) or plain
        if not found:
            return None
        names |= found
    return names


def _dependency_names(documents: Sequence[object]) -> set[str] | None:
    """Dependency names from ``autoloadSkills`` lists and explicit text references."""
    names: set[str] = set()
    stack: list[tuple[object, int]] = [(document, 0) for document in documents]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            return None
        if isinstance(value, dict):
            for field_name, child in value.items():
                if field_name == "autoloadSkills":
                    declared = _autoload_names(child)
                    if declared is None:
                        return None
                    names |= declared
                else:
                    stack.append((child, depth + 1))
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)
        elif isinstance(value, str):
            names |= _text_names(value)
    return names


def _reference_names(suffix: str, data: bytes) -> set[str] | None:
    """Markdown: frontmatter structure plus body text. YAML/JSON: structure only."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if suffix in (".md", ".markdown"):
        mapping, body, status = _parse_frontmatter(text)
        if status == "invalid":
            return None
        declared = _dependency_names([] if mapping is None else [mapping])
        return None if declared is None else declared | _text_names(body)
    if suffix not in _REFERENCE_SUFFIXES:
        return None
    try:
        return _dependency_names(list(yaml.safe_load_all(text)))
    except (yaml.YAMLError, RecursionError, ValueError):
        return None


def _read_references(
    paths: Sequence[Path], key: bytes, coverage: Counter[str], evidence: list[str]
) -> set[str]:
    names: set[str] = set()
    if not paths:
        coverage["references_not_provided"] += 1
        return names
    for path in paths:
        lexical = _lexical(path)
        real = Path(os.path.realpath(lexical))
        read = _read_file(real, key, "reference", MAX_REFERENCE_BYTES)
        if read is None:
            evidence.append(f"ref|{lexical}|{real}|unreadable")
            coverage["reference_unreadable"] += 1
            continue
        evidence.append(f"ref|{lexical}|{real}|{read.size}|{read.digest}")
        if read.data is None:
            coverage["reference_unreadable"] += 1
            continue
        declared = _reference_names(lexical.suffix.lower(), read.data)
        if declared is None:
            coverage["reference_invalid"] += 1
            continue
        names |= declared
        coverage["reference_files_read"] += 1
    return names


def _ownership(
    canonical: Path, sightings: Sequence[_Sighting], roots: Sequence[_ApprovedRoot]
) -> str:
    """Location decides; a purely managed file stays managed only if every view is managed."""
    containing = [
        root.ownership for root in roots if canonical.is_relative_to(root.resolved)
    ]
    by_root = {root.resolved: root.ownership for root in roots}
    seen = containing + [by_root[sighting.root] for sighting in sightings]
    chosen = [value for value in containing if value != OWNERSHIP_MANAGED] or seen
    result = chosen[0]
    for value in chosen[1:]:
        result = _stronger(result, value)
    if result == OWNERSHIP_MANAGED and any(sighting.link for sighting in sightings):
        return OWNERSHIP_PROTECTED
    return result


def _skill_fields(
    canonical: Path, data: bytes, coverage: Counter[str]
) -> tuple[str, str, tuple[str, ...]]:
    """Installed-file-sourced name, description and body headings."""
    mapping: dict[str, object] | None = None
    body = ""
    status = "invalid"
    try:
        mapping, body, status = _parse_frontmatter(data.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    if status == "invalid":
        coverage["frontmatter_invalid"] += 1
    elif status == "missing":
        coverage["frontmatter_missing"] += 1
    raw_name = None if mapping is None else mapping.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        name = raw_name.strip()
    else:
        name = canonical.parent.name
        if status == "ok":
            coverage["name_from_directory"] += 1
    raw_description = None if mapping is None else mapping.get("description")
    if isinstance(raw_description, str):
        description = raw_description
    else:
        description = ""
        if status == "ok":
            code = (
                "description_missing"
                if raw_description is None
                else "description_invalid"
            )
            coverage[code] += 1
    return name, description, _headings(body)


def _path_variants(
    canonical: Path,
    sightings: Sequence[_Sighting],
    roots: Sequence[_ApprovedRoot],
) -> set[str]:
    """Every approved lexical path that reaches this file, canonical path included."""
    by_root = {root.resolved: root for root in roots}
    variants = {str(canonical)}
    for root in roots:
        if canonical.is_relative_to(root.resolved):
            relative = canonical.relative_to(root.resolved)
            variants.update(
                os.path.normpath(os.path.join(lexical, relative))
                for lexical in root.lexicals
            )
    for sighting in sightings:
        variants.update(
            os.path.normpath(os.path.join(lexical, sighting.name, "SKILL.md"))
            for lexical in by_root[sighting.root].lexicals
        )
    return variants


def _digest_evidence(key: bytes, evidence: Sequence[str]) -> str:
    """Order-independent, unambiguous keyed digest over current installed evidence."""
    payload = "\n".join(sorted(repr(line) for line in evidence))
    return keyed_digest(key, "inventory", payload.encode("utf-8", "backslashreplace"))


def load_inventory(
    harness: Harness,
    *,
    key: bytes,
    skill_roots: Sequence[Path] | None = None,
    reference_paths: Sequence[Path] = (),
) -> Inventory:
    """Catalog installed skills from approved roots with a keyed drift-detecting digest."""
    if len(key) < _MIN_KEY_BYTES:
        raise SchemaError("invalid_key")
    coverage: Counter[str] = Counter()
    evidence: list[str] = []
    configured = _configured_roots(harness, skill_roots, coverage)
    approved = _approve_roots(configured, coverage, evidence)
    ordered = sorted(
        approved.values(),
        key=lambda root: (_STRENGTH[root.ownership], str(root.resolved)),
    )
    approved_paths = [root.resolved for root in ordered]
    visible = [root for root in ordered if root.visible]
    if not visible:
        coverage["skill_roots_unavailable"] += 1

    found: dict[Path, list[_Sighting]] = {}
    for root in visible:
        _scan_root(root, approved_paths, coverage, evidence, found)

    entries: list[InstalledSkill] = []
    claims: dict[str, Path] = {}
    ambiguous: set[str] = set()
    for canonical in sorted(found):
        sightings = found[canonical]
        read = _read_file(canonical, key, "skill", MAX_SKILL_BYTES)
        if read is None:
            evidence.append(f"file|{canonical}|unreadable")
            coverage["skill_file_unusable"] += 1
            continue
        evidence.append(f"file|{canonical}|{read.size}|{read.digest}")
        if read.data is None:
            coverage["skill_file_oversize"] += 1
            continue
        name, description, headings = _skill_fields(canonical, read.data, coverage)
        variants = _path_variants(canonical, sightings, ordered)
        for variant in sorted(variants):
            evidence.append(f"alias|{variant}|{canonical}")
            if claims.setdefault(variant, canonical) != canonical:
                ambiguous.add(variant)
        links = sum(sighting.link for sighting in sightings)
        if links:
            coverage["alias_entries"] += links
        if len({(sighting.root, sighting.name) for sighting in sightings}) > 1:
            coverage["duplicate_visibility"] += 1
        installed_at = _installed_at(read, canonical.parent)
        evidence.append(
            f"installation|{canonical}|"
            + (installed_at.isoformat() if installed_at is not None else "unavailable")
        )
        if installed_at is None:
            coverage["birthtime_unavailable"] += 1
        entries.append(
            InstalledSkill(
                name=name,
                description=description,
                path=canonical,
                aliases=tuple(
                    Path(item) for item in sorted(variants - {str(canonical)})
                ),
                ownership=_ownership(canonical, sightings, ordered),
                installed_at=installed_at,
                headings=headings,
            )
        )

    entries.sort(key=lambda item: (item.name, str(item.path)))
    name_counts = Counter(item.name for item in entries)
    duplicate_names = sum(1 for count in name_counts.values() if count > 1)
    if duplicate_names:
        coverage["duplicate_name"] += duplicate_names
    if entries:
        coverage["authored_creation_unknown"] += len(entries)
        coverage["name_resolution_unverified"] += len(entries)
    reference_names = _read_references(reference_paths, key, coverage, evidence)

    names_by_path = {item.path: item.name for item in entries}
    return Inventory(
        entries=entries,
        direct_paths={
            variant: names_by_path[canonical]
            for variant, canonical in sorted(claims.items())
            if variant not in ambiguous
        },
        ambiguous_paths=ambiguous,
        approved_roots=tuple(approved_paths),
        reference_names=reference_names,
        coverage=coverage,
        integrity=_digest_evidence(key, evidence),
    )
