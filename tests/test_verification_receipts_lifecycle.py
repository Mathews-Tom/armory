"""Durable real receipt evidence survives both native installation lifecycles.

These are filesystem/process tests, not authenticated native-host sessions. The
installed, declared Claude helper is a real CLI in both host artifacts; using it
here deliberately creates Claude-context receipts, including in the OMP case.
No public feature definition or exercised-host compatibility claim is added.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.build_extensions import require_bun
from scripts.extension_lifecycle import (
    HostLayout,
    LifecycleError,
    payload_problems,
    run_action,
)
from scripts.frontmatter import parse_frontmatter
from scripts.package_types import TYPES

NAME = "verification-receipts"
SOURCE = TYPES["extension"].repo_dir / NAME
FIXTURE = TYPES["extension"].repo_dir / "_fixtures" / "fixture-wordcount"


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _hashes(root: Path) -> dict[str, str]:
    return {
        relative: hashlib.sha256(data).hexdigest()
        for relative, data in _tree(root).items()
    }


@pytest.fixture
def receipt_source(tmp_path: Path) -> Path:
    """Give only this detached source an unclaimed synthetic definition."""
    feature = tmp_path / "sources" / NAME
    shutil.copytree(SOURCE, feature)
    metadata = parse_frontmatter((FIXTURE / "EXTENSION.md").read_text("utf-8"))
    metadata.update(
        name=NAME,
        description="Synthetic lifecycle declaration for the real receipts implementation.",
        metadata={"version": "1.0.0"},
    )
    metadata["extension"].update(
        hosts={
            "omp": {"entry": "omp/index.ts"},
            "claude": {"entry": "claude-code/register.ts"},
        },
        commands=["armory-verify", "armory-evidence"],
        helpers=["helpers/claude-cli.ts"],
        storage="user-private",
        permissions=["fs.read", "fs.write", "process.spawn"],
    )
    # Never inherit a fictional fixture's host-qualification claims.
    metadata["extension"].pop("tested", None)
    (feature / "EXTENSION.md").write_text(
        f"---\n{yaml.safe_dump(metadata, sort_keys=False)}---\n"
        "# Synthetic, unclaimed lifecycle test package\n",
        encoding="utf-8",
    )
    return feature


def _release(feature: Path, version: str) -> None:
    definition = feature / "EXTENSION.md"
    metadata = parse_frontmatter(definition.read_text("utf-8"))
    metadata["metadata"]["version"] = version
    definition.write_text(
        f"---\n{yaml.safe_dump(metadata, sort_keys=False)}---\n"
        "# Synthetic, unclaimed lifecycle test package\n",
        encoding="utf-8",
    )
    source = feature / "core" / "index.ts"
    lines = source.read_text("utf-8").splitlines(keepends=True)
    declarations = [
        index
        for index, line in enumerate(lines)
        if line.startswith("export const FEATURE_VERSION = ")
    ]
    assert len(declarations) == 1
    lines[declarations[0]] = f'export const FEATURE_VERSION = "{version}" as const;\n'
    source.write_text("".join(lines), encoding="utf-8")


def _repository(tmp_path: Path) -> tuple[Path, bytes]:
    repository = tmp_path / "repository"
    repository.mkdir()
    inputs = b"20\n22\n"
    (repository / "input.txt").write_bytes(inputs)
    # A real configured check reads and validates declared inputs, then produces
    # derived output. It does not merely echo a success token.
    (repository / "gate.py").write_text(
        "import hashlib, json\n"
        "from pathlib import Path\n"
        "data = Path('input.txt').read_bytes()\n"
        "total = sum(int(line) for line in data.splitlines())\n"
        "assert total == 42, 'unexpected input total'\n"
        "print(json.dumps({'sha256': hashlib.sha256(data).hexdigest(), "
        "'sum': total}, sort_keys=True))\n",
        encoding="utf-8",
    )
    configuration = {
        "schemaVersion": 1,
        "configId": "lifecycle-real-gate",
        "gates": {
            "check": {
                "criterionId": "input-total",
                "kind": "integration",
                "executable": sys.executable,
                "args": ["-I", "gate.py"],
                "cwd": ".",
                "timeoutMs": 5000,
                "maxOutputBytes": 4096,
                "requiresCompleteOutput": True,
                "scope": {
                    "paths": ["input.txt", "gate.py"],
                    "configPaths": ["receipts.json"],
                    "environmentNames": [],
                    "datasetIdentity": None,
                },
            }
        },
    }
    (repository / "receipts.json").write_text(
        json.dumps(configuration), encoding="utf-8"
    )
    git_config = tmp_path / "empty-git-config"
    git_config.write_bytes(b"")
    template = tmp_path / "empty-git-template"
    template.mkdir()
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(git_config),
        "GIT_CONFIG_SYSTEM": str(git_config),
        "GIT_TERMINAL_PROMPT": "0",
    }
    for arguments in (
        ["init", "--quiet", f"--template={template}"],
        ["add", "."],
        [
            "-c",
            "user.name=Armory Fixture",
            "-c",
            "user.email=armory-fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "synthetic gate inputs",
        ],
    ):
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            env=environment,
            check=True,
            capture_output=True,
            timeout=30,
        )
    output = (
        json.dumps(
            {"sha256": hashlib.sha256(inputs).hexdigest(), "sum": 42}, sort_keys=True
        )
        + "\n"
    ).encode()
    return repository, output


def _cli(
    helper: Path, action: str, repository: Path, data_root: Path
) -> dict[str, Any]:
    arguments = [
        require_bun(),
        str(helper),
        action,
        "--repo",
        str(repository),
        "--config",
        "receipts.json",
        "--data-root",
        str(data_root),
        "--session",
        "lifecycle-test-session",
        "--account",
        "lifecycle-test-account",
        "--work-context",
        "lifecycle-test-work",
    ]
    if action == "run":
        arguments.extend(["--gate", "check"])
    result = subprocess.run(
        arguments,
        cwd=repository.parent,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value: dict[str, Any] = json.loads(result.stdout)
    return value


@pytest.mark.parametrize("host", ["omp", "claude"])
def test_real_receipt_survives_lifecycle_update_rollback_and_refusal(
    host: str, receipt_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host_root = tmp_path / "host-root"
    host_root.mkdir()
    layout = HostLayout(root=host_root.resolve(), host=host, feature=NAME)
    foreign_package = host_root / "foreign-package"
    foreign_package.mkdir()
    foreign_files = {
        foreign_package / "package.json": b'{ "name": "foreign", "private": true }\n',
        foreign_package / "settings.json": b'{ "keep": [1, 2], "enabled": true }\n',
        foreign_package / "index.ts": b"export default function () {}\n",
    }
    for path, data in foreign_files.items():
        path.write_bytes(data)
    if host == "omp":
        original_config = (
            b"# foreign configuration\ntheme: dark\nextensions:\n- ./foreign-package\n"
        )
    else:
        original_config = (
            json.dumps(
                {
                    "model": "foreign-model",
                    "env": {
                        "CLAUDE_CODE_PLUGIN_DIRS": str(foreign_package),
                        "KEEP": "1",
                    },
                },
                indent=2,
            )
            + "\n"
        ).encode()
    layout.config.write_bytes(original_config)
    repository, output = _repository(tmp_path)
    # Keep evidence in the same target root, but outside the owned payload. A
    # broad installation cleanup must not delete a user's durable receipt store.
    data_root = host_root / "private-evidence"
    assert not data_root.is_relative_to(layout.payload)

    def act(action: str) -> str:
        return run_action(action, host, NAME, host_root, receipt_source.parent)

    def assert_foreign() -> None:
        assert {path: path.read_bytes() for path in foreign_files} == foreign_files

    assert "installed" in act("install")
    assert_foreign()
    enabled_config = layout.config.read_bytes()
    installed_payload = _tree(layout.payload)
    projection = _cli(
        layout.payload / "helpers" / "claude-cli.js", "run", repository, data_root
    )
    assert (projection["status"], projection["applicability"], projection["proof"]) == (
        "passed",
        "current",
        True,
    )
    assert projection["output"] == {
        "sha256": hashlib.sha256(output).hexdigest(),
        "capturedBytes": len(output),
        "totalBytes": len(output),
        "truncated": False,
    }
    receipt_files = list(data_root.rglob(f"receipts/{projection['executionId']}.json"))
    output_files = list(data_root.rglob(f"runs/{projection['executionId']}/output.bin"))
    assert len(receipt_files) == len(output_files) == 1
    receipt = json.loads(receipt_files[0].read_bytes())
    assert receipt["plan"]["gateId"] == "check"
    assert receipt["plan"]["context"]["host"] == "claude"
    assert receipt["result"]["status"] == "passed"
    assert receipt["result"]["exitCode"] == 0
    assert receipt["artifact"]["sha256"] == hashlib.sha256(output).hexdigest()
    assert output_files[0].read_bytes() == output
    durable_bytes = _tree(data_root)
    durable_hashes = _hashes(data_root)
    assert _tree(layout.payload) == installed_payload

    def assert_evidence() -> None:
        assert _tree(data_root) == durable_bytes
        assert _hashes(data_root) == durable_hashes
        assert_foreign()

    act("disable")
    assert _tree(layout.payload) == installed_payload
    if host == "omp":
        config = yaml.safe_load(layout.config.read_text("utf-8"))
        assert config["disabledExtensions"] == [layout.omp_disabled_id]
        config.pop("disabledExtensions")
        assert config == yaml.safe_load(original_config)
    else:
        assert layout.config.read_bytes() == original_config
    assert_evidence()

    assert "re-enabled" in act("install")
    assert layout.config.read_bytes() == enabled_config
    assert _tree(layout.payload) == installed_payload
    assert_evidence()

    source_before = (receipt_source / "core" / "index.ts").read_bytes()
    _release(receipt_source, "1.0.1")
    assert (receipt_source / "core" / "index.ts").read_bytes() != source_before
    act("update")
    updated_payload = _tree(layout.payload)
    assert updated_payload["core/index.ts"] != installed_payload["core/index.ts"]
    assert (
        updated_payload["helpers/claude-cli.js"]
        != installed_payload["helpers/claude-cli.js"]
    )
    owned = json.loads(layout.ownership.read_bytes())
    assert owned["version"] == "1.0.1"
    assert payload_problems(layout.payload, owned["files"]) == []
    assert layout.config.read_bytes() == enabled_config
    historical = {**projection, "applicability": "unknown", "proof": False}
    assert _cli(
        layout.payload / "helpers" / "claude-cli.js", "list", repository, data_root
    ) == {"receipts": [historical]}
    assert_evidence()

    # Reuse the lifecycle suite's failed staged-swap injection against the real
    # feature, with evidence already finalized outside the old/new payloads.
    _release(receipt_source, "1.0.2")
    real_rename = os.rename
    failed_swap = False

    def failing_swap(source: Path, destination: Path) -> None:
        nonlocal failed_swap
        if (
            not failed_swap
            and Path(source).is_relative_to(layout.staging)
            and Path(destination) == layout.payload
        ):
            failed_swap = True
            raise RuntimeError("simulated failure while swapping the update")
        real_rename(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(os, "rename", failing_swap)
        with pytest.raises(RuntimeError, match="simulated failure"):
            act("update")
    assert failed_swap, "the update must reach the actual payload swap"
    assert _tree(layout.payload) == updated_payload
    restored = json.loads(layout.ownership.read_bytes())
    assert restored == owned
    assert list(layout.staging.iterdir()) == []
    assert layout.config.read_bytes() == enabled_config
    assert_evidence()

    unknown = layout.payload / "user-note.txt"
    unknown.write_bytes(b"User-owned data must not be swept into package cleanup.\n")
    before_refusal = _tree(host_root)
    for action in ("update", "remove"):
        with pytest.raises(LifecycleError, match="user-note.txt: foreign file"):
            act(action)
        assert _tree(host_root) == before_refusal
        assert_evidence()
    unknown.unlink()  # Remove only the test-owned refusal trigger.

    act("remove")
    assert not layout.payload.exists()
    assert not layout.ownership.exists()
    assert layout.config.read_bytes() == original_config
    assert_evidence()
    # Removal does not strand evidence: the existing detached source CLI can
    # still read the same real receipt without reinstalling or invoking a host.
    assert _cli(
        receipt_source / "helpers" / "claude-cli.ts", "list", repository, data_root
    ) == {"receipts": [historical]}
    assert_evidence()
