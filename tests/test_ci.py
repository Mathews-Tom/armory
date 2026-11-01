"""Behavioral CI selection, isolated suite execution, and readiness contracts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import ci


def package(root: Path, name: str, definition: str = "SKILL.md") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / definition).write_text("test package\n", encoding="utf-8")
    return directory


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    package(tmp_path, "skills/alpha")
    package(tmp_path, "skills/beta")
    package(tmp_path, "extensions/native", "EXTENSION.md")
    return tmp_path


@pytest.mark.parametrize(
    "path",
    [
        "skills/alpha/SKILL.md",
        "skills/alpha/scripts/tool.py",
        "skills/alpha/references/guide.md",
        "skills/alpha/tests/deleted.py",
    ],
)
def test_package_owned_paths_select_only_that_archive(
    repository: Path, path: str
) -> None:
    plan = ci.selection(repository, [path])
    assert plan["full"] is False
    assert plan["packages"] == ["skills/alpha"]
    assert plan["definitions"] == (
        ["skills/alpha"] if path.endswith("SKILL.md") else []
    )


@pytest.mark.parametrize(
    "path",
    [
        "scripts/package.py",
        "templates/shared.md",
        "uv.lock",
        "pyproject.toml",
        "profiles.yaml",
        "manifest.yaml",
        ".github/workflows/tests.yml",
        "justfile",
        "tests/test_shared.py",
        "unknown/new.file",
        "skills/SHARED.md",
        "extensions/package.json",
        "extensions/bun.lock",
        "extensions/_tooling/build.ts",
        "extensions/_fixtures/fixture/core/index.ts",
        "skills/removed/SKILL.md",
        "skills/alpha/../../scripts/shared.py",
    ],
)
def test_shared_deleted_and_unknown_paths_build_everything(
    repository: Path, path: str
) -> None:
    plan = ci.selection(repository, ["skills/alpha/SKILL.md", path])
    assert plan["full"] is True
    assert plan["packages"] == ci.packages(repository)
    # Shared changes cannot erase a known changed definition's quality checks.
    assert plan["definitions"] == ["skills/alpha"]


def test_full_events_and_missing_history_select_all(repository: Path) -> None:
    plan = ci.selection(repository, None)
    assert plan["full"] is True
    assert plan["packages"] == ci.packages(repository)
    assert plan["definitions"] == ci.packages(repository)
    assert ci.changed_paths(repository, "nonexistent-base") is None
    assert ci.changed_paths(repository, "--malicious-option") is None


def test_empty_diff_is_an_explicit_packaging_noop(repository: Path) -> None:
    plan = ci.selection(repository, [])
    assert plan["full"] is False
    assert plan["packages"] == []
    assert plan["definitions"] == []


@pytest.mark.parametrize("rename", [False, True])
def test_removed_or_renamed_package_root_forces_full_build(
    repository: Path,
    rename: bool,
) -> None:
    changed = ["skills/alpha/SKILL.md"]
    if rename:
        (repository / "skills/alpha").rename(repository / "skills/gamma")
        changed.append("skills/gamma/SKILL.md")
    else:
        (repository / "skills/alpha/SKILL.md").unlink()
    plan = ci.selection(repository, changed)
    assert plan["full"] is True
    assert plan["packages"] == ci.packages(repository)
    assert "skills/alpha" not in plan["definitions"]


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def test_diff_uses_merge_base_and_preserves_deleted_renamed_paths(
    repository: Path,
) -> None:
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.email", "ci@example.invalid")
    git(repository, "config", "user.name", "CI Test")
    old = repository / "skills/alpha/old name.md"
    old.write_text("rename me\n", encoding="utf-8")
    deleted = repository / "skills/alpha/deleted.md"
    deleted.write_text("delete me\n", encoding="utf-8")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "base")
    git(repository, "checkout", "-b", "topic")
    old.rename(repository / "skills/alpha/new name.md")
    deleted.unlink()
    git(repository, "add", "-A")
    git(repository, "commit", "-m", "rename and delete")
    git(repository, "checkout", "main")
    (repository / "base-only.txt").write_text("not a PR change\n", encoding="utf-8")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "base moves")
    git(repository, "checkout", "topic")
    changed = ci.changed_paths(repository, "main")
    assert changed is not None
    assert set(changed) == {
        "skills/alpha/old name.md",
        "skills/alpha/new name.md",
        "skills/alpha/deleted.md",
    }
    assert ci.selection(repository, changed)["packages"] == ["skills/alpha"]


def test_local_comparison_includes_staged_unstaged_and_untracked_packages(
    repository: Path,
) -> None:
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.email", "ci@example.invalid")
    git(repository, "config", "user.name", "CI Test")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "base")
    (repository / "skills/alpha/SKILL.md").write_text("staged\n", encoding="utf-8")
    git(repository, "add", "skills/alpha/SKILL.md")
    (repository / "skills/beta/SKILL.md").write_text("unstaged\n", encoding="utf-8")
    package(repository, "skills/gamma")
    (repository / ".git/info/exclude").write_text(
        "ignored-local.txt\n", encoding="utf-8"
    )
    (repository / "ignored-local.txt").write_text("not an input\n", encoding="utf-8")
    changed = ci.changed_paths(repository, "main")
    assert changed is not None
    assert set(changed) == {
        "skills/alpha/SKILL.md",
        "skills/beta/SKILL.md",
        "skills/gamma/SKILL.md",
    }
    assert ci.selection(repository, changed)["definitions"] == [
        "skills/alpha",
        "skills/beta",
        "skills/gamma",
    ]


def test_suite_discovery_is_broad_and_includes_engine_tests(repository: Path) -> None:
    for name in ("skills/alpha/tests", "skills/beta/engine/tests"):
        suite = repository / name
        suite.mkdir(parents=True)
        (suite / "test_case.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (repository / "skills/alpha/empty/tests").mkdir(parents=True)
    plan = ci.selection(repository, ["skills/alpha/SKILL.md"])
    assert plan["suites"] == ["skills/alpha/tests", "skills/beta/engine/tests"]


def test_each_suite_uses_a_fresh_python_process(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci, "ROOT", repository)
    for name, expected in (
        ("skills/alpha/tests", "alpha"),
        ("skills/beta/engine/tests", "beta"),
    ):
        suite = repository / name
        suite.mkdir(parents=True)
        (suite / "same_module.py").write_text(
            f"VALUE = {expected!r}\n", encoding="utf-8"
        )
        (suite / "conftest.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).parent))\n",
            encoding="utf-8",
        )
        (suite / "test_same.py").write_text(
            f"import same_module\ndef test_value(): assert same_module.VALUE == {expected!r}\n",
            encoding="utf-8",
        )
    for suite_name in ci.suites(repository):
        ci.task("suite", ci.selection(repository, []), suite_name)
    with pytest.raises(ValueError, match="Unknown or empty"):
        ci.task("suite", ci.selection(repository, []), "../../outside")


@pytest.mark.parametrize(
    "result", ["failure", "cancelled", "skipped", "timed_out", "", None]
)
def test_readiness_rejects_every_non_success_result(result: str | None) -> None:
    assert not ci.readiness({"gate": {"result": result}}, ["gate"])


def test_readiness_rejects_missing_prerequisites_and_accepts_completed_noop() -> None:
    assert not ci.readiness({"first": {"result": "success"}}, ["first", "missing"])
    assert not ci.readiness({}, [])
    assert ci.readiness({"noop": {"result": "success"}}, ["noop"])


def test_selector_cli_outputs_machine_readable_plan_and_matrix(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    result = subprocess.run(
        [
            sys.executable,
            str(ci.ROOT / "scripts/ci.py"),
            "select",
            "--base",
            "missing-ci-base",
        ],
        cwd=ci.ROOT,
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        text=True,
        capture_output=True,
        check=True,
    )
    plan = json.loads(result.stdout)
    assert plan["full"] is True
    assert plan["packages"] == ci.packages(ci.ROOT)
    matrix = json.loads(output.read_text(encoding="utf-8").removeprefix("suites="))
    assert matrix == {"suite": ci.suites(ci.ROOT)}


def test_readiness_cli_fails_closed() -> None:
    for needs, expected in (
        ({}, 1),
        ({"job": {"result": "cancelled"}}, 1),
        ({"job": {"result": "success"}}, 0),
    ):
        result = subprocess.run(
            [
                sys.executable,
                str(ci.ROOT / "scripts/ci.py"),
                "ready",
                "--needs",
                json.dumps(needs),
                "--expect",
                "job",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == expected


def test_manifest_drift_uses_generated_content_not_git_cleanliness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = ci.ROOT
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("generate_manifest.py", "package_types.py", "frontmatter.py"):
        shutil.copy2(source / "scripts" / name, scripts / name)
    (scripts / "__init__.py").touch()
    definition = package(tmp_path, "skills/alpha") / "SKILL.md"
    definition.write_text(
        "---\nname: alpha\ndescription: Test skill\nmetadata:\n  version: 1.0.0\n---\n",
        encoding="utf-8",
    )
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "ci@example.invalid")
    git(tmp_path, "config", "user.name", "CI Test")
    git(tmp_path, "remote", "add", "origin", "https://github.com/fixture/armory.git")
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="out of sync"):
        ci.check_manifest()
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial manifest")
    definition.write_text(
        definition.read_text(encoding="utf-8").replace("1.0.0", "2.0.0"),
        encoding="utf-8",
    )
    ci.python("scripts/generate_manifest.py")
    assert git(tmp_path, "diff", "--name-only", "manifest.yaml") == "manifest.yaml"
    ci.check_manifest()  # Current generated content is valid even before commit.
    definition.write_text(
        definition.read_text(encoding="utf-8").replace("2.0.0", "3.0.0"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="out of sync"):
        ci.check_manifest()
