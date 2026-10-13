"""Unit tests for the Opus 4.7 migration scanner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scan import (  # noqa: E402  (conftest mutates sys.path)
    format_json_report,
    format_text_report,
    main,
    scan_repository,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "config").mkdir()

    (tmp_path / "src" / "reasoner.py").write_text(
        '"""Reasoner with fixed budget."""\n'
        "from anthropic import Anthropic\n"
        "client = Anthropic()\n"
        'MODEL = "claude-opus-4-5"\n'
        "response = client.messages.create(\n"
        "    model=MODEL,\n"
        '    thinking={"type": "enabled", "budget_tokens": 8000},\n'
        '    messages=[{"role": "user", "content": "hi"}],\n'
        ")\n"
    )

    (tmp_path / "src" / "planner.py").write_text(
        'budget_tokens = 4096\nDEFAULT_MODEL = "claude-sonnet-4-5"\n'
    )

    (tmp_path / "tests" / "test_reasoner.py").write_text(
        "def test_override():\n"
        '    override = "test-model-override"\n'
        '    assert override == "test-model-override"\n'
    )

    (tmp_path / "config" / "app.yaml").write_text(
        "models:\n  planner: claude-opus-4-5\n  critic: claude-sonnet-4-20250514\n"
    )

    (tmp_path / "agents" / "research-analyst").mkdir(parents=True)
    (tmp_path / "agents" / "research-analyst" / "AGENT.md").write_text(
        "# Research Analyst\n\n"
        "Spawn parallel research agents using the Agent tool. Each targets a source.\n"
        "Then explain the findings in detail when complete.\n"
    )

    (tmp_path / "agents" / "orchestrator" / "AGENT.md").parent.mkdir()
    (tmp_path / "agents" / "orchestrator" / "AGENT.md").write_text(
        "# Orchestrator\n\n"
        "Spawn three agents in parallel in a single assistant message. "
        "These sub-tasks are independent.\n"
    )

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("budget_tokens = 9999\n")

    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("thinking = {budget_tokens: 1}\n")

    return tmp_path


# ---------------------------------------------------------------------------
# Category A — fixed-budget Extended Thinking
# ---------------------------------------------------------------------------


def test_category_a_detects_budget_tokens_literal(sample_repo: Path) -> None:
    # Arrange
    requested = frozenset({"A"})

    # Act
    report = scan_repository(
        sample_repo, requested, ["__pycache__", ".git", "node_modules"]
    )

    # Assert
    findings = report.findings.get("A", [])
    assert len(findings) == 2
    matched_texts = {f.matched_text for f in findings}
    assert any("budget_tokens" in text for text in matched_texts)


def test_category_a_excludes_git_and_node_modules(sample_repo: Path) -> None:
    # Arrange / Act
    report = scan_repository(sample_repo, frozenset({"A"}), [".git", "node_modules"])

    # Assert
    for finding in report.findings.get("A", []):
        assert ".git" not in finding.path.parts
        assert "node_modules" not in finding.path.parts


# ---------------------------------------------------------------------------
# Category B — retired model ID aliases
# ---------------------------------------------------------------------------


def test_category_b_detects_retired_aliases(sample_repo: Path) -> None:
    # Arrange / Act
    report = scan_repository(sample_repo, frozenset({"B"}), [".git", "node_modules"])

    # Assert
    matched = {f.matched_text for f in report.findings.get("B", [])}
    assert "claude-opus-4-5" in matched
    assert "claude-sonnet-4-5" in matched
    assert "claude-sonnet-4-20250514" in matched


def test_category_b_does_not_flag_current_aliases(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "ok.py").write_text(
        'MODEL = "claude-opus-4-7"\nM2 = "claude-sonnet-4-6"\n'
    )

    # Act
    report = scan_repository(tmp_path, frozenset({"B"}), [])

    # Assert
    assert report.findings.get("B", []) == []


# ---------------------------------------------------------------------------
# Category C — hardcoded model refs outside config
# ---------------------------------------------------------------------------


def test_category_c_flags_hardcoded_code_refs(sample_repo: Path) -> None:
    # Arrange / Act
    report = scan_repository(sample_repo, frozenset({"C"}), [".git", "node_modules"])

    # Assert
    findings = report.findings.get("C", [])
    matched_paths = {str(f.path.relative_to(sample_repo)) for f in findings}
    assert any("src/reasoner.py" in path for path in matched_paths)
    assert any("src/planner.py" in path for path in matched_paths)


def test_category_c_ignores_test_sentinels(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "t.py").write_text(
        'override = "test-model-override"\nmodel = "claude-opus-4-7"\n'
    )

    # Act
    report = scan_repository(tmp_path, frozenset({"C"}), [])

    # Assert — line with test sentinel is skipped; literal model ref still flagged
    findings = report.findings.get("C", [])
    assert len(findings) == 1
    assert findings[0].line_number == 2


# ---------------------------------------------------------------------------
# Category D — verbosity-assuming prompts (heuristic)
# ---------------------------------------------------------------------------


def test_category_d_flags_verbosity_phrases(sample_repo: Path) -> None:
    # Arrange / Act
    report = scan_repository(sample_repo, frozenset({"D"}), [".git", "node_modules"])

    # Assert
    findings = report.findings.get("D", [])
    assert len(findings) >= 1


# ---------------------------------------------------------------------------
# Category E — non-explicit parallel dispatch (heuristic)
# ---------------------------------------------------------------------------


def test_category_e_flags_unclear_parallel_dispatch(sample_repo: Path) -> None:
    # Arrange / Act
    report = scan_repository(sample_repo, frozenset({"E"}), [".git", "node_modules"])

    # Assert — research-analyst AGENT.md should flag; orchestrator should not
    findings = report.findings.get("E", [])
    matched_paths = {str(f.path.relative_to(sample_repo)) for f in findings}
    assert any("research-analyst" in path for path in matched_paths)
    assert not any("agents/orchestrator" in path for path in matched_paths)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def test_text_report_contains_all_requested_categories(sample_repo: Path) -> None:
    # Arrange
    requested = frozenset({"A", "B", "C", "D", "E"})

    # Act
    report = scan_repository(sample_repo, requested, [".git", "node_modules"])
    text = format_text_report(report, requested)

    # Assert
    for label in ("Category A", "Category B", "Category C", "Category D", "Category E"):
        assert label in text
    assert "Total:" in text


def test_json_report_is_valid_and_structured(sample_repo: Path) -> None:
    # Arrange
    requested = frozenset({"A", "B"})

    # Act
    report = scan_repository(sample_repo, requested, [".git", "node_modules"])
    payload = json.loads(format_json_report(report, requested))

    # Assert
    assert payload["root"] == str(sample_repo)
    assert set(payload["findings"].keys()) == {"A", "B"}
    assert payload["totals"]["deterministic"] >= 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_exits_1_with_exit_code_flag_when_deterministic_findings(
    sample_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange / Act
    exit_code = main([str(sample_repo), "--categories", "A,B,C", "--exit-code"])

    # Assert
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Category A" in captured.out


def test_cli_exits_0_on_clean_repo(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "clean.py").write_text("x = 1\n")

    # Act
    exit_code = main([str(tmp_path), "--categories", "A,B,C", "--exit-code"])

    # Assert
    assert exit_code == 0


def test_cli_rejects_unknown_category(tmp_path: Path) -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="Unknown categories"):
        main([str(tmp_path), "--categories", "Z"])


def test_cli_raises_on_missing_repo(tmp_path: Path) -> None:
    # Arrange
    missing = tmp_path / "does-not-exist"

    # Act / Assert
    with pytest.raises(FileNotFoundError):
        main([str(missing)])
