"""Tests for the no-cost OMP SkillsBench preflight contract."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest

import scripts.omp_skillsbench as omp_skillsbench
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
        "openai/gpt-5-codex",
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


def test_main_prints_no_cost_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    call_kwargs: dict[str, object] = {}

    def usage_succeeds(*args: object, **kwargs: object) -> CompletedProcess[str]:
        call_kwargs.update(kwargs)
        return CompletedProcess(args=args[0], returncode=0, stdout=_USAGE, stderr="")

    monkeypatch.setattr(omp_skillsbench.subprocess, "run", usage_succeeds)

    assert omp_skillsbench.main(["--preflight"]) == 0
    assert '"model_request_made": false' in capsys.readouterr().out
    assert call_kwargs["timeout"] == 30
    assert call_kwargs["stdin"] is omp_skillsbench.subprocess.DEVNULL
    assert call_kwargs["capture_output"] is True


def test_main_fails_loudly_when_omp_usage_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        omp_skillsbench.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr="denied"
        ),
    )

    assert omp_skillsbench.main(["--preflight"]) == 2
    assert "omp usage failed: denied" in capsys.readouterr().err


def test_main_fails_loudly_when_omp_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing_omp(*args: object, **kwargs: object) -> CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(omp_skillsbench.subprocess, "run", missing_omp)

    assert omp_skillsbench.main(["--preflight"]) == 2
    assert "'omp' CLI not found in PATH" in capsys.readouterr().err


def test_main_fails_loudly_when_usage_times_out(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def timeout_omp(*args: object, **kwargs: object) -> CompletedProcess[str]:
        raise TimeoutExpired(cmd=["omp", "usage"], timeout=30)

    monkeypatch.setattr(omp_skillsbench.subprocess, "run", timeout_omp)

    assert omp_skillsbench.main(["--preflight"]) == 2
    assert "omp usage timed out after 30s" in capsys.readouterr().err


def test_main_normalizes_frozen_input_validation_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def invalid_strata() -> tuple[int, int]:
        raise ValueError("inventory drift")

    monkeypatch.setattr(omp_skillsbench, "validate_strata", invalid_strata)

    assert omp_skillsbench.main(["--preflight"]) == 2
    assert "frozen input validation failed: inventory drift" in capsys.readouterr().err
