"""Consumer-visible current-context, applicability and authority boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from github_ops import Check, Observation, PullRequest, Repository
from lifecycle import (
    Binding,
    Policy,
    evaluate,
    evidence_identity,
    load_decision,
    load_policy,
)

HEAD = "a" * 40
BASE = "b" * 40


def observed() -> Observation:
    return Observation(
        repo=Repository("owner/repo", "github.com", "main", ("merge", "squash")),
        pr=PullRequest(
            1,
            "https://github.com/owner/repo/pull/1",
            "OPEN",
            HEAD,
            "feature",
            "owner/repo",
            BASE,
            "main",
            "owner/repo",
            None,
            None,
            False,
            True,
            False,
        ),
        checks=(
            Check(
                "tests",
                HEAD,
                BASE,
                "completed",
                "success",
                "github-actions",
                "https://example.com/check",
                "2026-10-12T00:00:00Z",
            ),
        ),
        required_checks=("tests",),
        required_approvals=0,
        approvals=0,
        changes_requested=False,
        policy_known=True,
        issues=(),
    )


def policy() -> Policy:
    return Policy(
        (".github/workflows/ci.yml at current base",),
        ("tests",),
        "squash",
        (),
        HEAD,
        BASE,
    )


def test_unresolved_inventory_is_a_bounded_decision_not_green() -> None:
    result = evaluate(observed(), None)
    assert result.status == "NEEDS_JUDGMENT"
    assert result.details["required_checks"] == ["tests"]


@pytest.mark.parametrize("field", ["head_sha", "base_sha"])
def test_changed_head_or_base_invalidates_successful_check(field: str) -> None:
    current = observed()
    current = replace(current, pr=replace(current.pr, **{field: "c" * 40}))
    refreshed = replace(policy(), **{field: "c" * 40})
    assert evaluate(current, refreshed).status == "WAITING"


def test_missing_job_does_not_inherit_other_jobs_success() -> None:
    explicit = replace(policy(), expected_checks=("tests", "security"))
    result = evaluate(observed(), explicit)
    assert result.status == "WAITING"
    assert result.details["missing_checks"] == ["security"]


def test_failed_nonrequired_job_still_prevents_green() -> None:
    current = observed()
    extra = replace(current.checks[0], name="security", conclusion="failure")
    current = replace(current, checks=current.checks + (extra,))
    result = evaluate(current, policy())
    assert result.status == "NEEDS_JUDGMENT"
    assert result.details["check"] == "security"


@pytest.mark.parametrize(
    "status,conclusion",
    [
        ("queued", None),
        ("in_progress", None),
        ("completed", "cancelled"),
        ("completed", "timed_out"),
    ],
)
def test_pending_cancelled_and_timed_out_jobs_are_not_green(
    status: str, conclusion: str | None
) -> None:
    current = observed()
    current = replace(
        current,
        checks=(replace(current.checks[0], status=status, conclusion=conclusion),),
    )
    assert evaluate(current, policy()).status != "READY"


@pytest.mark.parametrize("conclusion", ["skipped", "neutral"])
def test_skips_need_an_explicit_applicability_decision(conclusion: str) -> None:
    current = observed()
    current = replace(
        current, checks=(replace(current.checks[0], conclusion=conclusion),)
    )
    assert evaluate(current, policy()).status == "NEEDS_JUDGMENT"
    assert (
        evaluate(current, replace(policy(), allowed_skips=("tests",))).status == "READY"
    )


def test_unassociated_base_needs_authorized_head_only_scope() -> None:
    current = observed()
    current = replace(current, checks=(replace(current.checks[0], base_sha=None),))
    assert evaluate(current, policy()).status == "WAITING"
    head_only = replace(policy(), head_only_checks=("tests",))
    assert evaluate(current, head_only).status == "READY"
    strict = replace(current, require_current_base=True)
    assert evaluate(strict, head_only).status == "WAITING"


def test_unknown_provider_policy_cannot_be_overridden() -> None:
    current = replace(observed(), policy_known=False, issues=("policy inaccessible",))
    assert evaluate(current, policy()).status == "BLOCKED"


def test_packet_cannot_remove_required_checks() -> None:
    explicit = replace(policy(), expected_checks=("other",))
    assert evaluate(observed(), explicit).status == "BLOCKED"


def test_required_approval_must_be_current() -> None:
    current = replace(observed(), required_approvals=1)
    assert evaluate(current, policy()).status == "BLOCKED"
    assert evaluate(replace(current, approvals=1), policy()).status == "READY"
    assert (
        evaluate(replace(current, approvals=1, changes_requested=True), policy()).status
        == "BLOCKED"
    )


def test_native_member_never_takes_the_ordinary_path() -> None:
    current = observed()
    current = replace(current, pr=replace(current.pr, native=True))
    assert evaluate(current, policy()).status == "BLOCKED"


def test_duplicate_historical_success_cannot_cover_new_pending() -> None:
    current = observed()
    new = replace(
        current.checks[0],
        status="queued",
        conclusion=None,
        updated_at="2026-10-12T01:00:00Z",
    )
    current = replace(current, checks=current.checks + (new,))
    assert evaluate(current, policy()).status == "NEEDS_JUDGMENT"


def test_merged_requires_authoritative_landing_identity() -> None:
    current = observed()
    current = replace(current, pr=replace(current.pr, state="MERGED"))
    assert evaluate(current, policy()).status == "BLOCKED"
    current = replace(
        current,
        pr=replace(
            current.pr, merge_commit_sha="c" * 40, merged_at="2026-10-12T00:00:00Z"
        ),
    )
    assert evaluate(current, policy()).status == "READY"


def test_action_identity_changes_with_context_and_policy() -> None:
    current = observed()
    identity = evidence_identity(current, policy())
    assert identity != evidence_identity(
        replace(current, pr=replace(current.pr, base_sha="c" * 40)), policy()
    )
    assert identity != evidence_identity(
        current, replace(policy(), merge_method="merge")
    )
    assert identity != evidence_identity(
        replace(current, required_approvals=1), policy()
    )


def test_packet_rejects_empty_ci_without_explicit_policy(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    payload = {
        "schema_version": 1,
        "sources": ["repository CI policy"],
        "expected_checks": [],
        "merge_method": "merge",
        "post_merge_commands": [],
        "head_sha": HEAD,
        "base_sha": BASE,
    }
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="ci_free"):
        load_policy(path)
    payload["ci_free"] = True
    path.write_text(json.dumps(payload))
    current = replace(observed(), checks=(), required_checks=())
    assert evaluate(current, load_policy(path)).status == "READY"


def test_packet_preserves_repeated_argv_and_rejects_unknown_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "policy.json"
    payload = {
        "schema_version": 1,
        "sources": ["CI policy"],
        "expected_checks": ["tests"],
        "merge_method": "merge",
        "post_merge_commands": [["echo", "same", "same"]],
        "head_sha": HEAD,
        "base_sha": BASE,
    }
    path.write_text(json.dumps(payload))
    assert load_policy(path).post_merge_commands == (("echo", "same", "same"),)
    payload["admin_bypass"] = True
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="unknown fields"):
        load_policy(path)


def test_unknown_optional_check_population_cannot_hide_behind_green() -> None:
    current = replace(observed(), issues=("checks-unavailable: permission denied",))
    assert evaluate(current, policy()).status == "NEEDS_JUDGMENT"


def test_boolean_is_not_a_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": True,
                "sources": ["CI source"],
                "expected_checks": ["tests"],
                "merge_method": "merge",
                "post_merge_commands": [],
            }
        )
    )
    with pytest.raises(ValueError, match="schema"):
        load_policy(path)


@pytest.mark.parametrize("field", ["head_sha", "base_sha"])
def test_decision_cannot_authorize_a_different_revision(field: str) -> None:
    current = replace(observed(), pr=replace(observed().pr, **{field: "c" * 40}))
    assert evaluate(current, policy()).status == "NEEDS_JUDGMENT"


def test_checkout_proof_failure_requires_judgment_without_an_explicit_head_only_policy() -> (
    None
):
    current = replace(
        observed(),
        checks=(replace(observed().checks[0], base_sha=None),),
        issues=(
            "checkout-proof-unverified: NEEDS_JUDGMENT missing actual checkout commit",
        ),
    )
    assert evaluate(current, policy()).status == "NEEDS_JUDGMENT"
    assert (
        evaluate(current, replace(policy(), head_only_checks=("tests",))).status
        == "READY"
    )


def test_pending_integration_waits_beside_a_tolerated_unverified_head_only_check() -> (
    None
):
    base = observed()
    lint = replace(base.checks[0], name="lint", base_sha=None)
    integration = replace(
        base.checks[0],
        name="integration",
        base_sha=None,
        status="in_progress",
        conclusion=None,
    )
    current = replace(
        base,
        checks=(lint, integration),
        required_checks=("lint", "integration"),
        issues=("checkout-proof-unverified: NEEDS_JUDGMENT missing checkout commit",),
    )
    decision = replace(
        policy(), expected_checks=("lint", "integration"), head_only_checks=("lint",)
    )
    assert evaluate(current, decision).status == "WAITING"

    unproven = replace(
        current,
        checks=(lint, replace(integration, status="completed", conclusion="success")),
    )
    assert evaluate(unproven, decision).status == "NEEDS_JUDGMENT"

    proven = replace(
        current,
        checks=(
            lint,
            replace(
                integration, status="completed", conclusion="success", base_sha=BASE
            ),
        ),
    )
    assert evaluate(proven, decision).status == "READY"


PLAN_IDENTITY = "d" * 64


def decision_payload(binding: object) -> dict[str, object]:
    return {
        "schema_version": 2,
        "sources": ["CI policy"],
        "expected_checks": ["tests"],
        "merge_method": "squash",
        "post_merge_commands": [["python3", "-c", "pass"]],
        "binding": binding,
    }


def test_publication_bound_decision_authorizes_only_the_bound_revisions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(decision_payload({"plan": PLAN_IDENTITY})))

    loaded = load_decision(path)

    assert isinstance(loaded, Binding)
    assert (loaded.plan, loaded.head, loaded.base_oid) == (PLAN_IDENTITY, None, None)
    bound = loaded.bind(HEAD, BASE)
    assert (bound.head_sha, bound.base_sha, bound.merge_method) == (
        HEAD,
        BASE,
        "squash",
    )
    assert evaluate(observed(), bound).status == "READY"
    moved = replace(observed(), pr=replace(observed().pr, head_sha="c" * 40))
    assert evaluate(moved, bound).status == "NEEDS_JUDGMENT"


def test_explicit_head_and_base_binding_is_parsed_exactly(tmp_path: Path) -> None:
    path = tmp_path / "decision.json"
    binding = {"head": HEAD, "base": {"ref": "main", "oid": BASE}}
    path.write_text(json.dumps(decision_payload(binding)))

    loaded = load_decision(path)

    assert isinstance(loaded, Binding)
    assert (loaded.plan, loaded.head, loaded.base_ref, loaded.base_oid) == (
        None,
        HEAD,
        "main",
        BASE,
    )
    other = tmp_path / "other.json"
    other.write_text(json.dumps(decision_payload({**binding, "head": "c" * 40})))
    assert load_decision(other).fingerprint != loaded.fingerprint


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"binding": {"plan": "short"}}, id="malformed-plan-identity"),
        pytest.param(
            {"binding": {"plan": PLAN_IDENTITY, "head": HEAD}}, id="plan-and-head"
        ),
        pytest.param({"binding": {"head": HEAD}}, id="head-without-base"),
        pytest.param(
            {
                "binding": {
                    "head": HEAD,
                    "base": {"ref": "refs/heads/main", "oid": BASE},
                }
            },
            id="base-ref-not-a-short-branch",
        ),
        pytest.param(
            {"binding": {"head": "HEAD", "base": {"ref": "main", "oid": BASE}}},
            id="symbolic-head",
        ),
        pytest.param({"head_sha": HEAD}, id="literal-revision-in-schema-2"),
        pytest.param({"binding": None}, id="missing-binding"),
    ],
)
def test_publication_bound_decision_rejects_ambiguous_bindings(
    tmp_path: Path, change: dict[str, object]
) -> None:
    path = tmp_path / "decision.json"
    path.write_text(json.dumps({**decision_payload({"plan": PLAN_IDENTITY}), **change}))

    with pytest.raises(ValueError):
        load_decision(path)


def test_schema_1_packets_still_load_as_revision_bound_policies(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    payload = {
        "schema_version": 1,
        "sources": ["CI policy"],
        "expected_checks": ["tests"],
        "merge_method": "merge",
        "post_merge_commands": [],
        "head_sha": HEAD,
        "base_sha": BASE,
    }
    path.write_text(json.dumps(payload))

    assert load_decision(path) == load_policy(path)
