"""Actual filesystem race at the archive replay boundary; synthetic HOME only."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pytest
import skill_inventory as cli
from inventory_io import Snapshot
from inventory_types import Harness


def test_deleted_binding_cannot_recapture_during_archive_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    logs = home / ".omp" / "agent" / "sessions"
    logs.mkdir(parents=True)
    for name in ("managed-skills", "skills"):
        (logs.parent / name).mkdir()
    monkeypatch.setenv("HOME", str(home))
    (logs / "fictional.jsonl").write_text(
        json.dumps(
            {
                "type": "session",
                "version": 3,
                "id": "fictional-session",
                "timestamp": "2025-01-01T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    binding = tmp_path / "binding.json"
    common = [
        "--harness",
        "omp",
        "--aggregate-only",
        "--as-of",
        "2025-01-31T00:00:00Z",
        "--window-days",
        "90",
        "--snapshot",
        str(binding),
        "--log-root",
        str(logs),
    ]
    cli.main(["measure", *common])
    binding.read_bytes()  # Actual capture must exist before the concurrent deletion.
    capsys.readouterr()
    proposal = tmp_path / "proposal.json"
    proposal.write_text("{}\n", encoding="utf-8")
    proposal.chmod(0o600)
    original = Snapshot.__init__

    def delete_before_open(
        self: Snapshot,
        binding_path: Path,
        *,
        harness: Harness,
        roots: Sequence[Path],
        as_of: datetime,
        window_days: int,
    ) -> None:
        binding_path.unlink()
        original(
            self,
            binding_path,
            harness=harness,
            roots=roots,
            as_of=as_of,
            window_days=window_days,
        )

    monkeypatch.setattr(Snapshot, "__init__", delete_before_open)
    result = cli.main(["archive", *common, "--proposal", str(proposal), "--dry-run"])
    public = capsys.readouterr()
    assert result == 2
    assert not binding.exists()
    assert not (logs.parent / "skill-inventory-archive").exists()
    assert proposal.read_bytes() == b"{}\n"
    assert str(tmp_path) not in public.out + public.err
    assert "fictional-session" not in public.out + public.err
