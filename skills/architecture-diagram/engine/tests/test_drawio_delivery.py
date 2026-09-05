"""Delivery integration tests for opt-in draw.io exports."""

from __future__ import annotations

import json
import os
from pathlib import Path
import xml.etree.ElementTree as ElementTree

import pytest

from engine import commands
from engine.receipts import sha256


def _deliver(
    capsys: pytest.CaptureFixture[str], spec: Path, output: Path, *extra: str
) -> tuple[int, dict[str, object]]:
    code = commands.main(
        [
            "deliver",
            str(spec),
            "--output",
            str(output),
            "--cache-dir",
            str(output.parent),
            "--json",
            *extra,
        ]
    )
    return code, json.loads(capsys.readouterr().out)


def test_deliver_emit_drawio_commits_a_digest_bound_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "diagram.yaml"
    spec.write_text(
        "nodes:\n"
        "  - id: public\n"
        "  - id: service\n"
        "edges:\n"
        "  - from: public\n"
        "    to: service\n"
        "    label: HTTPS\n"
    )
    output = tmp_path / "diagram.svg"

    code, receipt = _deliver(capsys, spec, output, "--emit", "drawio")

    drawio = tmp_path / "diagram.drawio"
    assert code == commands.EXIT_OK
    assert output.is_file()
    assert drawio.is_file()
    assert ElementTree.parse(drawio).getroot().tag == "mxfile"
    assert receipt["artifacts"] == [
        {
            "path": str(output),
            "sha256": sha256(output.read_bytes()),
            "bytes": output.stat().st_size,
        },
        {
            "path": str(drawio),
            "sha256": sha256(drawio.read_bytes()),
            "bytes": drawio.stat().st_size,
        },
    ]


def test_default_delivery_keeps_drawio_and_artifact_list_opt_in(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "diagram.yaml"
    spec.write_text("nodes:\n  - id: service\n")
    output = tmp_path / "diagram.svg"

    code, receipt = _deliver(capsys, spec, output)

    assert code == commands.EXIT_OK
    assert output.is_file()
    assert not (tmp_path / "diagram.drawio").exists()
    assert "artifacts" not in receipt


def test_drawio_commit_failure_restores_existing_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = tmp_path / "diagram.yaml"
    spec.write_text("nodes:\n  - id: service\n")
    output = tmp_path / "diagram.svg"
    drawio = tmp_path / "diagram.drawio"
    output.write_text("prior svg")
    drawio.write_text("prior drawio")
    replace = os.replace

    def fail_drawio_candidate(source: Path | str, target: Path | str) -> None:
        if Path(source).name == "candidate.drawio":
            raise OSError("injected drawio replacement failure")
        replace(source, target)

    monkeypatch.setattr("engine.delivery.os.replace", fail_drawio_candidate)

    code, receipt = _deliver(capsys, spec, output, "--emit", "drawio")

    assert code == commands.EXIT_FAILURE
    assert receipt["delivery_stage"] == "commit"
    assert output.read_text() == "prior svg"
    assert drawio.read_text() == "prior drawio"
