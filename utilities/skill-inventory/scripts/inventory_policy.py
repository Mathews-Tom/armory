"""Deterministic recommendation policy, tree states and the private proposal contract.

``recommend`` turns an actual measurement report, its installed-name-only private
evidence rows and the approved private policy inputs (pins, per-item attestations,
instruction references, the managed source tree) into two documents:

* a **public aggregate report**: counts, thresholds and fixed codes only; it never
  carries a skill name, path, description, tree hash or attestation, and
* a **private proposal**: installed-file identities, tree hashes and normalized
  evidence for the owner. It is written by the caller to an explicit private path.

Nothing here mutates a skill, a log or a configuration file. A missing, unknown or
incomplete input yields ``status: incomplete`` with every skill kept, never an empty
complete protection set. Recommendation never authorizes mutation: later human
approval binds the proposal digest and per-item tree digests.

Every diagnostic and reason is a fixed literal code. Log-derived names, paths and
identifiers are never read, stored or exported here; the only log-derived values are
the counts and dates the measurement already reduced to installed-name rows.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import os
import re
import stat
import unicodedata
from collections import Counter
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import cast

from inventory_catalog import BLOCKING_COVERAGE, MAX_SKILL_BYTES, reference_names
from inventory_io import (
    canonical_json,
    is_hex_digest,
    load_binding,
    open_directory,
    open_regular,
    read_private_json,
)
from inventory_types import (
    Harness,
    InstalledSkill,
    Inventory,
    SchemaError,
    as_int,
    as_list,
    as_number,
    as_object,
    as_string,
    utc_time,
)

SCHEMA_VERSION = 1
PROPOSAL_KIND = "skill-inventory-proposal"
REPORT_KIND = "skill-inventory-recommendation-report"
POLICY_VERSION = "skill-inventory-policy-v1"

MIN_AGE_DAYS = 90
MIN_SNAPSHOTS = 20
MIN_MAIN_GROUPS = 5
RARE_MAX_USES = 2
RARE_MIN_IDLE_DAYS = 60
RARE_GAP_MULTIPLE = 2
MERGE_THRESHOLD = Fraction(7, 10)
WEIGHT_NAME = Fraction(2, 5)
WEIGHT_DESCRIPTION = Fraction(2, 5)
WEIGHT_HEADINGS = Fraction(1, 5)

APPROVAL_POLICY: dict[str, int] = {
    "max_batch": 10,
    "dwell_days": 7,
    "dwell_sessions": 20,
    "quarantine_days": 21,
    "cohort_deadline_days": 21,
}

# Rule v1 from the plan: casefolded whole tokens in names, descriptions and headings.
HIGH_RISK_TOKENS = frozenset(
    {
        "auth",
        "authentication",
        "approval",
        "security",
        "secret",
        "secrets",
        "privacy",
        "permission",
        "permissions",
        "irreversible",
        "payment",
        "payments",
        "migration",
        "release",
        "publish",
        "restore",
        "benchmark",
        "provenance",
    }
)
# Frozen with the policy digest. "not" and the other negations are deliberately absent.
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "then",
        "this",
        "to",
        "use",
        "used",
        "using",
        "when",
        "where",
        "which",
        "will",
        "with",
        "you",
        "your",
        "skill",
        "skills",
    }
)
NEGATION_TOKENS = frozenset(
    {
        "not",
        "never",
        "no",
        "without",
        "except",
        "excluding",
        "unless",
        "instead",
        "avoid",
        "don",
        "doesn",
        "isn",
        "aren",
        "cannot",
    }
)

MAX_TREE_NODES = 50_000
MAX_TREE_DEPTH = 32
MAX_FILE_BYTES = 64 << 20
MAX_TREE_BYTES = 512 << 20
MAX_PATH_CHARS = 4096
MAX_NAME_BYTES = 255

_HARNESSES = ("omp", "claude", "codex")
_OWNERSHIPS = frozenset({"managed", "user", "protected", "unknown"})
_CLASSIFICATIONS = frozenset({"keep", "archive_candidate", "merge_candidate"})
_BOUNDARY_CLAUSE = re.compile(r"[.;!?\n]+")
_TOKEN = re.compile(r"[^\W_]+")
_UNSAFE_MODE_BITS = 0o7022
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_CHUNK = 1 << 20

REASON_CODES = frozenset(
    {
        "proposal_incomplete",
        "harness_not_mutable",
        "ownership_user",
        "ownership_protected",
        "ownership_unknown",
        "alias_or_link",
        "ambiguous_name",
        "pinned",
        "high_risk_term",
        "referenced_by_instruction",
        "referenced_by_skill_body",
        "referenced_by_observed_autoload",
        "observed_dependencies_unknown",
        "directory_name_mismatch",
        "source_tree_unavailable",
        "attestation_missing",
        "attestation_digest_mismatch",
        "not_harness_generated",
        "user_authorship_not_excluded",
        "description_only_unreviewed",
        "coverage_still_needed",
        "periodic_or_incident_workflow",
        "lineage_after_required_start",
        "age_unknown",
        "age_below_minimum",
        "window_below_minimum",
        "opportunities_unknown",
        "grouping_incomplete",
        "opportunities_below_minimum",
        "use_channel_unavailable",
        "use_above_rare_threshold",
        "use_dates_missing",
        "recent_use",
        "gap_unknown",
        "window_below_twice_gap",
        "never_read_in_window",
        "rare_read_in_window",
        "similar_installed_skill",
    }
)
COUNTER_EVIDENCE_CODES = frozenset(
    {
        "description_only_influence_unmeasured",
        "main_session_presence_unmeasured",
        "read_frequency_is_not_utility",
        "authored_creation_unknown",
        "historical_identity_owner_asserted",
        "observed_use_in_window",
        "similar_installed_skill_pair",
    }
)
_POSITIVE_REASONS = frozenset(
    {"never_read_in_window", "rare_read_in_window", "similar_installed_skill"}
)

_EVIDENCE_TEXT = ("historical_provenance", "installation_date_source")
_EVIDENCE_DATES = (
    "installation_date",
    "authored_creation_date",
    "first_observed_inventory_date",
    "first_read_date",
    "last_read_date",
    "first_invocation_date",
    "last_invocation_date",
    "window_first_use_date",
    "window_last_use_date",
)
_EVIDENCE_COUNTS = (
    "latest_observed_entry_chars",
    "observed_read_attempts",
    "observed_invocation_attempts",
    "window_read_attempts",
    "window_invocation_attempts",
    "inventory_present_subagent_snapshots",
    "inventory_present_main_task_groups",
)
_EVIDENCE_KEYS = frozenset(
    {
        "name",
        "ownership",
        *_EVIDENCE_TEXT,
        *_EVIDENCE_DATES,
        *_EVIDENCE_COUNTS,
        "largest_observed_inter_use_gap_days",
        "inventory_presence_grouping_complete",
        "log_observed_dependency",
    }
)
_PROPOSAL_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "harness",
        "as_of_utc",
        "window_days",
        "status",
        "snapshot_digest",
        "inventory_digest",
        "policy_digest",
        "measurement_scope",
        "managed_root",
        "managed_tree",
        "source_root_digest",
        "policy_inputs",
        "skills",
        "merge_pairs",
        "pin_names",
        "reference_names",
        "inventory_observations_by_utc_day",
        "approval_policy",
        "proposal_digest",
    }
)
_SKILL_KEYS = frozenset(
    {
        "name",
        "classification",
        "reasons",
        "counter_evidence",
        "tree_digest",
        "generated_only_attested",
        "never_user_authored_attested",
        "historical_lineage_attested",
        "description_only_reviewed",
        "coverage_still_needed",
        "periodic_or_incident_workflow",
        "eligible",
        "evidence",
    }
)
_PAIR_KEYS = frozenset(
    {
        "a",
        "b",
        "score",
        "features",
        "matched",
        "differences",
        "a_protected",
        "b_protected",
        "actionable",
        "review",
    }
)
_FEATURE_NAMES = ("name", "description", "headings")
_DIFFERENCE_NAMES = (
    "description_only_a",
    "description_only_b",
    "negative_boundaries_only_a",
    "negative_boundaries_only_b",
)
_TREE_KEYS = frozenset({"root_mode", "directories", "files", "digest"})
_ATTESTATION_KEYS = frozenset(
    {
        "name",
        "tree_digest",
        "harness_generated",
        "never_user_authored",
        "historical_identity_attested_since",
        "description_only_reviewed",
        "coverage_still_needed",
        "periodic_or_incident_workflow",
    }
)


# --------------------------------------------------------------------------- digests


def canonical_digest(value: object) -> str:
    """SHA-256 of compact, sorted-key, ASCII-escaped JSON with no NaN or infinity."""
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError):
        raise SchemaError("digest_input_invalid") from None
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _is_one(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 1


def _strict_bool(value: object, code: str) -> bool:
    if not isinstance(value, bool):
        raise SchemaError(code)
    return value


def _hex_or_none(value: object, code: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not is_hex_digest(value):
        raise SchemaError(code)
    return value


def _sorted_unique_strings(value: object, code: str) -> list[str]:
    items = [as_string(item, code) for item in as_list(value, code)]
    if any(left >= right for left, right in itertools.pairwise(items)):
        raise SchemaError(code)
    return items


# --------------------------------------------------------------------------- tree state


@dataclass(frozen=True)
class TreeState:
    """Exact content state of a directory tree below one root (the root is not listed)."""

    root_mode: int
    directories: tuple[tuple[str, int], ...]
    files: tuple[tuple[str, str, int, int], ...]
    digest: str


def _tree_body(
    root_mode: int,
    directories: Sequence[tuple[str, int]],
    files: Sequence[tuple[str, str, int, int]],
) -> dict[str, object]:
    return {
        "root_mode": root_mode,
        "directories": [[path, mode] for path, mode in directories],
        "files": [[path, sha, mode, size] for path, sha, mode, size in files],
    }


def _seal_tree(
    root_mode: int,
    directories: Sequence[tuple[str, int]],
    files: Sequence[tuple[str, str, int, int]],
) -> TreeState:
    digest = canonical_digest(_tree_body(root_mode, directories, files))
    return TreeState(root_mode, tuple(directories), tuple(files), digest)


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_CHARS:
        raise SchemaError("tree_path_invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise SchemaError("tree_path_invalid") from None
    for part in value.split("/"):
        if (
            part in ("", ".", "..")
            or "\x00" in part
            or len(part.encode()) > MAX_NAME_BYTES
        ):
            raise SchemaError("tree_path_invalid")
    return value


def _component(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\x00" in value
        or value in (".", "..")
        or len(value) > MAX_PATH_CHARS
    ):
        raise SchemaError("tree_name_invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise SchemaError("tree_name_invalid") from None
    if len(encoded) > MAX_NAME_BYTES:
        raise SchemaError("tree_name_invalid")
    return value


def _mode(value: object) -> int:
    mode = as_int(value, "tree_invalid")
    if mode > 0o7777:
        raise SchemaError("tree_invalid")
    return mode


def _parent(path: str) -> str | None:
    head, separator, _ = path.rpartition("/")
    return head if separator else None


def _check_shape(
    directories: Sequence[tuple[str, int]],
    files: Sequence[tuple[str, str, int, int]],
) -> None:
    dir_paths = [path for path, _ in directories]
    file_paths = [path for path, _, _, _ in files]
    if len(dir_paths) + len(file_paths) > MAX_TREE_NODES:
        raise SchemaError("tree_limit")
    for paths in (dir_paths, file_paths):
        if any(a >= b for a, b in itertools.pairwise(paths)):
            raise SchemaError("tree_invalid")
    known = set(dir_paths)
    if known & set(file_paths):
        raise SchemaError("tree_invalid")
    for path in (*dir_paths, *file_paths):
        parent = _parent(path)
        if parent is not None and parent not in known:
            raise SchemaError("tree_invalid")


def _checked(state: TreeState) -> TreeState:
    """Recompute the digest so a hand-built or altered state cannot be trusted."""
    if not isinstance(state, TreeState):
        raise SchemaError("tree_invalid")
    _check_shape(state.directories, state.files)
    expected = canonical_digest(
        _tree_body(state.root_mode, state.directories, state.files)
    )
    if not is_hex_digest(state.digest) or not hmac.compare_digest(
        expected, state.digest
    ):
        raise SchemaError("tree_digest_mismatch")
    return state


def tree_document(state: TreeState) -> dict[str, object]:
    checked = _checked(state)
    return {
        **_tree_body(checked.root_mode, checked.directories, checked.files),
        "digest": checked.digest,
    }


def tree_from_document(value: object) -> TreeState:
    document = as_object(value, "tree_invalid")
    if set(document) != _TREE_KEYS:
        raise SchemaError("tree_invalid")
    directories: list[tuple[str, int]] = []
    for row in as_list(document["directories"], "tree_invalid"):
        item = as_list(row, "tree_invalid")
        if len(item) != 2:
            raise SchemaError("tree_invalid")
        directories.append((_relative_path(item[0]), _mode(item[1])))
    files: list[tuple[str, str, int, int]] = []
    for row in as_list(document["files"], "tree_invalid"):
        item = as_list(row, "tree_invalid")
        if len(item) != 4 or not isinstance(item[1], str) or not is_hex_digest(item[1]):
            raise SchemaError("tree_invalid")
        files.append(
            (
                _relative_path(item[0]),
                item[1],
                _mode(item[2]),
                as_int(item[3], "tree_invalid"),
            )
        )
    _check_shape(directories, files)
    state = _seal_tree(_mode(document["root_mode"]), directories, files)
    declared = document["digest"]
    if not isinstance(declared, str) or not hmac.compare_digest(
        _hex_or_none(declared, "tree_invalid") or "", state.digest
    ):
        raise SchemaError("tree_digest_mismatch")
    return state


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    size = info.st_size if stat.S_ISREG(info.st_mode) else 0
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _check_entry(info: os.stat_result) -> None:
    """Sources must belong to the effective user and not be group/world writable."""
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & _UNSAFE_MODE_BITS:
        raise SchemaError("tree_entry_unsafe")


class _Scan:
    def __init__(self) -> None:
        self.directories: list[tuple[str, int]] = []
        self.files: list[tuple[str, str, int, int]] = []
        self.nodes = 0
        self.total_bytes = 0

    def walk(self, fd: int, before: os.stat_result, prefix: str, depth: int) -> None:
        if depth > MAX_TREE_DEPTH:
            raise SchemaError("tree_limit")
        names = sorted(os.listdir(fd))
        for name in names:
            self.nodes += 1
            if self.nodes > MAX_TREE_NODES:
                raise SchemaError("tree_limit")
            relative = _relative_path(prefix + name)
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                raise SchemaError("tree_unstable") from None
            _check_entry(info)
            if stat.S_ISDIR(info.st_mode):
                self._directory(fd, name, info, relative, depth)
            elif stat.S_ISREG(info.st_mode):
                self._file(fd, name, info, relative)
            else:
                raise SchemaError("tree_entry_unsafe")
        if _stamp(os.fstat(fd)) != _stamp(before) or sorted(os.listdir(fd)) != names:
            raise SchemaError("tree_unstable")

    def _directory(
        self, fd: int, name: str, info: os.stat_result, relative: str, depth: int
    ) -> None:
        child = os.open(name, _DIR_FLAGS, dir_fd=fd)
        try:
            opened = os.fstat(child)
            if _stamp(opened) != _stamp(info):
                raise SchemaError("tree_unstable")
            self.directories.append((relative, stat.S_IMODE(opened.st_mode)))
            self.walk(child, opened, relative + "/", depth + 1)
        finally:
            os.close(child)

    def _file(self, fd: int, name: str, info: os.stat_result, relative: str) -> None:
        if info.st_nlink != 1:
            raise SchemaError("tree_entry_unsafe")
        if info.st_size > MAX_FILE_BYTES:
            raise SchemaError("tree_limit")
        child = os.open(name, _FILE_FLAGS, dir_fd=fd)
        try:
            before = os.fstat(child)
            if _stamp(before) != _stamp(info):
                raise SchemaError("tree_unstable")
            hasher = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(child, _CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise SchemaError("tree_limit")
                hasher.update(chunk)
            after = os.fstat(child)
        finally:
            os.close(child)
        if _stamp(after) != _stamp(before) or size != before.st_size:
            raise SchemaError("tree_unstable")
        self.total_bytes += size
        if self.total_bytes > MAX_TREE_BYTES:
            raise SchemaError("tree_limit")
        self.files.append(
            (relative, hasher.hexdigest(), stat.S_IMODE(before.st_mode), size)
        )


def scan_tree_fd(fd: int) -> TreeState:
    """Scan every entry below an open directory descriptor; the caller keeps ``fd``.

    Traversal is descriptor-relative with ``O_NOFOLLOW``. Links, hardlinked or special
    files, entries not owned by the effective user, group/world-writable or
    setuid/setgid/sticky modes, over-limit trees, and any directory or file whose
    stamp or listing changes while being read all fail with a fixed code.
    """
    scan = _Scan()
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            raise SchemaError("tree_entry_unsafe")
        _check_entry(info)
        scan.walk(fd, info, "", 0)
    except (OSError, UnicodeError):
        raise SchemaError("tree_unreadable") from None
    return _seal_tree(
        stat.S_IMODE(info.st_mode), sorted(scan.directories), sorted(scan.files)
    )


def scan_tree(path: Path) -> TreeState:
    try:
        fd = open_directory(path)
    except OSError:
        raise SchemaError("tree_unreadable") from None
    try:
        return scan_tree_fd(fd)
    finally:
        os.close(fd)


def _subtree(state: TreeState, name: str) -> TreeState:
    child = _component(name)
    modes = dict(state.directories)
    if child not in modes:
        raise SchemaError("tree_entry_missing")
    prefix = child + "/"
    return _seal_tree(
        modes[child],
        [
            (path[len(prefix) :], mode)
            for path, mode in state.directories
            if path.startswith(prefix)
        ],
        [
            (path[len(prefix) :], sha, mode, size)
            for path, sha, mode, size in state.files
            if path.startswith(prefix)
        ],
    )


def subtree_state(state: TreeState, name: str) -> TreeState:
    """The state of one top-level child directory, derived without reading files."""
    return _subtree(_checked(state), name)


def without_children(state: TreeState, names: AbstractSet[str]) -> TreeState:
    """The state after removing top-level children, derived without reading files."""
    checked = _checked(state)
    children = {_component(name) for name in names}
    top_level = {path for path, _ in checked.directories if "/" not in path} | {
        path for path, _, _, _ in checked.files if "/" not in path
    }
    if not children <= top_level:
        raise SchemaError("tree_entry_missing")
    prefixes = tuple(child + "/" for child in children)

    def kept(path: str) -> bool:
        return path not in children and not path.startswith(prefixes)

    return _seal_tree(
        checked.root_mode,
        [(path, mode) for path, mode in checked.directories if kept(path)],
        [
            (path, sha, mode, size)
            for path, sha, mode, size in checked.files
            if kept(path)
        ],
    )


# --------------------------------------------------------------------------- evidence


def _optional_date_text(value: object) -> str | None:
    if value is None:
        return None
    utc_time(value, "evidence_invalid")
    return cast(str, value)


def normalize_evidence(row: dict[str, object]) -> dict[str, object]:
    """Validate one installed-name private evidence row into the fixed proposal shape.

    ``name`` and ``ownership`` are required; every other field is optional and becomes
    ``None`` when absent, which the policy treats as unknown (keep), never as zero.
    """
    source = as_object(row, "evidence_invalid")
    name = as_string(source.get("name"), "evidence_invalid")
    ownership = source.get("ownership")
    if not isinstance(ownership, str) or ownership not in _OWNERSHIPS:
        raise SchemaError("evidence_invalid")
    evidence: dict[str, object] = {"name": name, "ownership": ownership}
    for key in _EVIDENCE_TEXT:
        text = source.get(key)
        if text is not None and not isinstance(text, str):
            raise SchemaError("evidence_invalid")
        evidence[key] = text
    for key in _EVIDENCE_DATES:
        evidence[key] = _optional_date_text(source.get(key))
    for key in _EVIDENCE_COUNTS:
        count = source.get(key)
        evidence[key] = None if count is None else as_int(count, "evidence_invalid")
    gap = source.get("largest_observed_inter_use_gap_days")
    evidence["largest_observed_inter_use_gap_days"] = (
        None if gap is None else as_number(gap, "evidence_invalid")
    )
    grouping = source.get("inventory_presence_grouping_complete")
    if grouping is not None and not isinstance(grouping, bool):
        raise SchemaError("evidence_invalid")
    evidence["inventory_presence_grouping_complete"] = grouping
    dependency = source.get("log_observed_dependency")
    if dependency is not None and not isinstance(dependency, bool):
        raise SchemaError("evidence_invalid")
    evidence["log_observed_dependency"] = dependency
    return evidence


def _validate_evidence(value: object, name: str) -> dict[str, object]:
    evidence = as_object(value, "proposal_invalid")
    if set(evidence) != _EVIDENCE_KEYS or evidence["name"] != name:
        raise SchemaError("proposal_invalid")
    try:
        normalized = normalize_evidence(evidence)
    except SchemaError:
        raise SchemaError("proposal_invalid") from None
    if normalized != evidence:
        raise SchemaError("proposal_invalid")
    return evidence


def _count(evidence: dict[str, object], key: str) -> int | None:
    value = evidence[key]
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _moment(evidence: dict[str, object], key: str) -> datetime | None:
    value = evidence[key]
    return None if value is None else utc_time(value, "evidence_invalid")


# --------------------------------------------------------------------------- policy constants


def _policy_constants() -> dict[str, object]:
    return {
        "normalization": "NFC+casefold",
        "minimum_age_days": MIN_AGE_DAYS,
        "minimum_snapshots": MIN_SNAPSHOTS,
        "minimum_main_groups": MIN_MAIN_GROUPS,
        "rare_max_uses": RARE_MAX_USES,
        "rare_min_idle_days": RARE_MIN_IDLE_DAYS,
        "rare_gap_multiple": RARE_GAP_MULTIPLE,
        "merge_threshold": f"{MERGE_THRESHOLD.numerator}/{MERGE_THRESHOLD.denominator}",
        "weights": {
            "name": f"{WEIGHT_NAME.numerator}/{WEIGHT_NAME.denominator}",
            "description": f"{WEIGHT_DESCRIPTION.numerator}/{WEIGHT_DESCRIPTION.denominator}",
            "headings": f"{WEIGHT_HEADINGS.numerator}/{WEIGHT_HEADINGS.denominator}",
        },
        "high_risk_tokens": sorted(HIGH_RISK_TOKENS),
        "stopwords": sorted(STOPWORDS),
        "negation_tokens": sorted(NEGATION_TOKENS),
        "approval": dict(APPROVAL_POLICY),
    }


def policy_digest(
    as_of_utc: str, window_days: int, policy_inputs: dict[str, object]
) -> str:
    """Digest binding the frozen policy constants, the cutoff and the policy inputs."""
    return canonical_digest(
        {
            "version": POLICY_VERSION,
            "constants": _policy_constants(),
            "as_of_utc": as_of_utc,
            "window_days": window_days,
            "policy_inputs": policy_inputs,
        }
    )


def seal_proposal(body: dict[str, object]) -> dict[str, object]:
    """Return a copy of ``body`` whose ``proposal_digest`` covers every other field."""
    unsealed = {key: value for key, value in body.items() if key != "proposal_digest"}
    return {**unsealed, "proposal_digest": canonical_digest(unsealed)}


# --------------------------------------------------------------------------- proposal validation


def _validate_skill(
    value: object, tree: TreeState | None, complete: bool
) -> dict[str, object]:
    skill = as_object(value, "proposal_invalid")
    if set(skill) != _SKILL_KEYS:
        raise SchemaError("proposal_invalid")
    name = as_string(skill["name"], "proposal_invalid")
    classification = skill["classification"]
    if not isinstance(classification, str) or classification not in _CLASSIFICATIONS:
        raise SchemaError("proposal_invalid")
    reasons = _sorted_unique_strings(skill["reasons"], "proposal_invalid")
    counter = _sorted_unique_strings(skill["counter_evidence"], "proposal_invalid")
    if (
        not reasons
        or not set(reasons) <= REASON_CODES
        or not set(counter) <= COUNTER_EVIDENCE_CODES
    ):
        raise SchemaError("proposal_invalid")
    tree_digest = _hex_or_none(skill["tree_digest"], "proposal_invalid")
    flags = {
        key: _strict_bool(skill[key], "proposal_invalid")
        for key in (
            "generated_only_attested",
            "never_user_authored_attested",
            "historical_lineage_attested",
            "description_only_reviewed",
            "eligible",
        )
    }
    for key in ("coverage_still_needed", "periodic_or_incident_workflow"):
        if skill[key] is not None:
            _strict_bool(skill[key], "proposal_invalid")
    evidence = _validate_evidence(skill["evidence"], name)
    if classification == "archive_candidate":
        if reasons not in (["never_read_in_window"], ["rare_read_in_window"]):
            raise SchemaError("proposal_invalid")
    elif classification == "merge_candidate":
        if reasons != ["similar_installed_skill"]:
            raise SchemaError("proposal_invalid")
    elif _POSITIVE_REASONS & set(reasons):
        raise SchemaError("proposal_invalid")
    if flags["eligible"] != (classification == "archive_candidate"):
        raise SchemaError("proposal_invalid")
    if flags["eligible"]:
        if (
            not complete
            or tree is None
            or tree_digest is None
            or evidence["ownership"] != "managed"
            or not all(
                flags[key]
                for key in (
                    "generated_only_attested",
                    "never_user_authored_attested",
                    "historical_lineage_attested",
                    "description_only_reviewed",
                )
            )
            or skill["coverage_still_needed"] is not False
            or skill["periodic_or_incident_workflow"] is not False
        ):
            raise SchemaError("proposal_invalid")
        try:
            current = _subtree(tree, name).digest
        except SchemaError:
            raise SchemaError("proposal_tree_mismatch") from None
        if current != tree_digest:
            raise SchemaError("proposal_tree_mismatch")
    if not complete and classification != "keep":
        raise SchemaError("proposal_invalid")
    return skill


def _validate_name_lists(value: object, names: Sequence[str] | None = None) -> None:
    items = _sorted_unique_strings(value, "proposal_invalid")
    if names is not None and not set(items) <= set(names):
        raise SchemaError("proposal_invalid")


def _validate_pair(value: object, names: set[str], complete: bool) -> dict[str, object]:
    pair = as_object(value, "proposal_invalid")
    if set(pair) != _PAIR_KEYS:
        raise SchemaError("proposal_invalid")
    left = as_string(pair["a"], "proposal_invalid")
    right = as_string(pair["b"], "proposal_invalid")
    if left not in names or right not in names or pair["review"] != "human_required":
        raise SchemaError("proposal_invalid")
    score = as_number(pair["score"], "proposal_invalid")
    if not float(MERGE_THRESHOLD) <= score <= 1:
        raise SchemaError("proposal_invalid")
    features = as_object(pair["features"], "proposal_invalid")
    if set(features) != set(_FEATURE_NAMES) or any(
        as_number(features[key], "proposal_invalid") > 1 for key in _FEATURE_NAMES
    ):
        raise SchemaError("proposal_invalid")
    matched = as_object(pair["matched"], "proposal_invalid")
    if set(matched) != set(_FEATURE_NAMES):
        raise SchemaError("proposal_invalid")
    for key in _FEATURE_NAMES:
        _validate_name_lists(matched[key])
    differences = as_object(pair["differences"], "proposal_invalid")
    if set(differences) != set(_DIFFERENCE_NAMES):
        raise SchemaError("proposal_invalid")
    for key in _DIFFERENCE_NAMES:
        _validate_name_lists(differences[key])
    protected_a = _strict_bool(pair["a_protected"], "proposal_invalid")
    protected_b = _strict_bool(pair["b_protected"], "proposal_invalid")
    actionable = _strict_bool(pair["actionable"], "proposal_invalid")
    if actionable != (complete and not protected_a and not protected_b):
        raise SchemaError("proposal_invalid")
    return pair


def _validate_days(value: object, as_of: datetime, window_days: int) -> None:
    days = as_object(value, "proposal_invalid")
    first = (as_of - timedelta(days=window_days)).date()
    for key, count in days.items():
        try:
            moment = date.fromisoformat(key)
        except ValueError:
            raise SchemaError("proposal_invalid") from None
        if moment.isoformat() != key or not first <= moment <= as_of.date():
            raise SchemaError("proposal_invalid")
        as_int(count, "proposal_invalid")


def validate_proposal(value: object) -> dict[str, object]:
    """Validate schema, field shapes, tree/digest consistency and the proposal digest.

    The same dict is returned. A proposal that is incomplete may only keep; a complete
    one must have complete/valid/closed measurement and every policy-input digest.
    ``eligible`` is true exactly for archive candidates, whose attestation flags,
    managed-root child directory and tree digest are re-checked against the embedded
    whole managed-root tree.
    """
    proposal = as_object(value, "proposal_invalid")
    if set(proposal) != _PROPOSAL_KEYS:
        raise SchemaError("proposal_invalid")
    if not _is_one(proposal["schema_version"]) or proposal["kind"] != PROPOSAL_KIND:
        raise SchemaError("proposal_unsupported_schema")
    harness = proposal["harness"]
    if not isinstance(harness, str) or harness not in _HARNESSES:
        raise SchemaError("proposal_invalid")
    as_of_text = as_string(proposal["as_of_utc"], "proposal_invalid")
    as_of = utc_time(as_of_text, "proposal_invalid")
    if _utc_text(as_of) != as_of_text:
        raise SchemaError("proposal_invalid")
    window_days = as_int(proposal["window_days"], "proposal_invalid")
    status = proposal["status"]
    if window_days < 1 or status not in ("complete", "incomplete"):
        raise SchemaError("proposal_invalid")
    complete = status == "complete"
    for key in ("snapshot_digest", "inventory_digest", "policy_digest"):
        if _hex_or_none(proposal[key], "proposal_invalid") is None:
            raise SchemaError("proposal_invalid")
    scope = as_object(proposal["measurement_scope"], "proposal_invalid")
    if set(scope) != {"complete", "valid", "closed"}:
        raise SchemaError("proposal_invalid")
    scope_flags = [
        _strict_bool(scope[key], "proposal_invalid") for key in sorted(scope)
    ]
    inputs = as_object(proposal["policy_inputs"], "proposal_invalid")
    if set(inputs) != {"pins_digest", "attestations_digest", "references_digest"}:
        raise SchemaError("proposal_invalid")
    digests = [_hex_or_none(inputs[key], "proposal_invalid") for key in sorted(inputs)]
    if complete and (not all(scope_flags) or any(item is None for item in digests)):
        raise SchemaError("proposal_invalid")
    if proposal["policy_digest"] != policy_digest(as_of_text, window_days, inputs):
        raise SchemaError("proposal_policy_mismatch")
    root = proposal["managed_root"]
    document = proposal["managed_tree"]
    tree: TreeState | None = None
    if (root is None) != (document is None):
        raise SchemaError("proposal_invalid")
    if document is not None:
        as_string(root, "proposal_invalid")
        if harness != "omp" or not os.path.isabs(cast(str, root)):
            raise SchemaError("proposal_invalid")
        tree = tree_from_document(document)
    expected_root = None if tree is None else tree.digest
    if (
        _hex_or_none(proposal["source_root_digest"], "proposal_invalid")
        != expected_root
    ):
        raise SchemaError("proposal_invalid")
    skills = [
        _validate_skill(item, tree, complete)
        for item in as_list(proposal["skills"], "proposal_invalid")
    ]
    names = [cast(str, skill["name"]) for skill in skills]
    counts = Counter(names)
    if any(
        counts[cast(str, skill["name"])] > 1 and skill["classification"] != "keep"
        for skill in skills
    ):
        raise SchemaError("proposal_invalid")
    pairs = [
        _validate_pair(item, set(names), complete)
        for item in as_list(proposal["merge_pairs"], "proposal_invalid")
    ]
    actionable = {
        cast(str, pair[side]) for pair in pairs if pair["actionable"] for side in "ab"
    }
    for skill in skills:
        if (
            skill["classification"] == "merge_candidate"
            and skill["name"] not in actionable
        ):
            raise SchemaError("proposal_invalid")
    _validate_name_lists(proposal["pin_names"], names)
    _validate_name_lists(proposal["reference_names"], names)
    _validate_days(proposal["inventory_observations_by_utc_day"], as_of, window_days)
    if proposal["approval_policy"] != APPROVAL_POLICY:
        raise SchemaError("proposal_invalid")
    unsealed = {key: item for key, item in proposal.items() if key != "proposal_digest"}
    declared = proposal["proposal_digest"]
    if not isinstance(declared, str) or not hmac.compare_digest(
        canonical_digest(unsealed), declared
    ):
        raise SchemaError("proposal_digest_mismatch")
    return proposal


# --------------------------------------------------------------------------- policy inputs


@dataclass(frozen=True)
class _Attestation:
    tree_digest: str
    harness_generated: bool
    never_user_authored: bool
    since: datetime
    description_only_reviewed: bool
    coverage_still_needed: bool
    periodic: bool


def _read_optional(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        return read_private_json(path)
    except SchemaError as error:
        if error.code != "private_input_missing":
            raise
        return None


def _load_pins(
    path: Path | None, diagnostics: Counter[str]
) -> tuple[frozenset[str] | None, str | None]:
    document = _read_optional(path)
    if document is None:
        diagnostics["pins_missing"] += 1
        return None, None
    if set(document) != {"schema_version", "pins"} or not _is_one(
        document["schema_version"]
    ):
        raise SchemaError("pins_invalid")
    names = [
        as_string(item, "pins_invalid")
        for item in as_list(document["pins"], "pins_invalid")
    ]
    if len(set(names)) != len(names):
        raise SchemaError("pins_invalid")
    digest = canonical_digest({"schema_version": 1, "pins": sorted(names)})
    return frozenset(names), digest


def _load_attestations(
    path: Path | None, diagnostics: Counter[str]
) -> tuple[dict[str, _Attestation] | None, str | None]:
    document = _read_optional(path)
    if document is None:
        diagnostics["attestations_missing"] += 1
        return None, None
    if set(document) != {"schema_version", "items"} or not _is_one(
        document["schema_version"]
    ):
        raise SchemaError("attestations_invalid")
    found: dict[str, _Attestation] = {}
    normalized: list[dict[str, object]] = []
    for raw in as_list(document["items"], "attestations_invalid"):
        item = as_object(raw, "attestations_invalid")
        if set(item) != _ATTESTATION_KEYS:
            raise SchemaError("attestations_invalid")
        name = as_string(item["name"], "attestations_invalid")
        tree_digest = item["tree_digest"]
        since_text = as_string(
            item["historical_identity_attested_since"], "attestations_invalid"
        )
        if (
            name in found
            or not isinstance(tree_digest, str)
            or not is_hex_digest(tree_digest)
            or not since_text.endswith(("Z", "+00:00"))
        ):
            raise SchemaError("attestations_invalid")
        since = utc_time(since_text, "attestations_invalid")
        attestation = _Attestation(
            tree_digest=tree_digest,
            harness_generated=_strict_bool(
                item["harness_generated"], "attestations_invalid"
            ),
            never_user_authored=_strict_bool(
                item["never_user_authored"], "attestations_invalid"
            ),
            since=since,
            description_only_reviewed=_strict_bool(
                item["description_only_reviewed"], "attestations_invalid"
            ),
            coverage_still_needed=_strict_bool(
                item["coverage_still_needed"], "attestations_invalid"
            ),
            periodic=_strict_bool(
                item["periodic_or_incident_workflow"], "attestations_invalid"
            ),
        )
        found[name] = attestation
        normalized.append(
            {**item, "historical_identity_attested_since": _utc_text(since)}
        )
    normalized.sort(key=lambda entry: cast(str, entry["name"]))
    digest = canonical_digest({"schema_version": 1, "items": normalized})
    return found, digest


def _snapshot_digest(
    path: Path,
    harness: Harness,
    as_of: datetime,
    window_days: int,
    inventory: Inventory,
    diagnostics: Counter[str],
) -> str:
    """Digest of the private binding, whose random key gives the proposal digest entropy."""
    document = _read_optional(path)
    if document is None:
        diagnostics["snapshot_binding_missing"] += 1
        return canonical_digest({"snapshot_binding": "missing"})
    binding = load_binding(canonical_json(document))
    if (
        binding.harness != harness
        or binding.as_of != as_of
        or binding.window_days != window_days
    ):
        raise SchemaError("snapshot_binding_mismatch")
    if binding.inventory != inventory.integrity:
        diagnostics["inventory_drift"] += 1
    return canonical_digest(document)


def _inventory_digest(inventory: Inventory, entries: Sequence[InstalledSkill]) -> str:
    return canonical_digest(
        {
            "integrity": inventory.integrity,
            "entries": [
                [
                    entry.name,
                    str(entry.path),
                    entry.ownership,
                    sorted(str(alias) for alias in entry.aliases),
                ]
                for entry in entries
            ],
            "coverage": sorted(inventory.coverage.items()),
            "reference_names": sorted(inventory.reference_names),
            "approved_roots": sorted(str(root) for root in inventory.approved_roots),
        }
    )


# --------------------------------------------------------------------------- measurement alignment


def _check_report(
    report: dict[str, object],
    private_report: dict[str, object],
    as_of: datetime,
    window_days: int,
) -> tuple[Harness, dict[str, bool]]:
    scope = as_object(report.get("scope"), "report_invalid")
    harness = scope.get("harness")
    if not isinstance(harness, str) or harness not in _HARNESSES:
        raise SchemaError("report_invalid")
    if (
        utc_time(scope.get("as_of_utc"), "report_invalid") != as_of
        or scope.get("window_days") != window_days
    ):
        raise SchemaError("report_scope_mismatch")
    snapshot = as_object(report.get("snapshot"), "report_invalid")
    if (
        not _is_one(private_report.get("schema_version"))
        or private_report.get("status") != report.get("status")
        or private_report.get("scope") != scope
    ):
        raise SchemaError("private_report_mismatch")
    return cast(Harness, harness), {
        "complete": report.get("status") == "complete",
        "valid": snapshot.get("valid") is True,
        "closed": snapshot.get("closed") is True,
    }


def _align(
    private_report: dict[str, object], entries: Sequence[InstalledSkill]
) -> list[dict[str, object]]:
    rows = as_list(private_report.get("skills"), "private_report_invalid")
    if len(rows) != len(entries):
        raise SchemaError("private_report_mismatch")
    aligned: list[dict[str, object]] = []
    for entry, raw in zip(entries, rows, strict=True):
        evidence = normalize_evidence(as_object(raw, "private_report_invalid"))
        installed = _moment(evidence, "installation_date")
        if (
            evidence["name"] != entry.name
            or evidence["ownership"] != entry.ownership
            or installed != entry.installed_at
        ):
            raise SchemaError("private_report_mismatch")
        aligned.append(evidence)
    return aligned


def _observation_days(
    private_report: dict[str, object],
    as_of: datetime,
    window_days: int,
    diagnostics: Counter[str],
) -> dict[str, int]:
    raw = private_report.get("inventory_observations_by_utc_day")
    if raw is None:
        diagnostics["observation_calendar_missing"] += 1
        return {}
    document = as_object(raw, "private_report_invalid")
    first = (as_of - timedelta(days=window_days)).date()
    days: dict[str, int] = {}
    for key, value in document.items():
        try:
            moment = date.fromisoformat(key)
        except ValueError:
            raise SchemaError("private_report_invalid") from None
        if moment.isoformat() != key or not first <= moment <= as_of.date():
            raise SchemaError("private_report_invalid")
        days[key] = as_int(value, "private_report_invalid")
    return dict(sorted(days.items()))


def _activity_cutoff(
    private_report: dict[str, object], diagnostics: Counter[str]
) -> str:
    """A historical cutoff cannot authorize archiving while the captured prefix
    already holds skill activity after it. Missing is unknown, never "no activity"."""
    value = private_report.get("observed_activity_after_as_of")
    if value is None:
        diagnostics["observed_activity_after_as_of_unknown"] += 1
        return "unknown"
    if not isinstance(value, bool):
        raise SchemaError("private_report_invalid")
    if value:
        diagnostics["observed_activity_after_as_of"] += 1
        return "later_activity_observed"
    return "none_observed"


def _calendar(
    days: dict[str, int], as_of: datetime, window_days: int
) -> dict[str, object]:
    first = (as_of - timedelta(days=window_days)).date()
    last = as_of.date()
    span = (last - first).days + 1
    observed = sorted(date.fromisoformat(key) for key, count in days.items() if count)
    points = [first, *observed, last]
    gaps = [(right - left).days for left, right in itertools.pairwise(points)]
    return {
        "window_days": window_days,
        "calendar_days_in_window": span,
        "days_with_inventory_observations": len(observed),
        "coverage_fraction": round(len(observed) / span, 6),
        "inventory_observations": sum(days.values()),
        "largest_gap_days_including_window_edges": max(gaps) if observed else None,
        "main_session_presence": "unmeasured",
    }


# --------------------------------------------------------------------------- features and similarity


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(unicodedata.normalize("NFC", text).casefold())


def _content(tokens: Sequence[str]) -> frozenset[str]:
    return frozenset(token for token in tokens if token not in STOPWORDS)


def _boundary_tokens(description: str) -> frozenset[str]:
    found: set[str] = set()
    for clause in _BOUNDARY_CLAUSE.split(description):
        tokens = _tokens(clause)
        if NEGATION_TOKENS.intersection(tokens):
            found.update(token for token in tokens if token not in STOPWORDS)
    return frozenset(found)


@dataclass(frozen=True)
class _Features:
    name: frozenset[str]
    description: frozenset[str]
    headings: frozenset[str]
    boundaries: frozenset[str]
    high_risk: bool


def _features(entry: InstalledSkill) -> _Features:
    name = _tokens(entry.name)
    description = _tokens(entry.description)
    headings = [token for heading in entry.headings for token in _tokens(heading)]
    return _Features(
        name=_content(name),
        description=_content(description),
        headings=_content(headings),
        boundaries=_boundary_tokens(entry.description),
        high_risk=any(
            token in HIGH_RISK_TOKENS
            for part in (name, description, headings)
            for token in part
        ),
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> Fraction:
    union = len(left | right)
    return Fraction(len(left & right), union) if union else Fraction(0)


def _similarity(
    left: _Features, right: _Features
) -> tuple[Fraction, Fraction, Fraction, Fraction]:
    name = _jaccard(left.name, right.name)
    description = _jaccard(left.description, right.description)
    headings = _jaccard(left.headings, right.headings)
    score = (
        WEIGHT_NAME * name
        + WEIGHT_DESCRIPTION * description
        + WEIGHT_HEADINGS * headings
    )
    return score, name, description, headings


def _pair_record(
    left: InstalledSkill,
    right: InstalledSkill,
    left_features: _Features,
    right_features: _Features,
    parts: tuple[Fraction, Fraction, Fraction, Fraction],
    protected: tuple[bool, bool],
    complete: bool,
) -> dict[str, object]:
    score, name, description, headings = parts
    return {
        "a": left.name,
        "b": right.name,
        "score": round(float(score), 6),
        "features": {
            "name": round(float(name), 6),
            "description": round(float(description), 6),
            "headings": round(float(headings), 6),
        },
        "matched": {
            "name": sorted(left_features.name & right_features.name),
            "description": sorted(
                left_features.description & right_features.description
            ),
            "headings": sorted(left_features.headings & right_features.headings),
        },
        "differences": {
            "description_only_a": sorted(
                left_features.description - right_features.description
            ),
            "description_only_b": sorted(
                right_features.description - left_features.description
            ),
            "negative_boundaries_only_a": sorted(
                left_features.boundaries - right_features.boundaries
            ),
            "negative_boundaries_only_b": sorted(
                right_features.boundaries - left_features.boundaries
            ),
        },
        "a_protected": protected[0],
        "b_protected": protected[1],
        "actionable": complete and not protected[0] and not protected[1],
        "review": "human_required",
    }


# --------------------------------------------------------------------------- source references


def _read_body_names(path: Path) -> frozenset[str] | None:
    try:
        fd, _ = open_regular(path)
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(MAX_SKILL_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_SKILL_BYTES:
        return None
    names = reference_names(".md", data)
    return None if names is None else frozenset(names)


def _body_referrers(
    entries: Sequence[InstalledSkill],
) -> tuple[dict[str, set[Path]], bool]:
    referrers: dict[str, set[Path]] = {}
    complete = True
    for entry in entries:
        names = _read_body_names(entry.path)
        if names is None:
            complete = False
            continue
        for target in names:
            referrers.setdefault(target, set()).add(entry.path)
    return referrers, complete


def _managed_tree(
    harness: Harness,
    inventory: Inventory,
    diagnostics: Counter[str],
) -> tuple[Path | None, TreeState | None]:
    """The whole OMP managed root, scanned once; quiescence is judged on the whole root."""
    if harness != "omp":
        return None, None
    roots = [
        root
        for root in inventory.approved_roots
        if root.name == "managed-skills"
        and root.parent.name == "agent"
        and root.parent.parent.name == ".omp"
    ]
    managed = any(entry.ownership == "managed" for entry in inventory.entries)
    if not roots:
        if managed:
            diagnostics["managed_root_unresolved"] += 1
        return None, None
    if len(roots) > 1:
        diagnostics["managed_root_unresolved"] += 1
        return None, None
    try:
        return roots[0], scan_tree(roots[0])
    except SchemaError:
        diagnostics["managed_tree_unavailable"] += 1
        return None, None


# --------------------------------------------------------------------------- per-skill decision


@dataclass
class _Decision:
    entry: InstalledSkill
    evidence: dict[str, object]
    features: _Features
    tree_digest: str | None
    attestation: _Attestation | None
    lineage_ok: bool
    referenced: bool
    blockers: set[str]
    classification: str = "keep"
    reasons: set[str] = field(default_factory=set)
    counter: set[str] = field(default_factory=set)


def _age_start(evidence: dict[str, object], since: datetime | None) -> datetime | None:
    """Earliest reliable evidence the file/name existed: install time, or an observation
    that falls inside the attested lineage."""
    candidates: list[datetime] = []
    installed = _moment(evidence, "installation_date")
    if installed is not None:
        candidates.append(installed)
    first = _moment(evidence, "first_observed_inventory_date")
    if first is not None and since is not None and since <= first:
        candidates.append(first)
    return min(candidates) if candidates else None


def _window_uses(evidence: dict[str, object]) -> int | None:
    reads = _count(evidence, "window_read_attempts")
    invocations = _count(evidence, "window_invocation_attempts")
    return None if reads is None or invocations is None else reads + invocations


def _use_assessment(
    evidence: dict[str, object], as_of: datetime, window_days: int
) -> tuple[str | None, set[str]]:
    total = _window_uses(evidence)
    if total is None:
        return None, {"use_channel_unavailable"}
    if total == 0:
        return "never_read_in_window", set()
    if total > RARE_MAX_USES:
        return None, {"use_above_rare_threshold"}
    reasons: set[str] = set()
    last = _moment(evidence, "window_last_use_date")
    if last is None:
        reasons.add("use_dates_missing")
    elif as_of - last < timedelta(days=RARE_MIN_IDLE_DAYS):
        reasons.add("recent_use")
    gap = evidence["largest_observed_inter_use_gap_days"]
    if not isinstance(gap, int | float) or isinstance(gap, bool):
        reasons.add("gap_unknown")
    elif window_days < RARE_GAP_MULTIPLE * gap:
        reasons.add("window_below_twice_gap")
    return (None, reasons) if reasons else ("rare_read_in_window", set())


def _directory_name(entry: InstalledSkill, root: Path | None) -> str | None:
    if (
        root is None
        or entry.path.name != "SKILL.md"
        or entry.path.parent.parent != root
    ):
        return None
    return entry.path.parent.name


def _assess(
    entry: InstalledSkill,
    evidence: dict[str, object],
    *,
    harness: Harness,
    as_of: datetime,
    window_days: int,
    name_counts: Counter[str],
    pins: frozenset[str] | None,
    attestations: dict[str, _Attestation] | None,
    declared_references: AbstractSet[str],
    referrers: dict[str, set[Path]],
    root: Path | None,
    tree: TreeState | None,
    diagnostics: Counter[str],
) -> _Decision:
    features = _features(entry)
    blockers: set[str] = set()
    directory = _directory_name(entry, root)
    names = {entry.name} | ({directory} if directory is not None else set())
    if harness != "omp":
        blockers.add("harness_not_mutable")
    if entry.ownership != "managed":
        blockers.add(f"ownership_{entry.ownership}")
    if entry.aliases:
        blockers.add("alias_or_link")
    if name_counts[entry.name] > 1:
        blockers.add("ambiguous_name")
    if pins is not None and entry.name in pins:
        blockers.add("pinned")
    if features.high_risk:
        blockers.add("high_risk_term")
    instruction = bool(names & declared_references)
    body = any(
        path != entry.path for name in names for path in referrers.get(name, set())
    )
    if instruction:
        blockers.add("referenced_by_instruction")
    if body:
        blockers.add("referenced_by_skill_body")
    observed = evidence["log_observed_dependency"]
    if observed is True:
        blockers.add("referenced_by_observed_autoload")
    elif observed is None:
        blockers.add("observed_dependencies_unknown")
    tree_digest: str | None = None
    matched: _Attestation | None = None
    lineage_ok = False
    if harness == "omp" and entry.ownership == "managed":
        if directory is not None and directory != entry.name:
            blockers.add("directory_name_mismatch")
        if tree is not None and directory is not None:
            try:
                tree_digest = _subtree(tree, directory).digest
            except SchemaError:
                diagnostics["managed_tree_mismatch"] += 1
        if tree_digest is None:
            blockers.add("source_tree_unavailable")
        attested = None if attestations is None else attestations.get(entry.name)
        if attested is None:
            blockers.add("attestation_missing")
        elif tree_digest is not None:
            if attested.tree_digest == tree_digest:
                matched = attested
            else:
                blockers.add("attestation_digest_mismatch")
        since = None if matched is None else matched.since
        window_start = as_of - timedelta(days=window_days)
        if matched is not None:
            lineage_ok = since is not None and (
                since <= as_of - timedelta(days=MIN_AGE_DAYS) and since <= window_start
            )
            if not matched.harness_generated:
                blockers.add("not_harness_generated")
            if not matched.never_user_authored:
                blockers.add("user_authorship_not_excluded")
            if not matched.description_only_reviewed:
                blockers.add("description_only_unreviewed")
            if matched.coverage_still_needed:
                blockers.add("coverage_still_needed")
            if matched.periodic:
                blockers.add("periodic_or_incident_workflow")
            if not lineage_ok:
                blockers.add("lineage_after_required_start")
        started = _age_start(evidence, since)
        if started is None:
            blockers.add("age_unknown")
        elif as_of - started < timedelta(days=MIN_AGE_DAYS):
            blockers.add("age_below_minimum")
        if window_days < MIN_AGE_DAYS:
            blockers.add("window_below_minimum")
        snapshots = _count(evidence, "inventory_present_subagent_snapshots")
        groups = _count(evidence, "inventory_present_main_task_groups")
        grouping = evidence["inventory_presence_grouping_complete"]
        if snapshots is None or groups is None or grouping is None:
            blockers.add("opportunities_unknown")
        elif grouping is not True:
            blockers.add("grouping_incomplete")
        elif snapshots < MIN_SNAPSHOTS or groups < MIN_MAIN_GROUPS:
            blockers.add("opportunities_below_minimum")
    return _Decision(
        entry=entry,
        evidence=evidence,
        features=features,
        tree_digest=tree_digest,
        attestation=matched,
        lineage_ok=lineage_ok,
        referenced=instruction or body or observed is True,
        blockers=blockers,
    )


_CANDIDATE_COUNTER_EVIDENCE = frozenset(
    {
        "description_only_influence_unmeasured",
        "main_session_presence_unmeasured",
        "read_frequency_is_not_utility",
        "authored_creation_unknown",
        "historical_identity_owner_asserted",
    }
)


def _skill_record(decision: _Decision) -> dict[str, object]:
    attestation = decision.attestation
    return {
        "name": decision.entry.name,
        "classification": decision.classification,
        "reasons": sorted(decision.reasons),
        "counter_evidence": sorted(decision.counter),
        "tree_digest": decision.tree_digest,
        "generated_only_attested": attestation is not None
        and attestation.harness_generated,
        "never_user_authored_attested": attestation is not None
        and attestation.never_user_authored,
        "historical_lineage_attested": attestation is not None and decision.lineage_ok,
        "description_only_reviewed": attestation is not None
        and attestation.description_only_reviewed,
        "coverage_still_needed": (
            None if attestation is None else attestation.coverage_still_needed
        ),
        "periodic_or_incident_workflow": (
            None if attestation is None else attestation.periodic
        ),
        "eligible": decision.classification == "archive_candidate",
        "evidence": decision.evidence,
    }


def _public_report(
    *,
    status: str,
    harness: Harness,
    as_of: datetime,
    window_days: int,
    diagnostics: Counter[str],
    decisions: Sequence[_Decision],
    pairs: Sequence[dict[str, object]],
    pins: frozenset[str] | None,
    attestations: dict[str, _Attestation] | None,
    states: dict[str, str],
    days: dict[str, int],
    files_by_cohort: object,
    proposal_digest: str,
) -> dict[str, object]:
    classes = Counter(decision.classification for decision in decisions)
    reasons: Counter[str] = Counter()
    counter: Counter[str] = Counter()
    ownership: Counter[str] = Counter()
    for decision in decisions:
        reasons.update(decision.reasons)
        counter.update(decision.counter)
        ownership[decision.entry.ownership] += 1
    installed = {decision.entry.name for decision in decisions}
    ready = [
        decision
        for decision in decisions
        if _count(decision.evidence, "inventory_present_subagent_snapshots") is not None
    ]
    snapshots = [
        cast(int, _count(item.evidence, "inventory_present_subagent_snapshots"))
        for item in ready
    ]
    groups = [
        _count(item.evidence, "inventory_present_main_task_groups") or 0
        for item in ready
    ]
    complete = sum(
        item.evidence["inventory_presence_grouping_complete"] is True for item in ready
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "status": status,
        "scope": {
            "harness": harness,
            "as_of_utc": _utc_text(as_of),
            "window_days": window_days,
            "window_start_utc": _utc_text(as_of - timedelta(days=window_days)),
        },
        "policy": {
            "version": POLICY_VERSION,
            "minimum_age_days": MIN_AGE_DAYS,
            "minimum_inventory_present_snapshots": MIN_SNAPSHOTS,
            "minimum_main_task_groups": MIN_MAIN_GROUPS,
            "rare_max_observed_uses": RARE_MAX_USES,
            "rare_min_idle_days": RARE_MIN_IDLE_DAYS,
            "rare_window_to_largest_gap_multiple": RARE_GAP_MULTIPLE,
            "merge_similarity_threshold": float(MERGE_THRESHOLD),
            "similarity_weights": {
                "name": float(WEIGHT_NAME),
                "description": float(WEIGHT_DESCRIPTION),
                "headings": float(WEIGHT_HEADINGS),
            },
            "approval": dict(APPROVAL_POLICY),
        },
        "inputs": dict(sorted(states.items())),
        "counts": {
            "installed_entries": len(decisions),
            "by_ownership": dict(sorted(ownership.items())),
            "keep": classes["keep"],
            "archive_candidates": classes["archive_candidate"],
            "merge_candidates": classes["merge_candidate"],
            "eligible_for_archive_approval": classes["archive_candidate"],
            "pins_provided": None if pins is None else len(pins),
            "pins_matching_installed": (
                None if pins is None else len(pins & installed)
            ),
            "attestations_provided": None
            if attestations is None
            else len(attestations),
            "attestations_matching_current_tree": sum(
                decision.attestation is not None for decision in decisions
            ),
            "similar_pairs": len(pairs),
            "actionable_similar_pairs": sum(bool(pair["actionable"]) for pair in pairs),
        },
        "reasons": dict(sorted(reasons.items())),
        "counter_evidence": dict(sorted(counter.items())),
        "calendar": _calendar(days, as_of, window_days),
        "opportunities": {
            "entries_with_opportunity_evidence": len(ready),
            "entries_with_complete_grouping": complete,
            "entries_with_at_least_minimum_snapshots": sum(
                value >= MIN_SNAPSHOTS for value in snapshots
            ),
            "entries_with_at_least_minimum_main_groups": sum(
                value >= MIN_MAIN_GROUPS for value in groups
            ),
            "main_session_presence": "unmeasured",
        },
        "cohorts": {"files_by_cohort": files_by_cohort},
        "diagnostics": dict(sorted(diagnostics.items())),
        "limits": [
            "recommendation_never_authorizes_mutation",
            "read_frequency_is_not_utility",
            "historical_identity_is_owner_asserted_not_proven",
            "description_only_influence_is_unmeasured",
            "authored_creation_is_unknown",
        ],
        "proposal_digest": proposal_digest,
    }


# --------------------------------------------------------------------------- recommend


def recommend(
    report: dict[str, object],
    private_report: dict[str, object],
    inventory: Inventory,
    *,
    as_of: datetime,
    window_days: int,
    binding_path: Path,
    pins_path: Path | None,
    attestations_path: Path | None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Return ``(public_aggregate_report, private_proposal)``; nothing is written.

    Missing pins, attestations, references, binding, observation calendar or managed
    source tree, an incomplete or drifted measurement, or blocking catalog coverage
    makes the proposal ``incomplete`` with every skill kept. Wrong schemas and
    mismatched report/inventory/binding pairs raise ``SchemaError``. The caller must
    re-load the inventory and compare drift before writing the proposal.
    """
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise SchemaError("invalid_as_of")
    if isinstance(window_days, bool) or window_days <= 0:
        raise SchemaError("invalid_window")
    as_of = as_of.astimezone(UTC)
    diagnostics: Counter[str] = Counter()
    harness, measurement = _check_report(report, private_report, as_of, window_days)
    for flag, code in (
        ("complete", "measurement_incomplete"),
        ("valid", "snapshot_invalid"),
        ("closed", "snapshot_not_closed"),
    ):
        if not measurement[flag]:
            diagnostics[code] += 1
    entries = sorted(inventory.entries, key=lambda item: (item.name, str(item.path)))
    evidence = _align(private_report, entries)
    days = _observation_days(private_report, as_of, window_days, diagnostics)
    activity = _activity_cutoff(private_report, diagnostics)
    snapshot_digest = _snapshot_digest(
        binding_path, harness, as_of, window_days, inventory, diagnostics
    )
    pins, pins_digest = _load_pins(pins_path, diagnostics)
    attestations, attestations_digest = _load_attestations(
        attestations_path, diagnostics
    )
    if inventory.coverage["references_not_provided"]:
        diagnostics["references_not_provided"] += 1
    for code in sorted(BLOCKING_COVERAGE):
        if inventory.coverage[code]:
            diagnostics[f"catalog_{code}"] += inventory.coverage[code]
    referrers, bodies_complete = _body_referrers(entries)
    if not bodies_complete:
        diagnostics["skill_body_unreadable"] += 1
    references_digest: str | None = None
    if bodies_complete and not inventory.coverage["references_not_provided"]:
        references_digest = canonical_digest(
            {
                "declared": sorted(inventory.reference_names),
                "skill_bodies": sorted(
                    [str(path), target]
                    for target, paths in referrers.items()
                    for path in paths
                ),
            }
        )
    root, tree = _managed_tree(harness, inventory, diagnostics)
    name_counts = Counter(entry.name for entry in entries)
    decisions = [
        _assess(
            entry,
            row,
            harness=harness,
            as_of=as_of,
            window_days=window_days,
            name_counts=name_counts,
            pins=pins,
            attestations=attestations,
            declared_references=inventory.reference_names,
            referrers=referrers,
            root=root,
            tree=tree,
            diagnostics=diagnostics,
        )
        for entry, row in zip(entries, evidence, strict=True)
    ]
    complete = not diagnostics
    pairs: list[dict[str, object]] = []
    members: set[int] = set()
    paired: set[int] = set()
    for left in range(len(decisions)):
        for right in range(left + 1, len(decisions)):
            first, second = decisions[left], decisions[right]
            parts = _similarity(first.features, second.features)
            if parts[0] < MERGE_THRESHOLD:
                continue
            protected = (bool(first.blockers), bool(second.blockers))
            record = _pair_record(
                first.entry,
                second.entry,
                first.features,
                second.features,
                parts,
                protected,
                complete,
            )
            pairs.append(record)
            paired.update((left, right))
            if record["actionable"]:
                members.update((left, right))
    for index, decision in enumerate(decisions):
        uses = _window_uses(decision.evidence)
        if uses:
            decision.counter.add("observed_use_in_window")
        if index in paired and index not in members:
            decision.counter.add("similar_installed_skill_pair")
        if not complete or decision.blockers:
            decision.reasons = set(decision.blockers) | (
                set() if complete else {"proposal_incomplete"}
            )
        elif index in members:
            decision.classification = "merge_candidate"
            decision.reasons = {"similar_installed_skill"}
            decision.counter |= _CANDIDATE_COUNTER_EVIDENCE
        else:
            kind, why = _use_assessment(decision.evidence, as_of, window_days)
            if kind is None:
                decision.reasons = why
            else:
                decision.classification = "archive_candidate"
                decision.reasons = {kind}
                decision.counter |= _CANDIDATE_COUNTER_EVIDENCE
    status = "complete" if complete else "incomplete"
    installed = {decision.entry.name for decision in decisions}
    policy_inputs: dict[str, object] = {
        "pins_digest": pins_digest,
        "attestations_digest": attestations_digest,
        "references_digest": references_digest,
    }
    as_of_text = _utc_text(as_of)
    proposal = seal_proposal(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": PROPOSAL_KIND,
            "harness": harness,
            "as_of_utc": as_of_text,
            "window_days": window_days,
            "status": status,
            "snapshot_digest": snapshot_digest,
            "inventory_digest": _inventory_digest(inventory, entries),
            "policy_digest": policy_digest(as_of_text, window_days, policy_inputs),
            "measurement_scope": dict(measurement),
            "managed_root": None if root is None or tree is None else str(root),
            "managed_tree": None if tree is None else tree_document(tree),
            "source_root_digest": None if tree is None else tree.digest,
            "policy_inputs": policy_inputs,
            "skills": [_skill_record(decision) for decision in decisions],
            "merge_pairs": pairs,
            "pin_names": sorted(installed & (pins or frozenset())),
            "reference_names": sorted(
                {decision.entry.name for decision in decisions if decision.referenced}
            ),
            "inventory_observations_by_utc_day": days,
            "approval_policy": dict(APPROVAL_POLICY),
        }
    )
    scope = report.get("scope")
    cohorts = as_object(scope, "report_invalid").get("files_by_cohort")
    states = {
        "snapshot_binding": (
            "missing" if diagnostics["snapshot_binding_missing"] else "provided"
        ),
        "pins": "provided" if pins is not None else "missing",
        "attestations": "provided" if attestations is not None else "missing",
        "references": "provided" if references_digest is not None else "missing",
        "managed_tree": (
            "not_applicable"
            if harness != "omp"
            else "scanned"
            if tree is not None
            else "unavailable"
        ),
        "observation_calendar": (
            "missing" if diagnostics["observation_calendar_missing"] else "provided"
        ),
        "activity_after_cutoff": activity,
    }
    public = _public_report(
        status=status,
        harness=harness,
        as_of=as_of,
        window_days=window_days,
        diagnostics=diagnostics,
        decisions=decisions,
        pairs=pairs,
        pins=pins,
        attestations=attestations,
        states=states,
        days=days,
        files_by_cohort=cohorts,
        proposal_digest=cast(str, proposal["proposal_digest"]),
    )
    return public, validate_proposal(proposal)
