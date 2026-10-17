"""Behavior tests for the journaled archive and restore of managed OMP skills.

Every root, name and byte is invented and lives under a temporary directory; no
real log, skill tree or harness configuration is read or touched. Faults are injected
by patching real filesystem boundaries (exclusive rename, replace, fsync,
link and fstat), never through a production hook: ``Crash`` derives from
``BaseException`` so nothing in the implementation can catch it or clean up after it,
which models a process dying mid-operation. Assertions use counts, fixed diagnostic
codes, exact bytes and modes, and filesystem state, never report wording.
"""

from __future__ import annotations

import copy
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import inventory_archive as arc
import pytest
from inventory_archive import archive, restore
from inventory_policy import (
    APPROVAL_POLICY,
    canonical_digest,
    normalize_evidence,
    policy_digest,
    scan_tree,
    seal_proposal,
    subtree_state,
    tree_document,
    without_children,
)

NAMES = ["alder-notes", "birch-ledger", "cedar-index", "dogwood-trace"]
ATTESTATIONS = (
    "auto_learning_disabled",
    "writers_stopped",
    "coverage_reviewed",
    "ordinary_sessions_attested",
    "baseline_reviewed",
)
RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
HEX64 = re.compile(r"[0-9a-f]{64}")
AS_OF = datetime(2026, 10, 1, tzinfo=UTC)
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
DEFAULT_MODES = {"SKILL.md": 0o600, "scripts/run.sh": 0o700, "data/blob.bin": 0o400}
DEFAULT_DIR_MODES = {"scripts": 0o750, "data": 0o700}


class Crash(BaseException):
    """A simulated process death: nothing in the implementation may catch or clean up after it."""


def crash() -> None:
    raise Crash


def exdev() -> None:
    raise OSError(errno.EXDEV, "cross-device")


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def script_bytes(name: str) -> bytes:
    return b"#!/bin/sh\necho " + name.encode() + b"\n"


def default_files(name: str) -> dict[str, bytes]:
    return {
        "SKILL.md": f"---\nname: {name}\n---\nBody of {name}.\n".encode(),
        "scripts/run.sh": script_bytes(name),
        "data/blob.bin": bytes(range(256)) + name.encode(),
    }


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def content(root: Path) -> dict[str, tuple[int, str]]:
    """Relative path to (exact mode, sha256 of bytes) for every entry below ``root``."""
    result: dict[str, tuple[int, str]] = {".": (mode_of(root), "dir")}
    for current, directories, files in os.walk(root):
        for name in sorted([*directories, *files]):
            path = Path(current) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                digest = "link:" + os.readlink(path)
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                digest = "dir" if stat.S_ISDIR(info.st_mode) else "special"
            result[str(path.relative_to(root))] = (stat.S_IMODE(info.st_mode), digest)
    return result


def stamps(root: Path) -> dict[str, tuple[int, str, int, int]]:
    """``content`` plus modification and change times: equal only if nothing was written."""
    result: dict[str, tuple[int, str, int, int]] = {}
    for relative, (mode, digest) in content(root).items():
        info = (root / relative).lstat()
        result[relative] = (mode, digest, info.st_mtime_ns, info.st_ctime_ns)
    return result


class World:
    """A fictional home with a managed root, protected sibling trees and helpers."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.agent = self.home / ".omp" / "agent"
        self.managed = self.agent / "managed-skills"
        self.archive_root = self.agent / "skill-inventory-archive"
        self.user_skills = self.agent / "skills"
        self.claude = self.home / ".claude" / "skills"
        for directory in (
            self.home,
            self.home / ".omp",
            self.agent,
            self.managed,
            self.user_skills,
            self.home / ".claude",
            self.claude,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o755)
        for protected, text in ((self.user_skills, b"user"), (self.claude, b"claude")):
            (protected / "own-skill").mkdir()
            (protected / "own-skill" / "SKILL.md").write_bytes(text)
        self.seen: set[str] = set()
        self.last: tuple[dict[str, object], dict[str, object]] | None = None

    def add(self, name: str, files: dict[str, bytes] | None = None) -> Path:
        directory = self.managed / name
        directory.mkdir()
        directory.chmod(0o700)
        for relative, data in (files or default_files(name)).items():
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(DEFAULT_MODES.get(relative, 0o600))
        for relative, mode in DEFAULT_DIR_MODES.items():
            if (directory / relative).is_dir():
                (directory / relative).chmod(mode)
        self.seen.add(name)
        return directory

    def populate(self, count: int = 3) -> None:
        for name in NAMES[:count]:
            self.add(name)

    def proposal(
        self,
        candidates: Sequence[str] | None = None,
        *,
        as_of: datetime = AS_OF,
        observations: dict[str, int] | None = None,
        complete: bool = True,
    ) -> dict[str, object]:
        tree = scan_tree(self.managed)
        names = sorted(path.name for path in self.managed.iterdir())
        picked = set(names if candidates is None else candidates) if complete else set()
        stamp = as_of.astimezone(UTC).isoformat().replace("+00:00", "Z")
        inputs: dict[str, object] = {
            key: hashlib.sha256(key.encode()).hexdigest() if complete else None
            for key in ("pins_digest", "attestations_digest", "references_digest")
        }
        skills = []
        for name in names:
            candidate = name in picked
            skills.append(
                {
                    "name": name,
                    "classification": "archive_candidate" if candidate else "keep",
                    "reasons": ["never_read_in_window"] if candidate else ["pinned"],
                    "counter_evidence": [],
                    "tree_digest": subtree_state(tree, name).digest,
                    "generated_only_attested": candidate,
                    "never_user_authored_attested": candidate,
                    "historical_lineage_attested": candidate,
                    "description_only_reviewed": candidate,
                    "coverage_still_needed": False if candidate else None,
                    "periodic_or_incident_workflow": False if candidate else None,
                    "eligible": candidate,
                    "evidence": normalize_evidence(
                        {
                            "name": name,
                            "ownership": "managed",
                            "log_observed_dependency": False,
                        }
                    ),
                }
            )
        body: dict[str, object] = {
            "schema_version": 1,
            "kind": "skill-inventory-proposal",
            "harness": "omp",
            "as_of_utc": stamp,
            "window_days": 90,
            "status": "complete" if complete else "incomplete",
            "snapshot_digest": hashlib.sha256(b"snapshot").hexdigest(),
            "inventory_digest": hashlib.sha256(b"inventory").hexdigest(),
            "policy_digest": policy_digest(stamp, 90, inputs),
            "measurement_scope": {"complete": complete, "valid": True, "closed": True},
            "managed_root": str(self.managed),
            "managed_tree": tree_document(tree),
            "source_root_digest": tree.digest,
            "policy_inputs": inputs,
            "skills": skills,
            "merge_pairs": [],
            "pin_names": sorted(name for name in names if name not in picked),
            "reference_names": [],
            "inventory_observations_by_utc_day": dict(observations or {}),
            "approval_policy": dict(APPROVAL_POLICY),
        }
        return seal_proposal(body)

    @staticmethod
    def approval(
        proposal: dict[str, object], names: Sequence[str]
    ) -> dict[str, object]:
        digests = {
            skill["name"]: skill["tree_digest"]
            for skill in proposal["skills"]  # type: ignore[attr-defined]
        }
        return {
            "schema_version": 1,
            "proposal_digest": proposal["proposal_digest"],
            "items": [{"name": name, "tree_digest": digests[name]} for name in names],
            **dict.fromkeys(ATTESTATIONS, True),
        }

    def archive_batch(
        self,
        names: Sequence[str],
        *,
        apply: bool = True,
        candidates: Sequence[str] | None = None,
        as_of: datetime = AS_OF,
        observations: dict[str, int] | None = None,
        home: Path | None = None,
    ) -> dict[str, object]:
        picked = list(names) if candidates is None else candidates
        proposal = self.proposal(picked, as_of=as_of, observations=observations)
        current = self.proposal(picked, as_of=as_of, observations=observations)
        approval = self.approval(proposal, names)
        self.last = (proposal, approval)
        return archive(proposal, current, approval, apply=apply, home=home or self.home)

    def run_dirs(self) -> list[Path]:
        if not self.archive_root.is_dir():
            return []
        return sorted(
            p for p in self.archive_root.iterdir() if RUN_ID.fullmatch(p.name)
        )

    def manifest(self, batch: int = 1) -> Path:
        for run in self.run_dirs():
            path = run / "manifest.json"
            if json.loads(path.read_text())["batch"]["index"] == batch:
                return path
        raise AssertionError("no run for this batch")

    def load(self, batch: int = 1) -> dict[str, Any]:
        return json.loads(self.manifest(batch).read_text())  # type: ignore[no-any-return]

    def states(self, batch: int = 1) -> list[str]:
        return [item["state"] for item in self.load(batch)["items"]]

    def restore(self, **kwargs: Any) -> dict[str, object]:
        kwargs.setdefault("home", self.home)
        return restore(**kwargs)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path / "world")


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fixed = Clock(T0)
    monkeypatch.setattr(arc, "_utc_now", fixed)
    return fixed


def assert_anonymous(report: dict[str, object], world: World) -> None:
    """Public output carries no installed name, hash or path."""
    text = json.dumps(report, sort_keys=True)
    assert not HEX64.search(text)
    assert str(world.root) not in text
    assert "/" not in text
    for name in world.seen:
        assert name not in text


def assert_refused(report: dict[str, object], code: str) -> None:
    assert report["status"] == "refused"
    assert report["outcome"] == "refused"
    assert report["diagnostics"] == {code: 1}


@contextmanager
def renames(
    monkeypatch: pytest.MonkeyPatch,
    match: Callable[[str, str], bool],
    *,
    nth: int = 1,
    before: Callable[[], None] | None = None,
    after: Callable[[], None] | None = None,
) -> Iterator[dict[str, int]]:
    """Wrap actual exclusive moves and journal replacement around a matching call."""
    real_move = arc._rename_at
    real_replace = os.replace
    seen = {"hits": 0}

    def invoke(src: str, dst: str, operation: Callable[[], None]) -> None:
        hit = match(src, dst)
        seen["hits"] += int(hit)
        active = hit and seen["hits"] == nth
        if active and before is not None:
            before()
        operation()
        if active and after is not None:
            after()

    def move(src_fd: int, src: str, dst_fd: int, dst: str) -> None:
        invoke(src, dst, lambda: real_move(src_fd, src, dst_fd, dst))

    def replace_file(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        invoke(
            src,
            dst,
            lambda: real_replace(
                src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd
            ),
        )

    with monkeypatch.context() as patch:
        patch.setattr(arc, "_rename_at", move)
        patch.setattr(os, "replace", replace_file)
        yield seen


def is_item(name: str) -> Callable[[str, str], bool]:
    return lambda src, dst: src == name and dst == name


def is_manifest_replace(src: str, dst: str) -> bool:
    return src.startswith(".manifest-") and dst == "manifest.json"


def is_stage(src: str, dst: str) -> bool:
    return src.startswith(".stage-") and RUN_ID.fullmatch(dst) is not None


def edit_manifest(
    path: Path, change: Callable[[dict[str, Any]], object], *, seal: bool = True
) -> None:
    document = json.loads(path.read_text())
    change(document)
    if seal:
        document.pop("integrity", None)
        document["integrity"] = canonical_digest(document)
    path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")


# --------------------------------------------------------------------------- dry run and success


def test_dry_run_validates_and_creates_nothing(world: World) -> None:
    world.populate(3)
    before = stamps(world.root)

    report = world.archive_batch(NAMES[:2], apply=False)

    assert (report["status"], report["outcome"], report["mode"]) == (
        "complete",
        "dry_run_ready",
        "dry_run",
    )
    assert report["counts"]["approved"] == 2  # type: ignore[index]
    assert stamps(world.root) == before
    assert not world.archive_root.exists()
    assert_anonymous(report, world)


def test_missing_approval_is_reported_by_dry_run_and_refused_when_applying(
    world: World,
) -> None:
    world.populate(3)
    proposal = world.proposal(NAMES[:2])
    current = world.proposal(NAMES[:2])
    before = stamps(world.root)

    dry = archive(proposal, current, None, apply=False, home=world.home)
    applied = archive(proposal, current, None, apply=True, home=world.home)

    assert (dry["status"], dry["outcome"]) == ("incomplete", "approval_required")
    assert dry["counts"] == {"archive_candidates": 2}
    assert_refused(applied, "approval_required")
    assert stamps(world.root) == before
    assert not world.archive_root.exists()


def test_apply_moves_only_the_approved_items_and_preserves_bytes_and_modes(
    world: World,
) -> None:
    world.populate(3)
    before = {name: content(world.managed / name) for name in NAMES[:3]}
    outside = (content(world.user_skills), content(world.claude))
    tree_before = scan_tree(world.managed)

    report = world.archive_batch(NAMES[:2])

    assert (report["status"], report["outcome"], report["mode"]) == (
        "complete",
        "applied",
        "apply",
    )
    assert report["counts"]["moved"] == 2  # type: ignore[index]
    assert report["counts"]["remaining"] == 0  # type: ignore[index]
    assert report["last_move_date"] == "2026-10-01"
    assert report["quarantine_earliest_end_date"] == "2026-10-22"
    run = world.run_dirs()[0]
    assert run.name == report["run_id"]
    for name in NAMES[:2]:
        assert not (world.managed / name).exists()
        assert content(run / "skills" / name) == before[name]
    assert content(world.managed / NAMES[2]) == before[NAMES[2]]
    assert (content(world.user_skills), content(world.claude)) == outside
    assert (
        scan_tree(world.managed).digest
        == without_children(tree_before, set(NAMES[:2])).digest
    )
    assert mode_of(world.archive_root) == 0o700
    assert mode_of(run) == 0o700
    assert mode_of(run / "skills") == 0o700
    assert mode_of(run / "manifest.json") == 0o600
    assert (world.archive_root / ".lock").is_file()
    assert_anonymous(report, world)


def test_manifest_binds_proposal_approval_attestations_and_complete_hashes(
    world: World,
) -> None:
    world.populate(3)
    tree = scan_tree(world.managed)
    world.archive_batch(NAMES[:2])
    assert world.last is not None
    proposal, approval = world.last
    manifest = world.load()

    assert manifest["binding"]["proposal_digest"] == proposal["proposal_digest"]
    assert manifest["binding"]["approval_digest"] == canonical_digest(approval)
    assert manifest["binding"]["source_root_digest"] == tree.digest
    assert manifest["attestations"] == dict.fromkeys(ATTESTATIONS, True)
    assert manifest["batch"]["index"] == 1
    assert [(item["name"], item["state"]) for item in manifest["items"]] == [
        (NAMES[0], "moved"),
        (NAMES[1], "moved"),
    ]
    assert manifest["source_tree"] == json.loads(json.dumps(tree_document(tree)))
    script = script_bytes(NAMES[0])
    assert [
        f"{NAMES[0]}/scripts/run.sh",
        hashlib.sha256(script).hexdigest(),
        0o700,
        len(script),
    ] in manifest["source_tree"]["files"]


def test_default_home_comes_from_path_home(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(2)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: world.home))
    proposal = world.proposal(NAMES[:1])

    report = archive(
        proposal,
        copy.deepcopy(proposal),
        world.approval(proposal, NAMES[:1]),
        apply=False,
    )

    assert report["status"] == "complete"
    assert restore(list_runs=True)["outcome"] == "no_runs"


# --------------------------------------------------------------------------- approval refusals


def _digest_of(proposal: dict[str, object], name: str) -> object:
    for skill in proposal["skills"]:  # type: ignore[attr-defined]
        if skill["name"] == name:
            return skill["tree_digest"]
    raise AssertionError


APPROVAL_CASES: dict[
    str, tuple[Callable[[dict[str, Any], dict[str, Any]], object], str]
] = {
    "wrong_proposal_digest": (
        lambda a, p: a.update(proposal_digest="0" * 64),
        "approval_digest_mismatch",
    ),
    "unknown_key": (lambda a, p: a.update(extra=True), "approval_schema_invalid"),
    "missing_key": (lambda a, p: a.pop("baseline_reviewed"), "approval_schema_invalid"),
    "future_schema": (
        lambda a, p: a.update(schema_version=2),
        "approval_schema_invalid",
    ),
    "boolean_schema": (
        lambda a, p: a.update(schema_version=True),
        "approval_schema_invalid",
    ),
    **{
        f"{key}_false": (
            lambda a, p, key=key: a.update({key: False}),
            "approval_attestation_missing",
        )
        for key in ATTESTATIONS
    },
    "truthy_not_true": (
        lambda a, p: a.update(writers_stopped=1),
        "approval_attestation_missing",
    ),
    "items_not_a_list": (lambda a, p: a.update(items={}), "approval_schema_invalid"),
    "empty_items": (lambda a, p: a.update(items=[]), "approval_batch_invalid"),
    "duplicate_item": (
        lambda a, p: a["items"].append(dict(a["items"][0])),
        "approval_item_duplicate",
    ),
    "extra_item_key": (
        lambda a, p: a["items"][0].update(extra=1),
        "approval_schema_invalid",
    ),
    "wrong_item_digest": (
        lambda a, p: a["items"][0].update(tree_digest="0" * 64),
        "approval_tree_mismatch",
    ),
    "non_hex_digest": (
        lambda a, p: a["items"][0].update(tree_digest="xyz"),
        "approval_item_invalid",
    ),
    "traversal_name": (
        lambda a, p: a["items"][0].update(name="../escape"),
        "approval_item_invalid",
    ),
    "separator_name": (
        lambda a, p: a["items"][0].update(name="a/b"),
        "approval_item_invalid",
    ),
    "empty_name": (lambda a, p: a["items"][0].update(name=""), "approval_item_invalid"),
    "dot_name": (
        lambda a, p: a["items"][0].update(name=".hidden"),
        "approval_item_invalid",
    ),
    "keep_item": (
        lambda a, p: a["items"].__setitem__(
            0, {"name": NAMES[2], "tree_digest": _digest_of(p, NAMES[2])}
        ),
        "approval_item_not_eligible",
    ),
    "unknown_item": (
        lambda a, p: a["items"].__setitem__(
            0, {"name": "missing-skill", "tree_digest": "1" * 64}
        ),
        "approval_item_not_eligible",
    ),
}


@pytest.mark.parametrize(
    ("mutate", "code"), list(APPROVAL_CASES.values()), ids=list(APPROVAL_CASES)
)
def test_approval_deviations_are_refused_before_anything_is_touched(
    world: World, mutate: Callable[[dict[str, Any], dict[str, Any]], object], code: str
) -> None:
    world.populate(3)
    proposal = world.proposal(NAMES[:2])
    current = world.proposal(NAMES[:2])
    approval = world.approval(proposal, NAMES[:1])
    mutate(approval, proposal)
    before = stamps(world.root)

    for apply in (False, True):
        report = archive(proposal, current, approval, apply=apply, home=world.home)
        assert_refused(report, code)
        assert_anonymous(report, world)
        assert stamps(world.root) == before
        assert not world.archive_root.exists()


def test_batches_are_capped_at_ten_items(world: World) -> None:
    names = [f"skill-{index:02d}" for index in range(11)]
    for name in names:
        world.add(name)
    proposal = world.proposal(names)
    current = world.proposal(names)

    too_many = archive(
        proposal, current, world.approval(proposal, names), apply=True, home=world.home
    )
    ten = archive(
        proposal,
        current,
        world.approval(proposal, names[:10]),
        apply=False,
        home=world.home,
    )

    assert_refused(too_many, "approval_batch_invalid")
    assert not world.archive_root.exists()
    assert (ten["status"], ten["outcome"]) == ("complete", "dry_run_ready")


# --------------------------------------------------------------------------- proposal and live-state refusals


def _tamper_proposal(
    world: World, proposal: dict[str, Any], current: dict[str, Any]
) -> str:
    proposal["skills"][0]["reasons"] = ["rare_read_in_window"]
    return "proposal_digest_mismatch"


def _drifted_current(
    world: World, proposal: dict[str, Any], current: dict[str, Any]
) -> str:
    (world.managed / NAMES[2] / "SKILL.md").write_bytes(b"changed before the rebuild")
    current.clear()
    current.update(world.proposal(NAMES[:2]))
    return "proposal_drift"


def _live_selected_file(
    world: World, proposal: dict[str, Any], current: dict[str, Any]
) -> str:
    (world.managed / NAMES[0] / "SKILL.md").write_bytes(b"edited after review")
    return "source_changed"


def _live_unselected_file(
    world: World, proposal: dict[str, Any], current: dict[str, Any]
) -> str:
    (world.managed / NAMES[2] / "SKILL.md").write_bytes(b"edited after review")
    return "source_changed"


def _live_new_skill(
    world: World, proposal: dict[str, Any], current: dict[str, Any]
) -> str:
    world.add("elm-addition")
    return "source_changed"


def _live_removed_skill(
    world: World, proposal: dict[str, Any], current: dict[str, Any]
) -> str:
    shutil.rmtree(world.managed / NAMES[2])
    return "source_changed"


def _live_mode_only(
    world: World, proposal: dict[str, Any], current: dict[str, Any]
) -> str:
    (world.managed / NAMES[2] / "SKILL.md").chmod(0o640)
    return "source_changed"


@pytest.mark.parametrize(
    "setup",
    [
        _tamper_proposal,
        _drifted_current,
        _live_selected_file,
        _live_unselected_file,
        _live_new_skill,
        _live_removed_skill,
        _live_mode_only,
    ],
)
def test_proposal_and_live_state_deviations_refuse_without_a_trace(
    world: World, setup: Callable[[World, dict[str, Any], dict[str, Any]], str]
) -> None:
    world.populate(3)
    proposal = world.proposal(NAMES[:2])
    current = copy.deepcopy(proposal)
    approval = world.approval(proposal, NAMES[:1])
    code = setup(world, proposal, current)
    before = stamps(world.root)

    for apply in (False, True):
        report = archive(proposal, current, approval, apply=apply, home=world.home)
        assert_refused(report, code)
        assert stamps(world.root) == before
        assert not world.archive_root.exists()


def test_a_cutoff_after_the_real_operation_time_is_refused_exactly_at_the_boundary(
    world: World, clock: Clock
) -> None:
    world.populate(3)
    proposal = world.proposal(NAMES[:2], as_of=AS_OF)
    current = copy.deepcopy(proposal)
    approval = world.approval(proposal, NAMES[:1])
    before = stamps(world.root)

    clock.now = AS_OF - timedelta(seconds=1)
    for apply in (False, True):
        report = archive(proposal, current, approval, apply=apply, home=world.home)
        assert_refused(report, "future_evidence_cutoff")
    clock.now = AS_OF - timedelta(microseconds=1)
    assert_refused(
        archive(proposal, current, approval, apply=True, home=world.home),
        "future_evidence_cutoff",
    )
    assert stamps(world.root) == before
    assert not world.archive_root.exists()

    clock.now = AS_OF
    boundary = archive(proposal, current, approval, apply=False, home=world.home)
    assert (boundary["status"], boundary["outcome"]) == ("complete", "dry_run_ready")
    clock.now = AS_OF + timedelta(seconds=1)
    assert (
        archive(proposal, current, approval, apply=True, home=world.home)["outcome"]
        == "applied"
    )


def test_incomplete_proposals_and_foreign_homes_never_authorize_a_move(
    world: World, tmp_path: Path
) -> None:
    world.populate(3)
    incomplete = world.proposal(complete=False)
    proposal = world.proposal(NAMES[:2])
    approval = world.approval(proposal, NAMES[:1])
    other = World(tmp_path / "other")
    other.populate(3)
    before = (stamps(world.root), stamps(other.root))

    refused = [
        archive(
            incomplete, copy.deepcopy(incomplete), None, apply=False, home=world.home
        ),
        archive(
            proposal, copy.deepcopy(proposal), approval, apply=True, home=other.home
        ),
        archive(
            proposal,
            copy.deepcopy(proposal),
            approval,
            apply=True,
            home=Path("relative/home"),
        ),
    ]

    assert [r["diagnostics"] for r in refused] == [
        {"proposal_incomplete": 1},
        {"managed_root_mismatch": 1},
        {"home_invalid": 1},
    ]
    assert (stamps(world.root), stamps(other.root)) == before


# --------------------------------------------------------------------------- roots and tree safety


def _managed_symlink(world: World) -> None:
    real = world.root / "real-managed"
    os.rename(world.managed, real)
    world.managed.symlink_to(real)


def _omp_symlink(world: World) -> None:
    real = world.root / "real-omp"
    os.rename(world.home / ".omp", real)
    (world.home / ".omp").symlink_to(real)


def _archive_symlink(world: World) -> None:
    outside = world.root / "outside"
    outside.mkdir(mode=0o700)
    world.archive_root.symlink_to(outside)


def _archive_open_mode(world: World) -> None:
    world.archive_root.mkdir()
    world.archive_root.chmod(0o755)


def _managed_group_writable(world: World) -> None:
    world.managed.chmod(0o775)


def _agent_world_writable(world: World) -> None:
    world.agent.chmod(0o757)


def _home_group_writable(world: World) -> None:
    world.home.chmod(0o775)


@pytest.mark.parametrize(
    "unsafe",
    [
        _managed_symlink,
        _omp_symlink,
        _archive_symlink,
        _archive_open_mode,
        _managed_group_writable,
        _agent_world_writable,
        _home_group_writable,
    ],
)
def test_symlinked_or_unsafe_roots_are_refused_without_following_or_changing_them(
    world: World, unsafe: Callable[[World], None]
) -> None:
    world.populate(3)
    proposal = world.proposal(NAMES[:2])
    current = copy.deepcopy(proposal)
    approval = world.approval(proposal, NAMES[:1])
    unsafe(world)
    before = stamps(world.root)

    for apply in (False, True):
        report = archive(proposal, current, approval, apply=apply, home=world.home)
        assert_refused(report, "root_unsafe")
    assert stamps(world.root) == before
    listed = world.restore(list_runs=True)
    assert listed["status"] != "complete" or listed["outcome"] == "no_runs"


def _symlink_inside(item: Path) -> None:
    os.symlink("SKILL.md", item / "link")


def _hardlink_inside(item: Path) -> None:
    os.link(item / "SKILL.md", item / "hard")


def _fifo_inside(item: Path) -> None:
    os.mkfifo(item / "pipe")


def _world_writable_inside(item: Path) -> None:
    (item / "SKILL.md").chmod(0o666)


@pytest.mark.parametrize(
    "plant", [_symlink_inside, _hardlink_inside, _fifo_inside, _world_writable_inside]
)
@pytest.mark.parametrize("target", [NAMES[0], NAMES[2]], ids=["approved", "unapproved"])
def test_links_special_files_and_unsafe_modes_anywhere_in_the_tree_refuse_every_move(
    world: World, plant: Callable[[Path], None], target: str
) -> None:
    world.populate(3)
    proposal = world.proposal(NAMES[:2])
    current = copy.deepcopy(proposal)
    approval = world.approval(proposal, NAMES[:1])
    plant(world.managed / target)
    before = stamps(world.root)

    for apply in (False, True):
        report = archive(proposal, current, approval, apply=apply, home=world.home)
        assert_refused(report, "tree_entry_unsafe")
    assert stamps(world.root) == before
    assert not world.archive_root.exists()


def test_a_device_boundary_between_the_roots_is_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    proposal = world.proposal(NAMES[:2])
    current = copy.deepcopy(proposal)
    approval = world.approval(proposal, NAMES[:1])
    target = os.stat(world.agent)
    real = os.fstat

    def foreign_device(fd: int) -> os.stat_result:
        info = real(fd)
        if (info.st_dev, info.st_ino) != (target.st_dev, target.st_ino):
            return info
        values = list(info)
        values[2] = info.st_dev + 1
        return os.stat_result(values)

    before = stamps(world.root)
    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", foreign_device)
        for apply in (False, True):
            report = archive(proposal, current, approval, apply=apply, home=world.home)
            assert_refused(report, "cross_device")
    assert stamps(world.root) == before
    assert not world.archive_root.exists()


def test_a_rename_that_crosses_devices_stops_the_batch_with_nothing_moved(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)

    with renames(monkeypatch, is_item(NAMES[0]), before=exdev):
        report = world.archive_batch(NAMES[:2])

    assert (report["status"], report["outcome"]) == ("incomplete", "partial")
    assert report["diagnostics"] == {"local_io_error": 1}
    assert report["counts"]["moved"] == 0  # type: ignore[index]
    assert content(world.managed) == original
    assert world.states() == ["planned", "planned"]


def test_a_manifest_that_cannot_be_made_durable_blocks_every_move(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)
    real = os.fsync

    def failing_fsync(fd: int) -> None:
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "disk")
        real(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", failing_fsync)
        report = world.archive_batch(NAMES[:2])

    assert_refused(report, "private_write_failed")
    assert content(world.managed) == original
    assert world.run_dirs() == []
    leftovers = [
        p for p in world.archive_root.iterdir() if p.name.startswith(".stage-")
    ]
    assert len(leftovers) == 1 and not (leftovers[0] / "manifest.json").exists()
    assert world.restore(list_runs=True)["outcome"] == "no_runs"
    assert world.archive_batch(NAMES[:2])["outcome"] == "applied"


# --------------------------------------------------------------------------- interruption windows


def test_crash_before_the_first_rename_leaves_a_planned_journal_and_untouched_source(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)

    with renames(monkeypatch, is_item(NAMES[0]), before=crash), pytest.raises(Crash):
        world.archive_batch(NAMES[:2])

    assert content(world.managed) == original
    assert world.states() == ["planned", "planned"]
    listed = world.restore(list_runs=True)
    assert listed["counts"]["planned"] == 2  # type: ignore[index]
    assert listed["counts"]["needs_reconcile"] == 0  # type: ignore[index]
    # A new batch cannot start until the unfinished run is reconciled.
    assert_refused(world.archive_batch(NAMES[:2]), "unfinished_run")

    done = world.restore(manifest_path=world.manifest(), apply=True)
    assert (done["status"], done["outcome"]) == ("complete", "restored")
    assert done["counts"]["in_place"] == 2  # type: ignore[index]
    assert world.states() == ["restored", "restored"]
    assert content(world.managed) == original
    assert world.archive_batch(NAMES[:2])["outcome"] == "applied"
    assert world.load(2)["batch"]["index"] == 2


def test_crash_between_a_rename_and_its_journal_record_is_reconciled_from_filesystem_evidence(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)
    moved_before = content(world.managed / NAMES[0])

    with renames(monkeypatch, is_item(NAMES[0]), after=crash), pytest.raises(Crash):
        world.archive_batch(NAMES[:2])

    run = world.run_dirs()[0]
    recorded = world.manifest().read_bytes()
    assert not (world.managed / NAMES[0]).exists()
    assert (run / "skills" / NAMES[0]).is_dir()
    assert world.states() == ["planned", "planned"]
    before = stamps(world.root)

    listed = world.restore(list_runs=True)
    dry = world.restore(manifest_path=world.manifest(), apply=False)

    assert stamps(world.root) == before
    assert listed["counts"]["moved"] == 1 and listed["counts"]["planned"] == 1  # type: ignore[index]
    assert listed["counts"]["needs_reconcile"] == 1  # type: ignore[index]
    assert (dry["status"], dry["outcome"]) == ("complete", "dry_run_ready")
    assert dry["counts"]["would_restore"] == 1 and dry["counts"]["in_place"] == 1  # type: ignore[index]
    assert world.manifest().read_bytes() == recorded

    restored = world.restore(
        manifest_path=world.manifest(), items=[NAMES[0]], apply=True
    )

    assert restored["counts"]["restored"] == 1  # type: ignore[index]
    assert content(world.managed / NAMES[0]) == moved_before
    assert content(world.managed) == original
    assert world.states() == ["restored", "planned"]


def test_restoring_only_one_item_after_a_crash_records_the_other_as_moved_and_leaves_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    moved_before = content(world.managed / NAMES[0])

    with renames(monkeypatch, is_item(NAMES[0]), after=crash), pytest.raises(Crash):
        world.archive_batch(NAMES[:2])
    run = world.run_dirs()[0]

    report = world.restore(manifest_path=world.manifest(), items=[NAMES[1]], apply=True)

    assert report["counts"]["in_place"] == 1 and report["counts"]["unselected"] == 1  # type: ignore[index]
    assert content(run / "skills" / NAMES[0]) == moved_before
    assert not (world.managed / NAMES[0]).exists()
    manifest = world.load()
    assert [item["state"] for item in manifest["items"]] == ["moved", "restored"]
    assert manifest["items"][0]["moved_utc"] is not None


def test_crash_before_the_second_rename_keeps_the_first_move_recorded(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)

    with renames(monkeypatch, is_item(NAMES[1]), before=crash), pytest.raises(Crash):
        world.archive_batch(NAMES[:2])

    assert world.states() == ["moved", "planned"]
    listed = world.restore(list_runs=True)
    assert listed["counts"]["moved"] == 1 and listed["counts"]["planned"] == 1  # type: ignore[index]
    assert listed["counts"]["needs_reconcile"] == 0  # type: ignore[index]
    assert_refused(world.archive_batch([NAMES[2]]), "unfinished_run")

    done = world.restore(manifest_path=world.manifest(), apply=True)

    assert done["counts"]["restored"] == 1 and done["counts"]["in_place"] == 1  # type: ignore[index]
    assert content(world.managed) == original
    assert (world.run_dirs()[0] / "skills").is_dir()
    assert list((world.run_dirs()[0] / "skills").iterdir()) == []


def test_crash_while_replacing_the_journal_leaves_the_old_journal_and_a_tolerated_temp(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)

    with renames(monkeypatch, is_manifest_replace, before=crash), pytest.raises(Crash):
        world.archive_batch(NAMES[:2])

    run = world.run_dirs()[0]
    temporaries = [p for p in run.iterdir() if p.name.startswith(".manifest-")]
    assert len(temporaries) == 1
    assert world.states() == ["planned", "planned"]
    assert (run / "skills" / NAMES[0]).is_dir()
    listed = world.restore(list_runs=True)
    assert listed["status"] == "complete"
    assert listed["counts"]["moved"] == 1  # type: ignore[index]

    done = world.restore(manifest_path=world.manifest(), apply=True)

    assert done["status"] == "complete"
    assert content(world.managed) == original
    assert world.states() == ["restored", "restored"]
    assert temporaries[0].exists()


def test_failed_directory_sync_after_a_move_is_incomplete_and_reconcilable(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)
    armed = {"on": False}
    real = os.fsync

    def failing_fsync(fd: int) -> None:
        if armed["on"] and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "disk")
        real(fd)

    with (
        renames(monkeypatch, is_item(NAMES[0]), after=lambda: armed.update(on=True)),
        monkeypatch.context() as inner,
    ):
        inner.setattr(os, "fsync", failing_fsync)
        report = world.archive_batch(NAMES[:2])

    assert (report["status"], report["outcome"]) == ("incomplete", "partial")
    assert report["diagnostics"] == {"local_io_error": 1}
    assert world.states() == ["planned", "planned"]
    assert not (world.managed / NAMES[0]).exists()
    assert world.restore(list_runs=True)["counts"]["moved"] == 1  # type: ignore[index]

    world.restore(manifest_path=world.manifest(), apply=True)

    assert content(world.managed) == original


def test_crash_while_staging_leaves_no_run_and_does_not_block_a_later_batch(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)

    def interrupted(*args: object, **kwargs: object) -> None:
        raise Crash

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", interrupted)
        with pytest.raises(Crash):
            world.archive_batch(NAMES[:2])

    assert content(world.managed) == original
    assert world.run_dirs() == []
    listed = world.restore(list_runs=True)
    assert (listed["status"], listed["outcome"]) == ("complete", "no_runs")
    assert listed["counts"]["staging_leftovers"] == 1  # type: ignore[index]

    report = world.archive_batch(NAMES[:2])

    assert report["outcome"] == "applied"
    assert len(world.run_dirs()) == 1
    assert (
        len([p for p in world.archive_root.iterdir() if p.name.startswith(".stage-")])
        == 1
    )


def test_crash_during_restore_after_the_rename_back_is_reconciled_idempotently(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)
    world.archive_batch(NAMES[:2])

    with renames(monkeypatch, is_item(NAMES[0]), after=crash), pytest.raises(Crash):
        world.restore(manifest_path=world.manifest(), apply=True)

    assert world.states() == ["moved", "moved"]
    before = stamps(world.root)
    listed = world.restore(list_runs=True)
    assert stamps(world.root) == before
    assert listed["counts"]["restored"] == 1 and listed["counts"]["moved"] == 1  # type: ignore[index]
    assert listed["counts"]["needs_reconcile"] == 1  # type: ignore[index]

    done = world.restore(manifest_path=world.manifest(), apply=True)

    assert done["counts"]["in_place"] == 1 and done["counts"]["restored"] == 1  # type: ignore[index]
    assert world.states() == ["restored", "restored"]
    assert content(world.managed) == original


# --------------------------------------------------------------------------- interference during apply


def test_a_writer_touching_unselected_files_mid_batch_stops_after_recording_the_move(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    writer = world.managed / NAMES[2] / "SKILL.md"

    with renames(
        monkeypatch,
        is_item(NAMES[0]),
        after=lambda: writer.write_bytes(b"concurrent write"),
    ):
        report = world.archive_batch(NAMES[:2])

    assert (report["status"], report["outcome"]) == ("incomplete", "partial")
    assert report["diagnostics"] == {"source_changed": 1}
    assert report["counts"]["moved"] == 1 and report["counts"]["remaining"] == 1  # type: ignore[index]
    assert writer.read_bytes() == b"concurrent write"
    assert (world.managed / NAMES[1]).is_dir()
    assert world.states() == ["moved", "planned"]


def test_recreation_of_a_moved_source_name_stops_the_batch_and_restore_keeps_both_copies(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = {name: content(world.managed / name) for name in NAMES[:2]}

    def recreate() -> None:
        recreated = world.managed / NAMES[0]
        recreated.mkdir(mode=0o700)
        (recreated / "SKILL.md").write_bytes(b"written by a concurrent learner")
        (recreated / "SKILL.md").chmod(0o600)

    with renames(monkeypatch, is_item(NAMES[0]), after=recreate):
        report = world.archive_batch(NAMES[:2])

    assert report["diagnostics"] == {"source_changed": 1}
    run = world.run_dirs()[0]
    live_before = content(world.managed / NAMES[0])

    conflict = world.restore(
        manifest_path=world.manifest(), items=[NAMES[0]], apply=True
    )

    assert (conflict["status"], conflict["outcome"]) == ("incomplete", "conflict")
    assert conflict["counts"]["conflict"] == 1  # type: ignore[index]
    assert content(world.managed / NAMES[0]) == live_before
    assert content(run / "skills" / NAMES[0]) == original[NAMES[0]]
    item = world.load()["items"][0]
    assert (item["state"], item["conflict_reason"]) == ("conflict", "live_differs")
    # Re-running without resolution changes nothing; resolving then restores the original.
    again = world.restore(manifest_path=world.manifest(), items=[NAMES[0]], apply=True)
    assert again["outcome"] == "conflict"
    assert content(world.managed / NAMES[0]) == live_before
    shutil.rmtree(world.managed / NAMES[0])
    resolved = world.restore(
        manifest_path=world.manifest(), items=[NAMES[0]], apply=True
    )
    assert (resolved["status"], resolved["outcome"]) == ("complete", "restored")
    assert content(world.managed / NAMES[0]) == original[NAMES[0]]


def test_an_unexpected_destination_entry_stops_before_any_move(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.populate(3)
    original = content(world.managed)

    def squat() -> None:
        (world.run_dirs()[0] / "skills" / NAMES[0]).mkdir(mode=0o700)

    with renames(monkeypatch, is_stage, after=squat):
        report = world.archive_batch(NAMES[:2])

    assert report["diagnostics"] == {"destination_unexpected": 1}
    assert report["counts"]["moved"] == 0  # type: ignore[index]
    assert content(world.managed) == original
    assert (world.run_dirs()[0] / "skills" / NAMES[0]).is_dir()
    assert list((world.run_dirs()[0] / "skills" / NAMES[0]).iterdir()) == []


# --------------------------------------------------------------------------- restore behavior


def _archived(world: World, count: int = 2) -> dict[str, dict[str, tuple[int, str]]]:
    world.populate(3)
    before = {name: content(world.managed / name) for name in NAMES[:3]}
    assert world.archive_batch(NAMES[:count])["outcome"] == "applied"
    return before


def test_list_is_read_only_aggregate_and_reports_dates(world: World) -> None:
    _archived(world)
    before = stamps(world.root)

    report = world.restore(list_runs=True)

    assert stamps(world.root) == before
    assert (report["status"], report["outcome"], report["mode"]) == (
        "complete",
        "listed",
        "list",
    )
    assert report["counts"]["runs"] == 1 and report["counts"]["moved"] == 2  # type: ignore[index]
    assert report["counts"]["unreadable_runs"] == 0  # type: ignore[index]
    (entry,) = report["runs"]  # type: ignore[misc]
    assert RUN_ID.fullmatch(entry["run_id"])
    assert entry["items"] == 2 and entry["batch_index"] == 1
    assert entry["states"]["moved"] == 2 and entry["needs_reconcile"] == 0
    assert entry["created_date"] == "2026-10-01"
    assert entry["last_move_date"] == "2026-10-01"
    assert entry["quarantine_end_date"] == "2026-10-22"
    assert_anonymous(report, world)


def test_list_without_any_archive_root_is_an_explicit_empty_result(
    world: World,
) -> None:
    world.populate(2)
    before = stamps(world.root)

    report = world.restore(list_runs=True)

    assert (report["status"], report["outcome"]) == ("complete", "no_runs")
    assert report["counts"] == {} and report["runs"] == []
    assert stamps(world.root) == before
    assert not world.archive_root.exists()


def test_dry_run_never_mutates_and_counts_what_would_be_restored(world: World) -> None:
    _archived(world)
    before = stamps(world.root)

    everything = world.restore(manifest_path=world.manifest())
    one = world.restore(manifest_path=world.manifest(), items=[NAMES[0]])

    assert stamps(world.root) == before
    assert (everything["status"], everything["outcome"]) == (
        "complete",
        "dry_run_ready",
    )
    assert everything["counts"]["would_restore"] == 2  # type: ignore[index]
    assert one["counts"]["would_restore"] == 1 and one["counts"]["unselected"] == 1  # type: ignore[index]
    assert_anonymous(everything, world)


def test_subset_restore_is_exact_idempotent_and_leaves_the_rest_archived(
    world: World,
) -> None:
    before = _archived(world)
    run = world.run_dirs()[0]

    first = world.restore(manifest_path=world.manifest(), items=[NAMES[0]], apply=True)

    assert (first["status"], first["outcome"]) == ("complete", "restored")
    assert first["counts"]["restored"] == 1 and first["counts"]["unselected"] == 1  # type: ignore[index]
    assert content(world.managed / NAMES[0]) == before[NAMES[0]]
    assert content(run / "skills" / NAMES[1]) == before[NAMES[1]]
    assert not (world.managed / NAMES[1]).exists()
    assert world.states() == ["restored", "moved"]
    recorded = world.manifest().read_bytes()

    again = world.restore(manifest_path=world.manifest(), items=[NAMES[0]], apply=True)

    assert again["counts"]["already_restored"] == 1  # type: ignore[index]
    assert world.manifest().read_bytes() == recorded
    # A user edit after restoring is never treated as a conflict or reverted.
    (world.managed / NAMES[0] / "SKILL.md").write_bytes(b"edited by the user")
    edited = world.restore(manifest_path=world.manifest(), apply=True)
    assert (
        edited["counts"]["already_restored"] == 1 and edited["counts"]["restored"] == 1
    )  # type: ignore[index]
    assert (world.managed / NAMES[0] / "SKILL.md").read_bytes() == b"edited by the user"
    assert content(world.managed / NAMES[1]) == before[NAMES[1]]
    assert world.states() == ["restored", "restored"]
    assert list((run / "skills").iterdir()) == []


def test_full_cycle_restores_original_bytes_modes_and_the_whole_tree_without_deleting_anything(
    world: World,
) -> None:
    before = _archived(world)
    original = {name: content(world.managed / name) for name in NAMES[2:3]}
    outside = (content(world.user_skills), content(world.claude))
    assert scan_tree(world.managed).digest != ""

    report = world.restore(manifest_path=world.manifest(), apply=True)

    assert report["counts"]["restored"] == 2  # type: ignore[index]
    for name in NAMES[:2]:
        assert content(world.managed / name) == before[name]
    assert content(world.managed / NAMES[2]) == original[NAMES[2]]
    assert (content(world.user_skills), content(world.claude)) == outside
    assert world.manifest().is_file()
    assert (world.run_dirs()[0] / "skills").is_dir()
    assert_anonymous(report, world)


def test_identical_live_copy_is_recorded_as_externally_restored_without_deleting_either(
    world: World,
) -> None:
    before = _archived(world)
    run = world.run_dirs()[0]
    shutil.copytree(run / "skills" / NAMES[0], world.managed / NAMES[0])
    assert content(world.managed / NAMES[0]) == before[NAMES[0]]

    report = world.restore(manifest_path=world.manifest(), items=[NAMES[0]], apply=True)

    assert (report["status"], report["outcome"]) == ("complete", "restored")
    assert report["counts"]["externally_restored"] == 1  # type: ignore[index]
    assert content(world.managed / NAMES[0]) == before[NAMES[0]]
    assert content(run / "skills" / NAMES[0]) == before[NAMES[0]]
    assert world.states() == ["externally_restored", "moved"]


def test_a_differing_same_name_live_entry_is_a_conflict_that_keeps_both(
    world: World,
) -> None:
    before = _archived(world)
    run = world.run_dirs()[0]
    live = world.managed / NAMES[0]
    live.mkdir(mode=0o700)
    (live / "SKILL.md").write_bytes(b"a different skill with the same name")
    (live / "SKILL.md").chmod(0o600)
    live_before = content(live)

    dry = world.restore(manifest_path=world.manifest(), items=[NAMES[0]])
    applied = world.restore(
        manifest_path=world.manifest(), items=[NAMES[0]], apply=True
    )

    assert (dry["status"], dry["outcome"]) == ("incomplete", "conflict")
    assert (applied["status"], applied["outcome"]) == ("incomplete", "conflict")
    assert applied["diagnostics"] == {"restore_conflict": 1}
    assert content(live) == live_before
    assert content(run / "skills" / NAMES[0]) == before[NAMES[0]]
    item = world.load()["items"][0]
    assert (item["state"], item["conflict_reason"]) == ("conflict", "live_differs")
    # A conflict in history stops any later batch.
    assert_refused(world.archive_batch([NAMES[2]]), "unresolved_conflict")


def test_a_modified_or_missing_archived_copy_is_a_conflict_and_nothing_is_moved(
    world: World,
) -> None:
    _archived(world)
    run = world.run_dirs()[0]
    tampered = run / "skills" / NAMES[0] / "SKILL.md"
    tampered.chmod(0o600)
    tampered.write_bytes(b"modified in the archive")
    shutil.rmtree(run / "skills" / NAMES[1])

    report = world.restore(manifest_path=world.manifest(), apply=True)

    assert (report["status"], report["outcome"]) == ("incomplete", "conflict")
    assert report["counts"]["conflict"] == 2  # type: ignore[index]
    assert (
        not (world.managed / NAMES[0]).exists()
        and not (world.managed / NAMES[1]).exists()
    )
    assert tampered.read_bytes() == b"modified in the archive"
    reasons = [item["conflict_reason"] for item in world.load()["items"]]
    assert reasons == ["archive_differs", "archive_missing"]


def test_restore_requests_are_validated_before_any_change(
    world: World, tmp_path: Path
) -> None:
    _archived(world)
    manifest = world.manifest()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "manifest.json").write_bytes(manifest.read_bytes())
    (outside / "manifest.json").chmod(0o600)
    renamed = world.run_dirs()[0].parent / "not-a-run" / "manifest.json"
    before = stamps(world.root)

    cases: list[tuple[dict[str, Any], str]] = [
        ({"manifest_path": outside / "manifest.json"}, "manifest_path_invalid"),
        ({"manifest_path": renamed}, "manifest_path_invalid"),
        ({"manifest_path": manifest.parent / "other.json"}, "manifest_path_invalid"),
        (
            {
                "manifest_path": manifest.parent
                / ".."
                / manifest.parent.name
                / "manifest.json"
            },
            "manifest_path_invalid",
        ),
        (
            {"manifest_path": manifest, "items": ["unknown-name"]},
            "restore_item_unknown",
        ),
        ({"manifest_path": manifest, "items": []}, "restore_items_invalid"),
        (
            {"manifest_path": manifest, "items": [NAMES[0], NAMES[0]]},
            "restore_items_invalid",
        ),
        ({"manifest_path": manifest, "items": ["../escape"]}, "restore_items_invalid"),
        ({"manifest_path": None}, "manifest_required"),
        ({"list_runs": True, "apply": True}, "restore_request_invalid"),
        ({"list_runs": True, "items": [NAMES[0]]}, "restore_request_invalid"),
    ]
    for kwargs, code in cases:
        for apply in (False, True):
            if "list_runs" in kwargs and not apply:
                continue
            report = world.restore(**{"apply": apply, **kwargs})
            assert_refused(report, code)
    assert stamps(world.root) == before
    link = world.root / "homelink"
    link.symlink_to(world.home)
    assert_refused(restore(list_runs=True, home=link), "root_unsafe")


def test_restore_apply_without_a_managed_root_is_refused_but_list_still_works(
    world: World,
) -> None:
    _archived(world)
    shutil.rmtree(world.managed)

    applied = world.restore(manifest_path=world.manifest(), apply=True)
    listed = world.restore(list_runs=True)

    assert_refused(applied, "managed_root_missing")
    assert listed["status"] == "complete"
    assert listed["counts"]["moved"] == 2  # type: ignore[index]
    assert listed["counts"]["conflict"] == 0  # type: ignore[index]


def test_the_utility_lock_serializes_apply_but_never_blocks_read_only_calls(
    world: World,
) -> None:
    _archived(world)
    handle = os.open(world.archive_root / ".lock", os.O_RDWR)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = stamps(world.root)

        applied = world.restore(manifest_path=world.manifest(), apply=True)
        batch = world.archive_batch([NAMES[2]])
        listed = world.restore(list_runs=True)
        dry = world.restore(manifest_path=world.manifest())

        assert_refused(applied, "archive_locked")
        assert batch["status"] == "refused"
        assert listed["status"] == "complete" and dry["status"] == "complete"
        assert stamps(world.root) == before
    finally:
        os.close(handle)


def test_first_batch_is_refused_when_another_process_holds_the_lock(
    world: World,
) -> None:
    world.populate(3)
    world.archive_root.mkdir(mode=0o700)
    lock = world.archive_root / ".lock"
    handle = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = content(world.managed)

        report = world.archive_batch(NAMES[:2])

        assert_refused(report, "archive_locked")
        assert content(world.managed) == original
        assert world.run_dirs() == []
    finally:
        os.close(handle)


# --------------------------------------------------------------------------- journal tamper


def _flip_state(document: dict[str, Any]) -> None:
    document["items"][0]["state"] = "restored"


TAMPERS: dict[str, tuple[Callable[[dict[str, Any]], object], bool, str]] = {
    "state_without_reseal": (_flip_state, False, "manifest_integrity"),
    "future_schema": (
        lambda d: d.update(schema_version=2),
        True,
        "manifest_schema_unsupported",
    ),
    "boolean_schema": (
        lambda d: d.update(schema_version=True),
        True,
        "manifest_schema_unsupported",
    ),
    "extra_top_level_key": (lambda d: d.update(extra=1), True, "manifest_invalid"),
    "missing_key": (lambda d: d.pop("generation"), True, "manifest_invalid"),
    "wrong_kind": (lambda d: d.update(kind="other"), True, "manifest_invalid"),
    "wrong_operation": (
        lambda d: d.update(operation="restore"),
        True,
        "manifest_invalid",
    ),
    "wrong_roots": (
        lambda d: d.update(roots={"managed": "x", "archive": "y"}),
        True,
        "manifest_invalid",
    ),
    "item_digest": (
        lambda d: d["items"][0].update(tree_digest="0" * 64),
        True,
        "manifest_invalid",
    ),
    "item_traversal": (
        lambda d: d["items"][0].update(name="../escape"),
        True,
        "manifest_invalid",
    ),
    "item_state_unknown": (
        lambda d: d["items"][0].update(state="deleted"),
        True,
        "manifest_invalid",
    ),
    "restored_without_time": (_flip_state, True, "manifest_invalid"),
    "conflict_without_reason": (
        lambda d: d["items"][0].update(state="conflict"),
        True,
        "manifest_invalid",
    ),
    "items_swapped": (lambda d: d["items"].reverse(), True, "manifest_invalid"),
    "items_emptied": (lambda d: d.update(items=[]), True, "manifest_invalid"),
    "attestation_false": (
        lambda d: d["attestations"].update(writers_stopped=False),
        True,
        "manifest_invalid",
    ),
    "generation_zero": (lambda d: d.update(generation=0), True, "manifest_invalid"),
    "plan_digest": (
        lambda d: d.update(plan_digest="0" * 64),
        True,
        "manifest_integrity",
    ),
    "binding_digest": (
        lambda d: d["binding"].update(proposal_digest="0" * 64),
        True,
        "manifest_integrity",
    ),
    "tree_hash": (
        lambda d: d["source_tree"]["files"][0].__setitem__(1, "0" * 64),
        True,
        "tree_digest_mismatch",
    ),
    "tree_mode": (
        lambda d: d["source_tree"]["files"][0].__setitem__(2, 0o644),
        True,
        "tree_digest_mismatch",
    ),
}


@pytest.mark.parametrize(
    ("change", "seal", "code"), list(TAMPERS.values()), ids=list(TAMPERS)
)
def test_tampered_journals_are_refused_everywhere_and_never_listed_as_zero(
    world: World, change: Callable[[dict[str, Any]], object], seal: bool, code: str
) -> None:
    _archived(world)
    edit_manifest(world.manifest(), change, seal=seal)
    before = stamps(world.root)

    listed = world.restore(list_runs=True)
    dry = world.restore(manifest_path=world.manifest())
    applied = world.restore(manifest_path=world.manifest(), apply=True)
    batch = world.archive_batch([NAMES[2]])

    assert listed["status"] == "incomplete"
    assert listed["counts"]["unreadable_runs"] == 1 and listed["counts"]["runs"] == 0  # type: ignore[index]
    assert listed["diagnostics"] == {code: 1}
    assert_refused(dry, code)
    assert_refused(applied, code)
    assert_refused(batch, "history_unreadable")
    assert stamps(world.root) == before
    assert not (world.managed / NAMES[0]).exists()


def test_journal_permissions_links_and_layout_are_validated(
    world: World, tmp_path: Path
) -> None:
    _archived(world)
    run = world.run_dirs()[0]
    manifest = run / "manifest.json"
    good = manifest.read_bytes()
    before_content = content(world.managed)

    def outcome() -> dict[str, object]:
        return world.restore(manifest_path=manifest, apply=True)

    manifest.chmod(0o644)
    assert_refused(outcome(), "private_file_unsafe")
    manifest.chmod(0o600)

    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(good)
    foreign.chmod(0o600)
    manifest.unlink()
    manifest.symlink_to(foreign)
    assert_refused(outcome(), "private_file_unsafe")
    manifest.unlink()
    manifest.write_bytes(good)
    manifest.chmod(0o600)

    manifest.write_bytes(b'{"schema_version":1,"schema_version":1}')
    duplicate = outcome()
    assert duplicate["status"] == "refused"
    manifest.write_bytes(good)

    run.chmod(0o755)
    assert_refused(outcome(), "root_unsafe")
    run.chmod(0o700)

    (run / "notes.txt").write_bytes(b"stray")
    assert_refused(outcome(), "run_unexpected_entry")
    (run / "notes.txt").unlink()

    stray = world.archive_root / "stray-directory"
    stray.mkdir(mode=0o700)
    listed = world.restore(list_runs=True)
    assert listed["status"] == "incomplete"
    assert listed["counts"]["unexpected_entries"] == 1  # type: ignore[index]
    assert listed["counts"]["runs"] == 1  # type: ignore[index]
    assert listed["diagnostics"] == {"archive_root_unexpected": 1}
    stray.rmdir()

    renamed = world.archive_root / "20000101T000000Z-00000000"
    run.rename(renamed)
    mismatch = world.restore(manifest_path=renamed / "manifest.json")
    assert_refused(mismatch, "manifest_invalid")
    renamed.rename(run)

    assert content(world.managed) == before_content
    assert outcome()["status"] == "complete"


def test_a_missing_manifest_or_run_is_never_reported_as_zero_runs(world: World) -> None:
    _archived(world)
    world.manifest().unlink()

    report = world.restore(list_runs=True)

    assert report["status"] == "incomplete"
    assert report["counts"]["unreadable_runs"] == 1  # type: ignore[index]
    assert report["diagnostics"] == {"manifest_missing": 1}


# --------------------------------------------------------------------------- later-batch dwell


def _second_batch(
    world: World,
    clock: Clock,
    *,
    days: int,
    observations: dict[str, int],
    names: Sequence[str],
) -> dict[str, object]:
    moment = T0 + timedelta(days=days)
    clock.now = moment
    as_of = datetime(moment.year, moment.month, moment.day, tzinfo=UTC)
    return world.archive_batch(names, as_of=as_of, observations=observations)


def test_later_batches_need_seven_days_and_twenty_proven_observations_after_the_move_day(
    world: World, clock: Clock
) -> None:
    for name in NAMES:
        world.add(name)
    assert world.archive_batch(NAMES[:2])["outcome"] == "applied"
    rest = NAMES[2:]
    before = stamps(world.root)

    early = _second_batch(
        world, clock, days=3, observations={"2026-10-02": 40}, names=rest
    )
    thin = _second_batch(
        world, clock, days=8, observations={"2026-10-05": 19}, names=rest
    )
    # Observations on the move day itself are partial and never count.
    partial_day = _second_batch(
        world,
        clock,
        days=8,
        observations={"2026-10-01": 30, "2026-10-05": 19},
        names=rest,
    )
    undated = _second_batch(world, clock, days=8, observations={}, names=rest)

    assert_refused(early, "dwell_days_insufficient")
    assert_refused(thin, "dwell_sessions_insufficient")
    assert_refused(partial_day, "dwell_sessions_insufficient")
    assert_refused(undated, "dwell_sessions_insufficient")
    assert stamps(world.root) == before
    assert len(world.run_dirs()) == 1

    dry = _second_batch(
        world,
        clock,
        days=8,
        observations={"2026-10-05": 10, "2026-10-07": 10},
        names=rest,
    )
    assert dry["outcome"] == "applied"
    assert dry["counts"]["dwell_observations"] == 20  # type: ignore[index]
    assert dry["counts"]["dwell_days_elapsed"] == 8  # type: ignore[index]
    assert dry["counts"]["prior_runs"] == 1  # type: ignore[index]
    assert world.load(2)["batch"]["index"] == 2
    assert dry["last_move_date"] == "2026-10-09"
    assert dry["quarantine_earliest_end_date"] == "2026-10-30"


def test_dwell_is_enforced_by_dry_run_too_and_a_future_as_of_cannot_fake_it(
    world: World, clock: Clock
) -> None:
    for name in NAMES:
        world.add(name)
    world.archive_batch(NAMES[:2])
    clock.now = T0 + timedelta(days=2)

    # as-of eight days after the move while the clock is two days after it.
    proposal = world.proposal(
        NAMES[2:],
        as_of=datetime(2026, 10, 9, tzinfo=UTC),
        observations={"2026-10-05": 50},
    )
    report = archive(
        proposal,
        copy.deepcopy(proposal),
        world.approval(proposal, NAMES[2:]),
        apply=False,
        home=world.home,
    )

    assert_refused(report, "future_evidence_cutoff")
    clock.now = T0 + timedelta(days=9)
    proposal = world.proposal(
        NAMES[2:],
        as_of=datetime(2026, 10, 3, tzinfo=UTC),
        observations={"2026-10-02": 50},
    )
    short = archive(
        proposal,
        copy.deepcopy(proposal),
        world.approval(proposal, NAMES[2:]),
        apply=False,
        home=world.home,
    )
    assert_refused(short, "dwell_days_insufficient")


def test_dwell_counts_the_last_move_across_restored_batches(
    world: World, clock: Clock
) -> None:
    for name in NAMES:
        world.add(name)
    world.archive_batch(NAMES[:2])
    world.restore(manifest_path=world.manifest(), apply=True)

    report = _second_batch(
        world, clock, days=2, observations={"2026-10-02": 99}, names=NAMES[:2]
    )

    assert_refused(report, "dwell_days_insufficient")


def test_protected_roots_are_immutable_across_archive_and_restore(world: World) -> None:
    world.populate(3)
    protected = (
        stamps(world.user_skills),
        stamps(world.claude),
        content(world.managed / NAMES[2]),
    )

    world.archive_batch(NAMES[:2])
    world.restore(manifest_path=world.manifest(), items=[NAMES[0]], apply=True)
    world.restore(manifest_path=world.manifest(), apply=True)

    assert (
        stamps(world.user_skills),
        stamps(world.claude),
        content(world.managed / NAMES[2]),
    ) == protected
    assert sorted(path.name for path in (world.home / ".omp").iterdir()) == ["agent"]
    assert sorted(path.name for path in world.agent.iterdir()) == [
        "managed-skills",
        "skill-inventory-archive",
        "skills",
    ]


@pytest.mark.parametrize("operation", ["archive", "restore"])
def test_concurrently_created_empty_destination_is_never_overwritten(
    world: World, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    world.populate(1)
    name = NAMES[0]
    original = content(world.managed / name)
    if operation == "restore":
        assert world.archive_batch([name])["status"] == "complete"
    created: list[tuple[Path, int]] = []

    def recreate() -> None:
        destination = (
            world.managed / name
            if operation == "restore"
            else world.run_dirs()[0] / "skills" / name
        )
        destination.mkdir(mode=0o700)
        created.append((destination, destination.stat().st_ino))

    with renames(monkeypatch, is_item(name), before=recreate):
        result = (
            world.archive_batch([name])
            if operation == "archive"
            else world.restore(manifest_path=world.manifest(), apply=True)
        )
    assert result["status"] != "complete"
    destination, inode = created[0]
    assert destination.stat().st_ino == inode
    assert list(destination.iterdir()) == []
    source = (
        world.managed / name
        if operation == "archive"
        else world.run_dirs()[0] / "skills" / name
    )
    assert content(source) == original


def test_never_moved_edited_item_can_close_without_blocking_a_later_batch(
    world: World, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    world.populate(3)
    first = content(world.managed / NAMES[0])
    with renames(monkeypatch, is_item(NAMES[0]), after=crash), pytest.raises(Crash):
        world.archive_batch(NAMES[:2])
    unchanged = world.managed / NAMES[1]
    (unchanged / "SKILL.md").write_bytes(b"new fictional owner edit; never overwrite")
    edited = content(unchanged)
    result = world.restore(manifest_path=world.manifest(), apply=True)
    assert result["status"] == "complete"
    assert world.states() == ["restored", "restored"]
    assert content(world.managed / NAMES[0]) == first
    assert content(unchanged) == edited
    (unchanged / "SKILL.md").write_bytes(b"another later fictional owner edit")
    later = content(unchanged)
    # Crash recovery bounds an unjournaled move by real filesystem ctime as well.
    moved = datetime.fromisoformat(world.load()["items"][0]["moved_utc"])
    clock.now = moved + timedelta(days=8)
    observations = {(moved + timedelta(days=1)).date().isoformat(): 20}
    next_batch = world.archive_batch(
        [NAMES[2]], as_of=clock.now, observations=observations
    )
    assert next_batch["status"] == "complete"
    assert content(unchanged) == later


def test_kept_ambiguous_name_does_not_block_an_unrelated_candidate(
    world: World,
) -> None:
    world.populate(2)
    duplicate_path = world.user_skills / NAMES[1]
    duplicate_path.mkdir()
    (duplicate_path / "SKILL.md").write_bytes(
        b"Fictional user-authored same-name skill"
    )
    original = content(duplicate_path)
    proposal = world.proposal(candidates=[NAMES[0]])
    duplicate = copy.deepcopy(proposal["skills"][1])
    duplicate["tree_digest"] = None
    duplicate["evidence"] = normalize_evidence(
        {"name": NAMES[1], "ownership": "user", "log_observed_dependency": False}
    )
    duplicate["reasons"] = ["ambiguous_name", "ownership_user"]
    proposal["skills"].append(duplicate)
    proposal = seal_proposal(proposal)
    result = archive(
        proposal,
        copy.deepcopy(proposal),
        world.approval(proposal, [NAMES[0]]),
        apply=True,
        home=world.home,
    )
    assert result["status"] == "complete"
    assert not (world.managed / NAMES[0]).exists()
    assert (world.managed / NAMES[1]).exists()
    assert content(duplicate_path) == original
