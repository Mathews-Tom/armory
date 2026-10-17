"""Behavior tests for the installed-skill catalog on fictional synthetic roots.

Every skill name, path and reference below is invented. Assertions use entries,
ownership, resolution results and fixed coverage codes, never implementation wording.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import inventory_catalog
import pytest
from inventory_catalog import load_inventory
from inventory_types import Harness, InstalledSkill, Inventory, SchemaError

KEY = b"k" * 32
OTHER_KEY = b"q" * 32
HARNESSES: tuple[Harness, ...] = ("omp", "claude", "codex")


def write_skill(root: Path, directory: str, text: str) -> Path:
    folder = root / directory
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


def simple(
    root: Path,
    directory: str,
    *,
    name: str | None = None,
    description: str = "Fictional description.",
    body: str = "",
) -> Path:
    label = directory if name is None else name
    return write_skill(
        root,
        directory,
        f"---\nname: {label}\ndescription: {description}\n---\n\n{body}\n",
    )


def by_name(inventory: Inventory) -> dict[str, InstalledSkill]:
    skills = {entry.name: entry for entry in inventory.entries}
    assert len(skills) == len(inventory.entries)
    return skills


def by_directory(inventory: Inventory) -> dict[str, InstalledSkill]:
    return {entry.path.parent.name: entry for entry in inventory.entries}


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path.resolve()


@pytest.fixture
def home(base: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = base / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


# --------------------------------------------------------------------------- roots


def test_omp_defaults_classify_roots_and_reach_shared_skills_only_through_aliases(
    home: Path,
) -> None:
    managed = home / ".omp" / "agent" / "managed-skills"
    user = home / ".omp" / "agent" / "skills"
    shared = home / ".agents" / "skills"
    simple(managed, "alpha")
    simple(user, "beta")
    simple(shared, "gamma")
    simple(shared, "delta")
    (user / "gamma-link").symlink_to(shared / "gamma", target_is_directory=True)

    inventory = load_inventory("omp", key=KEY)

    skills = by_name(inventory)
    assert list(skills) == ["alpha", "beta", "gamma"]
    assert {name: skill.ownership for name, skill in skills.items()} == {
        "alpha": "managed",
        "beta": "user",
        "gamma": "protected",
    }
    link_path = user / "gamma-link" / "SKILL.md"
    assert skills["gamma"].path == shared / "gamma" / "SKILL.md"
    assert skills["gamma"].aliases == (link_path,)
    assert set(inventory.approved_roots) == {managed, user, shared}
    assert inventory.coverage["alias_entries"] == 1
    assert inventory.coverage["duplicate_visibility"] == 0
    assert inventory.resolve_direct(str(link_path)) == "gamma"
    assert inventory.resolve_direct(str(shared / "gamma" / "SKILL.md")) == "gamma"
    assert inventory.resolve_direct("~/.agents/skills/gamma/SKILL.md:1-20") == "gamma"
    assert inventory.resolve_direct(str(managed / "alpha" / "SKILL.md")) == "alpha"
    assert inventory.resolve_direct(str(shared / "delta" / "SKILL.md")) is None
    assert inventory.resolve_direct("skills/alpha/SKILL.md") is None
    assert re.fullmatch(r"[0-9a-f]{64}", inventory.integrity)


def test_missing_default_roots_are_explicit_coverage_not_silent_zeros(
    home: Path,
) -> None:
    first = load_inventory("omp", key=KEY)

    assert first.entries == []
    assert first.coverage == Counter(
        {
            "skill_root_missing": 2,
            "skill_roots_unavailable": 1,
            "references_not_provided": 1,
        }
    )
    assert load_inventory("omp", key=KEY).integrity == first.integrity
    assert load_inventory("omp", key=OTHER_KEY).integrity != first.integrity


def test_explicit_roots_replace_defaults_and_stay_unknown_ownership(
    home: Path, base: Path
) -> None:
    simple(home / ".omp" / "agent" / "managed-skills", "alpha")
    explicit = base / "archive"
    simple(explicit, "omega")

    for harness in HARNESSES:
        inventory = load_inventory(harness, key=KEY, skill_roots=[explicit])
        assert [(entry.name, entry.ownership) for entry in inventory.entries] == [
            ("omega", "unknown")
        ]
        assert inventory.approved_roots == (explicit,)

    empty = load_inventory("omp", key=KEY, skill_roots=[])
    assert empty.coverage["skill_roots_unavailable"] == 1


def test_short_keys_are_refused(base: Path) -> None:
    with pytest.raises(SchemaError) as error:
        load_inventory("omp", key=b"short", skill_roots=[base])
    assert error.value.code == "invalid_key"


def test_root_links_resolve_once_and_keep_every_lexical_path(base: Path) -> None:
    real = base / "real-root"
    simple(real, "skill-a")
    link = base / "link-root"
    link.symlink_to(real, target_is_directory=True)

    inventory = load_inventory("omp", key=KEY, skill_roots=[link, real])

    assert [entry.name for entry in inventory.entries] == ["skill-a"]
    assert inventory.approved_roots == (real,)
    assert inventory.coverage["duplicate_root"] == 1
    assert inventory.coverage["duplicate_visibility"] == 0
    assert inventory.entries[0].aliases == (link / "skill-a" / "SKILL.md",)
    assert inventory.resolve_direct(str(link / "skill-a" / "SKILL.md")) == "skill-a"
    assert inventory.resolve_direct(str(real / "skill-a" / "SKILL.md")) == "skill-a"


# --------------------------------------------------------------------------- aliases


def test_aliases_deduplicate_and_never_widen_roots(base: Path) -> None:
    root = base / "skills"
    outside = base / "outside"
    simple(root, "real")
    (root / "alias").symlink_to(root / "real", target_is_directory=True)
    simple(outside, "escape")
    (root / "escape-link").symlink_to(outside / "escape", target_is_directory=True)
    (root / "sneaky").mkdir()
    (root / "sneaky" / "SKILL.md").symlink_to(outside / "escape" / "SKILL.md")
    (root / ".hidden").mkdir()
    (root / "docs").mkdir()
    (root / "pipe").mkdir()
    os.mkfifo(root / "pipe" / "SKILL.md")

    inventory = load_inventory("omp", key=KEY, skill_roots=[root])

    skills = by_name(inventory)
    assert list(skills) == ["real"]
    assert skills["real"].ownership == "unknown"
    assert skills["real"].aliases == (root / "alias" / "SKILL.md",)
    assert inventory.approved_roots == (root,)
    for code, count in {
        "alias_entries": 1,
        "duplicate_visibility": 1,
        "alias_escape": 2,
        "hidden_entry_skipped": 1,
        "non_skill_entry": 1,
        "skill_file_unusable": 1,
    }.items():
        assert inventory.coverage[code] == count
    assert inventory.resolve_direct(str(root / "alias" / "SKILL.md")) == "real"
    for escaped in (
        root / "escape-link" / "SKILL.md",
        root / "sneaky" / "SKILL.md",
        outside / "escape" / "SKILL.md",
    ):
        assert inventory.resolve_direct(str(escaped)) is None


def test_approved_alias_targets_admit_escaping_links_as_protected_skills(
    home: Path, base: Path
) -> None:
    managed = home / ".omp" / "agent" / "managed-skills"
    shared = home / ".agents" / "skills"
    user = home / ".omp" / "agent" / "skills"
    shared.mkdir(parents=True)
    user.parent.mkdir(parents=True)
    user.symlink_to(shared, target_is_directory=True)
    checkout = base / "checkout" / "skills"
    simple(managed, "alpha")
    simple(checkout, "linked")
    simple(checkout, "unlinked")
    simple(base / "elsewhere", "stray")
    (shared / "linked").symlink_to(checkout / "linked", target_is_directory=True)
    (managed / "stray").symlink_to(base / "elsewhere" / "stray", True)

    before = load_inventory("omp", key=KEY)
    assert list(by_name(before)) == ["alpha"]
    assert before.coverage["alias_escape"] == 2

    inventory = load_inventory("omp", key=KEY, alias_targets=[checkout / "linked"])

    skills = by_name(inventory)
    assert list(skills) == ["alpha", "linked"]
    assert skills["linked"].ownership == "protected"
    assert skills["linked"].path == checkout / "linked" / "SKILL.md"
    assert inventory.coverage["alias_escape"] == 1
    linked_view = shared / "linked" / "SKILL.md"
    assert inventory.resolve_direct(str(linked_view)) == "linked"
    assert inventory.resolve_direct(str(checkout / "unlinked" / "SKILL.md")) is None
    assert inventory.integrity != before.integrity


def test_alias_targets_add_protected_containment_to_explicit_roots(
    base: Path,
) -> None:
    root = base / "skills"
    target = base / "checkout"
    simple(root, "plain")
    simple(target, "linked")
    (root / "linked").symlink_to(target / "linked", target_is_directory=True)

    inventory = load_inventory(
        "omp", key=KEY, skill_roots=[root], alias_targets=[target]
    )

    skills = by_name(inventory)
    assert list(skills) == ["linked", "plain"]
    assert skills["linked"].ownership == "protected"
    assert skills["plain"].ownership == "unknown"
    assert inventory.coverage["alias_escape"] == 0
    assert set(inventory.approved_roots) == {root, target}


def test_managed_skills_reached_through_links_are_protected(home: Path) -> None:
    managed = home / ".omp" / "agent" / "managed-skills"
    simple(managed, "alpha")
    simple(managed, "beta")
    (managed / "alpha-link").symlink_to(managed / "alpha", target_is_directory=True)

    inventory = load_inventory("omp", key=KEY)

    assert {entry.name: entry.ownership for entry in inventory.entries} == {
        "alpha": "protected",
        "beta": "managed",
    }


def test_duplicate_names_remain_visible_and_resolve_by_path(base: Path) -> None:
    root = base / "skills"
    simple(root, "one", name="shared-name")
    simple(root, "two", name="shared-name")

    inventory = load_inventory("omp", key=KEY, skill_roots=[root])

    assert [entry.name for entry in inventory.entries] == ["shared-name", "shared-name"]
    assert inventory.coverage["duplicate_name"] == 1
    assert inventory.resolve_direct(str(root / "one" / "SKILL.md")) == "shared-name"
    assert inventory.resolve_direct(str(root / "two" / "SKILL.md")) == "shared-name"


# --------------------------------------------------------------------------- YAML


FOLDED = """---
name: folded-skill
description: >-
  First line
  second line: with colon
metadata:
  tags: [a, b]
  anchor: &shared {k: v}
  copy: *shared
---

# Title

Some text

```python
# not a heading
```

## Section Two ##
#hashtag
~~~
## fenced tilde
~~~
### Third
"""


def test_actual_yaml_frontmatter_features(base: Path) -> None:
    root = base / "skills"
    write_skill(root, "folded", FOLDED)
    write_skill(
        root,
        "literal",
        "---\nname: literal-skill\ndescription: |\n  line one\n  line two\n---\n",
    )
    write_skill(
        root,
        "quoted",
        "---\nname: \"quoted: name\"\ndescription: 'it''s fine # not a comment'\n---\n",
    )
    write_skill(
        root,
        "comment",
        "---\n# leading comment\nname: comment-skill   # trailing\n"
        "description: Plain text # trailing comment\n---\n",
    )
    write_skill(
        root,
        "crlf",
        "\ufeff---\r\nname: crlf-skill\r\ndescription: café — ✓\r\n---\r\n\r\n# Heading\r\n",
    )
    write_skill(root, "listdoc", "---\n- a\n- b\n---\nbody\n")
    write_skill(root, "broken", "---\nname: [unclosed\n---\n")
    write_skill(root, "unterminated", "---\nname: x\ndescription: y\n")
    write_skill(root, "bare", "# Only Heading\n\nno frontmatter\n")
    write_skill(root, "typed", "---\nname: 123\ndescription:\n  - x\n---\n")
    write_skill(root, "nodesc", "---\nname: nodesc-skill\n---\n")

    inventory = load_inventory("omp", key=KEY, skill_roots=[root])

    skills = by_directory(inventory)
    folded = skills["folded"]
    assert folded.name == "folded-skill"
    assert folded.description == "First line second line: with colon"
    assert folded.headings == ("Title", "Section Two", "Third")
    assert skills["literal"].description == "line one\nline two\n"
    assert skills["quoted"].name == "quoted: name"
    assert skills["quoted"].description == "it's fine # not a comment"
    assert skills["comment"].name == "comment-skill"
    assert skills["comment"].description == "Plain text"
    assert skills["crlf"].name == "crlf-skill"
    assert skills["crlf"].description == "café — ✓"
    assert skills["crlf"].headings == ("Heading",)
    for directory in ("listdoc", "broken", "unterminated", "bare", "typed"):
        assert skills[directory].name == directory
        assert skills[directory].description == ""
    assert skills["bare"].headings == ("Only Heading",)
    assert skills["nodesc"].name == "nodesc-skill"
    for code, count in {
        "frontmatter_invalid": 3,
        "frontmatter_missing": 1,
        "name_from_directory": 1,
        "description_invalid": 1,
        "description_missing": 1,
    }.items():
        assert inventory.coverage[code] == count


# --------------------------------------------------------------------------- evidence


def test_installation_time_is_birth_evidence_only(base: Path) -> None:
    root = base / "skills"
    path = simple(root, "a")

    first = load_inventory("omp", key=KEY, skill_roots=[root])

    entry = first.entries[0]
    born = getattr(os.stat(path), "st_birthtime", None)
    if born is None:
        assert entry.installed_at is None
        assert first.coverage["birthtime_unavailable"] == 1
    else:
        directory_born = getattr(os.stat(path.parent), "st_birthtime", born)
        assert entry.installed_at == datetime.fromtimestamp(
            min(born, directory_born), UTC
        )
        assert entry.installed_at.utcoffset() == timedelta(0)
        assert first.coverage["birthtime_unavailable"] == 0
    assert first.coverage["authored_creation_unknown"] == 1
    assert first.coverage["name_resolution_unverified"] == 1

    future = time.time() + 365 * 86400
    os.utime(path, (future, future))
    second = load_inventory("omp", key=KEY, skill_roots=[root])
    assert second.entries[0].installed_at == entry.installed_at


def test_integrity_detects_content_listing_alias_and_reference_drift(
    base: Path,
) -> None:
    root = base / "skills"
    first = simple(root, "a")
    simple(root, "b")
    reference = base / "agent.md"
    reference.write_text("---\nautoloadSkills: [a]\n---\n")

    def digest(key: bytes = KEY, references: tuple[Path, ...] = (reference,)) -> str:
        return load_inventory(
            "omp", key=key, skill_roots=[root], reference_paths=references
        ).integrity

    baseline = digest()
    assert digest() == baseline
    assert digest(key=OTHER_KEY) != baseline
    assert digest(references=()) != baseline

    original = first.read_bytes()
    first.write_bytes(original.replace(b"Fictional", b"Fictiona1", 1))
    assert digest() != baseline
    first.write_bytes(original)
    assert digest() == baseline

    (root / "docs").mkdir()
    assert digest() != baseline
    (root / "docs").rmdir()
    assert digest() == baseline

    (root / "alias").symlink_to(root / "a", target_is_directory=True)
    assert digest() != baseline
    (root / "alias").unlink()
    assert digest() == baseline

    text = reference.read_text()
    reference.write_text(text.replace("[a]", "[b]"))
    assert digest() != baseline
    reference.write_text(text)
    assert digest() == baseline

    shutil.rmtree(root / "b")
    assert digest() != baseline


def test_oversize_skill_files_are_blocking_but_still_part_of_integrity(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = base / "skills"
    big = simple(root, "big", body="x" * 200)
    simple(root, "small")
    monkeypatch.setattr(inventory_catalog, "MAX_SKILL_BYTES", 150)

    before = load_inventory("omp", key=KEY, skill_roots=[root])
    big.write_bytes(big.read_bytes().replace(b"x", b"y", 1))
    after = load_inventory("omp", key=KEY, skill_roots=[root])

    assert [entry.name for entry in before.entries] == ["small"]
    assert before.coverage["skill_file_oversize"] == 1
    assert "skill_file_oversize" in inventory_catalog.BLOCKING_COVERAGE
    assert before.integrity != after.integrity


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_unreadable_skill_file_is_blocking_coverage(base: Path) -> None:
    root = base / "skills"
    locked = simple(root, "locked")
    locked.chmod(0)
    try:
        inventory = load_inventory("omp", key=KEY, skill_roots=[root])
    finally:
        locked.chmod(0o644)

    assert inventory.entries == []
    assert inventory.coverage["skill_file_unusable"] == 1


# --------------------------------------------------------------------------- references


AGENT = """---
name: fictional-agent
autoloadSkills:
  - alpha
  - skill://beta/references/x.md
notes: see skill://gamma?x=1#frag
---

# Instructions

Prefer /skill:delta for planning; also (/skill:epsilon).
A URL https://example.test/skill:zeta and a path ./a/skill:eta are not references.
Mentions skill://theta/SKILL.md in the body.
broken: [unclosed
- not: yaml
"""


def bomb() -> bytes:
    lines = ["a: &a [x, x, x, x, x, x, x, x, x]"]
    previous = "a"
    for name in "bcdef":
        lines.append(f"{name}: &{name} [{', '.join([f'*{previous}'] * 9)}]")
        previous = name
    return ("\n".join(lines) + "\n").encode()


def test_references_yield_dependency_names_from_frontmatter_structure_and_explicit_text(
    base: Path,
) -> None:
    root = base / "skills"
    simple(root, "alpha")
    (base / "agent.md").write_text(AGENT)
    (base / "agents.yaml").write_text(
        "---\nautoloadSkills:\n  - iota\n---\nitems:\n  - prompt: use skill://kappa now\n"
    )
    (base / "AGENTS.md").write_text(
        "Use /skill:lambda when planning.\n\nkey: [unclosed\n"
    )
    (base / "agent.json").write_text('{"autoloadSkills": ["mu"], "x": "skill://nu"}')
    references = [
        base / name for name in ("agent.md", "agents.yaml", "AGENTS.md", "agent.json")
    ]

    inventory = load_inventory(
        "omp", key=KEY, skill_roots=[root], reference_paths=references
    )

    assert inventory.reference_names == {
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "theta",
        "iota",
        "kappa",
        "lambda",
        "mu",
        "nu",
    }
    assert inventory.coverage["reference_files_read"] == 4
    assert inventory.coverage["references_not_provided"] == 0
    assert [entry.name for entry in inventory.entries] == ["alpha"]


def test_absent_references_are_explicit_coverage(base: Path) -> None:
    root = base / "skills"
    simple(root, "alpha")

    inventory = load_inventory("omp", key=KEY, skill_roots=[root])

    assert inventory.reference_names == set()
    assert inventory.coverage["references_not_provided"] == 1
    assert inventory.coverage.keys() & inventory_catalog.BLOCKING_COVERAGE == set()


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("bad-shape.yaml", b"autoloadSkills: alpha\n"),
        ("bad-item.yaml", b"autoloadSkills: [1]\n"),
        ("syntax.yaml", b"key: [unclosed\n"),
        ("binary.yaml", b"\xff\xfe\x00"),
        ("notes.txt", b"/skill:alpha\n"),
        ("unterminated.md", b"---\nname: x\n"),
        ("list-frontmatter.md", b"---\n- a\n---\nbody /skill:alpha\n"),
        ("bomb.yaml", bomb()),
    ],
)
def test_invalid_references_are_blocking_coverage_and_yield_no_names(
    base: Path, name: str, content: bytes
) -> None:
    root = base / "skills"
    simple(root, "alpha")
    path = base / name
    path.write_bytes(content)

    inventory = load_inventory(
        "omp", key=KEY, skill_roots=[root], reference_paths=[path]
    )

    assert inventory.reference_names == set()
    assert inventory.coverage["reference_invalid"] == 1
    assert inventory.coverage["reference_files_read"] == 0


def test_unreadable_references_are_blocking_coverage(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = base / "skills"
    simple(root, "alpha")
    present = base / "agent.md"
    present.write_text("/skill:alpha\n")
    directory = base / "dir.md"
    directory.mkdir()
    monkeypatch.setattr(inventory_catalog, "MAX_REFERENCE_BYTES", 8)

    inventory = load_inventory(
        "omp",
        key=KEY,
        skill_roots=[root],
        reference_paths=[base / "missing.md", directory, present],
    )

    assert inventory.reference_names == set()
    assert inventory.coverage["reference_unreadable"] == 3
