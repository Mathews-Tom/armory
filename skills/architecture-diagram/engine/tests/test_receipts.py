from __future__ import annotations

from pathlib import Path

from engine.diagnostics import Diagnostic, SEVERITY_ERROR
from engine.receipts import comparison_receipt, receipt, sha256


def test_receipt_binds_artifact_digest_and_delivery_stage() -> None:
    artifact = b"<svg/>"
    finding = Diagnostic(
        code="spec/no-nodes",
        severity=SEVERITY_ERROR,
        message="spec has no nodes",
    )

    payload = receipt(
        "deliver",
        Path("diagram.yaml"),
        b"nodes: []\n",
        artifact,
        [finding],
        "standard",
        output=Path("diagram.svg"),
        delivery_stage="check",
    )

    assert payload["ok"] is False
    assert payload["artifact"] == {"sha256": sha256(artifact), "bytes": len(artifact)}
    assert payload["output"] == {"path": "diagram.svg", "written": False}
    assert payload["delivery_stage"] == "check"
    validation = payload["validation"]
    assert isinstance(validation, dict)
    assert validation["checks_passed"] == 9


def test_comparison_receipt_keeps_authored_only_limitation() -> None:
    payload = comparison_receipt(
        Path("base.yaml"),
        b"nodes: []\n",
        Path("head.yaml"),
        b"nodes: []\n",
        [],
    )

    assert payload["ok"] is True
    assert payload["comparison"] == {"nodes": [], "edges": []}
    assert payload["limitations"] == (
        "Authored specification only; no runtime impact, causality, risk, or "
        "merge safety is inferred."
    )
