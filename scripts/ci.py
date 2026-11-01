#!/usr/bin/env python3
"""Shared CI commands; package selection is an optimization, never a test exclusion.

PR archives are independent package inputs. Repository tests and every package's
Python suites remain broad: this repository has no declared cross-package test
dependency graph. Unknown/shared paths and unavailable diff history build all.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = {
    "skills": "SKILL.md",
    "agents": "AGENT.md",
    "hooks": "HOOK.md",
    "rules": "RULE.md",
    "commands": "COMMAND.md",
    "utilities": "UTILITY.md",
    "presets": "PRESET.md",
    "extensions": "EXTENSION.md",
}
PYTHON_TYPES = tuple(kind for kind in DEFINITIONS if kind != "extensions")
CHECKS = (
    "templates",
    "ci-tooling",
    "ship",
    "appraise",
    "inventory",
    "extension-tooling",
)


class Plan(TypedDict):
    full: bool
    reason: str
    packages: list[str]
    definitions: list[str]
    suites: list[str]


def packages(root: Path) -> list[str]:
    return sorted(
        path.parent.relative_to(root).as_posix()
        for kind, definition in DEFINITIONS.items()
        for path in (root / kind).glob(f"*/{definition}")
    )


def suites(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for kind in PYTHON_TYPES
        for pattern in ("*/tests", "*/engine/tests")
        for path in (root / kind).glob(pattern)
        if any(path.glob("test_*.py"))
    )


def selection(root: Path, changed: list[str] | None) -> Plan:
    available = packages(root)
    selected: set[str] = set()
    definitions: set[str] = set()
    reason = "package-only changes"
    full = changed is None
    for name in changed or []:
        path = PurePosixPath(name)
        parts = path.parts
        if len(parts) < 3 or parts[0] not in DEFINITIONS or ".." in parts:
            full = True
            reason = "shared or unknown path"
            continue
        package = "/".join(parts[:2])
        if package not in available:
            # Removed/renamed packages, extension fixtures, workspace tooling,
            # and malformed package trees cannot safely use isolated packaging.
            full = True
            reason = "removed or unregistered package"
            continue
        selected.add(package)
        if len(parts) == 3 and parts[2] == DEFINITIONS[parts[0]]:
            definitions.add(package)
    if changed is None:
        reason = "full event or unavailable diff history"
    return {
        "full": full,
        "reason": reason,
        "packages": available if full else sorted(selected),
        # Unknown history cannot silently omit a changed definition's checks.
        # Full non-PR events explicitly opt out of PR-only quality in main().
        "definitions": available if changed is None else sorted(definitions),
        "suites": suites(root),
    }


def changed_paths(root: Path, base: str | None) -> list[str] | None:
    """Include committed changes and local staged, unstaged and untracked inputs."""
    if not base or base.startswith("-"):
        return None
    try:
        ancestor = subprocess.check_output(
            ["git", "merge-base", base, "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        result = subprocess.check_output(
            [
                "git",
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                ancestor,
                "--",
            ],
            cwd=root,
        )
        untracked = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=root,
        )
        return sorted(
            {os.fsdecode(path) for path in (result + untracked).split(b"\0") if path}
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def run(*args: str) -> None:
    print("+ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def python(*args: str) -> None:
    run(sys.executable, *args)


def lint(
    paths: list[str], typed: list[str] | None = None, extension: bool = False
) -> None:
    python("-m", "ruff", "check", *paths)
    python("-m", "ruff", "format", "--check", *paths)
    extra = ["--follow-imports=silent"] if extension else []
    python("-m", "mypy", "--strict", *extra, *(typed or paths[:1]))


def check_manifest() -> None:
    path = ROOT / "manifest.yaml"
    before = path.read_bytes() if path.exists() else None
    python("scripts/generate_manifest.py")
    if path.read_bytes() != before:
        raise ValueError(
            "manifest.yaml is out of sync; regenerate and include the updated file"
        )


def task(name: str, plan: Plan, suite: str | None) -> None:
    if name == "all":
        for check in (
            *CHECKS,
            "schemas",
            "repo-tests",
            "extension-workspace",
            "extension-offline",
        ):
            task(check, plan, None)
        discovered = suites(ROOT)
        if not discovered:
            raise ValueError("No package test suites found")
        for path in discovered:
            task("suite", plan, path)
        task("package", plan, None)
    elif name == "templates":
        python("scripts/sync_templates.py")
    elif name == "ci-tooling":
        lint(
            ["scripts/ci.py", "tests/test_ci.py"], ["scripts/ci.py", "tests/test_ci.py"]
        )
    elif name in ("ship", "appraise", "inventory"):
        package = {
            "ship": "skills/ship-workflow",
            "appraise": "skills/appraise",
            "inventory": "utilities/skill-inventory",
        }[name]
        lint([f"{package}/scripts", f"{package}/tests"])
    elif name == "extension-tooling":
        sources = [
            f"scripts/{item}.py"
            for item in (
                "build_extensions",
                "check_extensions",
                "extension_metadata",
                "extension_lifecycle",
                "acquire_claude",
            )
        ]
        typed = sources + [
            "tests/test_extension_ci.py",
            "tests/test_omp_native_gate.py",
            "tests/test_verification_receipts_lifecycle.py",
        ]
        smokes = [
            f"extensions/verification-receipts/tests/{host}-smoke.py"
            for host in ("omp", "claude")
        ]
        tests = sorted(
            path.as_posix() for path in Path("tests").glob("test_extension*.py")
        )
        lint(
            sources
            + tests
            + [
                "tests/test_omp_native_gate.py",
                "tests/test_verification_receipts_lifecycle.py",
            ]
            + smokes,
            typed + smokes,
            extension=True,
        )
    elif name == "repo-tests":
        python("-m", "pytest", "tests/", "-q")
    elif name == "suite":
        if suite not in suites(ROOT):
            raise ValueError(f"Unknown or empty package suite: {suite!r}")
        python("-m", "pytest", str(suite), "-q")
    elif name == "extension-workspace":
        for gate in ("typecheck", "lint", "test", "build"):
            run("bun", "run", "--cwd", "extensions", gate)
    elif name == "extension-offline":
        python("scripts/check_extensions.py", "--ci")
    elif name == "schemas":
        check_manifest()
        for script in ("validate_evals", "validate_frontmatter", "validate_references"):
            python(f"scripts/{script}.py")
    elif name == "quality":
        for package in plan["definitions"]:
            python("scripts/evaluate_package.py", "--path", package)
            if not (ROOT / package / "evals/cases.yaml").is_file():
                raise ValueError(
                    f"{package}: changed definition has no evals/cases.yaml"
                )
        if not plan["definitions"]:
            print(
                "No surviving package definitions changed; quality/coverage is not applicable."
            )
    elif name == "package":
        check_manifest()
        python("scripts/generate_adapters.py", "--validate")
        # Fixture reproducibility remains broad, even for package-only PRs.
        python(
            "-m",
            "pytest",
            "tests/test_extensions_packaging.py::test_native_package_archives_are_reproducible",
            "-q",
        )
        (ROOT / "dist").mkdir(exist_ok=True)
        for package in plan["packages"]:
            python("scripts/package.py", package, "--output-dir", "dist")
        print(f"Packaged {len(plan['packages'])} packages ({plan['reason']}).")
    else:
        raise ValueError(f"Unknown CI task: {name}")


def readiness(results: dict[str, object], expected: list[str]) -> bool:
    """Only explicit success satisfies required prerequisites, including matrices."""
    return bool(expected) and all(
        isinstance(entry := results.get(name), dict)
        and entry.get("result") == "success"
        for name in expected
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("select", "run", "ready"))
    parser.add_argument("task", nargs="?")
    parser.add_argument("--base", help="PR base commit/ref; omit for a full run")
    parser.add_argument("--suite")
    parser.add_argument("--needs", help="JSON job results for the readiness gate")
    parser.add_argument("--expect", nargs="+", default=[])
    args = parser.parse_args()
    if args.command == "ready":
        results = json.loads(args.needs or "{}")
        print(json.dumps(results, indent=2))
        return 0 if readiness(results, args.expect) else 1
    os.chdir(ROOT)
    plan = selection(ROOT, changed_paths(ROOT, args.base))
    if args.command == "select":
        print(json.dumps(plan, sort_keys=True))
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a", encoding="utf-8") as handle:
                handle.write("suites=" + json.dumps({"suite": plan["suites"]}) + "\n")
        return 0
    if args.task == "quality" and not args.base:
        print(
            "No PR comparison: changed-definition quality/coverage is not applicable."
        )
        return 0
    try:
        task(args.task or "", plan, args.suite)
        if args.task == "all" and args.base:
            task("quality", plan, None)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
