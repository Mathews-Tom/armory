"""Eligibility evidence must not inflate sessions or expose source identities."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from inventory_report import build_report
from inventory_types import (
    EntryCost,
    Exposure,
    InstalledSkill,
    Inventory,
    Invocation,
    ParsedFile,
    ReadAttempt,
)

CLOCK = datetime(2025, 1, 31, tzinfo=UTC)
NAME = "fictional-clarifier"


def observation(
    session: str, record: str, group: str | None, *, days: int = 1, seconds: int = 0
) -> Exposure:
    return Exposure(
        timestamp=CLOCK - timedelta(days=days) + timedelta(seconds=seconds),
        session_id=session,
        cohort="sub",
        source="omp_session_init",
        status="complete",
        block_chars=42,
        wrapper_chars=18,
        entry_chars=24,
        entries=(EntryCost(NAME, 24),),
        record_id=record,
        fingerprint=f"fictional-payload-{record}",
        main_task_group=group,
    )


def file(key: str, *observations: Exposure) -> ParsedFile:
    return ParsedFile(
        key,
        "sub",
        sessions={item.session_id: item.cohort for item in observations},
        exposures=list(observations),
    )


def private_report(
    files: list[ParsedFile],
) -> tuple[dict[str, object], dict[str, object]]:
    return build_report(
        harness="omp",
        parsed=files,
        inventory=Inventory(
            entries=[
                InstalledSkill(
                    NAME,
                    "Fictional description.",
                    Path("/fictional/SKILL.md"),
                    (),
                    "managed",
                )
            ]
        ),
        as_of=CLOCK,
        window_days=10,
        snapshot={"valid": True, "closed": True, "files": len(files)},
        input_issues=Counter(),
    )


def row(private: dict[str, object]) -> dict[str, object]:
    return cast(list[dict[str, object]], private["skills"])[0]


def test_reinitializations_and_copied_files_cannot_inflate_ordinary_sessions() -> None:
    files: list[ParsedFile] = []
    for index in range(20):
        observations = [
            observation(
                f"not-for-output-session-{index}",
                f"init-{index}-{repeat}",
                f"not-for-output-group-{index // 4}",
                seconds=repeat,
            )
            for repeat in range(4)
        ]
        files.extend(
            [
                file(f"opaque-{index}", *observations),
                file(f"copy-{index}", *observations),
            ]
        )
    public, private = private_report(files)
    measured = row(private)
    assert public["status"] == "complete"
    assert measured["inventory_present_subagent_snapshots"] == 20
    assert measured["inventory_present_main_task_groups"] == 5
    assert measured["inventory_presence_grouping_complete"] is True
    assert private["inventory_observations_by_utc_day"] == {"2025-01-30": 20}
    encoded = json.dumps(private)
    assert "not-for-output-session" not in encoded
    assert "not-for-output-group" not in encoded


def test_conflicting_physical_parent_groups_lose_opportunity_without_payload_conflict() -> (
    None
):
    first = observation("fictional-session", "same-init", "fictional-parent-one")
    second = replace(first, main_task_group="fictional-parent-two")
    public, private = private_report([file("one", first), file("two", second)])
    assert public["status"] == "complete"
    assert row(private)["inventory_present_subagent_snapshots"] == 0
    assert row(private)["inventory_present_main_task_groups"] == 0
    assert row(private)["inventory_presence_grouping_complete"] is False
    assert private["inventory_observations_by_utc_day"] == {}


def test_unknown_parent_or_main_session_cannot_supply_subagent_opportunities() -> None:
    unknown = observation("fictional-orphan", "orphan-init", None)
    main = replace(
        observation("fictional-main", "main-init", "fictional-parent"), cohort="main"
    )
    _, private = private_report([file("orphan", unknown), file("main", main)])
    assert row(private)["inventory_present_subagent_snapshots"] == 0
    assert row(private)["inventory_present_main_task_groups"] == 0
    assert row(private)["inventory_presence_grouping_complete"] is False
    assert private["inventory_observations_by_utc_day"] == {}


def test_a_continuing_old_session_is_not_a_new_ordinary_session_for_dwell() -> None:
    old = observation("fictional-continuation", "old", "fictional-parent", days=20)
    recent = observation("fictional-continuation", "recent", "fictional-parent")
    _, private = private_report([file("opaque", old, recent)])
    assert row(private)["inventory_present_subagent_snapshots"] == 1
    assert private["inventory_observations_by_utc_day"] == {}


def test_window_use_dates_and_gap_do_not_include_future_calls_or_erase_old_gaps() -> (
    None
):
    attempts = [
        ReadAttempt(
            "fictional-session",
            f"call-{days}",
            CLOCK - timedelta(days=days),
            NAME,
            "uri",
            True,
            False,
            f"fingerprint-{days}",
            "sub",
        )
        for days in (20, 10, 1, -1)
    ]
    invocation = Invocation(
        "fictional-session",
        "slash",
        CLOCK - timedelta(days=1),
        NAME,
        "slash",
        "slash-fingerprint",
        "sub",
    )
    parsed = ParsedFile(
        "opaque",
        "sub",
        sessions={"fictional-session": "sub"},
        attempts=attempts,
        invocations=[invocation],
    )
    _, private = private_report([parsed])
    measured = row(private)
    assert measured["window_read_attempts"] == 2
    assert measured["window_invocation_attempts"] == 1
    assert measured["window_first_use_date"] == "2025-01-21T00:00:00Z"
    assert measured["window_last_use_date"] == "2025-01-30T00:00:00Z"
    assert measured["largest_observed_inter_use_gap_days"] == 10
    assert private["observed_activity_after_as_of"] is True


def test_log_observed_dependencies_protect_only_installed_identity_rows() -> None:
    parsed = file(
        "opaque", observation("fictional-session", "init", "fictional-parent")
    )
    parsed.reference_names = {NAME, "not-for-output-uninstalled-log-name"}
    public, private = private_report([parsed])
    assert row(private)["log_observed_dependency"] is True
    assert row(private)["window_read_attempts"] == 0
    assert row(private)["window_invocation_attempts"] == 0
    assert "not-for-output-uninstalled-log-name" not in json.dumps(public)
    assert "not-for-output-uninstalled-log-name" not in json.dumps(private)
