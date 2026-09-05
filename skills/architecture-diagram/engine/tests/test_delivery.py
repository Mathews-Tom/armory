from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.delivery import BundleCommitError, commit_bundle


def test_commit_bundle_restores_existing_pair_after_second_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "diagram.svg"
    sidecar = tmp_path / "diagram.sources.json"
    output.write_text("old svg")
    sidecar.write_text("old sidecar")
    candidate = tmp_path / "candidate.svg"
    candidate_sidecar = tmp_path / "candidate.sources.json"
    candidate.write_text("new svg")
    candidate_sidecar.write_text("new sidecar")
    replace = os.replace

    def fail_second_replace(source: Path | str, target: Path | str) -> None:
        if Path(source) == candidate_sidecar:
            raise OSError("injected sidecar failure")
        replace(source, target)

    monkeypatch.setattr("engine.delivery.os.replace", fail_second_replace)

    with pytest.raises(BundleCommitError):
        commit_bundle(
            tmp_path,
            [(candidate, output), (candidate_sidecar, sidecar)],
        )

    assert output.read_text() == "old svg"
    assert sidecar.read_text() == "old sidecar"
