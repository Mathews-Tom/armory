"""Allowlisted, in-memory metadata; never serialize these objects wholesale."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

Cohort = Literal["main", "sub", "nested", "unknown"]
Harness = Literal["omp", "claude", "codex"]
Availability = Literal["complete", "lower_bound", "unavailable"]


class SchemaError(ValueError):
    """A fixed anonymous diagnostic, never an input value or exception message."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def as_object(value: object, code: str = "invalid_object") -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise SchemaError(code)
    return cast(dict[str, object], value)


def as_list(value: object, code: str = "invalid_list") -> list[object]:
    if not isinstance(value, list):
        raise SchemaError(code)
    return cast(list[object], value)


def as_string(value: object, code: str = "invalid_string") -> str:
    if not isinstance(value, str) or not value:
        raise SchemaError(code)
    return value


def as_int(value: object, code: str = "invalid_counter") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SchemaError(code)
    return value


def as_number(value: object, code: str = "invalid_number") -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or value < 0
        or not math.isfinite(value)
    ):
        raise SchemaError(code)
    return value


def utc_time(value: object, code: str = "invalid_timestamp") -> datetime:
    raw = as_string(value, code)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise SchemaError(code) from None
    if parsed.tzinfo is None:
        raise SchemaError(code)
    return parsed.astimezone(UTC)


def epoch_time(value: object) -> datetime:
    millis = as_int(value, "invalid_epoch_milliseconds")
    if millis < 1_000_000_000_000:
        raise SchemaError("invalid_epoch_milliseconds")
    try:
        return datetime.fromtimestamp(millis / 1000, UTC)
    except (ValueError, OverflowError, OSError):
        raise SchemaError("invalid_epoch_milliseconds") from None


def payload_fingerprint(value: object) -> str:
    """Ephemeral conflict detection only; this digest must never be exported."""
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class InstalledSkill:
    name: str
    description: str
    path: Path
    aliases: tuple[Path, ...]
    ownership: str
    installed_at: datetime | None = None
    headings: tuple[str, ...] = ()


@dataclass
class Inventory:
    entries: list[InstalledSkill] = field(default_factory=list)
    direct_paths: dict[str, str] = field(default_factory=dict)
    ambiguous_paths: set[str] = field(default_factory=set)
    approved_roots: tuple[Path, ...] = ()
    reference_names: set[str] = field(default_factory=set)
    coverage: Counter[str] = field(default_factory=Counter)
    integrity: str = ""

    def resolve_direct(self, path: str) -> str | None:
        """Match only cataloged aliases; never stat or open a log-named path."""
        value = re.sub(r":(?:\d[\d,:+\-]*|raw|img)$", "", path)
        if value.startswith("~/"):
            value = str(Path.home()) + value[1:]
        if not os.path.isabs(value):
            return None
        value = os.path.normpath(value)
        if value in self.ambiguous_paths:
            return None
        return self.direct_paths.get(value)


@dataclass(frozen=True)
class EntryCost:
    name: str
    chars: int


@dataclass(frozen=True)
class Exposure:
    timestamp: datetime
    session_id: str
    cohort: Cohort
    source: str
    status: Availability
    block_chars: int | None
    wrapper_chars: int | None
    entry_chars: int | None
    entries: tuple[EntryCost, ...] = ()
    prompt_chars: int | None = None
    virtual_block_chars: int | None = None
    separator_chars: int = 0
    block_separator_chars: int = 0
    declared_count: int | None = None
    listed_names: int | None = None
    record_id: str | None = None
    fingerprint: str | None = None


@dataclass(frozen=True)
class ReadAttempt:
    session_id: str
    call_id: str
    timestamp: datetime
    skill_name: str | None
    channel: Literal["uri", "direct"]
    body: bool
    partial: bool
    fingerprint: str
    cohort: Cohort


@dataclass(frozen=True)
class ReadResult:
    session_id: str
    call_id: str
    success: bool
    timestamp: datetime | None = None


@dataclass(frozen=True)
class Invocation:
    session_id: str
    call_id: str
    timestamp: datetime
    skill_name: str
    channel: Literal["slash", "native"]
    fingerprint: str
    cohort: Cohort


@dataclass(frozen=True)
class UsageObservation:
    identity: tuple[str, ...]
    timestamp: datetime
    source: str
    counter_kind: Literal["per_message", "last", "cumulative", "context"]
    values: dict[str, int | float]


@dataclass
class ParsedFile:
    file_key: str
    cohort_hint: Cohort
    sessions: dict[str, Cohort] = field(default_factory=dict)
    exposures: list[Exposure] = field(default_factory=list)
    attempts: list[ReadAttempt] = field(default_factory=list)
    results: list[ReadResult] = field(default_factory=list)
    invocations: list[Invocation] = field(default_factory=list)
    usage: list[UsageObservation] = field(default_factory=list)
    reference_names: set[str] = field(default_factory=set)
    issues: Counter[str] = field(default_factory=Counter)
    counts: Counter[str] = field(default_factory=Counter)
    coverage: dict[str, str] = field(default_factory=dict)
    versions: set[str] = field(default_factory=set)
    schema_supported: bool = True
