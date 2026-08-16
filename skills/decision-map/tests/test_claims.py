"""Tests for deterministic GitHub arbitration and local O_EXCL claims."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from frontier import (  # noqa: E402
    acquire_local_claim,
    parse_claims,
    release_local_claim,
    winning_claim,
)

NOW = datetime(2026, 8, 16, 10, tzinfo=UTC)


def _claim(comment_id: int, *, session: str, claimed_at: datetime) -> dict[str, object]:
    return {
        "id": f"IC_kwDO{comment_id}",
        "url": f"https://github.com/owner/repo/issues/1#issuecomment-{comment_id}",
        "body": (
            "decision-map claim\n"
            f"session: {session}\n"
            f"claimed-at: {claimed_at.isoformat()}"
        ),
    }


def test_lowest_fresh_comment_id_wins_claim_arbitration() -> None:
    winner = winning_claim(
        [
            _claim(28, session="later", claimed_at=NOW - timedelta(minutes=1)),
            _claim(17, session="first", claimed_at=NOW - timedelta(minutes=2)),
        ],
        now=NOW,
    )

    assert winner is not None
    assert winner.comment_id == 17
    assert winner.session == "first"


def test_malformed_claim_comment_is_ignored() -> None:
    claims = parse_claims(
        [
            {"id": 1, "body": "decision-map claim\nsession: missing-timestamp"},
            {"id": 2, "body": "wrong first line\nsession: ignored\nclaimed-at: 2026-08-16T09:59:00+00:00"},
            _claim(3, session="valid", claimed_at=NOW),
        ],
        now=NOW,
    )

    assert [claim.comment_id for claim in claims] == [3]


def test_stale_claim_is_preemptable_but_fresh_claim_is_not() -> None:
    stale = _claim(1, session="crashed", claimed_at=NOW - timedelta(hours=25))
    fresh = _claim(2, session="alive", claimed_at=NOW - timedelta(hours=23, minutes=59))

    assert winning_claim([stale], now=NOW) is None
    fresh_winner = winning_claim([fresh], now=NOW)
    assert fresh_winner is not None
    assert fresh_winner.session == "alive"


def test_local_o_excl_rejects_second_acquisition_and_releases_on_resolution(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    acquired = acquire_local_claim(claims_dir, 7, session="first", now=NOW)

    assert acquired.session == "first"
    with pytest.raises(FileExistsError, match="already has a fresh local claim"):
        acquire_local_claim(claims_dir, 7, session="second", now=NOW)

    release_local_claim(claims_dir, 7)

    replacement = acquire_local_claim(claims_dir, 7, session="second", now=NOW)
    assert replacement.session == "second"


def test_local_stale_lock_can_be_preempted(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    lock = claims_dir / "9.lock"
    lock.write_text(
        "session: crashed\nclaimed-at: 2026-08-15T08:00:00+00:00\n",
        encoding="utf-8",
    )

    replacement = acquire_local_claim(claims_dir, 9, session="replacement", now=NOW)

    assert replacement.session == "replacement"
    assert "replacement" in lock.read_text(encoding="utf-8")


def test_local_malformed_lock_is_rejected_without_overwrite(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    lock = claims_dir / "11.lock"
    lock.write_text("session: interrupted\n", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed"):
        acquire_local_claim(claims_dir, 11, session="replacement", now=NOW)

    assert lock.read_text(encoding="utf-8") == "session: interrupted\n"
