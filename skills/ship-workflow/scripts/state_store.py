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

SCHEMA_VERSION = 1
_RUN_ID = re.compile(r"[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_STATUSES = {"COMPLETE", "WAITING", "NEEDS_JUDGMENT", "BLOCKED"}
_ENDPOINTS = {"pr", "merged", "clean"}
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
class Receipt:
    run_id: str
    host: str
    repo: str
    number: int
    endpoint: str
    code_identity: str
    policy_identity: str | None
    inventory_identity: str
    head_sha: str
    base_sha: str
    head_ref: str
    head_repo: str
    base_ref: str
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

    def serialize(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def parse(cls, value: object) -> Receipt:
        raw = _object(value, "receipt")
        names = set(cls.__dataclass_fields__) | {"schema_version"}
        if set(raw) != names:
            raise ReceiptInputError("receipt fields are missing or unsupported")
        if (
            type(raw["schema_version"]) is not int
            or raw["schema_version"] != SCHEMA_VERSION
        ):
            raise ReceiptInputError("unsupported receipt schema version")
        number = raw["number"]
        if type(number) is not int or number <= 0:
            raise ReceiptInputError("receipt PR number must be a positive integer")
        endpoint = _text(raw["endpoint"], "endpoint")
        status = _text(raw["status"], "status")
        if endpoint not in _ENDPOINTS or status not in _STATUSES:
            raise ReceiptInputError("unsupported receipt endpoint or status")
        host = _text(raw["host"], "host")
        repo = _text(raw["repo"], "repo")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*", repo
        ):
            raise ReceiptInputError("invalid receipt provider namespace")
        verified = raw["merge_verified"]
        if not isinstance(verified, bool):
            raise ReceiptInputError("merge_verified must be a boolean")
        head_repo = raw["head_repo"]
        if not isinstance(head_repo, str) or "\x00" in head_repo:
            raise ReceiptInputError("head repository must be a NUL-free string")
        if head_repo and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*", head_repo
        ):
            raise ReceiptInputError("invalid receipt head namespace")
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
        return cls(
            run_id=validate_run_id(_text(raw["run_id"], "run_id")),
            host=host,
            repo=repo,
            number=number,
            endpoint=endpoint,
            code_identity=_digest(raw["code_identity"], "code_identity"),
            policy_identity=_optional_digest(raw["policy_identity"], "policy_identity"),
            inventory_identity=_digest(raw["inventory_identity"], "inventory_identity"),
            head_sha=_oid(raw["head_sha"], "head_sha"),
            base_sha=_oid(raw["base_sha"], "base_sha"),
            head_ref=_text(raw["head_ref"], "head_ref"),
            head_repo=head_repo,
            base_ref=_text(raw["base_ref"], "base_ref"),
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
