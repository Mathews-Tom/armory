"""Private, versioned lifecycle journals; current Git/provider facts remain authoritative."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

SCHEMA_VERSION = 2
_LEGACY_SCHEMA_VERSION = 1
_RUN_ID = re.compile(r"[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_STATUSES = {"COMPLETE", "WAITING", "NEEDS_JUDGMENT", "BLOCKED"}
_ENDPOINTS = {"pr", "merged", "clean"}
_REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_GROUP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_GATE_NAME = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
# Flat top-level keys that hold the confirmed PR target; all null before binding.
TARGET_KEYS = (
    "host",
    "repo",
    "number",
    "head_sha",
    "base_sha",
    "head_ref",
    "head_repo",
    "base_ref",
)
CHANGESET_MODES = ("current", "switch", "transplant")
_GROUP_OUTCOMES = {"PENDING", "VALIDATED", "FAILED"}
_GATE_OUTCOMES = {"PASSED", "FAILED", "TIMED_OUT"}
_UPDATE_OUTCOMES = {"PENDING", "CONFIRMED", "REJECTED"}
_CHANGESET_KEYS = {
    "plan_identity",
    "gates_identity",
    "source_snapshot",
    "source_head",
    "source_branch",
    "source_index",
    "base_ref",
    "base_oid",
    "branch",
    "mode",
    "groups",
    "update",
    "confirmed",
    "residual_snapshot",
}
# Historical receipts can lack this checkpoint; absence is unknown, not empty.
_CHANGESET_OPTIONAL_KEYS = {"preserved"}
_GROUP_KEYS = {
    "id",
    "parent",
    "tree",
    "message_identity",
    "commit",
    "outcome",
    "gates",
}
_GATE_ROW_KEYS = {"name", "identity", "outcome", "returncode"}
_UPDATE_KEYS = {
    "ref",
    "old",
    "new",
    "index_before",
    "index_after",
    "head_before",
    "head_after",
    "outcome",
}
_INTENT_KEYS = {
    "key",
    "kind",
    "resource",
    "expected_oid",
    "outcome",
    "actual_oid",
    "created_at",
    "namespace",
    "required",
    "ref",
    "proof",
}
_VERIFICATION_KEYS = {
    "sha",
    "command_index",
    "command_identity",
    "returncode",
    "outcome",
}
_CLEANUP_KEYS = {
    "kind",
    "resource",
    "namespace",
    "expected_oid",
    "actual_oid",
    "reason",
    "proof",
    "required",
    "ref",
}


class ReceiptInputError(ValueError):
    """A selector or journal is malformed or unsupported."""


class StateError(RuntimeError):
    """Private state ownership or durability cannot be established."""


class LockBusy(StateError):
    """Another cooperating controller currently owns the mutation boundary."""


def validate_run_id(value: str) -> str:
    if not _RUN_ID.fullmatch(value):
        raise ReceiptInputError(
            "run id must be exactly 32 lowercase hexadecimal characters"
        )
    return value


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ReceiptInputError(f"{label} must be a JSON object")
    return cast("dict[str, object]", value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReceiptInputError(f"{label} must be a nonempty NUL-free string")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _digest(value: object, label: str) -> str:
    result = _text(value, label)
    if not _DIGEST.fullmatch(result):
        raise ReceiptInputError(f"{label} must be a SHA-256 identity")
    return result


def _optional_digest(value: object, label: str) -> str | None:
    return None if value is None else _digest(value, label)


def _oid(value: object, label: str) -> str:
    result = _text(value, label)
    if not _OID.fullmatch(result):
        raise ReceiptInputError(f"{label} must be a full object identity")
    return result


def _optional_oid(value: object, label: str) -> str | None:
    return None if value is None else _oid(value, label)


def _json_value(value: object) -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, str) and "\x00" not in value:
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_value(item)
        return
    raise ReceiptInputError("receipt contains unsupported JSON data")


def _rows(value: object, label: str, allowed: set[str]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ReceiptInputError(f"{label} must be an explicit list")
    result: list[dict[str, object]] = []
    for item in value:
        row = _object(item, label)
        if set(row) != allowed:
            raise ReceiptInputError(f"{label} fields are missing or unsupported")
        _json_value(row)
        if "outcome" in row:
            _text(row["outcome"], f"{label}.outcome")
        for key in ("expected_oid", "actual_oid", "sha"):
            if key in row:
                _optional_oid(row[key], f"{label}.{key}")
        if allowed == _INTENT_KEYS:
            for key in ("key", "kind", "resource", "created_at"):
                _text(row[key], f"{label}.{key}")
            for key in ("namespace", "ref", "proof"):
                _optional_text(row[key], f"{label}.{key}")
            if not isinstance(row["required"], bool):
                raise ReceiptInputError("intent required flag must be a boolean")
            if row["kind"] not in {
                "merge",
                "fetch",
                "checkout",
                "verify",
                "delete_local",
                "delete_remote",
                "remove_worktree",
                "prune_tracking",
            } or row["outcome"] not in {"PENDING", "ACCEPTED", "CONFIRMED", "REJECTED"}:
                raise ReceiptInputError("unsupported operation intent")
        elif allowed == _VERIFICATION_KEYS:
            _oid(row["sha"], f"{label}.sha")
            _digest(row["command_identity"], "command_identity")
            if type(row["command_index"]) is not int or row["command_index"] < 0:
                raise ReceiptInputError("command index must be a nonnegative integer")
            if row["returncode"] is not None and type(row["returncode"]) is not int:
                raise ReceiptInputError("command returncode must be an integer or null")
            if row["outcome"] not in {
                "PASSED",
                "FAILED",
                "TIMED_OUT",
                "CHANGED_CHECKOUT",
            }:
                raise ReceiptInputError("unsupported command verification outcome")
            if row["outcome"] == "PASSED" and row["returncode"] != 0:
                raise ReceiptInputError("passed verification must have exit zero")
            if row["outcome"] == "FAILED" and (
                row["returncode"] is None or row["returncode"] == 0
            ):
                raise ReceiptInputError("failed verification must have a nonzero exit")
            if row["outcome"] == "TIMED_OUT" and row["returncode"] is not None:
                raise ReceiptInputError("timed-out verification has no completed exit")
        elif allowed == _CLEANUP_KEYS:
            for key in ("kind", "resource", "reason", "proof", "ref"):
                _text(row[key], f"{label}.{key}")
            _optional_text(row["namespace"], "cleanup namespace")
            if not isinstance(row["required"], bool):
                raise ReceiptInputError("cleanup required flag must be a boolean")
        result.append(row)
    return result


@dataclass
class Target:
    """The provider-confirmed PR a run lands; head/base revisions are refreshed."""

    host: str
    repo: str
    number: int
    head_sha: str
    base_sha: str
    head_ref: str
    head_repo: str
    base_ref: str


@dataclass
class GateRow:
    """Sanitized outcome of one gate command on one new commit (no raw output)."""

    name: str
    identity: str
    outcome: str
    returncode: int | None


@dataclass
class GroupRecord:
    """One planned logical commit: its exact parent/tree/message and validation."""

    id: str
    parent: str
    tree: str
    message_identity: str
    commit: str | None = None
    outcome: str = "PENDING"
    gates: list[GateRow] = field(default_factory=list)


@dataclass
class RefUpdate:
    """Journaled index and branch movement that publishes validated commits locally."""

    ref: str
    old: str | None
    new: str
    index_before: str
    index_after: str
    head_before: str | None
    head_after: str | None
    outcome: str = "PENDING"


@dataclass
class ChangesetRecord:
    """Snapshot-bound commit-plan execution state, recorded before each mutation."""

    plan_identity: str
    gates_identity: str
    source_snapshot: str
    source_head: str
    source_branch: str | None
    source_index: str
    base_ref: str
    base_oid: str
    branch: str
    mode: str
    groups: list[GroupRecord] = field(default_factory=list)
    update: RefUpdate | None = None
    confirmed: list[str] = field(default_factory=list)
    residual_snapshot: str | None = None
    preserved: str | None = None


def _gate_row(value: object) -> GateRow:
    raw = _object(value, "changeset gate row")
    if set(raw) != _GATE_ROW_KEYS:
        raise ReceiptInputError("changeset gate fields are missing or unsupported")
    name = _text(raw["name"], "gate name")
    if not _GATE_NAME.fullmatch(name):
        raise ReceiptInputError("gate name is not a supported identifier")
    outcome = _text(raw["outcome"], "gate outcome")
    returncode = raw["returncode"]
    if outcome not in _GATE_OUTCOMES:
        raise ReceiptInputError("unsupported gate outcome")
    if returncode is not None and type(returncode) is not int:
        raise ReceiptInputError("gate returncode must be an integer or null")
    if (outcome == "PASSED") != (returncode == 0):
        raise ReceiptInputError("only a zero exit is a passed gate")
    if outcome == "TIMED_OUT" and returncode is not None:
        raise ReceiptInputError("timed-out gate has no completed exit")
    if outcome == "FAILED" and returncode is None:
        raise ReceiptInputError("failed gate needs its nonzero exit")
    return GateRow(name, _digest(raw["identity"], "gate identity"), outcome, returncode)


def _group_record(value: object) -> GroupRecord:
    raw = _object(value, "changeset group")
    if set(raw) != _GROUP_KEYS:
        raise ReceiptInputError("changeset group fields are missing or unsupported")
    group_id = _text(raw["id"], "group id")
    if not _GROUP_ID.fullmatch(group_id):
        raise ReceiptInputError("group id is not a supported identifier")
    outcome = _text(raw["outcome"], "group outcome")
    if outcome not in _GROUP_OUTCOMES:
        raise ReceiptInputError("unsupported group outcome")
    if not isinstance(raw["gates"], list):
        raise ReceiptInputError("group gates must be an explicit list")
    gates = [_gate_row(row) for row in raw["gates"]]
    commit = _optional_oid(raw["commit"], "group commit")
    if outcome == "VALIDATED" and (
        commit is None or not gates or any(row.outcome != "PASSED" for row in gates)
    ):
        raise ReceiptInputError("a validated group needs its commit and passed gates")
    return GroupRecord(
        group_id,
        _oid(raw["parent"], "group parent"),
        _oid(raw["tree"], "group tree"),
        _digest(raw["message_identity"], "group message identity"),
        commit,
        outcome,
        gates,
    )


def _ref_update(value: object) -> RefUpdate:
    raw = _object(value, "changeset update")
    if set(raw) != _UPDATE_KEYS:
        raise ReceiptInputError("changeset update fields are missing or unsupported")
    ref = _text(raw["ref"], "update ref")
    if not ref.startswith("refs/heads/") or len(ref) == len("refs/heads/"):
        raise ReceiptInputError("update ref must be a full local branch ref")
    outcome = _text(raw["outcome"], "update outcome")
    if outcome not in _UPDATE_OUTCOMES:
        raise ReceiptInputError("unsupported update outcome")
    return RefUpdate(
        ref,
        _optional_oid(raw["old"], "update old"),
        _oid(raw["new"], "update new"),
        _digest(raw["index_before"], "index_before"),
        _digest(raw["index_after"], "index_after"),
        _optional_text(raw["head_before"], "head_before"),
        _optional_text(raw["head_after"], "head_after"),
        outcome,
    )


def _changeset(value: object) -> ChangesetRecord | None:
    if value is None:
        return None
    raw = _object(value, "changeset")
    keys = set(raw)
    if not _CHANGESET_KEYS <= keys <= _CHANGESET_KEYS | _CHANGESET_OPTIONAL_KEYS:
        raise ReceiptInputError("changeset fields are missing or unsupported")
    mode = _text(raw["mode"], "changeset mode")
    if mode not in CHANGESET_MODES:
        raise ReceiptInputError("unsupported changeset placement mode")
    if not isinstance(raw["groups"], list) or not isinstance(raw["confirmed"], list):
        raise ReceiptInputError("changeset groups/confirmed must be explicit lists")
    groups = [_group_record(group) for group in raw["groups"]]
    if len({group.id for group in groups}) != len(groups):
        raise ReceiptInputError("changeset group ids must be unique")
    update = None if raw["update"] is None else _ref_update(raw["update"])
    confirmed = [_oid(oid, "confirmed commit") for oid in raw["confirmed"]]
    residual = _optional_digest(raw["residual_snapshot"], "residual_snapshot")
    preserved = _optional_digest(raw.get("preserved"), "preserved")
    if preserved is not None and update is None:
        raise ReceiptInputError(
            "a preserved-work identity belongs to a journaled update"
        )
    if update is not None:
        commits = [group.commit for group in groups]
        if (
            not groups
            or any(group.outcome != "VALIDATED" for group in groups)
            or commits[-1] != update.new
        ):
            raise ReceiptInputError(
                "a journaled update must publish exactly the validated group chain"
            )
    confirmed_update = update is not None and update.outcome == "CONFIRMED"
    if confirmed_update != (residual is not None):
        raise ReceiptInputError(
            "residual snapshot is recorded exactly when the update is confirmed"
        )
    if confirmed_update and not set(
        cast("list[str]", [group.commit for group in groups])
    ) <= set(confirmed):
        raise ReceiptInputError("confirmed commits must include the published groups")
    return ChangesetRecord(
        plan_identity=_digest(raw["plan_identity"], "plan_identity"),
        gates_identity=_digest(raw["gates_identity"], "gates_identity"),
        source_snapshot=_digest(raw["source_snapshot"], "source_snapshot"),
        source_head=_oid(raw["source_head"], "source_head"),
        source_branch=_optional_text(raw["source_branch"], "source_branch"),
        source_index=_digest(raw["source_index"], "source_index"),
        base_ref=_text(raw["base_ref"], "base_ref"),
        base_oid=_oid(raw["base_oid"], "base_oid"),
        branch=_text(raw["branch"], "branch"),
        mode=mode,
        groups=groups,
        update=update,
        confirmed=confirmed,
        residual_snapshot=residual,
        preserved=preserved,
    )


def _target(raw: dict[str, object]) -> Target | None:
    values = [raw[key] for key in TARGET_KEYS]
    if all(value is None for value in values):
        return None
    number = raw["number"]
    if type(number) is not int or number <= 0:
        raise ReceiptInputError("receipt PR number must be a positive integer")
    host = _text(raw["host"], "host")
    repo = _text(raw["repo"], "repo")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host) or not _REPO_NAME.fullmatch(repo):
        raise ReceiptInputError("invalid receipt provider namespace")
    head_repo = raw["head_repo"]
    if not isinstance(head_repo, str) or "\x00" in head_repo:
        raise ReceiptInputError("head repository must be a NUL-free string")
    if head_repo and not _REPO_NAME.fullmatch(head_repo):
        raise ReceiptInputError("invalid receipt head namespace")
    return Target(
        host=host,
        repo=repo,
        number=number,
        head_sha=_oid(raw["head_sha"], "head_sha"),
        base_sha=_oid(raw["base_sha"], "base_sha"),
        head_ref=_text(raw["head_ref"], "head_ref"),
        head_repo=head_repo,
        base_ref=_text(raw["base_ref"], "base_ref"),
    )


@dataclass
class Receipt:
    run_id: str
    endpoint: str
    code_identity: str
    policy_identity: str | None
    inventory_identity: str
    target: Target | None
    status: str = "WAITING"
    evidence_identity: str | None = None
    merge_sha: str | None = None
    merge_verified: bool = False
    validation_sha: str | None = None
    validation_policy: str | None = None
    verification: list[dict[str, object]] = field(default_factory=list)
    intents: list[dict[str, object]] = field(default_factory=list)
    cleanup: dict[str, list[dict[str, object]]] = field(
        default_factory=lambda: {"removed": [], "retained": [], "failed": []}
    )
    issue: str | None = None
    next_action: str = "reconcile current target facts"
    changeset: ChangesetRecord | None = None

    def bound(self) -> Target:
        """The confirmed PR target; a pre-publication run has none to land."""
        if self.target is None:
            raise StateError("run has no provider-confirmed PR target yet")
        return self.target

    @property
    def host(self) -> str:
        return self.bound().host

    @property
    def repo(self) -> str:
        return self.bound().repo

    @property
    def number(self) -> int:
        return self.bound().number

    @property
    def head_sha(self) -> str:
        return self.bound().head_sha

    @head_sha.setter
    def head_sha(self, value: str) -> None:
        self.bound().head_sha = value

    @property
    def base_sha(self) -> str:
        return self.bound().base_sha

    @base_sha.setter
    def base_sha(self, value: str) -> None:
        self.bound().base_sha = value

    @property
    def head_ref(self) -> str:
        return self.bound().head_ref

    @head_ref.setter
    def head_ref(self, value: str) -> None:
        self.bound().head_ref = value

    @property
    def head_repo(self) -> str:
        return self.bound().head_repo

    @head_repo.setter
    def head_repo(self, value: str) -> None:
        self.bound().head_repo = value

    @property
    def base_ref(self) -> str:
        return self.bound().base_ref

    @base_ref.setter
    def base_ref(self, value: str) -> None:
        self.bound().base_ref = value

    def serialize(self) -> dict[str, object]:
        data = asdict(self)
        target = data.pop("target")
        for key in TARGET_KEYS:
            data[key] = None if target is None else target[key]
        return {"schema_version": SCHEMA_VERSION, **data}

    @classmethod
    def parse(cls, value: object) -> Receipt:
        raw = _object(value, "receipt")
        version = raw.get("schema_version")
        if type(version) is not int or version not in (
            _LEGACY_SCHEMA_VERSION,
            SCHEMA_VERSION,
        ):
            raise ReceiptInputError("unsupported receipt schema version")
        fields = (set(cls.__dataclass_fields__) - {"target"}) | set(TARGET_KEYS)
        if version == _LEGACY_SCHEMA_VERSION:
            # Exact v1 migration: PR-number receipts gain no changeset and must
            # keep a complete target; nothing else is defaulted or reinterpreted.
            if set(raw) != (fields - {"changeset"}) | {"schema_version"}:
                raise ReceiptInputError("receipt fields are missing or unsupported")
            if any(raw[key] is None for key in TARGET_KEYS):
                raise ReceiptInputError("legacy receipt must name its complete target")
            raw = {**raw, "schema_version": SCHEMA_VERSION, "changeset": None}
        if set(raw) != fields | {"schema_version"}:
            raise ReceiptInputError("receipt fields are missing or unsupported")
        endpoint = _text(raw["endpoint"], "endpoint")
        status = _text(raw["status"], "status")
        if endpoint not in _ENDPOINTS or status not in _STATUSES:
            raise ReceiptInputError("unsupported receipt endpoint or status")
        target = _target(raw)
        changeset = _changeset(raw["changeset"])
        verified = raw["merge_verified"]
        if not isinstance(verified, bool):
            raise ReceiptInputError("merge_verified must be a boolean")
        if target is None:
            lifecycle = (
                raw["merge_sha"],
                raw["validation_sha"],
                raw["validation_policy"],
                raw["evidence_identity"],
            )
            if (
                changeset is None
                or verified
                or any(item is not None for item in lifecycle)
                or raw["verification"] != []
                or raw["intents"] != []
                or status == "COMPLETE"
            ):
                raise ReceiptInputError(
                    "a run without a confirmed PR target holds only changeset state"
                )
        if verified and raw["merge_sha"] is None:
            raise ReceiptInputError("verified merge needs a landing identity")
        if raw["validation_sha"] is not None and (
            not verified
            or raw["policy_identity"] is None
            or raw["validation_policy"] != raw["policy_identity"]
        ):
            raise ReceiptInputError(
                "validation must be bound to the verified merge and policy"
            )
        if (
            status == "COMPLETE"
            and endpoint != "pr"
            and (
                not verified
                or raw["validation_sha"] is None
                or raw["policy_identity"] is None
            )
        ):
            raise ReceiptInputError(
                "completion needs reachable landing and acceptance evidence"
            )
        cleanup = _object(raw["cleanup"], "cleanup")
        if set(cleanup) != {"removed", "retained", "failed"}:
            raise ReceiptInputError("cleanup dispositions are missing or unsupported")
        if status == "COMPLETE" and endpoint == "clean" and cleanup["failed"] != []:
            raise ReceiptInputError(
                "cleanup completion cannot retain failed required actions"
            )
        if target is None and any(cleanup[key] != [] for key in cleanup):
            raise ReceiptInputError("a run without a PR target has no cleanup facts")
        return cls(
            run_id=validate_run_id(_text(raw["run_id"], "run_id")),
            endpoint=endpoint,
            code_identity=_digest(raw["code_identity"], "code_identity"),
            policy_identity=_optional_digest(raw["policy_identity"], "policy_identity"),
            inventory_identity=_digest(raw["inventory_identity"], "inventory_identity"),
            target=target,
            status=status,
            evidence_identity=_optional_digest(
                raw["evidence_identity"], "evidence_identity"
            ),
            merge_sha=_optional_oid(raw["merge_sha"], "merge_sha"),
            merge_verified=verified,
            validation_sha=_optional_oid(raw["validation_sha"], "validation_sha"),
            validation_policy=_optional_digest(
                raw["validation_policy"], "validation_policy"
            ),
            verification=_rows(raw["verification"], "verification", _VERIFICATION_KEYS),
            intents=_rows(raw["intents"], "intents", _INTENT_KEYS),
            cleanup={
                key: _rows(cleanup[key], f"cleanup.{key}", _CLEANUP_KEYS)
                for key in ("removed", "retained", "failed")
            },
            issue=_optional_text(raw["issue"], "issue"),
            next_action=_text(raw["next_action"], "next_action"),
            changeset=changeset,
        )


class Store:
    def __init__(self, common_dir: Path) -> None:
        if os.name != "posix":
            raise StateError("lifecycle receipts require a POSIX platform")
        self.common_dir = common_dir.resolve(strict=True)
        self.directory = self.common_dir / "armory" / "ship"
        self._loaded: dict[str, str | None] = {}

    def _directories(self, *, create: bool) -> bool:
        for path in (self.common_dir, self.common_dir / "armory", self.directory):
            try:
                info = path.lstat()
            except FileNotFoundError:
                if not create:
                    return False
                try:
                    path.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                raise StateError("journal directory ownership is unsafe")
            if info.st_mode & 0o022:
                raise StateError("journal directory is writable by another account")
        return True

    @staticmethod
    def _private_file(info: os.stat_result) -> None:
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise StateError("journal file ownership or permissions are unsafe")

    def _bytes(self, path: Path) -> bytes:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(path, flags)
        try:
            self._private_file(os.fstat(fd))
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ReceiptInputError("receipt exceeds the supported size")
            return data
        finally:
            os.close(fd)

    def load(self, run_id: str) -> Receipt:
        validate_run_id(run_id)
        if not self._directories(create=False):
            self._loaded[run_id] = None
            raise FileNotFoundError("requested receipt does not exist")
        path = self.directory / f"{run_id}.json"
        try:
            data = self._bytes(path)
        except FileNotFoundError:
            self._loaded[run_id] = None
            raise
        try:
            raw: object = json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise ReceiptInputError("receipt JSON is malformed") from error
        receipt = Receipt.parse(raw)
        if receipt.run_id != run_id:
            raise ReceiptInputError("receipt identity does not match its filename")
        self._loaded[run_id] = hashlib.sha256(data).hexdigest()
        return receipt

    def list_runs(self) -> tuple[Receipt, ...]:
        if not self._directories(create=False):
            return ()
        return tuple(
            self.load(path.stem)
            for path in sorted(self.directory.iterdir())
            if path.name.endswith(".json")
        )

    def save(self, receipt: Receipt) -> None:
        payload = receipt.serialize()
        Receipt.parse(payload)
        self._directories(create=True)
        target = self.directory / f"{receipt.run_id}.json"
        try:
            current = hashlib.sha256(self._bytes(target)).hexdigest()
        except FileNotFoundError:
            current = None
        if current != self._loaded.get(receipt.run_id):
            raise StateError(
                "receipt changed outside this controller; reload current facts"
            )
        data = (
            json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        fd, filename = tempfile.mkstemp(
            prefix=f".{receipt.run_id}.", dir=self.directory
        )
        temporary = Path(filename)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self._loaded[receipt.run_id] = hashlib.sha256(data).hexdigest()
        finally:
            if temporary.exists():
                temporary.unlink()

    @contextmanager
    def mutation_lock(self) -> Iterator[None]:
        if os.name != "posix":
            raise StateError("cooperative mutation locking requires a POSIX platform")
        import fcntl

        self._directories(create=True)
        path = self.directory / "mutation.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(fd)
            self._private_file(info)
            if info.st_size:
                raise StateError("unfamiliar mutation lock file; do not clear it")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise LockBusy(
                    "another controller owns this Git common-directory lock"
                ) from error
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
