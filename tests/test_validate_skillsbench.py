"""Tests for frozen SkillsBench package-strata validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_skillsbench import validate_strata

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STRATA_PATH = _REPO_ROOT / "evals" / "skillsbench" / "package_strata.yaml"


def test_validates_every_package_classification() -> None:
    # One included sample per package type is the frozen design; the excluded
    # count is just "however many packages the repo currently ships" and
    # pinning it turned every package addition into a test failure.
    included, excluded = validate_strata(_STRATA_PATH)
    assert included == 7
    assert excluded > 0


def test_rejects_conflicting_package_classification(tmp_path: Path) -> None:
    path = tmp_path / "strata.yaml"
    path.write_text(
        _STRATA_PATH.read_text(encoding="utf-8")
        + "\n  - package_type: agent\n    name: security-reviewer\n    rationale: duplicate\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cannot be both included and excluded"):
        validate_strata(path)
