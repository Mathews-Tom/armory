"""Filesystem and identity failures that must not certify complete measurement."""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from pathlib import Path

import inventory_catalog
import pytest
from inventory_catalog import load_inventory
from inventory_io import Snapshot, write_private_json
from inventory_omp import parse_file
from inventory_report import build_report
from inventory_types import Cohort, Inventory, SchemaError

CLOCK = datetime(2025, 1, 31, tzinfo=UTC)
KEY = b"fictional-contract-key-0000000000"


def header(identity: str = "fictional-session") -> dict[str, object]:
    return {
        "type": "session",
        "version": 3,
        "id": identity,
        "timestamp": "2025-01-01T00:00:00Z",
    }


def make_snapshot(base: Path) -> tuple[Snapshot, Path, Path]:
    logs = base / "logs"
    logs.mkdir()
    (logs / "empty").mkdir()
    source = logs / "session.jsonl"
    source.write_text(json.dumps(header()) + "\n")
    snapshot = Snapshot(
        base / "binding.json", harness="omp", roots=[logs], as_of=CLOCK, window_days=90
    )
    snapshot.bind_inventory("a" * 64)
    return snapshot, source, logs


def directory_identity(value: int | str | Path) -> tuple[int, int]:
    info = (
        os.fstat(value)
        if isinstance(value, int)
        else os.stat(value, follow_symlinks=False)
    )
    return info.st_dev, info.st_ino


def test_unusable_catalog_cannot_certify_complete_zero_inventory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    (root / "fictional-unreadable-skill" / "SKILL.md").mkdir(parents=True)
    inventory = load_inventory("omp", key=KEY, skill_roots=[root])
    parsed = parse_file(
        [header()], inventory=inventory, file_key="opaque", cohort_hint="main"
    )
    report, _ = build_report(
        harness="omp",
        parsed=[parsed],
        inventory=inventory,
        as_of=CLOCK,
        window_days=90,
        snapshot={"valid": True, "closed": True},
        input_issues=Counter(),
    )
    assert inventory.coverage["skill_file_unusable"] == 1
    assert report["status"] == "incomplete"
    assert report["diagnostics"] == {"catalog_skill_file_unusable": 1}


def test_capture_detects_same_inode_rewrite_before_first_record_read(
    tmp_path: Path,
) -> None:
    snapshot, source, _ = make_snapshot(tmp_path)
    original = source.read_bytes()
    replacement = original.replace(b"fictional-session", b"different-session")
    assert len(replacement) == len(original)
    inode = source.stat().st_ino
    source.write_bytes(replacement)
    assert source.stat().st_ino == inode
    for frozen in snapshot.files:
        list(snapshot.records(frozen))
    result = snapshot.finish("a" * 64)
    assert result["valid"] is False
    assert snapshot.issues["snapshot_rewritten"] == 1
    assert not (tmp_path / "binding.json").exists()


def test_final_unreadable_subtree_cannot_certify_closed_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _, logs = make_snapshot(tmp_path)
    # Include the subtree in both passes without adding any frozen file to it.
    empty = logs / "empty"
    for frozen in snapshot.files:
        list(snapshot.records(frozen))
    target = directory_identity(empty)
    real_scandir = os.scandir

    def unreadable(
        path: int | str | Path = ".",
    ) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        if directory_identity(path) == target:
            raise PermissionError("fictional denied subtree")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", unreadable)
    result = snapshot.finish("a" * 64)
    assert result["valid"] is False
    assert result["closed"] is False
    assert snapshot.issues["log_dir_unreadable"] > 0


def test_queued_log_directory_swap_never_reads_outside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logs = tmp_path / "logs"
    branch = logs / "branch"
    branch.mkdir(parents=True)
    (branch / "trusted.jsonl").write_text(
        json.dumps(header("fictional-trusted")) + "\n"
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "forbidden.jsonl").write_text(
        json.dumps(header("fictional-forbidden")) + "\n"
    )
    target = directory_identity(branch)
    real_scandir = os.scandir
    fired = False

    def swap(
        path: int | str | Path = ".",
    ) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        nonlocal fired
        if not fired and directory_identity(path) == target:
            fired = True
            branch.rename(tmp_path / "preserved-branch")
            branch.symlink_to(outside, target_is_directory=True)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap)
    snapshot = Snapshot(
        tmp_path / "binding.json",
        harness="omp",
        roots=[logs],
        as_of=CLOCK,
        window_days=90,
    )
    observed = [row for frozen in snapshot.files for row in snapshot.records(frozen)]
    assert fired
    assert all(row.get("id") != "fictional-forbidden" for row in observed)


def test_private_parent_swap_never_persists_payload_in_a_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)
    real_open = os.open
    fired = False

    def swap(
        path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        nonlocal fired
        if flags & os.O_CREAT and not fired:
            fired = True
            private.rename(tmp_path / "preserved-private")
            private.symlink_to(repository, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap)
    try:
        write_private_json(
            private / "binding.json", {"private_marker": "fictional-owner-only"}
        )
    except SchemaError:
        # Refusing the changed destination is valid; persisting inside Git is not.
        pass
    assert fired
    assert sorted(item.name for item in repository.iterdir()) == [".git"]


@pytest.mark.parametrize("conflicting", [False, True])
@pytest.mark.parametrize("copied_cohort", ["sub", "nested"])
def test_disclosure_identities_reconcile_across_copied_session_files(
    conflicting: bool, copied_cohort: Cohort
) -> None:
    inventory = Inventory()
    files = []
    for index in range(2):
        # Equal-length descriptions ensure conflict checks do not merely compare sizes.
        description = "tan." if conflicting and index else "red."
        init = {
            "type": "session_init",
            "id": "fictional-shared-init",
            "timestamp": "2025-01-01T00:00:01Z",
            "systemPrompt": f"<skills>\n- fictional-skill: {description}\n</skills>",
        }
        files.append(
            parse_file(
                [
                    header(),
                    init,
                    {
                        "type": "message",
                        "id": "fictional-shared-message",
                        "timestamp": "2025-01-01T00:00:02Z",
                        "message": {
                            "role": "assistant",
                            "timestamp": 1735689602000,
                            "content": [
                                {
                                    "type": "toolCall",
                                    "id": "fictional-shared-call",
                                    "name": "read",
                                    "arguments": {"path": "skill://fictional-skill"},
                                }
                            ],
                        },
                    },
                ],
                inventory=inventory,
                file_key=f"opaque-{index}",
                cohort_hint=copied_cohort if index else "sub",
            )
        )
    report, _ = build_report(
        harness="omp",
        parsed=files,
        inventory=inventory,
        as_of=CLOCK,
        window_days=90,
        snapshot={"valid": True, "closed": True},
        input_issues=Counter(),
    )
    if conflicting:
        assert report["status"] == "incomplete"
        assert report["diagnostics"] == {"conflicting_duplicate_disclosure": 1}
    else:
        assert report["status"] == "complete"
        assert isinstance(report["exposure"], dict)
        assert report["exposure"]["observations"] == 1
        events = report["events"]
        assert isinstance(events, dict)
        observed = events["all_observed"]
        assert isinstance(observed, dict)
        assert observed["read_attempts"] == 1
        assert observed["files_with_reads"] == 2
        if copied_cohort == "nested":
            scope = report["scope"]
            assert isinstance(scope, dict)
            assert scope["sessions_by_cohort"] == {"unknown": 1}
            assert report["exposure"]["by_cohort"] == {"unknown": 1}


def test_catalog_parent_swap_never_reads_an_unapproved_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skills"
    trusted = root / "fictional-trusted"
    trusted.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    for directory, name in (
        (trusted, "fictional-trusted"),
        (outside, "fictional-forbidden"),
    ):
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Fictional boundary fixture.\n---\n"
        )
    real_open = os.open
    fired = False

    def swap(
        path: str | bytes | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal fired
        if Path(os.fsdecode(path)).name == "SKILL.md" and not fired:
            fired = True
            trusted.rename(tmp_path / "preserved-skill")
            trusted.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap)
    inventory = load_inventory("omp", key=KEY, skill_roots=[root])
    assert fired
    assert [entry.name for entry in inventory.entries] == ["fictional-trusted"]


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root bypasses directory search permissions"
)
def test_unsearchable_skill_directory_blocks_complete_measurement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    directory = root / "fictional-denied"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\nname: fictional-denied\ndescription: Fictional inaccessible fixture.\n---\n"
    )
    directory.chmod(0o600)
    try:
        inventory = load_inventory("omp", key=KEY, skill_roots=[root])
    finally:
        directory.chmod(0o700)
    parsed = parse_file(
        [header()], inventory=inventory, file_key="opaque", cohort_hint="main"
    )
    report, _ = build_report(
        harness="omp",
        parsed=[parsed],
        inventory=inventory,
        as_of=CLOCK,
        window_days=90,
        snapshot={"valid": True, "closed": True},
        input_issues=Counter(),
    )
    assert report["status"] == "incomplete"
    assert report["diagnostics"] == {"catalog_skill_file_unusable": 1}


def test_installation_age_change_invalidates_frozen_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skills"
    directory = root / "fictional-age"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\nname: fictional-age\ndescription: Fictional age fixture.\n---\n"
    )
    birth = [1_600_000_000.0]
    # Controlled OS birth-time evidence works on platforms without st_birthtime.
    monkeypatch.setattr(inventory_catalog, "_birth", lambda _info: birth[0])
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "session.jsonl").write_text(json.dumps(header()) + "\n")
    snapshot = Snapshot(
        tmp_path / "binding.json",
        harness="omp",
        roots=[logs],
        as_of=CLOCK,
        window_days=90,
    )
    initial = load_inventory("omp", key=snapshot.key, skill_roots=[root])
    snapshot.bind_inventory(initial.integrity)
    for frozen in snapshot.files:
        list(snapshot.records(frozen))
    birth[0] = 1_700_000_000.0
    changed = load_inventory("omp", key=snapshot.key, skill_roots=[root])
    assert changed.entries[0].installed_at != initial.entries[0].installed_at
    assert snapshot.finish(changed.integrity)["valid"] is False
    assert snapshot.issues["inventory_drift"] == 1


def test_unclassifiable_directory_entry_blocks_catalog_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skills"
    (root / "fictional-unclassifiable").mkdir(parents=True)

    class DeniedEntry:
        name = "fictional-unclassifiable"

        def is_symlink(self) -> bool:
            raise PermissionError("fictional entry stat denied")

    @contextmanager
    def denied_scan(_path: int) -> Iterator[list[DeniedEntry]]:
        yield [DeniedEntry()]

    monkeypatch.setattr(os, "scandir", denied_scan)
    inventory = load_inventory("omp", key=KEY, skill_roots=[root])
    parsed = parse_file(
        [header()], inventory=inventory, file_key="opaque", cohort_hint="main"
    )
    report, _ = build_report(
        harness="omp",
        parsed=[parsed],
        inventory=inventory,
        as_of=CLOCK,
        window_days=90,
        snapshot={"valid": True, "closed": True},
        input_issues=Counter(),
    )
    assert report["status"] == "incomplete"
    assert report["diagnostics"] == {"catalog_skill_root_unusable": 1}


def test_inventory_root_reads_do_not_invent_a_distinct_skill_name() -> None:
    inventory = Inventory()
    records = [
        header(),
        {
            "type": "message",
            "id": "fictional-inventory-reader",
            "timestamp": "2025-01-01T00:00:02Z",
            "message": {
                "role": "assistant",
                "timestamp": 1735689602000,
                "content": [
                    {
                        "type": "toolCall",
                        "id": f"fictional-call-{index}",
                        "name": "read",
                        "arguments": {"path": path},
                    }
                    for index, path in enumerate(
                        ("skill://", "skill://:10-20", "skill://fictional-skill")
                    )
                ],
            },
        },
    ]
    parsed = parse_file(
        records, inventory=inventory, file_key="opaque", cohort_hint="main"
    )
    report, _ = build_report(
        harness="omp",
        parsed=[parsed],
        inventory=inventory,
        as_of=CLOCK,
        window_days=90,
        snapshot={"valid": True, "closed": True},
        input_issues=Counter(),
    )
    assert report["status"] == "complete"
    events = report["events"]
    assert isinstance(events, dict)
    observed = events["all_observed"]
    assert isinstance(observed, dict)
    assert observed["read_attempts"] == 3
    assert observed["distinct_uri_names"] == 1
    assert observed["distinct_skill_names"] == 1


@pytest.mark.parametrize("rewrite_prefix", [False, True])
def test_initial_hash_instability_cannot_become_a_closed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rewrite_prefix: bool
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    source = logs / "session.jsonl"
    original = (json.dumps(header()) + "\n").encode()
    source.write_bytes(original)
    inode = source.stat().st_ino
    replacement = original.replace(b"fictional-session", b"different-session")
    assert len(replacement) == len(original)
    real_read = os.read
    fired = False

    def mutate_during_baseline(fd: int, size: int) -> bytes:
        nonlocal fired
        if not fired and os.fstat(fd).st_ino == inode:
            fired = True
            if rewrite_prefix:
                source.write_bytes(replacement + b"fictional-append")
            else:
                with source.open("ab") as handle:
                    handle.write(b"fictional-append")
        return real_read(fd, size)

    monkeypatch.setattr(os, "read", mutate_during_baseline)
    snapshot = Snapshot(
        tmp_path / "binding.json",
        harness="omp",
        roots=[logs],
        as_of=CLOCK,
        window_days=90,
    )
    assert fired
    # Removing growth cannot turn an unestablished baseline into verified history.
    with source.open("r+b") as handle:
        handle.truncate(len(original))
    snapshot.bind_inventory("a" * 64)
    for frozen in snapshot.files:
        list(snapshot.records(frozen))
    result = snapshot.finish("a" * 64)
    assert result["valid"] is False
    assert result["closed"] is False
    assert result["initially_unstable_files"] == 1
    assert snapshot.issues["snapshot_initial_unstable"] == 1
    assert snapshot.issues["snapshot_rewritten"] == 0
    assert not (tmp_path / "binding.json").exists()


@pytest.mark.parametrize("missing_header", [False, True])
def test_unvalidated_headers_do_not_count_as_supported_schema_files(
    missing_header: bool,
) -> None:
    records = (
        []
        if missing_header
        else [{"type": "session", "version": 3, "timestamp": "2025-01-01T00:00:00Z"}]
    )
    inventory = Inventory()
    parsed = parse_file(
        records, inventory=inventory, file_key="opaque", cohort_hint="main"
    )
    report, _ = build_report(
        harness="omp",
        parsed=[parsed],
        inventory=inventory,
        as_of=CLOCK,
        window_days=90,
        snapshot={"valid": True, "closed": True},
        input_issues=Counter(),
    )
    assert report["status"] == "incomplete"
    scope = report["scope"]
    assert isinstance(scope, dict)
    assert scope["supported_schema_files"] == 0
    assert scope["validated_input_schema_identities"] == []
