"""Delivery completeness: source, assets, licences, current reports and the MP4 travel together.

Reports come from the real step runner driven through a local stub toolchain, so
every staleness case below is produced the way a user would produce it.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from helpers import write
from hv_config import Config, load_config
from hv_deliver import deliver
from hv_run import StepError, read_report, run_lint, run_render
from stubs import STUB_CLI, Rig, make_rig

CFG = load_config()
STEPS = ("lint", "check", "snapshot", "render")


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    rig = make_rig(tmp_path, monkeypatch, CFG)
    rig.run_all()
    return rig


def _codes(
    rig: Rig, name: str = "bundle", cfg: Config = CFG, fps: int | None = None
) -> list[str]:
    return [f.code for f in deliver(rig.project, rig.scratch / name, cfg, fps).findings]


def _video(rig: Rig) -> Path:
    return rig.project / "renders" / f"{rig.project.name}.mp4"


def _edit_source(rig: Rig) -> None:
    html = rig.project / "index.html"
    html.write_text(html.read_text() + "\n<!-- edited after the reports -->\n")


def test_a_new_environment_is_recorded_not_relabelled_over_old_results(
    rig: Rig,
) -> None:
    rig.rebootstrap_browser("StubChrome 2.0")
    assert "report_environment_mismatch" in _codes(rig, "old")
    rig.run_all()
    out = rig.scratch / "new"
    assert deliver(rig.project, out, CFG).ok
    record = json.loads((out / "RENDER.json").read_text())
    assert record["environment"]["browser"]["version"] == "StubChrome 2.0"
    for step in STEPS:
        report = json.loads((out / "reports" / f"{step}.json").read_text())
        assert report["environment"]["browser"]["version"] == "StubChrome 2.0"


def test_recorded_timestamps_are_informational_only(rig: Rig) -> None:
    for step in STEPS:
        path = rig.project / ".html-video/reports" / f"{step}.json"
        report = json.loads(path.read_text())
        report["recorded_at"] = "1999-01-01T00:00:00+00:00"
        path.write_text(json.dumps(report))
    assert deliver(rig.project, rig.scratch / "bundle", CFG).ok


def test_editing_the_source_after_a_report_makes_every_report_stale(rig: Rig) -> None:
    _edit_source(rig)
    codes = _codes(rig)
    assert codes.count("report_stale") == 4
    assert not (rig.scratch / "bundle").exists()


def test_missing_or_failed_reports_block_delivery(rig: Rig) -> None:
    (rig.project / ".html-video/reports/snapshot.json").unlink()
    rig.control(fail=["render"])
    assert not run_render(rig.project, CFG).ok
    codes = _codes(rig)
    assert "report_missing" in codes and "report_failed" in codes


def test_a_failed_or_aborted_rerun_cannot_leave_a_passing_report_behind(
    rig: Rig,
) -> None:
    rig.control(fail=["lint"])
    with pytest.raises(StepError):
        run_lint(rig.project, CFG)
    assert read_report(rig.project, "lint") is None
    assert "report_missing" in _codes(rig)
    rig.control()
    assert run_lint(rig.project, CFG).ok
    assert deliver(rig.project, rig.scratch / "again", CFG).ok

    rig.control(fail=["render"])
    assert not run_render(rig.project, CFG).ok
    assert "report_failed" in _codes(rig, "after-failed-render")


def test_a_rerun_that_cannot_verify_the_toolchain_invalidates_the_old_report(
    rig: Rig,
) -> None:
    rig.write_browser("StubChrome 9.9")  # drifted since bootstrap, lock not refreshed
    with pytest.raises(StepError):
        run_render(rig.project, CFG)
    assert read_report(rig.project, "render") is None
    assert "report_missing" in _codes(rig)


def test_a_valid_rerun_delivers_the_new_video_not_the_old_one(rig: Rig) -> None:
    rig.control(video_tag="-second")
    assert run_render(rig.project, CFG).ok
    out = rig.scratch / "bundle"
    assert deliver(rig.project, out, CFG).ok
    assert (out / _video(rig).name).read_bytes().endswith(b"-second")


def test_video_that_changed_or_vanished_after_rendering_is_refused(rig: Rig) -> None:
    video = _video(rig)
    original = video.read_bytes()
    video.write_bytes(b"x" * len(original))  # same size, different content
    assert "video_changed" in _codes(rig, "a")
    video.write_bytes(original + b"!")
    assert "video_changed" in _codes(rig, "b")
    video.unlink()
    assert "video_missing" in _codes(rig, "c")


def test_snapshot_evidence_must_still_match_the_report(rig: Rig) -> None:
    snapshots = rig.project / ".html-video/snapshots"
    original = (snapshots / "frame-00.png").read_bytes()
    (snapshots / "frame-00.png").write_bytes(b"other")
    assert "snapshot_changed" in _codes(rig, "altered")
    (snapshots / "frame-00.png").write_bytes(original)
    (snapshots / "frame-99.png").write_bytes(b"extra frame")
    assert "snapshot_changed" in _codes(rig, "extra")
    (snapshots / "frame-99.png").unlink()
    (snapshots / "contact-sheet-2.jpg").write_bytes(b"another sheet")
    assert "snapshot_changed" in _codes(rig, "sheet")
    (snapshots / "contact-sheet-2.jpg").unlink()
    assert "snapshot_changed" in _codes(rig, "no-sheet")
    (snapshots / "contact-sheet-2.jpg").write_bytes(b"jpg2")
    (snapshots / "frame-00.png").unlink()
    assert "snapshot_changed" in _codes(rig, "gone")


def test_missing_licence_record_or_asset_declaration_blocks_delivery(rig: Rig) -> None:
    licence = next((rig.project / "assets/fonts/licenses").iterdir())
    licence.unlink()
    assert "provenance_license_missing" in _codes(rig)


def test_a_non_empty_output_directory_is_never_overwritten(rig: Rig) -> None:
    out = write(rig.scratch, "bundle/keep.txt", "mine").parent
    assert "output_not_empty" in _codes(rig)
    assert (out / "keep.txt").read_text() == "mine"


# -- toolchain, config and fps bindings ---------------------------------------------


def test_a_browser_swap_after_the_reports_is_refused(rig: Rig) -> None:
    rig.rebootstrap_browser("StubChrome 2.0")
    result = deliver(rig.project, rig.scratch / "bundle", CFG)
    assert [f.code for f in result.findings].count("report_environment_mismatch") == 4
    assert "browser.version" in result.findings[0].message
    assert not (rig.scratch / "bundle").exists()


def test_a_tool_that_drifted_since_bootstrap_is_refused_before_any_copy(
    rig: Rig,
) -> None:
    rig.write_browser("StubChrome 9.9")
    codes = _codes(rig)
    assert "environment_invalid" in codes
    assert not (rig.scratch / "bundle").exists()


def test_a_changed_hyperframes_package_file_is_refused(rig: Rig) -> None:
    rig.replace_cli(STUB_CLI + "\n# a different build\n")
    result = deliver(rig.project, rig.scratch / "bundle", CFG)
    assert [f.code for f in result.findings].count("report_environment_mismatch") == 4
    assert "cli_sha256" in result.findings[0].message


def test_a_bumped_pin_is_refused(rig: Rig) -> None:
    bumped = dataclasses.replace(CFG, version="9.9.9")
    assert "environment_invalid" in _codes(rig, cfg=bumped)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workers", CFG.workers + 1),
        ("check_timeout_ms", CFG.check_timeout_ms + 1),
        ("max_check_samples", CFG.max_check_samples - 1),
        ("snapshot_frames", CFG.snapshot_frames - 1),
        ("forced_env", {**CFG.forced_env, "EXTRA": "1"}),
        ("scrubbed_env", ()),
    ],
)
def test_changed_config_after_the_reports_is_refused(
    rig: Rig, field: str, value: object
) -> None:
    changed = dataclasses.replace(CFG, **{field: value})
    codes = _codes(rig, cfg=changed)
    assert codes.count("report_config_mismatch") == 4


def test_changing_only_the_config_default_fps_does_not_hide_an_fps_mismatch(
    rig: Rig,
) -> None:
    other_default = dataclasses.replace(CFG, fps=24)
    codes = _codes(rig, cfg=other_default)
    assert codes.count("report_fps_mismatch") == 4
    assert "report_config_mismatch" not in codes
    assert deliver(rig.project, rig.scratch / "explicit", other_default, CFG.fps).ok


def test_fps_must_be_the_same_for_every_report_and_the_delivery(rig: Rig) -> None:
    rig.set_probe(24)
    assert run_render(rig.project, CFG, 24).ok  # only render moves to 24
    assert _codes(rig, "mixed").count("report_fps_mismatch") == 1
    assert _codes(rig, "mixed-24", fps=24).count("report_fps_mismatch") == 3
    rig.run_all(24)
    assert _codes(rig, "default").count("report_fps_mismatch") == 4
    assert deliver(rig.project, rig.scratch / "explicit", CFG, 24).ok
    assert "fps_invalid" in _codes(rig, "invalid", fps=0)


@pytest.mark.parametrize(
    ("section", "mutate"),
    [
        ("fps", lambda report: report.update(fps=report["fps"] + 1)),
        (
            "environment",
            lambda report: report["environment"]["node"].update(version="v1"),
        ),
        ("config", lambda report: report["config"].update(workers=99)),
        ("environment", lambda report: report.pop("environment")),
    ],
)
def test_an_edited_or_unbound_report_is_refused(
    rig: Rig, section: str, mutate: Callable[[dict[str, Any]], object]
) -> None:
    path = rig.project / ".html-video/reports/check.json"
    report = json.loads(path.read_text())
    mutate(report)
    path.write_text(json.dumps(report))
    assert f"report_{section}_mismatch" in _codes(rig)
