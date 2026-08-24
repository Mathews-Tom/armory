"""Tests for the no-cost OMP SkillsBench dispatcher prerequisite."""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.omp_skillsbench import declared_omp_cells, load_omp_run_contract
from scripts.omp_skillsbench_dispatch import (
    GlobalDispatchError,
    build_omp_command,
    dispatch_cell,
    dispatcher_preflight,
    prepare_cell,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_PATH = _REPO_ROOT / "evals" / "skillsbench" / "omp_run.yaml"


def _terminal_events() -> str:
    return json.dumps(
        {
            "type": "turn_end",
            "message": {
                "provider": "anthropic",
                "api": "anthropic-messages",
                "model": "claude-opus-5",
                "usage": {
                    "input": 10,
                    "output": 5,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "totalTokens": 15,
                },
                "duration": 2.5,
                "stopReason": "stop",
            },
            "toolResults": [],
        }
    )


def test_prepared_cell_has_explicit_condition_bundle(tmp_path: Path) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    cell = declared_omp_cells(contract)[0]
    prepared = prepare_cell(contract, cell, tmp_path / "cell")
    command = build_omp_command(contract, prepared)

    assert prepared.condition_bundle.is_file()
    assert "Frozen M4 Condition Bundle" in prepared.condition_bundle.read_text(
        encoding="utf-8"
    )
    assert "--mode" in command and command[command.index("--mode") + 1] == "json"
    assert "--no-session" in command
    assert (
        "--model" in command
        and command[command.index("--model") + 1] == "anthropic/claude-opus-5"
    )
    assert "--api-key" not in command


def test_dispatcher_preflight_builds_all_cells_without_model_request() -> None:
    report = dispatcher_preflight(load_omp_run_contract(_CONTRACT_PATH))

    assert report.cell_count == 900
    assert report.target_count == 2
    assert report.model_request_made is False


def test_dispatch_persists_one_derived_receipt(tmp_path: Path) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    cell = declared_omp_cells(contract)[0]
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        calls.append(command)
        assert kwargs["stdin"] is not None
        return CompletedProcess(command, 0, stdout=_terminal_events(), stderr="")

    receipt = dispatch_cell(contract, cell, tmp_path / "receipts", runner)

    assert receipt.task_id == cell.task_id
    assert len(calls) == 1
    assert "--append-system-prompt" in calls[0]
    assert list((tmp_path / "receipts").rglob("*.json"))


def test_dispatch_treats_auth_failures_as_global(tmp_path: Path) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    cell = declared_omp_cells(contract)[0]

    def runner(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(command, 1, stdout="", stderr="No API key found")

    with pytest.raises(GlobalDispatchError, match="authentication or quota"):
        dispatch_cell(contract, cell, tmp_path / "receipts", runner)
