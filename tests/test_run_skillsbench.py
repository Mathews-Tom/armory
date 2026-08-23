"""Tests for scripts.run_skillsbench pure logic (no live claude execution)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_skillsbench import (
    BenchmarkReport,
    ComparisonCell,
    TaskRunResult,
    aggregate_report,
    check_assertions,
    compare_reports,
    declared_cells,
    load_corpus_manifest,
    load_task,
    load_task_set,
    validate_observed_cells,
    verdict_from_score,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SEED_TASKS_DIR = _REPO_ROOT / "evals" / "skillsbench" / "tasks"
_CORPUS_PATH = _REPO_ROOT / "evals" / "skillsbench" / "corpus.yaml"


class TestLoadTask:
    def test_loads_seed_task(self) -> None:
        task = load_task(_SEED_TASKS_DIR / "task_001_code_review_simple.yaml")
        assert task.id == "task_001_code_review_simple"
        assert task.category == "review"
        assert len(task.assertions) >= 1
        assert 0.0 < task.pass_threshold <= 1.0

    def test_id_must_match_filename(self, tmp_path: Path) -> None:
        path = tmp_path / "mismatched.yaml"
        path.write_text(
            "id: other_name\n"
            "description: x\n"
            "category: review\n"
            "prompt: hi\n"
            "success_criterion:\n"
            "  type: assertion\n"
            "  assertions:\n"
            "    - {type: contains, target: x, weight: 1.0}\n"
            "  pass_threshold: 0.5\n"
            "limits: {max_turns: 1, max_tokens: 100, timeout_seconds: 10}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="must match filename"):
            load_task(path)

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "incomplete.yaml"
        path.write_text("id: incomplete\ndescription: x\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required fields"):
            load_task(path)

    def test_unsupported_criterion_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_criterion.yaml"
        path.write_text(
            "id: bad_criterion\n"
            "description: x\n"
            "category: review\n"
            "prompt: hi\n"
            "success_criterion:\n"
            "  type: llm_judge\n"
            "limits: {max_turns: 1, max_tokens: 100, timeout_seconds: 10}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unsupported criterion type"):
            load_task(path)

    def test_unsupported_assertion_type_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_assertion.yaml"
        path.write_text(
            "id: bad_assertion\n"
            "description: x\n"
            "category: review\n"
            "prompt: hi\n"
            "success_criterion:\n"
            "  type: assertion\n"
            "  assertions:\n"
            "    - {type: magic_type, target: x, weight: 1.0}\n"
            "  pass_threshold: 0.5\n"
            "limits: {max_turns: 1, max_tokens: 100, timeout_seconds: 10}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unsupported type"):
            load_task(path)


class TestLoadTaskSet:
    def test_seed_tasks_all_valid(self) -> None:
        tasks = load_task_set(_SEED_TASKS_DIR)
        assert len(tasks) >= 5
        ids = [t.id for t in tasks]
        assert len(ids) == len(set(ids))  # no duplicate ids

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert load_task_set(tmp_path / "nope") == []


class TestCorpusManifest:
    def test_loads_frozen_corpus_and_declared_cells(self) -> None:
        corpus = load_corpus_manifest(_CORPUS_PATH)
        cells = declared_cells(corpus)

        assert corpus.target_id == "claude-code-opus-xhigh"
        assert len(corpus.tasks) == 50
        assert corpus.repetitions == 3
        assert len(cells) == 450
        assert sum(task.criterion_type == "artifact" for task in corpus.tasks) == 3
        validate_observed_cells(corpus, cells)

    def test_rejects_undeclared_cell(self) -> None:
        corpus = load_corpus_manifest(_CORPUS_PATH)
        cells = declared_cells(corpus)
        undeclared = ComparisonCell(
            task_id="task_999_not_registered",
            condition="current",
            target_id=corpus.target_id,
            repetition=1,
        )

        with pytest.raises(ValueError, match="undeclared comparison cells"):
            validate_observed_cells(corpus, (*cells[1:], undeclared))

    def test_rejects_duplicate_cells(self) -> None:
        corpus = load_corpus_manifest(_CORPUS_PATH)
        cells = declared_cells(corpus)

        with pytest.raises(ValueError, match="contain duplicates"):
            validate_observed_cells(corpus, (*cells[1:], cells[1], cells[1]))

    def test_rejects_missing_cells(self) -> None:
        corpus = load_corpus_manifest(_CORPUS_PATH)
        cells = declared_cells(corpus)

        with pytest.raises(ValueError, match="cells are missing"):
            validate_observed_cells(corpus, cells[1:])

    def test_rejects_prose_only_artifact_claim(self, tmp_path: Path) -> None:
        path = tmp_path / "artifact_claim.yaml"
        path.write_text(
            "id: artifact_claim\n"
            "description: x\n"
            "category: development\n"
            "prompt: create a file\n"
            "success_criterion:\n"
            "  type: artifact\n"
            "  assertions:\n"
            "    - {type: contains, target: x, weight: 1.0}\n"
            "  artifact: {path: result.txt}\n"
            "limits: {max_turns: 1, max_tokens: 100, timeout_seconds: 10}\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="must not use prose assertions"):
            load_task(path)


class TestCheckAssertions:
    def test_all_pass(self) -> None:
        assertions = [
            {"type": "contains", "target": "hello", "weight": 0.5},
            {"type": "matches_regex", "target": "world", "weight": 0.5},
        ]
        score, details = check_assertions("hello world", assertions)
        assert score == 1.0
        assert all(d["passed"] for d in details)

    def test_all_fail(self) -> None:
        assertions = [{"type": "contains", "target": "missing", "weight": 1.0}]
        score, details = check_assertions("hello world", assertions)
        assert score == 0.0
        assert not details[0]["passed"]

    def test_weighted_partial(self) -> None:
        assertions = [
            {"type": "contains", "target": "yes", "weight": 0.75},
            {"type": "contains", "target": "no", "weight": 0.25},
        ]
        score, _ = check_assertions("yes", assertions)
        assert abs(score - 0.75) < 1e-9

    def test_weights_normalized_to_one(self) -> None:
        # Weights summing to 2.0 should still yield a score in [0, 1].
        assertions = [
            {"type": "contains", "target": "a", "weight": 1.0},
            {"type": "contains", "target": "b", "weight": 1.0},
        ]
        score, _ = check_assertions("a", assertions)
        assert abs(score - 0.5) < 1e-9

    def test_not_contains(self) -> None:
        assertions = [{"type": "not_contains", "target": "error", "weight": 1.0}]
        score, _ = check_assertions("clean output", assertions)
        assert score == 1.0

    def test_regex_case_insensitive(self) -> None:
        assertions = [{"type": "matches_regex", "target": "(?i)HELLO", "weight": 1.0}]
        score, _ = check_assertions("hello there", assertions)
        assert score == 1.0

    def test_zero_total_weight_returns_zero(self) -> None:
        assertions = [{"type": "contains", "target": "x", "weight": 0.0}]
        score, _ = check_assertions("x", assertions)
        assert score == 0.0


class TestVerdictFromScore:
    def test_above_threshold_passes(self) -> None:
        assert verdict_from_score(0.8, 0.7) == "pass"

    def test_at_threshold_passes(self) -> None:
        assert verdict_from_score(0.7, 0.7) == "pass"

    def test_below_threshold_fails(self) -> None:
        assert verdict_from_score(0.69, 0.7) == "fail"


def _result(
    task_id: str,
    config: str,
    verdict: str,
    score: float,
    attempt: int = 1,
) -> TaskRunResult:
    return TaskRunResult(
        task_id=task_id,
        config=config,
        attempt=attempt,
        verdict=verdict,
        weighted_score=score,
        output_excerpt="",
        assertion_results=[],
        execution_time_ms=100,
    )


class TestAggregateReport:
    def test_empty_results_zero_rate(self) -> None:
        report = aggregate_report("A", [])
        assert report.total_tasks == 0
        assert report.pass_rate == 0.0

    def test_pass_rate_matches_results(self) -> None:
        results = [
            _result("t1", "A", "pass", 0.9),
            _result("t2", "A", "pass", 0.8),
            _result("t3", "A", "fail", 0.4),
        ]
        report = aggregate_report("A", results)
        assert report.total_tasks == 3
        assert report.passed == 2
        assert abs(report.pass_rate - 2 / 3) < 1e-9

    def test_multiple_attempts_use_median(self) -> None:
        # Two attempts for t1: one pass, one fail. Median of 2 takes index 1
        # (the higher-scoring one) per sorted ordering.
        results = [
            _result("t1", "A", "fail", 0.2, attempt=1),
            _result("t1", "A", "pass", 0.9, attempt=2),
            _result("t1", "A", "pass", 0.8, attempt=3),
        ]
        report = aggregate_report("A", results)
        assert report.total_tasks == 1
        # Sorted scores: 0.2, 0.8, 0.9. Median index = 3//2 = 1 -> 0.8
        assert report.per_task[0].weighted_score == 0.8


class TestCompareReports:
    def _report(
        self, config: str, pass_rate: float, total: int = 10
    ) -> BenchmarkReport:
        return BenchmarkReport(
            config=config,
            timestamp="",
            total_tasks=total,
            passed=int(pass_rate * total),
            failed=total - int(pass_rate * total),
            errored=0,
            skipped=0,
            pass_rate=pass_rate,
            mean_score=pass_rate,
        )

    def test_s3_met_when_delta_exceeds_threshold(self) -> None:
        a = self._report("A", 0.85)
        b = self._report("B", 0.60)
        comparison = compare_reports(a, b)
        assert comparison["s3_exit_met"] is True
        assert comparison["verdict"] == "curation_validated"
        assert abs(comparison["delta_pp"] - 25.0) < 1e-9

    def test_s3_unmet_when_delta_below_threshold(self) -> None:
        a = self._report("A", 0.70)
        b = self._report("B", 0.65)
        comparison = compare_reports(a, b)
        assert comparison["s3_exit_met"] is False
        assert comparison["verdict"] == "thesis_unconfirmed"

    def test_custom_threshold(self) -> None:
        a = self._report("A", 0.70)
        b = self._report("B", 0.60)
        # 10pp delta meets a custom 10pp threshold
        comparison = compare_reports(a, b, min_delta_pp=10.0)
        assert comparison["s3_exit_met"] is True
