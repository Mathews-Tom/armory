"""Behavior tests for recommendation policy, tree states and the proposal contract.

Every skill, path and description below is invented. Assertions check classification,
fixed reason/diagnostic codes, digests, tree states and refusal behavior, never the
wording of the implementation. Skills are created on a temporary fictional OMP home.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import stat
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import inventory_policy
import pytest
from inventory_io import (
    BINDING_VERSION,
    SNAPSHOT_POLICY,
    canonical_json,
    keyed_digest,
    write_private_json,
)
from inventory_policy import (
    APPROVAL_POLICY,
    canonical_digest,
    normalize_evidence,
    policy_digest,
    scan_tree,
    scan_tree_fd,
    seal_proposal,
    subtree_state,
    tree_document,
    tree_from_document,
    validate_proposal,
    without_children,
)
from inventory_types import Harness, InstalledSkill, Inventory, SchemaError

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)
WINDOW = 90
KEY_HEX = "ab" * 32
OTHER_KEY_HEX = "cd" * 32
INTEGRITY = "c" * 64


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def ago(days: float) -> datetime:
    return AS_OF - timedelta(days=days)


def iso_day(moment: datetime) -> str:
    return moment.date().isoformat()


# --------------------------------------------------------------------------- tree fixtures


def build_tree(root: Path) -> Path:
    root.mkdir()
    os.chmod(root, 0o700)
    for directory, mode in (
        ("one", 0o700),
        ("one/refs", 0o750),
        ("two", 0o700),
        ("empty", 0o700),
    ):
        (root / directory).mkdir()
        os.chmod(root / directory, mode)
    for relative, data, mode in (
        ("one/SKILL.md", b"alpha", 0o600),
        ("one/refs/notes.txt", b"beta notes", 0o640),
        ("two/SKILL.md", b"gamma", 0o600),
        ("loose.txt", b"loose", 0o644),
    ):
        path = root / relative
        path.write_bytes(data)
        os.chmod(path, mode)
    return root


def test_canonical_digest_is_key_order_independent_ascii_json() -> None:
    expected = hashlib.sha256(b'{"a":[1,2],"b":1,"k":"\\u00e9"}').hexdigest()
    assert canonical_digest({"k": "é", "b": 1, "a": [1, 2]}) == expected
    assert canonical_digest({"a": [1, 2], "b": 1, "k": "é"}) == expected
    assert canonical_digest({"a": [2, 1], "b": 1, "k": "é"}) != expected


@pytest.mark.parametrize(
    "value", [math.nan, math.inf, {"x": -math.inf}, {1, 2}, object()]
)
def test_canonical_digest_refuses_nonfinite_and_unserializable_values(
    value: object,
) -> None:
    with pytest.raises(SchemaError) as error:
        canonical_digest(value)
    assert error.value.code == "digest_input_invalid"


def test_scan_tree_records_exact_content_modes_and_round_trips(tmp_path: Path) -> None:
    state = scan_tree(build_tree(tmp_path / "tree"))
    assert state.root_mode == 0o700
    assert dict(state.directories) == {
        "empty": 0o700,
        "one": 0o700,
        "one/refs": 0o750,
        "two": 0o700,
    }
    files = {path: (sha, mode, size) for path, sha, mode, size in state.files}
    assert files["one/SKILL.md"] == (hashlib.sha256(b"alpha").hexdigest(), 0o600, 5)
    assert files["one/refs/notes.txt"] == (
        hashlib.sha256(b"beta notes").hexdigest(),
        0o640,
        10,
    )
    assert files["loose.txt"][1] == 0o644
    assert list(state.files) == sorted(state.files)
    document = tree_document(state)
    assert tree_from_document(document) == state
    assert tree_from_document(json.loads(json.dumps(document))) == state


def test_scan_tree_digest_ignores_creation_order_and_reads(tmp_path: Path) -> None:
    first = build_tree(tmp_path / "first")
    before = scan_tree(first).digest
    (first / "loose.txt").read_bytes()
    assert scan_tree(first).digest == before
    second = tmp_path / "second"
    second.mkdir()
    os.chmod(second, 0o700)
    for name in ("loose.txt", "two", "one", "empty"):
        source = first / name
        if source.is_dir():
            shutil.copytree(source, second / name)
        else:
            shutil.copy2(source, second / name)
    for path in (second / "one" / "refs",):
        os.chmod(path, 0o750)
    assert scan_tree(second).digest == before


def _edit_byte(root: Path) -> None:
    (root / "one" / "SKILL.md").write_bytes(b"alphb")


def _chmod_file(root: Path) -> None:
    os.chmod(root / "one" / "SKILL.md", 0o640)


def _chmod_directory(root: Path) -> None:
    os.chmod(root / "two", 0o750)


def _chmod_root(root: Path) -> None:
    os.chmod(root, 0o750)


def _new_empty_directory(root: Path) -> None:
    (root / "more").mkdir(mode=0o700)
    os.chmod(root / "more", 0o700)


def _new_file(root: Path) -> None:
    (root / "new.txt").write_bytes(b"")
    os.chmod(root / "new.txt", 0o600)


def _rename_file(root: Path) -> None:
    (root / "loose.txt").rename(root / "tight.txt")


def _remove_file(root: Path) -> None:
    (root / "loose.txt").unlink()


@pytest.mark.parametrize(
    "mutation",
    [
        _edit_byte,
        _chmod_file,
        _chmod_directory,
        _chmod_root,
        _new_empty_directory,
        _new_file,
        _rename_file,
        _remove_file,
    ],
)
def test_every_content_mode_or_layout_change_changes_the_tree_digest(
    tmp_path: Path, mutation: Callable[[Path], None]
) -> None:
    root = build_tree(tmp_path / "tree")
    before = scan_tree(root).digest
    mutation(root)
    assert scan_tree(root).digest != before


def _symlink_file(root: Path) -> None:
    (root / "one" / "link").symlink_to(root / "loose.txt")


def _symlink_directory(root: Path) -> None:
    (root / "link").symlink_to(root / "one")


def _hardlink(root: Path) -> None:
    os.link(root / "loose.txt", root / "one" / "hard.txt")


def _fifo(root: Path) -> None:
    os.mkfifo(root / "pipe", 0o600)


def _group_writable_file(root: Path) -> None:
    os.chmod(root / "loose.txt", 0o664)


def _world_writable_directory(root: Path) -> None:
    os.chmod(root / "two", 0o707)


def _setgid_directory(root: Path) -> None:
    os.chmod(root / "two", 0o2700)


@pytest.mark.parametrize(
    "unsafe",
    [
        _symlink_file,
        _symlink_directory,
        _hardlink,
        _fifo,
        _group_writable_file,
        _world_writable_directory,
        _setgid_directory,
    ],
)
def test_scan_refuses_links_special_files_and_unsafe_modes_anonymously(
    tmp_path: Path, unsafe: Callable[[Path], None]
) -> None:
    root = build_tree(tmp_path / "tree")
    unsafe(root)
    with pytest.raises(SchemaError) as error:
        scan_tree(root)
    assert error.value.code == "tree_entry_unsafe"
    assert "loose" not in str(error.value)


def test_scan_refuses_missing_relative_and_symlinked_roots(tmp_path: Path) -> None:
    root = build_tree(tmp_path / "tree")
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    for bad in (tmp_path / "missing", Path("relative/tree"), alias):
        with pytest.raises(SchemaError) as error:
            scan_tree(bad)
        assert error.value.code == "tree_unreadable"


def test_scan_tree_fd_leaves_the_callers_descriptor_open(tmp_path: Path) -> None:
    root = build_tree(tmp_path / "tree")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        state = scan_tree_fd(fd)
        assert stat.S_ISDIR(os.fstat(fd).st_mode)
        assert scan_tree_fd(fd) == state
    finally:
        os.close(fd)
    assert state == scan_tree(root)


def test_scan_enforces_node_depth_and_file_size_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = build_tree(tmp_path / "tree")
    with monkeypatch.context() as limits:
        limits.setattr(inventory_policy, "MAX_TREE_NODES", 3)
        with pytest.raises(SchemaError) as nodes:
            scan_tree(root)
    with monkeypatch.context() as limits:
        limits.setattr(inventory_policy, "MAX_TREE_DEPTH", 1)
        with pytest.raises(SchemaError) as depth:
            scan_tree(root)
    with monkeypatch.context() as limits:
        limits.setattr(inventory_policy, "MAX_FILE_BYTES", 3)
        with pytest.raises(SchemaError) as size:
            scan_tree(root)
    assert {nodes.value.code, depth.value.code, size.value.code} == {"tree_limit"}


def test_scan_fails_when_a_file_changes_while_it_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = build_tree(tmp_path / "tree")
    target = root / "loose.txt"
    real_read = os.read
    fired: list[bool] = []

    def racing_read(fd: int, length: int) -> bytes:
        chunk = real_read(fd, length)
        if chunk and not fired:
            fired.append(True)
            with target.open("ab") as handle:
                handle.write(b"x")
        return chunk

    monkeypatch.setattr(inventory_policy.os, "read", racing_read)
    with pytest.raises(SchemaError) as error:
        scan_tree(root)
    assert error.value.code in {"tree_unstable", "tree_unreadable"}


def test_scan_fails_when_a_directory_listing_changes_during_the_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = build_tree(tmp_path / "tree")
    real_listdir = os.listdir
    fired: list[bool] = []

    def racing_listdir(fd: int) -> list[str]:
        names = real_listdir(fd)
        if not fired:
            fired.append(True)
            late = root / "late.txt"
            late.write_bytes(b"late")
            os.chmod(late, 0o600)
        return names

    monkeypatch.setattr(inventory_policy.os, "listdir", racing_listdir)
    with pytest.raises(SchemaError) as error:
        scan_tree(root)
    assert error.value.code == "tree_unstable"


def test_subtree_state_equals_scanning_that_directory(tmp_path: Path) -> None:
    root = build_tree(tmp_path / "tree")
    state = scan_tree(root)
    for name in ("one", "two", "empty"):
        derived = subtree_state(state, name)
        assert derived == scan_tree(root / name)
    assert {path for path, *_ in subtree_state(state, "one").files} == {
        "SKILL.md",
        "refs/notes.txt",
    }


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("one/refs", "tree_name_invalid"),
        ("", "tree_name_invalid"),
        (".", "tree_name_invalid"),
        ("..", "tree_name_invalid"),
        ("../tree", "tree_name_invalid"),
        ("/one", "tree_name_invalid"),
        ("one/", "tree_name_invalid"),
        ("missing", "tree_entry_missing"),
        ("loose.txt", "tree_entry_missing"),
        ("refs", "tree_entry_missing"),
    ],
)
def test_subtree_state_refuses_unsafe_or_absent_children(
    tmp_path: Path, name: str, code: str
) -> None:
    state = scan_tree(build_tree(tmp_path / "tree"))
    with pytest.raises(SchemaError) as error:
        subtree_state(state, name)
    assert error.value.code == code


def test_without_children_predicts_the_tree_after_a_real_move(tmp_path: Path) -> None:
    root = build_tree(tmp_path / "tree")
    before = scan_tree(root)
    derived = without_children(before, {"one", "loose.txt"})
    shutil.move(str(root / "one"), str(tmp_path / "moved"))
    (root / "loose.txt").unlink()
    assert scan_tree(root) == derived
    assert without_children(before, set()) == before


@pytest.mark.parametrize(
    ("names", "code"),
    [
        ({"missing"}, "tree_entry_missing"),
        ({"one/refs"}, "tree_name_invalid"),
        ({".."}, "tree_name_invalid"),
        ({""}, "tree_name_invalid"),
    ],
)
def test_without_children_refuses_unknown_or_nested_names(
    tmp_path: Path, names: set[str], code: str
) -> None:
    state = scan_tree(build_tree(tmp_path / "tree"))
    with pytest.raises(SchemaError) as error:
        without_children(state, names)
    assert error.value.code == code


def _document(tmp_path: Path) -> dict[str, Any]:
    return tree_document(scan_tree(build_tree(tmp_path / "tree")))


def _bad_digest(document: dict[str, Any]) -> None:
    document["digest"] = "0" * 64


def _bad_file_hash(document: dict[str, Any]) -> None:
    document["files"][0][1] = "0" * 64


def _extra_key(document: dict[str, Any]) -> None:
    document["note"] = 1


def _unsorted_directories(document: dict[str, Any]) -> None:
    document["directories"].reverse()


def _duplicate_directory(document: dict[str, Any]) -> None:
    document["directories"].append(document["directories"][0])


def _traversal(document: dict[str, Any]) -> None:
    document["files"][0][0] = "../escape"


def _absolute(document: dict[str, Any]) -> None:
    document["files"][0][0] = "/etc/passwd"


def _empty_segment(document: dict[str, Any]) -> None:
    document["files"][0][0] = "one//SKILL.md"


def _orphan(document: dict[str, Any]) -> None:
    document["files"].append(["ghost/x", "0" * 64, 0o600, 1])
    document["files"].sort()


def _file_on_directory(document: dict[str, Any]) -> None:
    document["files"].append(["one", "0" * 64, 0o600, 1])
    document["files"].sort()


def _boolean_mode(document: dict[str, Any]) -> None:
    document["directories"][0][1] = True


def _oversized_mode(document: dict[str, Any]) -> None:
    document["root_mode"] = 0o10000


def _short_hash(document: dict[str, Any]) -> None:
    document["files"][0][1] = "abc"


def _not_a_list(document: dict[str, Any]) -> None:
    document["directories"] = "one"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (_bad_digest, "tree_digest_mismatch"),
        (_bad_file_hash, "tree_digest_mismatch"),
        (_extra_key, "tree_invalid"),
        (_unsorted_directories, "tree_invalid"),
        (_duplicate_directory, "tree_invalid"),
        (_traversal, "tree_path_invalid"),
        (_absolute, "tree_path_invalid"),
        (_empty_segment, "tree_path_invalid"),
        (_orphan, "tree_invalid"),
        (_file_on_directory, "tree_invalid"),
        (_boolean_mode, "tree_invalid"),
        (_oversized_mode, "tree_invalid"),
        (_short_hash, "tree_invalid"),
        (_not_a_list, "tree_invalid"),
    ],
)
def test_tree_from_document_rejects_tampered_or_unsafe_documents(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None], code: str
) -> None:
    document = _document(tmp_path)
    mutation(document)
    with pytest.raises(SchemaError) as error:
        tree_from_document(document)
    assert error.value.code == code


# --------------------------------------------------------------------------- evidence


def test_normalize_evidence_fills_unknowns_with_none_not_zero() -> None:
    row = normalize_evidence({"name": "alpha-tool", "ownership": "managed"})
    assert row["window_read_attempts"] is None
    assert row["inventory_presence_grouping_complete"] is None
    assert row["largest_observed_inter_use_gap_days"] is None
    assert row["log_observed_dependency"] is None


@pytest.mark.parametrize(
    "row",
    [
        {"ownership": "managed"},
        {"name": "", "ownership": "managed"},
        {"name": "alpha-tool", "ownership": "owner"},
        {"name": "alpha-tool", "ownership": "managed", "window_read_attempts": True},
        {"name": "alpha-tool", "ownership": "managed", "window_read_attempts": -1},
        {"name": "alpha-tool", "ownership": "managed", "window_read_attempts": "3"},
        {
            "name": "alpha-tool",
            "ownership": "managed",
            "installation_date": "yesterday",
        },
        {
            "name": "alpha-tool",
            "ownership": "managed",
            "last_read_date": "2026-01-01T00:00:00",
        },
        {
            "name": "alpha-tool",
            "ownership": "managed",
            "largest_observed_inter_use_gap_days": math.inf,
        },
        {
            "name": "alpha-tool",
            "ownership": "managed",
            "largest_observed_inter_use_gap_days": -1.0,
        },
        {
            "name": "alpha-tool",
            "ownership": "managed",
            "inventory_presence_grouping_complete": 1,
        },
    ],
)
def test_normalize_evidence_rejects_wrong_types(row: dict[str, object]) -> None:
    with pytest.raises(SchemaError) as error:
        normalize_evidence(row)
    assert error.value.code == "evidence_invalid"


# --------------------------------------------------------------------------- fictional world


def default_row(entry: InstalledSkill) -> dict[str, object]:
    installed = entry.installed_at
    return {
        "name": entry.name,
        "ownership": entry.ownership,
        "historical_provenance": "current_name_match_unverified",
        "installation_date": None if installed is None else iso(installed),
        "installation_date_source": (
            "unavailable" if installed is None else "filesystem_birthtime"
        ),
        "authored_creation_date": None,
        "first_observed_inventory_date": iso(ago(150)),
        "window_read_attempts": 0,
        "window_invocation_attempts": 0,
        "window_first_use_date": None,
        "window_last_use_date": None,
        "largest_observed_inter_use_gap_days": None,
        "inventory_present_subagent_snapshots": 25,
        "inventory_present_main_task_groups": 6,
        "inventory_presence_grouping_complete": True,
        "log_observed_dependency": False,
    }


@dataclass
class Result:
    public: dict[str, Any]
    proposal: dict[str, Any]

    def skills(self, name: str) -> list[dict[str, Any]]:
        return [skill for skill in self.proposal["skills"] if skill["name"] == name]

    def skill(self, name: str) -> dict[str, Any]:
        found = self.skills(name)
        assert len(found) == 1
        return found[0]


class World:
    """A fictional OMP home: managed skills on disk plus the measurement documents."""

    def __init__(self, root: Path, *, harness: Harness = "omp") -> None:
        self.root = Path(os.path.realpath(root))
        self.managed = self.root / "home" / ".omp" / "agent" / "managed-skills"
        self.user_root = self.root / "home" / ".omp" / "agent" / "skills"
        self.private = self.root / "private"
        for folder in (self.managed, self.user_root, self.private):
            folder.mkdir(parents=True)
            os.chmod(folder, 0o700)
        self.harness = harness
        self.window_days = WINDOW
        self.items: list[tuple[InstalledSkill, dict[str, object]]] = []
        self.directories: dict[str, str] = {}
        self.reference_names: set[str] = set()
        self.coverage: Counter[str] = Counter()
        self.integrity = INTEGRITY
        self.binding_integrity = INTEGRITY
        self.approved: tuple[Path, ...] | None = None
        self.days: dict[str, int] | None = {
            iso_day(ago(1)): 4,
            iso_day(ago(5)): 6,
            iso_day(ago(20)): 12,
        }
        self.files = 0

    # ----- skills

    def add(
        self,
        name: str,
        *,
        description: str = "Reformat fictional invoices.",
        headings: tuple[str, ...] = ("Steps",),
        body: str = "",
        extra_frontmatter: str = "",
        directory: str | None = None,
        ownership: str = "managed",
        root: Path | None = None,
        aliases: tuple[Path, ...] = (),
        installed_days: float | None = 200,
        **row: object,
    ) -> InstalledSkill:
        base = self.managed if root is None else root
        folder = base / (directory or name)
        folder.mkdir()
        os.chmod(folder, 0o700)
        lines = ["---", f"name: {name}", f"description: {description}"]
        if extra_frontmatter:
            lines.append(extra_frontmatter)
        lines.append("---")
        text = "\n".join(lines) + "\n\n"
        text += "".join(f"# {heading}\n\n" for heading in headings) + body + "\n"
        skill = folder / "SKILL.md"
        skill.write_text(text, encoding="utf-8")
        os.chmod(skill, 0o600)
        entry = InstalledSkill(
            name=name,
            description=description,
            path=skill,
            aliases=aliases,
            ownership=ownership,
            installed_at=None if installed_days is None else ago(installed_days),
            headings=headings,
        )
        evidence = default_row(entry)
        evidence.update(row)
        self.items.append((entry, evidence))
        if ownership == "managed" and root is None:
            self.directories[name] = folder.name
        return entry

    def tree_digest(self, name: str) -> str:
        return subtree_state(scan_tree(self.managed), self.directories[name]).digest

    def attestation(self, name: str, **overrides: object) -> dict[str, object]:
        item: dict[str, object] = {
            "name": name,
            "tree_digest": self.tree_digest(name),
            "harness_generated": True,
            "never_user_authored": True,
            "historical_identity_attested_since": iso(ago(150)),
            "description_only_reviewed": True,
            "coverage_still_needed": False,
            "periodic_or_incident_workflow": False,
        }
        item.update(overrides)
        return item

    # ----- measurement documents

    def scope(self) -> dict[str, object]:
        return {
            "harness": self.harness,
            "as_of_utc": iso(AS_OF),
            "window_days": self.window_days,
            "files_by_cohort": {"main": 3, "sub": 25, "nested": 0, "unknown": 0},
        }

    def reports(
        self,
        *,
        status: str = "complete",
        valid: bool = True,
        closed: bool = True,
        activity: bool | None = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        scope = self.scope()
        rows = [
            row
            for _, row in sorted(
                self.items, key=lambda item: (item[0].name, str(item[0].path))
            )
        ]
        report: dict[str, Any] = {
            "schema_version": 1,
            "status": status,
            "scope": scope,
            "snapshot": {"valid": valid, "closed": closed},
        }
        private: dict[str, Any] = {
            "schema_version": 1,
            "status": status,
            "scope": scope,
            "skills": copy.deepcopy(rows),
            "diagnostics": {},
        }
        if activity is not None:
            private["observed_activity_after_as_of"] = activity
        if self.days is not None:
            private["inventory_observations_by_utc_day"] = dict(self.days)
        return report, private

    def write_binding(
        self,
        name: str = "binding.json",
        *,
        key_hex: str = KEY_HEX,
        harness: str | None = None,
        as_of: datetime = AS_OF,
        window_days: int | None = None,
        tamper: bool = False,
    ) -> Path:
        body: dict[str, object] = {
            "version": BINDING_VERSION,
            "policy": SNAPSHOT_POLICY,
            "harness": harness or self.harness,
            "as_of": iso(as_of),
            "window_days": window_days or self.window_days,
            "key": key_hex,
            "roots": [],
            "files": [],
            "inventory": self.binding_integrity,
        }
        seal = keyed_digest(bytes.fromhex(key_hex), "seal", canonical_json(body))
        if tamper:
            body["window_days"] = int(str(body["window_days"])) + 1
        path = self.private / name
        write_private_json(path, {**body, "seal": seal})
        return path

    def binding_path(self) -> Path:
        path = self.private / "binding.json"
        return path if path.exists() else self.write_binding()

    def _write(self, kind: str, document: object) -> Path:
        self.files += 1
        path = self.private / f"{kind}-{self.files}.json"
        write_private_json(path, document)
        return path

    # ----- the call under test

    def recommend(
        self,
        *,
        pins: list[str] | Literal["auto"] | None = "auto",
        pins_document: object = None,
        attestations: list[dict[str, object]] | Literal["auto"] | None = "auto",
        attestations_document: object = None,
        attestation_overrides: dict[str, dict[str, object]] | None = None,
        binding: Path | None = None,
        reports: tuple[dict[str, Any], dict[str, Any]] | None = None,
        reverse: bool = False,
        as_of: datetime = AS_OF,
        window_days: int | None = None,
    ) -> Result:
        report, private = self.reports() if reports is None else reports
        if pins_document is not None:
            pins_path: Path | None = self._write("pins", pins_document)
        elif pins is None:
            pins_path = None
        else:
            pins_path = self._write(
                "pins",
                {"schema_version": 1, "pins": [] if pins == "auto" else pins},
            )
        if attestations_document is not None:
            attestation_path: Path | None = self._write(
                "attestations", attestations_document
            )
        elif attestations is None:
            attestation_path = None
        else:
            overrides = attestation_overrides or {}
            if attestations == "auto":
                names = (
                    sorted(
                        {
                            entry.name
                            for entry, _ in self.items
                            if entry.ownership == "managed"
                            and entry.name in self.directories
                        }
                    )
                    if self.harness == "omp"
                    else []
                )
                items = [
                    self.attestation(name, **overrides.get(name, {})) for name in names
                ]
            else:
                items = attestations
            attestation_path = self._write(
                "attestations", {"schema_version": 1, "items": items}
            )
        entries = [entry for entry, _ in self.items]
        if reverse:
            entries.reverse()
        inventory = Inventory(
            entries=entries,
            approved_roots=(self.managed,) if self.approved is None else self.approved,
            reference_names=set(self.reference_names),
            coverage=Counter(self.coverage),
            integrity=self.integrity,
        )
        public, proposal = inventory_policy.recommend(
            report,
            private,
            inventory,
            as_of=as_of,
            window_days=self.window_days if window_days is None else window_days,
            binding_path=binding or self.binding_path(),
            pins_path=pins_path,
            attestations_path=attestation_path,
        )
        return Result(public, proposal)


def two_skill_world(tmp_path: Path) -> World:
    """One eligible never-read skill and one skill kept for a high-risk token."""
    world = World(tmp_path)
    world.add("alpha-tool", description="Reformat fictional invoices.")
    world.add("beta-auth", description="Fictional auth helper for invoices.")
    return world


# --------------------------------------------------------------------------- happy path and privacy


def test_attested_never_read_managed_skill_is_the_only_archive_candidate(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("invoice-tidy")
    world.add(
        "ledger-sync",
        description="Synchronize fictional ledgers weekly.",
        window_read_attempts=5,
        window_first_use_date=iso(ago(3)),
        window_last_use_date=iso(ago(3)),
        largest_observed_inter_use_gap_days=2.0,
    )
    result = world.recommend()
    tidy = result.skill("invoice-tidy")
    assert tidy["classification"] == "archive_candidate"
    assert tidy["reasons"] == ["never_read_in_window"]
    assert tidy["eligible"] is True
    assert tidy["tree_digest"] == world.tree_digest("invoice-tidy")
    assert "description_only_influence_unmeasured" in tidy["counter_evidence"]
    ledger = result.skill("ledger-sync")
    assert ledger["classification"] == "keep"
    assert ledger["reasons"] == ["use_above_rare_threshold"]
    assert ledger["eligible"] is False
    assert result.public["status"] == result.proposal["status"] == "complete"
    assert result.public["counts"]["archive_candidates"] == 1
    assert result.public["counts"]["keep"] == 1
    assert result.public["proposal_digest"] == result.proposal["proposal_digest"]
    assert validate_proposal(result.proposal) is result.proposal


def test_public_report_is_aggregate_only(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("invoice-tidy")
    result = world.recommend()
    public_text = json.dumps(result.public)
    private_values = [
        "invoice-tidy",
        "Reformat fictional invoices",
        world.tree_digest("invoice-tidy"),
        str(world.root),
        KEY_HEX,
        result.proposal["snapshot_digest"],
        result.proposal["source_root_digest"],
        result.proposal["policy_inputs"]["attestations_digest"],
    ]
    for value in private_values:
        assert value not in public_text
    assert result.public["inputs"] == {
        "attestations": "provided",
        "managed_tree": "scanned",
        "activity_after_cutoff": "none_observed",
        "observation_calendar": "provided",
        "pins": "provided",
        "references": "provided",
        "snapshot_binding": "provided",
    }
    assert result.public["counts"]["pins_provided"] == 0
    assert result.public["counts"]["attestations_matching_current_tree"] == 1


def test_recommend_is_deterministic_and_input_order_independent(
    tmp_path: Path,
) -> None:
    world = two_skill_world(tmp_path)
    first = world.recommend()
    second = world.recommend(reverse=True)
    assert first.proposal == second.proposal
    assert first.public == second.public


def test_recommend_never_mutates_sources_or_private_inputs(tmp_path: Path) -> None:
    world = two_skill_world(tmp_path)
    before = scan_tree(world.managed)
    binding = world.binding_path()
    binding_bytes = binding.read_bytes()
    world.recommend()
    assert scan_tree(world.managed) == before
    assert binding.read_bytes() == binding_bytes


def test_binding_entropy_changes_the_public_proposal_digest(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("invoice-tidy")
    first = world.recommend()
    other = world.write_binding("other.json", key_hex=OTHER_KEY_HEX)
    second = world.recommend(binding=other)
    assert first.skill("invoice-tidy") == second.skill("invoice-tidy")
    assert first.proposal["snapshot_digest"] != second.proposal["snapshot_digest"]
    assert first.public["proposal_digest"] != second.public["proposal_digest"]
    assert first.proposal["policy_digest"] == second.proposal["policy_digest"]


def test_calendar_aggregates_days_and_gaps_without_dates_of_use(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("invoice-tidy")
    world.days = {iso_day(ago(1)): 3, iso_day(ago(30)): 2, iso_day(ago(10)): 0}
    calendar = world.recommend().public["calendar"]
    assert calendar["days_with_inventory_observations"] == 2
    assert calendar["inventory_observations"] == 5
    assert calendar["calendar_days_in_window"] == 91
    assert calendar["coverage_fraction"] == round(2 / 91, 6)
    assert calendar["largest_gap_days_including_window_edges"] == 60
    assert calendar["main_session_presence"] == "unmeasured"
    assert world.recommend().public["cohorts"]["files_by_cohort"]["sub"] == 25


# --------------------------------------------------------------------------- incomplete inputs


def _case_pins(world: World) -> dict[str, Any]:
    return {"pins": None}


def _case_attestations(world: World) -> dict[str, Any]:
    return {"attestations": None}


def _case_binding(world: World) -> dict[str, Any]:
    return {"binding": world.private / "absent.json"}


def _case_references(world: World) -> dict[str, Any]:
    world.coverage["references_not_provided"] = 1
    return {}


def _case_catalog(world: World) -> dict[str, Any]:
    world.coverage["reference_unreadable"] = 2
    return {}


def _case_report(world: World) -> dict[str, Any]:
    return {"reports": world.reports(status="incomplete")}


def _case_open_snapshot(world: World) -> dict[str, Any]:
    return {"reports": world.reports(closed=False)}


def _case_invalid_snapshot(world: World) -> dict[str, Any]:
    return {"reports": world.reports(valid=False)}


def _case_calendar(world: World) -> dict[str, Any]:
    world.days = None
    return {}


def _case_drift(world: World) -> dict[str, Any]:
    world.integrity = "d" * 64
    return {}


def _case_root(world: World) -> dict[str, Any]:
    world.approved = ()
    return {}


def _case_later_activity(world: World) -> dict[str, Any]:
    return {"reports": world.reports(activity=True)}


def _case_unknown_activity(world: World) -> dict[str, Any]:
    return {"reports": world.reports(activity=None)}


@pytest.mark.parametrize(
    ("case", "code"),
    [
        (_case_pins, "pins_missing"),
        (_case_attestations, "attestations_missing"),
        (_case_binding, "snapshot_binding_missing"),
        (_case_references, "references_not_provided"),
        (_case_catalog, "catalog_reference_unreadable"),
        (_case_report, "measurement_incomplete"),
        (_case_open_snapshot, "snapshot_not_closed"),
        (_case_invalid_snapshot, "snapshot_invalid"),
        (_case_calendar, "observation_calendar_missing"),
        (_case_drift, "inventory_drift"),
        (_case_root, "managed_root_unresolved"),
        (_case_later_activity, "observed_activity_after_as_of"),
        (_case_unknown_activity, "observed_activity_after_as_of_unknown"),
    ],
)
def test_missing_or_incomplete_input_keeps_every_skill(
    tmp_path: Path, case: Callable[[World], dict[str, Any]], code: str
) -> None:
    world = World(tmp_path)
    world.add("invoice-tidy")
    world.add("ledger-sync", description="Synchronize fictional ledgers weekly.")
    result = world.recommend(**case(world))
    assert result.public["status"] == result.proposal["status"] == "incomplete"
    assert result.public["diagnostics"][code] >= 1
    for skill in result.proposal["skills"]:
        assert skill["classification"] == "keep"
        assert skill["eligible"] is False
        assert "proposal_incomplete" in skill["reasons"]
    assert result.public["counts"]["eligible_for_archive_approval"] == 0
    assert validate_proposal(result.proposal) is result.proposal


def test_incomplete_proposal_shows_similar_pairs_but_never_actionable(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    for name in ("relay-node", "node-relay"):
        world.add(name, description="Route fictional parcels between depots.")
    result = world.recommend(pins=None)
    assert len(result.proposal["merge_pairs"]) == 1
    assert result.proposal["merge_pairs"][0]["actionable"] is False
    assert result.public["counts"]["similar_pairs"] == 1
    assert result.public["counts"]["actionable_similar_pairs"] == 0
    assert {s["classification"] for s in result.proposal["skills"]} == {"keep"}


# --------------------------------------------------------------------------- invalid inputs


def test_later_skill_activity_in_the_captured_prefix_blocks_a_historical_cutoff(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    clean = world.recommend()
    later = world.recommend(reports=world.reports(activity=True))
    unknown = world.recommend(reports=world.reports(activity=None))
    assert clean.public["inputs"]["activity_after_cutoff"] == "none_observed"
    assert later.public["inputs"]["activity_after_cutoff"] == "later_activity_observed"
    assert unknown.public["inputs"]["activity_after_cutoff"] == "unknown"
    assert clean.skill("alpha-tool")["classification"] == "archive_candidate"
    for blocked in (later, unknown):
        assert blocked.public["status"] == "incomplete"
        assert blocked.skill("alpha-tool")["classification"] == "keep"
        assert blocked.public["counts"]["eligible_for_archive_approval"] == 0
    for value in ("false", 0, 1, [], {}):
        report, private = world.reports()
        private["observed_activity_after_as_of"] = value
        with pytest.raises(SchemaError) as error:
            world.recommend(reports=(report, private))
        assert error.value.code == "private_report_invalid"


PIN_DOCUMENTS: dict[str, object] = {
    "future_schema": {"schema_version": 2, "pins": []},
    "boolean_schema": {"schema_version": True, "pins": []},
    "extra_key": {"schema_version": 1, "pins": [], "note": "x"},
    "missing_schema": {"pins": []},
    "duplicate": {"schema_version": 1, "pins": ["alpha-tool", "alpha-tool"]},
    "non_string": {"schema_version": 1, "pins": [1]},
    "empty_name": {"schema_version": 1, "pins": [""]},
    "not_a_list": {"schema_version": 1, "pins": "alpha-tool"},
}


@pytest.mark.parametrize("document", sorted(PIN_DOCUMENTS))
def test_wrong_pin_schema_fails_rather_than_becoming_an_empty_set(
    tmp_path: Path, document: str
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    with pytest.raises(SchemaError) as error:
        world.recommend(pins_document=PIN_DOCUMENTS[document])
    assert error.value.code == "pins_invalid"


def _item(good: dict[str, object], **changes: object) -> dict[str, object]:
    return {"schema_version": 1, "items": [{**good, **changes}]}


ATTESTATION_MUTATIONS: dict[str, Callable[[dict[str, object]], object]] = {
    "string_boolean": lambda good: _item(good, harness_generated="true"),
    "integer_boolean": lambda good: _item(good, never_user_authored=1),
    "extra_key": lambda good: _item(good, note="x"),
    "missing_key": lambda good: {
        "schema_version": 1,
        "items": [
            {k: v for k, v in good.items() if k != "periodic_or_incident_workflow"}
        ],
    },
    "short_digest": lambda good: _item(good, tree_digest="abc"),
    "uppercase_digest": lambda good: _item(
        good, tree_digest=str(good["tree_digest"]).upper()
    ),
    "naive_time": lambda good: _item(
        good, historical_identity_attested_since="2026-01-01T00:00:00"
    ),
    "offset_time": lambda good: _item(
        good, historical_identity_attested_since="2026-01-01T00:00:00+02:00"
    ),
    "duplicate_name": lambda good: {"schema_version": 1, "items": [good, good]},
    "empty_name": lambda good: _item(good, name=""),
    "future_schema": lambda good: {"schema_version": 2, "items": []},
    "boolean_schema": lambda good: {"schema_version": True, "items": []},
    "items_not_list": lambda good: {"schema_version": 1, "items": {}},
    "top_level_extra": lambda good: {"schema_version": 1, "items": [], "note": 1},
}


@pytest.mark.parametrize("mutation", sorted(ATTESTATION_MUTATIONS))
def test_wrong_attestation_schema_or_types_fail(tmp_path: Path, mutation: str) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    document = ATTESTATION_MUTATIONS[mutation](world.attestation("alpha-tool"))
    with pytest.raises(SchemaError) as error:
        world.recommend(attestations_document=document)
    assert error.value.code == "attestations_invalid"


def test_explicit_empty_pins_is_valid_and_pin_names_are_counted(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    empty = world.recommend(pins=[])
    assert empty.public["counts"]["pins_provided"] == 0
    assert empty.proposal["pin_names"] == []
    pinned = world.recommend(pins=["alpha-tool", "ghost-tool"])
    assert pinned.proposal["pin_names"] == ["alpha-tool"]
    assert pinned.public["counts"]["pins_provided"] == 2
    assert pinned.public["counts"]["pins_matching_installed"] == 1
    assert pinned.skill("alpha-tool")["classification"] == "keep"
    assert "pinned" in pinned.skill("alpha-tool")["reasons"]
    assert (
        pinned.proposal["policy_inputs"]["pins_digest"]
        != (empty.proposal["policy_inputs"]["pins_digest"])
    )


def test_argument_and_report_mismatches_fail_with_fixed_codes(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    world.add("beta-tool", description="Synchronize fictional ledgers weekly.")

    def code(**kwargs: Any) -> str:
        with pytest.raises(SchemaError) as error:
            world.recommend(**kwargs)
        return error.value.code

    assert code(as_of=datetime(2026, 10, 1)) == "invalid_as_of"
    assert (
        code(as_of=datetime(2026, 10, 1, tzinfo=timezone(timedelta(hours=2))))
        == "invalid_as_of"
    )
    assert code(window_days=0) == "invalid_window"
    assert code(window_days=True) == "invalid_window"
    assert code(window_days=60) == "report_scope_mismatch"
    assert code(as_of=AS_OF + timedelta(days=1)) == "report_scope_mismatch"
    report, private = world.reports()
    private["skills"] = private["skills"][:-1]
    assert code(reports=(report, private)) == "private_report_mismatch"
    report, private = world.reports()
    private["skills"][0]["ownership"] = "user"
    assert code(reports=(report, private)) == "private_report_mismatch"
    report, private = world.reports()
    private["skills"].reverse()
    assert code(reports=(report, private)) == "private_report_mismatch"
    report, private = world.reports()
    private["status"] = "incomplete"
    assert code(reports=(report, private)) == "private_report_mismatch"
    report, private = world.reports()
    private["scope"] = {**private["scope"], "window_days": 30}
    assert code(reports=(report, private)) == "private_report_mismatch"
    report, private = world.reports()
    private["skills"][0]["window_read_attempts"] = "3"
    assert code(reports=(report, private)) == "evidence_invalid"


@pytest.mark.parametrize(
    "days",
    [
        {iso_day(ago(120)): 1},
        {iso_day(AS_OF + timedelta(days=1)): 1},
        {"2026-9-30": 1},
        {iso_day(ago(2)): -1},
        {iso_day(ago(2)): True},
    ],
)
def test_observation_calendar_outside_the_window_or_malformed_fails(
    tmp_path: Path, days: dict[str, int]
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    world.days = days
    with pytest.raises(SchemaError) as error:
        world.recommend()
    assert error.value.code == "private_report_invalid"


# --------------------------------------------------------------------------- binding


def test_binding_for_another_measurement_or_with_a_bad_seal_fails(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    cases = {
        "other_harness": world.write_binding("h.json", harness="claude"),
        "other_cutoff": world.write_binding("c.json", as_of=ago(1)),
        "other_window": world.write_binding("w.json", window_days=60),
    }
    for path in cases.values():
        with pytest.raises(SchemaError):
            world.recommend(binding=path)
    tampered = world.write_binding("t.json", tamper=True)
    with pytest.raises(SchemaError):
        world.recommend(binding=tampered)


# --------------------------------------------------------------------------- protection precedence


@pytest.mark.parametrize(
    ("name", "description", "headings"),
    [
        ("auth-helper", "Reformat fictional invoices.", ("Steps",)),
        ("alpha-tool", "Reformat invoices and publish results.", ("Steps",)),
        ("alpha-tool", "Reformat fictional invoices.", ("Payments overview",)),
        ("alpha-tool", "SECURITY review of fictional invoices.", ("Steps",)),
        ("pre-release-notes", "Reformat fictional invoices.", ("Steps",)),
        ("alpha-tool", "Reformat fictional invoices.", ("Restore the draft",)),
    ],
)
def test_high_risk_whole_tokens_force_keep_even_when_never_read(
    tmp_path: Path, name: str, description: str, headings: tuple[str, ...]
) -> None:
    world = World(tmp_path)
    world.add(name, description=description, headings=headings)
    skill = world.recommend().skill(name)
    assert skill["classification"] == "keep"
    assert "high_risk_term" in skill["reasons"]
    assert skill["eligible"] is False


def test_high_risk_matching_is_by_whole_token_not_substring(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add(
        "authority-check",
        description="Handles unreleased drafts of authorities and secretaries.",
        headings=("Migrations", "Releases"),
    )
    skill = world.recommend().skill("authority-check")
    assert skill["classification"] == "archive_candidate"
    assert "high_risk_term" not in skill["reasons"]


@pytest.mark.parametrize("ownership", ["user", "protected", "unknown"])
def test_non_managed_ownership_is_always_kept(tmp_path: Path, ownership: str) -> None:
    world = World(tmp_path)
    world.add("mine-tool", ownership=ownership, root=world.user_root)
    skill = world.recommend().skill("mine-tool")
    assert skill["classification"] == "keep"
    assert f"ownership_{ownership}" in skill["reasons"]
    assert skill["tree_digest"] is None
    assert skill["eligible"] is False


def test_alias_links_and_duplicate_names_are_kept(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("linked-tool", aliases=(Path("/fictional/alias/SKILL.md"),))
    world.add("twin-tool", directory="twin-one")
    world.add("twin-tool", directory="twin-two", description="Other fictional work.")
    result = world.recommend()
    assert "alias_or_link" in result.skill("linked-tool")["reasons"]
    twins = result.skills("twin-tool")
    assert len(twins) == 2
    assert all("ambiguous_name" in twin["reasons"] for twin in twins)
    assert all(twin["classification"] == "keep" for twin in twins)
    assert validate_proposal(result.proposal) is result.proposal


def test_a_different_directory_name_blocks_movement_but_not_review(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool", directory="alpha-dir")
    skill = world.recommend().skill("alpha-tool")
    assert skill["classification"] == "keep"
    assert skill["reasons"] == ["directory_name_mismatch"]
    assert skill["eligible"] is False


def test_non_omp_harnesses_never_become_actionable(tmp_path: Path) -> None:
    world = World(tmp_path, harness="claude")
    world.add("alpha-tool")
    result = world.recommend()
    skill = result.skill("alpha-tool")
    assert skill["classification"] == "keep"
    assert "harness_not_mutable" in skill["reasons"]
    assert result.proposal["managed_tree"] is None
    assert result.public["inputs"]["managed_tree"] == "not_applicable"
    assert result.public["counts"]["eligible_for_archive_approval"] == 0


# --------------------------------------------------------------------------- attestations


def test_attestation_bound_to_another_tree_or_missing_keeps_only_that_item(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    world.add("beta-tool", description="Synchronize fictional ledgers weekly.")
    world.add("gamma-tool", description="Archive fictional shipping labels.")
    stale = world.attestation("beta-tool", tree_digest="0" * 64)
    ghost = {**world.attestation("alpha-tool"), "name": "ghost-tool"}
    result = world.recommend(
        attestations=[world.attestation("alpha-tool"), stale, ghost]
    )
    assert result.public["status"] == "complete"
    assert result.skill("alpha-tool")["classification"] == "archive_candidate"
    assert "attestation_digest_mismatch" in result.skill("beta-tool")["reasons"]
    assert "attestation_missing" in result.skill("gamma-tool")["reasons"]
    assert result.skill("beta-tool")["historical_lineage_attested"] is False
    assert result.public["counts"]["attestations_provided"] == 3
    assert result.public["counts"]["attestations_matching_current_tree"] == 1


def test_editing_a_skill_after_attestation_voids_that_attestation(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    entry = world.add("alpha-tool")
    attested = world.attestation("alpha-tool")
    first = world.recommend(attestations=[attested])
    assert first.skill("alpha-tool")["classification"] == "archive_candidate"
    entry.path.write_text(entry.path.read_text() + "\nEdited later.\n")
    second = world.recommend(attestations=[attested])
    skill = second.skill("alpha-tool")
    assert skill["classification"] == "keep"
    assert skill["reasons"] == ["attestation_digest_mismatch"]
    assert skill["tree_digest"] != attested["tree_digest"]


@pytest.mark.parametrize(
    ("field", "value", "code", "flag"),
    [
        (
            "harness_generated",
            False,
            "not_harness_generated",
            "generated_only_attested",
        ),
        (
            "never_user_authored",
            False,
            "user_authorship_not_excluded",
            "never_user_authored_attested",
        ),
        (
            "description_only_reviewed",
            False,
            "description_only_unreviewed",
            "description_only_reviewed",
        ),
        ("coverage_still_needed", True, "coverage_still_needed", None),
        ("periodic_or_incident_workflow", True, "periodic_or_incident_workflow", None),
    ],
)
def test_an_unfavorable_owner_answer_keeps_the_item(
    tmp_path: Path, field: str, value: bool, code: str, flag: str | None
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    result = world.recommend(attestation_overrides={"alpha-tool": {field: value}})
    skill = result.skill("alpha-tool")
    assert skill["classification"] == "keep"
    assert skill["reasons"] == [code]
    assert skill["eligible"] is False
    if flag is not None:
        assert skill[flag] is False
    else:
        assert skill[field] is True


@pytest.mark.parametrize(
    ("installed_days", "first_observed_days", "since_days", "blocker"),
    [
        (89, None, 150, "age_below_minimum"),
        (90, None, 150, None),
        (30, 120, 150, None),
        (30, 120, 100, "age_below_minimum"),
        (None, None, 150, "age_unknown"),
        (200, 150, 89, "lineage_after_required_start"),
        (200, 150, 90, None),
    ],
)
def test_age_needs_ninety_reliable_days_and_attested_lineage(
    tmp_path: Path,
    installed_days: float | None,
    first_observed_days: float | None,
    since_days: float,
    blocker: str | None,
) -> None:
    world = World(tmp_path)
    world.add(
        "alpha-tool",
        installed_days=installed_days,
        first_observed_inventory_date=(
            None if first_observed_days is None else iso(ago(first_observed_days))
        ),
    )
    result = world.recommend(
        attestation_overrides={
            "alpha-tool": {"historical_identity_attested_since": iso(ago(since_days))}
        }
    )
    skill = result.skill("alpha-tool")
    if blocker is None:
        assert skill["classification"] == "archive_candidate"
    else:
        assert skill["classification"] == "keep"
        assert blocker in skill["reasons"]


def test_a_window_shorter_than_the_age_minimum_is_not_enough(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    world.window_days = 60
    skill = world.recommend().skill("alpha-tool")
    assert skill["classification"] == "keep"
    assert skill["reasons"] == ["window_below_minimum"]


@pytest.mark.parametrize(
    ("snapshots", "groups", "grouping", "blocker"),
    [
        (20, 5, True, None),
        (19, 5, True, "opportunities_below_minimum"),
        (20, 4, True, "opportunities_below_minimum"),
        (400, 50, False, "grouping_incomplete"),
        (None, 5, True, "opportunities_unknown"),
        (20, None, True, "opportunities_unknown"),
        (20, 5, None, "opportunities_unknown"),
    ],
)
def test_twenty_inventory_present_snapshots_across_five_groups_are_required(
    tmp_path: Path,
    snapshots: int | None,
    groups: int | None,
    grouping: bool | None,
    blocker: str | None,
) -> None:
    world = World(tmp_path)
    world.add(
        "alpha-tool",
        inventory_present_subagent_snapshots=snapshots,
        inventory_present_main_task_groups=groups,
        inventory_presence_grouping_complete=grouping,
    )
    skill = world.recommend().skill("alpha-tool")
    if blocker is None:
        assert skill["classification"] == "archive_candidate"
    else:
        assert skill["classification"] == "keep"
        assert skill["reasons"] == [blocker]


# --------------------------------------------------------------------------- never and rare


@pytest.mark.parametrize(
    ("reads", "invocations", "last_days", "gap", "kind", "reason"),
    [
        (0, 0, None, None, "archive_candidate", "never_read_in_window"),
        (1, 0, 60, 45.0, "archive_candidate", "rare_read_in_window"),
        (2, 0, 60, 45.0, "archive_candidate", "rare_read_in_window"),
        (1, 1, 60, 45.0, "archive_candidate", "rare_read_in_window"),
        (1, 0, 59, 45.0, "keep", "recent_use"),
        (2, 1, 60, 45.0, "keep", "use_above_rare_threshold"),
        (1, 0, 60, 45.5, "keep", "window_below_twice_gap"),
        (1, 0, 60, None, "keep", "gap_unknown"),
        (1, 0, None, 45.0, "keep", "use_dates_missing"),
        (None, None, None, None, "keep", "use_channel_unavailable"),
        (0, None, None, None, "keep", "use_channel_unavailable"),
    ],
)
def test_never_and_rare_use_thresholds(
    tmp_path: Path,
    reads: int | None,
    invocations: int | None,
    last_days: float | None,
    gap: float | None,
    kind: str,
    reason: str,
) -> None:
    world = World(tmp_path)
    last = None if last_days is None else iso(ago(last_days))
    world.add(
        "alpha-tool",
        window_read_attempts=reads,
        window_invocation_attempts=invocations,
        window_first_use_date=last,
        window_last_use_date=last,
        largest_observed_inter_use_gap_days=gap,
    )
    skill = world.recommend().skill("alpha-tool")
    assert skill["classification"] == kind
    assert skill["reasons"] == [reason]
    assert skill["eligible"] is (kind == "archive_candidate")
    if reason == "rare_read_in_window":
        assert "observed_use_in_window" in skill["counter_evidence"]


def test_never_read_means_zero_in_the_window_not_zero_in_all_history(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add(
        "alpha-tool",
        observed_read_attempts=7,
        first_read_date=iso(ago(400)),
        last_read_date=iso(ago(200)),
        window_read_attempts=0,
        window_invocation_attempts=0,
    )
    assert world.recommend().skill("alpha-tool")["reasons"] == ["never_read_in_window"]


# --------------------------------------------------------------------------- references


def test_instruction_references_protect_by_name(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    world.add("beta-tool", description="Synchronize fictional ledgers weekly.")
    world.reference_names = {"alpha-tool", "unrelated-name"}
    result = world.recommend()
    assert result.skill("alpha-tool")["reasons"] == ["referenced_by_instruction"]
    assert result.skill("beta-tool")["classification"] == "archive_candidate"
    assert result.proposal["reference_names"] == ["alpha-tool"]


@pytest.mark.parametrize(
    ("body", "extra_frontmatter"),
    [
        ("Load skill://alpha-tool before starting.", ""),
        ("Then run /skill:alpha-tool for the rest.", ""),
        ("", "autoloadSkills:\n  - alpha-tool"),
    ],
)
def test_other_skill_bodies_protect_what_they_load(
    tmp_path: Path, body: str, extra_frontmatter: str
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    world.add(
        "loader-tool",
        description="Synchronize fictional ledgers weekly.",
        body=body,
        extra_frontmatter=extra_frontmatter,
    )
    result = world.recommend()
    assert result.skill("alpha-tool")["reasons"] == ["referenced_by_skill_body"]
    assert result.skill("loader-tool")["classification"] == "archive_candidate"


def test_a_user_owned_skill_body_also_protects_a_managed_dependency(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool")
    world.add(
        "mine-loader",
        description="Synchronize fictional ledgers weekly.",
        body="Use skill://alpha-tool here.",
        ownership="user",
        root=world.user_root,
    )
    assert world.recommend().skill("alpha-tool")["reasons"] == [
        "referenced_by_skill_body"
    ]


def test_a_skill_never_protects_itself_and_directory_names_count(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool", body="Reload skill://alpha-tool when resuming.")
    world.add(
        "Fancy Name",
        directory="fancy-dir",
        description="Synchronize fictional ledgers weekly.",
    )
    world.add(
        "caller-tool",
        description="Archive fictional shipping labels.",
        body="Delegate to skill://fancy-dir.",
    )
    result = world.recommend()
    assert result.skill("alpha-tool")["classification"] == "archive_candidate"
    assert "referenced_by_skill_body" in result.skill("Fancy Name")["reasons"]


def test_unreadable_skill_body_makes_the_proposal_incomplete(tmp_path: Path) -> None:
    world = World(tmp_path)
    entry = world.add("alpha-tool")
    entry.path.unlink()
    result = world.recommend(attestations=[])
    assert result.public["status"] == "incomplete"
    assert result.public["diagnostics"]["skill_body_unreadable"] == 1
    assert result.skill("alpha-tool")["classification"] == "keep"


# --------------------------------------------------------------------------- merge similarity


MEETING = "Summarize meeting notes into action items."


def test_identical_unprotected_pair_becomes_merge_not_archive(tmp_path: Path) -> None:
    world = World(tmp_path)
    for name in ("meeting-notes-summary", "meeting_notes_summary"):
        world.add(name, description=MEETING, headings=("Procedure",))
    result = world.recommend()
    for name in ("meeting-notes-summary", "meeting_notes_summary"):
        skill = result.skill(name)
        assert skill["classification"] == "merge_candidate"
        assert skill["reasons"] == ["similar_installed_skill"]
        assert skill["eligible"] is False
    (pair,) = result.proposal["merge_pairs"]
    assert pair["a"] == "meeting-notes-summary"
    assert pair["b"] == "meeting_notes_summary"
    assert pair["score"] == 1.0
    assert pair["actionable"] is True
    assert pair["review"] == "human_required"
    counts = result.public["counts"]
    assert (counts["merge_candidates"], counts["archive_candidates"]) == (2, 0)
    assert counts["eligible_for_archive_approval"] == 0
    assert (counts["similar_pairs"], counts["actionable_similar_pairs"]) == (1, 1)


@pytest.mark.parametrize(
    ("other_description", "paired"),
    [
        ("gamma delta epsilon", True),
        ("gamma delta epsilon zeta eta", True),
        ("gamma delta epsilon zeta eta theta", False),
    ],
)
def test_similarity_threshold_is_exact_at_seventy_percent(
    tmp_path: Path, other_description: str, paired: bool
) -> None:
    world = World(tmp_path)
    world.add("alpha-beta", description="gamma delta epsilon zeta", headings=())
    world.add("beta-alpha", description=other_description, headings=())
    result = world.recommend()
    assert bool(result.proposal["merge_pairs"]) is paired
    kinds = {skill["classification"] for skill in result.proposal["skills"]}
    assert kinds == ({"merge_candidate"} if paired else {"archive_candidate"})
    if other_description == "gamma delta epsilon":
        assert result.proposal["merge_pairs"][0]["score"] == 0.7


def test_empty_features_contribute_zero_not_perfect_similarity(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("alpha-beta", description="", headings=())
    world.add("beta-alpha", description="", headings=())
    result = world.recommend()
    assert result.proposal["merge_pairs"] == []
    assert {s["classification"] for s in result.proposal["skills"]} == {
        "archive_candidate"
    }


def test_a_pinned_partner_makes_the_pair_reviewable_but_not_actionable(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    for name in ("meeting-notes-summary", "meeting_notes_summary"):
        world.add(name, description=MEETING, headings=("Procedure",))
    result = world.recommend(pins=["meeting-notes-summary"])
    pinned = result.skill("meeting-notes-summary")
    other = result.skill("meeting_notes_summary")
    assert pinned["classification"] == "keep"
    assert other["classification"] == "archive_candidate"
    assert "similar_installed_skill_pair" in other["counter_evidence"]
    (pair,) = result.proposal["merge_pairs"]
    assert (pair["a_protected"], pair["b_protected"]) == (True, False)
    assert pair["actionable"] is False
    assert result.public["counts"]["actionable_similar_pairs"] == 0


def test_a_high_risk_partner_protects_the_pair(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add(
        "meeting-notes-summary", description=MEETING, headings=("Security checks",)
    )
    world.add("meeting_notes_summary", description=MEETING, headings=("Procedure",))
    result = world.recommend()
    (pair,) = result.proposal["merge_pairs"]
    assert pair["actionable"] is False
    assert result.skill("meeting-notes-summary")["reasons"] == ["high_risk_term"]
    assert (
        result.skill("meeting_notes_summary")["classification"] == "archive_candidate"
    )


def test_similarity_is_never_clustered_transitively(tmp_path: Path) -> None:
    world = World(tmp_path)
    for name, description in (
        ("node-relay", "aaa bbb ccc ddd"),
        ("relay-node", "ccc ddd eee fff"),
        ("relay_node", "eee fff ggg hhh"),
    ):
        world.add(name, description=description, headings=("Procedure",))
    result = world.recommend()
    assert [(p["a"], p["b"]) for p in result.proposal["merge_pairs"]] == [
        ("node-relay", "relay-node"),
        ("relay-node", "relay_node"),
    ]
    assert {s["classification"] for s in result.proposal["skills"]} == {
        "merge_candidate"
    }
    assert result.public["counts"]["similar_pairs"] == 2


def test_pair_explanations_show_matching_and_differing_scope_and_boundaries(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add(
        "meeting-notes-summary",
        description="Summarize meeting notes. Do not use for interviews.",
        headings=("Procedure",),
    )
    world.add(
        "meeting_notes_summary",
        description="Summarize meeting notes. Do not use for standups.",
        headings=("Procedure",),
    )
    (pair,) = world.recommend().proposal["merge_pairs"]
    assert {"summarize", "meeting", "notes"} <= set(pair["matched"]["description"])
    assert pair["matched"]["name"] == ["meeting", "notes", "summary"]
    assert pair["matched"]["headings"] == ["procedure"]
    assert pair["differences"]["description_only_a"] == ["interviews"]
    assert pair["differences"]["description_only_b"] == ["standups"]
    assert pair["differences"]["negative_boundaries_only_a"] == ["interviews"]
    assert pair["differences"]["negative_boundaries_only_b"] == ["standups"]
    assert pair["features"]["name"] == 1.0
    assert 0.7 <= pair["score"] < 1.0


# --------------------------------------------------------------------------- managed tree


def test_proposal_embeds_the_whole_managed_root_and_per_skill_subtrees(
    tmp_path: Path,
) -> None:
    result = two_skill_world(tmp_path).recommend()
    world_tree = scan_tree(Path(result.proposal["managed_root"]))
    tree = tree_from_document(result.proposal["managed_tree"])
    assert tree == world_tree
    assert result.proposal["source_root_digest"] == tree.digest
    for name in ("alpha-tool", "beta-auth"):
        assert result.skill(name)["tree_digest"] == subtree_state(tree, name).digest
    assert without_children(tree, {"alpha-tool"}) != tree


def test_unrelated_root_change_moves_the_root_digest_but_not_skill_digests(
    tmp_path: Path,
) -> None:
    world = two_skill_world(tmp_path)
    first = world.recommend()
    extra = world.managed / "gamma-extra"
    extra.mkdir()
    os.chmod(extra, 0o700)
    (extra / "SKILL.md").write_text("fictional")
    os.chmod(extra / "SKILL.md", 0o600)
    second = world.recommend()
    assert (
        first.skill("alpha-tool")["tree_digest"]
        == second.skill("alpha-tool")["tree_digest"]
    )
    assert first.proposal["source_root_digest"] != second.proposal["source_root_digest"]
    assert first.proposal["proposal_digest"] != second.proposal["proposal_digest"]


@pytest.mark.parametrize("unsafe", ["symlink", "group_writable"])
def test_an_unsafe_managed_root_is_incomplete_and_keeps_everything(
    tmp_path: Path, unsafe: str
) -> None:
    world = two_skill_world(tmp_path)
    if unsafe == "symlink":
        (world.managed / "escape").symlink_to(world.root)
    else:
        os.chmod(world.managed / "alpha-tool" / "SKILL.md", 0o660)
    result = world.recommend(attestations=[])
    assert result.public["status"] == "incomplete"
    assert result.public["diagnostics"]["managed_tree_unavailable"] == 1
    assert result.public["inputs"]["managed_tree"] == "unavailable"
    assert result.proposal["managed_tree"] is None
    assert result.proposal["managed_root"] is None
    assert result.proposal["source_root_digest"] is None
    assert {s["classification"] for s in result.proposal["skills"]} == {"keep"}


# --------------------------------------------------------------------------- proposal validation


def test_seal_proposal_is_idempotent_and_recomputes_the_digest(tmp_path: Path) -> None:
    proposal = two_skill_world(tmp_path).recommend().proposal
    assert seal_proposal(proposal) == proposal
    edited = copy.deepcopy(proposal)
    with pytest.raises(SchemaError) as error:
        edited["pin_names"] = ["alpha-tool"]
        validate_proposal(edited)
    assert error.value.code == "proposal_digest_mismatch"
    resealed = seal_proposal(edited)
    assert resealed["proposal_digest"] != proposal["proposal_digest"]
    assert validate_proposal(resealed) is resealed


def _skill(proposal: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in proposal["skills"] if s["name"] == name)


def _beta_eligible(p: dict[str, Any]) -> None:
    _skill(p, "beta-auth")["eligible"] = True


def _alpha_not_eligible(p: dict[str, Any]) -> None:
    _skill(p, "alpha-tool")["eligible"] = False


def _wrong_subtree(p: dict[str, Any]) -> None:
    _skill(p, "alpha-tool")["tree_digest"] = _skill(p, "beta-auth")["tree_digest"]


def _unattested(p: dict[str, Any]) -> None:
    _skill(p, "alpha-tool")["generated_only_attested"] = False


def _needed(p: dict[str, Any]) -> None:
    _skill(p, "alpha-tool")["coverage_still_needed"] = True


def _periodic_unknown(p: dict[str, Any]) -> None:
    _skill(p, "alpha-tool")["periodic_or_incident_workflow"] = None


def _drop_evidence(p: dict[str, Any]) -> None:
    del _skill(p, "alpha-tool")["evidence"]["window_read_attempts"]


def _bad_evidence_type(p: dict[str, Any]) -> None:
    _skill(p, "alpha-tool")["evidence"]["window_read_attempts"] = "0"


def _invented_reason(p: dict[str, Any]) -> None:
    _skill(p, "alpha-tool")["reasons"] = ["bogus_code"]


def _invented_counter(p: dict[str, Any]) -> None:
    _skill(p, "alpha-tool")["counter_evidence"] = ["bogus_code"]


def _unsorted_counter(p: dict[str, Any]) -> None:
    _skill(p, "alpha-tool")["counter_evidence"].reverse()


def _no_reasons(p: dict[str, Any]) -> None:
    _skill(p, "beta-auth")["reasons"] = []


def _extra_top_level(p: dict[str, Any]) -> None:
    p["note"] = 1


def _missing_top_level(p: dict[str, Any]) -> None:
    del p["merge_pairs"]


def _incomplete_with_candidate(p: dict[str, Any]) -> None:
    p["status"] = "incomplete"


def _complete_without_digest(p: dict[str, Any]) -> None:
    p["policy_inputs"]["references_digest"] = None


def _approval_policy(p: dict[str, Any]) -> None:
    p["approval_policy"]["max_batch"] = 99


def _tree_hash(p: dict[str, Any]) -> None:
    p["managed_tree"]["files"][0][1] = "0" * 64


def _tree_removed(p: dict[str, Any]) -> None:
    p["managed_tree"] = None


def _root_digest(p: dict[str, Any]) -> None:
    p["source_root_digest"] = "0" * 64


def _merge_without_pair(p: dict[str, Any]) -> None:
    skill = _skill(p, "beta-auth")
    skill["classification"] = "merge_candidate"
    skill["reasons"] = ["similar_installed_skill"]


def _duplicate_candidate(p: dict[str, Any]) -> None:
    p["skills"].append(copy.deepcopy(_skill(p, "alpha-tool")))


def _day_outside_window(p: dict[str, Any]) -> None:
    p["inventory_observations_by_utc_day"]["2020-01-01"] = 1


def _noncanonical_time(p: dict[str, Any]) -> None:
    p["as_of_utc"] = "2026-10-01T00:00:00+00:00"


def _unknown_harness(p: dict[str, Any]) -> None:
    p["harness"] = "other"


def _positive_reason_on_keep(p: dict[str, Any]) -> None:
    _skill(p, "beta-auth")["reasons"] = ["never_read_in_window"]


@pytest.mark.parametrize(
    "mutation",
    [
        _beta_eligible,
        _alpha_not_eligible,
        _unattested,
        _needed,
        _periodic_unknown,
        _drop_evidence,
        _bad_evidence_type,
        _invented_reason,
        _invented_counter,
        _unsorted_counter,
        _no_reasons,
        _extra_top_level,
        _missing_top_level,
        _incomplete_with_candidate,
        _complete_without_digest,
        _approval_policy,
        _tree_removed,
        _root_digest,
        _merge_without_pair,
        _duplicate_candidate,
        _day_outside_window,
        _noncanonical_time,
        _unknown_harness,
        _positive_reason_on_keep,
    ],
)
def test_validate_proposal_rejects_resealed_inconsistent_proposals(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    proposal = two_skill_world(tmp_path).recommend().proposal
    mutated = copy.deepcopy(proposal)
    mutation(mutated)
    with pytest.raises(SchemaError):
        validate_proposal(seal_proposal(mutated))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (_wrong_subtree, "proposal_tree_mismatch"),
        (_tree_hash, "tree_digest_mismatch"),
    ],
)
def test_validate_proposal_reports_tree_inconsistency_with_its_own_code(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None], code: str
) -> None:
    proposal = two_skill_world(tmp_path).recommend().proposal
    mutated = copy.deepcopy(proposal)
    mutation(mutated)
    with pytest.raises(SchemaError) as error:
        validate_proposal(seal_proposal(mutated))
    assert error.value.code == code


def test_validate_proposal_binds_policy_inputs_schema_and_shape(tmp_path: Path) -> None:
    proposal = two_skill_world(tmp_path).recommend().proposal
    changed = copy.deepcopy(proposal)
    changed["policy_inputs"]["pins_digest"] = "0" * 64
    with pytest.raises(SchemaError) as error:
        validate_proposal(seal_proposal(changed))
    assert error.value.code == "proposal_policy_mismatch"
    for key, value in (("schema_version", 2), ("kind", "other")):
        wrong = copy.deepcopy(proposal)
        wrong[key] = value
        with pytest.raises(SchemaError) as unsupported:
            validate_proposal(seal_proposal(wrong))
        assert unsupported.value.code == "proposal_unsupported_schema"
    for bad in ([], "proposal", None):
        with pytest.raises(SchemaError):
            validate_proposal(bad)


def test_policy_digest_matches_what_recommend_wrote(tmp_path: Path) -> None:
    proposal = two_skill_world(tmp_path).recommend().proposal
    assert proposal["policy_digest"] == policy_digest(
        proposal["as_of_utc"], proposal["window_days"], proposal["policy_inputs"]
    )
    assert proposal["policy_digest"] != policy_digest(
        proposal["as_of_utc"], proposal["window_days"] + 1, proposal["policy_inputs"]
    )
    assert proposal["approval_policy"] == APPROVAL_POLICY


# --------------------------------------------------------------------------- reference workflow


@pytest.mark.parametrize("observed", [True, None])
def test_observed_or_unknown_autoload_dependency_cannot_be_archived(
    tmp_path: Path, observed: bool | None
) -> None:
    world = World(tmp_path)
    world.add("alpha-tool", log_observed_dependency=observed)
    result = world.recommend()
    assert result.skill("alpha-tool")["classification"] == "keep"
    assert result.skill("alpha-tool")["eligible"] is False
    assert result.public["counts"]["eligible_for_archive_approval"] == 0
    if observed:
        assert "alpha-tool" in result.proposal["reference_names"]
