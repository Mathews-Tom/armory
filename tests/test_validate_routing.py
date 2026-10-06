"""Tests for deterministic package-description routing validation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.validate_routing import (
    RoutingCase,
    evaluate,
    failures,
    load_cases,
    load_descriptions,
    main,
    score,
    tokenize,
)


def test_tokenize_removes_common_words_and_file_extensions() -> None:
    assert tokenize("Map the architecture decisions from README.md") == (
        "map",
        "architecture",
        "decisions",
        "readme",
    )


def test_score_rewards_exact_quoted_trigger() -> None:
    description = 'Triggers on: "map the decisions".'
    assert score("Please map the decisions", description) > score(
        "Please map this", description
    )


def test_load_cases_allows_no_non_winners(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.yaml"
    fixture.write_text(
        "cases:\n  - id: solo\n    prompt: route this\n    expected: skills/example\n",
        encoding="utf-8",
    )

    assert load_cases(fixture) == (
        RoutingCase("solo", "route this", "skills/example", ()),
    )


def test_load_cases_rejects_unknown_fields(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.yaml"
    fixture.write_text(
        "cases:\n"
        "  - id: invalid\n    prompt: prompt\n    expected: skills/example\n"
        "    non-winners: [skills/other]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown field"):
        load_cases(fixture)


def test_load_cases_rejects_duplicate_ids(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.yaml"
    fixture.write_text(
        "cases:\n"
        "  - id: duplicate\n    prompt: first\n    expected: skills/a\n    non_winners: []\n"
        "  - id: duplicate\n    prompt: second\n    expected: skills/b\n    non_winners: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate id"):
        load_cases(fixture)


def test_load_cases_rejects_duplicate_non_winners(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.yaml"
    fixture.write_text(
        "cases:\n  - id: duplicate\n    prompt: prompt\n    expected: skills/a\n"
        "    non_winners: [skills/b, skills/b]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must not contain duplicates"):
        load_cases(fixture)


def test_load_cases_rejects_expected_non_winner(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.yaml"
    fixture.write_text(
        "cases:\n"
        "  - id: invalid\n    prompt: prompt\n    expected: skills/decision-map\n"
        "    non_winners: [skills/decision-map]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cannot be a non-winner"):
        load_cases(fixture)


def test_load_descriptions_reads_requested_package(tmp_path: Path) -> None:
    definition = tmp_path / "skills" / "example" / "SKILL.md"
    definition.parent.mkdir(parents=True)
    definition.write_text(
        "---\nname: example\ndescription: Example routing description\n---\n",
        encoding="utf-8",
    )

    assert load_descriptions(tmp_path, {"skills/example"}) == {
        "skills/example": "Example routing description"
    }


def test_load_descriptions_rejects_missing_definition(tmp_path: Path) -> None:
    (tmp_path / "skills" / "example").mkdir(parents=True)

    with pytest.raises(ValueError, match="missing SKILL.md"):
        load_descriptions(tmp_path, {"skills/example"})


def test_load_descriptions_rejects_malformed_frontmatter(tmp_path: Path) -> None:
    definition = tmp_path / "skills" / "example" / "SKILL.md"
    definition.parent.mkdir(parents=True)
    definition.write_text("---\n[\n---\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Cannot read valid frontmatter"):
        load_descriptions(tmp_path, {"skills/example"})


def test_load_descriptions_rejects_missing_package(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown package path"):
        load_descriptions(tmp_path, {"skills/missing"})


def test_failures_rejects_non_winner_that_outranks_expected() -> None:
    case = RoutingCase(
        "boundary", "plan work", "skills/decision-map", ("skills/plan-prompts",)
    )
    results = evaluate(
        (case,),
        {
            "skills/decision-map": "map unresolved decisions",
            "skills/plan-prompts": "plan work",
        },
    )

    assert failures(results) == (
        "boundary: expected package has zero score",
        "boundary: expected skills/decision-map, got skills/plan-prompts",
    )


def test_failures_rejects_top_score_tie() -> None:
    case = RoutingCase("tie", "plan", "skills/expected", ("skills/other",))
    results = evaluate(
        (case,),
        {"skills/expected": "plan", "skills/other": "plan"},
    )

    assert failures(results) == (
        "tie: top score 1.000 ties skills/expected, skills/other",
    )


def test_main_reports_repository_fixture(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["validate_routing.py"])

    assert main() == 0
    assert "routing cases — all passed" in capsys.readouterr().out


def test_main_reports_invalid_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = tmp_path / "invalid.yaml"
    fixture.write_text("cases: not-a-list\n", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["validate_routing.py", "--fixtures", str(fixture)]
    )

    assert main() == 1
    assert "FAILED:" in capsys.readouterr().err


def test_repository_routing_cases_pass() -> None:
    fixture = Path(__file__).parent / "fixtures" / "routing_cases.yaml"
    cases = load_cases(fixture)
    paths = {case.expected for case in cases}
    paths.update(name for case in cases for name in case.non_winners)
    descriptions = load_descriptions(Path(__file__).parent.parent, paths)

    assert failures(evaluate(cases, descriptions)) == ()
