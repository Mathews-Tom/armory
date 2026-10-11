"""Toolchain pin checks and the coverage policy applied to check/render output."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from helpers import write
from hv_audit import Clip, Composition
from hv_config import load_config
from hv_env import (
    EnvError,
    child_env,
    detect_package_manager,
    install_command,
    installed_cli,
    verify_environment,
)
from hv_run import (
    StepError,
    evaluate_check_report,
    evaluate_render_probe,
    frame_times,
    parse_json_output,
    select_evenly,
    validate_fps,
)

CFG = load_config()


# -- pin and package manager ------------------------------------------------------


@pytest.mark.parametrize(
    ("lockfile", "manager"),
    [
        ("package-lock.json", "npm"),
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lock", "bun"),
        ("bun.lockb", "bun"),
    ],
)
def test_package_manager_follows_the_project_lockfile(
    tmp_path: Path, lockfile: str, manager: str
) -> None:
    write(tmp_path, lockfile, "")
    assert detect_package_manager(tmp_path) == manager


def test_fresh_project_uses_npm_and_conflicting_lockfiles_are_refused(
    tmp_path: Path,
) -> None:
    assert detect_package_manager(tmp_path) == "npm"
    write(tmp_path, "yarn.lock", "")
    write(tmp_path, "package-lock.json", "{}")
    with pytest.raises(EnvError, match="multiple"):
        detect_package_manager(tmp_path)


@pytest.mark.parametrize("manager", ["npm", "pnpm", "yarn", "bun"])
def test_install_command_pins_the_exact_spec_from_config(manager: str) -> None:
    argv = install_command(manager, CFG.spec)
    assert argv[0] == manager and argv[-1] == CFG.spec
    assert any("exact" in arg for arg in argv)
    assert "@latest" not in " ".join(argv)


def _install(
    project: Path, version: str, bin_value: object = "bin/hyperframes.mjs"
) -> None:
    write(
        project,
        f"node_modules/{CFG.package}/package.json",
        json.dumps({"name": CFG.package, "version": version, "bin": bin_value}),
    )
    write(project, f"node_modules/{CFG.package}/bin/hyperframes.mjs", "// cli")


def test_installed_cli_must_exist_and_match_the_pinned_version(tmp_path: Path) -> None:
    with pytest.raises(EnvError, match="bootstrap"):
        installed_cli(tmp_path, CFG)
    _install(tmp_path, "0.0.1")
    with pytest.raises(EnvError, match="pinned version"):
        installed_cli(tmp_path, CFG)
    _install(tmp_path, CFG.version)
    cli, version = installed_cli(tmp_path, CFG)
    assert version == CFG.version and cli.name == "hyperframes.mjs"


def test_installed_cli_accepts_a_bin_map_and_rejects_a_missing_entry_point(
    tmp_path: Path,
) -> None:
    _install(tmp_path, CFG.version, {CFG.package: "bin/hyperframes.mjs", "other": "x"})
    assert installed_cli(tmp_path, CFG)[0].is_file()
    _install(tmp_path, CFG.version, "bin/gone.mjs")
    with pytest.raises(EnvError, match="missing"):
        installed_cli(tmp_path, CFG)


def _lock(project: Path, tool: str, browser: str, hyperframes_version: str) -> None:
    entry = {"path": tool, "version": "x"}
    document = {
        "schema": 1,
        "hyperframes": {
            "package": CFG.package,
            "version": hyperframes_version,
            "cli": "node_modules/x",
            "package_manager": "npm",
        },
        "node": entry,
        "ffmpeg": entry,
        "ffprobe": entry,
        "browser": {"path": browser, "version": "1", "source": "user-path"},
    }
    write(project, ".html-video/environment.json", json.dumps(document))


def test_verify_environment_reports_every_problem_without_launching_anything(
    tmp_path: Path,
) -> None:
    env, problems = verify_environment(tmp_path, CFG)
    assert env is None and "bootstrap" in problems[0]
    _lock(tmp_path, str(tmp_path / "no-node"), str(tmp_path / "no-chrome"), "0.0.1")
    env, problems = verify_environment(tmp_path, CFG)
    joined = "\n".join(problems)
    assert env is not None
    assert (
        "config.toml pins" in joined
        and "browser recorded at" in joined
        and "node recorded at" in joined
    )
    assert "not installed" in joined


def test_recorded_tool_whose_version_changed_is_detected(tmp_path: Path) -> None:
    _lock(tmp_path, sys.executable, sys.executable, CFG.version)
    _, problems = verify_environment(tmp_path, CFG)
    assert any("changed since bootstrap" in p and "browser" in p for p in problems)


def test_child_environment_scrubs_pins_and_disables_telemetry(tmp_path: Path) -> None:
    _lock(tmp_path, sys.executable, sys.executable, CFG.version)
    env, _ = verify_environment(tmp_path, CFG)
    assert env is not None
    base = {
        "GEMINI_API_KEY": "secret",
        "HYPERFRAMES_BROWSER_PATH": "/stale",
        "PATH": "/bin",
        "HOME": "/h",
    }
    merged = child_env(CFG, env, base)
    assert "GEMINI_API_KEY" not in merged
    assert (
        merged["HYPERFRAMES_NO_TELEMETRY"] == "1"
        and merged["HYPERFRAMES_NO_UPDATE_CHECK"] == "1"
    )
    assert (
        merged["HYPERFRAMES_BROWSER_PATH"]
        == merged["PRODUCER_HEADLESS_SHELL_PATH"]
        == env.browser.path
    )
    assert merged["PATH"] == "/bin"
    bootstrap_env = child_env(CFG, None, base)
    assert (
        "HYPERFRAMES_BROWSER_PATH" not in bootstrap_env
    )  # a stale shell override must not steer browser selection


# -- sample planning --------------------------------------------------------------


def _comp(clips: list[Clip], duration: float = 10.0) -> Composition:
    return Composition(1920, 1080, duration, tuple(clips), True, True)


def test_frame_times_cover_boundaries_ends_and_stay_on_the_frame_grid() -> None:
    comp = _comp([Clip("a", 0, 3.5), Clip("b", 3.5, 10)])
    times = frame_times(comp, 30, 80)
    assert times[0] == 0 and times[-1] == round(299 / 30, 4)
    assert {3.4667, 3.5, 3.5333} <= set(times)
    assert times == sorted(set(times))
    assert all(abs(t * 30 - round(t * 30)) < 0.01 for t in times)
    assert max(times) < comp.duration


def test_frame_times_cap_keeps_the_ends_and_exact_boundaries() -> None:
    clips = [Clip(f"c{i}", i, i + 1) for i in range(9)]
    times = frame_times(_comp(clips), 30, 6)
    assert len(times) == 6 and times[0] == 0 and times[-1] == round(299 / 30, 4)
    assert 3.0 in times


def test_select_evenly_and_fps_validation() -> None:
    assert select_evenly([1.0, 2.0], 5) == [1.0, 2.0]
    picked = select_evenly([float(i) for i in range(30)], 5)
    assert picked[0] == 0 and picked[-1] == 29 and len(picked) == 5
    for bad in (0, -1, 121, True):
        with pytest.raises(StepError):
            validate_fps(bad)


# -- check coverage policy ----------------------------------------------------------


def _report(**overrides: object) -> dict[str, object]:
    report: dict[str, object] = {
        "ok": True,
        "browserSkipped": False,
        "lint": {"errorCount": 0, "warningCount": 0},
        "runtime": {"errorCount": 0, "warningCount": 0},
        "layout": {"errorCount": 0, "warningCount": 0, "samples": [0, 1.5, 3]},
        "motion": {"errorCount": 0, "warningCount": 0, "enabled": True, "samples": 61},
        "contrast": {
            "errorCount": 0,
            "warningCount": 0,
            "enabled": True,
            "checked": 6,
            "passed": 6,
        },
        "_meta": {"version": CFG.version},
    }
    report.update(overrides)
    return report


def _evaluate(
    report: dict[str, object],
    animated: bool = True,
    has_text: bool = True,
    requested: list[float] | None = None,
) -> list[str]:
    findings = evaluate_check_report(
        report,
        requested=requested or [0, 1.5, 3],
        animated=animated,
        has_text=has_text,
        expected_version=CFG.version,
    )
    return [f.code for f in findings if f.severity == "error"]


def test_complete_coverage_has_no_errors() -> None:
    assert _evaluate(_report()) == []


def test_browser_skipped_or_failed_check_is_never_a_pass() -> None:
    assert "browser_skipped" in _evaluate(_report(browserSkipped=True))
    assert "browser_skipped" in _evaluate(
        {k: v for k, v in _report().items() if k != "browserSkipped"}
    )
    assert "check_failed" in _evaluate(_report(ok=False))
    assert _evaluate({"ok": False, "error": "chrome crashed"}) == ["check_error"]
    assert "check_version_mismatch" in _evaluate(_report(_meta={"version": "9.9.9"}))


def test_requested_boundary_times_must_actually_have_been_sampled() -> None:
    layout = {"errorCount": 0, "warningCount": 0, "samples": [0, 3]}
    assert "samples_missing" in _evaluate(_report(layout=layout))
    assert "no_layout_samples" in _evaluate(_report(layout={"samples": []}))
    near = {
        "errorCount": 0,
        "warningCount": 0,
        "samples": [0, 1.733, 3],
    }  # the CLI rounds to 3 decimals
    assert _evaluate(_report(layout=near), requested=[0, 1.7333, 3]) == []


def test_animated_composition_must_have_run_motion_checks() -> None:
    off = {"errorCount": 0, "warningCount": 0, "enabled": False, "samples": 0}
    assert "motion_unproven" in _evaluate(_report(motion=off))
    assert "motion_unproven" not in _evaluate(_report(motion=off), animated=False)


def test_text_requires_checked_contrast_pairs_and_absent_text_is_not_a_proof() -> None:
    unchecked = {
        "errorCount": 0,
        "warningCount": 0,
        "enabled": True,
        "checked": 0,
        "passed": 0,
    }
    assert "contrast_unproven" in _evaluate(_report(contrast=unchecked))
    findings = evaluate_check_report(
        _report(contrast=unchecked),
        requested=[0, 1.5, 3],
        animated=True,
        has_text=False,
        expected_version=CFG.version,
    )
    assert [(f.code, f.severity) for f in findings] == [
        ("contrast_not_applicable", "warning")
    ]


def test_json_output_tolerates_leading_log_noise_but_not_garbage() -> None:
    assert parse_json_output('[INFO] compiling\n{"ok": true}\n') == {"ok": True}
    with pytest.raises(StepError):
        parse_json_output("no json here")


# -- render output policy -------------------------------------------------------------


def _probe(
    width: int = 1920,
    height: int = 1080,
    rate: str = "30/1",
    duration: str = "10.000000",
    frames: str = "300",
) -> dict[str, object]:
    stream = {
        "width": width,
        "height": height,
        "r_frame_rate": rate,
        "duration": duration,
        "nb_frames": frames,
    }
    return {"streams": [stream], "format": {"duration": duration}}


def test_render_matching_the_declared_composition_passes() -> None:
    assert evaluate_render_probe(_probe(), _comp([]), 30) == []


@pytest.mark.parametrize(
    "probe",
    [
        _probe(width=1280),
        _probe(rate="24/1"),
        _probe(duration="9.0"),
        _probe(duration="n/a"),
        _probe(frames="120"),
        {"streams": []},
    ],
)
def test_render_that_differs_from_the_declaration_is_rejected(
    probe: dict[str, object],
) -> None:
    findings = evaluate_render_probe(probe, _comp([]), 30)
    assert findings and all(f.code == "render_mismatch" for f in findings)
