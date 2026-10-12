"""Snapshot-bound change inventory, commit plans and lossless logical commits.

Inventory is read-only: it runs Git with ``GIT_OPTIONAL_LOCKS=0`` and computes
worktree blob identities with ``git hash-object`` *without* ``-w``. It never
writes objects, the index, refs, journals or locks, and never fetches.

A commit plan is data, not commands. It binds the selected repository, the
original HEAD/branch/snapshot/index identities and the inventory identity; it
lists every changed path (base64 of the exact Git path bytes) with an explicit
disposition, the chosen base, the target branch placement, serial groups with
plain messages, prior-only dependencies, gate references and the complete
proposed Git tree of every group, and the exact intended final tree. Repeated
groups over one file are successive exact tree states, never patches.

Execution creates each group commit with the user's own ``git commit`` hooks in
a private shared clone checked out at exactly the planned tree, imports the
byte-identical commit object, then runs every referenced gate and the outgoing
secret scan in a fresh clean clone of that commit, so ignored or untracked files
of the user's checkout cannot influence validation. Only after every group is
validated, under the cooperative lock and against the unchanged original
snapshot, is the index and then the branch moved, from a journal written first.
The working tree is never written; nothing is stashed, reset, cleaned or forced.
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import tempfile
import unicodedata
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from git_ops import GitError, GitRepository, redact_credentials
from lifecycle import Endpoint, Status, code_identity
from state_store import (
    ChangesetRecord,
    GateRow,
    GroupRecord,
    LockBusy,
    Receipt,
    RefUpdate,
    StateError,
    Store,
)

PLAN_SCHEMA_VERSION = 1
GATES_SCHEMA_VERSION = 1
INVENTORY_SCHEMA_VERSION = 1
SECRET_SCAN = "@secret-scan"
GATE_TIMEOUT = 1800.0
COMMIT_TIMEOUT = 1800.0
CLONE_TIMEOUT = 600.0
SCAN_BYTES = 1 << 20
BULK_BYTES = 5 << 20
MAX_INPUT_BYTES = 16 << 20
MAX_MESSAGE_BYTES = 64 << 10
DIAGNOSTIC_TAIL = 4096

_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_REGULAR = ("100644", "100755")
_MODES = {"100644": "blob", "100755": "blob", "120000": "blob", "160000": "commit"}
_SECRET_NAMES = re.compile(
    rb"(?:^|/)(?:\.env(?:\.[^/]*)?|\.netrc|\.npmrc|\.pypirc|credentials(?:\.[^/]*)?"
    rb"|id_(?:rsa|dsa|ecdsa|ed25519)|[^/]*\.(?:pem|key|p12|pfx|keystore|jks|asc))$",
    re.IGNORECASE,
)
_SECRET_CONTENT = re.compile(
    rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}"
    rb"|github_pat_[A-Za-z0-9_]{22,}|xox[abprs]-[A-Za-z0-9-]{10,}"
    rb"|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}"
)
_GENERATED = frozenset(
    {
        b"node_modules",
        b".venv",
        b"venv",
        b"__pycache__",
        b"dist",
        b"build",
        b".tox",
        b".mypy_cache",
        b".pytest_cache",
        b".ruff_cache",
        b"target",
        b".gradle",
        b"coverage",
        b".next",
    }
)
# Settings a commit needs to reproduce the user's own identity, signing and
# message handling inside the private clone; nothing else is copied. Every value
# is the one the user's own ``git commit`` in the source checkout resolves.
_COMMIT_CONFIG = (
    "user.name",
    "user.email",
    "author.name",
    "author.email",
    "committer.name",
    "committer.email",
    "user.signingkey",
    "commit.gpgsign",
    "gpg.format",
    "gpg.program",
    "gpg.ssh.program",
    "gpg.ssh.defaultKeyCommand",
    "gpg.ssh.allowedSignersFile",
    "gpg.openpgp.program",
    "gpg.x509.program",
    "i18n.commitEncoding",
)
_COMMIT_CONFIG_BOOL = frozenset({"commit.gpgsign"})
_ACKNOWLEDGEABLE = frozenset(
    {"potential-secret", "generated-artifact", "bulk-artifact", "submodule"}
)
_TOKEN_ENV = re.compile(r"TOKEN|PASSWORD|SECRET|API_KEY")


class PlanError(ValueError):
    """A plan, draft or gate packet is malformed or unsupported (exit 2)."""


class ChangesetStop(RuntimeError):
    """A bounded stop: the plan, snapshot, gates or placement need a decision."""

    def __init__(
        self,
        status: Status,
        reason: str,
        next_action: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(reason)
        self.status: Status = status
        self.next_action = next_action
        self.details: dict[str, object] = dict(details or {})


# -- encoding ---------------------------------------------------------------------------


def encode_path(path: bytes) -> str:
    """Reversible, byte-exact JSON form of one Git path."""
    return base64.b64encode(path).decode("ascii")


def decode_path(value: object, label: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise PlanError(f"{label} must be a base64 path")
    try:
        path = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as error:
        raise PlanError(f"{label} is not canonical base64") from error
    if encode_path(path) != value:
        raise PlanError(f"{label} is not canonical base64")
    check_path(path, label)
    return path


def check_path(path: bytes, label: str = "path") -> None:
    """Reject paths Git would not store in a tree or that escape the checkout."""
    if not path or b"\0" in path or path.startswith(b"/"):
        raise PlanError(f"{label} is empty, absolute or contains NUL")
    for part in path.split(b"/"):
        if part in (b"", b".", b"..") or part.lower() == b".git":
            raise PlanError(f"{label} has an empty, relative or .git component")


def display(path: bytes) -> str:
    """Readable form for humans only; never used to address a path."""
    return path.decode("utf-8", "backslashreplace")


def item_id(path: bytes) -> str:
    return "i" + hashlib.sha256(b"ship-item\0" + path).hexdigest()[:20]


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _oid(value: object, label: str) -> str:
    if not isinstance(value, str) or _OID_RE.fullmatch(value) is None:
        raise PlanError(f"{label} must be a full lowercase object id")
    return value


def _digest_field(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise PlanError(f"{label} must be a SHA-256 identity")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PlanError(f"{label} must be a nonempty NUL-free string")
    return value


def _object(value: object, label: str, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PlanError(f"{label} must be a JSON object")
    if set(value) != keys:
        raise PlanError(f"{label} fields are missing or unsupported")
    return cast("dict[str, object]", value)


def _names(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PlanError(f"{label} must be a list")
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or _NAME_RE.fullmatch(item) is None:
            raise PlanError(f"{label} entries must be simple identifiers")
        names.append(item)
    if len(set(names)) != len(names):
        raise PlanError(f"{label} entries must be unique")
    return tuple(names)


def _read_json(path: Path, label: str) -> object:
    with path.open("rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise PlanError(f"{label} exceeds the supported size")
    try:
        return cast("object", json.loads(data))
    except (ValueError, UnicodeError) as error:
        raise PlanError(f"{label} is not valid JSON") from error


def check_message(value: object, label: str) -> str:
    """A plain commit message: data, exact bytes, no comment or control tricks."""
    text = _text(value, label)
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise PlanError(f"{label} is too long")
    if any(ord(char) < 32 and char not in "\n\t" for char in text) or "\x7f" in text:
        raise PlanError(f"{label} contains control characters")
    subject = text.split("\n", 1)[0]
    if not subject.strip() or subject != subject.strip():
        raise PlanError(f"{label} needs a subject line without edge whitespace")
    if text != text.rstrip():
        raise PlanError(f"{label} must not end with whitespace")
    return text


# -- states and inventory ---------------------------------------------------------------


@dataclass(frozen=True)
class State:
    """One path's Git state: mode and blob (or gitlink commit) identity."""

    mode: str
    oid: str

    def to_json(self) -> dict[str, str]:
        return {"mode": self.mode, "oid": self.oid}


def _state_json(state: State | None) -> dict[str, str] | None:
    return None if state is None else state.to_json()


@dataclass(frozen=True)
class Item:
    """One changed path with its HEAD, index and working-tree states."""

    id: str
    path: bytes
    head: State | None
    index: State | None
    worktree: State | None
    concerns: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": encode_path(self.path),
            "display": display(self.path),
            "head": _state_json(self.head),
            "index": _state_json(self.index),
            "worktree": _state_json(self.worktree),
            "staged": self.index != self.head,
            "unstaged": self.worktree != self.index,
            "untracked": self.head is None and self.index is None,
            "deleted": self.worktree is None and not self.blockers,
            "concerns": list(self.concerns),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class Inventory:
    root: Path
    common_dir: Path
    head: str
    branch: str | None
    snapshot: str
    index: str
    items: tuple[Item, ...]
    ignored: tuple[bytes, ...]
    conflicts: tuple[str, ...]
    operations: tuple[str, ...]

    @property
    def identity(self) -> str:
        return digest(
            {
                "schema_version": INVENTORY_SCHEMA_VERSION,
                "root": str(self.root),
                "common_dir": str(self.common_dir),
                "head": self.head,
                "branch": self.branch,
                "index": self.index,
                "items": [item.to_json() for item in self.items],
            }
        )

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": INVENTORY_SCHEMA_VERSION,
            "identity": self.identity,
            "repository": {"root": str(self.root), "common_dir": str(self.common_dir)},
            "source": {
                "head": self.head,
                "branch": self.branch,
                "snapshot": self.snapshot,
                "index": self.index,
            },
            "items": [item.to_json() for item in self.items],
            "ignored": [encode_path(path) for path in self.ignored],
            "conflicts": list(self.conflicts),
            "operations": list(self.operations),
            "secret_detection": (
                "path and pattern heuristic over changed content only; it is not the "
                "outgoing secret scan and never proves absence"
            ),
        }


def _real(path: str | os.PathLike[str]) -> str:
    return os.path.realpath(path)


def _lstat(path: bytes) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _hex(value: bytes, label: str) -> str:
    text = value.decode("ascii", "replace").strip()
    if _OID_RE.fullmatch(text) is None:
        raise GitError(f"git returned an invalid {label}")
    return text


def _config_bool(git: GitRepository, key: str, default: bool) -> bool:
    result = git.run("config", "--bool", "--get", key, check=False)
    if result.returncode == 1 and not result.stderr.strip():
        return default
    if result.returncode != 0:
        raise GitError(f"git could not read {key}")
    value = result.stdout.strip()
    if value not in (b"true", b"false"):
        raise GitError(f"{key} is not a boolean")
    return value == b"true"


class _Hasher:
    """Content identities of worktree paths, optionally written to the object store."""

    def __init__(self, git: GitRepository, *, write: bool) -> None:
        self.git = git
        self.write = write
        self.root = os.fsencode(git.path)

    def file(self, path: bytes) -> str:
        args = ["hash-object", *(["-w"] if self.write else []), "--", os.fsdecode(path)]
        return _hex(self.git.run(*args).stdout, "blob id")

    def data(self, content: bytes) -> str:
        args = ["hash-object", *(["-w"] if self.write else []), "--stdin"]
        return _hex(self.git.run(*args, input_bytes=content).stdout, "blob id")

    def link(self, path: bytes) -> str:
        return self.data(os.readlink(os.path.join(self.root, path)))

    def gitlink(self, path: bytes) -> str:
        sub = GitRepository(
            Path(os.fsdecode(os.path.join(self.root, path))), timeout=self.git.timeout
        )
        return _hex(
            sub.run("rev-parse", "--verify", "HEAD^{commit}").stdout, "submodule head"
        )

    def state(self, path: bytes, mode: str) -> State:
        if mode in _REGULAR:
            return State(mode, self.file(path))
        if mode == "120000":
            return State(mode, self.link(path))
        if mode == "160000":
            return State(mode, self.gitlink(path))
        raise GitError(f"unsupported worktree mode {mode} for {display(path)!r}")


def _concerns(root: bytes, path: bytes, worktree: State | None) -> list[str]:
    found: list[str] = []
    if _SECRET_NAMES.search(path):
        found.append("potential-secret")
    if any(part in _GENERATED for part in path.split(b"/")[:-1]):
        found.append("generated-artifact")
    if worktree is not None and worktree.mode in _REGULAR:
        full = os.path.join(root, path)
        info = _lstat(full)
        if info is not None and info.st_size > BULK_BYTES:
            found.append("bulk-artifact")
        try:
            fd = os.open(full, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as error:
            raise GitError(
                f"cannot read {display(path)!r}: {error.strerror}"
            ) from error
        with os.fdopen(fd, "rb") as handle:
            sample = handle.read(SCAN_BYTES)
        if "potential-secret" not in found and _SECRET_CONTENT.search(sample):
            found.append("potential-secret")
    if worktree is not None and worktree.mode == "160000":
        found.append("submodule")
    return found


def _status_records(raw: bytes) -> list[bytes]:
    if raw and not raw.endswith(b"\0"):
        raise GitError("unterminated git status output")
    return raw.split(b"\0")[:-1]


def take_inventory(git: GitRepository) -> Inventory:
    """Read-only, byte-exact inventory of every staged, unstaged and untracked change."""
    before = git.snapshot()
    top = GitRepository(before.root, timeout=git.timeout)
    if not _config_bool(top, "core.symlinks", True):
        raise GitError("core.symlinks=false checkouts are not supported")
    filemode = _config_bool(top, "core.filemode", True)
    status = top.run(
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=all",
        "--ignored=no",
        "--no-renames",
        "--ignore-submodules=none",
    ).stdout
    index_raw = top.run("ls-files", "--stage", "-z").stdout
    ignored_raw = top.run(
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=normal",
        "--ignored=traditional",
        "--no-renames",
        "--ignore-submodules=none",
    ).stdout
    hasher = _Hasher(top, write=False)
    root = os.fsencode(before.root)
    states: dict[bytes, dict[str, object]] = {}
    conflicts: list[str] = []
    for token in _status_records(status):
        kind = token[:1]
        if kind == b"u":
            parts = token.split(b" ", 10)
            if len(parts) != 11:
                raise GitError("malformed unmerged status record")
            conflicts.append(display(parts[10]))
            continue
        if kind == b"1":
            parts = token.split(b" ", 8)
            if len(parts) != 9:
                raise GitError("malformed ordinary status record")
            xy, sub = parts[1].decode("ascii"), parts[2].decode("ascii")
            m_head, m_index, m_work = (part.decode("ascii") for part in parts[3:6])
            h_head, h_index = (part.decode("ascii") for part in parts[6:8])
            path = parts[8]
            check_path(path)
            entry = states.setdefault(path, {})
            if "tracked" in entry:
                raise GitError(f"git reported {display(path)!r} twice")
            head = None if m_head == "000000" else State(m_head, h_head)
            index = None if m_index == "000000" else State(m_index, h_index)
            entry.update(tracked=True, head=head, index=index)
            if "untracked" not in entry:
                # An index-deleted path can also be reported untracked; that
                # record carries the real working-tree state.
                if xy[1] == ".":
                    entry["worktree"] = index
                elif m_work == "000000":
                    entry["worktree"] = None
                else:
                    entry["worktree"] = hasher.state(path, m_work)
            if sub.startswith("S") and ("M" in sub[2:] or "U" in sub[2:]):
                entry["blocker"] = "submodule-dirty"
            continue
        if kind == b"?":
            if token[:2] != b"? ":
                raise GitError("malformed untracked status record")
            path = token[2:]
            check_path(path.rstrip(b"/"))
            entry = states.setdefault(path.rstrip(b"/"), {})
            if "untracked" in entry:
                raise GitError(f"git reported {display(path)!r} twice")
            entry["untracked"] = True
            if path.endswith(b"/"):
                entry["blocker"] = "nested-repository"
                entry["worktree"] = None
                continue
            info = _lstat(os.path.join(root, path))
            if info is not None and stat.S_ISLNK(info.st_mode):
                entry["worktree"] = State("120000", hasher.link(path))
            elif info is not None and stat.S_ISREG(info.st_mode):
                mode = "100755" if filemode and info.st_mode & 0o111 else "100644"
                entry["worktree"] = State(mode, hasher.file(path))
            else:
                entry["blocker"] = "unsupported-kind"
                entry["worktree"] = None
            continue
        raise GitError("unexpected git status record type")
    items: list[Item] = []
    for path in sorted(states):
        entry = states[path]
        head = cast("State | None", entry.get("head"))
        index = cast("State | None", entry.get("index"))
        work = cast("State | None", entry.get("worktree"))
        blocker = cast("str | None", entry.get("blocker"))
        identity = item_id(path)
        if any(item.id == identity for item in items):
            raise GitError("two changed paths share one item identity")
        items.append(
            Item(
                identity,
                path,
                head,
                index,
                work,
                tuple(_concerns(root, path, work) if blocker is None else ()),
                () if blocker is None else (blocker,),
            )
        )
    ignored = tuple(
        token[2:].rstrip(b"/")
        for token in _status_records(ignored_raw)
        if token[:2] == b"! "
    )
    after = git.snapshot()
    if after.fingerprint != before.fingerprint:
        raise GitError("repository changed while it was being inventoried")
    return Inventory(
        root=before.root,
        common_dir=before.common_dir,
        head=before.head,
        branch=before.branch,
        snapshot=before.fingerprint,
        index=hashlib.sha256(index_raw).hexdigest(),
        items=tuple(items),
        ignored=ignored,
        conflicts=tuple(sorted(conflicts)),
        operations=before.operations,
    )


# -- gate decision packet ---------------------------------------------------------------


@dataclass(frozen=True)
class Gate:
    name: str
    argv: tuple[str, ...]

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            json.dumps([self.name, list(self.argv)], ensure_ascii=True).encode()
        ).hexdigest()


@dataclass(frozen=True)
class GatePolicy:
    """Source-provenanced gate and outgoing-secret-scan decision; never auto-loaded."""

    sources: tuple[str, ...]
    gates: tuple[Gate, ...]
    secret_scan: tuple[str, ...]
    local_gates_free: bool = False

    @property
    def identity(self) -> str:
        return digest(
            {
                "sources": list(self.sources),
                "gates": [[gate.name, list(gate.argv)] for gate in self.gates],
                "secret_scan": list(self.secret_scan),
                "local_gates_free": self.local_gates_free,
            }
        )

    def gate(self, name: str) -> Gate:
        for gate in self.gates:
            if gate.name == name:
                return gate
        raise PlanError(f"gate {name!r} is not defined by the gate decision")

    def scan(self, base: str, head: str) -> Gate:
        argv = tuple(
            part.replace("{base}", base).replace("{head}", head)
            for part in self.secret_scan
        )
        return Gate(SECRET_SCAN, argv)


def _argv(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise PlanError(f"{label} must be a nonempty argv list")
    if any(not isinstance(part, str) or not part or "\x00" in part for part in value):
        raise PlanError(f"{label} entries must be nonempty NUL-free strings")
    return tuple(cast("list[str]", value))


def parse_gates(raw: object) -> GatePolicy:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise PlanError("gate decision must be a JSON object")
    allowed = {"schema_version", "sources", "gates", "secret_scan", "local_gates_free"}
    if (
        set(raw) - allowed
        or type(raw.get("schema_version")) is not int
        or raw.get("schema_version") != GATES_SCHEMA_VERSION
    ):
        raise PlanError("unsupported gate decision schema or unknown fields")
    sources = raw.get("sources")
    if (
        not isinstance(sources, list)
        or not sources
        or any(not isinstance(item, str) or not item.strip() for item in sources)
        or len(set(sources)) != len(sources)
    ):
        raise PlanError("gate decision needs unique nonempty source references")
    free = raw.get("local_gates_free", False)
    if not isinstance(free, bool):
        raise PlanError("local_gates_free must be a boolean")
    entries = raw.get("gates")
    if not isinstance(entries, list):
        raise PlanError("gates must be an explicit list")
    gates: list[Gate] = []
    for entry in entries:
        gate = _object(entry, "gate", {"name", "argv"})
        name = gate["name"]
        if not isinstance(name, str) or _NAME_RE.fullmatch(name) is None:
            raise PlanError("gate names must be simple identifiers")
        gates.append(Gate(name, _argv(gate["argv"], f"gate {name} argv")))
    if len({gate.name for gate in gates}) != len(gates):
        raise PlanError("gate names must be unique")
    if free == bool(gates):
        raise PlanError(
            "declare repository gates, or local_gates_free=true with no gates"
        )
    scan = _object(raw.get("secret_scan"), "secret_scan", {"argv"})
    return GatePolicy(
        tuple(cast("list[str]", sources)),
        tuple(gates),
        _argv(scan["argv"], "secret_scan argv"),
        free,
    )


def load_gates(path: Path) -> GatePolicy:
    return parse_gates(_read_json(path, "gate decision"))


# -- commit plan ------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanItem:
    id: str
    path: bytes
    disposition: Literal["include", "exclude"]
    reason: str | None
    acknowledge: tuple[str, ...]


@dataclass(frozen=True)
class PlanGroup:
    id: str
    message: str
    items: tuple[str, ...]
    requires: tuple[str, ...]
    tree: str
    validation: tuple[str, ...]

    @property
    def message_identity(self) -> str:
        return hashlib.sha256(self.message.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Plan:
    identity: str
    root: Path
    common_dir: Path
    source_head: str
    source_branch: str | None
    source_snapshot: str
    source_index: str
    inventory: str
    where: Placement
    items: tuple[PlanItem, ...]
    groups: tuple[PlanGroup, ...]
    final_tree: str

    @property
    def base_ref(self) -> str:
        return self.where.base_ref

    @property
    def base_oid(self) -> str:
        return self.where.base_oid

    @property
    def branch(self) -> str:
        return self.where.branch


_PLAN_KEYS = {
    "schema_version",
    "repository",
    "source",
    "inventory",
    "base",
    "placement",
    "items",
    "groups",
    "final_tree",
}


def _branch_text(value: object, label: str) -> str:
    text = _text(value, label)
    if text.startswith(("-", "refs/")) or text == "HEAD":
        raise PlanError(f"{label} must be a short branch name")
    return text


def _disposition(
    raw: dict[str, object], label: str
) -> tuple[Literal["include", "exclude"], str | None, tuple[str, ...]]:
    disposition: Literal["include", "exclude"]
    if raw["disposition"] == "include":
        disposition = "include"
    elif raw["disposition"] == "exclude":
        disposition = "exclude"
    else:
        raise PlanError(f"{label} disposition must be include or exclude")
    stated = raw["reason"]
    reason = None if stated is None else _text(stated, f"{label} reason")
    acknowledge = raw["acknowledge"]
    if not isinstance(acknowledge, list) or any(
        not isinstance(code, str) for code in acknowledge
    ):
        raise PlanError(f"{label} acknowledge must be a list of concern codes")
    codes = tuple(cast("list[str]", acknowledge))
    if len(set(codes)) != len(codes):
        raise PlanError(f"{label} acknowledgements must be unique")
    if disposition == "exclude" and (reason is None or codes):
        raise PlanError(f"{label} exclusion needs a reason and no acknowledgements")
    return disposition, reason, codes


def _plan_items(value: object) -> tuple[PlanItem, ...]:
    if not isinstance(value, list):
        raise PlanError("plan items must be an explicit list")
    items: list[PlanItem] = []
    for entry in value:
        row = _object(
            entry, "plan item", {"id", "path", "disposition", "reason", "acknowledge"}
        )
        identity = _text(row["id"], "item id")
        path = decode_path(row["path"], f"item {identity} path")
        if identity != item_id(path):
            raise PlanError(f"item {identity} does not identify its path")
        disposition, reason, codes = _disposition(row, f"item {identity}")
        items.append(PlanItem(identity, path, disposition, reason, codes))
    if len({item.id for item in items}) != len(items):
        raise PlanError("plan items must be unique")
    return tuple(items)


@dataclass(frozen=True)
class Placement:
    base_ref: str
    base_oid: str
    mode: Literal["current", "new"]
    branch: str


def _placement_fields(base_raw: object, placement_raw: object) -> Placement:
    base = _object(base_raw, "base", {"ref", "oid"})
    placement = _object(placement_raw, "placement", {"mode", "branch"})
    mode: Literal["current", "new"]
    if placement["mode"] == "current":
        mode = "current"
    elif placement["mode"] == "new":
        mode = "new"
    else:
        raise PlanError("placement mode must be current or new")
    return Placement(
        _branch_text(base["ref"], "base ref"),
        _oid(base["oid"], "base oid"),
        mode,
        _branch_text(placement["branch"], "placement branch"),
    )


def parse_plan(raw: object) -> Plan:
    """Structural validation only; :func:`validate` binds it to the repository."""
    data = _object(raw, "plan", _PLAN_KEYS)
    if (
        type(data["schema_version"]) is not int
        or data["schema_version"] != PLAN_SCHEMA_VERSION
    ):
        raise PlanError("unsupported plan schema version")
    repository = _object(data["repository"], "plan repository", {"root", "common_dir"})
    source = _object(
        data["source"], "plan source", {"head", "branch", "snapshot", "index"}
    )
    where = _placement_fields(data["base"], data["placement"])
    stated_branch = source["branch"]
    source_branch = (
        None if stated_branch is None else _text(stated_branch, "source branch")
    )
    items = _plan_items(data["items"])
    if not isinstance(data["groups"], list):
        raise PlanError("plan groups must be an explicit list")
    included = {item.id for item in items if item.disposition == "include"}
    groups: list[PlanGroup] = []
    seen: set[str] = set()
    for entry in data["groups"]:
        row = _object(
            entry,
            "plan group",
            {"id", "message", "items", "requires", "tree", "validation"},
        )
        group_id = row["id"]
        if not isinstance(group_id, str) or _NAME_RE.fullmatch(group_id) is None:
            raise PlanError("group ids must be simple identifiers")
        if group_id in seen:
            raise PlanError(f"group {group_id} is declared twice")
        members = row["items"]
        if (
            not isinstance(members, list)
            or not members
            or any(not isinstance(member, str) for member in members)
        ):
            raise PlanError(f"group {group_id} must list its items")
        member_ids = tuple(cast("list[str]", members))
        if len(set(member_ids)) != len(member_ids):
            raise PlanError(f"group {group_id} lists an item twice")
        if not set(member_ids) <= included:
            raise PlanError(f"group {group_id} references an unknown or excluded item")
        requires = _names(row["requires"], f"group {group_id} requires")
        if not set(requires) <= seen:
            raise PlanError(
                f"group {group_id} may only require earlier groups: {sorted(set(requires) - seen)}"
            )
        groups.append(
            PlanGroup(
                group_id,
                check_message(row["message"], f"group {group_id} message"),
                member_ids,
                requires,
                _oid(row["tree"], f"group {group_id} tree"),
                _names(row["validation"], f"group {group_id} validation"),
            )
        )
        seen.add(group_id)
    return Plan(
        identity=digest(data),
        root=Path(_text(repository["root"], "repository root")),
        common_dir=Path(_text(repository["common_dir"], "repository common_dir")),
        source_head=_oid(source["head"], "source head"),
        source_branch=source_branch,
        source_snapshot=_digest_field(source["snapshot"], "source snapshot"),
        source_index=_digest_field(source["index"], "source index"),
        inventory=_digest_field(data["inventory"], "inventory identity"),
        where=where,
        items=items,
        groups=tuple(groups),
        final_tree=_oid(data["final_tree"], "final tree"),
    )


def load_plan(path: Path) -> Plan:
    return parse_plan(_read_json(path, "commit plan"))


def load_draft(path: Path) -> object:
    return _read_json(path, "grouping draft")


# -- Git object reads -------------------------------------------------------------------


def _zero(oid: str) -> str:
    return "0" * len(oid)


def _object_type(git: GitRepository, oid: str) -> str | None:
    result = git.run("cat-file", "-t", oid, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.decode("ascii", "replace").strip()


def tree_map(git: GitRepository, tree: str) -> dict[bytes, State]:
    """Every leaf of ``tree`` as ``path -> State``; malformed trees are rejected."""
    if _object_type(git, tree) != "tree":
        raise ChangesetStop(
            "NEEDS_JUDGMENT",
            f"proposed tree {tree} is not an available tree object",
            "author the proposed tree objects in this repository and resubmit the plan",
        )
    raw = git.run("ls-tree", "-r", "-z", "--full-tree", tree).stdout
    entries: dict[bytes, State] = {}
    for record in _status_records(raw):
        meta, tab, path = record.partition(b"\t")
        fields = meta.split(b" ")
        if not tab or len(fields) != 3:
            raise GitError("malformed ls-tree record")
        mode, kind, oid = (part.decode("ascii", "replace") for part in fields)
        try:
            check_path(path, f"tree {tree} entry")
        except PlanError as error:
            raise ChangesetStop(
                "NEEDS_JUDGMENT",
                str(error),
                "rebuild the proposed tree without unsafe paths",
            ) from error
        if _MODES.get(mode) != kind or _OID_RE.fullmatch(oid) is None:
            raise ChangesetStop(
                "NEEDS_JUDGMENT",
                f"tree {tree} has an unsupported entry {display(path)!r} ({mode} {kind})",
                "rebuild the proposed tree with regular, executable, symlink or gitlink entries",
            )
        if path in entries:
            raise GitError("ls-tree listed one path twice")
        entries[path] = State(mode, oid)
    for path in entries:
        parent = path.rpartition(b"/")[0]
        while parent:
            if parent in entries:
                raise ChangesetStop(
                    "NEEDS_JUDGMENT",
                    f"tree {tree} holds {display(parent)!r} as both file and directory",
                    "rebuild the proposed tree without file/directory collisions",
                )
            parent = parent.rpartition(b"/")[0]
    return entries


def _missing_objects(git: GitRepository, oids: Iterable[str]) -> list[str]:
    wanted = sorted(set(oids))
    if not wanted:
        return []
    raw = git.run(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        input_bytes="".join(f"{oid}\n" for oid in wanted).encode("ascii"),
    ).stdout
    missing: list[str] = []
    for line in raw.decode("ascii", "replace").splitlines():
        oid, _, kind = line.partition(" ")
        if kind == "missing":
            missing.append(oid)
    return missing


def _blobs(git: GitRepository, oids: Iterable[str]) -> dict[str, bytes]:
    wanted = sorted(set(oids))
    if not wanted:
        return {}
    raw = git.run(
        "cat-file",
        "--batch",
        input_bytes="".join(f"{oid}\n" for oid in wanted).encode("ascii"),
    ).stdout
    found: dict[str, bytes] = {}
    offset = 0
    for oid in wanted:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].decode("ascii", "replace").split(" ")
        if len(header) != 3 or header[0] != oid or header[1] != "blob":
            raise GitError(f"object {oid} is not an available blob")
        size = int(header[2])
        found[oid] = raw[end + 1 : end + 1 + size]
        offset = end + 1 + size + 1
    return found


def _tree_of(git: GitRepository, commit: str) -> str:
    return _hex(
        git.run("rev-parse", "--verify", f"{commit}^{{tree}}").stdout, "tree id"
    )


def _parents(git: GitRepository, commit: str) -> list[str]:
    raw = git.run("rev-list", "--parents", "-n", "1", commit).stdout
    fields = raw.decode("ascii", "replace").split()
    if not fields or fields[0] != commit:
        raise GitError(f"cannot read the parents of {commit}")
    return fields[1:]


def write_tree(git: GitRepository, entries: Mapping[bytes, State]) -> str:
    """Write the nested tree objects for a flat leaf map (authorized authoring only)."""
    nested: dict[bytes, object] = {}
    for path, state in entries.items():
        node = nested
        parts = path.split(b"/")
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise PlanError(f"{display(path)!r} collides with a file")
            node = cast("dict[bytes, object]", child)
        if parts[-1] in node:
            raise PlanError(f"{display(path)!r} collides with a directory")
        node[parts[-1]] = state

    def build(node: dict[bytes, object]) -> str:
        lines: list[bytes] = []
        for name, value in node.items():
            if isinstance(value, State):
                kind = _MODES[value.mode]
                lines.append(
                    f"{value.mode} {kind} {value.oid}\t".encode() + name + b"\0"
                )
            else:
                sub = build(cast("dict[bytes, object]", value))
                lines.append(f"040000 tree {sub}\t".encode() + name + b"\0")
        return _hex(
            git.run("mktree", "-z", input_bytes=b"".join(lines)).stdout, "tree id"
        )

    return build(nested)


# -- semantic validation ----------------------------------------------------------------


@dataclass(frozen=True)
class Prepared:
    plan: Plan
    inventory: Inventory
    mode: Literal["current", "switch", "transplant"]
    start: str
    included: tuple[Item, ...]
    final: dict[bytes, State]


def _stop(reason: str, next_action: str, **details: object) -> ChangesetStop:
    return ChangesetStop("NEEDS_JUDGMENT", reason, next_action, details)


def _branch_available(git: GitRepository, name: str) -> None:
    result = git.run("check-ref-format", f"refs/heads/{name}", check=False)
    if result.returncode != 0:
        raise PlanError(f"{name!r} is not a usable branch name")


def _ref_alias(ref: str) -> str:
    """Spelling-insensitive form of one ref path.

    Loose refs are files, so a case- or normalization-insensitive filesystem
    (the macOS default) stores ``feat`` and ``Feat/parser``, or NFC and NFD
    spellings, at one path although Git's exact comparison sees two refs. Aliases
    are refused on every filesystem instead of being guessed from this one.
    """
    folded = unicodedata.normalize("NFD", ref).casefold()
    return unicodedata.normalize("NFD", folded)


def _unused_branch(git: GitRepository, name: str) -> None:
    target = _ref_alias(f"refs/heads/{name}")
    occupied = sorted(
        ref
        for ref in git.local_heads()
        if (alias := _ref_alias(ref)) == target
        or alias.startswith(target + "/")
        or target.startswith(alias + "/")
    )
    if occupied:
        raise ChangesetStop(
            "BLOCKED",
            f"branch {name} has an occupied or aliased ref path",
            "choose an unused, non-colliding feature branch",
            {"refs": occupied},
        )


def _require_bound_base(git: GitRepository, plan: Placement) -> None:
    remotes = [os.fsdecode(name) for name in git.run("remote").stdout.splitlines()]
    refs = [
        f"refs/heads/{plan.base_ref}",
        *(f"refs/remotes/{remote}/{plan.base_ref}" for remote in remotes),
    ]
    tips = {ref: oid for ref in refs if (oid := git.resolve_ref(ref)) is not None}
    if not any(git.is_ancestor(plan.base_oid, tip) for tip in tips.values()):
        raise _stop(
            "the proposed base commit is not on the named local or cached base branch",
            "observe the intended base ref and re-author the branch placement",
            base_ref=plan.base_ref,
            base_oid=plan.base_oid,
            observed_refs=tips,
        )


def _weave(base: list[bytes], other: list[bytes]) -> list[bytes]:
    """An ordered common supersequence of two line lists.

    Matched source runs appear once; changed runs keep both sides interleaved.
    This represents ordered hunk selections. The caller separately caps each
    byte-exact line's occurrences against the captured states.
    """
    matcher = difflib.SequenceMatcher(None, base, other, autojunk=False)
    woven: list[bytes] = []
    for tag, base_start, base_end, other_start, other_end in matcher.get_opcodes():
        if tag == "equal":
            woven.extend(base[base_start:base_end])
            continue
        old, new = base[base_start:base_end], other[other_start:other_end]
        for position in range(max(len(old), len(new))):
            woven.extend(old[position : position + 1])
            woven.extend(new[position : position + 1])
    return woven


def _first_unplaced(lines: list[bytes], woven: list[bytes]) -> int | None:
    """Index of the first line that no unused, in-order occurrence in ``woven`` supplies."""
    position = 0
    for index, line in enumerate(lines):
        while position < len(woven) and woven[position] != line:
            position += 1
        if position == len(woven):
            return index
        position += 1
    return None


def _provenance(
    start: State | None,
    staged: State | None,
    final: State | None,
    mid: State | None,
    blobs: Mapping[str, bytes],
) -> str | None:
    """Reject intermediate content absent from the snapshot-bound source states.

    Beyond exact HEAD, index and final states, an intermediate file must be an
    ordered selection of their lines: each line occurrence it holds is supplied
    by a source occurrence, in an order the sources themselves establish.
    """
    if mid in (start, staged, final):
        return None
    if mid is None:
        return "an intermediate group deletes a path that exists before and after"
    if mid.mode not in _REGULAR:
        return "an intermediate link or submodule must equal an inventoried state"
    if mid.mode not in {
        state.mode for state in (start, staged, final) if state is not None
    }:
        return "an intermediate state introduces a mode absent from the inventory"
    sources = [
        state
        for state in (start, staged, final)
        if state is not None and state.mode in _REGULAR
    ]
    if not sources:
        return "an intermediate file has no regular-file source state"
    content = blobs[mid.oid]
    texts = {state.oid: blobs[state.oid] for state in sources}
    if any(
        len(text) > BULK_BYTES or b"\0" in text for text in (content, *texts.values())
    ):
        return "binary or bulk content cannot be split across groups"
    source_lines = [text.splitlines(keepends=True) for text in texts.values()]
    available: Counter[bytes] = Counter()
    for lines in source_lines:
        available |= Counter(lines)
    intermediate = content.splitlines(keepends=True)
    for index, line in enumerate(intermediate):
        available[line] -= 1
        if available[line] < 0:
            return f"intermediate line {index + 1} exceeds the source occurrence count"
    woven = source_lines[0]
    for lines in source_lines[1:]:
        woven = _weave(woven, lines)
    unplaced = _first_unplaced(intermediate, woven)
    if unplaced is not None:
        return (
            f"intermediate line {unplaced + 1} is repeated, reordered or absent from "
            "the inventoried HEAD, index and final states"
        )
    return None


def _check_items(items: Sequence[PlanItem], inventory: Inventory) -> tuple[Item, ...]:
    by_id = {item.id: item for item in inventory.items}
    if {item.id: item.path for item in items} != {
        item.id: item.path for item in inventory.items
    }:
        missing = sorted(set(by_id) - {item.id for item in items})
        raise _stop(
            "plan does not give every inventoried change exactly one disposition",
            "re-inventory and account for every staged, unstaged, untracked and deleted path",
            missing=missing,
        )
    included: list[Item] = []
    for entry in items:
        item = by_id[entry.id]
        if entry.disposition == "exclude":
            continue
        if item.blockers:
            raise _stop(
                f"item {display(item.path)!r} cannot be committed: {', '.join(item.blockers)}",
                "exclude it with a reason or resolve it outside this changeset",
                item=item.id,
            )
        if (
            set(entry.acknowledge) != set(item.concerns)
            or not set(entry.acknowledge) <= _ACKNOWLEDGEABLE
        ):
            raise _stop(
                f"item {display(item.path)!r} needs an explicit decision on {list(item.concerns)}",
                "acknowledge exactly its concerns to include it, or exclude it with a reason",
                item=item.id,
                concerns=list(item.concerns),
            )
        included.append(item)
    return tuple(included)


def _check_gates(groups: Sequence[PlanGroup], gates: GatePolicy) -> None:
    for group in groups:
        if gates.local_gates_free:
            if group.validation:
                raise PlanError(f"group {group.id} names gates under local_gates_free")
        elif not group.validation:
            raise _stop(
                f"group {group.id} references no applicable gate",
                "reference the repository gates that apply to this commit",
            )
        for name in group.validation:
            gates.gate(name)


def _placement(
    git: GitRepository, plan: Placement, inventory: Inventory, included: Sequence[Item]
) -> tuple[Literal["current", "switch", "transplant"], str, dict[bytes, State]]:
    _branch_available(git, plan.branch)
    _branch_available(git, plan.base_ref)
    if git.resolve_ref(plan.base_oid) != plan.base_oid:
        raise ChangesetStop(
            "BLOCKED",
            f"base commit {plan.base_oid} is not available locally",
            "fetch the intended base before executing the plan",
        )
    _require_bound_base(git, plan)
    if plan.branch == plan.base_ref:
        raise _stop(
            "new commits cannot be placed on the intended base branch",
            "choose a feature branch for this changeset",
        )
    if plan.mode == "current":
        if inventory.branch != plan.branch:
            raise _stop(
                "current placement must name the checked-out feature branch",
                "use new placement or check out the intended feature branch",
            )
        if not git.is_ancestor(plan.base_oid, inventory.head):
            raise _stop(
                "the current branch does not descend from the intended base",
                "choose new placement or the base this branch was created from",
            )
        start = inventory.head
        mode: Literal["current", "switch", "transplant"] = "current"
    else:
        _unused_branch(git, plan.branch)
        start = plan.base_oid
        mode = "switch" if plan.base_oid == inventory.head else "transplant"
    start_map = tree_map(git, _tree_of(git, start))
    if mode == "transplant":
        moved = [
            encode_path(item.path)
            for item in included
            if start_map.get(item.path) != item.head
        ]
        if moved:
            raise _stop(
                "included paths differ between the checked-out HEAD and the intended base",
                "decide how this work moves onto the base; nothing was changed",
                paths=moved,
            )
    else:
        for item in included:
            if start_map.get(item.path) != item.head:
                raise GitError("inventory HEAD states disagree with the HEAD tree")
    return mode, start, start_map


def validate(
    git: GitRepository, plan: Plan, inventory: Inventory, gates: GatePolicy
) -> Prepared:
    """Bind a parsed plan to the current repository; read-only."""
    if (_real(plan.root), _real(plan.common_dir)) != (
        _real(inventory.root),
        _real(inventory.common_dir),
    ):
        raise ChangesetStop(
            "BLOCKED",
            "the plan belongs to a different repository or checkout",
            "author the plan from the selected repository",
        )
    bound = (
        plan.source_head,
        plan.source_branch,
        plan.source_snapshot,
        plan.source_index,
        plan.inventory,
    )
    current = (
        inventory.head,
        inventory.branch,
        inventory.snapshot,
        inventory.index,
        inventory.identity,
    )
    if bound != current:
        names = ("head", "branch", "snapshot", "index", "inventory")
        raise _stop(
            "the working tree, index or HEAD changed after this plan was authored",
            "re-inventory the current work and author a fresh plan",
            changed=[
                name for name, a, b in zip(names, bound, current, strict=True) if a != b
            ],
        )
    if inventory.conflicts or inventory.operations:
        raise ChangesetStop(
            "BLOCKED",
            "unresolved conflicts or an in-progress Git operation",
            "finish or abort the operation yourself; nothing was changed",
            {
                "conflicts": list(inventory.conflicts),
                "operations": list(inventory.operations),
            },
        )
    included = _check_items(plan.items, inventory)
    _check_gates(plan.groups, gates)
    if not plan.groups:
        raise _stop("the plan commits nothing", "include at least one changed item")
    mode, start, start_map = _placement(git, plan.where, inventory, included)
    final = dict(start_map)
    for item in included:
        if item.worktree is None:
            final.pop(item.path, None)
        else:
            final[item.path] = item.worktree
    by_id = {item.id: item for item in included}
    maps = [tree_map(git, group.tree) for group in plan.groups]
    closure: dict[str, set[str]] = {}
    last: dict[bytes, str] = {}
    previous = start_map
    pending: list[tuple[str, bytes, State | None]] = []
    for group, current_map in zip(plan.groups, maps, strict=True):
        closure[group.id] = set(group.requires).union(
            *(closure[name] for name in group.requires)
        )
        delta = {
            path
            for path in previous.keys() | current_map.keys()
            if previous.get(path) != current_map.get(path)
        }
        owned = {by_id[member].path for member in group.items}
        if not delta:
            raise _stop(f"group {group.id} changes nothing", "remove or fill the group")
        if delta - owned:
            raise _stop(
                f"group {group.id} changes paths outside its declared items",
                "list every changed item or remove unapproved additions from the tree",
                paths=sorted(encode_path(path) for path in delta - owned),
            )
        if owned - delta:
            raise _stop(
                f"group {group.id} lists items it does not change",
                "list only the items whose content this group changes",
                paths=sorted(encode_path(path) for path in owned - delta),
            )
        for path in sorted(delta):
            earlier = last.get(path)
            if earlier is not None and earlier not in closure[group.id]:
                raise _stop(
                    f"group {group.id} edits {display(path)!r} after {earlier} without requiring it",
                    "declare the dependency between successive states of one file",
                )
            last[path] = group.id
            pending.append((group.id, path, current_map.get(path)))
        previous = current_map
    if plan.groups[-1].tree != plan.final_tree:
        raise _stop(
            "the final tree is not the last group's tree",
            "set final_tree to the tree the last group commits",
        )
    if previous != final:
        wrong = sorted(
            encode_path(path)
            for path in previous.keys() | final.keys()
            if previous.get(path) != final.get(path)
        )
        raise _stop(
            "the final tree does not equal the original work for the included items",
            "commit exactly the working-tree content of every included item",
            paths=wrong,
        )
    staged = {item.path: item.index for item in included}
    if mode != "transplant":
        # Publication rewrites the index of every included item to its final state.
        # A staged state that the working tree reverted or deleted survives only if
        # some group commits it; a state superseded by a live working-tree change
        # is the user's own continued edit and needs no group of its own.
        committed = {(path, mid) for _, path, mid in pending}
        for item in included:
            index_state = staged[item.path]
            kept = final.get(item.path)
            if (
                index_state == item.head
                or index_state == kept
                or (kept is not None and kept != start_map.get(item.path))
                or (item.path, index_state) in committed
            ):
                continue
            raise _stop(
                f"the staged state of {display(item.path)!r} would be dropped: the "
                "working tree reverted or deleted it and no group commits it",
                "add an earlier group that commits the staged content, or exclude "
                "the item so its index and working-tree state are kept exactly",
                item=item.id,
            )
    blob_ids = {
        state.oid
        for _, path, mid in pending
        for state in (mid, start_map.get(path), staged.get(path), final.get(path))
        if state is not None and state.mode != "160000"
    }
    missing = _missing_objects(git, blob_ids)
    if missing:
        raise _stop(
            "proposed trees reference objects that are not in this repository",
            "write the proposed blobs before resubmitting the plan",
            objects=missing,
        )
    intermediate = [
        (group_id, path, mid)
        for group_id, path, mid in pending
        if mid not in (start_map.get(path), staged.get(path), final.get(path))
    ]
    contents = _blobs(
        git,
        {
            state.oid
            for _, path, mid in intermediate
            for state in (mid, start_map.get(path), staged.get(path), final.get(path))
            if state is not None and state.mode in _REGULAR
        },
    )
    for group_id, path, mid in intermediate:
        problem = _provenance(
            start_map.get(path), staged.get(path), final.get(path), mid, contents
        )
        if problem is not None:
            raise _stop(
                f"group {group_id} {display(path)!r}: {problem}",
                "build intermediate states only from inventoried HEAD, index and final hunks",
            )
    return Prepared(plan, inventory, mode, start, included, final)


# -- draft compilation (explicitly authorized object authoring) -------------------------


_DRAFT_KEYS = {"schema_version", "base", "placement", "dispositions", "groups"}


def compile_draft(
    git: GitRepository, raw: object, gates: GatePolicy
) -> dict[str, object]:
    """Write the proposed blobs/trees for an assistant-authored grouping draft.

    Writes Git objects only (no index, ref, worktree, journal or lock change) and
    returns the complete, validated commit plan.
    """
    data = _object(raw, "draft", _DRAFT_KEYS)
    if (
        type(data["schema_version"]) is not int
        or data["schema_version"] != PLAN_SCHEMA_VERSION
    ):
        raise PlanError("unsupported draft schema version")
    inventory = take_inventory(git)
    by_id = {item.id: item for item in inventory.items}
    if not isinstance(data["dispositions"], list) or not isinstance(
        data["groups"], list
    ):
        raise PlanError("draft dispositions and groups must be explicit lists")
    items: list[dict[str, object]] = []
    for entry in data["dispositions"]:
        row = _object(
            entry, "draft disposition", {"item", "disposition", "reason", "acknowledge"}
        )
        identity = row["item"]
        if not isinstance(identity, str) or identity not in by_id:
            raise PlanError("draft disposition names an unknown item")
        _disposition(row, f"item {identity}")
        items.append(
            {
                "id": identity,
                "path": encode_path(by_id[identity].path),
                "disposition": row["disposition"],
                "reason": row["reason"],
                "acknowledge": row["acknowledge"],
            }
        )
    where = _placement_fields(data["base"], data["placement"])
    included = _check_items(_plan_items(items), inventory)
    _, _, start_map = _placement(git, where, inventory, included)
    if not data["groups"]:
        raise PlanError("a draft needs at least one group")
    writer = _Hasher(GitRepository(inventory.root, timeout=git.timeout), write=True)
    current = dict(start_map)
    groups: list[dict[str, object]] = []
    for entry in data["groups"]:
        row = _object(
            entry, "draft group", {"id", "message", "requires", "validation", "changes"}
        )
        if not isinstance(row["changes"], list) or not row["changes"]:
            raise PlanError("draft group changes must be a nonempty list")
        members: list[str] = []
        for change in row["changes"]:
            if not isinstance(change, dict):
                raise PlanError("draft change must be an object")
            if set(change) == {"item", "content"}:
                spec = _object(change, "draft change", {"item", "content"})
                if spec["content"] != "final":
                    raise PlanError('draft change content must be "final"')
            else:
                spec = _object(change, "draft change", {"item", "blob_file", "mode"})
            identity = spec["item"]
            if not isinstance(identity, str) or identity not in by_id:
                raise PlanError("draft change names an unknown item")
            item = by_id[identity]
            if "content" in spec:
                state = _written_final(writer, item)
            else:
                mode = spec["mode"]
                if mode not in _REGULAR:
                    raise PlanError("partial content must be a regular file mode")
                blob = Path(_text(spec["blob_file"], "blob_file"))
                if not blob.is_absolute():
                    raise PlanError("blob_file must be an absolute path")
                state = State(mode, writer.data(blob.read_bytes()))
            if state is None:
                current.pop(item.path, None)
            else:
                current[item.path] = state
            members.append(identity)
        groups.append(
            {
                "id": row["id"],
                "message": row["message"],
                "items": members,
                "requires": row["requires"],
                "tree": write_tree(writer.git, current),
                "validation": row["validation"],
            }
        )
    plan_raw: dict[str, object] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "repository": {
            "root": str(inventory.root),
            "common_dir": str(inventory.common_dir),
        },
        "source": {
            "head": inventory.head,
            "branch": inventory.branch,
            "snapshot": inventory.snapshot,
            "index": inventory.index,
        },
        "inventory": inventory.identity,
        "base": {"ref": where.base_ref, "oid": where.base_oid},
        "placement": {"mode": where.mode, "branch": where.branch},
        "items": items,
        "groups": groups,
        "final_tree": groups[-1]["tree"],
    }
    validate(git, parse_plan(plan_raw), inventory, gates)
    return plan_raw


def _written_final(writer: _Hasher, item: Item) -> State | None:
    state = item.worktree
    if state is None:
        return None
    if state.mode == "160000":
        return state
    oid = writer.link(item.path) if state.mode == "120000" else writer.file(item.path)
    if oid != state.oid:
        raise GitError(f"{display(item.path)!r} changed after it was inventoried")
    return state


# -- isolated commit creation and gates -------------------------------------------------


@dataclass
class _CommandResult:
    outcome: Literal["PASSED", "FAILED", "TIMED_OUT"]
    returncode: int | None
    tail: str


def _redact(text: str) -> str:
    message = redact_credentials(text)
    for key, value in os.environ.items():
        if len(value) >= 8 and _TOKEN_ENV.search(key):
            message = message.replace(value, "[redacted credential]")
    return message


def _run_command(
    argv: Sequence[str], cwd: Path, env: dict[str, str], timeout: float
) -> _CommandResult:
    """Run one argv vector in its own process group; output is kept only as a tail."""
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        timed_out = False
        returncode: int | None = None
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(process)
        except BaseException:
            _kill(process)
            raise
        size = output.seek(0, os.SEEK_END)
        output.seek(max(0, size - DIAGNOSTIC_TAIL))
        tail = _redact(output.read().decode("utf-8", "replace"))
    if timed_out:
        return _CommandResult("TIMED_OUT", None, tail)
    return _CommandResult("PASSED" if returncode == 0 else "FAILED", returncode, tail)


def _kill(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _clone(source: GitRepository, parent: Path, head: str, tree: str) -> GitRepository:
    """A private shared clone at ``head`` whose index and files are exactly ``tree``."""
    target = parent / "checkout"
    GitRepository(parent, timeout=CLONE_TIMEOUT).run(
        "clone",
        "--quiet",
        "--shared",
        "--no-checkout",
        "--",
        str(source.path),
        str(target),
    )
    clone = GitRepository(target, timeout=COMMIT_TIMEOUT)
    clone.run("update-ref", "--no-deref", "HEAD", head)
    clone.run("read-tree", "--reset", "-u", tree)
    return clone


class _Isolation:
    """Creates and validates commits away from the user's index and working tree."""

    def __init__(self, source: GitRepository) -> None:
        self.source = source
        hooks = source.run(
            "rev-parse", "--path-format=absolute", "--git-path", "hooks"
        ).stdout
        self.hooks = os.fsdecode(hooks.rstrip(b"\n"))
        self.config: list[str] = []
        for key in _COMMIT_CONFIG:
            # The effective value, resolved against the source's real gitdir: global,
            # system and conditional includes (``includeIf gitdir:``) all apply to
            # the user's own commit, but never to the clone's temporary gitdir.
            kind = ["--type=bool"] if key in _COMMIT_CONFIG_BOOL else []
            result = source.run("config", *kind, "--get", key, check=False)
            if result.returncode == 1 and not result.stderr.strip():
                continue
            if result.returncode != 0:
                raise GitError(f"git could not read {key}")
            value = os.fsdecode(result.stdout.rstrip(b"\n"))
            self.config.extend(["-c", f"{key}={value}"])

    def commit(self, parent: str, tree: str, message: str) -> str:
        """Commit ``tree`` on ``parent`` through the repository's own commit hooks."""
        with tempfile.TemporaryDirectory(prefix="ship-commit-") as temp:
            clone = _clone(self.source, Path(temp), parent, tree)
            message_file = Path(temp) / "message"
            message_file.write_bytes(message.encode("utf-8") + b"\n")
            try:
                clone.run(
                    "-c",
                    f"core.hooksPath={self.hooks}",
                    *self.config,
                    "commit",
                    "--quiet",
                    "--cleanup=verbatim",
                    "--file",
                    str(message_file),
                )
            except GitError as error:
                raise ChangesetStop(
                    "NEEDS_JUDGMENT",
                    f"git commit or a repository commit hook refused the group: {_redact(str(error))[:600]}",
                    "repair the reported hook finding in the plan; hooks are never bypassed",
                ) from error
            commit = clone.resolve_ref("HEAD")
            if commit is None:
                raise GitError("the isolated commit did not produce a HEAD")
            if _tree_of(clone, commit) != tree or _parents(clone, commit) != [parent]:
                raise ChangesetStop(
                    "NEEDS_JUDGMENT",
                    "a repository commit hook changed the committed content",
                    "apply the hook's changes in the plan's trees and resubmit",
                )
            raw = clone.run("cat-file", "commit", commit).stdout
        imported = _hex(
            self.source.run(
                "hash-object", "-w", "-t", "commit", "--stdin", input_bytes=raw
            ).stdout,
            "commit id",
        )
        if imported != commit:
            raise GitError("the imported commit object does not match its identity")
        return commit

    def gate(self, commit: str, gate: Gate) -> _CommandResult:
        """Run one gate in a fresh clean checkout of exactly ``commit``."""
        with tempfile.TemporaryDirectory(prefix="ship-gate-") as temp:
            clone = _clone(self.source, Path(temp), commit, commit)
            stray = clone.run(
                "status",
                "--porcelain=v2",
                "-z",
                "--untracked-files=all",
                "--ignored=matching",
            ).stdout
            if stray:
                raise GitError("the isolated validation checkout is not clean")
            try:
                return _run_command(
                    gate.argv,
                    clone.path,
                    self.source.execution_environment(),
                    GATE_TIMEOUT,
                )
            except FileNotFoundError as error:
                raise ChangesetStop(
                    "BLOCKED",
                    f"gate {gate.name} executable is unavailable: {gate.argv[0]}",
                    "install the declared gate prerequisite; no weaker gate is substituted",
                ) from error


# -- execution --------------------------------------------------------------------------


@dataclass
class Outcome:
    status: Status
    reason: str | None
    next_action: str
    receipt: Receipt | None
    details: dict[str, object] = field(default_factory=dict)
    mutation_attempted: bool = False
    mutation_performed: bool = False
    cancelled: bool = False

    def commits(self) -> list[dict[str, object]]:
        record = None if self.receipt is None else self.receipt.changeset
        if record is None:
            return []
        return [
            {
                "group": group.id,
                "commit": group.commit,
                "parent": group.parent,
                "tree": group.tree,
                "outcome": group.outcome,
                "gates": [
                    {
                        "name": row.name,
                        "outcome": row.outcome,
                        "returncode": row.returncode,
                    }
                    for row in group.gates
                ],
            }
            for group in record.groups
        ]

    def result(self) -> dict[str, object]:
        record = None if self.receipt is None else self.receipt.changeset
        update = None if record is None else record.update
        return {
            "schema_version": 1,
            "run_id": None if self.receipt is None else self.receipt.run_id,
            "status": self.status,
            "changeset": None
            if record is None
            else {
                "plan": record.plan_identity,
                "branch": record.branch,
                "base": {"ref": record.base_ref, "oid": record.base_oid},
                "mode": record.mode,
                "published_locally": update is not None
                and update.outcome == "CONFIRMED",
                "head": update.new
                if update is not None and update.outcome == "CONFIRMED"
                else None,
            },
            "confirmed_commits": list(record.confirmed) if record is not None else [],
            "commits": self.commits(),
            "blocker": self.reason,
            "details": self.details,
            "next_action": self.next_action,
            "mutation_attempted": self.mutation_attempted,
            "mutation_performed": self.mutation_performed,
            "cancelled": self.cancelled,
        }


def _index_listing(git: GitRepository) -> bytes:
    return git.run("ls-files", "--stage", "-z").stdout


def _index_entries(raw: bytes) -> dict[bytes, list[tuple[str, str, str]]]:
    entries: dict[bytes, list[tuple[str, str, str]]] = {}
    for record in _status_records(raw):
        meta, tab, path = record.partition(b"\t")
        fields = meta.decode("ascii", "replace").split(" ")
        if not tab or len(fields) != 3:
            raise GitError("malformed ls-files record")
        entries.setdefault(path, []).append((fields[0], fields[1], fields[2]))
    return entries


def _expected_index(raw: bytes, prepared: Prepared) -> tuple[bytes, bytes]:
    """The exact final index listing and the ``update-index --index-info`` input."""
    entries = _index_entries(raw)
    removals: list[bytes] = []
    additions: list[bytes] = []
    for item in prepared.included:
        final = prepared.final.get(item.path)
        if final is None:
            zero = _zero(prepared.start)
            removals.append(f"0 {zero}\t".encode() + item.path + b"\0")
            entries.pop(item.path, None)
        else:
            additions.append(
                f"{final.mode} {final.oid} 0\t".encode() + item.path + b"\0"
            )
            entries[item.path] = [(final.mode, final.oid, "0")]
    listing = b"".join(
        f"{mode} {oid} {stage}\t".encode() + path + b"\0"
        for path in sorted(entries)
        for mode, oid, stage in entries[path]
    )
    # Removals first, so a file replaced by a directory never collides.
    return listing, b"".join(removals + additions)


def _symbolic_head(git: GitRepository) -> str | None:
    result = git.run("symbolic-ref", "--quiet", "HEAD", check=False)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise GitError("HEAD symbolic reference is unreadable")
    return os.fsdecode(result.stdout.rstrip(b"\n"))


class _PreservedChanged(GitError):
    """Work the update must leave untouched differs from its journaled baseline."""

    def __init__(self, expected: str, observed: str) -> None:
        super().__init__(
            "work the changeset must leave untouched differs from its state before "
            "publication"
        )
        self.expected = expected
        self.observed = observed


def _preserved_identity(items: Iterable[Item]) -> str:
    """Identity of the working-tree and index states a local update must not touch."""
    return digest(
        [
            [
                encode_path(item.path),
                _state_json(item.worktree),
                _state_json(item.index),
            ]
            for item in sorted(items, key=lambda item: item.path)
        ]
    )


class _Run:
    def __init__(
        self,
        git: GitRepository,
        store: Store,
        plan: Plan,
        gates: GatePolicy,
        endpoint: Endpoint,
        receipt: Receipt | None,
    ) -> None:
        self.git = git
        self.store = store
        self.plan = plan
        self.gates = gates
        self.endpoint = endpoint
        self.receipt = receipt
        self.code = code_identity()
        self.attempted = False
        self.performed = False
        self.reusable: dict[tuple[str, str, str], GroupRecord] = {}

    @property
    def record(self) -> ChangesetRecord:
        if self.receipt is None or self.receipt.changeset is None:
            raise StateError("changeset execution has no journal")
        return self.receipt.changeset

    def _save(self) -> None:
        if code_identity() != self.code:
            raise ChangesetStop(
                "NEEDS_JUDGMENT",
                "controller source changed during execution",
                "review the current controller and resubmit the plan",
            )
        if self.receipt is None:
            raise StateError("changeset execution has no receipt")
        self.store.save(self.receipt)

    def _outcome(
        self, status: Status, reason: str | None, next_action: str, **details: object
    ) -> Outcome:
        return Outcome(
            status,
            reason,
            next_action,
            self.receipt,
            dict(details),
            self.attempted,
            self.performed,
        )

    # -- journal ----------------------------------------------------------------

    def _adopt(self, inventory: Inventory) -> None:
        """Create or extend the run journal for this plan before any mutation."""
        record = ChangesetRecord(
            plan_identity=self.plan.identity,
            gates_identity=self.gates.identity,
            source_snapshot=self.plan.source_snapshot,
            source_head=self.plan.source_head,
            source_branch=self.plan.source_branch,
            source_index=self.plan.source_index,
            base_ref=self.plan.base_ref,
            base_oid=self.plan.base_oid,
            branch=self.plan.branch,
            mode="current",
        )
        with self.store.mutation_lock():
            if self.receipt is None:
                self.receipt = Receipt(
                    uuid.uuid4().hex,
                    self.endpoint,
                    self.code,
                    None,
                    inventory.snapshot,
                    None,
                    changeset=record,
                )
            else:
                previous = self.receipt.changeset
                if previous is not None:
                    record.confirmed = list(previous.confirmed)
                self.receipt.changeset = record
                self.receipt.status = "WAITING"
            self.receipt.issue = None
            self.receipt.next_action = "create and validate the planned commits"
            self._save()

    def _prepare(self) -> bool:
        """Reconcile any journaled update; True when this plan is already published."""
        receipt = self.receipt
        if receipt is None:
            return False
        if receipt.code_identity != self.code:
            raise ChangesetStop(
                "NEEDS_JUDGMENT",
                "saved actions belong to different controller sources",
                "review the new sources and resubmit the plan",
            )
        previous = receipt.changeset
        if previous is None:
            return False
        if previous.update is not None and previous.update.outcome == "PENDING":
            with self.store.mutation_lock():
                self._reconcile(previous)
        update = previous.update
        if previous.plan_identity == self.plan.identity:
            if update is not None and update.outcome == "CONFIRMED":
                head = self.git.resolve_ref(update.ref)
                if head is None or not self.git.is_ancestor(update.new, head):
                    raise ChangesetStop(
                        "BLOCKED",
                        "the published changeset is no longer on its branch",
                        "inspect the branch; confirmed commits are never recreated blindly",
                    )
                return True
        elif update is not None and update.outcome == "PENDING":
            raise StateError("pending update survived reconciliation")
        if previous.gates_identity == self.gates.identity:
            for group in previous.groups:
                if group.outcome == "VALIDATED" and group.commit is not None:
                    key = (group.parent, group.tree, group.message_identity)
                    self.reusable[key] = group
        return False

    def _reconcile(self, record: ChangesetRecord) -> None:
        """Settle a journaled index/ref update from current facts; never blind."""
        update = record.update
        if update is None:
            return
        ref_now = self.git.resolve_ref(update.ref)
        index_now = hashlib.sha256(_index_listing(self.git)).hexdigest()
        head_now = _symbolic_head(self.git)
        if ref_now == update.new:
            if index_now != update.index_after:
                raise _stop(
                    "the branch moved to the new commits but the index differs",
                    "inspect the index; nothing further is changed automatically",
                )
            if head_now != update.head_after:
                if head_now != update.head_before or update.head_after is None:
                    raise _stop(
                        "HEAD changed outside this controller after the update",
                        "inspect HEAD; nothing further is changed automatically",
                    )
                self.attempted = True
                self.git.run(
                    "symbolic-ref", "-m", "ship: changeset", "HEAD", update.head_after
                )
                self.performed = True
            self._confirm(record)
            return
        if ref_now == update.old:
            if index_now == update.index_after and index_now != update.index_before:
                self._move_ref(record)
                self._confirm(record)
                return
            if index_now == update.index_before:
                update.outcome = "REJECTED"
                self._save()
                return
        raise _stop(
            "the branch or index changed outside this controller during the update",
            "inspect the branch, index and journal; nothing was retried",
        )

    # -- groups -----------------------------------------------------------------

    def _groups(self, prepared: Prepared, isolation: _Isolation) -> list[str]:
        parent = prepared.start
        commits: list[str] = []
        for group in self.plan.groups:
            key = (parent, group.tree, group.message_identity)
            reused = self.reusable.get(key)
            expected = {*group.validation, SECRET_SCAN}
            if (
                reused is not None
                and reused.commit is not None
                and {row.name for row in reused.gates} == expected
                and _object_type(self.git, reused.commit) == "commit"
                and _tree_of(self.git, reused.commit) == group.tree
                and _parents(self.git, reused.commit) == [parent]
            ):
                record = GroupRecord(
                    group.id,
                    parent,
                    group.tree,
                    group.message_identity,
                    reused.commit,
                    "VALIDATED",
                    list(reused.gates),
                )
                with self.store.mutation_lock():
                    self.record.groups.append(record)
                    self._save()
            else:
                record = GroupRecord(
                    group.id, parent, group.tree, group.message_identity
                )
                with self.store.mutation_lock():
                    self.record.groups.append(record)
                    self._save()
                self.attempted = True
                commit = isolation.commit(parent, group.tree, group.message)
                record.commit = commit
                self._validate(record, group, commit, parent, isolation)
            if record.commit is None:
                raise StateError("validated group has no commit")
            commits.append(record.commit)
            parent = record.commit
        return commits

    def _validate(
        self,
        record: GroupRecord,
        group: PlanGroup,
        commit: str,
        parent: str,
        isolation: _Isolation,
    ) -> None:
        checks = [self.gates.gate(name) for name in group.validation]
        checks.append(self.gates.scan(parent, commit))
        for gate in checks:
            result = isolation.gate(commit, gate)
            record.gates.append(
                GateRow(gate.name, gate.identity, result.outcome, result.returncode)
            )
            if result.outcome != "PASSED":
                record.outcome = "FAILED"
                with self.store.mutation_lock():
                    self._save()
                if gate.name == SECRET_SCAN:
                    raise ChangesetStop(
                        "BLOCKED",
                        f"the outgoing secret scan flagged group {group.id}",
                        "remove the secret from the plan or obtain an explicit owner decision",
                        {
                            "group": group.id,
                            "commit": commit,
                            "diagnostic": result.tail,
                        },
                    )
                raise ChangesetStop(
                    "NEEDS_JUDGMENT",
                    f"gate {gate.name} {result.outcome.lower()} on group {group.id} "
                    f"(exit {result.returncode})",
                    "diagnose ownership: repair change-owned failures in the plan or record "
                    "an inherited/permission blocker; acceptance is never weakened",
                    {
                        "group": group.id,
                        "commit": commit,
                        "gate": gate.name,
                        "diagnostic": result.tail,
                    },
                )
        record.outcome = "VALIDATED"
        with self.store.mutation_lock():
            self._save()

    # -- local publication ------------------------------------------------------

    def _publish(self, prepared: Prepared, commits: list[str]) -> None:
        record = self.record
        with self.store.mutation_lock():
            snapshot = self.git.snapshot()
            if snapshot.fingerprint != self.plan.source_snapshot:
                raise _stop(
                    "the working tree, index or HEAD changed while commits were validated",
                    "re-inventory; validated commits are reused by a fresh plan",
                )
            raw = _index_listing(self.git)
            before = hashlib.sha256(raw).hexdigest()
            if before != self.plan.source_index:
                raise _stop(
                    "the index changed while commits were validated",
                    "re-inventory; validated commits are reused by a fresh plan",
                )
            _require_bound_base(self.git, self.plan.where)
            if prepared.mode != "current":
                _unused_branch(self.git, self.plan.branch)
            if prepared.mode == "transplant":
                listing, records = raw, b""
            else:
                listing, records = _expected_index(raw, prepared)
            source_ref = (
                None
                if self.plan.source_branch is None
                else f"refs/heads/{self.plan.source_branch}"
            )
            ref = f"refs/heads/{self.plan.branch}"
            update = RefUpdate(
                ref=ref,
                old=self.plan.source_head if prepared.mode == "current" else None,
                new=commits[-1],
                index_before=before,
                index_after=hashlib.sha256(listing).hexdigest(),
                head_before=source_ref,
                head_after=ref if prepared.mode == "switch" else source_ref,
            )
            included = {item.id for item in prepared.included}
            record.preserved = _preserved_identity(
                prepared.inventory.items
                if prepared.mode == "transplant"
                else (
                    item for item in prepared.inventory.items if item.id not in included
                )
            )
            record.mode = prepared.mode
            record.update = update
            self._save()
            self.attempted = True
            if records:
                self.git.run("update-index", "-z", "--index-info", input_bytes=records)
                if (
                    hashlib.sha256(_index_listing(self.git)).hexdigest()
                    != update.index_after
                ):
                    raise _stop(
                        "the index did not reach its expected exact state",
                        "inspect the index; the journal keeps the pending update",
                    )
            self._move_ref(record)
            self._confirm(record)

    def _move_ref(self, record: ChangesetRecord) -> None:
        update = record.update
        if update is None:
            raise StateError("no journaled update to apply")
        old = update.old if update.old is not None else _zero(update.new)
        self.attempted = True
        self.git.run("update-ref", "-m", "ship: changeset", update.ref, update.new, old)
        self.performed = True
        if update.head_after != update.head_before and update.head_after is not None:
            head = _symbolic_head(self.git)
            if head != update.head_before or (
                head is None and self.git.resolve_ref("HEAD") != record.source_head
            ):
                raise _stop(
                    "HEAD moved before the new branch could be checked out",
                    "inspect HEAD; the new branch already holds the commits",
                )
            self.git.run(
                "symbolic-ref", "-m", "ship: changeset", "HEAD", update.head_after
            )

    def _confirm(self, record: ChangesetRecord) -> None:
        update = record.update
        if update is None:
            raise StateError("no journaled update to confirm")
        if (
            self.git.resolve_ref(update.ref) != update.new
            or _symbolic_head(self.git) != update.head_after
            or hashlib.sha256(_index_listing(self.git)).hexdigest()
            != update.index_after
        ):
            raise GitError(
                "the local update did not reach its journaled state", uncertain=True
            )
        # The update is complete only with a successful preservation proof, on every
        # confirmation and recovery path. Until then it stays PENDING: the branch
        # already holds the commits, but no CONFIRMED outcome or residual snapshot
        # exists for a resume or a later publication to trust, and the baseline
        # journaled before publication keeps being re-proven.
        try:
            before = self.git.snapshot().fingerprint
            self._verify_residual()
            residual = self.git.snapshot().fingerprint
            if residual != before:
                raise GitError(
                    "the working tree changed while its preservation was verified"
                )
        except GitError as error:
            details: dict[str, object] = {
                "ref": update.ref,
                "commit": update.new,
                "ref_updated": True,
            }
            if isinstance(error, _PreservedChanged):
                details["expected_preserved"] = error.expected
                details["observed_preserved"] = error.observed
            raise ChangesetStop(
                "BLOCKED",
                "the branch already holds the planned commits but the preservation "
                f"proof failed: {_redact(str(error))[:600]}",
                "restore the reported work to its state before publication and resume "
                "this run, or take a fresh disposition from a retained checkout; the "
                "update stays unconfirmed and nothing is published",
                details,
            ) from error
        update.outcome = "CONFIRMED"
        for group in record.groups:
            if group.commit is not None and group.commit not in record.confirmed:
                record.confirmed.append(group.commit)
        record.residual_snapshot = residual
        self.performed = True
        if self.receipt is not None:
            self.receipt.status = "WAITING"
            self.receipt.issue = None
            self.receipt.next_action = "publish the confirmed commits"
        self._save()

    # -- driver -----------------------------------------------------------------

    def run(self) -> Outcome:
        try:
            if self._prepare():
                return self._outcome("COMPLETE", None, "publish the confirmed commits")
            inventory = take_inventory(self.git)
            prepared = validate(self.git, self.plan, inventory, self.gates)
            self._adopt(inventory)
            isolation = _Isolation(
                GitRepository(inventory.root, timeout=COMMIT_TIMEOUT)
            )
            commits = self._groups(prepared, isolation)
            self._publish(prepared, commits)
            return self._outcome("COMPLETE", None, "publish the confirmed commits")
        except ChangesetStop as stop:
            return self._stopped(stop.status, str(stop), stop.next_action, stop.details)
        except KeyboardInterrupt:
            outcome = self._stopped(
                "WAITING",
                "execution cancelled; reconcile before resuming",
                "resume this run; validated commits are reused and nothing is repeated blindly",
                {},
            )
            outcome.cancelled = True
            return outcome
        except LockBusy as error:
            return self._outcome(
                "WAITING", str(error), "resume when the controller lock is free"
            )
        except (GitError, StateError, OSError) as error:
            return self._stopped(
                "BLOCKED",
                _redact(str(error))[:800],
                "resolve the reported safety prerequisite and resume",
                {},
            )

    def _verify_residual(self) -> None:
        """Prove local publication left the user's work intact, or raise.

        The identity journaled with the update, before any index or ref write,
        covers every original item the update must leave untouched. It is recomputed
        from the current inventory, so the first run and every recovery path prove
        the same original baseline. Committed paths must be clean and nothing else
        may differ; the only way forward is restoring the work.
        """
        record = self.record
        update = record.update
        if update is None:
            raise StateError("no journaled update to prove")
        expected = record.preserved
        if expected is None:
            expected = self._derived_baseline(record)
        committed = self._committed_paths(record, update)
        items = take_inventory(self.git).items
        for item in items:
            if item.path in committed:
                raise GitError(
                    f"committed item {display(item.path)!r} still differs after publication"
                )
        observed = _preserved_identity(items)
        if observed != expected:
            raise _PreservedChanged(expected, observed)

    def _derived_baseline(self, record: ChangesetRecord) -> str:
        """Baseline of a journal that predates the preserved-work checkpoint.

        It is unknown, except that a matching plan which includes every inventoried
        item leaves nothing in place: the baseline is then the empty set, proven by
        the plan's complete dispositions and by every committed path being clean.
        """
        if (
            record.mode == "transplant"
            or self.plan.identity != record.plan_identity
            or any(entry.disposition != "include" for entry in self.plan.items)
        ):
            raise GitError(
                "the original preserved-work baseline was not journaled and cannot "
                "be recovered"
            )
        return _preserved_identity(())

    def _committed_paths(
        self, record: ChangesetRecord, update: RefUpdate
    ) -> set[bytes]:
        """Paths whose index and working-tree state the local update rewrote."""
        if record.mode == "transplant":
            return set()  # Neither the index nor the working tree is ever written.
        paths = set(
            _status_records(
                self.git.run(
                    "diff-tree",
                    "-r",
                    "--no-renames",
                    "--name-only",
                    "-z",
                    record.source_head,
                    update.new,
                ).stdout
            )
        )
        if self.plan.identity == record.plan_identity:
            paths |= {
                entry.path
                for entry in self.plan.items
                if entry.disposition == "include"
            }
        return paths

    def _stopped(
        self, status: Status, reason: str, next_action: str, details: dict[str, object]
    ) -> Outcome:
        if self.receipt is not None:
            self.receipt.status = status if status != "COMPLETE" else "WAITING"
            self.receipt.issue = reason
            self.receipt.next_action = next_action
            try:
                with self.store.mutation_lock():
                    self._save()
            except (StateError, OSError, ChangesetStop) as error:
                reason = f"{reason}; receipt preservation failed: {error}"
                status = "BLOCKED"
        return self._outcome(status, reason, next_action, **details)


def check_outgoing(
    git: GitRepository, gates: GatePolicy, base: str, head: str, *, run_gates: bool
) -> list[dict[str, object]]:
    """Validate an outgoing range before it is pushed; nothing local is changed.

    The secret scan always covers ``base..head``. With ``run_gates`` every
    declared gate runs on ``head`` (commits this workflow did not create and
    validate itself). Each runs in a fresh clean clone of ``head``.
    """
    isolation = _Isolation(GitRepository(git.path, timeout=COMMIT_TIMEOUT))
    checks = list(gates.gates) if run_gates else []
    checks.append(gates.scan(base, head))
    evidence: list[dict[str, object]] = []
    for gate in checks:
        result = isolation.gate(head, gate)
        evidence.append(
            {
                "name": gate.name,
                "identity": gate.identity,
                "outcome": result.outcome,
                "returncode": result.returncode,
            }
        )
        if result.outcome == "PASSED":
            continue
        if gate.name == SECRET_SCAN:
            raise ChangesetStop(
                "BLOCKED",
                "the outgoing secret scan flagged the revisions to publish",
                "remove the secret or obtain an explicit owner decision; nothing was pushed",
                {"head": head, "diagnostic": result.tail},
            )
        raise ChangesetStop(
            "NEEDS_JUDGMENT",
            f"gate {gate.name} {result.outcome.lower()} on the outgoing head "
            f"(exit {result.returncode})",
            "diagnose ownership: repair change-owned failures with a commit plan or "
            "record an inherited/permission blocker; nothing was pushed",
            {"head": head, "gate": gate.name, "diagnostic": result.tail},
        )
    return evidence


def execute_changeset(
    git: GitRepository,
    store: Store,
    plan: Plan,
    gates: GatePolicy,
    endpoint: Endpoint,
    receipt: Receipt | None = None,
) -> Outcome:
    """Create, validate and locally publish one snapshot-bound commit plan.

    ``COMPLETE`` means the planned commits are on the target branch, the index
    matches and the work the plan left in place is proven unchanged; publication to
    a provider is a separate, later operation. A failed proof keeps the update
    unconfirmed and is re-proven by every resume.
    """
    return _Run(git, store, plan, gates, endpoint, receipt).run()
