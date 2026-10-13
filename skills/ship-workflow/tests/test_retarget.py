"""``GitHub.retarget_pr`` against a stateful provider double.

``Forge`` models one pull request behind the documented REST/GraphQL shapes
``read_pr`` reads and the documented ``PATCH /repos/{owner}/{repo}/pulls/{n}``
edit; it is not vendor qualification of live GitHub behaviour.  Tests assert
the resulting provider state, the decoded request bodies and the call counts.
"""

from __future__ import annotations

import itertools
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from github_ops import GitHub, ProviderError, PullRequest

REPO = "acme/widget"
NUMBER = 7
REPO_PATH = f"/repos/{REPO}"
PULL = f"{REPO_PATH}/pulls/{NUMBER}"
TRUNK, PARENT, RELEASE = "main", "stack/parent", "release/1"
MERGE_DATE = "2026-10-13T12:00:00Z"


def sha(n: int) -> str:
    return f"{n:040x}"


HEAD, PUSHED, TRUNK_TIP, PARENT_TIP, RELEASE_TIP, LANDING = (
    sha(0xA1), sha(0xA2), sha(0xB1), sha(0xB2), sha(0xB3), sha(0xC1),
)  # fmt: skip


def answer(
    argv: Sequence[str],
    status: int,
    body: Any,
    headers: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    head = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
    out = f"HTTP/2.0 {status} X\r\n{head}\r\n{json.dumps(body)}".encode()
    ok = 200 <= status < 300
    err = b"" if ok else f"gh: error (HTTP {status})".encode()
    return subprocess.CompletedProcess(list(argv), 0 if ok else 1, out, err)


def fields(argv: Sequence[str]) -> dict[str, str]:
    """The request body gh builds from ``-f``/``-F`` pairs; raw input files are refused."""
    assert "--input" not in argv
    body: dict[str, str] = {}
    for flag, item in itertools.pairwise(argv):
        if flag in ("-f", "-F", "--field", "--raw-field"):
            name, _, value = item.partition("=")
            body[name] = value
    return body


@dataclass
class Forge:
    """One mutable pull request; ``mode`` fixes how the next PATCH behaves.

    ``apply`` edits and answers 200; ``applied-timeout`` edits and never answers;
    ``lost`` times out without effect; ``signal`` / ``oserror`` fail without
    effect; ``lagged`` edits but the next pull read still shows the old base;
    ``pushed`` edits while a push moves the head; ``unreadable`` edits but the
    next pull read is refused.  ``refusal`` answers with no effect.
    """

    state: str = "OPEN"
    head: str = HEAD
    base: str = PARENT
    title: str = "feat: child slice"
    body: str = "Stack-Id: s1"
    branches: dict[str, str] = field(
        default_factory=lambda: {
            TRUNK: TRUNK_TIP,
            PARENT: PARENT_TIP,
            RELEASE: RELEASE_TIP,
        }
    )
    mode: str = "apply"
    refusal: tuple[int, dict[str, Any], dict[str, str]] | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)
    patch_bodies: list[dict[str, str]] = field(default_factory=list)
    patch_timeouts: list[float] = field(default_factory=list)
    _lag: list[str] = field(default_factory=list, init=False)
    _refuse_reads: int = field(default=0, init=False)

    def __call__(
        self, argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        assert tuple(argv[:3]) == ("gh", "api", "--method"), argv
        method, target = argv[3], argv[-1]
        if target == "graphql":
            self.calls.append(("POST", "graphql"))
            return self._graphql(argv)
        path = target.split("?", 1)[0]
        self.calls.append((method, path))
        if method == "PATCH":
            return self._patch(argv, path, timeout)
        assert method == "GET", "provider reads must be GET"
        if path == REPO_PATH:
            return answer(argv, 200, {"full_name": REPO, "default_branch": TRUNK})
        assert path == PULL, f"unrouted provider read: {path}"
        if self._refuse_reads:
            self._refuse_reads -= 1
            return answer(argv, 404, {"message": "Not Found"})
        shown = self._lag.pop(0) if self._lag else self.base
        return answer(argv, 200, self.pull(shown))

    def pull(self, base: str) -> dict[str, Any]:
        merged = self.state == "MERGED"
        return {
            "number": NUMBER, "html_url": f"https://github.com/{REPO}/pull/{NUMBER}",
            "state": "open" if self.state == "OPEN" else "closed", "merged": merged,
            "merged_at": MERGE_DATE if merged else None, "draft": False, "mergeable": True,
            "title": self.title, "body": self.body, "user": {"login": "author"},
            "head": {"sha": self.head, "ref": "stack/child", "repo": {"full_name": REPO}},
            "base": {"sha": self.branches[base], "ref": base, "repo": {"full_name": REPO}},
        }  # fmt: skip

    def _graphql(self, argv: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        query = fields(argv)["query"]
        assert query.startswith("query") and "mutation" not in query.lower()
        merged = self.state == "MERGED"
        pr = {
            "number": NUMBER, "state": self.state, "merged": merged,
            "url": f"https://github.com/{REPO}/pull/{NUMBER}", "headRefOid": self.head,
            "headRefName": "stack/child", "baseRefName": self.base,
            "mergedAt": MERGE_DATE if merged else None,
            "mergeCommit": {"oid": LANDING} if merged else None,
        }  # fmt: skip
        data = {"data": {"repository": {"nameWithOwner": REPO, "pullRequest": pr}}}
        return answer(argv, 200, data)

    def _patch(
        self, argv: Sequence[str], path: str, timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        assert path == PULL, f"PATCH outside the pull request: {path}"
        body = fields(argv)
        self.patch_bodies.append(body)
        self.patch_timeouts.append(timeout)
        if self.mode == "lost":
            raise subprocess.TimeoutExpired(list(argv), timeout)
        if self.mode == "signal":
            return subprocess.CompletedProcess(list(argv), -9, b"", b"")
        if self.mode == "oserror":
            raise OSError("exec format error")
        if self.refusal is not None:
            return answer(argv, *self.refusal)
        target = body.get("base", self.base)
        if target not in self.branches:
            invalid = {"resource": "PullRequest", "field": "base", "code": "invalid"}
            return answer(
                argv, 422, {"message": "Validation Failed", "errors": [invalid]}
            )
        old, self.base = self.base, target
        self.title = body.get("title", self.title)
        self.body = body.get("body", self.body)
        self.state = {"closed": "CLOSED"}.get(body.get("state", ""), self.state)
        if self.mode == "lagged":
            self._lag.append(old)
        if self.mode == "pushed":
            self.head = PUSHED
        if self.mode == "unreadable":
            self._refuse_reads = 1
        if self.mode == "applied-timeout":
            raise subprocess.TimeoutExpired(list(argv), timeout)
        return answer(argv, 200, self.pull(self.base))


def client(forge: Forge, deadline: float | None = None) -> tuple[GitHub, list[float]]:
    sleeps: list[float] = []
    gh = GitHub(
        "github.com",
        REPO,
        deadline,
        runner=forge,
        sleep=sleeps.append,
        clock=lambda: 0.0,
    )
    return gh, sleeps


def retarget(gh: GitHub, base: str = TRUNK, old: str = PARENT) -> PullRequest:
    return gh.retarget_pr(NUMBER, base, HEAD, old)


def refused(gh: GitHub, base: str = TRUNK, old: str = PARENT) -> ProviderError:
    with pytest.raises(ProviderError) as raised:
        retarget(gh, base, old)
    return raised.value


READ_PR = [("GET", REPO_PATH), ("GET", PULL)]


# -- success and observed already-retargeted state ----------------------------


def test_retarget_moves_the_base_with_one_base_only_patch_between_authoritative_reads() -> (
    None
):
    forge = Forge()
    gh, sleeps = client(forge)

    pr = retarget(gh)

    assert (pr.state, pr.head_sha, pr.base_ref, pr.base_sha) == (
        "OPEN",
        HEAD,
        TRUNK,
        TRUNK_TIP,
    )
    assert forge.base == TRUNK
    assert forge.patch_bodies == [{"base": TRUNK}]
    assert forge.calls == [*READ_PR, ("PATCH", PULL), *READ_PR]
    assert (forge.title, forge.body, forge.state) == (
        "feat: child slice",
        "Stack-Id: s1",
        "OPEN",
    )
    assert sleeps == []


def test_retarget_accepts_a_fully_qualified_new_base_and_sends_the_branch_name() -> (
    None
):
    forge = Forge()
    gh, _ = client(forge)

    pr = retarget(gh, base=f"refs/heads/{TRUNK}")

    assert (pr.base_ref, forge.base) == (TRUNK, TRUNK)
    assert forge.patch_bodies == [{"base": TRUNK}]


def test_retarget_returns_an_already_retargeted_pull_request_without_dispatch() -> None:
    forge = Forge(base=TRUNK)  # the provider retargeted the child on its own
    gh, _ = client(forge)

    pr = retarget(gh)

    assert (pr.state, pr.head_sha, pr.base_ref, pr.base_sha) == (
        "OPEN",
        HEAD,
        TRUNK,
        TRUNK_TIP,
    )
    assert forge.patch_bodies == []
    assert forge.calls == READ_PR


# -- precheck refusals: definite, nothing dispatched --------------------------


@pytest.mark.parametrize(
    ("state", "head", "base", "detail"),
    [
        pytest.param("OPEN", PUSHED, PARENT, "retarget-head-changed", id="head-moved"),
        pytest.param(
            "OPEN", PUSHED, TRUNK, "retarget-head-changed", id="head-moved-retargeted"
        ),
        pytest.param("OPEN", HEAD, RELEASE, "retarget-base-changed", id="foreign-base"),
        pytest.param("MERGED", HEAD, PARENT, "retarget-state-changed", id="merged"),
        pytest.param("CLOSED", HEAD, PARENT, "retarget-state-changed", id="closed"),
    ],
)
def test_retarget_refuses_a_drifted_pull_request_without_dispatching(
    state: str, head: str, base: str, detail: str
) -> None:
    forge = Forge(state=state, head=head, base=base)
    gh, _ = client(forge)

    error = refused(gh)

    assert (error.kind, error.detail, error.uncertain) == ("BLOCKED", detail, False)
    assert forge.patch_bodies == []
    assert (forge.state, forge.head, forge.base) == (state, head, base)


# -- definite refusals of the dispatched edit ---------------------------------


@pytest.mark.parametrize(
    ("base", "refusal", "status"),
    [
        pytest.param("stack/gone", None, 422, id="base-branch-does-not-exist"),
        pytest.param(
            TRUNK,
            (403, {"message": "Resource not accessible by integration"}, {}),
            403,
            id="permission",
        ),
        pytest.param(TRUNK, (404, {"message": "Not Found"}, {}), 404, id="not-found"),
        pytest.param(
            TRUNK,
            (422, {"message": "Validation Failed", "errors": []}, {}),
            422,
            id="validation",
        ),
    ],
)
def test_retarget_definite_refusal_is_final_and_leaves_the_pull_request_unchanged(
    base: str,
    refusal: tuple[int, dict[str, Any], dict[str, str]] | None,
    status: int,
) -> None:
    forge = Forge(refusal=refusal)
    gh, sleeps = client(forge)

    error = refused(gh, base=base)

    assert (error.kind, error.detail, error.uncertain, error.http_status) == (
        "BLOCKED",
        "retarget-rejected",
        False,
        status,
    )
    assert (forge.base, forge.head, forge.state) == (PARENT, HEAD, "OPEN")
    assert forge.patch_bodies == [{"base": base}]
    assert sleeps == []


def test_retarget_rate_limit_is_a_definite_wait_and_not_retried() -> None:
    limited = (
        403,
        {"message": "API rate limit exceeded"},
        {"x-ratelimit-remaining": "0"},
    )
    forge = Forge(refusal=limited)
    gh, sleeps = client(forge)

    error = refused(gh)

    assert (error.kind, error.detail, error.uncertain) == (
        "WAITING",
        "retarget-rate-limited",
        False,
    )
    assert forge.base == PARENT
    assert len(forge.patch_bodies) == 1
    assert sleeps == []


# -- unknown outcomes: uncertain, never resent --------------------------------


def test_retarget_applied_but_unanswered_is_uncertain_and_reconciles_without_resend() -> (
    None
):
    forge = Forge(mode="applied-timeout")
    gh, sleeps = client(forge)

    error = refused(gh)

    assert (error.kind, error.detail, error.uncertain) == (
        "WAITING",
        "retarget-uncertain-timeout",
        True,
    )
    assert forge.calls == [*READ_PR, ("PATCH", PULL)]  # no reread, no resend
    assert gh.read_pr(NUMBER).base_ref == TRUNK  # the facts show the edit applied
    forge.mode = "apply"
    pr = retarget(gh)  # reconciling call observes the applied edit
    assert (pr.base_ref, pr.head_sha) == (TRUNK, HEAD)
    assert len(forge.patch_bodies) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    ("mode", "refusal", "kind", "detail"),
    [
        pytest.param(
            "lost", None, "WAITING", "retarget-uncertain-timeout", id="timeout"
        ),
        pytest.param(
            "apply",
            (503, {"message": "Service Unavailable"}, {}),
            "WAITING",
            "retarget-uncertain-transport",
            id="server-error",
        ),
        pytest.param(
            "apply",
            (501, {"message": "Not Implemented"}, {}),
            "WAITING",
            "retarget-uncertain-transport",
            id="unclassified-server-error",
        ),
        pytest.param(
            "signal", None, "WAITING", "retarget-uncertain-transport", id="signal"
        ),
        pytest.param(
            "oserror", None, "BLOCKED", "retarget-unknown-outcome", id="os-error"
        ),
    ],
)
def test_retarget_unknown_outcome_without_effect_is_uncertain_and_not_retried(
    mode: str,
    refusal: tuple[int, dict[str, Any], dict[str, str]] | None,
    kind: str,
    detail: str,
) -> None:
    forge = Forge(mode=mode, refusal=refusal)
    gh, sleeps = client(forge)

    error = refused(gh)

    assert (error.kind, error.detail, error.uncertain) == (kind, detail, True)
    assert forge.calls == [*READ_PR, ("PATCH", PULL)]
    assert sleeps == []
    assert gh.read_pr(NUMBER).base_ref == PARENT  # the facts show nothing applied


# -- post-edit verification ---------------------------------------------------


def test_retarget_accepted_but_reread_on_the_old_base_is_uncertain_not_rejected() -> (
    None
):
    forge = Forge(mode="lagged")
    gh, _ = client(forge)

    error = refused(gh)

    assert (error.kind, error.detail, error.uncertain) == (
        "WAITING",
        "retarget-unverified",
        True,
    )
    assert len(forge.patch_bodies) == 1
    assert gh.read_pr(NUMBER).base_ref == TRUNK  # a later read shows the accepted edit


def test_retarget_accepted_but_unreadable_afterwards_is_uncertain() -> None:
    forge = Forge(mode="unreadable")
    gh, _ = client(forge)

    error = refused(gh)

    assert (error.kind, error.detail, error.uncertain) == (
        "WAITING",
        "retarget-unverified",
        True,
    )
    assert forge.base == TRUNK
    assert len(forge.patch_bodies) == 1


def test_retarget_head_pushed_during_the_edit_is_a_head_moved_verification_failure() -> (
    None
):
    forge = Forge(mode="pushed")
    gh, _ = client(forge)

    error = refused(gh)

    assert (error.kind, error.detail, error.uncertain) == (
        "BLOCKED",
        "retarget-head-changed",
        True,
    )
    assert (forge.base, forge.head) == (TRUNK, PUSHED)
    assert len(forge.patch_bodies) == 1


# -- deadline ------------------------------------------------------------------


def test_retarget_with_an_expired_deadline_makes_no_provider_call() -> None:
    forge = Forge()
    gh, _ = client(forge, deadline=0.0)

    error = refused(gh)

    assert error.kind == "WAITING" and error.uncertain is False
    assert forge.calls == []
    assert forge.base == PARENT


def test_retarget_without_time_to_finish_reads_but_never_dispatches() -> None:
    forge = Forge()
    gh, _ = client(forge, deadline=5.0)

    error = refused(gh)

    assert (error.kind, error.detail, error.uncertain) == (
        "WAITING",
        "retarget-not-dispatched",
        False,
    )
    assert forge.calls == READ_PR
    assert forge.base == PARENT


def test_retarget_edit_is_bounded_by_the_remaining_deadline() -> None:
    forge = Forge()
    gh, _ = client(forge, deadline=30.0)

    retarget(gh)

    assert forge.patch_timeouts == [30.0]


# -- argument validation -------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "base", "head", "old"),
    [
        pytest.param(0, TRUNK, HEAD, PARENT, id="zero"),
        pytest.param(-3, TRUNK, HEAD, PARENT, id="negative"),
        pytest.param(True, TRUNK, HEAD, PARENT, id="bool"),
        pytest.param("7", TRUNK, HEAD, PARENT, id="string-number"),
        pytest.param(NUMBER, TRUNK, HEAD[:12], PARENT, id="short-head"),
        pytest.param(NUMBER, TRUNK, HEAD.upper(), PARENT, id="uppercase-head"),
        pytest.param(NUMBER, PARENT, HEAD, PARENT, id="same-base"),
        pytest.param(
            NUMBER, f"refs/heads/{PARENT}", HEAD, PARENT, id="same-base-qualified"
        ),
        pytest.param(NUMBER, "--force", HEAD, PARENT, id="option-like-base"),
        pytest.param(NUMBER, "-main", HEAD, PARENT, id="dash-base"),
        pytest.param(NUMBER, "main branch", HEAD, PARENT, id="space-base"),
        pytest.param(NUMBER, "main\x00", HEAD, PARENT, id="nul-base"),
        pytest.param(NUMBER, "", HEAD, PARENT, id="empty-base"),
        pytest.param(NUMBER, "a..b", HEAD, PARENT, id="dot-dot-base"),
        pytest.param(NUMBER, "refs/tags/v1", HEAD, PARENT, id="tag-base"),
        pytest.param(NUMBER, TRUNK, HEAD, "-parent", id="option-like-old-base"),
        pytest.param(NUMBER, TRUNK, HEAD, "stack/parent\n", id="newline-old-base"),
    ],
)
def test_retarget_rejects_invalid_arguments_before_any_provider_call(
    number: Any, base: Any, head: Any, old: Any
) -> None:
    forge = Forge()
    gh, _ = client(forge)

    with pytest.raises(ValueError):
        gh.retarget_pr(number, base, head, old)

    assert forge.calls == []
    assert forge.base == PARENT
