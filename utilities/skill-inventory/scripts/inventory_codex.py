"""Codex rollout adapter: reduces records to allowlisted, in-memory metadata.

Source fields read (all other record content is discarded without inspection):

* every record is ``{timestamp, type, payload}`` (optional integer ``ordinal``); the first record
  must be ``session_meta`` whose ``payload.cli_version`` is an exact allowlisted release
  identity. Any other identity is a schema failure, never a range match.
* ``session_meta.payload``: ``id`` (the thread identity), ``timestamp``, optional ``source``
  (``cli``/``exec``/``vscode`` or ``{subagent: {thread_spawn: {depth, ...}}}``),
  ``thread_source``, ``forked_from_id``, ``parent_thread_id``, ``base_instructions.text``.
  Fork and subagent lineage are independent facts: a fork is ``forked_from_id``; a subagent is a
  declared ``source.subagent``. A fork file carries a second ``session_meta`` describing the
  parent thread (``id == forked_from_id``) followed by replayed parent history; that parent record
  is counted but never registered as a session of this file.
* Tagged ``<skills_instructions>`` blocks are measured in exactly five text surfaces, each
  observation preserved with its own record timestamp and source label: developer
  ``response_item`` message ``input_text`` items, ``turn_context`` ``developer_instructions`` /
  ``user_instructions``, ``session_meta`` ``base_instructions.text`` and developer ``message``
  items of ``compacted.payload.replacement_history`` (same ``input_text`` shape; observed at the
  compaction record's timestamp, physical repeats of earlier items). Only the characters from
  the opening tag through the closing tag are measured; surrounding text is discarded. Inside the
  block only the ``### Available skills`` section yields entries
  (``- name: description (file: .../SKILL.md)``); it ends at the next heading of level <= 3 or the
  closing tag, so instructional bullets elsewhere are never counted. An entry spans its line plus
  its line terminator; everything else in the block is wrapper. Observations are physical and
  unkeyed (Codex declares no logical record id), never request charges.
* ``event_msg`` ``token_count``: ``payload.info`` is null or carries ``last_token_usage`` and
  ``total_token_usage`` with five validated counters each. Every persisted event is a physical
  observation emitting separate ``last`` and ``cumulative`` entries, identified by session, opaque
  file key and record position, never by counter values (identical tuples recur at separate
  times); they are never added together. Files declaring ``forked_from_id`` replay parent history
  with no marker separating it from new activity, so their events use a distinct source label
  and are physical telemetry that may repeat the parent's, not new requests or billing.
* Native skill reads and invocations are unavailable: ``function_call`` / ``custom_tool_call``
  envelopes are counted and never interpreted, so no attempt, result or invocation is emitted.

Issue and count keys are literal software labels; no log-provided value reaches one.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal

from inventory_types import (
    Cohort,
    EntryCost,
    Exposure,
    Inventory,
    ParsedFile,
    SchemaError,
    UsageObservation,
    as_int,
    as_list,
    as_object,
    as_string,
    payload_fingerprint,
    utc_time,
)

SUPPORTED_CLI_VERSIONS: Final = frozenset(
    {
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
    }
)

SOURCE_BASE_INSTRUCTIONS: Final = "codex_session_base_instructions"
SOURCE_DEVELOPER_MESSAGE: Final = "codex_developer_message"
SOURCE_TURN_DEVELOPER: Final = "codex_turn_developer_instructions"
SOURCE_TURN_USER: Final = "codex_turn_user_instructions"
SOURCE_COMPACTED_REPLACEMENT: Final = "codex_compacted_replacement_history"
SOURCE_USAGE: Final = "codex_token_count"
SOURCE_USAGE_FORK: Final = "codex_token_count_fork_lineage"

ISSUE_CODES: Final = frozenset(
    {
        "conflicting_session_lineage",
        "invalid_available_skills_section",
        "invalid_content_block",
        "invalid_counter",
        "invalid_instructions_field",
        "invalid_list",
        "invalid_message",
        "invalid_object",
        "invalid_payload",
        "invalid_record",
        "invalid_session_meta",
        "invalid_skills_entry",
        "invalid_string",
        "invalid_timestamp",
        "invalid_token_info",
        "malformed_skills_block",
        "missing_available_skills_section",
        "missing_record_type",
        "missing_session_meta",
        "multiple_session_meta",
        "multiple_skills_blocks",
        "record_before_session_meta",
        "unknown_content_block",
        "unknown_message_role",
        "unknown_payload_type",
        "unknown_record_type",
        "unmatched_skills_close_tag",
        "unsupported_cli_version",
        "unsupported_session_source",
        "unterminated_skills_block",
    }
)
_SCHEMA_BREAKING: Final = frozenset({"unsupported_cli_version"})

# Recognized record kinds that carry no skill measurement; counted, never interpreted.
_IGNORED_TOP_LEVEL: Final = frozenset(
    {"inter_agent_communication_metadata", "world_state"}
)
_RESPONSE_ITEM_TYPES: Final = frozenset(
    {
        "agent_message",
        "custom_tool_call",
        "custom_tool_call_output",
        "function_call",
        "function_call_output",
        "ghost_snapshot",
        "message",
        "reasoning",
        "tool_search_call",
        "tool_search_output",
        "web_search_call",
    }
)
_TOOL_ENVELOPES: Final = frozenset({"custom_tool_call", "function_call"})
_EVENT_TYPES: Final = frozenset(
    {
        "agent_message",
        "agent_reasoning",
        "collab_agent_spawn_end",
        "collab_close_end",
        "collab_waiting_end",
        "context_compacted",
        "error",
        "exec_command_end",
        "item_completed",
        "mcp_tool_call_end",
        "patch_apply_end",
        "sub_agent_activity",
        "task_complete",
        "task_started",
        "thread_goal_updated",
        "thread_name_updated",
        "thread_rolled_back",
        "thread_settings_applied",
        "token_count",
        "turn_aborted",
        "user_message",
        "web_search_end",
    }
)
_MESSAGE_ROLES: Final = frozenset({"assistant", "developer", "user"})
_STRING_SOURCES: Final = frozenset({"cli", "exec", "vscode"})
_THREAD_SOURCES: Final = frozenset({"subagent", "user"})
_COUNTERS: Final = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)

_TAG: Final = re.compile(r"</?skills_instructions>")
_OPEN_TAG: Final = "<skills_instructions>"
_CLOSE_TAG: Final = "</skills_instructions>"
_HEADING: Final = re.compile(r"^(#{1,6}) ")
_AVAILABLE_HEADING: Final = "### Available skills"
_PEER_HEADING_LEVEL: Final = 3
_ENTRY: Final = re.compile(
    r"^- (?P<name>[^\s:]+(?::[^\s:]+)*): (?P<description>.*) \(file: \S.*SKILL\.md\)$"
)


@dataclass(frozen=True)
class _Block:
    block_chars: int
    wrapper_chars: int
    entry_chars: int
    entries: tuple[EntryCost, ...]


def _locate_blocks(text: str) -> list[tuple[int, int]]:
    """Return inner (start, end) spans of tagged blocks; any malformed tagging is an error."""
    spans: list[tuple[int, int]] = []
    inside_at = -1
    for match in _TAG.finditer(text):
        opening = match.group(0) == _OPEN_TAG
        if inside_at < 0:
            if not opening:
                raise SchemaError("unmatched_skills_close_tag")
            inside_at = match.end()
        elif opening:
            raise SchemaError("malformed_skills_block")
        else:
            spans.append((inside_at, match.start()))
            inside_at = -1
    if inside_at >= 0:
        raise SchemaError("unterminated_skills_block")
    if len(spans) > 1:
        raise SchemaError("multiple_skills_blocks")
    return spans


def _measure_block(text: str, inner: tuple[int, int]) -> _Block:
    start, end = inner
    body = text[start:end]
    entries: list[EntryCost] = []
    section_seen = False
    in_available = False
    lines = body.split("\n")
    for index, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading is not None:
            level = len(heading.group(1))
            if in_available and level > _PEER_HEADING_LEVEL:
                raise SchemaError("invalid_available_skills_section")
            if level <= _PEER_HEADING_LEVEL:
                in_available = False
            if line == _AVAILABLE_HEADING:
                if section_seen:
                    raise SchemaError("invalid_available_skills_section")
                section_seen = in_available = True
            continue
        if not in_available or not line.strip():
            continue
        match = _ENTRY.match(line)
        if match is None:
            raise SchemaError("invalid_skills_entry")
        terminated = index < len(lines) - 1
        entries.append(EntryCost(match.group("name"), len(line) + int(terminated)))
    if not section_seen:
        raise SchemaError("missing_available_skills_section")
    block_chars = (end + len(_CLOSE_TAG)) - (start - len(_OPEN_TAG))
    entry_chars = sum(entry.chars for entry in entries)
    return _Block(
        block_chars=block_chars,
        wrapper_chars=block_chars - entry_chars,
        entry_chars=entry_chars,
        entries=tuple(entries),
    )


@dataclass
class _Events:
    """What one record contributes; committed only after the whole record validates."""

    exposures: list[Exposure] = field(default_factory=list)
    usage: list[UsageObservation] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class _Meta:
    session_id: str
    declared_at: datetime
    version: str
    forked_from: str | None
    parent_thread: str | None
    thread_source: str | None


class _Parser:
    def __init__(self, file_key: str, cohort_hint: Cohort) -> None:
        self.parsed = ParsedFile(file_key=file_key, cohort_hint=cohort_hint)
        self.hint = cohort_hint
        self.state: Literal["none", "ok", "bad"] = "none"
        self.session_id = ""
        self.cohort: Cohort = cohort_hint
        self.forked_from: str | None = None
        self.header_fingerprint = ""
        self.parent_meta_seen = False
        self.file_key = file_key

    def _issue(self, code: str) -> None:
        known = code if code in ISSUE_CODES else "invalid_record"
        self.parsed.issues[known] += 1
        if known in _SCHEMA_BREAKING:
            self.parsed.schema_supported = False

    # -- record loop ------------------------------------------------------------

    def feed(self, raw: dict[str, object]) -> None:
        self.parsed.counts["records"] += 1
        try:
            self._dispatch(raw)
        except SchemaError as error:
            self._issue(error.code)
            if self.state == "none":
                self.state = "bad"

    def _dispatch(self, raw: dict[str, object]) -> None:
        kind = as_string(raw.get("type"), "missing_record_type")
        if self.state == "bad":
            self.parsed.counts["skipped_records"] += 1
            return
        if self.state == "none" and kind != "session_meta":
            self.state = "bad"
            self.parsed.counts["skipped_records"] += 1
            raise SchemaError("record_before_session_meta")
        timestamp = utc_time(raw.get("timestamp"))
        if "ordinal" in raw:
            as_int(raw["ordinal"])
        payload = as_object(raw.get("payload"), "invalid_payload")
        events = _Events()
        if kind == "session_meta":
            self._session_meta(payload, timestamp, events)
        elif kind == "turn_context":
            self._turn_context(payload, timestamp, events)
        elif kind == "response_item":
            self._response_item(payload, timestamp, events)
        elif kind == "event_msg":
            self._event_msg(payload, timestamp, events)
        elif kind == "compacted":
            self._compacted(payload, timestamp, events)
        elif kind in _IGNORED_TOP_LEVEL:
            events.counts["ignored_records"] += 1
        else:
            raise SchemaError("unknown_record_type")
        self._commit(events)

    def _commit(self, events: _Events) -> None:
        parsed = self.parsed
        parsed.exposures.extend(events.exposures)
        parsed.usage.extend(events.usage)
        parsed.counts.update(events.counts)

    # -- session_meta -----------------------------------------------------------

    def _session_meta(
        self, payload: dict[str, object], timestamp: datetime, events: _Events
    ) -> None:
        meta = self._read_meta(payload)
        if self.state == "none":
            self._first_meta(payload, meta, timestamp, events)
            return
        fingerprint = self._meta_fingerprint(meta)
        if fingerprint == self.header_fingerprint:
            events.counts["duplicate_records"] += 1
            return
        if (
            self.forked_from is not None
            and meta.session_id == self.forked_from
            and not self.parent_meta_seen
        ):
            self.parent_meta_seen = True
            events.counts["fork_parent_meta_records"] += 1
            return
        raise SchemaError("multiple_session_meta")

    @staticmethod
    def _meta_fingerprint(meta: _Meta) -> str:
        return payload_fingerprint(
            {"id": meta.session_id, "timestamp": meta.declared_at.isoformat()}
        )

    def _read_meta(self, payload: dict[str, object]) -> _Meta:
        session_id = as_string(payload.get("id"), "invalid_session_meta")
        declared_at = utc_time(payload.get("timestamp"), "invalid_session_meta")
        version = as_string(payload.get("cli_version"), "invalid_session_meta")
        thread_source = payload.get("thread_source")
        if thread_source is not None and (
            not isinstance(thread_source, str) or thread_source not in _THREAD_SOURCES
        ):
            raise SchemaError("invalid_session_meta")
        if payload.get("instructions") is not None and not isinstance(
            payload["instructions"], str
        ):
            raise SchemaError("invalid_session_meta")
        return _Meta(
            session_id=session_id,
            declared_at=declared_at,
            version=version,
            forked_from=self._optional_string(payload, "forked_from_id"),
            parent_thread=self._optional_string(payload, "parent_thread_id"),
            thread_source=thread_source if isinstance(thread_source, str) else None,
        )

    @staticmethod
    def _optional_string(payload: dict[str, object], key: str) -> str | None:
        if key not in payload or payload[key] is None:
            return None
        return as_string(payload[key], "invalid_session_meta")

    def _first_meta(
        self,
        payload: dict[str, object],
        meta: _Meta,
        timestamp: datetime,
        events: _Events,
    ) -> None:
        if meta.version not in SUPPORTED_CLI_VERSIONS:
            raise SchemaError("unsupported_cli_version")
        cohort, lineage = self._declared_cohort(payload, meta)
        if meta.forked_from == meta.session_id:
            raise SchemaError("conflicting_session_lineage")
        base_text = self._base_instructions(payload)
        self.state = "ok"
        self.session_id = meta.session_id
        self.cohort = cohort
        self.forked_from = meta.forked_from
        self.header_fingerprint = self._meta_fingerprint(meta)
        self.parsed.sessions[meta.session_id] = cohort
        self.parsed.versions.add(f"codex-cli-{meta.version}")
        events.counts["session_meta_records"] += 1
        events.counts[lineage] += 1
        if meta.forked_from is not None:
            events.counts["forked_sessions"] += 1
        # A malformed tagged block fails its own observation, never the validated header.
        try:
            self._measure_text(base_text, SOURCE_BASE_INSTRUCTIONS, timestamp, events)
        except SchemaError as error:
            self._issue(error.code)

    @staticmethod
    def _base_instructions(payload: dict[str, object]) -> str | None:
        if payload.get("base_instructions") is None:
            return None
        base = as_object(payload["base_instructions"], "invalid_session_meta")
        text = base.get("text")
        if not isinstance(text, str):
            raise SchemaError("invalid_session_meta")
        return text

    def _declared_cohort(
        self, payload: dict[str, object], meta: _Meta
    ) -> tuple[Cohort, str]:
        source = payload.get("source")
        declared: Cohort | None
        if source is None:
            declared = None
        elif isinstance(source, str):
            if source not in _STRING_SOURCES:
                raise SchemaError("unsupported_session_source")
            declared = "main"
        else:
            declared = self._subagent_cohort(source, meta)
        if (
            meta.thread_source is not None
            and declared is not None
            and (meta.thread_source == "subagent") != (declared in ("sub", "nested"))
        ):
            raise SchemaError("conflicting_session_lineage")
        if declared is None and meta.thread_source is not None:
            declared = "sub" if meta.thread_source == "subagent" else "main"
        if declared is None:
            return self.hint, "sessions_without_declared_cohort"
        return declared, {
            "main": "main_sessions",
            "sub": "subagent_sessions",
            "nested": "nested_subagent_sessions",
        }[declared]

    @staticmethod
    def _subagent_cohort(source: object, meta: _Meta) -> Cohort:
        outer = as_object(source, "unsupported_session_source")
        if set(outer) != {"subagent"}:
            raise SchemaError("unsupported_session_source")
        inner = as_object(outer["subagent"], "unsupported_session_source")
        if set(inner) != {"thread_spawn"}:
            raise SchemaError("unsupported_session_source")
        spawn = as_object(inner["thread_spawn"], "unsupported_session_source")
        depth = as_int(spawn.get("depth"), "unsupported_session_source")
        if depth < 1:
            raise SchemaError("unsupported_session_source")
        declared_parent = spawn.get("parent_thread_id")
        if declared_parent is not None:
            as_string(declared_parent, "unsupported_session_source")
            if meta.parent_thread is not None and meta.parent_thread != declared_parent:
                raise SchemaError("conflicting_session_lineage")
        return "sub" if depth == 1 else "nested"

    # -- instruction surfaces ---------------------------------------------------

    def _turn_context(
        self, payload: dict[str, object], timestamp: datetime, events: _Events
    ) -> None:
        self._require_session()
        events.counts["turn_context_records"] += 1
        for key, source in (
            ("developer_instructions", SOURCE_TURN_DEVELOPER),
            ("user_instructions", SOURCE_TURN_USER),
        ):
            value = payload.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise SchemaError("invalid_instructions_field")
            self._measure_text(value, source, timestamp, events)

    def _response_item(
        self, payload: dict[str, object], timestamp: datetime, events: _Events
    ) -> None:
        self._require_session()
        kind = as_string(payload.get("type"), "unknown_payload_type")
        if kind not in _RESPONSE_ITEM_TYPES:
            raise SchemaError("unknown_payload_type")
        events.counts["response_items"] += 1
        if kind in _TOOL_ENVELOPES:
            as_string(payload.get("name"), "invalid_payload")
            as_string(payload.get("call_id"), "invalid_payload")
            events.counts["tool_call_envelopes"] += 1
            return
        if kind != "message":
            return
        role = as_string(payload.get("role"), "invalid_message")
        if role not in _MESSAGE_ROLES:
            raise SchemaError("unknown_message_role")
        content = as_list(payload.get("content"), "invalid_message")
        if role != "developer":
            return
        events.counts["developer_messages"] += 1
        for text in self._developer_texts(content):
            self._measure_text(text, SOURCE_DEVELOPER_MESSAGE, timestamp, events)

    def _compacted(
        self, payload: dict[str, object], timestamp: datetime, events: _Events
    ) -> None:
        self._require_session()
        events.counts["compacted_records"] += 1
        if not isinstance(payload.get("message"), str):
            raise SchemaError("invalid_message")
        history = payload.get("replacement_history")
        if history is None:
            events.counts["compacted_records_without_replacement_history"] += 1
            return
        # Replacement history repeats earlier items physically; developer messages use the
        # same input_text shape as live ones and are observed at the compaction time.
        for item in as_list(history, "invalid_list"):
            entry = as_object(item, "invalid_payload")
            if entry.get("type") != "message" or entry.get("role") != "developer":
                continue
            events.counts["compacted_developer_messages"] += 1
            content = as_list(entry.get("content"), "invalid_message")
            for text in self._developer_texts(content):
                self._measure_text(
                    text, SOURCE_COMPACTED_REPLACEMENT, timestamp, events
                )

    @staticmethod
    def _developer_texts(content: list[object]) -> list[str]:
        texts: list[str] = []
        for item in content:
            block = as_object(item, "invalid_content_block")
            if as_string(block.get("type"), "invalid_content_block") != "input_text":
                raise SchemaError("unknown_content_block")
            text = block.get("text")
            if not isinstance(text, str):
                raise SchemaError("invalid_content_block")
            texts.append(text)
        return texts

    def _measure_text(
        self,
        text: str | None,
        source: str,
        timestamp: datetime,
        events: _Events,
    ) -> None:
        if text is None:
            return
        spans = _locate_blocks(text)
        if not spans:
            events.counts["instruction_texts_without_skills_block"] += 1
            return
        block = _measure_block(text, spans[0])
        events.counts["skills_blocks"] += 1
        events.exposures.append(
            Exposure(
                timestamp=timestamp,
                session_id=self.session_id,
                cohort=self.cohort,
                source=source,
                status="complete",
                block_chars=block.block_chars,
                wrapper_chars=block.wrapper_chars,
                entry_chars=block.entry_chars,
                entries=block.entries,
                prompt_chars=None,
                virtual_block_chars=block.block_chars,
                declared_count=None,
                listed_names=len(block.entries),
                record_id=None,
                fingerprint=None,
            )
        )

    def _require_session(self) -> None:
        if self.state != "ok":
            raise SchemaError("missing_session_meta")

    # -- events -----------------------------------------------------------------

    def _event_msg(
        self, payload: dict[str, object], timestamp: datetime, events: _Events
    ) -> None:
        self._require_session()
        kind = as_string(payload.get("type"), "unknown_payload_type")
        if kind not in _EVENT_TYPES:
            raise SchemaError("unknown_payload_type")
        events.counts["event_msgs"] += 1
        if kind == "context_compacted":
            events.counts["context_compacted_events"] += 1
        elif kind == "thread_rolled_back":
            events.counts["thread_rolled_back_events"] += 1
        elif kind == "token_count":
            self._token_count(payload, timestamp, events)

    def _token_count(
        self, payload: dict[str, object], timestamp: datetime, events: _Events
    ) -> None:
        if "info" not in payload:
            raise SchemaError("invalid_token_info")
        events.counts["token_count_records"] += 1
        info = payload["info"]
        if info is None:
            events.counts["token_count_without_info"] += 1
            return
        fields = as_object(info, "invalid_token_info")
        total = self._counters(fields.get("total_token_usage"))
        last = self._counters(fields.get("last_token_usage"))
        if (
            "model_context_window" in fields
            and fields["model_context_window"] is not None
        ):
            as_int(fields["model_context_window"], "invalid_token_info")
        # Physical telemetry: each persisted event is its own observation. Counter tuples
        # repeat across events, forks and compactions, so values never form an identity.
        source = SOURCE_USAGE if self.forked_from is None else SOURCE_USAGE_FORK
        if self.forked_from is not None:
            events.counts["fork_lineage_token_count_records"] += 1
        position = str(self.parsed.counts["records"])
        observed: list[tuple[Literal["last", "cumulative"], dict[str, int | float]]] = [
            ("last", last),
            ("cumulative", total),
        ]
        for kind, values in observed:
            events.usage.append(
                UsageObservation(
                    identity=(self.session_id, self.file_key, position, kind),
                    timestamp=timestamp,
                    source=source,
                    counter_kind=kind,
                    values=dict(values),
                )
            )

    @staticmethod
    def _counters(value: object) -> dict[str, int | float]:
        usage = as_object(value, "invalid_token_info")
        return {name: as_int(usage.get(name), "invalid_counter") for name in _COUNTERS}

    # -- finish -----------------------------------------------------------------

    def finish(self) -> ParsedFile:
        parsed = self.parsed
        if self.state != "ok":
            parsed.schema_supported = False
        if self.state == "none":
            self._issue("missing_session_meta")
        parsed.coverage.update(self._coverage())
        return parsed

    def _coverage(self) -> dict[str, str]:
        parsed = self.parsed
        coverage = {
            "exposure": "complete" if parsed.exposures else "unavailable",
            "native_read": "unavailable",
            "slash_invocation": "unavailable",
            "native_invocation": "unavailable",
            "usage": "available" if parsed.usage else "unavailable",
        }
        return coverage


def parse_file(
    records: Iterable[dict[str, object]],
    *,
    inventory: Inventory,
    file_key: str,
    cohort_hint: Cohort,
) -> ParsedFile:
    """Reduce one Codex rollout to allowlisted metadata; failures are anonymous issue codes."""
    del (
        inventory
    )  # Roots, plugin visibility and ownership belong to the catalog, not the parser.
    parser = _Parser(file_key, cohort_hint)
    for record in records:
        parser.feed(record)
    return parser.finish()
