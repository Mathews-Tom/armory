"""GitHub provider evidence and the guarded merge mutations for the ship workflow.

Evidence comes from the user's ``gh`` credential store; this module never reads
or extracts tokens.  Reads are ``gh api --method GET`` requests, except
``queue_state``: merge-queue entries exist only in GraphQL, so it sends one
read-only ``query`` with ``--method POST``.  The mutations are
``GitHub.merge`` (one ``gh pr merge`` command, described below),
``GitHub.start_native_merge`` (one never-retried ``PUT .../merge-async``) and
``GitHub.create_pr`` (one never-retried ``POST .../pulls``).  Provider
responses are validated at the boundary; evidence that cannot be established
is reported through ``Observation.issues`` (or a ``ProviderError``) and never
defaults to an empty or green answer.

Conventions the gate engine relies on
-------------------------------------
* ``Observation.issues`` entries are ``"<code>: <detail>"`` strings.  Any
  issue means some evidence is unknown, partial or anomalous; none may be
  silently ignored.
* ``policy_known=False`` means the required checks, required approvals,
  approvals, merge methods or strict-base policy are not fully authoritative;
  ``required_checks`` / ``required_approvals`` / ``approvals`` are then lower
  bounds only.
* Assurance (``observe(..., assurance=)``).  ``routine`` (the default) judges
  from the provider's own current evidence: every applicable check run and
  commit status of the PR head, required reviews, protections and merge policy.
  It never reads job logs and trusts no repository checkout step.  Merge-context
  freshness comes only from provider facts: the strict required-checks policy is
  proven by the PR head containing the base commit (compare metadata); a
  ``pull_request`` job counts as merge-context only when its run still names the
  PR's current base ref and was triggered (``run.created_at``, immutable even
  across re-runs) after the last base change (``base_ref_changed`` or
  ``automatic_base_change_succeeded``; ``Check.retargeted``), so a run against a
  previous base never satisfies the current one even when the base commit
  coincides.  ``Check.base_sha`` is then the run metadata's base claim (None for
  head-only events and statuses).  In both modes only the newest applicable run
  of each (workflow, event) is judged, derived from every observed run of the
  head: older runs' rows are dropped, a newer run that is waiting, has no job,
  failed to start or lacks a row for one of its jobs (jobs listing,
  ``filter=latest``) is pending or failed evidence, never an older success, and
  rows of earlier attempts of a re-run give way to the current attempt.
  ``high`` adds *checkout proof*: ``Check.base_sha`` is set to the current base
  only when the completed job's own log shows exactly one ``actions/checkout``
  step that synced the PR's repository and emitted a commit
  (``git log -1 --format=%H``), and ``git/commits`` shows that commit has
  parents ``[tested base, PR head]``.  ``Check.test_sha`` is that commit and
  ``Check.run_id`` the workflow run.  Timestamps, ``merge_commit_sha`` and
  workflow-run PR metadata are never enough there: without proof ``base_sha`` is
  None (a provably different metadata base is kept as stale evidence) and a
  ``checkout-*`` issue whose detail contains ``NEEDS_JUDGMENT`` is reported.
  Push and other non-merge events and non-Actions checks are head-only
  (``base_sha`` None).
* Trust boundary (``high``): job logs are produced by workflow code, which the
  PR itself can change.  Only runner-structured text inside the checkout step's
  segment is read and the commit it names is authenticated through
  ``git/commits``; that it truly tested the commit is not cryptographically
  provable.
* ``PullRequest.head_repo == ""`` means the provider reports no head
  repository (for example a deleted fork).
* ``GitHub(deadline=...)`` is an absolute ``time.monotonic()`` value.
* ``read_pr`` returns identity, state and landing facts of one PR without
  reading checks, runs or reviews, so a merged PR (CI long expired) or an
  interrupted run keeps its facts.  ``base_tip`` reads the live branch commit,
  never PR or run metadata.
* ``Observation.queue_required`` is true when a readable, applicable ruleset
  ``merge_queue`` rule exists.  The queue's own ``merge_method`` then replaces
  the free choice of method: ``Repository.allowed_merge_methods`` is narrowed
  to it (and, as for every rule, to the repository's enabled methods).  With
  ``policy_known=False`` it is a lower bound only.  Classic branch protection's
  "require merge queue" setting is not exposed by the REST endpoints read
  here; such a queue is discovered only when ``queue_state`` reports it after
  a merge request.
* ``merge`` dispatches exactly one ``gh pr merge <n> --repo <host>/<repo>
  --match-head-commit <sha> --<method>``: never ``--admin``, ``--delete-branch``,
  ``--auto`` or an unguarded fallback, and it is never retried.  Success only
  means gh accepted the command (a PR that was queued, armed for auto-merge or
  already merged also exits 0); callers poll ``read_pr`` until ``MERGED``.
  ``ProviderError.uncertain`` is true whenever the command may have reached
  GitHub with an unknown result (timeout, transport failure, signal,
  unrecognised failure); every other failure is a definite refusal or the
  command was never dispatched.  Stale head/base refusals are ``WAITING``.
* ``retarget_pr`` sends one never-retried base-only ``PATCH .../pulls/<n>``
  between authoritative ``read_pr`` checks; GitHub offers no atomic head/base guard.
* ``queue_state`` answers only for the expected head: ``QUEUED`` (a merge-queue
  entry exists), ``AUTO_MERGE`` (auto-merge is armed, no entry yet) or ``IDLE``
  (GraphQL and REST agree that neither exists).  Head drift, a PR that is no
  longer open, disagreeing sources, or any missing/partial/unreadable evidence
  raises ``ProviderError``; it is never ``IDLE``.  ``IDLE`` read right after an
  accepted command can still be replication lag, so it is not proof that the
  command was ignored.
* ``landing_reachable(landing, base_tip)`` is a read-only proof from the
  compare metadata of ``landing...base_tip`` in the base repository: ``True``
  only for status ``ahead``/``identical`` with a merge base equal to
  ``landing`` and a permalink naming exactly those two commits; proven
  non-ancestry (``behind``/``diverged``) is ``False``.  Unknown commits,
  inaccessible repositories and malformed or self-contradicting metadata raise
  ``ProviderError``.  The (truncated) commit list and counts are never proof.

Native stacks
-------------
* ``PullRequest.native`` is true exactly when the PR carries a provider
  ``stack`` object.  ``native_stack_number``, ``native_stack_position``
  (1-based, bottom up), ``native_stack_size`` and ``native_stack_base`` (the
  stack's ``base.ref``) copy that object; a field the provider omits is None,
  an explicit unknown that never makes the PR a manual-stack member.  A
  present but malformed or self-contradicting field raises ``ProviderError``.
* ``read_native_stack(n)`` reads ``GET .../stacks/<n>``, then ``read_pr`` for
  every listed member, then the stack again.  Members are returned bottom to
  top, each an authoritative PR read (a MERGED member keeps its landing facts).
  Every member must be in this repository, listed once, carry exactly the
  stack's number, its own position, the member count as size and the stack
  base, and chain on the member below (or, OPEN above only MERGED members, on
  the stack base).  Any contradiction is ``BLOCKED`` (``native-stack-mismatch``);
  membership, heads or states that move between the reads are ``WAITING``
  (``native-stack-changed``).
* ``native_trunk_policy(stack)`` evaluates the rules of the stack base (the
  trunk whose rules govern the whole stack), never a member's own base branch.
  ``action`` is ``merge_queue`` when an applicable ruleset merge queue exists,
  ``direct_merge`` when the policy is fully known without one, and None when
  it is unknown; None is blocked, never a licence to merge directly.  A queue
  that only classic branch protection requires is not visible here (see
  ``queue_required`` above).
* ``start_native_merge(n, expected_head, method, action)`` dispatches exactly
  one ``PUT .../pulls/<n>/merge-async`` with ``sha=<expected_head>``,
  ``merge_action=<action>`` and ``bypass_rules=false``.  ``direct_merge``
  requires an explicit ``merge_method``; ``merge_queue`` sends no
  ``merge_method``, ``commit_title`` or ``commit_message`` (GitHub refuses
  them with 422 and the queue rules pick the method).  ``default`` queues when
  a queue applies to the base and merges directly otherwise; it sends
  ``merge_method`` only when one is given, and a given method is refused (422)
  when a queue applies.  ``default`` without a method guarantees no method,
  so callers routing from ``native_trunk_policy`` send its explicit action.
  The request merges the prefix of open members ending at ``n``, but ``sha``
  guards only PR ``n``'s head: lower members are not individually guarded, so
  callers verify them immediately before dispatch and verify every landing
  afterwards.  There is no implicit action change, no fallback to a
  synchronous merge and no retry.  A ``pending`` reply (a new request) must
  carry a UUID and echo the head, action, method (``default`` when none was
  sent) and ``bypass_rules=false`` exactly (``NativeMergeResult.matches``), or
  it is uncertain.  A 2xx ``merged`` or ``enqueued`` reply means the PR was
  already merged or already queued (no new request, normally no UUID) and a
  2xx ``failed`` reply is returned as read.  400 (closed or draft PR), 403,
  404 and 422 are definite refusals.  Uncertainty follows ``merge``; a 409
  naming an existing request raises ``NativeMergeInProgress`` carrying that
  request with its echoed options, which may differ from the ones sent:
  ``existing.matches(action, method, expected_head)`` tells them apart.
* ``read_native_merge(n, uuid)`` reads ``GET .../pulls/<n>/merge-async/<uuid>``.
  Statuses are ``pending``, ``enqueued``, ``merged`` (with the selected PR's
  merge commit ``sha``) and ``failed`` (GitHub's reason in ``message``);
  anything else is a malformed response.  ``enqueued`` is terminal for the
  request and is not a merge: it stays ``enqueued`` after queue groups land the
  PRs.  ``failed`` is a result, not an error or a retry signal.  Results are
  kept for 24 hours; a 404 (expired or unknown request) is ``BLOCKED``
  ``native-merge-request-unknown`` and never implies a merge.  Even ``merged``
  is no per-member proof; only ``read_pr`` facts prove that a member landed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlencode, urlsplit

API_VERSION = "2026-03-10"
PER_PAGE = 100
MAX_PAGES = 200
MAX_ATTEMPTS = 3
RETRY_DELAYS = (1.0, 2.0)
CALL_TIMEOUT = 60.0
MAX_LOG_BYTES = 16 * 1024 * 1024
NO_DEADLINE_RETRY_CAP = 60.0
MERGE_METHODS = ("merge", "squash", "rebase")
#: Evidence strength of an observation: ``routine`` uses current provider
#: evidence only; ``high`` additionally attests each Actions job's checkout.
ASSURANCES = ("routine", "high")
MERGE_TIMEOUT = 90.0
CREATE_TIMEOUT = 60.0
HELP_TIMEOUT = 15.0
MIN_MUTATION_WINDOW = 10.0
_MERGE_FLAGS = {"merge": "--merge", "squash": "--squash", "rebase": "--rebase"}
_REQUIRED_MERGE_FLAGS = ("--match-head-commit", "--repo", *_MERGE_FLAGS.values())
#: ``merge_action`` values of ``PUT .../merge-async``; ``default`` queues when a
#: merge queue applies to the base and merges directly otherwise.
NATIVE_MERGE_ACTIONS = ("default", "direct_merge", "merge_queue")
#: Documented ``merge-async`` request statuses; ``enqueued`` is not a merge and
#: ``failed`` is a reported outcome, not an error.
NATIVE_MERGE_STATUSES = ("pending", "enqueued", "merged", "failed")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$")
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$")
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_NEXT_RE = re.compile(r'<[^>]*>\s*;\s*rel="next"')
_STATUS_RE = re.compile(r"HTTP\s+(\d{3})")
_STATUS_LINE_RE = re.compile(r"^HTTP/[\d.]+\s+(\d{3})")
_SECRET_RE = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|(?i:bearer)\s+\S+|(?i:token)\s+[A-Za-z0-9_-]{16,})"
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_NETWORK_RE = re.compile(
    r"(timeout|timed out|connection (reset|refused|closed)|\bEOF\b|tls handshake|temporary failure|"
    r"no such host|network is unreachable|broken pipe|i/o timeout)",
    re.IGNORECASE,
)
_PR_EVENT_PREFIX = "pull_request"
_ACTIONS_APP = "github-actions"
#: Timeline events that move a PR to another base (manually or by GitHub itself).
_BASE_CHANGE_EVENTS = ("base_ref_changed", "automatic_base_change_succeeded")

# Classification of a failed ``gh pr merge``: only a positively recognised
# refusal or pre-dispatch failure is "certain"; anything else may have reached GitHub.
_FLAG_ERROR_RE = re.compile(
    r"^unknown (?:shorthand )?flag: |^flag needs an argument: |"
    r'^invalid argument "[^\n]*" for "-|^accepts at most \d+ arg|'
    r"^argument required when using |^specify only one of --|^only one of --merge|"
    r"^--merge, --rebase, or --squash required",
    re.IGNORECASE | re.MULTILINE,
)
_AUTH_RE = re.compile(
    r"gh auth login|not logged in|bad credentials|\bHTTP 401\b", re.IGNORECASE
)
_NOT_MERGEABLE_RE = re.compile(r"\bis not mergeable\b", re.IGNORECASE)
_HEAD_MOVED_RE = re.compile(r"head branch was modified", re.IGNORECASE)
_BASE_MOVED_RE = re.compile(r"base branch was modified", re.IGNORECASE)
_RATE_LIMIT_RE = re.compile(r"\bHTTP 429\b|rate limit|abuse detection", re.IGNORECASE)
_AMBIGUOUS_RE = re.compile(
    r"timeout|timed out|something went wrong|\bHTTP 5\d\d\b|connection (?:reset|refused|closed)|\bEOF\b|"
    r"tls handshake|temporary failure|no such host|network is unreachable|broken pipe|"
    r"try again later|service unavailable|bad gateway|gateway",
    re.IGNORECASE,
)
_REJECTED_RE = re.compile(r"\bGraphQL:|\bHTTP (?:400|403|404|405|409|410|422)\b")

#: Rules that do not gate a pull-request merge decision made from this observation.
_IGNORED_RULES = frozenset(
    {
        "creation",
        "deletion",
        "update",
        "non_fast_forward",
        "branch_name_pattern",
        "tag_name_pattern",
        "commit_message_pattern",
        "commit_author_email_pattern",
        "committer_email_pattern",
        "file_path_restriction",
        "max_file_path_length",
        "file_extension_restriction",
        "max_file_size",
    }
)

Runner = Callable[[Sequence[str], float], "subprocess.CompletedProcess[bytes]"]

QueueState = Literal["QUEUED", "AUTO_MERGE", "IDLE"]

#: ``merge_method`` values of a ruleset ``merge_queue`` rule / GraphQL merge-method enums.
MERGE_QUEUE_METHODS = ("MERGE", "SQUASH", "REBASE")

_QUEUE_ENTRY_STATES = frozenset(
    {"QUEUED", "AWAITING_CHECKS", "MERGEABLE", "UNMERGEABLE", "LOCKED"}
)
#: Read-only GraphQL ``query`` (never a mutation); fields per the public GitHub GraphQL schema.
_QUEUE_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){"
    "repository(owner:$owner,name:$name){nameWithOwner "
    "pullRequest(number:$number){number state merged headRefOid isInMergeQueue "
    "autoMergeRequest{mergeMethod} mergeQueueEntry{state position}}}}"
)
_LANDING_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){"
    "repository(owner:$owner,name:$name){nameWithOwner "
    "pullRequest(number:$number){number state merged url headRefOid headRefName "
    "baseRefName mergedAt mergeCommit{oid}}}}"
)


class ProviderError(RuntimeError):
    """A provider read produced no trustworthy evidence, or a mutation did not complete.

    ``uncertain`` is true only for a mutation that may have reached GitHub with
    an unknown result; such an error must be reconciled against actual provider
    state and never answered by repeating the mutation.  ``detail`` is a short
    machine code (for example ``merge-head-changed``) or a redacted provider message.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: Literal["BLOCKED", "WAITING"],
        operation: str,
        uncertain: bool = False,
        http_status: int | None = None,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.kind: Literal["BLOCKED", "WAITING"] = kind
        self.operation = operation
        self.uncertain = uncertain
        self.http_status = http_status
        self.detail = detail


@dataclass(frozen=True)
class Repository:
    full_name: str
    host: str
    default_branch: str
    allowed_merge_methods: tuple[str, ...]


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    state: str
    head_sha: str
    head_ref: str
    head_repo: str
    base_sha: str
    base_ref: str
    base_repo: str
    merge_commit_sha: str | None
    merged_at: str | None
    draft: bool
    mergeable: bool | None
    native: bool
    native_stack_number: int | None = None
    native_stack_position: int | None = None
    native_stack_size: int | None = None
    native_stack_base: str | None = None


@dataclass(frozen=True)
class NativeStack:
    number: int
    base_ref: str
    members: tuple[PullRequest, ...]  # bottom to top


@dataclass(frozen=True)
class NativeMergeResult:
    """One ``merge-async`` request status; never evidence that any member landed.

    ``sha`` is set only for ``merged``; ``message`` is GitHub's (for ``failed``,
    the reason).  ``uuid`` is None for an immediate already-merged/queued reply.
    ``merge_action``, ``merge_method`` and ``bypass_rules`` are the request
    options GitHub echoes in ``details`` (None when it omits one).
    """

    status: str
    uuid: str | None
    message: str
    sha: str | None
    expected_head_sha: str | None
    merge_action: str | None = None
    merge_method: str | None = None
    bypass_rules: bool | None = None

    def matches(self, action: str, method: str | None, expected_head: str) -> bool:
        """Whether this is exactly a request sent as ``start_native_merge`` sends it.

        True only for an identified request echoing ``action``, ``method``
        (``default`` for a request sent without one), ``expected_head`` and
        ``bypass_rules=false``.  Use it to reconcile ``NativeMergeInProgress``:
        a request with other options is not the one that was meant.
        """
        return (
            self.uuid is not None
            and self.merge_action == action
            and self.merge_method == (method or "default")
            and self.expected_head_sha == expected_head
            and self.bypass_rules is False
        )


@dataclass(frozen=True)
class NativeTrunkPolicy:
    trunk: str
    action: str | None
    methods: tuple[str, ...]
    policy_known: bool
    issues: tuple[str, ...]


class NativeMergeInProgress(ProviderError):
    """GitHub refused (409) because an async merge request already exists.

    ``existing`` is that request as GitHub reported it, with its echoed options;
    ``existing.matches`` decides whether it is exactly the intended request.
    Reconcile it with ``read_native_merge`` before treating the PR as handled.
    """

    def __init__(
        self, message: str, *, operation: str, existing: NativeMergeResult
    ) -> None:
        super().__init__(
            message,
            kind="WAITING",
            operation=operation,
            http_status=409,
            detail="native-merge-in-progress",
        )
        self.existing = existing


@dataclass(frozen=True)
class Check:
    name: str
    head_sha: str
    base_sha: str | None
    status: str
    conclusion: str | None
    app_slug: str
    url: str
    updated_at: str
    test_sha: str | None = None
    run_id: int | None = None
    app_id: int | None = None
    workflow_id: int | None = None
    event: str | None = None
    check_id: int | None = None
    retargeted: bool = False


@dataclass(frozen=True)
class Observation:
    repo: Repository
    pr: PullRequest
    checks: tuple[Check, ...]
    required_checks: tuple[str, ...]
    required_approvals: int
    approvals: int
    changes_requested: bool
    policy_known: bool
    issues: tuple[str, ...]
    require_current_base: bool = False
    required_apps: tuple[tuple[str, int], ...] = ()
    queue_required: bool = False
    assurance: str = "routine"
    head_contains_base: bool | None = None
    base_changed_at: str | None = None


@dataclass(frozen=True)
class RetryRecord:
    operation: str
    attempt: int
    reason: str
    delay: float


# --------------------------------------------------------------------------
# Boundary validation


def _clean(text: str, limit: int = 200) -> str:
    text = _SECRET_RE.sub("[redacted]", text)
    text = _CONTROL_RE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _Obj:
    """Typed view over a decoded JSON object; every violation is a ProviderError."""

    def __init__(self, data: dict[str, Any], op: str, path: str) -> None:
        self._d = data
        self._op = op
        self._path = path

    @classmethod
    def of(cls, value: Any, op: str, path: str) -> _Obj:
        if not isinstance(value, dict):
            raise _malformed(op, f"{path} is not an object")
        return cls(value, op, path)

    def _key(self, key: str) -> str:
        return f"{self._path}.{key}"

    def has(self, key: str) -> bool:
        return key in self._d

    def _need(self, key: str) -> Any:
        if key not in self._d:
            raise _malformed(self._op, f"{self._key(key)} is missing")
        return self._d[key]

    def text(self, key: str) -> str:
        value = self._need(key)
        if not isinstance(value, str):
            raise _malformed(self._op, f"{self._key(key)} is not a string")
        return value

    def opt_text(self, key: str) -> str | None:
        value = self._d.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise _malformed(self._op, f"{self._key(key)} is not a string")
        return value

    def integer(self, key: str) -> int:
        value = self._need(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise _malformed(self._op, f"{self._key(key)} is not an integer")
        return value

    def opt_integer(self, key: str) -> int | None:
        if self._d.get(key) is None:
            return None
        return self.integer(key)

    def flag(self, key: str) -> bool:
        value = self._need(key)
        if not isinstance(value, bool):
            raise _malformed(self._op, f"{self._key(key)} is not a boolean")
        return value

    def opt_flag(self, key: str) -> bool | None:
        if self._d.get(key) is None:
            return None
        return self.flag(key)

    def sha(self, key: str) -> str:
        value = self.text(key)
        if not _SHA_RE.match(value):
            raise _malformed(self._op, f"{self._key(key)} is not a full object id")
        return value

    def opt_sha(self, key: str) -> str | None:
        if self._d.get(key) is None:
            return None
        return self.sha(key)

    def obj(self, key: str) -> _Obj:
        return _Obj.of(self._need(key), self._op, self._key(key))

    def opt_obj(self, key: str) -> _Obj | None:
        value = self._d.get(key)
        if value is None:
            return None
        return _Obj.of(value, self._op, self._key(key))

    def arr(self, key: str) -> list[Any]:
        value = self._need(key)
        if not isinstance(value, list):
            raise _malformed(self._op, f"{self._key(key)} is not an array")
        return value

    def objs(self, key: str) -> list[_Obj]:
        return [
            _Obj.of(item, self._op, f"{self._key(key)}[{index}]")
            for index, item in enumerate(self.arr(key))
        ]


def _malformed(op: str, detail: str) -> ProviderError:
    return ProviderError(
        f"{op}: malformed provider response: {_clean(detail)}",
        kind="BLOCKED",
        operation=op,
        detail="malformed",
    )


def _objects(value: Any, op: str, path: str) -> list[_Obj]:
    if not isinstance(value, list):
        raise _malformed(op, f"{path} is not an array")
    return [_Obj.of(item, op, f"{path}[{index}]") for index, item in enumerate(value)]


def _timestamp(value: str, op: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _malformed(op, f"{name} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise _malformed(op, f"{name} has no timezone")
    return parsed


# --------------------------------------------------------------------------
# Transport


@dataclass(frozen=True)
class _Response:
    status: int | None
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class _Failure:
    kind: Literal["transient", "ratelimit", "blocked"]
    retry_after: float | None
    status: int | None
    detail: str


def _run_gh(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    env = {
        **os.environ,
        "GH_PROMPT_DISABLED": "1",
        "GH_NO_UPDATE_NOTIFIER": "1",
        "GH_SPINNER_DISABLED": "1",
        "NO_COLOR": "1",
    }
    return subprocess.run(
        list(argv),
        capture_output=True,
        timeout=timeout,
        check=False,
        stdin=subprocess.DEVNULL,
        env=env,
    )


def _split_response(stdout: bytes) -> _Response:
    for separator in (b"\r\n\r\n", b"\n\n"):
        head, found, body = stdout.partition(separator)
        if found and head.startswith(b"HTTP/"):
            lines = head.decode("utf-8", "replace").splitlines()
            status = _STATUS_LINE_RE.search(lines[0])
            headers: dict[str, str] = {}
            for line in lines[1:]:
                name, colon, value = line.partition(":")
                if colon:
                    headers[name.strip().lower()] = value.strip()
            return _Response(int(status.group(1)) if status else None, headers, body)
    return _Response(None, {}, stdout)


def _retry_after(value: str | None) -> float | None:
    if value is not None and re.fullmatch(r"\d+(\.\d+)?", value):
        return float(value)
    return None


def _failure(proc: subprocess.CompletedProcess[bytes], response: _Response) -> _Failure:
    stderr = proc.stderr.decode("utf-8", "replace")
    status = response.status
    if status is None:
        found = _STATUS_RE.search(stderr)
        status = int(found.group(1)) if found else None
    detail = ""
    try:
        payload = json.loads(response.body)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        detail = payload["message"]
    if not detail:
        detail = stderr
    detail = _clean(detail)
    lowered = detail.lower()
    graphql_limited = (
        isinstance(payload, dict)
        and isinstance(payload.get("errors"), list)
        and any(
            isinstance(error, dict)
            and (
                error.get("type") == "RATE_LIMITED"
                or isinstance(error.get("message"), str)
                and _RATE_LIMIT_RE.search(error["message"]) is not None
            )
            for error in payload["errors"]
        )
    )
    retry_after = _retry_after(response.headers.get("retry-after"))
    limited = status == 429 or (
        status in (200, 403)
        and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or retry_after is not None
            or "rate limit" in lowered
            or "abuse" in lowered
            or graphql_limited
        )
    )
    if limited:
        return _Failure("ratelimit", retry_after, status, detail)
    if status in (500, 502, 503, 504) or (
        status is None and _NETWORK_RE.search(stderr)
    ):
        return _Failure("transient", retry_after, status, detail)
    return _Failure("blocked", None, status, detail)


def validate_pr_title(title: str) -> None:
    """Reject invalid creation data before any intent or request is dispatched."""
    if (
        not isinstance(title, str)
        or not title.strip()
        or _CONTROL_RE.search(title)
        or len(title) > 256
    ):
        raise ValueError("PR title must be one plain line of at most 256 characters")


class GitHub:
    """Read GitHub evidence and dispatch guarded merge or creation requests."""

    def __init__(
        self,
        host: str,
        full_name: str,
        deadline: float | None = None,
        *,
        runner: Runner | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not _HOST_RE.fullmatch(host):
            raise ValueError(f"invalid GitHub host: {_clean(host, 80)!r}")
        _check_repo(full_name)
        self.host = host
        self.full_name = full_name
        self.deadline = deadline
        self._runner: Runner = runner or _run_gh
        self._sleep: Callable[[float], None] = sleep or time.sleep
        self._clock: Callable[[], float] = clock or time.monotonic
        self._retries: list[RetryRecord] = []
        self._merge_capable = False

    @property
    def retries(self) -> tuple[RetryRecord, ...]:
        return tuple(self._retries)

    # -- transport ---------------------------------------------------------

    def _remaining(self) -> float | None:
        return None if self.deadline is None else self.deadline - self._clock()

    def _waiting(
        self, op: str, message: str, status: int | None = None, detail: str = ""
    ) -> ProviderError:
        return ProviderError(
            f"{op}: {message}",
            kind="WAITING",
            operation=op,
            http_status=status,
            detail=detail,
        )

    def _get(self, path: str, op: str) -> tuple[Any, dict[str, str]]:
        response = self._request(path, op, ())
        try:
            return json.loads(response.body), response.headers
        except ValueError as exc:
            raise _malformed(op, "response body is not JSON") from exc

    def _get_log(self, path: str, op: str) -> str:
        """Job log text. Workflow-controlled data: callers may extract identifiers only."""
        try:
            body = self._request(path, op, ("--allow-escape-sequences",)).body
        except ProviderError as exc:
            if exc.kind != "BLOCKED" or "unknown flag" not in exc.detail.lower():
                raise
            body = self._request(
                path, op, ()
            ).body  # gh too old for the flag: one plain read
        if len(body) > MAX_LOG_BYTES:
            raise ProviderError(
                f"{op}: job log exceeds {MAX_LOG_BYTES} bytes and was not analysed", kind="BLOCKED",
                operation=op, detail="log-too-large",
            )  # fmt: skip
        return body.decode("utf-8", "replace")

    def _request(self, path: str, op: str, extra: tuple[str, ...]) -> _Response:
        argv = (
            "gh", "api", "--method", "GET", "--include", "--hostname", self.host, *extra,
            "-H", "Accept: application/vnd.github+json",
            "-H", f"X-GitHub-Api-Version: {API_VERSION}",
            path,
        )  # fmt: skip
        return self._dispatch(argv, op)

    def _dispatch(self, argv: Sequence[str], op: str) -> _Response:
        """Run one read-only ``gh api`` call, retrying transient failures within the deadline."""
        attempt = 0
        while True:
            attempt += 1
            remaining = self._remaining()
            if remaining is not None and remaining <= 0:
                raise self._waiting(
                    op, "monitoring deadline reached before the provider read completed"
                )
            timeout = (
                CALL_TIMEOUT if remaining is None else min(CALL_TIMEOUT, remaining)
            )
            try:
                proc = self._runner(argv, timeout)
            except FileNotFoundError as exc:
                raise ProviderError(
                    f"{op}: the GitHub CLI 'gh' is not installed",
                    kind="BLOCKED",
                    operation=op,
                    detail="missing-gh",
                ) from exc
            except subprocess.TimeoutExpired:
                failure = _Failure("transient", None, None, "gh request timed out")
            else:
                response = _split_response(proc.stdout)
                if (
                    proc.returncode == 0
                    and response.status is not None
                    and 200 <= response.status < 300
                ):
                    return response
                failure = _failure(proc, response)
            self._after_failure(op, attempt, failure)

    def _after_failure(self, op: str, attempt: int, failure: _Failure) -> None:
        """Sleep and return when a retry is permitted, otherwise raise."""
        status = (
            "no HTTP status" if failure.status is None else f"HTTP {failure.status}"
        )
        if failure.kind == "blocked":
            hint = {
                401: "authentication failed; run `gh auth login`",
                403: "permission denied",
                404: "not found or not accessible to the authenticated account",
            }.get(failure.status or 0, "request rejected")
            if failure.status is None and "auth login" in failure.detail.lower():
                hint = "authentication failed; run `gh auth login`"
            raise ProviderError(
                f"{op}: {status} ({hint}): {failure.detail}",
                kind="BLOCKED", operation=op, http_status=failure.status, detail=failure.detail,
            )  # fmt: skip
        if failure.kind == "ratelimit" and failure.retry_after is None:
            raise self._waiting(
                op, f"{status} rate limited with no Retry-After; wait before resuming: {failure.detail}",
                failure.status,
            )  # fmt: skip
        if attempt >= MAX_ATTEMPTS:
            raise self._waiting(
                op, f"{status} after {attempt} attempts ({failure.kind}): {failure.detail}", failure.status
            )  # fmt: skip
        delay = (
            failure.retry_after
            if failure.retry_after is not None
            else RETRY_DELAYS[attempt - 1]
        )
        remaining = self._remaining()
        limit = NO_DEADLINE_RETRY_CAP if remaining is None else remaining
        if delay > limit:
            raise self._waiting(
                op, f"{status}; provider asks to wait {delay:g}s which exceeds the {limit:g}s available", failure.status
            )  # fmt: skip
        self._retries.append(
            RetryRecord(op, attempt, f"{failure.kind}: {status}", delay)
        )
        self._sleep(delay)

    def _object(self, path: str, op: str) -> _Obj:
        return _Obj.of(self._get(path, op)[0], op, "response")

    def _list(
        self, path: str, op: str, params: dict[str, str] | None = None
    ) -> list[Any]:
        """Fully paginate an array-valued endpoint."""
        items: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            query = urlencode({**(params or {}), "per_page": PER_PAGE, "page": page})
            data, headers = self._get(f"{path}?{query}", f"{op}#page{page}")
            if not isinstance(data, list):
                raise _malformed(op, "response is not an array")
            items.extend(data)
            if len(data) < PER_PAGE and not _NEXT_RE.search(headers.get("link", "")):
                return items
        raise ProviderError(
            f"{op}: more than {MAX_PAGES} pages; evidence is incomplete", kind="BLOCKED", operation=op,
            detail="pagination-limit",
        )  # fmt: skip

    def _wrapped(
        self, path: str, op: str, key: str, params: dict[str, str] | None = None
    ) -> list[_Obj]:
        """Paginate ``{total_count, <key>: [...]}`` and prove the whole set was read."""
        collected: dict[int, _Obj] = {}
        total = 0
        for page in range(1, MAX_PAGES + 1):
            query = urlencode({**(params or {}), "per_page": PER_PAGE, "page": page})
            data, headers = self._get(f"{path}?{query}", f"{op}#page{page}")
            top = _Obj.of(data, op, "response")
            total = top.integer("total_count")
            rows = top.objs(key)
            for row in rows:
                collected[row.integer("id")] = row
            if len(rows) < PER_PAGE and not _NEXT_RE.search(headers.get("link", "")):
                break
            if len(collected) >= total:
                break
        else:
            raise ProviderError(
                f"{op}: more than {MAX_PAGES} pages; evidence is incomplete", kind="BLOCKED",
                operation=op, detail="pagination-limit",
            )  # fmt: skip
        if len(collected) != total:
            raise self._waiting(
                op,
                f"provider reported {total} {key} but {len(collected)} were read; the set changed while paging",
            )
        return list(collected.values())

    # -- public API --------------------------------------------------------

    def list_prs(
        self, state: Literal["open", "closed"], full_name: str | None = None
    ) -> tuple[PullRequest, ...]:
        if state not in ("open", "closed"):
            raise ValueError(f"unsupported pull request state: {state!r}")
        target = full_name if full_name is not None else self.full_name
        _check_repo(target)
        op = f"list-prs:{target}:{state}"
        raw = self._list(
            f"{_repo_path(target)}/pulls",
            op,
            {"state": state, "sort": "created", "direction": "desc"},
        )
        result: dict[int, PullRequest] = {}
        for index, item in enumerate(raw):
            pr, _ = _parse_pr(item, op, detailed=False, path=f"response[{index}]")
            if pr.base_repo.lower() != target.lower():
                raise _malformed(
                    op, f"response[{index}] belongs to another base repository"
                )
            allowed = ("OPEN",) if state == "open" else ("CLOSED", "MERGED")
            if pr.state not in allowed:
                raise _malformed(
                    op,
                    f"response[{index}] state {pr.state} contradicts the {state} query",
                )
            result[pr.number] = pr
        return tuple(result.values())

    def find_prs(
        self, head_repo: str, head_ref: str, base_ref: str | None = None
    ) -> tuple[PullRequest, ...]:
        """Every PR of this base repository with exactly this head namespace/ref.

        Fully paginated over all states. The provider ``head`` filter only
        narrows the listing; every row is rechecked against the base repository,
        head repository, head ref, optional base ref and PR URL. A row the filter
        returned whose head repository is unreadable or whose identity contradicts
        the request raises: incomplete evidence is never an empty answer.
        """
        _check_repo(head_repo)
        branch = _branch_name(head_ref)
        owner = head_repo.split("/", 1)[0]
        params = {
            "state": "all",
            "head": f"{owner}:{branch}",
            "sort": "created",
            "direction": "desc",
        }
        if base_ref is not None:
            params["base"] = _branch_name(base_ref)
        op = f"find-prs:{self.full_name}:{owner}:{branch}"
        raw = self._list(f"{_repo_path(self.full_name)}/pulls", op, params)
        found: dict[int, PullRequest] = {}
        for index, item in enumerate(raw):
            pr, _ = _parse_pr(item, op, detailed=False, path=f"response[{index}]")
            if (
                pr.base_repo.lower() != self.full_name.lower()
                or pr.head_ref != branch
                or (base_ref is not None and pr.base_ref != params["base"])
                or not _pull_url_matches(pr.url, self.host, self.full_name, pr.number)
            ):
                raise _malformed(op, f"response[{index}] contradicts the exact query")
            if not pr.head_repo:
                raise ProviderError(
                    f"{op}: PR #{pr.number} matches the head label but its head repository is unreadable",
                    kind="BLOCKED", operation=op, detail="pr-match-incomplete",
                )  # fmt: skip
            if pr.head_repo.lower() != head_repo.lower():
                continue  # same owner, another repository: a different namespace
            found[pr.number] = pr
        return tuple(found.values())

    def create_pr(
        self,
        head_repo: str,
        head_ref: str,
        base_ref: str,
        title: str,
        body_file: Path,
    ) -> PullRequest:
        """Create one PR with one ``gh api`` POST; never retried.

        Title and body are plain data; the body is read by gh from
        ``body_file``. ``ProviderError.uncertain`` means the request may have
        reached GitHub: reconcile with :meth:`find_prs` before any retry.
        ``detail == "pr-already-exists"`` is GitHub's own duplicate refusal.
        """
        _check_repo(head_repo)
        branch = _branch_name(head_ref)
        base = _branch_name(base_ref)
        validate_pr_title(title)
        op = f"create-pr:{self.full_name}:{head_repo}:{branch}"
        head_owner, head_name = head_repo.split("/", 1)
        cross = head_repo.lower() != self.full_name.lower()
        argv = [
            "gh", "api", "--method", "POST", "--include", "--hostname", self.host,
            "-H", "Accept: application/vnd.github+json",
            "-H", f"X-GitHub-Api-Version: {API_VERSION}",
            "-f", f"title={title}",
            "-f", f"head={head_owner}:{branch}" if cross else f"head={branch}",
            "-f", f"base={base}",
            "-F", f"body=@{body_file}",
            "-F", "draft=false",
        ]  # fmt: skip
        if cross and head_owner.lower() == self.full_name.split("/", 1)[0].lower():
            argv += ["-f", f"head_repo={head_name}"]
        argv.append(f"{_repo_path(self.full_name)}/pulls")
        remaining = self._remaining()
        if remaining is not None and remaining < MIN_MUTATION_WINDOW:
            raise self._waiting(
                op,
                "too little monitoring time remains to create the PR; nothing was dispatched",
                detail="create-not-dispatched",
            )
        timeout = (
            CREATE_TIMEOUT if remaining is None else min(CREATE_TIMEOUT, remaining)
        )
        unsafe = "the PR may exist; reconcile the exact head/base before any retry"
        try:
            proc = self._runner(argv, timeout)
        except FileNotFoundError as exc:
            raise ProviderError(
                f"{op}: the GitHub CLI 'gh' is not installed; nothing was dispatched",
                kind="BLOCKED", operation=op, detail="missing-gh",
            ) from exc  # fmt: skip
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"{op}: gh did not finish within {timeout:g}s; {unsafe}",
                kind="WAITING", operation=op, uncertain=True, detail="create-uncertain-timeout",
            ) from exc  # fmt: skip
        except OSError as exc:
            raise ProviderError(
                f"{op}: running gh failed ({_clean(str(exc), 120)}); {unsafe}",
                kind="BLOCKED", operation=op, uncertain=True, detail="create-unknown-outcome",
            ) from exc  # fmt: skip
        response = _split_response(proc.stdout)
        if proc.returncode == 0 and response.status == 201:
            try:
                pr, _ = _parse_pr(
                    json.loads(response.body), op, detailed=False, path="response"
                )
            except (ValueError, ProviderError) as exc:
                raise ProviderError(
                    f"{op}: the create response is unreadable; {unsafe}",
                    kind="WAITING", operation=op, uncertain=True, detail="create-unreadable",
                ) from exc  # fmt: skip
            if (
                pr.state != "OPEN"
                or pr.base_repo.lower() != self.full_name.lower()
                or pr.head_repo.lower() != head_repo.lower()
                or (pr.head_ref, pr.base_ref) != (branch, base)
                or not _pull_url_matches(pr.url, self.host, self.full_name, pr.number)
            ):
                raise ProviderError(
                    f"{op}: the created PR identity contradicts the request; {unsafe}",
                    kind="BLOCKED", operation=op, uncertain=True, detail="create-contradiction",
                )  # fmt: skip
            return pr
        if proc.returncode < 0 or proc.returncode == 0:
            raise ProviderError(
                f"{op}: gh ended without a created PR (exit {proc.returncode}); {unsafe}",
                kind="WAITING", operation=op, uncertain=True, detail="create-unknown-outcome",
            )  # fmt: skip
        failure = _failure(proc, response)
        evidence = (
            response.body.decode("utf-8", "replace")
            + proc.stderr.decode("utf-8", "replace")
        ).lower()
        if failure.status == 422 and "pull request already exists" in evidence:
            raise ProviderError(
                f"{op}: GitHub reports an existing PR for this head and base",
                kind="BLOCKED", operation=op, http_status=422, detail="pr-already-exists",
            )  # fmt: skip
        if failure.kind == "ratelimit":
            raise self._waiting(
                op,
                f"rate limited; the PR was not created: {failure.detail}",
                failure.status,
            )
        if failure.kind == "transient" or failure.status is None:
            raise ProviderError(
                f"{op}: {failure.detail or 'transport failure'}; {unsafe}",
                kind="WAITING", operation=op, uncertain=True,
                http_status=failure.status, detail="create-uncertain-transport",
            )  # fmt: skip
        raise ProviderError(
            f"{op}: HTTP {failure.status} GitHub refused to create the PR: {failure.detail}",
            kind="BLOCKED", operation=op, http_status=failure.status, detail="create-rejected",
        )  # fmt: skip

    def branch_protected(self, full_name: str, ref: str) -> bool:
        """True when the branch is the default branch or any protection applies.

        A missing branch is accepted only after the readable, fully paginated
        branch inventory independently confirms absence. Rules remain required.
        """
        _check_repo(full_name)
        branch = _branch_name(ref)
        op = f"branch-protected:{full_name}:{branch}"
        repo = self._object(_repo_path(full_name), f"{op}:repository")
        if repo.text("full_name").lower() != full_name.lower():
            raise _malformed(op, "protection repository identity does not match")
        if repo.text("default_branch") == branch:
            return True
        path = f"{_repo_path(full_name)}/branches/{_ref_path(branch)}"
        try:
            protected = self._object(path, f"{op}:branch").flag("protected")
        except ProviderError as error:
            if error.http_status != 404:
                raise
            inventory = self._list(f"{_repo_path(full_name)}/branches", f"{op}:absence")
            names = [item.text("name") for item in _objects(inventory, op, "branches")]
            if branch in names or len(names) != len(set(names)):
                raise _malformed(
                    op, "branch absence inventory is contradictory"
                ) from error
            protected = (
                False  # No current branch entity; active rules are still read below.
            )
        if protected:
            return True
        rules = self._list(
            f"{_repo_path(full_name)}/rules/branches/{_ref_path(branch)}", f"{op}:rules"
        )
        _objects(rules, op, "rules")
        return bool(rules)

    def observe(self, number: int, *, assurance: str = "routine") -> Observation:
        _check_number(number)
        if assurance not in ASSURANCES:
            raise ValueError("assurance must be routine or high")
        op = f"observe:{self.full_name}#{number}"
        repo_path = _repo_path(self.full_name)
        issues: list[str] = []

        repo_obj = self._object(repo_path, f"{op}:repository")
        canonical = repo_obj.text("full_name")
        if canonical.lower() != self.full_name.lower():
            raise ProviderError(
                f"{op}: provider resolved the repository as {_clean(canonical, 120)}, not {self.full_name}",
                kind="BLOCKED", operation=op, detail="identity-mismatch",
            )  # fmt: skip
        default_branch = repo_obj.text("default_branch")

        pr, author = _parse_pr(
            self._get(f"{repo_path}/pulls/{number}", f"{op}:pull")[0],
            f"{op}:pull",
            detailed=True,
            path="response",
        )
        if pr.number != number or pr.base_repo.lower() != canonical.lower():
            raise _malformed(
                f"{op}:pull", "pull request identity does not match the request"
            )
        if not pr.head_repo:
            issues.append(
                "head-repository-unavailable: the provider reports no head repository for this pull request"
            )

        policy = self._policy(pr.base_ref, op, issues)
        if (
            policy.base_sha is not None
            and pr.state == "OPEN"
            and pr.base_sha != policy.base_sha
        ):
            raise self._waiting(
                op,
                "the live base ref disagrees with pull request metadata; observe again",
            )
        methods = _merge_methods(repo_obj, policy, issues)
        changed_at = (
            self._base_change(pr, canonical, op, issues)
            if assurance == "routine" and pr.state == "OPEN"
            else None
        )
        checks = self._checks(pr, canonical, op, issues, assurance, changed_at)
        head_contains_base = (
            self._head_contains_base(pr, issues)
            if assurance == "routine"
            and pr.state == "OPEN"
            and policy.require_current_base
            else None
        )
        approvals, changes_requested, reviews_known = self._reviews(
            pr, author, canonical, op, issues
        )

        # The state read above must still describe the PR, otherwise every
        # head/base-bound fact in this observation is stale.
        again, _ = _parse_pr(
            self._get(f"{repo_path}/pulls/{number}", f"{op}:pull-recheck")[0],
            f"{op}:pull-recheck", detailed=True, path="response",
        )  # fmt: skip
        if (again.head_sha, again.base_sha, again.base_ref, again.state) != (
            pr.head_sha, pr.base_sha, pr.base_ref, pr.state,
        ):  # fmt: skip
            raise self._waiting(
                op,
                "the pull request head/base/state changed during observation; observe again",
            )
        if policy.base_sha is not None:
            base_again = (
                self._object(
                    f"{repo_path}/branches/{_ref_path(pr.base_ref)}",
                    f"{op}:base-recheck",
                )
                .obj("commit")
                .sha("sha")
            )
            if base_again != policy.base_sha:
                raise self._waiting(
                    op, "the live base ref changed during observation; observe again"
                )

        pr = self._with_landing(pr)
        return Observation(
            repo=Repository(canonical, self.host, default_branch, methods),
            pr=pr,
            checks=checks,
            required_checks=tuple(sorted(policy.required_checks)),
            required_approvals=policy.required_approvals,
            approvals=approvals,
            changes_requested=changes_requested,
            policy_known=policy.known and reviews_known,
            issues=tuple(dict.fromkeys(issues)),
            require_current_base=policy.require_current_base,
            required_apps=tuple(sorted(policy.required_apps)),
            queue_required=policy.queue_required,
            assurance=assurance,
            head_contains_base=head_contains_base,
            base_changed_at=None if changed_at is None else changed_at.isoformat(),
        )

    # -- existing-PR facts, queue state and the guarded merge ----------------

    def read_pr(self, number: int) -> PullRequest:
        """Identity, state and landing facts of one existing PR; reads no CI evidence.

        REST API 2026-03-10 omits the legacy merge field. A MERGED PR is
        bound to GraphQL mergeCommit.oid and matching namespace/head/ref/state.
        base_sha records the PR base; base_tip reads the live branch.
        """
        _check_number(number)
        op = f"read-pr:{self.full_name}#{number}"
        repo_path = _repo_path(self.full_name)
        canonical = self._object(repo_path, f"{op}:repository").text("full_name")
        if canonical.lower() != self.full_name.lower():
            raise ProviderError(
                f"{op}: provider resolved the repository as {_clean(canonical, 120)}, not {self.full_name}",
                kind="BLOCKED", operation=op, detail="identity-mismatch",
            )  # fmt: skip
        pr, _ = _parse_pr(
            self._get(f"{repo_path}/pulls/{number}", f"{op}:pull")[0],
            f"{op}:pull", detailed=True, path="response",
        )  # fmt: skip
        if pr.number != number or pr.base_repo.lower() != canonical.lower():
            raise _malformed(
                f"{op}:pull", "pull request identity does not match the request"
            )
        if pr.head_repo and not _REPO_RE.fullmatch(pr.head_repo):
            raise _malformed(
                f"{op}:pull", "head repository is not a valid repository name"
            )
        if not _pull_url_matches(pr.url, self.host, canonical, number):
            raise _malformed(
                f"{op}:pull",
                "pull request URL does not name the requested host, repository and number",
            )
        return self._with_landing(pr)

    def base_tip(self, base_ref: str) -> str:
        """Commit the live ``base_ref`` branch points to now (never cached PR or run metadata)."""
        branch = _branch_name(base_ref)
        op = f"base-tip:{self.full_name}:{branch}"
        reply = self._object(
            f"{_repo_path(self.full_name)}/branches/{_ref_path(branch)}", op
        )
        if reply.text("name") != branch:
            raise ProviderError(
                f"{op}: provider resolved the branch as {_clean(reply.text('name'), 80)}, not {branch}",
                kind="BLOCKED", operation=op, detail="identity-mismatch",
            )  # fmt: skip
        commit = reply.obj("commit")
        tip = commit.sha("sha")
        url = commit.opt_text("url")
        if url is not None and not urlsplit(url).path.lower().endswith(
            f"/repos/{self.full_name}/commits/{tip}".lower()
        ):
            raise ProviderError(
                f"{op}: the branch commit belongs to a different repository",
                kind="BLOCKED", operation=op, detail="identity-mismatch",
            )  # fmt: skip
        return tip

    def landing_reachable(self, landing: str, base_tip: str) -> bool:
        """Whether commit ``landing`` is ``base_tip`` or one of its ancestors in this repository.

        ``True`` is proven by the merge base of ``landing...base_tip`` being
        ``landing`` with status ``ahead``/``identical``; ``behind``/``diverged``
        is a proven ``False``.  Everything else (unknown commit, no access,
        unsupported or contradictory metadata) raises ``ProviderError``.
        """
        _check_sha(landing, "landing")
        _check_sha(base_tip, "base tip")
        op = f"landing-reachable:{self.full_name}:{landing[:12]}...{base_tip[:12]}"
        reply = self._object(
            f"{_repo_path(self.full_name)}/compare/{landing}...{base_tip}?per_page=1&page=1",
            op,
        )
        owner = self.full_name.split("/", 1)[0]
        link = urlsplit(reply.text("permalink_url"))
        prefix = f"/{self.full_name}/compare/{owner}:"
        suffix = (
            link.path[len(prefix) :]
            if link.path.lower().startswith(prefix.lower())
            else ""
        )
        halves = suffix.lower().split(f"...{owner.lower()}:")
        api = urlsplit(reply.text("url"))
        api_host = "api.github.com" if self.host == "github.com" else self.host
        api_prefix = "" if self.host == "github.com" else "/api/v3"
        api_path = f"{api_prefix}/repos/{self.full_name}/compare/{landing}...{base_tip}"
        if (
            link.scheme != "https"
            or link.netloc.lower() != self.host.lower()
            or link.query
            or link.fragment
            or len(halves) != 2
            or any(not re.fullmatch(r"[0-9a-f]{7,64}", part) for part in halves)
            or not landing.startswith(halves[0])
            or not base_tip.startswith(halves[1])
            or api.scheme != "https"
            or api.netloc.lower() != api_host.lower()
            or api.path.lower() != api_path.lower()
            or api.query
            or api.fragment
        ):
            raise _malformed(
                op, "compare metadata does not name the requested full commits"
            )
        if reply.obj("base_commit").sha("sha") != landing:
            raise _malformed(
                op, "compare base commit is not the requested landing commit"
            )
        merge_base = reply.obj("merge_base_commit").sha("sha")
        ahead, behind = reply.integer("ahead_by"), reply.integer("behind_by")
        verdicts = {
            "identical": (
                ahead == 0 and behind == 0 and landing == base_tip == merge_base,
                True,
            ),
            "ahead": (
                ahead > 0
                and behind == 0
                and landing != base_tip
                and merge_base == landing,
                True,
            ),
            "behind": (
                behind > 0
                and ahead == 0
                and landing != base_tip
                and merge_base == base_tip,
                False,
            ),
            "diverged": (
                ahead > 0 and behind > 0 and merge_base not in (landing, base_tip),
                False,
            ),
        }
        verdict = verdicts.get(reply.text("status"))
        if verdict is None or not verdict[0]:
            raise _malformed(
                op, "compare status, counts and merge base contradict each other"
            )
        return verdict[1]

    def _with_landing(self, pr: PullRequest) -> PullRequest:
        if pr.state != "MERGED":
            return pr
        op = f"landing:{self.full_name}#{pr.number}"
        pull = self._graphql_pull(pr.number, _LANDING_QUERY, op)
        if (
            pull.text("state") != pr.state
            or not pull.flag("merged")
            or pull.sha("headRefOid") != pr.head_sha
            or pull.text("headRefName") != pr.head_ref
            or pull.text("baseRefName") != pr.base_ref
            or pull.text("url") != pr.url
            or pull.text("mergedAt") != pr.merged_at
        ):
            raise self._waiting(
                op, "REST and GraphQL landing identities disagree; observe again"
            )
        return replace(pr, merge_commit_sha=pull.obj("mergeCommit").sha("oid"))

    def _graphql_pull(self, number: int, query: str, op: str) -> _Obj:
        owner, name = self.full_name.split("/", 1)
        response = self._dispatch(
            (
                "gh",
                "api",
                "--method",
                "POST",
                "--include",
                "--hostname",
                self.host,
                "-f",
                f"query={query}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-F",
                f"number={number}",
                "graphql",
            ),
            op,
        )
        try:
            payload = json.loads(response.body)
        except ValueError as exc:
            raise _malformed(op, "response body is not JSON") from exc
        top = _Obj.of(payload, op, "response")
        if top.has("errors") and top.arr("errors"):
            errors = top.objs("errors")
            if any(
                error.opt_text("type") == "RATE_LIMITED"
                or _RATE_LIMIT_RE.search(error.opt_text("message") or "")
                for error in errors
            ):
                raise self._waiting(
                    op,
                    "GraphQL rate limit; resume when the budget recovers",
                    200,
                    "graphql-rate-limited",
                )
            raise ProviderError(
                f"{op}: GitHub did not return complete GraphQL evidence",
                kind="BLOCKED",
                operation=op,
                detail="graphql-evidence-unavailable",
            )
        repository = top.obj("data").obj("repository")
        if repository.text("nameWithOwner").lower() != self.full_name.lower():
            raise _malformed(op, "GraphQL repository identity does not match")
        pull = repository.obj("pullRequest")
        if pull.integer("number") != number:
            raise _malformed(op, "GraphQL PR number does not match")
        return pull

    def queue_state(self, number: int, expected_head: str) -> QueueState:
        """Merge-queue/auto-merge state of the open PR whose head is ``expected_head``."""
        _check_number(number)
        _check_sha(expected_head, "expected head")
        op = f"queue-state:{self.full_name}#{number}"
        gop = f"{op}:graphql"
        rest_auto = self._rest_auto_merge(number, expected_head, f"{op}:pull")
        pull = self._graphql_pull(number, _QUEUE_QUERY, gop)
        state = pull.text("state")
        if state not in ("OPEN", "CLOSED", "MERGED") or pull.flag("merged") != (
            state == "MERGED"
        ):
            raise _malformed(
                gop, "pull request state is unsupported or contradicts merged"
            )
        head = pull.sha("headRefOid")
        in_queue = pull.flag("isInMergeQueue")
        if not (pull.has("mergeQueueEntry") and pull.has("autoMergeRequest")):
            raise _malformed(gop, "queue fields are missing from the response")
        entry = pull.opt_obj("mergeQueueEntry")
        if entry is not None:
            entry.integer("position")
            if entry.text("state") not in _QUEUE_ENTRY_STATES:
                raise _malformed(gop, "merge queue entry state is unsupported")
        auto = pull.opt_obj("autoMergeRequest")
        if auto is not None and auto.text("mergeMethod") not in MERGE_QUEUE_METHODS:
            raise _malformed(gop, "auto-merge method is unsupported")
        if in_queue != (entry is not None):
            raise _malformed(gop, "isInMergeQueue contradicts mergeQueueEntry")
        self._require_unchanged(gop, state, head, expected_head)
        if entry is not None:
            return "QUEUED"
        if auto is not None or rest_auto:
            if (auto is not None) != rest_auto:
                raise self._waiting(
                    op,
                    "GraphQL and REST disagree about auto-merge; read the queue state again",
                    detail="queue-sources-disagree",
                )
            return "AUTO_MERGE"
        if self._rest_auto_merge(number, expected_head, f"{op}:pull-recheck"):
            raise self._waiting(
                op,
                "auto-merge appeared while the queue state was read; read it again",
                detail="queue-sources-disagree",
            )
        return "IDLE"

    def _rest_auto_merge(self, number: int, expected_head: str, op: str) -> bool:
        """Whether REST shows auto-merge armed; the PR must be open at ``expected_head``."""
        raw = self._get(f"{_repo_path(self.full_name)}/pulls/{number}", op)[0]
        pr, _ = _parse_pr(raw, op, detailed=True, path="response")
        if pr.number != number or pr.base_repo.lower() != self.full_name.lower():
            raise _malformed(op, "pull request identity does not match the request")
        self._require_unchanged(op, pr.state, pr.head_sha, expected_head)
        body = _Obj.of(raw, op, "response")
        if not body.has("auto_merge"):
            raise _malformed(op, "response.auto_merge is missing")
        return body.opt_obj("auto_merge") is not None

    def _require_unchanged(
        self, op: str, state: str, head: str, expected_head: str
    ) -> None:
        if state != "OPEN":
            raise self._waiting(
                op,
                f"the pull request is {state}, not open; read its state again",
                detail="state-changed",
            )
        if head != expected_head:
            raise self._waiting(
                op,
                f"the pull request head is {head[:12]}, not the expected {expected_head[:12]}; observe again",
                detail="head-changed",
            )

    def merge(self, number: int, expected_head: str, method: str) -> None:
        """Request a merge of PR ``number`` guarded by ``expected_head`` (never retried).

        Returns when gh accepted the command; that is not a merge.  On a
        merge-queue branch gh queues the PR or arms auto-merge (the queue picks
        the method); an already merged or queued PR also exits 0.  Callers
        reconcile with ``read_pr`` / ``queue_state`` after every outcome,
        including ``ProviderError(uncertain=True)``.
        """
        _check_number(number)
        _check_sha(expected_head, "expected head")
        if method not in MERGE_METHODS:
            raise ValueError(f"unsupported merge method: {_clean(str(method), 40)!r}")
        op = f"merge:{self.full_name}#{number}"
        self._require_merge_capability(op)
        remaining = self._remaining()
        if remaining is not None and remaining < MIN_MUTATION_WINDOW:
            raise self._waiting(
                op,
                f"fewer than {MIN_MUTATION_WINDOW:g}s remain before the monitoring deadline, too little to run the merge to completion; nothing was dispatched",
                detail="merge-not-dispatched",
            )
        timeout = MERGE_TIMEOUT if remaining is None else min(MERGE_TIMEOUT, remaining)
        argv = (
            "gh", "pr", "merge", str(number),
            "--repo", f"{self.host}/{self.full_name}",
            "--match-head-commit", expected_head,
            _MERGE_FLAGS[method],
        )  # fmt: skip
        try:
            proc = self._runner(argv, timeout)
        except FileNotFoundError as exc:
            raise ProviderError(
                f"{op}: the GitHub CLI 'gh' is not installed; nothing was dispatched",
                kind="BLOCKED", operation=op, detail="missing-gh",
            ) from exc  # fmt: skip
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"{op}: gh did not finish within {timeout:g}s; the merge may have been accepted, so do not retry it; read the pull request state",
                kind="WAITING", operation=op, uncertain=True, detail="merge-uncertain-timeout",
            ) from exc  # fmt: skip
        except OSError as exc:
            raise ProviderError(
                f"{op}: running gh failed ({_clean(str(exc), 120)}); the merge may have been dispatched, so do not retry it; read the pull request state",
                kind="BLOCKED", operation=op, uncertain=True, detail="merge-unknown-outcome",
            ) from exc  # fmt: skip
        if proc.returncode != 0:
            raise _merge_failure(
                op, proc.returncode, proc.stderr.decode("utf-8", "replace")
            )

    def retarget_pr(
        self, number: int, base_ref: str, expected_head: str, expected_old_base: str
    ) -> PullRequest:
        """Move open PR ``number`` from ``expected_old_base`` to ``base_ref`` (never retried).

        GitHub documents no atomic head/base guard for a pull request base
        edit: the authoritative ``read_pr`` before and after the single
        base-only ``PATCH .../pulls/<n>`` narrow the race but do not remove it.
        Callers hold the common-directory mutation lock and a durable intent
        before calling, never resend an unknown outcome blind, and renew gates
        afterwards: a new base changes GitHub's diff and test context.  An open
        PR already on ``base_ref`` at ``expected_head`` is returned without
        dispatch (provider auto-retarget or an earlier unknown outcome).
        Precheck drift (``retarget-state-changed`` / ``-head-changed`` /
        ``-base-changed``) and definite 4xx refusals (``retarget-rejected``) are
        not uncertain.  ``uncertain`` is true for a dispatch with an unknown
        outcome and for every failed verification after GitHub accepted the
        edit: as with ``merge``, a reread can lag an accepted request, so a
        reread still on the old base is not proof of refusal.
        """
        _check_number(number)
        _check_sha(expected_head, "expected head")
        base, old = _branch_name(base_ref), _branch_name(expected_old_base)
        for name in (base, old):
            if (
                name == "@"
                or name.startswith(("-", ".", "/"))
                or name.endswith((".", "/", ".lock"))
                or re.search(r"[\s~^:?*\[\\]|\.\.|//|/\.|@\{|\.lock/", name)
            ):
                raise ValueError(f"invalid branch reference: {_clean(name, 80)!r}")
        if base == old:
            raise ValueError("the new base must differ from the expected old base")
        op = f"retarget-pr:{self.full_name}#{number}"
        before = self.read_pr(number)
        self._retarget_drift(op, before, expected_head, accepted=False)
        if before.base_ref == base:
            return before  # already there: auto-retarget or an earlier unknown outcome
        if before.base_ref != old:
            raise ProviderError(
                f"{op}: the pull request base is {_clean(before.base_ref, 80)}, not the expected {old}; nothing was dispatched",
                kind="BLOCKED", operation=op, detail="retarget-base-changed",
            )  # fmt: skip
        self._retarget_dispatch(
            op,
            (
                "gh", "api", "--method", "PATCH", "--include", "--hostname", self.host,
                "-H", "Accept: application/vnd.github+json",
                "-H", f"X-GitHub-Api-Version: {API_VERSION}",
                "-f", f"base={base}",
                f"{_repo_path(self.full_name)}/pulls/{number}",
            ),
        )  # fmt: skip
        accepted = "GitHub accepted the base edit; reconcile with read_pr and never resend it blind"
        try:
            after = self.read_pr(number)
        except ProviderError as exc:
            raise ProviderError(
                f"{op}: the pull request could not be reread ({_clean(str(exc), 160)}); {accepted}",
                kind="WAITING", operation=op, uncertain=True, detail="retarget-unverified",
            ) from exc  # fmt: skip
        self._retarget_drift(op, after, expected_head, accepted=True)
        if after.base_ref != base:
            raise ProviderError(
                f"{op}: the pull request base reads {_clean(after.base_ref, 80)}, not {base}; {accepted}",
                kind="WAITING", operation=op, uncertain=True, detail="retarget-unverified",
            )  # fmt: skip
        return after

    def _retarget_dispatch(self, op: str, argv: tuple[str, ...]) -> None:
        """Run the one base-edit request; return only when GitHub answered 2xx."""
        remaining = self._remaining()
        if remaining is not None and remaining < MIN_MUTATION_WINDOW:
            raise self._waiting(
                op,
                f"fewer than {MIN_MUTATION_WINDOW:g}s remain before the monitoring deadline; nothing was dispatched",
                detail="retarget-not-dispatched",
            )
        timeout = CALL_TIMEOUT if remaining is None else min(CALL_TIMEOUT, remaining)
        unsafe = "the base may have changed; reconcile with read_pr and never resend it blind"
        try:
            proc = self._runner(argv, timeout)
        except FileNotFoundError as exc:
            raise ProviderError(
                f"{op}: the GitHub CLI 'gh' is not installed; nothing was dispatched",
                kind="BLOCKED", operation=op, detail="missing-gh",
            ) from exc  # fmt: skip
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"{op}: gh did not finish within {timeout:g}s; {unsafe}",
                kind="WAITING", operation=op, uncertain=True, detail="retarget-uncertain-timeout",
            ) from exc  # fmt: skip
        except OSError as exc:
            raise ProviderError(
                f"{op}: running gh failed ({_clean(str(exc), 120)}); {unsafe}",
                kind="BLOCKED", operation=op, uncertain=True, detail="retarget-unknown-outcome",
            ) from exc  # fmt: skip
        response = _split_response(proc.stdout)
        status = response.status
        if proc.returncode == 0 and status is not None and 200 <= status < 300:
            return
        failure = None if proc.returncode <= 0 else _failure(proc, response)
        if failure is not None and failure.kind == "ratelimit":
            raise self._waiting(
                op,
                f"rate limited; the base was not changed: {failure.detail}",
                failure.status,
                "retarget-rate-limited",
            )
        if (
            failure is not None
            and failure.kind == "blocked"
            and failure.status is not None
            and 400 <= failure.status < 500
        ):
            raise ProviderError(
                f"{op}: HTTP {failure.status} GitHub refused the base edit: {failure.detail}",
                kind="BLOCKED", operation=op, http_status=failure.status, detail="retarget-rejected",
            )  # fmt: skip
        reason = (
            f"gh exited {proc.returncode} without a confirmed edit"
            if failure is None
            else failure.detail or "transport failure"
        )
        raise ProviderError(
            f"{op}: {reason}; {unsafe}",
            kind="WAITING", operation=op, uncertain=True,
            http_status=None if failure is None else failure.status, detail="retarget-uncertain-transport",
        )  # fmt: skip

    @staticmethod
    def _retarget_drift(
        op: str, pr: PullRequest, expected_head: str, *, accepted: bool
    ) -> None:
        """Refuse a PR that is not open at ``expected_head``; ``accepted`` marks a post-edit read."""
        tail = (
            "GitHub accepted the base edit; reconcile with read_pr and never resend it blind"
            if accepted
            else "nothing was dispatched"
        )
        if pr.state != "OPEN":
            raise ProviderError(
                f"{op}: the pull request is {pr.state}, not open; {tail}",
                kind="BLOCKED", operation=op, uncertain=accepted, detail="retarget-state-changed",
            )  # fmt: skip
        if pr.head_sha != expected_head:
            raise ProviderError(
                f"{op}: the pull request head moved to {pr.head_sha[:12]}, not the expected {expected_head[:12]}; {tail}",
                kind="BLOCKED", operation=op, uncertain=accepted, detail="retarget-head-changed",
            )  # fmt: skip

    def _require_merge_capability(self, op: str) -> None:
        """Prove, once, that the installed gh offers every flag the guarded merge needs."""
        if self._merge_capable:
            return
        remaining = self._remaining()
        if remaining is not None and remaining <= 0:
            raise self._waiting(
                op,
                "monitoring deadline reached before the merge capability was verified; nothing was dispatched",
                detail="merge-not-dispatched",
            )
        timeout = HELP_TIMEOUT if remaining is None else min(HELP_TIMEOUT, remaining)
        try:
            proc = self._runner(("gh", "pr", "merge", "--help"), timeout)
        except FileNotFoundError as exc:
            raise ProviderError(
                f"{op}: the GitHub CLI 'gh' is not installed; nothing was dispatched",
                kind="BLOCKED", operation=op, detail="missing-gh",
            ) from exc  # fmt: skip
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ProviderError(
                f"{op}: the GitHub CLI merge capability could not be verified; nothing was dispatched",
                kind="WAITING", operation=op, detail="merge-capability-unverified",
            ) from exc  # fmt: skip
        text = (
            proc.stdout.decode("utf-8", "replace")
            + "\n"
            + proc.stderr.decode("utf-8", "replace")
        )
        missing = [
            flag
            for flag in _REQUIRED_MERGE_FLAGS
            if not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text)
        ]
        if proc.returncode != 0 or missing:
            raise ProviderError(
                f"{op}: the installed GitHub CLI cannot run a head-guarded merge "
                f"({', '.join(missing) or f'help exited {proc.returncode}'}); upgrade gh; nothing was dispatched",
                kind="BLOCKED", operation=op, detail="merge-capability-missing",
            )  # fmt: skip
        self._merge_capable = True

    # -- native stacks -----------------------------------------------------

    def read_native_stack(self, number: int) -> NativeStack:
        """Native stack ``number`` with every member read authoritatively, bottom to top."""
        _check_number(number)
        op = f"native-stack:{self.full_name}#{number}"
        path = f"{_repo_path(self.full_name)}/stacks/{number}"
        listing = _parse_stack_listing(
            self._get(path, f"{op}:stack")[0], f"{op}:stack", self.full_name, number
        )
        members = tuple(self.read_pr(entry.number) for entry in listing.entries)
        self._verify_stack_members(op, listing, members)
        again = _parse_stack_listing(
            self._get(path, f"{op}:stack-recheck")[0],
            f"{op}:stack-recheck", self.full_name, number,
        )  # fmt: skip
        if again != listing:
            raise self._waiting(
                op,
                "the native stack membership, heads or states changed while it was read; read it again",
                detail="native-stack-changed",
            )
        return NativeStack(number, listing.base_ref, members)

    def _verify_stack_members(
        self, op: str, listing: _StackListing, members: tuple[PullRequest, ...]
    ) -> None:
        size = len(listing.entries)
        for index, (entry, pr) in enumerate(zip(listing.entries, members, strict=True)):
            label = f"member #{pr.number}"
            if (pr.head_sha, pr.state) != (entry.head_sha, entry.state):
                raise self._waiting(
                    op,
                    f"{label} changed between the stack read and its pull request read; read it again",
                    detail="native-stack-changed",
                )
            if pr.head_repo.lower() != self.full_name.lower():
                raise _stack_mismatch(op, f"{label} head is not in {self.full_name}")
            identity = (
                pr.native_stack_number,
                pr.native_stack_position,
                pr.native_stack_size,
                pr.native_stack_base,
            )
            expected = (listing.number, index + 1, size, listing.base_ref)
            if not pr.native or identity != expected:
                raise _stack_mismatch(
                    op,
                    f"{label} reports stack (number, position, size, base) {identity}, not {expected}",
                )
            lower = members[:index]
            bases = {lower[-1].head_ref} if lower else {listing.base_ref}
            if pr.state == "OPEN" and all(m.state == "MERGED" for m in lower):
                bases.add(listing.base_ref)
            if pr.base_ref not in bases:
                raise _stack_mismatch(
                    op, f"{label} is based on {pr.base_ref}, not on the member below it"
                )
            if pr.state == "MERGED" and any(m.state != "MERGED" for m in lower):
                raise _stack_mismatch(op, f"{label} is merged above an unmerged member")

    def native_trunk_policy(self, stack: NativeStack) -> NativeTrunkPolicy:
        """Merge routing evidence of the stack base, whose rules govern every member."""
        op = f"native-policy:{self.full_name}#{stack.number}"
        repo_obj = self._object(_repo_path(self.full_name), f"{op}:repository")
        canonical = repo_obj.text("full_name")
        if canonical.lower() != self.full_name.lower():
            raise ProviderError(
                f"{op}: provider resolved the repository as {_clean(canonical, 120)}, not {self.full_name}",
                kind="BLOCKED", operation=op, detail="identity-mismatch",
            )  # fmt: skip
        issues: list[str] = []
        policy = self._policy(_branch_name(stack.base_ref), op, issues)
        methods = _merge_methods(repo_obj, policy, issues)
        if policy.queue_required:
            action: str | None = "merge_queue"
        elif policy.known:
            action = "direct_merge"
        else:
            action = None
        return NativeTrunkPolicy(
            trunk=stack.base_ref,
            action=action,
            methods=methods,
            policy_known=policy.known,
            issues=tuple(dict.fromkeys(issues)),
        )

    def start_native_merge(
        self, number: int, expected_head: str, method: str | None, action: str
    ) -> NativeMergeResult:
        """Request one async merge of the native prefix ending at PR ``number`` (never retried).

        ``expected_head`` guards PR ``number`` only.  A new request is returned
        ``pending`` with its UUID; a ``merged`` or ``enqueued`` result without
        one means the PR was already merged or already queued, and ``failed``
        carries GitHub's reason.  Reconcile every outcome, including
        ``ProviderError(uncertain=True)``, with ``read_native_merge`` and
        ``read_pr`` and never by sending the request again.
        """
        _check_number(number)
        _check_sha(expected_head, "expected head")
        if action not in NATIVE_MERGE_ACTIONS:
            raise ValueError(
                f"unsupported native merge action: {_clean(str(action), 40)!r}"
            )
        if action == "merge_queue" and method is not None:
            raise ValueError(
                "a merge_queue request takes no merge method; the queue rules select it"
            )
        if (action == "direct_merge" or method is not None) and (
            method not in MERGE_METHODS
        ):
            raise ValueError(f"unsupported merge method: {_clean(str(method), 40)!r}")
        op = f"native-merge:{self.full_name}#{number}"
        argv = [
            "gh", "api", "--method", "PUT", "--include", "--hostname", self.host,
            "-H", "Accept: application/vnd.github+json",
            "-H", f"X-GitHub-Api-Version: {API_VERSION}",
            "-f", f"sha={expected_head}",
            "-f", f"merge_action={action}",
            "-F", "bypass_rules=false",
        ]  # fmt: skip
        if method is not None:
            argv += ["-f", f"merge_method={method}"]
        argv.append(f"{_repo_path(self.full_name)}/pulls/{number}/merge-async")
        remaining = self._remaining()
        if remaining is not None and remaining < MIN_MUTATION_WINDOW:
            raise self._waiting(
                op,
                f"fewer than {MIN_MUTATION_WINDOW:g}s remain before the monitoring deadline; nothing was dispatched",
                detail="native-merge-not-dispatched",
            )
        timeout = MERGE_TIMEOUT if remaining is None else min(MERGE_TIMEOUT, remaining)
        unsafe = "the async merge may have been accepted, so do not retry it; read the pull requests and any request status"
        try:
            proc = self._runner(argv, timeout)
        except FileNotFoundError as exc:
            raise ProviderError(
                f"{op}: the GitHub CLI 'gh' is not installed; nothing was dispatched",
                kind="BLOCKED", operation=op, detail="missing-gh",
            ) from exc  # fmt: skip
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"{op}: gh did not finish within {timeout:g}s; {unsafe}",
                kind="WAITING", operation=op, uncertain=True, detail="native-merge-uncertain-timeout",
            ) from exc  # fmt: skip
        except OSError as exc:
            raise ProviderError(
                f"{op}: running gh failed ({_clean(str(exc), 120)}); {unsafe}",
                kind="BLOCKED", operation=op, uncertain=True, detail="native-merge-unknown-outcome",
            ) from exc  # fmt: skip
        response = _split_response(proc.stdout)
        if (
            proc.returncode == 0
            and response.status is not None
            and 200 <= response.status < 300
        ):
            return _accepted_native_merge(
                op, response, expected_head, method, action, unsafe
            )
        if proc.returncode <= 0:
            raise ProviderError(
                f"{op}: gh ended without an accepted request (exit {proc.returncode}); {unsafe}",
                kind="WAITING", operation=op, uncertain=True, detail="native-merge-unknown-outcome",
            )  # fmt: skip
        raise _native_merge_failure(op, proc, response, unsafe)

    def read_native_merge(self, number: int, uuid: str) -> NativeMergeResult:
        """Status of async merge request ``uuid`` of PR ``number``; ``enqueued`` is not merged."""
        _check_number(number)
        if not isinstance(uuid, str) or not _UUID_RE.fullmatch(uuid):
            raise ValueError("async merge request id must be a lowercase UUID")
        op = f"native-merge-status:{self.full_name}#{number}"
        path = f"{_repo_path(self.full_name)}/pulls/{number}/merge-async/{uuid}"
        try:
            raw = self._get(path, op)[0]
        except ProviderError as exc:
            if exc.http_status != 404:
                raise
            raise ProviderError(
                f"{op}: GitHub does not know async merge request {uuid} (results expire after 24 hours, "
                "or the request or pull request is not accessible); it is not evidence of a merge; "
                "reconcile from read_pr facts",
                kind="BLOCKED", operation=op, http_status=404, detail="native-merge-request-unknown",
            ) from exc  # fmt: skip
        result = _parse_native_result(raw, op)
        if result.uuid is not None and result.uuid != uuid:
            raise _malformed(op, "response.details.uuid does not echo the requested id")
        return replace(result, uuid=uuid)

    # -- policy ------------------------------------------------------------

    def _guard(self, issues: list[str], code: str, action: Callable[[], None]) -> bool:
        """Run a secondary evidence read; non-retryable failures become issues."""
        try:
            action()
        except ProviderError as exc:
            if exc.kind == "WAITING":
                raise
            issues.append(f"{code}: {_clean(str(exc), 300)}")
            return False
        return True

    def _policy(self, base_ref: str, op: str, issues: list[str]) -> _Policy:
        policy = _Policy()
        repo_path = _repo_path(self.full_name)
        ref = _ref_path(base_ref)
        protected: list[bool] = []
        fallback: list[str] = []

        def read_branch() -> None:
            branch = self._object(f"{repo_path}/branches/{ref}", f"{op}:branch")
            protected.append(branch.flag("protected"))
            policy.base_sha = branch.obj("commit").sha("sha")
            protection = branch.opt_obj("protection")
            summary = (
                protection.opt_obj("required_status_checks") if protection else None
            )
            if summary is not None:
                fallback.extend(
                    str(item)
                    for item in summary.arr("contexts")
                    if isinstance(item, str)
                )
                fallback.extend(
                    check.text("context") for check in summary.objs("checks")
                )

        if not self._guard(issues, "policy-unreadable", read_branch):
            policy.known = False

        def read_rules() -> None:
            raw = self._list(f"{repo_path}/rules/branches/{ref}", f"{op}:rules")
            for rule in _objects(raw, f"{op}:rules", "rules"):
                policy.apply_rule(rule, issues)

        if not self._guard(issues, "policy-unreadable", read_rules):
            policy.known = False

        if not protected or protected[0]:

            def read_protection() -> None:
                try:
                    data = self._get(
                        f"{repo_path}/branches/{ref}/protection", f"{op}:protection"
                    )[0]
                except ProviderError as exc:
                    if exc.http_status == 404 and "not protected" in exc.detail.lower():
                        return
                    raise
                policy.apply_protection(
                    _Obj.of(data, f"{op}:protection", "response"), issues
                )

            if not self._guard(issues, "policy-unreadable", read_protection):
                policy.known = False
                policy.required_checks.update(fallback)
                issues.append(
                    "approvals-policy-unknown: classic branch protection could not be read; required reviews are unknown"
                )
        return policy

    # -- checks ------------------------------------------------------------

    def _checks(
        self,
        pr: PullRequest,
        repo: str,
        op: str,
        issues: list[str],
        assurance: str,
        changed_at: datetime | None,
    ) -> tuple[Check, ...]:
        repo_path = _repo_path(repo)
        head = pr.head_sha
        runs: list[_Run] | None = None
        raw_checks: list[_Obj] | None = None
        statuses: list[_Obj] | None = None

        def read_checks() -> None:
            nonlocal raw_checks
            raw_checks = self._wrapped(
                f"{repo_path}/commits/{head}/check-runs",
                f"{op}:check-runs",
                "check_runs",
                {"filter": "all"},
            )

        def read_runs() -> None:
            nonlocal runs
            raw = self._wrapped(
                f"{repo_path}/actions/runs",
                f"{op}:actions-runs",
                "workflow_runs",
                {"head_sha": head},
            )
            runs = [_parse_run(item, f"{op}:actions-runs") for item in raw]

        def read_statuses() -> None:
            nonlocal statuses
            statuses = self._combined_statuses(repo_path, head, op)

        ok_checks = self._guard(issues, "checks-unavailable", read_checks)
        ok_runs = self._guard(issues, "actions-runs-unavailable", read_runs)
        ok_statuses = self._guard(issues, "statuses-unavailable", read_statuses)

        runs_by_suite: dict[int, _Run] = {}
        for run in runs or []:
            if run.head_sha != head:
                issues.append(
                    f"stale-run-rejected: workflow run {run.id} belongs to {run.head_sha[:12]}, not the PR head"
                )
                continue
            if run.check_suite_id is not None:
                runs_by_suite[run.check_suite_id] = run

        rows: list[_Row] = []
        unverified_apps: dict[str, int] = {}
        for raw in raw_checks or []:
            row = self._check_row(raw, pr, runs_by_suite, ok_runs, op, issues)
            if row is None:
                continue
            if row.run is None and row.check.app_slug != _ACTIONS_APP:
                unverified_apps[row.check.app_slug] = (
                    unverified_apps.get(row.check.app_slug, 0) + 1
                )
            rows.append(row)
        for app, count in sorted(unverified_apps.items()):
            issues.append(
                f"base-unverified: {count} check row(s) from app '{_clean(app, 80)}' carry no base association"
            )

        rows = self._settle_runs(rows, runs or [], pr, repo_path, op, issues)
        rows = _latest_per_publisher(rows)
        if assurance == "high":
            rows = self._prove_rows(rows, pr, repo, op, issues)
        else:
            rows = [_routine_row(row, pr, changed_at) for row in rows]
        checks = [
            row.check for row in sorted(rows, key=lambda r: (r.check.name, r.check_id))
        ]

        latest_status: dict[str, _Obj] = {}
        for item in statuses or []:
            context = item.text("context")
            current = latest_status.get(context)
            if current is None or item.integer("id") > current.integer("id"):
                latest_status[context] = item
        status_checks = [
            _status_check(item, head, op) for item in latest_status.values()
        ]
        if status_checks:
            issues.append(
                f"base-unverified: {len(status_checks)} commit status context(s) carry no base association"
            )
        checks.extend(sorted(status_checks, key=lambda c: c.name))

        if ok_checks and ok_statuses and not raw_checks and not statuses:
            issues.append(
                "no-ci-evidence: the provider reports no check runs and no commit statuses for the PR head"
            )
        return tuple(checks)

    def _combined_statuses(self, repo_path: str, head: str, op: str) -> list[_Obj]:
        collected: dict[int, _Obj] = {}
        total = 0
        for page in range(1, MAX_PAGES + 1):
            query = urlencode({"per_page": PER_PAGE, "page": page})
            data, headers = self._get(
                f"{repo_path}/commits/{head}/status?{query}",
                f"{op}:statuses#page{page}",
            )
            top = _Obj.of(data, f"{op}:statuses", "response")
            if top.sha("sha") != head:
                raise _malformed(
                    f"{op}:statuses", "combined status belongs to a different commit"
                )
            total = top.integer("total_count")
            rows = top.objs("statuses")
            for row in rows:
                collected[row.integer("id")] = row
            if (
                len(rows) < PER_PAGE and not _NEXT_RE.search(headers.get("link", ""))
            ) or len(collected) >= total:
                break
        if len(collected) != total:
            raise self._waiting(
                f"{op}:statuses",
                f"provider reported {total} statuses but {len(collected)} were read",
            )
        return list(collected.values())

    def _base_change(
        self, pr: PullRequest, repo: str, op: str, issues: list[str]
    ) -> datetime | None:
        """Time of the PR's latest base change; None if it was never retargeted.

        Both a manual ``base_ref_changed`` and an ``automatic_base_change_succeeded``
        (GitHub retargeting a stacked PR after its base branch merged) count.
        """
        latest: datetime | None = None

        def read() -> None:
            nonlocal latest
            events = f"{op}:events"
            raw = self._list(f"{_repo_path(repo)}/issues/{pr.number}/events", events)
            for item in _objects(raw, events, "events"):
                if item.text("event") not in _BASE_CHANGE_EVENTS:
                    continue
                moment = _timestamp(item.text("created_at"), events, "event created_at")
                if latest is None or moment > latest:
                    latest = moment

        self._guard(issues, "retarget-freshness-unavailable", read)
        return latest

    def _head_contains_base(self, pr: PullRequest, issues: list[str]) -> bool | None:
        """Whether the PR head already contains the current base commit (strict freshness)."""
        proven: list[bool] = []

        def read() -> None:
            proven.append(self.landing_reachable(pr.base_sha, pr.head_sha))

        self._guard(issues, "strict-base-unavailable", read)
        return proven[0] if proven else None

    def _prove_rows(
        self, rows: list[_Row], pr: PullRequest, repo: str, op: str, issues: list[str]
    ) -> list[_Row]:
        """Bind each pull_request-event job to the commit its checkout step actually emitted."""
        parents: dict[str, tuple[str, ...] | None] = {}
        proven: list[_Row] = []
        for row in rows:
            if not row.integration or row.synthetic:
                proven.append(row)
                continue
            context = self._checkout_context(row, pr, repo, parents, op)
            base = context.base
            if (
                base is None
                and not context.head_only
                and row.run_base is not None
                and row.run_base != pr.base_sha
            ):
                base = (
                    row.run_base
                )  # provably historical claim; kept only as stale evidence
            if context.issue:
                issues.append(context.issue)
            proven.append(
                replace(
                    row,
                    check=replace(row.check, base_sha=base, test_sha=context.test_sha),
                )
            )
        return proven

    def _checkout_context(
        self,
        row: _Row,
        pr: PullRequest,
        repo: str,
        parents: dict[str, tuple[str, ...] | None],
        op: str,
    ) -> _Context:
        repo_path = _repo_path(repo)
        label = f"'{_clean(row.check.name, 80)}' (job {row.check_id})"

        def unproven(code: str, detail: str) -> _Context:
            return _Context(
                None, None, f"{code}: {label}: NEEDS_JUDGMENT: {detail}", False
            )

        run = row.run
        if run is None:
            return unproven(
                "checkout-proof-unverified",
                "no workflow run is associated with the job",
            )
        if row.check.status != "completed":
            return _Context(
                None,
                None,
                f"checkout-proof-pending: {label}: WAITING: the job has not "
                "completed, so its checkout cannot be proven yet",
                False,
            )
        try:
            job = self._object(f"{repo_path}/actions/jobs/{row.check_id}", f"{op}:job")
            bound = (
                job.integer("run_id"),
                job.sha("head_sha"),
                job.text("name"),
                job.text("status"),
            )
            if bound != (run.id, pr.head_sha, row.check.name, "completed"):
                return unproven(
                    "checkout-job-mismatch",
                    "the provider job record does not match this check's run, head or name",
                )
            log = self._get_log(
                f"{repo_path}/actions/jobs/{row.check_id}/logs", f"{op}:job-log"
            )
        except ProviderError as exc:
            if exc.kind == "WAITING":
                raise
            return unproven("checkout-logs-unavailable", _clean(str(exc), 300))
        found = _checkout_commit(log, repo)
        if found.sha is None:
            return unproven(
                "checkout-proof-unverified", found.problem or "no checkout commit"
            )
        sha = found.sha
        if sha not in parents:
            try:
                commit = self._object(
                    f"{repo_path}/git/commits/{sha}", f"{op}:checkout-commit"
                )
                parents[sha] = tuple(p.text("sha") for p in commit.objs("parents"))
            except ProviderError as exc:
                if exc.kind == "WAITING":
                    raise
                parents[sha] = None
        merged_parents = parents[sha]
        if merged_parents is None:
            return unproven(
                "checkout-commit-unverified",
                "the checked-out commit's parents cannot be read from the provider",
            )
        if len(merged_parents) == 2 and merged_parents[1] == pr.head_sha:
            return _Context(merged_parents[0], sha, None, False)
        if sha == pr.head_sha:
            issue = f"checkout-head-only: {label}: the job tested the PR head without merging a base"
            return _Context(None, sha, issue, True)
        return unproven(
            "checkout-commit-mismatch",
            "the checked-out commit is neither the PR head nor a merge of it",
        )

    def _check_row(
        self,
        raw: _Obj,
        pr: PullRequest,
        runs_by_suite: dict[int, _Run],
        runs_known: bool,
        op: str,
        issues: list[str],
    ) -> _Row | None:
        name = raw.text("name")
        head = raw.text("head_sha")
        if head != pr.head_sha:
            issues.append(
                f"stale-check-rejected: '{_clean(name, 80)}' belongs to {_clean(head, 12)}, not the PR head"
            )
            return None
        status = _check_status(raw.text("status"), op)
        conclusion = raw.opt_text("conclusion")
        if status == "completed" and conclusion is None:
            raise _malformed(
                op, f"check '{_clean(name, 80)}' is completed without a conclusion"
            )
        if status != "completed":
            conclusion = None
        app = raw.opt_obj("app")
        slug = app.text("slug") if app is not None else "unknown-app"
        app_id = app.opt_integer("id") if app is not None else None
        if app_id is not None and app_id <= 0:
            raise _malformed(op, "check publisher app id must be positive")
        suite = raw.opt_obj("check_suite")
        suite_id = suite.opt_integer("id") if suite is not None else None
        run: _Run | None = None
        integration = False
        run_base: str | None = None
        if slug == _ACTIONS_APP:
            run = runs_by_suite.get(suite_id) if suite_id is not None else None
            if run is None:
                if runs_known:
                    issues.append(
                        f"actions-run-unresolved: no workflow run found for check '{_clean(name, 80)}'"
                    )
                else:
                    issues.append(
                        f"base-unverified: workflow run for check '{_clean(name, 80)}' is unreadable"
                    )
            else:
                included, integration, run_base, issue = _membership(run, pr)
                if issue:
                    issues.append(issue)
                if not included:
                    return None
        updated = (
            raw.opt_text("completed_at")
            or raw.opt_text("started_at")
            or (run.updated_at if run else None)
        )
        if updated is None:
            issues.append(
                f"check-timestamp-unknown: '{_clean(name, 80)}' has no timestamp"
            )
            updated = ""
        url = raw.opt_text("html_url") or raw.opt_text("details_url") or ""
        check = Check(
            name,
            head,
            None,
            status,
            conclusion,
            slug,
            url,
            updated,
            None,
            run.id if run else None,
            app_id,
            run.workflow_id if run else None,
            run.event if run else None,
            raw.integer("id"),
        )
        return _Row(check, raw.integer("id"), run, integration, run_base)

    def _latest_jobs(
        self, repo_path: str, run_id: int, op: str, issues: list[str]
    ) -> list[_Obj] | None:
        """The provider's current jobs, keeping distinct IDs even when names repeat.

        A partial rerun can carry jobs from earlier attempts. ``filter=latest``
        defines membership; display names cannot supersede another current job.
        """
        listed: list[_Obj] = []

        def read() -> None:
            jobs = self._wrapped(
                f"{repo_path}/actions/runs/{run_id}/jobs",
                f"{op}:run-jobs",
                "jobs",
                {"filter": "latest"},
            )
            for job in jobs:
                job.integer("id")
                job.text("name")
                _attempt(job, f"{op}:run-jobs", "job")
            listed.extend(jobs)

        return listed if self._guard(issues, "run-jobs-unavailable", read) else None

    def _settle_runs(
        self,
        rows: list[_Row],
        runs: list[_Run],
        pr: PullRequest,
        repo_path: str,
        op: str,
        issues: list[str],
    ) -> list[_Row]:
        """Judge only the newest applicable run of each (workflow, event), current attempt only.

        The newest run is derived from every observed applicable run of the PR
        head, not from the check rows that happen to exist: a newer run that is
        waiting, has no job, failed to start, or has not published a row for one
        of its jobs supersedes an older success.  Rows of older runs, and of
        earlier attempts of the newest run, are dropped.  The newest run's jobs
        come from the provider's jobs listing whenever its state is not settled
        by its rows alone; a listed job without a check row becomes a pending
        placeholder, and a run without any job reports its own pending or failed
        state.  The run's own known status is authoritative too: a run still
        going, or finished unsuccessfully, with no current pending or failed row
        reports itself, so stale or unpublished successful rows never cover it.
        Nothing missing is ever turned into success; unreadable jobs are
        reported as ``run-jobs-unavailable`` and keep every row.
        """
        newest: dict[tuple[int, str], _Run] = {}
        applicable: list[_Run] = []
        for run in runs:
            if run.head_sha != pr.head_sha or not _membership(run, pr)[0]:
                continue
            applicable.append(run)
            key = (run.workflow_id, run.event)
            if key not in newest or (run.run_number, run.id) > (
                newest[key].run_number,
                newest[key].id,
            ):
                newest[key] = run
        owned: dict[int, list[_Row]] = {}
        kept: list[_Row] = []
        for row in rows:
            if row.run is None:
                kept.append(row)
            else:
                owned.setdefault(row.run.id, []).append(row)
        publisher = next(
            (
                row.check.app_id
                for row in rows
                if row.check.app_slug == _ACTIONS_APP and row.check.app_id is not None
            ),
            None,
        )
        for key, run in newest.items():
            own = owned.get(run.id, [])
            names = [row.check.name for row in own]
            superseding = any(
                other.id != run.id and (other.workflow_id, other.event) == key
                for other in applicable
            )
            unsettled = (
                run.status != "completed"
                or run.run_attempt > 1
                or superseding
                or not own
                or len(set(names)) != len(names)
            )
            settled: list[_Row] = []
            jobs = self._latest_jobs(repo_path, run.id, op, issues) if unsettled else []
            if jobs is None:
                settled.extend(own)
                if len(set(names)) != len(names):
                    issues.append(
                        f"attempt-unresolved: workflow run {run.id} has several rows of one job name whose "
                        "attempts cannot be proven; all are kept"
                    )
            elif not unsettled:
                settled.extend(own)
            else:
                current = {job.integer("id") for job in jobs}
                listed = {job.text("name") for job in jobs}
                for row in own:
                    if row.check_id in current:
                        settled.append(row)
                    elif row.check.name in listed:
                        continue  # an earlier attempt, superseded by the listed job
                    else:
                        settled.append(row)
                        issues.append(
                            f"attempt-unresolved: workflow run {run.id} job '{_clean(row.check.name, 80)}' "
                            "is not in the provider's current job listing; it is kept"
                        )
                have = {row.check_id for row in own}
                settled.extend(
                    _job_placeholder(run, pr, job, publisher)
                    for job in jobs
                    if job.integer("id") not in have
                )
            # The run's own state is authoritative.  Rows may all be successes of an
            # earlier attempt, or of jobs the provider has not republished yet, while
            # the run is still going or has failed: then the run reports itself.
            # Successful jobs a re-run legitimately carries over never trigger this
            # while a current job is pending or failed, and a settled success needs
            # no evidence.
            if run.status == "completed":
                contradicted = run.conclusion not in (
                    None,
                    "success",
                    "skipped",
                    "neutral",
                ) and not any(
                    row.check.status == "completed"
                    and row.check.conclusion not in ("success", "skipped", "neutral")
                    for row in settled
                )
            else:
                contradicted = not any(
                    row.check.status != "completed" for row in settled
                )
            if contradicted:
                settled.extend(_run_placeholder(run, pr, publisher))
            kept.extend(settled)
        return kept

    # -- reviews -----------------------------------------------------------

    def _reviews(
        self, pr: PullRequest, author: str, repo: str, op: str, issues: list[str]
    ) -> tuple[int, bool, bool]:
        repo_path = _repo_path(repo)
        latest: dict[str, tuple[int, str, str | None, str]] = {}

        def read() -> None:
            raw = self._list(f"{repo_path}/pulls/{pr.number}/reviews", f"{op}:reviews")
            for review in _objects(raw, f"{op}:reviews", "reviews"):
                state = review.text("state").upper()
                user = review.opt_obj("user")
                if user is None or state not in (
                    "APPROVED",
                    "CHANGES_REQUESTED",
                    "DISMISSED",
                ):
                    continue
                login = user.text("login")
                entry = (
                    review.integer("id"),
                    state,
                    review.opt_text("commit_id"),
                    login,
                )
                if login.lower() not in latest or latest[login.lower()][0] < entry[0]:
                    latest[login.lower()] = entry

        if not self._guard(issues, "reviews-unavailable", read):
            issues.append(
                "approvals-unknown: review evidence is unreadable, so approvals are reported as zero"
            )
            return 0, False, False
        changes_requested = any(
            state == "CHANGES_REQUESTED" for _, state, _, _ in latest.values()
        )
        approvals = 0
        known = True
        for _, state, commit, login in sorted(latest.values()):
            if state != "APPROVED":
                continue
            if commit != pr.head_sha:
                issues.append(
                    f"stale-approval-ignored: approval by '{_clean(login, 60)}' is not on the current head"
                )
                continue
            if login.lower() == author.lower():
                issues.append(
                    f"self-approval-ignored: '{_clean(login, 60)}' authored this pull request"
                )
                continue
            counted = self._can_approve(repo_path, login, op, issues)
            if counted is None:
                known = False
            elif counted:
                approvals += 1
        return approvals, changes_requested, known

    def _can_approve(
        self, repo_path: str, login: str, op: str, issues: list[str]
    ) -> bool | None:
        """True/False when the reviewer's access is known, None when it cannot be verified."""
        verdict: list[bool] = []

        def read() -> None:
            permission = self._object(
                f"{repo_path}/collaborators/{quote(login, safe='')}/permission",
                f"{op}:reviewer-permission",
            )
            role = permission.opt_text("role_name") or permission.text("permission")
            verdict.append(role in ("admin", "maintain", "write"))

        if not self._guard(issues, "reviewer-permission-unverified", read):
            return None
        if not verdict[0]:
            issues.append(
                f"approval-not-counted: '{_clean(login, 60)}' lacks write access, "
                "so the approval does not satisfy review policy"
            )
        return verdict[0]


# --------------------------------------------------------------------------
# Parsing helpers


def _check_number(number: int) -> None:
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise ValueError("pull request number must be a positive integer")


def _check_sha(value: str, what: str) -> None:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ValueError(f"{what} must be a full lowercase object id")


def _pull_url_matches(url: str, host: str, repo: str, number: int) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme in ("http", "https")
        and parts.netloc.lower() == host.lower()
        and parts.path.lower() == f"/{repo}/pull/{number}".lower()
    )


def _merge_failure(op: str, returncode: int, stderr: str) -> ProviderError:
    """Classify a failed ``gh pr merge``: certain refusal / never dispatched, or uncertain."""
    text = _ANSI_RE.sub("", stderr)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    def pick(pattern: re.Pattern[str]) -> str:
        line = next(
            (ln for ln in lines if pattern.search(ln)), lines[0] if lines else ""
        )
        return _clean(line, 160)

    def fail(
        kind: Literal["BLOCKED", "WAITING"],
        code: str,
        message: str,
        *,
        uncertain: bool = False,
        status: int | None = None,
    ) -> ProviderError:
        return ProviderError(
            f"{op}: {message}", kind=kind, operation=op, uncertain=uncertain,
            http_status=status, detail=code,
        )  # fmt: skip

    unsafe = "the merge may have been dispatched, so do not retry it; read the pull request state"
    if returncode < 0:
        return fail(
            "WAITING", "merge-uncertain-signal",
            f"gh was terminated by signal {-returncode}; {unsafe}", uncertain=True,
        )  # fmt: skip
    if _HEAD_MOVED_RE.search(text):
        return fail(
            "WAITING", "merge-head-changed",
            "GitHub refused the merge: the pull request head no longer matches the verified head; nothing was merged; observe again",
        )  # fmt: skip
    if _BASE_MOVED_RE.search(text):
        return fail(
            "WAITING", "merge-base-changed",
            "GitHub refused the merge: the base branch moved; nothing was merged; observe again",
        )  # fmt: skip
    if _FLAG_ERROR_RE.search(text):
        return fail(
            "BLOCKED", "merge-usage-error",
            f"gh rejected the merge command before contacting GitHub: {pick(_FLAG_ERROR_RE)}",
        )  # fmt: skip
    if _AUTH_RE.search(text):
        return fail(
            "BLOCKED", "merge-unauthenticated",
            "authentication failed; run `gh auth login`; the merge was not accepted", status=401,
        )  # fmt: skip
    if _NOT_MERGEABLE_RE.search(text):
        return fail(
            "BLOCKED", "merge-not-mergeable",
            f"gh found the pull request not mergeable and did not request the merge: {pick(_NOT_MERGEABLE_RE)}",
        )  # fmt: skip
    if _RATE_LIMIT_RE.search(text):
        return fail(
            "WAITING", "merge-rate-limited",
            "GitHub rate-limited the request; the merge was not accepted; wait before resuming",
        )  # fmt: skip
    if _AMBIGUOUS_RE.search(text):
        return fail(
            "WAITING", "merge-uncertain-transport",
            f"gh reported a transport or server failure ({pick(_AMBIGUOUS_RE)}); {unsafe}",
            uncertain=True,
        )  # fmt: skip
    if _REJECTED_RE.search(text):
        found = _STATUS_RE.search(text)
        return fail(
            "BLOCKED", "merge-rejected",
            f"GitHub refused the merge: {pick(_REJECTED_RE)}",
            status=int(found.group(1)) if found else None,
        )  # fmt: skip
    return fail(
        "BLOCKED", "merge-unknown-outcome",
        f"gh exited {returncode} with an unrecognised failure ({pick(_REJECTED_RE)}); {unsafe}",
        uncertain=True,
    )  # fmt: skip


def _accepted_native_merge(
    op: str,
    response: _Response,
    expected_head: str,
    method: str | None,
    action: str,
    unsafe: str,
) -> NativeMergeResult:
    """Bind a 2xx ``merge-async`` reply to the exact request that was sent.

    Only ``pending`` (a new request) must echo the UUID, head, action, method and
    ``bypass_rules=false``; ``merged``/``enqueued``/``failed`` are returned as read.
    """
    try:
        result = _parse_native_result(json.loads(response.body), op)
    except (ValueError, ProviderError) as exc:
        raise ProviderError(
            f"{op}: the async merge response is unreadable; {unsafe}",
            kind="WAITING", operation=op, uncertain=True, detail="native-merge-unreadable",
        ) from exc  # fmt: skip
    if result.status != "pending":
        # 200 for a PR already merged or already queued (no new request), or failed.
        return result
    if not result.matches(action, method, expected_head):
        raise ProviderError(
            f"{op}: the accepted async merge request contradicts the request sent; {unsafe}",
            kind="BLOCKED", operation=op, uncertain=True, detail="native-merge-contradiction",
        )  # fmt: skip
    return result


def _native_merge_failure(
    op: str,
    proc: subprocess.CompletedProcess[bytes],
    response: _Response,
    unsafe: str,
) -> ProviderError:
    """Classify a failed ``merge-async`` PUT: definite refusal, known request, or uncertain."""
    failure = _failure(proc, response)
    evidence = (
        response.body.decode("utf-8", "replace")
        + "\n"
        + proc.stderr.decode("utf-8", "replace")
    )

    def fail(
        kind: Literal["BLOCKED", "WAITING"],
        code: str,
        message: str,
        *,
        uncertain: bool = False,
    ) -> ProviderError:
        return ProviderError(
            f"{op}: {message}", kind=kind, operation=op, uncertain=uncertain,
            http_status=failure.status, detail=code,
        )  # fmt: skip

    if failure.status == 409:
        try:
            existing = _parse_native_result(json.loads(response.body), op)
        except (ValueError, ProviderError):
            existing = None
        if existing is not None and existing.uuid is not None:
            return NativeMergeInProgress(
                f"{op}: GitHub already has async merge request {existing.uuid}; nothing new was "
                "requested; reconcile its options with read_native_merge",
                operation=op, existing=existing,
            )  # fmt: skip
    if failure.status in (409, 422) and _HEAD_MOVED_RE.search(evidence):
        return fail(
            "WAITING", "native-merge-head-changed",
            "GitHub refused the async merge: the pull request head no longer matches the expected head; nothing was merged; observe again",
        )  # fmt: skip
    if failure.status in (409, 422) and _BASE_MOVED_RE.search(evidence):
        return fail(
            "WAITING", "native-merge-base-changed",
            "GitHub refused the async merge: the base branch moved; nothing was merged; observe again",
        )  # fmt: skip
    if failure.kind == "ratelimit":
        return fail(
            "WAITING", "native-merge-rate-limited",
            f"GitHub rate-limited the request; the async merge was not accepted: {failure.detail}",
        )  # fmt: skip
    if failure.status == 401:
        return fail(
            "BLOCKED", "native-merge-unauthenticated",
            "authentication failed; run `gh auth login`; the async merge was not accepted",
        )  # fmt: skip
    if failure.kind == "transient" or failure.status is None:
        return fail(
            "WAITING", "native-merge-uncertain-transport",
            f"{failure.detail or 'transport failure'}; {unsafe}", uncertain=True,
        )  # fmt: skip
    if 400 <= failure.status < 500:
        return fail(
            "BLOCKED", "native-merge-rejected",
            f"HTTP {failure.status} GitHub refused the async merge: {failure.detail}",
        )  # fmt: skip
    return fail(
        "BLOCKED", "native-merge-unknown-outcome",
        f"HTTP {failure.status} unrecognised failure; {unsafe}", uncertain=True,
    )  # fmt: skip


def _check_repo(full_name: str) -> None:
    if not _REPO_RE.fullmatch(full_name) or ".." in full_name:
        raise ValueError(f"invalid repository name: {_clean(full_name, 80)!r}")


def _repo_path(full_name: str) -> str:
    owner, name = full_name.split("/", 1)
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _branch_name(ref: str) -> str:
    branch = ref.removeprefix("refs/heads/")
    if not branch or branch.startswith("refs/") or _CONTROL_RE.search(branch):
        raise ValueError(f"invalid branch reference: {_clean(ref, 80)!r}")
    return branch


def _ref_path(branch: str) -> str:
    return quote(branch, safe="/")


def _parse_pr(
    raw: Any, op: str, *, detailed: bool, path: str
) -> tuple[PullRequest, str]:
    o = _Obj.of(raw, op, path)
    provider_state = o.text("state")
    if provider_state not in ("open", "closed"):
        raise _malformed(
            op, f"{path}.state has unsupported value {_clean(provider_state, 20)!r}"
        )
    merged_at = o.opt_text("merged_at")
    if detailed:
        if o.flag("merged") != (merged_at is not None):
            raise _malformed(op, f"{path}.merged contradicts merged_at")
        if not o.has("mergeable"):
            raise _malformed(op, f"{path}.mergeable is missing")
    if provider_state == "open":
        if merged_at is not None:
            raise _malformed(op, f"{path} is open but has merged_at")
        state = "OPEN"
    else:
        state = "MERGED" if merged_at is not None else "CLOSED"
    head = o.obj("head")
    base = o.obj("base")
    head_repo = head.opt_obj("repo")
    stack = o.opt_obj("stack")
    stack_number, stack_position, stack_size, stack_base = (
        _stack_identity(stack, op, f"{path}.stack")
        if stack is not None
        else (None, None, None, None)
    )
    user = o.opt_obj("user")
    pr = PullRequest(
        number=o.integer("number"),
        url=o.text("html_url"),
        state=state,
        head_sha=head.sha("sha"),
        head_ref=head.text("ref"),
        head_repo=head_repo.text("full_name") if head_repo is not None else "",
        base_sha=base.sha("sha"),
        base_ref=base.text("ref"),
        base_repo=base.obj("repo").text("full_name"),
        merge_commit_sha=None,
        merged_at=merged_at,
        draft=o.flag("draft"),
        mergeable=o.opt_flag("mergeable") if detailed else None,
        native=stack is not None,
        native_stack_number=stack_number,
        native_stack_position=stack_position,
        native_stack_size=stack_size,
        native_stack_base=stack_base,
    )
    return pr, user.text("login") if user is not None else ""


def _stack_identity(
    stack: _Obj, op: str, path: str
) -> tuple[int | None, int | None, int | None, str | None]:
    """``(number, position, size, base ref)`` of a PR ``stack`` object; absent is None."""
    base = stack.obj("base")
    base.opt_sha("sha")
    ref = base.opt_text("ref")
    if ref is not None and (not ref or _CONTROL_RE.search(ref)):
        raise _malformed(op, f"{path}.base.ref is not a branch name")
    stack.opt_integer("id")
    number, position, size = (
        stack.opt_integer(key) for key in ("number", "position", "size")
    )
    for key, value in (("number", number), ("position", position), ("size", size)):
        if value is not None and value <= 0:
            raise _malformed(op, f"{path}.{key} is not a positive integer")
    if position is not None and size is not None and position > size:
        raise _malformed(op, f"{path}.position exceeds {path}.size")
    return number, position, size, ref


@dataclass(frozen=True)
class _StackEntry:
    number: int
    head_sha: str
    state: str


@dataclass(frozen=True)
class _StackListing:
    number: int
    base_ref: str
    entries: tuple[_StackEntry, ...]


def _stack_mismatch(op: str, detail: str) -> ProviderError:
    return ProviderError(
        f"{op}: native stack evidence is inconsistent: {_clean(detail)}",
        kind="BLOCKED",
        operation=op,
        detail="native-stack-mismatch",
    )


def _api_url_names(url: str, full_name: str, suffix: str) -> bool:
    """Whether an API ``url`` names ``/repos/<full_name><suffix>`` (case-insensitively)."""
    return urlsplit(url).path.lower().endswith(f"/repos/{full_name}{suffix}".lower())


def _parse_stack_listing(
    raw: Any, op: str, full_name: str, number: int
) -> _StackListing:
    """``GET .../stacks/<n>``: identity, base and the ordered, unique, same-repository members."""
    o = _Obj.of(raw, op, "response")
    if o.integer("number") != number or not _api_url_names(
        o.text("url"), full_name, f"/stacks/{number}"
    ):
        raise _stack_mismatch(
            op, f"the response does not describe stack {number} of {full_name}"
        )
    base_ref = o.obj("base").text("ref")
    if not base_ref or _CONTROL_RE.search(base_ref):
        raise _malformed(op, "response.base.ref is not a branch name")
    entries: list[_StackEntry] = []
    for index, item in enumerate(o.objs("pull_requests")):
        where = f"response.pull_requests[{index}]"
        member = item.integer("number")
        if member <= 0:
            raise _malformed(op, f"{where}.number is not positive")
        if any(entry.number == member for entry in entries):
            raise _stack_mismatch(op, f"pull request #{member} is listed twice")
        head = item.obj("head")
        urls = (
            (item.text("url"), f"/pulls/{member}"),
            (head.obj("repo").text("url"), ""),
            (item.obj("base").obj("repo").text("url"), ""),
        )
        if not all(_api_url_names(url, full_name, suffix) for url, suffix in urls):
            raise _stack_mismatch(
                op, f"member #{member} is not a pull request of {full_name}"
            )
        provider_state = item.text("state")
        merged_at = item.opt_text("merged_at")
        if provider_state == "open" and merged_at is None:
            state = "OPEN"
        elif provider_state == "closed":
            state = "MERGED" if merged_at is not None else "CLOSED"
        else:
            raise _malformed(op, f"{where}.state is not a pull request state")
        entries.append(_StackEntry(member, head.sha("sha"), state))
    if not entries:
        raise _stack_mismatch(op, f"stack {number} lists no pull requests")
    return _StackListing(number, base_ref, tuple(entries))


def _parse_native_result(raw: Any, op: str) -> NativeMergeResult:
    """Strict ``merge-async`` status body, with the request options it echoes."""
    top = _Obj.of(raw, op, "response")
    status = top.text("status")
    if status not in NATIVE_MERGE_STATUSES:
        raise _malformed(
            op, f"response.status has unsupported value {_clean(status, 30)!r}"
        )
    details = top.obj("details")
    uuid = details.opt_text("uuid")
    if uuid is not None and not _UUID_RE.fullmatch(uuid):
        raise _malformed(op, "response.details.uuid is not a lowercase UUID")
    landed = details.opt_sha("sha")
    if (status == "merged") != (landed is not None):
        raise _malformed(op, "response.details.sha contradicts response.status")
    action = details.opt_text("merge_action")
    if action is not None and action not in NATIVE_MERGE_ACTIONS:
        raise _malformed(op, "response.details.merge_action is not a merge action")
    method = details.opt_text("merge_method")
    if method is not None and method not in ("default", *MERGE_METHODS):
        raise _malformed(op, "response.details.merge_method is not a merge method")
    return NativeMergeResult(
        status=status,
        uuid=uuid,
        message=_clean(details.text("message")),
        sha=landed,
        expected_head_sha=details.opt_sha("expected_head_sha"),
        merge_action=action,
        merge_method=method,
        bypass_rules=details.opt_flag("bypass_rules"),
    )


@dataclass(frozen=True)
class _RunPR:
    number: int
    head_sha: str | None
    base_sha: str | None
    base_ref: str | None = None


@dataclass(frozen=True)
class _Run:
    id: int
    workflow_id: int
    event: str
    run_number: int
    check_suite_id: int | None
    head_sha: str
    head_branch: str | None
    head_repository: str | None
    created_at: datetime
    updated_at: str
    prs: tuple[_RunPR, ...]
    status: str
    run_attempt: int
    conclusion: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class _Row:
    check: Check
    check_id: int
    run: _Run | None
    integration: bool = False
    run_base: str | None = None
    synthetic: bool = False


@dataclass(frozen=True)
class _Context:
    """Outcome of binding one job to its actual checkout."""

    base: str | None
    test_sha: str | None
    issue: str | None
    head_only: bool


def _attempt(o: _Obj, op: str, what: str) -> int:
    """The provider's ``run_attempt`` of a workflow run or job: required, positive.

    It selects the current attempt of a run, so a missing or non-positive value
    is malformed evidence and is never defaulted to the first attempt.
    """
    attempt = o.integer("run_attempt")
    if attempt <= 0:
        raise _malformed(op, f"{what} run_attempt must be a positive integer")
    return attempt


def _parse_run(o: _Obj, op: str) -> _Run:
    head_repo = o.opt_obj("head_repository")
    prs = []
    for item in o.objs("pull_requests"):
        head = item.opt_obj("head")
        base = item.opt_obj("base")
        prs.append(
            _RunPR(
                item.integer("number"),
                head.opt_sha("sha") if head else None,
                base.opt_sha("sha") if base else None,
                base.opt_text("ref") if base else None,
            )
        )
    return _Run(
        id=o.integer("id"),
        workflow_id=o.integer("workflow_id"),
        event=o.text("event"),
        run_number=o.integer("run_number"),
        check_suite_id=o.opt_integer("check_suite_id"),
        head_sha=o.text("head_sha"),
        head_branch=o.opt_text("head_branch"),
        head_repository=head_repo.text("full_name") if head_repo else None,
        created_at=_timestamp(o.text("created_at"), op, "run created_at"),
        updated_at=o.opt_text("updated_at") or o.text("created_at"),
        prs=tuple(prs),
        status=o.text("status"),
        conclusion=o.opt_text("conclusion"),
        name=o.opt_text("name"),
        run_attempt=_attempt(o, op, "workflow run"),
    )


def _membership(
    run: _Run, pr: PullRequest
) -> tuple[bool, bool, str | None, str | None]:
    """Return (applicable, needs checkout proof, run-metadata base, issue).

    The run's PR metadata base is only a *claim*: it is never promoted to a
    tested base by itself (it may be the live base stamped onto an old run).
    It is kept only as stale evidence when it provably differs from the
    current base and no checkout proof is available.
    """
    if not run.event.startswith(_PR_EVENT_PREFIX):
        return True, False, None, None
    entry = next((p for p in run.prs if p.number == pr.number), None)
    if entry is None:
        mine = (
            not run.prs
            and bool(pr.head_repo)
            and run.head_repository == pr.head_repo
            and run.head_branch == pr.head_ref
        )
        if not mine:
            return (
                False,
                False,
                None,
                f"foreign-run-excluded: workflow run {run.id} is not associated with this pull request",
            )
    elif entry.head_sha is not None and entry.head_sha != pr.head_sha:
        return (
            False,
            False,
            None,
            f"stale-run-rejected: workflow run {run.id} was associated with a different head",
        )
    if run.event != "pull_request":
        return (
            True,
            False,
            None,
            f"base-unverified: workflow run {run.id} ({run.event}) does not test a merge with the base",
        )
    return True, True, entry.base_sha if entry is not None else None, None


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ")
_STEP_START_RE = re.compile(r"^##\[group\]Run (.*?)\s*$")
_CHECKOUT_STEP_RE = re.compile(r"^actions/checkout@\S+$")
_STEP_END_RE = re.compile(r"^(?:Post job cleanup\.|Cleaning up orphan processes)\s*$")
_SYNC_RE = re.compile(r"^Syncing repository: (\S+)\s*$")
_HEAD_COMMAND_RE = re.compile(r"^\[command\]\S*git log -1 --format=%H\s*$")


@dataclass(frozen=True)
class _CheckoutLog:
    """The commit emitted by the job's single actions/checkout step for one repository."""

    sha: str | None
    problem: str | None


def _checkout_commit(log: str, repository: str) -> _CheckoutLog:
    """Extract the commit emitted by the one actions/checkout step that synced ``repository``.

    Any ambiguity (several checkout steps for the repository, or a checkout step
    whose repository cannot be read) or missing emission is a ``problem``; this
    never guesses.  Only runner-generated structure inside the checkout step's own
    log segment is read, never other steps' output.
    """
    lines = [
        _TIMESTAMP_RE.sub("", _ANSI_RE.sub("", raw).lstrip("\ufeff"))
        for raw in log.splitlines()
    ]
    segments: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in lines:
        started = _STEP_START_RE.match(line)
        if started or _STEP_END_RE.match(line):
            current = None
            if started and _CHECKOUT_STEP_RE.match(started.group(1)):
                current = []
                segments.append((started.group(1).partition("@")[2], current))
            continue
        if current is not None:
            current.append(line)
    if not segments:
        return _CheckoutLog(None, "the job log contains no actions/checkout step")
    relevant: list[tuple[str, list[str]]] = []
    for ref, step in segments:
        synced = [m.group(1) for line in step if (m := _SYNC_RE.match(line))]
        if len(synced) != 1:
            return _CheckoutLog(
                None,
                "an actions/checkout step does not state a single synced repository",
            )
        if synced[0].lower() == repository.lower():
            relevant.append((ref, step))
    if not relevant:
        return _CheckoutLog(
            None, "no actions/checkout step synced the pull request's repository"
        )
    if len(relevant) > 1:
        return _CheckoutLog(
            None, "several actions/checkout steps synced the pull request's repository"
        )
    ref, segment = relevant[0]
    if not _SHA_RE.match(ref):
        return _CheckoutLog(
            None, "the actions/checkout step is not pinned to a full commit"
        )
    emitted = [
        segment[i + 1].strip().strip("'\"")
        for i, line in enumerate(segment[:-1])
        if _HEAD_COMMAND_RE.match(line)
    ]
    if len(emitted) != 1 or not _SHA_RE.match(emitted[0]):
        return _CheckoutLog(
            None, "the checkout step did not emit exactly one checked-out commit"
        )
    return _CheckoutLog(emitted[0], None)


def _check_status(value: str, op: str) -> str:
    if value == "completed":
        return "completed"
    if value == "in_progress":
        return "in_progress"
    if value in ("queued", "waiting", "requested", "pending"):
        return "queued"
    raise _malformed(op, f"unsupported check status {_clean(value, 40)!r}")


def _status_check(item: _Obj, head: str, op: str) -> Check:
    state = item.text("state")
    context = item.text("context")
    if state == "pending":
        status, conclusion = "in_progress", None
    elif state == "success":
        status, conclusion = "completed", "success"
    elif state in ("failure", "error"):
        status, conclusion = "completed", "failure"
    else:
        raise _malformed(
            f"{op}:statuses", f"unsupported status state {_clean(state, 40)!r}"
        )
    updated = item.opt_text("updated_at") or item.opt_text("created_at") or ""
    return Check(
        context,
        head,
        None,
        status,
        conclusion,
        "commit-status",
        item.opt_text("target_url") or "",
        updated,
    )


def _publisher_key(check: Check) -> tuple[str, str]:
    """Identity of a non-Actions check: its publisher app and name."""
    publisher = str(check.app_id) if check.app_id is not None else check.app_slug
    return publisher, check.name


def _latest_per_publisher(rows: list[_Row]) -> list[_Row]:
    """Keep the newest row per (publisher app, name) of checks no workflow run owns.

    The app id, not the slug, is the publisher authority; rows owned by a
    workflow run are settled by :meth:`GitHub._settle_runs` instead.
    """
    newest: dict[tuple[str, str], int] = {}
    for row in rows:
        if row.run is None and row.check.app_slug != _ACTIONS_APP:
            key = _publisher_key(row.check)
            newest[key] = max(newest.get(key, 0), row.check_id)
    return [
        row
        for row in rows
        if row.run is not None
        or row.check.app_slug == _ACTIONS_APP
        or newest[_publisher_key(row.check)] == row.check_id
    ]


def _pending_status(value: str | None) -> str:
    """``in_progress`` or ``queued``; a job or run that is not finished is never completed."""
    return "in_progress" if value == "in_progress" else "queued"


def _job_placeholder(
    run: _Run, pr: PullRequest, job: _Obj, publisher: int | None
) -> _Row:
    """A pending row for a job the provider lists but has published no check row for.

    Whatever the job reports, the placeholder is pending: a missing row is never
    turned into success.
    """
    job_id = job.integer("id")
    _, integration, run_base, _ = _membership(run, pr)
    check = Check(
        job.text("name"),
        pr.head_sha,
        None,
        _pending_status(job.opt_text("status")),
        None,
        _ACTIONS_APP,
        job.opt_text("html_url") or "",
        job.opt_text("started_at") or run.updated_at,
        None,
        run.id,
        publisher,
        run.workflow_id,
        run.event,
        job_id,
    )
    return _Row(check, job_id, run, integration, run_base, synthetic=True)


def _run_placeholder(run: _Run, pr: PullRequest, publisher: int | None) -> list[_Row]:
    """The only evidence of a current run with no job: pending, or its own failure.

    A run that is still going is pending.  A finished run without jobs that did
    not succeed (``startup_failure``, ``cancelled``...) reports that conclusion;
    a successful job-less run has nothing to report.
    """
    if run.status == "completed":
        if run.conclusion in (None, "success"):
            return []
        status, conclusion = "completed", run.conclusion
    else:
        status, conclusion = _pending_status(run.status), None
    _, integration, run_base, _ = _membership(run, pr)
    check = Check(
        run.name or f"workflow-{run.workflow_id}",
        pr.head_sha,
        None,
        status,
        conclusion,
        _ACTIONS_APP,
        "",
        run.updated_at,
        None,
        run.id,
        publisher,
        run.workflow_id,
        run.event,
        -run.id,
    )
    return [_Row(check, -run.id, run, integration, run_base, synthetic=True)]


def _routine_row(row: _Row, pr: PullRequest, changed_at: datetime | None) -> _Row:
    """Attach the provider-reported merge context of a ``pull_request`` job.

    Head-only rows (push and other events, statuses, other apps) keep no base.
    A ``pull_request`` job is *retargeted* (stale for the current base) when its
    run still names another base ref, or when its run was triggered before the
    PR's latest base change.  The trigger time (``run.created_at``) is immutable:
    a re-run of an old run keeps its original event commit and ref yet starts
    new jobs later, so job timestamps prove nothing.  The run metadata's base
    association is mutable and never proves that an older run tested the new
    base, even when both bases share a commit.
    """
    if not row.integration or row.run is None:
        return row
    entry = next((item for item in row.run.prs if item.number == pr.number), None)
    other_base = (
        entry is not None
        and entry.base_ref is not None
        and entry.base_ref != pr.base_ref
    )
    before_change = changed_at is not None and row.run.created_at < changed_at
    retargeted = other_base or before_change
    base = None if retargeted else row.run_base
    return replace(row, check=replace(row.check, base_sha=base, retargeted=retargeted))


# --------------------------------------------------------------------------
# Effective policy


class _Policy:
    def __init__(self) -> None:
        self.known = True
        self.base_sha: str | None = None
        self.required_checks: set[str] = set()
        self.required_apps: set[tuple[str, int]] = set()
        self.required_approvals = 0
        self.require_current_base = False
        self.queue_required = False
        self.allowed_methods: set[str] | None = None
        self.dropped_methods: set[str] = set()

    def _unevaluated(self, issues: list[str], source: str, what: str) -> None:
        self.known = False
        issues.append(
            f"unevaluated-policy: {source} requires {what}, which this observation cannot verify"
        )

    def _require_check(self, check: _Obj, integration_field: str) -> None:
        name = check.text("context")
        self.required_checks.add(name)
        app_id = check.opt_integer(integration_field)
        if app_id is not None and app_id != -1:
            if app_id <= 0:
                raise _malformed(
                    "required checks", "publisher integration id must be positive"
                )
            self.required_apps.add((name, app_id))

    def _restrict(self, methods: set[str]) -> None:
        self.allowed_methods = (
            methods if self.allowed_methods is None else self.allowed_methods & methods
        )

    def apply_rule(self, rule: _Obj, issues: list[str]) -> None:
        kind = rule.text("type")
        params = rule.opt_obj("parameters")
        label = f"ruleset rule '{_clean(kind, 60)}'"
        if kind == "pull_request":
            if params is None:
                raise _malformed("rules", "pull_request rule has no parameters")
            self.required_approvals = max(
                self.required_approvals,
                params.integer("required_approving_review_count"),
            )
            if params.opt_flag("require_code_owner_review"):
                self._unevaluated(issues, label, "code-owner review")
            if params.opt_flag("require_last_push_approval"):
                self._unevaluated(
                    issues, label, "approval by someone other than the last pusher"
                )
            if params.opt_flag("required_review_thread_resolution"):
                self._unevaluated(issues, label, "resolved review threads")
            if params.has("required_reviewers") and params.arr("required_reviewers"):
                self._unevaluated(issues, label, "specific required reviewers")
            if params.has("allowed_merge_methods"):
                self._restrict({str(m) for m in params.arr("allowed_merge_methods")})
        elif kind == "required_status_checks":
            if params is None:
                raise _malformed(
                    "rules", "required_status_checks rule has no parameters"
                )
            for check in params.objs("required_status_checks"):
                self._require_check(check, "integration_id")
            if params.opt_flag("strict_required_status_checks_policy"):
                self.require_current_base = True
        elif kind == "required_linear_history":
            self.dropped_methods.add("merge")
        elif kind == "required_signatures":
            self.dropped_methods.add("rebase")
        elif kind == "merge_queue":
            self.queue_required = True
            method = params.opt_text("merge_method") if params is not None else None
            if method is not None and method in MERGE_QUEUE_METHODS:
                self._restrict({method.lower()})
            else:
                self._unevaluated(
                    issues,
                    label,
                    "a merge-queue merge method this observation cannot read",
                )
        elif kind not in _IGNORED_RULES:
            self._unevaluated(issues, label, "a gate that is not modelled")

    def apply_protection(self, o: _Obj, issues: list[str]) -> None:
        checks = o.opt_obj("required_status_checks")
        if checks is not None:
            for context in checks.arr("contexts"):
                if isinstance(context, str):
                    self.required_checks.add(context)
            for check in checks.objs("checks"):
                self._require_check(check, "app_id")
            if checks.flag("strict"):
                self.require_current_base = True
        reviews = o.opt_obj("required_pull_request_reviews")
        if reviews is not None:
            self.required_approvals = max(
                self.required_approvals,
                reviews.integer("required_approving_review_count"),
            )
            if reviews.opt_flag("require_code_owner_reviews"):
                self._unevaluated(issues, "branch protection", "code-owner review")
            if reviews.opt_flag("require_last_push_approval"):
                self._unevaluated(
                    issues,
                    "branch protection",
                    "approval by someone other than the last pusher",
                )
        for key, drop in (
            ("required_linear_history", "merge"),
            ("required_signatures", "rebase"),
        ):
            feature = o.opt_obj(key)
            if feature is not None and feature.flag("enabled"):
                self.dropped_methods.add(drop)
        resolution = o.opt_obj("required_conversation_resolution")
        if resolution is not None and resolution.flag("enabled"):
            self._unevaluated(issues, "branch protection", "resolved conversations")


def _merge_methods(repo: _Obj, policy: _Policy, issues: list[str]) -> tuple[str, ...]:
    flags = {
        "merge": repo.opt_flag("allow_merge_commit"),
        "squash": repo.opt_flag("allow_squash_merge"),
        "rebase": repo.opt_flag("allow_rebase_merge"),
    }
    if any(value is None for value in flags.values()):
        policy.known = False
        issues.append(
            "merge-methods-unknown: the provider does not expose the repository merge settings to this account"
        )
        return ()
    methods = tuple(
        method
        for method in MERGE_METHODS
        if flags[method]
        and (policy.allowed_methods is None or method in policy.allowed_methods)
        and method not in policy.dropped_methods
    )
    if not methods:
        issues.append(
            "no-merge-method: no merge method is permitted by repository settings and rules"
        )
    return methods
