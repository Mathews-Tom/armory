"""Calibration rules over synthetic verified registers (no Git needed)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from appraisal.calibration import Calibrator
from appraisal.schema import validate

RUBRIC: dict[str, Any] = json.loads(
    (
        Path(__file__).resolve().parent.parent / "rubrics" / "software_engineering.json"
    ).read_text()
)
TECH = [
    "problem_solving",
    "code_quality",
    "architecture",
    "system_design",
    "testing",
    "security",
    "operations",
    "technical_depth",
    "engineering_judgment",
    "learning",
]


def record(
    eid: str,
    repo: str = "R1",
    path: str | None = None,
    subsystem: str | None = None,
    **kw: Any,
) -> dict[str, Any]:
    rec = {
        "id": eid,
        "source": "agent",
        "kind": "source_code",
        "repository": repo,
        "revision": "a" * 40,
        "path": path or f"src/{eid}.py",
        "line_start": 1,
        "line_end": 10,
        "commit": None,
        "url": None,
        "span_sha256": "b" * 64,
        "subsystem": subsystem or f"src/{eid}",
        "polarity": "strength",
        "candidate_attribution": "verified",
        "attribution_share": 1.0,
        "attribution_basis": "blame",
        "verification": "directly_inspected",
        "status": "verified",
        "observation": "o",
        "interpretation": "i",
        "competencies": [],
        "confidence": "high",
        "caveats": [],
        "adjustments": [],
        "contested": None,
    }
    rec.update(kw)
    return rec


def world(
    scores: dict[str, int | None],
    sources: int = 3,
    repos: int = 1,
    opportunity: bool | None = False,
    confidence: str = "high",
    reviewed: bool = True,
    attribution: str = "verified",
    extra_evidence: list[dict[str, Any]] | None = None,
    self_reports: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    comps = []
    for cid, score in scores.items():
        ids = []
        for n in range(sources if score is not None else 0):
            eid = f"E-{len(evidence) + 1:03d}"
            evidence.append(
                record(eid, repo=f"R{n % repos + 1}", candidate_attribution=attribution)
            )
            ids.append(eid)
        comps.append(
            {
                "id": cid,
                "score": score,
                "rationale": "r",
                "supporting_evidence_ids": ids,
                "counterevidence_ids": [],
                "counterevidence_reviewed": reviewed,
                "confidence": confidence,
            }
        )
    evidence += extra_evidence or []
    evidence += self_reports or []
    forensics = {
        "repositories": [
            {
                "repo_id": f"R{i + 1}",
                "collaboration": {"opportunity": opportunity},
                "attribution": {
                    "role": "exclusive_author",
                    "attribution_confidence": "high",
                },
            }
            for i in range(repos)
        ]
    }
    register = {
        "evidence": evidence,
        "rejected": [],
        "duplicates": [],
        "coverage": {
            "repositories": [
                {"repo": f"R{i + 1}", "sample_items": 10, "sample_coverage": 1.0}
                for i in range(repos)
            ]
        },
    }
    judgments = {"competencies": comps}
    return forensics, register, judgments


def calibrate(
    scores: dict[str, int | None],
    rubric: dict[str, Any] = RUBRIC,
    target: str | None = None,
    **kw: Any,
) -> dict[str, Any]:
    f, r, j = world(scores, **kw)
    out: dict[str, Any] = Calibrator(rubric, f, r, j).calibrate(target)
    return out


SENIOR = {
    "problem_solving": 4,
    "code_quality": 4,
    "architecture": 4,
    "system_design": 3,
    "testing": 3,
    "security": 3,
    "operations": 3,
    "technical_depth": 4,
    "engineering_judgment": 4,
    "learning": 3,
    "ownership": 4,
    "product_thinking": 3,
    "collaboration": None,
    "technical_leadership": None,
}


def test_rubric_file_is_schema_valid() -> None:
    validate(RUBRIC, "rubric")


def test_solo_staff_strength_is_capped_at_senior_with_staff_upper_bound() -> None:
    out = calibrate(SENIOR)
    res = out["result"]
    assert res["technical_capability_level"] == "staff"
    assert res["recommended_level"] == "senior"
    assert (
        res["scope_influence_status"] == "partial"
    )  # only ownership feeds scope; collaboration/leadership N/O
    assert res["determination"].startswith("Senior. Every Senior requirement is met")
    assert res["plausible_range"]["upper"] in {"staff", "principal"}
    assert (
        "Staff is not reached" in res["determination"]
        and "no one else committed" in res["determination"]
    )
    collab = out["rated"]["collaboration"]
    assert (
        collab.status == "not_observable"
        and collab.reason == "no_opportunity"
        and collab.score is None
    )


def test_not_observable_is_never_zero_and_zero_needs_a_verified_deficiency() -> None:
    out = calibrate({**SENIOR, "security": 0})
    sec = out["rated"]["security"]
    assert sec.score is None and sec.status == "not_observable"
    weakness = record("E-900", polarity="weakness")
    f, r, j = world({**SENIOR, "security": 0}, extra_evidence=[weakness])
    for c in j["competencies"]:
        if c["id"] == "security":
            c["supporting_evidence_ids"] = ["E-900"]
    rated = Calibrator(RUBRIC, f, r, j).rate()
    assert rated["security"].score == 0 and rated["security"].status == "observed"


def test_high_scores_need_independent_sources_and_counterevidence_review() -> None:
    out = calibrate({**SENIOR, "architecture": 5}, sources=1)
    arch = out["rated"]["architecture"]
    assert arch.score == 3 and arch.capped
    out = calibrate({**SENIOR, "architecture": 5}, sources=3, reviewed=False)
    assert out["rated"]["architecture"].score == 3
    out = calibrate({**SENIOR, "architecture": 5}, sources=3)
    assert out["rated"]["architecture"].score == 5


def test_unattributable_evidence_cannot_support_any_score() -> None:
    out = calibrate(SENIOR, attribution="inherited")
    assert all(r.status == "not_observable" for r in out["rated"].values())
    assert out["rated"]["architecture"].reason == "insufficient_attribution"
    assert out["result"]["recommended_level"] == "inconclusive"


def test_title_is_not_an_arithmetic_mean() -> None:
    lopsided = {cid: 5 for cid in TECH} | {
        "architecture": 2,
        "system_design": 2,
        "ownership": 5,
    }
    res = calibrate(lopsided)["result"]
    assert res["technical_capability_level"] == "mid"


def test_sparse_evidence_is_inconclusive_with_reasons() -> None:
    res = calibrate({"architecture": 4, "testing": 3})["result"]
    assert res["recommended_level"] == "inconclusive"
    assert res["confidence"] == "low"
    assert any("observable" in reason for reason in res["inconclusive_reasons"])


def test_self_reports_never_raise_bands() -> None:
    sr = record(
        "SR-01",
        source="self_report",
        candidate_attribution="self_reported",
        verification="self_report",
        status="unverified",
        competencies=["collaboration", "technical_leadership"],
    )
    f, r, j = world(SENIOR, self_reports=[sr])
    out = Calibrator(RUBRIC, f, r, j).calibrate(None)
    assert out["rated"]["technical_leadership"].self_report_ids == ["SR-01"]
    assert out["result"]["recommended_level"] == "senior"
    j["competencies"].append(
        {
            "id": "technical_leadership",
            "score": 4,
            "rationale": "",
            "supporting_evidence_ids": [],
            "counterevidence_ids": [],
            "counterevidence_reviewed": True,
            "confidence": "high",
        }
    )
    j["competencies"] = [
        c
        for c in j["competencies"]
        if c["id"] != "technical_leadership" or c["score"] == 4
    ]
    rated = Calibrator(RUBRIC, f, r, j).rate()
    assert (
        rated["technical_leadership"].status == "self_reported"
        and rated["technical_leadership"].score == 3
    )


def test_staff_requires_observed_scope_and_principal_requires_several_repositories() -> (
    None
):
    team = {**SENIOR, "collaboration": 4, "technical_leadership": 4}
    res = calibrate(team, opportunity=True)["result"]
    assert res["recommended_level"] == "staff"
    principal = {cid: 5 for cid in TECH} | {
        "ownership": 5,
        "product_thinking": 4,
        "collaboration": 5,
        "technical_leadership": 5,
    }
    assert (
        calibrate(principal, opportunity=True, repos=1)["result"]["recommended_level"]
        == "staff"
    )
    assert (
        calibrate(principal, opportunity=True, repos=2)["result"]["recommended_level"]
        == "principal"
    )


def test_distinguished_is_unreachable_without_external_corroboration() -> None:
    top = {cid: 5 for cid in TECH} | {
        "ownership": 5,
        "product_thinking": 5,
        "collaboration": 5,
        "technical_leadership": 5,
    }
    res = calibrate(top, opportunity=True, repos=3)["result"]
    assert res["recommended_level"] == "principal"
    assert res["plausible_range"]["upper"] == "principal"


def test_low_confidence_widens_the_range_and_lowers_confidence() -> None:
    res = calibrate(SENIOR, confidence="low")["result"]
    lower, upper = res["plausible_range"]["lower"], res["plausible_range"]["upper"]
    assert RUBRIC_LEVELS.index(lower) < RUBRIC_LEVELS.index(upper)
    assert res["confidence"] == "low"


RUBRIC_LEVELS = [lv["id"] for lv in RUBRIC["levels"]]


def test_target_level_comparison_lists_blockers() -> None:
    res = calibrate(SENIOR, target="staff")["result"]
    t = res["target_level_comparison"]
    assert t["outcome"] == "below"
    assert any(
        b.startswith("Collaboration can't be observed") and "Staff needs 3 or more" in b
        for b in t["blockers"]
    )


def test_new_domain_rubric_needs_no_engine_change() -> None:
    rubric = copy.deepcopy(RUBRIC)
    rubric.update(
        {"rubric_id": "data_science", "domain": "data_science", "title": "Data science"}
    )
    rubric["competencies"] = [
        {
            "id": "statistics",
            "name": "Statistics",
            "group": "technical",
            "indicators": [],
            "evidence_sources": ["source_code"],
            "requires_opportunity": None,
        },
        {
            "id": "modeling",
            "name": "Modeling",
            "group": "technical",
            "indicators": [],
            "evidence_sources": ["source_code"],
            "requires_opportunity": None,
        },
        {
            "id": "communication",
            "name": "Communication",
            "group": "influence",
            "indicators": [],
            "evidence_sources": ["documentation"],
            "requires_opportunity": "collaborators",
        },
    ]
    rubric["levels"] = [
        {
            "id": "analyst",
            "label": "Analyst",
            "description": "d",
            "requires_scope": False,
            "technical": [
                {"type": "at_least", "of": "group:technical", "score": 2, "n": 2}
            ],
            "scope": [],
        },
        {
            "id": "lead",
            "label": "Lead",
            "description": "d",
            "requires_scope": True,
            "technical": [{"type": "at_least", "of": ["modeling"], "score": 4, "n": 1}],
            "scope": [
                {"type": "at_least", "of": ["communication"], "score": 3, "n": 1}
            ],
        },
    ]
    rubric["inconclusive_when"] = [
        {"type": "observed_below", "of": "group:technical", "n": 2}
    ]
    validate(rubric, "rubric")
    res = calibrate(
        {"statistics": 3, "modeling": 4, "communication": None}, rubric=rubric
    )["result"]
    assert res["recommended_level"] == "analyst"
    assert res["technical_capability_level"] == "lead"


def test_medium_confidence_on_a_threshold_keeps_the_next_level_in_range() -> None:
    edge = {**SENIOR, "architecture": 3, "system_design": 3}
    res = calibrate(edge, confidence="medium", sources=2)["result"]
    assert res["recommended_level"] == "mid"
    assert res["plausible_range"] == {"lower": "mid", "upper": "senior"}
    assert res["confidence"] != "high"
