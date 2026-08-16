"""Tests for pure decision-map graph normalization and state computation."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from frontier import (  # noqa: E402
    Claim,
    Ticket,
    compute_frontier,
    compute_state,
    format_report,
    normalize_github_issues,
    normalize_local_map,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 16, 10, tzinfo=UTC)


def _fixture(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


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
    tickets = normalize_github_issues(_fixture("github_issues.json"), map_number=42, now=NOW)

    frontier = compute_frontier(tickets)

    assert [ticket.number for ticket in frontier] == [7, 10, 12]
    assert next(ticket for ticket in tickets if ticket.number == 10).owner == "shared-agent"


def test_frontier_drops_claimed_and_open_blocked_tickets() -> None:
    tickets = normalize_github_issues(_fixture("github_issues.json"), map_number=42, now=NOW)

    frontier_numbers = {ticket.number for ticket in compute_frontier(tickets)}

    assert 8 not in frontier_numbers
    assert 11 not in frontier_numbers


def test_frontier_keeps_closed_blocker_and_drops_closed_ticket() -> None:
    tickets = normalize_github_issues(_fixture("github_issues.json"), map_number=42, now=NOW)

    frontier_numbers = {ticket.number for ticket in compute_frontier(tickets)}

    assert 12 in frontier_numbers
    assert 9 not in frontier_numbers


def test_state_ladder_reaches_all_five_states() -> None:
    claim = Claim(10, "session", NOW)

    assert compute_state([_ticket(1)], fog="") == "ACTIVE"
    assert compute_state([_ticket(1, claim=claim)], fog="") == "WAITING"
    assert compute_state([_ticket(1, blockers=(2,)), _ticket(2, blockers=(1,))], fog="") == "BLOCKED"
    assert compute_state([], fog="A question is still vague.") == "FOGGY"
    assert compute_state([], fog="") == "COMPLETE"


def test_degraded_normalization_matches_native_logical_graph() -> None:
    native = normalize_github_issues(_fixture("github_issues.json"), map_number=42, now=NOW)
    degraded = normalize_github_issues(
        _fixture("github_issues_degraded.json"), map_number=42, now=NOW, degraded=True
    )

    assert [(ticket.number, ticket.blocker_numbers, ticket.claimed) for ticket in degraded] == [
        (ticket.number, ticket.blocker_numbers, ticket.claimed) for ticket in native
    ]
    assert [ticket.number for ticket in compute_frontier(degraded)] == [7, 10, 12]


def test_afk_filter_preserves_only_actionable_afk_tickets() -> None:
    tickets = normalize_github_issues(_fixture("github_issues.json"), map_number=42, now=NOW)

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
