"""Native acceptance report boundaries; these cases never launch a coding host."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from scripts import check_extensions
from scripts.package_types import TYPES


def _report() -> dict[str, object]:
    workspace = TYPES["extension"].repo_dir
    version: str = json.loads((workspace / "package.json").read_text())[
        "devDependencies"
    ]["@oh-my-pi/pi-coding-agent"]
    return {
        "schemaVersion": 1,
        "host": "omp",
        "mode": "rpc",
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


def _negative_driver(feature: Path, report: dict[str, object], exit_code: int) -> None:
    tests = feature / "tests"
    tests.mkdir(parents=True)
    (tests / "omp-smoke.py").write_text(
        "import json, sys\nfrom pathlib import Path\n"
        f"value = json.loads({json.dumps(report)!r})\n"
        "Path(sys.argv[sys.argv.index('--report') + 1]).write_text(json.dumps(value))\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "defect", ["empty", "duplicate", "failed", "boolean-schema", "wrong-host"]
)
def test_successful_driver_exit_cannot_certify_invalid_native_evidence(
    tmp_path: Path, defect: str
) -> None:
    report = _report()
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
        report["host"] = "claude"
    _negative_driver(tmp_path, report, 0)
    with pytest.raises(check_extensions.GateFailure):
        check_extensions.omp_native_gate(tmp_path)


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


def test_native_diagnostic_does_not_render_private_or_control_text(
    tmp_path: Path,
) -> None:
    private = "fixture-private-output\x1b[31m"
    _negative_driver(
        tmp_path,
        {"status": "unavailable", "reasonCode": private},
        check_extensions.EXIT_INCOMPLETE,
    )
    with pytest.raises(check_extensions.GateUnavailable) as caught:
        check_extensions.omp_native_gate(tmp_path)
    assert private not in str(caught.value)
    assert "\x1b" not in str(caught.value)
