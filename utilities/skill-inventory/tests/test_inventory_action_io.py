"""Private policy input races and captured-parent opportunity boundaries."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import inventory_io
import pytest
from inventory_io import Snapshot, read_private_json, write_private_json
from inventory_types import SchemaError

CLOCK = datetime(2025, 1, 31, tzinfo=UTC)


def test_only_captured_parent_main_files_establish_main_task_groups(
    tmp_path: Path,
) -> None:
    logs = tmp_path / "logs"
    paths = [
        "project/main-a.jsonl",
        "project/main-a/worker-1.jsonl",
        "project/main-a/worker-1/nested-1.jsonl",
        "project/orphan/worker-2.jsonl",
        "project/main-b.jsonl",
        "project/main-b/worker-3.jsonl",
    ]
    for relative in paths:
        target = logs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "type": "session",
                    "version": 3,
                    "id": "fictional-" + target.stem,
                    "timestamp": "2025-01-25T00:00:00Z",
                    "cwd": "/fictional/workspace",
                }
            )
            + "\n"
        )
    snapshot = Snapshot(
        tmp_path / "binding.json",
        harness="omp",
        roots=[logs],
        as_of=CLOCK,
        window_days=90,
    )
    files = {item.path.name: item for item in snapshot.files}
    groups = snapshot.main_task_groups()
    assert groups[files["worker-1.jsonl"].key] == groups[files["nested-1.jsonl"].key]
    assert groups[files["worker-1.jsonl"].key] != groups[files["worker-3.jsonl"].key]
    assert files["worker-2.jsonl"].key not in groups
    assert files["main-a.jsonl"].key not in groups
    assert "main-a" not in json.dumps(groups)


def test_private_policy_edited_during_read_is_refused_not_accepted_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "pins.json"
    write_private_json(target, {"schema_version": 1, "pins": []})
    real_open = inventory_io._open_regular_at

    def changing_open(directory: int, name: str) -> tuple[int, os.stat_result]:
        fd, info = real_open(directory, name)
        before = target.stat()
        target.write_bytes(target.read_bytes().replace(b"1", b"2", 1))
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
        return fd, info

    monkeypatch.setattr(inventory_io, "_open_regular_at", changing_open)
    with pytest.raises(SchemaError) as failure:
        read_private_json(target)
    assert failure.value.code == "private_file_changed"
    assert json.loads(target.read_text())["schema_version"] == 2


def test_private_policy_inside_repository_is_refused_without_modification(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)
    target = repository / "pins.json"
    target.write_text('{"schema_version":1,"pins":[]}')
    target.chmod(0o600)
    before = target.read_bytes()
    with pytest.raises(SchemaError) as failure:
        read_private_json(target)
    assert str(target) not in str(failure.value)
    assert target.read_bytes() == before


def test_publicly_readable_policy_is_not_treated_as_a_private_approval(
    tmp_path: Path,
) -> None:
    target = tmp_path / "pins.json"
    target.write_text('{"schema_version":1,"pins":[]}')
    target.chmod(0o644)
    with pytest.raises(SchemaError) as failure:
        read_private_json(target)
    assert failure.value.code == "private_file_unsafe"
