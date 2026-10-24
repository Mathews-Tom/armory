#!/usr/bin/env python3
"""Versioned project bridge for Run Preflight; never a live OMP launcher."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypedDict, cast

if TYPE_CHECKING:
    from scripts.omp_skillsbench import OmpCell, OmpRunContract, OmpTarget

SCHEMA_VERSION: Final = 1
CORE_VERSION: Final = "1.0.0"
ADAPTER_ID: Final = "omp-skillsbench"
ADAPTER_VERSION: Final = 1


class PreflightAdmissionError(ValueError):
    """Missing, incompatible or stale project-managed admission."""


class InvocationCell(TypedDict):
    taskId: str
    condition: str
    targetId: str
    repetition: int
    conditionHash: str


class RunnerInvocation(TypedDict):
    adapterId: str
    adapterVersion: int
    targetId: str
    targetModel: str
    targetThinking: str
    profile: str
    cell: InvocationCell
    wallSeconds: int
    checkpointRoot: str


@dataclass(frozen=True)
class PreflightProjectConfig:
    """Explicit selected package, project and immutable raw config binding."""

    path: Path
    sha256: str
    package_root: Path
    helper_path: Path
    project_root: Path
    contract_path: Path
    bridge_argv: tuple[str, ...]


@dataclass(frozen=True)
class ProjectAdmission:
    """Complete helper-issued record, not a boolean or mutable declaration."""

    config: PreflightProjectConfig
    declaration_path: Path
    declaration_sha256: str
    declaration_json: str
    record_json: str
    purpose: str
    status: str


class DispatchInputs(TypedDict):
    """Adapter-owned files that a declaration must bind before dispatch."""

    source: tuple[Path, ...]
    config: tuple[Path, ...]
    data: tuple[Path, ...]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PreflightAdmissionError("preflight protocol requires a JSON object")
    return cast(dict[str, object], value)


def _read_object(path: Path) -> tuple[bytes, dict[str, object]]:
    try:
        raw = path.read_bytes()
        return raw, _object(json.loads(raw))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PreflightAdmissionError("cannot read preflight JSON input") from exc


def _absolute_path(value: object) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise PreflightAdmissionError("preflight paths must be explicit and absolute")
    return Path(value).resolve()


def load_project_config(path: Path) -> PreflightProjectConfig:
    """Bootstrap only from the configured source-prefix or installed package."""
    path = _absolute_path(str(path))
    raw, value = _read_object(path)
    if (
        type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != SCHEMA_VERSION
        or value.get("coreVersion") != CORE_VERSION
        or value.get("adapterId") != ADAPTER_ID
        or type(value.get("adapterVersion")) is not int
        or value.get("adapterVersion") != ADAPTER_VERSION
    ):
        raise PreflightAdmissionError("unsupported preflight config version or adapter")
    package_root = _absolute_path(value.get("packageRoot"))
    project_root = _absolute_path(value.get("projectRoot"))
    contract_path = _absolute_path(value.get("contractPath"))
    relative = value.get("helperPath")
    if relative not in ("helpers/cli.ts", "helpers/cli.js"):
        raise PreflightAdmissionError("unsupported configured preflight helper path")
    helper = (package_root / relative).resolve()
    if not helper.is_relative_to(package_root) or not helper.is_file():
        raise PreflightAdmissionError(
            "configured preflight helper is missing or escapes package"
        )
    if not project_root.is_dir() or not contract_path.is_file():
        raise PreflightAdmissionError(
            "configured project or frozen contract is missing"
        )
    argv = value.get("bridgeArgv")
    if (
        not isinstance(argv, list)
        or len(argv) < 2
        or not all(isinstance(item, str) and item for item in argv)
    ):
        raise PreflightAdmissionError("preflight bridge requires explicit trusted argv")
    bridge_argv = tuple(cast(list[str], argv))
    if not all(Path(argument).is_absolute() for argument in bridge_argv[:2]):
        raise PreflightAdmissionError(
            "preflight bridge requires an absolute executable and entry script"
        )
    return PreflightProjectConfig(
        path,
        _sha256(raw),
        package_root,
        helper,
        project_root,
        contract_path,
        bridge_argv,
    )


def derive_runner_invocation(
    contract: OmpRunContract,
    cell: OmpCell,
    target: OmpTarget,
    receipt_root: Path,
) -> RunnerInvocation:
    """Derive the actual runner tuple independently of declaration contents."""
    if cell.target_id != target.id:
        raise PreflightAdmissionError("actual cell and target do not match")
    return RunnerInvocation(
        adapterId=ADAPTER_ID,
        adapterVersion=ADAPTER_VERSION,
        targetId=target.id,
        targetModel=target.model,
        targetThinking=target.thinking,
        profile=contract.profile,
        cell=InvocationCell(
            taskId=cell.task_id,
            condition=cell.condition,
            targetId=cell.target_id,
            repetition=cell.repetition,
            conditionHash=cell.condition_hash,
        ),
        wallSeconds=contract.max_time_seconds + 30,
        checkpointRoot=str(receipt_root.resolve()),
    )


def required_dispatch_inputs(
    config: PreflightProjectConfig, contract: OmpRunContract, cell: OmpCell
) -> DispatchInputs:
    """Expose this adapter's fixed consumed inputs, not an import-graph scanner."""
    import yaml

    from scripts.run_skillsbench import _DEFAULT_CORPUS_PATH
    from scripts.validate_skillsbench import _DEFAULT_STRATA_PATH

    project_root = Path(__file__).resolve().parent.parent
    if config.project_root != project_root:
        raise PreflightAdmissionError("preflight project differs from actual adapter")
    task = next(
        (task for task in contract.corpus.tasks if task.id == cell.task_id), None
    )
    if task is None:
        raise PreflightAdmissionError("actual cell task is not in the frozen contract")
    try:
        corpus = _object(
            yaml.safe_load(_DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
        )
        model_fit = _object(corpus.get("model_fit"))
        model_config = model_fit.get("config")
        if not isinstance(model_config, str) or not model_config:
            raise PreflightAdmissionError("corpus model-fit configuration is missing")
        model_path = (_DEFAULT_CORPUS_PATH.parent / model_config).resolve()
        if not model_path.is_relative_to(project_root):
            raise PreflightAdmissionError("corpus configuration escapes actual project")
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PreflightAdmissionError(
            "cannot read actual corpus configuration"
        ) from exc
    sources = tuple(
        project_root / "scripts" / name
        for name in (
            "omp_preflight.py",
            "omp_preflight_cli.py",
            "omp_skillsbench_dispatch.py",
            "omp_skillsbench.py",
            "omp_skillsbench_results.py",
            "run_skillsbench.py",
            "model_fit.py",
            "validate_skillsbench.py",
        )
    )
    bridge_files = (Path(config.bridge_argv[1]).resolve(),)
    return DispatchInputs(
        source=tuple(
            dict.fromkeys(
                (
                    *sources,
                    *bridge_files,
                    *(item.source for item in contract.treatments),
                )
            )
        ),
        config=tuple(
            dict.fromkeys(
                (config.path, config.contract_path, model_path, _DEFAULT_STRATA_PATH)
            )
        ),
        data=tuple(
            dict.fromkeys(
                (
                    _DEFAULT_CORPUS_PATH,
                    Path(task.source_path.split("#", 1)[0]).resolve(),
                )
            )
        ),
    )


def _current_declaration(
    admission: ProjectAdmission,
) -> tuple[PreflightProjectConfig, bytes, dict[str, object]]:
    current = load_project_config(admission.config.path)
    if current != admission.config:
        raise PreflightAdmissionError("preflight project configuration changed")
    raw, declaration = _read_object(admission.declaration_path)
    if (
        _sha256(raw) != admission.declaration_sha256
        or raw.decode("utf-8") != admission.declaration_json
        or declaration.get("purpose") != admission.purpose
    ):
        raise PreflightAdmissionError(
            "preflight declaration or admission scope changed"
        )
    return current, raw, declaration


def canonical_dispatch_contract(
    admission: ProjectAdmission, contract: OmpRunContract, cell: OmpCell
) -> OmpRunContract:
    """Refuse omitted inputs or caller drift, then return a fresh private snapshot."""
    from scripts.omp_skillsbench import declared_omp_cells, load_omp_run_contract

    current, _raw, declaration = _current_declaration(admission)
    try:
        canonical = load_omp_run_contract(current.contract_path)
        if canonical != contract or cell not in declared_omp_cells(canonical):
            raise PreflightAdmissionError(
                "actual contract or cell differs from canonical bound inputs"
            )
        required = required_dispatch_inputs(current, canonical, cell)
        inputs = _object(declaration.get("inputs"))
        for category, paths in (
            ("source", required["source"]),
            ("config", required["config"]),
            ("data", required["data"]),
        ):
            entries = inputs.get(category)
            if not isinstance(entries, list):
                raise PreflightAdmissionError("actual dispatch input bindings missing")
            bindings = {
                binding.get("path"): binding.get("sha256")
                for binding in (_object(entry) for entry in entries)
                if isinstance(binding.get("path"), str)
            }
            for path in paths:
                if bindings.get(str(path)) != _sha256(path.read_bytes()):
                    raise PreflightAdmissionError(
                        f"actual dispatch {category} input is missing or changed"
                    )
    except (OSError, UnicodeError, ValueError) as exc:
        raise PreflightAdmissionError(
            "actual dispatch inputs are missing, changed or divergent"
        ) from exc
    return canonical


def _complete_record(
    value: object,
    config: PreflightProjectConfig,
    raw: bytes,
    declaration: dict[str, object],
) -> dict[str, object]:
    """Check the versioned complete envelope; the helper owns admission rules."""
    record = _object(value)
    keys = {
        "schemaVersion",
        "coreVersion",
        "issuedAt",
        "expiresAt",
        "declarationSha256",
        "configSha256",
        "invocationSha256",
        "factsSha256",
        "scopeSha256",
        "recordSha256",
        "declaration",
        "config",
        "facts",
        "scope",
        "capabilities",
    }
    if set(record) != keys or (
        type(record["schemaVersion"]) is not int
        or record["schemaVersion"] != SCHEMA_VERSION
        or record["coreVersion"] != CORE_VERSION
        or record["configSha256"] != config.sha256
        or record["declarationSha256"] != _sha256(raw)
        or record["declaration"] != declaration
        or record["config"] != _read_object(config.path)[1]
    ):
        raise PreflightAdmissionError(
            "incomplete or mismatched preflight admission record"
        )
    for key in (
        "declarationSha256",
        "configSha256",
        "invocationSha256",
        "factsSha256",
        "scopeSha256",
        "recordSha256",
    ):
        digest = record[key]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise PreflightAdmissionError("invalid preflight admission digest")
    if not all(
        isinstance(record[key], str) and record[key]
        for key in ("issuedAt", "expiresAt")
    ):
        raise PreflightAdmissionError("missing preflight admission freshness")
    facts = _object(record["facts"])
    if set(facts) != {
        "config",
        "declaration",
        "helper",
        "source",
        "configs",
        "data",
        "identityFile",
        "identity",
        "checkpoint",
        "projectRoot",
        "packageRoot",
    }:
        raise PreflightAdmissionError("incomplete preflight observation facts")
    file_keys = {"path", "sha256", "realPath", "device", "inode", "size", "modifiedNs"}
    for name in ("config", "declaration", "helper", "identityFile"):
        if set(_object(facts[name])) != file_keys:
            raise PreflightAdmissionError("incomplete preflight file fact")
    for name in ("source", "configs", "data"):
        entries = facts[name]
        if (
            not isinstance(entries, list)
            or not entries
            or any(set(_object(entry)) != file_keys for entry in entries)
        ):
            raise PreflightAdmissionError("incomplete preflight file bindings")
    for name in ("checkpoint", "projectRoot", "packageRoot"):
        if set(_object(facts[name])) != {
            "path",
            "realPath",
            "device",
            "inode",
            "mode",
            "uid",
            "gid",
            "writable",
        }:
            raise PreflightAdmissionError("incomplete preflight directory fact")
    if set(_object(facts["identity"])) != {
        "schemaVersion",
        "provider",
        "profile",
        "accountFingerprint",
        "kind",
        "auth",
        "observedAt",
        "expiresAt",
    }:
        raise PreflightAdmissionError("incomplete preflight identity fact")
    scope = _object(record["scope"])
    if set(scope) != {
        "runId",
        "purpose",
        "accountFingerprint",
        "authorization",
        "invocation",
    } or (
        scope["runId"] != declaration.get("runId")
        or scope["purpose"] != declaration.get("purpose")
        or scope["invocation"] != declaration.get("invocation")
        or scope["authorization"]
        not in cast(list[object], declaration.get("authorizations", []))
    ):
        raise PreflightAdmissionError("incomplete or mismatched preflight scope")
    if record["capabilities"] != {
        "wallSeconds": 630,
        "runnerMaxSeconds": 600,
        "calls": "caller-discipline",
        "workers": "caller-discipline",
        "concurrency": "caller-discipline",
        "tokens": "unsupported",
        "currency": "unsupported",
    }:
        raise PreflightAdmissionError("unsupported preflight runner capabilities")
    return record


def _helper(
    config: PreflightProjectConfig, operation: str, arguments: list[str]
) -> dict[str, object]:
    runtime = shutil.which("bun")
    if runtime is None:
        raise PreflightAdmissionError("configured preflight helper requires Bun")
    try:
        completed = subprocess.run(
            [
                runtime,
                str(config.helper_path),
                operation,
                "--config",
                str(config.path),
                *arguments,
            ],
            cwd=config.project_root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        value = _object(json.loads(completed.stdout))
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise PreflightAdmissionError(
            "preflight helper unavailable or invalid protocol"
        ) from exc
    if (
        type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != SCHEMA_VERSION
        or value.get("coreVersion") != CORE_VERSION
        or value.get("status") not in ("ready", "blocked", "unknown")
        or not isinstance(value.get("reasons"), list)
        or not isinstance(value.get("quota"), dict)
        or not isinstance(value.get("admitted"), bool)
        or "admission" not in value
        or completed.returncode != 0
    ):
        raise PreflightAdmissionError(
            "preflight helper rejected admission or protocol version"
        )
    return value


def issue_admission(config_path: Path, declaration_path: Path) -> ProjectAdmission:
    """Observe prerequisites without ever launching the managed child."""
    config = load_project_config(config_path)
    declaration_path = _absolute_path(str(declaration_path))
    raw, declaration = _read_object(declaration_path)
    if declaration.get("configSha256") != config.sha256:
        raise PreflightAdmissionError(
            "preflight config digest differs from declaration"
        )
    purpose = declaration.get("purpose")
    if purpose not in ("synthetic-local-sentinel", "managed"):
        raise PreflightAdmissionError("unsupported preflight declaration purpose")
    report = _helper(config, "check", ["--declaration", str(declaration_path)])
    record = report.get("admission")
    if not isinstance(record, dict) or report["status"] == "blocked":
        raise PreflightAdmissionError(
            "preflight prerequisites do not admit this invocation"
        )
    record = _complete_record(record, config, raw, declaration)
    return ProjectAdmission(
        config,
        declaration_path,
        _sha256(raw),
        raw.decode("utf-8"),
        json.dumps(record, sort_keys=True, separators=(",", ":")),
        purpose,
        cast(str, report["status"]),
    )


def revalidate_admission(
    admission: ProjectAdmission, invocation: RunnerInvocation
) -> None:
    """Consume the complete record immediately at the owned runner boundary."""
    current, raw, declaration = _current_declaration(admission)
    with tempfile.TemporaryDirectory(prefix="omp_preflight_admit_") as directory:
        record_path = Path(directory) / "record.json"
        invocation_path = Path(directory) / "invocation.json"
        record_path.write_text(admission.record_json, encoding="utf-8")
        invocation_path.write_text(json.dumps(invocation), encoding="utf-8")
        report = _helper(
            current,
            "admit",
            [
                "--declaration",
                str(admission.declaration_path),
                "--record",
                str(record_path),
                "--invocation",
                str(invocation_path),
            ],
        )
    if report.get("admitted") is not True or not isinstance(
        report.get("admission"), dict
    ):
        raise PreflightAdmissionError(
            "preflight admission is stale, missing or unauthorized"
        )
    _complete_record(report["admission"], current, raw, declaration)


def synthetic_sentinel(config_path: Path, declaration_path: Path) -> dict[str, object]:
    """Explicit synthetic bridge: one real Python pass child, never OMP argv."""
    from scripts.omp_skillsbench import declared_omp_cells, load_omp_run_contract
    from scripts.omp_skillsbench_dispatch import CellDispatchError, dispatch_cell

    spawns = 0

    def python_pass(
        _command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal spawns
        # Literal Python-pass argv only; never forward the prepared OMP argv.
        completed = subprocess.run(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=cast(int, kwargs["timeout"]),
        )
        spawns += 1
        return completed

    status = "blocked"
    try:
        admission = issue_admission(config_path, declaration_path)
        if admission.purpose != "synthetic-local-sentinel":
            raise PreflightAdmissionError(
                "bridge requires synthetic-local-sentinel authority"
            )
        declaration = _object(json.loads(admission.declaration_json))
        invocation = _object(declaration.get("invocation"))
        contract = load_omp_run_contract(admission.config.contract_path)
        cells = [
            cell
            for cell in declared_omp_cells(contract)
            if dict(
                derive_runner_invocation(
                    contract,
                    cell,
                    next(
                        target
                        for target in contract.targets
                        if target.id == cell.target_id
                    ),
                    Path(cast(str, invocation.get("checkpointRoot"))),
                )
            )
            == invocation
        ]
        if len(cells) != 1:
            raise PreflightAdmissionError(
                "synthetic declaration does not select one actual cell"
            )
        dispatch_cell(
            contract,
            cells[0],
            Path(cast(str, invocation["checkpointRoot"])),
            python_pass,
            admission=admission,
        )
        # A pass child cannot produce a valid OMP receipt.
        raise PreflightAdmissionError(
            "Python pass cannot produce an OMP terminal receipt"
        )
    except CellDispatchError:
        status = "terminal-receipt-unavailable" if spawns == 1 else "blocked"
    except (PreflightAdmissionError, ValueError, OSError, KeyError, TypeError):
        status = "blocked"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "coreVersion": CORE_VERSION,
        "status": status,
        "managedSpawns": spawns,
        "providerCalls": 0,
        "reasons": [status],
    }
