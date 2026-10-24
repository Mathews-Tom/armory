"""Real helper/dispatch admission tests; all managed children are Python pass."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from scripts.omp_preflight import (
    PreflightAdmissionError,
    ProjectAdmission,
    derive_runner_invocation,
    issue_admission,
    load_project_config,
    required_dispatch_inputs,
    synthetic_sentinel,
)
from scripts.omp_skillsbench import (
    OmpCell,
    OmpRunContract,
    declared_omp_cells,
    load_omp_run_contract,
)
from scripts.omp_skillsbench_dispatch import CellDispatchError, dispatch_cell

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_PATH = _REPO_ROOT / "evals" / "skillsbench" / "omp_run.yaml"


def _json_file(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _object_file(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _binding(path: Path) -> dict[str, str]:
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class AdmissionProject:
    config: Path
    declaration: Path
    receipts: Path
    source: Path
    selection: Path
    data: Path
    identity: Path
    contract: OmpRunContract
    cell: OmpCell

    def issue(self) -> ProjectAdmission:
        return issue_admission(self.config, self.declaration)


def make_admission_project(
    root: Path, *, receipt_root: Path | None = None, cell_index: int = 0
) -> AdmissionProject:
    """Fresh explicit synthetic authority, separate from frozen study approval."""
    root.mkdir(parents=True, exist_ok=True)
    receipts = receipt_root if receipt_root is not None else root / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    source = root / "selected-source.txt"
    selection = root / "selected-config.json"
    data = root / "selected-data.txt"
    identity = root / "identity.json"
    source.write_text("selected synthetic source\n", encoding="utf-8")
    _json_file(selection, {"selected": "synthetic-only"})
    data.write_text("selected synthetic data\n", encoding="utf-8")
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=10)
    _json_file(
        identity,
        {
            "schemaVersion": 1,
            "provider": "synthetic-local",
            "profile": "m4-benchmark",
            "accountFingerprint": "synthetic-no-account",
            "kind": "synthetic-local",
            "auth": "not-applicable",
            "observedAt": _utc(now),
            "expiresAt": _utc(expires),
        },
    )
    bridge = _REPO_ROOT / "scripts" / "omp_preflight_cli.py"
    config = root / "project.json"
    _json_file(
        config,
        {
            "schemaVersion": 1,
            "adapterId": "omp-skillsbench",
            "adapterVersion": 1,
            "coreVersion": "1.0.0",
            "packageRoot": str(_REPO_ROOT / "extensions" / "run-preflight"),
            "helperPath": "helpers/cli.ts",
            "projectRoot": str(_REPO_ROOT),
            "contractPath": str(_CONTRACT_PATH),
            "bridgeArgv": [sys.executable, str(bridge), "--synthetic-sentinel"],
        },
    )
    contract = load_omp_run_contract(_CONTRACT_PATH)
    cell = declared_omp_cells(contract)[cell_index]
    target = next(target for target in contract.targets if target.id == cell.target_id)
    invocation = derive_runner_invocation(contract, cell, target, receipts)
    required = required_dispatch_inputs(load_project_config(config), contract, cell)
    canonical = json.dumps(
        invocation, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    declaration = root / "declaration.json"
    _json_file(
        declaration,
        {
            "schemaVersion": 1,
            "runId": "synthetic-admission-test",
            "purpose": "synthetic-local-sentinel",
            "issuedAt": _utc(now),
            "expiresAt": _utc(expires),
            "configSha256": _binding(config)["sha256"],
            "invocation": invocation,
            "inputs": {
                "source": [
                    *[_binding(path) for path in required["source"]],
                    _binding(source),
                ],
                "config": [
                    *[_binding(path) for path in required["config"]],
                    _binding(selection),
                ],
                "data": [
                    _binding(data),
                    *[_binding(path) for path in required["data"]],
                ],
                "identity": _binding(identity),
            },
            "checkpoint": {"path": str(receipts.resolve())},
            "limits": {
                "calls": {"value": 1, "required": False},
                "workers": {"value": 1, "required": False},
                "concurrency": {"value": 1, "required": False},
                "wallSeconds": {"value": 630, "required": True},
                "tokens": None,
                "currency": None,
            },
            "quota": {
                "status": "unknown",
                "observedAt": _utc(now),
                "expiresAt": _utc(expires),
                "reason": "No provider observation in a synthetic local test",
                "source": "synthetic-test",
                "remainingCalls": None,
            },
            "authorizations": [
                {
                    "runId": "synthetic-admission-test",
                    "purpose": "synthetic-local-sentinel",
                    "accountFingerprint": "synthetic-no-account",
                    "scope": "local-sentinel-only",
                    "invocationSha256": hashlib.sha256(
                        canonical.encode("utf-8")
                    ).hexdigest(),
                    "acknowledgeUnknownQuota": True,
                    "issuedAt": _utc(now),
                    "expiresAt": _utc(expires),
                }
            ],
        },
    )
    return AdmissionProject(
        config, declaration, receipts, source, selection, data, identity, contract, cell
    )


class PythonPassRunner:
    """Count actual harmless children, not calls to a fabricated completion."""

    def __init__(self) -> None:
        self.children: list[subprocess.CompletedProcess[str]] = []

    def __call__(
        self, command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command[0] == "omp"  # This argv must never reach subprocess.run.
        assert kwargs["timeout"] == 630
        assert kwargs["stdin"] is subprocess.DEVNULL
        child = subprocess.run(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=630,
        )
        self.children.append(child)
        return child


def test_fresh_synthetic_admission_reaches_one_real_child_without_receipt(
    tmp_path: Path,
) -> None:
    project = make_admission_project(tmp_path)
    admission = project.issue()
    runner = PythonPassRunner()
    assert admission.status == "unknown"
    assert runner.children == []  # Normal check did not invoke this managed runner.
    with pytest.raises(CellDispatchError, match="terminal receipt failed"):
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert len(runner.children) == 1
    assert runner.children[0].returncode == 0
    assert runner.children[0].stdout == ""
    assert list(project.receipts.rglob("*.json")) == []


def test_missing_admission_reaches_no_managed_child(tmp_path: Path) -> None:
    project = make_admission_project(tmp_path)
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError, match="complete project admission"):
        dispatch_cell(project.contract, project.cell, project.receipts, runner)
    assert runner.children == []


@pytest.mark.parametrize(
    "changed",
    [
        "source",
        "selection",
        "data",
        "identity",
        "declaration",
        "config",
        "checkpoint",
        "declared-cap",
    ],
)
def test_prerequisite_races_refuse_actual_runner(tmp_path: Path, changed: str) -> None:
    project = make_admission_project(tmp_path)
    admission = project.issue()
    runner = PythonPassRunner()
    if changed == "checkpoint":
        project.receipts.rename(tmp_path / "old-checkpoint")
        project.receipts.mkdir()
    elif changed == "identity":
        identity = _object_file(project.identity)
        identity["accountFingerprint"] = "other-synthetic-account"
        _json_file(project.identity, identity)
    elif changed == "declared-cap":
        declaration = _object_file(project.declaration)
        cast(dict[str, object], declaration["limits"])["tokens"] = {
            "value": 1,
            "required": True,
        }
        _json_file(project.declaration, declaration)
    else:
        path = cast(Path, getattr(project, changed))
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(PreflightAdmissionError):
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


@pytest.mark.parametrize(
    "changed",
    [
        "cell",
        "condition-hash",
        "target",
        "target-model",
        "profile",
        "cap",
        "receipt-root",
    ],
)
def test_actual_tuple_is_derived_not_echoed(tmp_path: Path, changed: str) -> None:
    project = make_admission_project(tmp_path)
    admission = project.issue()
    runner = PythonPassRunner()
    cell, contract, receipts = project.cell, project.contract, project.receipts
    if changed == "cell":
        cell = replace(cell, repetition=cell.repetition + 1)
    elif changed == "condition-hash":
        cell = replace(cell, condition_hash="0" * 64)
    elif changed == "target":
        target = replace(contract.targets[0], thinking="low")
        contract = replace(contract, targets=(target, *contract.targets[1:]))
    elif changed == "target-model":
        target = replace(contract.targets[0], model="other-provider/other-model")
        contract = replace(contract, targets=(target, *contract.targets[1:]))
    elif changed == "profile":
        contract = replace(contract, profile="other-profile")
    elif changed == "cap":
        contract = replace(contract, max_time_seconds=599)
    else:
        receipts = tmp_path / "other-receipts"
        receipts.mkdir()
    with pytest.raises(PreflightAdmissionError):
        dispatch_cell(contract, cell, receipts, runner, admission=admission)
    assert runner.children == []


@pytest.mark.parametrize(
    "cap", ["calls", "workers", "concurrency", "tokens", "currency", "wallSeconds"]
)
def test_unsupported_required_cap_never_admits(tmp_path: Path, cap: str) -> None:
    project = make_admission_project(tmp_path)
    value = _object_file(project.declaration)
    limits = cast(dict[str, object], value["limits"])
    limits[cap] = {
        "value": 1,
        "required": True,
        **({"unit": "USD"} if cap == "currency" else {}),
    }
    _json_file(project.declaration, value)
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError):
        admission = project.issue()
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


@pytest.mark.parametrize(
    "missing", ["identity", "source", "selection", "data", "receipts"]
)
def test_missing_bound_input_never_admits(tmp_path: Path, missing: str) -> None:
    project = make_admission_project(tmp_path)
    path = cast(Path, getattr(project, missing))
    if path.is_dir():
        path.rmdir()
    else:
        path.unlink()
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError):
        admission = project.issue()
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


@pytest.mark.parametrize(
    "missing", ["auth-field", "authorization", "scope", "unknown-ack", "synthetic-kind"]
)
def test_missing_or_unauthorized_authority_never_reaches_child(
    tmp_path: Path, missing: str
) -> None:
    project = make_admission_project(tmp_path)
    value = _object_file(project.declaration)
    if missing in ("auth-field", "synthetic-kind"):
        identity = _object_file(project.identity)
        if missing == "auth-field":
            del identity["auth"]
        else:
            identity["kind"] = "managed"
            identity["auth"] = "attested"
        _json_file(project.identity, identity)
        cast(dict[str, object], value["inputs"])["identity"] = _binding(
            project.identity
        )
    elif missing == "authorization":
        value["authorizations"] = []
    else:
        authorization = cast(list[dict[str, object]], value["authorizations"])[0]
        if missing == "scope":
            authorization["scope"] = "managed-invocation"
        else:
            authorization["acknowledgeUnknownQuota"] = False
    _json_file(project.declaration, value)
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError):
        admission = project.issue()
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


@pytest.mark.parametrize("field", ["expiresAt", "quota", "authorizations", "identity"])
def test_expired_prerequisites_never_admit(tmp_path: Path, field: str) -> None:
    project = make_admission_project(tmp_path)
    value = _object_file(project.declaration)
    expired = _utc(datetime.now(UTC) - timedelta(seconds=1))
    if field == "expiresAt":
        value[field] = expired
    elif field == "quota":
        cast(dict[str, object], value[field])["expiresAt"] = expired
    elif field == "authorizations":
        cast(list[dict[str, object]], value[field])[0]["expiresAt"] = expired
    else:
        identity = _object_file(project.identity)
        identity["expiresAt"] = expired
        _json_file(project.identity, identity)
        cast(dict[str, object], value["inputs"])["identity"] = _binding(
            project.identity
        )
    _json_file(project.declaration, value)
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError):
        admission = project.issue()
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


def test_source_change_during_prepare_is_seen_at_runner_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import omp_skillsbench_dispatch as dispatcher

    project = make_admission_project(tmp_path)
    admission = project.issue()
    original = dispatcher.prepare_cell

    def prepare(
        contract: OmpRunContract, cell: OmpCell, workspace: Path
    ) -> dispatcher.PreparedCell:
        prepared = original(contract, cell, workspace)
        project.source.write_text("changed during prepare", encoding="utf-8")
        return prepared

    monkeypatch.setattr(dispatcher, "prepare_cell", prepare)
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError):
        dispatcher.dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


def test_forged_ready_boolean_is_not_an_admission(tmp_path: Path) -> None:
    project = make_admission_project(tmp_path)
    admission = replace(
        project.issue(), record_json='{"status":"ready","admitted":true}'
    )
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError):
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


def test_forged_wrapper_purpose_cannot_change_synthetic_scope(tmp_path: Path) -> None:
    project = make_admission_project(tmp_path)
    admission = replace(project.issue(), purpose="managed")
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError, match="scope changed"):
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


def test_synthetic_admission_cannot_use_default_omp_runner(tmp_path: Path) -> None:
    project = make_admission_project(tmp_path)
    with pytest.raises(PreflightAdmissionError, match="explicit local runner"):
        dispatch_cell(
            project.contract, project.cell, project.receipts, admission=project.issue()
        )


def test_explicit_bridge_reports_honest_unavailable_receipt(tmp_path: Path) -> None:
    project = make_admission_project(tmp_path)
    result = synthetic_sentinel(project.config, project.declaration)
    assert result == {
        "schemaVersion": 1,
        "coreVersion": "1.0.0",
        "status": "terminal-receipt-unavailable",
        "managedSpawns": 1,
        "providerCalls": 0,
        "reasons": ["terminal-receipt-unavailable"],
    }
    assert list(project.receipts.rglob("*.json")) == []


def test_stale_bridge_refuses_without_child(tmp_path: Path) -> None:
    project = make_admission_project(tmp_path)
    project.source.write_text("stale", encoding="utf-8")
    result = synthetic_sentinel(project.config, project.declaration)
    assert result["status"] == "blocked"
    assert result["managedSpawns"] == 0


def test_configured_helper_probe_uses_the_actual_project_bridge(tmp_path: Path) -> None:
    project = make_admission_project(tmp_path)
    config = load_project_config(project.config)
    bun = shutil.which("bun")
    assert bun is not None
    completed = subprocess.run(
        [
            bun,
            str(config.helper_path),
            "probe",
            "--config",
            str(project.config),
            "--declaration",
            str(project.declaration),
        ],
        cwd=config.project_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    report = cast(dict[str, object], json.loads(completed.stdout))
    assert report["status"] == "unknown"
    assert report["admitted"] is False
    probe = cast(dict[str, object], report["probe"])
    assert probe["status"] == "terminal-receipt-unavailable"
    assert probe["managedSpawns"] == 1
    assert probe["providerCalls"] == 0
    assert list(project.receipts.rglob("*.json")) == []


def test_normal_check_never_launches_the_configured_bridge(tmp_path: Path) -> None:
    project = make_admission_project(tmp_path)
    marker = tmp_path / "bridge-launched"
    bridge = tmp_path / "reject_if_launched.py"
    bridge.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('launched')\nraise SystemExit(72)\n",
        encoding="utf-8",
    )
    config = _object_file(project.config)
    config["bridgeArgv"] = [sys.executable, str(bridge)]
    _json_file(project.config, config)
    value = _object_file(project.declaration)
    value["configSha256"] = _binding(project.config)["sha256"]
    inputs = cast(dict[str, object], value["inputs"])
    cast(list[object], inputs["source"]).append(_binding(bridge))
    inputs["config"] = [
        _binding(Path(binding["path"]))
        for binding in cast(list[dict[str, str]], inputs["config"])
    ]
    _json_file(project.declaration, value)
    assert project.issue().status == "unknown"
    assert not marker.exists()


@pytest.mark.parametrize("change", ["version", "helper-path", "config-digest"])
def test_bootstrap_rejects_incompatible_configuration(
    tmp_path: Path, change: str
) -> None:
    project = make_admission_project(tmp_path)
    config = _object_file(project.config)
    if change == "version":
        config["coreVersion"] = "2.0.0"
    elif change == "helper-path":
        config["helperPath"] = "../outside/cli.ts"
    else:
        config["bridgeArgv"] = [sys.executable, "changed-bridge.py"]
    _json_file(project.config, config)
    with pytest.raises(PreflightAdmissionError):
        project.issue()


@pytest.mark.parametrize("category", ["source", "data"])
def test_actual_consumed_inputs_cannot_be_omitted(
    tmp_path: Path, category: str
) -> None:
    project = make_admission_project(tmp_path)
    task = next(
        task
        for task in project.contract.corpus.tasks
        if task.id == project.cell.task_id
    )
    omitted = (
        project.contract.treatments[0].source
        if category == "source"
        else Path(task.source_path)
    ).resolve()
    value = _object_file(project.declaration)
    inputs = cast(dict[str, object], value["inputs"])
    inputs[category] = [
        binding
        for binding in cast(list[dict[str, str]], inputs[category])
        if binding["path"] != str(omitted)
    ]
    _json_file(project.declaration, value)
    admission = project.issue()
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError):
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


def test_mutated_in_memory_prompt_never_reaches_child(tmp_path: Path) -> None:
    project = make_admission_project(tmp_path)
    admission = project.issue()
    task = next(
        task
        for task in project.contract.corpus.tasks
        if task.id == project.cell.task_id
    )
    task.prompt = "A different prompt not authorized by the bound corpus"
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError):
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


@pytest.mark.parametrize(
    ("category", "relative"),
    [
        ("source", "scripts/omp_preflight_cli.py"),
        ("source", "scripts/omp_skillsbench_dispatch.py"),
        ("source", "scripts/run_skillsbench.py"),
        ("config", "model_fit.yaml"),
        ("config", "evals/skillsbench/package_strata.yaml"),
        ("data", "evals/skillsbench/corpus.yaml"),
    ],
)
def test_adapter_owned_inputs_cannot_be_omitted(
    tmp_path: Path, category: str, relative: str
) -> None:
    project = make_admission_project(tmp_path)
    value = _object_file(project.declaration)
    inputs = cast(dict[str, object], value["inputs"])
    omitted = str((_REPO_ROOT / relative).resolve())
    inputs[category] = [
        binding
        for binding in cast(list[dict[str, str]], inputs[category])
        if binding["path"] != omitted
    ]
    _json_file(project.declaration, value)
    runner = PythonPassRunner()
    with pytest.raises(PreflightAdmissionError):
        admission = project.issue()
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=admission,
        )
    assert runner.children == []


def test_inline_task_inventory_binds_corpus_once_without_fragment(
    tmp_path: Path,
) -> None:
    project = make_admission_project(tmp_path, cell_index=90)
    task = next(
        task
        for task in project.contract.corpus.tasks
        if task.id == project.cell.task_id
    )
    assert "#tasks[" in task.source_path
    required = required_dispatch_inputs(
        load_project_config(project.config), project.contract, project.cell
    )
    assert required["data"] == (_REPO_ROOT / "evals" / "skillsbench" / "corpus.yaml",)
    runner = PythonPassRunner()
    with pytest.raises(CellDispatchError, match="terminal receipt failed"):
        dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            runner,
            admission=project.issue(),
        )
    assert len(runner.children) == 1


def test_dispatch_uses_private_canonical_prompt_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import omp_skillsbench_dispatch as dispatcher

    project = make_admission_project(tmp_path)
    admission = project.issue()
    task = next(
        task
        for task in project.contract.corpus.tasks
        if task.id == project.cell.task_id
    )
    expected_prompt = task.prompt
    original = dispatcher.prepare_cell

    def prepare(
        contract: OmpRunContract, cell: OmpCell, workspace: Path
    ) -> dispatcher.PreparedCell:
        assert contract is not project.contract
        task.prompt = "caller mutation during preparation must not change this command"
        return original(contract, cell, workspace)

    monkeypatch.setattr(dispatcher, "prepare_cell", prepare)
    runner = PythonPassRunner()

    def capture(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command[-1] == expected_prompt
        return runner(command, **kwargs)

    with pytest.raises(CellDispatchError, match="terminal receipt failed"):
        dispatcher.dispatch_cell(
            project.contract,
            project.cell,
            project.receipts,
            capture,
            admission=admission,
        )
    assert len(runner.children) == 1


@pytest.mark.parametrize(
    "bridge_argv",
    [
        [sys.executable],
        [sys.executable, "-c", "pass"],
        [sys.executable, "-m", "scripts.omp_preflight_cli"],
        [sys.executable, "scripts/omp_preflight_cli.py"],
        ["python", str(_REPO_ROOT / "scripts" / "omp_preflight_cli.py")],
    ],
)
def test_bootstrap_requires_literal_absolute_bridge_entry(
    tmp_path: Path, bridge_argv: list[str]
) -> None:
    project = make_admission_project(tmp_path)
    config = _object_file(project.config)
    config["bridgeArgv"] = bridge_argv
    _json_file(project.config, config)
    with pytest.raises(PreflightAdmissionError):
        load_project_config(project.config)
