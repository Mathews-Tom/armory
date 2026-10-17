"""Tests for scripts/generate_adapters.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import scripts.generate_adapters as generate_adapters
import scripts.package_types as package_types
from scripts.generate_adapters import (
    CodexAdapter,
    GeminiAdapter,
    load_packages,
    main,
)


def _write_skill(skills_dir: Path, name: str) -> None:
    package_dir = skills_dir / name
    package_dir.mkdir(parents=True)
    (package_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill {name}.\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def _write_stale(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stale", encoding="utf-8")


@pytest.fixture
def repo_with_archived_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repo layout with one active skill and one archived skill."""
    repo = tmp_path / "repo"
    _write_skill(repo / "skills", "kept")
    _write_skill(repo / "archive" / "skills", "retired")
    monkeypatch.setattr(package_types, "REPO_ROOT", repo)
    monkeypatch.setattr(generate_adapters, "REPO_ROOT", repo)
    return repo


def test_invalid_definition_leaves_existing_generation_untouched(
    repo_with_archived_skill: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = repo_with_archived_skill / "skills" / "bad"
    invalid.mkdir()
    (invalid / "SKILL.md").write_text("---\n- not-a-mapping\n---\nBody.\n")
    out = tmp_path / "out"
    retained = out / "cursor" / ".cursor" / "rules" / "kept.mdc"
    _write_stale(retained)
    monkeypatch.setattr(sys, "argv", ["generate_adapters.py", "--output-dir", str(out)])

    assert main() == 1
    assert {
        p.relative_to(out).as_posix(): p.read_text()
        for p in out.rglob("*")
        if p.is_file()
    } == {"cursor/.cursor/rules/kept.mdc": "stale"}


class TestStaleOutputPruning:
    def test_archived_skill_is_not_discovered(
        self, repo_with_archived_skill: Path
    ) -> None:
        names = {pkg.name for pkg in load_packages()["skill"]}

        assert names == {"kept"}

    def test_regeneration_removes_output_of_archived_skill(
        self,
        repo_with_archived_skill: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        out = tmp_path / "out"
        # Output left behind by a run from before the skill was archived.
        _write_stale(out / "cursor" / ".cursor" / "rules" / "retired.mdc")
        _write_stale(out / "gemini" / ".gemini" / "skills" / "retired" / "SKILL.md")
        _write_stale(
            out / "gemini" / ".gemini" / "skills" / "retired" / "references" / "r.md"
        )
        # Files the generator does not own must survive.
        _write_stale(out / "cursor" / ".cursor" / "rules" / "notes.txt")
        _write_stale(out / "cursor" / ".cursor" / "rules" / "local.mdc")
        _write_stale(out / "gemini" / ".gemini" / "skills" / "local" / "SKILL.md")
        _write_stale(out / "gemini" / ".gemini" / "settings.json")
        monkeypatch.setattr(
            sys, "argv", ["generate_adapters.py", "--output-dir", str(out)]
        )

        assert main() == 0

        assert (out / "cursor" / ".cursor" / "rules" / "kept.mdc").is_file()
        assert (out / "gemini" / ".gemini" / "skills" / "kept" / "SKILL.md").is_file()
        assert not (out / "cursor" / ".cursor" / "rules" / "retired.mdc").exists()
        assert not (out / "gemini" / ".gemini" / "skills" / "retired").exists()
        assert (out / "cursor" / ".cursor" / "rules" / "notes.txt").is_file()
        assert (
            out / "cursor" / ".cursor" / "rules" / "local.mdc"
        ).read_text() == "stale"
        assert (
            out / "gemini" / ".gemini" / "skills" / "local" / "SKILL.md"
        ).read_text() == "stale"
        assert (out / "gemini" / ".gemini" / "settings.json").is_file()
        assert (
            "retired"
            not in (out / "codex" / "skills" / "AGENTS.md")
            .read_text(encoding="utf-8")
            .lower()
        )

    def test_partial_generation_keeps_output_of_unrequested_types(
        self,
        repo_with_archived_skill: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        out = tmp_path / "out"
        _write_stale(out / "cursor" / ".cursor" / "rules" / "existing-agent.mdc")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "generate_adapters.py",
                "--output-dir",
                str(out),
                "--platform",
                "cursor",
                "--type",
                "skill",
            ],
        )

        assert main() == 0

        assert (out / "cursor" / ".cursor" / "rules" / "kept.mdc").is_file()
        assert (out / "cursor" / ".cursor" / "rules" / "existing-agent.mdc").is_file()


class TestCodexAdapter:
    def test_generated_root_stays_within_size_budget(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "adapters" / "codex"
        adapter = CodexAdapter(output_dir)

        adapter.generate(load_packages())

        root = output_dir / "AGENTS.md"
        assert root.exists()
        assert len(root.read_bytes()) <= adapter.SIZE_BUDGET_BYTES
        assert adapter.validate() == []


class TestGeminiAdapter:
    def test_same_name_utility_wrapper_replaces_skill(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _write_skill(repo / "skills", "shared")
        for subdir, filename in (("scripts", "launcher.sh"), ("references", "a.md")):
            (repo / "skills" / "shared" / subdir).mkdir()
            (repo / "skills" / "shared" / subdir / filename).write_text(
                "skill-only\n", encoding="utf-8"
            )
        _write_skill(repo / "skills", "plain")
        utility = repo / "utilities" / "shared"
        (utility / "scripts").mkdir(parents=True)
        (utility / "UTILITY.md").write_text(
            "---\nname: shared\ndescription: Test utility shared.\n"
            "utility: {runtime: python, entry_point: scripts/run.py}\n---\n\n"
            "# Utility body\n",
            encoding="utf-8",
        )
        (utility / "scripts" / "run.py").write_text("print()\n", encoding="utf-8")
        monkeypatch.setattr(package_types, "REPO_ROOT", repo)
        monkeypatch.setattr(generate_adapters, "REPO_ROOT", repo)
        output_dir = tmp_path / "gemini"

        GeminiAdapter(output_dir).generate(load_packages())

        skills = output_dir / ".gemini" / "skills"
        assert (skills / "plain" / "SKILL.md").is_file()
        assert "# Utility body" in (skills / "shared" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert sorted(p.name for p in (skills / "shared").iterdir()) == [
            "SKILL.md",
            "scripts",
        ]
        assert sorted(p.name for p in (skills / "shared" / "scripts").iterdir()) == [
            "run.py"
        ]
