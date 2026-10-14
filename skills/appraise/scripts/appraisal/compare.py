"""Diff two assessments: recalibration after answers/disputes, or progress over time."""

from __future__ import annotations

from typing import Any

_RESULT_FIELDS = (
    "recommended_level",
    "technical_capability_level",
    "scope_influence_level",
    "scope_influence_status",
    "confidence",
)


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    result_changes = []
    for key in _RESULT_FIELDS:
        if old["result"].get(key) != new["result"].get(key):
            result_changes.append(
                {
                    "field": key,
                    "from": old["result"].get(key),
                    "to": new["result"].get(key),
                }
            )
    old_range = old["result"]["plausible_range"]
    new_range = new["result"]["plausible_range"]
    if old_range != new_range:
        result_changes.append(
            {"field": "plausible_range", "from": old_range, "to": new_range}
        )

    old_c = {c["id"]: c for c in old["competencies"]}
    comp_changes = []
    for c in new["competencies"]:
        prev = old_c.get(c["id"])
        if prev is None:
            comp_changes.append(
                {
                    "id": c["id"],
                    "from": None,
                    "to": c["score"],
                    "status_from": None,
                    "status_to": c["status"],
                    "confidence_from": None,
                    "confidence_to": c["confidence"],
                }
            )
            continue
        if (prev["score"], prev["status"], prev["confidence"]) != (
            c["score"],
            c["status"],
            c["confidence"],
        ):
            comp_changes.append(
                {
                    "id": c["id"],
                    "from": prev["score"],
                    "to": c["score"],
                    "status_from": prev["status"],
                    "status_to": c["status"],
                    "confidence_from": prev["confidence"],
                    "confidence_to": c["confidence"],
                }
            )

    def ids(doc: dict[str, Any]) -> set[str]:
        out = {
            i
            for c in doc["competencies"]
            for i in c["supporting_evidence_ids"] + c["counterevidence_ids"]
        }
        out |= {s["id"] for s in doc["self_reports"]}
        return out

    added, removed = sorted(ids(new) - ids(old)), sorted(ids(old) - ids(new))
    freshness = []
    old_rev = {r["repo_id"]: (r["locator"], r["revision"]) for r in old["repositories"]}
    for r in new["repositories"]:
        prev = old_rev.get(r["repo_id"])
        if prev is None or prev[0] != r["locator"]:
            freshness.append(
                f"{r['repo_id']} ({r['locator']}) was not part of the previous assessment"
            )
        elif prev[1] != r["revision"]:
            freshness.append(
                f"{r['repo_id']} revision changed {prev[1][:12]} -> {r['revision'][:12]}"
            )

    summary = []
    for ch in result_changes:
        summary.append(f"{ch['field']}: {ch['from']} -> {ch['to']}")
    for ch in comp_changes:
        summary.append(
            f"{ch['id']}: {ch['from']} ({ch['status_from']}, {ch['confidence_from']}) -> {ch['to']} ({ch['status_to']}, {ch['confidence_to']})"
        )
    new_sr = [s for s in new["self_reports"] if s["id"] in added]
    if new_sr:
        summary.append(
            f"{len(new_sr)} self-report(s) added; they are preserved but never raise a level band"
        )
    contested = [c["id"] for c in new["contested_evidence"]]
    if contested:
        summary.append("contested evidence: " + ", ".join(contested))
    if not summary:
        summary.append("no change to levels, confidence or competency ratings")
    return {
        "previous_assessment_id": old["assessment_id"],
        "summary": summary,
        "result_changes": result_changes,
        "competency_changes": comp_changes,
        "evidence_added": added,
        "evidence_removed": removed,
        "freshness": freshness,
    }
