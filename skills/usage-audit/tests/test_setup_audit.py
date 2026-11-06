"""Consumer-visible evidence, approval and verification boundaries."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/setup_audit.py"
SPEC = importlib.util.spec_from_file_location("setup_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def store(path: Path, value: dict[str, Any]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    root.chmod(0o700)
    return root


def prepare(
    root: Path, before: str = "old rule\n", after: str = "new rule\n"
) -> tuple[Path, Path, dict[str, Any]]:
    target = root / "instructions.md"
    target.write_text(before, encoding="utf-8")
    second = root / "status.json"
    second.write_text('{"connected": false}\n', encoding="utf-8")
    snapshot = root / "snapshot.json"
    AUDIT.capture("omp", [target, second], snapshot)
    finding = {
        "id": "repair-rule",
        "category": "instructions",
        "priority": "medium",
        "problem": "Rule references a retired workflow.",
        "consequence": "The agent uses the wrong workflow.",
        "recommendation": "Replace the confirmed stale rule.",
        "confidence": "observed",
        "evidence": [
            {
                "source_id": "s001",
                "line_start": 1,
                "line_end": 1,
                "observation": "The owner confirmed this instruction is stale.",
            }
        ],
        "change": {"source_id": "s001", "replacement": after},
    }
    authored = {
        "coverage": [
            {
                "area": "context costs",
                "status": "unavailable",
                "detail": "No current context telemetry supplied.",
            }
        ],
        "findings": [finding],
    }
    return target, snapshot, authored


def build(
    root: Path, snapshot: Path, authored: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    findings = store(root / "findings.json", authored)
    AUDIT.review(snapshot, findings, root / "review")
    bundle_path = root / "review/bundle.json"
    return bundle_path, AUDIT.load(bundle_path)


def select(root: Path, bundle: dict[str, Any], selected: list[str]) -> Path:
    return store(
        root / "selection.json",
        {
            "schema_version": 1,
            "bundle_digest": bundle["bundle_digest"],
            "selected": selected,
            "comments": {},
        },
    )


def test_exact_approval_then_native_edit_and_verified_receipt(workspace: Path) -> None:
    target, snapshot, authored = prepare(workspace)
    bundle_path, bundle = build(workspace, snapshot, authored)
    selection = select(workspace, bundle, ["repair-rule"])
    authorization = workspace / "authorization.json"
    AUDIT.check(bundle_path, selection, bundle["bundle_digest"], authorization)
    assert target.read_text() == "old rule\n"  # Approval validation cannot apply edits.
    change = AUDIT.load(authorization)["changes"][0]
    assert change["path"] == str(target)
    target.write_text(change["replacement"], encoding="utf-8")
    receipt = workspace / "receipt.json"
    assert AUDIT.verify(authorization, receipt) is True
    assert AUDIT.load(receipt)["results"] == [
        {"source_id": "s001", "status": "applied"},
        {"source_id": "s002", "status": "unchanged"},
    ]
    assert stat.S_IMODE(authorization.stat().st_mode) == 0o600
    assert stat.S_IMODE((workspace / "review").stat().st_mode) == 0o700


def test_capture_preserves_syntax_failure_without_storing_private_content(
    workspace: Path,
) -> None:
    source = workspace / "settings.json"
    source.write_text('{"token": "SECRET",}', encoding="utf-8")
    snapshot = workspace / "snapshot.json"
    AUDIT.capture("claude", [source], snapshot)
    result = AUDIT.load(snapshot)["sources"][0]
    assert result["syntax"] == "invalid"
    assert result["characters"] == len(source.read_text())
    assert "SECRET" not in snapshot.read_text()


@pytest.mark.parametrize("stage", ["review", "check"])
def test_changed_evidence_refuses_stale_proposal(workspace: Path, stage: str) -> None:
    target, snapshot, authored = prepare(workspace)
    if stage == "review":
        target.write_text("user change\n")
        with pytest.raises(AUDIT.AuditError, match="source changed"):
            build(workspace, snapshot, authored)
    else:
        bundle_path, bundle = build(workspace, snapshot, authored)
        selection = select(workspace, bundle, ["repair-rule"])
        target.write_text("user change\n")
        with pytest.raises(AUDIT.AuditError, match="source changed"):
            AUDIT.check(
                bundle_path,
                selection,
                bundle["bundle_digest"],
                workspace / "authorization.json",
            )
    assert not (workspace / "authorization.json").exists()
    assert target.read_text() == "user change\n"


def test_changed_bundle_and_wrong_confirmation_are_refused(workspace: Path) -> None:
    _, snapshot, authored = prepare(workspace)
    bundle_path, bundle = build(workspace, snapshot, authored)
    selection = select(workspace, bundle, ["repair-rule"])
    with pytest.raises(AUDIT.AuditError, match="approval does not match"):
        AUDIT.check(bundle_path, selection, "0" * 64, workspace / "authorization.json")
    bundle["findings"][0]["change"]["replacement"] = "unapproved\n"
    store(bundle_path, bundle)
    with pytest.raises(AUDIT.AuditError, match="fingerprint mismatch"):
        AUDIT.check(
            bundle_path,
            selection,
            bundle["bundle_digest"],
            workspace / "authorization.json",
        )


@pytest.mark.parametrize("selected", [["missing"], ["repair-rule", "repair-rule"]])
def test_unknown_and_duplicate_selections_refused(
    workspace: Path, selected: list[str]
) -> None:
    _, snapshot, authored = prepare(workspace)
    bundle_path, bundle = build(workspace, snapshot, authored)
    selection = select(workspace, bundle, selected)
    with pytest.raises(AUDIT.AuditError):
        AUDIT.check(
            bundle_path,
            selection,
            bundle["bundle_digest"],
            workspace / "authorization.json",
        )


def test_report_only_finding_cannot_authorize_a_change(workspace: Path) -> None:
    _, snapshot, authored = prepare(workspace)
    authored["findings"][0]["change"] = None
    bundle_path, bundle = build(workspace, snapshot, authored)
    selection = select(workspace, bundle, ["repair-rule"])
    with pytest.raises(AUDIT.AuditError, match="not a proposed file change"):
        AUDIT.check(
            bundle_path,
            selection,
            bundle["bundle_digest"],
            workspace / "authorization.json",
        )


@pytest.mark.parametrize("empty_findings", [False, True])
def test_keep_everything_is_valid_without_cost_telemetry(
    workspace: Path, empty_findings: bool
) -> None:
    target, snapshot, authored = prepare(workspace)
    if empty_findings:
        authored["findings"] = []
    bundle_path, bundle = build(workspace, snapshot, authored)
    selection = select(workspace, bundle, [])
    authorization = workspace / "authorization.json"
    AUDIT.check(bundle_path, selection, bundle["bundle_digest"], authorization)
    assert AUDIT.load(authorization)["changes"] == []
    assert AUDIT.verify(authorization, workspace / "receipt.json") is True
    assert target.read_text() == "old rule\n"


@pytest.mark.parametrize(
    "mutation,expected",
    [("none", "not_applied"), ("unexpected", "drift"), ("missing", "unavailable")],
)
def test_receipt_distinguishes_unfinished_unapproved_and_missing_targets(
    workspace: Path, mutation: str, expected: str
) -> None:
    target, snapshot, authored = prepare(workspace)
    bundle_path, bundle = build(workspace, snapshot, authored)
    selection = select(workspace, bundle, ["repair-rule"])
    authorization = workspace / "authorization.json"
    AUDIT.check(bundle_path, selection, bundle["bundle_digest"], authorization)
    if mutation == "unexpected":
        target.write_text("not the approved edit\n")
    elif mutation == "missing":
        target.unlink()
    assert AUDIT.verify(authorization, workspace / "receipt.json") is False
    assert AUDIT.load(workspace / "receipt.json")["results"][0]["status"] == expected


def test_unselected_source_drift_cannot_be_reported_as_success(workspace: Path) -> None:
    _, snapshot, authored = prepare(workspace)
    bundle_path, bundle = build(workspace, snapshot, authored)
    selection = select(workspace, bundle, [])
    authorization = workspace / "authorization.json"
    AUDIT.check(bundle_path, selection, bundle["bundle_digest"], authorization)
    (workspace / "status.json").write_text('{"connected": true}\n')
    assert AUDIT.verify(authorization, workspace / "receipt.json") is False
    assert AUDIT.load(workspace / "receipt.json")["results"][1]["status"] == "drift"


def test_replaced_target_symlink_is_not_followed(workspace: Path) -> None:
    target, snapshot, authored = prepare(workspace)
    bundle_path, bundle = build(workspace, snapshot, authored)
    selection = select(workspace, bundle, ["repair-rule"])
    alternate = workspace / "other.md"
    alternate.write_text("old rule\n")
    target.unlink()
    target.symlink_to(alternate)
    with pytest.raises(AUDIT.AuditError, match="aliases"):
        AUDIT.check(
            bundle_path,
            selection,
            bundle["bundle_digest"],
            workspace / "authorization.json",
        )
    assert alternate.read_text() == "old rule\n"


@pytest.mark.parametrize("invalid", ["range", "repeat_target", "no_evidence"])
def test_findings_need_bounded_unambiguous_evidence(
    workspace: Path, invalid: str
) -> None:
    _, snapshot, authored = prepare(workspace)
    if invalid == "range":
        authored["findings"][0]["evidence"][0]["line_end"] = 999
    elif invalid == "no_evidence":
        authored["findings"][0]["evidence"] = []
    else:
        second = json.loads(json.dumps(authored["findings"][0]))
        second["id"] = "competing-rule"
        authored["findings"].append(second)
    with pytest.raises(AUDIT.AuditError):
        build(workspace, snapshot, authored)
    assert not (workspace / "review").exists()


def test_review_excludes_full_replacement_and_displays_final_newline_change(
    workspace: Path,
) -> None:
    before = "private_key=UNCHANGED_SECRET\nold rule\n"
    after = "private_key=UNCHANGED_SECRET\nnew rule"
    _, snapshot, authored = prepare(workspace, before, after)
    bundle_path, bundle = build(workspace, snapshot, authored)
    change = bundle["findings"][0]["change"]
    assert change["replacement"] == after
    assert "+new rule\n\\ No newline at end of file\n" in change["diff"]
    assert "UNCHANGED_SECRET" not in (bundle_path.parent / "review.html").read_text()


def test_output_cannot_overwrite_or_write_inside_repository(workspace: Path) -> None:
    _, snapshot, _ = prepare(workspace)
    original = snapshot.read_bytes()
    with pytest.raises(FileExistsError):
        AUDIT.save(snapshot, {"different": True})
    assert snapshot.read_bytes() == original
    repository = workspace / "repo"
    repository.mkdir(mode=0o700)
    (repository / ".git").write_text("gitdir: elsewhere")
    with pytest.raises(AUDIT.AuditError, match="outside Git"):
        AUDIT.save(repository / "private.json", {})


def test_output_refuses_shared_directory(workspace: Path) -> None:
    shared = workspace / "shared"
    shared.mkdir(mode=0o755)
    with pytest.raises(AUDIT.AuditError, match="owner-only"):
        AUDIT.save(shared / "snapshot.json", {})


def test_cli_parse_failure_does_not_echo_sensitive_input(workspace: Path) -> None:
    secret = workspace / "secret.json"
    secret.write_text('{"private": SECRET_MARKER')
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "review",
            "--snapshot",
            str(secret),
            "--findings",
            str(secret),
            "--out-dir",
            str(workspace / "review"),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    assert result.returncode == 2
    assert "SECRET_MARKER" not in result.stderr
    assert str(secret) not in result.stderr
    assert not (workspace / "review").exists()


@pytest.mark.parametrize("category", ["connectors", "tasks"])
def test_connector_and_task_changes_are_never_selectable(
    workspace: Path, category: str
) -> None:
    _, snapshot, authored = prepare(workspace)
    authored["findings"][0]["category"] = category
    with pytest.raises(AUDIT.AuditError, match="report-only"):
        build(workspace, snapshot, authored)
    assert not (workspace / "review").exists()


@pytest.mark.parametrize("selected", [[], ["repair-rule"]])
def test_missing_audited_target_cannot_be_recreated_as_receipt(
    workspace: Path, selected: list[str]
) -> None:
    target, snapshot, authored = prepare(workspace)
    bundle_path, bundle = build(workspace, snapshot, authored)
    selection = select(workspace, bundle, selected)
    authorization = workspace / "authorization.json"
    AUDIT.check(bundle_path, selection, bundle["bundle_digest"], authorization)
    target.unlink()
    with pytest.raises(AUDIT.AuditError, match="must not be an audited target"):
        AUDIT.verify(authorization, target)
    assert not target.exists()


def test_unicode_separator_is_not_a_source_line_or_missing_newline(
    workspace: Path,
) -> None:
    before = "old\u2028instruction\npreserved\n"
    after = "new\u2028instruction\npreserved\n"
    _, snapshot, authored = prepare(workspace, before, after)
    assert AUDIT.load(snapshot)["sources"][0]["lines"] == 2
    _, bundle = build(workspace, snapshot, authored)
    diff = bundle["findings"][0]["change"]["diff"]
    assert "-old\u2028instruction\n+new\u2028instruction\n" in diff
    assert "\\ No newline" not in diff
