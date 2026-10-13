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
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

SCHEMA_VERSION = 3
_LEGACY_SCHEMA_VERSION = 1
_CHANGESET_SCHEMA_VERSION = 2
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
# Journaled before an index/ref update writes; absent in historical receipts, where
# absence means unknown (never a fabricated baseline) and is never rewritten on load.
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
_PUBLICATION_KEYS = {
    "host",
    "base_repo",
    "base_ref",
    "base_oid",
    "head_repo",
    "head_ref",
    "remote",
    "head",
    "validated_head",
    "push",
    "create",
    "decision_identity",
}
_PUSH_KEYS = {"old", "new", "outcome"}
_CREATE_KEYS = {"title_identity", "body_identity", "created_at", "outcome", "number"}
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
# Stack-graph master journals are a separate document kind with their own version,
# stored in a subdirectory so receipt enumeration never meets them.
GRAPH_SCHEMA_VERSION = 1
GRAPH_KIND = "stack-graph"
GRAPH_NODE_STATES = ("PENDING", "PROMOTED", "LANDED", "RETAINED")
GRAPH_INTENT_KINDS = ("capture", "rewrite-push", "retarget", "advance-local")
_GRAPH_MAX_NODES = 64
GRAPH_MAX_INTENTS = 1024
_GRAPH_MAX_COMMITS = 10_000
_GRAPH_DETAIL_CHARS = 512
_PR_MAX = 2**31 - 1
_HOST_NAME = re.compile(r"[a-z0-9][a-z0-9.-]*")
_INTENT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_BRANCH_FORBIDDEN = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


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


def validate_branch(value: object, label: str) -> str:
    """A short branch name that ``git check-ref-format`` accepts under refs/heads/."""
    name = _text(value, label)
    if (
        len(name.encode("utf-8")) > 255
        or name in ("HEAD", "@")
        or name.startswith(("-", "/", "refs/"))
        or name.endswith(("/", "."))
        or _BRANCH_FORBIDDEN.search(name)
        or any(token in name for token in ("..", "@{", "//"))
        or any(
            part.startswith(".") or part.endswith(".lock") for part in name.split("/")
        )
    ):
        raise ReceiptInputError(f"{label} must be a short branch name Git accepts")
    return name


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


@dataclass
class PushRecord:
    """Journaled guarded push: the exact expected remote and intended head."""

    old: str | None
    new: str
    outcome: str = "PENDING"


@dataclass
class CreateRecord:
    """Journaled PR creation; content is identified by hashes, never stored."""

    title_identity: str
    body_identity: str
    created_at: str
    outcome: str = "PENDING"
    number: int | None = None


@dataclass
class PublicationRecord:
    """Intended head/base identities of a publication; fork namespaces stay separate."""

    host: str
    base_repo: str
    base_ref: str
    base_oid: str | None
    head_repo: str
    head_ref: str
    remote: str
    head: str
    validated_head: str | None = None
    push: PushRecord | None = None
    create: CreateRecord | None = None
    decision_identity: str | None = None


def _publication(value: object) -> PublicationRecord | None:
    if value is None:
        return None
    raw = _object(value, "publication")
    if set(raw) not in (_PUBLICATION_KEYS, _PUBLICATION_KEYS - {"decision_identity"}):
        raise ReceiptInputError("publication fields are missing or unsupported")
    host = _text(raw["host"], "publication host")
    base_repo = _text(raw["base_repo"], "publication base repository")
    head_repo = _text(raw["head_repo"], "publication head repository")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host) or not all(
        _REPO_NAME.fullmatch(name) for name in (base_repo, head_repo)
    ):
        raise ReceiptInputError("invalid publication provider namespace")
    head = _oid(raw["head"], "publication head")
    push: PushRecord | None = None
    if raw["push"] is not None:
        row = _object(raw["push"], "publication push")
        if set(row) != _PUSH_KEYS:
            raise ReceiptInputError("push fields are missing or unsupported")
        outcome = _text(row["outcome"], "push outcome")
        if outcome not in _UPDATE_OUTCOMES:
            raise ReceiptInputError("unsupported push outcome")
        push = PushRecord(
            _optional_oid(row["old"], "push old"), _oid(row["new"], "push new"), outcome
        )
        if push.new != head:
            raise ReceiptInputError("the journaled push must publish the intended head")
    create: CreateRecord | None = None
    if raw["create"] is not None:
        row = _object(raw["create"], "publication create")
        if set(row) != _CREATE_KEYS:
            raise ReceiptInputError("create fields are missing or unsupported")
        outcome = _text(row["outcome"], "create outcome")
        number = row["number"]
        if outcome not in _UPDATE_OUTCOMES:
            raise ReceiptInputError("unsupported create outcome")
        if number is not None and (type(number) is not int or number <= 0):
            raise ReceiptInputError("created PR number must be a positive integer")
        if (outcome == "CONFIRMED") != (number is not None):
            raise ReceiptInputError("exactly a confirmed creation names its PR")
        create = CreateRecord(
            _digest(row["title_identity"], "title identity"),
            _digest(row["body_identity"], "body identity"),
            _text(row["created_at"], "created_at"),
            outcome,
            number,
        )
    return PublicationRecord(
        host=host,
        base_repo=base_repo,
        base_ref=_text(raw["base_ref"], "publication base ref"),
        base_oid=_optional_oid(raw["base_oid"], "publication base oid"),
        head_repo=head_repo,
        head_ref=_text(raw["head_ref"], "publication head ref"),
        remote=_text(raw["remote"], "publication remote"),
        head=head,
        validated_head=_optional_oid(raw["validated_head"], "validated head"),
        push=push,
        create=create,
        decision_identity=_optional_digest(
            raw.get("decision_identity"), "publication decision identity"
        ),
    )


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
    publication: PublicationRecord | None = None

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
            _CHANGESET_SCHEMA_VERSION,
            SCHEMA_VERSION,
        ):
            raise ReceiptInputError("unsupported receipt schema version")
        fields = (set(cls.__dataclass_fields__) - {"target"}) | set(TARGET_KEYS)
        if version == _LEGACY_SCHEMA_VERSION:
            # Exact v1 migration: PR-number receipts gain no changeset/publication
            # and keep a complete target; nothing else is defaulted or reinterpreted.
            legacy = fields - {"changeset", "publication"}
            if set(raw) != legacy | {"schema_version"}:
                raise ReceiptInputError("receipt fields are missing or unsupported")
            if any(raw[key] is None for key in TARGET_KEYS):
                raise ReceiptInputError("legacy receipt must name its complete target")
            raw = {**raw, "changeset": None}
        if version in (_LEGACY_SCHEMA_VERSION, _CHANGESET_SCHEMA_VERSION):
            # Schema 2 had no publication journal; nothing was ever published by it.
            if "publication" in raw:
                raise ReceiptInputError("receipt fields are missing or unsupported")
            raw = {**raw, "schema_version": SCHEMA_VERSION, "publication": None}
        if set(raw) != fields | {"schema_version"}:
            raise ReceiptInputError("receipt fields are missing or unsupported")
        endpoint = _text(raw["endpoint"], "endpoint")
        status = _text(raw["status"], "status")
        if endpoint not in _ENDPOINTS or status not in _STATUSES:
            raise ReceiptInputError("unsupported receipt endpoint or status")
        target = _target(raw)
        changeset = _changeset(raw["changeset"])
        publication = _publication(raw["publication"])
        verified = raw["merge_verified"]
        if not isinstance(verified, bool):
            raise ReceiptInputError("merge_verified must be a boolean")
        created = None if publication is None else publication.create
        if (
            target is not None
            and created is not None
            and created.number is not None
            and created.number != target.number
        ):
            raise ReceiptInputError("the bound target is not the PR this run created")
        if target is None:
            lifecycle = (
                raw["merge_sha"],
                raw["validation_sha"],
                raw["validation_policy"],
                raw["evidence_identity"],
            )
            if (
                (changeset is None and publication is None)
                or verified
                or any(item is not None for item in lifecycle)
                or raw["verification"] != []
                or raw["intents"] != []
                or status == "COMPLETE"
            ):
                raise ReceiptInputError(
                    "a run without a confirmed PR target holds only changeset or "
                    "publication state"
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
            publication=publication,
        )


@dataclass
class Promotion:
    """Journaled proof of one child promotion onto its landed parent's trunk tip.

    ``fork`` is the recorded old parent head F the child slice sits on, ``old_head``
    the child head that slice was captured from, ``landing`` the observed trunk tip
    L, ``expected_tree`` the clean three-way merge tree (base F, ours L, theirs
    ``old_head``), ``new_head`` the replayed head with exactly that tree and
    ``commits`` the replayed slice length; ``slice_identity`` optionally identifies
    the slice. ``verified`` records that the proof held before any push.
    """

    fork: str
    old_head: str
    landing: str
    expected_tree: str
    new_head: str
    commits: int
    slice_identity: str | None
    verified: bool


@dataclass
class GraphNode:
    """One stack-graph node; current provider facts always beat these rows.

    ``head_sha``/``base_ref`` are the last confirmed provider head and base.
    ``decision_identity`` and the preassigned per-node lifecycle ``run_id`` belong
    only to selected nodes. ``fork``, ``old_head`` and ``captured_at`` are recorded
    together, with one CONFIRMED ``capture`` intent, before the parent's merge is
    dispatched. ``state`` is informational, yet consistent: exactly unselected nodes
    are RETAINED, PROMOTED needs a verified promotion and LANDED its node run id.
    """

    pr: int
    parent: int | None
    selected: bool
    head_repo: str
    head_ref: str
    head_sha: str
    base_ref: str
    decision_identity: str | None
    run_id: str | None = None
    fork: str | None = None
    old_head: str | None = None
    captured_at: str | None = None
    promotion: Promotion | None = None
    state: str = "PENDING"


@dataclass
class GraphIntent:
    """A graph-level mutation journaled before dispatch and reconciled after.

    ``resource`` is ``pull/<pr>`` for ``capture``/``retarget`` and a full
    ``refs/heads/`` branch ref for ``rewrite-push``/``advance-local``. Every kind
    names both identities, so ``expected_old``/``new`` are never null: OIDs, except
    a ``retarget``'s old (the parent's head ref) and new (the trunk) base branch
    names. A ``capture`` records the child's old head and the parent head F; it is
    never dispatched, so it is only ever CONFIRMED. ``actual`` is the observed
    identity once reconciled: CONFIRMED observed ``new``; REJECTED anything else.
    """

    key: str
    kind: str
    pr: int
    resource: str
    expected_old: str
    new: str
    created_at: str
    outcome: str = "PENDING"
    actual: str | None = None
    detail: str | None = None


@dataclass
class GraphJournal:
    """The master journal of one stack-graph run; per-node receipts stay separate.

    ``plan`` is the canonical normalized stack plan this run froze; it is validated
    here only as bounded JSON, and ``graph.journal_plan`` cross-checks it against
    ``plan_identity``, ``topology`` and the node rows.
    """

    run_id: str
    host: str
    repo: str
    trunk: str
    endpoint: str
    plan_identity: str
    topology: str
    plan: dict[str, object]
    code_identity: str
    nodes: list[GraphNode]
    created_at: str
    updated_at: str
    intents: list[GraphIntent] = field(default_factory=list)
    status: str = "WAITING"
    issue: str | None = None
    next_action: str | None = None
    kind: Literal["stack-graph"] = "stack-graph"

    def node(self, pr: int) -> GraphNode:
        for node in self.nodes:
            if node.pr == pr:
                return node
        raise StateError(f"PR #{pr} is not a node of this graph run")

    def serialize(self) -> dict[str, object]:
        return {"schema_version": GRAPH_SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def parse(cls, value: object) -> GraphJournal:
        raw = _object(value, "graph journal")
        version = raw.get("schema_version")
        if type(version) is not int or version != GRAPH_SCHEMA_VERSION:
            raise ReceiptInputError("unsupported graph journal schema version")
        if set(raw) != set(cls.__dataclass_fields__) | {"schema_version"}:
            raise ReceiptInputError("graph journal fields are missing or unsupported")
        if raw["kind"] != GRAPH_KIND:
            raise ReceiptInputError("journal is not a stack-graph journal")
        host = _text(raw["host"], "graph host")
        repo = _text(raw["repo"], "graph repo")
        if not (_HOST_NAME.fullmatch(host) and _REPO_NAME.fullmatch(repo)):
            raise ReceiptInputError("invalid graph provider namespace")
        endpoint = _text(raw["endpoint"], "graph endpoint")
        status = _text(raw["status"], "graph status")
        if endpoint not in _ENDPOINTS or status not in _STATUSES:
            raise ReceiptInputError("unsupported graph endpoint or status")
        plan = _object(raw["plan"], "graph plan")
        _json_value(plan)
        nodes, intents = raw["nodes"], raw["intents"]
        if not isinstance(nodes, list) or not 0 < len(nodes) <= _GRAPH_MAX_NODES:
            raise ReceiptInputError(
                f"graph journal needs between 1 and {_GRAPH_MAX_NODES} nodes"
            )
        if not isinstance(intents, list) or len(intents) > GRAPH_MAX_INTENTS:
            raise ReceiptInputError(
                f"graph journal holds at most {GRAPH_MAX_INTENTS} intents"
            )
        journal = cls(
            run_id=validate_run_id(_text(raw["run_id"], "run_id")),
            host=host,
            repo=repo,
            trunk=validate_branch(raw["trunk"], "graph trunk"),
            endpoint=endpoint,
            plan_identity=_digest(raw["plan_identity"], "plan_identity"),
            topology=_digest(raw["topology"], "topology"),
            plan=plan,
            code_identity=_digest(raw["code_identity"], "code_identity"),
            nodes=[_graph_node(row) for row in nodes],
            created_at=_timestamp(raw["created_at"], "created_at"),
            updated_at=_timestamp(raw["updated_at"], "updated_at"),
            intents=[_graph_intent(row) for row in intents],
            status=status,
            issue=_optional_text(raw["issue"], "issue"),
            next_action=_optional_text(raw["next_action"], "next_action"),
        )
        _check_graph_nodes(journal)
        _check_graph_intents(journal)
        _check_graph_completion(journal)
        return journal


def _pr_number(value: object, label: str) -> int:
    if type(value) is not int or not 0 < value <= _PR_MAX:
        raise ReceiptInputError(f"{label} must be a positive PR number")
    return value


def _timestamp(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ReceiptInputError(f"{label} must be an ISO-8601 timestamp") from error
    if len(text) > 64 or parsed.tzinfo is None:
        raise ReceiptInputError(f"{label} must be a timezone-aware ISO-8601 timestamp")
    return text


def _plain(value: object, label: str, limit: int) -> str:
    text = _text(value, label)
    if len(text) > limit or _CONTROL.search(text):
        raise ReceiptInputError(
            f"{label} must be plain text of at most {limit} characters"
        )
    return text


def _promotion(value: object, label: str) -> Promotion:
    raw = _object(value, label)
    if set(raw) != set(Promotion.__dataclass_fields__):
        raise ReceiptInputError(f"{label} fields are missing or unsupported")
    commits = raw["commits"]
    if type(commits) is not int or not 0 < commits <= _GRAPH_MAX_COMMITS:
        raise ReceiptInputError(f"{label} must replay a bounded nonempty slice")
    verified = raw["verified"]
    if not isinstance(verified, bool):
        raise ReceiptInputError(f"{label} verified flag must be a boolean")
    promotion = Promotion(
        fork=_oid(raw["fork"], f"{label} fork"),
        old_head=_oid(raw["old_head"], f"{label} old head"),
        landing=_oid(raw["landing"], f"{label} landing"),
        expected_tree=_oid(raw["expected_tree"], f"{label} expected tree"),
        new_head=_oid(raw["new_head"], f"{label} new head"),
        commits=commits,
        slice_identity=_optional_digest(raw["slice_identity"], f"{label} slice"),
        verified=verified,
    )
    if len({promotion.fork, promotion.old_head, promotion.new_head}) != 3:
        raise ReceiptInputError(f"{label} must move a nonempty slice to a new head")
    return promotion


def _graph_node(value: object) -> GraphNode:
    raw = _object(value, "graph node")
    if set(raw) != set(GraphNode.__dataclass_fields__):
        raise ReceiptInputError("graph node fields are missing or unsupported")
    pr = _pr_number(raw["pr"], "graph node pr")
    label = f"graph node #{pr}"
    parent = (
        None if raw["parent"] is None else _pr_number(raw["parent"], f"{label} parent")
    )
    selected = raw["selected"]
    if not isinstance(selected, bool):
        raise ReceiptInputError(f"{label} selected flag must be a boolean")
    head_repo = _text(raw["head_repo"], f"{label} head repository")
    if not _REPO_NAME.fullmatch(head_repo):
        raise ReceiptInputError(f"{label} head repository is invalid")
    state = _text(raw["state"], f"{label} state")
    if state not in GRAPH_NODE_STATES:
        raise ReceiptInputError(f"{label} has an unsupported state")
    capture = (raw["fork"], raw["old_head"], raw["captured_at"])
    if len({item is None for item in capture}) != 1:
        raise ReceiptInputError(f"{label} records fork, old head and time together")
    fork = _optional_oid(raw["fork"], f"{label} fork")
    old_head = _optional_oid(raw["old_head"], f"{label} old head")
    if fork is not None and (parent is None or fork == old_head):
        raise ReceiptInputError(f"{label} fork needs a parent and a nonempty slice")
    decision = _optional_digest(raw["decision_identity"], f"{label} decision")
    run_id = (
        None
        if raw["run_id"] is None
        else validate_run_id(_text(raw["run_id"], f"{label} run id"))
    )
    if selected != (decision is not None) or (not selected and run_id is not None):
        raise ReceiptInputError(
            f"{label}: exactly selected nodes carry a decision and a node run id"
        )
    if selected == (state == "RETAINED"):
        raise ReceiptInputError(f"{label}: exactly unselected nodes are RETAINED")
    if state == "LANDED" and run_id is None:
        raise ReceiptInputError(f"{label} is LANDED only through its node run")
    promotion = _node_promotion(raw, label, (fork, old_head) if selected else None)
    if state == "PROMOTED" and (promotion is None or not promotion.verified):
        raise ReceiptInputError(f"{label} is PROMOTED only by a verified promotion")
    return GraphNode(
        pr=pr,
        parent=parent,
        selected=selected,
        head_repo=head_repo,
        head_ref=validate_branch(raw["head_ref"], f"{label} head ref"),
        head_sha=_oid(raw["head_sha"], f"{label} head"),
        base_ref=validate_branch(raw["base_ref"], f"{label} base ref"),
        decision_identity=decision,
        run_id=run_id,
        fork=fork,
        old_head=old_head,
        captured_at=(
            None
            if raw["captured_at"] is None
            else _timestamp(raw["captured_at"], f"{label} captured_at")
        ),
        promotion=promotion,
        state=state,
    )


def _node_promotion(
    raw: dict[str, object], label: str, capture: tuple[str | None, str | None] | None
) -> Promotion | None:
    """A node's promotion; only a selected node (``capture`` given) may hold one,
    and it starts from exactly that node's captured fork and old head."""
    if raw["promotion"] is None:
        return None
    promotion = _promotion(raw["promotion"], label)
    if capture != (promotion.fork, promotion.old_head):
        raise ReceiptInputError(
            f"{label} promotion must start from the selected node's captured fork"
        )
    return promotion


def _graph_intent(value: object) -> GraphIntent:
    raw = _object(value, "graph intent")
    if set(raw) != set(GraphIntent.__dataclass_fields__):
        raise ReceiptInputError("graph intent fields are missing or unsupported")
    key = _text(raw["key"], "graph intent key")
    if not _INTENT_KEY.fullmatch(key):
        raise ReceiptInputError("graph intent key is not a supported identifier")
    label = f"graph intent {key}"
    kind = _text(raw["kind"], f"{label} kind")
    outcome = _text(raw["outcome"], f"{label} outcome")
    if kind not in GRAPH_INTENT_KINDS or outcome not in _UPDATE_OUTCOMES:
        raise ReceiptInputError(f"{label} has an unsupported kind or outcome")
    pr = _pr_number(raw["pr"], f"{label} pr")
    resource = _text(raw["resource"], f"{label} resource")
    if kind in ("capture", "retarget"):
        if resource != f"pull/{pr}":
            raise ReceiptInputError(f"{label} resource must be pull/{pr}")
    elif not resource.startswith("refs/heads/"):
        raise ReceiptInputError(f"{label} resource must be a full branch ref")
    else:
        validate_branch(resource.removeprefix("refs/heads/"), f"{label} resource")
    identity = validate_branch if kind == "retarget" else _oid
    expected_old = identity(raw["expected_old"], f"{label} expected old")
    new = identity(raw["new"], f"{label} new")
    actual = (
        None if raw["actual"] is None else identity(raw["actual"], f"{label} actual")
    )
    if expected_old == new:
        raise ReceiptInputError(f"{label} must change its resource")
    if (outcome == "PENDING" and actual is not None) or (
        outcome != "PENDING" and (outcome == "CONFIRMED") != (actual == new)
    ):
        raise ReceiptInputError(
            f"{label}: only a reconciled intent has an observed outcome, and only "
            "observing the new identity confirms it"
        )
    return GraphIntent(
        key=key,
        kind=kind,
        pr=pr,
        resource=resource,
        expected_old=expected_old,
        new=new,
        created_at=_timestamp(raw["created_at"], f"{label} created_at"),
        outcome=outcome,
        actual=actual,
        detail=(
            None
            if raw["detail"] is None
            else _plain(raw["detail"], f"{label} detail", _GRAPH_DETAIL_CHARS)
        ),
    )


def _check_graph_nodes(journal: GraphJournal) -> None:
    numbers = [node.pr for node in journal.nodes]
    if numbers != sorted(set(numbers)):
        raise ReceiptInputError("graph nodes must be unique and ordered by PR number")
    parents = {node.pr: node.parent for node in journal.nodes}
    for node in journal.nodes:
        if node.parent is not None and (
            node.parent == node.pr or node.parent not in parents
        ):
            raise ReceiptInputError(f"graph node #{node.pr} parent is not another node")
    for node in journal.nodes:
        current, steps = node.parent, 0
        while current is not None:
            steps += 1
            if steps > len(parents):
                raise ReceiptInputError("graph parent relation has a cycle")
            current = parents[current]
    run_ids = [node.run_id for node in journal.nodes if node.run_id is not None]
    if len(set(run_ids)) != len(run_ids) or journal.run_id in run_ids:
        raise ReceiptInputError(
            "per-node run ids must differ from each other and from the graph run"
        )


def _check_graph_intents(journal: GraphJournal) -> None:
    nodes = {node.pr: node for node in journal.nodes}
    keys: set[str] = set()
    pending: set[tuple[str, str]] = set()
    captured: set[int] = set()
    for intent in journal.intents:
        label = f"graph intent {intent.key}"
        node = nodes.get(intent.pr)
        if node is None:
            raise ReceiptInputError(f"{label} names a PR outside the graph")
        if intent.key in keys:
            raise ReceiptInputError("graph intent keys must be unique")
        keys.add(intent.key)
        if intent.outcome == "PENDING":
            if (intent.kind, intent.resource) in pending:
                raise ReceiptInputError(
                    f"{label} repeats an unreconciled intent for {intent.resource}"
                )
            pending.add((intent.kind, intent.resource))
        if intent.kind == "capture" and intent.outcome == "CONFIRMED":
            if intent.pr in captured:
                raise ReceiptInputError(f"{label}: a node has one confirmed capture")
            captured.add(intent.pr)
        parent = None if node.parent is None else nodes[node.parent]
        _check_intent_node(journal.trunk, node, parent, intent, label)
    for node in journal.nodes:
        if node.fork is not None and node.pr not in captured:
            raise ReceiptInputError(
                f"graph node #{node.pr} capture is not journaled by a capture intent"
            )
    if journal.endpoint == "pr" and journal.intents:
        raise ReceiptInputError("a pr-endpoint graph run is observation-only")
    if journal.status == "COMPLETE" and pending:
        raise ReceiptInputError("a complete graph run has no unreconciled intent")


def _check_graph_completion(journal: GraphJournal) -> None:
    """A landing endpoint completes only once every selected node has landed."""
    if journal.status != "COMPLETE" or journal.endpoint == "pr":
        return
    for node in journal.nodes:
        if node.selected and node.state != "LANDED":
            raise ReceiptInputError(
                "a complete graph run has landed every selected node; "
                f"#{node.pr} is {node.state}"
            )


def _check_intent_node(
    trunk: str,
    node: GraphNode,
    parent: GraphNode | None,
    intent: GraphIntent,
    label: str,
) -> None:
    if intent.kind == "capture":
        if parent is None:
            raise ReceiptInputError(f"{label} captures a fork of a trunk-based node")
        # A capture records observed facts before the parent changes; it is never
        # dispatched, so it has no unknown or refused outcome.
        if intent.outcome != "CONFIRMED":
            raise ReceiptInputError(f"{label}: a capture is only ever CONFIRMED")
        if (intent.expected_old, intent.new) != (node.old_head, node.fork):
            raise ReceiptInputError(f"{label} is not the node's recorded capture")
        return
    if not node.selected or parent is None:
        raise ReceiptInputError(f"{label} mutates only a selected child node")
    if intent.kind == "retarget":
        if intent.new != trunk:
            raise ReceiptInputError(f"{label} must retarget onto the trunk")
        if intent.expected_old != parent.head_ref:
            raise ReceiptInputError(f"{label} must retarget from the parent's head ref")
        return
    if intent.resource != f"refs/heads/{node.head_ref}":
        verb = "push" if intent.kind == "rewrite-push" else "advance"
        raise ReceiptInputError(f"{label} must {verb} the node's own head ref")
    promotion = node.promotion
    if intent.outcome != "REJECTED" and (
        promotion is None
        or not promotion.verified
        or (promotion.old_head, promotion.new_head) != (intent.expected_old, intent.new)
    ):
        raise ReceiptInputError(f"{label} must move exactly a verified promotion")


def _graph_key(run_id: str) -> str:
    """Compare-and-swap baseline key of a graph journal; never a bare receipt id."""
    return f"graph/{run_id}"


def _present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


class Store:
    def __init__(self, common_dir: Path) -> None:
        if os.name != "posix":
            raise StateError("lifecycle receipts require a POSIX platform")
        self.common_dir = common_dir.resolve(strict=True)
        self.directory = self.common_dir / "armory" / "ship"
        self.graph_directory = self.directory / "graphs"
        self._loaded: dict[str, str | None] = {}

    def _directories(self, *, create: bool, graphs: bool = False) -> bool:
        paths = [self.common_dir, self.common_dir / "armory", self.directory]
        if graphs:
            paths.append(self.graph_directory)
        for path in paths:
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

    def _bytes(self, path: Path, label: str = "receipt") -> bytes:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(path, flags)
        try:
            self._private_file(os.fstat(fd))
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ReceiptInputError(f"{label} exceeds the supported size")
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

    def list_runs(self, *, exclude: str | None = None) -> tuple[Receipt, ...]:
        """Every saved receipt, sorted by run id, except ``exclude``.

        ``exclude`` is never read. A controller holding its own run in memory must
        not enumerate that run through :meth:`load`: loading adopts the file's
        current bytes as the compare-and-swap baseline while the controller keeps
        its older in-memory state, so a later save would overwrite another
        controller's journaled intent instead of being refused.
        """
        if exclude is not None:
            validate_run_id(exclude)
        if not self._directories(create=False):
            return ()
        return tuple(
            self.load(path.stem)
            for path in sorted(self.directory.iterdir())
            if path.name.endswith(".json") and path.stem != exclude
        )

    def save(self, receipt: Receipt) -> None:
        payload = receipt.serialize()
        Receipt.parse(payload)
        self._directories(create=True)
        self._replace(
            self.directory, receipt.run_id, receipt.run_id, payload, "receipt"
        )

    def _replace(
        self,
        directory: Path,
        run_id: str,
        key: str,
        payload: dict[str, object],
        label: str,
    ) -> None:
        """Atomically replace ``run_id``'s journal iff its bytes are the loaded ones."""
        target = directory / f"{run_id}.json"
        try:
            current = hashlib.sha256(self._bytes(target, label)).hexdigest()
        except FileNotFoundError:
            current = None
        if current != self._loaded.get(key):
            raise StateError(
                f"{label} changed outside this controller; reload current facts"
            )
        data = (
            json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        fd, filename = tempfile.mkstemp(prefix=f".{run_id}.", dir=directory)
        temporary = Path(filename)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self._loaded[key] = hashlib.sha256(data).hexdigest()
        finally:
            if temporary.exists():
                temporary.unlink()

    def load_graph(self, run_id: str) -> GraphJournal:
        """The stack-graph journal ``run_id``; adopts its bytes as the save baseline."""
        validate_run_id(run_id)
        key = _graph_key(run_id)
        if not self._directories(create=False, graphs=True):
            self._loaded[key] = None
            raise FileNotFoundError("requested graph journal does not exist")
        path = self.graph_directory / f"{run_id}.json"
        try:
            data = self._bytes(path, "graph journal")
        except FileNotFoundError:
            self._loaded[key] = None
            raise
        try:
            raw: object = json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise ReceiptInputError("graph journal JSON is malformed") from error
        journal = GraphJournal.parse(raw)
        if journal.run_id != run_id:
            raise ReceiptInputError(
                "graph journal identity does not match its filename"
            )
        self._loaded[key] = hashlib.sha256(data).hexdigest()
        return journal

    def list_graphs(self, *, exclude: str | None = None) -> tuple[GraphJournal, ...]:
        """Every saved graph journal, sorted by run id, except ``exclude``.

        ``exclude`` is never read, for the reason :meth:`list_runs` gives.
        """
        if exclude is not None:
            validate_run_id(exclude)
        if not self._directories(create=False, graphs=True):
            return ()
        return tuple(
            self.load_graph(path.stem)
            for path in sorted(self.graph_directory.iterdir())
            if path.name.endswith(".json") and path.stem != exclude
        )

    def save_graph(self, journal: GraphJournal) -> None:
        """Compare-and-swap save under the same discipline as :meth:`save`.

        A run id already naming a lifecycle receipt is refused, so one id never
        denotes two documents.
        """
        payload = journal.serialize()
        GraphJournal.parse(payload)
        self._directories(create=True, graphs=True)
        if _present(self.directory / f"{journal.run_id}.json"):
            raise StateError("a lifecycle receipt already uses this graph run id")
        self._replace(
            self.graph_directory,
            journal.run_id,
            _graph_key(journal.run_id),
            payload,
            "graph journal",
        )

    def kind_of(self, run_id: str) -> Literal["receipt", "graph"] | None:
        """Which saved document ``run_id`` names, by existence only (nothing read)."""
        validate_run_id(run_id)
        if not self._directories(create=False):
            return None
        receipt = _present(self.directory / f"{run_id}.json")
        graph_path = self.graph_directory / f"{run_id}.json"
        graph = self._directories(create=False, graphs=True) and _present(graph_path)
        if receipt and graph:
            raise StateError(
                "run id names both a lifecycle receipt and a graph journal; "
                "inspect both before resuming"
            )
        if receipt:
            return "receipt"
        return "graph" if graph else None

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
