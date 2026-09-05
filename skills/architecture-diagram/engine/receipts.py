"""Machine-readable command receipt construction."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .diagnostics import SEVERITY_ERROR, Diagnostic, count_by_severity

RECEIPT_SCHEMA_VERSION = 1
COMPARISON_LIMITATIONS = (
    "Authored specification only; no runtime impact, causality, risk, or merge "
    "safety is inferred."
)

_VALIDATION_CHECKS = (
    "spec",
    "layout",
    "route-rhythm",
    "edge-through-node",
    "proper-crossing",
    "ambiguous-corridor",
    "label-route-clearance",
    "icons",
    "labels",
    "editability",
)


def sha256(payload: bytes) -> str:
    """Return the stable digest recorded in command receipts."""
    return hashlib.sha256(payload).hexdigest()


def check_name(diagnostic: Diagnostic) -> str:
    """Map one diagnostic to its validation receipt check."""
    code = diagnostic.code
    if code.startswith("spec/"):
        return "spec"
    if code.startswith("profile/"):
        return "profile"
    if code in ("layout/node-overlap", "layout/zone-overlap"):
        return "layout"
    if code == "layout/label-overflow":
        return "labels"
    if code.startswith("composition/micro-segment") or code.startswith(
        "composition/short-interior-segment"
    ):
        return "route-rhythm"
    if code == "composition/edge-through-node":
        return "edge-through-node"
    if code == "composition/proper-crossing":
        return "proper-crossing"
    if code == "composition/ambiguous-corridor":
        return "ambiguous-corridor"
    if code == "composition/label-route-clearance":
        return "label-route-clearance"
    if code.startswith("icon/"):
        return "icons"
    return "editability"


def validation_receipt(
    diagnostics: list[Diagnostic], quality: str, profile_active: bool = False
) -> dict[str, object]:
    """Summarize validation checks without changing diagnostic detail."""
    checks = _VALIDATION_CHECKS + (("profile",) if profile_active else ())
    counts = count_by_severity(diagnostics)
    composition = [d for d in diagnostics if d.code.startswith("composition/")]
    if any(d.severity == SEVERITY_ERROR for d in composition):
        composition_status = "failed"
    elif composition:
        composition_status = "warnings"
    else:
        composition_status = "passed"
    failed_checks = {
        check_name(diagnostic)
        for diagnostic in diagnostics
        if diagnostic.severity == SEVERITY_ERROR
    }
    return {
        "checks_passed": len(checks) - len(failed_checks),
        "checks_total": len(checks),
        "quality": quality,
        "composition_status": composition_status,
        "errors": counts["errors"],
        "warnings": counts["warnings"],
    }


def receipt(
    command: str,
    input_path: Path,
    input_bytes: bytes | None,
    artifact_bytes: bytes | None,
    diagnostics: list[Diagnostic],
    quality: str,
    output: Path | None = None,
    written: bool = False,
    delivery_stage: str | None = None,
    profile_active: bool = False,
    evidence: dict[str, object] | None = None,
    artifacts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build the stable validate or deliver JSON receipt."""
    result: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "ok": not any(d.severity == SEVERITY_ERROR for d in diagnostics),
        "command": command,
        "type": "architecture-diagram",
        "input": {
            "path": str(input_path),
            "sha256": sha256(input_bytes) if input_bytes is not None else None,
            "bytes": len(input_bytes) if input_bytes is not None else None,
        },
        "artifact": {
            "sha256": sha256(artifact_bytes) if artifact_bytes is not None else None,
            "bytes": len(artifact_bytes) if artifact_bytes is not None else None,
        },
        "output": {
            "path": str(output) if output is not None else None,
            "written": written,
        },
        "validation": validation_receipt(diagnostics, quality, profile_active),
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
    }
    if evidence is not None:
        result["evidence"] = evidence
    if artifacts is not None:
        result["artifacts"] = artifacts
    if delivery_stage is not None:
        result["delivery_stage"] = delivery_stage
    return result


def comparison_receipt(
    base_path: Path,
    base_bytes: bytes | None,
    head_path: Path,
    head_bytes: bytes | None,
    diagnostics: list[Diagnostic],
    comparison: dict[str, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    """Build the stable authored-spec comparison JSON receipt."""
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "ok": not any(d.severity == SEVERITY_ERROR for d in diagnostics),
        "command": "compare",
        "type": "architecture-diagram",
        "base": {
            "path": str(base_path),
            "sha256": sha256(base_bytes) if base_bytes is not None else None,
            "bytes": len(base_bytes) if base_bytes is not None else None,
        },
        "head": {
            "path": str(head_path),
            "sha256": sha256(head_bytes) if head_bytes is not None else None,
            "bytes": len(head_bytes) if head_bytes is not None else None,
        },
        "comparison": comparison or {"nodes": [], "edges": []},
        "limitations": COMPARISON_LIMITATIONS,
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
    }
