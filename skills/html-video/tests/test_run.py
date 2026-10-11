"""The step runner against a local stub toolchain: report binding, invalidation and font policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hv_config import load_config
from hv_run import (
    StepError,
    read_report,
    run_check,
    run_lint,
    run_render,
    run_snapshot,
)
from stubs import Rig, make_rig

CFG = load_config()
STEPS = ("lint", "check", "snapshot", "render")


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    return make_rig(tmp_path, monkeypatch, CFG)


def _report(rig: Rig, step: str) -> dict[str, Any]:
    report = read_report(rig.project, step)
    assert report is not None, step
    return report


def test_invalid_fps_aborts_and_removes_the_previous_report(rig: Rig) -> None:
    rig.run_all()
    for step, call in (("lint", run_lint), ("render", run_render)):
        with pytest.raises(StepError):
            call(rig.project, CFG, 0)
        assert read_report(rig.project, step) is None


def test_a_step_that_cannot_run_leaves_no_report(rig: Rig) -> None:
    rig.run_all()
    rig.control(fail=["lint", "check"])
    for step, call in (("lint", run_lint), ("check", run_check)):
        with pytest.raises(StepError):
            call(rig.project, CFG)
        assert read_report(rig.project, step) is None


def test_a_failing_tool_records_a_failed_report_replacing_the_passing_one(
    rig: Rig,
) -> None:
    rig.run_all()
    for step, call in (("snapshot", run_snapshot), ("render", run_render)):
        rig.control(fail=[step])
        outcome = call(rig.project, CFG)
        report = _report(rig, step)
        assert not outcome.ok and report["ok"] is False
        assert f"{step}_failed" in [f["code"] for f in report["findings"]]
        assert "sha256" not in report["detail"]


def test_a_blocked_rerun_replaces_the_old_report_with_a_failed_one(rig: Rig) -> None:
    rig.run_all()
    (rig.project / "index.html").write_text("<html><body>no composition</body></html>")
    for step, call in (
        ("lint", run_lint),
        ("check", run_check),
        ("render", run_render),
    ):
        assert not call(rig.project, CFG).ok
        assert _report(rig, step)["ok"] is False


def test_a_toolchain_that_drifted_aborts_and_removes_the_old_report(rig: Rig) -> None:
    rig.run_all()
    rig.write_browser("StubChrome 9.9")
    with pytest.raises(StepError, match="changed since bootstrap"):
        run_check(rig.project, CFG)
    assert read_report(rig.project, "check") is None


def test_source_edited_while_a_step_runs_cannot_pass(rig: Rig) -> None:
    rig.control(
        mutate_source={
            "path": str(rig.project / "index.html"),
            "text": "\n<!-- edited mid-run -->\n",
            "during": ["check"],
        }
    )
    outcome = run_check(rig.project, CFG)
    assert not outcome.ok and "source_changed" in [f.code for f in outcome.findings]
    assert _report(rig, "check")["ok"] is False


def test_the_observed_unmapped_font_degradation_fails_the_render(rig: Rig) -> None:
    rig.control(font_warning=True)
    outcome = run_render(rig.project, CFG)
    assert not outcome.ok
    finding = next(f for f in outcome.findings if f.code == "font_unmapped")
    assert "HV Text" in finding.message and "@font-face" in finding.message
    assert _report(rig, "render")["ok"] is False


def test_benign_compiler_logs_do_not_fail_the_render(rig: Rig) -> None:
    rig.control(benign_warning=True)
    outcome = run_render(rig.project, CFG)
    assert outcome.ok, outcome.findings
    assert json.dumps(_report(rig, "render")["findings"]).count("font_") == 0


@pytest.mark.parametrize(
    "relative",
    [
        "index.html",
        "index.motion.json",
        "renders/input.mp4",
        "assets/unreferenced.mp4",
        "renders/output.txt",
        "renders/directory.mp4",
    ],
)
def test_rejected_render_destination_preserves_source(rig: Rig, relative: str) -> None:
    target = rig.project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if relative == "renders/directory.mp4":
        target.mkdir()
    elif not target.exists():
        target.write_bytes(b"existing user content")
    if relative == "renders/input.mp4":
        entry = rig.project / "index.html"
        entry.write_text(
            entry.read_text().replace(
                "</body>", '<video src="renders/input.mp4"></video></body>'
            )
        )
    entry_before = (rig.project / "index.html").read_bytes()
    target_before = None if target.is_dir() else target.read_bytes()
    with pytest.raises(StepError):
        run_render(rig.project, CFG, output=target)
    assert (rig.project / "index.html").read_bytes() == entry_before
    if target_before is None:
        assert target.is_dir() and list(target.iterdir()) == []
    else:
        assert target.read_bytes() == target_before
    assert read_report(rig.project, "render") is None


def test_default_render_directory_cannot_escape_through_symlink(rig: Rig) -> None:
    outside = rig.scratch / "outside-render"
    outside.mkdir()
    (rig.project / "renders").symlink_to(outside, target_is_directory=True)
    with pytest.raises(StepError):
        run_render(rig.project, CFG)
    assert list(outside.iterdir()) == []
