from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import appraise

NOW = "2026-10-14T00:00:00Z"
Runner = Callable[..., tuple[int, dict[str, Any]]]


@pytest.fixture
def cli(capsys: pytest.CaptureFixture[str]) -> Runner:
    def run(*args: str) -> tuple[int, dict[str, Any]]:
        capsys.readouterr()
        try:
            appraise.main(list(args))
        except SystemExit as exc:
            code = int(exc.code or 0)
        else:
            code = 0
        out = capsys.readouterr().out
        try:
            return code, json.loads(out)
        except json.JSONDecodeError:
            return code, {"raw": out}

    return run


def judgments_for(
    run_dir: Path,
    evidence: list[dict[str, Any]],
    scores: dict[str, tuple[int | None, list[str], str]] | None = None,
    **extra: Any,
) -> Path:
    """Write a structurally complete judgments.json. scores: id -> (score, evidence ids, confidence)."""
    template = json.loads((run_dir / "judgments.template.json").read_text())
    for comp in template["competencies"]:
        if scores and comp["id"] in scores:
            score, ids, conf = scores[comp["id"]]
            comp.update(
                {
                    "score": score,
                    "supporting_evidence_ids": ids,
                    "confidence": conf,
                    "counterevidence_reviewed": True,
                    "rationale": f"rated from {', '.join(ids) or 'nothing'}",
                }
            )
    first = evidence[0]["id"] if evidence else "E-001"
    template.update(
        {
            "summary": "Synthetic assessor summary.",
            "evidence": evidence,
            "inspected": extra.pop("inspected", []),
            "development_plan": [
                {
                    "id": f"P-0{i}",
                    "category": "evidence_gap",
                    "title": f"plan item {i}",
                    "competencies": ["testing"],
                    "source_evidence_ids": [first],
                    "why": "w",
                    "action": "a",
                    "success_criterion": "s",
                    "effort": "S",
                    "priority": "P2",
                    "horizon_days": 30,
                }
                for i in range(1, 4)
            ],
            "interview_questions": [
                {
                    "id": f"Q-0{i}",
                    "question": f"Why was design choice {i} made this way?",
                    "competencies": ["architecture"],
                    "evidence_ids": [first],
                    "would_change": "architecture confidence",
                }
                for i in range(1, 6)
            ],
        }
    )
    template.update(extra)
    path = run_dir / "judgments.json"
    path.write_text(json.dumps(template, indent=2))
    return path


def ev(
    eid: str,
    repo: str,
    path: str,
    start: int | None = None,
    end: int | None = None,
    **kw: Any,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": eid,
        "kind": kw.pop("kind", "source_code"),
        "repo": repo,
        "path": path,
        "polarity": kw.pop("polarity", "strength"),
        "verification": kw.pop("verification", "directly_inspected"),
        "observation": kw.pop("observation", f"observed {path}"),
        "interpretation": kw.pop("interpretation", "interpretation"),
        "competencies": kw.pop("competencies", ["code_quality"]),
        "confidence": kw.pop("confidence", "medium"),
        "caveats": [],
    }
    if start is not None:
        item["line_start"], item["line_end"] = start, end
    item.update(kw)
    return item
