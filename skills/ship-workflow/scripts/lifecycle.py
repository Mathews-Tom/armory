"""Existing-PR reconciliation; provider evidence is never replaced by receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from git_ops import (
    GitError,
    GitRefused,
    GitRepository,
    Snapshot,
    parse_remote_identity,
    redact_credentials,
    worktree_activity,
)
from github_ops import GitHub, Observation, ProviderError, PullRequest
from state_store import (
    LockBusy,
    Receipt,
    ReceiptInputError,
    StateError,
    Store,
    Target,
)

Status = Literal["PLANNED", "COMPLETE", "WAITING", "NEEDS_JUDGMENT", "BLOCKED"]
Endpoint = Literal["pr", "merged", "clean"]
GateStatus = Literal["READY", "WAITING", "NEEDS_JUDGMENT", "BLOCKED"]
EXIT_CODES: dict[str, int] = {
    "PLANNED": 0,
    "COMPLETE": 0,
    "WAITING": 3,
    "NEEDS_JUDGMENT": 4,
    "BLOCKED": 5,
}


@dataclass(frozen=True)
class Policy:
    """An explicit assistant/caller decision, not auto-loaded repository config."""

    sources: tuple[str, ...]
    expected_checks: tuple[str, ...]
    merge_method: str
    post_merge_commands: tuple[tuple[str, ...], ...]
    head_sha: str
    base_sha: str
    allowed_skips: tuple[str, ...] = ()
    head_only_checks: tuple[str, ...] = ()
    protected_refs: tuple[str, ...] = ()
    ci_free: bool = False

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()


@dataclass(frozen=True)
class Gate:
    status: GateStatus
    reason: str
    details: dict[str, object]


def _strings(
    value: object,
    field: str,
    *,
    empty: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() or "\x00" in item
        for item in value
    ):
        raise ValueError(f"{field} must be a list of nonempty strings")
    result = tuple(item for item in value if isinstance(item, str))
    if (not empty and not result) or (unique and len(set(result)) != len(result)):
        raise ValueError(f"{field} violates its nonempty/unique requirements")
    return result


_DECISION_FIELDS = {
    "sources",
    "expected_checks",
    "merge_method",
    "post_merge_commands",
    "allowed_skips",
    "head_only_checks",
    "protected_refs",
    "ci_free",
}
_OID_PATTERN = r"(?:[a-f0-9]{40}|[a-f0-9]{64})"


@dataclass(frozen=True)
class Decision:
    """The revision-free part of a source-backed lifecycle decision."""

    sources: tuple[str, ...]
    expected_checks: tuple[str, ...]
    merge_method: str
    post_merge_commands: tuple[tuple[str, ...], ...]
    allowed_skips: tuple[str, ...]
    head_only_checks: tuple[str, ...]
    protected_refs: tuple[str, ...]
    ci_free: bool

    def bound(self, head_sha: str, base_sha: str) -> Policy:
        return Policy(
            self.sources,
            self.expected_checks,
            self.merge_method,
            self.post_merge_commands,
            head_sha,
            base_sha,
            self.allowed_skips,
            self.head_only_checks,
            self.protected_refs,
            self.ci_free,
        )


@dataclass(frozen=True)
class Binding:
    """Schema 2 decision bound to receipt-proven publication, not literal revisions.

    ``plan`` binds the head produced by executing exactly that commit plan and its
    base; ``head``/``base_ref``/``base_oid`` bind already-existing local commits.
    The bound :class:`Policy` is formed only from confirmed facts.
    """

    decision: Decision
    plan: str | None
    head: str | None
    base_ref: str | None
    base_oid: str | None

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()

    def bind(self, head_sha: str, base_sha: str) -> Policy:
        return self.decision.bound(head_sha, base_sha)


def _decision_json(path: Path) -> dict[str, object]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or any(not isinstance(k, str) for k in raw):
        raise ValueError("policy must be a JSON object")
    return cast("dict[str, object]", raw)


def load_decision(path: Path) -> Policy | Binding:
    """Load a schema 1 revision-bound or schema 2 publication-bound decision."""
    raw = _decision_json(path)
    if type(raw.get("schema_version")) is not int or raw.get("schema_version") != 2:
        return load_policy(path)
    if set(raw) - _DECISION_FIELDS - {"schema_version", "binding"}:
        raise ValueError("unsupported policy schema or unknown fields")
    binding = raw.get("binding")
    if not isinstance(binding, dict) or any(not isinstance(k, str) for k in binding):
        raise ValueError("binding must name a plan or an explicit head and base")
    decision = _parse_decision(raw)
    if set(binding) == {"plan"}:
        plan = binding["plan"]
        if not isinstance(plan, str) or re.fullmatch(r"[0-9a-f]{64}", plan) is None:
            raise ValueError("binding.plan must be a commit-plan identity")
        return Binding(decision, plan, None, None, None)
    if set(binding) != {"head", "base"}:
        raise ValueError("binding must name a plan or an explicit head and base")
    base = binding["base"]
    if not isinstance(base, dict) or set(base) != {"ref", "oid"}:
        raise ValueError("binding.base needs exactly ref and oid")
    head, base_ref, base_oid = binding["head"], base["ref"], base["oid"]
    if (
        not isinstance(head, str)
        or not isinstance(base_oid, str)
        or re.fullmatch(_OID_PATTERN, head) is None
        or re.fullmatch(_OID_PATTERN, base_oid) is None
    ):
        raise ValueError("binding head and base must be full commit identities")
    if (
        not isinstance(base_ref, str)
        or not base_ref
        or base_ref.startswith(("-", "refs/"))
    ):
        raise ValueError("binding.base.ref must be a short branch name")
    return Binding(decision, None, head, base_ref, base_oid)


def load_policy(path: Path) -> Policy:
    """Load only an explicitly supplied packet; reject ambiguous/unknown inputs."""
    raw = _decision_json(path)
    allowed = _DECISION_FIELDS | {"schema_version", "head_sha", "base_sha"}
    if (
        set(raw) - allowed
        or type(raw.get("schema_version")) is not int
        or raw.get("schema_version") != 1
    ):
        raise ValueError("unsupported policy schema or unknown fields")
    revisions = [raw.get(field) for field in ("head_sha", "base_sha")]
    if any(
        not isinstance(sha, str) or re.fullmatch(_OID_PATTERN, sha) is None
        for sha in revisions
    ):
        raise ValueError(
            "head_sha and base_sha must bind full observed commit identities"
        )
    return _parse_decision(raw).bound(str(revisions[0]), str(revisions[1]))


def _parse_decision(raw: dict[str, object]) -> Decision:
    sources = _strings(raw.get("sources"), "sources", empty=False)
    expected = _strings(raw.get("expected_checks"), "expected_checks")
    skips = _strings(raw.get("allowed_skips", []), "allowed_skips")
    head_only = _strings(raw.get("head_only_checks", []), "head_only_checks")
    protected = _strings(raw.get("protected_refs", []), "protected_refs")
    ci_free = raw.get("ci_free", False)
    method = raw.get("merge_method")
    commands = raw.get("post_merge_commands")
    if not isinstance(ci_free, bool) or (not expected and not ci_free):
        raise ValueError("empty expected_checks requires explicit ci_free=true")
    if ci_free and expected:
        raise ValueError("ci_free cannot contradict expected_checks")
    if method not in ("merge", "squash", "rebase"):
        raise ValueError("merge_method must be merge, squash, or rebase")
    if not set(skips + head_only) <= set(expected):
        raise ValueError("check exemptions must name expected checks")
    if not isinstance(commands, list):
        raise TypeError("post_merge_commands must be an explicit argv list")
    argv = tuple(
        _strings(command, "command argv", empty=False, unique=False)
        for command in commands
    )
    return Decision(
        sources, expected, str(method), argv, skips, head_only, protected, ci_free
    )


def evaluate(observation: Observation, policy: Policy | None) -> Gate:
    """Decide from current identity, all applicable checks and provider policy."""
    pr = observation.pr
    if pr.state == "CLOSED":
        return Gate("BLOCKED", "PR is closed without a confirmed merge", {})
    if pr.native:
        return Gate("BLOCKED", "native membership requires the native stack path", {})
    if not observation.policy_known:
        return Gate(
            "BLOCKED",
            "provider protection/review policy is unknown",
            {
                "issues": list(observation.issues),
            },
        )
    if policy is None:
        return Gate(
            "NEEDS_JUDGMENT",
            "resolve the source-backed validation policy",
            {
                "required_checks": list(observation.required_checks),
                "observed_checks": sorted({check.name for check in observation.checks}),
                "head_sha": pr.head_sha,
                "base_sha": pr.base_sha,
                "allowed_merge_methods": list(observation.repo.allowed_merge_methods),
                "required_decision": [
                    "expected applicable jobs and source references",
                    "merge method under repository conventions",
                    "explicit skip/head-only applicability, if any",
                    "applicable post-merge argv commands",
                ],
            },
        )
    if policy.merge_method not in observation.repo.allowed_merge_methods:
        return Gate(
            "BLOCKED", "requested merge method is disabled by the repository", {}
        )
    if not set(observation.required_checks) <= set(policy.expected_checks):
        return Gate("BLOCKED", "decision packet omits provider-required checks", {})
    if pr.state == "MERGED":
        if not pr.merge_commit_sha or not pr.merged_at:
            return Gate(
                "BLOCKED", "merged PR is missing authoritative landing identity", {}
            )
        return Gate(
            "READY", "provider confirms landing; local verification remains", {}
        )
    if policy.head_sha != pr.head_sha or policy.base_sha != pr.base_sha:
        return Gate(
            "NEEDS_JUDGMENT",
            "revision-bound applicability decision is stale",
            {
                "head_sha": pr.head_sha,
                "base_sha": pr.base_sha,
                "required_decision": "refresh source-backed expected jobs and commands for this context",
            },
        )
    incomplete = [
        issue
        for issue in observation.issues
        if issue.partition(":")[0]
        in {
            "checks-unavailable",
            "statuses-unavailable",
            "actions-runs-unavailable",
            "actions-run-unresolved",
            "run-jobs-unavailable",
            "attempt-unresolved",
            "head-repository-unavailable",
            "check-timestamp-unknown",
            "base-conflict",
        }
    ]
    if incomplete:
        return Gate(
            "NEEDS_JUDGMENT",
            "applicable provider evidence is incomplete",
            {
                "issues": incomplete,
            },
        )
    unresolved_checkout = [
        issue
        for issue in observation.issues
        if issue.partition(":")[0].startswith("checkout-") and "NEEDS_JUDGMENT" in issue
    ]
    if unresolved_checkout and any(
        check.base_sha is None
        and check.status == "completed"
        and (
            check.name not in policy.head_only_checks
            or observation.require_current_base
            and check.name in observation.required_checks
        )
        for check in observation.checks
    ):
        return Gate(
            "NEEDS_JUDGMENT",
            "actual tested context requires a bounded decision",
            {
                "issues": unresolved_checkout,
            },
        )
    if pr.draft:
        return Gate("BLOCKED", "draft PR cannot be landed", {})
    if observation.changes_requested:
        return Gate("BLOCKED", "current blocking review remains unresolved", {})
    if observation.approvals < observation.required_approvals:
        return Gate(
            "BLOCKED",
            "required current-head human approvals are missing",
            {
                "required": observation.required_approvals,
                "current": observation.approvals,
            },
        )
    counts = Counter(check.name for check in observation.checks)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        return Gate(
            "NEEDS_JUDGMENT",
            "ambiguous duplicate check identities",
            {
                "checks": duplicates,
            },
        )
    present = set(counts)
    missing = sorted(set(policy.expected_checks) - present)
    if missing:
        return Gate(
            "WAITING",
            "expected jobs have not produced current evidence",
            {
                "missing_checks": missing,
            },
        )
    if not present and not policy.ci_free:
        return Gate("NEEDS_JUDGMENT", "empty CI is not evidence of GREEN", {})
    for name, app_id in observation.required_apps:
        candidates = [
            check
            for check in observation.checks
            if check.name == name and check.head_sha == pr.head_sha
        ]
        if any(check.app_id == app_id for check in candidates):
            continue
        if any(check.app_id is None for check in candidates):
            return Gate(
                "NEEDS_JUDGMENT",
                "required check publisher identity is unavailable",
                {
                    "check": name,
                    "required_app_id": app_id,
                },
            )
        return Gate(
            "WAITING",
            "required check publisher has not reported on this head",
            {
                "check": name,
                "required_app_id": app_id,
            },
        )
    for check in observation.checks:
        if check.head_sha != pr.head_sha:
            return Gate(
                "WAITING",
                "check belongs to a different head revision",
                {
                    "check": check.name,
                },
            )
        requires_base = check.name not in policy.head_only_checks or (
            observation.require_current_base
            and check.name in observation.required_checks
        )
        if requires_base and check.base_sha != pr.base_sha:
            return Gate(
                "WAITING",
                "current tested base association is missing or stale",
                {
                    "check": check.name,
                    "tested_base": check.base_sha,
                    "current_base": pr.base_sha,
                },
            )
        if check.status != "completed":
            return Gate(
                "WAITING", "applicable job is still pending", {"check": check.name}
            )
        if check.conclusion in ("skipped", "neutral"):
            if check.name not in policy.allowed_skips:
                return Gate(
                    "NEEDS_JUDGMENT",
                    "skip/neutral has no applicability decision",
                    {
                        "check": check.name,
                        "conclusion": check.conclusion,
                    },
                )
        elif check.conclusion != "success":
            return Gate(
                "NEEDS_JUDGMENT",
                "applicable CI is not GREEN; diagnose ownership",
                {
                    "check": check.name,
                    "conclusion": check.conclusion,
                    "url": check.url,
                    "required_decision": "repair change-owned failure or record inherited/permission blocker",
                },
            )
    if pr.mergeable is None:
        return Gate("WAITING", "provider mergeability is unresolved", {})
    if not pr.mergeable:
        return Gate("NEEDS_JUDGMENT", "PR conflicts require scoped resolution", {})
    return Gate("READY", "all current applicable gates are satisfied", {})


def evidence_identity(observation: Observation, policy: Policy | None) -> str:
    """Bind actions to current revisions, policy, checks and independent reviews."""
    payload = {
        "observation": asdict(observation),
        "policy": policy.fingerprint if policy else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_namespace(git: GitRepository, host: str, names: tuple[str, ...]) -> None:
    if not any(name and git.remote_for(host, name) for name in names):
        raise GitError("target PR is not associated with this Git repository's remotes")


def inspection(
    git: GitRepository,
    provider: GitHub,
    number: int,
    endpoint: Endpoint,
    policy: Policy | None,
) -> dict[str, object]:
    snapshot = git.snapshot()
    observed = provider.observe(number)
    validate_namespace(
        git, observed.repo.host, (observed.pr.base_repo, observed.pr.head_repo)
    )
    gate = evaluate(observed, policy)
    if snapshot.dirty and observed.pr.state != "MERGED" and endpoint != "pr":
        gate = Gate(
            "NEEDS_JUDGMENT", "local changes need explicit changeset disposition", {}
        )
    if snapshot.conflicts or snapshot.operations:
        gate = Gate(
            "BLOCKED",
            "Git operation/conflict must be resolved before execution",
            {
                "conflicts": list(snapshot.conflicts),
                "operations": list(snapshot.operations),
            },
        )
    return {
        "schema_version": 1,
        "run_id": None,
        "status": "PLANNED",
        "target": {
            "repository": observed.pr.base_repo,
            "pr": number,
            "endpoint": endpoint,
        },
        "observed_revisions": {
            "head": observed.pr.head_sha,
            "base": observed.pr.base_sha,
        },
        "local_snapshot": snapshot.fingerprint,
        "gate": asdict(gate),
        "provider_issues": list(observed.issues),
        "confirmed_prs": [observed.pr.url],
        "confirmed_merges": [observed.pr.merge_commit_sha]
        if observed.pr.state == "MERGED"
        else [],
        "cleanup": {"removed": [], "retained": [], "failed": []},
        "next_action": "resolve gate decision"
        if gate.status != "READY"
        else "execute authorized endpoint",
        "mutation_performed": False,
    }


POLL_INTERVAL = 10.0
POST_COMMAND_TIMEOUT = 1800.0


def code_identity() -> str:
    digest = hashlib.sha256()
    for name in (
        "ship.py",
        "lifecycle.py",
        "changeset.py",
        "publish.py",
        "git_ops.py",
        "github_ops.py",
        "state_store.py",
    ):
        digest.update(name.encode("ascii"))
        digest.update((Path(__file__).resolve().parent / name).read_bytes())
    return digest.hexdigest()


def _command_identity(argv: tuple[str, ...]) -> str:
    return hashlib.sha256(json.dumps(argv, ensure_ascii=True).encode()).hexdigest()


def _safe_error(error: Exception) -> str:
    if isinstance(error, ProviderError):
        return (
            f"{error.operation}: {error.kind}; detail={error.detail}; "
            f"HTTP={error.http_status}; uncertain={error.uncertain}"
        )
    if isinstance(error, GitError) and not isinstance(error, GitRefused):
        identity = hashlib.sha256(str(error).encode()).hexdigest()
        return f"Git evidence/operation failed; uncertain={error.uncertain}; diagnostic={identity}"
    if isinstance(error, OSError):
        return f"system call failed; errno={error.errno}"
    message = redact_credentials(str(error))
    message = re.sub(r"https?://[^\s'\"<>]+", "[redacted URL]", message)
    return message[:500]


class _Stop(RuntimeError):
    def __init__(self, status: Status, reason: str, next_action: str) -> None:
        super().__init__(reason)
        self.status = status
        self.next_action = next_action


@dataclass(frozen=True)
class _Candidate:
    kind: Literal["local", "remote"]
    branch: str
    namespace: str | None
    oid: str
    required: bool
    remote: str | None = None
    remote_branch: str | None = None

    @property
    def source_branch(self) -> str:
        return self.remote_branch or self.branch

    @property
    def resource(self) -> str:
        return f"refs/heads/{self.branch}"


class _Execution:
    def __init__(
        self,
        git: GitRepository,
        provider: GitHub,
        number: int,
        endpoint: Endpoint,
        policy: Policy | None,
        wait_timeout: float,
        store: Store,
        receipt: Receipt | None,
    ) -> None:
        self.git = git
        self.provider = provider
        self.number = number
        self.endpoint = endpoint
        self.policy = policy
        self.store = store
        self.receipt = receipt
        self.initial = git.snapshot()
        self.latest: PullRequest | None = None
        self.base_tip: str | None = None
        self.current_reachable: bool | None = None
        self.checkout: Snapshot | None = None
        self.code = code_identity()
        self.deadline = time.monotonic() + wait_timeout
        self.mutation_attempted = False
        self.mutation_confirmed = False
        self.cancelled = False
        self.initialized = False
        self.diagnostic: str | None = None
        self.last_gate: dict[str, object] | None = None

    def _diagnose(self, error: Exception) -> None:
        message = redact_credentials(str(error))
        for key, value in os.environ.items():
            if len(value) >= 8 and re.search(r"TOKEN|PASSWORD|SECRET|API_KEY", key):
                message = message.replace(value, "[redacted credential]")
        self.diagnostic = message[:800]

    @property
    def record(self) -> Receipt:
        if self.receipt is None:
            raise StateError("execution has no initialized receipt")
        return self.receipt

    def _save(self) -> None:
        if code_identity() != self.code:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "controller source changed during execution",
                "review the current controller and refresh the source-backed packet",
            )
        self.store.save(self.record)

    def _intent(
        self,
        kind: str,
        resource: str,
        expected_oid: str | None,
        *,
        namespace: str | None = None,
        required: bool = False,
        ref: str | None = None,
        proof: str | None = None,
    ) -> dict[str, object]:
        operation: dict[str, object] = {
            "key": str(len(self.record.intents) + 1),
            "kind": kind,
            "resource": resource,
            "expected_oid": expected_oid,
            "outcome": "PENDING",
            "actual_oid": None,
            "created_at": datetime.now(UTC).isoformat(),
            "namespace": namespace,
            "required": required,
            "ref": ref,
            "proof": proof,
        }
        self.record.intents.append(operation)
        self._save()
        return operation

    def _outcome(
        self, operation: dict[str, object], outcome: str, actual_oid: str | None
    ) -> None:
        operation["outcome"] = outcome
        operation["actual_oid"] = actual_oid
        self._save()

    def _facts(self, pr: PullRequest) -> None:
        self.latest = pr
        if pr.state == "MERGED" and self.receipt is not None:
            if (
                self.record.merge_sha is not None
                and self.record.merge_sha != pr.merge_commit_sha
            ):
                raise _Stop(
                    "BLOCKED",
                    "recorded and current landing identities disagree",
                    "inspect both landings before refreshing any cleanup authority",
                )
            self.record.merge_sha = pr.merge_commit_sha

    def _read(self) -> PullRequest:
        pr = self.provider.read_pr(self.number)
        validate_namespace(self.git, self.provider.host, (pr.base_repo, pr.head_repo))
        self._facts(pr)
        return pr

    def _initialize(self, pr: PullRequest) -> None:
        if self.receipt is None:
            self.receipt = Receipt(
                uuid.uuid4().hex,
                self.endpoint,
                self.code,
                self.policy.fingerprint if self.policy else None,
                self.initial.fingerprint,
                Target(
                    self.provider.host,
                    pr.base_repo,
                    self.number,
                    pr.head_sha,
                    pr.base_sha,
                    pr.head_ref,
                    pr.head_repo,
                    pr.base_ref,
                ),
            )
            self._facts(pr)
            with self.store.mutation_lock():
                self._save()
            return
        record = self.record
        if (record.host, record.repo.lower(), record.number) != (
            self.provider.host,
            pr.base_repo.lower(),
            self.number,
        ):
            raise ReceiptInputError(
                "receipt target does not match the selected PR namespace"
            )
        dispatched = any(
            op["kind"] == "merge"
            and op["outcome"] in ("PENDING", "ACCEPTED", "CONFIRMED")
            for op in record.intents
        )
        if dispatched and (pr.head_repo.lower(), pr.head_ref, pr.base_ref) != (
            record.head_repo.lower(),
            record.head_ref,
            record.base_ref,
        ):
            raise _Stop(
                "NEEDS_JUDGMENT",
                "dispatched target namespace or ref roles changed",
                "reconcile the original target; do not rebind pending mutation authority",
            )
        ranks = {"pr": 0, "merged": 1, "clean": 2}
        if ranks[self.endpoint] > ranks[record.endpoint]:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "resumption cannot expand the saved endpoint",
                "start a new explicitly authorized run for the broader endpoint",
            )
        if self.endpoint != record.endpoint and any(
            op["kind"] == "merge" and op["outcome"] in ("PENDING", "ACCEPTED")
            for op in record.intents
        ):
            raise _Stop(
                "NEEDS_JUDGMENT",
                "scope cannot narrow while a merge remains unresolved",
                "reconcile the original merge outcome before narrowing the saved endpoint",
            )
        if record.code_identity != self.code and (
            self.policy is None or self.policy.fingerprint == record.policy_identity
        ):
            raise _Stop(
                "NEEDS_JUDGMENT",
                "saved actions belong to different controller sources",
                "review the new sources and pass a refreshed applicability packet",
            )
        refreshed = (
            self.policy is not None
            and self.policy.fingerprint != record.policy_identity
        )
        if refreshed:
            if (
                any(
                    op["kind"] == "merge"
                    and op["outcome"] in ("PENDING", "ACCEPTED", "CONFIRMED")
                    for op in record.intents
                )
                and self.policy is not None
                and (self.policy.head_sha != record.head_sha)
            ):
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "a dispatched merge remains bound to its original head",
                    "reconcile the original provider outcome before changing the head",
                )
            record.policy_identity = self.policy.fingerprint if self.policy else None
            if record.publication is not None and self.policy is not None:
                record.publication.decision_identity = self.policy.fingerprint
            record.validation_sha = None
            record.validation_policy = None
            record.code_identity = self.code
            record.status = "WAITING"
        narrowed = record.endpoint != self.endpoint
        if narrowed:
            record.endpoint = self.endpoint
        if refreshed or narrowed:
            with self.store.mutation_lock():
                self._save()

    def _sleep(self, reason: str) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Stop(
                "WAITING", reason, "resume this run after provider execution advances"
            )
        with self.store.mutation_lock():
            self.record.status = "WAITING"
            self.record.issue = reason
            self.record.next_action = "resume monitoring this run"
            self._save()
        # No cooperative mutation lock is held during monitoring.
        time.sleep(min(POLL_INTERVAL, remaining))

    def _pending_merge(self) -> dict[str, object] | None:
        operations = [op for op in self.record.intents if op["kind"] == "merge"]
        return operations[-1] if operations else None

    def _await_or_merge(self) -> PullRequest:
        while True:
            pr = self._read()
            if pr.native:
                raise _Stop(
                    "BLOCKED",
                    "native membership cannot use the ordinary M1 path",
                    "use the qualified native-stack owner; do not fall back to ordinary merge",
                )
            if pr.state == "MERGED":
                if pr.head_sha != self.record.head_sha:
                    raise _Stop(
                        "BLOCKED",
                        "provider merged a different head than the recorded target",
                        "inspect the actual landing and refresh cleanup scope; preserve refs",
                    )
                with self.store.mutation_lock():
                    operation = self._pending_merge()
                    if operation is not None:
                        operation["outcome"] = "CONFIRMED"
                        operation["actual_oid"] = pr.merge_commit_sha
                    self._save()
                return pr
            if pr.state != "OPEN":
                raise _Stop(
                    "BLOCKED",
                    "selected PR closed without a confirmed merge",
                    "resolve the selected PR state; no cleanup is authorized",
                )
            operation = self._pending_merge()
            if operation is not None and operation["outcome"] in (
                "PENDING",
                "ACCEPTED",
            ):
                if pr.head_sha != operation["expected_oid"]:
                    raise _Stop(
                        "NEEDS_JUDGMENT",
                        "head changed after merge dispatch",
                        "reconcile the original queue/merge; do not dispatch a replacement",
                    )
                state = self.provider.queue_state(self.number, self.record.head_sha)
                if state != "IDLE":
                    with self.store.mutation_lock():
                        operation["outcome"] = "ACCEPTED"
                        self._save()
                elif operation["outcome"] == "PENDING":
                    raise _Stop(
                        "NEEDS_JUDGMENT",
                        "merge outcome remains unknown while PR is open",
                        "inspect provider outcome/audit; never retry an uncertain mutation",
                    )
                self._sleep(f"accepted merge is not MERGED yet ({state})")
                continue
            observed = self.provider.observe(self.number)
            self._facts(observed.pr)
            gate = evaluate(observed, self.policy)
            self.last_gate = {
                "status": gate.status,
                "reason": gate.reason,
                "details": gate.details,
            }
            if gate.status == "WAITING":
                self._sleep(gate.reason)
                continue
            if gate.status != "READY":
                raise _Stop(
                    cast("Status", gate.status),
                    gate.reason,
                    "resolve the bounded gate and resume with a source-backed packet",
                )
            if observed.pr.state == "MERGED":
                continue
            snapshot = self.git.snapshot()
            if snapshot.dirty or snapshot.conflicts or snapshot.operations:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "local changes or Git operations need disposition",
                    "preserve the changes and resolve their intended scope before merging",
                )
            with self.store.mutation_lock():
                current = self.git.snapshot()
                if current.fingerprint != snapshot.fingerprint:
                    raise _Stop(
                        "NEEDS_JUDGMENT",
                        "external local snapshot changed",
                        "re-inventory current work before authorizing the next mutation",
                    )
                observed = self.provider.observe(self.number)
                self._facts(observed.pr)
                gate = evaluate(observed, self.policy)
                self.last_gate = {
                    "status": gate.status,
                    "reason": gate.reason,
                    "details": gate.details,
                }
                if observed.pr.state == "MERGED":
                    continue
                if gate.status != "READY":
                    raise _Stop(
                        cast("Status", gate.status),
                        gate.reason,
                        "resume from fresh current-context evidence",
                    )
                if self.policy is None:
                    raise StateError("READY merge gate has no applicability packet")
                self.record.head_sha = observed.pr.head_sha
                self.record.base_sha = observed.pr.base_sha
                self.record.head_ref = observed.pr.head_ref
                self.record.head_repo = observed.pr.head_repo
                self.record.base_ref = observed.pr.base_ref
                self.record.evidence_identity = evidence_identity(observed, self.policy)
                operation = self._intent("merge", observed.pr.url, observed.pr.head_sha)
                self.mutation_attempted = True
                try:
                    self.provider.merge(
                        self.number, observed.pr.head_sha, self.policy.merge_method
                    )
                except ProviderError as error:
                    if not error.uncertain:
                        self._outcome(operation, "REJECTED", None)
                    raise
                self._outcome(operation, "ACCEPTED", None)
            # A successful gh command is acceptance only. Read actual state again.

    def _reachable(self, landing: str, tip: str) -> bool:
        if (
            self.git.resolve_ref(landing) is not None
            and self.git.resolve_ref(tip) is not None
        ):
            return self.git.is_ancestor(landing, tip)
        return self.provider.landing_reachable(landing, tip)

    def _retained(self, base_ref: str) -> GitRepository:
        snapshot = self.git.snapshot()
        occupied = [tree for tree in snapshot.worktrees if tree.branch == base_ref]
        if len(occupied) > 1:
            raise _Stop(
                "BLOCKED",
                "base branch is checked out in multiple registered worktrees",
                "resolve branch ownership without forcing a duplicate checkout",
            )
        if occupied:
            selected = GitRepository(occupied[0].path)
            if selected.snapshot().common_dir != self.initial.common_dir:
                raise StateError(
                    "retained checkout belongs to a different Git common directory"
                )
            return selected
        return self.git

    def _landing(self, pr: PullRequest) -> GitRepository:
        if self.policy is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "post-merge acceptance has no applicability packet",
                "provide explicit source-backed post-merge commands and cleanup policy",
            )
        if not pr.merge_commit_sha:
            raise _Stop(
                "BLOCKED",
                "MERGED has no authoritative landing object",
                "resolve the provider landing identity; preserve all refs",
            )
        remote = self.git.remote_for(self.provider.host, pr.base_repo)
        if remote is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "intended base has no unambiguous associated Git remote",
                "associate the actual base namespace and resume",
            )
        tip = self.provider.base_tip(pr.base_ref)
        self.base_tip = tip
        with self.store.mutation_lock():
            current = self._read()
            if (current.state, current.head_sha, current.merge_commit_sha) != (
                "MERGED",
                self.record.head_sha,
                pr.merge_commit_sha,
            ):
                raise _Stop(
                    "BLOCKED",
                    "landing identity changed during reconciliation",
                    "inspect the actual provider target before any checkout or deletion",
                )
            tracking = f"refs/remotes/{remote}/{pr.base_ref}"
            if (
                self.git.resolve_ref(tracking) != tip
                or self.git.resolve_ref(tip) is None
            ):
                operation = self._intent(
                    "fetch",
                    f"{remote}:{pr.base_ref}",
                    tip,
                    namespace=pr.base_repo,
                    ref=f"refs/heads/{pr.base_ref}",
                )
                self.mutation_attempted = True
                self.git.fetch_base(remote, pr.base_ref, tip)
                self.mutation_confirmed = True
                self._outcome(operation, "CONFIRMED", tip)
            if not self.git.is_ancestor(pr.merge_commit_sha, tip):
                raise _Stop(
                    "BLOCKED",
                    "confirmed landing is not reachable from intended base",
                    "resolve base history; no cleanup follows an unreachable landing",
                )
            self.current_reachable = True
            self.record.merge_verified = True
            retained = self._retained(pr.base_ref)
            snapshot = retained.snapshot()
            if snapshot.head != tip or snapshot.branch != pr.base_ref:
                operation = self._intent("checkout", str(snapshot.root), tip)
                self.mutation_attempted = True
                self.checkout = retained.prepare_base_checkout(
                    pr.base_ref, tip, snapshot
                )
                self.mutation_confirmed = True
                self._outcome(operation, "CONFIRMED", tip)
            else:
                if snapshot.dirty or snapshot.conflicts or snapshot.operations:
                    raise _Stop(
                        "BLOCKED",
                        "retained base checkout contains user changes",
                        "preserve and resolve those changes before post-merge acceptance",
                    )
                self.checkout = snapshot
            self._save()
        return retained

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()

    def _checks(self, retained: GitRepository) -> None:
        if self.policy is None or self.base_tip is None:
            raise StateError("post-merge checks have no selected policy/base")
        if (self.record.validation_sha, self.record.validation_policy) == (
            self.base_tip,
            self.policy.fingerprint,
        ):
            return
        for index, argv in enumerate(self.policy.post_merge_commands):
            identity = _command_identity(argv)
            matching = [
                row
                for row in self.record.verification
                if row["sha"] == self.base_tip
                and row["command_identity"] == identity
                and row["command_index"] == index
            ]
            if matching and matching[-1]["outcome"] == "PASSED":
                continue
            before = retained.snapshot()
            if (
                before.head != self.base_tip
                or before.dirty
                or before.operations
                or before.conflicts
                or self.checkout is None
                or before.branch != self.checkout.branch
            ):
                raise _Stop(
                    "BLOCKED",
                    "validation checkout is not the clean fetched base",
                    "resolve checkout ownership without discarding user work",
                )
            with self.store.mutation_lock():
                operation = self._intent(
                    "verify", f"command:{index}:{identity}", self.base_tip
                )
            timed_out = False
            returncode: int | None = None
            # Unlinked private files bound memory and avoid persisting raw test/source output.
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                process = subprocess.Popen(
                    argv,
                    cwd=before.root,
                    env=retained.execution_environment(),
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                try:
                    returncode = process.wait(timeout=POST_COMMAND_TIMEOUT)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._terminate(process)
                except BaseException:
                    self._terminate(process)
                    raise
            after = retained.snapshot()
            changed = (
                after.fingerprint != before.fingerprint
                or after.dirty
                or after.operations
                or after.conflicts
            )
            outcome = (
                "TIMED_OUT"
                if timed_out
                else "CHANGED_CHECKOUT"
                if changed
                else "PASSED"
                if returncode == 0
                else "FAILED"
            )
            with self.store.mutation_lock():
                self.record.verification.append(
                    {
                        "sha": self.base_tip,
                        "command_index": index,
                        "command_identity": identity,
                        "returncode": returncode,
                        "outcome": outcome,
                    }
                )
                self._outcome(
                    operation,
                    "CONFIRMED" if outcome == "PASSED" else "REJECTED",
                    self.base_tip,
                )
            if outcome != "PASSED":
                raise _Stop(
                    "BLOCKED",
                    f"post-merge command {index} {outcome.lower()} (exit {returncode})",
                    "diagnose the packet's command in the retained checkout; no cleanup ran",
                )
        with self.store.mutation_lock():
            snapshot = retained.snapshot()
            if (
                snapshot.head != self.base_tip
                or snapshot.dirty
                or snapshot.operations
                or snapshot.conflicts
                or self.checkout is None
                or snapshot.fingerprint != self.checkout.fingerprint
            ):
                raise _Stop(
                    "BLOCKED",
                    "checkout changed before validation confirmation",
                    "reconcile the changed checkout and rerun acceptance",
                )
            self.record.validation_sha = self.base_tip
            self.record.validation_policy = self.policy.fingerprint
            self.checkout = snapshot
            self._save()

    def _open_refs(self) -> set[tuple[str, str]]:
        result: set[tuple[str, str]] = set()
        namespaces = {self.record.repo, self.record.head_repo} - {""}
        for namespace in sorted(namespaces):
            for pr in self.provider.list_prs("open", full_name=namespace):
                if pr.head_repo:
                    result.add((pr.head_repo.lower(), pr.head_ref))
                result.add((pr.base_repo.lower(), pr.base_ref))
        return result

    def _protected(
        self, candidate: _Candidate, open_refs: set[tuple[str, str]]
    ) -> str | None:
        branch = candidate.branch
        source = candidate.source_branch
        if (
            candidate.kind == "local"
            and branch == self.record.base_ref
            or candidate.namespace is not None
            and candidate.namespace.lower() == self.record.repo.lower()
            and source == self.record.base_ref
        ):
            return "intended retained base"
        if self.policy is not None and any(
            name in self.policy.protected_refs
            for name in (branch, candidate.resource, source, f"refs/heads/{source}")
        ):
            return "source-authorized protected ref"
        if any(
            re.match(r"^(?:release|releases)(?:/|$)", name, re.IGNORECASE)
            for name in (branch, source)
        ):
            return "release purpose is not disposable"
        if candidate.namespace is None:
            return "local repository/ref namespace is unproved"
        if candidate.namespace.lower() != self.record.head_repo.lower():
            return "outside the authorized head repository namespace"
        if (candidate.namespace.lower(), source) in open_refs:
            return "an open PR uses this namespace/ref as head or base"
        if candidate.kind == "local":
            upstream = self.git.branch_upstream(branch)
            if (upstream is None) != (candidate.remote_branch is None):
                return "local tracking scope changed during cleanup"
            if upstream is not None:
                snapshot = self.git.snapshot()
                identity = parse_remote_identity(snapshot.remotes.get(upstream[0], ""))
                if (
                    identity is None
                    or identity[0] != self.provider.host
                    or identity[1].lower() != candidate.namespace.lower()
                    or upstream[1] != f"refs/heads/{source}"
                ):
                    return "local tracking namespace/ref changed during cleanup"
        if self.provider.branch_protected(candidate.namespace, source):
            return "provider default/protected ref"
        if candidate.kind == "remote":
            # Local candidates precede remote candidates. A surviving associated
            # checkout was not safely disposable, so its remote ref is retained.
            aliases = {
                local.branch
                for local in self._candidates()
                if local.kind == "local"
                and local.namespace is not None
                and local.namespace.lower() == candidate.namespace.lower()
                and local.source_branch == source
            }
            for tree in self.git.snapshot().worktrees:
                if self.checkout is not None and tree.path == self.checkout.root:
                    continue
                if tree.branch in aliases or tree.head == candidate.oid:
                    return (
                        "an associated worktree remains retained or of unknown purpose"
                    )
        return None

    def _candidates(self) -> tuple[_Candidate, ...]:
        pr = self.latest
        if pr is None or not pr.head_repo:
            raise _Stop(
                "BLOCKED",
                "head repository identity is unavailable for required cleanup",
                "resolve authorized head-ref namespace; never substitute the base repository",
            )
        remote = self.git.remote_for(self.provider.host, pr.head_repo)
        if remote is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "head repository has no unambiguous associated remote",
                "associate the authorized head namespace and resume cleanup only",
            )
        snapshot = self.git.snapshot()
        identities = {
            parse_remote_identity(url) for url in snapshot.remotes.values()
        } - {None}
        local: list[_Candidate] = []
        for ref, oid in sorted(self.git.local_heads().items()):
            branch = ref.removeprefix("refs/heads/")
            namespace: str | None = None
            upstream = self.git.branch_upstream(branch)
            remote_branch: str | None = None
            if upstream is not None:
                identity = parse_remote_identity(snapshot.remotes[upstream[0]])
                if identity is not None and identity[0] == self.provider.host:
                    namespace = identity[1]
                    remote_branch = upstream[1].removeprefix("refs/heads/")
            elif len(identities) == 1:
                identity = next(iter(identities))
                if identity is not None and identity[0] == self.provider.host:
                    namespace = identity[1]
            elif branch == pr.head_ref and oid == self.record.head_sha:
                namespace = pr.head_repo
            required = (remote_branch or branch) == pr.head_ref and (
                namespace is None or namespace.lower() == pr.head_repo.lower()
            )
            local.append(
                _Candidate(
                    "local",
                    branch,
                    namespace,
                    oid,
                    required,
                    remote_branch=remote_branch,
                )
            )
        remote_candidates = tuple(
            _Candidate(
                "remote",
                ref.removeprefix("refs/heads/"),
                pr.head_repo,
                oid,
                ref == f"refs/heads/{pr.head_ref}",
                remote,
            )
            for ref, oid in sorted(self.git.remote_heads(remote).items())
        )
        return (*local, *remote_candidates)

    def _proof(
        self, candidate: _Candidate, closed: tuple[PullRequest, ...]
    ) -> str | None:
        if self.base_tip is None or candidate.namespace is None:
            return None
        matching = [
            pr
            for pr in closed
            if pr.state == "MERGED"
            and not pr.native
            and pr.head_repo.lower() == candidate.namespace.lower()
            and pr.head_ref == candidate.source_branch
            and pr.base_repo.lower() == self.record.repo.lower()
            and pr.base_ref == self.record.base_ref
        ]
        if candidate.required:
            if candidate.oid != self.record.head_sha:
                return None
            matching = [pr for pr in matching if pr.number == self.number]
        elif not re.match(
            r"^(?:feat|feature|fix|bugfix|chore|docs|refactor|test|ci|perf|build)/",
            candidate.branch,
        ):
            return None
        for listed in matching:
            pr = self.provider.read_pr(listed.number)
            if (
                pr.state != "MERGED"
                or pr.native
                or pr.head_repo.lower() != candidate.namespace.lower()
                or pr.head_ref != candidate.source_branch
                or pr.base_repo.lower() != self.record.repo.lower()
                or pr.base_ref != self.record.base_ref
            ):
                continue
            if pr.merge_commit_sha is None:
                continue
            if not self._reachable(pr.merge_commit_sha, self.base_tip):
                continue
            operation = self._pending_merge() if pr.number == self.number else None
            recorded = (
                operation is not None
                and operation["outcome"] == "CONFIRMED"
                and operation["expected_oid"] == candidate.oid
                and operation["actual_oid"] == pr.merge_commit_sha
            )
            remote = self.git.remote_for(self.provider.host, pr.base_repo)
            if remote is None:
                return None
            historical = self.git.pr_head(remote, pr.number)
            if historical is not None and historical != candidate.oid:
                continue
            if recorded or historical == candidate.oid:
                return (
                    f"landed-head:{pr.url}@{candidate.oid};"
                    f"landing:{pr.merge_commit_sha};base-tip:{self.base_tip}"
                )
            if (
                candidate.oid == pr.head_sha
                and self.git.resolve_ref(candidate.oid) is not None
                and self.git.resolve_ref(pr.merge_commit_sha) is not None
                and self.git.whole_change_landed(
                    candidate.oid, pr.merge_commit_sha, self.base_tip
                )
            ):
                return (
                    f"whole-tree-delta:{candidate.oid};pr:{pr.url};"
                    f"landing:{pr.merge_commit_sha};base-tip:{self.base_tip}"
                )
        return None

    @staticmethod
    def _row(
        candidate: _Candidate,
        reason: str,
        proof: str,
        *,
        resource: str | None = None,
        kind: str | None = None,
    ) -> dict[str, object]:
        return {
            "kind": kind or candidate.kind,
            "resource": resource or candidate.resource,
            "namespace": candidate.namespace,
            "expected_oid": candidate.oid,
            "actual_oid": None,
            "reason": reason,
            "proof": proof,
            "required": candidate.required,
            "ref": f"refs/heads/{candidate.source_branch}",
        }

    def _retain(
        self,
        candidate: _Candidate,
        reason: str,
        *,
        resource: str | None = None,
        kind: str | None = None,
    ) -> None:
        row = self._row(candidate, reason, "not eligible", resource=resource, kind=kind)
        self.record.cleanup["retained"].append(row)
        if candidate.required:
            self.record.cleanup["failed"].append(row)

    def _current_oid(self, candidate: _Candidate) -> str | None:
        if candidate.kind == "local":
            return self.git.local_heads().get(candidate.resource)
        if candidate.remote is None or candidate.namespace is None:
            raise StateError("remote candidate namespace is missing")
        if (
            self.git.remote_for(self.provider.host, candidate.namespace)
            != candidate.remote
        ):
            raise _Stop(
                "BLOCKED",
                "remote namespace changed before deletion",
                "re-inventory the actual transport association",
            )
        return self.git.remote_heads(candidate.remote).get(candidate.resource)

    def _guard_checkout(self) -> None:
        if self.checkout is None or self.record.validation_sha is None:
            raise StateError("cleanup has no verified retained checkout")
        current = GitRepository(self.checkout.root).snapshot()
        if (
            current.common_dir != self.initial.common_dir
            or current.head != self.record.validation_sha
            or current.branch != self.record.base_ref
            or current.fingerprint != self.checkout.fingerprint
            or current.dirty
            or current.operations
            or current.conflicts
        ):
            raise _Stop(
                "BLOCKED",
                "retained checkout changed after acceptance",
                "preserve the new work and reconcile the checkout before cleanup",
            )

    def _cleanup_one(
        self, candidate: _Candidate, closed: tuple[PullRequest, ...]
    ) -> None:
        if self._current_oid(candidate) is None:
            return
        protection = self._protected(candidate, self._open_refs())
        if protection is not None:
            self._retain(candidate, protection)
            return
        proof = self._proof(candidate, closed)
        if proof is None:
            self._retain(
                candidate,
                "whole landing/current feature identity is unproved or changed",
            )
            return
        if candidate.kind == "local":
            trees = [
                tree
                for tree in self.git.snapshot().worktrees
                if tree.branch == candidate.branch
            ]
            for tree in trees:
                if tree.path == self.initial.root:
                    self._retain(
                        candidate,
                        "main/current invoking checkout cannot be removed",
                        resource=str(tree.path),
                        kind="worktree",
                    )
                    return
                activity = worktree_activity(tree.path)
                if activity.status != "INACTIVE":
                    self._retain(
                        candidate,
                        activity.reason,
                        resource=str(tree.path),
                        kind="worktree",
                    )
                    return
                with self.store.mutation_lock():
                    self._guard_checkout()
                    if self._protected(candidate, self._open_refs()) is not None:
                        raise _Stop(
                            "BLOCKED",
                            "dependencies changed before worktree removal",
                            "reconcile current PR head/base dependencies",
                        )
                    operation = self._intent(
                        "remove_worktree",
                        str(tree.path),
                        candidate.oid,
                        namespace=candidate.namespace,
                        required=candidate.required,
                        ref=f"refs/heads/{candidate.source_branch}",
                        proof=proof,
                    )
                    self.mutation_attempted = True
                    try:
                        self.git.remove_worktree(tree.path, tree.head, tree.branch)
                    except GitRefused as error:
                        self._outcome(operation, "REJECTED", None)
                        self._retain(
                            candidate,
                            _safe_error(error),
                            resource=str(tree.path),
                            kind="worktree",
                        )
                        return
                    self.mutation_confirmed = True
                    self._outcome(operation, "CONFIRMED", None)
                    self.record.cleanup["removed"].append(
                        self._row(
                            candidate,
                            "verified worktree removal",
                            proof,
                            resource=str(tree.path),
                            kind="worktree",
                        )
                    )
        with self.store.mutation_lock():
            self._guard_checkout()
            if (
                self.provider.base_tip(self.record.base_ref)
                != self.record.validation_sha
            ):
                raise _Stop(
                    "WAITING",
                    "intended base advanced after post-merge validation",
                    "resume and validate the current fetched base before cleanup",
                )
            if self._protected(candidate, self._open_refs()) is not None:
                raise _Stop(
                    "BLOCKED",
                    "dependencies/protection changed before ref deletion",
                    "resume from current protection evidence; preserve the ref",
                )
            if self._current_oid(candidate) != candidate.oid:
                raise _Stop(
                    "BLOCKED",
                    "candidate ref changed before deletion",
                    "inspect the new work; never delete a changed ref",
                )
            if self._proof(candidate, closed) is None:
                raise _Stop(
                    "BLOCKED",
                    "landing proof changed before deletion",
                    "reconstruct complete current landing proof",
                )
            kind = "delete_local" if candidate.kind == "local" else "delete_remote"
            operation = self._intent(
                kind,
                candidate.resource,
                candidate.oid,
                namespace=candidate.namespace,
                required=candidate.required,
                ref=f"refs/heads/{candidate.source_branch}",
                proof=proof,
            )
            self.mutation_attempted = True
            try:
                if candidate.kind == "local":
                    self.git.delete_local_head(candidate.branch, candidate.oid)
                else:
                    if candidate.remote is None:
                        raise StateError("remote deletion has no associated transport")
                    self.git.delete_remote_head(
                        candidate.remote, candidate.branch, candidate.oid
                    )
            except GitError as error:
                if self._current_oid(candidate) is None:
                    self.mutation_confirmed = True
                    self._outcome(operation, "CONFIRMED", None)
                else:
                    if not error.uncertain:
                        self._outcome(operation, "REJECTED", None)
                    self.record.cleanup["failed"].append(
                        self._row(candidate, _safe_error(error), proof)
                    )
                    raise
            else:
                if self._current_oid(candidate) is not None:
                    raise StateError("deleted ref still exists")
                self.mutation_confirmed = True
                self._outcome(operation, "CONFIRMED", None)
            self.record.cleanup["removed"].append(
                self._row(candidate, "verified absent", proof)
            )
            self._save()

    def _reconcile_cleanup_intents(self) -> None:
        kinds = {"delete_local", "delete_remote", "remove_worktree", "prune_tracking"}
        for operation in self.record.intents:
            if operation["kind"] not in kinds or operation["outcome"] != "PENDING":
                continue
            resource = cast(str, operation["resource"])
            namespace = cast(str | None, operation["namespace"])
            with self.store.mutation_lock():
                self._guard_checkout()
                if operation["kind"] == "delete_remote":
                    if (
                        namespace is None
                        or namespace.lower() != self.record.head_repo.lower()
                    ):
                        raise ReceiptInputError(
                            "pending remote deletion has no authorized namespace"
                        )
                    remote = self.git.remote_for(self.provider.host, namespace)
                    if remote is None:
                        raise StateError(
                            "pending delete transport cannot be associated"
                        )
                    present = resource in self.git.remote_heads(remote)
                elif operation["kind"] == "remove_worktree":
                    present = any(
                        tree.path == Path(resource)
                        for tree in self.git.snapshot().worktrees
                    )
                    present = (
                        present
                        or Path(resource).exists()
                        or Path(resource).is_symlink()
                    )
                else:
                    present = self.git.resolve_ref(resource) is not None
                if present:
                    raise _Stop(
                        "NEEDS_JUDGMENT",
                        "a pending cleanup mutation has no confirmed absence",
                        "reconcile its original outcome/current epoch; do not blindly resend it",
                    )
                proof = operation["proof"]
                ref = operation["ref"]
                if not isinstance(proof, str) or not isinstance(ref, str):
                    raise ReceiptInputError(
                        "pending cleanup has no recorded scope/landing proof"
                    )
                operation["outcome"] = "CONFIRMED"
                operation["actual_oid"] = None
                kind = {
                    "delete_local": "local",
                    "delete_remote": "remote",
                    "remove_worktree": "worktree",
                    "prune_tracking": "tracking",
                }[operation["kind"]]
                self.record.cleanup["removed"].append(
                    {
                        "kind": kind,
                        "resource": resource,
                        "namespace": namespace,
                        "expected_oid": operation["expected_oid"],
                        "actual_oid": None,
                        "reason": "reconciled authoritative absence",
                        "proof": proof,
                        "required": operation["required"],
                        "ref": ref,
                    }
                )
                self._save()

    def _required_local_refs(self) -> set[str]:
        refs = {
            cast(str, operation["resource"])
            for operation in self.record.intents
            if operation["kind"] == "delete_local" and operation["required"] is True
        }
        refs.update(
            candidate.resource
            for candidate in self._candidates()
            if candidate.kind == "local" and candidate.required
        )
        return refs

    def _prune_tracking(self) -> None:
        remote = self.git.remote_for(self.provider.host, self.record.head_repo)
        if remote is None:
            raise StateError("required head tracking namespace is unavailable")
        targets: dict[str, tuple[str, bool, str]] = {}
        for row in self.record.cleanup["removed"]:
            if (
                row["kind"] not in ("local", "remote")
                or row["namespace"] != self.record.head_repo
            ):
                continue
            targets[cast(str, row["ref"])] = (
                cast(str, row["expected_oid"]),
                cast(bool, row["required"]),
                cast(str, row["proof"]),
            )
        selected = f"refs/heads/{self.record.head_ref}"
        targets[selected] = (
            self.record.head_sha,
            True,
            f"reachable landing:{self.record.merge_sha}",
        )
        for source_ref, (expected, required, proof) in sorted(targets.items()):
            branch = source_ref.removeprefix("refs/heads/")
            tracking = f"refs/remotes/{remote}/{branch}"
            oid = self.git.resolve_ref(tracking)
            if oid is None:
                continue
            candidate = _Candidate(
                "remote", branch, self.record.head_repo, expected, required, remote
            )
            with self.store.mutation_lock():
                self._guard_checkout()
                if (
                    source_ref in self.git.remote_heads(remote)
                    or oid != expected
                    or (self.record.head_repo.lower(), branch) in self._open_refs()
                ):
                    self._retain(
                        candidate,
                        "tracking/current remote epoch is not safely stale",
                        resource=tracking,
                        kind="tracking",
                    )
                    if required:
                        raise _Stop(
                            "BLOCKED",
                            "required tracking ref is not safely stale",
                            "preserve and inspect its current namespace/ref epoch",
                        )
                    continue
                operation = self._intent(
                    "prune_tracking",
                    tracking,
                    oid,
                    namespace=self.record.head_repo,
                    required=required,
                    ref=source_ref,
                    proof=proof,
                )
                self.mutation_attempted = True
                self.git.run("update-ref", "-d", "--no-deref", tracking, oid)
                if self.git.resolve_ref(tracking) is not None:
                    raise StateError("scoped tracking deletion did not confirm absence")
                self.mutation_confirmed = True
                self._outcome(operation, "CONFIRMED", None)
                self.record.cleanup["removed"].append(
                    self._row(
                        candidate,
                        "verified scoped tracking absence",
                        proof,
                        resource=tracking,
                        kind="tracking",
                    )
                )
                self._save()

    def _cleanup(self) -> None:
        self.record.cleanup["retained"] = []
        self.record.cleanup["failed"] = []
        self._reconcile_cleanup_intents()
        closed = self.provider.list_prs("closed", full_name=self.record.repo)
        for candidate in self._candidates():
            self._cleanup_one(candidate, closed)
        if self.record.cleanup["failed"]:
            raise _Stop(
                "BLOCKED",
                "required cleanup targets remain unsafe or failed",
                "resolve the reported targets and resume cleanup only",
            )
        self._prune_tracking()
        selected_ref = f"refs/heads/{self.record.head_ref}"
        if any(
            self.git.local_heads().get(ref) is not None
            for ref in self._required_local_refs()
        ):
            raise StateError("required local feature ref remains after cleanup")
        remote = self.git.remote_for(self.provider.host, self.record.head_repo)
        if remote is None or selected_ref in self.git.remote_heads(remote):
            raise StateError("required remote feature ref absence is not confirmed")

    def _noop(self, pr: PullRequest) -> bool:
        if self.record.status != "COMPLETE":
            return False
        if self.endpoint == "pr":
            return True
        if (
            pr.state != "MERGED"
            or pr.head_sha != self.record.head_sha
            or pr.merge_commit_sha != self.record.merge_sha
            or not self.record.merge_verified
        ):
            raise _Stop(
                "BLOCKED",
                "saved completion no longer matches provider landing facts",
                "reconcile the actual target; a receipt is not authoritative",
            )
        self.base_tip = self.provider.base_tip(pr.base_ref)
        if pr.merge_commit_sha is None or not self._reachable(
            pr.merge_commit_sha, self.base_tip
        ):
            raise _Stop(
                "BLOCKED",
                "completed landing is no longer reachable from intended base",
                "resolve base history without deleting any refs",
            )
        self.current_reachable = True
        if self.endpoint == "clean":
            selected = f"refs/heads/{self.record.head_ref}"
            remote = self.git.remote_for(self.provider.host, self.record.head_repo)
            heads = self.git.local_heads()
            if (
                any(heads.get(ref) is not None for ref in self._required_local_refs())
                or remote is None
                or selected in self.git.remote_heads(remote)
            ):
                raise _Stop(
                    "BLOCKED",
                    "completed cleanup absence proof changed",
                    "inspect the new/retained refs; do not treat completion as deletion authority",
                )
        snapshot = self._retained(pr.base_ref).snapshot()
        if (
            snapshot.head == self.record.validation_sha
            and snapshot.branch == pr.base_ref
            and not snapshot.dirty
            and not snapshot.conflicts
            and not snapshot.operations
        ):
            self.checkout = snapshot
        return True

    def _result(
        self, status: Status, reason: str | None, next_action: str
    ) -> dict[str, object]:
        pr = self.latest
        record = self.receipt
        return {
            "schema_version": 1,
            "run_id": record.run_id if record else None,
            "status": status,
            "target": {
                "repository": pr.base_repo if pr else self.provider.full_name,
                "pr": self.number,
                "endpoint": self.endpoint,
            },
            "observed_revisions": {
                "head": pr.head_sha if pr else None,
                "base": self.base_tip or (pr.base_sha if pr else None),
            },
            "confirmed_commits": [],
            "confirmed_prs": [pr.url] if pr else [],
            "confirmed_merges": [
                {
                    "url": pr.url,
                    "landing": pr.merge_commit_sha,
                    "reachable": self.current_reachable,
                }
            ]
            if pr is not None and pr.state == "MERGED"
            else [],
            "verification": record.verification if record else [],
            "cleanup": record.cleanup
            if record
            else {"removed": [], "retained": [], "failed": []},
            "usable_checkout": {
                "path": str(self.checkout.root),
                "head": self.checkout.head,
                "branch": self.checkout.branch,
            }
            if self.checkout
            else None,
            "blocker": reason,
            "next_action": next_action,
            "diagnostic": self.diagnostic,
            "last_gate": self.last_gate,
            "last_operation": record.intents[-1]
            if record is not None and record.intents
            else None,
            "mutation_attempted": self.mutation_attempted,
            "mutation_performed": self.mutation_confirmed,
            "cancelled": self.cancelled,
        }

    def _finish(
        self, status: Status, reason: str | None, next_action: str, *, save: bool = True
    ) -> tuple[dict[str, object], int]:
        if code_identity() != self.code:
            status = "NEEDS_JUDGMENT"
            reason = "controller sources changed; pending actions are invalidated"
            next_action = "review current sources and resume with a refreshed applicability packet"
        if save and self.receipt is not None and self.initialized:
            self.record.status = status
            self.record.issue = reason
            self.record.next_action = next_action
            try:
                with self.store.mutation_lock():
                    self.store.save(self.record)
            except (StateError, OSError) as error:
                status = "WAITING" if isinstance(error, LockBusy) else "BLOCKED"
                reason = f"receipt preservation failed: {_safe_error(error)}"
                next_action = (
                    "inspect current facts and the private receipt before resumption"
                )
        result = self._result(status, reason, next_action)
        return result, 130 if self.cancelled else EXIT_CODES[status]

    def run(self) -> tuple[dict[str, object], int]:
        try:
            pr = self._read()
            if self.endpoint == "pr" and pr.state == "CLOSED":
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"PR {pr.number} is closed without a confirmed merge",
                    "explicitly choose whether to reopen that PR or publish a replacement",
                )
            if self.endpoint == "pr" and self.receipt is None:
                return self._finish("COMPLETE", None, "none", save=False)
            self._initialize(pr)
            self.initialized = True
            if self._noop(pr):
                return self._finish("COMPLETE", None, "none", save=False)
            if self.endpoint == "pr":
                return self._finish("COMPLETE", None, "none")
            pr = self._await_or_merge()
            self.provider.deadline = None
            retained = self._landing(pr)
            self._checks(retained)
            if self.endpoint == "clean":
                self._cleanup()
            self.checkout = retained.snapshot()
            if (
                self.checkout.head != self.record.validation_sha
                or self.checkout.branch != self.record.base_ref
                or self.checkout.dirty
                or self.checkout.operations
                or self.checkout.conflicts
            ):
                raise _Stop(
                    "BLOCKED",
                    "checkout changed before endpoint confirmation",
                    "preserve and reconcile current work before declaring completion",
                )
            return self._finish("COMPLETE", None, "none")
        except KeyboardInterrupt:
            self.cancelled = True
            return self._finish(
                "WAITING",
                "execution cancelled; reconcile before resuming",
                "resume this run; do not repeat an uncertain mutation",
            )
        except _Stop as error:
            return self._finish(error.status, str(error), error.next_action)
        except LockBusy as error:
            return self._finish(
                "WAITING",
                _safe_error(error),
                "resume when the controller lock is free",
                save=False,
            )
        except ProviderError as error:
            self._diagnose(error)
            status: Status = "WAITING" if error.kind == "WAITING" else "BLOCKED"
            return self._finish(
                status,
                _safe_error(error),
                "reconcile current provider facts and resolve the exact prerequisite",
            )
        except (GitError, StateError, OSError) as error:
            self._diagnose(error)
            return self._finish(
                "BLOCKED",
                _safe_error(error),
                "resolve the reported safety/permission prerequisite and resume",
            )


def execute(
    git: GitRepository,
    provider: GitHub,
    number: int,
    endpoint: Endpoint,
    policy: Policy | None,
    wait_timeout: float,
    store: Store,
    receipt: Receipt | None = None,
) -> tuple[dict[str, object], int]:
    if receipt is not None and receipt.target is None:
        raise ReceiptInputError(
            "saved run has no provider-confirmed PR target; publish its changeset first"
        )
    return _Execution(
        git, provider, number, endpoint, policy, wait_timeout, store, receipt
    ).run()
