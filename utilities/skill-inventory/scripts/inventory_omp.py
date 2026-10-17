"""OMP session schema-v3 adapter: reduces records to allowlisted, in-memory metadata.

Semantics (all counts are persisted characters unless a name says ``virtual``):

* ``session_init.systemPrompt`` is a string or an ordered list of strings. The skills
  block is located in the newline-joined *virtual* view; each inserted join newline is
  not persisted, so it is excluded from every persisted span and reported separately
  (``separator_chars`` across the whole prompt, ``block_separator_chars`` inside the block).
* The block spans the line ``<skills>`` through the line ``</skills>`` (no trailing
  newline). An entry spans its ``- name: `` line through the character before the next entry
  or the closing tag, so it includes its own line terminator and any continuation lines;
  ``wrapper_chars`` is everything else in the block.
* No block, or no ``systemPrompt``, or no ``session_init`` at all is ``unavailable``,
  never a successful zero.
* Message epoch fields are validated on every relevant message; the envelope UTC timestamp
  is a separate field and never rescues a present invalid epoch.

Issue keys are literal codes only; log-provided values never reach an issue, count key or
exception message.
"""

from __future__ import annotations

import bisect
import hashlib
import os
import posixpath
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from inventory_types import (
    Cohort,
    EntryCost,
    Exposure,
    Inventory,
    Invocation,
    ParsedFile,
    ReadAttempt,
    ReadResult,
    SchemaError,
    UsageObservation,
    as_int,
    as_list,
    as_number,
    as_object,
    as_string,
    epoch_time,
    payload_fingerprint,
    utc_time,
)

SUPPORTED_SESSION_VERSION: Final = 3
SUPPORTED_RUNTIME_VERSIONS: Final = frozenset({"18.11.0", "18.11.1"})

SOURCE_INIT: Final = "omp_session_init"
SOURCE_USAGE: Final = "omp_message_usage"
SOURCE_CONTEXT: Final = "omp_context_snapshot"

ISSUE_CODES: Final = frozenset(
    {
        "conflicting_duplicate_call",
        "conflicting_duplicate_record",
        "conflicting_duplicate_result",
        "invalid_attribution",
        "invalid_autoload_skills",
        "invalid_content_block",
        "invalid_context_snapshot",
        "invalid_counter",
        "invalid_custom_message",
        "invalid_epoch_milliseconds",
        "invalid_list",
        "invalid_mcp_tool_selection",
        "invalid_message",
        "invalid_message_content",
        "invalid_message_role",
        "invalid_number",
        "invalid_object",
        "invalid_read_path",
        "invalid_record",
        "invalid_record_id",
        "invalid_runtime",
        "invalid_session_header",
        "invalid_skill_prompt",
        "invalid_string",
        "invalid_system_prompt",
        "invalid_timestamp",
        "invalid_tool_call",
        "invalid_tool_result",
        "invalid_usage",
        "missing_record_type",
        "missing_session_header",
        "misplaced_title",
        "multiple_session_headers",
        "multiple_skills_blocks",
        "record_before_header",
        "tool_result_mismatch",
        "unknown_content_block",
        "unknown_message_role",
        "unknown_record_type",
        "unsupported_runtime_version",
        "unsupported_schema_version",
        "unsupported_skill_tool",
        "unterminated_skills_block",
    }
)
_SCHEMA_BREAKING: Final = frozenset(
    {"unsupported_runtime_version", "unsupported_schema_version"}
)

# Known record types that carry no skill measurement; counted, never interpreted.
_IGNORED_TYPES: Final = frozenset(
    {
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
    }
)
# Message roles that are validated for an epoch (when present) and otherwise ignored.
_IGNORED_ROLES: Final = frozenset(
    {
        "bashExecution",
        "pythonExecution",
        "hookMessage",
        "fileMention",
        "branchSummary",
        "compactionSummary",
    }
)
_EPOCH_REQUIRED_ROLES: Final = frozenset({"user", "developer"})
_IGNORED_BLOCKS: Final = frozenset(
    {"text", "thinking", "redacted_thinking", "redactedThinking", "image"}
)
_USAGE_COUNTERS: Final = ("input", "output", "totalTokens", "cacheRead", "cacheWrite")
_COST_KEYS: Final = ("input", "output", "cacheRead", "cacheWrite", "total")
_CONTEXT_KEYS: Final = ("promptTokens", "nonMessageTokens")

_SKILL_URI: Final = re.compile(r"skill://", re.IGNORECASE)
_SELECTOR: Final = re.compile(r":(raw|img|conflicts|-?\d[\d,+\-]*)$")
_ENTRY: Final = re.compile(r"^- (\S+?):(?:\s|$)")
_OPEN_TAG: Final = "<skills>"
_CLOSE_TAG: Final = "</skills>"


@dataclass(frozen=True)
class _ReadCall:
    call_id: str
    fingerprint: str
    attempt: ReadAttempt | None


@dataclass(frozen=True)
class _PendingResult:
    call_id: str
    tool_name: str
    is_error: bool
    timestamp: datetime


@dataclass
class _Events:
    """Everything one record contributes; committed only if the record is not a duplicate."""

    exposures: list[Exposure] = field(default_factory=list)
    read_calls: list[_ReadCall] = field(default_factory=list)
    results: list[_PendingResult] = field(default_factory=list)
    invocations: list[Invocation] = field(default_factory=list)
    usage: list[UsageObservation] = field(default_factory=list)
    references: set[str] = field(default_factory=set)
    counts: Counter[str] = field(default_factory=Counter)
    runtime: str | None = None

    def digest(self, kind: str) -> str:
        shape = (
            kind,
            self.exposures,
            self.read_calls,
            self.results,
            self.invocations,
            self.usage,
            sorted(self.references),
        )
        return hashlib.sha256(repr(shape).encode()).hexdigest()


@dataclass(frozen=True)
class _Block:
    block_chars: int
    virtual_block_chars: int
    block_separator_chars: int
    wrapper_chars: int
    entry_chars: int
    entries: tuple[EntryCost, ...]


def _peel_selectors(value: str) -> tuple[str, bool]:
    """Strip trailing read selectors; ``partial`` is true only for line/tail ranges."""
    partial = False
    while (match := _SELECTOR.search(value)) is not None:
        if match.group(1)[0] in "-0123456789":
            partial = True
        value = value[: match.start()]
    return value, partial


def _normalized_absolute(path: str) -> str | None:
    # Mirrors Inventory.resolve_direct normalization; it never touches the filesystem.
    value = path
    if value.startswith("~/"):
        value = str(Path.home()) + value[1:]
    if not os.path.isabs(value):
        return None
    return os.path.normpath(value)


def _measure_block(segments: Sequence[str]) -> _Block | None:
    """Locate the one actual skills block in the joined view and map spans to persisted chars."""
    virtual = "\n".join(segments)
    joins: list[int] = []
    position = 0
    for segment in segments[:-1]:
        position += len(segment)
        joins.append(position)
        position += 1

    def persisted(start: int, end: int) -> int:
        inside = bisect.bisect_left(joins, end) - bisect.bisect_left(joins, start)
        return end - start - inside

    offset = 0
    open_start = -1
    close_start = -1
    close_end = -1
    found = False
    inside_block = False
    entry_starts: list[tuple[int, str]] = []
    for line in virtual.split("\n"):
        start = offset
        end = start + len(line)
        offset = end + 1
        if not inside_block:
            if line == _OPEN_TAG:
                if found:
                    raise SchemaError("multiple_skills_blocks")
                inside_block = True
                open_start = start
            continue
        if line == _CLOSE_TAG:
            inside_block = False
            found = True
            close_start = start
            close_end = end
            continue
        match = _ENTRY.match(line)
        if match is not None:
            entry_starts.append((start, match.group(1)))
    if inside_block:
        raise SchemaError("unterminated_skills_block")
    if not found:
        return None

    entries: list[EntryCost] = []
    for index, (start, name) in enumerate(entry_starts):
        end = (
            entry_starts[index + 1][0] if index + 1 < len(entry_starts) else close_start
        )
        entries.append(EntryCost(name=name, chars=persisted(start, end)))
    block_chars = persisted(open_start, close_end)
    entry_chars = sum(entry.chars for entry in entries)
    virtual_chars = close_end - open_start
    return _Block(
        block_chars=block_chars,
        virtual_block_chars=virtual_chars,
        block_separator_chars=virtual_chars - block_chars,
        wrapper_chars=block_chars - entry_chars,
        entry_chars=entry_chars,
        entries=tuple(entries),
    )


class _Parser:
    def __init__(
        self, inventory: Inventory, file_key: str, cohort_hint: Cohort
    ) -> None:
        self.inventory = inventory
        self.parsed = ParsedFile(file_key=file_key, cohort_hint=cohort_hint)
        self.cohort: Cohort = cohort_hint
        self.names: frozenset[str] = frozenset(
            entry.name for entry in inventory.entries
        ) | frozenset(inventory.direct_paths.values())
        self.header_state: Literal["none", "ok", "bad"] = "none"
        self.session_id = ""
        self.header_fingerprint = ""
        self.title_seen = False
        self.seen: dict[str, str] = {}
        self.read_calls: dict[str, str] = {}
        self.attempts: dict[str, ReadAttempt] = {}
        self.results: dict[str, _PendingResult] = {}
        self.result_conflicts: set[str] = set()

    # -- issue bookkeeping -------------------------------------------------

    def _issue(self, code: str) -> None:
        known = code if code in ISSUE_CODES else "invalid_record"
        self.parsed.issues[known] += 1
        if known in _SCHEMA_BREAKING:
            self.parsed.schema_supported = False

    # -- record loop ---------------------------------------------------------

    def feed(self, raw: dict[str, object]) -> None:
        self.parsed.counts["records"] += 1
        try:
            self._dispatch(raw)
        except SchemaError as error:
            self._issue(error.code)

    def _dispatch(self, raw: dict[str, object]) -> None:
        kind = as_string(raw.get("type"), "missing_record_type")
        if kind == "title":
            self._title()
            return
        if kind == "session":
            self._header(raw)
            return
        if self.header_state == "none":
            raise SchemaError("record_before_header")
        if self.header_state == "bad":
            self.parsed.counts["skipped_records"] += 1
            return
        entry_id = as_string(raw.get("id"), "invalid_record_id")
        if kind == "session_init":
            events = self._session_init(raw, entry_id)
        elif kind == "message":
            events = self._message(raw, entry_id)
        elif kind == "custom_message":
            events = self._custom_message(raw, entry_id)
        elif kind == "mcp_tool_selection":
            # Historical MCP discovery state is not skill evidence.
            utc_time(raw.get("timestamp"))
            selected = as_list(
                raw.get("selectedToolNames"), "invalid_mcp_tool_selection"
            )
            for tool_name in selected:
                if not isinstance(tool_name, str):
                    raise SchemaError("invalid_mcp_tool_selection")
            events = _Events()
            events.counts["ignored_records"] += 1
        elif kind in _IGNORED_TYPES:
            if "timestamp" in raw:
                utc_time(raw["timestamp"])
            events = _Events()
            events.counts["ignored_records"] += 1
        else:
            raise SchemaError("unknown_record_type")
        self._commit(entry_id, events.digest(kind), events)

    # -- header / title ------------------------------------------------------

    def _title(self) -> None:
        if self.header_state != "none" or self.title_seen:
            raise SchemaError("misplaced_title")
        self.title_seen = True
        self.parsed.counts["title_records"] += 1

    def _header(self, raw: dict[str, object]) -> None:
        version = raw.get("version")
        if isinstance(version, bool) or not isinstance(version, int):
            if self.header_state == "none":
                self.header_state = "bad"
            raise SchemaError("invalid_session_header")
        if version != SUPPORTED_SESSION_VERSION:
            if self.header_state == "none":
                self.header_state = "bad"
            raise SchemaError("unsupported_schema_version")
        try:
            session_id = as_string(raw.get("id"), "invalid_session_header")
            timestamp = utc_time(raw.get("timestamp"), "invalid_session_header")
            for key in ("title", "parentSession"):
                if key in raw and not isinstance(raw[key], str):
                    raise SchemaError("invalid_session_header")
        except SchemaError:
            if self.header_state == "none":
                self.header_state = "bad"
            raise
        fingerprint = hashlib.sha256(repr((session_id, timestamp)).encode()).hexdigest()
        if self.header_state == "ok":
            if fingerprint == self.header_fingerprint:
                self.parsed.counts["duplicate_records"] += 1
                return
            raise SchemaError("multiple_session_headers")
        if self.header_state == "bad":
            raise SchemaError("multiple_session_headers")
        self.header_state = "ok"
        self.session_id = session_id
        self.header_fingerprint = fingerprint
        self.parsed.sessions[session_id] = self.cohort
        self.parsed.versions.add(f"omp-session-{SUPPORTED_SESSION_VERSION}")

    # -- session_init --------------------------------------------------------

    def _session_init(self, raw: dict[str, object], entry_id: str) -> _Events:
        timestamp = utc_time(raw.get("timestamp"))
        events = _Events()
        if "runtime" in raw:
            runtime = as_object(raw["runtime"], "invalid_runtime")
            version = as_string(runtime.get("version"), "invalid_runtime")
            if version not in SUPPORTED_RUNTIME_VERSIONS:
                raise SchemaError("unsupported_runtime_version")
            events.runtime = version
        if "autoloadSkills" in raw:
            for item in as_list(raw["autoloadSkills"], "invalid_autoload_skills"):
                events.references.add(as_string(item, "invalid_autoload_skills"))
        segments = self._segments(raw)
        fingerprint = payload_fingerprint(
            {
                "systemPrompt": raw.get("systemPrompt"),
                "timestamp": raw.get("timestamp"),
                "runtimeVersion": events.runtime,
                "autoloadSkills": raw.get("autoloadSkills"),
            }
        )
        events.counts["session_inits"] += 1
        if segments is None:
            events.exposures.append(
                self._unavailable(
                    timestamp, SOURCE_INIT, None, 0, entry_id, fingerprint
                )
            )
            return events
        block = _measure_block(segments)
        prompt_chars = sum(len(segment) for segment in segments)
        joined = max(len(segments) - 1, 0)
        if block is None:
            events.exposures.append(
                self._unavailable(
                    timestamp, SOURCE_INIT, prompt_chars, joined, entry_id, fingerprint
                )
            )
            return events
        events.exposures.append(
            Exposure(
                timestamp=timestamp,
                session_id=self.session_id,
                cohort=self.cohort,
                source=SOURCE_INIT,
                status="complete",
                block_chars=block.block_chars,
                wrapper_chars=block.wrapper_chars,
                entry_chars=block.entry_chars,
                entries=block.entries,
                prompt_chars=prompt_chars,
                virtual_block_chars=block.virtual_block_chars,
                separator_chars=joined,
                block_separator_chars=block.block_separator_chars,
                declared_count=None,
                listed_names=len(block.entries),
                record_id=entry_id,
                fingerprint=fingerprint,
            )
        )
        return events

    @staticmethod
    def _segments(raw: dict[str, object]) -> list[str] | None:
        if "systemPrompt" not in raw:
            return None
        prompt = raw["systemPrompt"]
        if isinstance(prompt, str):
            return [prompt]
        if isinstance(prompt, list):
            segments: list[str] = []
            for item in prompt:
                if not isinstance(item, str):
                    raise SchemaError("invalid_system_prompt")
                segments.append(item)
            return segments
        raise SchemaError("invalid_system_prompt")

    def _unavailable(
        self,
        timestamp: datetime,
        source: str,
        prompt_chars: int | None,
        separators: int,
        record_id: str,
        fingerprint: str,
    ) -> Exposure:
        return Exposure(
            timestamp=timestamp,
            session_id=self.session_id,
            cohort=self.cohort,
            source=source,
            status="unavailable",
            block_chars=None,
            wrapper_chars=None,
            entry_chars=None,
            prompt_chars=prompt_chars,
            separator_chars=separators,
            record_id=record_id,
            fingerprint=fingerprint,
        )

    # -- messages --------------------------------------------------------------

    def _message(self, raw: dict[str, object], entry_id: str) -> _Events:
        envelope = utc_time(raw.get("timestamp"))
        message = as_object(raw.get("message"), "invalid_message")
        role = as_string(message.get("role"), "invalid_message_role")
        events = _Events()
        events.counts["messages"] += 1
        if role == "assistant":
            return self._assistant(message, entry_id, events)
        if role == "toolResult":
            return self._tool_result(message, envelope, events)
        if role == "custom":
            epoch = epoch_time(message.get("timestamp"))
            self._skill_prompt(message, entry_id, epoch, events)
            return events
        if role in _EPOCH_REQUIRED_ROLES:
            epoch_time(message.get("timestamp"))
            events.counts["ignored_records"] += 1
            return events
        if role in _IGNORED_ROLES:
            if "timestamp" in message:
                epoch_time(message["timestamp"])
            events.counts["ignored_records"] += 1
            return events
        raise SchemaError("unknown_message_role")

    def _assistant(
        self, message: dict[str, object], entry_id: str, events: _Events
    ) -> _Events:
        epoch = epoch_time(message.get("timestamp"))
        events.counts["assistant_messages"] += 1
        content = as_list(message.get("content"), "invalid_message_content")
        for block in content:
            item = as_object(block, "invalid_content_block")
            block_type = as_string(item.get("type"), "invalid_content_block")
            if block_type == "toolCall":
                self._tool_call(item, epoch, events)
            elif block_type not in _IGNORED_BLOCKS:
                raise SchemaError("unknown_content_block")
        self._usage(message, entry_id, epoch, events)
        return events

    def _tool_call(
        self, block: dict[str, object], epoch: datetime, events: _Events
    ) -> None:
        call_id = as_string(block.get("id"), "invalid_tool_call")
        name = as_string(block.get("name"), "invalid_tool_call")
        if name == "skill":
            raise SchemaError("unsupported_skill_tool")
        if name != "read":
            events.counts["other_tool_calls"] += 1
            return
        arguments = as_object(block.get("arguments"), "invalid_read_path")
        path = as_string(arguments.get("path"), "invalid_read_path")
        attempt = self._attempt(call_id, path, epoch)
        if attempt is None:
            events.counts["non_skill_reads"] += 1
        fingerprint = payload_fingerprint({"tool": "read", "path": path})
        events.read_calls.append(_ReadCall(call_id, fingerprint, attempt))

    def _attempt(self, call_id: str, path: str, epoch: datetime) -> ReadAttempt | None:
        if _SKILL_URI.match(path) is not None:
            return self._uri_attempt(call_id, path, epoch)
        return self._direct_attempt(call_id, path, epoch)

    def _uri_attempt(self, call_id: str, path: str, epoch: datetime) -> ReadAttempt:
        rest = re.split(r"[?#]", path[len("skill://") :], maxsplit=1)[0]
        rest, partial = _peel_selectors(rest)
        parts = [part for part in rest.split("/") if part not in ("", ".")]
        name: str | None = None
        resource = ""
        body = False
        if parts:
            if len(parts) >= 2 and f"{parts[0]}/{parts[1]}" in self.names:
                name = f"{parts[0]}/{parts[1]}"
                tail = parts[2:]
            else:
                name = parts[0]
                tail = parts[1:]
            resource = posixpath.normpath("/".join(tail)) if tail else ""
            resource = "" if resource == "." else resource
            body = resource in ("", "SKILL.md")
        return ReadAttempt(
            session_id=self.session_id,
            call_id=call_id,
            timestamp=epoch,
            skill_name=name,
            channel="uri",
            body=body,
            partial=partial and name is not None,
            fingerprint=payload_fingerprint({"channel": "uri", "path": path}),
            cohort=self.cohort,
        )

    def _direct_attempt(
        self, call_id: str, path: str, epoch: datetime
    ) -> ReadAttempt | None:
        base, partial = _peel_selectors(path)
        name = self.inventory.resolve_direct(base)
        if name is None:
            normalized = _normalized_absolute(base)
            if normalized is None or normalized not in self.inventory.ambiguous_paths:
                return None
        return ReadAttempt(
            session_id=self.session_id,
            call_id=call_id,
            timestamp=epoch,
            skill_name=name,
            channel="direct",
            body=True,
            partial=partial,
            fingerprint=payload_fingerprint({"channel": "direct", "path": path}),
            cohort=self.cohort,
        )

    def _tool_result(
        self, message: dict[str, object], envelope: datetime, events: _Events
    ) -> _Events:
        epoch_time(message.get("timestamp"))
        call_id = as_string(message.get("toolCallId"), "invalid_tool_result")
        tool_name = as_string(message.get("toolName"), "invalid_tool_result")
        is_error = message.get("isError")
        if not isinstance(is_error, bool):
            raise SchemaError("invalid_tool_result")
        events.results.append(_PendingResult(call_id, tool_name, is_error, envelope))
        return events

    def _usage(
        self,
        message: dict[str, object],
        entry_id: str,
        epoch: datetime,
        events: _Events,
    ) -> None:
        if "usage" in message:
            usage = as_object(message["usage"], "invalid_usage")
            values: dict[str, int | float] = {
                key: as_int(usage.get(key), "invalid_usage") for key in _USAGE_COUNTERS
            }
            if "cost" in usage:
                cost = as_object(usage["cost"], "invalid_usage")
                for key in _COST_KEYS:
                    if key in cost:
                        values[f"cost_{key}"] = as_number(cost[key], "invalid_usage")
            events.usage.append(
                UsageObservation(
                    identity=(self.session_id, entry_id, "usage"),
                    timestamp=epoch,
                    source=SOURCE_USAGE,
                    counter_kind="per_message",
                    values=values,
                )
            )
        else:
            events.counts["assistant_without_usage"] += 1
        if "contextSnapshot" in message:
            snapshot = as_object(message["contextSnapshot"], "invalid_context_snapshot")
            context: dict[str, int | float] = {
                key: as_int(snapshot[key], "invalid_context_snapshot")
                for key in _CONTEXT_KEYS
                if key in snapshot
            }
            if not context:
                raise SchemaError("invalid_context_snapshot")
            events.usage.append(
                UsageObservation(
                    identity=(self.session_id, entry_id, "context"),
                    timestamp=epoch,
                    source=SOURCE_CONTEXT,
                    counter_kind="context",
                    values=context,
                )
            )

    # -- custom skill-prompt shapes -----------------------------------------

    def _custom_message(self, raw: dict[str, object], entry_id: str) -> _Events:
        envelope = utc_time(raw.get("timestamp"))
        events = _Events()
        self._skill_prompt(raw, entry_id, envelope, events)
        return events

    def _skill_prompt(
        self, fields: dict[str, object], entry_id: str, when: datetime, events: _Events
    ) -> None:
        custom_type = as_string(fields.get("customType"), "invalid_custom_message")
        if custom_type != "skill-prompt":
            events.counts["ignored_records"] += 1
            return
        attribution = fields.get("attribution")
        if attribution not in ("user", "agent"):
            raise SchemaError("invalid_attribution")
        details = as_object(fields.get("details"), "invalid_skill_prompt")
        name = as_string(details.get("name"), "invalid_skill_prompt")
        if attribution == "agent":
            events.references.add(name)
            events.counts["autoload_injections"] += 1
            return
        events.invocations.append(
            Invocation(
                session_id=self.session_id,
                call_id=entry_id,
                timestamp=when,
                skill_name=name,
                channel="slash",
                fingerprint=payload_fingerprint(
                    {"custom": "skill-prompt", "name": name}
                ),
                cohort=self.cohort,
            )
        )

    # -- commit / finalize -----------------------------------------------------

    def _commit(self, entry_id: str, digest: str, events: _Events) -> None:
        prior = self.seen.get(entry_id)
        if prior is not None:
            if prior == digest:
                self.parsed.counts["duplicate_records"] += 1
            else:
                self._issue("conflicting_duplicate_record")
            return
        self.seen[entry_id] = digest
        parsed = self.parsed
        parsed.counts.update(events.counts)
        if events.runtime:
            parsed.versions.add(f"omp-runtime-{events.runtime}")
        parsed.exposures.extend(events.exposures)
        parsed.invocations.extend(events.invocations)
        parsed.usage.extend(events.usage)
        parsed.reference_names |= events.references
        for call in events.read_calls:
            known = self.read_calls.get(call.call_id)
            if known is None:
                self.read_calls[call.call_id] = call.fingerprint
                if call.attempt is not None:
                    self.attempts[call.call_id] = call.attempt
                    parsed.attempts.append(call.attempt)
            elif known == call.fingerprint:
                parsed.counts["duplicate_calls"] += 1
            else:
                self._issue("conflicting_duplicate_call")
        for result in events.results:
            prior_result = self.results.get(result.call_id)
            if prior_result is None:
                self.results[result.call_id] = result
            elif (prior_result.is_error, prior_result.tool_name) == (
                result.is_error,
                result.tool_name,
            ):
                if result.timestamp < prior_result.timestamp:
                    self.results[result.call_id] = result
                parsed.counts["duplicate_results"] += 1
            else:
                self.result_conflicts.add(result.call_id)

    def finish(self) -> ParsedFile:
        parsed = self.parsed
        if self.header_state != "ok":
            parsed.schema_supported = False
        if self.header_state == "none":
            self._issue("missing_session_header")
        for call_id, result in self.results.items():
            attempt = self.attempts.get(call_id)
            if attempt is None:
                parsed.counts["other_results"] += 1
            elif call_id in self.result_conflicts:
                self._issue("conflicting_duplicate_result")
            elif result.tool_name != "read":
                self._issue("tool_result_mismatch")
            else:
                parsed.results.append(
                    ReadResult(
                        session_id=self.session_id,
                        call_id=call_id,
                        success=not result.is_error,
                        timestamp=result.timestamp,
                    )
                )
        parsed.coverage.update(self._coverage())
        return parsed

    def _coverage(self) -> dict[str, str]:
        statuses = {exposure.status for exposure in self.parsed.exposures}
        if not statuses or statuses == {"unavailable"}:
            exposure = "unavailable"
        elif statuses == {"complete"}:
            exposure = "complete"
        else:
            exposure = "partial"
        return {
            "exposure": exposure,
            "native_read": "available",
            "slash_invocation": "available",
            "native_invocation": "unavailable",
            "usage": "available" if self.parsed.usage else "unavailable",
        }


def parse_file(
    records: Iterable[dict[str, object]],
    *,
    inventory: Inventory,
    file_key: str,
    cohort_hint: Cohort,
) -> ParsedFile:
    """Reduce one OMP session file to allowlisted metadata; failures are anonymous issue codes."""
    parser = _Parser(inventory, file_key, cohort_hint)
    for record in records:
        parser.feed(record)
    return parser.finish()
