"""Reversible, journaled archive and restore of generated OMP managed skills.

The only mutation this module performs is a same-filesystem directory rename between

    <home>/.omp/agent/managed-skills/<name>
    <home>/.omp/agent/skill-inventory-archive/<run-id>/skills/<name>

Nothing is ever deleted, rewritten or chmod-ed, no harness configuration is read or
changed, and no other tree is touched. ``archive`` needs an exact reviewed proposal,
a freshly rebuilt identical proposal, a matching approval document and the operator's
attestations (auto-learning disabled, writers stopped, baseline and coverage reviewed,
ordinary sessions attested). ``restore`` and its ``list`` form work from the private
``manifest.json`` at the fixed run root.

Safety model, in the order it is enforced:

* roots are fixed under the home directory; every component is opened with
  ``O_NOFOLLOW`` through descriptors, so a symlinked root or ancestor is refused, and
  roots must be owned by the effective user and not group- or world-writable (the
  archive root, run roots and skills directory must be owner-only);
* the whole managed tree is scanned (every byte and mode) and must equal the approved
  proposal immediately before and after each rename, so unselected files are
  revalidated and any concurrent writer stops the batch;
* the manifest is the write-ahead journal: it is created exclusively, fsynced and
  renamed into place with every item ``planned`` before the first move, and later
  state changes are exclusive-temp + fsync + atomic replace + directory fsync;
* a crash between a rename and its journal record is reconciled from filesystem
  evidence (in memory for ``list`` and dry-run, persisted by ``restore --apply``);
* an existing live entry is never overwritten: identical bytes are recorded as
  externally restored, different bytes are a conflict that keeps both copies.

Limits worth stating plainly: the manifest and journal carry an integrity digest that
catches accidental damage and naive edits, not a same-user adversary who recomputes it;
the ``flock`` on the archive root serializes this utility only and is not a harness
writer lock; a directory rename cannot be made batch-atomic. Individual moves use
native atomic no-replace rename, including empty destinations, with no unsafe fallback.
Public reports contain aggregate counts, fixed diagnostics, generated run ids and dates
only; installed names, hashes and paths stay in the private manifest.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import re
import secrets
import stat
import sys
from collections import Counter
from collections.abc import Callable
from contextlib import ExitStack, suppress
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import cast

from inventory_io import (
    MAX_PRIVATE_BYTES,
    canonical_json,
    is_hex_digest,
    open_directory,
    private_parent,
    read_private_json,
    write_private_json,
)
from inventory_policy import (
    APPROVAL_POLICY,
    TreeState,
    canonical_digest,
    scan_tree_fd,
    subtree_state,
    tree_document,
    tree_from_document,
    validate_proposal,
    without_children,
)
from inventory_types import SchemaError, as_int, as_list, as_object, as_string, utc_time

__all__ = ["archive", "restore"]

SCHEMA_VERSION = 1
MANIFEST_KIND = "skill-inventory-archive-manifest"
MANIFEST_NAME = "manifest.json"
SKILLS_NAME = "skills"
LOCK_NAME = ".lock"
MANAGED_PARTS = (".omp", "agent", "managed-skills")
ARCHIVE_PARTS = (".omp", "agent", "skill-inventory-archive")
MANAGED_LABEL = "/".join(MANAGED_PARTS)
ARCHIVE_LABEL = "/".join(ARCHIVE_PARTS)

MAX_BATCH = as_int(APPROVAL_POLICY["max_batch"])
DWELL_DAYS = as_int(APPROVAL_POLICY["dwell_days"])
DWELL_SESSIONS = as_int(APPROVAL_POLICY["dwell_sessions"])
QUARANTINE_DAYS = as_int(APPROVAL_POLICY["quarantine_days"])

PLANNED = "planned"
MOVED = "moved"
RESTORED = "restored"
EXTERNAL = "externally_restored"
CONFLICT = "conflict"
_STATES = (PLANNED, MOVED, RESTORED, EXTERNAL, CONFLICT)
_TERMINAL = frozenset({RESTORED, EXTERNAL})
_CONFLICT_REASONS = ("live_differs", "archive_missing", "archive_differs")
_OCCUPIED = (errno.ENOTEMPTY, errno.EEXIST, errno.ENOTDIR, errno.EISDIR)

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_TEMP_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_LOCK_FLAGS = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC

_RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_STAGE = re.compile(r"^\.stage-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_TEMP = re.compile(r"^\.manifest-[0-9a-f]{16}\.tmp$")
_STAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_DAY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

_ATTESTATIONS = (
    "auto_learning_disabled",
    "writers_stopped",
    "coverage_reviewed",
    "ordinary_sessions_attested",
    "baseline_reviewed",
)
_APPROVAL_KEYS = frozenset(
    {"schema_version", "proposal_digest", "items", *_ATTESTATIONS}
)
_POLICY_INPUTS = ("pins_digest", "attestations_digest", "references_digest")
_BASE_KEYS = (
    "schema_version",
    "kind",
    "operation",
    "harness",
    "run_id",
    "created_utc",
    "roots",
    "binding",
    "attestations",
    "batch",
    "source_tree",
)
_MANIFEST_KEYS = frozenset(
    {*_BASE_KEYS, "plan_digest", "items", "generation", "updated_utc", "integrity"}
)
_BINDING_KEYS = frozenset(
    {
        "proposal_digest",
        "approval_digest",
        "snapshot_digest",
        "policy_digest",
        "source_root_digest",
        "as_of_utc",
        "window_days",
        "policy_inputs",
    }
)
_BATCH_KEYS = frozenset(
    {"index", "max_batch", "dwell_days", "dwell_sessions", "quarantine_days"}
)
_ITEM_KEYS = frozenset(
    {"name", "tree_digest", "state", "moved_utc", "restored_utc", "conflict_reason"}
)
_RESTORE_COUNTS = (
    "selected",
    "restored",
    "would_restore",
    "in_place",
    "externally_restored",
    "already_restored",
    "conflict",
    "unselected",
)


# --------------------------------------------------------------------------- time


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _second(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(microsecond=0)


def _stamp(moment: datetime) -> str:
    return _second(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_stamp(value: object, code: str) -> datetime:
    text = as_string(value, code)
    if not _STAMP.fullmatch(text):
        raise SchemaError(code)
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise SchemaError(code) from None


def _read_optional_stamp(value: object, code: str) -> datetime | None:
    return None if value is None else _read_stamp(value, code)


def _read_day(value: object, code: str) -> date:
    text = as_string(value, code)
    if not _DAY.fullmatch(text):
        raise SchemaError(code)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise SchemaError(code) from None


# --------------------------------------------------------------------------- reports


def _report(
    operation: str,
    mode: str,
    status: str,
    outcome: str,
    *,
    counts: dict[str, int] | None = None,
    diagnostics: dict[str, int] | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "mode": mode,
        "status": status,
        "outcome": outcome,
        "counts": dict(counts or {}),
        "diagnostics": dict(diagnostics or {}),
    }
    report.update(extra or {})
    return report


def _refused(operation: str, mode: str, code: str) -> dict[str, object]:
    return _report(operation, mode, "refused", "refused", diagnostics={code: 1})


# --------------------------------------------------------------------------- paths and descriptors


def _home(home: Path | None) -> Path:
    try:
        path = Path.home() if home is None else Path(home)
    except RuntimeError:
        raise SchemaError("home_invalid") from None
    if not path.is_absolute() or str(path) != os.path.normpath(path):
        raise SchemaError("home_invalid")
    return path


def _valid_name(value: object) -> bool:
    if not isinstance(value, str) or not 0 < len(value) <= 200:
        return False
    if value.startswith(".") or any(
        ch in "/\\" or ord(ch) < 32 or ord(ch) == 127 for ch in value
    ):
        return False
    return len(os.fsencode(value)) <= 255


def _identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _fsync(fd: int) -> None:
    os.fsync(fd)
    full = getattr(fcntl, "F_FULLFSYNC", None)
    if full is not None:
        with suppress(OSError):
            fcntl.fcntl(fd, full)


@cache
def _exclusive_renamer() -> tuple[Callable[[int, bytes, int, bytes, int], int], int]:
    """Resolve the platform's atomic no-replace primitive; never emulate it."""
    if sys.platform == "darwin":
        symbol, flag = "renameatx_np", 0x00000004  # Darwin RENAME_EXCL.
    elif sys.platform == "linux":
        symbol, flag = "renameat2", 1  # Linux RENAME_NOREPLACE.
    else:
        raise SchemaError("exclusive_rename_unavailable")
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, symbol, None)
    if function is None:
        raise SchemaError("exclusive_rename_unavailable")
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    return cast(Callable[[int, bytes, int, bytes, int], int], function), flag


def _rename_at(src_fd: int, src: str, dst_fd: int, dst: str) -> None:
    rename, flag = _exclusive_renamer()
    if rename(src_fd, os.fsencode(src), dst_fd, os.fsencode(dst), flag) != 0:
        code = ctypes.get_errno()
        if code in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.ENOTSUP}:
            raise SchemaError("exclusive_rename_unavailable")
        raise OSError(code, os.strerror(code))


def _vet(fd: int, *, private: bool) -> None:
    """Owned by the effective user, never group/world writable; owner-only when private."""
    info = os.fstat(fd)
    mask = 0o077 if private else 0o022
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & mask
    ):
        raise SchemaError("root_unsafe")


def _open_vetted(path: Path, *, private: bool) -> int | None:
    """Open one canonical directory with no link followed; None only when it is absent."""
    try:
        fd = open_directory(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise SchemaError("root_unsafe") from None
    try:
        _vet(fd, private=private)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_below(
    home: Path, parts: tuple[str, ...], *, private: bool = False
) -> int | None:
    """Open ``home/parts`` vetting home and every component; None when any is absent."""
    paths = [home]
    for part in parts:
        paths.append(paths[-1] / part)
    held: int | None = None
    try:
        for index, path in enumerate(paths):
            fd = _open_vetted(path, private=private and index == len(paths) - 1)
            if fd is None:
                if held is not None:
                    os.close(held)
                return None
            if held is not None:
                os.close(held)
            held = fd
    except BaseException:
        if held is not None:
            os.close(held)
        raise
    return held


def _ensure_archive(home: Path, agent_fd: int) -> int:
    fd = _open_below(home, ARCHIVE_PARTS, private=True)
    if fd is not None:
        return fd
    os.mkdir(ARCHIVE_PARTS[-1], 0o700, dir_fd=agent_fd)
    _fsync(agent_fd)
    fd = _open_below(home, ARCHIVE_PARTS, private=True)
    if fd is None:
        raise SchemaError("root_unsafe")
    return fd


def _lock(archive_fd: int) -> int:
    """Exclusive, non-blocking utility lock; it serializes this tool, not the harness."""
    try:
        fd = os.open(LOCK_NAME, _LOCK_FLAGS, 0o600, dir_fd=archive_fd)
    except OSError:
        raise SchemaError("lock_unsafe") from None
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
        ):
            raise SchemaError("lock_unsafe")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SchemaError("archive_locked") from None
    except BaseException:
        os.close(fd)
        raise
    return fd


def _absent(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    return False


def _scan_at(parent_fd: int, name: str) -> TreeState | None:
    """Scan one child directory by descriptor; None when absent, SchemaError when unsafe."""
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise SchemaError("entry_unsafe") from None
    try:
        return scan_tree_fd(fd)
    finally:
        os.close(fd)


def _classify(parent_fd: int | None, name: str, expected: TreeState) -> str:
    """Filesystem evidence about one entry: absent, match (exact bytes and modes) or differs."""
    if parent_fd is None:
        return "absent"
    try:
        state = _scan_at(parent_fd, name)
    except (SchemaError, OSError):
        return "differs"
    if state is None:
        return "absent"
    return "match" if state.digest == expected.digest else "differs"


# --------------------------------------------------------------------------- manifest


@dataclass
class _Item:
    name: str
    tree_digest: str
    state: str
    moved: datetime | None
    restored: datetime | None
    reason: str | None


@dataclass
class _Manifest:
    run_id: str
    created: datetime
    updated: datetime
    generation: int
    base: dict[str, object]
    source: TreeState
    items: list[_Item]
    index: int


def _exact(
    value: object, keys: frozenset[str], code: str = "manifest_invalid"
) -> dict[str, object]:
    obj = as_object(value, code)
    if set(obj) != keys:
        raise SchemaError(code)
    return obj


def _item_document(item: _Item) -> dict[str, object]:
    return {
        "name": item.name,
        "tree_digest": item.tree_digest,
        "state": item.state,
        "moved_utc": None if item.moved is None else _stamp(item.moved),
        "restored_utc": None if item.restored is None else _stamp(item.restored),
        "conflict_reason": item.reason,
    }


def _plan_digest(base: dict[str, object], items: list[_Item]) -> str:
    return canonical_digest(
        {
            **{key: base[key] for key in _BASE_KEYS},
            "items": [[item.name, item.tree_digest] for item in items],
        }
    )


def _document(manifest: _Manifest) -> dict[str, object]:
    document: dict[str, object] = {
        **manifest.base,
        "items": [_item_document(item) for item in manifest.items],
        "generation": manifest.generation,
        "updated_utc": _stamp(manifest.updated),
    }
    document["integrity"] = canonical_digest(document)
    return document


def _new_manifest(
    *,
    run_id: str,
    now: datetime,
    binding: dict[str, object],
    index: int,
    source: TreeState,
    items: list[_Item],
) -> _Manifest:
    base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "operation": "archive",
        "harness": "omp",
        "run_id": run_id,
        "created_utc": _stamp(now),
        "roots": {"managed": MANAGED_LABEL, "archive": ARCHIVE_LABEL},
        "binding": binding,
        "attestations": dict.fromkeys(_ATTESTATIONS, True),
        "batch": {
            "index": index,
            "max_batch": MAX_BATCH,
            "dwell_days": DWELL_DAYS,
            "dwell_sessions": DWELL_SESSIONS,
            "quarantine_days": QUARANTINE_DAYS,
        },
        "source_tree": tree_document(source),
    }
    base["plan_digest"] = _plan_digest(base, items)
    manifest = _Manifest(
        run_id=run_id,
        created=_second(now),
        updated=_second(now),
        generation=1,
        base=base,
        source=source,
        items=items,
        index=index,
    )
    if len(canonical_json(_document(manifest))) > MAX_PRIVATE_BYTES:
        raise SchemaError("manifest_too_large")
    return manifest


def _parse_binding(value: object) -> dict[str, object]:
    binding = _exact(value, _BINDING_KEYS)
    for key in (
        "proposal_digest",
        "approval_digest",
        "snapshot_digest",
        "policy_digest",
    ):
        if not is_hex_digest(binding[key]):
            raise SchemaError("manifest_invalid")
    if not is_hex_digest(binding["source_root_digest"]):
        raise SchemaError("manifest_invalid")
    _read_stamp(binding["as_of_utc"], "manifest_invalid")
    as_int(binding["window_days"], "manifest_invalid")
    inputs = _exact(binding["policy_inputs"], frozenset(_POLICY_INPUTS))
    if not all(is_hex_digest(inputs[key]) for key in _POLICY_INPUTS):
        raise SchemaError("manifest_invalid")
    return binding


def _parse_item(raw: object, source: TreeState) -> _Item:
    entry = _exact(raw, _ITEM_KEYS)
    name = entry["name"]
    if not _valid_name(name) or not isinstance(name, str):
        raise SchemaError("manifest_invalid")
    digest = entry["tree_digest"]
    if not is_hex_digest(digest) or digest != subtree_state(source, name).digest:
        raise SchemaError("manifest_invalid")
    state = entry["state"]
    if state not in _STATES or not isinstance(state, str):
        raise SchemaError("manifest_invalid")
    moved = _read_optional_stamp(entry["moved_utc"], "manifest_invalid")
    restored = _read_optional_stamp(entry["restored_utc"], "manifest_invalid")
    reason = entry["conflict_reason"]
    if reason is not None and reason not in _CONFLICT_REASONS:
        raise SchemaError("manifest_invalid")
    consistent = {
        PLANNED: moved is None and restored is None and reason is None,
        MOVED: moved is not None and restored is None and reason is None,
        RESTORED: restored is not None and reason is None,
        EXTERNAL: restored is not None and reason is None,
        CONFLICT: restored is None and reason is not None,
    }[state]
    if not consistent:
        raise SchemaError("manifest_invalid")
    return _Item(
        name,
        str(digest),
        state,
        moved,
        restored,
        None if reason is None else str(reason),
    )


def _parse_manifest(value: dict[str, object], run_id: str) -> _Manifest:
    version = value.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise SchemaError("manifest_schema_unsupported")
    if set(value) != _MANIFEST_KEYS:
        raise SchemaError("manifest_invalid")
    unsealed = {key: item for key, item in value.items() if key != "integrity"}
    if (
        not is_hex_digest(value["integrity"])
        or canonical_digest(unsealed) != value["integrity"]
    ):
        raise SchemaError("manifest_integrity")
    if (
        value["kind"] != MANIFEST_KIND
        or value["operation"] != "archive"
        or value["harness"] != "omp"
        or value["run_id"] != run_id
        or value["roots"] != {"managed": MANAGED_LABEL, "archive": ARCHIVE_LABEL}
    ):
        raise SchemaError("manifest_invalid")
    created = _read_stamp(value["created_utc"], "manifest_invalid")
    updated = _read_stamp(value["updated_utc"], "manifest_invalid")
    generation = as_int(value["generation"], "manifest_invalid")
    if generation < 1 or updated < created:
        raise SchemaError("manifest_invalid")
    _parse_binding(value["binding"])
    if value["attestations"] != dict.fromkeys(_ATTESTATIONS, True):
        raise SchemaError("manifest_invalid")
    batch = _exact(value["batch"], _BATCH_KEYS)
    index = as_int(batch["index"], "manifest_invalid")
    if index < 1 or any(
        as_int(batch[key], "manifest_invalid") < 1 for key in _BATCH_KEYS
    ):
        raise SchemaError("manifest_invalid")
    source = tree_from_document(value["source_tree"])
    raw_items = as_list(value["items"], "manifest_invalid")
    items = [_parse_item(raw, source) for raw in raw_items]
    names = [item.name for item in items]
    if not items or names != sorted(set(names)):
        raise SchemaError("manifest_invalid")
    base = {key: value[key] for key in _BASE_KEYS}
    if value["plan_digest"] != _plan_digest(base, items):
        raise SchemaError("manifest_integrity")
    base["plan_digest"] = value["plan_digest"]
    return _Manifest(run_id, created, updated, generation, base, source, items, index)


def _load_run(archive_fd: int, archive_path: Path, run_id: str) -> _Manifest:
    """Read one run's manifest through the private boundary; any damage is a fixed refusal."""
    try:
        run_fd = os.open(run_id, _DIR_FLAGS, dir_fd=archive_fd)
    except OSError:
        raise SchemaError("run_unsafe") from None
    try:
        _vet(run_fd, private=True)
        names = set(os.listdir(run_fd))
        if MANIFEST_NAME not in names:
            raise SchemaError("manifest_missing")
        if any(
            name not in (MANIFEST_NAME, SKILLS_NAME) and not _TEMP.fullmatch(name)
            for name in names
        ):
            raise SchemaError("run_unexpected_entry")
        path = archive_path / run_id / MANIFEST_NAME
        with private_parent(path, pinned=_identity(run_fd)):
            document = read_private_json(path)
    finally:
        os.close(run_fd)
    return _parse_manifest(document, run_id)


def _replace_manifest(
    run_path: Path, identity: tuple[int, int], document: dict[str, object]
) -> None:
    """Exclusive temp, fsync, atomic replace of a validated existing file, fsync the directory."""
    payload = canonical_json(document)
    if len(payload) > MAX_PRIVATE_BYTES:
        raise SchemaError("manifest_too_large")
    with private_parent(run_path / MANIFEST_NAME, pinned=identity) as parent:
        info = os.stat(parent.name, dir_fd=parent.fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
        ):
            raise SchemaError("private_file_unsafe")
        temporary = f".manifest-{secrets.token_hex(8)}.tmp"
        fd = os.open(temporary, _TEMP_FLAGS, 0o600, dir_fd=parent.fd)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(
                temporary, parent.name, src_dir_fd=parent.fd, dst_dir_fd=parent.fd
            )
        except Exception:
            with suppress(OSError):
                os.unlink(temporary, dir_fd=parent.fd)
            raise
        _fsync(parent.fd)


def _persist(manifest: _Manifest, run_path: Path, identity: tuple[int, int]) -> None:
    manifest.generation += 1
    manifest.updated = _second(_utc_now())
    _replace_manifest(run_path, identity, _document(manifest))


# --------------------------------------------------------------------------- archive history


@dataclass
class _History:
    runs: list[_Manifest]
    unreadable: int
    unexpected: int
    leftovers: int
    codes: Counter[str]


def _scan_archive(archive_fd: int, archive_path: Path) -> _History:
    """Every run's manifest; damage is counted with fixed codes, never skipped silently."""
    history = _History([], 0, 0, 0, Counter())
    for name in sorted(os.listdir(archive_fd)):
        if name == LOCK_NAME:
            continue
        if _STAGE.fullmatch(name):
            history.leftovers += 1
        elif not _RUN_ID.fullmatch(name):
            history.unexpected += 1
            history.codes["archive_root_unexpected"] += 1
        else:
            try:
                history.runs.append(_load_run(archive_fd, archive_path, name))
            except SchemaError as error:
                history.unreadable += 1
                history.codes[error.code] += 1
            except OSError:
                history.unreadable += 1
                history.codes["local_io_error"] += 1
    return history


def _last_move(runs: list[_Manifest]) -> datetime | None:
    stamps = [
        item.moved for run in runs for item in run.items if item.moved is not None
    ]
    return max(stamps) if stamps else None


# --------------------------------------------------------------------------- proposals and approval


@dataclass(frozen=True)
class _Plan:
    proposal: dict[str, object]
    managed: TreeState
    as_of: datetime
    observations: dict[date, int]
    skills: dict[str, dict[str, object]]
    max_batch: int
    dwell_days: int
    dwell_sessions: int


def _actionable(
    saved: dict[str, object], current: dict[str, object], managed_path: Path
) -> _Plan:
    proposal = validate_proposal(saved)
    fresh = validate_proposal(current)
    if proposal != fresh:
        raise SchemaError("proposal_drift")
    if proposal["harness"] != "omp" or proposal["status"] != "complete":
        raise SchemaError("proposal_incomplete")
    scope = as_object(proposal["measurement_scope"], "proposal_incomplete")
    if any(scope.get(key) is not True for key in ("complete", "valid", "closed")):
        raise SchemaError("measurement_incomplete")
    if (
        proposal["managed_root"] != str(managed_path)
        or proposal["managed_tree"] is None
    ):
        raise SchemaError("managed_root_mismatch")
    managed = tree_from_document(proposal["managed_tree"])
    if proposal["source_root_digest"] != managed.digest:
        raise SchemaError("source_digest_mismatch")
    inputs = as_object(proposal["policy_inputs"], "policy_inputs_missing")
    if not all(is_hex_digest(inputs.get(key)) for key in _POLICY_INPUTS):
        raise SchemaError("policy_inputs_missing")
    for key in ("snapshot_digest", "policy_digest", "proposal_digest"):
        if not is_hex_digest(proposal[key]):
            raise SchemaError("proposal_incomplete")
    policy = as_object(proposal["approval_policy"], "approval_policy_invalid")
    skills: dict[str, dict[str, object]] = {}
    for raw in as_list(proposal["skills"], "proposal_incomplete"):
        skill = as_object(raw, "proposal_incomplete")
        name = as_string(skill["name"], "proposal_incomplete")
        # Proposal validation permits duplicate identities only when both are kept.
        # They must not block a distinct, unambiguous approved archive candidate.
        if name in skills:
            continue
        skills[name] = skill
    observations: dict[date, int] = {}
    raw_days = as_object(
        proposal["inventory_observations_by_utc_day"], "observations_invalid"
    )
    for key, count in raw_days.items():
        observations[_read_day(key, "observations_invalid")] = as_int(
            count, "observations_invalid"
        )
    return _Plan(
        proposal=proposal,
        managed=managed,
        as_of=utc_time(proposal["as_of_utc"]),
        observations=observations,
        skills=skills,
        max_batch=min(
            MAX_BATCH, as_int(policy["max_batch"], "approval_policy_invalid")
        ),
        dwell_days=max(
            DWELL_DAYS, as_int(policy["dwell_days"], "approval_policy_invalid")
        ),
        dwell_sessions=max(
            DWELL_SESSIONS, as_int(policy["dwell_sessions"], "approval_policy_invalid")
        ),
    )


def _is_candidate(skill: dict[str, object]) -> bool:
    return (
        skill.get("classification") == "archive_candidate"
        and skill.get("eligible") is True
        and skill.get("generated_only_attested") is True
        and skill.get("never_user_authored_attested") is True
        and skill.get("historical_lineage_attested") is True
        and skill.get("description_only_reviewed") is True
        and skill.get("coverage_still_needed") is False
        and skill.get("periodic_or_incident_workflow") is False
        and is_hex_digest(skill.get("tree_digest"))
    )


def _parse_approval(approval: dict[str, object], plan: _Plan) -> list[tuple[str, str]]:
    """The exact reviewed subset as sorted (name, tree digest) pairs; any deviation refuses."""
    document = _exact(approval, _APPROVAL_KEYS, "approval_schema_invalid")
    version = document["schema_version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise SchemaError("approval_schema_invalid")
    if document["proposal_digest"] != plan.proposal["proposal_digest"]:
        raise SchemaError("approval_digest_mismatch")
    if any(document[key] is not True for key in _ATTESTATIONS):
        raise SchemaError("approval_attestation_missing")
    raw = as_list(document["items"], "approval_schema_invalid")
    if not raw or len(raw) > plan.max_batch:
        raise SchemaError("approval_batch_invalid")
    chosen: dict[str, str] = {}
    for entry in raw:
        item = _exact(
            entry, frozenset({"name", "tree_digest"}), "approval_schema_invalid"
        )
        name, digest = item["name"], item["tree_digest"]
        if (
            not _valid_name(name)
            or not isinstance(name, str)
            or not is_hex_digest(digest)
        ):
            raise SchemaError("approval_item_invalid")
        if name in chosen:
            raise SchemaError("approval_item_duplicate")
        chosen[name] = str(digest)
    for name, digest in chosen.items():
        skill = plan.skills.get(name)
        if skill is None or not _is_candidate(skill):
            raise SchemaError("approval_item_not_eligible")
        if (
            skill["tree_digest"] != digest
            or subtree_state(plan.managed, name).digest != digest
        ):
            raise SchemaError("approval_tree_mismatch")
    return sorted(chosen.items())


def _gate_history(history: _History, plan: _Plan, now: datetime) -> dict[str, int]:
    """Refuse unreadable/unfinished history and enforce the later-batch dwell."""
    if history.unreadable or history.unexpected:
        raise SchemaError("history_unreadable")
    for run in history.runs:
        if any(item.state == PLANNED for item in run.items):
            raise SchemaError("unfinished_run")
        if any(item.state == CONFLICT for item in run.items):
            raise SchemaError("unresolved_conflict")
    stats = {"prior_runs": len(history.runs)}
    last = _last_move(history.runs)
    if last is None:
        return stats
    last_day = last.date()
    elapsed = min((plan.as_of.date() - last_day).days, (now.date() - last_day).days)
    # The move day is partial, so only whole later days count; the as-of day is already
    # bounded by what the proposal observed.
    observed = sum(
        count
        for day, count in plan.observations.items()
        if last_day < day <= plan.as_of.date()
    )
    stats.update(dwell_days_elapsed=max(elapsed, 0), dwell_observations=observed)
    if elapsed < plan.dwell_days:
        raise SchemaError("dwell_days_insufficient")
    if observed < plan.dwell_sessions:
        raise SchemaError("dwell_sessions_insufficient")
    return stats


# --------------------------------------------------------------------------- archive


def archive(
    proposal: dict[str, object],
    current_proposal: dict[str, object],
    approval: dict[str, object] | None,
    *,
    apply: bool,
    home: Path | None = None,
) -> dict[str, object]:
    """Validate, and with ``apply`` move, an approved subset of generated managed skills.

    ``current_proposal`` must be rebuilt by the caller from fresh inputs and be
    identical to the saved ``proposal``. Without ``apply`` nothing is created: no
    directory, lock or manifest. Failures return a ``refused`` or ``incomplete`` report
    with a fixed diagnostic; a simulated or real crash propagates untouched.
    """
    mode = "apply" if apply else "dry_run"
    try:
        return _archive(proposal, current_proposal, approval, apply=apply, home=home)
    except SchemaError as error:
        return _refused("archive", mode, error.code)
    except (OSError, UnicodeError):
        return _refused("archive", mode, "local_io_error")


def _archive(
    proposal: dict[str, object],
    current: dict[str, object],
    approval: dict[str, object] | None,
    *,
    apply: bool,
    home: Path | None,
) -> dict[str, object]:
    mode = "apply" if apply else "dry_run"
    base = _home(home)
    operation = _utc_now()
    now = _second(operation)
    plan = _actionable(proposal, current, base.joinpath(*MANAGED_PARTS))
    # Evidence cannot be aged with an analysis clock ahead of the real one.
    if plan.as_of > operation:
        raise SchemaError("future_evidence_cutoff")
    candidates = sum(1 for skill in plan.skills.values() if _is_candidate(skill))
    if approval is None:
        if apply:
            raise SchemaError("approval_required")
        return _report(
            "archive",
            mode,
            "incomplete",
            "approval_required",
            counts={"archive_candidates": candidates},
            diagnostics={"approval_required": 1},
        )
    chosen = _parse_approval(approval, plan)
    archive_path = base.joinpath(*ARCHIVE_PARTS)
    with ExitStack() as stack:
        agent_fd = _open_below(base, MANAGED_PARTS[:2])
        if agent_fd is None:
            raise SchemaError("managed_root_missing")
        stack.callback(os.close, agent_fd)
        managed_fd = _open_below(base, MANAGED_PARTS)
        if managed_fd is None:
            raise SchemaError("managed_root_missing")
        stack.callback(os.close, managed_fd)
        archive_fd = _open_below(base, ARCHIVE_PARTS, private=True)
        if archive_fd is not None:
            stack.callback(os.close, archive_fd)
        # Everything is checked read-only first, so a refusal leaves no trace; apply then
        # creates the archive root, takes the lock and checks again under it.
        checked = _check(
            plan, chosen, now, agent_fd, managed_fd, archive_fd, archive_path
        )
        counts = {"approved": len(chosen), "archive_candidates": candidates}
        if not apply:
            return _report(
                "archive",
                mode,
                "complete",
                "dry_run_ready",
                counts={**counts, **checked.stats},
            )
        _exclusive_renamer()
        if archive_fd is None:
            archive_fd = _ensure_archive(base, agent_fd)
            stack.callback(os.close, archive_fd)
        stack.callback(os.close, _lock(archive_fd))
        checked = _check(
            plan, chosen, now, agent_fd, managed_fd, archive_fd, archive_path
        )
        return _execute(
            plan=plan,
            checked=checked,
            approval=approval,
            base=base,
            managed_fd=managed_fd,
            archive_fd=archive_fd,
            now=now,
            counts={**counts, **checked.stats},
        )


@dataclass(frozen=True)
class _Checked:
    entries: list[tuple[str, TreeState]]
    history: _History
    stats: dict[str, int]


def _check(
    plan: _Plan,
    chosen: list[tuple[str, str]],
    now: datetime,
    agent_fd: int,
    managed_fd: int,
    archive_fd: int | None,
    archive_path: Path,
) -> _Checked:
    """Read-only verification of history, devices and the whole live managed tree."""
    history = (
        _History([], 0, 0, 0, Counter())
        if archive_fd is None
        else _scan_archive(archive_fd, archive_path)
    )
    stats = _gate_history(history, plan, now)
    managed_dev = os.fstat(managed_fd).st_dev
    target_dev = os.fstat(agent_fd if archive_fd is None else archive_fd).st_dev
    if target_dev != managed_dev:
        raise SchemaError("cross_device")
    live = scan_tree_fd(managed_fd)
    if live.digest != plan.managed.digest:
        raise SchemaError("source_changed")
    entries: list[tuple[str, TreeState]] = []
    for name, digest in chosen:
        tree = subtree_state(live, name)
        if tree.digest != digest:
            raise SchemaError("tree_mismatch")
        info = os.stat(name, dir_fd=managed_fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_dev != managed_dev:
            raise SchemaError("cross_device")
        entries.append((name, tree))
    return _Checked(entries, history, stats)


def _execute(
    *,
    plan: _Plan,
    checked: _Checked,
    approval: dict[str, object],
    base: Path,
    managed_fd: int,
    archive_fd: int,
    now: datetime,
    counts: dict[str, int],
) -> dict[str, object]:
    entries, history = checked.entries, checked.history
    archive_path = base.joinpath(*ARCHIVE_PARTS)
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    stage = f".stage-{run_id}"
    inputs = as_object(plan.proposal["policy_inputs"])
    binding: dict[str, object] = {
        "proposal_digest": plan.proposal["proposal_digest"],
        "approval_digest": canonical_digest(approval),
        "snapshot_digest": plan.proposal["snapshot_digest"],
        "policy_digest": plan.proposal["policy_digest"],
        "source_root_digest": plan.managed.digest,
        "as_of_utc": _stamp(plan.as_of),
        "window_days": as_int(plan.proposal["window_days"]),
        "policy_inputs": {key: inputs[key] for key in _POLICY_INPUTS},
    }
    manifest = _new_manifest(
        run_id=run_id,
        now=now,
        binding=binding,
        index=len(history.runs) + 1,
        source=plan.managed,
        items=[
            _Item(name, tree.digest, PLANNED, None, None, None)
            for name, tree in entries
        ],
    )
    if not (_absent(archive_fd, run_id) and _absent(archive_fd, stage)):
        raise SchemaError("destination_unexpected")
    os.mkdir(stage, 0o700, dir_fd=archive_fd)
    with ExitStack() as stack:
        stage_fd = os.open(stage, _DIR_FLAGS, dir_fd=archive_fd)
        stack.callback(os.close, stage_fd)
        os.mkdir(SKILLS_NAME, 0o700, dir_fd=stage_fd)
        skills_fd = os.open(SKILLS_NAME, _DIR_FLAGS, dir_fd=stage_fd)
        stack.callback(os.close, skills_fd)
        if os.fstat(skills_fd).st_dev != os.fstat(managed_fd).st_dev:
            raise SchemaError("cross_device")
        write_private_json(archive_path / stage / MANIFEST_NAME, _document(manifest))
        _fsync(skills_fd)
        _fsync(stage_fd)
        _rename_at(archive_fd, stage, archive_fd, run_id)
        _fsync(archive_fd)
        return _move_all(
            manifest=manifest,
            entries=entries,
            original=plan.managed,
            managed_fd=managed_fd,
            skills_fd=skills_fd,
            run_path=archive_path / run_id,
            identity=_identity(stage_fd),
            counts=counts,
        )


def _move_all(
    *,
    manifest: _Manifest,
    entries: list[tuple[str, TreeState]],
    original: TreeState,
    managed_fd: int,
    skills_fd: int,
    run_path: Path,
    identity: tuple[int, int],
    counts: dict[str, int],
) -> dict[str, object]:
    managed_dev = os.fstat(managed_fd).st_dev
    moved: list[str] = []
    code: str | None = None
    try:
        for item, (name, tree) in zip(manifest.items, entries, strict=True):
            live = scan_tree_fd(managed_fd)
            if live.digest != without_children(original, set(moved)).digest:
                raise SchemaError("source_changed")
            if subtree_state(live, name).digest != tree.digest:
                raise SchemaError("tree_mismatch")
            if sorted(os.listdir(skills_fd)) != sorted(moved):
                raise SchemaError("destination_unexpected")
            info = os.stat(name, dir_fd=managed_fd, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or info.st_dev != managed_dev:
                raise SchemaError("cross_device")
            _rename_at(managed_fd, name, skills_fd, name)
            moved.append(name)
            _fsync(managed_fd)
            _fsync(skills_fd)
            if _classify(skills_fd, name, tree) != "match":
                item.state = CONFLICT
                item.reason = "archive_differs"
                item.moved = _second(_utc_now())
                _persist(manifest, run_path, identity)
                raise SchemaError("destination_changed")
            item.state = MOVED
            item.moved = _second(_utc_now())
            _persist(manifest, run_path, identity)
            if (
                scan_tree_fd(managed_fd).digest
                != without_children(original, set(moved)).digest
            ):
                raise SchemaError("source_changed")
    except SchemaError as error:
        code = error.code
    except OSError:
        code = "local_io_error"
    last = _last_move([manifest])
    shared: dict[str, object] = {"run_id": manifest.run_id}
    if last is not None:
        shared["last_move_date"] = last.date().isoformat()
        shared["quarantine_earliest_end_date"] = (
            last.date() + timedelta(days=QUARANTINE_DAYS)
        ).isoformat()
    done = {**counts, "moved": len(moved), "remaining": len(entries) - len(moved)}
    if code is None:
        return _report(
            "archive", "apply", "complete", "applied", counts=done, extra=shared
        )
    return _report(
        "archive",
        "apply",
        "incomplete",
        "partial",
        counts=done,
        diagnostics={code: 1},
        extra=shared,
    )


# --------------------------------------------------------------------------- restore evidence


@dataclass(frozen=True)
class _Verdict:
    """What the filesystem says about one entry, independent of the recorded state."""

    state: str
    reason: str | None
    bound: datetime | None


def _derive(recorded: str, live: str, archived: str) -> tuple[str, str | None]:
    if recorded in _TERMINAL:
        return recorded, None
    if archived == "match":
        if live == "absent":
            return MOVED, None
        if live == "match":
            return EXTERNAL, None
        return CONFLICT, "live_differs"
    if live == "match":
        if archived == "absent":
            return (PLANNED if recorded == PLANNED else RESTORED), None
        return EXTERNAL, None
    if archived == "differs":
        return CONFLICT, "archive_differs"
    if recorded == PLANNED and archived == "absent" and live != "absent":
        # No archive copy exists: leave a never-moved, subsequently edited skill in place.
        return PLANNED, None
    return CONFLICT, ("archive_missing" if live == "absent" else "live_differs")


def _move_bound(skills_fd: int | None, name: str, updated: datetime) -> datetime:
    """Latest-plausible move time for an unrecorded move: journal write or entry ctime."""
    if skills_fd is None:
        return updated
    try:
        changed = os.stat(name, dir_fd=skills_fd, follow_symlinks=False).st_ctime
    except OSError:
        return updated
    return max(updated, _second(datetime.fromtimestamp(changed, UTC)))


def _reconcile(
    manifest: _Manifest, managed_fd: int | None, skills_fd: int | None
) -> dict[str, _Verdict]:
    verdicts: dict[str, _Verdict] = {}
    for item in manifest.items:
        if item.state in _TERMINAL:
            verdicts[item.name] = _Verdict(item.state, None, None)
            continue
        tree = subtree_state(manifest.source, item.name)
        state, reason = _derive(
            item.state,
            _classify(managed_fd, item.name, tree),
            _classify(skills_fd, item.name, tree),
        )
        bound = None
        if state == MOVED and item.moved is None:
            bound = _move_bound(skills_fd, item.name, manifest.updated)
        verdicts[item.name] = _Verdict(state, reason, bound)
    return verdicts


def _adopt(item: _Item, verdict: _Verdict, now: datetime) -> bool:
    before = (item.state, item.moved, item.restored, item.reason)
    if verdict.state == MOVED and item.moved is None:
        item.moved = verdict.bound or now
    if verdict.state in _TERMINAL and item.state not in _TERMINAL:
        item.restored = now
    item.reason = verdict.reason if verdict.state == CONFLICT else None
    item.state = verdict.state
    return before != (item.state, item.moved, item.restored, item.reason)


def _last_known_move(
    manifest: _Manifest, verdicts: dict[str, _Verdict]
) -> datetime | None:
    stamps = [
        moment
        for item in manifest.items
        if (moment := item.moved or verdicts[item.name].bound) is not None
    ]
    return max(stamps) if stamps else None


# --------------------------------------------------------------------------- restore


def restore(
    *,
    manifest_path: Path | None = None,
    items: list[str] | None = None,
    apply: bool = False,
    list_runs: bool = False,
    home: Path | None = None,
) -> dict[str, object]:
    """List runs, dry-run or apply restoring one run's items to the managed root.

    ``list_runs`` and the default dry-run are strictly read-only. Applying restores
    the selected items (all when ``items`` is None), is idempotent per item, never
    overwrites a live entry and records externally restored or conflicting items
    without deleting either copy.
    """
    mode = "list" if list_runs else "apply" if apply else "dry_run"
    try:
        return _restore(
            manifest_path=manifest_path,
            items=items,
            apply=apply,
            list_runs=list_runs,
            home=home,
        )
    except SchemaError as error:
        return _refused("restore", mode, error.code)
    except (OSError, UnicodeError):
        return _refused("restore", mode, "local_io_error")


def _selection(items: list[str] | None) -> frozenset[str] | None:
    if items is None:
        return None
    if (
        not isinstance(items, list)
        or not items
        or not all(_valid_name(name) for name in items)
        or len(set(items)) != len(items)
    ):
        raise SchemaError("restore_items_invalid")
    return frozenset(items)


def _run_id_of(manifest_path: Path, archive_path: Path) -> str:
    path = Path(manifest_path)
    if (
        path.name != MANIFEST_NAME
        or not _RUN_ID.fullmatch(path.parent.name)
        or path.parent.parent != archive_path
    ):
        raise SchemaError("manifest_path_invalid")
    return path.parent.name


def _restore(
    *,
    manifest_path: Path | None,
    items: list[str] | None,
    apply: bool,
    list_runs: bool,
    home: Path | None,
) -> dict[str, object]:
    mode = "list" if list_runs else "apply" if apply else "dry_run"
    base = _home(home)
    archive_path = base.joinpath(*ARCHIVE_PARTS)
    if list_runs:
        if apply or items is not None:
            raise SchemaError("restore_request_invalid")
    elif manifest_path is None:
        raise SchemaError("manifest_required")
    selected = _selection(items)
    run_id = None if manifest_path is None else _run_id_of(manifest_path, archive_path)
    with ExitStack() as stack:
        archive_fd = _open_below(base, ARCHIVE_PARTS, private=True)
        if archive_fd is None:
            if list_runs:
                return _report(
                    "restore", mode, "complete", "no_runs", extra={"runs": []}
                )
            raise SchemaError("manifest_missing")
        stack.callback(os.close, archive_fd)
        managed_fd = _open_below(base, MANAGED_PARTS)
        if managed_fd is not None:
            stack.callback(os.close, managed_fd)
        if list_runs:
            return _list(archive_fd, archive_path, managed_fd, run_id)
        if run_id is None:
            raise SchemaError("manifest_required")
        return _restore_run(
            archive_fd=archive_fd,
            archive_path=archive_path,
            managed_fd=managed_fd,
            run_id=run_id,
            selected=selected,
            apply=apply,
        )


def _open_run(archive_fd: int, run_id: str, stack: ExitStack) -> int:
    try:
        fd = os.open(run_id, _DIR_FLAGS, dir_fd=archive_fd)
    except OSError:
        raise SchemaError("run_unsafe") from None
    stack.callback(os.close, fd)
    _vet(fd, private=True)
    return fd


def _open_skills(run_fd: int, stack: ExitStack) -> int | None:
    try:
        fd = os.open(SKILLS_NAME, _DIR_FLAGS, dir_fd=run_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise SchemaError("run_unsafe") from None
    stack.callback(os.close, fd)
    _vet(fd, private=True)
    return fd


def _state_counts(manifest: _Manifest, verdicts: dict[str, _Verdict]) -> dict[str, int]:
    tally = Counter(verdicts[item.name].state for item in manifest.items)
    return {state: tally.get(state, 0) for state in _STATES}


def _note(history: _History, error: SchemaError | OSError) -> None:
    history.unreadable += 1
    history.codes[
        error.code if isinstance(error, SchemaError) else "local_io_error"
    ] += 1


def _list(
    archive_fd: int, archive_path: Path, managed_fd: int | None, run_id: str | None
) -> dict[str, object]:
    if run_id is None:
        history = _scan_archive(archive_fd, archive_path)
    else:
        history = _History([], 0, 0, 0, Counter())
        try:
            history.runs.append(_load_run(archive_fd, archive_path, run_id))
        except (SchemaError, OSError) as error:
            _note(history, error)
    runs: list[dict[str, object]] = []
    totals: Counter[str] = Counter()
    for manifest in history.runs:
        with ExitStack() as stack:
            try:
                run_fd = _open_run(archive_fd, manifest.run_id, stack)
                skills_fd = _open_skills(run_fd, stack)
            except (SchemaError, OSError) as error:
                _note(history, error)
                continue
            verdicts = _reconcile(manifest, managed_fd, skills_fd)
        states = _state_counts(manifest, verdicts)
        pending = sum(
            1 for item in manifest.items if verdicts[item.name].state != item.state
        )
        last = _last_known_move(manifest, verdicts)
        runs.append(
            {
                "run_id": manifest.run_id,
                "created_date": manifest.created.date().isoformat(),
                "batch_index": manifest.index,
                "items": len(manifest.items),
                "states": states,
                "needs_reconcile": pending,
                "last_move_date": None if last is None else last.date().isoformat(),
                "quarantine_end_date": None
                if last is None
                else (last.date() + timedelta(days=QUARANTINE_DAYS)).isoformat(),
            }
        )
        totals.update(states)
        totals["items"] += len(manifest.items)
        totals["needs_reconcile"] += pending
    counts = {
        "runs": len(runs),
        "unreadable_runs": history.unreadable,
        "unexpected_entries": history.unexpected,
        "staging_leftovers": history.leftovers,
        "items": totals["items"],
        "needs_reconcile": totals["needs_reconcile"],
        **{state: totals[state] for state in _STATES},
    }
    damaged = bool(history.unreadable or history.unexpected)
    if not runs and not damaged:
        return _report(
            "restore", "list", "complete", "no_runs", counts=counts, extra={"runs": []}
        )
    return _report(
        "restore",
        "list",
        "incomplete" if damaged else "complete",
        "listed",
        counts=counts,
        diagnostics=dict(history.codes),
        extra={"runs": runs},
    )


def _restore_run(
    *,
    archive_fd: int,
    archive_path: Path,
    managed_fd: int | None,
    run_id: str,
    selected: frozenset[str] | None,
    apply: bool,
) -> dict[str, object]:
    mode = "apply" if apply else "dry_run"
    with ExitStack() as stack:
        if apply:
            if managed_fd is None:
                raise SchemaError("managed_root_missing")
            stack.callback(os.close, _lock(archive_fd))
        manifest = _load_run(archive_fd, archive_path, run_id)
        names = {item.name for item in manifest.items}
        if selected is not None and not selected <= names:
            raise SchemaError("restore_item_unknown")
        chosen = names if selected is None else set(selected)
        run_fd = _open_run(archive_fd, run_id, stack)
        skills_fd = _open_skills(run_fd, stack)
        identity = _identity(run_fd)
        verdicts = _reconcile(manifest, managed_fd, skills_fd)
        tally: Counter[str] = Counter({key: 0 for key in _RESTORE_COUNTS})
        tally["selected"] = len(chosen)
        run_path = archive_path / run_id
        now = _second(_utc_now())
        stopped: str | None = None
        dirty = False
        try:
            for item in manifest.items:
                verdict = verdicts[item.name]
                picked = item.name in chosen
                if item.state in _TERMINAL:
                    tally["already_restored" if picked else "unselected"] += 1
                    continue
                if not picked:
                    tally["unselected"] += 1
                    dirty = (apply and _adopt(item, verdict, now)) or dirty
                    continue
                if verdict.state == MOVED:
                    if not apply or managed_fd is None or skills_fd is None:
                        tally["would_restore"] += 1
                        continue
                    if item.moved is None:
                        item.moved = verdict.bound or now
                    outcome = _restore_one(manifest, item, managed_fd, skills_fd)
                    tally["restored" if outcome == RESTORED else "conflict"] += 1
                    _persist(manifest, run_path, identity)
                    dirty = False
                    continue
                if verdict.state in (PLANNED, RESTORED):
                    tally["in_place"] += 1
                    verdict = replace(verdict, state=RESTORED)
                elif verdict.state == EXTERNAL:
                    tally["externally_restored"] += 1
                else:
                    tally["conflict"] += 1
                dirty = (apply and _adopt(item, verdict, now)) or dirty
            if apply and dirty:
                _persist(manifest, run_path, identity)
        except SchemaError as error:
            stopped = error.code
        except OSError:
            stopped = "local_io_error"
        counts = {key: tally[key] for key in _RESTORE_COUNTS}
        last = _last_known_move(manifest, verdicts)
        shared: dict[str, object] = {"run_id": run_id}
        if last is not None:
            shared["last_move_date"] = last.date().isoformat()
            shared["quarantine_end_date"] = (
                last.date() + timedelta(days=QUARANTINE_DAYS)
            ).isoformat()
        if stopped is not None:
            return _report(
                "restore",
                mode,
                "incomplete",
                "partial",
                counts=counts,
                diagnostics={stopped: 1},
                extra=shared,
            )
        if tally["conflict"]:
            return _report(
                "restore",
                mode,
                "incomplete",
                "conflict",
                counts=counts,
                diagnostics={"restore_conflict": tally["conflict"]},
                extra=shared,
            )
        outcome_name = "restored" if apply else "dry_run_ready"
        return _report(
            "restore", mode, "complete", outcome_name, counts=counts, extra=shared
        )


def _restore_one(
    manifest: _Manifest, item: _Item, managed_fd: int, skills_fd: int
) -> str:
    """Move one archived entry back; state is updated in memory, never overwriting live data."""
    tree = subtree_state(manifest.source, item.name)
    now = _second(_utc_now())
    if not _absent(managed_fd, item.name):
        item.state, item.reason = CONFLICT, "live_differs"
        return CONFLICT
    try:
        _rename_at(skills_fd, item.name, managed_fd, item.name)
    except OSError as error:
        if error.errno not in _OCCUPIED:
            raise
        item.state, item.reason = CONFLICT, "live_differs"
        return CONFLICT
    _fsync(skills_fd)
    _fsync(managed_fd)
    if _classify(managed_fd, item.name, tree) != "match":
        item.state, item.reason = CONFLICT, "live_differs"
        return CONFLICT
    item.state, item.reason, item.restored = RESTORED, None, now
    return RESTORED
