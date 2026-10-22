"""Regression tests for static conformance and executable routing evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from scripts.evaluate_package import evaluate_package
from scripts.package_types import TYPES
from scripts.run_evals import execute_case


def _write_skill(package_dir: Path, *, description: str = "Short description.") -> None:
    package_dir.mkdir()
    (package_dir / "SKILL.md").write_text(
        f"---\nname: sample-skill\ndescription: {description}\n---\n\n# Sample\n",
        encoding="utf-8",
    )


def test_static_conformance_does_not_reward_body_shape(tmp_path: Path) -> None:
    package_dir = tmp_path / "sample-skill"
    _write_skill(package_dir, description="Tiny.")

    result = evaluate_package(package_dir, TYPES["skill"])
    static_conformance = cast(dict[str, object], result["static_conformance"])
    live_effectiveness = cast(dict[str, object], result["live_effectiveness"])
    assert result["report_version"] == 2
    assert result["status"] == "PASS"
    assert static_conformance["status"] == "PASS"
    assert live_effectiveness["status"] == "NOT_MEASURED"


def test_static_conformance_reports_type_specific_frontmatter(tmp_path: Path) -> None:
    package_dir = tmp_path / "sample-hook"
    package_dir.mkdir()
    (package_dir / "HOOK.md").write_text(
        "---\nname: sample-hook\ndescription: Test hook.\n---\n",
        encoding="utf-8",
    )

    result = evaluate_package(package_dir, TYPES["hook"])

    findings = cast(list[dict[str, str]], result["findings"])
    live_effectiveness = cast(dict[str, object], result["live_effectiveness"])
    messages = [finding["message"] for finding in findings]
    assert result["status"] == "FAIL"
    assert "Missing required frontmatter field: hook" in messages
    assert live_effectiveness["dimensions"] == [
        "event handling",
        "observable side effect",
    ]


def test_negative_case_fails_when_route_reports_engagement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "scripts.run_evals.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, "Package engaged\nARMORY_EVAL_ROUTE: engaged", ""
        ),
    )
    package_dir = tmp_path / "sample-skill"
    package_dir.mkdir()
    case = {
        "id": "negative-routing",
        "prompt": "Unrelated request",
        "trigger_expected": False,
    }

    result = execute_case(case, package_dir, timeout_seconds=1)

    assert result.oracle_verdict == "fail"
    assert result.weighted_score == 0.0
    assert result.error == "negative route reported package engagement"


def test_negative_case_passes_when_route_reports_inactive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "scripts.run_evals.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, "Direct answer\nARMORY_EVAL_ROUTE: inactive", ""
        ),
    )
    package_dir = tmp_path / "sample-skill"
    package_dir.mkdir()
    case = {
        "id": "negative-routing",
        "prompt": "Unrelated request",
        "trigger_expected": False,
    }

    result = execute_case(case, package_dir, timeout_seconds=1)

    assert result.oracle_verdict == "pass"
    assert result.error is None


def test_negative_case_without_route_marker_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "scripts.run_evals.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, "Direct answer", ""
        ),
    )
    package_dir = tmp_path / "sample-skill"
    package_dir.mkdir()
    case = {
        "id": "negative-routing",
        "prompt": "Unrelated request",
        "trigger_expected": False,
    }

    result = execute_case(case, package_dir, timeout_seconds=1)

    assert result.oracle_verdict == "fail"
    assert result.error == "missing or ambiguous routing declaration"


@pytest.mark.parametrize("dry_run", [False, True])
def test_native_eval_never_launches_prompt_loader(
    tmp_path: Path, dry_run: bool
) -> None:
    root = Path(__file__).resolve().parent.parent
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sentinel = tmp_path / "prompt-loader-started"
    fake_claude = bin_dir / "claude"
    fake_claude.write_text(
        '#!/bin/sh\nprintf invoked > "$ARMORY_NATIVE_EVAL_SENTINEL"\nexit 97\n',
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)
    output = tmp_path / "results.json"
    command = [
        sys.executable,
        str(root / "scripts" / "run_evals.py"),
        "--package",
        "extensions/_fixtures/fixture-wordcount",
        "--output",
        str(output),
        "--no-history",
    ]
    if dry_run:
        command.append("--dry-run")

    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=os.environ
        | {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "ARMORY_NATIVE_EVAL_SENTINEL": str(sentinel),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == (0 if dry_run else 1)
    assert not sentinel.exists()
    packages = json.loads(output.read_text(encoding="utf-8"))["packages"]
    if dry_run:
        assert {
            case["case_id"]: case["oracle_verdict"]
            for case in packages[0]["case_results"]
        } == {
            "counts-words": "skipped",
            "unrelated-request": "skipped",
            "character-count-request": "skipped",
        }
    else:
        assert packages == []
