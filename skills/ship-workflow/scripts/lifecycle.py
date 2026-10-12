"""Existing-PR reconciliation; provider evidence is never replaced by receipts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from git_ops import GitError, GitRepository, Snapshot
from github_ops import GitHub, Observation

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


def load_policy(path: Path) -> Policy:
    """Load only an explicitly supplied packet; reject ambiguous/unknown inputs."""
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or any(not isinstance(k, str) for k in raw):
        raise ValueError("policy must be a JSON object")
    allowed = {
        "schema_version",
        "sources",
        "expected_checks",
        "merge_method",
        "post_merge_commands",
        "allowed_skips",
        "head_only_checks",
        "protected_refs",
        "ci_free",
        "head_sha",
        "base_sha",
    }
    if (
        set(raw) - allowed
        or type(raw.get("schema_version")) is not int
        or raw.get("schema_version") != 1
    ):
        raise ValueError("unsupported policy schema or unknown fields")
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
    revisions = [raw.get(field) for field in ("head_sha", "base_sha")]
    if any(
        not isinstance(sha, str)
        or re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", sha) is None
        for sha in revisions
    ):
        raise ValueError(
            "head_sha and base_sha must bind full observed commit identities"
        )
    return Policy(
        sources,
        expected,
        str(method),
        argv,
        str(revisions[0]),
        str(revisions[1]),
        skips,
        head_only,
        protected,
        ci_free,
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


def validate_repository(snapshot: Snapshot, observation: Observation) -> None:
    names = {
        name for name in (observation.pr.base_repo, observation.pr.head_repo) if name
    }
    git = GitRepository(snapshot.root)
    if not any(git.remote_for(observation.repo.host, name) for name in names):
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
    validate_repository(snapshot, observed)
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
