#!/usr/bin/env python3
"""Validate deterministic routing boundaries between selected armory packages.

The harness scores only each fixture's expected package and explicit non-winners.
It does not change package routing; it detects when package descriptions stop
separating a declared boundary prompt.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.frontmatter import parse_frontmatter  # noqa: E402
from scripts.package_types import TYPES  # noqa: E402

_TOKEN = re.compile(r"[a-z0-9][a-z0-9-]*")
_QUOTED_TRIGGER = re.compile(r'"([^"]+)"')
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "md",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "use",
        "when",
        "with",
    }
)


@dataclass(frozen=True)
class RoutingCase:
    """One expected routing result and its explicit competitors."""

    identifier: str
    prompt: str
    expected: str
    non_winners: tuple[str, ...]


@dataclass(frozen=True)
class RoutingResult:
    """One evaluated routing fixture."""

    case: RoutingCase
    scores: tuple[tuple[str, float], ...]

    @property
    def winner(self) -> str:
        return self.scores[0][0]


def tokenize(text: str) -> tuple[str, ...]:
    """Return meaningful, normalized tokens in deterministic source order."""
    return tuple(
        token
        for token in _TOKEN.findall(text.lower())
        if token not in _STOP_WORDS and len(token) > 1
    )


def score(prompt: str, description: str) -> float:
    """Score normalized term overlap and complete declared trigger matches."""
    prompt_tokens = set(tokenize(prompt))
    description_tokens = set(tokenize(description))
    union = prompt_tokens | description_tokens
    overlap = len(prompt_tokens & description_tokens) / len(union) if union else 0.0
    trigger_bonus = sum(
        1.0
        for trigger in _QUOTED_TRIGGER.findall(description)
        if trigger.lower() in prompt.lower()
    )
    return overlap + trigger_bonus


def load_cases(path: Path) -> tuple[RoutingCase, ...]:
    """Load and validate routing fixtures from YAML."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Cannot read valid YAML from {path}: {error}") from error

    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ValueError(f"{path}: expected a top-level 'cases' list")

    cases: list[RoutingCase] = []
    identifiers: set[str] = set()
    for index, item in enumerate(raw["cases"], start=1):
        prefix = f"{path} case #{index}"
        if not isinstance(item, dict):
            raise ValueError(f"{prefix}: expected a mapping")
        unknown_fields = set(item) - {"id", "prompt", "expected", "non_winners"}
        if unknown_fields:
            raise ValueError(
                f"{prefix}: unknown field(s): {', '.join(sorted(unknown_fields))}"
            )
        identifier = item.get("id")
        prompt = item.get("prompt")
        expected = item.get("expected")
        non_winners = item.get("non_winners", [])
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"{prefix}: 'id' must be a non-empty string")
        if identifier in identifiers:
            raise ValueError(f"{prefix}: duplicate id '{identifier}'")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"{prefix}: 'prompt' must be a non-empty string")
        if not isinstance(expected, str) or not expected:
            raise ValueError(f"{prefix}: 'expected' must be a non-empty string")
        if not isinstance(non_winners, list) or not all(
            isinstance(name, str) and name for name in non_winners
        ):
            raise ValueError(
                f"{prefix}: 'non_winners' must be a list of non-empty strings"
            )
        if len(set(non_winners)) != len(non_winners):
            raise ValueError(f"{prefix}: 'non_winners' must not contain duplicates")
        if expected in non_winners:
            raise ValueError(f"{prefix}: expected package cannot be a non-winner")
        identifiers.add(identifier)
        cases.append(RoutingCase(identifier, prompt, expected, tuple(non_winners)))
    if not cases:
        raise ValueError(f"{path}: 'cases' must not be empty")
    return tuple(cases)


def load_descriptions(repo_root: Path, package_paths: Iterable[str]) -> dict[str, str]:
    """Load requested package descriptions, rejecting invalid package definitions."""
    requested = set(package_paths)
    descriptions: dict[str, str] = {}
    for package_type in TYPES.values():
        package_root = repo_root / package_type.dir_name
        if not package_root.exists():
            continue
        for package_dir in package_root.iterdir():
            package_path = f"{package_type.dir_name}/{package_dir.name}"
            if package_path not in requested:
                continue
            definition = package_dir / package_type.definition_file
            if not definition.is_file():
                raise ValueError(
                    f"{package_path}: missing {package_type.definition_file}"
                )
            try:
                metadata = parse_frontmatter(definition.read_text(encoding="utf-8"))
            except (OSError, ValueError, yaml.YAMLError) as error:
                raise ValueError(
                    f"Cannot read valid frontmatter from {definition}: {error}"
                ) from error
            if not isinstance(metadata, dict):
                raise ValueError(f"{definition}: frontmatter must be a mapping")
            description = metadata.get("description")
            if not isinstance(description, str) or not description.strip():
                raise ValueError(
                    f"{definition}: package description must be a non-empty string"
                )
            descriptions[package_path] = description
    missing = sorted(requested - descriptions.keys())
    if missing:
        raise ValueError(
            f"Routing fixtures reference unknown package path(s): {', '.join(missing)}"
        )
    return descriptions


def evaluate(
    cases: Iterable[RoutingCase], descriptions: dict[str, str]
) -> tuple[RoutingResult, ...]:
    """Rank each fixture's expected package and explicit non-winners."""
    results: list[RoutingResult] = []
    for case in cases:
        candidates = (case.expected, *case.non_winners)
        scores = tuple(
            sorted(
                ((name, score(case.prompt, descriptions[name])) for name in candidates),
                key=lambda entry: (-entry[1], entry[0]),
            )
        )
        results.append(RoutingResult(case, scores))
    return tuple(results)


def failures(results: Iterable[RoutingResult]) -> tuple[str, ...]:
    """Return routing contract failures, including zero-score and tied winners."""
    errors: list[str] = []
    for result in results:
        expected_score = dict(result.scores)[result.case.expected]
        highest_score = result.scores[0][1]
        tied = [
            name
            for name, candidate_score in result.scores
            if candidate_score == highest_score
        ]
        if expected_score == 0:
            errors.append(f"{result.case.identifier}: expected package has zero score")
        if result.winner != result.case.expected:
            errors.append(
                f"{result.case.identifier}: expected {result.case.expected}, got {result.winner}"
            )
        if len(tied) > 1:
            errors.append(
                f"{result.case.identifier}: top score {highest_score:.3f} ties {', '.join(tied)}"
            )
    return tuple(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=_REPO_ROOT / "tests/fixtures/routing_cases.yaml",
        help="YAML routing fixtures (default: tests/fixtures/routing_cases.yaml)",
    )
    args = parser.parse_args()

    try:
        cases = load_cases(args.fixtures)
        package_paths = {case.expected for case in cases}
        package_paths.update(name for case in cases for name in case.non_winners)
        descriptions = load_descriptions(_REPO_ROOT, package_paths)
        results = evaluate(cases, descriptions)
    except ValueError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1

    for result in results:
        ranking = ", ".join(
            f"{name}={candidate_score:.3f}" for name, candidate_score in result.scores
        )
        print(f"{result.case.identifier}: {ranking}")
    errors = failures(results)
    if errors:
        print("FAILED:", file=sys.stderr)
        for failure in errors:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(f"Validated {len(results)} routing cases — all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
