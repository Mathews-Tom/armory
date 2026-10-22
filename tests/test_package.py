"""Tests for scripts/package.py — type-aware packaging."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.package import (
    collect_files,
    package,
    package_skill,
    validate_frontmatter,
)
from scripts.package_types import TYPES, PackageType, detect_type_from_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_definition(
    pkg_dir: Path,
    pkg_type: PackageType,
    *,
    name: str = "test-pkg",
    version: str = "1.0.0",
    extras: str = "",
) -> None:
    """Write a minimal definition file with valid frontmatter."""
    fields = f"name: {name}\ndescription: A test package.\nmetadata:\n  version: {version}\n"
    if "model" in pkg_type.required_frontmatter:
        fields += "model: gpt-4.1\n"
    if "color" in pkg_type.required_frontmatter:
        fields += "color: blue\n"
    if "hook" in pkg_type.required_frontmatter:
        fields += "hook: pre-commit\n"
    if "utility" in pkg_type.required_frontmatter:
        fields += "utility: formatter\n"
    if "preset" in pkg_type.required_frontmatter:
        fields += "preset: default\n"
    if "extension" in pkg_type.required_frontmatter:
        fields += "extension: {schema_version: 1}\n"
    fields += extras
    content = f"---\n{fields}---\n# Content\n"
    (pkg_dir / pkg_type.definition_file).write_text(content)


# ---------------------------------------------------------------------------
# validate_frontmatter
# ---------------------------------------------------------------------------


class TestValidateFrontmatter:
    """Type-aware frontmatter validation."""

    @pytest.mark.parametrize("type_key", list(TYPES.keys()))
    def test_valid_all_types(self, tmp_path: Path, type_key: str) -> None:
        pkg_type = TYPES[type_key]
        pkg_dir = tmp_path / "my-pkg"
        pkg_dir.mkdir()
        _write_definition(pkg_dir, pkg_type)
        meta = validate_frontmatter(pkg_dir, pkg_type)
        assert meta["name"] == "test-pkg"
        assert meta["_resolved_version"] == "1.0.0"

    def test_missing_definition_file(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "my-agent"
        pkg_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="AGENT.md not found"):
            validate_frontmatter(pkg_dir, TYPES["agent"])

    def test_missing_type_specific_field(self, tmp_path: Path) -> None:
        """Agent requires 'model' — omit it and expect failure."""
        pkg_type = TYPES["agent"]
        pkg_dir = tmp_path / "bad-agent"
        pkg_dir.mkdir()
        # Write without model/color fields
        content = "---\nname: bad-agent\ndescription: Missing fields.\nmetadata:\n  version: 1.0.0\n---\n"
        (pkg_dir / "AGENT.md").write_text(content)
        with pytest.raises(ValueError, match="missing required fields.*model"):
            validate_frontmatter(pkg_dir, pkg_type)

    def test_invalid_version(self, tmp_path: Path) -> None:
        pkg_type = TYPES["skill"]
        pkg_dir = tmp_path / "bad-ver"
        pkg_dir.mkdir()
        content = "---\nname: bad-ver\ndescription: Bad version.\nmetadata:\n  version: v1.0\n---\n"
        (pkg_dir / "SKILL.md").write_text(content)
        with pytest.raises(ValueError, match="Invalid version"):
            validate_frontmatter(pkg_dir, pkg_type)


# ---------------------------------------------------------------------------
# collect_files
# ---------------------------------------------------------------------------


class TestCollectFiles:
    def test_excludes_pycache_and_ds_store(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "main.py").write_text("code")
        pycache = pkg_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.pyc").write_text("bytecode")
        (pkg_dir / ".DS_Store").write_text("ds")

        included, excluded = collect_files(pkg_dir)
        included_names = {p.name for p in included}
        excluded_names = {p.name for p in excluded}

        assert "main.py" in included_names
        assert "cached.pyc" in excluded_names
        assert ".DS_Store" in excluded_names


# ---------------------------------------------------------------------------
# package (archive creation)
# ---------------------------------------------------------------------------


class TestPackage:
    @pytest.mark.parametrize(
        "type_key,expected_ext",
        [
            ("skill", ".skill"),
            ("agent", ".agent"),
            ("hook", ".hook"),
            ("rule", ".rule"),
            ("command", ".command"),
            ("utility", ".utility"),
            ("preset", ".preset"),
        ],
    )
    def test_archive_extension_per_type(
        self, tmp_path: Path, type_key: str, expected_ext: str
    ) -> None:
        pkg_type = TYPES[type_key]
        pkg_dir = tmp_path / "my-pkg"
        pkg_dir.mkdir()
        _write_definition(pkg_dir, pkg_type, name="my-pkg", version="2.0.0")

        output_dir = tmp_path / "dist"
        result = package(pkg_dir, output_dir, pkg_type)

        assert result.name == f"my-pkg-2.0.0{expected_ext}"
        assert result.exists()
        assert zipfile.is_zipfile(result)

    def test_archive_contains_files(self, tmp_path: Path) -> None:
        pkg_type = TYPES["rule"]
        pkg_dir = tmp_path / "my-rule"
        pkg_dir.mkdir()
        _write_definition(pkg_dir, pkg_type)
        (pkg_dir / "extra.txt").write_text("content")

        result = package(pkg_dir, tmp_path / "dist", pkg_type)
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert any("RULE.md" in n for n in names)
            assert any("extra.txt" in n for n in names)


# ---------------------------------------------------------------------------
# package_skill (backward compat wrapper)
# ---------------------------------------------------------------------------


class TestPackageSkill:
    def test_backward_compat(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        _write_definition(skill_dir, TYPES["skill"], name="my-skill", version="3.0.0")

        result = package_skill(skill_dir, tmp_path / "dist")
        assert result.name == "my-skill-3.0.0.skill"
        assert zipfile.is_zipfile(result)


# ---------------------------------------------------------------------------
# detect_type_from_path (auto-detection)
# ---------------------------------------------------------------------------


class TestDetectType:
    @pytest.mark.parametrize(
        "type_key,dir_name",
        [(k, t.dir_name) for k, t in TYPES.items()],
    )
    def test_detect_all_types(self, type_key: str, dir_name: str) -> None:
        """Detect type from a path under the repo's type directory."""
        from scripts.package_types import REPO_ROOT

        pkg_path = REPO_ROOT / dir_name / "some-pkg"
        detected = detect_type_from_path(pkg_path)
        assert detected.key == type_key

    def test_unknown_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Cannot detect package type"):
            detect_type_from_path(tmp_path / "random" / "pkg")
