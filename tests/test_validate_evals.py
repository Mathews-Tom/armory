"""Tests for active package eval coverage validation."""

from __future__ import annotations

from pathlib import Path

from scripts.package_types import TYPES
from scripts.validate_evals import validate_pkg_evals


def _write_skill(package_dir: Path, *, deprecated: bool = False) -> None:
    package_dir.mkdir()
    metadata = "metadata:\n  status: deprecated\n" if deprecated else ""
    (package_dir / "SKILL.md").write_text(
        f"---\nname: {package_dir.name}\ndescription: Test skill.\n{metadata}---\n",
        encoding="utf-8",
    )


def test_active_package_without_eval_file_fails(tmp_path: Path) -> None:
    package_dir = tmp_path / "active-skill"
    _write_skill(package_dir)

    assert validate_pkg_evals(package_dir, TYPES["skill"]) == [
        "active-skill: missing required evals/cases.yaml"
    ]


def test_deprecated_package_without_eval_file_is_exempt(tmp_path: Path) -> None:
    package_dir = tmp_path / "deprecated-skill"
    _write_skill(package_dir, deprecated=True)

    assert validate_pkg_evals(package_dir, TYPES["skill"]) == []
