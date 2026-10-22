"""Tests for scripts/install.py (package installer)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from rich.prompt import Prompt

from scripts.install import (
    BODY_ONLY_TYPES,
    InstallAction,
    InstallInputError,
    InstallPlan,
    PackageInfo,
    build_install_plans,
    copy_package,
    discover_packages,
    filter_by_profile,
    get_installed_version,
    install_body_only,
    install_utility,
    is_newer,
    parse_selection,
    parse_version,
    resolve_preset_packages,
    resolve_profile_packages,
)
from scripts.package_types import (
    TYPES,
    PackageType,
    UnsupportedInstallError,
    should_exclude,
)


def _skill_type() -> PackageType:
    return TYPES["skill"]


def _agent_type() -> PackageType:
    return TYPES["agent"]


def _rule_type() -> PackageType:
    return TYPES["rule"]


def _command_type() -> PackageType:
    return TYPES["command"]


def _utility_type() -> PackageType:
    return TYPES["utility"]


class TestParseVersion:
    """Tests for semver parsing."""

    def test_valid_version(self) -> None:
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_zero_version(self) -> None:
        assert parse_version("0.0.0") == (0, 0, 0)

    def test_large_numbers(self) -> None:
        assert parse_version("10.20.30") == (10, 20, 30)

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError):
            parse_version("1.0")


class TestIsNewer:
    """Tests for version comparison."""

    def test_newer_major(self) -> None:
        assert is_newer("2.0.0", "1.0.0") is True

    def test_newer_minor(self) -> None:
        assert is_newer("1.1.0", "1.0.0") is True

    def test_newer_patch(self) -> None:
        assert is_newer("1.0.1", "1.0.0") is True

    def test_same_version(self) -> None:
        assert is_newer("1.0.0", "1.0.0") is False

    def test_older_version(self) -> None:
        assert is_newer("1.0.0", "2.0.0") is False


class TestExtractVersion:
    """Tests for version extraction from frontmatter (via shared module)."""

    def test_metadata_version(self) -> None:
        from scripts.frontmatter import extract_version
        assert extract_version({"metadata": {"version": "2.0.0"}}) == "2.0.0"

    def test_legacy_top_level(self) -> None:
        from scripts.frontmatter import extract_version
        assert extract_version({"version": "1.0.0"}) == "1.0.0"

    def test_metadata_takes_precedence(self) -> None:
        from scripts.frontmatter import extract_version
        assert extract_version({"version": "1.0.0", "metadata": {"version": "2.0.0"}}) == "2.0.0"

    def test_no_version_returns_empty(self) -> None:
        from scripts.frontmatter import extract_version
        assert extract_version({}) == ""


class TestParseSelection:
    """Tests for user input parsing."""

    def test_single_number(self) -> None:
        assert parse_selection("3", 10) == [2]

    def test_comma_separated(self) -> None:
        assert parse_selection("1,3,5", 10) == [0, 2, 4]

    def test_range(self) -> None:
        assert parse_selection("2-5", 10) == [1, 2, 3, 4]

    def test_mixed(self) -> None:
        assert parse_selection("1,3-5,8", 10) == [0, 2, 3, 4, 7]

    def test_all(self) -> None:
        assert parse_selection("all", 5) == [0, 1, 2, 3, 4]

    def test_quit(self) -> None:
        assert parse_selection("q", 10) == []

    def test_out_of_bounds(self) -> None:
        with pytest.raises(ValueError, match="out of bounds"):
            parse_selection("11", 10)

    def test_invalid_range(self) -> None:
        with pytest.raises(ValueError, match="out of bounds"):
            parse_selection("0-5", 10)

    def test_deduplication(self) -> None:
        assert parse_selection("1,1,1", 10) == [0]


class TestShouldExclude:
    """Tests for file exclusion during copy."""

    def test_pycache_excluded(self, tmp_path: Path) -> None:
        path = tmp_path / "__pycache__" / "mod.pyc"
        assert should_exclude(path, tmp_path) is True

    def test_ds_store_excluded(self, tmp_path: Path) -> None:
        path = tmp_path / ".DS_Store"
        assert should_exclude(path, tmp_path) is True

    def test_normal_file_included(self, tmp_path: Path) -> None:
        path = tmp_path / "SKILL.md"
        assert should_exclude(path, tmp_path) is False

    def test_evals_excluded(self, tmp_path: Path) -> None:
        path = tmp_path / "evals" / "test.json"
        assert should_exclude(path, tmp_path) is True


class TestGetInstalledVersion:
    """Tests for detecting installed package versions."""

    def test_not_installed(self, tmp_path: Path) -> None:
        assert get_installed_version(tmp_path, "missing-skill", _skill_type()) is None

    def test_installed_with_version(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: test\nmetadata:\n  version: 1.2.3\n---\n"
        )
        assert get_installed_version(tmp_path, "test-skill", _skill_type()) == "1.2.3"

    def test_installed_with_legacy_version(self, tmp_path: Path) -> None:
        """Legacy top-level version still detected."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\nversion: 1.2.3\ndescription: test\n---\n"
        )
        assert get_installed_version(tmp_path, "test-skill", _skill_type()) == "1.2.3"

    def test_installed_without_version(self, tmp_path: Path) -> None:
        """Missing version field treated as 0.0.0."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: test\n---\n"
        )
        assert get_installed_version(tmp_path, "test-skill", _skill_type()) == "0.0.0"

    def test_installed_with_bad_frontmatter(self, tmp_path: Path) -> None:
        """Invalid frontmatter treated as 0.0.0."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# No frontmatter\nJust content.")
        assert get_installed_version(tmp_path, "test-skill", _skill_type()) == "0.0.0"

    def test_rule_body_only_not_installed(self, tmp_path: Path) -> None:
        assert get_installed_version(tmp_path, "my-rule", _rule_type()) is None

    def test_rule_body_only_installed(self, tmp_path: Path) -> None:
        """Rules are installed as single .md files."""
        (tmp_path / "my-rule.md").write_text(
            "---\nname: my-rule\nmetadata:\n  version: 1.0.0\n---\nBody content."
        )
        assert get_installed_version(tmp_path, "my-rule", _rule_type()) == "1.0.0"

    def test_agent_installed(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "my-agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\nname: my-agent\ndescription: test\nmetadata:\n  version: 2.0.0\n---\n"
        )
        assert get_installed_version(tmp_path, "my-agent", _agent_type()) == "2.0.0"


class TestBuildInstallPlans:
    """Tests for install plan generation."""

    def _make_pkg(
        self, name: str, version: str, tmp_path: Path,
        pkg_type: PackageType | None = None,
    ) -> PackageInfo:
        pt = pkg_type or _skill_type()
        source = tmp_path / "repo" / name
        source.mkdir(parents=True, exist_ok=True)
        return PackageInfo(
            name=name, version=version, description="",
            source_path=source, pkg_type=pt,
        )

    def test_new_install(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / "claude"
        (claude_dir / "skills").mkdir(parents=True)
        pkgs = [self._make_pkg("new-skill", "1.0.0", tmp_path)]
        plans = build_install_plans(pkgs, claude_dir)
        assert len(plans) == 1
        assert plans[0].action == InstallAction.INSTALL
        assert plans[0].installed_version is None

    def test_upgrade(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / "claude"
        skill_dir = claude_dir / "skills" / "old-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: old-skill\ndescription: test\nmetadata:\n  version: 0.9.0\n---\n"
        )
        pkgs = [self._make_pkg("old-skill", "1.0.0", tmp_path)]
        plans = build_install_plans(pkgs, claude_dir)
        assert plans[0].action == InstallAction.UPGRADE
        assert plans[0].installed_version == "0.9.0"

    def test_skip_same_version(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / "claude"
        skill_dir = claude_dir / "skills" / "current-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: current-skill\ndescription: test\nmetadata:\n  version: 1.0.0\n---\n"
        )
        pkgs = [self._make_pkg("current-skill", "1.0.0", tmp_path)]
        plans = build_install_plans(pkgs, claude_dir)
        assert plans[0].action == InstallAction.SKIP

    def test_reinstall_same_version(self, tmp_path: Path) -> None:
        """With reinstall=True, same-version packages get REINSTALL action."""
        claude_dir = tmp_path / "claude"
        skill_dir = claude_dir / "skills" / "current-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: current-skill\ndescription: test\nmetadata:\n  version: 1.0.0\n---\n"
        )
        pkgs = [self._make_pkg("current-skill", "1.0.0", tmp_path)]
        plans = build_install_plans(pkgs, claude_dir, reinstall=True)
        assert plans[0].action == InstallAction.REINSTALL
        assert plans[0].installed_version == "1.0.0"

    def test_reinstall_does_not_affect_new_installs(self, tmp_path: Path) -> None:
        """New packages stay as INSTALL even with reinstall=True."""
        claude_dir = tmp_path / "claude"
        (claude_dir / "skills").mkdir(parents=True)
        pkgs = [self._make_pkg("brand-new", "1.0.0", tmp_path)]
        plans = build_install_plans(pkgs, claude_dir, reinstall=True)
        assert plans[0].action == InstallAction.INSTALL

    def test_reinstall_does_not_affect_upgrades(self, tmp_path: Path) -> None:
        """Upgradeable packages stay as UPGRADE even with reinstall=True."""
        claude_dir = tmp_path / "claude"
        skill_dir = claude_dir / "skills" / "old-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: old-skill\ndescription: test\nmetadata:\n  version: 0.9.0\n---\n"
        )
        pkgs = [self._make_pkg("old-skill", "1.0.0", tmp_path)]
        plans = build_install_plans(pkgs, claude_dir, reinstall=True)
        assert plans[0].action == InstallAction.UPGRADE

    def test_skip_symlink(self, tmp_path: Path) -> None:
        """Symlinked packages are skipped entirely."""
        claude_dir = tmp_path / "claude"
        (claude_dir / "skills").mkdir(parents=True)
        (claude_dir / "skills" / "linked-skill").symlink_to(tmp_path)
        pkgs = [self._make_pkg("linked-skill", "1.0.0", tmp_path)]
        plans = build_install_plans(pkgs, claude_dir)
        assert len(plans) == 0

    def test_multi_type_plans(self, tmp_path: Path) -> None:
        """Plans span multiple package types."""
        claude_dir = tmp_path / "claude"
        (claude_dir / "skills").mkdir(parents=True)
        (claude_dir / "agents").mkdir(parents=True)
        pkgs = [
            self._make_pkg("my-skill", "1.0.0", tmp_path, _skill_type()),
            self._make_pkg("my-agent", "1.0.0", tmp_path, _agent_type()),
        ]
        plans = build_install_plans(pkgs, claude_dir)
        assert len(plans) == 2
        assert plans[0].target_path == claude_dir / "skills" / "my-skill"
        assert plans[1].target_path == claude_dir / "agents" / "my-agent"

    def test_rule_target_is_file(self, tmp_path: Path) -> None:
        """Rule packages target a .md file, not a directory."""
        claude_dir = tmp_path / "claude"
        (claude_dir / "rules").mkdir(parents=True)
        pkgs = [self._make_pkg("my-rule", "1.0.0", tmp_path, _rule_type())]
        plans = build_install_plans(pkgs, claude_dir)
        assert plans[0].target_path == claude_dir / "rules" / "my-rule.md"


class TestCopyPackage:
    """Tests for package copying."""

    def test_copies_files(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        (source / "SKILL.md").write_text("---\nname: test\ndescription: t\nmetadata:\n  version: 1.0.0\n---\n")
        (source / "refs").mkdir()
        (source / "refs" / "data.txt").write_text("data")

        target = tmp_path / "target"
        count = copy_package(source, target)

        assert count == 2
        assert (target / "SKILL.md").exists()
        assert (target / "refs" / "data.txt").exists()

    def test_excludes_pycache(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        (source / "SKILL.md").write_text("---\nname: test\ndescription: t\nmetadata:\n  version: 1.0.0\n---\n")
        (source / "__pycache__").mkdir()
        (source / "__pycache__" / "mod.pyc").write_text("bytecode")

        target = tmp_path / "target"
        count = copy_package(source, target)

        assert count == 1
        assert not (target / "__pycache__").exists()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        """Upgrade scenario: existing target is removed first."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "SKILL.md").write_text("---\nname: test\ndescription: t\nmetadata:\n  version: 2.0.0\n---\n")

        target = tmp_path / "target"
        target.mkdir()
        (target / "old_file.txt").write_text("old")

        copy_package(source, target)

        assert not (target / "old_file.txt").exists()
        assert (target / "SKILL.md").exists()


class TestInstallBodyOnly:
    """Tests for body-only installation (rules, commands)."""

    def test_extracts_body(self, tmp_path: Path) -> None:
        source = tmp_path / "my-rule"
        source.mkdir()
        (source / "RULE.md").write_text(
            "---\nname: my-rule\ndescription: test\nmetadata:\n  version: 1.0.0\n---\nBody content here."
        )
        target = tmp_path / "output" / "my-rule.md"
        count = install_body_only(source, target, _rule_type())
        assert count == 1
        assert target.exists()
        assert target.read_text() == "Body content here."

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        source = tmp_path / "my-cmd"
        source.mkdir()
        (source / "COMMAND.md").write_text(
            "---\nname: my-cmd\n---\nCommand body."
        )
        target = tmp_path / "deep" / "nested" / "my-cmd.md"
        install_body_only(source, target, _command_type())
        assert target.exists()


class TestInstallUtility:
    """Tests for utility installation with chmod."""

    def test_sets_executable(self, tmp_path: Path) -> None:
        source = tmp_path / "my-util"
        source.mkdir()
        (source / "UTILITY.md").write_text(
            "---\nname: my-util\ndescription: test\nutility:\n  entry_point: run.sh\nmetadata:\n  version: 1.0.0\n---\n"
        )
        (source / "run.sh").write_text("#!/bin/bash\necho hi")

        target = tmp_path / "target"
        install_utility(source, target, _utility_type())

        ep = target / "run.sh"
        assert ep.exists()
        assert ep.stat().st_mode & 0o111  # executable bits set


class TestDiscoverPackages:
    """Tests for multi-type discovery."""

    def test_discover_from_manifest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Discovers skills and agents from manifest.yaml."""
        import scripts.install as mod

        # Create source dirs
        (tmp_path / "skills" / "s1").mkdir(parents=True)
        (tmp_path / "agents" / "a1").mkdir(parents=True)

        manifest = {
            "packages": {
                "skills": [
                    {"name": "s1", "version": "1.0.0", "description": "skill", "path": "skills/s1"},
                ],
                "agents": [
                    {"name": "a1", "version": "2.0.0", "description": "agent", "path": "agents/a1"},
                ],
            },
        }
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(yaml.dump(manifest))

        monkeypatch.setattr(mod, "MANIFEST_PATH", manifest_path)
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr("scripts.package_types.REPO_ROOT", tmp_path)

        pkgs = discover_packages()
        assert len(pkgs) == 2
        assert pkgs[0].name == "s1"
        assert pkgs[0].pkg_type.key == "skill"
        assert pkgs[1].name == "a1"
        assert pkgs[1].pkg_type.key == "agent"

    def test_discover_single_type(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Filtering to a single type returns only that type."""
        import scripts.install as mod

        (tmp_path / "skills" / "s1").mkdir(parents=True)
        (tmp_path / "agents" / "a1").mkdir(parents=True)

        manifest = {
            "packages": {
                "skills": [
                    {"name": "s1", "version": "1.0.0", "description": "skill", "path": "skills/s1"},
                ],
                "agents": [
                    {"name": "a1", "version": "2.0.0", "description": "agent", "path": "agents/a1"},
                ],
            },
        }
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(yaml.dump(manifest))

        monkeypatch.setattr(mod, "MANIFEST_PATH", manifest_path)
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr("scripts.package_types.REPO_ROOT", tmp_path)

        pkgs = discover_packages(_skill_type())
        assert len(pkgs) == 1
        assert pkgs[0].pkg_type.key == "skill"

    def test_discover_from_definition_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to scanning definition files when no manifest."""
        import scripts.install as mod
        import scripts.package_types as pt_mod

        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: a skill\nmetadata:\n  version: 1.0.0\n---\nBody."
        )

        monkeypatch.setattr(mod, "MANIFEST_PATH", tmp_path / "nonexistent.yaml")
        monkeypatch.setattr(pt_mod, "REPO_ROOT", tmp_path)

        pkgs = discover_packages(_skill_type())
        assert len(pkgs) == 1
        assert pkgs[0].name == "my-skill"

    def test_discover_handles_missing_type_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-existent type directories are skipped gracefully."""
        import scripts.install as mod
        import scripts.package_types as pt_mod

        monkeypatch.setattr(mod, "MANIFEST_PATH", tmp_path / "nonexistent.yaml")
        monkeypatch.setattr(pt_mod, "REPO_ROOT", tmp_path)

        pkgs = discover_packages()
        assert pkgs == []


class TestProfileFiltering:
    """Tests for profile-based package filtering."""

    def test_core_profile(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import scripts.install as mod

        profiles = {
            "core": {
                "description": "Essential",
                "packages": {"skills": ["pr-review", "code-refiner"]},
            },
        }
        profiles_path = tmp_path / "profiles.yaml"
        profiles_path.write_text(yaml.dump({"profiles": profiles}))
        monkeypatch.setattr(mod, "PROFILES_PATH", profiles_path)

        all_pkgs = [
            PackageInfo("pr-review", "1.0.0", "", tmp_path, _skill_type()),
            PackageInfo("code-refiner", "1.0.0", "", tmp_path, _skill_type()),
            PackageInfo("other-skill", "1.0.0", "", tmp_path, _skill_type()),
        ]
        filtered = filter_by_profile(all_pkgs, "core")
        assert len(filtered) == 2
        assert {p.name for p in filtered} == {"pr-review", "code-refiner"}

    def test_profile_with_includes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import scripts.install as mod

        profiles = {
            "core": {
                "packages": {"skills": ["pr-review"]},
            },
            "developer": {
                "includes": ["core"],
                "packages": {"skills": ["test-harness"]},
            },
        }
        profiles_path = tmp_path / "profiles.yaml"
        profiles_path.write_text(yaml.dump({"profiles": profiles}))
        monkeypatch.setattr(mod, "PROFILES_PATH", profiles_path)

        all_pkgs = [
            PackageInfo("pr-review", "1.0.0", "", tmp_path, _skill_type()),
            PackageInfo("test-harness", "1.0.0", "", tmp_path, _skill_type()),
            PackageInfo("other", "1.0.0", "", tmp_path, _skill_type()),
        ]
        filtered = filter_by_profile(all_pkgs, "developer")
        assert len(filtered) == 2
        assert {p.name for p in filtered} == {"pr-review", "test-harness"}

    def test_full_profile_returns_all(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import scripts.install as mod

        profiles = {
            "full": {"description": "Everything", "all": True},
        }
        profiles_path = tmp_path / "profiles.yaml"
        profiles_path.write_text(yaml.dump({"profiles": profiles}))
        monkeypatch.setattr(mod, "PROFILES_PATH", profiles_path)

        all_pkgs = [
            PackageInfo("pr-review", "1.0.0", "", tmp_path, _skill_type()),
            PackageInfo("other", "1.0.0", "", tmp_path, _skill_type()),
        ]
        filtered = filter_by_profile(all_pkgs, "full")
        assert len(filtered) == 2

    def test_unknown_profile_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import scripts.install as mod

        profiles_path = tmp_path / "profiles.yaml"
        profiles_path.write_text(yaml.dump({"profiles": {}}))
        monkeypatch.setattr(mod, "PROFILES_PATH", profiles_path)

        with pytest.raises(ValueError, match="Unknown profile"):
            filter_by_profile([], "nonexistent")

    def test_profile_multi_type(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Profile can span multiple package types."""
        import scripts.install as mod

        profiles = {
            "mixed": {
                "packages": {
                    "skills": ["my-skill"],
                    "agents": ["my-agent"],
                },
            },
        }
        profiles_path = tmp_path / "profiles.yaml"
        profiles_path.write_text(yaml.dump({"profiles": profiles}))
        monkeypatch.setattr(mod, "PROFILES_PATH", profiles_path)

        all_pkgs = [
            PackageInfo("my-skill", "1.0.0", "", tmp_path, _skill_type()),
            PackageInfo("my-agent", "1.0.0", "", tmp_path, _agent_type()),
            PackageInfo("extra", "1.0.0", "", tmp_path, _skill_type()),
        ]
        filtered = filter_by_profile(all_pkgs, "mixed")
        assert len(filtered) == 2
        assert {p.name for p in filtered} == {"my-skill", "my-agent"}


class TestResolveProfilePackages:
    """Tests for profile resolution internals."""

    def test_circular_includes_safe(self) -> None:
        """Circular includes do not infinite-loop."""
        profiles = {
            "a": {"includes": ["b"], "packages": {"skills": ["s1"]}},
            "b": {"includes": ["a"], "packages": {"skills": ["s2"]}},
        }
        result = resolve_profile_packages("a", profiles)
        assert "skill" in result
        assert "s1" in result["skill"]
        assert "s2" in result["skill"]

    def test_include_all_propagates(self) -> None:
        """Including an 'all: true' profile propagates to parent."""
        profiles = {
            "full": {"all": True},
            "extended": {"includes": ["full"], "packages": {"skills": ["extra"]}},
        }
        result = resolve_profile_packages("extended", profiles)
        # Empty dict signals "all"
        assert result == {}


def _point_at_repo(mod: ModuleType, monkeypatch: pytest.MonkeyPatch, root: Path, manifest: object | None) -> None:
    manifest_path = root / "manifest.yaml"
    if manifest is not None:
        manifest_path.write_text(manifest if isinstance(manifest, str) else yaml.dump(manifest))
    monkeypatch.setattr(mod, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(mod, "REPO_ROOT", root)
    monkeypatch.setattr("scripts.package_types.REPO_ROOT", root)


class TestInvalidDeclarations:
    """Invalid package declarations fail loudly instead of being dropped."""

    @pytest.mark.parametrize(
        "manifest",
        [
            {},
            [],
            "just a string",
            {"packages": []},
            {"packages": {"skills": "nope"}},
            {"packages": {"skills": ["nope"]}},
            {"packages": {"skills": [{"path": "skills/s1"}]}},
            {"packages": {"skills": [{"name": "s1"}]}},
            {"packages": {"skills": [{"name": "s1", "path": "skills/s1", "version": "1.2.3\n"}]}},
            {"packages": {"skills": [{"name": "s1", "path": "skills/s1", "description": None}]}},
            {"packages": {"skills": [{"name": "s1", "path": "skills/s1", "version": 1.5}]}},
            "packages: [unclosed",
        ],
    )
    def test_malformed_manifest_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: object,
    ) -> None:
        import scripts.install as mod

        (tmp_path / "skills" / "s1").mkdir(parents=True)
        _point_at_repo(mod, monkeypatch, tmp_path, manifest)
        with pytest.raises(ValueError, match="manifest.yaml"):
            discover_packages()

    def test_missing_declared_directory_names_package_and_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import scripts.install as mod

        _point_at_repo(mod, monkeypatch, tmp_path, {
            "packages": {"skills": [{"name": "ghost", "path": "skills/ghost"}]},
        })
        with pytest.raises(ValueError, match="ghost") as info:
            discover_packages()
        assert "skills/ghost" in str(info.value)

    @pytest.mark.parametrize(
        "content",
        ["", "---\n---\nBody", "---\n- a\n- b\n---\nBody", "---\njust text\n---\nBody",
         "---\nname: [unclosed\n---\nBody", "---\ndescription: no name\n---\nBody",
         "---\nname: [a, b]\n---\nBody"],
    )
    def test_fallback_invalid_definition_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str,
    ) -> None:
        import scripts.install as mod

        skill_dir = tmp_path / "skills" / "bad"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(content)
        _point_at_repo(mod, monkeypatch, tmp_path, None)
        with pytest.raises(ValueError, match="SKILL.md"):
            discover_packages()

    def test_fallback_ignores_non_package_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import scripts.install as mod

        (tmp_path / "skills" / "no-definition").mkdir(parents=True)
        (tmp_path / "skills" / "README.txt").write_text("not a package")
        _point_at_repo(mod, monkeypatch, tmp_path, None)
        assert discover_packages() == []

    def test_unresolved_profile_package_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import scripts.install as mod

        profiles_path = tmp_path / "profiles.yaml"
        profiles_path.write_text(yaml.dump({"profiles": {"p": {"packages": {"skills": ["missing"]}}}}))
        monkeypatch.setattr(mod, "PROFILES_PATH", profiles_path)
        pkgs = [PackageInfo("present", "1.0.0", "", tmp_path, _skill_type())]
        with pytest.raises(ValueError, match="missing"):
            filter_by_profile(pkgs, "p")

    def test_unknown_profile_section_raises(self) -> None:
        profiles = {"p": {"packages": {"widgets": ["w"]}}}
        with pytest.raises(ValueError, match="widgets"):
            resolve_profile_packages("p", profiles)


class TestMainValidation:
    """main() resolves profiles across types and fails before mutating anything."""

    def _run(self, mod: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str]) -> tuple[int, Path]:
        claude_dir = tmp_path / "claude-home"
        monkeypatch.setattr(mod, "DEFAULT_CLAUDE_DIR", claude_dir)
        monkeypatch.setattr("sys.argv", ["install.py", *argv])
        return mod.main(), claude_dir

    def test_invalid_selection_returns_nonzero_without_mutation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        import scripts.install as mod

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "skills" / "valid").mkdir(parents=True)
        _point_at_repo(mod, monkeypatch, repo, {
            "packages": {"skills": [
                {"name": "valid", "path": "skills/valid"},
                {"name": "[red]ghost", "path": "skills/ghost"},
            ]},
        })
        code, claude_dir = self._run(mod, monkeypatch, tmp_path, [])
        assert code != 0
        assert not claude_dir.exists()
        assert "[red]ghost" in capsys.readouterr().out

    def test_unresolved_profile_returns_nonzero_without_mutation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import scripts.install as mod

        repo = tmp_path / "repo"
        (repo / "skills" / "s1").mkdir(parents=True)
        _point_at_repo(mod, monkeypatch, repo, {
            "packages": {"skills": [{"name": "s1", "path": "skills/s1"}]},
        })
        profiles_path = repo / "profiles.yaml"
        profiles_path.write_text(yaml.dump({"profiles": {"p": {"packages": {"skills": ["nope"]}}}}))
        monkeypatch.setattr(mod, "PROFILES_PATH", profiles_path)
        code, claude_dir = self._run(mod, monkeypatch, tmp_path, ["--profile", "p"])
        assert code != 0
        assert not claude_dir.exists()

    @pytest.mark.parametrize("entrypoint", ["cli", "library"])
    def test_preset_discovery_failure_does_not_copy_the_preset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entrypoint: str,
    ) -> None:
        import scripts.install as mod

        repo = tmp_path / "repo"
        preset = repo / "presets" / "bundle"
        preset.mkdir(parents=True)
        (preset / "PRESET.md").write_text(
            "---\nname: bundle\nmetadata:\n  version: 1.0.0\npreset:\n"
            "  packages:\n    skills:\n      - name: ghost\n---\nBundle.\n"
        )
        _point_at_repo(mod, monkeypatch, repo, {
            "packages": {
                "presets": [{"name": "bundle", "path": "presets/bundle", "version": "1.0.0"}],
                "skills": [{"name": "ghost", "path": "skills/ghost", "version": "1.0.0"}],
            },
        })
        if entrypoint == "cli":
            code, destination = self._run(mod, monkeypatch, tmp_path, ["--type", "preset"])
            assert code == 1
        else:
            destination = tmp_path / "claude-home"
            pkg = PackageInfo("bundle", "1.0.0", "", preset, TYPES["preset"])
            plan = InstallPlan(pkg, InstallAction.INSTALL, None, destination / "presets" / "bundle")
            with pytest.raises(mod.InstallInputError):
                mod.install_preset(plan, destination)
        assert not destination.exists()

    @pytest.mark.parametrize(
        ("platform", "retained_path"),
        [
            ("cursor", ".cursor/rules/existing.mdc"),
            ("gemini", ".gemini/skills/existing/SKILL.md"),
            ("codex", "AGENTS.md"),
        ],
    )
    def test_invalid_adapter_definition_preserves_installed_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        platform: str, retained_path: str,
    ) -> None:
        import scripts.generate_adapters as adapters
        import scripts.install as mod

        repo = tmp_path / "repo"
        for name, content in (
            ("good", "---\nname: good\ndescription: Good skill\n---\nBody.\n"),
            ("bad", "---\n- not-a-mapping\n---\nBody.\n"),
        ):
            skill = repo / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(content)
        monkeypatch.setattr("scripts.package_types.REPO_ROOT", repo)
        monkeypatch.setattr(adapters, "REPO_ROOT", repo)
        project = tmp_path / "project"
        retained = project / retained_path
        retained.parent.mkdir(parents=True)
        retained.write_bytes(b"retained user content\n")
        code, _ = self._run(
            mod, monkeypatch, tmp_path,
            ["--target", platform, "--project-dir", str(project)],
        )
        assert code == 1
        assert {
            p.relative_to(project).as_posix(): p.read_bytes()
            for p in project.rglob("*") if p.is_file()
        } == {retained_path: b"retained user content\n"}

    def test_mixed_profile_with_type_filter_selects_that_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import scripts.install as mod

        repo = tmp_path / "repo"
        (repo / "skills" / "s1").mkdir(parents=True)
        (repo / "agents" / "a1").mkdir(parents=True)
        skill_content = "---\nname: s1\nmetadata:\n  version: 1.0.0\n---\nSkill body.\n"
        (repo / "skills" / "s1" / "SKILL.md").write_text(skill_content)
        (repo / "agents" / "a1" / "AGENT.md").write_text("---\nname: a1\n---\nAgent body.\n")
        _point_at_repo(mod, monkeypatch, repo, {
            "packages": {
                "skills": [{"name": "s1", "path": "skills/s1", "version": "1.0.0"}],
                "agents": [{"name": "a1", "path": "agents/a1", "version": "1.0.0"}],
            },
        })
        profiles_path = repo / "profiles.yaml"
        profiles_path.write_text(yaml.dump({"profiles": {
            "mixed": {"packages": {"skills": ["s1"], "agents": ["a1"]}},
        }}))
        monkeypatch.setattr(mod, "PROFILES_PATH", profiles_path)

        answers = iter(["all", "y"])
        monkeypatch.setattr(mod.Prompt, "ask", lambda *args, **kwargs: next(answers))
        code, claude_dir = self._run(
            mod, monkeypatch, tmp_path, ["--profile", "mixed", "--type", "skill"]
        )
        assert code == 0
        assert (claude_dir / "skills" / "s1" / "SKILL.md").read_text() == skill_content
        assert not (claude_dir / "agents").exists()


class TestNativeExtensionsStayExplicit:
    """Native extensions never ride along with interactive, profile, preset or all installs."""

    def _native_package(self, root: Path) -> PackageInfo:
        source = root / "extensions" / "native-demo"
        source.mkdir(parents=True)
        (source / "EXTENSION.md").write_text("---\nname: native-demo\n---\n")
        return PackageInfo("native-demo", "1.0.0", "", source, TYPES["extension"])

    def test_all_selection_installs_legacy_packages_but_not_native_extensions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import scripts.install as mod

        repo = tmp_path / "repo"
        skill = repo / "skills" / "demo-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo-skill\nmetadata:\n  version: 1.0.0\n---\nBody\n")
        self._native_package(repo)
        _point_at_repo(mod, monkeypatch, repo, {
            "packages": {
                "skills": [{"name": "demo-skill", "version": "1.0.0", "path": "skills/demo-skill"}],
                "extensions": [{"name": "native-demo", "version": "1.0.0", "path": "extensions/native-demo"}],
            },
        })
        answers = iter(["all", "y"])
        monkeypatch.setattr(Prompt, "ask", lambda *_args, **_kwargs: next(answers))
        claude_dir = tmp_path / "claude-home"
        monkeypatch.setattr(mod, "DEFAULT_CLAUDE_DIR", claude_dir)
        monkeypatch.setattr("sys.argv", ["install.py"])

        assert mod.main() == 0
        assert (claude_dir / "skills" / "demo-skill" / "SKILL.md").is_file()
        assert sorted(entry.name for entry in claude_dir.iterdir()) == ["skills"]

    def test_profile_with_native_section_is_rejected(self) -> None:
        profiles = {"p": {"packages": {"extensions": ["native-demo"]}}}
        with pytest.raises(InstallInputError, match="profiles cannot include native extensions"):
            resolve_profile_packages("p", profiles)

    def test_preset_bundling_native_extension_is_rejected(self, tmp_path: Path) -> None:
        preset = tmp_path / "bundle"
        preset.mkdir()
        (preset / "PRESET.md").write_text(
            "---\nname: bundle\npreset:\n  packages:\n    extensions:\n      - name: native-demo\n---\n"
        )
        with pytest.raises(InstallInputError, match="presets cannot bundle native extensions"):
            resolve_preset_packages(preset, TYPES["preset"])

    def test_copy_install_plan_refuses_native_package(self, tmp_path: Path) -> None:
        native = self._native_package(tmp_path / "repo")
        claude_dir = tmp_path / "claude-home"
        with pytest.raises(UnsupportedInstallError):
            build_install_plans([native], claude_dir)
        assert not claude_dir.exists()

    @pytest.mark.parametrize(
        ("argv", "message"),
        [
            (["--type", "extension", "--platform", "omp", "--name", "x", "--action", "install",
              "--target-root", "ROOT"], "requires --yes"),
            (["--type", "extension", "--yes"], "requires --platform, --name, --action, --target-root"),
            (["--platform", "omp"], "--platform apply only to --type extension"),
            (["--type", "skill", "--action", "remove", "--yes"], "--action, --yes apply only to --type extension"),
            (["--type", "extension", "--platform", "claude", "--name", "x", "--action", "remove",
              "--target-root", "ROOT", "--yes", "--profile", "core"], "--profile cannot be combined"),
            (["--type", "extension", "--platform", "claude", "--name", "x", "--action", "remove",
              "--target-root", "ROOT", "--yes", "--target", "cursor"], "--target cannot be combined"),
            (["--type", "extension", "--platform", "cursor"], "invalid choice: 'cursor'"),
            (["--type", "extension", "--action", "enable"], "invalid choice: 'enable'"),
        ],
    )
    def test_extension_cli_requires_explicit_complete_flags(
        self, argv: list[str], message: str, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        import scripts.install as mod

        monkeypatch.setattr("sys.argv", ["install.py", *[str(tmp_path) if a == "ROOT" else a for a in argv]])
        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 2
        assert message in capsys.readouterr().err
        assert list(tmp_path.iterdir()) == []

    def test_extension_cli_does_not_install_unregistered_fixture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import scripts.install as mod

        monkeypatch.setattr("sys.argv", [
            "install.py", "--type", "extension", "--platform", "omp", "--name", "fixture-wordcount",
            "--action", "install", "--target-root", str(tmp_path), "--yes",
        ])
        assert mod.main() == 1
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mode", ["legacy", "native-unsupported"])
def test_native_platform_dependency_is_isolated_from_legacy_installation(
    mode: str, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    definition = b"---\nname: fictional-legacy\nmetadata:\n  version: 1.0.0\n---\nLegacy body.\n"
    (source / "SKILL.md").write_bytes(definition)
    (source / "references").mkdir()
    reference = b"SYNTHETIC_REFERENCE\n"
    (source / "references" / "context.md").write_bytes(reference)
    target = tmp_path / "target"
    target.mkdir()
    foreign = b'{"foreign":"keep exact bytes"}\n'
    (target / "settings.json").write_bytes(foreign)
    child = """
import argparse
import builtins
import os
from pathlib import Path
import sys

original_import = builtins.__import__
def without_native_locking(name, *args, **kwargs):
    if name == "fcntl":
        raise ModuleNotFoundError("synthetic unavailable POSIX locking", name="fcntl")
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_native_locking
sys.path.insert(0, sys.argv[1])
from scripts.install import PackageInfo, build_install_plans, execute_plans, run_extension_action
from scripts.package_types import TYPES
source, target = Path(sys.argv[2]), Path(sys.argv[3])
if sys.argv[4] == "legacy":
    package = PackageInfo("fictional-legacy", "1.0.0", "Synthetic package", source, TYPES["skill"])
    execute_plans(build_install_plans([package], target), [0], target)
else:
    original_name = os.name
    os.name = "unsupported-platform"
    try:
        result = run_extension_action(argparse.Namespace(
            action="install", platform="omp", name="fictional-native", target_root=target
        ))
    finally:
        os.name = original_name
    if result != 1:
        raise AssertionError("unsupported native installation did not fail")
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(Path(__file__).resolve().parents[1]),
         str(source), str(target), mode],
        text=True, capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "settings.json").read_bytes() == foreign
    if mode == "legacy":
        installed = target / "skills" / "fictional-legacy"
        assert (installed / "SKILL.md").read_bytes() == definition
        assert (installed / "references" / "context.md").read_bytes() == reference
    else:
        assert sorted(path.name for path in target.iterdir()) == ["settings.json"]
