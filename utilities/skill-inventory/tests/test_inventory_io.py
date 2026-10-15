"""Behavior tests for frozen snapshots and private JSON on fictional logs only.

Every name, line and identifier below is invented. Assertions use counts, anonymous
issue codes, validity and file state, never wording of the implementation.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import inventory_io
import pytest
from inventory_io import FrozenFile, Snapshot, cohort_hint, write_private_json
from inventory_types import SchemaError

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)
INTEGRITY = "a" * 64
OTHER_INTEGRITY = "b" * 64


def encode(line: object) -> bytes:
    if isinstance(line, bytes):
        return line
    if isinstance(line, str):
        return line.encode() + b"\n"
    return json.dumps(line).encode() + b"\n"


class World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.logs = root / "logs"
        self.logs.mkdir()
        self.private = root / "private"
        self.private.mkdir()
        self.private.chmod(0o700)
        self.binding = self.private / "binding.json"

    def write(self, relative: str, *lines: object) -> Path:
        path = self.logs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(encode(line) for line in lines))
        return path

    def snapshot(
        self,
        *,
        harness: Any = "omp",
        roots: list[Path] | None = None,
        as_of: datetime = AS_OF,
        window_days: int = 90,
    ) -> Snapshot:
        return Snapshot(
            self.binding,
            harness=harness,
            roots=[self.logs] if roots is None else roots,
            as_of=as_of,
            window_days=window_days,
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def drain(snapshot: Snapshot) -> list[dict[str, object]]:
    return [record for file in snapshot.files for record in snapshot.records(file)]


def run(
    world: World, integrity: str = INTEGRITY
) -> tuple[Snapshot, list[dict[str, object]], dict[str, object]]:
    """Capture when no binding exists, replay otherwise; always read every file."""
    snapshot = world.snapshot()
    snapshot.bind_inventory(integrity)
    records = drain(snapshot)
    return snapshot, records, snapshot.finish(integrity)


def code_of(error: pytest.ExceptionInfo[SchemaError]) -> str:
    return error.value.code


def edit_bytes(path: Path, old: bytes, new: bytes) -> None:
    """Change content without changing length."""
    assert len(old) == len(new)
    data = path.read_bytes()
    assert old in data
    path.write_bytes(data.replace(old, new, 1))


# --------------------------------------------------------------------------- freezing


def test_capture_freezes_sorted_files_with_hierarchy_cohorts(world: World) -> None:
    names = [
        "p1/a.jsonl",
        "p1/s/b.jsonl",
        "p1/s/n/c.jsonl",
        "flat.jsonl",
        "p1/s/n/d/e.jsonl",
    ]
    for index, name in enumerate(names):
        world.write(name, {"type": "event", "n": index})
    world.write("p1/notes.txt", "not a log")

    snapshot, records, meta = run(world)

    root = Path(os.path.realpath(world.logs))
    assert [file.path.relative_to(root).as_posix() for file in snapshot.files] == [
        "flat.jsonl",
        "p1/a.jsonl",
        "p1/s/b.jsonl",
        "p1/s/n/c.jsonl",
        "p1/s/n/d/e.jsonl",
    ]
    assert [file.cohort for file in snapshot.files] == [
        "unknown",
        "main",
        "sub",
        "nested",
        "unknown",
    ]
    assert [file.size for file in snapshot.files] == [
        file.path.stat().st_size for file in snapshot.files
    ]
    assert len({file.key for file in snapshot.files}) == 5
    assert [record["n"] for record in records] == [3, 0, 1, 2, 4]
    assert meta["valid"] is True
    assert meta["closed"] is True
    assert meta["files"] == 5
    assert meta["complete_lines"] == 5
    assert meta["cohorts"] == {"main": 1, "nested": 1, "sub": 1, "unknown": 2}
    assert snapshot.issues == Counter()


def test_cohort_hints_follow_each_harness_hierarchy_only() -> None:
    assert [cohort_hint("omp", depth) for depth in (1, 2, 3, 4, 5)] == [
        "unknown",
        "main",
        "sub",
        "nested",
        "unknown",
    ]
    assert [cohort_hint("claude", depth) for depth in (1, 2, 3, 4, 5)] == [
        "unknown",
        "main",
        "unknown",
        "sub",
        "unknown",
    ]
    assert {cohort_hint("codex", depth) for depth in range(1, 6)} == {"unknown"}


def test_replay_reproduces_frozen_prefix_and_counts_growth_without_reading_it(
    world: World,
) -> None:
    log = world.write("p/s.jsonl", {"type": "a", "n": 1}, {"type": "a", "n": 2})
    first, first_records, first_meta = run(world)
    bound = world.binding.read_bytes()

    again, again_records, again_meta = run(world)

    assert again_records == first_records
    assert again_meta == first_meta
    assert [file.key for file in again.files] == [file.key for file in first.files]
    assert world.binding.read_bytes() == bound

    with log.open("ab") as handle:
        handle.write(encode({"type": "a", "n": 3}))
    world.write("p/other.jsonl", {"type": "a", "n": 9})

    grown, grown_records, grown_meta = run(world)

    assert grown_records == first_records
    assert grown_meta["appended_files"] == 1
    assert grown_meta["new_files"] == 1
    assert grown_meta["valid"] is True
    assert grown_meta["closed"] is False
    assert grown.issues == Counter()
    assert world.binding.read_bytes() == bound


def test_growth_between_freeze_and_finish_is_counted_and_never_read(
    world: World,
) -> None:
    log = world.write("p/s.jsonl", {"type": "a", "n": 1})
    snapshot = world.snapshot()
    snapshot.bind_inventory(INTEGRITY)
    with log.open("ab") as handle:
        handle.write(encode({"type": "a", "n": 2}))

    records = drain(snapshot)
    meta = snapshot.finish(INTEGRITY)

    assert records == [{"type": "a", "n": 1}]
    assert meta["appended_files"] == 1
    assert meta["valid"] is True
    assert meta["closed"] is False
    replayed, replayed_records, _ = run(world)
    assert replayed_records == records
    assert replayed.files[0].size == len(encode({"type": "a", "n": 1}))


def test_incomplete_tail_is_excluded_with_an_explicit_count(world: World) -> None:
    tail = b'{"type":"a","n"'
    log = world.write("p/s.jsonl", {"type": "a", "n": 1}, tail)

    snapshot, records, meta = run(world)

    assert records == [{"type": "a", "n": 1}]
    assert meta["partial_tail_files"] == 1
    assert meta["partial_tail_bytes"] == len(tail)
    assert meta["complete_lines"] == 1
    assert meta["valid"] is True
    assert meta["closed"] is False
    assert snapshot.issues == Counter()

    with log.open("ab") as handle:
        handle.write(b":2}\n")
    _, replayed, replay_meta = run(world)

    assert replayed == records
    assert replay_meta["appended_files"] == 1
    assert replay_meta["partial_tail_files"] == 1


def test_chunk_boundaries_and_overlong_lines_are_bounded(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inventory_io, "CHUNK_BYTES", 7)
    monkeypatch.setattr(inventory_io, "MAX_LINE_BYTES", 64)
    tail = b"y" * 100
    world.write(
        "p/s.jsonl",
        {"n": 1},
        {"pad": "x" * 200},
        {"n": 2},
        tail,
    )

    snapshot, records, meta = run(world)

    assert records == [{"n": 1}, {"n": 2}]
    assert snapshot.issues == Counter({"line_too_long": 1})
    assert meta["complete_lines"] == 3
    assert meta["partial_tail_files"] == 1
    assert meta["partial_tail_bytes"] == len(tail)
    assert meta["valid"] is True


def test_malformed_complete_lines_are_counted_anonymously(world: World) -> None:
    deep = "[" * 100_000 + "]" * 100_000
    world.write(
        "p/s.jsonl",
        {"n": 1},
        "not json at all",
        '{"a": 1, "a": 2}',
        '{"a": NaN}',
        '{"a": 1e999}',
        "[1, 2]",
        b"\xff\xfe\n",
        "",
        deep,
        {"n": 2},
    )

    snapshot, records, meta = run(world)

    assert records == [{"n": 1}, {"n": 2}]
    assert snapshot.issues == Counter(
        {
            "malformed_json": 2,
            "duplicate_json_key": 1,
            "nonfinite_json_constant": 2,
            "record_not_object": 1,
            "invalid_utf8": 1,
            "json_too_deep": 1,
        }
    )
    assert meta["complete_lines"] == 10
    assert meta["valid"] is True


# --------------------------------------------------------------------------- invalidation


def test_prefix_mutation_after_reading_invalidates_capture_and_writes_nothing(
    world: World,
) -> None:
    log = world.write("p/s.jsonl", {"type": "a", "n": 1}, {"type": "a", "n": 2})
    snapshot = world.snapshot()
    snapshot.bind_inventory(INTEGRITY)
    assert len(drain(snapshot)) == 2

    edit_bytes(log, b'"n": 1', b'"n": 7')
    meta = snapshot.finish(INTEGRITY)

    assert meta["valid"] is False
    assert meta["rewritten_files"] == 1
    assert snapshot.issues == Counter({"snapshot_rewritten": 1})
    assert not world.binding.exists()


def test_replacing_a_frozen_file_is_detected_even_with_identical_bytes(
    world: World,
) -> None:
    log = world.write("p/s.jsonl", {"type": "a", "n": 1})
    snapshot = world.snapshot()
    snapshot.bind_inventory(INTEGRITY)

    replacement = log.with_name("s.tmp")
    replacement.write_bytes(log.read_bytes())
    os.replace(replacement, log)
    drain(snapshot)
    meta = snapshot.finish(INTEGRITY)

    assert meta["valid"] is False
    assert snapshot.issues == Counter({"snapshot_rewritten": 1})
    assert not world.binding.exists()


def mutate_rewrite(path: Path) -> None:
    edit_bytes(path, b'"n": 1', b'"n": 7')


def mutate_truncate(path: Path) -> None:
    path.write_bytes(path.read_bytes()[:5])


def mutate_delete(path: Path) -> None:
    path.unlink()


@pytest.mark.parametrize(
    ("mutate", "code", "counter"),
    [
        (mutate_rewrite, "snapshot_rewritten", "rewritten_files"),
        (mutate_truncate, "snapshot_truncated", "truncated_files"),
        (mutate_delete, "snapshot_missing_file", "missing_files"),
    ],
)
def test_changed_snapshots_are_invalid_and_never_refreshed(
    world: World, mutate: Callable[[Path], None], code: str, counter: str
) -> None:
    changed = world.write("p/a.jsonl", {"type": "a", "n": 1}, {"type": "a", "n": 2})
    world.write("p/b.jsonl", {"type": "a", "n": 3})
    run(world)
    bound = world.binding.read_bytes()

    mutate(changed)
    snapshot, _, meta = run(world)

    assert meta["valid"] is False
    assert meta[counter] == 1
    assert snapshot.issues == Counter({code: 1})
    assert world.binding.read_bytes() == bound


def test_unread_files_invalidate_the_snapshot(world: World) -> None:
    world.write("p/a.jsonl", {"type": "a", "n": 1})
    snapshot = world.snapshot()
    snapshot.bind_inventory(INTEGRITY)

    meta = snapshot.finish(INTEGRITY)

    assert meta["valid"] is False
    assert meta["unread_files"] == 1
    assert snapshot.issues == Counter({"snapshot_unread": 1})
    assert not world.binding.exists()


def test_inventory_drift_invalidates_capture_and_replay(world: World) -> None:
    world.write("p/a.jsonl", {"type": "a", "n": 1})

    snapshot = world.snapshot()
    snapshot.bind_inventory(INTEGRITY)
    drain(snapshot)
    meta = snapshot.finish(OTHER_INTEGRITY)
    assert meta["valid"] is False
    assert snapshot.issues == Counter({"inventory_drift": 1})
    assert not world.binding.exists()

    _, _, captured = run(world)
    assert captured["valid"] is True

    bound_changed = world.snapshot()
    bound_changed.bind_inventory(OTHER_INTEGRITY)
    drain(bound_changed)
    assert bound_changed.finish(OTHER_INTEGRITY)["valid"] is False
    assert bound_changed.issues == Counter({"inventory_drift": 1})

    finished_changed = world.snapshot()
    finished_changed.bind_inventory(INTEGRITY)
    drain(finished_changed)
    assert finished_changed.finish(OTHER_INTEGRITY)["valid"] is False
    assert finished_changed.issues == Counter({"inventory_drift": 1})


def test_binding_swapped_during_replay_is_reported(world: World) -> None:
    world.write("p/a.jsonl", {"type": "a", "n": 1})
    run(world)
    snapshot = world.snapshot()
    snapshot.bind_inventory(INTEGRITY)
    drain(snapshot)

    document = json.loads(world.binding.read_text())
    document["window_days"] = 91
    world.binding.write_text(json.dumps(document))
    meta = snapshot.finish(INTEGRITY)

    assert meta["valid"] is False
    assert snapshot.issues == Counter({"snapshot_binding_changed": 1})


def test_lifecycle_misuse_fails_with_fixed_codes(world: World) -> None:
    world.write("p/a.jsonl", {"type": "a", "n": 1})
    snapshot = world.snapshot()
    (file,) = snapshot.files

    with pytest.raises(SchemaError) as unbound:
        snapshot.finish(INTEGRITY)
    assert code_of(unbound) == "inventory_not_bound"

    with pytest.raises(SchemaError) as bad_digest:
        snapshot.bind_inventory("not-a-digest")
    assert code_of(bad_digest) == "invalid_inventory_integrity"

    snapshot.bind_inventory(INTEGRITY)
    with pytest.raises(SchemaError) as rebound:
        snapshot.bind_inventory(OTHER_INTEGRITY)
    assert code_of(rebound) == "inventory_already_bound"

    forged = FrozenFile(file.path, "0" * 32, file.size, file.cohort)
    with pytest.raises(SchemaError) as unknown:
        snapshot.records(forged)
    assert code_of(unknown) == "unknown_snapshot_file"

    list(snapshot.records(file))
    with pytest.raises(SchemaError) as twice:
        snapshot.records(file)
    assert code_of(twice) == "snapshot_file_already_read"

    snapshot.finish(INTEGRITY)
    with pytest.raises(SchemaError) as finished:
        snapshot.finish(INTEGRITY)
    assert code_of(finished) == "snapshot_finished"


# --------------------------------------------------------------------------- discovery


def test_inner_links_and_special_files_are_never_followed(
    world: World, tmp_path: Path
) -> None:
    world.write("real/x.jsonl", {"n": 1})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "y.jsonl").write_bytes(encode({"n": 2}))
    (world.logs / "linkdir").symlink_to(outside, target_is_directory=True)
    (world.logs / "real" / "z.jsonl").symlink_to(outside / "y.jsonl")
    (world.logs / "dangling").symlink_to(tmp_path / "missing")
    os.mkfifo(world.logs / "real" / "pipe.jsonl")

    snapshot, records, meta = run(world)

    assert records == [{"n": 1}]
    assert meta["files"] == 1
    assert snapshot.issues == Counter(
        {"inner_link_skipped": 2, "non_regular_skipped": 1}
    )


def test_overlapping_roots_and_root_links_resolve_once(
    world: World, tmp_path: Path
) -> None:
    world.write("p/a.jsonl", {"n": 1})
    world.write("p/s/b.jsonl", {"n": 2})
    alias = tmp_path / "alias"
    alias.symlink_to(world.logs, target_is_directory=True)

    first = world.snapshot(roots=[world.logs, world.logs / "p", alias])
    first.bind_inventory(INTEGRITY)
    records = drain(first)
    meta = first.finish(INTEGRITY)

    assert {record["n"] for record in records} == {1, 2}
    assert meta["roots"] == 2
    assert meta["duplicate_files"] == 2
    assert first.issues == Counter()

    replayed = world.snapshot(roots=[alias, world.logs / "p", world.logs])
    replayed.bind_inventory(INTEGRITY)
    assert drain(replayed) == records
    assert replayed.finish(INTEGRITY)["valid"] is True


def test_missing_root_and_empty_listing_are_explicit_issues(
    world: World, tmp_path: Path
) -> None:
    snapshot = world.snapshot(roots=[tmp_path / "does-not-exist"])
    snapshot.bind_inventory(INTEGRITY)

    meta = snapshot.finish(INTEGRITY)

    assert snapshot.issues == Counter({"log_root_missing": 1, "no_log_files": 1})
    assert meta["files"] == 0


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"as_of": datetime(2026, 10, 1)}, "invalid_as_of"),
        ({"window_days": 0}, "invalid_window"),
        ({"window_days": True}, "invalid_window"),
        ({"roots": []}, "log_roots_required"),
        ({"harness": "gemini"}, "invalid_harness"),
    ],
)
def test_invalid_arguments_fail_before_any_read(
    world: World, changes: dict[str, Any], code: str
) -> None:
    with pytest.raises(SchemaError) as error:
        world.snapshot(**changes)
    assert code_of(error) == code


# --------------------------------------------------------------------------- binding


def test_binding_and_metadata_hold_no_paths_content_or_raw_hashes(world: World) -> None:
    line = {"type": "event", "text": "fictional-private-sentence"}
    log = world.write("fictional-project-name/fictional-session-id.jsonl", line)
    data = log.read_bytes()

    snapshot, _, meta = run(world)

    binding = world.binding.read_text()
    published = json.dumps(meta)
    needles = [
        "fictional-private-sentence",
        "fictional-project-name",
        "fictional-session-id",
        str(world.root),
        hashlib.sha256(data).hexdigest(),
        hashlib.sha256(data.rstrip(b"\n")).hexdigest(),
    ]
    for needle in needles:
        assert needle not in binding
        assert needle not in published
    assert snapshot.key.hex() not in published
    assert re.search(r"[0-9a-f]{32}", published) is None
    assert stat.S_IMODE(world.binding.stat().st_mode) == 0o600
    assert list(world.private.iterdir()) == [world.binding]


@pytest.mark.parametrize("location", ["repository", "worktree", "package", "log_root"])
def test_binding_placement_outside_repositories_package_and_logs(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    world.write("p/a.jsonl", {"n": 1})
    if location == "repository":
        (tmp_path / "repo" / ".git").mkdir(parents=True)
        (tmp_path / "repo" / "nested").mkdir()
        target = tmp_path / "repo" / "nested" / "binding.json"
        expected = "private_path_in_repository"
    elif location == "worktree":
        (tmp_path / "tree").mkdir()
        (tmp_path / "tree" / ".git").write_text("gitdir: elsewhere\n")
        target = tmp_path / "tree" / "binding.json"
        expected = "private_path_in_repository"
    elif location == "package":
        package = tmp_path / "package"
        (package / "state").mkdir(parents=True)
        monkeypatch.setattr(inventory_io, "PACKAGE_ROOT", package.resolve())
        target = package / "state" / "binding.json"
        expected = "private_path_in_package"
    else:
        target = world.logs / "binding.json"
        expected = "snapshot_binding_in_log_root"

    with pytest.raises(SchemaError) as snapshot_error:
        Snapshot(target, harness="omp", roots=[world.logs], as_of=AS_OF, window_days=90)
    assert code_of(snapshot_error) == expected
    if location != "log_root":
        with pytest.raises(SchemaError) as write_error:
            write_private_json(target, {"n": 1})
        assert code_of(write_error) == expected
    assert not target.exists()


def test_binding_parent_must_exist_and_not_be_writable_by_others(
    world: World, tmp_path: Path
) -> None:
    world.write("p/a.jsonl", {"n": 1})
    with pytest.raises(SchemaError) as missing:
        write_private_json(tmp_path / "absent" / "binding.json", {})
    assert code_of(missing) == "private_parent_missing"

    world.private.chmod(0o770)
    try:
        with pytest.raises(SchemaError) as unsafe:
            world.snapshot()
        assert code_of(unsafe) == "private_parent_unsafe"
    finally:
        world.private.chmod(0o700)


def test_write_private_json_is_exclusive_owner_only_and_never_modifies(
    world: World,
) -> None:
    target = world.private / "report.json"
    write_private_json(target, {"b": 2, "a": [1, {"d": 4, "c": 3}]})

    assert target.read_bytes() == b'{"a":[1,{"c":3,"d":4}],"b":2}\n'
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    inode = target.stat().st_ino

    write_private_json(target, {"a": [1, {"c": 3, "d": 4}], "b": 2})
    assert target.stat().st_ino == inode

    with pytest.raises(SchemaError) as changed:
        write_private_json(target, {"a": 1})
    assert code_of(changed) == "private_file_exists_changed"
    assert target.read_bytes() == b'{"a":[1,{"c":3,"d":4}],"b":2}\n'

    with pytest.raises(SchemaError) as invalid:
        write_private_json(world.private / "nan.json", {"x": float("nan")})
    assert code_of(invalid) == "private_json_invalid"
    assert sorted(path.name for path in world.private.iterdir()) == ["report.json"]


def test_write_private_json_refuses_unsafe_existing_files(
    world: World, tmp_path: Path
) -> None:
    open_file = world.private / "open.json"
    open_file.write_bytes(b"{}\n")
    open_file.chmod(0o644)
    with pytest.raises(SchemaError) as shared:
        write_private_json(open_file, {})
    assert code_of(shared) == "private_file_unsafe"

    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    link = world.private / "link.json"
    link.symlink_to(victim)
    with pytest.raises(SchemaError) as linked:
        write_private_json(link, {})
    assert code_of(linked) == "private_file_unsafe"
    assert victim.read_text() == "keep"


def edit_version(document: dict[str, Any]) -> None:
    document["version"] = 1


def edit_policy(document: dict[str, Any]) -> None:
    document["policy"] = "frozen-complete-jsonl-prefix-v1"


def add_key(document: dict[str, Any]) -> None:
    document["extra"] = 1


def drop_inventory(document: dict[str, Any]) -> None:
    del document["inventory"]


def bad_key(document: dict[str, Any]) -> None:
    document["key"] = "zz"


def bool_window(document: dict[str, Any]) -> None:
    document["window_days"] = True


def grow_size(document: dict[str, Any]) -> None:
    document["files"][0]["size"] += 1


def switch_harness(document: dict[str, Any]) -> None:
    document["harness"] = "claude"


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (edit_version, "snapshot_binding_schema"),
        (edit_policy, "snapshot_binding_schema"),
        (add_key, "snapshot_binding_schema"),
        (drop_inventory, "snapshot_binding_schema"),
        (bad_key, "snapshot_binding_schema"),
        (bool_window, "snapshot_binding_schema"),
        (grow_size, "snapshot_binding_corrupt"),
        (switch_harness, "snapshot_binding_corrupt"),
    ],
)
def test_binding_schema_and_seal_mismatches_are_rejected(
    world: World, edit: Callable[[dict[str, Any]], None], code: str
) -> None:
    world.write("p/a.jsonl", {"n": 1})
    run(world)
    document = json.loads(world.binding.read_text())
    edit(document)
    world.binding.write_text(json.dumps(document))

    with pytest.raises(SchemaError) as error:
        world.snapshot()
    assert code_of(error) == code


@pytest.mark.parametrize("text", ["not json", '{"version": 1, "version": 1}', "[]", ""])
def test_unparseable_bindings_are_schema_errors(world: World, text: str) -> None:
    world.write("p/a.jsonl", {"n": 1})
    world.binding.write_text(text)
    world.binding.chmod(0o600)

    with pytest.raises(SchemaError) as error:
        world.snapshot()
    assert code_of(error) == "snapshot_binding_schema"


def test_group_readable_binding_is_refused(world: World) -> None:
    world.write("p/a.jsonl", {"n": 1})
    run(world)
    world.binding.chmod(0o640)

    with pytest.raises(SchemaError) as error:
        world.snapshot()
    assert code_of(error) == "private_file_unsafe"


def test_replay_requires_the_bound_policy_harness_and_roots(
    world: World, tmp_path: Path
) -> None:
    world.write("p/a.jsonl", {"n": 1})
    run(world)
    other_root = tmp_path / "other"
    other_root.mkdir()

    cases: list[tuple[dict[str, Any], str]] = [
        ({"as_of": datetime(2026, 10, 2, tzinfo=UTC)}, "snapshot_policy_mismatch"),
        ({"window_days": 30}, "snapshot_policy_mismatch"),
        ({"harness": "claude"}, "snapshot_harness_mismatch"),
        ({"roots": [other_root]}, "snapshot_roots_mismatch"),
        ({"roots": [world.logs, other_root]}, "snapshot_roots_mismatch"),
    ]
    for changes, code in cases:
        with pytest.raises(SchemaError) as error:
            world.snapshot(**changes)
        assert code_of(error) == code

    offset = timezone(timedelta(hours=5, minutes=30))
    equivalent = world.snapshot(as_of=datetime(2026, 10, 1, 5, 30, tzinfo=offset))
    assert len(equivalent.files) == 1


# --------------------------------------------------------------------------- descriptor access


def canonical(path: Path) -> Path:
    return Path(os.path.realpath(path))


def test_open_directory_walks_canonical_paths_without_following_links(
    tmp_path: Path,
) -> None:
    base = canonical(tmp_path)
    (base / "real" / "inner").mkdir(parents=True)
    (base / "real" / "file.txt").write_bytes(b"x")
    (base / "alias").symlink_to(base / "real", target_is_directory=True)

    fd = inventory_io.open_directory(base / "real" / "inner")
    try:
        opened = os.fstat(fd)
    finally:
        os.close(fd)
    expected = (base / "real" / "inner").stat()
    assert (opened.st_dev, opened.st_ino) == (expected.st_dev, expected.st_ino)

    for refused in (
        base / "alias",
        base / "alias" / "inner",
        base / "real" / ".." / "real",
        base / "real" / "file.txt",
        base / "missing",
    ):
        with pytest.raises(OSError):
            inventory_io.open_directory(refused)
    with pytest.raises(OSError) as relative:
        inventory_io.open_directory("real/inner")
    assert relative.value.errno == errno.EINVAL


def test_open_regular_refuses_links_special_files_and_linked_parents(
    tmp_path: Path,
) -> None:
    base = canonical(tmp_path)
    (base / "dir").mkdir()
    target = base / "dir" / "file.jsonl"
    target.write_bytes(b"x\n")
    (base / "dir" / "link.jsonl").symlink_to(target)
    (base / "alias").symlink_to(base / "dir", target_is_directory=True)
    os.mkfifo(base / "dir" / "pipe.jsonl")

    fd, info = inventory_io.open_regular(target)
    os.close(fd)
    assert stat.S_ISREG(info.st_mode)

    for refused in (
        base / "dir" / "link.jsonl",
        base / "alias" / "file.jsonl",
        base / "dir" / "pipe.jsonl",
        base / "dir",
        base / "dir" / "absent.jsonl",
    ):
        with pytest.raises(OSError):
            inventory_io.open_regular(refused)


def hook_first_open(
    monkeypatch: pytest.MonkeyPatch, path: Path, action: Callable[[Path], None]
) -> None:
    """Run ``action`` once, immediately before the first descriptor open of ``path``."""
    real_open_regular = inventory_io.open_regular
    target = os.fsencode(canonical(path))
    fired: list[bool] = []

    def hooked(candidate: Path | str) -> Any:
        if not fired and os.fsencode(candidate) == target:
            fired.append(True)
            action(path)
        return real_open_regular(candidate)

    monkeypatch.setattr(inventory_io, "open_regular", hooked)


def deny_listing(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    info = directory.stat()
    target = (info.st_dev, info.st_ino)
    real_scandir = os.scandir

    def guarded(path: Any = ".") -> Any:
        if isinstance(path, int):
            opened = os.fstat(path)
            if (opened.st_dev, opened.st_ino) == target:
                raise PermissionError("fictional denied directory")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", guarded)


def test_rewrite_between_discovery_and_baseline_invalidates_capture(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = world.write("p/s.jsonl", {"type": "a", "n": 1})
    original = log.stat()

    def rewrite(path: Path) -> None:
        edit_bytes(path, b'"n": 1', b'"n": 7')
        # A distinct, deterministic modification time on coarse-clock filesystems.
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 5_000_000_000))

    hook_first_open(monkeypatch, log, rewrite)
    snapshot = world.snapshot()
    snapshot.bind_inventory(INTEGRITY)

    assert drain(snapshot) == []
    meta = snapshot.finish(INTEGRITY)

    assert meta["valid"] is False
    assert not world.binding.exists()


def test_unreadable_directory_in_the_initial_pass_invalidates_capture(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.write("p/a.jsonl", {"n": 1})
    locked = world.logs / "locked"
    locked.mkdir()
    deny_listing(monkeypatch, locked)
    snapshot = world.snapshot()
    snapshot.bind_inventory(INTEGRITY)
    assert drain(snapshot) == [{"n": 1}]
    monkeypatch.undo()

    meta = snapshot.finish(INTEGRITY)

    assert meta["valid"] is False
    assert meta["closed"] is False
    assert snapshot.issues == Counter({"log_dir_unreadable": 1})
    assert not world.binding.exists()


def test_swapped_root_ancestor_is_not_followed_by_final_discovery(
    world: World, tmp_path: Path
) -> None:
    outer = tmp_path / "outer"
    (outer / "logs" / "p").mkdir(parents=True)
    (outer / "logs" / "p" / "a.jsonl").write_bytes(encode({"n": 1}))
    copy = tmp_path / "copy"
    shutil.copytree(outer, copy)
    snapshot = world.snapshot(roots=[outer / "logs"])
    snapshot.bind_inventory(INTEGRITY)
    assert drain(snapshot) == [{"n": 1}]

    outer.rename(tmp_path / "preserved")
    outer.symlink_to(copy, target_is_directory=True)
    meta = snapshot.finish(INTEGRITY)

    assert meta["valid"] is False
    assert meta["closed"] is False
    assert meta["missing_files"] == 1
    assert snapshot.issues["log_root_unusable"] == 1
    assert not world.binding.exists()


@pytest.mark.parametrize(
    ("mode", "accepted"),
    [(0o770, False), (0o707, False), (0o1777, True)],
)
def test_private_placement_vets_every_ancestor_not_only_the_parent(
    tmp_path: Path, mode: int, accepted: bool
) -> None:
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    inner.chmod(0o700)
    outer.chmod(mode)
    target = inner / "report.json"
    try:
        if accepted:
            write_private_json(target, {"n": 1})
            assert target.read_bytes() == b'{"n":1}\n'
        else:
            with pytest.raises(SchemaError) as error:
                write_private_json(target, {"n": 1})
            assert code_of(error) == "private_parent_unsafe"
            assert not target.exists()
    finally:
        outer.chmod(0o700)


def test_binding_parent_swapped_before_finish_is_never_written_through(
    world: World,
) -> None:
    world.write("p/a.jsonl", {"n": 1})
    snapshot = world.snapshot()
    snapshot.bind_inventory(INTEGRITY)
    drain(snapshot)

    preserved = world.root / "preserved-private"
    world.private.rename(preserved)
    world.private.mkdir(mode=0o700)
    with pytest.raises(SchemaError) as error:
        snapshot.finish(INTEGRITY)

    assert code_of(error) == "private_parent_changed"
    assert list(world.private.iterdir()) == []
    assert list(preserved.iterdir()) == []


# --------------------------------------------------------------------------- versioning


@pytest.mark.parametrize("legacy_version", [1, 2])
def test_binding_from_the_previous_schema_is_rejected_not_migrated(
    world: World,
    legacy_version: int,
) -> None:
    world.write("p/a.jsonl", {"n": 1})
    run(world)
    document = json.loads(world.binding.read_text())
    legacy = dict(document)
    legacy["version"] = legacy_version
    if legacy_version == 1:
        del legacy["policy"]
    else:
        legacy["policy"] = "frozen-complete-jsonl-prefix-v2"
    world.binding.write_text(json.dumps(legacy))

    with pytest.raises(SchemaError) as error:
        world.snapshot()

    assert code_of(error) == "snapshot_binding_schema"
    assert json.loads(world.binding.read_text()) == legacy
