"""Consumer-visible cutoff, duplicate and telemetry aggregation boundaries."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from inventory_claude import parse_file as parse_claude
from inventory_codex import parse_file as parse_codex
from inventory_report import build_report
from inventory_types import (
    InstalledSkill,
    Inventory,
    ParsedFile,
    ReadAttempt,
    ReadResult,
    UsageObservation,
)

CLOCK = datetime(2025, 1, 31, tzinfo=UTC)


def _report(
    files: list[ParsedFile], *, harness: str = "omp"
) -> tuple[dict[str, object], dict[str, object]]:
    from inventory_types import Harness

    return build_report(
        harness=cast(Harness, harness),
        parsed=files,
        inventory=Inventory(),
        as_of=CLOCK,
        window_days=10,
        snapshot={"valid": True, "files": len(files)},
        input_issues=Counter(),
    )


def _counts(report: dict[str, object], window: str) -> dict[str, object]:
    return cast(dict[str, object], cast(dict[str, object], report["events"])[window])


def test_future_result_does_not_resolve_a_call_at_the_cutoff() -> None:
    old = ReadAttempt(
        "fictional-session",
        "old-call",
        CLOCK - timedelta(days=20),
        "fictional-skill",
        "uri",
        True,
        False,
        "old-fingerprint",
        "main",
    )
    recent = ReadAttempt(
        "fictional-session",
        "recent-call",
        CLOCK - timedelta(days=1),
        "fictional-skill",
        "uri",
        True,
        False,
        "recent-fingerprint",
        "main",
    )
    file = ParsedFile(
        "opaque-file",
        "main",
        sessions={"fictional-session": "main"},
        attempts=[old, recent],
        results=[
            ReadResult(old.session_id, old.call_id, True, CLOCK - timedelta(days=19)),
            ReadResult(
                recent.session_id, recent.call_id, True, CLOCK + timedelta(days=1)
            ),
        ],
    )
    report, _ = _report([file])
    assert _counts(report, "all_observed")["successful_reads"] == 1
    assert _counts(report, "within_window")["successful_reads"] == 0
    assert _counts(report, "within_window")["unresolved_results"] == 1
    assert report["status"] == "complete"


def test_copied_calls_are_deduplicated_but_physical_file_coverage_is_not() -> None:
    call = ReadAttempt(
        "fictional-session",
        "call",
        CLOCK,
        "fictional-skill",
        "uri",
        True,
        False,
        "same-payload",
        "sub",
    )
    files = [
        ParsedFile(
            "original", "sub", sessions={"fictional-session": "sub"}, attempts=[call]
        ),
        ParsedFile(
            "fork-copy", "sub", sessions={"fictional-session": "sub"}, attempts=[call]
        ),
    ]
    report, _ = _report(files)
    counts = _counts(report, "all_observed")
    assert counts["read_attempts"] == 1
    assert counts["files_with_reads"] == 2
    assert counts["files_with_reads_by_cohort"] == {
        "main": 0,
        "sub": 2,
        "nested": 0,
        "unknown": 0,
    }


def test_conflicting_copied_call_refuses_complete_measurement() -> None:
    original = ReadAttempt(
        "fictional-session",
        "call",
        CLOCK,
        "one-skill",
        "uri",
        True,
        False,
        "one-payload",
        "sub",
    )
    conflicting = ReadAttempt(
        "fictional-session",
        "call",
        CLOCK,
        "other-skill",
        "uri",
        True,
        False,
        "different-payload",
        "sub",
    )
    report, _ = _report(
        [
            ParsedFile("original", "sub", attempts=[original]),
            ParsedFile("fork-copy", "sub", attempts=[conflicting]),
        ]
    )
    assert report["status"] == "incomplete"
    assert report["diagnostics"] == {"conflicting_duplicate_event": 1}
    assert _counts(report, "all_observed")["read_attempts"] == 1


def test_claude_stream_chunks_are_not_added_as_separate_requests() -> None:
    chunks = [
        UsageObservation(
            ("fictional-session", "provider-message"),
            CLOCK,
            "claude.usage",
            "per_message",
            {"input_tokens": 100, "output_tokens": 2},
        ),
        UsageObservation(
            ("fictional-session", "provider-message"),
            CLOCK,
            "claude.usage",
            "per_message",
            {"input_tokens": 100, "output_tokens": 12},
        ),
        UsageObservation(
            ("fictional-session", "other-message"),
            CLOCK,
            "claude.usage",
            "per_message",
            {"input_tokens": 50, "output_tokens": 3},
        ),
    ]
    report, _ = _report([ParsedFile("opaque", "main", usage=chunks)], harness="claude")
    usage = cast(dict[str, object], report["usage"])
    assert usage["counter_sums_separated_by_kind"] == {
        "per_message": {"input_tokens": 150, "output_tokens": 15}
    }
    assert usage["deduplicated_observations"] == 2


def test_codex_cumulative_and_last_counters_are_separate_and_loads_unavailable() -> (
    None
):
    observations = [
        UsageObservation(
            ("fictional-session", "event-a"),
            CLOCK,
            "codex.usage",
            "last",
            {"input_tokens": 10},
        ),
        UsageObservation(
            ("fictional-session", "event-b"),
            CLOCK,
            "codex.usage",
            "last",
            {"input_tokens": 20},
        ),
        UsageObservation(
            ("fictional-session", "event-a"),
            CLOCK,
            "codex.usage",
            "cumulative",
            {"input_tokens": 10},
        ),
        UsageObservation(
            ("fictional-session", "event-b"),
            CLOCK,
            "codex.usage",
            "cumulative",
            {"input_tokens": 30},
        ),
    ]
    report, _ = _report(
        [ParsedFile("opaque", "unknown", usage=observations)], harness="codex"
    )
    usage = cast(dict[str, object], report["usage"])
    assert usage["counter_sums_separated_by_kind"] == {"last": {"input_tokens": 30}}
    assert usage["cumulative_session_maxima_separate_not_billing"] == {
        "input_tokens": 30
    }
    assert cast(dict[str, object], report["events"])["all_observed"] is None


def test_private_identity_is_installed_file_sourced_not_uninstalled_log_name(
    tmp_path: Path,
) -> None:
    installed = InstalledSkill(
        "installed-example",
        "An installed example.",
        tmp_path / "SKILL.md",
        (),
        "managed",
    )
    call = ReadAttempt(
        "fictional-session",
        "call",
        CLOCK,
        "uninstalled-private-example",
        "uri",
        True,
        False,
        "payload",
        "main",
    )
    report, private = build_report(
        harness="omp",
        parsed=[ParsedFile("opaque", "main", attempts=[call])],
        inventory=Inventory(entries=[installed]),
        as_of=CLOCK,
        window_days=10,
        snapshot={"valid": True},
        input_issues=Counter(),
    )
    rows = cast(list[dict[str, object]], private["skills"])
    assert [row["name"] for row in rows] == ["installed-example"]
    assert rows[0]["observed_read_attempts"] == 0
    assert rows[0]["authored_creation_date"] is None
    assert _counts(report, "all_observed")["read_attempts"] == 1


def test_cache_writes_and_cost_estimates_do_not_imply_measured_cache_reads() -> None:
    for values, expected in [
        ({"input": 10, "cacheWrite": 4}, "unavailable"),
        ({"input": 10, "cost_cacheRead": 0.01}, "unavailable"),
        ({"input": 10, "cacheRead": 0}, "whole_request_fields_only"),
    ]:
        usage = UsageObservation(
            ("fictional-session", "message"), CLOCK, "omp.usage", "per_message", values
        )
        report, _ = _report(
            [
                ParsedFile(
                    "opaque",
                    "main",
                    sessions={"fictional-session": "main"},
                    usage=[usage],
                )
            ]
        )
        assert (
            cast(dict[str, object], report["usage"])["cache_read_exposure"] == expected
        )


def test_missing_init_is_a_coverage_gap_not_a_disclosure_observation() -> None:
    from inventory_omp import parse_file

    inventory = Inventory()
    header = {
        "type": "session",
        "version": 3,
        "id": "fictional-main",
        "timestamp": "2025-01-01T00:00:00Z",
    }
    init = {
        "type": "session_init",
        "id": "fictional-init",
        "timestamp": "2025-01-01T00:00:01Z",
        "systemPrompt": "<skills>\n- fictional-skill: A description.\n</skills>",
    }
    files = [
        parse_file([header], inventory=inventory, file_key="main", cohort_hint="main"),
        parse_file(
            [header | {"id": "fictional-sub"}, init],
            inventory=inventory,
            file_key="sub",
            cohort_hint="sub",
        ),
    ]
    report, _ = _report(files)
    exposure = cast(dict[str, object], report["exposure"])
    assert exposure["observations"] == 1
    assert exposure["available"] == 1
    assert exposure["files_without_persisted_disclosure"] == 1


def test_aggregate_usage_reports_tokens_without_disclosing_recorded_cost_values() -> (
    None
):
    usage = UsageObservation(
        ("fictional-session", "message"),
        CLOCK,
        "omp.usage",
        "per_message",
        {"input": 100, "cost_input": 0.12345678234},
    )
    report, _ = _report(
        [
            ParsedFile(
                "opaque",
                "main",
                sessions={"fictional-session": "main"},
                usage=[usage],
            )
        ]
    )
    measured = cast(dict[str, object], report["usage"])
    assert measured["counter_sums_separated_by_kind"] == {"per_message": {"input": 100}}
    assert measured["persisted_cost_estimate_fields"] == ["cost_input"]


def test_dynamic_listings_cannot_dilute_the_initial_source_median() -> None:
    initial = "- fictional-skill: " + "Detailed fictional description. " * 8
    dynamic = "- fictional-skill"
    records: list[dict[str, object]] = []
    for index in range(4):
        records.append(
            {
                "type": "attachment",
                "uuid": f"fictional-listing-{index}",
                "sessionId": "fictional-session",
                "timestamp": "2025-01-25T10:00:00Z",
                "version": "2.1.301",
                "isSidechain": False,
                "attachment": {
                    "type": "skill_listing",
                    "content": initial if index == 0 else dynamic,
                    "names": ["fictional-skill"],
                    "skillCount": 1,
                    "isInitial": index == 0,
                },
            }
        )
    parsed = parse_claude(
        records, inventory=Inventory(), file_key="opaque", cohort_hint="main"
    )
    report, _ = _report([parsed], harness="claude")
    assert report["status"] == "complete"
    exposure = cast(dict[str, object], report["exposure"])
    monthly = cast(
        dict[str, dict[str, dict[str, object]]], exposure["monthly_by_source"]
    )
    assert monthly["claude_skill_listing_initial"]["2025-01"][
        "median_observed_block_chars"
    ] == len(initial)
    assert monthly["claude_skill_listing_dynamic"]["2025-01"][
        "median_observed_block_chars"
    ] == len(dynamic)


def test_identical_codex_telemetry_values_do_not_collapse_distinct_observations() -> (
    None
):
    values = {
        "input_tokens": 10,
        "cached_input_tokens": 3,
        "output_tokens": 5,
        "reasoning_output_tokens": 2,
        "total_tokens": 15,
    }
    records: list[dict[str, object]] = [
        {
            "timestamp": "2025-01-25T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "fictional-codex-session",
                "timestamp": "2025-01-25T10:00:00Z",
                "cli_version": "0.153.4",
                "source": "cli",
            },
        }
    ]
    for minute in (1, 2):
        records.append(
            {
                "timestamp": f"2025-01-25T10:0{minute}:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": values, "total_token_usage": values},
                },
            }
        )
    parsed = parse_codex(
        records, inventory=Inventory(), file_key="opaque", cohort_hint="unknown"
    )
    report, _ = _report([parsed], harness="codex")
    assert report["status"] == "complete"
    usage = cast(dict[str, object], report["usage"])
    totals = cast(dict[str, dict[str, int]], usage["counter_sums_separated_by_kind"])
    assert totals["last"]["input_tokens"] == 20
    assert totals["last"]["total_tokens"] == 30
    maxima = cast(
        dict[str, int], usage["cumulative_session_maxima_separate_not_billing"]
    )
    assert maxima["input_tokens"] == 10
    assert maxima["total_tokens"] == 15
    assert usage["cache_read_exposure"] == "persisted_token_count_telemetry_only"


def test_private_counts_remain_unavailable_without_any_valid_input_schema() -> None:
    inventory = Inventory(
        entries=[
            InstalledSkill(
                "fictional-skill",
                "Fictional description.",
                Path("/fictional/SKILL.md"),
                (),
                "user",
            )
        ]
    )
    for harness in ("omp", "claude", "codex"):
        _, private = build_report(
            harness=harness,
            parsed=[ParsedFile("opaque", "unknown", schema_supported=False)],
            inventory=inventory,
            as_of=CLOCK,
            window_days=10,
            snapshot={"valid": True, "files": 1},
            input_issues=Counter(),
        )
        rows = cast(list[dict[str, object]], private["skills"])
        assert rows[0]["observed_read_attempts"] is None
        assert rows[0]["observed_invocation_attempts"] is None
        assert rows[0]["first_read_date"] is None
        assert rows[0]["last_read_date"] is None
