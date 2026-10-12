"""Read-only GitHub provider evidence for the ship workflow.

Everything here is an inspection: it issues ``gh api --method GET`` requests
through the user's ``gh`` credential store and never extracts tokens or
performs a write.  Provider responses are validated at the boundary; evidence
that cannot be established is reported through ``Observation.issues`` (or a
``ProviderError``) and never defaults to an empty or green answer.

Conventions the gate engine relies on
-------------------------------------
* ``Observation.issues`` entries are ``"<code>: <detail>"`` strings.  Any
  issue means some evidence is unknown, partial or anomalous; none may be
  silently ignored.
* ``policy_known=False`` means the required checks, required approvals,
  approvals, merge methods or strict-base policy are not fully authoritative;
  ``required_checks`` / ``required_approvals`` / ``approvals`` are then lower
  bounds only.
* ``Check.base_sha`` is set to the current base only with *checkout proof*: the
  completed job's own log shows exactly one ``actions/checkout`` step that
  synced the PR's repository and emitted a commit (``git log -1 --format=%H``),
  and ``git/commits`` shows that commit has parents ``[tested base, PR head]``.
  ``Check.test_sha`` is that commit and ``Check.run_id`` the workflow run.
  Timestamps, ``merge_commit_sha`` and workflow-run PR metadata are never
  enough: without proof ``base_sha`` is None (a provably different metadata
  base is kept as stale evidence) and a ``checkout-*`` issue whose detail
  contains ``NEEDS_JUDGMENT`` is reported.  Push and other non-merge events
  and non-Actions checks are head-only (``base_sha`` None).
* Trust boundary: job logs are produced by workflow code, which the PR itself
  can change.  Only runner-structured text inside the checkout step's segment
  is read and the commit it names is authenticated through ``git/commits``;
  that it truly tested the commit is not cryptographically provable.
* ``PullRequest.head_repo == ""`` means the provider reports no head
  repository (for example a deleted fork).
* ``GitHub(deadline=...)`` is an absolute ``time.monotonic()`` value.
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
from typing import Any, Literal
from urllib.parse import quote, urlencode

API_VERSION = "2026-03-10"
PER_PAGE = 100
MAX_PAGES = 200
MAX_ATTEMPTS = 3
RETRY_DELAYS = (1.0, 2.0)
CALL_TIMEOUT = 60.0
MAX_LOG_BYTES = 16 * 1024 * 1024
NO_DEADLINE_RETRY_CAP = 60.0
MERGE_METHODS = ("merge", "squash", "rebase")

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


class ProviderError(RuntimeError):
    """A provider read could not produce trustworthy evidence."""

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
    retry_after = _retry_after(response.headers.get("retry-after"))
    limited = status == 429 or (
        status == 403
        and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or retry_after is not None
            or "rate limit" in lowered
            or "abuse" in lowered
        )
    )
    if limited:
        return _Failure("ratelimit", retry_after, status, detail)
    if status in (500, 502, 503, 504) or (
        status is None and _NETWORK_RE.search(stderr)
    ):
        return _Failure("transient", retry_after, status, detail)
    return _Failure("blocked", None, status, detail)


class GitHub:
    """Read-only observer for one repository on one GitHub host."""

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
        if not _HOST_RE.match(host):
            raise ValueError(f"invalid GitHub host: {_clean(host, 80)!r}")
        _check_repo(full_name)
        self.host = host
        self.full_name = full_name
        self.deadline = deadline
        self._runner: Runner = runner or _run_gh
        self._sleep: Callable[[float], None] = sleep or time.sleep
        self._clock: Callable[[], float] = clock or time.monotonic
        self._retries: list[RetryRecord] = []

    @property
    def retries(self) -> tuple[RetryRecord, ...]:
        return tuple(self._retries)

    # -- transport ---------------------------------------------------------

    def _remaining(self) -> float | None:
        return None if self.deadline is None else self.deadline - self._clock()

    def _waiting(
        self, op: str, message: str, status: int | None = None
    ) -> ProviderError:
        return ProviderError(
            f"{op}: {message}", kind="WAITING", operation=op, http_status=status
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

    def branch_protected(self, full_name: str, ref: str) -> bool:
        """True when the branch is the default branch or any protection applies.

        Missing, inaccessible or unreadable protection evidence raises; it is
        never reported as unprotected.
        """
        _check_repo(full_name)
        branch = _branch_name(ref)
        op = f"branch-protected:{full_name}:{branch}"
        repo = self._object(_repo_path(full_name), f"{op}:repository")
        if repo.text("default_branch") == branch:
            return True
        if self._object(
            f"{_repo_path(full_name)}/branches/{_ref_path(branch)}", f"{op}:branch"
        ).flag("protected"):
            return True
        rules = self._list(
            f"{_repo_path(full_name)}/rules/branches/{_ref_path(branch)}", f"{op}:rules"
        )
        _objects(rules, op, "rules")
        return bool(rules)

    def observe(self, number: int) -> Observation:
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise ValueError("pull request number must be a positive integer")
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
        checks = self._checks(pr, canonical, op, issues)
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
        )

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
        self, pr: PullRequest, repo: str, op: str, issues: list[str]
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

        rows = self._deduplicate(rows, repo_path, op, issues)
        rows = self._prove_rows(rows, pr, repo, op, issues)
        checks = [
            row.check for row in sorted(rows, key=lambda r: (r.check.name, r.check_id))
        ]

        status_checks = [_status_check(item, head, op) for item in statuses or []]
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

    def _prove_rows(
        self, rows: list[_Row], pr: PullRequest, repo: str, op: str, issues: list[str]
    ) -> list[_Row]:
        """Bind each pull_request-event job to the commit its checkout step actually emitted."""
        parents: dict[str, tuple[str, ...] | None] = {}
        proven: list[_Row] = []
        for row in rows:
            if not row.integration:
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
            return unproven(
                "checkout-proof-pending",
                "the job has not completed, so its checkout cannot be proven yet",
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
        )
        return _Row(check, raw.integer("id"), run, integration, run_base)

    def _deduplicate(
        self, rows: list[_Row], repo_path: str, op: str, issues: list[str]
    ) -> list[_Row]:
        """Drop only rows superseded by a newer attempt/run of the same workflow job."""
        dropped: set[int] = set()
        by_run: dict[tuple[int, str], list[_Row]] = {}
        for row in rows:
            if row.run is not None:
                by_run.setdefault((row.run.id, row.check.name), []).append(row)
        attempts: dict[int, dict[int, int] | None] = {}
        for (run_id, name), group in by_run.items():
            if len(group) < 2:
                continue
            if run_id not in attempts:
                attempts[run_id] = self._job_attempts(repo_path, run_id, op, issues)
            job_attempts = attempts[run_id]
            if job_attempts is None or any(
                row.check_id not in job_attempts for row in group
            ):
                issues.append(
                    f"attempt-unresolved: workflow run {run_id} has several '{_clean(name, 80)}' rows whose attempts "
                    "cannot be proven; all are kept"
                )
                continue
            newest = max(job_attempts[row.check_id] for row in group)
            dropped.update(
                row.check_id for row in group if job_attempts[row.check_id] < newest
            )
        remaining = [row for row in rows if row.check_id not in dropped]
        newest_run: dict[tuple[int, str, str], tuple[int, int]] = {}
        for row in remaining:
            if row.run is not None:
                key = (row.run.workflow_id, row.run.event, row.check.name)
                newest_run[key] = max(
                    newest_run.get(key, (0, 0)), (row.run.run_number, row.check_id)
                )
        return [
            row
            for row in remaining
            if row.run is None
            or newest_run[(row.run.workflow_id, row.run.event, row.check.name)][0]
            == row.run.run_number
        ]

    def _job_attempts(
        self, repo_path: str, run_id: int, op: str, issues: list[str]
    ) -> dict[int, int] | None:
        result: dict[int, int] = {}

        def read() -> None:
            jobs = self._wrapped(
                f"{repo_path}/actions/runs/{run_id}/jobs",
                f"{op}:run-jobs",
                "jobs",
                {"filter": "all"},
            )
            for job in jobs:
                result[job.integer("id")] = job.integer("run_attempt")

        return result if self._guard(issues, "run-jobs-unavailable", read) else None

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


def _check_repo(full_name: str) -> None:
    if not _REPO_RE.match(full_name) or ".." in full_name:
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
    if stack is not None:
        stack.obj("base")
        for key in ("size", "position", "id", "number"):
            stack.opt_integer(key)
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
        merge_commit_sha=o.opt_sha("merge_commit_sha"),
        merged_at=merged_at,
        draft=o.flag("draft"),
        mergeable=o.opt_flag("mergeable") if detailed else None,
        native=stack is not None,
    )
    return pr, user.text("login") if user is not None else ""


@dataclass(frozen=True)
class _RunPR:
    number: int
    head_sha: str | None
    base_sha: str | None


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


@dataclass(frozen=True)
class _Row:
    check: Check
    check_id: int
    run: _Run | None
    integration: bool = False
    run_base: str | None = None


@dataclass(frozen=True)
class _Context:
    """Outcome of binding one job to its actual checkout."""

    base: str | None
    test_sha: str | None
    issue: str | None
    head_only: bool


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
