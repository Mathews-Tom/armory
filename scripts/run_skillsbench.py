#!/usr/bin/env python3
"""SkillsBench harness — bootstrap benchmark for Memento-Skills integration.

Loads tasks from ``evals/skillsbench/tasks/``, executes them against a live
Claude session in one of two configurations (A: full armory, B: primitives
only), and scores the output against each task's assertion rules.

This module contains three layers:

1. **Pure logic** (task loading, validation, assertion scoring, result
   aggregation) — fully unit-tested in ``tests/test_run_skillsbench.py``.
2. **Execution orchestration** (spawning ``claude -p``, worktree isolation,
   per-run capture) — gated behind the ``--live`` flag because it requires
   an installed ``claude`` CLI and burns real budget. Dry-run mode exercises
   only the pure logic for CI.
3. **Comparison and reporting** — reads two result files and reports the
   Config A vs Config B delta against the S3 exit criterion (≥15pp).

See ``evals/skillsbench/README.md`` for the experiment design. Full
execution is deferred to the operator — a meaningful benchmark requires
hours of live execution and should be scheduled deliberately.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TypedDict

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml  # type: ignore[import-untyped]

from scripts.model_fit import ModelFitConfigError, load_model_fit_config, select_target

_SUPPORTED_CRITERION_TYPES = {"assertion"}
_SUPPORTED_ASSERTION_TYPES = {"contains", "not_contains", "matches_regex"}
_CORPUS_SCHEMA_VERSION = 1
_REQUIRED_CONDITIONS = frozenset(
    {"current", "reduced-or-rewritten", "strengthened-contract"}
)
_DEFAULT_CORPUS_PATH = _REPO_ROOT / "evals" / "skillsbench" / "corpus.yaml"

# Tolerance for floating-point comparisons in compare_reports. Pass-rate
# subtractions like 0.70 - 0.60 produce values slightly below 0.10 in
# IEEE-754, which would incorrectly fail a threshold of exactly 0.10.
# One microunit (1e-6 percentage points) is small enough to be
# semantically irrelevant and large enough to absorb FP error.
_COMPARE_TOLERANCE_PP = 1e-6


class Assertion(TypedDict):
    """A validated final-answer assertion."""

    type: str
    target: str
    weight: float


@dataclass
class TaskDefinition:
    """A single SkillsBench task loaded from YAML."""

    id: str
    description: str
    category: str
    difficulty: str
    prompt: str
    assertions: list[Assertion]
    pass_threshold: float
    max_turns: int
    max_tokens: int
    timeout_seconds: int
    tags: list[str]
    source_path: str


@dataclass(frozen=True)
class ComparisonCell:
    """One predeclared task × condition × target × repetition cell."""

    task_id: str
    condition: str
    target_id: str
    repetition: int


@dataclass(frozen=True)
class CorpusManifest:
    """A validated, pre-result SkillsBench comparison declaration."""

    target_id: str
    baseline: str
    treatments: tuple[str, ...]
    repetitions: int
    exclusions: tuple[tuple[str, str], ...]
    tasks: tuple[TaskDefinition, ...]


@dataclass
class TaskRunResult:
    """Result of running a single task in a single configuration."""

    task_id: str
    config: str
    attempt: int
    verdict: str  # "pass" | "fail" | "error" | "skipped"
    weighted_score: float
    output_excerpt: str
    assertion_results: list[dict[str, object]]
    execution_time_ms: int
    error: str | None = None


@dataclass
class BenchmarkReport:
    """Aggregated report across all tasks in one configuration."""

    config: str
    timestamp: str
    total_tasks: int
    passed: int
    failed: int
    errored: int
    skipped: int
    pass_rate: float
    mean_score: float
    per_task: list[TaskRunResult] = field(default_factory=list)


def _require_mapping(value: object, location: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{location}: expected a mapping")
    return value


def _require_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{location}: expected a non-empty string")
    return value


def _require_string_list(value: object, location: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{location}: expected a list of strings")
    values = tuple(
        _require_string(item, f"{location}[{index}]")
        for index, item in enumerate(value)
    )
    if len(values) != len(set(values)):
        raise ValueError(f"{location}: must not contain duplicates")
    return values


def _require_positive_int(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{location}: expected a positive integer")
    return value


def _require_probability(value: object, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{location}: expected a number from 0 to 1")
    probability = float(value)
    if not 0 < probability <= 1:
        raise ValueError(f"{location}: expected a number from 0 to 1")
    return probability


def _load_task_raw(
    raw: object,
    source_path: str,
    expected_id: str | None = None,
) -> TaskDefinition:
    """Validate one file-backed or inline task mapping."""
    task = _require_mapping(raw, source_path)
    required = {
        "id",
        "description",
        "category",
        "prompt",
        "success_criterion",
        "limits",
    }
    missing = required - task.keys()
    if missing:
        raise ValueError(f"{source_path}: missing required fields: {sorted(missing)}")

    task_id = _require_string(task["id"], f"{source_path}.id")
    if expected_id is not None and task_id != expected_id:
        raise ValueError(
            f"{source_path}: task id {task_id!r} must match filename stem "
            f"{expected_id!r}"
        )

    criterion = _require_mapping(
        task["success_criterion"], f"{source_path}.success_criterion"
    )
    criterion_type = _require_string(
        criterion.get("type"), f"{source_path}.success_criterion.type"
    )
    if criterion_type not in _SUPPORTED_CRITERION_TYPES:
        raise ValueError(
            f"{source_path}: unsupported criterion type {criterion_type!r} "
            f"(supported: {sorted(_SUPPORTED_CRITERION_TYPES)})"
        )

    assertions_raw = criterion.get("assertions")
    if not isinstance(assertions_raw, list) or not assertions_raw:
        raise ValueError(f"{source_path}: criterion has no assertions")
    assertions: list[Assertion] = []
    for index, assertion_raw in enumerate(assertions_raw):
        assertion = _require_mapping(assertion_raw, f"{source_path}.assertion {index}")
        assertion_type = _require_string(
            assertion.get("type"), f"{source_path}.assertion {index}.type"
        )
        if assertion_type not in _SUPPORTED_ASSERTION_TYPES:
            raise ValueError(
                f"{source_path}: assertion {index} has unsupported type "
                f"{assertion_type!r}"
            )

        assertions.append(
            Assertion(
                type=assertion_type,
                target=_require_string(
                    assertion.get("target"),
                    f"{source_path}.assertion {index}.target",
                ),
                weight=_require_probability(
                    assertion.get("weight"),
                    f"{source_path}.assertion {index}.weight",
                ),
            )
        )

    limits = _require_mapping(task["limits"], f"{source_path}.limits")
    return TaskDefinition(
        id=task_id,
        description=_require_string(task["description"], f"{source_path}.description"),
        category=_require_string(task["category"], f"{source_path}.category"),
        difficulty=_require_string(
            task.get("difficulty", "medium"), f"{source_path}.difficulty"
        ),
        prompt=_require_string(task["prompt"], f"{source_path}.prompt"),
        assertions=assertions,
        pass_threshold=_require_probability(
            criterion.get("pass_threshold", 0.7),
            f"{source_path}.success_criterion.pass_threshold",
        ),
        max_turns=_require_positive_int(
            limits.get("max_turns", 5), f"{source_path}.limits.max_turns"
        ),
        max_tokens=_require_positive_int(
            limits.get("max_tokens", 10000), f"{source_path}.limits.max_tokens"
        ),
        timeout_seconds=_require_positive_int(
            limits.get("timeout_seconds", 180), f"{source_path}.limits.timeout_seconds"
        ),
        tags=list(_require_string_list(task.get("tags", []), f"{source_path}.tags")),
        source_path=source_path,
    )


def load_task(path: Path) -> TaskDefinition:
    """Load and validate one legacy file-backed SkillsBench task."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{path}: cannot read task: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: cannot parse task YAML: {exc}") from exc
    return _load_task_raw(raw, str(path), expected_id=path.stem)


def load_task_set(tasks_dir: Path) -> list[TaskDefinition]:
    """Load every legacy task YAML under a directory, sorted by id."""
    if not tasks_dir.is_dir():
        return []
    return [load_task(path) for path in sorted(tasks_dir.glob("*.yaml"))]


def _resolve_manifest_path(base: Path, value: object, location: str) -> Path:
    relative_path = Path(_require_string(value, location))
    if relative_path.is_absolute():
        raise ValueError(f"{location}: absolute paths are not allowed")
    resolved = (base / relative_path).resolve()
    if not resolved.is_relative_to(_REPO_ROOT.resolve()):
        raise ValueError(f"{location}: path must remain under the repository root")
    return resolved


def load_corpus_manifest(path: Path = _DEFAULT_CORPUS_PATH) -> CorpusManifest:
    """Load a frozen M3 corpus and verify its M2 target and comparison matrix."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{path}: cannot read corpus manifest: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: cannot parse corpus YAML: {exc}") from exc
    manifest = _require_mapping(raw, str(path))

    schema_version = manifest.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != _CORPUS_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: schema_version must be {_CORPUS_SCHEMA_VERSION}, "
            f"got {schema_version!r}"
        )

    model_fit = _require_mapping(manifest.get("model_fit"), f"{path}.model_fit")
    config_path = _resolve_manifest_path(
        path.parent, model_fit.get("config"), f"{path}.model_fit.config"
    )
    target_id = _require_string(model_fit.get("target"), f"{path}.model_fit.target")
    try:
        select_target(load_model_fit_config(config_path), target_id)
    except ModelFitConfigError as exc:
        raise ValueError(f"{path}.model_fit: {exc}") from exc

    comparison = _require_mapping(manifest.get("comparison"), f"{path}.comparison")
    baseline = _require_string(
        comparison.get("baseline"), f"{path}.comparison.baseline"
    )
    treatments = _require_string_list(
        comparison.get("treatments"), f"{path}.comparison.treatments"
    )
    conditions = {baseline, *treatments}
    if baseline != "current" or conditions != _REQUIRED_CONDITIONS:
        raise ValueError(
            f"{path}.comparison: must declare current, reduced-or-rewritten, "
            "and strengthened-contract conditions"
        )
    repetitions = _require_positive_int(
        comparison.get("repetitions"), f"{path}.comparison.repetitions"
    )
    if repetitions < 3:
        raise ValueError(f"{path}.comparison.repetitions: must be at least 3")

    exclusions_raw = comparison.get("exclusions")
    if not isinstance(exclusions_raw, list) or not exclusions_raw:
        raise ValueError(f"{path}.comparison.exclusions: must be a non-empty list")
    exclusions = tuple(
        (
            _require_string(
                _require_mapping(
                    exclusion_raw, f"{path}.comparison.exclusions[{index}]"
                ).get("id"),
                f"{path}.comparison.exclusions[{index}].id",
            ),
            _require_string(
                _require_mapping(
                    exclusion_raw, f"{path}.comparison.exclusions[{index}]"
                ).get("rationale"),
                f"{path}.comparison.exclusions[{index}].rationale",
            ),
        )
        for index, exclusion_raw in enumerate(exclusions_raw)
    )
    if len({exclusion[0] for exclusion in exclusions}) != len(exclusions):
        raise ValueError(f"{path}.comparison.exclusions: ids must be unique")

    tasks_raw = manifest.get("tasks")
    if not isinstance(tasks_raw, list):
        raise ValueError(f"{path}.tasks: expected a list")
    if len(tasks_raw) < 50:
        raise ValueError(f"{path}.tasks: requires at least 50 registered tasks")
    tasks: list[TaskDefinition] = []
    for index, task_raw in enumerate(tasks_raw):
        task_mapping = _require_mapping(task_raw, f"{path}.tasks[{index}]")
        if "file" in task_mapping:
            if len(task_mapping) != 1:
                raise ValueError(
                    f"{path}.tasks[{index}]: file references cannot add fields"
                )
            task_path = _resolve_manifest_path(
                path.parent, task_mapping["file"], f"{path}.tasks[{index}].file"
            )
            tasks.append(load_task(task_path))
        else:
            tasks.append(_load_task_raw(task_mapping, f"{path}#tasks[{index}]"))
    task_ids = tuple(task.id for task in tasks)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError(f"{path}.tasks: task ids must be unique")

    return CorpusManifest(
        target_id=target_id,
        baseline=baseline,
        treatments=treatments,
        repetitions=repetitions,
        exclusions=exclusions,
        tasks=tuple(tasks),
    )


def declared_cells(corpus: CorpusManifest) -> tuple[ComparisonCell, ...]:
    """Expand a frozen manifest into its exact comparison cells."""
    return tuple(
        ComparisonCell(
            task_id=task.id,
            condition=condition,
            target_id=corpus.target_id,
            repetition=repetition,
        )
        for task in corpus.tasks
        for condition in (corpus.baseline, *corpus.treatments)
        for repetition in range(1, corpus.repetitions + 1)
    )


def validate_observed_cells(
    corpus: CorpusManifest, observed_cells: tuple[ComparisonCell, ...]
) -> None:
    """Reject result-cell sets that differ from the frozen comparison matrix."""
    expected = set(declared_cells(corpus))
    observed = set(observed_cells)
    if len(observed) != len(observed_cells):
        raise ValueError("observed comparison cells contain duplicates")
    undeclared = observed - expected
    if undeclared:
        raise ValueError(
            "observed undeclared comparison cells: "
            f"{sorted(undeclared, key=lambda cell: (cell.task_id, cell.condition, cell.target_id, cell.repetition))!r}"
        )
    missing = expected - observed
    if missing:
        raise ValueError(
            "observed comparison cells are missing: "
            f"{sorted(missing, key=lambda cell: (cell.task_id, cell.condition, cell.target_id, cell.repetition))!r}"
        )


def check_assertions(
    output: str,
    assertions: list[Assertion],
) -> tuple[float, list[dict[str, object]]]:
    """Score output against a task's assertions.

    Args:
        output: The assistant's final output text.
        assertions: Parsed assertion list from a task definition.

    Returns:
        A tuple of (weighted_score, per_assertion_detail). The score is
        the sum of weights for passing assertions divided by the sum of
        all weights (so the score is in ``[0.0, 1.0]`` regardless of
        whether the weights themselves sum to 1).
    """
    total_weight = sum(float(a["weight"]) for a in assertions)
    if total_weight <= 0:
        return 0.0, []

    passed_weight = 0.0
    details: list[dict[str, object]] = []
    for assertion in assertions:
        a_type = assertion["type"]
        target = str(assertion["target"])
        weight = float(assertion["weight"])
        passed = _check_assertion(output, a_type, target)
        if passed:
            passed_weight += weight
        details.append(
            {
                "type": a_type,
                "target": target,
                "weight": weight,
                "passed": passed,
            }
        )

    return passed_weight / total_weight, details


def _check_assertion(output: str, a_type: str, target: str) -> bool:
    """Evaluate one assertion against output text.

    Args:
        output: Assistant output to check.
        a_type: Assertion type (contains, not_contains, matches_regex).
        target: Literal or regex target per assertion type.

    Returns:
        True if the assertion passes.
    """
    if a_type == "contains":
        return target in output
    if a_type == "not_contains":
        return target not in output
    if a_type == "matches_regex":
        return re.search(target, output) is not None
    raise ValueError(f"unsupported assertion type: {a_type}")


def verdict_from_score(score: float, threshold: float) -> str:
    """Convert a weighted score into a pass/fail verdict."""
    return "pass" if score >= threshold else "fail"


def aggregate_report(
    config: str,
    results: list[TaskRunResult],
) -> BenchmarkReport:
    """Aggregate per-task results into a BenchmarkReport.

    When a task has multiple attempts, only the median-scored attempt is
    used for the aggregate (matches the plan's "median of 3 runs" rule).
    """
    by_task: dict[str, list[TaskRunResult]] = {}
    for r in results:
        by_task.setdefault(r.task_id, []).append(r)

    median_attempts: list[TaskRunResult] = []
    for attempts in by_task.values():
        sorted_attempts = sorted(attempts, key=lambda r: r.weighted_score)
        median_attempts.append(sorted_attempts[len(sorted_attempts) // 2])

    total = len(median_attempts)
    passed = sum(1 for r in median_attempts if r.verdict == "pass")
    failed = sum(1 for r in median_attempts if r.verdict == "fail")
    errored = sum(1 for r in median_attempts if r.verdict == "error")
    skipped = sum(1 for r in median_attempts if r.verdict == "skipped")
    pass_rate = passed / total if total > 0 else 0.0
    mean_score = (
        sum(r.weighted_score for r in median_attempts) / total if total > 0 else 0.0
    )

    return BenchmarkReport(
        config=config,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        total_tasks=total,
        passed=passed,
        failed=failed,
        errored=errored,
        skipped=skipped,
        pass_rate=pass_rate,
        mean_score=mean_score,
        per_task=median_attempts,
    )


def compare_reports(
    report_a: BenchmarkReport,
    report_b: BenchmarkReport,
    min_delta_pp: float = 15.0,
) -> dict[str, object]:
    """Compare two configuration reports against the S3 exit criterion.

    Args:
        report_a: Config A report (armory-loaded).
        report_b: Config B report (primitives-only).
        min_delta_pp: Required percentage-point advantage for Config A.
            Default 15.0 matches the plan's S3 threshold.

    Returns:
        Dict with the delta, verdict, and supporting numbers.
    """
    delta_pp = (report_a.pass_rate - report_b.pass_rate) * 100
    s3_met = delta_pp + _COMPARE_TOLERANCE_PP >= min_delta_pp
    return {
        "config_a_pass_rate": report_a.pass_rate,
        "config_b_pass_rate": report_b.pass_rate,
        "delta_pp": delta_pp,
        "min_delta_pp": min_delta_pp,
        "s3_exit_met": s3_met,
        "verdict": "curation_validated" if s3_met else "thesis_unconfirmed",
        "total_tasks_a": report_a.total_tasks,
        "total_tasks_b": report_b.total_tasks,
    }


def run_task_live(
    task: TaskDefinition,
    config: str,
    allowed_tools: list[str] | None = None,
) -> TaskRunResult:
    """Execute a single task against a live ``claude`` session.

    **Operator note:** this function actually spawns ``claude -p`` and
    burns budget. Guard calls behind the ``--live`` CLI flag. The pure
    logic above (loading, scoring, aggregation) is what the unit tests
    exercise; this function is only covered by integration runs.

    Args:
        task: The task to run.
        config: ``"A"`` or ``"B"`` — used only for labeling the result.
        allowed_tools: Explicit tool allowlist for ``claude -p``. If
            ``None``, defaults to a broad read-only set; Config B runs
            should restrict to the primitives.

    Returns:
        A TaskRunResult with the verdict and captured output excerpt.
    """
    start_ms = time.monotonic_ns() // 1_000_000
    tools = allowed_tools or ["Read", "Glob", "Grep", "Bash", "WebFetch"]
    tmpdir = tempfile.mkdtemp(prefix="skillsbench_")
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                task.prompt,
                "--output-format",
                "text",
                "--allowedTools",
                *tools,
            ],
            capture_output=True,
            text=True,
            timeout=task.timeout_seconds,
            cwd=tmpdir,
        )
        output = result.stdout or ""
        error: str | None = None
        if result.returncode != 0:
            error = f"claude returncode={result.returncode}: {result.stderr[:500]}"
    except subprocess.TimeoutExpired:
        output = ""
        error = f"timed out after {task.timeout_seconds}s"
    except FileNotFoundError:
        output = ""
        error = "'claude' CLI not found in PATH"

    elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms

    if error:
        return TaskRunResult(
            task_id=task.id,
            config=config,
            attempt=1,
            verdict="error",
            weighted_score=0.0,
            output_excerpt="",
            assertion_results=[],
            execution_time_ms=elapsed_ms,
            error=error,
        )

    score, details = check_assertions(output, task.assertions)
    return TaskRunResult(
        task_id=task.id,
        config=config,
        attempt=1,
        verdict=verdict_from_score(score, task.pass_threshold),
        weighted_score=score,
        output_excerpt=output[:2000],
        assertion_results=details,
        execution_time_ms=elapsed_ms,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the SkillsBench bootstrap benchmark",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_DEFAULT_CORPUS_PATH,
        help="Frozen corpus manifest to validate and load",
    )
    parser.add_argument(
        "--task",
        help="Run one registered task by id (default: all registered tasks)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Explicitly select every registered task",
    )
    parser.add_argument(
        "--config",
        choices=["A", "B"],
        default="A",
        help="A: full armory, B: primitives only + librarian",
    )
    parser.add_argument(
        "--output",
        default="evals/skillsbench/results/latest.json",
        help="Path to write the benchmark report",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load tasks and validate schema without running claude",
    )
    parser.add_argument(
        "--validate-manifest",
        action="store_true",
        help="Validate the frozen corpus and print its declared cell count",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually invoke claude -p (otherwise dry-run is implied)",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("REPORT_A", "REPORT_B"),
        help="Compare two saved reports and print the S3 verdict",
    )
    args = parser.parse_args()

    if args.compare:
        return _compare_command(args.compare[0], args.compare[1])

    corpus = load_corpus_manifest(args.manifest)
    cells = declared_cells(corpus)
    if len(cells) != len(set(cells)):
        raise ValueError(f"{args.manifest}: generated duplicate comparison cells")
    if args.validate_manifest:
        print(
            f"Validated {len(corpus.tasks)} task(s), {len(cells)} declared cell(s), "
            f"and {len(corpus.exclusions)} exclusion rule(s)."
        )
        return 0

    if args.task:
        tasks = [task for task in corpus.tasks if task.id == args.task]
        if not tasks:
            parser.error(f"undeclared task: {args.task}")
    else:
        tasks = list(corpus.tasks)

    if args.dry_run or not args.live:
        print(
            f"Loaded {len(tasks)} registered task(s) for config {args.config} "
            f"from {args.manifest}"
        )
        print(
            f"Frozen comparison: target={corpus.target_id}, "
            f"conditions={','.join((corpus.baseline, *corpus.treatments))}, "
            f"repetitions={corpus.repetitions}, declared_cells={len(cells)}"
        )
        print("Dry run — no tasks executed. Pass --live to actually run claude -p.")
        for task in tasks:
            print(
                f"  - {task.id} ({task.category}/{task.difficulty}): {task.description}"
            )
        return 0

    allowed_tools: list[str] | None
    if args.config == "B":
        allowed_tools = ["Read", "Glob", "Grep", "Bash", "WebFetch"]
    else:
        allowed_tools = None

    results: list[TaskRunResult] = []
    for task in tasks:
        print(f"Running {task.id} [{args.config}]...")
        result = run_task_live(task, args.config, allowed_tools=allowed_tools)
        results.append(result)
        print(f"  verdict={result.verdict} score={result.weighted_score:.2f}")

    report = aggregate_report(args.config, results)
    output_path = _REPO_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    print(
        f"Report written to {args.output} "
        f"(pass_rate={report.pass_rate:.2%}, mean_score={report.mean_score:.2f})"
    )
    return 0 if report.failed == 0 and report.errored == 0 else 1


def _compare_command(path_a: str, path_b: str) -> int:
    """Implement the ``--compare`` subcommand."""
    data_a = json.loads((_REPO_ROOT / path_a).read_text(encoding="utf-8"))
    data_b = json.loads((_REPO_ROOT / path_b).read_text(encoding="utf-8"))
    report_a = BenchmarkReport(
        config=data_a["config"],
        timestamp=data_a["timestamp"],
        total_tasks=data_a["total_tasks"],
        passed=data_a["passed"],
        failed=data_a["failed"],
        errored=data_a["errored"],
        skipped=data_a["skipped"],
        pass_rate=data_a["pass_rate"],
        mean_score=data_a["mean_score"],
    )
    report_b = BenchmarkReport(
        config=data_b["config"],
        timestamp=data_b["timestamp"],
        total_tasks=data_b["total_tasks"],
        passed=data_b["passed"],
        failed=data_b["failed"],
        errored=data_b["errored"],
        skipped=data_b["skipped"],
        pass_rate=data_b["pass_rate"],
        mean_score=data_b["mean_score"],
    )
    comparison = compare_reports(report_a, report_b)
    print(json.dumps(comparison, indent=2))
    return 0 if comparison["s3_exit_met"] else 2


if __name__ == "__main__":
    sys.exit(main())
