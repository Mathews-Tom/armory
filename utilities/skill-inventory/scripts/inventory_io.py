"""Frozen JSONL snapshots with a private keyed binding, and private JSON files.

Log content is streamed and reduced to validated top-level objects; nothing is
cached or persisted. The only persisted state is the private binding, which
holds opaque keyed identities, byte lengths and keyed integrity digests. Every
diagnostic is a fixed literal code, never a path, identifier or input value.

Callers authorize canonical absolute roots first. Directory walks, listings, file
opens and private writes then go through descriptors opened component by component
with ``O_NOFOLLOW`` from ``/``, so a component swapped for a link after a check
fails instead of redirecting a read or a write.
"""

from __future__ import annotations

import errno
import hashlib
import hmac
import json
import math
import os
import secrets
import stat
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from inventory_types import (
    Cohort,
    Harness,
    SchemaError,
    as_int,
    as_list,
    as_object,
    as_string,
    utc_time,
)

PACKAGE_ROOT = Path(os.path.realpath(Path(__file__).parent.parent))
CHUNK_BYTES = 1 << 20
MAX_LINE_BYTES = 128 << 20
MAX_PRIVATE_BYTES = 64 << 20
BINDING_VERSION = 3
SNAPSHOT_POLICY = "frozen-complete-jsonl-prefix-v3"

_HARNESSES: tuple[Harness, ...] = ("omp", "claude", "codex")
_COHORTS: tuple[Cohort, ...] = ("main", "nested", "sub", "unknown")
_DOMAIN = b"skill-inventory/"
_HEX = frozenset("0123456789abcdef")
_BINDING_KEYS = frozenset(
    {
        "version",
        "policy",
        "harness",
        "as_of",
        "window_days",
        "key",
        "roots",
        "files",
        "inventory",
        "seal",
    }
)
_FILE_KEYS = frozenset({"id", "size", "digest"})


# --------------------------------------------------------------------------- keyed digests


def keyed_hasher(key: bytes, label: str) -> hmac.HMAC:
    """A domain-separated incremental keyed digest; digests never leave the process."""
    derived = hmac.new(key, _DOMAIN + label.encode("ascii"), hashlib.sha256).digest()
    return hmac.new(derived, digestmod=hashlib.sha256)


def keyed_digest(key: bytes, label: str, data: bytes) -> str:
    hasher = keyed_hasher(key, label)
    hasher.update(data)
    return hasher.hexdigest()


def is_hex_digest(value: object, length: int = 64) -> bool:
    return isinstance(value, str) and len(value) == length and set(value) <= _HEX


# --------------------------------------------------------------------------- strict JSON


def _reject_constant(_: str) -> object:
    raise SchemaError("nonfinite_json_constant")


def _parse_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise SchemaError("nonfinite_json_constant")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise SchemaError("duplicate_json_key")
        result[name] = value
    return result


def strict_json_loads(text: str) -> object:
    """Parse one JSON document, rejecting duplicate keys and nonfinite numbers."""
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_parse_float,
        )
    except SchemaError:
        raise
    except RecursionError:
        raise SchemaError("json_too_deep") from None
    except ValueError:
        raise SchemaError("malformed_json") from None


def canonical_json(data: object) -> bytes:
    try:
        text = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise SchemaError("private_json_invalid") from None
    return (text + "\n").encode("ascii")


# --------------------------------------------------------------------------- safe file access


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _canonical_parts(path: Path | str) -> list[bytes]:
    """Components of an absolute path; ``..`` is refused, never resolved lexically."""
    raw = os.fsencode(path)
    if not raw.startswith(b"/"):
        raise OSError(errno.EINVAL, "path must be absolute")
    parts = [part for part in raw.split(b"/") if part not in (b"", b".")]
    if b".." in parts:
        raise OSError(errno.EINVAL, "path must be canonical")
    return parts


def open_directory(path: Path | str) -> int:
    """Open a canonical absolute directory through a descriptor walk from ``/``.

    Every component is opened relative to its pinned parent with ``O_NOFOLLOW``, so no
    link anywhere in the path is followed and a component swapped for a link after
    the caller authorized the canonical path fails instead of redirecting. The caller
    owns the returned descriptor. Callers resolve and authorize roots first.
    """
    parts = _canonical_parts(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts:
            child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def _check_component(name: str | bytes) -> None:
    raw = os.fsencode(name)
    if not raw or raw in (b".", b"..") or b"/" in raw:
        raise OSError(errno.EINVAL, "not a single path component")


def _open_regular_at(
    directory_fd: int, name: str | bytes
) -> tuple[int, os.stat_result]:
    """Open a regular file read-only relative to a pinned directory, never following a link."""
    _check_component(name)
    fd = os.open(name, _FILE_FLAGS, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, "not a regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd, info


def open_regular(path: Path | str) -> tuple[int, os.stat_result]:
    """Open a regular file read-only from a canonical absolute path without blocking.

    The parent is walked with ``open_directory`` and the final component is opened
    relative to that pinned descriptor with ``O_NOFOLLOW``.
    """
    parts = _canonical_parts(path)
    if not parts:
        raise OSError(errno.EINVAL, "not a regular file")
    directory = open_directory(os.fsdecode(b"/" + b"/".join(parts[:-1])))
    try:
        return _open_regular_at(directory, parts[-1])
    finally:
        os.close(directory)


def _contains(root: Path, path: Path) -> bool:
    return path == root or root in path.parents


def _resolve(path: Path) -> Path:
    return Path(os.path.realpath(os.path.abspath(path)))


def _stat_at(directory_fd: int, name: str, *, follow: bool) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=follow)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _is_git_boundary_at(directory_fd: int) -> bool:
    """A work tree (``.git`` of any kind) or a bare repository layout, via the pinned directory."""
    if _stat_at(directory_fd, ".git", follow=False) is not None:
        return True
    head = _stat_at(directory_fd, "HEAD", follow=True)
    if head is None or not stat.S_ISREG(head.st_mode):
        return False
    objects = _stat_at(directory_fd, "objects", follow=True)
    if objects is None or not stat.S_ISDIR(objects.st_mode):
        return False
    refs = _stat_at(directory_fd, "refs", follow=True)
    return refs is not None and stat.S_ISDIR(refs.st_mode)


def _package_identity() -> tuple[int, int] | None:
    try:
        info = os.stat(PACKAGE_ROOT)
    except OSError:
        return None
    return info.st_dev, info.st_ino


@dataclass(frozen=True)
class PrivateParent:
    fd: int
    name: str
    directory: Path
    identity: tuple[int, int]


def _open_private_parent(path: Path | str) -> PrivateParent:
    """Walk the resolved parent by descriptors, vetting every ancestor, and keep it pinned.

    Every directory from ``/`` down must be outside Git repositories and the package,
    owned by the effective user or root, and not group- or world-writable unless
    sticky. Later private reads, creates, links and unlinks are relative to the
    returned descriptor, so a component swapped after this check cannot redirect them.
    """
    absolute = os.path.abspath(path)
    name = os.path.basename(absolute)
    if not name:
        raise SchemaError("private_path_invalid")
    directory = os.path.realpath(os.path.dirname(absolute))
    package = _package_identity()
    euid = os.geteuid()
    in_package = in_repository = unsafe = False
    fd = -1
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        steps: list[bytes | None] = [*_canonical_parts(directory), None]
        for part in steps:
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):
                raise OSError(errno.ENOTDIR, "not a directory")
            in_package = in_package or (info.st_dev, info.st_ino) == package
            unsafe = unsafe or bool(
                (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX)
                or info.st_uid not in (0, euid)
            )
            try:
                in_repository = in_repository or _is_git_boundary_at(fd)
            except OSError:
                raise SchemaError("private_parent_unsafe") from None
            if part is None:
                break
            child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        if in_package:
            raise SchemaError("private_path_in_package")
        if in_repository:
            raise SchemaError("private_path_in_repository")
        if unsafe:
            raise SchemaError("private_parent_unsafe")
        return PrivateParent(fd, name, Path(directory), (info.st_dev, info.st_ino))
    except OSError:
        if fd >= 0:
            os.close(fd)
        raise SchemaError("private_parent_missing") from None
    except BaseException:
        if fd >= 0:
            os.close(fd)
        raise


@contextmanager
def private_parent(
    path: Path | str, pinned: tuple[int, int] | None = None
) -> Iterator[PrivateParent]:
    parent = _open_private_parent(path)
    try:
        if pinned is not None and parent.identity != pinned:
            raise SchemaError("private_parent_changed")
        yield parent
    finally:
        os.close(parent.fd)


def _read_private_at(directory_fd: int, name: str) -> bytes | None:
    """Read an owner-only regular file relative to a pinned directory; None when absent."""
    try:
        fd, info = _open_regular_at(directory_fd, name)
    except FileNotFoundError:
        return None
    except OSError:
        raise SchemaError("private_file_unsafe") from None
    with os.fdopen(fd, "rb") as handle:
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise SchemaError("private_file_unsafe")
        if info.st_size > MAX_PRIVATE_BYTES:
            raise SchemaError("private_file_too_large")
        data = handle.read(MAX_PRIVATE_BYTES + 1)
        after = os.fstat(handle.fileno())
        endpoint = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        stamps = (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
            "st_uid",
            "st_mode",
            "st_nlink",
        )
        if (
            len(data) != info.st_size
            or any(getattr(info, field) != getattr(after, field) for field in stamps)
            or any(getattr(info, field) != getattr(endpoint, field) for field in stamps)
        ):
            raise SchemaError("private_file_changed")
        return data


def _create_exclusive_at(directory_fd: int, name: str, payload: bytes) -> None:
    """Write a temporary owner-only file, then link it into place atomically and exclusively.

    Create, link and unlink are all relative to the pinned directory descriptor.
    """
    temporary = f".{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
    except OSError:
        raise SchemaError("private_write_failed") from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(
            temporary,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        raise SchemaError("private_file_exists_changed") from None
    except OSError:
        raise SchemaError("private_write_failed") from None
    finally:
        with suppress(OSError):
            os.unlink(temporary, dir_fd=directory_fd)


def _store_private(parent: PrivateParent, payload: bytes) -> None:
    """Create the file; identical existing bytes are an unchanged update, anything else is refused."""
    existing = _read_private_at(parent.fd, parent.name)
    if existing is None:
        _create_exclusive_at(parent.fd, parent.name, payload)
    elif existing != payload:
        raise SchemaError("private_file_exists_changed")


def write_private_json(path: Path, data: object) -> None:
    """Create an owner-only canonical JSON file outside every repository and the package.

    An existing file is never modified: identical bytes are accepted as an unchanged
    update, anything else is refused.
    """
    payload = canonical_json(data)
    with private_parent(path) as parent:
        _store_private(parent, payload)


def read_private_json(path: Path) -> dict[str, object]:
    """Read a stable owner-only JSON object through the existing private boundary."""
    with private_parent(path) as parent:
        data = _read_private_at(parent.fd, parent.name)
    if data is None:
        raise SchemaError("private_input_missing")
    try:
        return as_object(
            strict_json_loads(data.decode("utf-8")), "private_input_invalid"
        )
    except UnicodeError:
        raise SchemaError("private_input_invalid") from None


# --------------------------------------------------------------------------- binding


@dataclass(frozen=True)
class _BoundFile:
    size: int
    digest: str


@dataclass(frozen=True)
class _Binding:
    harness: Harness
    as_of: datetime
    window_days: int
    key: bytes
    roots: tuple[str, ...]
    files: dict[str, _BoundFile]
    inventory: str
    seal: str


def _as_harness(value: object) -> Harness:
    text = as_string(value)
    for harness in _HARNESSES:
        if harness == text:
            return harness
    raise SchemaError("invalid_harness")


def _bound_hex(value: object, length: int) -> str:
    text = as_string(value)
    if not is_hex_digest(text, length):
        raise SchemaError("invalid_digest")
    return text


def load_binding(raw: bytes) -> _Binding:
    try:
        document = as_object(strict_json_loads(raw.decode("utf-8")))
        if (
            set(document) != _BINDING_KEYS
            or as_int(document["version"]) != BINDING_VERSION
            or as_string(document["policy"]) != SNAPSHOT_POLICY
        ):
            raise SchemaError("snapshot_binding_schema")
        window_days = as_int(document["window_days"])
        if window_days < 1:
            raise SchemaError("snapshot_binding_schema")
        key_hex = _bound_hex(document["key"], 64)
        roots = tuple(_bound_hex(item, 32) for item in as_list(document["roots"]))
        files: dict[str, _BoundFile] = {}
        for item in as_list(document["files"]):
            entry = as_object(item)
            if set(entry) != _FILE_KEYS:
                raise SchemaError("snapshot_binding_schema")
            identity = _bound_hex(entry["id"], 32)
            if identity in files:
                raise SchemaError("snapshot_binding_schema")
            files[identity] = _BoundFile(
                as_int(entry["size"]), _bound_hex(entry["digest"], 64)
            )
        binding = _Binding(
            harness=_as_harness(document["harness"]),
            as_of=utc_time(document["as_of"]),
            window_days=window_days,
            key=bytes.fromhex(key_hex),
            roots=roots,
            files=files,
            inventory=_bound_hex(document["inventory"], 64),
            seal=_bound_hex(document["seal"], 64),
        )
    except (SchemaError, UnicodeDecodeError):
        raise SchemaError("snapshot_binding_schema") from None
    body = {name: value for name, value in document.items() if name != "seal"}
    expected = keyed_digest(binding.key, "seal", canonical_json(body))
    if not hmac.compare_digest(expected, binding.seal):
        raise SchemaError("snapshot_binding_corrupt")
    return binding


# --------------------------------------------------------------------------- snapshot


@dataclass(frozen=True)
class FrozenFile:
    path: Path
    key: str
    size: int
    cohort: Cohort


@dataclass(frozen=True)
class _Found:
    key: str
    path: Path
    size: int
    cohort: Cohort
    device: int
    inode: int
    mtime_ns: int


@dataclass
class _Discovery:
    found: list[_Found]
    issues: Counter[str]
    duplicates: int


@dataclass
class _FileState:
    device: int
    inode: int
    mtime_ns: int
    baseline: str | None = None
    started: bool = False
    read_digest: str | None = None
    verified: str = ""
    complete_lines: int = 0
    tail_bytes: int = 0
    replaced: bool = False
    unreadable: bool = False
    short_read: bool = False
    modified: bool = False

    @property
    def failed(self) -> bool:
        return self.replaced or self.unreadable or self.short_read or self.modified

    def mark(self, status: str) -> None:
        """Record a failed open or digest pass; ``ok`` and unknown statuses change nothing."""
        if status == "replaced":
            self.replaced = True
        elif status == "unreadable":
            self.unreadable = True
        elif status == "truncated":
            self.short_read = True
        elif status == "unstable":
            self.modified = True


# Discovery codes that mean part of an approved tree could not be listed.
_INCOMPLETE_TRAVERSAL = ("log_root_unusable", "log_dir_unreadable")

_COHORT_BY_DEPTH: dict[Harness, dict[int, Cohort]] = {
    "omp": {2: "main", 3: "sub", 4: "nested"},
    "claude": {2: "main", 4: "sub"},
    "codex": {},
}


def cohort_hint(harness: Harness, depth: int) -> Cohort:
    """Hierarchy-only cohort from path depth below the root, filename included."""
    return _COHORT_BY_DEPTH[harness].get(depth, "unknown")


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _open_frozen(file: FrozenFile, state: _FileState) -> tuple[int, str]:
    try:
        fd, info = open_regular(file.path)
    except OSError:
        return -1, "unreadable"
    if (info.st_dev, info.st_ino) != (state.device, state.inode):
        os.close(fd)
        return -1, "replaced"
    return fd, "ok"


def _drift(before: os.stat_result, after: os.stat_result, size: int) -> str | None:
    """Metadata evidence that a frozen prefix changed while one descriptor was reading it.

    A shrink is truncation. A write that keeps the size exactly at the frozen length
    moves the modification time; growth beyond it is expected and left to the digests.
    """
    if after.st_size < size:
        return "truncated"
    if (
        before.st_size == after.st_size == size
        and before.st_mtime_ns != after.st_mtime_ns
    ):
        return "unstable"
    return None


class _Held:
    """A directory descriptor kept open until every queued child has been opened.

    ``DirEntry`` stats from a descriptor listing resolve against this descriptor, so
    it must outlive the listing's entries; queued children need it to open by name.
    """

    __slots__ = ("fd", "parts", "refs")

    def __init__(self, fd: int, parts: tuple[str, ...]) -> None:
        self.fd = fd
        self.parts = parts
        self.refs = 1

    def release(self) -> None:
        self.refs -= 1
        if self.refs == 0:
            os.close(self.fd)


def _scan_directory(
    held: _Held,
    index: int,
    queue: list[tuple[_Held, str]],
    candidates: list[tuple[int, tuple[str, ...], os.stat_result]],
    issues: Counter[str],
) -> None:
    """List one pinned directory; queue subdirectories and stat ``*.jsonl`` files in place."""
    try:
        with os.scandir(held.fd) as listing:
            entries = sorted(listing, key=lambda item: item.name)
    except OSError:
        issues["log_dir_unreadable"] += 1
        return
    for entry in entries:
        try:
            if entry.is_symlink():
                if entry.name.endswith(".jsonl") or entry.is_dir():
                    issues["inner_link_skipped"] += 1
                continue
            if entry.is_dir(follow_symlinks=False):
                held.refs += 1
                queue.append((held, entry.name))
                continue
            if not entry.name.endswith(".jsonl"):
                continue
            if not entry.is_file(follow_symlinks=False):
                issues["non_regular_skipped"] += 1
                continue
            info = entry.stat(follow_symlinks=False)
        except OSError:
            issues["log_dir_unreadable"] += 1
            continue
        candidates.append((index, (*held.parts, entry.name), info))


class Snapshot:
    """Capture or replay a frozen set of newline-complete JSONL prefixes.

    Capture creates a random key, discovers files through pinned directory
    descriptors, and eagerly hashes every frozen prefix as a keyed baseline checked
    against the discovery stamp. At ``finish`` it compares baseline, read and final
    digests and writes a private owner-only binding. Replay loads that binding, whose
    digests are the baseline, rediscovers files by keyed identity and compares the
    frozen prefixes. Growth and new files are counted but their bytes are never read;
    truncation, rewriting, deletion, inventory drift and a traversal that could not
    list a directory invalidate the snapshot.
    """

    key: bytes
    files: tuple[FrozenFile, ...]
    issues: Counter[str]
    mode: Literal["captured", "replayed"]

    def __init__(
        self,
        binding_path: Path,
        *,
        harness: Harness,
        roots: Sequence[Path],
        as_of: datetime,
        window_days: int,
    ) -> None:
        if harness not in _HARNESSES:
            raise SchemaError("invalid_harness")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise SchemaError("invalid_as_of")
        if (
            isinstance(window_days, bool)
            or not isinstance(window_days, int)
            or window_days < 1
        ):
            raise SchemaError("invalid_window")
        if not roots:
            raise SchemaError("log_roots_required")
        self.issues = Counter()
        self._harness: Harness = harness
        self._as_of = as_of.astimezone(UTC)
        self._window = window_days
        with private_parent(binding_path) as parent:
            self._binding_path = parent.directory / parent.name
            self._binding_identity = parent.identity
            self._roots = tuple(sorted({_resolve(root) for root in roots}, key=str))
            if any(_contains(root, self._binding_path) for root in self._roots):
                raise SchemaError("snapshot_binding_in_log_root")
            raw = _read_private_at(parent.fd, parent.name)
        self._bound = None if raw is None else load_binding(raw)
        self._inventory: str | None = None
        self._finished = False
        if self._bound is None:
            self.key = secrets.token_bytes(32)
            self.mode = "captured"
        else:
            self.key = self._bound.key
            self.mode = "replayed"
            if self._bound.harness != harness:
                raise SchemaError("snapshot_harness_mismatch")
            if (
                self._bound.as_of != self._as_of
                or self._bound.window_days != window_days
            ):
                raise SchemaError("snapshot_policy_mismatch")
            if sorted(self._root_id(root) for root in self._roots) != sorted(
                self._bound.roots
            ):
                raise SchemaError("snapshot_roots_mismatch")
            self._inventory = self._bound.inventory
        discovery = self._discover()
        self.issues.update(discovery.issues)
        self._initial_issues = discovery.issues
        self._duplicates = discovery.duplicates
        if self._bound is None:
            self._frozen = {found.key: found.size for found in discovery.found}
        else:
            self._frozen = {
                name: bound.size for name, bound in self._bound.files.items()
            }
        self.files = tuple(
            FrozenFile(found.path, found.key, self._frozen[found.key], found.cohort)
            for found in discovery.found
            if found.key in self._frozen
        )
        self._states = {
            found.key: _FileState(found.device, found.inode, found.mtime_ns)
            for found in discovery.found
            if found.key in self._frozen
        }
        self._by_key = {file.key: file for file in self.files}
        self._inventory_drift = False
        if not self._frozen:
            self.issues["no_log_files"] += 1
        if self._bound is None:
            for file in self.files:
                self._capture_baseline(file, self._states[file.key])
        else:
            for file in self.files:
                self._states[file.key].baseline = self._bound.files[file.key].digest

    # ------------------------------------------------------------------ identities

    def _root_id(self, root: Path) -> str:
        return keyed_digest(self.key, "root", os.fsencode(root))[:32]

    def _file_id(self, root_id: str, parts: tuple[str, ...]) -> str:
        data = root_id.encode("ascii") + b"\0" + os.fsencode("/".join(parts))
        return keyed_digest(self.key, "file", data)[:32]

    def _prefix_hasher(self, file: FrozenFile) -> hmac.HMAC:
        hasher = keyed_hasher(self.key, "prefix")
        hasher.update(
            file.key.encode("ascii") + b"\0" + str(file.size).encode("ascii") + b"\0"
        )
        return hasher

    # ------------------------------------------------------------------ discovery

    def _discover(self) -> _Discovery:
        """List ``*.jsonl`` files below each resolved root through pinned descriptors.

        The root and every subdirectory are opened relative to their pinned parent
        with ``O_NOFOLLOW``, listed and stat'ed through that descriptor, so a component
        swapped for a link after it was queued fails instead of redirecting the walk.
        Entry paths are rebuilt from the root and entry names.
        """
        issues: Counter[str] = Counter()
        candidates: list[tuple[int, tuple[str, ...], os.stat_result]] = []
        for index, root in enumerate(self._roots):
            try:
                root_fd = open_directory(root)
            except FileNotFoundError:
                issues["log_root_missing"] += 1
                continue
            except OSError:
                issues["log_root_unusable"] += 1
                continue
            queue: list[tuple[_Held, str]] = []
            try:
                top = _Held(root_fd, ())
                try:
                    _scan_directory(top, index, queue, candidates, issues)
                finally:
                    top.release()
                while queue:
                    parent, name = queue.pop()
                    try:
                        try:
                            child_fd = os.open(name, _DIR_FLAGS, dir_fd=parent.fd)
                        except OSError:
                            issues["log_dir_unreadable"] += 1
                            continue
                    finally:
                        parent.release()
                    child = _Held(child_fd, (*parent.parts, name))
                    try:
                        _scan_directory(child, index, queue, candidates, issues)
                    finally:
                        child.release()
            finally:
                for pending, _ in queue:
                    pending.release()
        candidates.sort(key=lambda item: (item[0], item[1]))
        found: list[_Found] = []
        seen: set[tuple[int, int]] = set()
        duplicates = 0
        root_ids = [self._root_id(root) for root in self._roots]
        for index, parts, info in candidates:
            identity = (info.st_dev, info.st_ino)
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            found.append(
                _Found(
                    key=self._file_id(root_ids[index], parts),
                    path=self._roots[index].joinpath(*parts),
                    size=info.st_size,
                    cohort=cohort_hint(self._harness, len(parts)),
                    device=info.st_dev,
                    inode=info.st_ino,
                    mtime_ns=info.st_mtime_ns,
                )
            )
        return _Discovery(found, issues, duplicates)

    # ------------------------------------------------------------------ inventory binding

    def bind_inventory(self, integrity: str) -> None:
        """Store (capture) or check (replay) the inventory the report is computed against."""
        if not is_hex_digest(integrity):
            raise SchemaError("invalid_inventory_integrity")
        if self._inventory is None:
            self._inventory = integrity
        elif not hmac.compare_digest(self._inventory, integrity):
            if self._bound is None:
                raise SchemaError("inventory_already_bound")
            self._inventory_drift = True

    def main_task_groups(self) -> dict[str, str]:
        """RAM-only groups proven by a captured OMP parent-main file, never log paths."""
        if self._harness != "omp":
            return {}
        captured = {file.path: file for file in self.files}
        groups: dict[str, str] = {}
        for file in self.files:
            if file.cohort not in ("sub", "nested"):
                continue
            for root in self._roots:
                if not file.path.is_relative_to(root):
                    continue
                parts = file.path.relative_to(root).parts
                if len(parts) not in (3, 4):
                    continue
                parent = root / parts[0] / (parts[1] + ".jsonl")
                main = captured.get(parent)
                if main is not None and main.cohort == "main":
                    groups[file.key] = keyed_digest(
                        self.key, "main-task-group", os.fsencode(parent)
                    )
                    break
        return groups

    # ------------------------------------------------------------------ digests

    def _digest_prefix(
        self, file: FrozenFile, state: _FileState, *, stamped: bool = False
    ) -> tuple[str, str]:
        """Keyed digest of the frozen prefix and a status.

        Status is ``ok``, ``replaced``, ``unreadable``, ``truncated`` or ``unstable``.
        With ``stamped`` both fstats must match the discovery stamp. Before an
        initial baseline exists, growth cannot prove that the prefix stayed intact.
        """
        fd, status = _open_frozen(file, state)
        if status != "ok":
            return status, ""
        hasher = self._prefix_hasher(file)
        remaining = file.size
        try:
            before = os.fstat(fd)
            if before.st_size < file.size:
                return "truncated", ""
            if stamped and (
                before.st_size != file.size or before.st_mtime_ns != state.mtime_ns
            ):
                return "unstable", ""
            while remaining:
                chunk = os.read(fd, min(CHUNK_BYTES, remaining))
                if not chunk:
                    return "truncated", ""
                remaining -= len(chunk)
                hasher.update(chunk)
            after = os.fstat(fd)
        except OSError:
            return "unreadable", ""
        finally:
            os.close(fd)
        drift = _drift(before, after, file.size)
        if drift is not None:
            return drift, ""
        if stamped and (
            after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns
        ):
            return "unstable", ""
        return "ok", hasher.hexdigest()

    def _capture_baseline(self, file: FrozenFile, state: _FileState) -> None:
        """Eagerly hash the prefix frozen at discovery, before any record is read."""
        status, digest = self._digest_prefix(file, state, stamped=True)
        if status == "ok":
            state.baseline = digest
        else:
            state.mark(status)

    # ------------------------------------------------------------------ streaming

    def records(self, file: FrozenFile) -> Iterator[dict[str, object]]:
        """Stream validated top-level objects from the frozen newline-complete prefix."""
        frozen = self._by_key.get(file.key)
        if frozen is None or frozen != file:
            raise SchemaError("unknown_snapshot_file")
        state = self._states[file.key]
        if state.started:
            raise SchemaError("snapshot_file_already_read")
        state.started = True
        return self._stream(frozen, state)

    def _parse_line(self, line: bytes) -> dict[str, object] | None:
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            self.issues["invalid_utf8"] += 1
            return None
        try:
            return as_object(strict_json_loads(text), "record_not_object")
        except SchemaError as error:
            self.issues[error.code] += 1
            return None

    def _stream(
        self, file: FrozenFile, state: _FileState
    ) -> Iterator[dict[str, object]]:
        if state.failed:
            return
        fd, status = _open_frozen(file, state)
        if status != "ok":
            state.mark(status)
            return
        hasher = self._prefix_hasher(file)
        remaining = file.size
        pending = bytearray()
        tail = 0
        overflow = False
        try:
            before = os.fstat(fd)
            while remaining:
                chunk = os.read(fd, min(CHUNK_BYTES, remaining))
                if not chunk:
                    state.short_read = True
                    return
                remaining -= len(chunk)
                hasher.update(chunk)
                start = 0
                while True:
                    end = chunk.find(b"\n", start)
                    if end < 0:
                        rest = len(chunk) - start
                        tail += rest
                        if not overflow:
                            if len(pending) + rest > MAX_LINE_BYTES:
                                overflow = True
                                pending.clear()
                            else:
                                pending += chunk[start:]
                        break
                    state.complete_lines += 1
                    if overflow or len(pending) + end - start > MAX_LINE_BYTES:
                        self.issues["line_too_long"] += 1
                    else:
                        if pending:
                            pending += chunk[start:end]
                            line = bytes(pending)
                        else:
                            line = chunk[start:end]
                        record = self._parse_line(line)
                        if record is not None:
                            yield record
                    pending.clear()
                    overflow = False
                    tail = 0
                    start = end + 1
            after = os.fstat(fd)
        except OSError:
            state.unreadable = True
            return
        finally:
            os.close(fd)
        state.tail_bytes = tail
        digest = hasher.hexdigest()
        state.read_digest = digest
        drift = _drift(before, after, file.size)
        if drift is not None:
            state.mark(drift)
        elif state.baseline is not None and not hmac.compare_digest(
            state.baseline, digest
        ):
            state.modified = True

    # ------------------------------------------------------------------ finish

    def finish(self, current_inventory_integrity: str) -> dict[str, object]:
        """Verify frozen prefixes, listings and inventory; persist or revalidate the binding.

        Returns aggregate-only metadata. A changed snapshot is reported invalid with
        anonymous issue codes and is never refreshed or written.
        """
        if self._finished:
            raise SchemaError("snapshot_finished")
        if self._inventory is None:
            raise SchemaError("inventory_not_bound")
        if not is_hex_digest(current_inventory_integrity):
            raise SchemaError("invalid_inventory_integrity")
        self._finished = True

        final = self._discover()
        incomplete = final.issues["log_root_missing"] > self._initial_issues[
            "log_root_missing"
        ] or any(
            self._initial_issues[code] or final.issues[code]
            for code in _INCOMPLETE_TRAVERSAL
        )
        # Initial codes are already counted; a code seen in both passes keeps its larger count.
        for code, count in final.issues.items():
            self.issues[code] = max(self.issues[code], count)
        now = {found.key: found for found in final.found}
        missing = sum(1 for name in self._frozen if name not in now)
        new_files = sum(1 for name in now if name not in self._frozen)
        appended = truncated = rewritten = unreadable = unread = 0
        initially_unstable = 0
        for file in self.files:
            state = self._states[file.key]
            current = now.get(file.key)
            if current is not None and current.size > file.size:
                appended += 1
            if state.modified and state.baseline is None:
                initially_unstable += 1
            elif state.replaced or state.modified:
                rewritten += 1
            elif state.unreadable:
                unreadable += 1
            elif state.short_read or (current is not None and current.size < file.size):
                truncated += 1
            elif current is not None:
                status, digest = self._digest_prefix(file, state)
                if status in ("replaced", "unstable"):
                    rewritten += 1
                elif status == "truncated":
                    truncated += 1
                elif status == "unreadable":
                    unreadable += 1
                elif any(
                    known is not None and not hmac.compare_digest(known, digest)
                    for known in (state.baseline, state.read_digest)
                ):
                    rewritten += 1
                elif state.read_digest is None:
                    unread += 1
                else:
                    state.verified = digest
        drift = self._inventory_drift or not hmac.compare_digest(
            self._inventory, current_inventory_integrity
        )
        binding_changed = self._binding_changed()
        for code, count in (
            ("snapshot_missing_file", missing),
            ("snapshot_truncated", truncated),
            ("snapshot_rewritten", rewritten),
            ("snapshot_initial_unstable", initially_unstable),
            ("file_unreadable", unreadable),
            ("snapshot_unread", unread),
            ("inventory_drift", int(drift)),
            ("snapshot_binding_changed", int(binding_changed)),
        ):
            if count:
                self.issues[code] += count
        valid = not (
            missing
            or truncated
            or rewritten
            or initially_unstable
            or unreadable
            or unread
            or drift
            or binding_changed
            or incomplete
        )
        if valid and self._bound is None:
            self._save_binding()

        tails = [state for state in self._states.values() if state.tail_bytes]
        partial_tail_bytes = sum(state.tail_bytes for state in tails)
        cohorts = Counter(file.cohort for file in self.files)
        return {
            "appended_files": appended,
            "as_of": _utc_text(self._as_of),
            "binding_schema_version": BINDING_VERSION,
            "bytes": sum(self._frozen.values()),
            "closed": valid and not (appended or new_files or tails),
            "cohorts": {name: cohorts[name] for name in _COHORTS},
            "complete_lines": sum(
                state.complete_lines for state in self._states.values()
            ),
            "duplicate_files": self._duplicates,
            "files": len(self._frozen),
            "harness": self._harness,
            "initially_unstable_files": initially_unstable,
            "missing_files": missing,
            "new_files": new_files,
            "partial_tail_bytes": partial_tail_bytes,
            "partial_tail_files": len(tails),
            "policy": SNAPSHOT_POLICY,
            "rewritten_files": rewritten,
            "roots": len(self._roots),
            "truncated_files": truncated,
            "unread_files": unread,
            "unreadable_files": unreadable,
            "valid": valid,
            "window_days": self._window,
        }

    def _binding_changed(self) -> bool:
        if self._bound is None:
            return False
        try:
            with private_parent(self._binding_path, self._binding_identity) as parent:
                raw = _read_private_at(parent.fd, parent.name)
            return raw is None or load_binding(raw).seal != self._bound.seal
        except SchemaError:
            return True

    def _save_binding(self) -> None:
        if self._inventory is None:
            raise SchemaError("inventory_not_bound")
        body: dict[str, object] = {
            "version": BINDING_VERSION,
            "policy": SNAPSHOT_POLICY,
            "harness": self._harness,
            "as_of": _utc_text(self._as_of),
            "window_days": self._window,
            "key": self.key.hex(),
            "roots": sorted(self._root_id(root) for root in self._roots),
            "files": [
                {
                    "id": file.key,
                    "size": file.size,
                    "digest": self._states[file.key].verified,
                }
                for file in sorted(self.files, key=lambda item: item.key)
            ],
            "inventory": self._inventory,
        }
        seal = keyed_digest(self.key, "seal", canonical_json(body))
        payload = canonical_json({**body, "seal": seal})
        with private_parent(self._binding_path, self._binding_identity) as parent:
            _store_private(parent, payload)
