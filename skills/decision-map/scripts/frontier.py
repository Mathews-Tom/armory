#!/usr/bin/env python3
"""Compute a decision-map frontier from GitHub or local tracker data.

The adapters normalize external tracker shapes. Frontier and state computation below
that boundary are pure functions over ``Ticket`` instances, so tests do not need a
network connection or a GitHub CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

TYPE_LABELS: frozenset[str] = frozenset(
    {
        "decision-map:discussion",
        "decision-map:research",
        "decision-map:prototype",
        "decision-map:unblock",
    }
)
INTERACTION_LABELS: frozenset[str] = frozenset(
    {"decision-map:hitl", "decision-map:afk"}
)
_CLAIM_FIRST_LINE = "decision-map claim"
_CLAIM_FIELD = re.compile(r"^(session|claimed-at):\s*(.+?)\s*$", re.MULTILINE)
_BLOCKED_BY = re.compile(r"^Blocked by:\s*((?:#\d+(?:\s*,\s*)?)*)\s*$", re.MULTILINE)
_CHILD_REFERENCE = re.compile(r"#(\d+)")
_ISSUE_COMMENT_ID = re.compile(r"#issuecomment-(\d+)$")
_LOCAL_HEADER = re.compile(r"^(Type|Interaction|Status|Blocked by):\s*(.*?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Claim:
    """A valid, non-arbitrated claim comment."""

    comment_id: int
    session: str
    claimed_at: datetime


@dataclass(frozen=True)
class Ticket:
    """Backend-neutral state for one decision ticket."""

    number: int
    title: str
    open: bool
    type: str
    interaction: str
    blocker_numbers: tuple[int, ...]
    owner: str | None
    claim: Claim | None

    @property
    def claimed(self) -> bool:
        return self.claim is not None


def parse_claims(
    comments: Iterable[dict[str, Any]],
    *,
    now: datetime,
    ttl: timedelta = timedelta(hours=24),
) -> tuple[Claim, ...]:
    """Return syntactically valid, fresh claims sorted by server comment id."""

    claims: list[Claim] = []
    for comment in comments:
        body = comment.get("body")
        comment_id = _database_comment_id(comment)
        if not isinstance(body, str) or comment_id is None:
            continue
        if body.splitlines()[:1] != [_CLAIM_FIRST_LINE]:
            continue
        fields = {name: value for name, value in _CLAIM_FIELD.findall(body)}
        session = fields.get("session")
        raw_timestamp = fields.get("claimed-at")
        if not session or not raw_timestamp:
            continue
        try:
            claimed_at = _parse_timestamp(raw_timestamp)
        except ValueError:
            continue
        if now - claimed_at > ttl:
            continue
        claims.append(Claim(comment_id, session, claimed_at))
    return tuple(sorted(claims, key=lambda claim: claim.comment_id))


def winning_claim(
    comments: Iterable[dict[str, Any]],
    *,
    now: datetime,
    ttl: timedelta = timedelta(hours=24),
) -> Claim | None:
    """Return the lowest-id fresh claim, which is the deterministic winner."""

    claims = parse_claims(comments, now=now, ttl=ttl)
    return claims[0] if claims else None


def normalize_github_issues(
    issues: Iterable[dict[str, Any]],
    *,
    map_number: int,
    now: datetime,
    degraded: bool = False,
) -> tuple[Ticket, ...]:
    """Normalize GitHub issue JSON without invoking GitHub.

    Native mode selects issues whose parent is the requested map. Degraded mode
    selects numbers listed in the map body's generated child index and derives
    blockers from ``Blocked by: #N`` ticket-body lines.
    """

    materialized = tuple(issues)
    map_issue = next(
        (
            issue
            for issue in materialized
            if isinstance(issue.get("number"), int) and issue["number"] == map_number
        ),
        None,
    )
    degraded_children = (
        frozenset(_CHILD_REFERENCE.findall(str(map_issue.get("body", ""))))
        if degraded and map_issue is not None
        else frozenset()
    )
    tickets: list[Ticket] = []
    for issue in materialized:
        number = issue.get("number")
        if not isinstance(number, int) or number == map_number:
            continue
        if degraded:
            selected = str(number) in degraded_children
        else:
            parent = issue.get("parent")
            selected = isinstance(parent, dict) and parent.get("number") == map_number
        if not selected:
            continue
        tickets.append(_normalize_issue(issue, now=now, degraded=degraded))
    return tuple(tickets)


def normalize_local_map(root: Path, *, now: datetime) -> tuple[tuple[Ticket, ...], str]:
    """Normalize local map files and their O_EXCL claim locks."""

    map_path = root / "map.md"
    if not map_path.is_file():
        raise FileNotFoundError(f"Local map is missing: {map_path}")
    fog = _section_text(map_path.read_text(encoding="utf-8"), "Not yet specified")
    tickets: list[Ticket] = []
    for path in sorted(root.glob("*.md")):
        if path.name == "map.md":
            continue
        text = path.read_text(encoding="utf-8")
        fields = {name: value for name, value in _LOCAL_HEADER.findall(text)}
        number = _ticket_number(path)
        ticket_type = fields.get("Type")
        interaction = fields.get("Interaction")
        status = fields.get("Status")
        if ticket_type not in TYPE_LABELS:
            raise ValueError(f"{path}: expected exactly one decision-map type")
        if interaction not in INTERACTION_LABELS:
            raise ValueError(f"{path}: expected exactly one decision-map interaction")
        if status is None:
            raise ValueError(f"{path}: missing Status header")
        blockers = tuple(int(value) for value in _CHILD_REFERENCE.findall(fields.get("Blocked by", "")))
        lock = _read_local_claim(root / "claims" / f"{number}.lock", now=now)
        title = _title_from_text(text, fallback=path.stem)
        tickets.append(
            Ticket(
                number=number,
                title=title,
                open=status.strip().upper() == "OPEN",
                type=ticket_type,
                interaction=interaction,
                blocker_numbers=blockers,
                owner=None,
                claim=lock,
            )
        )
    return tuple(tickets), fog


def compute_frontier(tickets: Sequence[Ticket], *, afk_only: bool = False) -> tuple[Ticket, ...]:
    """Return open, unclaimed tickets with no open blockers in input order."""

    by_number = {ticket.number: ticket for ticket in tickets}
    frontier: list[Ticket] = []
    for ticket in tickets:
        if not ticket.open or ticket.claimed:
            continue
        if afk_only and ticket.interaction != "decision-map:afk":
            continue
        if any(by_number.get(blocker, _closed_ticket(blocker)).open for blocker in ticket.blocker_numbers):
            continue
        frontier.append(ticket)
    return tuple(frontier)


def compute_state(
    tickets: Sequence[Ticket],
    *,
    fog: str,
    unresolved_contradiction: bool = False,
) -> str:
    """Compute the ordered five-state map ladder.

    A map-level contradiction outside the five modeled states is an error, not a
    silent COMPLETE result.
    """

    if compute_frontier(tickets):
        return "ACTIVE"
    open_tickets = tuple(ticket for ticket in tickets if ticket.open)
    if open_tickets and any(ticket.claimed for ticket in open_tickets):
        return "WAITING"
    if open_tickets:
        return "BLOCKED"
    if fog.strip():
        return "FOGGY"
    if unresolved_contradiction:
        raise ValueError("Map has an unresolved contradiction and cannot be COMPLETE")
    return "COMPLETE"


def acquire_local_claim(
    claims_dir: Path,
    ticket_number: int,
    *,
    session: str,
    now: datetime,
    ttl: timedelta = timedelta(hours=24),
) -> Claim:
    """Create an exclusive local lock, preempting only a documented stale lock."""

    claims_dir.mkdir(parents=True, exist_ok=True)
    path = claims_dir / f"{ticket_number}.lock"
    existing = _read_local_claim(path, now=now, ttl=ttl)
    if existing is not None:
        raise FileExistsError(f"Ticket {ticket_number} already has a fresh local claim")
    if path.exists():
        path.unlink()
    payload = f"session: {session}\nclaimed-at: {now.isoformat()}\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload.encode("utf-8"))
    finally:
        os.close(descriptor)
    return Claim(ticket_number, session, now)


def release_local_claim(claims_dir: Path, ticket_number: int) -> None:
    """Release a local lock after its ticket resolution is recorded."""

    (claims_dir / f"{ticket_number}.lock").unlink()


def format_report(tickets: Sequence[Ticket], *, fog: str, afk_only: bool = False) -> str:
    """Format frontier entries and a non-silent empty-frontier explanation."""

    frontier = compute_frontier(tickets, afk_only=afk_only)
    state = compute_state(tickets, fog=fog)
    lines = [
        f"#{ticket.number} — {ticket.title} [{ticket.type.removeprefix('decision-map:')}/{ticket.interaction.removeprefix('decision-map:')}]"
        for ticket in frontier
    ]
    if not lines:
        unfiltered_frontier = compute_frontier(tickets)
        open_tickets = tuple(ticket for ticket in tickets if ticket.open)
        if afk_only and unfiltered_frontier:
            hitl_count = sum(
                ticket.interaction == "decision-map:hitl"
                for ticket in unfiltered_frontier
            )
            lines.append(
                f"frontier: empty — no AFK-ready tickets; {hitl_count} HITL tickets are actionable"
            )
        elif open_tickets and any(ticket.claimed for ticket in open_tickets):
            lines.append("frontier: empty — all actionable tickets are claimed or blocked")
        elif open_tickets:
            lines.append("frontier: empty — all open tickets are blocked")
        elif fog.strip():
            lines.append("frontier: empty — no open tickets; fog remains")
        else:
            lines.append("frontier: empty — no open tickets or fog remain")
    lines.append(f"state: {state}")
    return "\n".join(lines)


def _normalize_issue(issue: dict[str, Any], *, now: datetime, degraded: bool) -> Ticket:
    labels: set[str] = set()
    for label in issue.get("labels", []):
        if isinstance(label, dict):
            name = label.get("name")
            if isinstance(name, str):
                labels.add(name)
    types = sorted(labels & TYPE_LABELS)
    interactions = sorted(labels & INTERACTION_LABELS)
    number = issue.get("number")
    title = issue.get("title")
    if not isinstance(number, int) or not isinstance(title, str):
        raise ValueError("Issue requires integer number and string title")
    if len(types) != 1:
        raise ValueError(f"#{number}: expected exactly one decision-map type label")
    if len(interactions) != 1:
        raise ValueError(f"#{number}: expected exactly one decision-map interaction label")
    if degraded:
        blockers = tuple(int(value) for value in _CHILD_REFERENCE.findall(_blocked_by_body(issue)))
    else:
        blockers = tuple(
            blocker["number"]
            for blocker in issue.get("blockedBy", [])
            if isinstance(blocker, dict) and isinstance(blocker.get("number"), int)
        )
    assignees = issue.get("assignees", [])
    owner = next(
        (
            assignee.get("login")
            for assignee in assignees
            if isinstance(assignee, dict) and isinstance(assignee.get("login"), str)
        ),
        None,
    )
    state = issue.get("state")
    if not isinstance(state, str):
        raise ValueError(f"#{number}: missing state")
    return Ticket(
        number=number,
        title=title,
        open=state.upper() == "OPEN",
        type=types[0],
        interaction=interactions[0],
        blocker_numbers=blockers,
        owner=owner,
        claim=winning_claim(issue.get("comments", []), now=now),
    )


def _run_gh(arguments: Sequence[str]) -> Any:
    completed = subprocess.run(["gh", *arguments], capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(
            f"gh {' '.join(arguments)} failed: {completed.stderr.strip()}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"gh {' '.join(arguments)} returned invalid JSON") from error


def _read_github_map(map_number: int, *, degraded: bool) -> tuple[tuple[Ticket, ...], str]:
    map_issue = _run_gh(["issue", "view", str(map_number), "--json", "number,title,body"])
    if not degraded:
        probe = subprocess.run(
            ["gh", "issue", "view", str(map_number), "--json", "blockedBy"],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            degraded = True
    fields = ["number", "title", "state", "assignees", "labels", "comments", "body"]
    if not degraded:
        fields.extend(["parent", "blockedBy"])
    issues = _run_gh(
        [
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            ",".join(fields),
        ]
    )
    materialized = (map_issue, *issues)
    now = datetime.now(UTC)
    return (
        normalize_github_issues(
            materialized, map_number=map_number, now=now, degraded=degraded
        ),
        _section_text(str(map_issue.get("body", "")), "Not yet specified"),
    )


def _database_comment_id(comment: dict[str, Any]) -> int | None:
    """Return GitHub's monotonic database comment id from a comment URL."""

    url = comment.get("url")
    if isinstance(url, str):
        match = _ISSUE_COMMENT_ID.search(url)
        if match is not None:
            return int(match.group(1))
    legacy_id = comment.get("id")
    return legacy_id if isinstance(legacy_id, int) else None


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(UTC)


def _blocked_by_body(issue: dict[str, Any]) -> str:
    match = _BLOCKED_BY.search(str(issue.get("body", "")))
    return match.group(1) if match else ""


def _section_text(text: str, title: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(title)}\s*$\n(.*?)(?=^##\s+|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _ticket_number(path: Path) -> int:
    match = re.match(r"(\d+)-", path.name)
    if match is None:
        raise ValueError(f"Ticket file must start with a number: {path}")
    return int(match.group(1))


def _title_from_text(text: str, *, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    return match.group(1) if match else fallback


def _read_local_claim(
    path: Path,
    *,
    now: datetime,
    ttl: timedelta = timedelta(hours=24),
) -> Claim | None:
    if not path.exists():
        return None
    fields = {name: value for name, value in _CLAIM_FIELD.findall(path.read_text(encoding="utf-8"))}
    session = fields.get("session")
    raw_timestamp = fields.get("claimed-at")
    if not session or not raw_timestamp:
        raise ValueError(f"Claim lock is malformed: {path}")
    try:
        claimed_at = _parse_timestamp(raw_timestamp)
    except ValueError as error:
        raise ValueError(f"Claim lock is malformed: {path}") from error
    if now - claimed_at > ttl:
        return None
    try:
        ticket_number = int(path.stem)
    except ValueError as error:
        raise ValueError(f"Claim lock has invalid ticket name: {path}") from error
    return Claim(ticket_number, session, claimed_at)


def _closed_ticket(number: int) -> Ticket:
    return Ticket(number, "external closed blocker", False, "", "", (), None, None)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--map", type=int, help="GitHub decision-map issue number")
    source.add_argument("--local", type=Path, help="Local .docs/decision-maps effort directory")
    parser.add_argument("--degraded", action="store_true", help="Parse generated child and blocker links")
    parser.add_argument("--afk", action="store_true", help="Show only AFK frontier tickets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    now = datetime.now(UTC)
    if args.local is not None:
        tickets, fog = normalize_local_map(args.local, now=now)
    else:
        tickets, fog = _read_github_map(args.map, degraded=args.degraded)
    print(format_report(tickets, fog=fog, afk_only=args.afk))
    return 0


if __name__ == "__main__":
    sys.exit(main())
