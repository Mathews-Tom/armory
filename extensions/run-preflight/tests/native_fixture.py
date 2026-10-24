"""Disposable real project declarations for the two native qualification drivers.

This module launches nothing. The installed helper invokes the existing project
CLI/library, which owns the actual synthetic Python-pass dispatch boundary.
"""

from __future__ import annotations

import hashlib
import importlib
import json as jsonlib
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def _save(path: Path, value: object) -> None:
    data = (jsonlib.dumps(value, sort_keys=True, ensure_ascii=False) + "\n").encode()
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _binding(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@dataclass(frozen=True, slots=True)
class Fixture:
    config: Path
    declaration: Path
    identity: Path
    checkpoint: Path
    ready: Path
    release: Path
    pid: Path

    def command(self, action: str, json: bool = True) -> str:
        if action not in {"check", "probe"}:
            raise ValueError("native fixture action must be explicit check or probe")
        selected = jsonlib.dumps(
            {"config": str(self.config), "declaration": str(self.declaration)},
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return f"/armory-preflight {action} {selected}" + (" --json" if json else "")

    def stale_identity(self) -> None:
        descriptor = os.open(self.identity, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(b"\n")

    def expire_declaration(self) -> None:
        value: dict[str, Any] = jsonlib.loads(self.declaration.read_text())
        now = datetime.now(UTC)
        value["issuedAt"] = (
            (now - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
        )
        value["expiresAt"] = (
            (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        )
        _save(self.declaration, value)

    def release_bridge(self) -> None:
        _save(self.release, {"release": True})


def make_fixture(
    feature_dir: Path, artifact: Path, root: Path, *, barrier: bool = False
) -> Fixture:
    """Create one fresh authority in a new owned root; never modify study inputs."""
    feature = feature_dir.resolve(strict=True)
    repository = feature.parent.parent
    if feature.name != "run-preflight" or feature.parent.name != "extensions":
        raise ValueError("select the actual Run Preflight project source")
    package = artifact.resolve(strict=True)
    helper = package / "helpers" / "cli.js"
    if helper.is_symlink() or not helper.is_file():
        raise ValueError("select the detached production package with its own helper")
    root = root.parent.resolve(strict=True) / root.name
    root.mkdir(mode=0o700)
    checkpoint = root / "checkpoint"
    checkpoint.mkdir(mode=0o700)
    fixture = Fixture(
        config=root / "project.json",
        declaration=root / "declaration.json",
        identity=root / "identity.json",
        checkpoint=checkpoint,
        ready=root / "bridge-ready.json",
        release=root / "bridge-release.json",
        pid=root / "bridge.pid",
    )
    # Select this real project explicitly. A previously imported different checkout
    # is not an acceptable fallback, including in an embedding test process.
    sys.path.insert(0, str(repository))
    preflight = importlib.import_module("scripts.omp_preflight")
    skillsbench = importlib.import_module("scripts.omp_skillsbench")
    preflight_file = preflight.__file__
    skillsbench_file = skillsbench.__file__
    if (
        preflight_file is None
        or Path(preflight_file).resolve() != repository / "scripts" / "omp_preflight.py"
    ):
        raise RuntimeError("native fixture imported a different project adapter")
    if (
        skillsbench_file is None
        or Path(skillsbench_file).resolve()
        != repository / "scripts" / "omp_skillsbench.py"
    ):
        raise RuntimeError("native fixture imported a different frozen-contract loader")
    entry = repository / "scripts" / "omp_preflight_cli.py"
    if barrier:
        wrapper = root / "bound-bridge.py"
        body = f"""from pathlib import Path
import os
import sys
import time

pid = Path({str(fixture.pid)!r})
fd = os.open(pid, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write(str(os.getpid()))
ready = Path({str(fixture.ready)!r})
fd = os.open(ready, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
os.close(fd)
release = Path({str(fixture.release)!r})
deadline = time.monotonic() + 25
while not release.exists():
    if time.monotonic() >= deadline:
        raise SystemExit(9)
    time.sleep(0.01)
os.execv(sys.executable, [sys.executable, {str(entry)!r}, *sys.argv[1:]])
"""
        descriptor = os.open(
            wrapper, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w") as stream:
            stream.write(body)
        entry = wrapper
    _save(
        fixture.config,
        {
            "schemaVersion": 1,
            "coreVersion": "1.0.0",
            "adapterId": "omp-skillsbench",
            "adapterVersion": 1,
            "packageRoot": str(package),
            "helperPath": "helpers/cli.js",
            "projectRoot": str(repository),
            "contractPath": str(repository / "evals" / "skillsbench" / "omp_run.yaml"),
            "bridgeArgv": [sys.executable, str(entry), "--synthetic-sentinel"],
        },
    )
    config = preflight.load_project_config(fixture.config)
    contract = skillsbench.load_omp_run_contract(config.contract_path)
    cell = skillsbench.declared_omp_cells(contract)[0]
    target = next(target for target in contract.targets if target.id == cell.target_id)
    invocation = preflight.derive_runner_invocation(contract, cell, target, checkpoint)
    inventory = preflight.required_dispatch_inputs(config, contract, cell)
    inputs: dict[str, Any] = {
        category: [_binding(path) for path in paths]
        for category, paths in inventory.items()
    }
    now = datetime.now(UTC)
    issued = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    expires = (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    fingerprint = "native-local-sentinel-no-account"
    _save(
        fixture.identity,
        {
            "schemaVersion": 1,
            "provider": "synthetic-local",
            "profile": contract.profile,
            "accountFingerprint": fingerprint,
            "kind": "synthetic-local",
            "auth": "not-applicable",
            "observedAt": issued,
            "expiresAt": expires,
        },
    )
    inputs["identity"] = _binding(fixture.identity)
    canonical = jsonlib.dumps(
        invocation, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    _save(
        fixture.declaration,
        {
            "schemaVersion": 1,
            "runId": "native-explicit-local-sentinel",
            "purpose": "synthetic-local-sentinel",
            "issuedAt": issued,
            "expiresAt": expires,
            "configSha256": _binding(fixture.config)["sha256"],
            "invocation": invocation,
            "inputs": inputs,
            "checkpoint": {"path": str(checkpoint)},
            "limits": {
                **{
                    name: {"value": 1, "required": False}
                    for name in ("calls", "workers", "concurrency")
                },
                "wallSeconds": {"value": 630, "required": True},
                "tokens": None,
                "currency": None,
            },
            "quota": {
                "status": "unknown",
                "observedAt": issued,
                "expiresAt": expires,
                "reason": "No account or provider observation requested",
                "source": "explicit-native-synthetic-qualification",
                "remainingCalls": None,
            },
            "authorizations": [
                {
                    "runId": "native-explicit-local-sentinel",
                    "purpose": "synthetic-local-sentinel",
                    "accountFingerprint": fingerprint,
                    "scope": "local-sentinel-only",
                    "invocationSha256": hashlib.sha256(canonical.encode()).hexdigest(),
                    "acknowledgeUnknownQuota": True,
                    "issuedAt": issued,
                    "expiresAt": expires,
                }
            ],
        },
    )
    return fixture
