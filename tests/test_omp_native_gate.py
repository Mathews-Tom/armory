"""Native acceptance report boundaries; these cases never launch a coding host."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from scripts import check_extensions
from scripts.package_types import TYPES


def _report(host: str = "omp") -> dict[str, object]:
    workspace = TYPES["extension"].repo_dir
    version: str = (
        json.loads((workspace / "package.json").read_text())["devDependencies"][
            "@oh-my-pi/pi-coding-agent"
        ]
        if host == "omp"
        else check_extensions._claude()[1].split()[0]
    )
    return {
        "schemaVersion": 1,
        "host": host,
        "mode": "rpc" if host == "omp" else "interactive",
        "version": version,
        "status": "passed",
        "scenarios": [
            {"name": name, "status": "passed"}
            for name in (
                "success",
                "failure",
                "reopen",
                "freshness",
                "changed-during-run",
                "cancellation",
                "private-output",
                "native-text",
            )
        ],
    }


def _negative_driver(
    feature: Path, report: dict[str, object], exit_code: int, host: str = "omp"
) -> None:
    tests = feature / "tests"
    tests.mkdir(parents=True)
    (tests / f"{host}-smoke.py").write_text(
        "import json, sys\nfrom pathlib import Path\n"
        f"value = json.loads({json.dumps(report)!r})\n"
        "Path(sys.argv[sys.argv.index('--report') + 1]).write_text(json.dumps(value))\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("host", ["omp", "claude"])
@pytest.mark.parametrize(
    "defect", ["empty", "duplicate", "failed", "boolean-schema", "wrong-host"]
)
def test_successful_driver_exit_cannot_certify_invalid_native_evidence(
    tmp_path: Path, defect: str, host: str
) -> None:
    report = _report(host)
    cases = cast(list[dict[str, str]], report["scenarios"])
    if defect == "empty":
        report["scenarios"] = []
    elif defect == "duplicate":
        report["scenarios"] = [*cases[:-1], cases[0]]
    elif defect == "failed":
        cases[0] = {"name": "success", "status": "failed"}
    elif defect == "boolean-schema":
        report["schemaVersion"] = True
    else:
        report["host"] = "claude" if host == "omp" else "omp"
    _negative_driver(tmp_path, report, 0, host)
    gate = (
        check_extensions.omp_native_gate
        if host == "omp"
        else check_extensions.claude_native_gate
    )
    with pytest.raises(check_extensions.GateFailure):
        gate(tmp_path)


def test_unavailable_native_prerequisite_stays_unavailable(tmp_path: Path) -> None:
    _negative_driver(
        tmp_path,
        {"status": "unavailable", "reasonCode": "host-authentication-unavailable"},
        check_extensions.EXIT_INCOMPLETE,
    )
    report = check_extensions.Report(scope="fixture", stage="omp")
    report.run("omp-native-smoke", lambda: check_extensions.omp_native_gate(tmp_path))
    assert report.exit_code == check_extensions.EXIT_INCOMPLETE
    assert report.feature_complete is False
    assert report.surfaces[0].status == "unavailable"


@pytest.mark.parametrize("status", ["unavailable", "failed"])
def test_native_diagnostic_does_not_render_private_or_control_text(
    tmp_path: Path, status: str
) -> None:
    private = "fixture-private-output\x1b[31m"
    _negative_driver(
        tmp_path,
        {"status": status, "reasonCode": private},
        check_extensions.EXIT_INCOMPLETE if status == "unavailable" else 1,
    )
    error = (
        check_extensions.GateUnavailable
        if status == "unavailable"
        else check_extensions.GateFailure
    )
    with pytest.raises(error) as caught:
        check_extensions.omp_native_gate(tmp_path)
    assert private not in str(caught.value)
    assert "\x1b" not in str(caught.value)


@pytest.mark.parametrize("host", ["omp", "claude"])
def test_native_evidence_for_another_artifact_cannot_certify_this_build(
    tmp_path: Path, host: str
) -> None:
    report = _report(host)
    report["artifact"] = {"contentManifestSha256": "0" * 64}
    report["artifactManifestSha256"] = "0" * 64
    _negative_driver(tmp_path, report, 0, host)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "armory-extension.json").write_text('{"selected":"artifact"}\n')
    gate = (
        check_extensions.omp_native_gate
        if host == "omp"
        else check_extensions.claude_native_gate
    )
    with pytest.raises(check_extensions.GateFailure, match="does not bind"):
        gate(tmp_path, artifact)


def test_actual_claude_driver_without_reviewed_context_is_unavailable(
    tmp_path: Path,
) -> None:
    feature = TYPES["extension"].repo_dir / "verification-receipts"
    report = tmp_path / "report.json"
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {"ARMORY_CLAUDE_NATIVE_CWD", "ARMORY_CLAUDE_NATIVE_SETTINGS"}
    }
    result = subprocess.run(
        [
            sys.executable,
            str(feature / "tests" / "claude-smoke.py"),
            "--feature-dir",
            str(feature),
            "--report",
            str(report),
        ],
        check=False,
        cwd=feature,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    evidence = json.loads(report.read_text())
    assert result.returncode == check_extensions.EXIT_INCOMPLETE
    assert evidence["status"] == "unavailable"
    assert evidence["reasonCode"] == "reviewed-native-settings-and-trusted-cwd-required"
    assert evidence["version"] is None
    assert not any(case["status"] == "passed" for case in evidence["scenarios"])
