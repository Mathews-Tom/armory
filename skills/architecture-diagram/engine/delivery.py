"""Same-filesystem multi-artifact delivery with caught-failure rollback."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil


@dataclass(frozen=True)
class BundleCommitError(Exception):
    """One bundle commit failed, with any rollback failure retained."""

    stage: str
    cause: OSError
    rollback_cause: OSError | None = None

    def __str__(self) -> str:
        if self.rollback_cause is None:
            return f"{self.stage} failed: {self.cause}"
        return f"{self.stage} failed and rollback failed: {self.rollback_cause}"


def commit_bundle(stage_dir: Path, replacements: list[tuple[Path, Path]]) -> None:
    """Replace a staged bundle or restore every prior target after an OSError."""
    snapshots: list[tuple[Path, Path | None]] = []
    try:
        for index, (_, target) in enumerate(replacements):
            snapshot = stage_dir / f"previous-{index}"
            if target.exists():
                shutil.copyfile(target, snapshot)
                snapshots.append((target, snapshot))
            else:
                snapshots.append((target, None))
        for candidate, target in replacements:
            os.replace(candidate, target)
    except OSError as cause:
        try:
            for target, snapshot in snapshots:
                if snapshot is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(snapshot, target)
        except OSError as rollback_cause:
            raise BundleCommitError("commit", cause, rollback_cause) from cause
        raise BundleCommitError("commit", cause) from cause
