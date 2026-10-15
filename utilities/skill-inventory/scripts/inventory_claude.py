"""Claude Code transcript adapter: reduces records to allowlisted, in-memory metadata.

Evidence base. The listing grammar, envelope fields and tool shapes below come from
the public installed ``2.1.301`` consumer. Every other client identity in
``SUPPORTED_CLIENT_VERSIONS`` is admitted only because the plan's census observed it;
there is no range and no suffix grammar (Claude transcripts have no file suffix).

Semantics (all counts are decoded Unicode code points):

* Client identity is the top-level ``version`` string. It is required on ``user``,
  ``assistant`` and ``attachment`` records and checked when present on ``system`` and
  ``progress`` records. Any value outside the allowlist is ``unsupported_client_version``
  and the file is schema-unsupported. A file that never validates an identity is
  schema-unsupported as well. Identities exported as ``versions`` come from a fixed table.
* ``attachment.type=skill_listing`` carries ``content`` (str), ``names`` (str[]),
  ``skillCount`` (non-negative int) and ``isInitial`` (bool). Only the persisted listing
  content is measured, never the unpersisted renderer wrapper. Rows are ``- name`` or
  ``- name (alias)`` optionally followed by ``: description``; a row spans its line through
  the separator newline, so rows tile the content and ``wrapper_chars`` is zero.
* A listing is ``lower_bound`` when it is a non-initial (dynamic) snapshot, when any row is
  name-only (an over-budget listing downgrades descriptions to name-only, so agreement of
  names and counts alone never proves full descriptions), when a description ends in the
  producer's Unicode ellipsis truncation marker, or when ``skillCount``, ``names`` and the
  content rows disagree. Content that is not a ``- `` row grammar fails anonymously.
  Non-initial listings are never added to or substituted for initial exposure.
* ``tool_use`` blocks named ``Skill`` are native invocation ATTEMPTS (``input.skill`` is
  trimmed and one leading ``/`` removed, as the consumer does; the qualified name is
  otherwise preserved). ``Skill.args`` must be a string when present; it is hashed in
  memory only, so one call id reused with different arguments conflicts, and it is
  never retained or exported. ``Read`` blocks are direct reads only when
  ``Inventory.resolve_direct`` matches an approved alias; no log-named path is ever
  opened. A ``Read`` without a string ``file_path``, or with a non-null ``offset`` or
  ``limit`` that is not a non-negative int, fails anonymously. A valid path outside the
  approved aliases is a counted non-skill read; a non-null ``offset``/``limit`` makes a
  read partial. Skill-like tool names other than exactly ``Skill`` fail anonymously;
  unrelated tool names do not.
* ``user`` ``tool_result`` blocks correlate by ``tool_use_id`` with counted reads. An absent
  ``is_error`` means success (Messages API semantics) and is counted explicitly.
* Streaming and forks. Every record is interpreted; ``message.id`` is never used to drop a
  record before its blocks and usage are collected. Identities are the declared session,
  provider ``message.id`` and ``tool_use.id``. A record carrying ``forkedFrom`` is a copy of
  a record of that declared origin session, so its session and logical record id are the
  origin's; this resolves one hop only. Provider message ids, tool ids, envelope uuids and
  parent links stay distinct. Reusing one ``sessionId`` for a parent and its sidechain is
  legitimate; the declared ``isSidechain`` flag (never file placement) selects the cohort.
* Usage is emitted once per distinct ``(message, timestamp, counters)`` chunk. Chunks of a
  streamed message share an identity and are reduced by maximum downstream, never summed.
* Not interpreted or persisted: message text, ``toolUseResult``, ``args``, attachment
  bodies, ``invoked_skills`` contents, ``progress`` payloads and API telemetry records.

Issue, counter, coverage and version keys are literal software labels; log-provided values
never reach an issue, count key, coverage value, version or exception message.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Final

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
    as_object,
    as_string,
    payload_fingerprint,
    utc_time,
)

SUPPORTED_CLIENT_VERSIONS: Final = (
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
_VERSION_IDENTITY: Final = {
    version: f"claude-code-{version}" for version in SUPPORTED_CLIENT_VERSIONS
}

SOURCE_LISTING_INITIAL: Final = "claude_skill_listing_initial"
SOURCE_LISTING_DYNAMIC: Final = "claude_skill_listing_dynamic"
SOURCE_USAGE: Final = "claude_message_usage"

ISSUE_CODES: Final = frozenset(
    {
        "conflicting_duplicate_call",
        "conflicting_duplicate_record",
        "conflicting_duplicate_result",
        "invalid_agent_id",
        "invalid_attachment",
        "invalid_content_block",
        "invalid_fork_origin",
        "invalid_message",
        "invalid_message_content",
        "invalid_message_id",
        "invalid_message_role",
        "invalid_read_path",
        "invalid_read_range",
        "invalid_record",
        "invalid_record_uuid",
        "invalid_session_id",
        "invalid_sidechain",
        "invalid_skill_input",
        "invalid_skill_listing",
        "invalid_timestamp",
        "invalid_tool_result",
        "invalid_tool_use",
        "invalid_usage",
        "missing_client_version",
        "missing_record_type",
        "unknown_content_block",
        "unknown_record_type",
        "unsupported_client_version",
        "unsupported_skill_attachment",
        "unsupported_skill_tool",
        "unvalidated_client_identity",
    }
)
_SCHEMA_BREAKING: Final = frozenset(
    {"unsupported_client_version", "unvalidated_client_identity"}
)

# Conversation records written by the transcript serializer; only these carry a client
# identity. ``system`` and ``progress`` carry no skill measurement.
_RELEVANT_TYPES: Final = frozenset({"user", "assistant", "attachment"})
_UNMEASURED_TRANSCRIPT_TYPES: Final = frozenset({"system", "progress"})
_TRANSCRIPT_TYPES: Final = _RELEVANT_TYPES | _UNMEASURED_TRANSCRIPT_TYPES

# Public-consumer-verified top-level records without skill measurement. This list is not
# proof that an arbitrary future record is irrelevant: unknown types fail anonymously.
_IGNORED_TYPES: Final = frozenset(
    {
        "agent-color",
        "agent-name",
        "agent-setting",
        "ai-title",
        "api-request",
        "api-request-blob",
        "api-request-shape",
        "artifact-autoreact-ledger",
        "artifact-comment-monitor",
        "atis-latch",
        "attribution-snapshot",
        "bridge-session",
        "content-replacement",
        "continued-in",
        "cost-state",
        "custom-title",
        "dev-mods",
        "ended-by-model",
        "file-history-delta",
        "file-history-snapshot",
        "fork-context-ref",
        "frame-link",
        "history-suppression",
        "isolation-latch",
        "last-prompt",
        "memory-mode",
        "mode",
        "observer-ref",
        "permission-mode",
        "pr-link",
        "queue-operation",
        "relocated",
        "session-info",
        "summary",
        "tag",
        "worktree-state",
    }
)
_IGNORED_ASSISTANT_BLOCKS: Final = frozenset(
    {
        "bash_code_execution_tool_result",
        "code_execution_tool_result",
        "compaction",
        "container_upload",
        "image",
        "mcp_tool_result",
        "mcp_tool_use",
        "redacted_thinking",
        "server_tool_use",
        "text",
        "text_editor_code_execution_tool_result",
        "thinking",
        "tool_search_tool_result",
        "web_fetch_tool_result",
        "web_search_tool_result",
    }
)
_IGNORED_USER_BLOCKS: Final = frozenset(
    {"container_upload", "document", "image", "search_result", "text"}
)

_REQUIRED_USAGE: Final = ("input_tokens", "output_tokens")
_OPTIONAL_USAGE: Final = ("cache_read_input_tokens", "cache_creation_input_tokens")
_CACHE_TIERS: Final = (
    ("ephemeral_5m_input_tokens", "cache_creation.ephemeral_5m_input_tokens"),
    ("ephemeral_1h_input_tokens", "cache_creation.ephemeral_1h_input_tokens"),
)

# The consumer's own transcript validator rejects listings beyond these bounds.
_MAX_LISTING_NAMES: Final = 4096
_MAX_LISTING_NAME_CHARS: Final = 512
# Unicode ellipsis appended by the consumer when it truncates one description.
_TRUNCATION_MARKER: Final = "\u2026"

_SKILL_TOOL: Final = "Skill"
_READ_TOOL: Final = "Read"
# Claude's Read tool has no ``:selector`` grammar, so a suffixed path is a different file.
_SELECTOR_SUFFIX: Final = re.compile(r":(?:\d[\d,:+\-]*|raw|img)$")
_ROW: Final = re.compile(
    r"- (?P<name>[^\n]+?)(?: \((?P<alias>[^()\n]*)\))?(?:: (?P<desc>.*))?",
    re.DOTALL,
)

Key = tuple[str, str]
ExposureKey = tuple[str, str, str]
UsageKey = tuple[tuple[str, ...], str, tuple[tuple[str, int | float], ...]]


@dataclass(frozen=True)
class _Envelope:
    timestamp: datetime
    session: str
    origin_uuid: str | None
    cohort: Cohort


@dataclass(frozen=True)
class _Row:
    name: str
    chars: int
    described: bool
    aliased: bool
    truncated: bool


@dataclass(frozen=True)
class _Call:
    key: Key
    fingerprint: str
    attempt: ReadAttempt | None = None
    invocation: Invocation | None = None


@dataclass(frozen=True)
class _PendingResult:
    key: Key
    is_error: bool
    timestamp: datetime


@dataclass
class _Events:
    """Everything one record contributes; committed only if the whole record is valid."""

    sessions: set[tuple[str, Cohort]] = field(default_factory=set)
    exposures: list[tuple[ExposureKey, Exposure]] = field(default_factory=list)
    calls: list[_Call] = field(default_factory=list)
    results: list[_PendingResult] = field(default_factory=list)
    usage: list[UsageObservation] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)


def _union(first: Cohort, second: Cohort) -> Cohort:
    if first == second:
        return first
    return "unknown"


def _session_cohort(cohorts: set[Cohort]) -> Cohort:
    if len(cohorts) == 1:
        return next(iter(cohorts))
    return "unknown"


def _normalized_absolute(path: str) -> str | None:
    # Mirrors Inventory.resolve_direct normalization; it never touches the filesystem.
    value = path
    if value.startswith("~/"):
        value = str(Path.home()) + value[1:]
    if not os.path.isabs(value):
        return None
    return os.path.normpath(value)


def _merged_call(prior: _Call, other: _Call) -> _Call:
    """Fold an identical copy of one call: earliest instant, ``unknown`` on a cohort split."""
    attempt = prior.attempt
    if attempt is not None and other.attempt is not None:
        attempt = replace(
            attempt,
            timestamp=min(attempt.timestamp, other.attempt.timestamp),
            cohort=_union(attempt.cohort, other.attempt.cohort),
        )
    invocation = prior.invocation
    if invocation is not None and other.invocation is not None:
        invocation = replace(
            invocation,
            timestamp=min(invocation.timestamp, other.invocation.timestamp),
            cohort=_union(invocation.cohort, other.invocation.cohort),
        )
    return replace(prior, attempt=attempt, invocation=invocation)


# -- listing grammar -------------------------------------------------------------------


def _classify(rest: str) -> tuple[bool, bool, bool] | None:
    """Return (described, aliased, truncated) for the text following a row's name."""
    aliased = False
    if rest.startswith(" ("):
        close = rest.find(")")
        if close < 0:
            return None
        aliased = True
        rest = rest[close + 1 :]
    if rest == "":
        return False, aliased, False
    if rest.startswith(": "):
        return True, aliased, rest.endswith(_TRUNCATION_MARKER)
    return None


def _next_boundary(content: str, marker: str, start: int) -> int | None:
    """Find the separator newline that begins the next row, not a description's text."""
    found = content.find(marker, start)
    while found >= 0:
        after = found + len(marker)
        if after == len(content) or content.startswith(("\n", " (", ": "), after):
            return found
        found = content.find(marker, found + 1)
    return None


def _anchored_rows(content: str, names: list[str]) -> list[_Row] | None:
    """Tile the content exactly with the declared ordered names, or return ``None``."""
    rows: list[_Row] = []
    position = 0
    last = len(names) - 1
    for index, name in enumerate(names):
        head = f"- {name}"
        if not content.startswith(head, position):
            return None
        cursor = position + len(head)
        if index == last:
            end = len(content)
        else:
            boundary = _next_boundary(content, f"\n- {names[index + 1]}", cursor)
            if boundary is None:
                return None
            end = boundary
        shape = _classify(content[cursor:end])
        if shape is None:
            return None
        described, aliased, truncated = shape
        stop = end if index == last else end + 1
        rows.append(_Row(name, stop - position, described, aliased, truncated))
        position = stop
    return rows if position == len(content) else None


def _line_rows(content: str) -> list[_Row] | None:
    """Row structure without trusting the declared names; ``None`` is an unknown grammar."""
    if content == "":
        return []
    starts: list[int] = []
    offset = 0
    for line in content.split("\n"):
        if line.startswith("- "):
            starts.append(offset)
        elif not starts:
            return None
        offset += len(line) + 1
    rows: list[_Row] = []
    for index, start in enumerate(starts):
        is_last = index + 1 == len(starts)
        stop = len(content) if is_last else starts[index + 1]
        text = content[start : stop if is_last else stop - 1]
        match = _ROW.fullmatch(text)
        if match is None:
            return None
        description = match.group("desc")
        described = description is not None
        truncated = described and description.endswith(_TRUNCATION_MARKER)
        aliased = match.group("alias") is not None
        name = match.group("name")
        rows.append(_Row(name, stop - start, described, aliased, truncated))
    return rows


def _measure_listing(content: str, names: list[str]) -> tuple[list[_Row], bool]:
    """Rows plus whether the declared names tile the content exactly."""
    anchored = _anchored_rows(content, names)
    if anchored is not None:
        return anchored, True
    fallback = _line_rows(content)
    if fallback is None:
        raise SchemaError("invalid_skill_listing")
    return fallback, False


def _listing_names(value: object) -> list[str]:
    items = as_list(value, "invalid_skill_listing")
    if len(items) > _MAX_LISTING_NAMES:
        raise SchemaError("invalid_skill_listing")
    names: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise SchemaError("invalid_skill_listing")
        if not 0 < len(item) <= _MAX_LISTING_NAME_CHARS:
            raise SchemaError("invalid_skill_listing")
        names.append(item)
    return names


class _Parser:
    def __init__(
        self, inventory: Inventory, file_key: str, cohort_hint: Cohort
    ) -> None:
        self.inventory = inventory
        self.parsed = ParsedFile(file_key=file_key, cohort_hint=cohort_hint)
        self.session_cohorts: dict[str, set[Cohort]] = {}
        self.exposures: dict[ExposureKey, Exposure] = {}
        self.calls: dict[Key, _Call] = {}
        self.results: dict[Key, _PendingResult] = {}
        self.result_conflicts: set[Key] = set()
        self.usage_seen: set[UsageKey] = set()

    # -- issue bookkeeping ---------------------------------------------------------

    def _issue(self, code: str) -> None:
        known = code if code in ISSUE_CODES else "invalid_record"
        self.parsed.issues[known] += 1
        if known in _SCHEMA_BREAKING:
            self.parsed.schema_supported = False

    # -- record loop -----------------------------------------------------------------

    def feed(self, raw: dict[str, object]) -> None:
        self.parsed.counts["records"] += 1
        try:
            self._dispatch(raw)
        except SchemaError as error:
            self._issue(error.code)

    def _dispatch(self, raw: dict[str, object]) -> None:
        kind = as_string(raw.get("type"), "missing_record_type")
        if kind in _IGNORED_TYPES:
            self.parsed.counts["ignored_records"] += 1
            return
        if kind not in _TRANSCRIPT_TYPES:
            raise SchemaError("unknown_record_type")
        self._client_version(raw, required=kind in _RELEVANT_TYPES)
        if kind in _UNMEASURED_TRANSCRIPT_TYPES:
            self.parsed.counts["ignored_records"] += 1
            return
        events = _Events()
        if kind == "assistant":
            self._assistant(raw, events)
        elif kind == "user":
            self._user(raw, events)
        else:
            self._attachment(raw, events)
        self._commit(events)

    def _client_version(self, raw: dict[str, object], *, required: bool) -> None:
        if "version" not in raw:
            if required:
                raise SchemaError("missing_client_version")
            return
        value = raw["version"]
        identity = _VERSION_IDENTITY.get(value) if isinstance(value, str) else None
        if identity is None:
            raise SchemaError("unsupported_client_version")
        self.parsed.versions.add(identity)

    def _envelope(self, raw: dict[str, object], events: _Events) -> _Envelope:
        declared = as_string(raw.get("sessionId"), "invalid_session_id")
        sidechain = raw.get("isSidechain")
        if not isinstance(sidechain, bool):
            raise SchemaError("invalid_sidechain")
        if "agentId" in raw:
            as_string(raw["agentId"], "invalid_agent_id")
        timestamp = utc_time(raw.get("timestamp"))
        session = declared
        origin_uuid: str | None = None
        if "forkedFrom" in raw:
            origin = as_object(raw["forkedFrom"], "invalid_fork_origin")
            session = as_string(origin.get("sessionId"), "invalid_fork_origin")
            origin_uuid = as_string(origin.get("messageUuid"), "invalid_fork_origin")
            events.counts["forked_records"] += 1
        cohort: Cohort = "sub" if sidechain else "main"
        events.sessions.add((declared, cohort))
        events.sessions.add((session, cohort))
        return _Envelope(timestamp, session, origin_uuid, cohort)

    # -- assistant records -------------------------------------------------------------

    def _assistant(self, raw: dict[str, object], events: _Events) -> None:
        envelope = self._envelope(raw, events)
        message = as_object(raw.get("message"), "invalid_message")
        if message.get("role") != "assistant":
            raise SchemaError("invalid_message_role")
        message_id = as_string(message.get("id"), "invalid_message_id")
        content = as_list(message.get("content"), "invalid_message_content")
        events.counts["assistant_messages"] += 1
        for block in content:
            item = as_object(block, "invalid_content_block")
            block_type = as_string(item.get("type"), "invalid_content_block")
            if block_type == "tool_use":
                self._tool_use(item, envelope, events)
            elif block_type not in _IGNORED_ASSISTANT_BLOCKS:
                raise SchemaError("unknown_content_block")
        self._usage(message, message_id, envelope, events)

    def _tool_use(
        self, block: dict[str, object], envelope: _Envelope, events: _Events
    ) -> None:
        call_id = as_string(block.get("id"), "invalid_tool_use")
        name = as_string(block.get("name"), "invalid_tool_use")
        if name == _SKILL_TOOL:
            self._skill_call(call_id, block, envelope, events)
        elif name == _READ_TOOL:
            self._read_call(call_id, block, envelope, events)
        elif name.casefold() == "skill" or name.startswith("skill__"):
            raise SchemaError("unsupported_skill_tool")
        else:
            events.counts["other_tool_calls"] += 1

    def _skill_call(
        self,
        call_id: str,
        block: dict[str, object],
        envelope: _Envelope,
        events: _Events,
    ) -> None:
        arguments = as_object(block.get("input"), "invalid_skill_input")
        skill = arguments.get("skill")
        if not isinstance(skill, str):
            raise SchemaError("invalid_skill_input")
        name = skill.strip()
        name = name.removeprefix("/")
        if not name:
            raise SchemaError("invalid_skill_input")
        args = arguments.get("args")
        if "args" in arguments and not isinstance(args, str):
            raise SchemaError("invalid_skill_input")
        # The allowlisted payload is hashed in memory only so a call id reused with
        # different arguments conflicts; the arguments themselves are never retained.
        payload = {"skill": name, "args": args}
        invocation = Invocation(
            session_id=envelope.session,
            call_id=call_id,
            timestamp=envelope.timestamp,
            skill_name=name,
            channel="native",
            fingerprint=payload_fingerprint({"channel": "native", **payload}),
            cohort=envelope.cohort,
        )
        events.counts["skill_tool_calls"] += 1
        events.calls.append(
            _Call(
                key=(envelope.session, call_id),
                fingerprint=payload_fingerprint({"tool": _SKILL_TOOL, **payload}),
                invocation=invocation,
            )
        )

    def _read_call(
        self,
        call_id: str,
        block: dict[str, object],
        envelope: _Envelope,
        events: _Events,
    ) -> None:
        arguments = as_object(block.get("input"), "invalid_read_path")
        path = arguments.get("file_path")
        if not isinstance(path, str) or not path:
            raise SchemaError("invalid_read_path")
        partial = False
        for key in ("offset", "limit"):
            if arguments.get(key) is not None:
                as_int(arguments[key], "invalid_read_range")
                partial = True
        attempt = self._direct_attempt(call_id, path, partial, envelope)
        if attempt is None:
            events.counts["non_skill_reads"] += 1
        call_fingerprint = payload_fingerprint(
            {"tool": _READ_TOOL, "path": path, "partial": partial}
        )
        events.calls.append(
            _Call(
                key=(envelope.session, call_id),
                fingerprint=call_fingerprint,
                attempt=attempt,
            )
        )

    def _direct_attempt(
        self, call_id: str, path: str, partial: bool, envelope: _Envelope
    ) -> ReadAttempt | None:
        if _SELECTOR_SUFFIX.search(path) is not None:
            return None
        name = self.inventory.resolve_direct(path)
        if name is None:
            normalized = _normalized_absolute(path)
            if normalized is None or normalized not in self.inventory.ambiguous_paths:
                return None
        return ReadAttempt(
            session_id=envelope.session,
            call_id=call_id,
            timestamp=envelope.timestamp,
            skill_name=name,
            channel="direct",
            body=True,
            partial=partial,
            fingerprint=payload_fingerprint({"channel": "direct", "path": path}),
            cohort=envelope.cohort,
        )

    def _usage(
        self,
        message: dict[str, object],
        message_id: str,
        envelope: _Envelope,
        events: _Events,
    ) -> None:
        if "usage" not in message:
            events.counts["assistant_without_usage"] += 1
            return
        usage = as_object(message["usage"], "invalid_usage")
        values: dict[str, int | float] = {}
        for key in _REQUIRED_USAGE:
            values[key] = as_int(usage.get(key), "invalid_usage")
        for key in _OPTIONAL_USAGE:
            if key not in usage:
                continue
            if usage[key] is None:
                events.counts["usage_null_counters"] += 1
                continue
            values[key] = as_int(usage[key], "invalid_usage")
        if usage.get("cache_creation") is not None:
            tiers = as_object(usage["cache_creation"], "invalid_usage")
            for source_key, label in _CACHE_TIERS:
                if source_key not in tiers:
                    continue
                if tiers[source_key] is None:
                    events.counts["usage_null_counters"] += 1
                    continue
                values[label] = as_int(tiers[source_key], "invalid_usage")
        events.usage.append(
            UsageObservation(
                identity=(envelope.session, message_id),
                timestamp=envelope.timestamp,
                source=SOURCE_USAGE,
                counter_kind="per_message",
                values=values,
            )
        )

    # -- user records ------------------------------------------------------------------

    def _user(self, raw: dict[str, object], events: _Events) -> None:
        envelope = self._envelope(raw, events)
        message = as_object(raw.get("message"), "invalid_message")
        if message.get("role") != "user":
            raise SchemaError("invalid_message_role")
        content = message.get("content")
        if isinstance(content, str):
            events.counts["ignored_records"] += 1
            return
        events.counts["user_messages"] += 1
        for block in as_list(content, "invalid_message_content"):
            item = as_object(block, "invalid_content_block")
            block_type = as_string(item.get("type"), "invalid_content_block")
            if block_type == "tool_result":
                self._tool_result(item, envelope, events)
            elif block_type not in _IGNORED_USER_BLOCKS:
                raise SchemaError("unknown_content_block")

    def _tool_result(
        self, block: dict[str, object], envelope: _Envelope, events: _Events
    ) -> None:
        call_id = as_string(block.get("tool_use_id"), "invalid_tool_result")
        flag = block.get("is_error", False)
        if not isinstance(flag, bool):
            raise SchemaError("invalid_tool_result")
        if "is_error" not in block:
            events.counts["tool_results_without_error_flag"] += 1
        key = (envelope.session, call_id)
        events.results.append(_PendingResult(key, flag, envelope.timestamp))

    # -- attachment records -----------------------------------------------------------

    def _attachment(self, raw: dict[str, object], events: _Events) -> None:
        envelope = self._envelope(raw, events)
        attachment = as_object(raw.get("attachment"), "invalid_attachment")
        kind = as_string(attachment.get("type"), "invalid_attachment")
        if kind == "skill_listing":
            self._listing(raw, attachment, envelope, events)
        elif kind == "invoked_skills":
            # A state snapshot of earlier invocations, not a new invocation.
            for item in as_list(attachment.get("skills"), "invalid_attachment"):
                as_object(item, "invalid_attachment")
            events.counts["invoked_skills_snapshots"] += 1
        elif kind == "dynamic_skill":
            events.counts["dynamic_skill_notices"] += 1
        elif kind == "skill_mention":
            events.counts["skill_mention_notices"] += 1
        elif "skill" in kind.casefold():
            raise SchemaError("unsupported_skill_attachment")
        else:
            events.counts["other_attachments"] += 1

    def _listing(
        self,
        raw: dict[str, object],
        attachment: dict[str, object],
        envelope: _Envelope,
        events: _Events,
    ) -> None:
        uuid = as_string(raw.get("uuid"), "invalid_record_uuid")
        content = attachment.get("content")
        if not isinstance(content, str):
            raise SchemaError("invalid_skill_listing")
        names = _listing_names(attachment.get("names"))
        skill_count = as_int(attachment.get("skillCount"), "invalid_skill_listing")
        is_initial = attachment.get("isInitial")
        if not isinstance(is_initial, bool):
            raise SchemaError("invalid_skill_listing")
        rows, tiled = _measure_listing(content, names)
        counts = events.counts
        if is_initial:
            counts["skill_listings_initial"] += 1
        else:
            counts["skill_listings_dynamic"] += 1
        counts["listing_rows_described"] += sum(row.described for row in rows)
        counts["listing_rows_name_only"] += sum(not row.described for row in rows)
        counts["listing_rows_aliased"] += sum(row.aliased for row in rows)
        counts["listing_rows_truncated"] += sum(row.truncated for row in rows)
        agreed = tiled and skill_count == len(rows) == len(names)
        reasons = (
            ("listing_dynamic_lower_bounds", not is_initial),
            ("listing_name_only_lower_bounds", any(not r.described for r in rows)),
            ("listing_truncation_lower_bounds", any(r.truncated for r in rows)),
            ("listing_count_lower_bounds", not agreed),
        )
        lower_bound = False
        for label, applies in reasons:
            if applies:
                counts[label] += 1
                lower_bound = True
        source = SOURCE_LISTING_INITIAL if is_initial else SOURCE_LISTING_DYNAMIC
        record_id = envelope.origin_uuid if envelope.origin_uuid is not None else uuid
        entry_chars = sum(row.chars for row in rows)
        fingerprint = payload_fingerprint(
            {
                "source": source,
                "timestamp": envelope.timestamp.isoformat(),
                "content": content,
                "names": names,
                "skillCount": skill_count,
                "isInitial": is_initial,
            }
        )
        exposure = Exposure(
            timestamp=envelope.timestamp,
            session_id=envelope.session,
            cohort=envelope.cohort,
            source=source,
            status="lower_bound" if lower_bound else "complete",
            block_chars=len(content),
            wrapper_chars=len(content) - entry_chars,
            entry_chars=entry_chars,
            entries=tuple(EntryCost(row.name, row.chars) for row in rows),
            declared_count=skill_count,
            listed_names=len(names),
            record_id=record_id,
            fingerprint=fingerprint,
        )
        events.exposures.append(((envelope.session, source, record_id), exposure))

    # -- commit / finalize -----------------------------------------------------------

    def _commit(self, events: _Events) -> None:
        parsed = self.parsed
        parsed.counts.update(events.counts)
        for session, cohort in events.sessions:
            self.session_cohorts.setdefault(session, set()).add(cohort)
        for key, exposure in events.exposures:
            prior = self.exposures.get(key)
            if prior is None:
                self.exposures[key] = exposure
            elif prior == replace(exposure, cohort=prior.cohort):
                parsed.counts["duplicate_records"] += 1
                if prior.cohort != exposure.cohort:
                    self.exposures[key] = replace(prior, cohort="unknown")
            else:
                self._issue("conflicting_duplicate_record")
        for call in events.calls:
            known = self.calls.get(call.key)
            if known is None:
                self.calls[call.key] = call
            elif known.fingerprint == call.fingerprint:
                parsed.counts["duplicate_calls"] += 1
                self.calls[call.key] = _merged_call(known, call)
            else:
                self._issue("conflicting_duplicate_call")
        for result in events.results:
            prior_result = self.results.get(result.key)
            if prior_result is None:
                self.results[result.key] = result
            elif prior_result.is_error == result.is_error:
                parsed.counts["duplicate_results"] += 1
                if result.timestamp < prior_result.timestamp:
                    self.results[result.key] = result
            else:
                self.result_conflicts.add(result.key)
        for observation in events.usage:
            usage_key = (
                observation.identity,
                observation.timestamp.isoformat(),
                tuple(sorted(observation.values.items())),
            )
            if usage_key in self.usage_seen:
                parsed.counts["duplicate_usage_chunks"] += 1
                continue
            self.usage_seen.add(usage_key)
            parsed.usage.append(observation)

    def finish(self) -> ParsedFile:
        parsed = self.parsed
        if not parsed.versions and parsed.schema_supported:
            self._issue("unvalidated_client_identity")
        for key, result in self.results.items():
            call = self.calls.get(key)
            if call is None or call.attempt is None:
                parsed.counts["other_results"] += 1
            elif key in self.result_conflicts:
                self._issue("conflicting_duplicate_result")
            else:
                parsed.results.append(
                    ReadResult(
                        session_id=key[0],
                        call_id=key[1],
                        success=not result.is_error,
                        timestamp=result.timestamp,
                    )
                )
        parsed.exposures.extend(self.exposures.values())
        for call in self.calls.values():
            if call.attempt is not None:
                parsed.attempts.append(call.attempt)
            if call.invocation is not None:
                parsed.invocations.append(call.invocation)
        for session, cohorts in self.session_cohorts.items():
            parsed.sessions[session] = _session_cohort(cohorts)
        parsed.coverage.update(self._coverage())
        return parsed

    def _coverage(self) -> dict[str, str]:
        parsed = self.parsed
        counts = parsed.counts
        statuses = {exposure.status for exposure in parsed.exposures}
        if not statuses or statuses == {"unavailable"}:
            exposure = "unavailable"
        elif statuses == {"complete"} and not counts["dynamic_skill_notices"]:
            exposure = "complete"
        else:
            # Lower-bound listings and unmeasured dynamic-skill notices leave a gap.
            exposure = "partial"
        # Skill-body state and mentions are not proven Skill tool calls, so Skill
        # tool-call counts may not cover every load in a file that carries them.
        mentions = counts["invoked_skills_snapshots"] + counts["skill_mention_notices"]
        return {
            "exposure": exposure,
            "native_read": "available",
            "slash_invocation": "unavailable",
            "native_invocation": "partial" if mentions else "available",
            "usage": "available" if parsed.usage else "unavailable",
        }


def parse_file(
    records: Iterable[dict[str, object]],
    *,
    inventory: Inventory,
    file_key: str,
    cohort_hint: Cohort,
) -> ParsedFile:
    """Reduce one Claude Code transcript to allowlisted metadata; failures are anonymous."""
    parser = _Parser(inventory, file_key, cohort_hint)
    for record in records:
        parser.feed(record)
    return parser.finish()
