"""Tests for pure decision-map graph normalization and state computation."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from shutil import copytree
from typing import cast

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from frontier import (
    Claim,
    Ticket,
    _build_parser,
    acquire_local_claim,
    compute_frontier,
    compute_state,
    format_report,
    normalize_github_issues,
    normalize_local_map,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 16, 10, tzinfo=UTC)


def _fixture(name: str) -> list[dict[str, object]]:
    return cast(
        list[dict[str, object]],
        json.loads((FIXTURES / name).read_text(encoding="utf-8")),
    )


def _ticket(
    number: int,
    *,
    open: bool = True,
    blockers: tuple[int, ...] = (),
    claim: Claim | None = None,
    interaction: str = "decision-map:hitl",
) -> Ticket:
    return Ticket(
        number=number,
        title=f"Ticket {number}",
        open=open,
        type="decision-map:discussion",
        interaction=interaction,
        blocker_numbers=blockers,
        owner=None,
        claim=claim,
    )


def test_frontier_keeps_unblocked_unclaimed_and_assigned_unclaimed() -> None:
    tickets = normalize_github_issues(
        _fixture("github_issues.json"), map_number=42, now=NOW
    )

    frontier = compute_frontier(tickets)

    assert [ticket.number for ticket in frontier] == [7, 10, 12]
    assert (
        next(ticket for ticket in tickets if ticket.number == 10).owner
        == "shared-agent"
    )


def test_frontier_drops_claimed_and_open_blocked_tickets() -> None:
    tickets = normalize_github_issues(
        _fixture("github_issues.json"), map_number=42, now=NOW
    )

    frontier_numbers = {ticket.number for ticket in compute_frontier(tickets)}

    assert 8 not in frontier_numbers
    assert 11 not in frontier_numbers


def test_frontier_keeps_closed_blocker_and_drops_closed_ticket() -> None:
    tickets = normalize_github_issues(
        _fixture("github_issues.json"), map_number=42, now=NOW
    )

    frontier_numbers = {ticket.number for ticket in compute_frontier(tickets)}

    assert 12 in frontier_numbers
    assert 9 not in frontier_numbers


def test_state_ladder_reaches_all_five_states() -> None:
    claim = Claim(10, "session", NOW)

    assert compute_state([_ticket(1)], fog="") == "ACTIVE"
    assert compute_state([_ticket(1, claim=claim)], fog="") == "WAITING"
    assert (
        compute_state([_ticket(1, blockers=(2,)), _ticket(2, blockers=(1,))], fog="")
        == "BLOCKED"
    )
    assert compute_state([], fog="A question is still vague.") == "FOGGY"
    assert compute_state([], fog="") == "COMPLETE"


def test_degraded_normalization_matches_native_logical_graph() -> None:
    native = normalize_github_issues(
        _fixture("github_issues.json"), map_number=42, now=NOW
    )
    degraded = normalize_github_issues(
        _fixture("github_issues_degraded.json"), map_number=42, now=NOW, degraded=True
    )

    assert [
        (ticket.number, ticket.blocker_numbers, ticket.claimed) for ticket in degraded
    ] == [(ticket.number, ticket.blocker_numbers, ticket.claimed) for ticket in native]
    assert [ticket.number for ticket in compute_frontier(degraded)] == [7, 10, 12]


def test_afk_filter_preserves_only_actionable_afk_tickets() -> None:
    tickets = normalize_github_issues(
        _fixture("github_issues.json"), map_number=42, now=NOW
    )

    frontier = compute_frontier(tickets, afk_only=True)

    assert [ticket.number for ticket in frontier] == [12]


def test_empty_frontier_report_explains_reason_and_state() -> None:
    report = format_report([_ticket(1, claim=Claim(10, "session", NOW))], fog="")

    assert "frontier: empty" in report
    assert "state: WAITING" in report


def test_local_normalization_reads_headers_and_fog() -> None:
    tickets, fog = normalize_local_map(FIXTURES / "local_map", now=NOW)

    assert [ticket.number for ticket in tickets] == [1, 2]
    assert tickets[1].blocker_numbers == (1,)
    assert "Regional retention rules" in fog


def test_local_argument_documents_docs_storage() -> None:
    assert ".docs/decision-maps" in _build_parser().format_help()


def test_unresolved_local_prototype_retains_open_ticket_and_claim() -> None:
    tickets, fog = normalize_local_map(FIXTURES / "unresolved_prototype", now=NOW)

    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket.number == 10
    assert ticket.title == "Prevent a second refund"
    assert ticket.open
    assert ticket.type == "decision-map:prototype"
    assert ticket.interaction == "decision-map:hitl"
    assert ticket.blocker_numbers == ()
    assert ticket.claim is not None
    assert ticket.claim.session == "prototype-session"
    assert ticket.claim.claimed_at == NOW - timedelta(hours=1)
    assert compute_frontier(tickets) == ()
    assert compute_state(tickets, fog=fog) == "WAITING"


@pytest.mark.parametrize("degraded", [False, True])
def test_unresolved_github_comment_preserves_metadata_and_claim(degraded: bool) -> None:
    tickets = normalize_github_issues(
        _fixture("github_unresolved_prototype.json"),
        map_number=42,
        now=NOW,
        degraded=degraded,
    )

    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket.open
    assert ticket.type == "decision-map:prototype"
    assert ticket.interaction == "decision-map:hitl"
    assert ticket.blocker_numbers == ()
    assert ticket.owner == "shared-agent"
    assert ticket.claim is not None
    assert ticket.claim.comment_id == 120
    assert ticket.claim.session == "prototype-session"
    assert ticket.claim.claimed_at == NOW - timedelta(hours=1)
    assert compute_frontier(tickets) == ()
    assert compute_state(tickets, fog="") == "WAITING"


@pytest.mark.parametrize(
    "evidence",
    [
        (
            "Status: CLOSED\nType: decision-map:research\n"
            "Interaction: decision-map:afk\nBlocked by: #99"
        ),
        (
            "```text\nType: invalid\n\nInteraction: invalid\nStatus: INVALIDATED\n"
            "Blocked by: #10, #99\n```"
        ),
        (
            "# Replacement title\n## Question\nA different question?\n"
            "decision-map claim\nsession: replacement\nclaimed-at: 2026-08-16T10:00:00+00:00"
        ),
    ],
)
def test_quoted_local_evidence_append_preserves_normalized_ticket(
    tmp_path: Path, evidence: str
) -> None:
    root = tmp_path / "map"
    copytree(FIXTURES / "unresolved_prototype", root)
    before = normalize_local_map(root, now=NOW)
    quoted = "\n".join(f"> {line}" if line else ">" for line in evidence.splitlines())
    with (root / "010-refund-state.md").open("a", encoding="utf-8") as ticket_file:
        ticket_file.write(f"\n## Evidence\n{quoted}\n")

    after = normalize_local_map(root, now=NOW)

    assert after == before
    assert compute_state(after[0], fog=after[1]) == "WAITING"


def test_unresolved_local_claim_rejects_second_claim_then_obeys_stale_rule(
    tmp_path: Path,
) -> None:
    root = tmp_path / "map"
    copytree(FIXTURES / "unresolved_prototype", root)

    with pytest.raises(FileExistsError, match="already has a fresh local claim"):
        acquire_local_claim(root / "claims", 10, session="second", now=NOW)

    stale_now = NOW + timedelta(hours=23, minutes=30)
    tickets, fog = normalize_local_map(root, now=stale_now)
    assert tickets[0].open
    assert tickets[0].claim is None
    assert [ticket.number for ticket in compute_frontier(tickets)] == [10]
    assert compute_state(tickets, fog=fog) == "ACTIVE"

    replacement = acquire_local_claim(
        root / "claims", 10, session="replacement-after-stale", now=stale_now
    )
    resumed, fog = normalize_local_map(root, now=stale_now)
    assert resumed[0].claim == replacement
    assert resumed[0].open
    assert compute_state(resumed, fog=fog) == "WAITING"


@pytest.mark.parametrize("degraded", [False, True])
def test_unresolved_github_evidence_does_not_refresh_stale_claim(
    degraded: bool,
) -> None:
    tickets = normalize_github_issues(
        _fixture("github_unresolved_prototype.json"),
        map_number=42,
        now=NOW + timedelta(hours=23, minutes=30),
        degraded=degraded,
    )

    assert tickets[0].open
    assert tickets[0].claim is None
    assert [ticket.number for ticket in compute_frontier(tickets)] == [10]
    assert compute_state(tickets, fog="") == "ACTIVE"
