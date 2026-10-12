"""Provider-evidence tests driven by deterministic gh runner doubles.

The fixtures model documented GitHub REST shapes; they are not vendor
qualification of any live provider behaviour.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
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


Route = Reply | list[Reply] | Callable[[dict[str, str]], Reply]


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
        ok = 200 <= reply.status < 300
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
            list(argv), 0 if ok else 1, (out + body).encode(), err.encode()
        )


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
        "merge_commit_sha": MERGE,
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


def observe(table: dict[str, Route]) -> Observation:
    return make(table)[0].observe(NUMBER)


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
    assert obs.pr.merge_commit_sha == MERGE and obs.pr.mergeable is True


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
    ("stack", "native"),
    [
        (
            {
                "base": {"ref": "main", "sha": BASE},
                "size": 3,
                "position": 2,
                "id": 9,
                "number": 4,
            },
            True,
        ),
        (None, False),
    ],
)
def test_native_membership_comes_from_the_pr_stack_property(
    stack: dict[str, Any] | None, native: bool
) -> None:
    body = pull(**({"stack": stack} if stack is not None else {}))
    obs = observe(routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=body)})
    assert obs.pr.native is native


def test_malformed_stack_property_is_rejected_not_read_as_native() -> None:
    with pytest.raises(ProviderError) as err:
        observe(
            routes() | {f"/repos/{REPO}/pulls/{NUMBER}": Reply(body=pull(stack="yes"))}
        )
    assert err.value.kind == "BLOCKED" and "stack" in str(err.value)


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
    obs = gh.observe(NUMBER)
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

    obs = GitHub("github.com", REPO, runner=old_gh).observe(NUMBER)
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
    obs = gh.observe(NUMBER)
    assert by_name(obs)["test"].base_sha is None and has_issue(
        obs, "checkout-job-mismatch"
    )
    assert fake.count(f"/repos/{REPO}/actions/jobs/1000/logs") == 0


def test_job_that_has_not_completed_is_not_proven_and_logs_are_not_read() -> None:
    checks = [check_run(1000, "test", status="in_progress", conclusion=None)]
    gh, fake, _ = make(with_ci([run(10, suite=100)], checks))
    obs = gh.observe(NUMBER)
    assert by_name(obs)["test"].base_sha is None and has_issue(
        obs, "checkout-proof-pending"
    )
    assert fake.count(f"/repos/{REPO}/actions/jobs/1000") == 0


def test_checkout_commit_is_looked_up_once_for_many_jobs_and_logs_use_escape_flag() -> (
    None
):
    checks = [check_run(1000 + n, f"job-{n}") for n in range(5)]
    gh, fake, _ = make(with_ci([run(10, suite=100)], checks))
    obs = gh.observe(NUMBER)
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
    )
    checks = observe(table).checks
    assert [(c.name, c.status, c.conclusion) for c in checks] == [
        ("test", "in_progress", None)
    ]


def test_newer_failure_wins_over_older_success_and_newer_success_wins_over_failure() -> (
    None
):
    older_ok = observe(with_ci(
        [run(10, suite=100, number=1), run(12, suite=102, number=2)],
        [check_run(1000, "test", suite=100), check_run(1002, "test", suite=102, conclusion="failure")],
    ))  # fmt: skip
    assert [c.conclusion for c in older_ok.checks] == ["failure"]
    older_bad = observe(with_ci(
        [run(10, suite=100, number=1), run(12, suite=102, number=2)],
        [check_run(1000, "test", suite=100, conclusion="failure"), check_run(1002, "test", suite=102)],
    ))  # fmt: skip
    assert [c.conclusion for c in older_bad.checks] == ["success"]


def test_attempts_of_one_run_are_collapsed_only_with_authoritative_attempt_numbers() -> (
    None
):
    jobs = f"/repos/{REPO}/actions/runs/10/jobs"
    rows = [
        check_run(1000, "build", conclusion="success"),
        check_run(1001, "build", conclusion="failure"),
    ]
    attempts = {1000: 1, 1001: 2}
    table = with_ci([run(10, suite=100)], rows) | {
        jobs: wrapped(
            "jobs",
            [{"id": i, "run_attempt": a, "name": "build"} for i, a in attempts.items()],
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


def test_non_actions_checks_are_included_undeduplicated_with_base_issue() -> None:
    rows = [check_run(2000, "scan", suite=300, app="security-bot", conclusion="failure"),
            check_run(2001, "scan", suite=300, app="security-bot")]  # fmt: skip
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
    gh.observe(NUMBER)
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


def test_missing_branch_is_an_error_not_unprotected() -> None:
    table = _protection_routes(
        **{
            f"/repos/{REPO}/branches/gone": Reply(
                status=404, body={"message": "Branch not found"}
            )
        }
    )
    with pytest.raises(ProviderError):
        make(table)[0].branch_protected(REPO, "gone")


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
        ("current workflow and provider policy",), ("test",), "squash", (), HEAD, BASE
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
    decision = Policy(("current workflow",), ("test",), "squash", (), HEAD, BASE)
    assert evaluate(observe(table), decision).status == "BLOCKED"
