#!/usr/bin/env python3
"""Validate the no-cost OMP contract for the frozen SkillsBench run."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, cast

_REPO_ROOT: Final = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import re

import yaml  # type: ignore[import-untyped]

from scripts.run_skillsbench import CorpusManifest, load_corpus_manifest
from scripts.validate_skillsbench import validate_strata

_DEFAULT_CONTRACT_PATH: Final = _REPO_ROOT / "evals" / "skillsbench" / "omp_run.yaml"
_REQUIRED_CONDITIONS: Final = (
    "current",
    "reduced-or-rewritten",
    "strengthened-contract",
)

_EXPECTED_TASK_COUNT: Final = 50
_EXPECTED_TARGET_COUNT: Final = 2
_EXPECTED_REPETITIONS: Final = 3
_EXPECTED_CELL_COUNT: Final = 900
_USAGE_TIMEOUT_SECONDS: Final = 30


class OmpRunConfigError(ValueError):
    """Raised when an OMP benchmark contract is not reproducible."""


@dataclass(frozen=True)
class OmpTarget:
    """A subscription-authenticated model target."""

    id: str
    model: str
    subscription_label: str
    thinking: str


@dataclass(frozen=True)
class TreatmentVariant:
    """One reviewed source and its declared treatment transformations."""

    package: str
    source: Path
    source_sha256: str
    reduced_sections: tuple[str, ...]
    strengthened_append: str


@dataclass(frozen=True)
class OmpCell:
    """One immutable task × condition × target × repetition unit."""

    task_id: str
    condition: str
    target_id: str
    repetition: int
    condition_hash: str


@dataclass(frozen=True)
class OmpRunContract:
    """Validated no-cost specification for the OMP comparative pilot."""

    targets: tuple[OmpTarget, ...]
    treatments: tuple[TreatmentVariant, ...]
    attempts_per_cell: int
    max_time_seconds: int
    corpus: CorpusManifest


@dataclass(frozen=True)
class PreflightReport:
    """Machine-readable no-cost verification output."""

    targets: tuple[str, ...]
    task_count: int
    cell_count: int
    attempts_per_cell: int
    max_time_seconds: int
    condition_hashes: dict[str, str]
    subscription_labels: tuple[str, ...]
    model_request_made: bool


def _mapping(value: object, location: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OmpRunConfigError(f"{location}: expected a mapping")
    return cast(dict[str, object], value)


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise OmpRunConfigError(f"{location}: expected a non-empty string")
    return value


def _positive_int(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OmpRunConfigError(f"{location}: expected a positive integer")
    return value


def _strings(value: object, location: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise OmpRunConfigError(f"{location}: expected a non-empty list of strings")
    values = tuple(
        _string(item, f"{location}[{index}]") for index, item in enumerate(value)
    )
    if len(values) != len(set(values)):
        raise OmpRunConfigError(f"{location}: must not contain duplicates")
    return values


def _load_yaml(path: Path) -> dict[str, object]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OmpRunConfigError(f"cannot read contract {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise OmpRunConfigError(f"cannot parse contract {path}: {exc}") from exc
    return _mapping(raw, str(path))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_target(raw: object, index: int) -> OmpTarget:
    location = f"targets[{index}]"
    target = _mapping(raw, location)
    model = _string(target.get("model"), f"{location}.model")
    if "/" not in model:
        raise OmpRunConfigError(
            f"{location}.model: use an explicit provider/model selector"
        )
    return OmpTarget(
        id=_string(target.get("id"), f"{location}.id"),
        model=model,
        subscription_label=_string(
            target.get("subscription_label"), f"{location}.subscription_label"
        ),
        thinking=_string(target.get("thinking"), f"{location}.thinking"),
    )


def _load_treatment(raw: object, index: int) -> TreatmentVariant:
    location = f"treatments[{index}]"
    treatment = _mapping(raw, location)
    source_value = Path(_string(treatment.get("source"), f"{location}.source"))
    if source_value.is_absolute() or ".." in source_value.parts:
        raise OmpRunConfigError(
            f"{location}.source: expected a safe repository-relative path"
        )
    source = (_REPO_ROOT / source_value).resolve()
    if not source.is_relative_to(_REPO_ROOT) or not source.is_file():
        raise OmpRunConfigError(f"{location}.source: source file is unavailable")
    source_sha256 = _string(treatment.get("source_sha256"), f"{location}.source_sha256")
    if _sha256(source) != source_sha256:
        raise OmpRunConfigError(f"{location}.source_sha256: source revision changed")
    sections = _strings(
        treatment.get("reduced_sections"), f"{location}.reduced_sections"
    )
    source_text = source.read_text(encoding="utf-8")
    for section in sections:
        if re.search(rf"^## {re.escape(section)}$", source_text, re.MULTILINE) is None:
            raise OmpRunConfigError(
                f"{location}.reduced_sections: missing level-two heading {section!r}"
            )
    return TreatmentVariant(
        package=_string(treatment.get("package"), f"{location}.package"),
        source=source,
        source_sha256=source_sha256,
        reduced_sections=sections,
        strengthened_append=_string(
            treatment.get("strengthened_append"), f"{location}.strengthened_append"
        ),
    )


def load_omp_run_contract(path: Path = _DEFAULT_CONTRACT_PATH) -> OmpRunContract:
    """Load and validate the fixed OMP target and treatment declaration."""
    contract = _load_yaml(path)
    if contract.get("schema_version") != 1:
        raise OmpRunConfigError("schema_version must be 1")
    execution = _mapping(contract.get("execution"), "execution")
    if execution.get("runner") != "omp" or execution.get("mode") != "json":
        raise OmpRunConfigError("execution must use omp JSON mode")
    if execution.get("subscription_only") is not True:
        raise OmpRunConfigError("execution.subscription_only must be true")
    if execution.get("session_persistence") is not False:
        raise OmpRunConfigError("execution.session_persistence must be false")
    if execution.get("derived_receipts_only") is not True:
        raise OmpRunConfigError("execution.derived_receipts_only must be true")
    attempts = _positive_int(
        execution.get("attempts_per_cell"), "execution.attempts_per_cell"
    )
    if attempts != 1:
        raise OmpRunConfigError("execution.attempts_per_cell must be exactly 1")
    targets_raw = contract.get("targets")
    if not isinstance(targets_raw, list) or len(targets_raw) != _EXPECTED_TARGET_COUNT:
        raise OmpRunConfigError(
            f"targets must declare exactly {_EXPECTED_TARGET_COUNT} OMP targets"
        )
    targets = tuple(_load_target(raw, index) for index, raw in enumerate(targets_raw))
    target_ids = tuple(target.id for target in targets)
    if len(target_ids) != len(set(target_ids)):
        raise OmpRunConfigError("targets must not contain duplicate ids")
    target_models = {target.model for target in targets}
    if target_models != {"anthropic/claude-opus-5", "openai-codex/gpt-5.6-terra"}:
        raise OmpRunConfigError(
            "targets must declare the approved Claude and Codex models"
        )

    treatments_raw = contract.get("treatments")
    if not isinstance(treatments_raw, list) or len(treatments_raw) != 7:
        raise OmpRunConfigError("treatments must declare all seven package samples")
    treatments = tuple(
        _load_treatment(raw, index) for index, raw in enumerate(treatments_raw)
    )
    packages = tuple(treatment.package for treatment in treatments)
    if len(packages) != len(set(packages)):
        raise OmpRunConfigError("treatments must not contain duplicate packages")
    try:
        validate_strata()
        corpus = load_corpus_manifest()
    except ValueError as exc:
        raise OmpRunConfigError(f"frozen input validation failed: {exc}") from exc
    if len(corpus.tasks) != _EXPECTED_TASK_COUNT:
        raise OmpRunConfigError(
            f"corpus must contain exactly {_EXPECTED_TASK_COUNT} tasks"
        )
    if corpus.repetitions != _EXPECTED_REPETITIONS:
        raise OmpRunConfigError(
            f"corpus must declare exactly {_EXPECTED_REPETITIONS} repetitions"
        )
    if (corpus.baseline, *corpus.treatments) != _REQUIRED_CONDITIONS:
        raise OmpRunConfigError("corpus conditions do not match the approved matrix")
    return OmpRunContract(
        targets=targets,
        treatments=treatments,
        attempts_per_cell=attempts,
        max_time_seconds=_positive_int(
            execution.get("max_time_seconds"), "execution.max_time_seconds"
        ),
        corpus=corpus,
    )


def condition_hashes(contract: OmpRunContract) -> dict[str, str]:
    """Produce stable hashes for the three concrete treatment specifications."""
    payloads = {
        "current": [
            {"package": treatment.package, "source": treatment.source_sha256}
            for treatment in contract.treatments
        ],
        "reduced-or-rewritten": [
            {
                "package": treatment.package,
                "source": treatment.source_sha256,
                "sections": treatment.reduced_sections,
            }
            for treatment in contract.treatments
        ],
        "strengthened-contract": [
            {
                "package": treatment.package,
                "source": treatment.source_sha256,
                "append": treatment.strengthened_append,
            }
            for treatment in contract.treatments
        ],
    }
    return {
        condition: hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for condition, payload in payloads.items()
    }


def declared_omp_cells(contract: OmpRunContract) -> tuple[OmpCell, ...]:
    """Expand the immutable M3 corpus into its two-target OMP matrix."""
    hashes = condition_hashes(contract)
    return tuple(
        OmpCell(
            task_id=task.id,
            condition=condition,
            target_id=target.id,
            repetition=repetition,
            condition_hash=hashes[condition],
        )
        for task in contract.corpus.tasks
        for condition in (contract.corpus.baseline, *contract.corpus.treatments)
        for target in contract.targets
        for repetition in range(1, contract.corpus.repetitions + 1)
    )


def validate_subscription_usage(contract: OmpRunContract, usage_output: str) -> None:
    """Require OMP's no-cost usage report to show every approved subscription."""
    missing = [
        target.subscription_label
        for target in contract.targets
        if re.search(
            rf"^{re.escape(target.subscription_label)}\s*[—:-].*\b\d+\s+accounts?\b",
            usage_output,
            re.IGNORECASE | re.MULTILINE,
        )
        is None
    ]
    if missing:
        raise OmpRunConfigError(
            f"OMP subscription usage is missing approved target(s): {', '.join(missing)}"
        )


def preflight(contract: OmpRunContract, usage_output: str) -> PreflightReport:
    """Validate matrix, source revisions, and subscriptions without a model call."""
    validate_subscription_usage(contract, usage_output)
    cells = declared_omp_cells(contract)
    if len(cells) != len(set(cells)):
        raise OmpRunConfigError("OMP matrix contains duplicate cells")
    if len(cells) != _EXPECTED_CELL_COUNT:
        raise OmpRunConfigError(
            f"OMP matrix must contain exactly {_EXPECTED_CELL_COUNT} cells"
        )
    return PreflightReport(
        targets=tuple(target.model for target in contract.targets),
        task_count=len(contract.corpus.tasks),
        cell_count=len(cells),
        attempts_per_cell=contract.attempts_per_cell,
        max_time_seconds=contract.max_time_seconds,
        condition_hashes=condition_hashes(contract),
        subscription_labels=tuple(
            target.subscription_label for target in contract.targets
        ),
        model_request_made=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=_DEFAULT_CONTRACT_PATH)
    parser.add_argument(
        "--preflight", action="store_true", help="Run no-cost contract validation"
    )
    args = parser.parse_args(argv)
    if not args.preflight:
        parser.error(
            "--preflight is required; live OMP execution is not available in this command"
        )
    try:
        contract = load_omp_run_contract(args.contract)
        try:
            usage = subprocess.run(
                ["omp", "usage"],
                capture_output=True,
                check=False,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=_USAGE_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise OmpRunConfigError("'omp' CLI not found in PATH") from exc
        except OSError as exc:
            raise OmpRunConfigError(f"cannot execute omp usage: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise OmpRunConfigError(
                f"omp usage timed out after {_USAGE_TIMEOUT_SECONDS}s"
            ) from exc
        if usage.returncode != 0:
            detail = usage.stderr.strip() or f"exit status {usage.returncode}"
            raise OmpRunConfigError(f"omp usage failed: {detail}")
        report = preflight(contract, usage.stdout)
    except ValueError as exc:
        print(f"OMP SkillsBench preflight failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
