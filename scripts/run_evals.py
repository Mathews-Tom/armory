#!/usr/bin/env python3
"""Ground-truth oracle for eval case execution.

Executes eval cases against live Claude Code sessions via ``claude -p``
(headless mode) and checks structured assertions. Returns opaque pass/fail
verdicts — diagnostic explanations are the surrogate verifier's job.

Usage:
    uv run python scripts/run_evals.py --package skills/architecture-reviewer
    uv run python scripts/run_evals.py --all --timeout-per-case 120
    uv run python scripts/run_evals.py --package skills/immune --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


import yaml  # noqa: E402

from scripts.eval_assertions import AssertionResult, run_all_assertions  # noqa: E402
from scripts.package_types import TYPES  # noqa: E402
from scripts.task_signature import task_signature  # noqa: E402


_ROUTE_PATTERN = re.compile(r"(?m)^ARMORY_EVAL_ROUTE:\s*(engaged|inactive)\s*$")


def _evaluation_prompt(prompt: str) -> str:
    """Append the declared-routing receipt required by the eval harness."""
    return (
        f"{prompt}\n\n"
        "Evaluation receipt: append exactly one final line in this form after answering:\n"
        "ARMORY_EVAL_ROUTE: engaged|inactive\n"
        "Use engaged only when the package supplied for this evaluation materially guided "
        "your response. Use inactive when it did not."
    )


def _declared_route(output: str) -> str | None:
    """Return the unambiguous routing declaration emitted by an eval run."""
    routes = _ROUTE_PATTERN.findall(output)
    return routes[0] if len(routes) == 1 else None


@dataclass
class CaseResult:
    """Result of executing a single eval case."""

    case_id: str
    prompt: str
    trigger_expected: bool
    oracle_verdict: str  # "pass" or "fail"
    weighted_score: float
    assertion_details: list[dict]
    execution_time_ms: int
    error: str | None = None


@dataclass
class PackageResult:
    """Aggregated results for a single package."""

    package_name: str
    package_path: str
    total_cases: int
    passed: int
    failed: int
    skipped: int
    aggregate_score: float
    case_results: list[CaseResult]


def find_package_dir(package_path: str) -> Path | None:
    """Resolve a package path relative to repo root."""
    candidate = _REPO_ROOT / package_path
    if candidate.is_dir():
        return candidate
    return None


def load_cases(pkg_dir: Path) -> list[dict] | None:
    """Load eval cases from a package directory."""
    cases_file = pkg_dir / "evals" / "cases.yaml"
    if not cases_file.exists():
        return None
    data = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "cases" not in data:
        return None
    return data["cases"]


def _assertion_details(results: list[AssertionResult]) -> list[dict[str, object]]:
    """Serialize assertion results for the stable eval receipt."""
    return [
        {
            "type": result.assertion_type,
            "target": result.target,
            "passed": result.passed,
            "weight": result.weight,
            "detail": result.detail,
        }
        for result in results
    ]


def _git_untracked_files(repo_root: Path) -> set[str]:
    """List untracked files in a git repo via git status --porcelain."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        files: set[str] = set()
        for line in result.stdout.strip().splitlines():
            if line.startswith("??"):
                files.add(str(repo_root / line[3:].strip()))
        return files
    except (subprocess.SubprocessError, OSError):
        return set()


def _snapshot_files(directory: str) -> set[str]:
    """Take a snapshot of files — git untracked for repos, rglob for temp dirs."""
    root = Path(directory)
    if not root.is_dir():
        return set()
    if (root / ".git").exists():
        return _git_untracked_files(root)
    return {str(p) for p in root.rglob("*") if p.is_file()}


def execute_case(
    case: dict,
    pkg_dir: Path,
    timeout_seconds: int,
    dry_run: bool = False,
) -> CaseResult:
    """Execute a single eval case against a live Claude session.

    In dry-run mode, skips actual execution and returns a placeholder result.
    """
    case_id = case["id"]
    prompt = case["prompt"]
    trigger_expected = case["trigger_expected"]
    assertions = case.get("assertions", [])

    if dry_run:
        return CaseResult(
            case_id=case_id,
            prompt=prompt,
            trigger_expected=trigger_expected,
            oracle_verdict="skipped",
            weighted_score=0.0,
            assertion_details=[],
            execution_time_ms=0,
            error="dry-run mode",
        )

    start_ms = time.monotonic_ns() // 1_000_000

    # Snapshot existing files so we can detect new files written by the skill.
    # Skills often write artifacts (ADRs, test files, reports) that contain
    # the structured content assertions need to check.
    tmpdir = tempfile.mkdtemp(prefix="armory_eval_")
    pre_files = _snapshot_files(tmpdir) | _snapshot_files(str(_REPO_ROOT))

    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                _evaluation_prompt(prompt),
                "--add-dir",
                str(pkg_dir),
                "--output-format",
                "text",
                "--strict-mcp-config",
                "--no-session-persistence",
                "--allowedTools",
                "Read",
                "Glob",
                "Grep",
                "Write",
                "Edit",
                "Bash",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=tmpdir,
        )
        output = result.stdout
        exit_code = result.returncode

        # Collect new files written during execution and append to output.
        post_files = _snapshot_files(tmpdir) | _snapshot_files(str(_REPO_ROOT))
        new_files = post_files - pre_files
        for fpath_str in sorted(new_files):
            fpath = Path(fpath_str)
            if fpath.is_file() and fpath.stat().st_size < 100_000:
                try:
                    content = fpath.read_text(encoding="utf-8")
                    output += f"\n\n--- FILE: {fpath.name} ---\n{content}"
                except (UnicodeDecodeError, OSError):
                    pass
        # Clean up files written to the repo by the skill
        for fpath_str in sorted(new_files):
            fpath = Path(fpath_str)
            if fpath.is_file() and str(_REPO_ROOT) in fpath_str:
                fpath.unlink(missing_ok=True)
        # Clean up empty directories left behind
        for fpath_str in sorted(new_files, reverse=True):
            fpath = Path(fpath_str)
            parent = fpath.parent
            if parent.is_dir() and parent != _REPO_ROOT and not any(parent.iterdir()):
                parent.rmdir()

    except subprocess.TimeoutExpired:
        elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms
        shutil.rmtree(tmpdir, ignore_errors=True)
        return CaseResult(
            case_id=case_id,
            prompt=prompt,
            trigger_expected=trigger_expected,
            oracle_verdict="fail",
            weighted_score=0.0,
            assertion_details=[],
            execution_time_ms=elapsed_ms,
            error=f"Timed out after {timeout_seconds}s",
        )
    except FileNotFoundError:
        elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms
        shutil.rmtree(tmpdir, ignore_errors=True)
        return CaseResult(
            case_id=case_id,
            prompt=prompt,
            trigger_expected=trigger_expected,
            oracle_verdict="fail",
            weighted_score=0.0,
            assertion_details=[],
            execution_time_ms=elapsed_ms,
            error="'claude' CLI not found in PATH",
        )

    shutil.rmtree(tmpdir, ignore_errors=True)
    elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms

    if not trigger_expected:
        route = _declared_route(output)
        assertions_passed = True
        assertion_details: list[dict[str, object]] = []
        weighted_score = 1.0
        if assertions:
            assertions_passed, weighted_score, results = run_all_assertions(
                output, assertions
            )
            assertion_details = _assertion_details(results)
        passed = exit_code == 0 and route == "inactive" and assertions_passed
        if passed:
            error = None
        elif route == "engaged":
            error = "negative route reported package engagement"
        else:
            error = "missing or ambiguous routing declaration"
        return CaseResult(
            case_id=case_id,
            prompt=prompt,
            trigger_expected=trigger_expected,
            oracle_verdict="pass" if passed else "fail",
            weighted_score=weighted_score if passed else 0.0,
            assertion_details=assertion_details,
            execution_time_ms=elapsed_ms,
            error=error,
        )

    # Positive cases without assertions retain the existing non-empty-output oracle.
    if not assertions:
        verdict = "pass" if (exit_code == 0 and len(output.strip()) > 0) else "fail"
        return CaseResult(
            case_id=case_id,
            prompt=prompt,
            trigger_expected=trigger_expected,
            oracle_verdict=verdict,
            weighted_score=1.0 if verdict == "pass" else 0.0,
            assertion_details=[],
            execution_time_ms=elapsed_ms,
        )

    all_passed, weighted_score, results = run_all_assertions(output, assertions)
    assertion_details = _assertion_details(results)

    return CaseResult(
        case_id=case_id,
        prompt=prompt,
        trigger_expected=trigger_expected,
        oracle_verdict="pass" if all_passed else "fail",
        weighted_score=weighted_score,
        assertion_details=assertion_details,
        execution_time_ms=elapsed_ms,
    )


def run_package_evals(
    pkg_path: str,
    timeout_seconds: int = 120,
    dry_run: bool = False,
) -> PackageResult | None:
    """Run all eval cases for a single package."""
    pkg_dir = find_package_dir(pkg_path)
    if pkg_dir is None:
        print(f"Package not found: {pkg_path}", file=sys.stderr)
        return None

    cases = load_cases(pkg_dir)
    if cases is None:
        print(f"No evals/cases.yaml found in {pkg_path}", file=sys.stderr)
        return None

    results: list[CaseResult] = []
    for case in cases:
        result = execute_case(case, pkg_dir, timeout_seconds, dry_run)
        results.append(result)

    passed = sum(1 for r in results if r.oracle_verdict == "pass")
    failed = sum(1 for r in results if r.oracle_verdict == "fail")
    skipped = sum(1 for r in results if r.oracle_verdict == "skipped")
    total = len(results)
    aggregate_score = (
        sum(r.weighted_score for r in results) / total if total > 0 else 0.0
    )

    return PackageResult(
        package_name=pkg_dir.name,
        package_path=pkg_path,
        total_cases=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        aggregate_score=aggregate_score,
        case_results=results,
    )


def collect_all_packages() -> list[str]:
    """Collect all package paths that have evals/cases.yaml."""
    packages: list[str] = []
    for pkg_type in TYPES.values():
        type_dir = pkg_type.repo_dir
        if not type_dir.exists():
            continue
        for pkg_dir in sorted(type_dir.iterdir()):
            if not pkg_dir.is_dir():
                continue
            if (pkg_dir / "evals" / "cases.yaml").exists():
                packages.append(str(pkg_dir.relative_to(_REPO_ROOT)))
    return packages


def write_results(results: list[PackageResult], output_path: Path) -> None:
    """Write results to JSON."""
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_packages": len(results),
        "packages": [asdict(r) for r in results],
    }
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _prompt_hash(prompt: str) -> str:
    """Return a short, stable, non-reversible fingerprint of a prompt.

    Used in the history log for dedup and cross-run identification
    without storing raw prompt text (which may contain secrets or PII).

    Args:
        prompt: The raw task prompt.

    Returns:
        First 16 hex characters of the SHA-256 digest.
    """
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return digest[:16]


def write_history(results: list[PackageResult], history_path: Path) -> None:
    """Append per-case eval outcomes to the history log as JSONL.

    Each case becomes one JSON line with shape::

        {
          "timestamp": ISO8601 UTC,
          "package_path": str,
          "case_id": str,
          "task_signature": str,
          "prompt_hash": str (16-char SHA-256 prefix),
          "trigger_expected": bool,
          "oracle_verdict": "pass" | "fail" | "skipped",
          "weighted_score": float,
          "execution_time_ms": int
        }

    The history log is append-only. Raw prompt text is never stored —
    only the normalized task signature (from :mod:`scripts.task_signature`)
    and a truncated SHA-256 hash. This protects against prompts that
    contain credentials, tokens, or PII.

    Args:
        results: Package results from a run_evals session.
        history_path: Path to the history log. Parent dirs are created
            if missing.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines: list[str] = []
    for pkg in results:
        for case in pkg.case_results:
            entry = {
                "timestamp": timestamp,
                "package_path": pkg.package_path,
                "case_id": case.case_id,
                "task_signature": task_signature(case.prompt),
                "prompt_hash": _prompt_hash(case.prompt),
                "trigger_expected": case.trigger_expected,
                "oracle_verdict": case.oracle_verdict,
                "weighted_score": case.weighted_score,
                "execution_time_ms": case.execution_time_ms,
            }
            lines.append(json.dumps(entry, separators=(",", ":")))
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute eval cases against live Claude sessions"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--package", help="Path to a single package (relative to repo root)"
    )
    group.add_argument("--all", action="store_true", help="Run evals for all packages")
    parser.add_argument(
        "--timeout-per-case", type=int, default=120, help="Timeout per case in seconds"
    )
    parser.add_argument(
        "--output", default="evals/results.json", help="Output file path"
    )
    parser.add_argument(
        "--history", default="evals/history.jsonl", help="Append-only history log path"
    )
    parser.add_argument(
        "--no-history", action="store_true", help="Skip appending to the history log"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip actual execution, validate structure only",
    )
    args = parser.parse_args()

    packages = collect_all_packages() if args.all else [args.package]
    results: list[PackageResult] = []

    for pkg_path in packages:
        print(f"Running evals for {pkg_path}...")
        result = run_package_evals(pkg_path, args.timeout_per_case, args.dry_run)
        if result is not None:
            results.append(result)
            status = "PASS" if result.failed == 0 else "FAIL"
            print(
                f"  {status}: {result.passed}/{result.total_cases} passed (score: {result.aggregate_score:.2f})"
            )

    output_path = _REPO_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_results(results, output_path)
    print(f"\nResults written to {args.output}")

    if not args.no_history and not args.dry_run:
        history_path = _REPO_ROOT / args.history
        write_history(results, history_path)
        total_cases = sum(r.total_cases for r in results)
        print(f"History appended: {total_cases} cases -> {args.history}")

    total_failed = sum(r.failed for r in results)
    return 1 if total_failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
