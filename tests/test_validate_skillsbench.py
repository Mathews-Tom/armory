"""Tests for frozen SkillsBench package-strata validation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from scripts.install import PackageInfo, discover_packages
from scripts.package_types import TYPES
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


_OMP_RUN_PATH = _REPO_ROOT / "evals" / "skillsbench" / "omp_run.yaml"


def _with_native_package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Add one registered native extension to the real discovered inventory."""
    import scripts.validate_skillsbench as module

    real = discover_packages()
    source = tmp_path / "extensions" / "native-demo"
    source.mkdir(parents=True)
    native = PackageInfo("native-demo", "1.0.0", "", source, TYPES["extension"])
    monkeypatch.setattr(module, "discover_packages", lambda: [*real, native])


def _strata_with(tmp_path: Path, section: str) -> Path:
    document = yaml.safe_load(_STRATA_PATH.read_text(encoding="utf-8"))
    document[section].append(
        {
            "package_type": "extension",
            "name": "native-demo",
            "rationale": "Native runtime outside the original study.",
        }
    )
    path = tmp_path / "strata.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_registered_native_extension_must_be_classified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_native_package(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match=r"missing=\[\('extension', 'native-demo'\)\]"):
        validate_strata(_STRATA_PATH)


def test_excluded_native_extension_keeps_frozen_seven_type_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_native_package(monkeypatch, tmp_path)
    included, _excluded = validate_strata(_strata_with(tmp_path, "excluded"))
    assert included == 7


def test_native_extension_cannot_join_the_frozen_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_native_package(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="historically eligible types"):
        validate_strata(_strata_with(tmp_path, "included"))


def test_included_sample_is_the_frozen_treatment_population() -> None:
    """The included definitions are exactly the pinned treatment sources, byte for byte."""
    strata = yaml.safe_load(_STRATA_PATH.read_text(encoding="utf-8"))
    included = {
        f"{entry['package_type']}/{entry['name']}" for entry in strata["included"]
    }
    treatments = yaml.safe_load(_OMP_RUN_PATH.read_text(encoding="utf-8"))["treatments"]

    assert included == {treatment["package"] for treatment in treatments}
    for treatment in treatments:
        source = _REPO_ROOT / treatment["source"]
        assert (
            hashlib.sha256(source.read_bytes()).hexdigest()
            == treatment["source_sha256"]
        ), treatment["package"]
