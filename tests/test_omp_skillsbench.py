"""Tests for the no-cost OMP SkillsBench preflight contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import omp_skillsbench
from scripts.omp_skillsbench import (
    OmpRunConfigError,
    declared_omp_cells,
    load_omp_run_contract,
    preflight,
    validate_subscription_usage,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_PATH = _REPO_ROOT / "evals" / "skillsbench" / "omp_run.yaml"
_USAGE = "Anthropic — 1 account\nOpenai Codex — 1 account\n"


def test_loads_fixed_two_target_contract() -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    cells = declared_omp_cells(contract)

    assert [target.model for target in contract.targets] == [
        "anthropic/claude-opus-5",
        "openai-codex/gpt-5.6-terra",
    ]
    assert len(contract.treatments) == 7
    assert len(cells) == 900
    assert len(cells) == len(set(cells))


def test_preflight_is_explicitly_no_cost() -> None:
    report = preflight(load_omp_run_contract(_CONTRACT_PATH), _USAGE)

    assert report.cell_count == 900
    assert report.attempts_per_cell == 1
    assert report.model_request_made is False
    assert set(report.condition_hashes) == {
        "current",
        "reduced-or-rewritten",
        "strengthened-contract",
    }


def test_rejects_missing_subscription() -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)

    with pytest.raises(OmpRunConfigError, match="Openai Codex"):
        validate_subscription_usage(contract, "Anthropic — 1 account\n")


def test_rejects_provider_mentions_without_subscription_account() -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)

    with pytest.raises(OmpRunConfigError, match="Anthropic"):
        validate_subscription_usage(
            contract,
            "Anthropic: not configured\nOpenai Codex: unavailable\n",
        )


def test_rejects_source_revision_drift(tmp_path: Path) -> None:
    contract = _CONTRACT_PATH.read_text(encoding="utf-8")
    path = tmp_path / "omp_run.yaml"
    path.write_text(
        contract.replace(
            "e27c6b70f4fb08456e4098f4a06007e598323e71c36c34fd0badbbe9826f3e71", "a" * 64
        ),
        encoding="utf-8",
    )

    with pytest.raises(OmpRunConfigError, match="source revision changed"):
        load_omp_run_contract(path)


def test_rejects_unpinned_corpus_cardinality(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = load_omp_run_contract(_CONTRACT_PATH)
    monkeypatch.setattr(
        omp_skillsbench,
        "load_corpus_manifest",
        lambda: replace(contract.corpus, repetitions=4),
    )

    with pytest.raises(OmpRunConfigError, match="exactly 3 repetitions"):
        load_omp_run_contract(_CONTRACT_PATH)


def test_main_normalizes_frozen_input_validation_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def invalid_strata() -> tuple[int, int]:
        raise ValueError("inventory drift")

    monkeypatch.setattr(omp_skillsbench, "validate_strata", invalid_strata)

    assert omp_skillsbench.main(["--preflight"]) == 2
    assert "frozen input validation failed: inventory drift" in capsys.readouterr().err


def test_preflight_cli_does_not_query_provider_accounts(tmp_path: Path) -> None:
    """Offline contract validation must not query authenticated provider accounts."""
    tools = tmp_path / "tools"
    tools.mkdir()
    marker = tmp_path / "provider-usage-attempted"
    executable = tools / "omp"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('provider usage was invoked')\n"
        "raise SystemExit(23)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    environment = dict(os.environ)
    environment["PATH"] = str(tools) + os.pathsep + environment["PATH"]
    result = subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts/omp_skillsbench.py"), "--preflight"],
        cwd=_REPO_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=60,
    )

    assert not marker.exists(), result.stderr
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["subscription_observation"] == "unknown"
    assert report["provider_request_made"] is False
    assert report["model_request_made"] is False
