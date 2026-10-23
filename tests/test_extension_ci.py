"""CI selection exercises real offline gates without launching a native session."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from scripts import build_extensions, check_extensions, package_types

WORKSPACE = package_types.TYPES["extension"].repo_dir
FIXTURE = WORKSPACE / "_fixtures" / "fixture-wordcount"
NAME = FIXTURE.name


@dataclass(frozen=True)
class CIWorkspace:
    root: Path
    feature: Path
    stage: str
    native_marker: Path

    def surface(self, name: str) -> str:
        return f"{NAME}[{self.stage}]:{name}"


@pytest.fixture(params=["omp", "full"])
def ci_workspace(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> CIWorkspace:
    """Copy sources/config, sharing only the installed, immutable dependencies."""
    stage = cast(str, request.param)
    root = tmp_path / "repository"
    extensions = root / "extensions"
    feature = extensions / NAME
    shutil.copytree(FIXTURE, feature)
    for name in ("package.json", "tsconfig.json", "eslint.config.js"):
        shutil.copy2(WORKSPACE / name, extensions / name)
    shutil.copytree(WORKSPACE / "_tooling", extensions / "_tooling")
    (extensions / "node_modules").symlink_to(
        WORKSPACE / "node_modules", target_is_directory=True
    )
    (root / ".claude-plugin").mkdir()
    shutil.copy2(
        WORKSPACE.parent / ".claude-plugin/plugin.json",
        root / ".claude-plugin/plugin.json",
    )
    shutil.copy2(WORKSPACE.parent / "LICENSE", root / "LICENSE")
    (root / "profiles.yaml").write_text("profiles: {}\n", encoding="utf-8")
    if stage == "omp":
        (feature / "EXTENSION.md").unlink()
        shutil.rmtree(feature / "claude-code")
    entries = [{"name": NAME, "version": "1.0.0"}] if stage == "full" else []
    manifest = root / "manifest.yaml"
    manifest.write_text(
        json.dumps({"packages": {"extensions": entries}}), encoding="utf-8"
    )
    monkeypatch.setattr(package_types, "REPO_ROOT", root)
    monkeypatch.setattr(build_extensions, "REPO_ROOT", root)
    monkeypatch.setattr(check_extensions, "REPO_ROOT", root)
    monkeypatch.setattr(check_extensions, "MANIFEST_PATH", manifest)

    marker = root / "native-driver-ran"
    (feature / "tests/omp-smoke.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('native driver must not run in CI')\n"
        "raise SystemExit(91)\n",
        encoding="utf-8",
    )
    return CIWorkspace(root, feature, stage, marker)


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, Any]]:
    code = check_extensions.main(argv)
    report = cast(dict[str, Any], json.loads(capsys.readouterr().out))
    assert report["exit_code"] == code
    return code, report


def _surfaces(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {surface["name"]: surface for surface in report["surfaces"]}


def _assert_ci_did_not_launch(
    workspace: CIWorkspace, report: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    assert not workspace.native_marker.exists()
    assert report["feature_complete"] is False
    surfaces = _surfaces(report)
    native = [surface for name, surface in surfaces.items() if "native-smoke" in name]
    assert native, report
    assert all(surface["status"] == "not-run" for surface in native), report
    return surfaces


def test_ci_runs_offline_gates_without_native_driver_and_manual_fails_closed(
    ci_workspace: CIWorkspace, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = _run(["--ci"], capsys)
    surfaces = _assert_ci_did_not_launch(ci_workspace, report)
    assert code == check_extensions.EXIT_OK, report
    build = "omp-prefix-build" if ci_workspace.stage == "omp" else "reproducible-build"
    assert surfaces[ci_workspace.surface(build)]["status"] == "passed", report
    assert surfaces[ci_workspace.surface("unit-tests")]["status"] == "passed", report
    if ci_workspace.stage == "full":
        for surface in (
            "omp-artifact",
            "claude-static-validation",
            "claude-native-tests",
            "omp-lifecycle",
            "claude-lifecycle",
        ):
            assert surfaces[ci_workspace.surface(surface)]["status"] == "passed", report
    else:
        assert not (ci_workspace.feature / "EXTENSION.md").exists()
        assert not (ci_workspace.feature / "claude-code").exists()

    argv = ["--feature", NAME]
    argv += ["--stage", "omp"] if ci_workspace.stage == "omp" else ["--native-smoke"]
    manual_code, manual = _run(argv, capsys)
    assert ci_workspace.native_marker.is_file()
    assert manual_code == check_extensions.EXIT_FAILED, manual
    assert _surfaces(manual)["omp-native-smoke"]["status"] == "failed", manual
    assert manual["feature_complete"] is False


def test_ci_rejects_a_real_adapter_that_registers_no_command(
    ci_workspace: CIWorkspace, capsys: pytest.CaptureFixture[str]
) -> None:
    (ci_workspace.feature / "omp/index.ts").write_text(
        "export default function brokenAdapter(): void {}\n", encoding="utf-8"
    )
    code, report = _run(["--ci"], capsys)
    surfaces = _assert_ci_did_not_launch(ci_workspace, report)
    assert code == check_extensions.EXIT_FAILED, report
    failure = "omp-prefix-build" if ci_workspace.stage == "omp" else "omp-artifact"
    assert surfaces[ci_workspace.surface(failure)]["status"] == "failed", report
    assert surfaces[ci_workspace.surface("typecheck")]["status"] == "passed", report


def test_ci_rejects_an_import_available_in_sources_but_outside_the_artifact(
    ci_workspace: CIWorkspace, capsys: pytest.CaptureFixture[str]
) -> None:
    (ci_workspace.feature.parent / "outside.ts").write_text(
        "export const outside = true;\n", encoding="utf-8"
    )
    entry = ci_workspace.feature / "omp/index.ts"
    entry.write_text(
        'import { outside } from "../../outside.ts";\n'
        'if (!outside) throw new Error("outside fixture");\n'
        + entry.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    code, report = _run(["--ci"], capsys)
    surfaces = _assert_ci_did_not_launch(ci_workspace, report)
    assert code == check_extensions.EXIT_FAILED, report
    failure = (
        "omp-prefix-build" if ci_workspace.stage == "omp" else "reproducible-build"
    )
    assert surfaces[ci_workspace.surface(failure)]["status"] == "failed", report
    for surface in ("typecheck", "lint", "unit-tests"):
        assert surfaces[ci_workspace.surface(surface)]["status"] == "passed", report


def test_ci_rejects_a_runtime_sdk_dependency_but_not_erased_sdk_types(
    ci_workspace: CIWorkspace, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = ci_workspace.feature / "omp/index.ts"
    sdk = "@oh-my-pi/pi-coding-agent/extensibility/extensions/types"
    entry.write_text(
        f'import {{ getExtensionUISelectOptionLabel }} from "{sdk}";\n'
        'if (getExtensionUISelectOptionLabel("fixture") !== "fixture") {\n'
        '  throw new Error("SDK runtime helper mismatch");\n'
        "}\n" + entry.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    code, report = _run(["--ci"], capsys)
    surfaces = _assert_ci_did_not_launch(ci_workspace, report)
    assert code == check_extensions.EXIT_FAILED, report
    failure = (
        "omp-prefix-build" if ci_workspace.stage == "omp" else "reproducible-build"
    )
    build = surfaces[ci_workspace.surface(failure)]
    assert build["status"] == "failed", report
    assert f"omp/index.ts imports '{sdk}'" in build["detail"], report
    assert "packages outside themselves" in build["detail"], report
    for surface in ("typecheck", "lint", "unit-tests"):
        assert surfaces[ci_workspace.surface(surface)]["status"] == "passed", report


def test_ci_probes_the_detached_adapter_not_only_the_source_factory(
    ci_workspace: CIWorkspace, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = ci_workspace.feature / "omp/index.ts"
    source_url = json.dumps(entry.resolve().as_uri())
    entry.write_text(
        f'if (import.meta.url !== {source_url}) throw new Error("detached fixture failure");\n'
        + entry.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    code, report = _run(["--ci"], capsys)
    surfaces = _assert_ci_did_not_launch(ci_workspace, report)
    assert code == check_extensions.EXIT_FAILED, report
    failure = "omp-prefix-build" if ci_workspace.stage == "omp" else "omp-artifact"
    assert surfaces[ci_workspace.surface(failure)]["status"] == "failed", report
    for surface in ("typecheck", "lint", "unit-tests"):
        assert surfaces[ci_workspace.surface(surface)]["status"] == "passed", report


def test_ci_fails_for_an_adapter_bun_case_even_at_the_core_stage(
    ci_workspace: CIWorkspace, capsys: pytest.CaptureFixture[str]
) -> None:
    (ci_workspace.feature / "tests/adapter.test.ts").write_text(
        'import { expect, test } from "bun:test";\n'
        'test("failing adapter contract", () => { expect("actual").toBe("expected"); });\n',
        encoding="utf-8",
    )
    code, report = _run(["--ci"], capsys)
    surfaces = _assert_ci_did_not_launch(ci_workspace, report)
    assert code == check_extensions.EXIT_FAILED, report
    assert surfaces[ci_workspace.surface("unit-tests")]["status"] == "failed", report
    assert surfaces[ci_workspace.surface("typecheck")]["status"] == "passed", report
    if ci_workspace.stage == "omp":
        shutil.rmtree(ci_workspace.feature / "omp")
        core = CIWorkspace(
            ci_workspace.root, ci_workspace.feature, "core", ci_workspace.native_marker
        )
        core_code, core_report = _run(["--ci"], capsys)
        core_surfaces = _assert_ci_did_not_launch(core, core_report)
        assert core_code == check_extensions.EXIT_FAILED, core_report
        assert core_surfaces[core.surface("unit-tests")]["status"] == "failed", (
            core_report
        )


def test_ci_keeps_missing_required_offline_tools_nonzero(
    ci_workspace: CIWorkspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty_path = tmp_path / "no-tools"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))
    code, report = _run(["--ci"], capsys)
    surfaces = _assert_ci_did_not_launch(ci_workspace, report)
    assert code != check_extensions.EXIT_OK, report
    assert surfaces[ci_workspace.surface("toolchain")]["status"] == "unavailable", (
        report
    )


def test_ci_keeps_applicable_static_source_failures_nonzero(
    ci_workspace: CIWorkspace, capsys: pytest.CaptureFixture[str]
) -> None:
    if ci_workspace.stage == "full":
        shutil.rmtree(ci_workspace.feature / "claude-code/mod-checks")
        failure = "claude-native-tests"
    else:
        (ci_workspace.feature / "core/private.key").write_text(
            "forbidden distributable input\n", encoding="utf-8"
        )
        failure = "core-sources"
    code, report = _run(["--ci"], capsys)
    surfaces = _assert_ci_did_not_launch(ci_workspace, report)
    assert code == check_extensions.EXIT_FAILED, report
    assert surfaces[ci_workspace.surface(failure)]["status"] == "failed", report


@pytest.mark.parametrize("bundle_fault", ["different-bytes", "invalid-syntax"])
def test_ci_rejects_bad_real_bundle_process_outputs(
    ci_workspace: CIWorkspace,
    bundle_fault: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Delegate to real Bun, then corrupt only its actual bundle process output."""
    bun = shutil.which("bun")
    assert bun is not None, "the offline test toolchain requires pinned Bun"
    bin_dir = tmp_path / "bundle-tool"
    bin_dir.mkdir()
    marker = tmp_path / "bundle-process-ran"
    wrapper = bin_dir / "bun"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, subprocess, sys\n"
        f"real_bun = {bun!r}\n"
        "args = sys.argv[1:]\n"
        "is_source_tool = any(arg.endswith('/build-inputs.ts') for arg in args)\n"
        "request = sys.stdin.read() if is_source_tool else None\n"
        "result = subprocess.run([real_bun, *args], input=request, capture_output=True, text=True)\n"
        "output = result.stdout\n"
        "if result.returncode == 0 and request and json.loads(request).get('action') == 'bundle':\n"
        f"    marker = pathlib.Path({str(marker)!r})\n"
        "    previous = marker.read_text() if marker.exists() else ''\n"
        "    marker.write_text(previous + 'x')\n"
        f"    if {bundle_fault!r} == 'invalid-syntax':\n"
        "        output = 'export const = ;\\n'\n"
        "    else:\n"
        "        output += '\\n// bundle fixture ' + previous + '\\n'\n"
        "sys.stdout.write(output)\n"
        "sys.stderr.write(result.stderr)\n"
        "raise SystemExit(result.returncode)\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    code, report = _run(["--ci"], capsys)
    surfaces = _assert_ci_did_not_launch(ci_workspace, report)
    assert marker.is_file(), "the real bundling process must run"
    assert code == check_extensions.EXIT_FAILED, report
    failure = (
        "omp-prefix-build" if ci_workspace.stage == "omp" else "reproducible-build"
    )
    assert surfaces[ci_workspace.surface(failure)]["status"] == "failed", report
