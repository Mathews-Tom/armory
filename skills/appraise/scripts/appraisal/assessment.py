"""Assemble assessment.json from forensics, the evidence register and calibration."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from . import TOOL_NAME, TOOL_VERSION
from .calibration import Calibrator, Rated
from .compare import diff

QUESTION_RANGE = (5, 10)
_EVIDENCE_GAP_HINT = {
    "no_opportunity": "No collaborators or review activity exist in the analysed repositories, so this cannot be shown here. Not a deficiency.",
    "no_evidence": "Nothing inspected demonstrated this competency.",
    "evidence_rejected": "Cited evidence failed verification.",
    "insufficient_attribution": "Relevant evidence exists but is not attributable to the candidate at the required confidence.",
    "access_limited": "Host data (pull requests, reviews) was unavailable, so this could not be assessed.",
    "not_sampled": "The sample did not reach the parts of the repository that would show this.",
}


def canonical_sha(doc: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


class JudgmentError(ValueError):
    """Judgments are structurally valid but violate an assessment contract."""


def check_contracts(
    judgments: dict[str, Any], rubric: dict[str, Any], mode: str
) -> list[str]:
    problems: list[str] = []
    n = len(judgments["interview_questions"])
    lo, hi = QUESTION_RANGE
    if not lo <= n <= hi:
        problems.append(f"{n} interview/reflection questions; {lo}-{hi} required")
    if len(judgments["development_plan"]) < 3:
        problems.append("development plan needs at least 3 prioritized items")
    ids = {c["id"] for c in rubric["competencies"]}
    rated = {c["id"] for c in judgments["competencies"]}
    missing = sorted(ids - rated)
    if missing:
        problems.append(
            f"competencies missing from judgments (use score null for not observable): {', '.join(missing)}"
        )
    for q in judgments["interview_questions"]:
        unknown = sorted(set(q["competencies"]) - ids)
        if unknown:
            problems.append(f"{q['id']} targets unknown competencies {unknown}")
    if mode in {"review", "manager"}:
        for where, text in _strings(judgments, "$"):
            m = _EMAIL.search(text)
            if m and not m.group(0).lower().endswith("@users.noreply.github.com"):
                local, _, domain = m.group(0).partition("@")
                problems.append(
                    f"{where} contains an email address ({local[:1]}***@{domain}); redact personal data"
                )
    return problems


_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"
)


def _strings(node: Any, path: str) -> list[tuple[str, str]]:
    """Every string value in a judgments document with its JSON path."""
    if isinstance(node, str):
        return [(path, node)]
    if isinstance(node, dict):
        return [
            pair
            for key, value in node.items()
            for pair in _strings(value, f"{path}.{key}")
        ]
    if isinstance(node, list):
        return [
            pair
            for i, value in enumerate(node)
            for pair in _strings(value, f"{path}[{i}]")
        ]
    return []


def build(
    *,
    run_id: str,
    input_doc: dict[str, Any],
    rubric: dict[str, Any],
    forensics: dict[str, Any],
    register: dict[str, Any],
    judgments: dict[str, Any],
    hashes: dict[str, str],
    generated_at: str,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    calibrator = Calibrator(rubric, forensics, register, judgments)
    outcome = calibrator.calibrate(input_doc["target_level"])
    rated: dict[str, Rated] = outcome["rated"]
    evidence = {e["id"]: e for e in register["evidence"]}
    usable = {eid for eid, e in evidence.items() if calibrator.supports(e)}
    limitations: list[dict[str, Any]] = []

    def findings(key: str) -> list[dict[str, Any]]:
        out = []
        for f in judgments[key]:
            ids = list(
                dict.fromkeys(calibrator.alias.get(i, i) for i in f["evidence_ids"])
            )
            kept = [i for i in ids if i in usable]
            dropped = [i for i in ids if i not in usable]
            if not kept:
                limitations.append(
                    {
                        "code": "finding_dropped",
                        "message": f"{key[:-1].replace('_', ' ')} '{f['summary'][:80]}' dropped: none of its evidence is verified and attributable.",
                        "impact": "verification",
                        "repo": None,
                    }
                )
                continue
            out.append(
                {
                    "summary": f["summary"],
                    "evidence_ids": kept,
                    "dropped_evidence_ids": dropped,
                    "competencies": f.get("competencies", []),
                }
            )
        return out

    competencies = [
        {
            "id": r.id,
            "name": r.name,
            "group": r.group,
            "score": r.score,
            "status": r.status,
            "not_observable_reason": r.reason if r.status == "not_observable" else None,
            "confidence": r.confidence,
            "proposed_score": r.proposed,
            "supporting_evidence_ids": [i for i in r.supporting_ids if i in usable],
            "counterevidence_ids": [i for i in r.counter_ids if i in usable],
            "self_report_ids": r.self_report_ids,
            "independent_sources": r.independent,
            "adjustments": r.adjustments,
            "rationale": r.rationale,
        }
        for r in rated.values()
    ]
    gaps = []
    for r in rated.values():
        if r.status == "observed":
            continue
        reason = r.reason or "self_reported"
        sources = ", ".join(calibrator.comp[r.id]["evidence_sources"])
        text = _EVIDENCE_GAP_HINT.get(reason, "Supported only by self-report.")
        gaps.append(
            {
                "competency": r.id,
                "reason": f"{reason}: {text}",
                "resolution": f"Evidence that would resolve it: {sources}.",
            }
        )

    observed_ids = set(usable) | {
        e["id"] for e in register["evidence"] if e["source"] == "self_report"
    }
    plan = []
    for item in sorted(
        judgments["development_plan"], key=lambda p: (p["priority"], p["id"])
    ):
        src = list(
            dict.fromkeys(
                calibrator.alias.get(i, i) for i in item["source_evidence_ids"]
            )
        )
        kept = [i for i in src if i in observed_ids]
        entry = dict(item, source_evidence_ids=kept)
        if len(kept) != len(src):
            entry["dropped_evidence_ids"] = [i for i in src if i not in observed_ids]
        plan.append(entry)
    questions = [
        dict(
            q,
            evidence_ids=[
                i
                for i in dict.fromkeys(
                    calibrator.alias.get(i, i) for i in q["evidence_ids"]
                )
                if i in evidence
            ],
        )
        for q in judgments["interview_questions"]
    ]

    repos = []
    coverage = {c["repo"]: c for c in register["coverage"]["repositories"]}
    for r in forensics["repositories"]:
        lin = r["lineage"]
        for lim in r["limitations"]:
            limitations.append(dict(lim, repo=r["repo_id"]))
        if r["injection_flags"]:
            limitations.append(
                {
                    "code": "evaluator_directed_text",
                    "message": f"{len(r['injection_flags'])} location(s) contain text addressed to evaluators or models (first: {r['injection_flags'][0]['path']}:{r['injection_flags'][0]['line']}); treated as data and blocked from supporting scores.",
                    "impact": "verification",
                    "repo": r["repo_id"],
                }
            )

        def lim(
            code: str, message: str, impact: str, repo_id: str = r["repo_id"]
        ) -> None:
            limitations.append(
                {"code": code, "message": message, "impact": impact, "repo": repo_id}
            )

        ai = r["attribution"]["ai_assisted_commits"]
        if ai:
            lim(
                "ai_assisted_commits",
                f"{ai} candidate commits declare AI assistance. Neutral for scoring; validation practice is an interview topic.",
                "attribution",
            )
        else:
            mentioned = r["attribution"]["ai_mentioned_commits"]
            hint = (
                f" {mentioned} candidate commit message(s) mention AI tooling, so ask how such changes were validated."
                if mentioned
                else ""
            )
            lim(
                "ai_assistance_undeclared",
                "No candidate commit carries an AI co-author trailer. AI assistance is undeclared, not shown to be absent; scores rest on the decisions visible in the code either way."
                + hint,
                "attribution",
            )
        collab = r["collaboration"]
        if collab["opportunity"] is False:
            lim(
                "no_collaboration_opportunity",
                f"No other human committed and no reviews of others' pull requests were found ({collab['human_contributors']} human contributor(s)). Collaboration and influence cannot be observed here; this is not evidence of weakness.",
                "collaboration",
            )
        elif collab["opportunity"] is None:
            lim(
                "collaboration_unassessed",
                "Host review and pull-request data were unavailable, so collaboration beyond commits could not be assessed.",
                "collaboration",
            )
        repos.append(
            {
                "repo_id": r["repo_id"],
                "locator": r["host"]["web_url"] or r["locator"],
                "revision": r["revision"],
                "revision_time": r["revision_time"],
                "analyzed_at": r["analyzed_at"],
                "is_fork": r["host_metadata"]["fork"],
                "relationship": lin["relationship"],
                "parent_locator": lin["upstream_locator"],
                "upstream_diff_status": lin["delta_kind"],
                "ancestry": lin["ancestry"],
                "candidate_role": r["attribution"]["role"],
                "attribution_confidence": r["attribution"]["attribution_confidence"],
                "candidate_surviving_share": r["attribution"][
                    "candidate_surviving_share"
                ],
                "sample_coverage": coverage[r["repo_id"]]["sample_coverage"],
                "history_shallow": r["history"]["is_shallow"],
                "analysis_depth": input_doc["depth"],
            }
        )
        cov = coverage[r["repo_id"]]
        if cov["sample_coverage"] < 0.5:
            lim(
                "low_sample_coverage",
                f"Line-weighted sample coverage is {cov['sample_coverage']:.0%} ({cov['sample_items_inspected']} of {cov['sample_items']} planned items at least partly inspected).",
                "coverage",
            )
        if cov["candidate_lines_total"] and cov["candidate_line_coverage"] < 0.1:
            lim(
                "candidate_line_coverage_low",
                f"{cov['candidate_line_coverage']:.1%} of candidate-attributed lines ({cov['candidate_lines_inspected']} of {cov['candidate_lines_total']}) were read; conclusions extrapolate from a stratified sample.",
                "coverage",
            )
        if cov["sample_items_audited"] < cov["sample_items_inspected"]:
            lim(
                "inspection_self_declared",
                f"{cov['sample_items_inspected'] - cov['sample_items_audited']} inspected sample item(s) were not read through `appraise.py show`; their inspection is self-declared.",
                "coverage",
            )
    if register["rejected"]:
        limitations.append(
            {
                "code": "evidence_rejected",
                "message": f"{len(register['rejected'])} cited item(s) failed verification and were excluded: "
                + ", ".join(x["id"] for x in register["rejected"][:10]),
                "impact": "verification",
                "repo": None,
            }
        )
    if input_doc["depth"] == "quick":
        limitations.append(
            {
                "code": "quick_depth",
                "message": "Quick depth: shallow sample; treat the result as provisional.",
                "impact": "coverage",
                "repo": None,
            }
        )

    cand = forensics["candidate"]
    basis = sorted(
        {
            m["match"]
            for r in forensics["repositories"]
            for m in r["identity"]["matched"]
        }
    )
    verified_identity = cand["status"] == "resolved" and all(
        r["identity"]["basis_confidence"] == "high"
        for r in forensics["repositories"]
        if r["identity"]["status"] == "resolved"
    )
    doc: dict[str, Any] = {
        "schema_version": "1.0",
        "assessment_id": "",
        "run_id": run_id,
        "generated_at": generated_at,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "mode": input_doc["mode"],
        "subject": {
            "candidate_id": cand["display"] or "unnamed sole contributor",
            "identity_verified": verified_identity,
            "identity_basis": basis,
            "domain": rubric["domain"],
            "specialization": input_doc["specialization"],
            "target_level": input_doc["target_level"],
            "consent": input_doc["consent"],
        },
        "repositories": repos,
        "result": outcome["result"],
        "competencies": competencies,
        "strengths": findings("strengths"),
        "confirmed_weaknesses": findings("confirmed_weaknesses"),
        "potential_risks": findings("potential_risks"),
        "evidence_gaps": gaps,
        "development_plan": plan,
        "interview_questions": questions,
        "summary": judgments["summary"],
        "self_reports": [
            e for e in register["evidence"] if e["source"] == "self_report"
        ],
        "contested_evidence": [
            {"id": e["id"], **e["contested"]}
            for e in register["evidence"]
            if e["contested"]
        ],
        "rejected_evidence": register["rejected"],
        "coverage": register["coverage"],
        "limitations": limitations,
        "provenance": {
            "rubric_id": rubric["rubric_id"],
            "rubric_version": rubric["rubric_version"],
            "rubric_sha256": hashes["rubric"],
            "input_sha256": hashes["input"],
            "forensics_sha256": hashes["forensics"],
            "judgments_sha256": hashes["judgments"],
            "evidence_sha256": hashes["evidence"],
        },
        "changes": None,
    }
    doc["assessment_id"] = canonical_sha(
        {
            k: v
            for k, v in doc.items()
            if k not in {"assessment_id", "generated_at", "changes"}
        }
    )
    if previous is not None:
        doc["changes"] = diff(previous, doc)
    return doc
