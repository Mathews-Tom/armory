"""Tests for scripts/generate_manifest.py."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from scripts.frontmatter import parse_frontmatter
from scripts.generate_manifest import (
    collect_packages,
    enforce_bidirectional_complements,
    resolve_repo,
    write_manifest,
)
from scripts.package_types import TYPES


class TestParseFrontmatter:
    """Tests for frontmatter extraction (shared module)."""

    def test_extracts_all_fields(self) -> None:
        content = "---\nname: my-skill\ndescription: Does things.\nmetadata:\n  version: 1.2.3\n---\n# Body"
        meta = parse_frontmatter(content)
        assert meta["name"] == "my-skill"
        assert meta["metadata"]["version"] == "1.2.3"
        assert meta["description"] == "Does things."

    def test_raises_on_missing_frontmatter(self) -> None:
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

        with patch("subprocess.check_output", side_effect=sp.CalledProcessError(1, "git")):
            with pytest.raises(SystemExit):
                resolve_repo(None)


class TestCollectPackages:
    """Tests for package collection from definition files."""

    def test_includes_source_url(self) -> None:
        """Verify source URLs are generated for each skill."""
        entries = collect_packages(TYPES["skill"], "Mathews-Tom/armory")
        for entry in entries:
            source = str(entry["source"])
            assert source.startswith("https://github.com/Mathews-Tom/armory/blob/main/skills/")
            assert source.endswith("/SKILL.md")

    def test_returns_empty_for_nonexistent_dir(self) -> None:
        """collect_packages returns [] when the type directory doesn't exist."""
        from scripts.package_types import PackageType

        fake_type = PackageType(
            key="fake",
            dir_name="nonexistent_type_dir",
            definition_file="FAKE.md",
            claude_subdir="fake",
            archive_ext=".fake",
            required_frontmatter=("name", "description"),
            manifest_section="fakes",
        )
        entries = collect_packages(fake_type, "Mathews-Tom/armory")
        assert entries == []

    def test_collects_from_synthetic_type(self, tmp_path: Path) -> None:
        """Verify collect_packages works for non-skill types using a temp dir."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_dir = agents_dir / "test-agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\nname: test-agent\ndescription: A test agent.\n"
            "model: gpt-4.1\ncategory: coding\nexecution_phase: plan\n"
            "metadata:\n  version: 0.1.0\n---\n# Body\n"
        )

        from scripts.package_types import PackageType

        fake_type = PackageType(
            key="agent",
            dir_name="agents",
            definition_file="AGENT.md",
            claude_subdir="agents",
            archive_ext=".agent",
            required_frontmatter=("name", "description", "model", "color"),
            manifest_section="agents",
        )

        with (
            patch.object(type(fake_type), "repo_dir", new_callable=lambda: property(lambda self: agents_dir)),
            patch("scripts.generate_manifest.REPO_ROOT", tmp_path),
        ):
            entries = collect_packages(fake_type, "test/repo")

        assert len(entries) == 1
        assert entries[0]["name"] == "test-agent"
        assert entries[0]["model"] == "gpt-4.1"
        assert entries[0]["category"] == "coding"
        assert entries[0]["execution_phase"] == "plan"
        assert entries[0]["path"] == "agents/test-agent"
        assert entries[0]["source"] == "https://github.com/test/repo/blob/main/agents/test-agent/AGENT.md"

    def test_extracts_hook_events(self, tmp_path: Path) -> None:
        """Verify hook events are extracted from frontmatter."""
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_dir = hooks_dir / "pre-commit"
        hook_dir.mkdir()
        (hook_dir / "HOOK.md").write_text(
            "---\nname: pre-commit\ndescription: Runs before commit.\n"
            "hook:\n  events:\n    - PreCommit\n    - PrePush\n"
            "metadata:\n  version: 1.0.0\n---\n# Body\n"
        )

        from scripts.package_types import PackageType

        fake_type = PackageType(
            key="hook",
            dir_name="hooks",
            definition_file="HOOK.md",
            claude_subdir="hooks",
            archive_ext=".hook",
            required_frontmatter=("name", "description", "hook"),
            manifest_section="hooks",
        )

        with (
            patch.object(type(fake_type), "repo_dir", new_callable=lambda: property(lambda self: hooks_dir)),
            patch("scripts.generate_manifest.REPO_ROOT", tmp_path),
        ):
            entries = collect_packages(fake_type, "test/repo")

        assert len(entries) == 1
        assert entries[0]["events"] == ["PreCommit", "PrePush"]

    def test_extracts_preset_package_count(self, tmp_path: Path) -> None:
        """Verify preset package_count is computed from preset.packages list."""
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        preset_dir = presets_dir / "starter"
        preset_dir.mkdir()
        (preset_dir / "PRESET.md").write_text(
            "---\nname: starter\ndescription: Starter pack.\n"
            "preset:\n  packages:\n    - skill-a\n    - skill-b\n    - agent-c\n"
            "metadata:\n  version: 1.0.0\n---\n# Body\n"
        )

        from scripts.package_types import PackageType

        fake_type = PackageType(
            key="preset",
            dir_name="presets",
            definition_file="PRESET.md",
            claude_subdir="presets",
            archive_ext=".preset",
            required_frontmatter=("name", "description", "preset"),
            manifest_section="presets",
        )

        with (
            patch.object(type(fake_type), "repo_dir", new_callable=lambda: property(lambda self: presets_dir)),
            patch("scripts.generate_manifest.REPO_ROOT", tmp_path),
        ):
            entries = collect_packages(fake_type, "test/repo")

        assert len(entries) == 1
        assert entries[0]["package_count"] == 3

    def test_skips_entries_missing_name(self, tmp_path: Path) -> None:
        """Entries without a name field are skipped."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "broken"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: No name.\nmetadata:\n  version: 1.0.0\n---\n# Body\n"
        )

        from scripts.package_types import PackageType

        fake_type = PackageType(
            key="skill",
            dir_name="skills",
            definition_file="SKILL.md",
            claude_subdir="skills",
            archive_ext=".skill",
            required_frontmatter=("name", "description"),
            manifest_section="skills",
        )

        with (
            patch.object(type(fake_type), "repo_dir", new_callable=lambda: property(lambda self: skills_dir)),
            patch("scripts.generate_manifest.REPO_ROOT", tmp_path),
        ):
            entries = collect_packages(fake_type, "test/repo")

        assert entries == []


class TestBidirectionalComplements:
    """Tests for bidirectional complements enforcement."""

    def test_mirrors_complement(self) -> None:
        entries: list[dict[str, Any]] = [
            {"name": "skill-a", "complements": ["skill-b"]},
            {"name": "skill-b"},
        ]
        enforce_bidirectional_complements(entries)
        assert "skill-a" in entries[1]["complements"]

    def test_no_duplicate_on_existing(self) -> None:
        entries: list[dict[str, Any]] = [
            {"name": "skill-a", "complements": ["skill-b"]},
            {"name": "skill-b", "complements": ["skill-a"]},
        ]
        enforce_bidirectional_complements(entries)
        assert entries[1]["complements"] == ["skill-a"]

    def test_ignores_nonexistent_peer(self) -> None:
        entries: list[dict[str, Any]] = [
            {"name": "skill-a", "complements": ["nonexistent"]},
        ]
        enforce_bidirectional_complements(entries)
        assert len(entries) == 1

    def test_mutual_mirroring(self) -> None:
        entries: list[dict[str, Any]] = [
            {"name": "a", "complements": ["b"]},
            {"name": "b", "complements": ["c"]},
            {"name": "c"},
        ]
        enforce_bidirectional_complements(entries)
        assert "a" in entries[1]["complements"]
        assert "b" in entries[2]["complements"]


class TestWriteManifest:
    """Tests for manifest file generation."""

    def test_writes_valid_yaml(self, tmp_path: Path) -> None:
        all_packages: dict[str, list[dict[str, Any]]] = {
            "skills": [
                {
                    "name": "test-skill",
                    "version": "1.0.0",
                    "description": "A test skill.",
                    "path": "skills/test-skill",
                    "source": "https://github.com/test/repo/blob/main/skills/test-skill/SKILL.md",
                }
            ]
        }

        import scripts.generate_manifest as gm
        import scripts.package_types as pt

        orig_manifest = pt.MANIFEST_PATH
        pt.MANIFEST_PATH = tmp_path / "manifest.yaml"
        gm_orig_manifest = gm.MANIFEST_PATH
        gm.MANIFEST_PATH = pt.MANIFEST_PATH

        try:
            write_manifest(all_packages)

            manifest_content = pt.MANIFEST_PATH.read_text()
            assert "Auto-generated" in manifest_content
            manifest_data = yaml.safe_load(manifest_content)
            assert len(manifest_data["packages"]["skills"]) == 1
            assert manifest_data["packages"]["skills"][0]["name"] == "test-skill"
        finally:
            pt.MANIFEST_PATH = orig_manifest
            gm.MANIFEST_PATH = gm_orig_manifest

    def test_writes_multiple_types(self, tmp_path: Path) -> None:
        all_packages: dict[str, list[dict[str, Any]]] = {
            "skills": [{"name": "s1", "version": "1.0.0", "description": "Skill."}],
            "agents": [{"name": "a1", "version": "0.1.0", "description": "Agent.", "model": "gpt-4.1"}],
        }

        import scripts.generate_manifest as gm
        import scripts.package_types as pt

        orig_manifest = pt.MANIFEST_PATH
        pt.MANIFEST_PATH = tmp_path / "manifest.yaml"
        gm.MANIFEST_PATH = pt.MANIFEST_PATH

        try:
            write_manifest(all_packages)

            data = yaml.safe_load(pt.MANIFEST_PATH.read_text())
            assert "skills" in data["packages"]
            assert "agents" in data["packages"]
            assert data["packages"]["agents"][0]["model"] == "gpt-4.1"
        finally:
            pt.MANIFEST_PATH = orig_manifest
            gm.MANIFEST_PATH = orig_manifest
