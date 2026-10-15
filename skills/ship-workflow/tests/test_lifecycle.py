"""Consumer-visible current-context, applicability and authority boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from github_ops import Check, Observation, PullRequest, Repository
from lifecycle import (
    Binding,
    Decision,
    Policy,
    assurance_refusal,
    decision_assurance,
    evaluate,
    evidence_identity,
    load_decision,
    load_policy,
    routine_policy,
)

HEAD = "a" * 40
BASE = "b" * 40


def observed(assurance: str = "high") -> Observation:
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
        assurance=assurance,
    )


def policy(assurance: str = "high") -> Policy:
    return Policy(
        (".github/workflows/ci.yml at current base",),
        ("tests",),
        "squash",
        (),
        HEAD,
        BASE,
        assurance=assurance,
    )


def test_unresolved_inventory_is_a_bounded_decision_not_green() -> None:
    assert evaluate(observed("high"), None).status == "NEEDS_JUDGMENT"
    result = evaluate(observed("routine"), None)
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
    assert evaluate(current, policy()).status == "WAITING"


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
    current = replace(observed("routine"), checks=(), required_checks=())
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
        "assurance": "high",
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


# -- routine provider-backed assurance --------------------------------------------


def row(
    name: str = "tests",
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    app: str = "github-actions",
    app_id: int | None = 15368,
    event: str | None = "pull_request",
    workflow: int | None = 1,
    base: str | None = BASE,
    retargeted: bool = False,
) -> Check:
    return Check(
        name,
        HEAD,
        base,
        status,
        conclusion if status == "completed" else None,
        app,
        f"https://example.com/{name}",
        "2026-10-12T00:00:00Z",
        None,
        None,
        app_id,
        workflow,
        event,
        None,
        retargeted,
    )


def routine(
    *checks: Check, methods: tuple[str, ...] = ("squash",), **over: Any
) -> Observation:
    """A routine observation; provider-required checks are only those passed in."""
    current = observed("routine")
    over.setdefault("required_checks", ())
    return replace(
        current,
        checks=checks,
        repo=replace(current.repo, allowed_merge_methods=methods),
        **over,
    )


def test_routine_needs_no_policy_when_provider_evidence_and_method_are_unambiguous() -> (
    None
):
    gate = evaluate(routine(row()), None)
    assert (gate.status, gate.reason) == (
        "READY",
        "all current applicable gates are satisfied",
    )
    derived = routine_policy(routine(row()))
    assert derived is not None and derived.merge_method == "squash"
    assert (derived.expected_checks, derived.post_merge_commands) == ((), ())


def test_routine_asks_for_a_merge_method_instead_of_picking_one() -> None:
    current = routine(row(), methods=("merge", "squash"))
    assert routine_policy(current) is None
    gate = evaluate(current, None)
    assert gate.status == "NEEDS_JUDGMENT" and "merge method" in gate.reason
    assert gate.details["allowed_merge_methods"] == ["merge", "squash"]
    decided = Policy(("provider",), (), "squash", (), HEAD, BASE)
    assert evaluate(current, decided).status == "READY"


def test_routine_never_infers_missing_or_empty_ci_as_success(tmp_path: Path) -> None:
    assert evaluate(routine(), None).status == "NEEDS_JUDGMENT"  # empty CI
    required = routine(required_checks=("tests",))
    waiting = evaluate(required, None)
    assert (waiting.status, waiting.details["missing_checks"]) == ("WAITING", ["tests"])
    other = routine(row("lint"), required_checks=("tests",))
    assert evaluate(other, None).status == "WAITING"
    path = tmp_path / "decision.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "merge_method": "squash",
                "ci_free": True,
                "head_sha": HEAD,
                "base_sha": BASE,
            }
        )
    )
    assert evaluate(routine(), load_policy(path)).status == "READY"


def test_explicit_expected_checks_stay_authoritative_in_routine() -> None:
    explicit = replace(policy("routine"), expected_checks=("tests", "security"))
    gate = evaluate(routine(row()), explicit)
    assert (gate.status, gate.details["missing_checks"]) == ("WAITING", ["security"])
    omitted = replace(policy("routine"), expected_checks=("other",))
    assert (
        evaluate(routine(row(), required_checks=("tests",)), omitted).status
        == "BLOCKED"
    )


def test_same_named_rows_are_judged_by_identity_and_none_is_hidden() -> None:
    push = row(event="push", base=None, workflow=2)
    both_green = routine(push, row())
    assert evaluate(both_green, None).status == "READY"
    failing = routine(push, row(conclusion="failure"))
    gate = evaluate(failing, None)
    assert gate.status == "NEEDS_JUDGMENT"
    assert (gate.details["event"], gate.details["workflow_id"]) == ("pull_request", 1)
    pending = routine(push, row(status="in_progress"))
    assert evaluate(pending, None).status == "WAITING"
    status_failure = routine(
        row(),
        row(
            app="commit-status",
            app_id=None,
            event=None,
            workflow=None,
            conclusion="failure",
        ),
    )
    gate = evaluate(status_failure, None)
    assert (
        gate.status == "NEEDS_JUDGMENT" and gate.details["publisher"] == "commit-status"
    )
    other_app = routine(
        row(), row(app="github-actions", app_id=99, conclusion="failure")
    )
    assert evaluate(other_app, None).status == "NEEDS_JUDGMENT"


def test_required_publisher_is_by_app_id_not_slug() -> None:
    rows = (row(app_id=99),)
    wanted = routine(
        *rows, required_checks=("tests",), required_apps=(("tests", 15368),)
    )
    gate = evaluate(wanted, None)
    assert (gate.status, gate.details["required_app_id"]) == ("WAITING", 15368)
    both = routine(
        row(app_id=99),
        row(app_id=15368, workflow=3),
        required_checks=("tests",),
        required_apps=(("tests", 15368),),
    )
    assert evaluate(both, None).status == "READY"
    unknown = routine(
        row(app_id=None), required_checks=("tests",), required_apps=(("tests", 15368),)
    )
    assert evaluate(unknown, None).status == "NEEDS_JUDGMENT"


def test_routine_uses_no_checkout_attestation_while_high_still_requires_it() -> None:
    unattested = row(base=None)
    issue = ("checkout-proof-unverified: 'tests' (job 1): NEEDS_JUDGMENT: no log",)
    assert evaluate(routine(unattested, issues=issue), None).status == "READY"
    attested = replace(observed("high"), checks=(unattested,), issues=issue)
    assert evaluate(attested, policy()).status == "NEEDS_JUDGMENT"
    attested = replace(observed("high"), checks=(unattested,))
    assert evaluate(attested, policy()).status == "WAITING"
    assert (
        evaluate(attested, replace(policy(), head_only_checks=("tests",))).status
        == "READY"
    )


def test_decision_and_observation_assurance_must_agree() -> None:
    gate = evaluate(routine(row()), policy("high"))
    assert gate.status == "NEEDS_JUDGMENT" and gate.details["decision"] == "high"
    assert evaluate(observed("high"), policy("routine")).status == "NEEDS_JUDGMENT"
    assert evaluate(observed("high"), None).status == "NEEDS_JUDGMENT"


def test_strict_policy_needs_the_current_base_proved_in_the_head() -> None:
    def strict(*checks: Check, contains: bool | None = True) -> Observation:
        return routine(
            *checks,
            required_checks=("tests",),
            require_current_base=True,
            head_contains_base=contains,
        )

    push = row(event="push", base=None, workflow=2)
    assert evaluate(strict(row()), None).status == "READY"
    behind = evaluate(strict(row(), contains=False), None)
    assert behind.status == "WAITING" and "current base" in behind.reason
    assert evaluate(strict(row(), contains=None), None).status == "NEEDS_JUDGMENT"
    # A head-only job satisfies strict only through the head containing the base.
    assert evaluate(strict(push), None).status == "READY"
    assert evaluate(strict(push, contains=False), None).status == "WAITING"
    explicit = replace(
        policy("routine"), expected_checks=("tests",), head_only_checks=("tests",)
    )
    assert evaluate(strict(push, contains=False), explicit).status == "WAITING"
    status_only = row(
        app="commit-status", app_id=None, event=None, workflow=None, base=None
    )
    assert evaluate(strict(status_only), None).status == "READY"


def test_stale_pull_request_context_is_never_hidden_by_a_push_success() -> None:
    push = row(event="push", base=None, workflow=2)
    stale = row(base="c" * 40)
    current = routine(
        push,
        stale,
        required_checks=("tests",),
        require_current_base=True,
        head_contains_base=True,
    )
    gate = evaluate(current, None)
    assert gate.status == "WAITING"
    assert (
        gate.details["tested_base"] == "c" * 40 and gate.details["current_base"] == BASE
    )
    # Without a strict policy an older base is the provider's accepted state.
    assert (
        evaluate(replace(current, require_current_base=False), None).status == "READY"
    )
    retargeted = replace(current, checks=(push, row(base=None, retargeted=True)))
    assert evaluate(retargeted, None).status == "WAITING"


def test_non_strict_routine_accepts_a_head_only_required_job() -> None:
    push = row(event="push", base=None, workflow=2)
    assert evaluate(routine(push, required_checks=("tests",)), None).status == "READY"


def test_retargeted_run_waits_even_when_head_and_base_commits_coincide() -> None:
    stale = row(base=None, retargeted=True)
    gate = evaluate(routine(stale), None)
    assert gate.status == "WAITING" and gate.details["check"] == "tests"
    assert evaluate(routine(stale, row(workflow=7)), None).status == "WAITING"
    assert evaluate(routine(row(workflow=7)), None).status == "READY"


@pytest.mark.parametrize(
    "issue",
    [
        "strict-base-unavailable: compare unreadable",
        "retarget-freshness-unavailable: events unreadable",
        "checks-unavailable: HTTP 403",
        "actions-run-unresolved: no workflow run",
        "attempt-unresolved: several rows",
    ],
)
def test_unavailable_evidence_is_never_green(issue: str) -> None:
    assert evaluate(routine(row(), issues=(issue,)), None).status == "NEEDS_JUDGMENT"


def test_minimal_routine_packet_defaults_to_provider_evidence(tmp_path: Path) -> None:
    path = tmp_path / "decision.json"
    base = {
        "schema_version": 1,
        "merge_method": "squash",
        "head_sha": HEAD,
        "base_sha": BASE,
    }
    path.write_text(json.dumps(base))
    loaded = load_policy(path)
    assert (loaded.assurance, loaded.sources, loaded.expected_checks) == (
        "routine",
        ("provider",),
        (),
    )
    assert loaded.post_merge_commands == () and loaded.ci_free is False
    assert evaluate(routine(row()), loaded).status == "READY"

    path.write_text(json.dumps({**base, "expected_checks": []}))
    with pytest.raises(ValueError, match="ci_free"):
        load_policy(path)
    path.write_text(json.dumps({**base, "assurance": "high"}))
    with pytest.raises(ValueError):
        load_policy(path)
    path.write_text(json.dumps({**base, "assurance": "medium"}))
    with pytest.raises(ValueError, match="assurance"):
        load_policy(path)


def test_high_packet_keeps_its_explicit_requirements(tmp_path: Path) -> None:
    path = tmp_path / "decision.json"
    full = {
        "schema_version": 1,
        "assurance": "high",
        "sources": ["ci at base"],
        "expected_checks": ["tests"],
        "merge_method": "squash",
        "post_merge_commands": [],
        "head_sha": HEAD,
        "base_sha": BASE,
    }
    path.write_text(json.dumps(full))
    loaded = load_policy(path)
    assert loaded.assurance == "high" and loaded.expected_checks == ("tests",)
    for missing in ("sources", "expected_checks", "post_merge_commands"):
        path.write_text(json.dumps({k: v for k, v in full.items() if k != missing}))
        with pytest.raises((ValueError, TypeError)):
            load_policy(path)


def test_assurance_is_part_of_decision_and_action_identity() -> None:
    assert policy("high").fingerprint != policy("routine").fingerprint
    current = observed("routine")
    assert evidence_identity(current, policy("routine")) != evidence_identity(
        replace(current, assurance="high"), policy("routine")
    )
    binding = Binding(
        Decision(("ci",), ("tests",), "squash", (), (), (), (), False),
        None,
        HEAD,
        "main",
        BASE,
    )
    attested = replace(binding, decision=replace(binding.decision, assurance="high"))
    assert binding.fingerprint != attested.fingerprint
    assert decision_assurance(None) == decision_assurance(binding) == "routine"
    assert decision_assurance(attested) == decision_assurance(policy("high")) == "high"


def test_saved_assurance_never_silently_weakens() -> None:
    assert assurance_refusal("routine", "routine") is None
    assert assurance_refusal("routine", "high") is None
    assert assurance_refusal("high", "high") is None
    assert assurance_refusal(None, "high") is None
    for saved in ("high", None):
        refusal = assurance_refusal(saved, "routine")
        assert refusal is not None and "assurance" in refusal[0]
