"""Synthetic Claude Code transcripts: identity, listing grammar, events, usage and dedup."""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from inventory_claude import (
    ISSUE_CODES,
    SOURCE_LISTING_DYNAMIC,
    SOURCE_LISTING_INITIAL,
    SOURCE_USAGE,
    parse_file,
)
from inventory_types import (
    Cohort,
    EntryCost,
    Exposure,
    InstalledSkill,
    Inventory,
    ParsedFile,
    ReadResult,
)

Record = dict[str, object]

VERSION = "2.1.301"
TS = "2026-03-01T10:00:00.000Z"
T0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
SENTINEL = "PRIVATE-SENTINEL-8f2c"
ALPHA = "/skills/alpha/SKILL.md"
ROW_A = "- alpha: Alpha helper"
ROW_B = "- beta (b): Beta helper"
FULL = f"{ROW_A}\n{ROW_B}"
NAMES2 = ["alpha", "beta"]
USAGE: dict[str, object] = {"input_tokens": 10, "output_tokens": 2}

EXPECTED_VERSIONS = (
    "2.1.258",
    "2.1.263",
    "2.1.272",
    "2.1.273",
    "2.1.274",
    "2.1.276",
    "2.1.278",
    "2.1.280",
    "2.1.281",
    "2.1.282",
    "2.1.283",
    "2.1.284",
    "2.1.285",
    "2.1.286",
    "2.1.287",
    "2.1.288",
    "2.1.289",
    "2.1.290",
    "2.1.291",
    "2.1.292",
    "2.1.293",
    "2.1.294",
    "2.1.295",
    "2.1.296",
    "2.1.299",
    "2.1.300",
    "2.1.301",
)


class _Sentinel:
    """Marks an omitted field, distinct from an explicit null."""


MISSING = _Sentinel()


def inventory() -> Inventory:
    entries = [
        InstalledSkill("alpha", "d", Path(ALPHA), (), "managed"),
    ]
    return Inventory(
        entries=entries,
        direct_paths={
            ALPHA: "alpha",
            "/alias/alpha/SKILL.md": "alpha",
            "/home/synth/.skills/zed/SKILL.md": "zed",
        },
        ambiguous_paths={"/shared/dup/SKILL.md"},
    )


def parse(records: list[Record], hint: Cohort = "main") -> ParsedFile:
    return parse_file(
        iter(records), inventory=inventory(), file_key="file-1", cohort_hint=hint
    )


def envelope(
    kind: str,
    uuid: str,
    *,
    session: object = "s1",
    sidechain: object = False,
    version: object = VERSION,
    ts: object = TS,
    **extra: object,
) -> Record:
    record: Record = {
        "type": kind,
        "uuid": uuid,
        "parentUuid": None,
        "sessionId": session,
        "isSidechain": sidechain,
        "version": version,
        "timestamp": ts,
    }
    record.update(extra)
    return record


def mutated(record: Record, key: str, value: object) -> Record:
    changed = copy.deepcopy(record)
    if isinstance(value, _Sentinel):
        changed.pop(key, None)
    else:
        changed[key] = value
    return changed


def listing(
    content: str,
    names: list[str],
    count: int | None = None,
    *,
    initial: bool = True,
    uuid: str = "l1",
    **env: object,
) -> Record:
    attachment: Record = {
        "type": "skill_listing",
        "content": content,
        "names": names,
        "skillCount": len(names) if count is None else count,
        "isInitial": initial,
    }
    return envelope("attachment", uuid, attachment=attachment, **env)


def listing_with(**fields: object) -> Record:
    attachment: Record = {
        "type": "skill_listing",
        "content": FULL,
        "names": NAMES2,
        "skillCount": 2,
        "isInitial": True,
    }
    for key, value in fields.items():
        if isinstance(value, _Sentinel):
            attachment.pop(key, None)
        else:
            attachment[key] = value
    return envelope("attachment", "l1", attachment=attachment)


def tool_use(call_id: str, name: str, **arguments: object) -> Record:
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


def assistant(
    message_id: str,
    *blocks: Record,
    uuid: str = "a1",
    usage: object = USAGE,
    **env: object,
) -> Record:
    message: Record = {"id": message_id, "role": "assistant", "content": list(blocks)}
    if not isinstance(usage, _Sentinel):
        message["usage"] = usage
    return envelope("assistant", uuid, message=message, **env)


def results(uuid: str, *blocks: Record, **env: object) -> Record:
    message: Record = {"role": "user", "content": list(blocks)}
    return envelope("user", uuid, message=message, **env)


def result_block(call_id: str, **fields: object) -> Record:
    block: Record = {"type": "tool_result", "tool_use_id": call_id, "content": "ok"}
    block.update(fields)
    return block


def full_file(version: object) -> list[Record]:
    return [
        listing(FULL, NAMES2, version=version),
        assistant(
            "m1",
            tool_use("c1", "Skill", skill="alpha"),
            tool_use("c2", "Read", file_path=ALPHA),
            version=version,
        ),
        results("u1", result_block("c2"), version=version),
    ]


def issues(parsed: ParsedFile) -> dict[str, int]:
    return dict(parsed.issues)


# -- client identity -----------------------------------------------------------------


@pytest.mark.parametrize("version", EXPECTED_VERSIONS)
def test_each_enumerated_version_is_admitted_with_every_measured_shape(
    version: str,
) -> None:
    parsed = parse(full_file(version))
    assert not parsed.issues
    assert parsed.schema_supported
    assert parsed.versions == {f"claude-code-{version}"}
    assert [exposure.status for exposure in parsed.exposures] == ["complete"]
    assert [call.skill_name for call in parsed.invocations] == ["alpha"]
    assert [read.skill_name for read in parsed.attempts] == ["alpha"]
    assert [result.success for result in parsed.results] == [True]
    assert [item.identity for item in parsed.usage] == [("s1", "m1")]
    assert parsed.coverage["usage"] == "available"


@pytest.mark.parametrize(
    "version",
    [
        "2.1.257",
        "2.1.259",
        "2.1.264",
        "2.1.275",
        "2.1.279",
        "2.1.297",
        "2.1.298",
        "2.1.302",
        "2.2.0",
        "3.0.0",
        "2.1",
        "2.1.301-beta",
        "v2.1.301",
        " 2.1.301",
        "2.1.301 ",
        "claude-export-import",
        "",
        2,
        2.1,
        None,
        True,
        ["2.1.301"],
    ],
)
def test_version_outside_the_enumeration_is_unsupported_and_uninterpreted(
    version: object,
) -> None:
    parsed = parse(full_file(version))
    assert issues(parsed) == {"unsupported_client_version": 3}
    assert not parsed.schema_supported
    assert not parsed.versions
    assert not (
        parsed.exposures
        or parsed.invocations
        or parsed.attempts
        or parsed.results
        or parsed.usage
    )
    assert parsed.sessions == {}


def test_measured_record_without_a_version_fails_but_the_file_identity_stands() -> None:
    unversioned = mutated(
        assistant("m2", tool_use("c3", "Skill", skill="beta"), uuid="a2"),
        "version",
        MISSING,
    )
    parsed = parse([*full_file(VERSION), unversioned])
    assert issues(parsed) == {"missing_client_version": 1}
    assert parsed.schema_supported
    assert parsed.versions == {"claude-code-2.1.301"}
    assert [call.skill_name for call in parsed.invocations] == ["alpha"]


def test_system_and_progress_may_omit_a_version_but_cannot_forge_one() -> None:
    quiet = parse(
        [*full_file(VERSION), {"type": "system"}, {"type": "progress", "data": {}}]
    )
    assert not quiet.issues
    assert quiet.counts["ignored_records"] == 2
    forged = parse([*full_file(VERSION), {"type": "system", "version": "9.9.9"}])
    assert issues(forged) == {"unsupported_client_version": 1}
    assert not forged.schema_supported


@pytest.mark.parametrize(
    "records",
    [[], [{"type": "summary", "summary": "x"}, {"type": "system"}]],
)
def test_file_that_never_validates_a_client_identity_is_schema_unsupported(
    records: list[Record],
) -> None:
    parsed = parse(records)
    assert issues(parsed) == {"unvalidated_client_identity": 1}
    assert not parsed.schema_supported


def test_resumed_file_may_mix_enumerated_versions() -> None:
    parsed = parse(
        [
            listing(FULL, NAMES2, version="2.1.299"),
            assistant("m1", uuid="a1", version="2.1.301"),
        ]
    )
    assert not parsed.issues
    assert parsed.versions == {"claude-code-2.1.299", "claude-code-2.1.301"}


# -- skill_listing grammar and lower bounds ------------------------------------------------


def test_complete_initial_listing_measures_persisted_rows_and_identity() -> None:
    parsed = parse(
        [
            listing(
                FULL,
                NAMES2,
                uuid="listing-1",
                session="sess-1",
                ts="2026-03-01T12:00:00.000+02:00",
            )
        ]
    )
    assert not parsed.issues
    (exposure,) = parsed.exposures
    assert exposure == Exposure(
        timestamp=T0,
        session_id="sess-1",
        cohort="main",
        source=SOURCE_LISTING_INITIAL,
        status="complete",
        block_chars=len(FULL),
        wrapper_chars=0,
        entry_chars=len(FULL),
        entries=(
            EntryCost("alpha", len(ROW_A) + 1),
            EntryCost("beta", len(ROW_B)),
        ),
        declared_count=2,
        listed_names=2,
        record_id="listing-1",
        fingerprint=exposure.fingerprint,
    )
    assert exposure.fingerprint is not None and len(exposure.fingerprint) == 64
    assert parsed.sessions == {"sess-1": "main"}
    assert parsed.counts["skill_listings_initial"] == 1
    assert parsed.counts["listing_rows_described"] == 2
    assert parsed.counts["listing_rows_aliased"] == 1
    assert parsed.counts["listing_rows_name_only"] == 0
    assert parsed.coverage["exposure"] == "complete"


@pytest.mark.parametrize(
    "rows",
    [
        [ROW_A, "- gamma"],
        ["- alpha", "- gamma"],
        [ROW_A, "- gamma (g)"],
    ],
)
def test_name_only_rows_make_the_listing_a_lower_bound(rows: list[str]) -> None:
    content = "\n".join(rows)
    parsed = parse([listing(content, ["alpha", "gamma"])])
    assert not parsed.issues
    (exposure,) = parsed.exposures
    assert exposure.status == "lower_bound"
    assert exposure.block_chars == len(content)
    assert exposure.declared_count == exposure.listed_names == 2
    assert [entry.name for entry in exposure.entries] == ["alpha", "gamma"]
    assert parsed.counts["listing_name_only_lower_bounds"] == 1
    assert parsed.counts["listing_rows_name_only"] >= 1
    assert parsed.coverage["exposure"] == "partial"


def test_alias_is_part_of_the_row_but_never_of_the_skill_name() -> None:
    content = "- alpha (a1): Alpha (with) parens\n- beta (b2)"
    parsed = parse([listing(content, NAMES2)])
    (exposure,) = parsed.exposures
    assert [entry.name for entry in exposure.entries] == ["alpha", "beta"]
    assert exposure.entry_chars == len(content)
    assert parsed.counts["listing_rows_aliased"] == 2
    assert parsed.counts["listing_rows_described"] == 1


def test_producer_ellipsis_marks_truncation_but_ascii_dots_do_not() -> None:
    truncated = parse([listing(f"- alpha: {'x' * 10}\u2026\n{ROW_B}", NAMES2)])
    assert truncated.exposures[0].status == "lower_bound"
    assert truncated.counts["listing_rows_truncated"] == 1
    assert truncated.counts["listing_truncation_lower_bounds"] == 1
    plain = parse([listing(f"- alpha: Wait for it...\n{ROW_B}", NAMES2)])
    assert plain.exposures[0].status == "complete"
    assert plain.counts["listing_rows_truncated"] == 0


def test_descriptions_may_span_lines_and_bullets_without_forging_rows() -> None:
    first = "- alpha: first line\n- not-a-skill: still alpha\nsecond\n"
    content = f"{first}- beta: next"
    parsed = parse([listing(content, NAMES2)])
    assert not parsed.issues
    (exposure,) = parsed.exposures
    assert exposure.status == "complete"
    assert exposure.entries == (
        EntryCost("alpha", len(first)),
        EntryCost("beta", len("- beta: next")),
    )
    assert exposure.entry_chars == len(content)
    assert exposure.wrapper_chars == 0


@pytest.mark.parametrize(
    ("names", "count", "content"),
    [
        (NAMES2, 5, FULL),
        (NAMES2, 1, FULL),
        (["alpha", "beta", "gamma"], 3, FULL),
        (["alpha", "delta"], 2, FULL),
        (["beta", "alpha"], 2, FULL),
        (NAMES2, 2, ""),
    ],
)
def test_count_name_and_row_disagreement_is_a_lower_bound_not_a_failure(
    names: list[str], count: int, content: str
) -> None:
    parsed = parse([listing(content, names, count)])
    assert not parsed.issues
    (exposure,) = parsed.exposures
    assert exposure.status == "lower_bound"
    assert exposure.declared_count == count
    assert exposure.listed_names == len(names)
    assert exposure.block_chars == len(content)
    assert exposure.entry_chars == len(content)
    assert parsed.counts["listing_count_lower_bounds"] == 1


def test_names_that_disagree_with_content_keep_the_rows_found_in_content() -> None:
    parsed = parse([listing(FULL, ["alpha", "delta"], 2)])
    (exposure,) = parsed.exposures
    assert [entry.name for entry in exposure.entries] == ["alpha", "beta"]


def test_non_initial_listing_is_a_dynamic_lower_bound_never_initial_exposure() -> None:
    parsed = parse([listing(FULL, NAMES2, initial=False)])
    assert not parsed.issues
    (exposure,) = parsed.exposures
    assert exposure.source == SOURCE_LISTING_DYNAMIC
    assert exposure.status == "lower_bound"
    assert exposure.block_chars == len(FULL)
    assert parsed.counts["skill_listings_dynamic"] == 1
    assert parsed.counts["skill_listings_initial"] == 0
    assert parsed.counts["listing_dynamic_lower_bounds"] == 1
    assert parsed.coverage["exposure"] == "partial"


def test_empty_listing_is_a_measured_empty_block_not_unavailable() -> None:
    parsed = parse([listing("", [], 0)])
    assert not parsed.issues
    (exposure,) = parsed.exposures
    assert exposure.status == "complete"
    assert exposure.block_chars == 0
    assert exposure.entry_chars == 0
    assert exposure.entries == ()


@pytest.mark.parametrize(
    "content",
    [
        "Available skills:\n- alpha: a",
        "\n- alpha: a",
        " - alpha: a",
        "* alpha: a",
        "- ",
        "- alpha\n",
        "alpha",
    ],
)
def test_content_outside_the_row_grammar_fails_anonymously_without_an_exposure(
    content: str,
) -> None:
    parsed = parse([listing(content, ["alpha"])])
    assert issues(parsed) == {"invalid_skill_listing": 1}
    assert parsed.exposures == []
    assert parsed.schema_supported


@pytest.mark.parametrize(
    "fields",
    [
        {"content": None},
        {"content": 5},
        {"content": ["- alpha"]},
        {"content": MISSING},
        {"names": None},
        {"names": "alpha"},
        {"names": MISSING},
        {"names": ["alpha", 5]},
        {"names": ["alpha", ""]},
        {"names": ["alpha", "n" * 513]},
        {"names": ["n"] * 4097},
        {"skillCount": True},
        {"skillCount": -1},
        {"skillCount": 1.5},
        {"skillCount": "2"},
        {"skillCount": None},
        {"skillCount": MISSING},
        {"isInitial": "true"},
        {"isInitial": 1},
        {"isInitial": None},
        {"isInitial": MISSING},
    ],
)
def test_wrongly_typed_listing_fields_fail_without_an_exposure(
    fields: dict[str, object],
) -> None:
    parsed = parse([listing_with(**fields)])
    assert issues(parsed) == {"invalid_skill_listing": 1}
    assert parsed.exposures == []


def test_plugin_qualified_names_are_preserved_in_rows_and_native_input() -> None:
    rows = "- acme:review (rv): Reviews code\n- acme:deploy\n- alpha: Alpha helper"
    names = ["acme:review", "acme:deploy", "alpha"]
    parsed = parse(
        [
            listing(rows, names),
            assistant(
                "m1",
                tool_use("c1", "Skill", skill="acme:review"),
                tool_use("c2", "Skill", skill="/acme:deploy"),
                tool_use("c3", "Skill", skill="review"),
            ),
        ]
    )
    assert not parsed.issues
    (exposure,) = parsed.exposures
    assert [entry.name for entry in exposure.entries] == names
    assert exposure.entry_chars == len(rows)
    assert [call.skill_name for call in parsed.invocations] == [
        "acme:review",
        "acme:deploy",
        "review",
    ]


def test_listing_bounds_at_the_consumer_caps_are_accepted_as_shapes() -> None:
    wide = parse([listing_with(names=["x" * 512], skillCount=1)])
    assert not wide.issues
    assert wide.exposures[0].status == "lower_bound"
    many = parse([listing_with(names=[f"n{i}" for i in range(4096)])])
    assert not many.issues
    assert many.exposures[0].listed_names == 4096
    assert many.exposures[0].status == "lower_bound"


@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("uuid", MISSING, "invalid_record_uuid"),
        ("uuid", "", "invalid_record_uuid"),
        ("uuid", 7, "invalid_record_uuid"),
    ],
)
def test_listing_needs_a_declared_logical_record_id_not_an_invented_one(
    key: str, value: object, code: str
) -> None:
    parsed = parse([mutated(listing(FULL, NAMES2), key, value)])
    assert issues(parsed) == {code: 1}
    assert parsed.exposures == []


# -- envelope fields on every measured record kind ----------------------------------------


def _listing_record() -> Record:
    return listing(FULL, NAMES2)


def _assistant_record() -> Record:
    return assistant("m1")


def _user_record() -> Record:
    return results("u1", result_block("c1"))


BUILDERS = [_listing_record, _assistant_record, _user_record]


@pytest.mark.parametrize("build", BUILDERS)
@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("sessionId", MISSING, "invalid_session_id"),
        ("sessionId", "", "invalid_session_id"),
        ("sessionId", 3, "invalid_session_id"),
        ("isSidechain", MISSING, "invalid_sidechain"),
        ("isSidechain", "false", "invalid_sidechain"),
        ("isSidechain", 0, "invalid_sidechain"),
        ("isSidechain", None, "invalid_sidechain"),
        ("timestamp", MISSING, "invalid_timestamp"),
        ("timestamp", "not a time", "invalid_timestamp"),
        ("timestamp", "2026-03-01T10:00:00", "invalid_timestamp"),
        ("timestamp", 1_772_359_200, "invalid_timestamp"),
        ("timestamp", "0001-01-01T00:00:00+05:00", "invalid_timestamp"),
        ("agentId", "", "invalid_agent_id"),
        ("agentId", 5, "invalid_agent_id"),
        ("forkedFrom", None, "invalid_fork_origin"),
        ("forkedFrom", [], "invalid_fork_origin"),
        ("forkedFrom", {}, "invalid_fork_origin"),
        ("forkedFrom", {"sessionId": "o"}, "invalid_fork_origin"),
        ("forkedFrom", {"messageUuid": "m"}, "invalid_fork_origin"),
        ("forkedFrom", {"sessionId": "", "messageUuid": "m"}, "invalid_fork_origin"),
        ("forkedFrom", {"sessionId": "o", "messageUuid": 3}, "invalid_fork_origin"),
    ],
)
def test_declared_envelope_fields_are_required_and_typed(
    build: Callable[[], Record], key: str, value: object, code: str
) -> None:
    parsed = parse([mutated(build(), key, value)])
    assert issues(parsed) == {code: 1}
    assert not (parsed.exposures or parsed.usage or parsed.results)
    assert parsed.sessions == {}


# -- listing duplicates and forks ------------------------------------------------------------


def test_identical_listing_copies_count_once_and_conflicting_copies_fail() -> None:
    original = listing(FULL, NAMES2)
    copied = parse([original, copy.deepcopy(original)])
    assert not copied.issues
    assert len(copied.exposures) == 1
    assert copied.counts["duplicate_records"] == 1
    assert copied.counts["skill_listings_initial"] == 2
    assert copied.counts["records"] == 2

    conflicting = parse([original, listing(ROW_A, ["alpha"])])
    assert issues(conflicting) == {"conflicting_duplicate_record": 1}
    assert [exposure.block_chars for exposure in conflicting.exposures] == [len(FULL)]


def test_same_record_id_in_distinct_declared_sessions_is_not_a_duplicate() -> None:
    parsed = parse(
        [listing(FULL, NAMES2, session="s1"), listing(FULL, NAMES2, session="s2")]
    )
    assert not parsed.issues
    assert sorted(exposure.session_id for exposure in parsed.exposures) == ["s1", "s2"]


def test_listing_copy_across_physical_cohorts_becomes_unknown_not_conflict() -> None:
    parsed = parse(
        [
            listing(FULL, NAMES2),
            listing(FULL, NAMES2, sidechain=True, agentId="agent-1"),
        ]
    )
    assert not parsed.issues
    assert [exposure.cohort for exposure in parsed.exposures] == ["unknown"]


def test_fork_copy_resolves_to_its_declared_origin_identity() -> None:
    original = parse([listing(FULL, NAMES2, uuid="u-orig", session="origin")])
    fork = listing(
        FULL,
        NAMES2,
        uuid="u-copy",
        session="fork-session",
        forkedFrom={"sessionId": "origin", "messageUuid": "u-orig"},
    )
    forked = parse([fork])
    assert not forked.issues
    assert forked.exposures == original.exposures
    assert forked.sessions == {"fork-session": "main", "origin": "main"}
    assert forked.counts["forked_records"] == 1
    both = parse([listing(FULL, NAMES2, uuid="u-orig", session="origin"), fork])
    assert len(both.exposures) == 1
    assert both.counts["duplicate_records"] == 1


def test_fork_copies_of_calls_usage_and_results_match_their_originals() -> None:
    blocks = (
        tool_use("c1", "Skill", skill="alpha"),
        tool_use("c2", "Read", file_path=ALPHA),
    )
    original = parse(
        [
            assistant("m1", *blocks, uuid="a1", session="origin"),
            results("u1", result_block("c2"), session="origin"),
        ]
    )
    forked = parse(
        [
            assistant(
                "m1",
                *blocks,
                uuid="a1",
                session="fork-session",
                forkedFrom={"sessionId": "origin", "messageUuid": "a1"},
            ),
            results(
                "u1",
                result_block("c2"),
                session="fork-session",
                forkedFrom={"sessionId": "origin", "messageUuid": "u1"},
            ),
        ]
    )
    assert not forked.issues
    assert forked.invocations == original.invocations
    assert forked.attempts == original.attempts
    assert forked.results == original.results
    assert forked.usage == original.usage
    assert forked.usage[0].identity == ("origin", "m1")


# -- native invocations and tool envelopes ---------------------------------------------------


def test_skill_tool_use_is_a_native_invocation_attempt_with_a_normalized_name() -> None:
    parsed = parse(
        [
            assistant(
                "m1",
                tool_use("c1", "Skill", skill="  /plugin:alpha  ", args=SENTINEL),
                tool_use("c2", "Skill", skill="beta"),
            )
        ]
    )
    assert not parsed.issues
    assert [
        (call.call_id, call.skill_name, call.channel, call.cohort, call.session_id)
        for call in parsed.invocations
    ] == [
        ("c1", "plugin:alpha", "native", "main", "s1"),
        ("c2", "beta", "native", "main", "s1"),
    ]
    assert parsed.invocations[0].timestamp == T0
    assert parsed.attempts == [] and parsed.results == []
    assert SENTINEL not in repr(parsed)
    assert parsed.counts["skill_tool_calls"] == 2


def test_streamed_copy_of_one_tool_use_is_deduplicated_by_declared_tool_id() -> None:
    late = assistant(
        "m1",
        tool_use("c1", "Skill", skill="alpha", args="same"),
        uuid="a1",
        ts="2026-03-01T10:00:05.000Z",
    )
    early = assistant(
        "m1",
        tool_use("c1", "Skill", skill="alpha", args="same"),
        uuid="a2",
        ts="2026-03-01T10:00:01.000Z",
    )
    for order in ([late, early], [early, late]):
        parsed = parse(order)
        assert not parsed.issues
        assert len(parsed.invocations) == 1
        assert parsed.invocations[0].timestamp == datetime(
            2026, 3, 1, 10, 0, 1, tzinfo=UTC
        )
        assert parsed.counts["duplicate_calls"] == 1


def test_call_id_reused_with_other_arguments_conflicts_without_export() -> None:
    first = assistant("m1", tool_use("c1", "Skill", skill="alpha", args=SENTINEL))
    variants = [
        tool_use("c1", "Skill", skill="alpha", args="other"),
        tool_use("c1", "Skill", skill="alpha", args=""),
        tool_use("c1", "Skill", skill="alpha"),
    ]
    for block in variants:
        parsed = parse([first, assistant("m2", block, uuid="a2")])
        assert issues(parsed) == {"conflicting_duplicate_call": 1}
        assert [item.call_id for item in parsed.invocations] == ["c1"]
        assert SENTINEL not in repr(parsed)
    absent = assistant("m1", tool_use("c1", "Skill", skill="alpha"))
    empty = assistant("m2", tool_use("c1", "Skill", skill="alpha", args=""), uuid="a2")
    assert issues(parse([absent, empty])) == {"conflicting_duplicate_call": 1}


def test_invocation_fingerprint_separates_arguments_without_retaining_them() -> None:
    def fingerprint(**arguments: object) -> str:
        block = tool_use("c1", "Skill", skill="alpha", **arguments)
        (item,) = parse([assistant("m1", block)]).invocations
        assert SENTINEL not in item.fingerprint
        return item.fingerprint

    assert fingerprint(args=SENTINEL) == fingerprint(args=SENTINEL)
    assert len({fingerprint(), fingerprint(args=""), fingerprint(args=SENTINEL)}) == 3


def test_identical_call_in_parent_and_sidechain_is_unknown_cohort() -> None:
    parent = assistant("m1", tool_use("c1", "Skill", skill="alpha"), uuid="a1")
    side = assistant(
        "m1",
        tool_use("c1", "Skill", skill="alpha"),
        uuid="a2",
        sidechain=True,
        agentId="agent-1",
    )
    parsed = parse([parent, side])
    assert not parsed.issues
    assert [call.cohort for call in parsed.invocations] == ["unknown"]
    assert parsed.counts["duplicate_calls"] == 1
    assert len(parsed.usage) == 1


@pytest.mark.parametrize(
    "second",
    [
        tool_use("c1", "Skill", skill="beta"),
        tool_use("c1", "Read", file_path=ALPHA),
    ],
)
def test_same_tool_id_with_a_different_counted_payload_is_a_conflict(
    second: Record,
) -> None:
    parsed = parse(
        [
            assistant("m1", tool_use("c1", "Skill", skill="alpha"), uuid="a1"),
            assistant("m2", second, uuid="a2"),
        ]
    )
    assert issues(parsed) == {"conflicting_duplicate_call": 1}
    assert [call.skill_name for call in parsed.invocations] == ["alpha"]
    assert parsed.attempts == []


@pytest.mark.parametrize(
    "block",
    [
        {"type": "tool_use", "id": "c1", "name": "Skill"},
        {"type": "tool_use", "id": "c1", "name": "Skill", "input": "alpha"},
        tool_use("c1", "Skill"),
        tool_use("c1", "Skill", skill=None),
        tool_use("c1", "Skill", skill=3),
        tool_use("c1", "Skill", skill=["alpha"]),
        tool_use("c1", "Skill", skill=""),
        tool_use("c1", "Skill", skill="   "),
        tool_use("c1", "Skill", skill="/"),
        tool_use("c1", "Skill", skill=" / "),
        tool_use("c1", "Skill", skill="alpha", args=None),
        tool_use("c1", "Skill", skill="alpha", args=5),
        tool_use("c1", "Skill", skill="alpha", args=["x"]),
        tool_use("c1", "Skill", skill="alpha", args={}),
        tool_use("c1", "Skill", skill="alpha", args=True),
    ],
)
def test_unusable_skill_input_fails_anonymously(block: Record) -> None:
    parsed = parse([assistant("m1", block)])
    assert issues(parsed) == {"invalid_skill_input": 1}
    assert parsed.invocations == []


@pytest.mark.parametrize("name", ["skill", "SKILL", "sKiLl", "skill__plugin__alpha"])
def test_skill_loading_envelopes_other_than_the_verified_tool_fail(name: str) -> None:
    parsed = parse([assistant("m1", tool_use("c1", name, skill="alpha"))])
    assert issues(parsed) == {"unsupported_skill_tool": 1}
    assert parsed.invocations == []


def test_other_tools_are_counted_without_events_even_when_they_mention_skills() -> None:
    parsed = parse(
        [
            assistant(
                "m1",
                tool_use("c1", "Bash", command=f"cat {ALPHA}"),
                tool_use("c2", "Grep", pattern="Skill"),
                tool_use("c3", "Skills", skill="alpha"),
                tool_use("c4", "mcp__srv__skill", skill="alpha"),
                {"type": "text", "text": "Skill(alpha) skill://alpha"},
            )
        ]
    )
    assert not parsed.issues
    assert parsed.counts["other_tool_calls"] == 4
    assert not (parsed.invocations or parsed.attempts)


@pytest.mark.parametrize(
    "block",
    [
        {"type": "tool_use", "name": "Skill", "input": {"skill": "alpha"}},
        {"type": "tool_use", "id": "", "name": "Skill", "input": {"skill": "alpha"}},
        {"type": "tool_use", "id": "c1", "input": {}},
        {"type": "tool_use", "id": "c1", "name": 3, "input": {}},
    ],
)
def test_tool_use_needs_a_declared_id_and_name(block: Record) -> None:
    parsed = parse([assistant("m1", block)])
    assert issues(parsed) == {"invalid_tool_use": 1}


# -- direct reads and result correlation ---------------------------------------------------


def test_direct_reads_resolve_only_approved_aliases_and_never_open_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/home/synth")
    parsed = parse(
        [
            assistant(
                "m1",
                tool_use("r1", "Read", file_path=ALPHA),
                tool_use("r2", "Read", file_path="/alias/alpha/SKILL.md", offset=10),
                tool_use("r3", "Read", file_path="~/.skills/zed/SKILL.md", limit=50),
                tool_use("r4", "Read", file_path=ALPHA, offset=None, limit=None),
                tool_use("r5", "Read", file_path="/shared/dup/SKILL.md"),
                tool_use("r6", "Read", file_path="/etc/hosts"),
                tool_use("r7", "Read", file_path="relative/SKILL.md"),
                tool_use("r8", "Read", file_path=f"{ALPHA}:12-40"),
            )
        ]
    )
    assert not parsed.issues
    assert [
        (read.call_id, read.skill_name, read.partial) for read in parsed.attempts
    ] == [
        ("r1", "alpha", False),
        ("r2", "alpha", True),
        ("r3", "zed", True),
        ("r4", "alpha", False),
        ("r5", None, False),
    ]
    assert {(read.channel, read.body, read.cohort) for read in parsed.attempts} == {
        ("direct", True, "main")
    }
    assert parsed.counts["non_skill_reads"] == 3


@pytest.mark.parametrize(
    "block",
    [
        {"type": "tool_use", "id": "r1", "name": "Read"},
        {"type": "tool_use", "id": "r1", "name": "Read", "input": []},
        {"type": "tool_use", "id": "r1", "name": "Read", "input": "x"},
        tool_use("r1", "Read"),
        tool_use("r1", "Read", file_path=None),
        tool_use("r1", "Read", file_path=7),
        tool_use("r1", "Read", file_path=""),
        tool_use("r1", "Read", file_path=["a"]),
        tool_use("r1", "Read", path=ALPHA),
    ],
)
def test_read_without_a_string_path_is_malformed_not_a_non_skill_read(
    block: Record,
) -> None:
    parsed = parse([assistant("m1", block)])
    assert issues(parsed) == {"invalid_read_path": 1}
    assert parsed.attempts == []
    assert parsed.counts["non_skill_reads"] == 0
    assert parsed.usage == []


def test_valid_outside_paths_are_known_non_skill_reads_unlike_malformed_ones() -> None:
    outside = assistant("m1", tool_use("r1", "Read", file_path="/etc/hosts"), uuid="a1")
    malformed = assistant("m2", tool_use("r2", "Read", file_path=None), uuid="a2")
    parsed = parse([outside, malformed])
    assert issues(parsed) == {"invalid_read_path": 1}
    assert parsed.counts["non_skill_reads"] == 1


@pytest.mark.parametrize("key", ["offset", "limit"])
@pytest.mark.parametrize("value", [True, False, -1, 1.5, "10", [], {}])
def test_non_null_read_ranges_must_be_non_negative_ints(
    key: str, value: object
) -> None:
    block = tool_use("r1", "Read", file_path=ALPHA, **{key: value})
    parsed = parse([assistant("m1", block)])
    assert issues(parsed) == {"invalid_read_range": 1}
    assert parsed.attempts == []
    assert parsed.counts["non_skill_reads"] == 0


@pytest.mark.parametrize(
    ("arguments", "partial"),
    [
        ({}, False),
        ({"offset": None, "limit": None}, False),
        ({"offset": 0}, True),
        ({"limit": 7}, True),
        ({"offset": 3, "limit": 7}, True),
    ],
)
def test_partial_means_a_non_null_validated_range(
    arguments: dict[str, object], partial: bool
) -> None:
    block = tool_use("r1", "Read", file_path=ALPHA, **arguments)
    (read,) = parse([assistant("m1", block)]).attempts
    assert read.partial is partial


def test_call_id_reused_with_a_different_range_is_a_conflict() -> None:
    parsed = parse(
        [
            assistant("m1", tool_use("r1", "Read", file_path=ALPHA), uuid="a1"),
            assistant(
                "m2",
                tool_use("r1", "Read", file_path=ALPHA, offset=5),
                uuid="a2",
            ),
        ]
    )
    assert issues(parsed) == {"conflicting_duplicate_call": 1}
    assert [read.partial for read in parsed.attempts] == [False]


def test_results_resolve_attempts_with_explicit_error_and_absence_states() -> None:
    parsed = parse(
        [
            assistant(
                "m1",
                tool_use("implicit", "Read", file_path=ALPHA),
                tool_use("explicit", "Read", file_path=ALPHA),
                tool_use("failed", "Read", file_path=ALPHA),
                tool_use("pending", "Read", file_path=ALPHA),
            ),
            results(
                "u1",
                result_block("implicit"),
                result_block("explicit", is_error=False),
                result_block("failed", is_error=True),
                ts="2026-03-01T17:30:00.000+05:30",
            ),
        ]
    )
    done = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    assert not parsed.issues
    assert parsed.results == [
        ReadResult("s1", "implicit", True, done),
        ReadResult("s1", "explicit", True, done),
        ReadResult("s1", "failed", False, done),
    ]
    assert len(parsed.attempts) == 4
    assert parsed.counts["tool_results_without_error_flag"] == 1


def test_result_correlation_does_not_depend_on_record_order() -> None:
    parsed = parse(
        [
            results("u1", result_block("c1")),
            assistant("m1", tool_use("c1", "Read", file_path=ALPHA)),
        ]
    )
    assert [(read.call_id, read.success) for read in parsed.results] == [("c1", True)]


def test_duplicate_results_keep_the_earliest_instant_and_conflicts_fail() -> None:
    call = assistant("m1", tool_use("c1", "Read", file_path=ALPHA))
    late = results("u1", result_block("c1"), ts="2026-03-01T10:09:00.000Z")
    early = results("u2", result_block("c1"), ts="2026-03-01T10:01:00.000Z")
    parsed = parse([call, late, early])
    assert not parsed.issues
    assert parsed.results == [
        ReadResult("s1", "c1", True, datetime(2026, 3, 1, 10, 1, tzinfo=UTC))
    ]
    assert parsed.counts["duplicate_results"] == 1

    contradicting = results("u3", result_block("c1", is_error=True))
    conflict = parse([call, late, contradicting])
    assert issues(conflict) == {"conflicting_duplicate_result": 1}
    assert conflict.results == []


def test_results_for_uncounted_tools_are_other_results_not_failures() -> None:
    parsed = parse(
        [
            assistant(
                "m1",
                tool_use("c1", "Skill", skill="alpha"),
                tool_use("c2", "Bash", command="ls"),
                tool_use("c3", "Read", file_path="/etc/hosts"),
            ),
            results(
                "u1",
                result_block("c1"),
                result_block("c2"),
                result_block("c3"),
                result_block("ghost"),
            ),
        ]
    )
    assert not parsed.issues
    assert parsed.results == []
    assert parsed.counts["other_results"] == 4


@pytest.mark.parametrize(
    "block",
    [
        {"type": "tool_result", "content": "x"},
        {"type": "tool_result", "tool_use_id": "", "content": "x"},
        {"type": "tool_result", "tool_use_id": 4},
        result_block("c1", is_error=None),
        result_block("c1", is_error="true"),
        result_block("c1", is_error=1),
    ],
)
def test_malformed_tool_results_fail_anonymously(block: Record) -> None:
    parsed = parse([results("u1", block)])
    assert issues(parsed) == {"invalid_tool_result": 1}
    assert parsed.results == []


# -- streaming and usage ---------------------------------------------------------------------


def test_streamed_chunks_are_all_collected_and_usage_is_not_dropped_by_id() -> None:
    chunks = [
        assistant(
            "msg-1",
            {"type": "thinking", "thinking": SENTINEL, "signature": "s"},
            uuid="a1",
            usage={"input_tokens": 100, "output_tokens": 1},
            ts="2026-03-01T10:00:01.000Z",
        ),
        assistant(
            "msg-1",
            tool_use("c1", "Skill", skill="alpha"),
            uuid="a2",
            usage={"input_tokens": 100, "output_tokens": 7},
            ts="2026-03-01T10:00:02.000Z",
        ),
        assistant(
            "msg-1",
            tool_use("c2", "Read", file_path=ALPHA),
            uuid="a3",
            usage={
                "input_tokens": 100,
                "output_tokens": 42,
                "cache_read_input_tokens": 5,
            },
            ts="2026-03-01T10:00:03.000Z",
        ),
    ]
    parsed = parse(chunks)
    assert not parsed.issues
    assert [call.call_id for call in parsed.invocations] == ["c1"]
    assert [read.call_id for read in parsed.attempts] == ["c2"]
    assert [
        (item.identity, item.source, item.counter_kind, item.values["output_tokens"])
        for item in parsed.usage
    ] == [
        (("s1", "msg-1"), SOURCE_USAGE, "per_message", 1),
        (("s1", "msg-1"), SOURCE_USAGE, "per_message", 7),
        (("s1", "msg-1"), SOURCE_USAGE, "per_message", 42),
    ]
    assert parsed.usage[2].values["cache_read_input_tokens"] == 5
    assert "cache_read_input_tokens" not in parsed.usage[0].values
    assert SENTINEL not in repr(parsed)

    replay = parse([*chunks, copy.deepcopy(chunks[1])])
    assert len(replay.usage) == 3
    assert replay.counts["duplicate_usage_chunks"] == 1
    assert replay.counts["duplicate_calls"] == 1
    assert replay.counts["records"] == 4


def test_usage_exports_only_persisted_counters_with_actual_cache_fields() -> None:
    full: dict[str, object] = {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_input_tokens": 3,
        "cache_creation_input_tokens": 4,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 5,
            "ephemeral_1h_input_tokens": 6,
        },
        "service_tier": "standard",
        "server_tool_use": {"web_search_requests": 9},
        "unrelated": SENTINEL,
    }
    (observation,) = parse([assistant("m1", usage=full)]).usage
    assert observation.values == {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_input_tokens": 3,
        "cache_creation_input_tokens": 4,
        "cache_creation.ephemeral_5m_input_tokens": 5,
        "cache_creation.ephemeral_1h_input_tokens": 6,
    }
    assert SENTINEL not in repr(observation)
    minimal = {"input_tokens": 1, "output_tokens": 2}
    (bare,) = parse([assistant("m1", usage=minimal)]).usage
    assert bare.values == minimal


def test_null_optional_counters_are_absent_not_zero() -> None:
    usage: dict[str, object] = {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_input_tokens": None,
        "cache_creation_input_tokens": None,
        "cache_creation": {
            "ephemeral_5m_input_tokens": None,
            "ephemeral_1h_input_tokens": 7,
        },
    }
    parsed = parse([assistant("m1", usage=usage)])
    assert not parsed.issues
    assert parsed.usage[0].values == {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_creation.ephemeral_1h_input_tokens": 7,
    }
    assert parsed.counts["usage_null_counters"] == 3
    absent = parse([assistant("m1", usage=MISSING)])
    assert absent.usage == []
    assert absent.counts["assistant_without_usage"] == 1
    assert absent.coverage["usage"] == "unavailable"


@pytest.mark.parametrize(
    "usage",
    [
        None,
        [],
        "x",
        {},
        {"input_tokens": 1},
        {"output_tokens": 1},
        {"input_tokens": True, "output_tokens": 1},
        {"input_tokens": -1, "output_tokens": 1},
        {"input_tokens": 1.5, "output_tokens": 1},
        {"input_tokens": "1", "output_tokens": 1},
        {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": "3"},
        {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": -2},
        {"input_tokens": 1, "output_tokens": 1, "cache_creation": []},
        {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_creation": {"ephemeral_5m_input_tokens": False},
        },
        {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_creation": {"ephemeral_1h_input_tokens": 1.0},
        },
    ],
)
def test_malformed_usage_fails_the_whole_record_anonymously(usage: object) -> None:
    block = tool_use("c1", "Skill", skill="alpha")
    parsed = parse([assistant("m1", block, usage=usage)])
    assert issues(parsed) == {"invalid_usage": 1}
    assert parsed.usage == []
    assert parsed.invocations == []


@pytest.mark.parametrize("message_id", [MISSING, "", 5, None])
def test_assistant_needs_a_declared_provider_message_id(message_id: object) -> None:
    record = assistant("m1", tool_use("c1", "Skill", skill="alpha"))
    message = record["message"]
    assert isinstance(message, dict)
    if isinstance(message_id, _Sentinel):
        message.pop("id")
    else:
        message["id"] = message_id
    parsed = parse([record])
    assert issues(parsed) == {"invalid_message_id": 1}
    assert parsed.invocations == [] and parsed.usage == []


def test_a_record_is_committed_atomically() -> None:
    parsed = parse(
        [assistant("m1", tool_use("c1", "Skill", skill="alpha"), {"type": "hologram"})]
    )
    assert issues(parsed) == {"unknown_content_block": 1}
    assert not (parsed.invocations or parsed.usage)
    assert parsed.sessions == {}


@pytest.mark.parametrize(
    "block",
    ["text", "thinking", "redacted_thinking", "server_tool_use", "mcp_tool_use"],
)
def test_recognized_unrelated_assistant_blocks_are_ignored(block: str) -> None:
    parsed = parse([assistant("m1", {"type": block, "text": SENTINEL})])
    assert not parsed.issues
    assert SENTINEL not in repr(parsed)


@pytest.mark.parametrize("block", ["text", "image", "document"])
def test_recognized_unrelated_user_blocks_are_ignored(block: str) -> None:
    parsed = parse([results("u1", {"type": block, "text": SENTINEL})])
    assert not parsed.issues
    assert SENTINEL not in repr(parsed)


def test_plain_text_user_prompts_are_ignored_but_declare_their_session() -> None:
    record = envelope("user", "u1", message={"role": "user", "content": SENTINEL})
    parsed = parse([record])
    assert not parsed.issues
    assert parsed.counts["ignored_records"] == 1
    assert parsed.sessions == {"s1": "main"}
    assert SENTINEL not in repr(parsed)


@pytest.mark.parametrize(
    ("kind", "message", "code"),
    [
        ("assistant", "x", "invalid_message"),
        ("assistant", MISSING, "invalid_message"),
        ("assistant", None, "invalid_message"),
        (
            "assistant",
            {"role": "user", "id": "m", "content": []},
            "invalid_message_role",
        ),
        ("assistant", {"role": "assistant", "id": "m"}, "invalid_message_content"),
        (
            "assistant",
            {"role": "assistant", "id": "m", "content": "x"},
            "invalid_message_content",
        ),
        (
            "assistant",
            {"role": "assistant", "id": "m", "content": ["text"]},
            "invalid_content_block",
        ),
        (
            "assistant",
            {"role": "assistant", "id": "m", "content": [{"text": "no type"}]},
            "invalid_content_block",
        ),
        (
            "assistant",
            {"role": "assistant", "id": "m", "content": [{"type": 3}]},
            "invalid_content_block",
        ),
        (
            "assistant",
            {"role": "assistant", "id": "m", "content": [{"type": "hologram"}]},
            "unknown_content_block",
        ),
        ("user", None, "invalid_message"),
        ("user", {"role": "assistant", "content": []}, "invalid_message_role"),
        ("user", {"role": "user"}, "invalid_message_content"),
        ("user", {"role": "user", "content": 5}, "invalid_message_content"),
        ("user", {"role": "user", "content": {}}, "invalid_message_content"),
        ("user", {"role": "user", "content": [None]}, "invalid_content_block"),
        (
            "user",
            {"role": "user", "content": [{"type": None}]},
            "invalid_content_block",
        ),
        (
            "user",
            {"role": "user", "content": [{"type": "hologram"}]},
            "unknown_content_block",
        ),
    ],
)
def test_message_shapes_fail_with_fixed_codes(
    kind: str, message: object, code: str
) -> None:
    record = envelope(kind, "r1")
    if not isinstance(message, _Sentinel):
        record["message"] = message
    parsed = parse([record])
    assert issues(parsed) == {code: 1}


# -- cohorts and sessions --------------------------------------------------------------------


def test_cohort_comes_from_the_declared_sidechain_flag_not_file_placement() -> None:
    records = [
        assistant(
            "m1",
            tool_use("c1", "Skill", skill="alpha"),
            uuid="a1",
            sidechain=True,
            agentId="agent-1",
        ),
        assistant("m2", tool_use("c2", "Read", file_path=ALPHA), uuid="a2"),
    ]
    for hint in ("main", "sub", "nested", "unknown"):
        parsed = parse(records, hint)
        assert not parsed.issues
        assert parsed.cohort_hint == hint
        assert [call.cohort for call in parsed.invocations] == ["sub"]
        assert [read.cohort for read in parsed.attempts] == ["main"]
        assert parsed.sessions == {"s1": "unknown"}


def test_one_session_id_reused_by_parent_and_sidechain_files_is_legitimate() -> None:
    parent = assistant("m1", tool_use("c1", "Skill", skill="alpha"), uuid="a1")
    side = assistant(
        "m2",
        tool_use("c2", "Skill", skill="beta"),
        uuid="a2",
        sidechain=True,
        agentId="agent-1",
    )
    assert parse([parent]).sessions == {"s1": "main"}
    assert parse([side]).sessions == {"s1": "sub"}
    assert not parse([parent]).issues and not parse([side]).issues


def test_sessions_reflect_only_declared_identities() -> None:
    parsed = parse(
        [
            assistant("m1", session="s-a"),
            assistant("m2", session="s-b", sidechain=True, uuid="a2"),
            mutated(assistant("m3", uuid="a3"), "sessionId", MISSING),
        ]
    )
    assert issues(parsed) == {"invalid_session_id": 1}
    assert parsed.sessions == {"s-a": "main", "s-b": "sub"}


# -- top-level records and attachments -----------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "summary",
        "file-history-snapshot",
        "file-history-delta",
        "queue-operation",
        "custom-title",
        "ai-title",
        "agent-name",
        "agent-color",
        "tag",
        "pr-link",
        "last-prompt",
        "session-info",
        "atis-latch",
        "mode",
        "permission-mode",
        "cost-state",
        "bridge-session",
        "frame-link",
        "artifact-comment-monitor",
        "artifact-autoreact-ledger",
        "isolation-latch",
        "api-request-shape",
        "api-request-blob",
        "api-request",
        "continued-in",
        "content-replacement",
        "fork-context-ref",
        "relocated",
        "memory-mode",
        "history-suppression",
        "worktree-state",
    ],
)
def test_recognized_unrelated_records_are_counted_not_interpreted(
    kind: str,
) -> None:
    parsed = parse(
        [*full_file(VERSION), {"type": kind, "payload": SENTINEL, "version": 123}]
    )
    assert not parsed.issues
    assert parsed.counts["ignored_records"] == 1
    assert SENTINEL not in repr(parsed)


@pytest.mark.parametrize("kind", ["hologram", SENTINEL, "User", "assistant ", "skill"])
def test_unknown_record_types_fail_without_echoing_the_type(kind: str) -> None:
    parsed = parse([*full_file(VERSION), {"type": kind, "version": VERSION}])
    assert issues(parsed) == {"unknown_record_type": 1}
    assert SENTINEL not in repr((parsed.issues, parsed.counts, parsed.coverage))


@pytest.mark.parametrize("kind", [MISSING, None, 5, "", ["user"]])
def test_missing_or_wrongly_typed_discriminator_fails(kind: object) -> None:
    record: Record = {"version": VERSION}
    if not isinstance(kind, _Sentinel):
        record["type"] = kind
    assert issues(parse([*full_file(VERSION), record])) == {"missing_record_type": 1}


def test_skill_related_attachments_are_state_not_invocations_or_exposure() -> None:
    invoked: Record = {
        "type": "invoked_skills",
        "skills": [{"name": SENTINEL, "path": "/p", "content": SENTINEL}],
    }
    parsed = parse(
        [
            envelope("attachment", "x1", attachment=invoked),
            envelope(
                "attachment",
                "x2",
                attachment={"type": "skill_mention", "skillName": SENTINEL},
            ),
            envelope(
                "attachment",
                "x3",
                attachment={"type": "dynamic_skill", "skillNames": [SENTINEL]},
            ),
            envelope(
                "attachment", "x4", attachment={"type": "hook_success", "content": "x"}
            ),
            envelope(
                "attachment", "x5", attachment={"type": "todo_reminder", "content": []}
            ),
        ]
    )
    assert not parsed.issues
    assert not (parsed.invocations or parsed.attempts or parsed.exposures)
    assert parsed.counts["invoked_skills_snapshots"] == 1
    assert parsed.counts["skill_mention_notices"] == 1
    assert parsed.counts["dynamic_skill_notices"] == 1
    assert parsed.counts["other_attachments"] == 2
    assert parsed.coverage["exposure"] == "unavailable"
    assert parsed.coverage["native_invocation"] == "partial"
    assert SENTINEL not in repr(parsed)


def test_unmeasured_dynamic_skill_notice_prevents_complete_exposure_coverage() -> None:
    notice = envelope(
        "attachment", "x1", attachment={"type": "dynamic_skill", "skillNames": ["z"]}
    )
    assert parse([listing(FULL, NAMES2)]).coverage["exposure"] == "complete"
    assert parse([listing(FULL, NAMES2), notice]).coverage["exposure"] == "partial"


def test_body_mentions_never_become_skill_tool_invocations() -> None:
    call = assistant("m1", tool_use("c1", "Skill", skill="alpha"))
    mention = envelope(
        "attachment", "x1", attachment={"type": "skill_mention", "skillName": "alpha"}
    )
    state = envelope(
        "attachment",
        "x2",
        attachment={"type": "invoked_skills", "skills": [{"name": "alpha"}]},
    )
    notice = envelope(
        "attachment", "x3", attachment={"type": "dynamic_skill", "skillNames": ["z"]}
    )
    assert parse([call]).coverage["native_invocation"] == "available"
    for extra in (mention, state):
        parsed = parse([call, extra])
        assert [item.call_id for item in parsed.invocations] == ["c1"]
        assert parsed.coverage["native_invocation"] == "partial"
    disclosed = parse([call, notice])
    assert [item.call_id for item in disclosed.invocations] == ["c1"]
    assert disclosed.coverage["native_invocation"] == "available"
    assert parse([notice]).invocations == []


@pytest.mark.parametrize("kind", ["skill_autoload", "Skills_Loaded", "preloaded_SKILL"])
def test_unknown_skill_loading_attachments_fail_but_unrelated_ones_do_not(
    kind: str,
) -> None:
    parsed = parse([envelope("attachment", "x1", attachment={"type": kind})])
    assert issues(parsed) == {"unsupported_skill_attachment": 1}
    unrelated = parse([envelope("attachment", "x2", attachment={"type": "new_notice"})])
    assert not unrelated.issues
    assert unrelated.counts["other_attachments"] == 1


@pytest.mark.parametrize(
    "attachment",
    [
        MISSING,
        None,
        "skill_listing",
        {},
        {"type": None},
        {"type": ""},
        {"type": "invoked_skills"},
        {"type": "invoked_skills", "skills": "x"},
        {"type": "invoked_skills", "skills": [3]},
    ],
)
def test_malformed_attachment_envelopes_fail(attachment: object) -> None:
    record = envelope("attachment", "x1")
    if not isinstance(attachment, _Sentinel):
        record["attachment"] = attachment
    assert issues(parse([record])) == {"invalid_attachment": 1}


# -- coverage, privacy and determinism -------------------------------------------------------


def test_coverage_labels_are_fixed_and_reflect_measured_channels() -> None:
    bare = parse([assistant("m1", usage=MISSING)])
    assert bare.coverage == {
        "exposure": "unavailable",
        "native_read": "available",
        "slash_invocation": "unavailable",
        "native_invocation": "available",
        "usage": "unavailable",
    }
    full = parse([listing(FULL, NAMES2), assistant("m1")])
    assert full.coverage["exposure"] == "complete"
    assert full.coverage["usage"] == "available"
    lower = parse([listing("- alpha", ["alpha"]), assistant("m1")])
    assert lower.coverage["exposure"] == "partial"


def test_hostile_values_never_reach_issues_counters_coverage_or_versions() -> None:
    hostile: list[Record] = [
        {"type": SENTINEL},
        {"type": "user", "version": SENTINEL},
        envelope("assistant", "a0", message={"id": SENTINEL, "role": SENTINEL}),
        assistant("m1", {"type": SENTINEL}),
        assistant("m2", tool_use(SENTINEL, SENTINEL, skill=SENTINEL)),
        assistant("m3", tool_use("c", "Skill", skill=3, args=SENTINEL)),
        listing(SENTINEL, [SENTINEL]),
        envelope("attachment", "a1", attachment={"type": f"{SENTINEL}_skill"}),
        results("u1", {"type": SENTINEL}),
        results(
            "u2", {"type": "tool_result", "tool_use_id": SENTINEL, "is_error": SENTINEL}
        ),
        assistant("m4", usage={"input_tokens": SENTINEL, "output_tokens": 1}),
        assistant("m5", session=SENTINEL, forkedFrom={"sessionId": 1}),
    ]
    parsed = parse(hostile)
    assert parsed.issues
    assert set(parsed.issues) <= ISSUE_CODES
    public = repr(
        (
            dict(parsed.issues),
            dict(parsed.counts),
            parsed.coverage,
            sorted(parsed.versions),
        )
    )
    assert SENTINEL not in public
    assert parsed.counts["records"] == len(hostile)


def test_parsing_is_deterministic_and_leaves_inputs_untouched() -> None:
    records = [
        *full_file(VERSION),
        assistant("m2", tool_use("c3", "Skill", skill="beta"), uuid="a2"),
        results("u2", result_block("c3")),
    ]
    snapshot = copy.deepcopy(records)
    shared = inventory()
    before = copy.deepcopy(shared)
    first = parse_file(
        iter(records), inventory=shared, file_key="file-1", cohort_hint="main"
    )
    second = parse_file(
        iter(records), inventory=shared, file_key="file-1", cohort_hint="main"
    )
    assert first == second
    assert records == snapshot
    assert shared == before
    assert first.file_key == "file-1"
