#!/usr/bin/env python3
"""Prepare and supervise one declared OMP SkillsBench cell.

The command-line interface is intentionally preflight-only. `dispatch_cell` is
an injectable library boundary for the separately authorized live run; it never
persists prompts, assistant text, or raw OMP events.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Final

_REPO_ROOT: Final = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.omp_skillsbench import (
    OmpCell,
    OmpRunContract,
    OmpTarget,
    declared_omp_cells,
    load_omp_run_contract,
)
from scripts.omp_skillsbench_results import (
    DerivedReceipt,
    MaterializedCondition,
    OmpResultError,
    derive_receipt,
    materialize_condition,
    write_derived_receipt,
)

_EXPECTED_CELL_COUNT: Final = 900
_TOOL_SURFACE: Final = "Read,Write,Edit,Bash,Glob,Grep"


class OmpDispatchError(ValueError):
    """Base class for failures while preparing or dispatching a cell."""


class GlobalDispatchError(OmpDispatchError):
    """A provider/auth/quota failure that invalidates every remaining cell."""


class CellDispatchError(OmpDispatchError):
    """A single-cell failure that must be persisted by a future run ledger."""


@dataclass(frozen=True)
class PreparedCell:
    """Ephemeral isolated workspace and deterministic condition input."""

    cell: OmpCell
    target: OmpTarget
    workspace: Path
    materialized: MaterializedCondition
    condition_bundle: Path


@dataclass(frozen=True)
class DispatcherPreflightReport:
    """No-cost proof that every target command is deterministic and isolated."""

    cell_count: int
    target_count: int
    tools: tuple[str, ...]
    model_request_made: bool


def _task_for_cell(contract: OmpRunContract, cell: OmpCell) -> str:
    for task in contract.corpus.tasks:
        if task.id == cell.task_id:
            return task.prompt
    raise OmpDispatchError(f"undeclared task: {cell.task_id}")


def _target_for_cell(contract: OmpRunContract, cell: OmpCell) -> OmpTarget:
    for target in contract.targets:
        if target.id == cell.target_id:
            return target
    raise OmpDispatchError(f"undeclared target: {cell.target_id}")


def _write_condition_bundle(
    workspace: Path, materialized: MaterializedCondition
) -> Path:
    root = workspace / "condition"
    entries: list[str] = [
        "# Frozen M4 Condition Bundle",
        f"Condition: {materialized.condition}",
        f"Content hash: {materialized.content_hash}",
        "Use these package definitions as the complete condition input for this task.",
    ]
    for relative in materialized.files:
        content = (root / relative).read_text(encoding="utf-8")
        entries.extend((f"\n## Source: {relative}\n", content.rstrip()))
    bundle = workspace / "CONDITION.md"
    bundle.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return bundle


def prepare_cell(
    contract: OmpRunContract, cell: OmpCell, workspace: Path
) -> PreparedCell:
    """Materialize one exact cell in a caller-owned isolated workspace."""
    target = _target_for_cell(contract, cell)
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    materialized = materialize_condition(
        contract, cell.condition, workspace / "condition"
    )
    return PreparedCell(
        cell=cell,
        target=target,
        workspace=workspace,
        materialized=materialized,
        condition_bundle=_write_condition_bundle(workspace, materialized),
    )


def build_omp_command(contract: OmpRunContract, prepared: PreparedCell) -> list[str]:
    """Build the exact headless command without executing it."""
    if prepared.cell.target_id != prepared.target.id:
        raise OmpDispatchError("prepared cell target does not match its target")
    prompt = _task_for_cell(contract, prepared.cell)
    return [
        "omp",
        "-p",
        "--mode",
        "json",
        "--no-session",
        "--no-title",
        "--no-extensions",
        "--no-skills",
        "--no-rules",
        "--tools",
        _TOOL_SURFACE,
        "--model",
        prepared.target.model,
        "--thinking",
        prepared.target.thinking,
        "--max-time",
        str(contract.max_time_seconds),
        "--cwd",
        str(prepared.workspace),
        "--append-system-prompt",
        str(prepared.condition_bundle),
        prompt,
    ]


def _classify_nonzero(stderr: str) -> OmpDispatchError:
    normalized = stderr.casefold()
    if any(
        token in normalized
        for token in (
            "no api key",
            "not logged",
            "auth",
            "quota",
            "rate limit",
            "credit",
        )
    ):
        return GlobalDispatchError("OMP provider authentication or quota failure")
    return CellDispatchError("OMP process failed for the declared cell")


def dispatch_cell(
    contract: OmpRunContract,
    cell: OmpCell,
    receipt_root: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DerivedReceipt:
    """Dispatch exactly one cell; intended only after a future execution gate."""
    with tempfile.TemporaryDirectory(prefix="omp_skillsbench_cell_") as directory:
        prepared = prepare_cell(contract, cell, Path(directory) / "workspace")
        command = build_omp_command(contract, prepared)
        try:
            completed = runner(
                command,
                capture_output=True,
                check=False,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=contract.max_time_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise CellDispatchError(
                "OMP cell exceeded its declared wall-time limit"
            ) from exc
        except OSError as exc:
            raise GlobalDispatchError(f"cannot launch OMP: {exc}") from exc
        if completed.returncode != 0:
            raise _classify_nonzero(completed.stderr)
        try:
            receipt = derive_receipt(
                prepared.cell,
                prepared.target,
                prepared.materialized,
                completed.stdout,
            )
        except OmpResultError as exc:
            raise GlobalDispatchError(
                f"OMP terminal receipt is invalid: {exc}"
            ) from exc
        write_derived_receipt(receipt_root, receipt)
        return receipt


def dispatcher_preflight(contract: OmpRunContract) -> DispatcherPreflightReport:
    """Validate all command shapes without launching any provider process."""
    cells = declared_omp_cells(contract)
    if len(cells) != _EXPECTED_CELL_COUNT or len(cells) != len(set(cells)):
        raise OmpDispatchError("dispatcher matrix is not the exact 900-cell set")
    with tempfile.TemporaryDirectory(prefix="omp_skillsbench_dispatch_") as directory:
        root = Path(directory)
        for index, cell in enumerate(cells):
            prepared = prepare_cell(contract, cell, root / str(index))
            command = build_omp_command(contract, prepared)
            if "--model" not in command or "--append-system-prompt" not in command:
                raise OmpDispatchError(
                    "dispatcher command omits required target or condition input"
                )
            if "--api-key" in command or "--profile" in command:
                raise OmpDispatchError(
                    "dispatcher command may not override subscription auth"
                )
    return DispatcherPreflightReport(
        cell_count=len(cells),
        target_count=len(contract.targets),
        tools=tuple(_TOOL_SURFACE.split(",")),
        model_request_made=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv)
    if not args.preflight:
        parser.error("--preflight is required; live OMP execution is unavailable")
    try:
        report = dispatcher_preflight(load_omp_run_contract())
    except OmpDispatchError as exc:
        print(f"OMP SkillsBench dispatcher preflight failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
