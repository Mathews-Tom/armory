"""Synthetic OMP schema-v3 fixtures: counts, spans, errors, custom shapes, results and dedup."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pytest
from inventory_omp import ISSUE_CODES, parse_file
from inventory_types import Cohort, InstalledSkill, Inventory, ParsedFile

TS = "2026-03-01T10:00:00.000Z"
TS_RESULT = "2026-03-01T11:30:00.000Z"
EPOCH = 1_772_359_200_000
EPOCH_DT = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
RESULT_DT = datetime(2026, 3, 1, 11, 30, 0, tzinfo=UTC)

Record = dict[str, object]


def inventory() -> Inventory:
    entries = [
        InstalledSkill("alpha", "d", Path("/skills/alpha/SKILL.md"), (), "managed"),
        InstalledSkill("team/beta", "d", Path("/skills/beta/SKILL.md"), (), "managed"),
    ]
    return Inventory(
        entries=entries,
        direct_paths={
            "/skills/alpha/SKILL.md": "alpha",
            "/alias/alpha/SKILL.md": "alpha",
            "/home/synth/.skills/zed/SKILL.md": "zed",
        },
        ambiguous_paths={"/shared/dup/SKILL.md"},
    )


def parse(records: list[Record], hint: Cohort = "main") -> ParsedFile:
    return parse_file(
        iter(records), inventory=inventory(), file_key="file-1", cohort_hint=hint
    )


def header(session_id: str = "s1", **extra: object) -> Record:
    record: Record = {
        "type": "session",
        "version": 3,
        "id": session_id,
        "timestamp": TS,
    }
    record.update(extra)
    return record


def init(prompt: object, entry_id: str = "i1", **extra: object) -> Record:
    record: Record = {
        "type": "session_init",
        "id": entry_id,
        "parentId": None,
        "timestamp": TS,
        "systemPrompt": prompt,
    }
    record.update(extra)
    return record


def call(call_id: str, path: object, name: str = "read") -> Record:
    return {
        "type": "toolCall",
        "id": call_id,
        "name": name,
        "arguments": {"path": path},
    }


def assistant(
    entry_id: str, *blocks: Record, epoch: object = EPOCH, **message: object
) -> Record:
    body: Record = {"role": "assistant", "timestamp": epoch, "content": list(blocks)}
    body.update(message)
    return {
        "type": "message",
        "id": entry_id,
        "parentId": None,
        "timestamp": TS,
        "message": body,
    }


def result(
    entry_id: str,
    call_id: str,
    *,
    is_error: object = False,
    tool: str = "read",
    envelope: str = TS_RESULT,
    epoch: object = EPOCH + 1000,
) -> Record:
    body: Record = {
        "role": "toolResult",
        "toolCallId": call_id,
        "toolName": tool,
        "isError": is_error,
        "content": [{"type": "text", "text": "x"}],
        "timestamp": epoch,
    }
    return {
        "type": "message",
        "id": entry_id,
        "parentId": None,
        "timestamp": envelope,
        "message": body,
    }


def custom_top(entry_id: str, **fields: object) -> Record:
    record: Record = {
        "type": "custom_message",
        "id": entry_id,
        "parentId": None,
        "timestamp": TS_RESULT,
        "customType": "skill-prompt",
        "content": "x",
        "display": True,
        "details": {"name": "alpha"},
        "attribution": "user",
    }
    record.update(fields)
    return record


def custom_role(entry_id: str, epoch: object = EPOCH, **fields: object) -> Record:
    body: Record = {
        "role": "custom",
        "customType": "skill-prompt",
        "attribution": "user",
        "details": {"name": "alpha"},
        "content": "x",
        "timestamp": epoch,
    }
    body.update(fields)
    return {
        "type": "message",
        "id": entry_id,
        "parentId": None,
        "timestamp": TS,
        "message": body,
    }


def plain(entry_id: str, role: str, **body: object) -> Record:
    message: Record = {"role": role, "content": "x"}
    message.update(body)
    return {
        "type": "message",
        "id": entry_id,
        "parentId": None,
        "timestamp": TS,
        "message": message,
    }


def only_issue(parsed: ParsedFile) -> str:
    assert len(parsed.issues) == 1
    ((code, count),) = parsed.issues.items()
    assert count == 1
    return code


# --------------------------------------------------------------------------- header / title


def test_title_before_header_is_valid_and_its_content_is_not_interpreted() -> None:
    parsed = parse(
        [{"type": "title", "title": "private words", "source": "auto"}, header()]
    )
    assert not parsed.issues
    assert parsed.sessions == {"s1": "main"}
    assert parsed.versions == {"omp-session-3"}
    assert parsed.counts["title_records"] == 1


@pytest.mark.parametrize(
    "records",
    [
        [header(), {"type": "title", "title": "t"}],
        [{"type": "title"}, {"type": "title"}, header()],
    ],
)
def test_misplaced_or_repeated_title_fails(records: list[Record]) -> None:
    assert only_issue(parse(records)) == "misplaced_title"


@pytest.mark.parametrize("version", [1, 2, 4, 10])
def test_unknown_session_version_fails_and_nothing_after_it_is_interpreted(
    version: int,
) -> None:
    parsed = parse(
        [
            header(version=version),
            init(["<skills>\n- alpha: x\n</skills>"]),
            assistant("m1", call("c1", "skill://alpha")),
        ]
    )
    assert only_issue(parsed) == "unsupported_schema_version"
    assert parsed.schema_supported is False
    assert parsed.counts["skipped_records"] == 2
    assert not parsed.exposures and not parsed.attempts and not parsed.sessions


@pytest.mark.parametrize("version", [3.0, True, "3", None])
def test_wrongly_typed_version_is_a_header_error_not_a_supported_header(
    version: object,
) -> None:
    parsed = parse(
        [header(version=version), assistant("m1", call("c1", "skill://alpha"))]
    )
    assert only_issue(parsed) == "invalid_session_header"
    assert not parsed.attempts and not parsed.sessions


@pytest.mark.parametrize(
    "bad",
    [
        {"id": ""},
        {"id": 7},
        {"timestamp": "2026-03-01T10:00:00"},
        {"timestamp": 1772359200000},
        {"title": 5},
        {"parentSession": ["x"]},
    ],
)
def test_malformed_header_fields_fail_anonymously(bad: Record) -> None:
    parsed = parse([header(**bad)])
    assert only_issue(parsed) == "invalid_session_header"
    assert not parsed.sessions


def test_missing_header_and_empty_file_fail_without_fabricating_exposure() -> None:
    empty = parse([])
    assert only_issue(empty) == "missing_session_header"
    assert not empty.exposures
    assert only_issue(parse([{"type": "title"}])) == "missing_session_header"


def test_record_before_header_fails_but_header_still_establishes_session() -> None:
    parsed = parse([init("p"), header()])
    assert parsed.issues == {"record_before_header": 1}
    assert parsed.sessions == {"s1": "main"}


def test_identical_repeated_header_is_a_duplicate_but_a_different_one_fails() -> None:
    same = parse([header(), header()])
    assert not same.issues and same.counts["duplicate_records"] == 1
    assert only_issue(parse([header(), header("s2")])) == "multiple_session_headers"


# --------------------------------------------------------------------------- exposure spans


def test_string_prompt_counts_block_wrapper_entries_and_prompt_exactly() -> None:
    block = "<skills>\n- alpha: Alpha text\n- beta: Beta\n</skills>"
    prompt = f"intro line\n{block}\ntail"
    parsed = parse([header(), init(prompt)])
    (exposure,) = parsed.exposures
    first, second = "- alpha: Alpha text\n", "- beta: Beta\n"
    assert exposure.status == "complete"
    assert exposure.block_chars == len(block)
    assert exposure.entry_chars == len(first) + len(second)
    assert exposure.wrapper_chars == len("<skills>\n") + len("</skills>")
    assert [(e.name, e.chars) for e in exposure.entries] == [
        ("alpha", len(first)),
        ("beta", len(second)),
    ]
    assert exposure.listed_names == 2 and exposure.declared_count is None
    assert exposure.prompt_chars == len(prompt)
    assert exposure.virtual_block_chars == len(block)
    assert exposure.separator_chars == 0 and exposure.block_separator_chars == 0
    assert exposure.timestamp == EPOCH_DT
    assert exposure.session_id == "s1" and exposure.cohort == "main"
    assert parsed.coverage["exposure"] == "complete"


def test_list_prompt_excludes_inserted_separators_and_reports_them_separately() -> None:
    segments = [
        "intro",
        "<skills>\n- alpha: Alpha",
        "text\n- beta: Beta\n</skills>",
        "tail",
    ]
    parsed = parse([header(), init(segments)])
    (exposure,) = parsed.exposures
    virtual = "\n".join(segments)
    virtual_block = virtual[virtual.index("<skills>") : virtual.index("</skills>") + 9]
    alpha = "- alpha: Alphatext\n"  # the inserted join newline is not persisted
    beta = "- beta: Beta\n"
    assert exposure.prompt_chars == sum(len(s) for s in segments)
    assert exposure.separator_chars == 3
    assert exposure.virtual_block_chars == len(virtual_block)
    assert exposure.block_separator_chars == 1
    assert exposure.block_chars == len(virtual_block) - 1
    assert [e.chars for e in exposure.entries] == [len(alpha), len(beta)]
    assert exposure.entry_chars == len(alpha) + len(beta)
    assert exposure.wrapper_chars == exposure.block_chars - exposure.entry_chars
    assert exposure.wrapper_chars == len("<skills>\n") + len("</skills>")


def test_separator_before_the_open_tag_is_outside_the_block() -> None:
    parsed = parse([header(), init(["intro", "<skills>\n- a: x\n</skills>"])])
    (exposure,) = parsed.exposures
    assert exposure.separator_chars == 1 and exposure.block_separator_chars == 0
    assert (
        exposure.block_chars
        == exposure.virtual_block_chars
        == len("<skills>\n- a: x\n</skills>")
    )


def test_separator_before_the_closing_tag_is_not_charged_to_the_last_entry() -> None:
    parsed = parse([header(), init(["<skills>\n- a: x", "</skills>"])])
    (exposure,) = parsed.exposures
    assert exposure.block_separator_chars == 1
    assert exposure.block_chars == len("<skills>\n- a: x</skills>")
    assert [e.chars for e in exposure.entries] == [len("- a: x")]
    assert exposure.wrapper_chars == len("<skills>\n") + len("</skills>")


def test_names_with_namespaces_colons_and_empty_descriptions_and_intro_text() -> None:
    prompt = "<skills>\nPick one.\n- team/beta: Beta\n- a:b: C: D\n- solo:\n</skills>"
    (exposure,) = parse([header(), init(prompt)]).exposures
    assert [e.name for e in exposure.entries] == ["team/beta", "a:b", "solo"]
    assert exposure.wrapper_chars == len("<skills>\nPick one.\n") + len("</skills>")
    assert exposure.listed_names == 3


def test_continuation_lines_belong_to_the_preceding_entry() -> None:
    prompt = "<skills>\n- a: first\nsecond line\n- b: x\n</skills>"
    (exposure,) = parse([header(), init(prompt)]).exposures
    assert [e.chars for e in exposure.entries] == [
        len("- a: first\nsecond line\n"),
        len("- b: x\n"),
    ]


def test_empty_block_is_available_with_zero_entries_not_unavailable() -> None:
    (exposure,) = parse([header(), init("<skills>\n</skills>")]).exposures
    assert exposure.status == "complete"
    assert (
        exposure.entries == ()
        and exposure.entry_chars == 0
        and exposure.listed_names == 0
    )
    assert exposure.block_chars == exposure.wrapper_chars == len("<skills>\n</skills>")


@pytest.mark.parametrize(
    "prompt",
    [
        "no block at all",
        "Use the <skills> block, then </skills> later",
        "</skills>\nclosing tag alone is not a block",
        "  <skills>\n- a: x\n  </skills>",
        "",
        [],
        ["only", "prose"],
    ],
)
def test_absent_block_is_unavailable_and_never_zero(prompt: object) -> None:
    parsed = parse([header(), init(prompt)])
    assert not parsed.issues
    (exposure,) = parsed.exposures
    assert exposure.status == "unavailable"
    assert exposure.block_chars is None and exposure.wrapper_chars is None
    assert exposure.entry_chars is None and exposure.listed_names is None
    assert exposure.entries == ()
    assert parsed.coverage["exposure"] == "unavailable"


def test_unavailable_exposure_still_records_persisted_prompt_length() -> None:
    (exposure,) = parse([header(), init(["abc", "de"])]).exposures
    assert exposure.prompt_chars == 5 and exposure.separator_chars == 1


def test_missing_system_prompt_field_is_unavailable_without_prompt_length() -> None:
    record = init("x")
    del record["systemPrompt"]
    parsed = parse([header(), record])
    assert not parsed.issues
    (exposure,) = parsed.exposures
    assert exposure.status == "unavailable" and exposure.prompt_chars is None


def test_missing_init_is_unavailable_without_inventing_a_disclosure_record() -> None:
    parsed = parse([header(), assistant("m1", call("c1", "skill://alpha"))])
    assert parsed.exposures == []
    assert len(parsed.attempts) == 1
    assert parsed.coverage["exposure"] == "unavailable"


def test_failed_session_init_is_an_issue_not_a_second_missing_exposure() -> None:
    parsed = parse([header(), init(7)])
    assert only_issue(parsed) == "invalid_system_prompt"
    assert parsed.exposures == []


@pytest.mark.parametrize("prompt", [7, None, {"a": 1}, ["ok", 3], [["nested"]], True])
def test_wrongly_typed_system_prompt_fails(prompt: object) -> None:
    assert only_issue(parse([header(), init(prompt)])) == "invalid_system_prompt"


def test_two_actual_blocks_or_an_unterminated_block_fail() -> None:
    two = parse(
        [
            header(),
            init("<skills>\n- a: x\n</skills>\nmid\n<skills>\n- b: y\n</skills>"),
        ]
    )
    assert only_issue(two) == "multiple_skills_blocks" and two.exposures == []
    open_only = parse([header(), init("<skills>\n- a: x\n")])
    assert (
        only_issue(open_only) == "unterminated_skills_block"
        and open_only.exposures == []
    )


def test_multiple_snapshots_each_become_an_observation_and_mixed_coverage_is_partial() -> (
    None
):
    later = "2026-03-02T10:00:00.000Z"
    second = init("no block", "i2")
    second["timestamp"] = later
    parsed = parse([header(), init("<skills>\n- a: x\n</skills>"), second])
    assert [e.status for e in parsed.exposures] == ["complete", "unavailable"]
    assert parsed.exposures[1].timestamp == datetime(2026, 3, 2, 10, tzinfo=UTC)
    assert parsed.coverage["exposure"] == "partial"


def test_init_timestamp_must_be_utc_aware_and_id_is_required() -> None:
    bad = init("x")
    bad["timestamp"] = "2026-03-01T10:00:00"
    assert only_issue(parse([header(), bad])) == "invalid_timestamp"
    missing = init("x")
    del missing["id"]
    assert only_issue(parse([header(), missing])) == "invalid_record_id"


# --------------------------------------------------------------------------- runtime / autoload


def test_runtime_is_optional_and_only_the_observed_version_is_accepted() -> None:
    absent = parse([header(), init("x")])
    assert not absent.issues and absent.versions == {"omp-session-3"}
    known = parse([header(), init("x", runtime={"version": "18.11.0", "pid": 5})])
    assert not known.issues and known.versions == {
        "omp-session-3",
        "omp-runtime-18.11.0",
    }
    assert len(known.exposures) == 1
    patch = parse([header(), init("x", runtime={"version": "18.11.1", "pid": 5})])
    assert not patch.issues and patch.versions == {
        "omp-session-3",
        "omp-runtime-18.11.1",
    }
    assert "omp-runtime-18.11.0" not in patch.versions
    assert len(patch.exposures) == 1


@pytest.mark.parametrize("version", ["18.11.2", "18.10.0", "19.0.0", "18.11.0-beta"])
def test_unknown_runtime_version_fails_closed(version: str) -> None:
    parsed = parse([header(), init("x", runtime={"version": version})])
    assert only_issue(parsed) == "unsupported_runtime_version"
    assert parsed.schema_supported is False
    assert parsed.versions == {"omp-session-3"} and parsed.exposures == []


@pytest.mark.parametrize(
    "runtime", ["18.11.0", 18, [], {}, {"version": 18}, {"version": ""}, None]
)
def test_malformed_runtime_is_an_issue(runtime: object) -> None:
    assert (
        only_issue(parse([header(), init("x", runtime=runtime)])) == "invalid_runtime"
    )


def test_autoload_skills_are_dependency_names_never_reads_or_invocations() -> None:
    parsed = parse([header(), init("x", autoloadSkills=["alpha", "team/beta"])])
    assert parsed.reference_names == {"alpha", "team/beta"}
    assert not parsed.attempts and not parsed.invocations and not parsed.results


@pytest.mark.parametrize("value", ["alpha", [1], [""], {"a": 1}])
def test_malformed_autoload_skills_fail(value: object) -> None:
    assert (
        only_issue(parse([header(), init("x", autoloadSkills=value)]))
        == "invalid_autoload_skills"
    )


# --------------------------------------------------------------------------- URI reads


@pytest.mark.parametrize(
    ("path", "name", "body", "partial"),
    [
        ("skill://alpha", "alpha", True, False),
        ("skill://alpha/SKILL.md", "alpha", True, False),
        ("skill://alpha/./SKILL.md", "alpha", True, False),
        ("skill://alpha/SKILL.md:10-20", "alpha", True, True),
        ("skill://alpha/SKILL.md:raw", "alpha", True, False),
        ("skill://alpha:raw:5-9", "alpha", True, True),
        ("skill://alpha/SKILL.md:-40", "alpha", True, True),
        ("skill://alpha/SKILL.md:1-5,9-12", "alpha", True, True),
        ("skill://alpha/references/guide.md", "alpha", False, False),
        ("skill://alpha/references/guide.md:-40", "alpha", False, True),
        ("skill://alpha/references/guide.md:raw", "alpha", False, False),
        ("skill://alpha/../beta/SKILL.md", "alpha", False, False),
        ("SKILL://alpha", "alpha", True, False),
        ("skill://alpha?x=1#frag", "alpha", True, False),
        ("skill://team/beta", "team/beta", True, False),
        ("skill://team/beta/references/x.md:3", "team/beta", False, True),
        ("skill://missing/SKILL.md", "missing", True, False),
        ("skill://missing/other", "missing", False, False),
        ("skill://", None, False, False),
        ("skill://:10-20", None, False, False),
    ],
)
def test_uri_roots_resources_and_selectors_are_normalized_separately(
    path: str, name: str | None, body: bool, partial: bool
) -> None:
    parsed = parse([header(), assistant("m1", call("c1", path))])
    assert not parsed.issues
    (attempt,) = parsed.attempts
    assert (attempt.skill_name, attempt.body, attempt.partial) == (name, body, partial)
    assert (
        attempt.channel == "uri"
        and attempt.session_id == "s1"
        and attempt.call_id == "c1"
    )
    assert attempt.timestamp == EPOCH_DT and attempt.cohort == "main"
    assert attempt.fingerprint and path not in attempt.fingerprint


def test_textual_mentions_and_other_tools_are_never_read_attempts() -> None:
    parsed = parse(
        [
            header(),
            assistant(
                "m1",
                {"type": "text", "text": "please read skill://alpha"},
                {"type": "thinking", "thinking": "skill://alpha"},
                {
                    "type": "toolCall",
                    "id": "c1",
                    "name": "bash",
                    "arguments": {"command": "cat skill://alpha"},
                },
                call("c2", "skill://alpha", name="grep"),
                call("c3", "/not/a/skill.md"),
            ),
            plain("u1", "user", timestamp=EPOCH, content="skill://alpha"),
        ]
    )
    assert not parsed.issues and not parsed.attempts
    assert (
        parsed.counts["other_tool_calls"] == 2 and parsed.counts["non_skill_reads"] == 1
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"path": 5},
        {"path": ""},
        {},
        {"path": None},
        {"path": ["skill://a"]},
        "skill://a",
        None,
    ],
)
def test_malformed_read_path_is_an_issue_and_never_a_silent_skip(
    arguments: object,
) -> None:
    block: Record = {
        "type": "toolCall",
        "id": "c1",
        "name": "read",
        "arguments": arguments,
    }
    parsed = parse([header(), assistant("m1", block)])
    assert only_issue(parsed) == "invalid_read_path"
    assert not parsed.attempts


@pytest.mark.parametrize(
    "block",
    [
        {"type": "toolCall", "name": "read", "arguments": {"path": "skill://a"}},
        {
            "type": "toolCall",
            "id": "",
            "name": "read",
            "arguments": {"path": "skill://a"},
        },
        {"type": "toolCall", "id": "c1", "arguments": {"path": "skill://a"}},
        {"type": "toolCall", "id": 1, "name": "bash"},
    ],
)
def test_tool_calls_require_id_and_name_even_for_unrelated_tools(block: Record) -> None:
    assert only_issue(parse([header(), assistant("m1", block)])) == "invalid_tool_call"


def test_unrelated_new_tool_names_do_not_invalidate_but_a_skill_tool_does() -> None:
    other = {"type": "toolCall", "id": "c9", "name": "quantum_read", "arguments": 7}
    parsed = parse([header(), assistant("m1", other, call("c1", "skill://alpha"))])
    assert not parsed.issues and len(parsed.attempts) == 1
    skill_tool = {
        "type": "toolCall",
        "id": "c2",
        "name": "skill",
        "arguments": {"name": "alpha"},
    }
    assert (
        only_issue(parse([header(), assistant("m2", skill_tool)]))
        == "unsupported_skill_tool"
    )


def test_unknown_assistant_content_block_is_an_issue_but_known_blocks_are_not() -> None:
    blocks: list[Record] = [
        {"type": "text"},
        {"type": "thinking"},
        {"type": "redacted_thinking"},
        {"type": "image"},
    ]
    assert not parse([header(), assistant("m1", *blocks)]).issues
    assert (
        only_issue(parse([header(), assistant("m2", {"type": "serverToolUse"})]))
        == "unknown_content_block"
    )
    assert (
        only_issue(parse([header(), assistant("m3", {"id": "x"})]))
        == "invalid_content_block"
    )
    bad = assistant("m4")
    bad["message"]["content"] = "text"  # type: ignore[index]
    assert only_issue(parse([header(), bad])) == "invalid_message_content"


# --------------------------------------------------------------------------- direct reads


@pytest.mark.parametrize(
    ("path", "name", "partial"),
    [
        ("/skills/alpha/SKILL.md", "alpha", False),
        ("/alias/alpha/SKILL.md:1-50", "alpha", True),
        ("/alias/alpha/SKILL.md:raw", "alpha", False),
        ("/skills/other/../alpha/SKILL.md", "alpha", False),
        ("/shared/dup/SKILL.md", None, False),
        ("/shared/dup/SKILL.md:3-4", None, True),
    ],
)
def test_direct_reads_match_only_cataloged_aliases_and_keep_ambiguity_unresolved(
    path: str, name: str | None, partial: bool
) -> None:
    parsed = parse([header(), assistant("m1", call("c1", path))])
    assert not parsed.issues
    (attempt,) = parsed.attempts
    assert (attempt.skill_name, attempt.channel, attempt.body, attempt.partial) == (
        name,
        "direct",
        True,
        partial,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/elsewhere/proj/SKILL.md",
        "skills/alpha/SKILL.md",
        "/skills/alpha/references/x.md",
        "/skills/alpha",
    ],
)
def test_unapproved_unresolved_or_relative_paths_are_not_skill_reads(path: str) -> None:
    parsed = parse([header(), assistant("m1", call("c1", path))])
    assert not parsed.issues and not parsed.attempts
    assert parsed.counts["non_skill_reads"] == 1


def test_home_relative_direct_reads_resolve_against_the_cataloged_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/home/synth")
    parsed = parse([header(), assistant("m1", call("c1", "~/.skills/zed/SKILL.md"))])
    assert [a.skill_name for a in parsed.attempts] == ["zed"]


# --------------------------------------------------------------------------- results


def test_result_links_by_call_id_and_keeps_success_distinct_from_attempt() -> None:
    parsed = parse(
        [
            header(),
            assistant(
                "m1", call("c1", "skill://alpha"), call("c2", "skill://alpha/SKILL.md")
            ),
            result("r1", "c1"),
            result("r2", "c2", is_error=True),
        ]
    )
    assert not parsed.issues and len(parsed.attempts) == 2
    by_call = {r.call_id: r for r in parsed.results}
    assert by_call["c1"].success is True and by_call["c2"].success is False
    assert {r.session_id for r in parsed.results} == {"s1"}


def test_result_time_is_the_envelope_time_not_the_message_epoch() -> None:
    parsed = parse(
        [header(), assistant("m1", call("c1", "skill://alpha")), result("r1", "c1")]
    )
    (outcome,) = parsed.results
    assert outcome.timestamp == RESULT_DT
    assert parsed.attempts[0].timestamp == EPOCH_DT


def test_attempt_without_result_stays_unresolved_and_result_may_precede_attempt() -> (
    None
):
    lone = parse([header(), assistant("m1", call("c1", "skill://alpha"))])
    assert len(lone.attempts) == 1 and lone.results == []
    reordered = parse(
        [header(), result("r1", "c1"), assistant("m1", call("c1", "skill://alpha"))]
    )
    assert [r.call_id for r in reordered.results] == ["c1"]


def test_results_for_other_reads_and_tools_are_not_emitted() -> None:
    parsed = parse(
        [
            header(),
            assistant("m1", call("c1", "/etc/hosts"), call("c2", "skill://alpha")),
            result("r1", "c1"),
            result("r2", "ghost"),
            result("r3", "c9", tool="bash"),
        ]
    )
    assert not parsed.issues and parsed.results == []
    assert parsed.counts["other_results"] == 3


def test_result_for_a_skill_read_from_another_tool_is_a_mismatch() -> None:
    parsed = parse(
        [
            header(),
            assistant("m1", call("c1", "skill://alpha")),
            result("r1", "c1", tool="bash"),
        ]
    )
    assert only_issue(parsed) == "tool_result_mismatch" and parsed.results == []


@pytest.mark.parametrize("is_error", ["false", None, 0, 1, "true"])
def test_is_error_must_be_boolean(is_error: object) -> None:
    parsed = parse(
        [
            header(),
            assistant("m1", call("c1", "skill://alpha")),
            result("r1", "c1", is_error=is_error),
        ]
    )
    assert only_issue(parsed) == "invalid_tool_result" and parsed.results == []


@pytest.mark.parametrize("field", ["toolCallId", "toolName", "isError"])
def test_tool_result_requires_linking_fields(field: str) -> None:
    record = result("r1", "c1")
    del record["message"][field]  # type: ignore[attr-defined,index]
    assert only_issue(parse([header(), record])) == "invalid_tool_result"


# --------------------------------------------------------------------------- epochs / envelopes

BAD_EPOCHS: list[object] = [
    "2026-03-01T10:00:00Z",
    "1772359200000",
    1_772_359_200,
    1_772_359_200_000.5,
    1_772_359_200_000.0,
    True,
    -1,
    None,
    [],
    999_999_999_999,
]


@pytest.mark.parametrize("epoch", BAD_EPOCHS)
@pytest.mark.parametrize(
    "role", ["assistant", "user", "developer", "toolResult", "custom"]
)
def test_present_or_missing_message_epoch_fails_even_with_a_valid_envelope(
    role: str, epoch: object
) -> None:
    builders: dict[str, Record] = {
        "assistant": assistant("m1", epoch=epoch),
        "user": plain("m1", "user", timestamp=epoch),
        "developer": plain("m1", "developer", timestamp=epoch),
        "toolResult": result("m1", "c1", epoch=epoch),
        "custom": custom_role("m1", epoch=epoch),
    }
    parsed = parse([header(), builders[role]])
    assert only_issue(parsed) == "invalid_epoch_milliseconds"
    assert not parsed.attempts and not parsed.invocations and not parsed.usage


def test_epoch_without_any_skill_read_is_still_validated() -> None:
    parsed = parse(
        [
            header(),
            assistant("m1", {"type": "text", "text": "hi"}, epoch="bad"),
            plain("u1", "user", timestamp=EPOCH),
        ]
    )
    assert parsed.issues == {"invalid_epoch_milliseconds": 1}


@pytest.mark.parametrize(
    "role", ["bashExecution", "pythonExecution", "hookMessage", "fileMention"]
)
def test_ignored_roles_are_counted_and_validated_only_when_an_epoch_is_present(
    role: str,
) -> None:
    good = parse([header(), plain("m1", role), plain("m2", role, timestamp=EPOCH)])
    assert not good.issues and good.counts["ignored_records"] == 2
    assert (
        only_issue(parse([header(), plain("m3", role, timestamp="soon")]))
        == "invalid_epoch_milliseconds"
    )


def test_unknown_or_missing_message_role_fails() -> None:
    assert (
        only_issue(parse([header(), plain("m1", "oracle", timestamp=EPOCH)]))
        == "unknown_message_role"
    )
    nameless = plain("m2", "user")
    del nameless["message"]["role"]  # type: ignore[attr-defined,index]
    assert only_issue(parse([header(), nameless])) == "invalid_message_role"
    broken = plain("m3", "user")
    broken["message"] = "text"
    assert only_issue(parse([header(), broken])) == "invalid_message"


@pytest.mark.parametrize(
    "stamp", ["2026-03-01T10:00:00", "yesterday", 1772359200000, None]
)
def test_envelope_timestamp_must_be_utc_aware_text(stamp: object) -> None:
    record = assistant("m1", call("c1", "skill://alpha"))
    record["timestamp"] = stamp
    parsed = parse([header(), record])
    assert only_issue(parsed) == "invalid_timestamp" and not parsed.attempts


def test_epoch_and_envelope_are_independent_clocks() -> None:
    record = assistant("m1", call("c1", "skill://alpha"), epoch=EPOCH + 5_000)
    record["timestamp"] = "2026-03-01T23:00:00Z"
    (attempt,) = parse([header(), record]).attempts
    assert attempt.timestamp == datetime(2026, 3, 1, 10, 0, 5, tzinfo=UTC)


def test_every_entry_requires_a_string_id() -> None:
    record = assistant("m1")
    for bad in (None, 5, ""):
        record["id"] = bad
        assert only_issue(parse([header(), record])) == "invalid_record_id"


# --------------------------------------------------------------------------- native custom shapes


def test_user_skill_prompt_shapes_are_slash_invocations_with_their_own_clock() -> None:
    parsed = parse(
        [header(), custom_top("c1"), custom_role("c2", details={"name": "team/beta"})]
    )
    assert not parsed.issues and not parsed.attempts
    top, role = parsed.invocations
    assert (top.skill_name, top.channel, top.call_id, top.session_id) == (
        "alpha",
        "slash",
        "c1",
        "s1",
    )
    assert top.timestamp == RESULT_DT
    assert (role.skill_name, role.call_id, role.timestamp) == (
        "team/beta",
        "c2",
        EPOCH_DT,
    )
    assert top.fingerprint and top.fingerprint != role.fingerprint


def test_agent_attributed_skill_prompt_is_an_autoload_dependency_not_an_invocation() -> (
    None
):
    parsed = parse(
        [
            header(),
            custom_top("c1", attribution="agent"),
            custom_role("c2", attribution="agent", details={"name": "team/beta"}),
        ]
    )
    assert not parsed.issues and not parsed.invocations and not parsed.attempts
    assert parsed.reference_names == {"alpha", "team/beta"}
    assert parsed.counts["autoload_injections"] == 2


@pytest.mark.parametrize("attribution", [None, "system", "USER", 1, ["user"]])
def test_skill_prompt_attribution_must_be_user_or_agent(attribution: object) -> None:
    for record in (
        custom_top("c1", attribution=attribution),
        custom_role("c2", attribution=attribution),
    ):
        parsed = parse([header(), record])
        assert only_issue(parsed) == "invalid_attribution" and not parsed.invocations


@pytest.mark.parametrize(
    "details", [None, "alpha", {}, {"name": ""}, {"name": 4}, {"other": "alpha"}, []]
)
def test_skill_prompt_requires_details_name(details: object) -> None:
    for record in (
        custom_top("c1", details=details),
        custom_role("c2", details=details),
    ):
        parsed = parse([header(), record])
        assert only_issue(parsed) == "invalid_skill_prompt" and not parsed.invocations


def test_other_custom_types_are_ignored_but_the_type_field_is_required() -> None:
    other = parse(
        [
            header(),
            custom_top("c1", customType="my-extension", details=7, attribution=None),
        ]
    )
    assert (
        not other.issues
        and not other.invocations
        and other.counts["ignored_records"] == 1
    )
    for bad in (None, 5, ""):
        assert (
            only_issue(parse([header(), custom_top("c2", customType=bad)]))
            == "invalid_custom_message"
        )
    role_other = parse(
        [
            header(),
            custom_role("c3", customType="x"),
            custom_role("c4", epoch="bad", customType="x"),
        ]
    )
    assert role_other.issues == {"invalid_epoch_milliseconds": 1}


# --------------------------------------------------------------------------- usage / context


USAGE: Record = {
    "input": 100,
    "output": 20,
    "totalTokens": 999,
    "cacheRead": 5_000,
    "cacheWrite": 7,
    "cost": {
        "input": 0.25,
        "output": 0.5,
        "cacheRead": 0.125,
        "cacheWrite": 0.0,
        "total": 0.875,
    },
}


def test_usage_counters_cost_and_context_are_distinct_unmerged_observations() -> None:
    parsed = parse(
        [
            header(),
            assistant(
                "m1",
                usage=USAGE,
                contextSnapshot={
                    "promptTokens": 1_234,
                    "nonMessageTokens": 567,
                    "other": "ignored",
                },
            ),
        ]
    )
    assert not parsed.issues
    usage, context = parsed.usage
    assert usage.counter_kind == "per_message" and context.counter_kind == "context"
    assert usage.identity != context.identity and usage.timestamp == EPOCH_DT
    assert usage.values == {
        "input": 100,
        "output": 20,
        "totalTokens": 999,
        "cacheRead": 5_000,
        "cacheWrite": 7,
        "cost_input": 0.25,
        "cost_output": 0.5,
        "cost_cacheRead": 0.125,
        "cost_cacheWrite": 0.0,
        "cost_total": 0.875,
    }
    assert context.values == {"promptTokens": 1_234, "nonMessageTokens": 567}
    assert usage.source != context.source
    assert parsed.coverage["usage"] == "available"


def test_usage_without_cost_has_no_cost_keys_and_absent_usage_is_not_zero() -> None:
    bare = {k: v for k, v in USAGE.items() if k != "cost"}
    parsed = parse([header(), assistant("m1", usage=bare), assistant("m2")])
    (observation,) = parsed.usage
    assert set(observation.values) == {
        "input",
        "output",
        "totalTokens",
        "cacheRead",
        "cacheWrite",
    }
    assert parsed.counts["assistant_without_usage"] == 1
    assert parse([header(), assistant("m3")]).coverage["usage"] == "unavailable"


def test_context_snapshot_accepts_either_signal_alone() -> None:
    parsed = parse(
        [
            header(),
            assistant("m1", contextSnapshot={"promptTokens": 9}),
            assistant("m2", contextSnapshot={"nonMessageTokens": 0}),
        ]
    )
    assert [u.values for u in parsed.usage] == [
        {"promptTokens": 9},
        {"nonMessageTokens": 0},
    ]


@pytest.mark.parametrize(
    "usage",
    [
        {**USAGE, "input": -1},
        {**USAGE, "output": True},
        {**USAGE, "totalTokens": 1.5},
        {**USAGE, "cacheRead": "5"},
        {**USAGE, "cacheWrite": None},
        {k: v for k, v in USAGE.items() if k != "cacheRead"},
        {**USAGE, "cost": {"total": -0.1}},
        {**USAGE, "cost": {"total": math.inf}},
        {**USAGE, "cost": {"total": math.nan}},
        {**USAGE, "cost": {"total": True}},
        {**USAGE, "cost": "free"},
        None,
        5,
    ],
)
def test_malformed_usage_fails_without_a_partial_observation(usage: object) -> None:
    parsed = parse([header(), assistant("m1", usage=usage)])
    assert only_issue(parsed) == "invalid_usage" and parsed.usage == []


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"other": 1},
        {"promptTokens": -1},
        {"promptTokens": 1.0},
        {"nonMessageTokens": True},
        {"promptTokens": "9"},
        None,
        [],
    ],
)
def test_malformed_context_snapshot_fails(snapshot: object) -> None:
    parsed = parse([header(), assistant("m1", contextSnapshot=snapshot)])
    assert only_issue(parsed) == "invalid_context_snapshot" and parsed.usage == []


# --------------------------------------------------------------------------- dedup


def test_identical_duplicate_record_is_counted_once() -> None:
    record = assistant("m1", call("c1", "skill://alpha"), usage=USAGE)
    parsed = parse(
        [header(), record, dict(record), result("r1", "c1"), result("r1", "c1")]
    )
    assert not parsed.issues
    assert (
        len(parsed.attempts) == 1
        and len(parsed.usage) == 1
        and len(parsed.results) == 1
    )
    assert parsed.counts["duplicate_records"] == 2


def test_same_entry_id_with_different_payload_or_type_is_a_conflict() -> None:
    first = assistant("m1", call("c1", "skill://alpha"))
    other_path = assistant("m1", call("c1", "skill://team/beta"))
    parsed = parse([header(), first, other_path])
    assert only_issue(parsed) == "conflicting_duplicate_record"
    assert [a.skill_name for a in parsed.attempts] == ["alpha"]
    label: Record = {"type": "label", "id": "m1", "timestamp": TS}
    assert only_issue(parse([header(), first, label])) == "conflicting_duplicate_record"


def test_same_call_id_in_distinct_entries_dedups_when_identical_and_conflicts_otherwise() -> (
    None
):
    same = parse(
        [
            header(),
            assistant("m1", call("c1", "skill://alpha")),
            assistant("m2", call("c1", "skill://alpha")),
        ]
    )
    assert (
        not same.issues
        and len(same.attempts) == 1
        and same.counts["duplicate_calls"] == 1
    )
    differ = parse(
        [
            header(),
            assistant("m1", call("c1", "skill://alpha")),
            assistant("m2", call("c1", "skill://alpha/SKILL.md")),
        ]
    )
    assert (
        only_issue(differ) == "conflicting_duplicate_call" and len(differ.attempts) == 1
    )
    mixed = parse(
        [
            header(),
            assistant("m1", call("c1", "skill://alpha")),
            assistant("m2", call("c1", "/etc/hosts")),
        ]
    )
    assert only_issue(mixed) == "conflicting_duplicate_call"
    within = parse(
        [
            header(),
            assistant(
                "m1", call("c1", "skill://alpha"), call("c1", "skill://team/beta")
            ),
        ]
    )
    assert only_issue(within) == "conflicting_duplicate_call"


def test_duplicate_results_dedup_or_conflict_on_outcome() -> None:
    attempt = assistant("m1", call("c1", "skill://alpha"))
    same = parse(
        [
            header(),
            attempt,
            result("r1", "c1"),
            result("r2", "c1", envelope="2026-03-01T12:00:00Z"),
        ]
    )
    assert (
        not same.issues
        and len(same.results) == 1
        and same.counts["duplicate_results"] == 1
    )
    differ = parse(
        [header(), attempt, result("r1", "c1"), result("r2", "c1", is_error=True)]
    )
    assert only_issue(differ) == "conflicting_duplicate_result"
    assert differ.results == []


def test_identical_repeated_invocation_counts_once_but_two_loads_are_two_events() -> (
    None
):
    once = parse([header(), custom_top("c1"), custom_top("c1")])
    assert len(once.invocations) == 1 and not once.issues
    twice = parse([header(), custom_top("c1"), custom_top("c2")])
    assert len(twice.invocations) == 2
    assert (
        only_issue(
            parse(
                [
                    header(),
                    custom_top("c1"),
                    custom_top("c1", details={"name": "team/beta"}),
                ]
            )
        )
        == "conflicting_duplicate_record"
    )


# --------------------------------------------------------------------------- cohorts and identity


@pytest.mark.parametrize("hint", ["main", "sub", "nested", "unknown"])
def test_cohort_hint_is_preserved_on_every_event_and_never_upgraded_to_main(
    hint: Cohort,
) -> None:
    parsed = parse(
        [
            header(parentSession="p"),
            init("<skills>\n- a: x\n</skills>"),
            assistant("m1", call("c1", "skill://alpha"), usage=USAGE),
            custom_top("c2"),
        ],
        hint=hint,
    )
    assert parsed.file_key == "file-1" and parsed.cohort_hint == hint
    assert parsed.sessions == {"s1": hint}
    assert {
        parsed.exposures[0].cohort,
        parsed.attempts[0].cohort,
        parsed.invocations[0].cohort,
    } == {hint}


def test_session_identity_comes_from_the_header_not_the_entry_ids() -> None:
    parsed = parse(
        [
            header("session-xyz"),
            assistant("m1", call("c1", "skill://alpha"), usage=USAGE),
        ]
    )
    assert parsed.attempts[0].session_id == "session-xyz"
    assert parsed.usage[0].identity[0] == "session-xyz"


# --------------------------------------------------------------------------- unrelated and unknown records


@pytest.mark.parametrize(
    "kind",
    [
        "model_usage",
        "thinking_level_change",
        "model_change",
        "service_tier_change",
        "compaction",
        "branch_summary",
        "reset_boundary",
        "custom",
        "label",
        "title_change",
        "ttsr_injection",
        "credential_pin",
        "mode_change",
    ],
)
def test_known_unrelated_record_types_are_counted_and_ignored(kind: str) -> None:
    parsed = parse(
        [header(), {"type": kind, "id": "x1", "timestamp": TS, "payload": {"a": [1]}}]
    )
    assert not parsed.issues
    assert parsed.counts["ignored_records"] == 1 and parsed.counts["records"] == 2


def test_ignored_records_still_need_ids_and_valid_timestamps_when_present() -> None:
    assert (
        only_issue(parse([header(), {"type": "label", "timestamp": TS}]))
        == "invalid_record_id"
    )
    assert (
        only_issue(parse([header(), {"type": "label", "id": "x", "timestamp": "nope"}]))
        == "invalid_timestamp"
    )
    assert not parse([header(), {"type": "label", "id": "x"}]).issues


@pytest.mark.parametrize("kind", ["tool_use", "session_end", "Message", "skill_load"])
def test_unknown_record_types_fail(kind: str) -> None:
    assert (
        only_issue(parse([header(), {"type": kind, "id": "x", "timestamp": TS}]))
        == "unknown_record_type"
    )


@pytest.mark.parametrize("kind", [None, 5, "", ["message"]])
def test_missing_or_wrongly_typed_discriminator_fails(kind: object) -> None:
    assert (
        only_issue(parse([header(), {"type": kind, "id": "x"}]))
        == "missing_record_type"
    )
    assert only_issue(parse([header(), {"id": "x"}])) == "missing_record_type"


# --------------------------------------------------------------------------- anonymity / partial counts


SENTINEL = "zq-sentinel-secret-7f3a"


def test_issue_keys_are_literal_codes_and_never_echo_log_values() -> None:
    hostile: list[Record] = [
        {"type": SENTINEL, "id": SENTINEL},
        {
            "type": "message",
            "id": SENTINEL,
            "timestamp": SENTINEL,
            "message": {"role": SENTINEL},
        },
        plain(SENTINEL, "user", timestamp=SENTINEL),
        plain("a1", SENTINEL, timestamp=EPOCH),
        assistant("a2", {"type": SENTINEL}),
        assistant(
            "a3",
            {
                "type": "toolCall",
                "id": SENTINEL,
                "name": SENTINEL,
                "arguments": {"path": 5},
            },
        ),
        assistant(
            "a4",
            {
                "type": "toolCall",
                "id": SENTINEL,
                "name": "read",
                "arguments": {"path": [SENTINEL]},
            },
        ),
        assistant(
            "a5", {"type": "toolCall", "id": SENTINEL, "name": "skill", "arguments": {}}
        ),
        assistant("a6", usage={"input": SENTINEL}),
        custom_top(SENTINEL, attribution=SENTINEL),
        custom_top("c9", details={"name": 5, "x": SENTINEL}),
        init(SENTINEL, runtime={"version": SENTINEL}),
        init(SENTINEL, "i9"),
        init([SENTINEL, 7], "i8"),
    ]
    parsed = parse([header(SENTINEL, title=SENTINEL)] + hostile)
    assert parsed.issues
    assert set(parsed.issues) <= ISSUE_CODES
    assert SENTINEL not in repr(dict(parsed.issues)) + repr(dict(parsed.counts)) + repr(
        parsed.coverage
    )
    assert SENTINEL not in repr(sorted(parsed.versions))


def test_valid_records_survive_alongside_malformed_ones_and_the_failure_is_counted() -> (
    None
):
    parsed = parse(
        [
            header(),
            init("<skills>\n- a: x\n</skills>"),
            assistant("m1", call("c1", "skill://alpha")),
            plain("bad", "user", timestamp="never"),
            assistant("m2", call("c2", "skill://team/beta/SKILL.md")),
            result("r1", "c2"),
        ]
    )
    assert parsed.issues == {"invalid_epoch_milliseconds": 1}
    assert [a.call_id for a in parsed.attempts] == ["c1", "c2"]
    assert [r.call_id for r in parsed.results] == ["c2"]
    assert parsed.counts["records"] == 6 and len(parsed.exposures) == 1


def test_parsing_is_deterministic_and_does_not_mutate_the_inventory() -> None:
    records = [
        header(),
        init(["a", "<skills>\n- alpha: x\n</skills>"]),
        assistant(
            "m1",
            call("c1", "skill://alpha"),
            call("c2", "/alias/alpha/SKILL.md"),
            usage=USAGE,
        ),
        result("r1", "c1"),
        custom_top("c3"),
    ]
    catalog = inventory()
    before = (
        list(catalog.entries),
        dict(catalog.direct_paths),
        set(catalog.ambiguous_paths),
    )
    first = parse_file(
        iter(records), inventory=catalog, file_key="f", cohort_hint="sub"
    )
    second = parse_file(
        iter(records), inventory=catalog, file_key="f", cohort_hint="sub"
    )
    assert first == second
    assert before == (catalog.entries, catalog.direct_paths, catalog.ambiguous_paths)


def test_read_invocation_and_dependency_channels_stay_separate() -> None:
    parsed = parse(
        [
            header(),
            init("x", autoloadSkills=["alpha"]),
            assistant("m1", call("c1", "skill://alpha")),
            custom_top("c2"),
            custom_top("c3", attribution="agent"),
        ]
    )
    assert len(parsed.attempts) == 1 and len(parsed.invocations) == 1
    assert parsed.reference_names == {"alpha"}
    assert parsed.coverage["native_invocation"] == "unavailable"
    assert parsed.coverage["slash_invocation"] == "available"


def test_unrelated_async_result_changes_do_not_taint_skill_read_coverage() -> None:
    parsed = parse(
        [
            header(),
            assistant(
                "background", call("background-call", "not-a-skill", name="bash")
            ),
            result("pending", "background-call", tool="bash"),
            result("completed", "background-call", tool="bash", is_error=True),
            assistant("reading", call("skill-call", "skill://alpha")),
            result("loaded", "skill-call"),
        ]
    )
    assert parsed.issues == {}
    assert len(parsed.attempts) == len(parsed.results) == 1
    assert parsed.results[0].success
