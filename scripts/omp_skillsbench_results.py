#!/usr/bin/env python3
"""Build and validate immutable, derived OMP SkillsBench result receipts.

This module deliberately has no live-model execution path. It materializes the
approved treatment inputs in temporary isolated directories, validates the exact
900-cell contract, and parses OMP terminal JSON events into derived receipts
without retaining prompts, assistant content, or stream events.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, cast

_REPO_ROOT: Final = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.omp_skillsbench import (
    OmpCell,
    OmpRunConfigError,
    OmpRunContract,
    OmpTarget,
    TreatmentVariant,
    declared_omp_cells,
    load_omp_run_contract,
)

_SCHEMA_VERSION: Final = 1
_EXPECTED_CELL_COUNT: Final = 900
_EXPECTED_API_BY_PROVIDER: Final = {
    "anthropic": "anthropic-messages",
    "openai-codex": "openai-codex-responses",
}


class OmpResultError(ValueError):
    """Raised when a terminal OMP receipt is incomplete or incomparable."""


@dataclass(frozen=True)
class MaterializedCondition:
    """One isolated, deterministic treatment-input bundle."""

    condition: str
    content_hash: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class TerminalReceipt:
    """Terminal OMP fields safe to retain as benchmark evidence."""

    provider: str
    api: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    duration_ms: float
    stop_reason: str
    tool_names: tuple[str, ...]


@dataclass(frozen=True)
class DerivedReceipt:
    """One immutable, target-scoped result receipt without raw model content."""

    schema_version: int
    task_id: str
    condition: str
    target_id: str
    repetition: int
    condition_hash: str
    materialized_hash: str
    provider: str
    api: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    duration_ms: float
    stop_reason: str
    tool_names: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionPreflightReport:
    """No-cost evidence that result inputs are materializable and complete."""

    cell_count: int
    conditions: tuple[MaterializedCondition, ...]
    model_request_made: bool


def _mapping(value: object, location: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OmpResultError(f"{location}: expected a mapping")
    return cast(dict[str, object], value)


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise OmpResultError(f"{location}: expected a non-empty string")
    return value


def _nonnegative_int(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OmpResultError(f"{location}: expected a non-negative integer")
    return value


def _positive_float(value: object, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise OmpResultError(f"{location}: expected a positive number")
    return float(value)


def _safe_destination(root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise OmpResultError("treatment source must be a safe relative path")
    destination = (root / relative_path).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise OmpResultError("treatment destination escapes the isolated directory")
    return destination


def _reduced_content(treatment: TreatmentVariant) -> str:
    """Keep the reviewed level-two sections and the source preamble."""
    source = treatment.source.read_text(encoding="utf-8")
    headings = list(re.finditer(r"^## .+$", source, re.MULTILINE))
    if not headings:
        raise OmpResultError(f"{treatment.package}: source has no level-two headings")
    preamble = source[: headings[0].start()].rstrip()
    sections: list[str] = []
    for expected in treatment.reduced_sections:
        match = re.search(rf"^## {re.escape(expected)}$", source, re.MULTILINE)
        if match is None:
            raise OmpResultError(
                f"{treatment.package}: reviewed section {expected!r} is unavailable"
            )
        next_heading = re.search(r"^## .+$", source[match.end() :], re.MULTILINE)
        end = match.end() + next_heading.start() if next_heading else len(source)
        sections.append(source[match.start() : end].strip())
    return "\n\n".join((preamble, *sections)).rstrip() + "\n"


def _condition_content(treatment: TreatmentVariant, condition: str) -> str:
    source = treatment.source.read_text(encoding="utf-8")
    if condition == "current":
        return source
    if condition == "reduced-or-rewritten":
        return _reduced_content(treatment)
    if condition == "strengthened-contract":
        return (
            source.rstrip()
            + "\n\n## M4 Strengthened Contract\n\n"
            + treatment.strengthened_append
            + "\n"
        )
    raise OmpResultError(f"undeclared treatment condition: {condition}")


def _bundle_hash(root: Path) -> tuple[str, tuple[str, ...]]:
    digest = hashlib.sha256()
    files: list[str] = []
    for path in sorted(
        candidate for candidate in root.rglob("*") if candidate.is_file()
    ):
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
        files.append(relative)
    if not files:
        raise OmpResultError("materialized condition contains no files")
    return digest.hexdigest(), tuple(files)


def materialize_condition(
    contract: OmpRunContract, condition: str, destination: Path
) -> MaterializedCondition:
    """Materialize one reviewed condition in an isolated directory."""
    if condition not in (contract.corpus.baseline, *contract.corpus.treatments):
        raise OmpResultError(f"undeclared treatment condition: {condition}")
    destination.mkdir(parents=True, exist_ok=False)
    for treatment in contract.treatments:
        relative = treatment.source.relative_to(_REPO_ROOT)
        output = _safe_destination(destination, relative)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_condition_content(treatment, condition), encoding="utf-8")
    content_hash, files = _bundle_hash(destination)
    return MaterializedCondition(
        condition=condition,
        content_hash=content_hash,
        files=files,
    )


def execution_preflight(contract: OmpRunContract) -> ExecutionPreflightReport:
    """Materialize all reviewed inputs and verify the frozen result matrix."""
    cells = declared_omp_cells(contract)
    if len(cells) != _EXPECTED_CELL_COUNT or len(cells) != len(set(cells)):
        raise OmpResultError("execution matrix is not the exact 900-cell set")
    with tempfile.TemporaryDirectory(prefix="omp_skillsbench_preflight_") as directory:
        root = Path(directory)
        conditions = tuple(
            materialize_condition(contract, condition, root / condition)
            for condition in (contract.corpus.baseline, *contract.corpus.treatments)
        )
    if len({condition.content_hash for condition in conditions}) != len(conditions):
        raise OmpResultError("treatment materializations must have distinct hashes")
    return ExecutionPreflightReport(
        cell_count=len(cells),
        conditions=conditions,
        model_request_made=False,
    )


def _terminal_event(events: str) -> dict[str, object]:
    terminal: dict[str, object] | None = None
    for line_number, line in enumerate(events.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = _mapping(json.loads(line), f"event line {line_number}")
        except json.JSONDecodeError as exc:
            raise OmpResultError(f"event line {line_number}: malformed JSON") from exc
        if event.get("type") == "turn_end":
            if terminal is not None:
                raise OmpResultError(
                    "event stream contains multiple terminal turn_end events"
                )
            terminal = event
    if terminal is None:
        raise OmpResultError("event stream has no terminal turn_end event")
    return terminal


def parse_terminal_receipt(events: str, target: OmpTarget) -> TerminalReceipt:
    """Parse terminal evidence only; never retain model content or raw events."""
    event = _terminal_event(events)
    terminal = _mapping(event.get("message"), "turn_end.message")
    expected_provider, expected_model = target.model.split("/", maxsplit=1)
    provider = _string(terminal.get("provider"), "turn_end.message.provider")
    api = _string(terminal.get("api"), "turn_end.message.api")
    model = _string(terminal.get("model"), "turn_end.message.model")
    if provider != expected_provider or model != expected_model:
        raise OmpResultError(
            "terminal receipt provider/model differs from the declared target"
        )
    if api != _EXPECTED_API_BY_PROVIDER.get(provider):
        raise OmpResultError("terminal receipt uses an unapproved provider API")
    usage = _mapping(terminal.get("usage"), "turn_end.message.usage")
    input_tokens = _nonnegative_int(usage.get("input"), "usage.input")
    output_tokens = _nonnegative_int(usage.get("output"), "usage.output")
    total_tokens = _nonnegative_int(usage.get("totalTokens"), "usage.totalTokens")
    if input_tokens <= 0 or output_tokens <= 0 or total_tokens <= 0:
        raise OmpResultError("terminal receipt must contain non-zero actual usage")
    tool_results = event.get("toolResults", [])
    if not isinstance(tool_results, list):
        raise OmpResultError("turn_end.toolResults must be a list")
    tool_names = tuple(
        _string(
            _mapping(result, "toolResults[]").get("toolName"), "toolResults[].toolName"
        )
        for result in tool_results
    )
    return TerminalReceipt(
        provider=provider,
        api=api,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=_nonnegative_int(
            usage.get("cacheRead", 0), "usage.cacheRead"
        ),
        cache_write_tokens=_nonnegative_int(
            usage.get("cacheWrite", 0), "usage.cacheWrite"
        ),
        total_tokens=total_tokens,
        duration_ms=_positive_float(
            terminal.get("duration"), "turn_end.message.duration"
        ),
        stop_reason=_string(terminal.get("stopReason"), "turn_end.message.stopReason"),
        tool_names=tool_names,
    )


def derive_receipt(
    cell: OmpCell,
    target: OmpTarget,
    materialized: MaterializedCondition,
    events: str,
) -> DerivedReceipt:
    """Create one immutable derived result receipt from a declared OMP cell."""
    if cell.target_id != target.id:
        raise OmpResultError("cell target differs from the terminal target")
    if cell.condition != materialized.condition:
        raise OmpResultError("cell condition differs from the materialized input")
    terminal = parse_terminal_receipt(events, target)
    if terminal.stop_reason != "stop":
        raise OmpResultError("terminal receipt did not finish normally")
    return DerivedReceipt(
        schema_version=_SCHEMA_VERSION,
        task_id=cell.task_id,
        condition=cell.condition,
        target_id=cell.target_id,
        repetition=cell.repetition,
        condition_hash=cell.condition_hash,
        materialized_hash=materialized.content_hash,
        provider=terminal.provider,
        api=terminal.api,
        model=terminal.model,
        input_tokens=terminal.input_tokens,
        output_tokens=terminal.output_tokens,
        cache_read_tokens=terminal.cache_read_tokens,
        cache_write_tokens=terminal.cache_write_tokens,
        total_tokens=terminal.total_tokens,
        duration_ms=terminal.duration_ms,
        stop_reason=terminal.stop_reason,
        tool_names=terminal.tool_names,
    )


def _safe_segment(value: str, field: str) -> str:
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value) is None:
        raise OmpResultError(f"{field}: unsafe receipt path segment")
    return value


def write_derived_receipt(root: Path, receipt: DerivedReceipt) -> Path:
    """Persist one receipt exactly once without retaining raw model content."""
    root = root.resolve()
    target = _safe_segment(receipt.target_id, "target_id")
    condition = _safe_segment(receipt.condition, "condition")
    task = _safe_segment(receipt.task_id, "task_id")
    path = (root / target / condition / task / f"{receipt.repetition}.json").resolve()
    if not path.is_relative_to(root):
        raise OmpResultError("receipt destination escapes the result root")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(asdict(receipt), indent=2, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise OmpResultError(f"derived receipt already exists: {path}") from exc
    return path


def validate_receipts(
    contract: OmpRunContract, receipts: tuple[DerivedReceipt, ...]
) -> None:
    """Require exactly one comparable receipt for every declared cell."""
    expected = {
        (cell.task_id, cell.condition, cell.target_id, cell.repetition): cell
        for cell in declared_omp_cells(contract)
    }
    actual = {
        (
            receipt.task_id,
            receipt.condition,
            receipt.target_id,
            receipt.repetition,
        ): receipt
        for receipt in receipts
    }
    if len(actual) != len(receipts):
        raise OmpResultError("derived receipts contain duplicate cells")
    undeclared = actual.keys() - expected.keys()
    if undeclared:
        raise OmpResultError(
            f"derived receipts contain undeclared cells: {sorted(undeclared)}"
        )
    missing = expected.keys() - actual.keys()
    if missing:
        raise OmpResultError(f"derived receipts are missing cells: {sorted(missing)}")
    expected_materialized = {
        condition.condition: condition.content_hash
        for condition in execution_preflight(contract).conditions
    }
    for key, receipt in actual.items():
        expected_cell = expected[key]
        if receipt.condition_hash != expected_cell.condition_hash:
            raise OmpResultError(f"derived receipt condition hash drift: {key}")
        if receipt.materialized_hash != expected_materialized[receipt.condition]:
            raise OmpResultError(f"derived receipt materialized hash drift: {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv)
    if not args.preflight:
        parser.error("--preflight is required; live OMP execution is unavailable")
    try:
        report = execution_preflight(load_omp_run_contract())
    except (OmpRunConfigError, OmpResultError) as exc:
        print(f"OMP SkillsBench result preflight failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
