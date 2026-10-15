"""Provider-evidence tests driven by deterministic gh runner doubles.

The fixtures model documented GitHub REST/GraphQL shapes and documented
``gh pr merge`` behaviour (see ``Provider``); they are not vendor qualification
of any live provider behaviour, merge queue, auto-merge or fork permission.
"""

from __future__ import annotations

import itertools
import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import github_ops
import pytest
from github_ops import GitHub, Observation, ProviderError

REPO = "acme/widget"
NUMBER = 7


def sha(n: int) -> str:
    return f"{n:040x}"


HEAD, BASE, OLD_BASE, MERGE, OTHER_HEAD = sha(1), sha(2), sha(3), sha(4), sha(5)
MERGE_DATE = "2026-10-12T12:00:00Z"
AFTER_MERGE = "2026-10-12T12:05:00Z"
BEFORE_MERGE = "2026-10-12T11:00:00Z"


@dataclass
class Reply:
    status: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    stderr: str | None = None
    raw: str | None = None
    exit_code: int | None = None  # gh exit status when it differs from the HTTP outcome


Route = Reply | list[Reply] | Callable[[dict[str, str]], Reply]


def render(argv: Sequence[str], reply: Reply) -> subprocess.CompletedProcess[bytes]:
    text = {
        200: "OK",
        403: "Forbidden",
        404: "Not Found",
        429: "Too Many Requests",
        503: "Service Unavailable",
    }
    head = "".join(f"{k}: {v}\r\n" for k, v in reply.headers.items())
    out = f"HTTP/2.0 {reply.status} {text.get(reply.status, 'X')}\r\n{head}\r\n"
    body = reply.raw if reply.raw is not None else json.dumps(reply.body)
    ok = (
        reply.exit_code == 0
        if reply.exit_code is not None
        else 200 <= reply.status < 300
    )
    err = (
        ""
        if ok
        else (
            reply.stderr
            if reply.stderr is not None
            else f"gh: error (HTTP {reply.status})"
        )
    )
    return subprocess.CompletedProcess(
        list(argv),
        0 if ok else (reply.exit_code or 1),
        (out + body).encode(),
        err.encode(),
    )


class FakeGH:
    """Runner double: routes by API path, records every argv."""

    def __init__(self, routes: dict[str, Route]) -> None:
        self.routes = dict(routes)
        self.argvs: list[tuple[str, ...]] = []

    def paths(self) -> list[str]:
        return [urlsplit(argv[-1]).path for argv in self.argvs]

    def count(self, path: str) -> int:
        return self.paths().count(path)

    def __call__(
        self, argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        self.argvs.append(tuple(argv))
        split = urlsplit(argv[-1])
        if split.path not in self.routes:
            raise AssertionError(f"unrouted provider read: {split.path}")
        route = self.routes[split.path]
        if callable(route):
            reply = route(dict(parse_qsl(split.query)))
        elif isinstance(route, list):
            reply = route.pop(0) if len(route) > 1 else route[0]
        else:
            reply = route
        return render(argv, reply)


def paged(rows: list[Any]) -> Callable[[dict[str, str]], Reply]:
    def route(query: dict[str, str]) -> Reply:
        size, page = int(query["per_page"]), int(query["page"])
        return Reply(body=rows[(page - 1) * size : page * size])

    return route


def wrapped(
    key: str, rows: list[Any], total: int | None = None
) -> Callable[[dict[str, str]], Reply]:
    def route(query: dict[str, str]) -> Reply:
        size, page = int(query["per_page"]), int(query["page"])
        return Reply(
            body={
                "total_count": len(rows) if total is None else total,
                key: rows[(page - 1) * size : page * size],
            }
        )

    return route


def pull(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "number": NUMBER,
        "html_url": f"https://github.com/{REPO}/pull/{NUMBER}",
        "state": "open",
        "merged": False,
        "merged_at": None,
        "draft": False,
        "mergeable": True,
        "user": {"login": "author"},
        "head": {"sha": HEAD, "ref": "feat/x", "repo": {"full_name": REPO}},
        "base": {"sha": BASE, "ref": "main", "repo": {"full_name": REPO}},
    }
    body.update(over)
    return body


def check_run(
    cid: int,
    name: str,
    *,
    suite: int | None = 100,
    head: str = HEAD,
    status: str = "completed",
    conclusion: str | None = "success",
    app: str = "github-actions",
) -> dict[str, Any]:
    return {
        "id": cid, "name": name, "head_sha": head, "status": status, "conclusion": conclusion,
        "started_at": AFTER_MERGE, "completed_at": AFTER_MERGE if status == "completed" else None,
        "html_url": f"https://github.com/{REPO}/runs/{cid}", "details_url": None,
        "app": {"slug": app}, "check_suite": {"id": suite} if suite is not None else None,
    }  # fmt: skip


def run(
    rid: int,
    *,
    suite: int,
    event: str = "pull_request",
    workflow: int = 5,
    number: int = 1,
    created: str = AFTER_MERGE,
    base: str | None = BASE,
    prs: list[dict[str, Any]] | None = None,
    head: str = HEAD,
) -> dict[str, Any]:
    if prs is None:
        prs = (
            [{"number": NUMBER, "head": {"sha": head}, "base": {"sha": base}}]
            if base
            else []
        )
    return {
        "id": rid, "workflow_id": workflow, "event": event, "run_number": number, "check_suite_id": suite,
        "head_sha": head, "head_branch": "feat/x", "head_repository": {"full_name": REPO},
        "created_at": created, "updated_at": created, "pull_requests": prs,
        "status": "completed", "conclusion": "success", "run_attempt": 1,
    }  # fmt: skip


def review(rid: int, login: str, state: str, commit: str = HEAD) -> dict[str, Any]:
    return {"id": rid, "state": state, "commit_id": commit, "user": {"login": login}}


def merge_commit(parents: list[str] | None = None) -> Reply:
    return Reply(body={"sha": MERGE, "parents": [{"sha": p} for p in (parents or [BASE, HEAD])],
                       "committer": {"date": MERGE_DATE}})  # fmt: skip


def permission(role: str = "write") -> Reply:
    return Reply(body={"permission": role, "role_name": role})


def routes() -> dict[str, Route]:
    base = f"/repos/{REPO}"
    table: dict[str, Route] = {
        base: Reply(
            body={
                "full_name": REPO,
                "default_branch": "main",
                "allow_merge_commit": True,
                "allow_squash_merge": True,
                "allow_rebase_merge": False,
            }
        ),
        f"{base}/pulls/{NUMBER}": Reply(body=pull()),
        f"{base}/branches/main": Reply(
            body={"protected": False, "commit": {"sha": BASE}}
        ),
        f"{base}/rules/branches/main": Reply(body=[]),
        f"{base}/commits/{HEAD}/check-runs": wrapped("check_runs", []),
        f"{base}/actions/runs": wrapped("workflow_runs", []),
        f"{base}/commits/{HEAD}/status": Reply(
            body={"sha": HEAD, "state": "success", "total_count": 0, "statuses": []}
        ),
        f"{base}/pulls/{NUMBER}/reviews": paged([]),
        f"{base}/git/commits/{MERGE}": merge_commit(),
    }
    return table


def make(table: dict[str, Route], **kwargs: Any) -> tuple[GitHub, FakeGH, list[float]]:
    fake = FakeGH(table)
    sleeps: list[float] = []
    return (
        GitHub(
            "github.com",
            REPO,
            runner=fake,
            sleep=sleeps.append,
            clock=lambda: 0.0,
            **kwargs,
        ),
        fake,
        sleeps,
    )


def checkout_log(
    sha: str, repo: str = REPO, *, extra: str = "", with_bom: bool = False
) -> str:
    """Runner-structured job log in the shape emitted by a pinned actions/checkout step."""
    stamp = "2026-10-12T12:05:0{}.1234567Z "
    body = [
        "Current runner version: '2.337.0'",
        "##[group]Run actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
        "with:",
        f"  repository: {repo}",
        "##[endgroup]",
        f"Syncing repository: {repo}",
        "##[group]Fetching the repository",
        f"[command]/usr/bin/git -c protocol.version=2 fetch --no-tags --depth=1 origin +{sha}:refs/remotes/pull/7/merge",
        "##[endgroup]",
        "[command]/usr/bin/git log -1 --format=%H",
        sha,
        "##[group]Run actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405",
        "##[endgroup]",
        "Post job cleanup.",
    ]
    text = "".join(
        stamp.format(i % 10) + line + "\r\n" for i, line in enumerate(body[:-1])
    )
    text += extra + stamp.format(9) + body[-1] + "\r\n"
    return ("\ufeff" if with_bom else "") + text.replace(
        "##[group]", "\x1b[36;1m##[group]\x1b[0m", 1
    )


def job_routes(
    runs: list[dict[str, Any]], checks: list[dict[str, Any]], sha: str = MERGE
) -> dict[str, Route]:
    """Provider job record + checkout log for every pull_request-event Actions job."""
    suites = {r["check_suite_id"]: r for r in runs}
    table: dict[str, Route] = {}
    for check in checks:
        owner = suites.get((check["check_suite"] or {}).get("id"))
        if (
            check["app"]["slug"] != "github-actions"
            or owner is None
            or owner["event"] != "pull_request"
        ):
            continue
        path = f"/repos/{REPO}/actions/jobs/{check['id']}"
        table[path] = Reply(body={"id": check["id"], "run_id": owner["id"], "head_sha": check["head_sha"],
                                  "name": check["name"], "status": check["status"], "run_attempt": 1})  # fmt: skip
        table[path + "/logs"] = Reply(raw=checkout_log(sha))
    return table


def with_ci(
    runs: list[dict[str, Any]], checks: list[dict[str, Any]], **extra: Route
) -> dict[str, Route]:
    base = f"/repos/{REPO}"
    table = routes()
    table[f"{base}/actions/runs"] = wrapped("workflow_runs", runs)
    table[f"{base}/commits/{HEAD}/check-runs"] = wrapped("check_runs", checks)
    table.update(job_routes(runs, checks))
    table.update(extra)
    return table


def observe(table: dict[str, Route], assurance: str = "high") -> Observation:
    return make(table)[0].observe(NUMBER, assurance=assurance)


def by_name(obs: Observation) -> dict[str, github_ops.Check]:
    return {c.name: c for c in obs.checks}


def has_issue(obs: Observation, code: str) -> bool:
    return any(i.startswith(code + ":") for i in obs.issues)


# --------------------------------------------------------------------------
# Identity and native membership


def test_fork_pr_resolves_head_and_base_repositories_separately() -> None:
    fork = pull(
        head={"sha": HEAD, "ref": "feat/x", "repo": {"full_name": "fork-owner/widget"}}
    )
    obs = observe(routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=fork)})
    assert (obs.pr.head_repo, obs.pr.base_repo, obs.repo.full_name) == (
        "fork-owner/widget",
        REPO,
        REPO,
    )
    assert (
        obs.pr.state == "OPEN" and obs.pr.head_sha == HEAD and obs.pr.base_sha == BASE
    )


def test_deleted_fork_head_is_reported_not_invented() -> None:
    gone = pull(head={"sha": HEAD, "ref": "feat/x", "repo": None})
    obs = observe(routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=gone)})
    assert obs.pr.head_repo == ""
    assert has_issue(obs, "head-repository-unavailable")


def test_repository_identity_mismatch_blocks() -> None:
    table = routes() | {
        f"/repos/{REPO}": Reply(
            body={"full_name": "other/renamed", "default_branch": "main"}
        )
    }
    with pytest.raises(ProviderError) as err:
        observe(table)
    assert err.value.kind == "BLOCKED"


def test_pr_for_other_base_repository_blocks() -> None:
    wrong = pull(base={"sha": BASE, "ref": "main", "repo": {"full_name": "other/repo"}})
    with pytest.raises(ProviderError):
        observe(routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=wrong)})


@pytest.mark.parametrize(
    ("stack", "identity"),
    [
        (
            {
                "base": {"ref": "main", "sha": BASE},
                "size": 3,
                "position": 2,
                "id": 9,
                "number": 4,
            },
            (True, 4, 2, 3, "main"),
        ),
        (None, (False, None, None, None, None)),
    ],
)
def test_native_membership_and_identity_come_from_the_pr_stack_property(
    stack: dict[str, Any] | None, identity: tuple[Any, ...]
) -> None:
    body = pull(**({"stack": stack} if stack is not None else {}))
    obs = observe(routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=body)})
    pr = obs.pr
    assert (
        pr.native,
        pr.native_stack_number,
        pr.native_stack_position,
        pr.native_stack_size,
        pr.native_stack_base,
    ) == identity


@pytest.mark.parametrize(
    "stack",
    [
        "yes",
        {"size": 2},
        {"base": "main", "number": 4},
        {"base": {"ref": "main"}, "number": "4"},
        {"base": {"ref": "main"}, "number": True},
        {"base": {"ref": "main"}, "number": 4, "position": 0, "size": 2},
        {"base": {"ref": "main"}, "number": 4, "position": 3, "size": 2},
        {"base": {"ref": ""}, "number": 4},
        {"base": {"ref": "main", "sha": "abc"}, "number": 4},
    ],
)
def test_malformed_stack_property_is_rejected_not_read_as_unknown(stack: Any) -> None:
    with pytest.raises(ProviderError) as err:
        observe(
            routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(stack=stack))}
        )
    assert (err.value.kind, err.value.detail) == ("BLOCKED", "malformed")
    assert "stack" in str(err.value)


def test_list_prs_carries_native_membership_and_states() -> None:
    merged = pull(
        number=2,
        state="closed",
        merged_at="2026-10-01T00:00:00Z",
        stack={"base": {"ref": "main", "sha": BASE}},
    )
    merged.pop("merged"), merged.pop("mergeable")
    closed = pull(number=3, state="closed")
    closed.pop("merged"), closed.pop("mergeable")
    gh, _, _ = make({f"/repos/{REPO}/pulls": paged([merged, closed])})
    prs = {p.number: p for p in gh.list_prs("closed")}
    assert (prs[2].state, prs[2].native, prs[2].merged_at) == (
        "MERGED",
        True,
        "2026-10-01T00:00:00Z",
    )
    assert (prs[3].state, prs[3].native, prs[3].mergeable) == ("CLOSED", False, None)


def test_list_prs_rejects_state_that_contradicts_the_query() -> None:
    row = pull(number=2)
    row.pop("merged"), row.pop("mergeable")
    gh, _, _ = make({f"/repos/{REPO}/pulls": paged([row])})
    with pytest.raises(ProviderError):
        gh.list_prs("closed")


# --------------------------------------------------------------------------
# Pagination completeness


def _list_row(n: int) -> dict[str, Any]:
    row = pull(number=n, state="closed")
    row.pop("merged"), row.pop("mergeable")
    return row


@pytest.mark.parametrize("total", [0, 99, 100, 101, 230])
def test_list_prs_reads_every_page(total: int) -> None:
    gh, fake, _ = make(
        {f"/repos/{REPO}/pulls": paged([_list_row(n) for n in range(1, total + 1)])}
    )
    assert [p.number for p in gh.list_prs("closed")] == list(range(1, total + 1))
    assert fake.count(f"/repos/{REPO}/pulls") == total // 100 + 1


def test_check_runs_are_fully_paginated_with_count_proof() -> None:
    rows = [check_run(1000 + n, f"job-{n}") for n in range(250)]
    table = with_ci([run(10, suite=100)], rows)
    gh, fake, _ = make(table)
    obs = gh.observe(NUMBER, assurance="high")
    assert len(obs.checks) == 250 and {c.name for c in obs.checks} == {
        f"job-{n}" for n in range(250)
    }
    assert fake.count(f"/repos/{REPO}/commits/{HEAD}/check-runs") == 3


def test_check_run_set_that_disagrees_with_total_is_waiting_not_partial() -> None:
    rows = [check_run(1000 + n, f"job-{n}") for n in range(150)]
    table = with_ci([], rows) | {
        f"/repos/{REPO}/commits/{HEAD}/check-runs": wrapped(
            "check_runs", rows, total=151
        )
    }
    with pytest.raises(ProviderError) as err:
        observe(table)
    assert err.value.kind == "WAITING"


def test_reviews_beyond_one_page_are_all_considered() -> None:
    reviews = [review(n, f"user{n}", "APPROVED") for n in range(1, 131)]
    perms = {
        f"/repos/{REPO}/collaborators/user{n}/permission": permission()
        for n in range(1, 131)
    }
    obs = observe(
        routes() | {f"/repos/{REPO}/pulls/{NUMBER}/reviews": paged(reviews)} | perms
    )
    assert obs.approvals == 130


def test_later_review_pages_supersede_earlier_approvals() -> None:
    reviews = [review(n, f"user{n}", "APPROVED") for n in range(1, 101)]
    reviews.extend(
        [
            review(101, "user1", "DISMISSED"),
            review(102, "user2", "CHANGES_REQUESTED"),
            review(103, "user3", "APPROVED", commit=OTHER_HEAD),
        ]
    )
    perms = {
        f"/repos/{REPO}/collaborators/user{n}/permission": permission()
        for n in range(1, 101)
    }
    obs = observe(
        routes() | {f"/repos/{REPO}/pulls/{NUMBER}/reviews": paged(reviews)} | perms
    )
    assert obs.approvals == 97
    assert obs.changes_requested is True
    assert has_issue(obs, "stale-approval-ignored")


# --------------------------------------------------------------------------
# Check evidence: head/base binding, duplicates, non-Actions rows


def test_current_run_is_bound_to_head_and_the_verified_synthetic_merge_base() -> None:
    table = with_ci(
        [run(10, suite=100), run(11, suite=101, event="push", workflow=6, base=None)],
        [check_run(1000, "test"), check_run(1001, "lint", suite=101)],
        **{f"/repos/{REPO}/commits/{HEAD}/status": Reply(body={"sha": HEAD, "state": "pending", "total_count": 1,
            "statuses": [{"id": 1, "context": "ci/legacy", "state": "pending", "target_url": None,
                          "updated_at": AFTER_MERGE}]})},
    )  # fmt: skip
    obs = observe(table)
    checks = by_name(obs)
    assert (checks["test"].head_sha, checks["test"].base_sha) == (HEAD, BASE)
    assert (checks["test"].test_sha, checks["test"].run_id) == (
        MERGE,
        10,
    )  # proven checkout commit, bound run
    assert (checks["lint"].test_sha, checks["lint"].run_id) == (None, 11)
    assert (
        checks["lint"].base_sha is None
    )  # push run: head-only evidence, never given a base
    legacy = checks["ci/legacy"]
    assert (legacy.status, legacy.conclusion, legacy.base_sha) == (
        "in_progress",
        None,
        None,
    )
    assert has_issue(obs, "base-unverified") and not has_issue(obs, "no-ci-evidence")


def test_timestamp_and_current_metadata_without_checkout_proof_never_acquire_a_base() -> (
    None
):
    """Run created after the current merge commit, metadata naming the current base: still no proof."""
    table = with_ci([run(10, suite=100)], [check_run(1000, "test")]) | {
        f"/repos/{REPO}/actions/jobs/1000": Reply(
            status=404, body={"message": "Not Found"}
        ),
        f"/repos/{REPO}/actions/jobs/1000/logs": Reply(
            status=404, body={"message": "Not Found"}
        ),
    }
    obs = observe(table)
    check = by_name(obs)["test"]
    assert check.base_sha is None and check.test_sha is None
    assert any(
        i.startswith("checkout-logs-unavailable:") and "NEEDS_JUDGMENT" in i
        for i in obs.issues
    )


def _unproven(log: str | None = None, **over: Route) -> Observation:
    table = with_ci([run(10, suite=100)], [check_run(1000, "test")])
    if log is not None:
        table[f"/repos/{REPO}/actions/jobs/1000/logs"] = Reply(raw=log)
    table.update(over)
    return observe(table)


def test_checkout_proof_of_a_historical_merge_overrides_current_looking_metadata() -> (
    None
):
    hist_merge = sha(6)
    runs = [run(10, suite=100), run(11, suite=101, base=OLD_BASE, workflow=6)]
    checks = [check_run(1000, "stamped"), check_run(1001, "historical", suite=101)]
    table = (
        with_ci(runs, checks)
        | job_routes(runs, checks[:1], sha=hist_merge)
        | {
            f"/repos/{REPO}/git/commits/{hist_merge}": merge_commit(
                parents=[OLD_BASE, HEAD]
            ),
            f"/repos/{REPO}/actions/jobs/1001": Reply(
                status=404, body={"message": "Not Found"}
            ),
        }
    )
    obs = observe(table)
    stamped, historical = by_name(obs)["stamped"], by_name(obs)["historical"]
    assert (stamped.base_sha, stamped.test_sha, stamped.run_id) == (
        OLD_BASE,
        hist_merge,
        10,
    )  # metadata said BASE
    assert (historical.base_sha, historical.test_sha) == (
        OLD_BASE,
        None,
    )  # unproven claim kept as stale evidence only
    assert has_issue(obs, "checkout-logs-unavailable")


def test_checkout_proof_outranks_run_metadata_that_disagrees() -> None:
    obs = observe(
        with_ci([run(10, suite=100, base=OLD_BASE)], [check_run(1000, "test")])
    )
    check = by_name(obs)["test"]
    assert (check.base_sha, check.test_sha) == (BASE, MERGE)
    assert not any("NEEDS_JUDGMENT" in i for i in obs.issues)


def test_checkout_commit_that_does_not_merge_the_head_is_a_mismatch() -> None:
    obs = _unproven(
        **{
            f"/repos/{REPO}/git/commits/{MERGE}": merge_commit(
                parents=[OLD_BASE, OTHER_HEAD]
            )
        }
    )
    assert (by_name(obs)["test"].base_sha, by_name(obs)["test"].test_sha) == (
        None,
        None,
    )
    assert has_issue(obs, "checkout-commit-mismatch")


def test_head_only_checkout_has_no_base_but_records_the_tested_commit() -> None:
    obs = _unproven(
        checkout_log(HEAD),
        **{f"/repos/{REPO}/git/commits/{HEAD}": merge_commit(parents=[sha(9)])},
    )
    check = by_name(obs)["test"]
    assert (check.base_sha, check.test_sha) == (None, HEAD) and has_issue(
        obs, "checkout-head-only"
    )


SECOND_CHECKOUT = (
    "##[group]Run actions/checkout@v4\r\n  repository: acme/widget\r\n##[endgroup]\r\n"
    "Syncing repository: acme/widget\r\n[command]/usr/bin/git log -1 --format=%H\r\n"
    + sha(8)
    + "\r\n"
)


@pytest.mark.parametrize(
    ("log", "reason"),
    [
        (checkout_log(MERGE, extra=SECOND_CHECKOUT), "several"),
        (checkout_log(MERGE, repo="other/lib"), "no actions/checkout step synced"),
        (checkout_log(MERGE, extra="##[group]Run actions/checkout@v4\r\n##[endgroup]\r\n"), "single synced repository"),
        (checkout_log(MERGE).replace(MERGE, "not-a-commit"), "exactly one checked-out commit"),
        ("##[group]Run make test\r\nok\r\n", "no actions/checkout step"),
        # another step's output imitating checkout lines is not a checkout step
        ("##[group]Run echo forged\r\nSyncing repository: acme/widget\r\n[command]/usr/bin/git log -1 --format=%H\r\n"
         + MERGE + "\r\n", "no actions/checkout step"),
    ],
)  # fmt: skip
def test_ambiguous_or_missing_checkout_emission_never_yields_a_base(
    log: str, reason: str
) -> None:
    obs = _unproven(log)
    check = by_name(obs)["test"]
    assert (check.base_sha, check.test_sha) == (None, None)
    issue = next(i for i in obs.issues if i.startswith("checkout-proof-unverified:"))
    assert reason in issue and "NEEDS_JUDGMENT" in issue


def test_unpinned_checkout_step_is_not_trusted_as_proof() -> None:
    pinned = "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
    obs = _unproven(checkout_log(MERGE).replace(pinned, "v4"))
    assert by_name(obs)["test"].base_sha is None
    assert any("not pinned to a full commit" in i for i in obs.issues)


def test_gh_without_the_escape_flag_gets_one_plain_log_read() -> None:
    fake = FakeGH(with_ci([run(10, suite=100)], [check_run(1000, "test")]))

    def old_gh(
        argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        if "--allow-escape-sequences" in argv:
            return subprocess.CompletedProcess(
                list(argv), 1, b"", b"unknown flag: --allow-escape-sequences"
            )
        return fake(argv, timeout)

    obs = GitHub("github.com", REPO, runner=old_gh).observe(NUMBER, assurance="high")
    assert by_name(obs)["test"].base_sha == BASE


def test_unreadable_checkout_commit_parents_are_unverified() -> None:
    obs = _unproven(
        **{
            f"/repos/{REPO}/git/commits/{MERGE}": Reply(
                status=404, body={"message": "Not Found"}
            )
        }
    )
    assert by_name(obs)["test"].base_sha is None and has_issue(
        obs, "checkout-commit-unverified"
    )


def test_job_record_must_match_the_checks_run_head_and_name_before_logs_are_read() -> (
    None
):
    runs, checks = [run(10, suite=100)], [check_run(1000, "test")]
    table = with_ci(runs, checks)
    table[f"/repos/{REPO}/actions/jobs/1000"] = Reply(body={"id": 1000, "run_id": 999, "head_sha": HEAD, "name": "test",
                                                           "status": "completed"})  # fmt: skip
    gh, fake, _ = make(table)
    obs = gh.observe(NUMBER, assurance="high")
    assert by_name(obs)["test"].base_sha is None and has_issue(
        obs, "checkout-job-mismatch"
    )
    assert fake.count(f"/repos/{REPO}/actions/jobs/1000/logs") == 0


def test_job_that_has_not_completed_is_not_proven_and_logs_are_not_read() -> None:
    from lifecycle import Policy, evaluate

    checks = [check_run(1000, "test", status="in_progress", conclusion=None)]
    gh, fake, _ = make(with_ci([run(10, suite=100)], checks))
    obs = gh.observe(NUMBER, assurance="high")
    assert by_name(obs)["test"].base_sha is None and has_issue(
        obs, "checkout-proof-pending"
    )
    assert fake.count(f"/repos/{REPO}/actions/jobs/1000") == 0
    decision = Policy(
        ("current fixture workflow",),
        ("test",),
        "squash",
        (),
        HEAD,
        BASE,
        assurance="high",
    )
    assert evaluate(obs, decision).status == "WAITING"

    completed = observe(with_ci([run(10, suite=100)], [check_run(1000, "test")]))
    assert evaluate(completed, decision).status == "READY"
    assert (
        evaluate(_unproven("no checkout emission"), decision).status == "NEEDS_JUDGMENT"
    )


def test_checkout_commit_is_looked_up_once_for_many_jobs_and_logs_use_escape_flag() -> (
    None
):
    checks = [check_run(1000 + n, f"job-{n}") for n in range(5)]
    gh, fake, _ = make(with_ci([run(10, suite=100)], checks))
    obs = gh.observe(NUMBER, assurance="high")
    assert {c.base_sha for c in obs.checks} == {BASE} and {
        c.test_sha for c in obs.checks
    } == {MERGE}
    assert fake.count(f"/repos/{REPO}/git/commits/{MERGE}") == 1
    log_calls = [a for a in fake.argvs if urlsplit(a[-1]).path.endswith("/logs")]
    assert len(log_calls) == 5 and all(
        "--allow-escape-sequences" in a for a in log_calls
    )


def test_log_text_never_reaches_the_observation() -> None:
    leak = "##[group]Run make\r\nsecret ghp_abcdefghijklmnop1234 and source code here\r\n##[endgroup]\r\n"
    obs = _unproven(checkout_log(MERGE, extra=leak, with_bom=True))
    assert by_name(obs)["test"].base_sha == BASE
    assert "ghp_" not in repr(obs) and "source code" not in repr(obs)


REAL_LOG = (
    "\ufeff2026-10-12T00:49:25.1206431Z Current runner version: '2.337.0'\r\n"
    "2026-10-12T00:49:25.7830234Z ##[group]Run actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\r\n"
    "2026-10-12T00:49:25.7831333Z with:\r\n"
    "2026-10-12T00:49:25.7831864Z   repository: Mathews-Tom/armory-ship-smoke-20261012\r\n"
    "2026-10-12T00:49:25.7841885Z ##[endgroup]\r\n"
    "2026-10-12T00:49:25.9006609Z Syncing repository: Mathews-Tom/armory-ship-smoke-20261012\r\n"
    "2026-10-12T00:49:26.0903055Z ##[group]Fetching the repository\r\n"
    "2026-10-12T00:49:26.0912505Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --depth=1 origin "
    "+8557827db6753c272dab413c137736cecfcbf2b1:refs/remotes/pull/1/merge\r\n"
    "2026-10-12T00:49:26.3210855Z ##[endgroup]\r\n"
    "2026-10-12T00:49:26.3393391Z HEAD is now at 8557827 Merge a82a973 into 13492a8\r\n"
    "2026-10-12T00:49:26.3473405Z [command]/usr/bin/git log -1 --format=%H\r\n"
    "2026-10-12T00:49:26.3504357Z 8557827db6753c272dab413c137736cecfcbf2b1\r\n"
    "2026-10-12T00:49:26.3816794Z ##[group]Run actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405\r\n"
    "2026-10-12T00:49:27.3267531Z Post job cleanup.\r\n"
)


def test_checkout_commit_parser_reads_the_real_runner_log_shape() -> None:
    found = github_ops._checkout_commit(
        REAL_LOG, "mathews-tom/Armory-Ship-Smoke-20261012"
    )
    assert (found.sha, found.problem) == (
        "8557827db6753c272dab413c137736cecfcbf2b1",
        None,
    )


def test_check_row_for_another_head_is_rejected() -> None:
    table = with_ci(
        [run(10, suite=100)],
        [check_run(1000, "old", head=OTHER_HEAD), check_run(1001, "current")],
    )
    obs = observe(table)
    assert set(by_name(obs)) == {"current"} and has_issue(obs, "stale-check-rejected")


def test_run_for_another_head_is_not_used_for_association() -> None:
    table = with_ci([run(10, suite=100, head=OTHER_HEAD)], [check_run(1000, "test")])
    obs = observe(table)
    assert by_name(obs)["test"].base_sha is None
    assert has_issue(obs, "stale-run-rejected") and has_issue(
        obs, "actions-run-unresolved"
    )


def test_run_belonging_to_another_pull_request_is_excluded() -> None:
    other = run(
        10,
        suite=100,
        prs=[{"number": 99, "head": {"sha": HEAD}, "base": {"sha": OLD_BASE}}],
    )
    obs = observe(with_ci([other], [check_run(1000, "test")]))
    assert obs.checks == () and has_issue(obs, "foreign-run-excluded")


def test_fork_run_without_pr_list_is_matched_by_head_repository_and_branch() -> None:
    fork_pr = pull(
        head={"sha": HEAD, "ref": "feat/x", "repo": {"full_name": "fork-owner/widget"}}
    )
    fork_run = run(10, suite=100, prs=[])
    fork_run["head_repository"] = {"full_name": "fork-owner/widget"}
    table = with_ci([fork_run], [check_run(1000, "test")]) | {
        f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=fork_pr)
    }
    assert by_name(observe(table))["test"].base_sha == BASE


def test_newer_pending_duplicate_is_never_hidden_behind_older_success() -> None:
    table = with_ci(
        [run(10, suite=100, number=1), run(12, suite=102, number=2)],
        [
            check_run(1000, "test", suite=100),
            check_run(1002, "test", suite=102, status="in_progress", conclusion=None),
        ],
    ) | run_jobs(12, job(1002, status="in_progress", conclusion=None))
    checks = observe(table).checks
    assert [(c.name, c.status, c.conclusion) for c in checks] == [
        ("test", "in_progress", None)
    ]


def test_newer_failure_wins_over_older_success_and_newer_success_wins_over_failure() -> (
    None
):
    runs = [run(10, suite=100, number=1), run(12, suite=102, number=2)]
    older_ok = observe(with_ci(
        runs,
        [check_run(1000, "test", suite=100), check_run(1002, "test", suite=102, conclusion="failure")],
    ) | run_jobs(12, job(1002, conclusion="failure")))  # fmt: skip
    assert [c.conclusion for c in older_ok.checks] == ["failure"]
    older_bad = observe(with_ci(
        runs,
        [check_run(1000, "test", suite=100, conclusion="failure"), check_run(1002, "test", suite=102)],
    ) | run_jobs(12, job(1002)))  # fmt: skip
    assert [c.conclusion for c in older_bad.checks] == ["success"]


def test_attempts_of_one_run_are_collapsed_only_with_authoritative_attempt_numbers() -> (
    None
):
    jobs = f"/repos/{REPO}/actions/runs/10/jobs"
    rows = [
        check_run(1000, "build", conclusion="success"),
        check_run(1001, "build", conclusion="failure"),
    ]
    table = with_ci([run(10, suite=100)], rows) | {
        jobs: wrapped(
            "jobs",
            [{"id": 1001, "run_attempt": 2, "name": "build"}],
        )
    }
    assert [c.conclusion for c in observe(table).checks] == [
        "failure"
    ]  # newest attempt, even though it failed

    unknown = with_ci([run(10, suite=100)], rows) | {
        jobs: Reply(status=403, body={"message": "Forbidden"})
    }
    obs = observe(unknown)
    assert sorted(c.conclusion or "" for c in obs.checks) == ["failure", "success"]
    assert has_issue(obs, "run-jobs-unavailable") and has_issue(
        obs, "attempt-unresolved"
    )


def test_same_named_jobs_in_one_attempt_are_both_kept() -> None:
    jobs = f"/repos/{REPO}/actions/runs/10/jobs"
    rows = [
        check_run(1000, "build", conclusion="success"),
        check_run(1001, "build", conclusion="failure"),
    ]
    table = with_ci([run(10, suite=100)], rows) | {
        jobs: wrapped(
            "jobs",
            [
                {"id": 1000, "run_attempt": 1, "name": "build"},
                {"id": 1001, "run_attempt": 1, "name": "build"},
            ],
        )
    }
    assert len(observe(table).checks) == 2


def test_non_actions_checks_are_included_with_base_issue() -> None:
    rows = [check_run(2000, "scan", suite=300, app="security-bot"),
            check_run(2001, "other", suite=300, app="security-bot")]  # fmt: skip
    obs = observe(with_ci([], rows))
    assert [(c.app_slug, c.base_sha) for c in obs.checks] == [
        ("security-bot", None)
    ] * 2
    assert any(
        "security-bot" in i for i in obs.issues if i.startswith("base-unverified")
    )


def test_status_contexts_map_without_inventing_green() -> None:
    statuses = [{"id": i, "context": f"ctx/{state}", "state": state, "target_url": None, "updated_at": AFTER_MERGE}
                for i, state in enumerate(["success", "failure", "error", "pending"], 1)]  # fmt: skip
    body = {"sha": HEAD, "state": "failure", "total_count": 4, "statuses": statuses}
    checks = by_name(
        observe(routes() | {f"/repos/{REPO}/commits/{HEAD}/status": Reply(body=body)})
    )
    assert [(n, c.status, c.conclusion) for n, c in sorted(checks.items())] == [
        ("ctx/error", "completed", "failure"), ("ctx/failure", "completed", "failure"),
        ("ctx/pending", "in_progress", None), ("ctx/success", "completed", "success"),
    ]  # fmt: skip


def test_status_for_a_different_commit_is_rejected() -> None:
    body = {"sha": OTHER_HEAD, "state": "success", "total_count": 0, "statuses": []}
    obs = observe(routes() | {f"/repos/{REPO}/commits/{HEAD}/status": Reply(body=body)})
    assert has_issue(obs, "statuses-unavailable") and obs.checks == ()


def test_empty_ci_evidence_is_explicit_not_green() -> None:
    obs = observe(routes())
    assert obs.checks == () and has_issue(obs, "no-ci-evidence")


def test_inaccessible_check_evidence_is_an_issue_not_empty_success() -> None:
    table = routes() | {
        f"/repos/{REPO}/commits/{HEAD}/check-runs": Reply(
            status=403, body={"message": "Resource not accessible"}
        )
    }
    obs = observe(table)
    assert obs.checks == () and has_issue(obs, "checks-unavailable")
    assert not has_issue(obs, "no-ci-evidence")  # absence is not proven


def test_completed_check_without_conclusion_is_malformed() -> None:
    with pytest.raises(ProviderError) as err:
        observe(
            with_ci([run(10, suite=100)], [check_run(1000, "test", conclusion=None)])
        )
    assert err.value.kind == "BLOCKED"


# --------------------------------------------------------------------------
# Reviews and policy


def test_approvals_bind_to_current_head_and_latest_review_per_reviewer() -> None:
    reviews = [
        review(1, "alice", "APPROVED", commit=OTHER_HEAD),  # stale head
        review(2, "bob", "APPROVED"),
        review(3, "carol", "APPROVED"), review(4, "carol", "DISMISSED"),
        review(5, "dave", "APPROVED"), review(6, "dave", "CHANGES_REQUESTED"),
        review(7, "erin", "CHANGES_REQUESTED"), review(8, "erin", "APPROVED"),
        review(9, "author", "APPROVED"),  # own pull request
        review(10, "frank", "COMMENTED"),
    ]  # fmt: skip
    perms = {
        f"/repos/{REPO}/collaborators/{n}/permission": permission()
        for n in ("bob", "erin")
    }
    obs = observe(
        routes() | {f"/repos/{REPO}/pulls/{NUMBER}/reviews": paged(reviews)} | perms
    )
    assert obs.approvals == 2  # bob, erin
    assert obs.changes_requested is True  # dave's latest review still blocks
    assert has_issue(obs, "stale-approval-ignored") and has_issue(
        obs, "self-approval-ignored"
    )


def test_approval_from_reviewer_without_write_access_does_not_count() -> None:
    table = routes() | {
        f"/repos/{REPO}/pulls/{NUMBER}/reviews": paged([review(1, "bob", "APPROVED")]),
        f"/repos/{REPO}/collaborators/bob/permission": permission("read"),
    }
    obs = observe(table)
    assert obs.approvals == 0 and has_issue(obs, "approval-not-counted")


def test_unverifiable_reviewer_permission_never_counts_and_makes_policy_unknown() -> (
    None
):
    table = routes() | {
        f"/repos/{REPO}/pulls/{NUMBER}/reviews": paged([review(1, "bob", "APPROVED")]),
        f"/repos/{REPO}/collaborators/bob/permission": Reply(
            status=403, body={"message": "Must have push access"}
        ),
    }
    obs = observe(table)
    assert obs.approvals == 0 and obs.policy_known is False
    assert has_issue(obs, "reviewer-permission-unverified")


def test_unreadable_reviews_are_not_zero_approval_certainty() -> None:
    table = routes() | {
        f"/repos/{REPO}/pulls/{NUMBER}/reviews": Reply(
            status=403, body={"message": "Forbidden"}
        )
    }
    obs = observe(table)
    assert (
        obs.policy_known is False
        and has_issue(obs, "reviews-unavailable")
        and has_issue(obs, "approvals-unknown")
    )


def _ruleset(*rules: dict[str, Any]) -> Reply:
    return Reply(body=list(rules))


def test_effective_rules_and_classic_protection_combine_to_strictest_gate() -> None:
    rules = _ruleset(
        {"type": "pull_request", "parameters": {"required_approving_review_count": 2,
                                                  "allowed_merge_methods": ["squash", "rebase"]}},
        {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "test"}],
                                                          "strict_required_status_checks_policy": False}},
        {"type": "deletion"},
    )  # fmt: skip
    protection = Reply(body={
        "required_status_checks": {"strict": False, "contexts": ["lint"], "checks": [{"context": "build", "app_id": 1}]},
        "required_pull_request_reviews": {"required_approving_review_count": 1},
        "required_linear_history": {"enabled": False},
    })  # fmt: skip
    table = routes() | {
        f"/repos/{REPO}/rules/branches/main": rules,
        f"/repos/{REPO}/branches/main": Reply(
            body={"protected": True, "commit": {"sha": BASE}}
        ),
        f"/repos/{REPO}/branches/main/protection": protection,
    }
    obs = observe(table)
    assert (
        obs.required_checks == ("build", "lint", "test") and obs.required_approvals == 2
    )
    assert obs.policy_known is True and obs.require_current_base is False
    assert obs.repo.allowed_merge_methods == (
        "squash",
    )  # repo allows merge+squash, ruleset squash+rebase


@pytest.mark.parametrize("source", ["ruleset", "classic"])
def test_strict_status_policy_sets_require_current_base(source: str) -> None:
    if source == "ruleset":
        table = routes() | {f"/repos/{REPO}/rules/branches/main": _ruleset(
            {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "t"}],
                                                              "strict_required_status_checks_policy": True}})}  # fmt: skip
    else:
        table = routes() | {
            f"/repos/{REPO}/branches/main": Reply(
                body={"protected": True, "commit": {"sha": BASE}}
            ),
            f"/repos/{REPO}/branches/main/protection": Reply(
                body={
                    "required_status_checks": {
                        "strict": True,
                        "contexts": ["t"],
                        "checks": [],
                    }
                }
            ),
        }
    obs = observe(table)
    assert (
        obs.require_current_base is True
        and obs.required_checks == ("t",)
        and obs.policy_known is True
    )


def test_unprotected_branch_with_readable_policy_is_known_zero_gates() -> None:
    obs = observe(routes())
    assert (
        obs.required_checks,
        obs.required_approvals,
        obs.policy_known,
        obs.require_current_base,
    ) == ((), 0, True, False)


def test_unreadable_classic_protection_fails_closed_and_keeps_visible_contexts() -> (
    None
):
    table = routes() | {
        f"/repos/{REPO}/branches/main": Reply(body={"protected": True, "commit": {"sha": BASE}, "protection": {
            "enabled": True, "required_status_checks": {"contexts": ["ci"], "checks": [], "enforcement_level": "everyone"}}}),
        f"/repos/{REPO}/branches/main/protection": Reply(status=403, body={"message": "Resource not accessible"}),
    }  # fmt: skip
    obs = observe(table)
    assert obs.policy_known is False and obs.required_checks == ("ci",)
    assert has_issue(obs, "policy-unreadable") and has_issue(
        obs, "approvals-policy-unknown"
    )


def test_unreadable_rules_make_policy_unknown() -> None:
    obs = observe(
        routes()
        | {
            f"/repos/{REPO}/rules/branches/main": Reply(
                status=404, body={"message": "Not Found"}
            )
        }
    )
    assert obs.policy_known is False and has_issue(obs, "policy-unreadable")


@pytest.mark.parametrize(
    "rule",
    [
        {"type": "merge_queue", "parameters": {}},
        {"type": "workflows", "parameters": {"workflows": []}},
        {"type": "some_future_rule"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 1,
                "require_code_owner_review": True,
            },
        },
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 1,
                "require_last_push_approval": True,
            },
        },
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 0,
                "required_review_thread_resolution": True,
            },
        },
    ],
)
def test_gates_the_observation_cannot_verify_make_policy_unknown(
    rule: dict[str, Any],
) -> None:
    obs = observe(routes() | {f"/repos/{REPO}/rules/branches/main": _ruleset(rule)})
    assert obs.policy_known is False and has_issue(obs, "unevaluated-policy")


def test_malformed_rule_payload_is_not_silently_ignored() -> None:
    obs = observe(
        routes()
        | {f"/repos/{REPO}/rules/branches/main": _ruleset({"type": "pull_request"})}
    )
    assert obs.policy_known is False and has_issue(obs, "policy-unreadable")


def test_merge_methods_follow_repository_flags_rules_and_linear_history() -> None:
    table = routes() | {
        f"/repos/{REPO}/rules/branches/main": _ruleset(
            {"type": "required_linear_history"}
        )
    }
    assert observe(table).repo.allowed_merge_methods == ("squash",)


def test_merge_methods_unknown_when_repository_settings_are_hidden() -> None:
    table = routes() | {
        f"/repos/{REPO}": Reply(body={"full_name": REPO, "default_branch": "main"})
    }
    obs = observe(table)
    assert obs.repo.allowed_merge_methods == () and obs.policy_known is False
    assert has_issue(obs, "merge-methods-unknown")


# --------------------------------------------------------------------------
# Stale observation, malformed and inaccessible responses


def test_head_moving_during_observation_is_waiting_not_a_stale_observation() -> None:
    moved = pull(head={"sha": OTHER_HEAD, "ref": "feat/x", "repo": {"full_name": REPO}})
    table = routes() | {
        f"/repos/{REPO}/pulls/{NUMBER}": [Reply(body=pull()), Reply(body=moved)]
    }
    with pytest.raises(ProviderError) as err:
        observe(table)
    assert err.value.kind == "WAITING"


def test_base_moving_during_observation_is_waiting() -> None:
    moved = pull(base={"sha": OLD_BASE, "ref": "main", "repo": {"full_name": REPO}})
    table = routes() | {
        f"/repos/{REPO}/pulls/{NUMBER}": [Reply(body=pull()), Reply(body=moved)]
    }
    with pytest.raises(ProviderError) as err:
        observe(table)
    assert err.value.kind == "WAITING"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("head"),
        lambda p: p["head"].update(sha="abc"),
        lambda p: p.update(state="weird"),
        lambda p: p.update(merged=True),  # contradicts merged_at
        lambda p: p.pop("mergeable"),
        lambda p: p.update(number="7"),
    ],
)
def test_malformed_pull_request_payloads_block(
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    body = pull()
    mutate(body)
    with pytest.raises(ProviderError) as err:
        observe(routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=body)})
    assert err.value.kind == "BLOCKED"


def test_non_json_and_non_object_responses_block() -> None:
    def garbled(
        argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            list(argv), 0, b"HTTP/2.0 200 OK\r\n\r\n<html>", b""
        )

    with pytest.raises(ProviderError) as err:
        GitHub("github.com", REPO, runner=garbled).observe(NUMBER)
    assert err.value.kind == "BLOCKED"
    with pytest.raises(ProviderError):
        observe(routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=[1])})


def test_inaccessible_pull_request_blocks_with_exact_diagnostic_and_no_retry() -> None:
    gh, fake, sleeps = make(
        routes()
        | {
            f"/repos/{REPO}/pulls/{NUMBER}": Reply(
                status=404, body={"message": "Not Found"}
            )
        }
    )
    with pytest.raises(ProviderError) as err:
        gh.observe(NUMBER)
    assert (
        err.value.kind == "BLOCKED"
        and err.value.http_status == 404
        and err.value.uncertain is False
    )
    assert "not accessible" in str(err.value)
    assert fake.count(f"/repos/{REPO}/pulls/{NUMBER}") == 1 and sleeps == []


def test_authentication_failure_blocks_without_leaking_credentials() -> None:
    reply = Reply(status=401, body={"message": "Bad credentials ghp_abcdefghijklmnop1234"},
                  stderr="gh: Bearer ghp_abcdefghijklmnop1234 (HTTP 401)")  # fmt: skip
    gh, _, _ = make(routes() | {f"/repos/{REPO}": reply})
    with pytest.raises(ProviderError) as err:
        gh.observe(NUMBER)
    assert err.value.kind == "BLOCKED" and "gh auth login" in str(err.value)
    assert "ghp_" not in str(err.value) and "ghp_" not in err.value.detail


def test_missing_gh_binary_blocks() -> None:
    def absent(
        argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("gh")

    with pytest.raises(ProviderError) as err:
        GitHub("github.com", REPO, runner=absent).observe(NUMBER)
    assert err.value.kind == "BLOCKED"


def test_every_provider_call_is_a_credential_store_read() -> None:
    table = with_ci([run(10, suite=100)], [check_run(1000, "test")])
    gh, fake, _ = make(table)
    gh.observe(NUMBER, assurance="high")
    assert fake.argvs
    for argv in fake.argvs:
        assert argv[:4] == ("gh", "api", "--method", "GET")
        assert not {
            "-f",
            "-F",
            "-X",
            "--input",
            "--field",
            "--raw-field",
            "--token",
        } & set(argv)
        assert not any(
            "token" in part.lower() or "authorization" in part.lower() for part in argv
        )


def test_observation_contains_no_provider_text_beyond_identifiers() -> None:
    body_marker = "private body fixture"
    body = pull(title=f"leak {body_marker}", body=f"source {body_marker}")
    obs = observe(routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=body)})
    assert body_marker not in repr(obs)


def test_invalid_inputs_are_rejected_at_the_boundary() -> None:
    with pytest.raises(ValueError):
        GitHub("github.com", "no-slash")
    with pytest.raises(ValueError):
        GitHub("bad host", REPO)
    gh, _, _ = make(routes())
    with pytest.raises(ValueError):
        gh.observe(0)
    with pytest.raises(ValueError):
        gh.list_prs("all")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Bounded retries


def _seq(*replies: Reply) -> dict[str, Route]:
    return {f"/repos/{REPO}/pulls": list(replies)}


def test_transient_failures_retry_with_one_then_two_second_delays() -> None:
    fail = Reply(status=503, body={"message": "unavailable"})
    gh, fake, sleeps = make(_seq(fail, fail, Reply(body=[])))
    assert gh.list_prs("open") == ()
    assert fake.count(f"/repos/{REPO}/pulls") == 3 and sleeps == [1.0, 2.0]
    assert [(r.attempt, r.delay) for r in gh.retries] == [(1, 1.0), (2, 2.0)]


def test_transient_failures_stop_after_three_attempts_as_waiting() -> None:
    fail = Reply(status=503, body={"message": "unavailable"})
    gh, fake, sleeps = make(_seq(fail))
    with pytest.raises(ProviderError) as err:
        gh.list_prs("open")
    assert err.value.kind == "WAITING" and err.value.uncertain is False
    assert fake.count(f"/repos/{REPO}/pulls") == 3 and sleeps == [1.0, 2.0]


def test_network_timeouts_are_transient() -> None:
    calls: list[int] = []

    def flaky(
        argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(1)
        if len(calls) < 2:
            raise subprocess.TimeoutExpired(list(argv), timeout)
        return subprocess.CompletedProcess(
            list(argv), 0, b"HTTP/2.0 200 OK\r\n\r\n[]", b""
        )

    sleeps: list[float] = []
    assert (
        GitHub("github.com", REPO, runner=flaky, sleep=sleeps.append).list_prs("open")
        == ()
    )
    assert len(calls) == 2 and sleeps == [1.0]


def test_retry_after_replaces_default_delay_when_it_fits_the_deadline() -> None:
    limited = Reply(
        status=429, body={"message": "slow down"}, headers={"Retry-After": "5"}
    )
    gh, _, sleeps = make(_seq(limited, Reply(body=[])), deadline=100.0)
    assert gh.list_prs("open") == () and sleeps == [5.0]


def test_retry_after_longer_than_remaining_window_is_waiting_without_sleeping() -> None:
    limited = Reply(
        status=403, body={"message": "rate limit"}, headers={"Retry-After": "50"}
    )
    gh, fake, sleeps = make(_seq(limited), deadline=10.0)
    with pytest.raises(ProviderError) as err:
        gh.list_prs("open")
    assert (
        err.value.kind == "WAITING"
        and sleeps == []
        and fake.count(f"/repos/{REPO}/pulls") == 1
    )


def test_rate_limit_with_unknown_wait_is_waiting() -> None:
    limited = Reply(
        status=403, body={"message": "You have exceeded a secondary rate limit"}
    )
    gh, fake, sleeps = make(_seq(limited))
    with pytest.raises(ProviderError) as err:
        gh.list_prs("open")
    assert (
        err.value.kind == "WAITING" and "Retry-After" in str(err.value) and sleeps == []
    )
    assert fake.count(f"/repos/{REPO}/pulls") == 1


def test_plain_forbidden_is_blocked_not_retried_as_rate_limit() -> None:
    gh, fake, sleeps = make(
        _seq(
            Reply(
                status=403, body={"message": "Resource not accessible by integration"}
            )
        )
    )
    with pytest.raises(ProviderError) as err:
        gh.list_prs("open")
    assert err.value.kind == "BLOCKED" and "permission denied" in str(err.value)
    assert sleeps == [] and fake.count(f"/repos/{REPO}/pulls") == 1


def test_expired_deadline_stops_before_any_read() -> None:
    now = [10.0]
    fake = FakeGH(routes())
    gh = GitHub("github.com", REPO, deadline=5.0, runner=fake, clock=lambda: now[0])
    with pytest.raises(ProviderError) as err:
        gh.observe(NUMBER)
    assert err.value.kind == "WAITING" and fake.argvs == []


# --------------------------------------------------------------------------
# branch_protected


def _protection_routes(**over: Route) -> dict[str, Route]:
    return routes() | over


def test_default_branch_is_always_protected_even_with_no_protection_configured() -> (
    None
):
    gh, _, _ = make(
        {
            "/repos/other/fork": Reply(
                body={"full_name": "other/fork", "default_branch": "trunk"}
            )
        }
    )
    assert gh.branch_protected("other/fork", "trunk") is True


def test_branch_protected_by_classic_flag_or_by_ruleset() -> None:
    gh, _, _ = make(
        _protection_routes(
            **{f"/repos/{REPO}/branches/release": Reply(body={"protected": True})}
        )
    )
    assert gh.branch_protected(REPO, "release") is True
    table = _protection_routes(
        **{
            f"/repos/{REPO}/branches/release": Reply(body={"protected": False}),
            f"/repos/{REPO}/rules/branches/release": Reply(body=[{"type": "deletion"}]),
        }
    )
    assert make(table)[0].branch_protected(REPO, "refs/heads/release") is True


def test_branch_with_readable_empty_evidence_is_unprotected() -> None:
    table = _protection_routes(
        **{
            f"/repos/{REPO}/branches/topic": Reply(body={"protected": False}),
            f"/repos/{REPO}/rules/branches/topic": Reply(body=[]),
        }
    )
    assert make(table)[0].branch_protected(REPO, "topic") is False


@pytest.mark.parametrize("failing", ["branches", "rules"])
def test_inaccessible_protection_evidence_is_never_unprotected(failing: str) -> None:
    table = _protection_routes(
        **{
            f"/repos/{REPO}/branches/topic": Reply(body={"protected": False}),
            f"/repos/{REPO}/rules/branches/topic": Reply(body=[]),
        }
    )
    table[
        f"/repos/{REPO}/{failing}/{'topic' if failing == 'branches' else 'branches/topic'}"
    ] = Reply(status=403, body={"message": "forbidden"})
    with pytest.raises(ProviderError) as err:
        make(table)[0].branch_protected(REPO, "topic")
    assert err.value.kind == "BLOCKED"


@pytest.mark.parametrize(
    "rules,protected", [([], False), ([{"type": "deletion"}], True)]
)
def test_absent_branch_requires_readable_inventory_and_current_rules(
    rules: list[dict[str, str]],
    protected: bool,
) -> None:
    table = _protection_routes(
        **{
            f"/repos/{REPO}/branches/gone": Reply(
                status=404, body={"message": "Not Found"}
            ),
            f"/repos/{REPO}/branches": Reply(body=[{"name": "main"}]),
            f"/repos/{REPO}/rules/branches/gone": Reply(body=rules),
        }
    )
    assert make(table)[0].branch_protected(REPO, "gone") is protected


@pytest.mark.parametrize(
    "inventory",
    [
        Reply(status=403, body={"message": "Resource not accessible"}),
        Reply(body=[{"name": "gone"}]),
        Reply(body=[{"name": "main"}, {"name": "main"}]),
    ],
)
def test_404_cannot_bypass_unknown_or_contradictory_branch_inventory(
    inventory: Reply,
) -> None:
    table = _protection_routes(
        **{
            f"/repos/{REPO}/branches/gone": Reply(
                status=404, body={"message": "Not Found"}
            ),
            f"/repos/{REPO}/branches": inventory,
            f"/repos/{REPO}/rules/branches/gone": Reply(body=[]),
        }
    )
    with pytest.raises(ProviderError) as error:
        make(table)[0].branch_protected(REPO, "gone")
    assert error.value.kind == "BLOCKED"


def test_branch_names_with_slashes_are_path_safe() -> None:
    table = _protection_routes(
        **{
            f"/repos/{REPO}/branches/feat/a%20b": Reply(body={"protected": False}),
            f"/repos/{REPO}/rules/branches/feat/a%20b": Reply(body=[]),
        }
    )
    assert make(table)[0].branch_protected(REPO, "feat/a b") is False


@pytest.mark.parametrize("source", ["ruleset", "classic"])
@pytest.mark.parametrize("publisher", [42, 99, None])
def test_required_check_publisher_controls_landing_not_only_its_name(
    source: str, publisher: int | None
) -> None:
    from lifecycle import Policy, evaluate

    report = check_run(1000, "test")
    report["app"]["id"] = publisher
    table = with_ci([run(10, suite=100)], [report])
    if source == "ruleset":
        table[f"/repos/{REPO}/rules/branches/main"] = _ruleset(
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "test", "integration_id": 42}
                    ],
                    "strict_required_status_checks_policy": False,
                },
            }
        )
    else:
        table[f"/repos/{REPO}/branches/main"] = Reply(
            body={"protected": True, "commit": {"sha": BASE}}
        )
        table[f"/repos/{REPO}/branches/main/protection"] = Reply(
            body={
                "required_status_checks": {
                    "contexts": [],
                    "checks": [{"context": "test", "app_id": 42}],
                    "strict": False,
                },
            }
        )
    decision = Policy(
        ("current workflow and provider policy",),
        ("test",),
        "squash",
        (),
        HEAD,
        BASE,
        assurance="high",
    )
    result = evaluate(observe(table), decision)
    assert result.status == (
        "READY"
        if publisher == 42
        else "NEEDS_JUDGMENT"
        if publisher is None
        else "WAITING"
    )


def test_base_ref_cannot_inherit_green_from_cached_pull_metadata() -> None:
    table = routes() | {
        f"/repos/{REPO}/branches/main": Reply(
            body={"protected": False, "commit": {"sha": OLD_BASE}},
        ),
    }
    with pytest.raises(ProviderError) as raised:
        observe(table)
    assert raised.value.kind == "WAITING"


def test_base_ref_change_during_observation_invalidates_the_snapshot() -> None:
    table = routes() | {
        f"/repos/{REPO}/branches/main": [
            Reply(body={"protected": False, "commit": {"sha": BASE}}),
            Reply(body={"protected": False, "commit": {"sha": OLD_BASE}}),
        ],
    }
    with pytest.raises(ProviderError) as raised:
        observe(table)
    assert raised.value.kind == "WAITING"


def test_missing_live_base_identity_cannot_authorize_a_completed_job() -> None:
    from lifecycle import Policy, evaluate

    table = with_ci([run(10, suite=100)], [check_run(1000, "test")])
    table[f"/repos/{REPO}/branches/main"] = Reply(body={"protected": False})
    decision = Policy(
        ("current workflow",), ("test",), "squash", (), HEAD, BASE, assurance="high"
    )
    assert evaluate(observe(table), decision).status == "BLOCKED"


# --------------------------------------------------------------------------
# Existing-PR lifecycle: read_pr, base_tip, landing_reachable, merge, queue_state, merge_queue policy

NEW_BASE = sha(0xC6)  # contains hex letters, so .upper() is a different string
DROP = object()  # remove a field from a fixture payload

GH_HELP = """Merge a pull request on GitHub.

FLAGS
      --admin                   Use administrator privileges to merge a pull request that does not meet requirements
      --auto                    Automatically merge only after necessary requirements are met
  -d, --delete-branch           Delete the local and remote branch after merge
      --match-head-commit SHA   Commit SHA that the pull request head must match to allow merge
  -m, --merge                   Merge the commits with the base branch
  -r, --rebase                  Rebase the commits onto the base branch
  -s, --squash                  Squash the commits into one commit and merge it into the base branch

INHERITED FLAGS
  -R, --repo [HOST/]OWNER/REPO   Select another repository using the [HOST/]OWNER/REPO format
"""
OLD_GH_HELP = "\n".join(
    line for line in GH_HELP.splitlines() if "match-head-commit" not in line
)
_VALUE_FLAGS = {
    "--repo": "--repo", "-R": "--repo", "--match-head-commit": "--match-head-commit",
    "--author-email": "--author-email", "-A": "--author-email", "--body": "--body",
    "-b": "--body", "--body-file": "--body-file", "-F": "--body-file",
    "--subject": "--subject", "-t": "--subject",
}  # fmt: skip
_BOOL_FLAGS = {
    "--admin": "--admin", "--delete-branch": "--delete-branch", "-d": "--delete-branch",
    "--auto": "--auto", "--disable-auto": "--disable-auto", "--merge": "--merge",
    "-m": "--merge", "--rebase": "--rebase", "-r": "--rebase", "--squash": "--squash",
    "-s": "--squash",
}  # fmt: skip


def _done(
    argv: Sequence[str], code: int, stderr: str = ""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(list(argv), code, b"", stderr.encode())


class Provider:
    """A mutable GitHub repository plus the documented contracts of ``gh api`` and ``gh pr merge``.

    Merge model (gh manual): unknown flags are usage errors; ``--match-head-commit``
    is enforced by GitHub; a merge-queue branch queues the PR (checks green) or
    arms auto-merge (checks pending) instead of merging and only warns about a
    strategy; ``--admin`` bypasses policy and queue; ``--auto`` arms auto-merge
    when requirements are unmet; ``--delete-branch`` deletes the head branch;
    an already merged or queued PR exits 0.  Every REST read must be ``GET`` and
    the only GraphQL operation allowed is a ``query``.  Tests assert on the
    resulting provider state, never on how the arguments were forwarded.
    """

    def __init__(self, *, head_repo: str = REPO) -> None:
        self.state = "OPEN"  # OPEN | CLOSED | MERGED
        self.head = HEAD
        self.base = BASE
        self.head_repo = head_repo
        self.merge_sha: str | None = None
        self.merged_via: str | None = None
        self.queue_branch = False  # the base branch requires a merge queue
        self.checks_green = True
        self.queue = "none"  # none | auto | queued
        self.entry_state = "QUEUED"
        self.mergeable = True  # gh's pre-flight mergeability verdict
        self.allowed = {"merge", "squash", "rebase"}
        self.help = GH_HELP
        self.hang = ""  # "" | before | after (effect) | oserror
        self.fail: tuple[int, str] | None = None  # refusal/failure with no effect
        self.gql_patch: dict[str, Any] = {}
        self.gql_reply: Reply | None = None
        self.rest_patch: dict[str, Any] = {}
        self.arm_on_pull_read: int | None = None
        self.argvs: list[tuple[str, ...]] = []
        self.reads: list[str] = []
        self.gql_calls: list[dict[str, str]] = []
        self.merge_calls: list[tuple[str, ...]] = []
        self.merge_timeouts: list[float] = []
        self.help_calls = 0
        self.admin_merges = 0
        self.branch_deleted = False
        self._pull_reads = 0

    def land(self, method: str = "squash") -> None:
        self.state = "MERGED"
        self.merge_sha = MERGE
        self.merged_via = method
        self.queue = "none"

    def __call__(
        self, argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        self.argvs.append(tuple(argv))
        if argv[:3] == ("gh", "pr", "merge"):
            return self._merge(argv, timeout)
        assert argv[:2] == ("gh", "api"), argv
        if argv[-1] == "graphql":
            return render(argv, self._graphql(argv))
        assert argv[:4] == ("gh", "api", "--method", "GET"), "REST read must be GET"
        return render(argv, self._rest(urlsplit(argv[-1]).path))

    def _pull(self) -> dict[str, Any]:
        merged = self.state == "MERGED"
        head_repo = {"full_name": self.head_repo} if self.head_repo else None
        body = pull(
            state="open" if self.state == "OPEN" else "closed",
            merged=merged,
            merged_at=MERGE_DATE if merged else None,
            head={"sha": self.head, "ref": "feat/x", "repo": head_repo},
            base={"sha": self.base, "ref": "main", "repo": {"full_name": REPO}},
        )
        body["auto_merge"] = (
            {"enabled_by": {"login": "bot"}, "merge_method": "squash",
             "commit_title": "t", "commit_message": "m"}
            if self.queue == "auto"
            else None
        )  # fmt: skip
        for key, value in self.rest_patch.items():
            if value is DROP:
                body.pop(key, None)
            else:
                body[key] = value
        return body

    def _rest(self, path: str) -> Reply:
        self.reads.append(path)
        base = f"/repos/{REPO}"
        if path == base:
            return Reply(body={"full_name": REPO, "default_branch": "main"})
        if path == f"{base}/pulls/{NUMBER}":
            self._pull_reads += 1
            if self.arm_on_pull_read == self._pull_reads:
                self.queue = "auto"
            return Reply(body=self._pull())
        if path == f"{base}/branches/main":
            return Reply(body=branch(self.base))
        raise AssertionError(f"unrouted provider read: {path}")

    def _graphql(self, argv: Sequence[str]) -> Reply:
        assert argv[3] == "POST"
        fields = {
            item.partition("=")[0]: item.partition("=")[2]
            for flag, item in itertools.pairwise(argv)
            if flag in ("-f", "-F")
        }
        self.gql_calls.append(fields)
        query = fields["query"]
        assert query.lstrip().startswith("query") and "mutation" not in query.lower()
        if self.gql_reply is not None:
            return self.gql_reply
        pr: dict[str, Any] = {
            "number": NUMBER,
            "state": self.state,
            "merged": self.state == "MERGED",
            "headRefOid": self.head,
            "url": f"https://github.com/{REPO}/pull/{NUMBER}",
            "headRefName": "feat/x",
            "baseRefName": "main",
            "mergedAt": MERGE_DATE if self.state == "MERGED" else None,
            "mergeCommit": {"oid": self.merge_sha or MERGE}
            if self.state == "MERGED"
            else None,
            "isInMergeQueue": self.queue == "queued",
            "autoMergeRequest": {"mergeMethod": "SQUASH"}
            if self.queue == "auto"
            else None,
            "mergeQueueEntry": {"state": self.entry_state, "position": 1}
            if self.queue == "queued"
            else None,
        }
        for key, value in self.gql_patch.items():
            if value is DROP:
                pr.pop(key, None)
            else:
                pr[key] = value
        return Reply(
            body={"data": {"repository": {"nameWithOwner": REPO, "pullRequest": pr}}}
        )

    def _merge(
        self, argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        args = list(argv[3:])
        if args == ["--help"]:
            self.help_calls += 1
            return subprocess.CompletedProcess(list(argv), 0, self.help.encode(), b"")
        self.merge_calls.append(tuple(args))
        self.merge_timeouts.append(timeout)
        positional: list[str] = []
        flags: dict[str, Any] = {}
        index = 0
        while index < len(args):
            token = args[index]
            if token in _VALUE_FLAGS:
                if index + 1 >= len(args):
                    return _done(argv, 1, f"flag needs an argument: {token}")
                flags[_VALUE_FLAGS[token]] = args[index + 1]
                index += 2
            elif token in _BOOL_FLAGS:
                flags[_BOOL_FLAGS[token]] = True
                index += 1
            elif token.startswith("-"):
                return _done(argv, 1, f"unknown flag: {token}")
            else:
                positional.append(token)
                index += 1
        if len(positional) != 1:
            return _done(
                argv, 1, f"accepts at most 1 arg(s), received {len(positional)}"
            )
        if positional[0] != str(NUMBER) or flags.get("--repo") != f"github.com/{REPO}":
            return _done(
                argv,
                1,
                "GraphQL: Could not resolve to a PullRequest. (repository.pullRequest)",
            )
        if self.fail is not None:
            return _done(argv, *self.fail)
        if self.hang == "oserror":
            raise OSError("exec format error")
        if self.hang == "before":
            raise subprocess.TimeoutExpired(list(argv), timeout)
        chosen = [m for m in ("merge", "rebase", "squash") if flags.get(f"--{m}")]
        admin = bool(flags.get("--admin"))
        guard = flags.get("--match-head-commit")
        warning = ""
        if self.state == "MERGED" or self.queue == "queued":
            pass  # gh: already merged / already queued; exit 0 and nothing changes
        elif self.state == "CLOSED":
            return _done(argv, 1, "GraphQL: Pull request is closed. (mergePullRequest)")
        elif guard is not None and guard != self.head:
            return _done(
                argv,
                1,
                "GraphQL: Head branch was modified. Review and try the merge again. (mergePullRequest)",
            )
        elif self.queue_branch and not admin:
            self.queue = "queued" if self.checks_green else "auto"
            warning = (
                "! The merge strategy for main is set by the merge queue"
                if chosen
                else ""
            )
        else:
            if not chosen:
                return _done(
                    argv,
                    1,
                    "--merge, --rebase, or --squash required when not running interactively",
                )
            if len(chosen) > 1:
                return _done(
                    argv, 1, "only one of --merge, --rebase, or --squash can be enabled"
                )
            if flags.get("--auto") and not self.mergeable:
                self.queue = "auto"
            elif not self.mergeable and not admin:
                return _done(
                    argv,
                    1,
                    f"X Pull request {REPO}#{NUMBER} is not mergeable: the base branch policy prohibits the merge.\nTo use administrator privileges to immediately merge the pull request, add the `--admin` flag.",
                )
            elif chosen[0] not in self.allowed:
                return _done(
                    argv,
                    1,
                    f"GraphQL: {chosen[0].title()} merges are not allowed on this repository. (mergePullRequest)",
                )
            else:
                self.land(chosen[0])
                self.admin_merges += 1 if admin else 0
                self.branch_deleted = bool(flags.get("--delete-branch"))
        if self.hang == "after":
            raise subprocess.TimeoutExpired(list(argv), timeout)
        return _done(argv, 0, warning)


def branch(tip: str, name: str = "main", url: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "protected": False,
        "commit": {
            "sha": tip,
            "url": url or f"https://api.github.com/repos/{REPO}/commits/{tip}",
        },
    }


def provider_gh(provider: Provider, **kwargs: Any) -> tuple[GitHub, list[float]]:
    sleeps: list[float] = []
    gh = GitHub(
        "github.com",
        REPO,
        runner=provider,
        sleep=sleeps.append,
        clock=lambda: 0.0,
        **kwargs,
    )
    return gh, sleeps


def refused(call: Callable[[], Any]) -> ProviderError:
    with pytest.raises(ProviderError) as raised:
        call()
    return raised.value


# -- read_pr -----------------------------------------------------------------


def test_read_pr_keeps_landing_facts_of_a_merged_pr_without_any_ci_evidence() -> None:
    provider = Provider()
    provider.land()
    pr = provider_gh(provider)[0].read_pr(NUMBER)
    assert (pr.state, pr.merge_commit_sha, pr.merged_at) == (
        "MERGED",
        MERGE,
        MERGE_DATE,
    )
    # check runs, workflow runs, jobs, logs and reviews are unrouted in Provider
    assert set(provider.reads) == {f"/repos/{REPO}", f"/repos/{REPO}/pulls/{NUMBER}"}


@pytest.mark.parametrize(
    "patch",
    [
        {"headRefOid": OTHER_HEAD},
        {"state": "OPEN"},
        {"baseRefName": "other"},
        {"url": f"https://github.com/other/repo/pull/{NUMBER}"},
        {"mergeCommit": None},
    ],
)
def test_rest_merged_cannot_authorize_missing_or_mismatched_graphql_landing(
    patch: dict[str, Any],
) -> None:
    provider = Provider()
    provider.land()
    provider.gql_patch.update(patch)
    with pytest.raises(ProviderError):
        provider_gh(provider)[0].read_pr(NUMBER)


@pytest.mark.parametrize("state", ["OPEN", "MERGED", "CLOSED"])
def test_read_pr_keeps_fork_head_and_base_namespaces_distinct(state: str) -> None:
    provider = Provider(head_repo="fork-owner/widget")
    provider.state = state
    pr = provider_gh(provider)[0].read_pr(NUMBER)
    assert (pr.state, pr.head_repo, pr.base_repo) == (state, "fork-owner/widget", REPO)
    assert pr.head_sha == HEAD and pr.head_ref == "feat/x"


def test_read_pr_reports_a_deleted_fork_head_instead_of_inventing_one() -> None:
    provider = Provider(head_repo="")
    pr = provider_gh(provider)[0].read_pr(NUMBER)
    assert (pr.head_repo, pr.base_repo) == ("", REPO)


def test_read_pr_keeps_missing_native_stack_identity_explicitly_unknown() -> None:
    plain = make(routes())[0].read_pr(NUMBER)
    stacked = make(
        routes()
        | {
            f"/repos/{REPO}/pulls/{NUMBER}": Reply(
                body=pull(stack={"base": {}, "size": 2})
            )
        }
    )[0].read_pr(NUMBER)
    assert (plain.native, stacked.native) == (False, True)
    assert (
        stacked.native_stack_number,
        stacked.native_stack_position,
        stacked.native_stack_size,
        stacked.native_stack_base,
    ) == (None, None, 2, None)


@pytest.mark.parametrize(
    "override",
    [
        {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(number=NUMBER + 1))},
        {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(base={"sha": BASE, "ref": "main", "repo": {"full_name": "other/repo"}}))},
        {f"/repos/{REPO}": Reply(body={"full_name": "other/renamed", "default_branch": "main"})},
        {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(html_url=f"https://evil.example/{REPO}/pull/{NUMBER}"))},
        {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(html_url=f"https://github.com/other/repo/pull/{NUMBER}"))},
        {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(html_url=f"https://github.com/{REPO}/pull/{NUMBER + 1}"))},
        {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(head={"sha": HEAD, "ref": "x", "repo": {"full_name": "not a repo"}}))},
        {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(stack="yes"))},
        {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(state="draft"))},
        {f"/repos/{REPO}/pulls/{NUMBER}": Reply(status=404, body={"message": "Not Found"})},
    ],
    ids=["number", "base-repo", "renamed-repo", "url-host", "url-repo", "url-number",
         "head-repo-name", "stack", "state", "inaccessible"],
)  # fmt: skip
def test_read_pr_blocks_instead_of_answering_for_a_different_pr(
    override: dict[str, Route],
) -> None:
    assert (
        refused(lambda: make(routes() | override)[0].read_pr(NUMBER)).kind == "BLOCKED"
    )


@pytest.mark.parametrize("bad", [0, -1, True, "7", 7.0])
def test_read_pr_rejects_invalid_numbers_before_any_provider_call(bad: Any) -> None:
    gh, fake, _ = make(routes())
    with pytest.raises(ValueError):
        gh.read_pr(bad)
    assert fake.argvs == []


# -- base_tip ------------------------------------------------------------------


def test_base_tip_reads_the_live_branch_not_cached_pull_metadata() -> None:
    path = f"/repos/{REPO}/branches/main"
    gh, fake, _ = make(routes() | {path: Reply(body=branch(NEW_BASE))})
    pr = gh.read_pr(NUMBER)
    assert pr.base_sha == BASE  # what the PR recorded
    assert gh.base_tip(pr.base_ref) == NEW_BASE  # what the branch is now
    assert fake.count(path) == 1


def test_base_tip_rereads_the_branch_on_every_call() -> None:
    path = f"/repos/{REPO}/branches/main"
    gh, fake, _ = make(
        routes() | {path: [Reply(body=branch(BASE)), Reply(body=branch(NEW_BASE))]}
    )
    assert (gh.base_tip("main"), gh.base_tip("refs/heads/main")) == (BASE, NEW_BASE)
    assert fake.count(path) == 2


@pytest.mark.parametrize(
    "reply",
    [
        Reply(body=branch(NEW_BASE, name="renamed")),
        Reply(body=branch(NEW_BASE[:12])),
        Reply(body=branch(NEW_BASE.upper())),
        Reply(body=branch(NEW_BASE, url=f"https://api.github.com/repos/other/repo/commits/{NEW_BASE}")),
        Reply(body={"name": "main", "protected": False}),
        Reply(body={"name": "main", "commit": None}),
        Reply(status=404, body={"message": "Branch not found"}),
        Reply(status=403, body={"message": "Forbidden"}),
    ],
    ids=["renamed", "abbreviated", "uppercase", "foreign-commit", "no-commit", "null-commit",
         "missing", "forbidden"],
)  # fmt: skip
def test_base_tip_never_returns_a_value_it_cannot_attribute_to_the_branch(
    reply: Reply,
) -> None:
    gh, _, _ = make(routes() | {f"/repos/{REPO}/branches/main": reply})
    assert refused(lambda: gh.base_tip("main")).kind == "BLOCKED"


def test_base_tip_is_path_safe_and_rejects_non_branch_references() -> None:
    path = f"/repos/{REPO}/branches/feat/a%20b"
    gh, _, _ = make({path: Reply(body=branch(NEW_BASE, name="feat/a b"))})
    assert gh.base_tip("feat/a b") == NEW_BASE
    for bad in ("", "refs/tags/v1", "main\nx"):
        with pytest.raises(ValueError):
            gh.base_tip(bad)


# -- landing_reachable -----------------------------------------------------------

LANDED, TIP = sha(0xA8), sha(0xB9)


def compare(
    landing: str,
    tip: str,
    status: str,
    ahead: int,
    behind: int,
    merge_base: str,
    **over: Any,
) -> Reply:
    body: dict[str, Any] = {
        "url": f"https://api.github.com/repos/{REPO}/compare/{landing}...{tip}",
        "html_url": f"https://github.com/{REPO}/compare/{landing}...{tip}",
        "permalink_url": f"https://github.com/{REPO}/compare/acme:{landing}...acme:{tip}",
        "diff_url": f"https://github.com/{REPO}/compare/{landing}...{tip}.diff",
        "patch_url": f"https://github.com/{REPO}/compare/{landing}...{tip}.patch",
        "status": status,
        "ahead_by": ahead,
        "behind_by": behind,
        "total_commits": 0,  # deliberately unrelated to ahead_by: counts are not proof
        "base_commit": {"sha": landing},
        "merge_base_commit": {"sha": merge_base},
        "commits": [],  # deliberately empty: a truncated list is not proof
    }
    body.update(over)
    return Reply(body=body)


def reach(reply: Reply, landing: str = LANDED, tip: str = TIP) -> tuple[bool, FakeGH]:
    path = f"/repos/{REPO}/compare/{landing}...{tip}"
    gh, fake, _ = make({path: reply})
    return gh.landing_reachable(landing, tip), fake


def test_landing_is_reachable_when_the_tip_is_ahead_with_the_landing_as_merge_base() -> (
    None
):
    reachable, fake = reach(compare(LANDED, TIP, "ahead", 3, 0, LANDED))
    assert reachable is True
    assert all(argv[:4] == ("gh", "api", "--method", "GET") for argv in fake.argvs)


def test_comparison_accepts_provider_abbreviated_permalink_only_with_full_requested_api_identity() -> (
    None
):
    landing, tip = (
        "13492a8e041a0d6a8d17e49230a58068daa26042",
        "a82a97331213c362784aad59015bcf0bfc354bb5",
    )
    reply = compare(
        landing,
        tip,
        "ahead",
        2,
        0,
        landing,
        permalink_url=f"https://github.com/{REPO}/compare/acme:{landing[:7]}...acme:{tip[:7]}",
    )
    assert reach(reply, landing, tip)[0] is True
    reply.body["url"] = (
        f"https://api.github.com/repos/{REPO}/compare/{landing}...{sha(99)}"
    )
    with pytest.raises(ProviderError):
        reach(reply, landing, tip)


def test_the_exact_same_commit_is_reachable_but_only_if_the_provider_has_it() -> None:
    assert reach(compare(TIP, TIP, "identical", 0, 0, TIP), TIP, TIP)[0] is True
    unknown = Reply(status=404, body={"message": "No commit found for SHA"})
    assert refused(lambda: reach(unknown, TIP, TIP)).kind == "BLOCKED"


@pytest.mark.parametrize(
    "reply",
    [
        compare(LANDED, TIP, "behind", 0, 4, TIP),
        compare(LANDED, TIP, "diverged", 2, 3, sha(10)),
    ],
    ids=["tip-is-an-ancestor-of-landing", "diverged"],
)
def test_proven_non_ancestry_is_false_not_an_error(reply: Reply) -> None:
    assert reach(reply)[0] is False


@pytest.mark.parametrize(
    "reply",
    [
        compare(LANDED, TIP, "ahead", 3, 0, sha(10)),  # merge base is not the landing
        compare(LANDED, TIP, "ahead", 3, 1, LANDED),
        compare(LANDED, TIP, "ahead", 0, 0, LANDED),
        compare(LANDED, TIP, "identical", 0, 0, LANDED),  # identical needs one commit
        compare(LANDED, TIP, "behind", 0, 2, LANDED),
        compare(LANDED, TIP, "diverged", 1, 1, LANDED),  # diverged cannot have landing as merge base
        compare(LANDED, TIP, "force-pushed", 1, 0, LANDED),
        compare(LANDED, TIP, "ahead", -1, 0, LANDED),
        compare(LANDED, TIP, "ahead", 3, 0, LANDED, base_commit={"sha": sha(10)}),
        compare(LANDED, TIP, "ahead", 3, 0, LANDED, permalink_url=f"https://github.com/{REPO}/compare/acme:{LANDED}...acme:{sha(10)}"),
        compare(LANDED, TIP, "ahead", 3, 0, LANDED, permalink_url=f"https://github.com/other/repo/compare/other:{LANDED}...other:{TIP}"),
        compare(LANDED, TIP, "ahead", 3, 0, LANDED, permalink_url=f"https://evil.example/{REPO}/compare/acme:{LANDED}...acme:{TIP}"),
        compare(LANDED, TIP, "ahead", 3, 0, LANDED, merge_base_commit=None),
        compare(LANDED, TIP, "ahead", 3, 0, LANDED, merge_base_commit={"sha": "abc"}),
        compare(LANDED, TIP, "ahead", 3, 0, LANDED, ahead_by="3"),
        compare(LANDED, TIP, "ahead", 3, 0, LANDED, permalink_url=None),
        Reply(body=[1]),
        Reply(raw="<html>"),
        Reply(status=404, body={"message": "Not Found"}),
        Reply(status=403, body={"message": "Forbidden"}),
    ],
    ids=["merge-base", "behind-count", "no-ahead-count", "identical-different", "behind-merge-base",
         "diverged-merge-base", "status", "negative", "base-commit", "permalink-head", "permalink-repo",
         "permalink-host", "no-merge-base", "short-merge-base", "string-count", "no-permalink",
         "array", "not-json", "unknown-commit", "inaccessible"],
)  # fmt: skip
def test_unknown_or_contradictory_compare_evidence_fails_closed(reply: Reply) -> None:
    assert refused(lambda: reach(reply)).kind == "BLOCKED"


@pytest.mark.parametrize(
    "bad", ["main", LANDED[:12], LANDED.upper(), LANDED + "\n", "-" + LANDED[1:]]
)
def test_landing_reachable_rejects_non_object_ids_before_any_provider_call(
    bad: str,
) -> None:
    gh, fake, _ = make({})
    for landing, tip in ((bad, TIP), (LANDED, bad)):
        with pytest.raises(ValueError):
            gh.landing_reachable(landing, tip)
    assert fake.argvs == []


def test_landing_reachable_compares_in_the_current_base_repository() -> None:
    path = f"/repos/upstream/widget/compare/{LANDED}...{TIP}"
    reply = compare(
        LANDED, TIP, "ahead", 1, 0, LANDED,
        permalink_url=f"https://github.com/upstream/widget/compare/upstream:{LANDED}...upstream:{TIP}",
        url=f"https://api.github.com/repos/upstream/widget/compare/{LANDED}...{TIP}",
    )  # fmt: skip
    gh = GitHub("github.com", "upstream/widget", runner=FakeGH({path: reply}))
    assert gh.landing_reachable(LANDED, TIP) is True


# -- merge ---------------------------------------------------------------------


@pytest.mark.parametrize("method", ["merge", "squash", "rebase"])
def test_merge_at_the_verified_head_lands_through_the_requested_method_only(
    method: str,
) -> None:
    provider = Provider()
    gh, _ = provider_gh(provider)
    assert gh.merge(NUMBER, HEAD, method) is None
    pr = gh.read_pr(NUMBER)
    assert (pr.state, pr.merge_commit_sha, provider.merged_via) == (
        "MERGED",
        MERGE,
        method,
    )
    assert provider.admin_merges == 0 and provider.branch_deleted is False


def test_merge_for_a_moved_head_is_refused_by_github_and_changes_nothing() -> None:
    provider = Provider()
    provider.head = OTHER_HEAD  # pushed after the controller verified HEAD
    gh, sleeps = provider_gh(provider)
    err = refused(lambda: gh.merge(NUMBER, HEAD, "squash"))
    assert (err.kind, err.detail, err.uncertain) == (
        "WAITING",
        "merge-head-changed",
        False,
    )
    assert provider.state == "OPEN" and provider.merged_via is None
    assert len(provider.merge_calls) == 1 and sleeps == []


def test_merge_never_bypasses_unmet_policy_arms_auto_merge_or_deletes_branches() -> (
    None
):
    provider = Provider()
    provider.mergeable = False
    gh, _ = provider_gh(provider)
    err = refused(lambda: gh.merge(NUMBER, HEAD, "squash"))
    assert (err.kind, err.detail, err.uncertain) == (
        "BLOCKED",
        "merge-not-mergeable",
        False,
    )
    # --admin would have merged, --auto would have armed auto-merge
    assert (provider.state, provider.queue) == ("OPEN", "none")
    assert provider.admin_merges == 0 and provider.branch_deleted is False


def test_merge_never_bypasses_a_merge_queue_with_administrator_privileges() -> None:
    provider = Provider()
    provider.queue_branch = True
    gh, _ = provider_gh(provider)
    gh.merge(NUMBER, HEAD, "squash")
    assert provider.state == "OPEN" and provider.admin_merges == 0
    assert provider.queue == "queued"


def test_merge_method_disabled_by_the_repository_is_a_definite_refusal() -> None:
    provider = Provider()
    provider.allowed = {"squash"}
    err = refused(lambda: provider_gh(provider)[0].merge(NUMBER, HEAD, "merge"))
    assert (err.kind, err.detail, err.uncertain) == ("BLOCKED", "merge-rejected", False)
    assert provider.state == "OPEN"


def test_merge_without_head_guard_support_is_blocked_and_never_run_unguarded() -> None:
    provider = Provider()
    provider.help = OLD_GH_HELP
    gh, _ = provider_gh(provider)
    err = refused(lambda: gh.merge(NUMBER, HEAD, "squash"))
    assert (err.kind, err.detail, err.uncertain) == (
        "BLOCKED",
        "merge-capability-missing",
        False,
    )
    assert "--match-head-commit" in str(err)
    assert provider.merge_calls == [] and provider.state == "OPEN"


def test_merge_capability_is_probed_once_per_instance() -> None:
    provider = Provider()
    gh, _ = provider_gh(provider)
    gh.merge(NUMBER, HEAD, "squash")
    gh.merge(NUMBER, HEAD, "squash")  # already merged: gh exits 0, nothing changes
    assert provider.help_calls == 1 and provider.merged_via == "squash"


@pytest.mark.parametrize(
    ("fail", "kind", "detail", "status"),
    [
        ((1, "unknown flag: --match-head-commit"), "BLOCKED", "merge-usage-error", None),
        ((4, "To get started with GitHub CLI, please run:  gh auth login"), "BLOCKED", "merge-unauthenticated", 401),
        ((1, "HTTP 403: Resource not accessible by integration (https://api.github.com/graphql)"), "BLOCKED", "merge-rejected", 403),
        ((1, "HTTP 403: API rate limit exceeded for user ID 1."), "WAITING", "merge-rate-limited", None),
        ((1, "GraphQL: Base branch was modified. Review and try the merge again. (mergePullRequest)"), "WAITING", "merge-base-changed", None),
        ((1, "GraphQL: Pull request is closed. (mergePullRequest)"), "BLOCKED", "merge-rejected", None),
    ],
    ids=["usage", "unauthenticated", "forbidden", "rate-limited", "base-moved", "refused"],
)  # fmt: skip
def test_recognised_refusals_are_certain_and_never_retried(
    fail: tuple[int, str], kind: str, detail: str, status: int | None
) -> None:
    provider = Provider()
    provider.fail = fail
    gh, sleeps = provider_gh(provider)
    err = refused(lambda: gh.merge(NUMBER, HEAD, "squash"))
    assert (err.kind, err.detail, err.uncertain, err.http_status) == (
        kind,
        detail,
        False,
        status,
    )
    assert provider.state == "OPEN" and len(provider.merge_calls) == 1 and sleeps == []


@pytest.mark.parametrize(
    ("setup", "effect"),
    [
        ({"hang": "after"}, "MERGED"),
        ({"hang": "before"}, "OPEN"),
        ({"hang": "oserror"}, "OPEN"),
        ({"fail": (-9, "")}, "OPEN"),
        ({"fail": (1, "gh: something odd happened")}, "OPEN"),
        ({"fail": (1, "HTTP 502: Bad Gateway (https://api.github.com/graphql)")}, "OPEN"),
        ({"fail": (1, 'Post "https://api.github.com/graphql": EOF')}, "OPEN"),
        ({"fail": (1, 'Post "https://api.github.com/graphql": net/http: TLS handshake timeout')}, "OPEN"),
        ({"fail": (1, "GraphQL: Something went wrong while executing your query. (mergePullRequest)")}, "OPEN"),
    ],
    ids=["timeout-after-effect", "timeout-before-effect", "spawn-failure", "signal", "unrecognised",
         "bad-gateway", "eof", "tls-timeout", "graphql-internal"],
)  # fmt: skip
def test_possibly_dispatched_outcomes_are_uncertain_and_never_retried(
    setup: dict[str, Any], effect: str
) -> None:
    provider = Provider()
    for key, value in setup.items():
        setattr(provider, key, value)
    gh, sleeps = provider_gh(provider)
    err = refused(lambda: gh.merge(NUMBER, HEAD, "squash"))
    assert err.uncertain is True and "do not retry" in str(err)
    assert len(provider.merge_calls) == 1 and sleeps == []  # no blind second dispatch
    # classification is independent of whether the mutation took effect; the
    # caller reconciles from the provider
    assert gh.read_pr(NUMBER).state == provider.state == effect


def test_merge_errors_redact_credentials_and_never_echo_response_bodies() -> None:
    provider = Provider()
    provider.fail = (
        1,
        "Bearer ghp_abcdefghijklmnop1234\n" + "private-response-body " * 300,
    )
    err = refused(lambda: provider_gh(provider)[0].merge(NUMBER, HEAD, "squash"))
    shown = f"{err} {err.detail}"
    assert (
        "ghp_" not in shown
        and "private-response-body private-response-body" not in shown
    )
    assert len(shown) < 700


def test_merge_is_bounded_by_the_monitoring_deadline() -> None:
    provider = Provider()
    provider_gh(provider, deadline=30.0)[0].merge(NUMBER, HEAD, "squash")
    assert provider.merge_timeouts == [30.0]
    other = Provider()
    provider_gh(other)[0].merge(NUMBER, HEAD, "squash")
    assert 0 < other.merge_timeouts[0] <= github_ops.MERGE_TIMEOUT


def test_merge_is_not_started_without_time_to_finish() -> None:
    provider = Provider()
    gh, _ = provider_gh(provider, deadline=5.0)
    err = refused(lambda: gh.merge(NUMBER, HEAD, "squash"))
    assert (err.kind, err.detail, err.uncertain) == (
        "WAITING",
        "merge-not-dispatched",
        False,
    )
    assert provider.merge_calls == [] and provider.state == "OPEN"
    expired = Provider()
    err = refused(
        lambda: provider_gh(expired, deadline=0.0)[0].merge(NUMBER, HEAD, "squash")
    )
    assert (
        err.uncertain is False and expired.help_calls == 0 and expired.merge_calls == []
    )


@pytest.mark.parametrize(
    ("number", "head", "method"),
    [
        (0, HEAD, "squash"), (True, HEAD, "squash"), ("7", HEAD, "squash"),
        (NUMBER, HEAD[:12], "squash"), (NUMBER, "A" * 40, "squash"), (NUMBER, HEAD + "\n", "squash"),
        (NUMBER, "--admin", "squash"), (NUMBER, "main", "squash"),
        (NUMBER, HEAD, "admin"), (NUMBER, HEAD, "squash --admin"), (NUMBER, HEAD, "fast-forward"),
        (NUMBER, HEAD, ""), (NUMBER, HEAD, "SQUASH"),
    ],
)  # fmt: skip
def test_merge_inputs_are_validated_before_any_process_starts(
    number: Any, head: str, method: str
) -> None:
    provider = Provider()
    gh, _ = provider_gh(provider)
    with pytest.raises(ValueError):
        gh.merge(number, head, method)
    assert provider.argvs == []


def test_trailing_newlines_do_not_pass_repository_or_host_validation() -> None:
    with pytest.raises(ValueError):
        GitHub("github.com", "acme/widget\n")
    with pytest.raises(ValueError):
        GitHub("github.com\n", REPO)


@pytest.mark.parametrize(
    ("checks_green", "queued"), [(True, "QUEUED"), (False, "AUTO_MERGE")]
)
def test_merge_queue_acceptance_is_waiting_not_merged(
    checks_green: bool, queued: str
) -> None:
    provider = Provider()
    provider.queue_branch, provider.checks_green = True, checks_green
    gh, _ = provider_gh(provider)
    assert gh.merge(NUMBER, HEAD, "squash") is None  # the command was accepted ...
    assert gh.read_pr(NUMBER).state == "OPEN"  # ... nothing is merged yet
    assert gh.queue_state(NUMBER, HEAD) == queued
    provider.land()  # the queue (or auto-merge) completes later
    assert gh.read_pr(NUMBER).state == "MERGED"
    err = refused(lambda: gh.queue_state(NUMBER, HEAD))  # never IDLE once merged
    assert (err.kind, err.detail) == ("WAITING", "state-changed")


# -- queue_state ---------------------------------------------------------------


@pytest.mark.parametrize(
    "entry", ["QUEUED", "AWAITING_CHECKS", "MERGEABLE", "UNMERGEABLE", "LOCKED"]
)
def test_a_merge_queue_entry_is_queued_whatever_its_progress(entry: str) -> None:
    provider = Provider()
    provider.queue, provider.entry_state = "queued", entry
    assert provider_gh(provider)[0].queue_state(NUMBER, HEAD) == "QUEUED"


def test_armed_auto_merge_without_an_entry_is_auto_merge() -> None:
    provider = Provider()
    provider.queue = "auto"
    assert provider_gh(provider)[0].queue_state(NUMBER, HEAD) == "AUTO_MERGE"


def test_idle_needs_graphql_and_rest_to_agree_before_and_after_the_read() -> None:
    provider = Provider()
    assert provider_gh(provider)[0].queue_state(NUMBER, HEAD) == "IDLE"
    assert (
        provider.reads.count(f"/repos/{REPO}/pulls/{NUMBER}") == 2
        and len(provider.gql_calls) == 1
    )


def test_auto_merge_armed_during_the_read_is_not_idle() -> None:
    provider = Provider()
    provider.arm_on_pull_read = 2  # armed between the GraphQL read and the REST recheck
    err = refused(lambda: provider_gh(provider)[0].queue_state(NUMBER, HEAD))
    assert (err.kind, err.detail) == ("WAITING", "queue-sources-disagree")


@pytest.mark.parametrize(
    ("queue", "patch"),
    [
        ("auto", {"autoMergeRequest": None}),
        ("none", {"autoMergeRequest": {"mergeMethod": "SQUASH"}}),
    ],
    ids=["rest-only", "graphql-only"],
)
def test_sources_that_disagree_about_auto_merge_are_never_idle(
    queue: str, patch: dict[str, Any]
) -> None:
    provider = Provider()
    provider.queue, provider.gql_patch = queue, patch
    err = refused(lambda: provider_gh(provider)[0].queue_state(NUMBER, HEAD))
    assert (err.kind, err.detail) == ("WAITING", "queue-sources-disagree")


@pytest.mark.parametrize("where", ["rest", "graphql"])
def test_head_drift_is_waiting_never_idle_or_queued(where: str) -> None:
    provider = Provider()
    provider.queue = "queued"
    if where == "rest":
        provider.head = OTHER_HEAD
    else:
        provider.gql_patch = {"headRefOid": OTHER_HEAD}
    err = refused(lambda: provider_gh(provider)[0].queue_state(NUMBER, HEAD))
    assert (err.kind, err.detail) == ("WAITING", "head-changed")
    if where == "rest":
        assert provider.gql_calls == []  # stopped before asking for queue evidence


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
def test_a_pr_that_is_no_longer_open_is_never_idle(state: str) -> None:
    provider = Provider()
    provider.state = state
    err = refused(lambda: provider_gh(provider)[0].queue_state(NUMBER, HEAD))
    assert (err.kind, err.detail) == ("WAITING", "state-changed")
    racing = Provider()  # REST still open, GraphQL already merged
    racing.gql_patch = {"state": "MERGED", "merged": True}
    err = refused(lambda: provider_gh(racing)[0].queue_state(NUMBER, HEAD))
    assert (err.kind, err.detail) == ("WAITING", "state-changed")


_FORBIDDEN = Reply(
    status=200, exit_code=1, stderr="gh: Resource not accessible by integration",
    body={"data": {"repository": None}, "errors": [{"type": "FORBIDDEN", "message": "Resource not accessible by integration"}]},
)  # fmt: skip
_PARTIAL = Reply(
    body={
        "data": {"repository": {"nameWithOwner": REPO, "pullRequest": {
            "number": NUMBER, "state": "OPEN", "merged": False, "headRefOid": HEAD,
            "isInMergeQueue": False, "autoMergeRequest": None, "mergeQueueEntry": None}}},
        "errors": [{"type": "FORBIDDEN", "path": ["repository", "pullRequest", "mergeQueueEntry"],
                    "message": "Resource not accessible by integration"}],
    }
)  # fmt: skip


@pytest.mark.parametrize(
    ("reply", "patch"),
    [
        (_FORBIDDEN, {}),
        (_PARTIAL, {}),
        (Reply(body={"data": {"repository": None}}), {}),
        (Reply(body={"data": {"repository": {"nameWithOwner": REPO, "pullRequest": None}}}), {}),
        (Reply(body={"data": {"repository": {"nameWithOwner": "other/repo", "pullRequest": {}}}}), {}),
        (Reply(body={"data": None}), {}),
        (Reply(body=[1]), {}),
        (Reply(raw="<html>"), {}),
        (None, {"mergeQueueEntry": DROP}),
        (None, {"autoMergeRequest": DROP}),
        (None, {"isInMergeQueue": DROP}),
        (None, {"mergeQueueEntry": {"state": "FUTURE", "position": 1}, "isInMergeQueue": True}),
        (None, {"mergeQueueEntry": {"state": "QUEUED"}, "isInMergeQueue": True}),
        (None, {"isInMergeQueue": True}),
        (None, {"mergeQueueEntry": {"state": "QUEUED", "position": 1}}),
        (None, {"number": NUMBER + 1}),
        (None, {"headRefOid": "abc"}),
        (None, {"state": "SOMETHING"}),
        (None, {"merged": True}),
        (None, {"autoMergeRequest": {"mergeMethod": "FAST_FORWARD"}}),
    ],
    ids=["forbidden", "partial-with-errors", "repository-null", "pull-request-null", "other-repository",
         "data-null", "array", "not-json", "no-entry-field", "no-auto-field", "no-queue-flag",
         "unknown-entry-state", "entry-without-position", "queue-flag-without-entry",
         "entry-without-queue-flag", "other-number", "bad-head", "unknown-state", "merged-contradiction",
         "unknown-merge-method"],
)  # fmt: skip
def test_missing_partial_or_unsupported_queue_evidence_is_an_error_never_idle(
    reply: Reply | None, patch: dict[str, Any]
) -> None:
    provider = Provider()
    provider.gql_reply, provider.gql_patch = reply, patch
    err = refused(lambda: provider_gh(provider)[0].queue_state(NUMBER, HEAD))
    assert err.kind == "BLOCKED"


def test_graphql_errors_reported_with_a_success_exit_are_still_incomplete_evidence() -> (
    None
):
    provider = Provider()
    provider.gql_reply = Reply(body=_PARTIAL.body, exit_code=0)
    err = refused(lambda: provider_gh(provider)[0].queue_state(NUMBER, HEAD))
    assert err.kind == "BLOCKED"


def test_rest_without_the_auto_merge_property_is_not_read_as_no_auto_merge() -> None:
    provider = Provider()
    provider.rest_patch = {"auto_merge": DROP}
    assert (
        refused(lambda: provider_gh(provider)[0].queue_state(NUMBER, HEAD)).kind
        == "BLOCKED"
    )


def test_a_graphql_outage_is_waiting_after_bounded_read_retries() -> None:
    provider = Provider()
    provider.gql_reply = Reply(status=503, body={"message": "Service Unavailable"})
    gh, sleeps = provider_gh(provider)
    err = refused(lambda: gh.queue_state(NUMBER, HEAD))
    assert err.kind == "WAITING" and err.uncertain is False
    assert len(provider.gql_calls) == github_ops.MAX_ATTEMPTS and sleeps == [1.0, 2.0]


def test_queue_state_only_reads_and_never_touches_the_merge_command() -> None:
    provider = Provider()
    provider.queue = "queued"
    gh, _ = provider_gh(provider)
    assert gh.queue_state(NUMBER, HEAD) == "QUEUED"
    assert not any(argv[:2] == ("gh", "pr") for argv in provider.argvs)
    posts = [argv for argv in provider.argvs if argv[3] == "POST"]
    assert len(posts) == 1 and "--input" not in posts[0] and "-X" not in posts[0]
    assert provider.gql_calls[0]["number"] == str(NUMBER)
    assert provider.merge_calls == [] and provider.state == "OPEN"


@pytest.mark.parametrize(
    "bad",
    [
        (0, HEAD),
        (True, HEAD),
        (NUMBER, HEAD[:12]),
        (NUMBER, "main"),
        (NUMBER, HEAD + "\n"),
    ],
)
def test_queue_state_rejects_invalid_inputs_before_any_provider_call(
    bad: tuple[Any, str],
) -> None:
    provider = Provider()
    with pytest.raises(ValueError):
        provider_gh(provider)[0].queue_state(*bad)
    assert provider.argvs == []


# -- merge_queue policy ----------------------------------------------------------


def _queue_rule(method: Any = "SQUASH", **over: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "check_response_timeout_minutes": 60,
        "grouping_strategy": "ALLGREEN",
        "max_entries_to_build": 5,
        "max_entries_to_merge": 5,
        "merge_method": method,
        "min_entries_to_merge": 1,
        "min_entries_to_merge_wait_minutes": 5,
    }
    params.update(over)
    return {"type": "merge_queue", "parameters": params}


def _queue_observation(*rules: dict[str, Any]) -> Observation:
    return observe(routes() | {f"/repos/{REPO}/rules/branches/main": _ruleset(*rules)})


def test_branches_without_a_queue_rule_do_not_require_a_queue() -> None:
    obs = observe(routes())
    assert obs.queue_required is False and obs.policy_known is True


@pytest.mark.parametrize(
    ("method", "allowed"), [("SQUASH", ("squash",)), ("MERGE", ("merge",))]
)
def test_a_queue_rule_requires_the_queue_and_pins_its_merge_method(
    method: str, allowed: tuple[str, ...]
) -> None:
    obs = _queue_observation(_queue_rule(method))
    assert obs.queue_required is True and obs.policy_known is True
    assert (
        obs.repo.allowed_merge_methods == allowed
    )  # repository enables merge + squash


def test_a_queue_method_the_repository_disables_leaves_no_permitted_method() -> None:
    obs = _queue_observation(
        _queue_rule("REBASE")
    )  # routes(): rebase merges are disabled
    assert obs.queue_required is True and obs.repo.allowed_merge_methods == ()
    assert has_issue(obs, "no-merge-method")


def test_queue_method_is_intersected_with_other_method_rules() -> None:
    obs = _queue_observation(
        {"type": "pull_request", "parameters": {"required_approving_review_count": 0, "allowed_merge_methods": ["merge", "rebase"]}},
        _queue_rule("SQUASH"),
    )  # fmt: skip
    assert obs.queue_required is True and obs.repo.allowed_merge_methods == ()
    conflicting = _queue_observation(_queue_rule("SQUASH"), _queue_rule("MERGE"))
    assert conflicting.repo.allowed_merge_methods == ()


@pytest.mark.parametrize(
    "rule",
    [
        {"type": "merge_queue"},
        {"type": "merge_queue", "parameters": {}},
        _queue_rule("FAST_FORWARD"),
        _queue_rule("squash"),
        _queue_rule(None),
        {"type": "merge_queue", "parameters": {"merge_method": ["SQUASH"]}},
    ],
    ids=[
        "no-parameters",
        "empty-parameters",
        "unknown-method",
        "lowercase-method",
        "null-method",
        "wrong-type",
    ],
)
def test_a_queue_whose_method_cannot_be_read_blocks_instead_of_assuming_one(
    rule: dict[str, Any],
) -> None:
    obs = _queue_observation(rule)
    assert obs.queue_required is True and obs.policy_known is False


def test_other_unsupported_rules_still_fail_closed_next_to_a_queue_rule() -> None:
    obs = _queue_observation(
        _queue_rule("SQUASH"), {"type": "workflows", "parameters": {"workflows": []}}
    )
    assert obs.queue_required is True and obs.policy_known is False
    assert has_issue(obs, "unevaluated-policy")


def test_unreadable_rules_make_queue_required_a_lower_bound_not_a_denial() -> None:
    obs = observe(
        routes()
        | {
            f"/repos/{REPO}/rules/branches/main": Reply(
                status=404, body={"message": "Not Found"}
            )
        }
    )
    assert (obs.queue_required, obs.policy_known) == (False, False)


@pytest.mark.parametrize(
    ("queue_method", "decision_method", "status"),
    [
        ("SQUASH", "squash", "READY"),
        ("MERGE", "squash", "BLOCKED"),
        ("SQUASH", "merge", "BLOCKED"),
        ("REBASE", "rebase", "BLOCKED"),
    ],
)
def test_permission_to_land_follows_the_queues_configured_method(
    queue_method: str, decision_method: str, status: str
) -> None:
    from lifecycle import Policy, evaluate

    report = check_run(1000, "test")
    report["app"]["id"] = 42
    table = with_ci([run(10, suite=100)], [report])
    table[f"/repos/{REPO}/rules/branches/main"] = _ruleset(
        {"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": "test", "integration_id": 42}],
            "strict_required_status_checks_policy": False}},
        _queue_rule(queue_method),
    )  # fmt: skip
    decision = Policy(
        ("current workflow and provider policy",),
        ("test",),
        decision_method,
        (),
        HEAD,
        BASE,
        assurance="high",
    )
    obs = observe(table)
    assert obs.queue_required is True
    assert evaluate(obs, decision).status == status


def test_inflight_transport_invalid_argument_is_not_certain_usage_failure() -> None:
    provider = Provider()
    provider.fail = (
        1,
        'Post "https://api.github.com/graphql": write tcp 10.0.0.2:51234->140.82.112.6:443: write: invalid argument',
    )
    error = refused(lambda: provider_gh(provider)[0].merge(NUMBER, HEAD, "squash"))
    assert error.uncertain is True
    assert len(provider.merge_calls) == 1


@pytest.mark.parametrize("exit_code", [0, 1])
def test_graphql_http_200_rate_limit_waits_without_rejecting_queue(
    exit_code: int,
) -> None:
    provider = Provider()
    provider.gql_reply = Reply(
        status=200,
        exit_code=exit_code,
        headers={"x-ratelimit-remaining": "0"},
        stderr="gh: API rate limit exceeded for user ID 1.",
        body={
            "errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]
        },
    )
    gh, sleeps = provider_gh(provider)
    error = refused(lambda: gh.queue_state(NUMBER, HEAD))
    assert error.kind == "WAITING"
    assert provider.state == "OPEN" and provider.queue == "none"
    assert provider.merge_calls == [] and sleeps == []


# --------------------------------------------------------------------------
# Exact PR lookup and creation

PULLS = f"/repos/{REPO}/pulls"


def head_row(
    number: int,
    *,
    head_repo: str | None = REPO,
    ref: str = "feat/x",
    state: str = "open",
) -> dict[str, Any]:
    row = pull(
        number=number,
        html_url=f"https://github.com/{REPO}/pull/{number}",
        state=state,
        head={
            "sha": HEAD,
            "ref": ref,
            "repo": None if head_repo is None else {"full_name": head_repo},
        },
    )
    row.pop("merged"), row.pop("mergeable")
    return row


def query_of(argv: tuple[str, ...]) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(argv[-1]).query))


def test_find_prs_reads_every_page_of_the_exact_head_query() -> None:
    rows = [head_row(n, state="open" if n == 1 else "closed") for n in range(1, 131)]
    gh, fake, _ = make({PULLS: paged(rows)})

    found = gh.find_prs(REPO, "refs/heads/feat/x", "main")

    assert [pr.number for pr in found] == list(range(1, 131))
    assert [pr.state for pr in found[:2]] == ["OPEN", "CLOSED"]
    assert fake.count(PULLS) == 2
    query = query_of(fake.argvs[0])
    assert (query["head"], query["base"], query["state"]) == (
        "acme:feat/x",
        "main",
        "all",
    )


def test_find_prs_keeps_a_fork_head_namespace_apart_from_the_base() -> None:
    gh, fake, _ = make({PULLS: paged([head_row(3, head_repo="contrib/widget")])})

    [pr] = gh.find_prs("contrib/widget", "feat/x")

    assert (pr.number, pr.head_repo, pr.base_repo) == (3, "contrib/widget", REPO)
    assert query_of(fake.argvs[0])["head"] == "contrib:feat/x"


def test_find_prs_excludes_another_repository_of_the_same_owner() -> None:
    rows = [head_row(1, head_repo="acme/other"), head_row(2)]
    gh, _, _ = make({PULLS: paged(rows)})

    assert [pr.number for pr in gh.find_prs(REPO, "feat/x")] == [2]


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(head_row(1, head_repo=None), id="unreadable-head-repository"),
        pytest.param(head_row(1, ref="feat/other"), id="head-ref-contradicts-query"),
        pytest.param(
            {**head_row(1), "html_url": f"https://github.com/{REPO}/pull/9"},
            id="url-of-another-pr",
        ),
        pytest.param(
            {
                **head_row(1),
                "base": {"sha": BASE, "ref": "main", "repo": {"full_name": "x/y"}},
            },
            id="another-base-repository",
        ),
    ],
)
def test_find_prs_never_reads_incomplete_or_contradictory_evidence_as_absence(
    row: dict[str, Any],
) -> None:
    gh, _, _ = make({PULLS: paged([row])})

    with pytest.raises(ProviderError):
        gh.find_prs(REPO, "feat/x")


def test_find_prs_inaccessible_listing_is_an_error_not_an_empty_answer() -> None:
    gh, _, _ = make(
        {PULLS: Reply(status=403, body={"message": "Resource not accessible"})}
    )

    with pytest.raises(ProviderError):
        gh.find_prs(REPO, "feat/x")


def created(number: int = NUMBER, **over: Any) -> Reply:
    return Reply(
        status=201,
        body=pull(
            number=number, html_url=f"https://github.com/{REPO}/pull/{number}", **over
        ),
    )


def body_file(tmp_path: Path) -> Path:
    path = tmp_path / "body.md"
    path.write_bytes(b"## Changes\n$(touch pwned) `rm -rf /`\n")
    return path


def test_create_pr_sends_one_post_with_plain_title_and_the_body_as_a_file(
    tmp_path: Path,
) -> None:
    body = body_file(tmp_path)
    gh, fake, _ = make({PULLS: created()})

    pr = gh.create_pr(REPO, "feat/x", "main", "feat: add $(widget)", body)

    assert (pr.number, pr.state, pr.head_ref, pr.base_ref) == (
        NUMBER,
        "OPEN",
        "feat/x",
        "main",
    )
    [argv] = fake.argvs
    assert argv[:4] == ("gh", "api", "--method", "POST")
    assert {
        "title=feat: add $(widget)",
        "head=feat/x",
        "base=main",
        f"body=@{body}",
    } <= set(argv)
    assert not any("rm -rf" in part for part in argv)


@pytest.mark.parametrize(
    ("head_repo", "fields"),
    [
        ("contrib/widget", {"head=contrib:feat/x"}),
        ("acme/widget-fork", {"head=acme:feat/x", "head_repo=widget-fork"}),
    ],
)
def test_create_pr_names_a_fork_head_namespace_explicitly(
    tmp_path: Path, head_repo: str, fields: set[str]
) -> None:
    head = {"sha": HEAD, "ref": "feat/x", "repo": {"full_name": head_repo}}
    gh, fake, _ = make({PULLS: created(head=head)})

    pr = gh.create_pr(head_repo, "feat/x", "main", "feat: x", body_file(tmp_path))

    assert (pr.head_repo, pr.base_repo) == (head_repo, REPO)
    [argv] = fake.argvs
    assert fields <= set(argv)


def test_create_pr_duplicate_refusal_names_the_existing_pr_condition(
    tmp_path: Path,
) -> None:
    duplicate = Reply(
        status=422,
        body={
            "message": "Validation Failed",
            "errors": [{"message": "A pull request already exists for acme:feat/x."}],
        },
    )
    gh, fake, _ = make({PULLS: duplicate})

    with pytest.raises(ProviderError) as caught:
        gh.create_pr(REPO, "feat/x", "main", "feat: x", body_file(tmp_path))

    assert (caught.value.detail, caught.value.uncertain) == ("pr-already-exists", False)
    assert len(fake.argvs) == 1


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(
            Reply(
                status=403, body={"message": "Resource not accessible by integration"}
            ),
            id="permission",
        ),
        pytest.param(
            Reply(
                status=422,
                body={
                    "message": "Validation Failed",
                    "errors": [{"message": "No commits between main and feat/x"}],
                },
            ),
            id="validation",
        ),
    ],
)
def test_create_pr_definite_refusal_is_final_not_uncertain(
    tmp_path: Path, reply: Reply
) -> None:
    gh, fake, _ = make({PULLS: reply})

    with pytest.raises(ProviderError) as caught:
        gh.create_pr(REPO, "feat/x", "main", "feat: x", body_file(tmp_path))

    error = caught.value
    assert (error.kind, error.detail, error.uncertain) == (
        "BLOCKED",
        "create-rejected",
        False,
    )
    assert len(fake.argvs) == 1


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(
            Reply(status=503, body={"message": "unavailable"}), id="transient"
        ),
        pytest.param(Reply(status=201, raw="{not json"), id="unreadable-created"),
        pytest.param(
            created(base={"sha": BASE, "ref": "develop", "repo": {"full_name": REPO}}),
            id="created-identity-contradicts-request",
        ),
    ],
)
def test_create_pr_unknown_outcome_is_uncertain_and_never_resent(
    tmp_path: Path, reply: Reply
) -> None:
    gh, fake, _ = make({PULLS: reply})

    with pytest.raises(ProviderError) as caught:
        gh.create_pr(REPO, "feat/x", "main", "feat: x", body_file(tmp_path))

    assert caught.value.uncertain is True
    assert len(fake.argvs) == 1


def test_create_pr_timeout_is_uncertain_and_never_resent(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def hang(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
        calls.append(tuple(argv))
        raise subprocess.TimeoutExpired(list(argv), timeout)

    gh = GitHub(
        "github.com", REPO, runner=hang, sleep=lambda _: None, clock=lambda: 0.0
    )

    with pytest.raises(ProviderError) as caught:
        gh.create_pr(REPO, "feat/x", "main", "feat: x", body_file(tmp_path))

    assert (caught.value.kind, caught.value.uncertain) == ("WAITING", True)
    assert len(calls) == 1


def test_create_pr_rejects_a_multi_line_title_before_any_process(
    tmp_path: Path,
) -> None:
    gh, fake, _ = make({PULLS: created()})

    with pytest.raises(ValueError):
        gh.create_pr(REPO, "feat/x", "main", "feat: x\n$(id)", body_file(tmp_path))

    assert fake.argvs == []


# --------------------------------------------------------------------------
# Native stacks and asynchronous merge requests

STACK = 12
TRUNK = "qual/trunk"
UUID = "6aa849f9-5647-4c96-a58d-8019d8830a2c"
OTHER_UUID = "c1e61598-c685-45a7-85e2-b03b271a6950"
API = "https://api.github.com"
NATIVE_LANDED = {4: "3071156d680bc71a453c6218db381349365fc2d4",
          5: "648f5b07c0efd27488c3d7ea661b3520fc3d6162"}  # fmt: skip


@dataclass
class Member:
    number: int
    head: str
    head_ref: str
    base_ref: str
    state: str = "OPEN"  # OPEN | MERGED
    landing: str | None = None
    head_repo: str = REPO
    stack: dict[str, Any] | None = field(default_factory=dict)  # None: no stack


@dataclass(frozen=True)
class Operation:
    """One async merge GitHub accepted: the open native prefix it merges."""

    uuid: str
    action: str
    method: str  # "default" when the request named none
    scope: tuple[int, ...]
    bypass_rules: bool = False


QUEUE_CUSTOM_PARAMS = (
    "Custom merge params (merge_method, commit_title, commit_message) are "
    "not supported with the merge_queue merge action."
)
HEAD_MODIFIED = "Head branch was modified. Review and try the merge again."


def refusal(status: int, message: str) -> Reply:
    return Reply(status, {"message": message}, stderr=f"gh: {message} (HTTP {status})")


class NativeProvider:
    """Stateful double of one native stack, its member PRs and async merge requests.

    Shapes follow the REST ``stacks``, ``pulls`` and ``merge-async`` responses.
    Landing changes PR facts only; the async request status is a separate
    resource that changes independently, as GitHub reports them.
    """

    def __init__(self, count: int = 3, first: int = 4) -> None:
        self.members: dict[int, Member] = {}
        below = TRUNK
        for offset in range(count):
            number = first + offset
            ref = f"stack/layer{offset + 1}"
            self.members[number] = Member(number, sha(0x100 + number), ref, below)
            below = ref
        self.order: list[int] = list(self.members)  # the stack listing order
        self.after_first_stack_read: Callable[[], None] | None = None
        self.queue_method: str | None = None  # ruleset merge-queue method on TRUNK
        self.rules_reply: Reply | None = None
        self.listing_patch: dict[str, Any] = {}
        self.put_replies: list[Reply] = []
        self.put_raises: BaseException | None = None
        self.status_replies: list[Reply] = []
        self.request_status = "pending"
        self.request_landing: str | None = None
        self.request_message: str | None = None  # GitHub's reason for "failed"
        self.puts: list[dict[str, str]] = []  # every PUT received, for counting
        self.operations: list[Operation] = []  # accepted async merges
        self.paths: list[str] = []
        self.timeouts: list[float] = []
        self.stack_reads = 0

    def land(self, *numbers: int) -> None:
        """Members land; the provider retargets the lowest open member to the trunk."""
        for number in numbers:
            member = self.members[number]
            member.state, member.landing = "MERGED", NATIVE_LANDED[number]
        remaining = [m for m in self.members.values() if m.state == "OPEN"]
        if remaining:
            remaining[0].base_ref = TRUNK

    def __call__(
        self, argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        self.timeouts.append(timeout)
        if argv[-1] == "graphql":
            return render(argv, self._landing(argv))
        method = argv[list(argv).index("--method") + 1]
        path = urlsplit(argv[-1]).path
        self.paths.append(f"{method} {path}")
        if method == "PUT":
            return self._put(argv, path)
        assert method == "GET", argv
        return render(argv, self._get(path))

    def _put(
        self, argv: Sequence[str], path: str
    ) -> subprocess.CompletedProcess[bytes]:
        """Validate and accept one request as GitHub does; refusals accept nothing.

        The accepted operation covers every open member from the stack bottom
        up to the selected PR; members above it are not part of it. While an
        accepted request covering the selected PR is pending, a new one is
        refused with 409 naming that request and its options.
        """
        assert path.endswith("/merge-async"), path
        fields = {
            name: value
            for flag, item in itertools.pairwise(argv)
            if flag in ("-f", "-F")
            for name, _, value in [item.partition("=")]
        }
        self.puts.append(fields)
        if self.put_raises is not None:
            raise self.put_raises
        if self.put_replies:
            return render(argv, self.put_replies.pop(0))
        number = int(path.rsplit("/", 2)[1])
        selected = self.members[number]
        active = [op for op in self.operations if number in op.scope]
        if active and self.request_status == "pending":
            details = self._details(active[-1], selected.head)
            return render(argv, Reply(409, {"status": "pending", "details": details}))
        action = fields["merge_action"]
        custom = {"merge_method", "commit_title", "commit_message"} & fields.keys()
        if action == "merge_queue" and custom:
            return render(argv, refusal(422, QUEUE_CUSTOM_PARAMS))
        if fields.get("sha", selected.head) != selected.head:
            return render(argv, refusal(409, HEAD_MODIFIED))
        bottom_up = list(self.members)
        operation = Operation(
            uuid=UUID,
            action=action,
            method=fields.get("merge_method", "default"),
            scope=tuple(
                n
                for n in bottom_up[: bottom_up.index(number) + 1]
                if self.members[n].state == "OPEN"
            ),
            bypass_rules=fields.get("bypass_rules") == "true",
        )
        self.operations.append(operation)
        details = self._details(operation, selected.head)
        return render(argv, Reply(202, {"status": "pending", "details": details}))

    @staticmethod
    def _details(operation: Operation, head: str) -> dict[str, Any]:
        return {
            "message": "Merge request enqueued.",
            "uuid": operation.uuid,
            "merge_method": operation.method,
            "merge_action": operation.action,
            "expected_head_sha": head,
            "bypass_rules": operation.bypass_rules,
        }

    def _get(self, path: str) -> Reply:
        base = f"/repos/{REPO}"
        if path == base:
            return Reply(body={"full_name": REPO, "default_branch": "main",
                               "allow_merge_commit": True, "allow_squash_merge": True,
                               "allow_rebase_merge": True})  # fmt: skip
        if path == f"{base}/stacks/{STACK}":
            self.stack_reads += 1
            body = self._listing()
            if self.stack_reads == 1 and self.after_first_stack_read is not None:
                self.after_first_stack_read()
            return Reply(body=body)
        if "/merge-async/" in path:
            if self.status_replies:
                return self.status_replies.pop(0)
            message = self.request_message
            if message is None:
                message = f"request is {self.request_status}"
            details: dict[str, Any] = {"message": message}
            if self.request_landing is not None:
                details["sha"] = self.request_landing
            return Reply(body={"status": self.request_status, "details": details})
        if path.startswith(f"{base}/pulls/"):
            return Reply(body=self._pull(self.members[int(path.rsplit("/", 1)[1])]))
        if path == f"{base}/branches/{TRUNK}":
            return Reply(body=branch(BASE, TRUNK))
        if path == f"{base}/rules/branches/{TRUNK}":
            if self.rules_reply is not None:
                return self.rules_reply
            params = {"merge_method": self.queue_method}
            queue = {"type": "merge_queue", "parameters": params}
            return Reply(body=[queue] if self.queue_method else [])
        raise AssertionError(f"unrouted provider read: {path}")

    def _pull(self, member: Member) -> dict[str, Any]:
        merged = member.state == "MERGED"
        body = pull(
            number=member.number,
            html_url=f"https://github.com/{REPO}/pull/{member.number}",
            state="closed" if merged else "open",
            merged=merged,
            merged_at=MERGE_DATE if merged else None,
            head={"sha": member.head, "ref": member.head_ref,
                  "repo": {"full_name": member.head_repo}},
            base={"sha": BASE, "ref": member.base_ref, "repo": {"full_name": REPO}},
        )  # fmt: skip
        if member.stack is not None:
            body["stack"] = {
                "id": 2043368,
                "number": STACK,
                "position": list(self.members).index(member.number) + 1,
                "size": len(self.members),
                "base": {"ref": TRUNK, "sha": BASE},
            } | member.stack
        return body

    def _listing(self) -> dict[str, Any]:
        def entry(member: Member) -> dict[str, Any]:
            merged = member.state == "MERGED"
            return {
                "url": f"{API}/repos/{REPO}/pulls/{member.number}",
                "number": member.number,
                "head": {"ref": member.head_ref, "sha": member.head,
                         "repo": {"url": f"{API}/repos/{member.head_repo}"}},
                "base": {"ref": member.base_ref, "sha": BASE,
                         "repo": {"url": f"{API}/repos/{REPO}"}},
                "state": "closed" if merged else "open",
                "merged_at": MERGE_DATE if merged else None,
            }  # fmt: skip

        return {
            "id": 2043368,
            "number": STACK,
            "url": f"{API}/repos/{REPO}/stacks/{STACK}",
            "base": {"ref": TRUNK},
            "open": True,
            "pull_requests": [entry(self.members[n]) for n in self.order],
        } | self.listing_patch

    def _landing(self, argv: Sequence[str]) -> Reply:
        fields = {
            item.partition("=")[0]: item.partition("=")[2]
            for flag, item in itertools.pairwise(argv)
            if flag in ("-f", "-F")
        }
        member = self.members[int(fields["number"])]
        assert member.state == "MERGED", "landing facts are read only for merged PRs"
        pr = {"number": member.number, "state": "MERGED", "merged": True,
              "url": f"https://github.com/{REPO}/pull/{member.number}",
              "headRefOid": member.head, "headRefName": member.head_ref,
              "baseRefName": member.base_ref, "mergedAt": MERGE_DATE,
              "mergeCommit": {"oid": member.landing}}  # fmt: skip
        repository = {"nameWithOwner": REPO, "pullRequest": pr}
        return Reply(body={"data": {"repository": repository}})


def native_gh(provider: NativeProvider, **kwargs: Any) -> tuple[GitHub, list[float]]:
    sleeps: list[float] = []
    gh = GitHub(
        "github.com", REPO, runner=provider, sleep=sleeps.append, clock=lambda: 0.0,
        **kwargs,
    )  # fmt: skip
    return gh, sleeps


def outcome(error: ProviderError) -> tuple[str, str]:
    return error.kind, error.detail


def test_read_native_stack_returns_members_bottom_up_from_authoritative_reads() -> None:
    provider = NativeProvider()

    stack = native_gh(provider)[0].read_native_stack(STACK)

    assert (stack.number, stack.base_ref) == (STACK, TRUNK)
    assert [(m.number, m.head_sha, m.base_ref, m.state) for m in stack.members] == [
        (4, sha(0x104), TRUNK, "OPEN"),
        (5, sha(0x105), "stack/layer1", "OPEN"),
        (6, sha(0x106), "stack/layer2", "OPEN"),
    ]
    assert [m.native_stack_position for m in stack.members] == [1, 2, 3]
    assert all(f"GET /repos/{REPO}/pulls/{n}" in provider.paths for n in (4, 5, 6))
    assert provider.stack_reads == 2


def test_read_native_stack_keeps_merged_members_with_their_landing_facts() -> None:
    provider = NativeProvider()
    provider.land(4, 5)

    stack = native_gh(provider)[0].read_native_stack(STACK)

    facts = [(m.number, m.state, m.merge_commit_sha, m.base_ref) for m in stack.members]
    assert facts == [
        (4, "MERGED", NATIVE_LANDED[4], TRUNK),
        (5, "MERGED", NATIVE_LANDED[5], "stack/layer1"),
        (6, "OPEN", None, TRUNK),
    ]


def _misorder(p: NativeProvider) -> None:
    p.order = [5, 4, 6]


def _duplicate(p: NativeProvider) -> None:
    p.order = [4, 4, 5, 6]


def _short_listing(p: NativeProvider) -> None:
    p.order = [4, 5]


def _foreign_head(p: NativeProvider) -> None:
    p.members[5].head_repo = "fork-owner/widget"


def _wrong_size(p: NativeProvider) -> None:
    p.members[6].stack = {"size": 4}


def _other_stack(p: NativeProvider) -> None:
    p.members[5].stack = {"number": STACK + 1}


def _other_trunk(p: NativeProvider) -> None:
    p.members[4].stack = {"base": {"ref": "main"}}


def _not_native(p: NativeProvider) -> None:
    p.members[6].stack = None


def _broken_chain(p: NativeProvider) -> None:
    p.members[6].base_ref = "unrelated"


def _merged_above_open(p: NativeProvider) -> None:
    p.members[5].state, p.members[5].landing = "MERGED", NATIVE_LANDED[5]


@pytest.mark.parametrize(
    "corrupt",
    [_misorder, _duplicate, _short_listing, _foreign_head, _wrong_size, _other_stack,
     _other_trunk, _not_native, _broken_chain, _merged_above_open],
)  # fmt: skip
def test_read_native_stack_rejects_inconsistent_membership(
    corrupt: Callable[[NativeProvider], None],
) -> None:
    provider = NativeProvider()
    corrupt(provider)

    with pytest.raises(ProviderError) as caught:
        native_gh(provider)[0].read_native_stack(STACK)

    assert outcome(caught.value) == ("BLOCKED", "native-stack-mismatch")


@pytest.mark.parametrize(
    "listing",
    [
        {"number": STACK + 1, "url": f"{API}/repos/{REPO}/stacks/{STACK + 1}"},
        {"url": f"{API}/repos/other/repo/stacks/{STACK}"},
        {"pull_requests": []},
    ],
)
def test_read_native_stack_rejects_a_listing_for_another_stack_or_none(
    listing: dict[str, Any],
) -> None:
    provider = NativeProvider()
    provider.listing_patch = listing

    with pytest.raises(ProviderError) as caught:
        native_gh(provider)[0].read_native_stack(STACK)

    assert outcome(caught.value) == ("BLOCKED", "native-stack-mismatch")


def test_read_native_stack_rejects_membership_that_moves_between_reads() -> None:
    provider = NativeProvider(count=4)
    provider.order = [4, 5, 6]
    provider.members[7].stack = {"size": 3}

    def grow() -> None:
        provider.order = [4, 5, 6, 7]

    provider.after_first_stack_read = grow
    for member in (4, 5, 6):
        provider.members[member].stack = {"size": 3}

    with pytest.raises(ProviderError) as caught:
        native_gh(provider)[0].read_native_stack(STACK)

    assert outcome(caught.value) == ("WAITING", "native-stack-changed")


def test_read_native_stack_rejects_a_head_pushed_after_the_listing() -> None:
    provider = NativeProvider()

    def push() -> None:
        provider.members[5].head = OTHER_HEAD

    provider.after_first_stack_read = push

    with pytest.raises(ProviderError) as caught:
        native_gh(provider)[0].read_native_stack(STACK)

    assert outcome(caught.value) == ("WAITING", "native-stack-changed")


def test_native_trunk_policy_routes_by_the_stack_base_queue_rules() -> None:
    provider = NativeProvider()
    provider.queue_method = "SQUASH"
    gh, _ = native_gh(provider)
    stack = gh.read_native_stack(STACK)
    provider.paths.clear()

    policy = gh.native_trunk_policy(stack)

    assert (policy.trunk, policy.action) == (TRUNK, "merge_queue")
    assert policy.methods == ("squash",)
    branch_reads = [p for p in provider.paths if "/branches/" in p]
    assert branch_reads and all(TRUNK in p for p in branch_reads)


def test_native_trunk_policy_is_direct_only_when_fully_known() -> None:
    provider = NativeProvider()
    gh, _ = native_gh(provider)
    stack = gh.read_native_stack(STACK)
    direct = gh.native_trunk_policy(stack)
    provider.rules_reply = Reply(403, {"message": "Resource not accessible"})

    unknown = gh.native_trunk_policy(stack)

    assert (direct.action, direct.methods, direct.policy_known) == (
        "direct_merge", ("merge", "squash", "rebase"), True,
    )  # fmt: skip
    assert (unknown.action, unknown.policy_known) == (None, False)


def test_start_native_merge_direct_merges_the_prefix_up_to_the_selected_pr() -> None:
    provider = NativeProvider()
    head = provider.members[5].head
    gh, sleeps = native_gh(provider)

    result = gh.start_native_merge(5, head, "squash", "direct_merge")

    assert provider.operations == [Operation(UUID, "direct_merge", "squash", (4, 5))]
    assert (result.status, result.uuid, result.expected_head_sha, result.sha) == (
        "pending", UUID, head, None,
    )  # fmt: skip
    assert sleeps == []


def test_start_native_merge_queue_is_accepted_by_the_strict_provider() -> None:
    provider = NativeProvider()
    head = provider.members[5].head
    gh, _ = native_gh(provider)

    with pytest.raises(ValueError):
        gh.start_native_merge(5, head, "squash", "merge_queue")
    assert provider.puts == []

    result = gh.start_native_merge(5, head, None, "merge_queue")

    assert provider.operations == [Operation(UUID, "merge_queue", "default", (4, 5))]
    assert (result.status, result.uuid, result.expected_head_sha) == (
        "pending", UUID, head,
    )  # fmt: skip


def test_start_native_merge_excludes_members_that_already_landed() -> None:
    provider = NativeProvider()
    provider.land(4)
    gh, _ = native_gh(provider)

    gh.start_native_merge(6, provider.members[6].head, "merge", "direct_merge")

    assert provider.operations == [Operation(UUID, "direct_merge", "merge", (5, 6))]


@pytest.mark.parametrize(
    ("method", "action"), [("squash", "direct_merge"), (None, "merge_queue")]
)
def test_start_native_merge_head_pushed_after_the_snapshot_is_refused(
    method: str | None, action: str
) -> None:
    provider = NativeProvider()
    expected_head = provider.members[5].head
    gh, sleeps = native_gh(provider)
    provider.members[5].head = OTHER_HEAD  # pushed before the request is sent

    with pytest.raises(ProviderError) as caught:
        gh.start_native_merge(5, expected_head, method, action)

    assert outcome(caught.value) == ("WAITING", "native-merge-head-changed")
    assert caught.value.uncertain is False
    assert provider.operations == []
    assert (len(provider.puts), sleeps) == (1, [])


@pytest.mark.parametrize(
    ("method", "action"),
    [("squash", "merge_queue"), (None, "direct_merge"), ("fast-forward", "direct_merge"),
     ("fast-forward", "default"), (None, "merge")],
)  # fmt: skip
def test_start_native_merge_rejects_inexact_options_before_any_dispatch(
    method: str | None, action: str
) -> None:
    provider = NativeProvider()
    gh, _ = native_gh(provider)

    with pytest.raises(ValueError):
        gh.start_native_merge(5, provider.members[5].head, method, action)

    assert provider.paths == []


def test_start_native_merge_definite_422_refusal_is_not_uncertain() -> None:
    provider = NativeProvider()
    provider.put_replies = [refusal(422, QUEUE_CUSTOM_PARAMS)]
    gh, _ = native_gh(provider)

    with pytest.raises(ProviderError) as caught:
        gh.start_native_merge(5, provider.members[5].head, None, "merge_queue")

    error = caught.value
    assert (error.kind, error.uncertain, error.http_status, error.detail) == (
        "BLOCKED", False, 422, "native-merge-rejected",
    )  # fmt: skip
    assert len(provider.puts) == 1


def test_start_native_merge_409_surfaces_the_existing_request_identity() -> None:
    provider = NativeProvider()
    head = provider.members[5].head
    existing = {"status": "pending", "details": {
        "message": "A merge request is already in progress.", "uuid": OTHER_UUID,
        "merge_method": "merge", "merge_action": "direct_merge",
        "expected_head_sha": head, "bypass_rules": False}}  # fmt: skip
    provider.put_replies = [Reply(409, existing)]

    with pytest.raises(github_ops.NativeMergeInProgress) as caught:
        native_gh(provider)[0].start_native_merge(5, head, "squash", "direct_merge")

    error = caught.value
    assert (error.kind, error.uncertain, error.http_status) == ("WAITING", False, 409)
    assert (error.existing.uuid, error.existing.status) == (OTHER_UUID, "pending")
    assert len(provider.puts) == 1
    assert not error.existing.matches("direct_merge", "squash", head)
    assert error.existing.matches("direct_merge", "merge", head)


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ((None, "merge_queue"), (None, "merge_queue"), True),
        (("squash", "direct_merge"), ("squash", "direct_merge"), True),
        ((None, "default"), (None, "merge_queue"), False),
        (("merge", "direct_merge"), ("squash", "direct_merge"), False),
        (("squash", "default"), (None, "default"), False),
    ],
)  # fmt: skip
def test_request_already_in_flight_reconciles_by_its_exact_options(
    first: tuple[str | None, str],
    second: tuple[str | None, str],
    same: bool,
) -> None:
    provider = NativeProvider()
    head = provider.members[5].head
    gh, sleeps = native_gh(provider)
    started = gh.start_native_merge(5, head, *first)

    with pytest.raises(github_ops.NativeMergeInProgress) as caught:
        gh.start_native_merge(5, head, *second)

    existing = caught.value.existing
    assert (existing.uuid, existing.status) == (started.uuid, "pending")
    assert existing.matches(second[1], second[0], head) is same
    assert existing.matches(first[1], first[0], head)
    assert not existing.matches(first[1], first[0], OTHER_HEAD)
    assert len(provider.operations) == 1
    assert (len(provider.puts), sleeps) == (2, [])


def test_start_native_merge_default_without_method_lets_github_choose() -> None:
    provider = NativeProvider()
    head = provider.members[5].head
    gh, _ = native_gh(provider)

    result = gh.start_native_merge(5, head, None, "default")

    assert provider.operations == [Operation(UUID, "default", "default", (4, 5))]
    assert (result.status, result.uuid, result.expected_head_sha) == (
        "pending", UUID, head,
    )  # fmt: skip


def test_start_native_merge_default_with_method_merges_with_that_method() -> None:
    provider = NativeProvider()
    head = provider.members[5].head
    gh, _ = native_gh(provider)

    result = gh.start_native_merge(5, head, "squash", "default")

    assert provider.operations == [Operation(UUID, "default", "squash", (4, 5))]
    assert (result.status, result.uuid) == ("pending", UUID)


def test_start_native_merge_default_with_a_contradicting_echo_is_uncertain() -> None:
    provider = NativeProvider()
    head = provider.members[5].head
    provider.put_replies = [Reply(202, {"status": "pending", "details": {
        "message": "m", "uuid": UUID, "merge_action": "merge_queue",
        "merge_method": "default", "expected_head_sha": head,
        "bypass_rules": False}})]  # fmt: skip

    with pytest.raises(ProviderError) as caught:
        native_gh(provider)[0].start_native_merge(5, head, None, "default")

    assert outcome(caught.value) == ("BLOCKED", "native-merge-contradiction")
    assert caught.value.uncertain is True
    assert len(provider.puts) == 1


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"status": "merged", "details": {"message": "Pull request already merged.",
                                          "sha": NATIVE_LANDED[5]}},
         ("merged", None, NATIVE_LANDED[5], None, "Pull request already merged.")),
        ({"status": "enqueued", "details": {"message": "Already in the merge queue."}},
         ("enqueued", None, None, None, "Already in the merge queue.")),
        ({"status": "failed", "details": {"message": "Merge conflict."}},
         ("failed", None, None, None, "Merge conflict.")),
    ],
)  # fmt: skip
def test_start_native_merge_immediate_reply_is_a_result_without_a_new_request(
    body: dict[str, Any], expected: tuple[str | None, ...]
) -> None:
    provider = NativeProvider()
    provider.put_replies = [Reply(200, body)]
    gh, sleeps = native_gh(provider)

    result = gh.start_native_merge(5, provider.members[5].head, None, "merge_queue")

    observed = (result.status, result.uuid, result.sha, result.expected_head_sha,
                result.message)  # fmt: skip
    assert observed == expected
    assert (provider.paths, sleeps) == ([f"PUT /repos/{REPO}/pulls/5/merge-async"], [])


@pytest.mark.parametrize(
    ("status", "message"),
    [(400, "Pull request is not ready to merge."), (404, "Not Found")],
)
def test_start_native_merge_not_ready_or_missing_pr_is_a_definite_refusal(
    status: int, message: str
) -> None:
    provider = NativeProvider()
    provider.put_replies = [refusal(status, message)]

    with pytest.raises(ProviderError) as caught:
        native_gh(provider)[0].start_native_merge(
            5, provider.members[5].head, "squash", "direct_merge"
        )

    error = caught.value
    assert (error.kind, error.uncertain, error.http_status, error.detail) == (
        "BLOCKED", False, status, "native-merge-rejected",
    )  # fmt: skip
    assert len(provider.puts) == 1


@pytest.mark.parametrize(
    ("raises", "reply"),
    [
        (subprocess.TimeoutExpired(["gh"], 1.0), None),
        (OSError("broken pipe"), None),
        (None, Reply(502, {"message": "Bad Gateway"})),
        (None, Reply(500, raw="", stderr="")),
        (None, Reply(202, raw="not json")),
        (None, Reply(202, {"status": "pending", "details": {"message": "m"}})),
        (None, Reply(202, {"status": "pending", "details": {
            "message": "m", "uuid": UUID, "merge_action": "merge_queue",
            "expected_head_sha": OTHER_HEAD, "bypass_rules": False}})),
        (None, Reply(202, {"status": "pending", "details": {
            "message": "m", "uuid": UUID, "merge_action": "merge_queue",
            "merge_method": "squash", "expected_head_sha": sha(0x105),
            "bypass_rules": False}})),
        (None, Reply(202, {"status": "pending", "details": {
            "message": "m", "uuid": UUID, "merge_action": "merge_queue",
            "expected_head_sha": sha(0x105), "bypass_rules": True}})),
        (None, Reply(202, {"status": "pending", "details": {
            "message": "m", "uuid": UUID, "merge_action": "merge_queue",
            "expected_head_sha": sha(0x105), "bypass_rules": False}})),
        (None, Reply(202, {"status": "pending", "details": {
            "message": "m", "uuid": UUID, "merge_action": "queue",
            "merge_method": "default", "expected_head_sha": sha(0x105),
            "bypass_rules": False}})),
    ],
)  # fmt: skip
def test_start_native_merge_unknown_outcome_is_uncertain_and_never_resent(
    raises: BaseException | None, reply: Reply | None
) -> None:
    provider = NativeProvider()
    provider.put_raises = raises
    provider.put_replies = [reply] if reply is not None else []
    gh, sleeps = native_gh(provider)

    with pytest.raises(ProviderError) as caught:
        gh.start_native_merge(5, provider.members[5].head, None, "merge_queue")

    assert caught.value.uncertain is True
    assert not isinstance(caught.value, github_ops.NativeMergeInProgress)
    assert (len(provider.puts), sleeps) == (1, [])


def test_start_native_merge_honours_the_absolute_monitoring_deadline() -> None:
    provider = NativeProvider()
    head = provider.members[5].head
    late, _ = native_gh(provider, deadline=5.0)

    with pytest.raises(ProviderError) as caught:
        late.start_native_merge(5, head, None, "merge_queue")

    assert (caught.value.kind, caught.value.uncertain, caught.value.detail) == (
        "WAITING", False, "native-merge-not-dispatched",
    )  # fmt: skip
    assert (provider.puts, provider.operations) == ([], [])
    in_time, _ = native_gh(provider, deadline=30.0)
    in_time.start_native_merge(5, head, None, "merge_queue")
    assert provider.timeouts == [30.0]
    assert provider.operations == [Operation(UUID, "merge_queue", "default", (4, 5))]


@pytest.mark.parametrize(
    "body",
    [
        {"status": "queued", "details": {"message": "m"}},
        {"status": "merged", "details": {"message": "m"}},
        {"status": "enqueued", "details": {"message": "m", "sha": NATIVE_LANDED[5]}},
        {"status": "enqueued", "details": {"message": "m", "uuid": OTHER_UUID}},
        {"status": "enqueued", "details": {"message": "m", "uuid": UUID.upper()}},
        {"status": "merged", "details": {"message": "m", "sha": "abc"}},
        {"status": "failed", "details": {"message": "m", "sha": NATIVE_LANDED[5]}},
        {"status": "failed"},
        {"status": "enqueued"},
        {"status": "pending", "details": {"message": "m", "merge_action": "squash"}},
        {"status": "pending", "details": {"message": "m", "merge_method": "ff"}},
        {"status": "pending", "details": {"message": "m", "bypass_rules": "no"}},
    ],
)
def test_read_native_merge_rejects_malformed_or_unknown_status(
    body: dict[str, Any],
) -> None:
    provider = NativeProvider()
    provider.status_replies = [Reply(body=body)]

    with pytest.raises(ProviderError) as caught:
        native_gh(provider)[0].read_native_merge(5, UUID)

    assert outcome(caught.value) == ("BLOCKED", "malformed")


def test_failed_native_request_is_a_result_with_the_reason_and_no_retry() -> None:
    provider = NativeProvider()
    gh, sleeps = native_gh(provider)
    head = provider.members[5].head
    started = gh.start_native_merge(5, head, "squash", "direct_merge")
    provider.request_status = "failed"
    provider.request_message = 'Required status check "ci" is failing.'

    failed = gh.read_native_merge(5, started.uuid or "")
    pr = gh.read_pr(5)

    assert (failed.status, failed.uuid, failed.sha) == ("failed", UUID, None)
    assert (pr.state, pr.head_sha) == ("OPEN", head)
    assert (len(provider.puts), sleeps) == (1, [])


def test_read_native_merge_unknown_or_expired_request_is_blocked_not_merged() -> None:
    provider = NativeProvider()
    provider.status_replies = [
        Reply(404, {"message": "Not Found"}, stderr="gh: Not Found (HTTP 404)")
    ]
    gh, sleeps = native_gh(provider)

    with pytest.raises(ProviderError) as caught:
        gh.read_native_merge(5, UUID)

    error = caught.value
    assert (error.kind, error.uncertain, error.http_status, error.detail) == (
        "BLOCKED", False, 404, "native-merge-request-unknown",
    )  # fmt: skip
    assert sleeps == []


def test_read_native_merge_rejects_a_malformed_request_id_before_reading() -> None:
    provider = NativeProvider()

    with pytest.raises(ValueError):
        native_gh(provider)[0].read_native_merge(5, "../../pulls/5")

    assert provider.paths == []


def test_read_native_merge_retries_reads_by_the_read_convention() -> None:
    provider = NativeProvider()
    provider.status_replies = [Reply(503, {"message": "unavailable"})]
    provider.request_status = "enqueued"
    gh, sleeps = native_gh(provider)

    result = gh.read_native_merge(5, UUID)

    assert (result.status, result.uuid, sleeps) == ("enqueued", UUID, [1.0])


def test_queued_native_request_stays_enqueued_while_members_land() -> None:
    provider = NativeProvider()
    gh, _ = native_gh(provider)
    head = gh.read_native_stack(STACK).members[1].head_sha
    started = gh.start_native_merge(5, head, None, "merge_queue")
    provider.request_status = "enqueued"
    queued = gh.read_native_merge(5, started.uuid or "")

    provider.land(4, 5)
    after = gh.read_native_merge(5, started.uuid or "")
    stack = gh.read_native_stack(STACK)

    statuses = (started.status, queued.status, after.status)
    assert statuses == ("pending", "enqueued", "enqueued")
    assert (queued.sha, after.sha) == (None, None)
    assert [(m.number, m.state, m.merge_commit_sha) for m in stack.members] == [
        (4, "MERGED", NATIVE_LANDED[4]), (5, "MERGED", NATIVE_LANDED[5]), (6, "OPEN", None),
    ]  # fmt: skip


def test_direct_native_request_reports_the_selected_landing_only() -> None:
    provider = NativeProvider()
    gh, _ = native_gh(provider)
    head = provider.members[5].head
    started = gh.start_native_merge(5, head, "merge", "direct_merge")

    provider.land(4, 5)
    provider.request_status, provider.request_landing = "merged", NATIVE_LANDED[5]
    result = gh.read_native_merge(5, started.uuid or "")
    lower = gh.read_pr(4)

    assert (result.status, result.sha) == ("merged", NATIVE_LANDED[5])
    assert (lower.state, lower.merge_commit_sha) == ("MERGED", NATIVE_LANDED[4])


# --------------------------------------------------------------------------
# Routine assurance: current provider evidence only


def app_check(cid: int, name: str, app_id: int, **over: Any) -> dict[str, Any]:
    row = check_run(cid, name, suite=900 + cid, app="security-bot", **over)
    row["app"]["id"] = app_id
    return row


def routine_table(
    runs: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    *,
    events: list[dict[str, Any]] | None = None,
    strict: bool = False,
    contains: bool = True,
    **extra: Route,
) -> dict[str, Route]:
    """Provider routes for a routine read: no job, log or git-commit routes exist."""
    base = f"/repos/{REPO}"
    table = routes()
    table[f"{base}/actions/runs"] = wrapped("workflow_runs", runs)
    table[f"{base}/commits/{HEAD}/check-runs"] = wrapped("check_runs", checks)
    table[f"{base}/issues/{NUMBER}/events"] = paged(events or [])
    if strict:
        table[f"{base}/rules/branches/main"] = Reply(body=[{
            "type": "required_status_checks",
            "parameters": {
                "required_status_checks": [{"context": "test"}],
                "strict_required_status_checks_policy": True,
            },
        }])  # fmt: skip
        table[f"{base}/compare/{BASE}...{HEAD}"] = (
            compare(BASE, HEAD, "ahead", 2, 0, BASE)
            if contains
            else compare(BASE, HEAD, "behind", 0, 3, HEAD)
        )
    table.update(extra)
    return table


def retarget_event(at: str) -> dict[str, Any]:
    return {"event": "base_ref_changed", "created_at": at}


def job(
    jid: int,
    name: str = "test",
    *,
    attempt: int = 1,
    status: str = "completed",
    conclusion: str | None = "success",
) -> dict[str, Any]:
    return {
        "id": jid,
        "name": name,
        "run_attempt": attempt,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/{REPO}/jobs/{jid}",
        "started_at": AFTER_MERGE,
    }


def run_jobs(run_id: int, *jobs: dict[str, Any]) -> dict[str, Route]:
    """The provider's ``filter=latest`` jobs listing of one workflow run."""
    return {f"/repos/{REPO}/actions/runs/{run_id}/jobs": wrapped("jobs", list(jobs))}


def newer(
    rid: int = 12, number: int = 2, suite: int = 102, **fields: Any
) -> dict[str, Any]:
    """A later run of the same workflow and event as ``run(10, ...)``."""
    later = run(rid, suite=suite, number=number)
    if fields.get("status", "completed") != "completed":
        later["conclusion"] = None
    later.update(fields)
    return later


def test_routine_observation_trusts_provider_checks_and_reads_no_logs() -> None:
    table = routine_table([run(10, suite=100)], [check_run(1000, "test")])
    gh, fake, _ = make(table)
    obs = gh.observe(NUMBER)
    assert obs.assurance == "routine"
    assert not [p for p in fake.paths() if "/actions/jobs" in p or "/git/commits" in p]
    assert not [i for i in obs.issues if i.startswith("checkout-")]
    check = by_name(obs)["test"]
    assert (check.base_sha, check.event, check.workflow_id, check.check_id) == (
        BASE,
        "pull_request",
        5,
        1000,
    )
    assert check.retargeted is False and check.test_sha is None
    assert obs.head_contains_base is None and obs.base_changed_at is None


def test_observe_rejects_an_unknown_assurance() -> None:
    with pytest.raises(ValueError, match="assurance"):
        make(routes())[0].observe(NUMBER, assurance="medium")


def test_high_observation_keeps_attestation_and_reads_no_routine_evidence() -> None:
    gh, fake, _ = make(with_ci([run(10, suite=100)], [check_run(1000, "test")]))
    obs = gh.observe(NUMBER, assurance="high")
    assert obs.assurance == "high" and by_name(obs)["test"].test_sha == MERGE
    assert not [p for p in fake.paths() if "/events" in p or "/compare/" in p]


def test_same_named_rows_of_different_workflows_events_and_publishers_all_survive() -> (
    None
):
    statuses = {
        "sha": HEAD, "state": "success", "total_count": 1,
        "statuses": [{"id": 1, "context": "test", "state": "success", "target_url": None, "updated_at": AFTER_MERGE}],
    }  # fmt: skip
    table = routine_table(
        [run(10, suite=100), run(11, suite=101, event="push", workflow=6, prs=[])],
        [
            check_run(1000, "test", suite=100),
            check_run(1001, "test", suite=101),
            app_check(2000, "test", 500),
        ],
        **{f"/repos/{REPO}/commits/{HEAD}/status": Reply(body=statuses)},
    )
    obs = observe(table, "routine")
    assert sorted(
        (c.name, c.event or "", c.app_slug, c.workflow_id or 0) for c in obs.checks
    ) == [
        ("test", "", "commit-status", 0),
        ("test", "", "security-bot", 0),
        ("test", "pull_request", "github-actions", 5),
        ("test", "push", "github-actions", 6),
    ]
    push = next(c for c in obs.checks if c.event == "push")
    assert push.base_sha is None and push.retargeted is False


def test_non_actions_checks_keep_the_latest_row_per_publisher_app_id() -> None:
    rows = [
        app_check(2000, "scan", 500, conclusion="failure"),
        app_check(2001, "scan", 500),  # the later re-run replaces the failure
        app_check(2002, "scan", 501, conclusion="failure"),  # another publisher
        app_check(2003, "gate", 502),
        app_check(2004, "gate", 502, status="in_progress", conclusion=None),
        app_check(2005, "audit", 503),
        app_check(2006, "audit", 503, conclusion="failure"),
    ]
    obs = observe(routine_table([], rows), "routine")
    assert sorted((c.name, c.app_id, c.status, c.conclusion) for c in obs.checks) == [
        ("audit", 503, "completed", "failure"),
        ("gate", 502, "in_progress", None),
        ("scan", 500, "completed", "success"),
        ("scan", 501, "completed", "failure"),
    ]


def test_new_run_attempt_pending_or_failed_supersedes_older_success() -> None:
    jobs = f"/repos/{REPO}/actions/runs/10/jobs"
    attempts = [
        {"id": 1001, "run_attempt": 2, "name": "test"},
    ]
    for newest, expected in (
        (
            check_run(1001, "test", status="in_progress", conclusion=None),
            ("in_progress", None),
        ),
        (check_run(1001, "test", conclusion="failure"), ("completed", "failure")),
    ):
        table = routine_table(
            [run(10, suite=100)],
            [check_run(1000, "test"), newest],
            **{jobs: wrapped("jobs", attempts)},
        )
        assert [(c.status, c.conclusion) for c in observe(table, "routine").checks] == [
            expected
        ]


def test_queued_job_without_a_check_row_is_pending_never_invented_success() -> None:
    new = newer(status="in_progress")
    jobs = [
        {
            "id": 1500,
            "name": "test",
            "run_attempt": 1,
            "status": "queued",
            "html_url": "https://github.com/j",
            "started_at": None,
        },
        {
            "id": 1501,
            "name": "lint",
            "run_attempt": 1,
            "status": "completed",
            "html_url": "",
            "started_at": None,
        },
    ]
    table = routine_table(
        [run(10, suite=100, number=1), new],
        [check_run(1000, "test", suite=100)],
        **{f"/repos/{REPO}/actions/runs/12/jobs": wrapped("jobs", jobs)},
    )
    obs = observe(table, "routine")
    assert [(c.name, c.status, c.conclusion, c.run_id) for c in obs.checks] == [
        ("lint", "queued", None, 12),
        ("test", "queued", None, 12),
    ]  # a completed job without a row is pending too
    unreadable = table | {
        f"/repos/{REPO}/actions/runs/12/jobs": Reply(
            status=403, body={"message": "Forbidden"}
        )
    }
    assert has_issue(observe(unreadable, "routine"), "run-jobs-unavailable")


@pytest.mark.parametrize("contains", [True, False])
def test_strict_policy_freshness_is_proven_by_the_head_containing_the_base(
    contains: bool,
) -> None:
    table = routine_table(
        [run(10, suite=100)], [check_run(1000, "test")], strict=True, contains=contains
    )
    obs = observe(table, "routine")
    assert obs.require_current_base and obs.head_contains_base is contains


def test_unreadable_strict_freshness_is_reported_not_assumed() -> None:
    table = routine_table(
        [run(10, suite=100)],
        [check_run(1000, "test")],
        strict=True,
        **{
            f"/repos/{REPO}/compare/{BASE}...{HEAD}": Reply(
                status=403, body={"message": "Forbidden"}
            )
        },
    )
    obs = observe(table, "routine")
    assert obs.head_contains_base is None and has_issue(obs, "strict-base-unavailable")


def test_run_started_before_a_retarget_is_stale_even_when_base_commits_coincide() -> (
    None
):
    # The run's mutable PR metadata names the very same base commit and ref.
    after = routine_table(
        [run(10, suite=100)],
        [check_run(1000, "test")],
        events=[retarget_event("2026-10-12T12:30:00Z")],
    )
    stale = by_name(observe(after, "routine"))["test"]
    assert stale.retargeted is True and stale.base_sha is None
    assert (observe(after, "routine").base_changed_at or "").startswith(
        "2026-10-12T12:30:00"
    )
    renewed = routine_table(
        [run(10, suite=100)],
        [check_run(1000, "test")],
        events=[
            retarget_event("2026-10-12T12:00:00Z"),
            {"event": "labeled", "created_at": "2026-10-12T13:00:00Z"},
        ],
    )
    fresh = by_name(observe(renewed, "routine"))["test"]
    assert fresh.retargeted is False and fresh.base_sha == BASE


def test_run_naming_another_base_ref_is_retargeted_without_any_event() -> None:
    def named(ref: str) -> dict[str, Any]:
        return run(
            10,
            suite=100,
            prs=[
                {
                    "number": NUMBER,
                    "head": {"sha": HEAD},
                    "base": {"sha": BASE, "ref": ref},
                }
            ],
        )

    old = by_name(
        observe(routine_table([named("release")], [check_run(1000, "test")]), "routine")
    )["test"]
    assert old.retargeted is True and old.base_sha is None
    current = by_name(
        observe(routine_table([named("main")], [check_run(1000, "test")]), "routine")
    )["test"]
    assert current.retargeted is False and current.base_sha == BASE


def test_head_only_push_run_is_never_marked_retargeted() -> None:
    table = routine_table(
        [run(11, suite=101, event="push", workflow=6, prs=[])],
        [check_run(1001, "test", suite=101)],
        events=[retarget_event("2026-10-12T12:30:00Z")],
    )
    push = by_name(observe(table, "routine"))["test"]
    assert push.retargeted is False and push.base_sha is None


def test_unreadable_retarget_events_are_reported_not_assumed_fresh() -> None:
    table = routine_table(
        [run(10, suite=100)],
        [check_run(1000, "test")],
        **{
            f"/repos/{REPO}/issues/{NUMBER}/events": Reply(
                status=403, body={"message": "Forbidden"}
            )
        },
    )
    assert has_issue(observe(table, "routine"), "retarget-freshness-unavailable")


def test_waiting_run_without_jobs_supersedes_an_older_success() -> None:
    table = routine_table(
        [run(10, suite=100, number=1), newer(status="queued", name="CI")],
        [check_run(1000, "test", suite=100)],
        **run_jobs(12),
    )
    obs = observe(table, "routine")
    assert [(c.name, c.status, c.conclusion, c.run_id) for c in obs.checks] == [
        ("CI", "queued", None, 12)
    ]


def test_startup_failure_run_supersedes_an_older_success() -> None:
    table = routine_table(
        [
            run(10, suite=100, number=1),
            newer(status="completed", conclusion="startup_failure", name="CI"),
        ],
        [check_run(1000, "test", suite=100)],
        **run_jobs(12),
    )
    obs = observe(table, "routine")
    assert [(c.name, c.status, c.conclusion) for c in obs.checks] == [
        ("CI", "completed", "startup_failure")
    ]


def test_job_less_successful_run_reports_nothing_and_drops_the_older_row() -> None:
    table = routine_table(
        [run(10, suite=100, number=1), newer(status="completed", conclusion="success")],
        [check_run(1000, "test", suite=100)],
        **run_jobs(12),
    )
    assert observe(table, "routine").checks == ()


def test_new_completed_run_with_a_job_but_no_check_row_is_pending() -> None:
    table = routine_table(
        [
            run(10, suite=100, number=1),
            newer(status="completed", conclusion="success"),
        ],
        [check_run(1000, "test", suite=100)],
        **run_jobs(12, job(1500, "test", conclusion="success")),
    )
    obs = observe(table, "routine")
    assert [(c.name, c.status, c.conclusion, c.run_id) for c in obs.checks] == [
        ("test", "queued", None, 12)
    ]  # the provider's job report is never promoted to success


def test_same_run_new_attempt_without_a_row_replaces_the_old_sole_row() -> None:
    rerun = run(10, suite=100)
    rerun.update(run_attempt=2, status="in_progress", conclusion=None)
    table = routine_table(
        [rerun],
        [check_run(1000, "test")],
        **run_jobs(
            10,
            job(1001, "test", attempt=2, status="in_progress", conclusion=None),
        ),
    )
    obs = observe(table, "routine")
    assert [(c.check_id, c.status, c.conclusion) for c in obs.checks] == [
        (1001, "in_progress", None)
    ]


def test_unreadable_jobs_of_a_newer_run_are_reported_and_never_leave_the_old_success() -> (
    None
):
    table = routine_table(
        [run(10, suite=100, number=1), newer(status="in_progress", name="CI")],
        [check_run(1000, "test", suite=100)],
        **{
            f"/repos/{REPO}/actions/runs/12/jobs": Reply(
                status=403, body={"message": "Forbidden"}
            )
        },
    )
    obs = observe(table, "routine")
    assert has_issue(obs, "run-jobs-unavailable")
    # The older run's success is superseded; the newer run reports itself pending.
    assert [(c.name, c.status) for c in obs.checks] == [("CI", "in_progress")]


def test_a_run_of_another_workflow_is_not_superseded() -> None:
    table = routine_table(
        [
            run(10, suite=100, number=1),
            run(11, suite=101, workflow=6),
            newer(status="queued", name="CI"),
        ],
        [check_run(1000, "test", suite=100), check_run(1001, "lint", suite=101)],
        **run_jobs(12),
    )
    assert sorted(c.name for c in observe(table, "routine").checks) == ["CI", "lint"]


def test_rerun_of_a_pre_retarget_run_started_after_the_base_change_is_stale() -> None:
    row = check_run(1000, "test")
    row["started_at"] = row["completed_at"] = "2026-10-12T13:00:00Z"
    table = routine_table(
        [run(10, suite=100, created="2026-10-12T12:05:00Z")],
        [row],
        events=[retarget_event("2026-10-12T12:30:00Z")],
    )
    stale = by_name(observe(table, "routine"))["test"]
    assert stale.retargeted is True and stale.base_sha is None


@pytest.mark.parametrize(
    "event", ["base_ref_changed", "automatic_base_change_succeeded"]
)
def test_manual_and_automatic_base_changes_renew_the_context_with_coincident_shas(
    event: str,
) -> None:
    table = routine_table(
        [run(10, suite=100)],
        [check_run(1000, "test")],
        events=[{"event": event, "created_at": "2026-10-12T12:30:00Z"}],
    )
    obs = observe(table, "routine")
    assert by_name(obs)["test"].retargeted is True
    assert (obs.base_changed_at or "").startswith("2026-10-12T12:30:00")
    mixed = routine_table(
        [run(10, suite=100)],
        [check_run(1000, "test")],
        events=[
            retarget_event("2026-10-12T12:00:00Z"),
            {
                "event": "automatic_base_change_succeeded",
                "created_at": "2026-10-12T12:30:00Z",
            },
        ],
    )
    assert by_name(observe(mixed, "routine"))["test"].retargeted is True


def test_high_assurance_also_judges_only_the_newest_run() -> None:
    for fields, expected in (
        ({"status": "queued"}, ("CI", "queued", None)),
        (
            {"status": "completed", "conclusion": "startup_failure"},
            ("CI", "completed", "startup_failure"),
        ),
    ):
        table = with_ci(
            [run(10, suite=100, number=1), newer(name="CI", **fields)],
            [check_run(1000, "test", suite=100)],
        ) | run_jobs(12)
        obs = observe(table, "high")
        assert obs.assurance == "high"
        assert [(c.name, c.status, c.conclusion) for c in obs.checks] == [expected]
        assert not has_issue(obs, "checkout-job-mismatch")


def named_run(**fields: Any) -> dict[str, Any]:
    current = run(10, suite=100)
    if fields.get("status", "completed") != "completed":
        current["conclusion"] = None
    current.update({"name": "CI", **fields})
    return current


@pytest.mark.parametrize("assurance", ["routine", "high"])
def test_running_attempt_two_is_not_covered_by_attempt_one_successes(
    assurance: str,
) -> None:
    running = [named_run(run_attempt=2, status="in_progress")]
    jobs = run_jobs(10, job(1000, "test"))  # the new attempt's jobs are not published
    if assurance == "high":
        table = with_ci(running, [check_run(1000, "test")]) | jobs
    else:
        table = routine_table(running, [check_run(1000, "test")], **jobs)
    obs = observe(table, assurance)
    assert sorted((c.name, c.status, c.conclusion) for c in obs.checks) == [
        ("CI", "in_progress", None),
        ("test", "completed", "success"),
    ]


@pytest.mark.parametrize("attempt", [1, 2])
def test_failed_run_is_not_covered_by_stale_successful_jobs(attempt: int) -> None:
    table = routine_table(
        [named_run(run_attempt=attempt, status="completed", conclusion="failure")],
        [check_run(1000, "test")],
        **run_jobs(10, job(1000, "test")),  # the job API lags the run
    )
    obs = observe(table, "routine")
    assert sorted((c.name, c.status, c.conclusion) for c in obs.checks) == [
        ("CI", "completed", "failure"),
        ("test", "completed", "success"),
    ]


def test_rerun_of_failed_jobs_only_keeps_carried_successes_without_extra_evidence() -> (
    None
):
    carried = job(1000, "build")
    pending = job(1501, "test", attempt=2, status="in_progress", conclusion=None)
    table = routine_table(
        [named_run(run_attempt=2, status="in_progress")],
        [check_run(1000, "build")],
        **run_jobs(10, carried, pending),
    )
    obs = observe(table, "routine")
    assert sorted((c.name, c.status) for c in obs.checks) == [
        ("build", "completed"),
        ("test", "in_progress"),
    ]
    finished = routine_table(
        [named_run(run_attempt=2, status="completed", conclusion="success")],
        [check_run(1000, "build"), check_run(1501, "test")],
        **run_jobs(10, carried, job(1501, "test", attempt=2)),
    )
    obs = observe(finished, "routine")
    assert sorted((c.name, c.status, c.conclusion) for c in obs.checks) == [
        ("build", "completed", "success"),
        ("test", "completed", "success"),
    ]


@pytest.mark.parametrize("assurance", ["routine", "high"])
@pytest.mark.parametrize(
    "key, value",
    [
        ("run_attempt", None),
        ("run_attempt", 0),
        ("run_attempt", -1),
        ("run_attempt", "2"),
        ("run_attempt", True),
        ("status", None),
    ],
)
def test_run_without_current_attempt_or_status_evidence_is_incomplete(
    assurance: str, key: str, value: Any
) -> None:
    broken = run(10, suite=100)
    if value is None:
        del broken[key]
    else:
        broken[key] = value
    table = with_ci([broken], [check_run(1000, "test")])
    table[f"/repos/{REPO}/issues/{NUMBER}/events"] = paged([])
    obs = observe(table, assurance)
    assert has_issue(obs, "actions-runs-unavailable")


@pytest.mark.parametrize("value", [None, 0, "1"])
def test_job_without_a_positive_run_attempt_is_unresolved_never_attempt_one(
    value: Any,
) -> None:
    broken = job(1000, "build")
    if value is None:
        del broken["run_attempt"]
    else:
        broken["run_attempt"] = value
    table = routine_table(
        [run(10, suite=100)],
        [
            check_run(1000, "build"),
            check_run(1001, "build", conclusion="failure"),
        ],
        **run_jobs(10, broken, job(1001, "build")),
    )
    obs = observe(table, "routine")
    assert has_issue(obs, "run-jobs-unavailable")
    assert has_issue(obs, "attempt-unresolved")
    assert sorted(c.conclusion or "" for c in obs.checks) == ["failure", "success"]


@pytest.mark.parametrize("assurance", ["routine", "high"])
def test_same_named_current_jobs_from_different_attempts_are_all_authoritative(
    assurance: str,
) -> None:
    from lifecycle import Policy, evaluate

    rows = [
        check_run(1000, "test", conclusion="failure"),
        check_run(1001, "test"),
    ]
    current = [named_run(run_attempt=2)]
    jobs = run_jobs(
        10,
        job(1000, "test", attempt=1, conclusion="failure"),
        job(1001, "test", attempt=2),
    )
    table = (
        with_ci(current, rows) | jobs
        if assurance == "high"
        else routine_table(current, rows, **jobs)
    )

    observed = observe(table, assurance)
    decision = Policy(
        ("repository workflows",),
        ("test",),
        "squash",
        (),
        HEAD,
        BASE,
        assurance=assurance,
    )

    assert sorted((check.check_id, check.conclusion) for check in observed.checks) == [
        (1000, "failure"),
        (1001, "success"),
    ]
    assert evaluate(observed, decision).status == "NEEDS_JUDGMENT"
