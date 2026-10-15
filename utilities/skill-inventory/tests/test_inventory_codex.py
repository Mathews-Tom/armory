"""Synthetic Codex rollout fixtures: tagged-block spans, lineage, usage and fail-closed shapes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from inventory_codex import (
    ISSUE_CODES,
    SOURCE_BASE_INSTRUCTIONS,
    SOURCE_COMPACTED_REPLACEMENT,
    SOURCE_DEVELOPER_MESSAGE,
    SOURCE_TURN_DEVELOPER,
    SOURCE_TURN_USER,
    SOURCE_USAGE,
    SOURCE_USAGE_FORK,
    parse_file,
)
from inventory_types import Cohort, InstalledSkill, Inventory, ParsedFile

Record = dict[str, object]

# Exact release identities admitted by the approved contract; no ranges.
OBSERVED_VERSIONS = [
    "0.39.0",
    "0.57.0",
    "0.77.0",
    "0.79.0",
    "0.80.0",
    "0.94.0-alpha.10",
    "0.98.0",
    "0.100.0-alpha.10",
    "0.101.0",
    "0.107.0",
    "0.112.0",
    "0.114.0",
    "0.115.0-alpha.4",
    "0.116.0",
    "0.118.0",
    "0.118.0-alpha.2",
    "0.120.0",
    "0.122.0",
    "0.124.0",
    "0.128.0",
    "0.128.0-alpha.1",
    "0.129.0",
    "0.130.0",
    "0.131.0",
    "0.133.0",
    "0.134.0",
    "0.135.0",
    "0.136.0",
    "0.137.0",
    "0.144.1",
    "0.153.4",
]

TS = "2026-03-01T10:00:00.000Z"
T1 = "2026-03-01T10:05:00.000Z"
T2 = "2026-03-01T10:10:00.000Z"
T3 = "2026-03-01T10:15:00.000Z"
DT = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
DT1 = datetime(2026, 3, 1, 10, 5, 0, tzinfo=UTC)
DT2 = datetime(2026, 3, 1, 10, 10, 0, tzinfo=UTC)
DT3 = datetime(2026, 3, 1, 10, 15, 0, tzinfo=UTC)

ENTRY_AURORA = "- aurora: Draw northern lights (file: r0/aurora/SKILL.md)"
ENTRY_BIRCH = "- birch:forest: Plant trees (file: r0/birch/SKILL.md)"
LOOKALIKE_HOWTO = (
    "- cedar: Instructional bullet shaped like an entry (file: r0/cedar/SKILL.md)"
)
LOOKALIKE_ROOT = "- dune: Root bullet shaped like an entry (file: r0/dune/SKILL.md)"

# Skill roots precede Available skills; instructional sections follow it (observed template).
FULL_BLOCK = (
    "<skills_instructions>\n"
    "## Skills\n"
    "Intro prose.\n"
    "### Skill roots\n"
    f"{LOOKALIKE_ROOT}\n"
    "### Available skills\n"
    f"{ENTRY_AURORA}\n"
    f"{ENTRY_BIRCH}\n"
    "### How to use skills\n"
    f"{LOOKALIKE_HOWTO}\n"
    "- Plain instruction bullet\n"
    "</skills_instructions>"
)
# Newer template: no instructional section, so the closing tag ends the last entry.
TAIL_BLOCK = (
    "<skills_instructions>\n"
    "## Skills\n"
    "### Available skills\n"
    f"{ENTRY_AURORA}\n"
    f"{ENTRY_BIRCH}</skills_instructions>"
)


def inventory() -> Inventory:
    return Inventory(
        entries=[
            InstalledSkill(
                "aurora", "d", Path("/skills/aurora/SKILL.md"), (), "managed"
            )
        ],
        direct_paths={"/skills/aurora/SKILL.md": "aurora"},
    )


def parse(records: list[Record], hint: Cohort = "main") -> ParsedFile:
    return parse_file(
        iter(records), inventory=inventory(), file_key="file-1", cohort_hint=hint
    )


def rec(kind: str, payload: object, ts: object = TS) -> Record:
    return {"timestamp": ts, "type": kind, "payload": payload}


def meta(
    session_id: str = "thread-a",
    *,
    version: str = "0.153.4",
    ts: str = TS,
    **extra: object,
) -> Record:
    payload: Record = {
        "id": session_id,
        "timestamp": ts,
        "cli_version": version,
        "originator": "synthetic_cli",
        "source": "cli",
    }
    payload.update(extra)
    return rec("session_meta", payload, ts)


def spawn(depth: object = 1, parent: str | None = "thread-p") -> Record:
    return {
        "subagent": {
            "thread_spawn": {
                "depth": depth,
                "parent_thread_id": parent,
                "agent_nickname": "n",
                "agent_role": None,
                "agent_path": None,
            }
        }
    }


def developer(*texts: str, ts: str = TS) -> Record:
    return rec(
        "response_item",
        {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": text} for text in texts],
        },
        ts,
    )


def turn(ts: str = TS, **fields: object) -> Record:
    payload: Record = {"cwd": "/synthetic", "model": "synthetic-model"}
    payload.update(fields)
    return rec("turn_context", payload, ts)


def counters(scale: int = 1) -> dict[str, int]:
    return {
        "input_tokens": 100 * scale,
        "cached_input_tokens": 40 * scale,
        "output_tokens": 10 * scale,
        "reasoning_output_tokens": 3 * scale,
        "total_tokens": 110 * scale,
    }


def token(info: object, ts: str = TS) -> Record:
    return rec(
        "event_msg", {"type": "token_count", "info": info, "rate_limits": None}, ts
    )


def usage_info(
    total: Mapping[str, object] | None = None,
    last: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "total_token_usage": total if total is not None else counters(5),
        "last_token_usage": last if last is not None else counters(1),
        "model_context_window": 200000,
    }


def assert_issues(parsed: ParsedFile, expected: dict[str, int]) -> None:
    assert dict(parsed.issues) == expected
    assert set(parsed.issues) <= ISSUE_CODES


def entries_of(parsed: ParsedFile) -> list[tuple[str, int]]:
    return [(e.name, e.chars) for x in parsed.exposures for e in x.entries]


# -- versions -----------------------------------------------------------------


@pytest.mark.parametrize("version", OBSERVED_VERSIONS)
def test_every_observed_version_is_admitted_with_its_identity(version: str) -> None:
    parsed = parse([meta(version=version), developer(FULL_BLOCK)])
    assert parsed.schema_supported
    assert parsed.versions == {f"codex-cli-{version}"}
    assert_issues(parsed, {})
    assert len(parsed.exposures) == 1


@pytest.mark.parametrize(
    "version",
    [
        "0.153.5",
        "0.153",
        "0.153.4-alpha.1",
        "0.153.4+local",
        " 0.153.4",
        "v0.153.4",
        "0.100.0",
        "0.118.0-alpha.1",
        "1.0.0",
        "0.0.0-SECRETVERSION",
    ],
)
def test_unlisted_versions_fail_closed_without_measuring(version: str) -> None:
    parsed = parse([meta(version=version), developer(FULL_BLOCK), token(usage_info())])
    assert not parsed.schema_supported
    assert_issues(parsed, {"unsupported_cli_version": 1})
    assert parsed.versions == set()
    assert parsed.sessions == {}
    assert parsed.exposures == []
    assert parsed.usage == []
    assert parsed.counts["skipped_records"] == 2
    assert "SECRETVERSION" not in repr(
        (dict(parsed.issues), dict(parsed.counts), parsed.versions)
    )


# -- tagged-block measurement ---------------------------------------------------


def test_only_the_tagged_span_and_available_entries_are_measured() -> None:
    text = "Preamble that is not charged.\n" + FULL_BLOCK + "\nTrailing prose."
    parsed = parse([meta(), developer(text, ts=T1)])
    (exposure,) = parsed.exposures
    aurora = len(ENTRY_AURORA) + 1
    birch = len(ENTRY_BIRCH) + 1
    assert exposure.status == "complete"
    assert exposure.block_chars == len(FULL_BLOCK)
    assert exposure.entry_chars == aurora + birch
    assert exposure.wrapper_chars == len(FULL_BLOCK) - aurora - birch
    assert [(e.name, e.chars) for e in exposure.entries] == [
        ("aurora", aurora),
        ("birch:forest", birch),
    ]
    assert exposure.listed_names == 2
    assert exposure.prompt_chars is None
    assert exposure.virtual_block_chars == exposure.block_chars
    assert exposure.separator_chars == 0
    assert exposure.block_separator_chars == 0
    assert exposure.declared_count is None
    assert exposure.timestamp == DT1
    assert exposure.session_id == "thread-a"
    assert parsed.counts["skills_blocks"] == 1


def test_entry_shaped_bullets_outside_available_are_excluded_on_both_sides() -> None:
    parsed = parse([meta(), developer(FULL_BLOCK)])
    names = [name for name, _ in entries_of(parsed)]
    assert names == ["aurora", "birch:forest"]
    assert "cedar" not in names
    assert "dune" not in names


def test_available_section_ends_at_a_peer_or_higher_heading() -> None:
    after_roots = (
        "<skills_instructions>\n"
        "### Available skills\n"
        f"{ENTRY_AURORA}\n"
        "### Skill roots\n"
        f"{LOOKALIKE_ROOT}\n"
        "</skills_instructions>"
    )
    after_higher = (
        "<skills_instructions>\n"
        "### Available skills\n"
        f"{ENTRY_AURORA}\n"
        "## Other\n"
        f"{LOOKALIKE_HOWTO}\n"
        "</skills_instructions>"
    )
    parsed = parse([meta(), developer(after_roots, after_higher)])
    assert entries_of(parsed) == [
        ("aurora", len(ENTRY_AURORA) + 1),
        ("aurora", len(ENTRY_AURORA) + 1),
    ]


def test_closing_tag_ends_last_entry_without_a_line_terminator() -> None:
    parsed = parse([meta(), developer(TAIL_BLOCK)])
    (exposure,) = parsed.exposures
    assert exposure.block_chars == len(TAIL_BLOCK)
    assert [(e.name, e.chars) for e in exposure.entries] == [
        ("aurora", len(ENTRY_AURORA) + 1),
        ("birch:forest", len(ENTRY_BIRCH)),
    ]
    assert exposure.wrapper_chars == len(TAIL_BLOCK) - exposure.entry_chars


def test_blank_lines_in_available_are_wrapper_not_entry_cost() -> None:
    block = (
        "<skills_instructions>\n### Available skills\n"
        f"{ENTRY_AURORA}\n\n{ENTRY_BIRCH}\n"
        "</skills_instructions>"
    )
    (exposure,) = parse([meta(), developer(block)]).exposures
    assert exposure.entry_chars == len(ENTRY_AURORA) + 1 + len(ENTRY_BIRCH) + 1
    assert exposure.wrapper_chars == len(block) - exposure.entry_chars
    assert exposure.wrapper_chars > len("<skills_instructions>") + len(
        "</skills_instructions>"
    )


def test_duplicate_names_are_preserved_as_separate_entries() -> None:
    block = (
        "<skills_instructions>\n### Available skills\n"
        f"{ENTRY_AURORA}\n{ENTRY_AURORA}\n"
        "</skills_instructions>"
    )
    (exposure,) = parse([meta(), developer(block)]).exposures
    assert [e.name for e in exposure.entries] == ["aurora", "aurora"]
    assert exposure.listed_names == 2


def test_empty_available_section_is_a_measured_block_with_no_entries() -> None:
    block = "<skills_instructions>\n### Available skills\n</skills_instructions>"
    (exposure,) = parse([meta(), developer(block)]).exposures
    assert exposure.block_chars == len(block)
    assert exposure.entries == ()
    assert exposure.entry_chars == 0
    assert exposure.wrapper_chars == len(block)


# -- sources and observations -----------------------------------------------------


def test_each_surface_observation_is_preserved_with_its_own_timestamp_and_source() -> (
    None
):
    records = [
        meta(base_instructions={"text": "Prefix. " + FULL_BLOCK}),
        developer(FULL_BLOCK, TAIL_BLOCK, ts=T1),
        turn(
            ts=T2,
            developer_instructions=TAIL_BLOCK,
            user_instructions=FULL_BLOCK,
        ),
        developer(FULL_BLOCK, ts=T3),
    ]
    parsed = parse(records)
    assert_issues(parsed, {})
    observed = [(x.source, x.timestamp, x.block_chars) for x in parsed.exposures]
    assert observed == [
        (SOURCE_BASE_INSTRUCTIONS, DT, len(FULL_BLOCK)),
        (SOURCE_DEVELOPER_MESSAGE, DT1, len(FULL_BLOCK)),
        (SOURCE_DEVELOPER_MESSAGE, DT1, len(TAIL_BLOCK)),
        (SOURCE_TURN_DEVELOPER, DT2, len(TAIL_BLOCK)),
        (SOURCE_TURN_USER, DT2, len(FULL_BLOCK)),
        (SOURCE_DEVELOPER_MESSAGE, DT3, len(FULL_BLOCK)),
    ]
    assert {x.source for x in parsed.exposures} == {
        SOURCE_BASE_INSTRUCTIONS,
        SOURCE_DEVELOPER_MESSAGE,
        SOURCE_TURN_DEVELOPER,
        SOURCE_TURN_USER,
    }
    assert {x.record_id for x in parsed.exposures} == {None}
    assert {x.fingerprint for x in parsed.exposures} == {None}
    assert parsed.coverage["exposure"] == "complete"


def test_repeated_identical_blocks_are_not_collapsed_or_summed() -> None:
    parsed = parse(
        [
            meta(),
            developer(FULL_BLOCK, ts=T1),
            developer(FULL_BLOCK, ts=T2),
            turn(ts=T2, user_instructions=FULL_BLOCK),
        ]
    )
    assert [x.block_chars for x in parsed.exposures] == [len(FULL_BLOCK)] * 3
    assert parsed.counts["skills_blocks"] == 3


def test_other_roles_and_record_kinds_never_become_exposures() -> None:
    records = [
        meta(),
        rec(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": FULL_BLOCK},
                    {"type": "input_image", "image_url": "x"},
                ],
            },
        ),
        rec(
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": FULL_BLOCK}],
            },
        ),
        rec(
            "response_item",
            {"type": "function_call_output", "call_id": "c1", "output": FULL_BLOCK},
        ),
        rec("event_msg", {"type": "user_message", "message": FULL_BLOCK}),
    ]
    parsed = parse(records)
    assert_issues(parsed, {})
    assert parsed.exposures == []
    assert parsed.coverage["exposure"] == "unavailable"
    assert parsed.counts["developer_messages"] == 0


def test_text_without_a_tagged_block_is_not_a_zero_exposure() -> None:
    parsed = parse(
        [
            meta(),
            developer("Plain developer guidance, no block."),
            turn(user_instructions="Project notes."),
        ]
    )
    assert_issues(parsed, {})
    assert parsed.exposures == []
    assert parsed.counts["instruction_texts_without_skills_block"] == 2
    assert parsed.coverage["exposure"] == "unavailable"


def test_tag_matching_is_exact() -> None:
    wrong_case = FULL_BLOCK.replace("skills_instructions", "Skills_Instructions")
    parsed = parse([meta(), developer(wrong_case)])
    assert_issues(parsed, {})
    assert parsed.exposures == []


def _history_developer(*texts: str) -> dict[str, object]:
    return {
        "type": "message",
        "role": "developer",
        "content": [{"type": "input_text", "text": text} for text in texts],
    }


def test_compacted_developer_history_is_measured_as_physical_observations() -> None:
    history = [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": FULL_BLOCK}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": FULL_BLOCK}],
        },
        {"type": "compaction", "encrypted_content": "opaque"},
        _history_developer(FULL_BLOCK, TAIL_BLOCK),
    ]
    compacted = {"message": "", "replacement_history": history}
    parsed = parse(
        [
            meta(),
            developer(FULL_BLOCK, ts=T1),
            rec("compacted", compacted, ts=T2),
            rec("compacted", compacted, ts=T3),
        ]
    )
    assert_issues(parsed, {})
    observed = [(x.source, x.timestamp, x.block_chars) for x in parsed.exposures]
    assert observed == [
        (SOURCE_DEVELOPER_MESSAGE, DT1, len(FULL_BLOCK)),
        (SOURCE_COMPACTED_REPLACEMENT, DT2, len(FULL_BLOCK)),
        (SOURCE_COMPACTED_REPLACEMENT, DT2, len(TAIL_BLOCK)),
        (SOURCE_COMPACTED_REPLACEMENT, DT3, len(FULL_BLOCK)),
        (SOURCE_COMPACTED_REPLACEMENT, DT3, len(TAIL_BLOCK)),
    ]
    assert {x.record_id for x in parsed.exposures} == {None}
    assert parsed.counts["compacted_records"] == 2
    assert parsed.counts["compacted_developer_messages"] == 2
    assert parsed.counts["skills_blocks"] == 5


def test_compacted_history_without_blocks_is_not_a_zero_exposure() -> None:
    parsed = parse(
        [
            meta(),
            rec(
                "compacted",
                {
                    "message": "",
                    "replacement_history": [_history_developer("Plain guidance.")],
                },
            ),
            rec("compacted", {"message": "", "replacement_history": []}),
        ]
    )
    assert_issues(parsed, {})
    assert parsed.exposures == []
    assert parsed.counts["instruction_texts_without_skills_block"] == 1
    assert parsed.coverage["exposure"] == "unavailable"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"replacement_history": "not-a-list"}, "invalid_list"),
        ({"replacement_history": ["not-an-object"]}, "invalid_payload"),
        (
            {
                "replacement_history": [
                    _history_developer(
                        FULL_BLOCK, "<skills_instructions>\n### Available skills\n"
                    )
                ]
            },
            "unterminated_skills_block",
        ),
        (
            {
                "replacement_history": [
                    {
                        "type": "message",
                        "role": "developer",
                        "content": [{"type": "input_image"}],
                    }
                ]
            },
            "unknown_content_block",
        ),
        (
            {
                "replacement_history": [
                    {"type": "message", "role": "developer", "content": "text"}
                ]
            },
            "invalid_message",
        ),
    ],
)
def test_malformed_compacted_history_fails_its_record_and_measures_nothing_from_it(
    payload: dict[str, object], code: str
) -> None:
    parsed = parse(
        [
            meta(),
            rec("compacted", {"message": "", **payload}),
            developer(FULL_BLOCK, ts=T1),
        ]
    )
    assert_issues(parsed, {code: 1})
    assert parsed.schema_supported
    assert [x.source for x in parsed.exposures] == [SOURCE_DEVELOPER_MESSAGE]


# -- malformed tagging --------------------------------------------------------------

UNTERMINATED = "<skills_instructions>\n### Available skills\n" + ENTRY_AURORA + "\n"
MALFORMED_CASES = [
    pytest.param(UNTERMINATED, "unterminated_skills_block", id="unterminated"),
    pytest.param(
        "text</skills_instructions>", "unmatched_skills_close_tag", id="stray-close"
    ),
    pytest.param(
        "<skills_instructions><skills_instructions></skills_instructions>",
        "malformed_skills_block",
        id="nested-open",
    ),
    pytest.param(
        FULL_BLOCK + "\n" + TAIL_BLOCK, "multiple_skills_blocks", id="two-blocks"
    ),
    pytest.param(
        "<skills_instructions>\n## Skills\n</skills_instructions>",
        "missing_available_skills_section",
        id="no-available",
    ),
    pytest.param(
        "<skills_instructions>\n### Available skills\n- aurora: no file suffix\n"
        "</skills_instructions>",
        "invalid_skills_entry",
        id="bad-entry",
    ),
    pytest.param(
        "<skills_instructions>\n### Available skills\n"
        f"{ENTRY_AURORA}\ncontinuation prose\n</skills_instructions>",
        "invalid_skills_entry",
        id="continuation-line",
    ),
    pytest.param(
        "<skills_instructions>\n### Available skills\n"
        f"{ENTRY_AURORA}\n#### Nested\n</skills_instructions>",
        "invalid_available_skills_section",
        id="deeper-heading",
    ),
    pytest.param(
        "<skills_instructions>\n### Available skills\n"
        f"{ENTRY_AURORA}\n### Available skills\n{ENTRY_BIRCH}\n</skills_instructions>",
        "invalid_available_skills_section",
        id="repeated-available",
    ),
]


@pytest.mark.parametrize(("text", "code"), MALFORMED_CASES)
def test_malformed_blocks_fail_their_record_only(text: str, code: str) -> None:
    parsed = parse([meta(), developer(text), developer(FULL_BLOCK, ts=T1)])
    assert_issues(parsed, {code: 1})
    assert parsed.schema_supported
    assert [x.timestamp for x in parsed.exposures] == [DT1]
    assert parsed.counts["records"] == 3
    assert parsed.coverage["exposure"] == "complete"


def test_a_failing_item_discards_every_observation_from_its_record() -> None:
    parsed = parse([meta(), developer(FULL_BLOCK, UNTERMINATED)])
    assert_issues(parsed, {"unterminated_skills_block": 1})
    assert parsed.exposures == []
    assert parsed.counts["skills_blocks"] == 0
    assert parsed.coverage["exposure"] == "unavailable"


def test_block_split_across_content_items_is_not_stitched_together() -> None:
    head = "<skills_instructions>\n### Available skills\n" + ENTRY_AURORA + "\n"
    tail = "</skills_instructions>"
    parsed = parse([meta(), developer(head), developer(tail)])
    assert_issues(
        parsed, {"unterminated_skills_block": 1, "unmatched_skills_close_tag": 1}
    )
    assert parsed.exposures == []


def test_malformed_base_instructions_fail_the_observation_not_the_header() -> None:
    parsed = parse(
        [meta(base_instructions={"text": UNTERMINATED}), developer(FULL_BLOCK)]
    )
    assert_issues(parsed, {"unterminated_skills_block": 1})
    assert parsed.schema_supported
    assert parsed.sessions == {"thread-a": "main"}
    assert parsed.versions == {"codex-cli-0.153.4"}
    assert [x.source for x in parsed.exposures] == [SOURCE_DEVELOPER_MESSAGE]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            {"role": "developer", "content": [{"type": "input_image"}]},
            "unknown_content_block",
        ),
        ({"role": "developer", "content": ["text"]}, "invalid_content_block"),
        (
            {"role": "developer", "content": [{"type": "input_text"}]},
            "invalid_content_block",
        ),
        ({"role": "developer", "content": "text"}, "invalid_message"),
        ({"role": "system", "content": []}, "unknown_message_role"),
        ({"content": []}, "invalid_message"),
    ],
)
def test_malformed_message_shapes_fail_anonymously(
    payload: dict[str, object], code: str
) -> None:
    parsed = parse([meta(), rec("response_item", {"type": "message", **payload})])
    assert_issues(parsed, {code: 1})
    assert parsed.exposures == []


@pytest.mark.parametrize(
    "fields",
    [{"developer_instructions": 7}, {"user_instructions": ["x"]}],
)
def test_turn_context_instruction_fields_must_be_strings(
    fields: dict[str, object],
) -> None:
    parsed = parse([meta(), turn(**fields)])
    assert_issues(parsed, {"invalid_instructions_field": 1})


# -- lineage ------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["cli", "exec", "vscode"])
@pytest.mark.parametrize("hint", ["main", "sub", "nested", "unknown"])
def test_declared_interactive_sources_override_file_placement(
    source: str, hint: Cohort
) -> None:
    parsed = parse([meta(source=source), developer(FULL_BLOCK)], hint=hint)
    assert parsed.sessions == {"thread-a": "main"}
    assert parsed.cohort_hint == hint
    assert [x.cohort for x in parsed.exposures] == ["main"]
    assert parsed.counts["main_sessions"] == 1


@pytest.mark.parametrize(
    ("depth", "cohort"), [(1, "sub"), (2, "nested"), (5, "nested")]
)
def test_subagent_depth_maps_to_declared_cohort_without_implying_a_fork(
    depth: int, cohort: str
) -> None:
    parsed = parse(
        [
            meta(source=spawn(depth), thread_source="subagent"),
            developer(FULL_BLOCK),
            token(usage_info()),
        ],
        hint="main",
    )
    assert_issues(parsed, {})
    assert parsed.sessions == {"thread-a": cohort}
    assert [x.cohort for x in parsed.exposures] == [cohort]
    assert parsed.counts["forked_sessions"] == 0
    assert parsed.counts["fork_parent_meta_records"] == 0
    assert (
        parsed.counts[
            "subagent_sessions" if cohort == "sub" else "nested_subagent_sessions"
        ]
        == 1
    )
    assert {u.counter_kind for u in parsed.usage} == {"last", "cumulative"}


def test_fork_records_the_parent_meta_without_registering_a_second_session() -> None:
    records = [
        meta("thread-child", forked_from_id="thread-parent"),
        meta("thread-parent", ts=T1),
        developer(FULL_BLOCK, ts=T2),
    ]
    parsed = parse(records, hint="unknown")
    assert_issues(parsed, {})
    assert parsed.sessions == {"thread-child": "main"}
    assert parsed.counts["forked_sessions"] == 1
    assert parsed.counts["fork_parent_meta_records"] == 1
    assert parsed.counts["session_meta_records"] == 1
    assert [x.session_id for x in parsed.exposures] == ["thread-child"]


def test_fork_and_subagent_are_independent_facts() -> None:
    forked_subagent = parse(
        [
            meta(
                "thread-child",
                forked_from_id="thread-parent",
                source=spawn(1, "thread-parent"),
            ),
            meta("thread-parent", ts=T1),
        ]
    )
    plain_fork = parse(
        [
            meta("thread-child", forked_from_id="thread-parent"),
            meta("thread-parent", ts=T1),
        ]
    )
    assert forked_subagent.sessions == {"thread-child": "sub"}
    assert plain_fork.sessions == {"thread-child": "main"}
    assert (
        forked_subagent.counts["forked_sessions"]
        == plain_fork.counts["forked_sessions"]
        == 1
    )


def test_thread_source_declares_cohort_when_source_is_absent() -> None:
    sub = parse([meta(source=None, thread_source="subagent")], hint="main")
    user = parse([meta(source=None, thread_source="user")], hint="sub")
    assert sub.sessions == {"thread-a": "sub"}
    assert user.sessions == {"thread-a": "main"}


def test_missing_declarations_use_the_file_hint_and_are_counted() -> None:
    parsed = parse([meta(source=None)], hint="sub")
    assert parsed.sessions == {"thread-a": "sub"}
    assert parsed.counts["sessions_without_declared_cohort"] == 1
    assert parsed.counts["main_sessions"] == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"source": "mcp"},
        {"source": {"subagent": "review"}},
        {"source": {"other": {}}},
        {"source": spawn(0)},
        {"source": spawn(-1)},
        {"source": spawn(True)},
        {"source": 7},
    ],
)
def test_unrecognized_sources_fail_closed(extra: dict[str, object]) -> None:
    parsed = parse([meta(**extra), developer(FULL_BLOCK)])
    assert not parsed.schema_supported
    assert_issues(parsed, {"unsupported_session_source": 1})
    assert parsed.sessions == {}
    assert parsed.exposures == []


@pytest.mark.parametrize(
    "extra",
    [
        {"source": "cli", "thread_source": "subagent"},
        {"source": spawn(1), "thread_source": "user"},
        {"forked_from_id": "thread-a"},
        {"source": spawn(1, "thread-y"), "parent_thread_id": "thread-x"},
    ],
)
def test_contradictory_lineage_declarations_fail(extra: dict[str, object]) -> None:
    parsed = parse([meta(**extra)])
    assert not parsed.schema_supported
    assert_issues(parsed, {"conflicting_session_lineage": 1})
    assert parsed.sessions == {}


@pytest.mark.parametrize(
    "extra",
    [
        {"thread_source": "robot"},
        {"thread_source": 3},
        {"forked_from_id": 4},
        {"instructions": 5},
    ],
)
def test_invalid_declared_metadata_types_fail(extra: dict[str, object]) -> None:
    parsed = parse([meta(**extra)])
    assert not parsed.schema_supported
    assert_issues(parsed, {"invalid_session_meta": 1})


def test_identical_repeated_meta_is_a_duplicate_but_other_metas_conflict() -> None:
    duplicate = parse([meta(), meta()])
    assert_issues(duplicate, {})
    assert duplicate.counts["duplicate_records"] == 1
    assert duplicate.counts["session_meta_records"] == 1
    stranger = parse([meta(), meta("thread-b", ts=T1)])
    assert_issues(stranger, {"multiple_session_meta": 1})
    assert stranger.sessions == {"thread-a": "main"}
    second_parent = parse(
        [
            meta("thread-child", forked_from_id="thread-parent"),
            meta("thread-parent", ts=T1),
            meta("thread-parent", ts=T2),
        ]
    )
    assert_issues(second_parent, {"multiple_session_meta": 1})
    not_a_fork = parse([meta("thread-child"), meta("thread-parent", ts=T1)])
    assert_issues(not_a_fork, {"multiple_session_meta": 1})


def test_header_failures_mark_the_file_unsupported_and_skip_the_rest() -> None:
    no_id = parse(
        [
            rec("session_meta", {"timestamp": TS, "cli_version": "0.153.4"}),
            developer(FULL_BLOCK),
        ]
    )
    assert not no_id.schema_supported
    assert_issues(no_id, {"invalid_session_meta": 1})
    assert no_id.exposures == [] and no_id.sessions == {}
    assert no_id.counts["skipped_records"] == 1

    naive_envelope = parse(
        [rec("session_meta", {"id": "t"}, ts="2026-03-01T10:00:00"), meta()]
    )
    assert not naive_envelope.schema_supported
    assert_issues(naive_envelope, {"invalid_timestamp": 1})

    late = parse([developer(FULL_BLOCK), meta()])
    assert not late.schema_supported
    assert_issues(late, {"record_before_session_meta": 1})
    assert late.sessions == {} and late.exposures == []
    assert late.counts["skipped_records"] == 2

    empty = parse([])
    assert not empty.schema_supported
    assert_issues(empty, {"missing_session_meta": 1})
    assert empty.coverage["exposure"] == "unavailable"


# -- usage --------------------------------------------------------------------------


def test_null_info_is_valid_and_never_a_zero_observation() -> None:
    parsed = parse([meta(), token(None)])
    assert_issues(parsed, {})
    assert parsed.usage == []
    assert parsed.counts["token_count_records"] == 1
    assert parsed.counts["token_count_without_info"] == 1
    assert parsed.coverage["usage"] == "unavailable"


def test_last_and_cumulative_counters_are_separate_unsummed_observations() -> None:
    total, last = counters(5), counters(1)
    parsed = parse([meta(), token(usage_info(total, last), ts=T1)])
    assert_issues(parsed, {})
    by_kind = {u.counter_kind: u for u in parsed.usage}
    assert set(by_kind) == {"last", "cumulative"}
    assert by_kind["last"].values == last
    assert by_kind["cumulative"].values == total
    for observation in parsed.usage:
        assert observation.source == SOURCE_USAGE
        assert observation.timestamp == DT1
        assert set(observation.values) == set(counters())
    assert parsed.coverage["usage"] == "available"


def test_progressing_totals_keep_every_physical_event() -> None:
    parsed = parse(
        [
            meta(),
            token(usage_info(counters(2), counters(2)), ts=T1),
            token(usage_info(counters(5), counters(3)), ts=T2),
        ]
    )
    last = [u for u in parsed.usage if u.counter_kind == "last"]
    cumulative = [u for u in parsed.usage if u.counter_kind == "cumulative"]
    assert [u.values for u in last] == [counters(2), counters(3)]
    assert [u.values for u in cumulative] == [counters(2), counters(5)]
    assert len({u.identity for u in parsed.usage}) == 4


def test_identical_counter_tuples_at_separate_times_stay_separate() -> None:
    info = usage_info(counters(5), counters(1))
    parsed = parse([meta(), token(info, ts=T1), token(info, ts=T2), token(info, ts=T3)])
    assert_issues(parsed, {})
    assert [(u.counter_kind, u.timestamp) for u in parsed.usage] == [
        ("last", DT1),
        ("cumulative", DT1),
        ("last", DT2),
        ("cumulative", DT2),
        ("last", DT3),
        ("cumulative", DT3),
    ]
    assert len({u.identity for u in parsed.usage}) == 6
    assert parsed.counts["token_count_records"] == 3


def test_same_total_with_different_last_keeps_every_observation() -> None:
    reset_last = {name: 0 for name in counters()} | {"total_tokens": 777}
    parsed = parse(
        [
            meta(),
            token(usage_info(counters(5), counters(1)), ts=T1),
            token(usage_info(counters(5), reset_last), ts=T2),
        ]
    )
    assert [u.counter_kind for u in parsed.usage] == [
        "last",
        "cumulative",
        "last",
        "cumulative",
    ]
    assert parsed.usage[2].values == reset_last
    assert len({u.identity for u in parsed.usage}) == 4


def test_usage_identity_is_scoped_to_the_physical_file() -> None:
    records = [meta(), token(usage_info(), ts=T1)]
    first = parse_file(
        iter(records), inventory=inventory(), file_key="file-1", cohort_hint="main"
    )
    second = parse_file(
        iter(records), inventory=inventory(), file_key="file-2", cohort_hint="main"
    )
    assert {u.identity for u in first.usage}.isdisjoint(
        u.identity for u in second.usage
    )


def test_extra_info_fields_are_tolerated_and_other_event_kinds_are_not_usage() -> None:
    info = usage_info() | {"unrelated": {"nested": 1}}
    parsed = parse([meta(), token(info), rec("event_msg", {"type": "task_started"})])
    assert_issues(parsed, {})
    assert len(parsed.usage) == 2


def _bad_counter_cases() -> list[object]:
    cases: list[object] = []
    for key in ("total_token_usage", "last_token_usage"):
        for label, value in (
            ("bool", True),
            ("negative", -1),
            ("float", 1.5),
            ("string", "7"),
            ("null", None),
        ):
            bad: dict[str, object] = {**counters(), "input_tokens": value}
            info = usage_info()
            info[key] = bad
            cases.append(pytest.param(info, "invalid_counter", id=f"{key}-{label}"))
        missing = counters()
        del missing["cached_input_tokens"]
        info = usage_info()
        info[key] = missing
        cases.append(pytest.param(info, "invalid_counter", id=f"{key}-missing"))
    return cases


@pytest.mark.parametrize(("info", "code"), _bad_counter_cases())
def test_invalid_counters_fail_without_partial_usage(
    info: dict[str, object], code: str
) -> None:
    parsed = parse([meta(), token(info), token(usage_info(), ts=T1)])
    assert_issues(parsed, {code: 1})
    assert [u.timestamp for u in parsed.usage] == [DT1, DT1]


@pytest.mark.parametrize(
    "info",
    [
        [],
        "x",
        {"last_token_usage": counters()},
        {"total_token_usage": counters()},
        {"total_token_usage": counters(), "last_token_usage": []},
        usage_info() | {"model_context_window": -1},
        usage_info() | {"model_context_window": True},
    ],
)
def test_invalid_info_shapes_fail(info: object) -> None:
    parsed = parse([meta(), token(info)])
    assert_issues(parsed, {"invalid_token_info": 1})
    assert parsed.usage == []


def test_token_count_without_info_key_is_malformed_not_null() -> None:
    parsed = parse([meta(), rec("event_msg", {"type": "token_count"})])
    assert_issues(parsed, {"invalid_token_info": 1})


def test_fork_lineage_usage_is_retained_under_its_own_source() -> None:
    records = [
        meta("thread-child", forked_from_id="thread-parent"),
        meta("thread-parent", ts=T1),
        token(usage_info(), ts=T2),
        token(None, ts=T3),
        developer(FULL_BLOCK, ts=T3),
    ]
    parsed = parse(records)
    assert_issues(parsed, {})
    assert {u.source for u in parsed.usage} == {SOURCE_USAGE_FORK}
    assert [(u.counter_kind, u.timestamp) for u in parsed.usage] == [
        ("last", DT2),
        ("cumulative", DT2),
    ]
    assert parsed.counts["fork_lineage_token_count_records"] == 1
    assert parsed.counts["token_count_without_info"] == 1
    assert parsed.coverage["usage"] == "available"
    assert len(parsed.exposures) == 1

    plain = parse([meta(), token(usage_info(), ts=T2)])
    assert {u.source for u in plain.usage} == {SOURCE_USAGE}
    assert plain.counts["fork_lineage_token_count_records"] == 0

    broken = parse(
        [
            meta("thread-child", forked_from_id="thread-parent"),
            token(usage_info(counters(1) | {"input_tokens": -4})),
        ]
    )
    assert_issues(broken, {"invalid_counter": 1})
    assert broken.usage == []


# -- unavailable channels and unknown shapes ---------------------------------------


def test_native_reads_and_invocations_are_unavailable_not_inferred() -> None:
    def call(kind: str, name: str, **fields: object) -> Record:
        return rec(
            "response_item",
            {"type": kind, "name": name, "call_id": f"call-{name}", **fields},
        )

    records = [
        meta(),
        call("function_call", "read", arguments='{"path":"/skills/aurora/SKILL.md"}'),
        call("function_call", "Skill", arguments='{"skill":"aurora"}'),
        call(
            "custom_tool_call",
            "shell",
            input="cat skill://aurora/SKILL.md",
            status="done",
        ),
        rec(
            "response_item",
            {"type": "function_call_output", "call_id": "call-read", "output": "body"},
        ),
        developer(FULL_BLOCK),
    ]
    parsed = parse(records)
    assert_issues(parsed, {})
    assert parsed.attempts == []
    assert parsed.results == []
    assert parsed.invocations == []
    assert parsed.reference_names == set()
    assert parsed.counts["tool_call_envelopes"] == 3
    for channel in ("native_read", "slash_invocation", "native_invocation"):
        assert parsed.coverage[channel] == "unavailable"


@pytest.mark.parametrize("missing", ["name", "call_id"])
def test_tool_envelopes_require_declared_identifiers(missing: str) -> None:
    payload: Record = {"type": "function_call", "name": "n", "call_id": "c"}
    del payload[missing]
    parsed = parse([meta(), rec("response_item", payload)])
    assert_issues(parsed, {"invalid_payload": 1})


def test_recognized_unrelated_records_are_counted_not_failed() -> None:
    records = [
        meta(),
        rec("response_item", {"type": "reasoning", "summary": []}),
        rec("response_item", {"type": "web_search_call"}),
        rec("event_msg", {"type": "exec_command_end"}),
        rec("event_msg", {"type": "agent_message"}),
        rec("event_msg", {"type": "context_compacted"}),
        rec("event_msg", {"type": "thread_rolled_back"}),
        rec("world_state", {"anything": 1}),
        rec("inter_agent_communication_metadata", {"anything": 1}),
        rec("turn_context", {"model": "m"}),
    ]
    records[1]["ordinal"] = 12
    parsed = parse(records)
    assert_issues(parsed, {})
    assert parsed.counts["records"] == 10
    assert parsed.counts["response_items"] == 2
    assert parsed.counts["event_msgs"] == 4
    assert parsed.counts["ignored_records"] == 2
    assert parsed.counts["turn_context_records"] == 1
    assert parsed.counts["context_compacted_events"] == 1
    assert parsed.counts["thread_rolled_back_events"] == 1


@pytest.mark.parametrize(
    ("record", "code"),
    [
        (rec("brand_new_kind", {}), "unknown_record_type"),
        (rec("response_item", {"type": "brand_new_item"}), "unknown_payload_type"),
        (rec("event_msg", {"type": "brand_new_event"}), "unknown_payload_type"),
        (rec("event_msg", {}), "unknown_payload_type"),
        ({"timestamp": TS, "payload": {}}, "missing_record_type"),
        (rec("event_msg", ["not", "an", "object"]), "invalid_payload"),
        ({"timestamp": TS, "type": "event_msg"}, "invalid_payload"),
        (
            rec("event_msg", {"type": "task_started"}, ts="2026-03-01T10:00:00"),
            "invalid_timestamp",
        ),
        (
            rec("event_msg", {"type": "task_started"}, ts=1772359200),
            "invalid_timestamp",
        ),
        (
            {"type": "event_msg", "payload": {"type": "task_started"}},
            "invalid_timestamp",
        ),
        (
            {**rec("event_msg", {"type": "task_started"}), "ordinal": -1},
            "invalid_counter",
        ),
        (
            {**rec("event_msg", {"type": "task_started"}), "ordinal": True},
            "invalid_counter",
        ),
    ],
)
def test_unknown_or_malformed_records_fail_anonymously_and_parsing_continues(
    record: Record, code: str
) -> None:
    parsed = parse([meta(), record, developer(FULL_BLOCK, ts=T1)])
    assert_issues(parsed, {code: 1})
    assert parsed.schema_supported
    assert len(parsed.exposures) == 1


# -- privacy --------------------------------------------------------------------------


def test_no_log_value_reaches_issues_counts_coverage_or_versions() -> None:
    secret = "SECRETVALUE"
    secret_block = FULL_BLOCK.replace("aurora", f"{secret}skill").replace(
        "Draw northern lights", f"{secret}desc"
    )
    records = [
        meta(
            f"{secret}session",
            forked_from_id=f"{secret}parent",
            base_instructions={"text": f"{secret}prefix " + secret_block},
        ),
        meta(f"{secret}parent", ts=T1),
        developer(secret_block, f"{secret}<skills_instructions>"),
        turn(user_instructions=f"{secret}</skills_instructions>"),
        rec(
            "response_item",
            {"type": "function_call", "name": f"{secret}n", "call_id": f"{secret}c"},
        ),
        rec(f"{secret}kind", {}),
        rec("event_msg", {"type": f"{secret}event"}),
        token(usage_info(counters(1) | {"input_tokens": f"{secret}"})),
    ]
    parsed = parse(records)
    surface = repr(
        (dict(parsed.issues), dict(parsed.counts), parsed.coverage, parsed.versions)
    )
    assert secret not in surface
    assert set(parsed.issues) <= ISSUE_CODES
    assert parsed.issues


@pytest.mark.parametrize("version", OBSERVED_VERSIONS)
def test_summary_only_compactions_do_not_invent_disclosure(version: str) -> None:
    parsed = parse(
        [
            meta(version=version),
            rec("compacted", {"message": "Fictional summary."}, ts=T1),
            rec("compacted", {"message": "", "replacement_history": None}, ts=T2),
        ]
    )
    assert_issues(parsed, {})
    assert parsed.exposures == []
    assert parsed.coverage["exposure"] == "unavailable"
    assert parsed.counts["compacted_records_without_replacement_history"] == 2


@pytest.mark.parametrize("message", [None, 7, {}, False])
def test_compaction_summary_field_requires_a_string(message: object) -> None:
    parsed = parse(
        [meta(), rec("compacted", {"message": message, "replacement_history": []})]
    )
    assert_issues(parsed, {"invalid_message": 1})
    assert parsed.exposures == []


def test_utc_normalization_overflow_is_an_anonymous_schema_failure() -> None:
    parsed = parse([meta(), developer(FULL_BLOCK, ts="0001-01-01T00:00:00+14:00")])
    assert_issues(parsed, {"invalid_timestamp": 1})
    assert parsed.exposures == []
