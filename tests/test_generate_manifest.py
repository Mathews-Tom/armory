"""Tests for scripts/generate_manifest.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.generate_manifest import (
    collect_skills,
    enforce_bidirectional_complements,
    parse_frontmatter,
    resolve_repo,
    write_manifest,
)


class TestParseFrontmatter:
    """Tests for frontmatter extraction."""

    def test_extracts_all_fields(self) -> None:
        content = "---\nname: my-skill\ndescription: Does things.\nmetadata:\n  version: 1.2.3\n---\n# Body"
        meta = parse_frontmatter(content)
        assert meta["name"] == "my-skill"
        assert meta["metadata"]["version"] == "1.2.3"
        assert meta["description"] == "Does things."

    def test_raises_on_missing_frontmatter(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="No valid YAML frontmatter"):
            parse_frontmatter("# No frontmatter")


class TestResolveRepo:
    """Tests for --repo flag and git remote parsing."""

    def test_explicit_repo_flag(self) -> None:
        assert resolve_repo("Mathews-Tom/armory") == "Mathews-Tom/armory"

    def test_https_remote(self) -> None:
        with patch("subprocess.check_output", return_value="https://github.com/Mathews-Tom/armory.git\n"):
            assert resolve_repo(None) == "Mathews-Tom/armory"

    def test_https_remote_no_git_suffix(self) -> None:
        with patch("subprocess.check_output", return_value="https://github.com/org/repo\n"):
            assert resolve_repo(None) == "org/repo"

    def test_ssh_remote(self) -> None:
        with patch("subprocess.check_output", return_value="git@github.com:Mathews-Tom/armory.git\n"):
            assert resolve_repo(None) == "Mathews-Tom/armory"

    def test_ssh_remote_no_git_suffix(self) -> None:
        with patch("subprocess.check_output", return_value="git@github.com:org/repo\n"):
            assert resolve_repo(None) == "org/repo"

    def test_no_remote_fails(self) -> None:
        import subprocess as sp

        import pytest

        with patch("subprocess.check_output", side_effect=sp.CalledProcessError(1, "git")):
            with pytest.raises(SystemExit):
                resolve_repo(None)


class TestCollectSkills:
    """Tests for skill collection from SKILL.md files."""

    def test_collects_from_real_repo(self) -> None:
        """Verify collect_skills finds all skills in the actual repo."""
        entries = collect_skills("Mathews-Tom/armory")
        assert len(entries) >= 39

        names = {e["name"] for e in entries}
        assert "agent-builder" in names
        assert "tavily" in names
        assert "concept-to-video" in names
        assert "remotion-video" in names

        for entry in entries:
            assert str(entry["path"]).startswith("skills/")
            assert entry["description"]
            # Version must be valid semver (X.Y.Z)
            parts = str(entry["version"]).split(".")
            assert len(parts) == 3, f"Invalid version {entry['version']} for {entry['name']}"
            assert all(p.isdigit() for p in parts)

    def test_includes_source_url(self) -> None:
        """Verify source URLs are generated for each skill."""
        entries = collect_skills("Mathews-Tom/armory")
        for entry in entries:
            source = str(entry["source"])
            assert source.startswith("https://github.com/Mathews-Tom/armory/blob/main/skills/")
            assert source.endswith("/SKILL.md")


class TestBidirectionalComplements:
    """Tests for bidirectional complements enforcement."""

    def test_mirrors_complement(self) -> None:
        entries: list[dict[str, str | list[str]]] = [
            {"name": "skill-a", "complements": ["skill-b"]},
            {"name": "skill-b"},
        ]
        enforce_bidirectional_complements(entries)
        assert "skill-a" in entries[1]["complements"]  # type: ignore[operator]

    def test_no_duplicate_on_existing(self) -> None:
        entries: list[dict[str, str | list[str]]] = [
            {"name": "skill-a", "complements": ["skill-b"]},
            {"name": "skill-b", "complements": ["skill-a"]},
        ]
        enforce_bidirectional_complements(entries)
        assert entries[1]["complements"] == ["skill-a"]  # no duplicate

    def test_ignores_nonexistent_peer(self) -> None:
        entries: list[dict[str, str | list[str]]] = [
            {"name": "skill-a", "complements": ["nonexistent"]},
        ]
        enforce_bidirectional_complements(entries)
        # No crash, no new entries
        assert len(entries) == 1

    def test_mutual_mirroring(self) -> None:
        entries: list[dict[str, str | list[str]]] = [
            {"name": "a", "complements": ["b"]},
            {"name": "b", "complements": ["c"]},
            {"name": "c"},
        ]
        enforce_bidirectional_complements(entries)
        # a↔b, b↔c
        assert "a" in entries[1]["complements"]  # type: ignore[operator]
        assert "b" in entries[2]["complements"]  # type: ignore[operator]


class TestWriteManifest:
    """Tests for manifest file generation."""

    def test_writes_valid_yaml(self, tmp_path: Path) -> None:
        entries: list[dict[str, str | list[str]]] = [
            {
                "name": "test-skill",
                "version": "1.0.0",
                "description": "A test skill.",
                "path": "skills/test-skill",
                "source": "https://github.com/test/repo/blob/main/skills/test-skill/SKILL.md",
            }
        ]

        import scripts.generate_manifest as gm

        original = gm.MANIFEST_PATH
        gm.MANIFEST_PATH = tmp_path / "skills.yaml"

        try:
            write_manifest(entries)

            content = gm.MANIFEST_PATH.read_text()
            assert "Auto-generated" in content

            data = yaml.safe_load(content)
            assert len(data["skills"]) == 1
            assert data["skills"][0]["name"] == "test-skill"
            assert data["skills"][0]["version"] == "1.0.0"
            assert data["skills"][0]["source"].startswith("https://github.com/")
        finally:
            gm.MANIFEST_PATH = original
