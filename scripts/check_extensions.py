#!/usr/bin/env python3
"""Run native extension gates selected by each feature's committed implementation.

Exit status: 0 when every executed surface passed, 1 when any surface failed,
2 for invalid arguments, 3 when a required surface is unavailable or the
requested gate is not yet implemented (incomplete). A JSON report on stdout
names the selected stage, ``feature_complete`` and every exercised or
unavailable surface. Static, test-kit and lifecycle passes never certify
real-host compatibility. CI runs credential-free offline gates and reports
native smoke as not requested. The explicit OMP prefix additionally runs its
feature-owned actual-host driver; full compatibility requires both adapters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml

from scripts.build_extensions import (
    CONTENT_MANIFEST,
    BuildError,
    ToolUnavailableError,
    build_feature,
    bundle_omp_adapter,
    collect_source_tree,
    load_metadata,
    registered_features,
    require_bun,
    resolve_feature_dir,
    verify_artifact_dir,
)
from scripts.evaluate_package import evaluate_package
from scripts.extension_lifecycle import LifecycleError, run_action
from scripts.extension_metadata import (
    ADAPTER_DIRS,
    CORE_DIR,
    is_feature_name,
)
from scripts.frontmatter import parse_frontmatter
from scripts.package_types import MANIFEST_PATH, NATIVE_HOSTS, REPO_ROOT, TYPES
from scripts.validate_evals import validate_pkg_evals
from scripts.validate_frontmatter import validate_package
from scripts.validate_references import validate_pkg_references

EXTENSION_TYPE = TYPES["extension"]
STAGES: tuple[str, ...] = ("core", "omp")
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INCOMPLETE = 3
OMP_PROBE = Path("_tooling") / "omp-probe.ts"
CLAUDE_NATIVE_TESTS = "mod-checks"
# Nonpersistent controls for the static Claude commands: no update download or
# nonessential traffic during validation. Credentials and policy are untouched.
_CLAUDE_ENV = {
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}
_PASS_COUNT = re.compile(r"(\d+) pass\b")
_FAIL_COUNT = re.compile(r"(\d+) fail\b")
_OUTPUT_TAIL = 2000


class GateFailure(RuntimeError):
    """A selected gate ran and did not pass."""


class GateUnavailable(RuntimeError):
    """A selected gate could not run because a prerequisite is missing."""


@dataclass
class Surface:
    name: str
    status: str
    detail: str


@dataclass
class Report:
    scope: str
    stage: str
    feature_complete: bool = False
    surfaces: list[Surface] = field(default_factory=list)

    def run(self, name: str, gate: Callable[[], str]) -> bool:
        """Execute one gate, recording passed/failed/unavailable."""
        try:
            detail = gate()
        except (GateUnavailable, ToolUnavailableError) as exc:
            self.surfaces.append(Surface(name, "unavailable", str(exc)))
            return False
        except (GateFailure, BuildError, LifecycleError) as exc:
            self.surfaces.append(Surface(name, "failed", str(exc)))
            return False
        self.surfaces.append(Surface(name, "passed", detail))
        return True

    def note(self, name: str, status: str, detail: str) -> None:
        self.surfaces.append(Surface(name, status, detail))

    @property
    def exit_code(self) -> int:
        statuses = {surface.status for surface in self.surfaces}
        if "failed" in statuses:
            return EXIT_FAILED
        if "unavailable" in statuses or "incomplete" in statuses:
            return EXIT_INCOMPLETE
        return EXIT_OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "stage": self.stage,
            "feature_complete": self.feature_complete,
            "exit_code": self.exit_code,
            "surfaces": [surface.__dict__ for surface in self.surfaces],
        }


# ---------------------------------------------------------------------------
# Stage selection from committed files
# ---------------------------------------------------------------------------


def implemented_stage(feature_dir: Path) -> str:
    """Derive the implemented stage from the feature's committed layout."""
    if (feature_dir / EXTENSION_TYPE.definition_file).is_file():
        return "full"
    if (feature_dir / ADAPTER_DIRS["claude"]).exists():
        raise GateFailure(
            f"{feature_dir.name}: a Claude adapter exists without {EXTENSION_TYPE.definition_file}; "
            "the complete package must be introduced atomically"
        )
    if (feature_dir / ADAPTER_DIRS["omp"]).is_dir():
        return "omp"
    if (feature_dir / CORE_DIR).is_dir():
        return "core"
    raise GateFailure(
        f"{feature_dir.name}: no implemented component (expected {CORE_DIR}/)"
    )


def feature_directories(extensions_root: Path) -> list[Path]:
    """Every kebab-case feature directory, registered or in a prefix stage."""
    if not extensions_root.is_dir():
        return []
    return sorted(
        entry
        for entry in extensions_root.iterdir()
        if is_feature_name(entry.name) and entry.is_dir() and not entry.is_symlink()
    )


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def _run(
    command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=None if env is None else {**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def _tail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout + result.stderr).strip()[-_OUTPUT_TAIL:]


def _counted_pass(result: subprocess.CompletedProcess[str], what: str) -> str:
    output = result.stdout + result.stderr
    passed = sum(int(count) for count in _PASS_COUNT.findall(output))
    failed = sum(int(count) for count in _FAIL_COUNT.findall(output))
    if result.returncode != 0 or failed:
        raise GateFailure(f"{what} failed (exit {result.returncode}):\n{_tail(result)}")
    if passed == 0:
        raise GateFailure(f"{what} executed no passing cases:\n{_tail(result)}")
    return f"{passed} passed"


def _workspace_relative(feature_dir: Path) -> str:
    workspace = EXTENSION_TYPE.repo_dir.resolve()
    resolved = feature_dir.resolve()
    if not resolved.is_relative_to(workspace):
        raise GateFailure(
            f"{feature_dir} is outside the extensions workspace {workspace}"
        )
    return resolved.relative_to(workspace).as_posix()


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def toolchain_gate() -> str:
    bun = require_bun()
    if not (EXTENSION_TYPE.repo_dir / "node_modules").is_dir():
        raise GateUnavailable(
            "extensions/node_modules is missing; run `bun install --cwd extensions --frozen-lockfile`"
        )
    return bun


def typecheck_gate(bun: str) -> str:
    result = _run([bun, "run", "typecheck"], EXTENSION_TYPE.repo_dir)
    if result.returncode != 0:
        raise GateFailure(f"tsc --noEmit failed:\n{_tail(result)}")
    return "tsc --noEmit passed for the workspace"


def lint_gate(bun: str, feature_dir: Path) -> str:
    rel = _workspace_relative(feature_dir)
    result = _run(
        [bun, "run", "eslint", "--max-warnings=0", rel], EXTENSION_TYPE.repo_dir
    )
    if result.returncode != 0:
        raise GateFailure(f"eslint failed for {rel}:\n{_tail(result)}")
    return f"eslint passed for {rel}"


def unit_test_gate(bun: str, feature_dir: Path) -> str:
    tests = feature_dir / "tests"
    cases = sorted(tests.glob("*.test.ts")) if tests.is_dir() else []
    if not cases:
        raise GateFailure(
            f"{feature_dir.name}: no unit test cases under tests/*.test.ts"
        )
    rel = _workspace_relative(tests)
    return _counted_pass(
        _run([bun, "test", f"{rel}/"], EXTENSION_TYPE.repo_dir), f"bun test {rel}"
    )


def core_source_gate(feature_dir: Path) -> str:
    files = collect_source_tree(feature_dir, CORE_DIR)
    return (
        f"{len(files)} distributable core files; purity enforced by the core lint rules"
    )


def omp_probe(bun: str, entry: Path) -> list[str]:
    """Load an OMP entry with a recording ExtensionAPI and return registered commands."""
    probe = EXTENSION_TYPE.repo_dir / OMP_PROBE
    with tempfile.TemporaryDirectory(prefix="armory-omp-probe-") as scratch:
        result = _run([bun, str(probe), str(entry)], Path(scratch))
    if result.returncode != 0:
        raise GateFailure(f"OMP factory probe failed for {entry}:\n{_tail(result)}")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure(f"OMP factory probe produced no JSON report: {exc}") from exc
    commands = report.get("commands") if isinstance(report, dict) else None
    if not isinstance(commands, list) or not all(
        isinstance(command, str) for command in commands
    ):
        raise GateFailure("OMP factory probe report lacks a commands list")
    return commands


def omp_source_gate(bun: str, feature_dir: Path) -> str:
    entry = feature_dir / ADAPTER_DIRS["omp"] / "index.ts"
    if not entry.is_file():
        raise GateFailure(
            f"{feature_dir.name}: OMP adapter entry {ADAPTER_DIRS['omp']}/index.ts is missing"
        )
    commands = omp_probe(bun, entry)
    if not commands:
        raise GateFailure(f"{feature_dir.name}: OMP factory registered no commands")
    return (
        f"OMP factory registered {', '.join(commands)} (test-kit probe, not host proof)"
    )


def omp_prefix_build_gate(bun: str, feature_dir: Path) -> str:
    """Reproduce and probe a detached OMP bundle without registering a package."""
    entry = f"{ADAPTER_DIRS['omp']}/index.ts"
    with tempfile.TemporaryDirectory(prefix="armory-omp-prefix-") as tmp:
        bundles: list[bytes] = []
        entries: list[Path] = []
        for name in ("build-a", "build-b"):
            artifact = Path(tmp) / name
            artifact.mkdir()
            bundle = bundle_omp_adapter(feature_dir, entry, bun)
            detached_entry = artifact / "index.js"
            detached_entry.write_bytes(bundle)
            bundles.append(bundle)
            entries.append(detached_entry)
        if bundles[0] != bundles[1]:
            raise GateFailure("OMP prefix bundle bytes differ between build roots")
        commands = omp_probe(bun, entries[0])
        if not commands or sorted(commands) != sorted(
            omp_probe(bun, feature_dir / entry)
        ):
            raise GateFailure("detached OMP prefix factory commands differ from source")
    return (
        "identical detached OMP bundle bytes across two build roots; source and "
        "bundle imports confined; factory commands match (offline test-kit, not host proof)"
    )


def definition_gate(feature_dir: Path) -> str:
    load_metadata(feature_dir)
    errors = [
        *validate_package(feature_dir, EXTENSION_TYPE),
        *validate_pkg_references(feature_dir, EXTENSION_TYPE),
        *validate_pkg_evals(feature_dir, EXTENSION_TYPE),
    ]
    if not (feature_dir / "CHANGELOG.md").is_file():
        errors.append(f"{feature_dir.name}: CHANGELOG.md is missing")
    if errors:
        raise GateFailure("; ".join(errors))
    return "definition, references, eval cases and CHANGELOG present"


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def reproducible_build_gate(feature_dir: Path, scratch: Path) -> dict[str, Path]:
    """Build into two distinct roots and require identical artifact bytes."""
    first = build_feature(feature_dir, scratch / "build-a")
    second = build_feature(feature_dir, scratch / "build-b")
    for host, path in first.items():
        verify_artifact_dir(path)
        if _tree_bytes(path) != _tree_bytes(second[host]):
            raise GateFailure(f"{host} artifact bytes differ between build roots")
    return first


def omp_artifact_gate(bun: str, artifact: Path, declared: list[str]) -> str:
    package = json.loads((artifact / "package.json").read_text(encoding="utf-8"))
    entries = package.get("omp", {}).get("extensions")
    if not isinstance(entries, list) or len(entries) != 1:
        raise GateFailure(
            "OMP package.json must declare exactly one omp.extensions entry"
        )
    commands = omp_probe(bun, artifact / entries[0])
    if sorted(commands) != sorted(declared):
        raise GateFailure(
            f"OMP artifact registers {sorted(commands)}; metadata declares {sorted(declared)}"
        )
    return f"detached OMP artifact registers exactly {', '.join(sorted(commands))} (test-kit probe)"


def _claude() -> tuple[str, str]:
    claude = shutil.which("claude")
    if claude is None:
        raise GateUnavailable(
            "claude is not on PATH; provision the pinned binary from extensions/native-hosts.json"
        )
    result = _run([claude, "--version"], REPO_ROOT, _CLAUDE_ENV)
    if result.returncode != 0:
        raise GateUnavailable(f"claude --version failed with exit {result.returncode}")
    version = result.stdout.strip()
    if not version:
        raise GateUnavailable("installed claude reported no version")
    return claude, version


def claude_validate_gate(artifact: Path) -> str:
    claude, version = _claude()
    result = _run(
        [claude, "plugin", "validate", str(artifact), "--strict", "--json"],
        artifact,
        _CLAUDE_ENV,
    )
    if result.returncode != 0:
        raise GateFailure(f"claude plugin validate --strict failed:\n{_tail(result)}")
    try:
        json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure(
            f"claude plugin validate --json produced unparseable output: {exc}"
        ) from exc
    return f"strict static validation passed with observed {version} (not a compatibility certification)"


def claude_native_test_gate(feature_dir: Path, artifact: Path, scratch: Path) -> str:
    """Run the feature's Claude test-kit cases against a copy of the built artifact."""
    source = feature_dir / ADAPTER_DIRS["claude"] / CLAUDE_NATIVE_TESTS
    cases = sorted(source.glob("*.test.ts")) if source.is_dir() else []
    if not cases:
        raise GateFailure(
            f"{feature_dir.name}: no Claude native test cases under claude-code/{CLAUDE_NATIVE_TESTS}/"
        )
    claude, _version = _claude()
    staged = scratch / "claude-native-tests"
    shutil.copytree(artifact, staged)
    (staged / CLAUDE_NATIVE_TESTS).mkdir()
    for case in cases:
        shutil.copy2(case, staged / CLAUDE_NATIVE_TESTS / case.name)
    result = _run([claude, "plugin", "test", str(staged)], staged, _CLAUDE_ENV)
    return (
        _counted_pass(result, "claude plugin test")
        + " (native test kit, not a signed-in session)"
    )


def _foreign_sentinels(root: Path, host: str) -> dict[Path, bytes]:
    if host == "claude":
        sentinels = {
            root / "settings.json": (
                json.dumps({"theme": "dark", "env": {"FOREIGN": "1"}}, indent=2) + "\n"
            ).encode(),
            root / "plugins" / "foreign" / "marker.txt": b"foreign plugin\n",
        }
    else:
        sentinels = {
            root / "config.yml": yaml.safe_dump(
                {"theme": "dark"}, sort_keys=False
            ).encode(),
            root
            / "extensions"
            / "foreign-ext"
            / "index.ts": b"export default function () {}\n",
        }
    for path, data in sentinels.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return sentinels


def lifecycle_gate(feature_dir: Path, host: str) -> str:
    """Exercise the owned lifecycle in a disposable root with foreign sentinels."""
    with tempfile.TemporaryDirectory(prefix=f"armory-lifecycle-{host}-") as scratch:
        root = Path(scratch)
        sentinels = _foreign_sentinels(root, host)
        steps = ("install", "disable", "install", "update", "remove")
        outcomes = [
            run_action(action, host, feature_dir.name, root, feature_dir.parent)
            for action in steps
        ]
        changed = [
            str(path.relative_to(root))
            for path, data in sentinels.items()
            if path.read_bytes() != data
        ]
        if changed:
            raise GateFailure(f"{host} lifecycle changed foreign files: {changed}")
        owned = [
            root / ".armory-native" / "ownership" / f"{host}-{feature_dir.name}.json",
            root / "extensions" / feature_dir.name,
            root / ".armory-native" / "claude-plugins" / feature_dir.name,
        ]
        leftovers = [str(path.relative_to(root)) for path in owned if path.exists()]
        if leftovers:
            raise GateFailure(f"{host} lifecycle left owned state behind: {leftovers}")
    return f"{' -> '.join(steps)} in a disposable root; foreign files byte-equal ({outcomes[-1]})"


# ---------------------------------------------------------------------------
# Gate compositions
# ---------------------------------------------------------------------------


def _core_gates(report: Report, feature_dir: Path) -> str | None:
    """Toolchain, core sources, typecheck, lint and unit tests; return bun when available."""
    toolchain: dict[str, str] = {}

    def provision() -> str:
        toolchain["bun"] = toolchain_gate()
        return f"pinned bun at {toolchain['bun']} with a locked workspace install"

    report.run("toolchain", provision)
    report.run("core-sources", lambda: core_source_gate(feature_dir))
    bun = toolchain.get("bun")
    if bun is None:
        return None
    report.run("typecheck", lambda: typecheck_gate(bun))
    report.run("lint", lambda: lint_gate(bun, feature_dir))
    report.run("unit-tests", lambda: unit_test_gate(bun, feature_dir))
    return bun


def _native_gate(
    feature_dir: Path,
    host: str,
    mode: str,
    expected_version: str,
    artifact: Path | None,
) -> str:
    """Require real scenario evidence, bound to the selected production artifact."""
    driver = feature_dir / "tests" / f"{host}-smoke.py"
    if driver.is_symlink() or not driver.is_file():
        raise GateUnavailable(f"no feature-owned actual {host} smoke driver")
    with tempfile.TemporaryDirectory(prefix=f"armory-{host}-native-report-") as scratch:
        report_path = Path(scratch) / "report.json"
        argv = [
            sys.executable,
            str(driver),
            "--feature-dir",
            str(feature_dir),
            "--report",
            str(report_path),
        ]
        if artifact is not None:
            argv.extend(["--artifact", str(artifact)])
        result = _run(argv, feature_dir)
        try:
            evidence = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateFailure(f"{host} native driver produced no valid report") from exc
    if not isinstance(evidence, dict):
        raise GateFailure(f"{host} native report must be an object")
    reason = evidence.get("reasonCode")
    if not isinstance(reason, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", reason):
        reason = "native-prerequisite-unavailable"
    if result.returncode == EXIT_INCOMPLETE and evidence.get("status") == "unavailable":
        raise GateUnavailable(f"{host} {mode} smoke unavailable: {reason}")
    if artifact is not None:
        expected_digest = hashlib.sha256(
            (artifact / CONTENT_MANIFEST).read_bytes()
        ).hexdigest()
        binding = (
            evidence.get("artifact", {}).get("contentManifestSha256")
            if host == "omp" and isinstance(evidence.get("artifact"), dict)
            else evidence.get("artifactManifestSha256")
        )
        if binding != expected_digest:
            raise GateFailure(
                f"{host} native evidence does not bind the selected artifact"
            )
    scenarios = evidence.get("scenarios")
    required = {
        "success",
        "failure",
        "reopen",
        "freshness",
        "changed-during-run",
        "cancellation",
        "private-output",
        "native-text",
    }
    if (
        result.returncode != 0
        or type(evidence.get("schemaVersion")) is not int
        or evidence["schemaVersion"] != 1
        or evidence.get("host") != host
        or evidence.get("mode") != mode
        or evidence.get("version") != expected_version
        or evidence.get("status") != "passed"
        or not isinstance(scenarios, list)
        or len(scenarios) != len(required)
        or any(
            not isinstance(case, dict)
            or not isinstance(case.get("name"), str)
            or case.get("status") != "passed"
            for case in scenarios
        )
        or {case["name"] for case in scenarios} != required
    ):
        raise GateFailure(
            f"{host} actual-host scenario evidence is failed or incomplete: {reason}"
        )
    return f"{host} {expected_version} {mode}: actual execution, persistence, scoped freshness and cancellation"


def omp_native_gate(feature_dir: Path, artifact: Path | None = None) -> str:
    expected_version = json.loads(
        (EXTENSION_TYPE.repo_dir / "package.json").read_text(encoding="utf-8")
    )["devDependencies"]["@oh-my-pi/pi-coding-agent"]
    return _native_gate(feature_dir, "omp", "rpc", expected_version, artifact)


def claude_native_gate(feature_dir: Path, artifact: Path | None = None) -> str:
    _, version = _claude()
    return _native_gate(
        feature_dir, "claude", "interactive", version.split()[0], artifact
    )


def _native_smoke_gates(
    report: Report,
    feature_dir: Path,
    hosts: tuple[str, ...],
    artifacts: dict[str, Path] | None = None,
) -> None:
    for host in hosts:
        artifact = artifacts.get(host) if artifacts is not None else None
        gate = omp_native_gate if host == "omp" else claude_native_gate
        report.run(f"{host}-native-smoke", partial(gate, feature_dir, artifact))


def check_stage(feature_dir: Path, stage: str, *, native_smoke: bool = True) -> Report:
    """Run a prefix gate, with real-host OMP qualification only when requested."""
    report = Report(scope=feature_dir.name, stage=stage)
    if not native_smoke:
        report.note("native-smoke", "not-run", "live-host validation not requested")
    bun = _core_gates(report, feature_dir)
    if stage == "omp":
        if bun is not None and report.exit_code == EXIT_OK:
            build_ok = report.run(
                "omp-prefix-build", lambda: omp_prefix_build_gate(bun, feature_dir)
            )
            adapter_ok = build_ok and report.run(
                "omp-adapter", lambda: omp_source_gate(bun, feature_dir)
            )
            if native_smoke and adapter_ok:
                _native_smoke_gates(report, feature_dir, ("omp",))
        elif native_smoke:
            report.note(
                "omp-native-smoke",
                "unavailable",
                "native launch requires passed core/type/lint/unit prerequisites",
            )
    return report


def check_registered(feature_dir: Path, *, native_smoke: bool) -> Report:
    """Run every static, test-kit, build and lifecycle gate for a registered feature."""
    report = Report(scope=feature_dir.name, stage="full")
    if not native_smoke:
        report.note("native-smoke", "not-run", "live-host validation not requested")
    if not report.run("definition", lambda: definition_gate(feature_dir)):
        return report
    metadata = load_metadata(feature_dir)
    bun = _core_gates(report, feature_dir)
    missing_hosts = [host for host in NATIVE_HOSTS if host not in metadata.hosts]
    if missing_hosts:
        report.note(
            "host-coverage",
            "incomplete",
            f"no native adapter declared for {', '.join(missing_hosts)}",
        )
    with tempfile.TemporaryDirectory(prefix="armory-check-") as tmp:
        scratch = Path(tmp)
        built: dict[str, Path] = {}

        def build() -> str:
            built.update(reproducible_build_gate(feature_dir, scratch))
            return (
                f"identical bytes across two build roots for {', '.join(sorted(built))}"
            )

        if report.run("reproducible-build", build):
            if "omp" in built and bun is not None:
                report.run(
                    "omp-artifact",
                    lambda: omp_artifact_gate(
                        bun, built["omp"], list(metadata.commands)
                    ),
                )
            if "claude" in built:
                report.run(
                    "claude-static-validation",
                    lambda: claude_validate_gate(built["claude"]),
                )
                report.run(
                    "claude-native-tests",
                    lambda: claude_native_test_gate(
                        feature_dir, built["claude"], scratch
                    ),
                )
        for host in metadata.hosts:
            report.run(f"{host}-lifecycle", partial(lifecycle_gate, feature_dir, host))
        if native_smoke:
            if report.exit_code == EXIT_OK:
                _native_smoke_gates(report, feature_dir, metadata.hosts, built)
            else:
                report.note(
                    "native-smoke",
                    "unavailable",
                    "native launch requires passed static, build and lifecycle prerequisites",
                )
    report.feature_complete = (
        native_smoke and report.exit_code == EXIT_OK and not missing_hosts
    )
    return report


def check_feature(
    feature_dir: Path, *, stage: str | None, native_smoke: bool
) -> Report:
    implemented = implemented_stage(feature_dir)
    if stage is not None:
        return check_stage(feature_dir, stage)
    if implemented == "full":
        return check_registered(feature_dir, native_smoke=native_smoke)
    report = Report(scope=feature_dir.name, stage="full")
    report.note(
        "registration",
        "incomplete",
        f"{feature_dir.name} has no {EXTENSION_TYPE.definition_file}; implemented stage is '{implemented}'. "
        f"Run --stage {implemented} for the prefix gate; the full gate stays incomplete until the package is complete.",
    )
    return report


def _catalog_consumer_gates(report: Report, registered: list[str]) -> None:
    extensions_root = EXTENSION_TYPE.repo_dir

    def manifest() -> str:
        data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = (data.get("packages") or {}).get(
            EXTENSION_TYPE.manifest_section
        ) or []
        listed = {(entry["name"], entry["version"]) for entry in entries}
        expected = {
            (name, load_metadata(extensions_root / name).version) for name in registered
        }
        if listed != expected:
            raise GateFailure(
                f"manifest extensions {sorted(listed)} differ from registered {sorted(expected)}"
            )
        return f"manifest lists exactly the {len(expected)} registered extension(s)"

    def evaluator() -> str:
        failing = [
            name
            for name in registered
            if evaluate_package(extensions_root / name, EXTENSION_TYPE)["status"]
            != "PASS"
        ]
        if failing:
            raise GateFailure(f"static conformance failed for {failing}")
        return f"report-v2 static conformance PASS for {len(registered)} extension(s); live effectiveness NOT_MEASURED"

    def no_implicit_install() -> str:
        profiles = (
            yaml.safe_load((REPO_ROOT / "profiles.yaml").read_text(encoding="utf-8"))
            or {}
        )
        offenders = [
            f"profile {name}"
            for name, profile in (profiles.get("profiles") or {}).items()
            if EXTENSION_TYPE.manifest_section
            in ((profile or {}).get("packages") or {})
        ]
        preset_type = TYPES["preset"]
        for definition in sorted(
            preset_type.repo_dir.glob(f"*/{preset_type.definition_file}")
        ):
            packages = (
                parse_frontmatter(definition.read_text(encoding="utf-8")).get("preset")
                or {}
            ).get("packages")
            if (
                isinstance(packages, dict)
                and EXTENSION_TYPE.manifest_section in packages
            ):
                offenders.append(f"preset {definition.parent.name}")
        plugin = (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
        if f"{EXTENSION_TYPE.dir_name}/" in plugin:
            offenders.append("legacy .claude-plugin/plugin.json")
        if (REPO_ROOT / "hooks" / "hooks.json").exists():
            offenders.append(
                "repository hooks/hooks.json would turn the legacy plugin into a mod"
            )
        if offenders:
            raise GateFailure(
                f"native extensions must be installed explicitly; implicit references: {offenders}"
            )
        return (
            "no profile, preset or legacy plugin installs a native extension implicitly"
        )

    report.run("catalog-manifest", manifest)
    report.run("catalog-evaluator", evaluator)
    report.run("catalog-explicit-install", no_implicit_install)


def check_catalog() -> Report:
    registered = registered_features(EXTENSION_TYPE.repo_dir)
    report = Report(scope="catalog", stage="catalog")
    report.note(
        "registered-extensions",
        "passed",
        f"{len(registered)} registered: {', '.join(registered) or 'none'}",
    )
    for name in registered:
        sub = check_registered(EXTENSION_TYPE.repo_dir / name, native_smoke=False)
        for surface in sub.surfaces:
            report.note(f"{name}:{surface.name}", surface.status, surface.detail)
    _catalog_consumer_gates(report, registered)
    return report


def check_ci() -> Report:
    """Run committed offline gates without requesting authenticated native smoke."""
    report = Report(scope="ci", stage="committed")
    for feature_dir in feature_directories(EXTENSION_TYPE.repo_dir):
        try:
            stage = implemented_stage(feature_dir)
        except GateFailure as exc:
            report.note(f"{feature_dir.name}:stage", "failed", str(exc))
            continue
        sub = (
            check_registered(feature_dir, native_smoke=False)
            if stage == "full"
            else check_stage(feature_dir, stage, native_smoke=False)
        )
        for surface in sub.surfaces:
            report.note(
                f"{feature_dir.name}[{stage}]:{surface.name}",
                surface.status,
                surface.detail,
            )
    catalog = check_catalog()
    for surface in catalog.surfaces:
        if ":" not in surface.name:
            report.note(f"catalog:{surface.name}", surface.status, surface.detail)
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run native extension gates. --feature runs the full static/type/package/unit/integration "
            "gate of a registered feature; --stage runs the development-prefix gate of an unregistered "
            "feature (OMP includes local/manual real-host proof); --native-smoke adds real-host "
            "proof to a full feature; --all --catalog verifies every registered extension and "
            "its catalog consumers; --ci runs committed credential-free offline gates only, "
            "with live-host validation reported as not requested."
        ),
        epilog="Exit status: 0 passed, 1 failed, 2 invalid arguments, 3 incomplete or unavailable.",
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--feature", metavar="NAME", help="feature directory under extensions/"
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="every registered extension (requires --catalog)",
    )
    selection.add_argument(
        "--ci",
        action="store_true",
        help="committed credential-free offline gates; no live native smoke",
    )
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="with --all: verify catalog consumers too",
    )
    parser.add_argument(
        "--native-smoke",
        action="store_true",
        help="with --feature: require real-host proof",
    )
    parser.add_argument(
        "--stage", choices=STAGES, help="with --feature: development-prefix gate"
    )
    args = parser.parse_args(argv)
    if args.all != args.catalog:
        parser.error("--all and --catalog must be given together")
    if (args.native_smoke or args.stage) and not args.feature:
        parser.error("--native-smoke and --stage require --feature")
    if args.native_smoke and args.stage:
        parser.error(
            "--native-smoke checks a complete feature; it cannot be combined with --stage"
        )
    if args.feature is not None:
        try:
            feature_dir = resolve_feature_dir(args.feature, EXTENSION_TYPE.repo_dir)
        except BuildError as exc:
            parser.error(str(exc))
        if args.stage and (feature_dir / EXTENSION_TYPE.definition_file).is_file():
            parser.error(
                f"--stage applies to unregistered prefix features; {args.feature} is registered"
            )
        args.feature_dir = feature_dir
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.ci:
            report = check_ci()
        elif args.all:
            report = check_catalog()
        else:
            report = check_feature(
                args.feature_dir, stage=args.stage, native_smoke=args.native_smoke
            )
    except GateFailure as exc:
        report = Report(scope=args.feature or "extensions", stage=args.stage or "full")
        report.note("stage-selection", "failed", str(exc))
    print(json.dumps(report.as_dict(), indent=2))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
