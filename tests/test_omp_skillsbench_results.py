"""Tests for immutable derived OMP SkillsBench result receipts."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from scripts import omp_skillsbench
from scripts.omp_skillsbench import declared_omp_cells, load_omp_run_contract
from scripts.omp_skillsbench_results import (
    OmpResultError,
    derive_receipt,
    execution_preflight,
    materialize_condition,
    parse_terminal_receipt,
    validate_receipts,
    write_derived_receipt,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_PATH = _REPO_ROOT / "evals" / "skillsbench" / "omp_run.yaml"


def _events(target_provider: str, api: str, model: str, *, output: int = 5) -> str:
    return json.dumps(
        {
            "type": "turn_end",
            "message": {
                "provider": target_provider,
                "api": api,
                "model": model,
                "usage": {
                    "input": 10,
                    "output": output,
                    "cacheRead": 1,
                    "cacheWrite": 2,
                    "totalTokens": 18 if output else 13,
                },
                "duration": 12.5,
                "stopReason": "stop",
            },
            "toolResults": [{"toolName": "Write"}],
        }
    )


def test_execution_preflight_materializes_three_distinct_conditions() -> None:
    report = execution_preflight(load_omp_run_contract(_CONTRACT_PATH))

    assert report.cell_count == 900
    assert report.model_request_made is False
    assert len(report.conditions) == 3
    assert len({condition.content_hash for condition in report.conditions}) == 3
    assert all(len(condition.files) == 7 for condition in report.conditions)


@pytest.mark.parametrize(
    "condition", ["current", "reduced-or-rewritten", "strengthened-contract"]
)
def test_snapshot_preserves_historical_bundle_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    document = yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))
    historical_root = tmp_path / "historical"
    for treatment, entry in zip(
        contract.treatments, document["treatments"], strict=True
    ):
        original = historical_root / entry["source"]
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(treatment.source.read_bytes())
        entry.pop("snapshot", None)
    historical_path = tmp_path / "historical.yaml"
    historical_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    monkeypatch.setattr(omp_skillsbench, "_REPO_ROOT", historical_root)
    historical = load_omp_run_contract(historical_path)

    previous = materialize_condition(historical, condition, tmp_path / "previous")
    current = materialize_condition(contract, condition, tmp_path / "current")

    assert current.content_hash == previous.content_hash
    assert current.files == previous.files
    assert "skills/pr-review/SKILL.md" in current.files
    assert omp_skillsbench.condition_hashes(
        contract
    ) == omp_skillsbench.condition_hashes(historical)


def test_derives_terminal_receipt_without_model_content(tmp_path: Path) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    target = contract.targets[0]
    cell = declared_omp_cells(contract)[0]
    materialized = materialize_condition(
        contract, cell.condition, tmp_path / cell.condition
    )

    receipt = derive_receipt(
        cell,
        target,
        materialized,
        _events("anthropic", "anthropic-messages", "claude-opus-5"),
    )

    assert receipt.provider == "anthropic"
    assert receipt.tool_names == ("Write",)
    assert not hasattr(receipt, "content")


def test_rejects_nonterminal_or_zero_usage_receipt() -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    target = contract.targets[1]

    with pytest.raises(OmpResultError, match="non-zero actual usage"):
        parse_terminal_receipt(
            _events(
                "openai-codex", "openai-codex-responses", "gpt-5.6-terra", output=0
            ),
            target,
        )

    with pytest.raises(OmpResultError, match="no terminal turn_end"):
        parse_terminal_receipt('{"type":"agent_end"}', target)


def test_rejects_fallback_provider_identity(tmp_path: Path) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    target = contract.targets[1]
    cell = next(
        item for item in declared_omp_cells(contract) if item.target_id == target.id
    )
    materialized = materialize_condition(
        contract, cell.condition, tmp_path / cell.condition
    )

    with pytest.raises(OmpResultError, match="provider/model differs"):
        derive_receipt(
            cell,
            target,
            materialized,
            _events("openai", "openai-responses", "gpt-5.6-terra"),
        )


def test_receipt_validator_rejects_incomplete_matrix(tmp_path: Path) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    target = contract.targets[0]
    cell = declared_omp_cells(contract)[0]
    materialized = materialize_condition(
        contract, cell.condition, tmp_path / cell.condition
    )
    receipt = derive_receipt(
        cell,
        target,
        materialized,
        _events("anthropic", "anthropic-messages", "claude-opus-5"),
    )

    with pytest.raises(OmpResultError, match="missing cells"):
        validate_receipts(contract, (receipt,))


def test_receipt_write_is_immutable_and_content_free(tmp_path: Path) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    target = contract.targets[0]
    cell = declared_omp_cells(contract)[0]
    materialized = materialize_condition(contract, cell.condition, tmp_path / "inputs")
    receipt = derive_receipt(
        cell,
        target,
        materialized,
        _events("anthropic", "anthropic-messages", "claude-opus-5"),
    )

    path = write_derived_receipt(tmp_path / "receipts", receipt)

    assert path.is_file()
    assert "OK" not in path.read_text(encoding="utf-8")
    with pytest.raises(OmpResultError, match="already exists"):
        write_derived_receipt(tmp_path / "receipts", receipt)


def test_receipt_validator_rejects_materialized_hash_drift(tmp_path: Path) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    targets = {target.id: target for target in contract.targets}
    materials = {
        condition: materialize_condition(contract, condition, tmp_path / condition)
        for condition in (contract.corpus.baseline, *contract.corpus.treatments)
    }
    receipts = tuple(
        derive_receipt(
            cell,
            targets[cell.target_id],
            materials[cell.condition],
            _events(
                "anthropic"
                if cell.target_id.startswith("omp-anthropic")
                else "openai-codex",
                "anthropic-messages"
                if cell.target_id.startswith("omp-anthropic")
                else "openai-codex-responses",
                "claude-opus-5"
                if cell.target_id.startswith("omp-anthropic")
                else "gpt-5.6-terra",
            ),
        )
        for cell in declared_omp_cells(contract)
    )
    drifted = (*receipts[:-1], replace(receipts[-1], materialized_hash="0" * 64))

    with pytest.raises(OmpResultError, match="materialized hash drift"):
        validate_receipts(contract, drifted)
