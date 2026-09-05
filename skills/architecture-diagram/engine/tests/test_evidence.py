from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from engine.commands import main
from engine.evidence import verify_sources
from engine.receipts import sha256
from engine.spec import load_spec


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_spec(repository: Path, revision: str, path: str, lines: str) -> Path:
    spec = repository / "diagram.yaml"
    spec.write_text(
        f"""sources:
  - id: api
    revision: {revision}
    path: {path}
    lines: {lines}
nodes:
  - id: service
    sources: [api]
"""
    )
    return spec


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Source Evidence Tests")
    (repo / "src").mkdir()
    (repo / "src" / "api.py").write_text("one\ntwo\nthree")
    _git(repo, "add", "src/api.py")
    _git(repo, "commit", "-qm", "fixture")
    _git(repo, "remote", "add", "origin", "https://example.invalid/diagram.git")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_verifies_uppercase_commit_and_no_final_newline(
    repository: tuple[Path, str],
) -> None:
    repo, revision = repository
    spec_path = _write_spec(repo, revision.upper(), "src/api.py", "[1, 3]")

    evidence, diagnostics = verify_sources(load_spec(spec_path.read_text()), spec_path)

    assert diagnostics == []
    assert evidence is not None
    assert evidence.sources[0].revision == revision
    assert evidence.sources[0].line_count == 3


@pytest.mark.parametrize(
    ("revision", "path", "lines", "expected"),
    [
        ("a" * 40, "src/api.py", "[1, 3]", "source/missing-commit"),
        ("HEAD", "missing.py", "[1, 3]", "source/missing-path"),
        ("HEAD", "src", "[1, 3]", "source/non-blob-path"),
        ("HEAD", "src/api.py", "[1, 4]", "source/line-range-out-of-bounds"),
    ],
)
def test_rejects_unverifiable_source_references(
    repository: tuple[Path, str], revision: str, path: str, lines: str, expected: str
) -> None:
    repo, head = repository
    actual_revision = head if revision == "HEAD" else revision
    spec_path = _write_spec(repo, actual_revision, path, lines)

    evidence, diagnostics = verify_sources(load_spec(spec_path.read_text()), spec_path)

    assert evidence is None
    assert [diagnostic.code for diagnostic in diagnostics] == [expected]


def test_rejects_binary_blob(repository: tuple[Path, str]) -> None:
    repo, _ = repository
    (repo / "src" / "binary.bin").write_bytes(b"\0binary")
    _git(repo, "add", "src/binary.bin")
    _git(repo, "commit", "-qm", "binary fixture")
    spec_path = _write_spec(
        repo, _git(repo, "rev-parse", "HEAD"), "src/binary.bin", "[1, 1]"
    )

    evidence, diagnostics = verify_sources(load_spec(spec_path.read_text()), spec_path)

    assert evidence is None
    assert [diagnostic.code for diagnostic in diagnostics] == ["source/binary-blob"]


def test_rejects_source_outside_a_git_repository(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path, "a" * 40, "src/api.py", "[1, 1]")

    evidence, diagnostics = verify_sources(load_spec(spec_path.read_text()), spec_path)

    assert evidence is None
    assert [diagnostic.code for diagnostic in diagnostics] == ["source/no-repository"]


def test_rejects_repository_without_origin(tmp_path: Path) -> None:
    repo = tmp_path / "no-origin"
    repo.mkdir()
    _git(repo, "init", "-q")
    spec_path = _write_spec(repo, "a" * 40, "src/api.py", "[1, 1]")

    evidence, diagnostics = verify_sources(load_spec(spec_path.read_text()), spec_path)

    assert evidence is None
    assert [diagnostic.code for diagnostic in diagnostics] == ["source/no-origin"]


def test_validate_receipt_reports_verified_evidence(
    repository: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, revision = repository
    spec_path = _write_spec(repo, revision, "src/api.py", "[1, 3]")

    assert main(["validate", str(spec_path), "--verify-sources", "--json"]) == 0

    receipt = json.loads(capsys.readouterr().out)
    assert receipt["evidence"] == {
        "mode": "verified",
        "sourced_edges": 0,
        "sourced_nodes": 1,
        "verified_sources": 1,
    }


def test_deliver_verifies_before_writing(
    repository: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, revision = repository
    spec_path = _write_spec(repo, revision, "src/api.py", "[1, 3]")
    output = repo / "diagram.svg"
    _git(
        repo,
        "remote",
        "set-url",
        "origin",
        "https://user:secret@example.invalid/diagram.git",
    )

    assert (
        main(
            [
                "deliver",
                str(spec_path),
                "--verify-sources",
                "--json",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    receipt = json.loads(capsys.readouterr().out)
    sidecar_path = repo / "diagram.sources.json"
    sidecar = json.loads(sidecar_path.read_text())

    assert output.is_file()
    assert receipt["evidence"]["verified_sources"] == 1
    assert receipt["evidence"]["sidecar"]["path"] == str(sidecar_path)
    assert sidecar["artifact"]["sha256"] == receipt["artifact"]["sha256"]
    assert sidecar["sources"][0]["id"] == "api"
    assert sidecar["repository"]["origin"] == "https://example.invalid/diagram.git"
    assert 'data-source-ids="api"' in output.read_text()
    assert "VERIFIED SRC 1" in output.read_text()


def test_combined_delivery_commits_a_coherent_source_evidence_bundle(
    repository: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, revision = repository
    spec_path = _write_spec(repo, revision, "src/api.py", "[1, 3]")
    output = repo / "diagram.svg"
    drawio_path = repo / "diagram.drawio"
    sidecar_path = repo / "diagram.sources.json"

    assert (
        main(
            [
                "deliver",
                str(spec_path),
                "--verify-sources",
                "--emit",
                "drawio",
                "--json",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    receipt = json.loads(capsys.readouterr().out)
    assert [artifact["path"] for artifact in receipt["artifacts"]] == [
        str(output),
        str(drawio_path),
        str(sidecar_path),
    ]
    for artifact, path in zip(
        receipt["artifacts"], (output, drawio_path, sidecar_path), strict=True
    ):
        assert artifact == {
            "path": str(path),
            "sha256": sha256(path.read_bytes()),
            "bytes": path.stat().st_size,
        }
    assert "source-badge-node-service" in drawio_path.read_text()
