"""Publication and entry routing against real Git remotes and a stateful provider model.

Pushes go to real bare repositories (a base and a fork). The provider model is a
behavioural stand-in, not GitHub: it derives PR heads from those bare refs, keeps
``refs/pull/N/head`` in the base, and lands PRs with real squash commits. It makes
no claim about vendor behaviour; live qualification is a separate gate.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import lifecycle
import publish
import pytest
from changeset import (
    GatePolicy,
    compile_draft,
    parse_gates,
    parse_plan,
    take_inventory,
)
from changeset import Plan as CommitPlan
from git_ops import GitError, GitRefused, GitRepository, Snapshot
from github_ops import (
    Check,
    GitHub,
    Observation,
    ProviderError,
    PullRequest,
    QueueState,
    Repository,
)
from lifecycle import Binding, Decision, Endpoint, Policy
from publish import Request
from state_store import CreateRecord, PushRecord, Receipt, ReceiptInputError, Store

pytestmark = pytest.mark.skipif(os.name != "posix", reason="journals require POSIX")

HOST = "github.com"
BASE_REPO = "owner/repo"
FORK_REPO = "contrib/repo"
REMOTES = {BASE_REPO: "origin", FORK_REPO: "fork"}
URLS = {name: f"https://{HOST}/{repo}.git" for repo, name in REMOTES.items()}
MERGED_AT = "2026-10-12T00:00:00Z"
BRANCH = "feat/topic"
RECORDER = """\
import subprocess, sys
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                      check=True).stdout.strip()
with open(sys.argv[1], "a") as handle:
    handle.write(head + "\\n")
"""

Result = dict[str, object]
CreateMode = Literal[
    "ok", "interrupt_after", "lost", "accepted_unlisted", "refused", "forbidden"
]


@pytest.fixture(autouse=True)
def isolated_git(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    for name in list(os.environ):
        if name.startswith("GIT_") or name.lower().endswith("_proxy"):
            monkeypatch.delenv(name, raising=False)
    home = tmp_path_factory.mktemp("home")
    config = home / "gitconfig"
    config.write_text(
        "[gc]\nauto = 0\n[maintenance]\nauto = false\n[receive]\nautoGC = false\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("NO_PROXY", "*")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Ship Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "ship@example.invalid")
    monkeypatch.setattr(lifecycle, "POLL_INTERVAL", 0.0)
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def git(cwd: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {args} failed: {result.stderr.decode(errors='replace')}"
        )
    return os.fsdecode(result.stdout).rstrip("\n")


def ref(repo: Path, name: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", name],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    return result.stdout.decode().strip() if result.returncode == 0 else None


class MappedGit(GitRepository):
    """Real Git over temp paths, presented under canonical provider namespaces."""

    def remote_for(self, host: str, full_name: str) -> str | None:
        name = REMOTES.get(full_name.lower()) if host.lower() == HOST else None
        configured = self.run("remote").stdout.decode().split()
        return name if name in configured else None

    def snapshot(self) -> Snapshot:
        real = super().snapshot()
        return replace(real, remotes={name: URLS[name] for name in real.remotes})


@dataclass
class Entry:
    number: int
    head_repo: str
    head_ref: str
    base_ref: str
    merged: tuple[str, str, str] | None = None
    listed: bool = True  # False: created, but not yet returned by PR listings
    closed: bool = False


class Hub(GitHub):
    """Stateful provider model over bare repositories."""

    def __init__(self, bares: dict[str, Path]) -> None:
        super().__init__(HOST, BASE_REPO)
        self.bares = bares
        self.entries: dict[int, Entry] = {}
        self.create_calls: list[tuple[str, str, str, str, bytes]] = []
        self.merge_calls: list[tuple[int, str, str]] = []
        self.lookups: list[tuple[str, str, str | None]] = []
        self.create_mode: CreateMode = "ok"
        self.lookup_error: ProviderError | None = None

    def open_pr(self, head_repo: str, head_ref: str, base_ref: str = "main") -> int:
        number = len(self.entries) + 1
        self.entries[number] = Entry(number, head_repo, head_ref, base_ref)
        return number

    def _pr(self, number: int) -> PullRequest:
        entry = self.entries[number]
        url = f"https://{HOST}/{BASE_REPO}/pull/{number}"
        if entry.merged is not None:
            head, base, landing = entry.merged
            return PullRequest(
                number, url, "MERGED", head, entry.head_ref, entry.head_repo,
                base, entry.base_ref, BASE_REPO, landing, MERGED_AT, False, None, False,
            )  # fmt: skip
        head = ref(self.bares[entry.head_repo], f"refs/heads/{entry.head_ref}")
        base = ref(self.bares[BASE_REPO], f"refs/heads/{entry.base_ref}")
        assert head is not None and base is not None
        pull = f"refs/pull/{number}/head"
        if entry.head_repo == BASE_REPO:
            git(self.bares[BASE_REPO], "update-ref", pull, head)
        else:
            git(
                self.bares[BASE_REPO],
                "fetch",
                "-q",
                str(self.bares[entry.head_repo]),
                f"+refs/heads/{entry.head_ref}:{pull}",
            )
        return PullRequest(
            number, url, "CLOSED" if entry.closed else "OPEN", head, entry.head_ref, entry.head_repo,
            base, entry.base_ref, BASE_REPO, None, None, False, True, False,
        )  # fmt: skip

    def find_prs(
        self, head_repo: str, head_ref: str, base_ref: str | None = None
    ) -> tuple[PullRequest, ...]:
        self.lookups.append((head_repo, head_ref, base_ref))
        if self.lookup_error is not None:
            raise self.lookup_error
        return tuple(
            self._pr(entry.number)
            for entry in self.entries.values()
            if entry.listed
            and entry.head_repo.lower() == head_repo.lower()
            and entry.head_ref == head_ref
            and (base_ref is None or entry.base_ref == base_ref)
        )

    def create_pr(
        self, head_repo: str, head_ref: str, base_ref: str, title: str, body_file: Path
    ) -> PullRequest:
        self.create_calls.append(
            (head_repo, head_ref, base_ref, title, body_file.read_bytes())
        )
        assert ref(self.bares[head_repo], f"refs/heads/{head_ref}") is not None
        if self.create_mode == "lost":
            self.create_mode = "ok"
            raise ProviderError(
                "create: connection reset", kind="WAITING", operation="create",
                uncertain=True, detail="create-uncertain-transport",
            )  # fmt: skip
        if self.create_mode == "forbidden":
            raise ProviderError(
                "create: HTTP 403", kind="BLOCKED", operation="create",
                http_status=403, detail="create-rejected",
            )  # fmt: skip
        if self.create_mode == "refused":
            raise ProviderError(
                "create: HTTP 422 Validation Failed", kind="BLOCKED", operation="create",
                http_status=422, detail="create-rejected",
            )  # fmt: skip
        number = self.open_pr(head_repo, head_ref, base_ref)
        if self.create_mode == "accepted_unlisted":
            # Accepted, but the response was lost and listings lag behind.
            self.create_mode = "ok"
            self.entries[number].listed = False
            raise ProviderError(
                "create: gh timed out", kind="WAITING", operation="create",
                uncertain=True, detail="create-uncertain-timeout",
            )  # fmt: skip
        if self.create_mode == "interrupt_after":
            self.create_mode = "ok"
            raise KeyboardInterrupt
        return self._pr(number)

    def read_pr(self, number: int) -> PullRequest:
        return self._pr(number)

    def observe(self, number: int) -> Observation:
        pr = self._pr(number)
        return Observation(
            repo=Repository(BASE_REPO, HOST, "main", ("merge", "squash")),
            pr=pr,
            checks=(
                Check(
                    "tests",
                    pr.head_sha,
                    pr.base_sha,
                    "completed",
                    "success",
                    "github-actions",
                    "https://example.com/check",
                    MERGED_AT,
                ),
            ),
            required_checks=("tests",),
            required_approvals=0,
            approvals=0,
            changes_requested=False,
            policy_known=True,
            issues=(),
        )

    def queue_state(self, number: int, expected_head: str) -> QueueState:
        return "IDLE"

    def merge(self, number: int, expected_head: str, method: str) -> None:
        self.merge_calls.append((number, expected_head, method))
        pr = self._pr(number)
        assert pr.head_sha == expected_head and pr.head_repo == BASE_REPO
        bare = self.bares[BASE_REPO]
        tree = git(bare, "rev-parse", f"{pr.head_sha}^{{tree}}")
        landing = git(
            bare, "commit-tree", tree, "-p", pr.base_sha, "-m", f"Ship (#{number})"
        )
        git(bare, "update-ref", f"refs/heads/{pr.base_ref}", landing, pr.base_sha)
        self.entries[number].merged = (pr.head_sha, pr.base_sha, landing)

    def base_tip(self, base_ref: str) -> str:
        tip = ref(self.bares[BASE_REPO], f"refs/heads/{base_ref}")
        assert tip is not None
        return tip

    def landing_reachable(self, landing: str, base_tip: str) -> bool:
        return (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", landing, base_tip],
                cwd=self.bares[BASE_REPO],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )

    def list_prs(
        self, state: Literal["open", "closed"], full_name: str | None = None
    ) -> tuple[PullRequest, ...]:
        if (full_name or BASE_REPO).lower() != BASE_REPO:
            return ()
        prs = tuple(self._pr(number) for number in self.entries)
        wanted = ("OPEN",) if state == "open" else ("MERGED", "CLOSED")
        return tuple(pr for pr in prs if pr.state in wanted)

    def branch_protected(self, full_name: str, ref: str) -> bool:
        return ref == "main"


@dataclass
class Shop:
    root: Path
    work: Path
    bare: Path
    fork: Path
    hub: Hub
    base: str
    marker: Path
    gates: GatePolicy = field(init=False)

    def __post_init__(self) -> None:
        self.gates = parse_gates(
            {
                "schema_version": 1,
                "sources": ["test policy: repository gates"],
                "gates": [
                    {
                        "name": "unit",
                        "argv": [sys.executable, "-c", RECORDER, str(self.marker)],
                    }
                ],
                "secret_scan": {"argv": [sys.executable, "-c", "raise SystemExit(0)"]},
            }
        )

    def repo(self) -> MappedGit:
        return MappedGit(self.work)

    def store(self) -> Store:
        return Store(
            Path(
                git(
                    self.work, "rev-parse", "--path-format=absolute", "--git-common-dir"
                )
            )
        )

    def plan(
        self,
        branch: str = BRANCH,
        mode: str = "new",
        *,
        exclude: tuple[bytes, ...] = (),
    ) -> CommitPlan:
        inventory = take_inventory(self.repo())
        draft = {
            "schema_version": 1,
            "base": {"ref": "main", "oid": self.base},
            "placement": {"mode": mode, "branch": branch},
            "dispositions": [
                {
                    "item": item.id,
                    "disposition": "exclude" if item.path in exclude else "include",
                    "reason": "retained unrelated user work"
                    if item.path in exclude
                    else None,
                    "acknowledge": [],
                }
                for item in inventory.items
            ],
            "groups": [
                {
                    "id": "g1",
                    "message": "feat: logical change",
                    "requires": [],
                    "validation": ["unit"],
                    "changes": [
                        {"item": item.id, "content": "final"}
                        for item in inventory.items
                        if item.path not in exclude
                    ],
                }
            ],
        }
        return parse_plan(compile_draft(self.repo(), draft, self.gates))

    def request(self, **changes: object) -> Request:
        base = Request(
            host=HOST,
            base_repo=BASE_REPO,
            head_repo=None,
            number=None,
            branch=None,
            endpoint="pr",
            plan=None,
            gates=self.gates,
            decision=None,
            title="feat: logical change",
            body=b"## Changes\n- logical change\n",
            wait_timeout=30.0,
        )
        return replace(base, **changes)

    def ship(self, request: Request, run_id: str | None = None) -> tuple[Result, int]:
        """Resume through the same journal handle that loaded the receipt."""
        store = self.store()
        receipt = store.load(run_id) if run_id is not None else None
        return publish.ship(self.repo(), self.hub, store, request, receipt)

    def receipt(self, result: Result) -> Receipt:
        return self.store().load(run_of(result))

    def gate_heads(self) -> list[str]:
        return self.marker.read_text().split() if self.marker.exists() else []


@pytest.fixture
def shop(tmp_path: Path) -> Shop:
    root = tmp_path.resolve()
    bare = root / "remote.git"
    fork = root / "fork.git"
    work = root / "work"
    git(root, "init", "-q", "--bare", "-b", "main", str(bare))
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    git(work, "remote", "add", "origin", str(bare))
    (work / "README.md").write_text("base\n")
    (work / "a.txt").write_text("alpha\n")
    (work / "old.txt").write_text("old\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    git(work, "push", "-q", "-u", "origin", "main")
    git(root, "clone", "-q", "--bare", str(bare), str(fork))
    hub = Hub({BASE_REPO: bare, FORK_REPO: fork})
    return Shop(
        root, work, bare, fork, hub, git(work, "rev-parse", "HEAD"), root / "gates.log"
    )


def run_of(result: Result) -> str:
    run_id = result["run_id"]
    assert isinstance(run_id, str)
    return run_id


def dirty(shop: Shop) -> None:
    (shop.work / "a.txt").write_text("alpha\nstaged\n")
    git(shop.work, "add", "a.txt")
    (shop.work / "a.txt").write_text("alpha\nstaged\nunstaged\n")
    git(shop.work, "rm", "-q", "old.txt")
    (shop.work / "new.txt").write_text("new\n")


def lifecycle_decision(plan: CommitPlan) -> Binding:
    decision = Decision(
        ("ci workflow of the base",),
        ("tests",),
        "squash",
        ((sys.executable, "-c", "pass"),),
        (),
        (),
        (),
        False,
    )
    return Binding(decision, plan.identity, None, None, None)


def feature_pr(shop: Shop) -> tuple[int, str]:
    """A published feature branch with an open PR; the checkout stays on it."""
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\npublished\n")
    git(shop.work, "commit", "-q", "-am", "feat: published work")
    git(shop.work, "push", "-q", "-u", "origin", BRANCH)
    return shop.hub.open_pr(BASE_REPO, BRANCH), git(shop.work, "rev-parse", "HEAD")


# -- dirty entry to a published PR ---------------------------------------------------


def test_dirty_default_branch_becomes_one_published_pr_and_stops_at_pr(
    shop: Shop,
) -> None:
    dirty(shop)
    plan = shop.plan()

    result, code = shop.ship(shop.request(plan=plan))

    assert (code, result["status"]) == (0, "COMPLETE"), result
    tip = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    assert result["confirmed_commits"] == [tip]
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == tip
    assert ref(shop.bare, "refs/heads/main") == shop.base
    assert git(shop.work, "rev-parse", "refs/heads/main") == shop.base
    assert git(shop.work, "symbolic-ref", "HEAD") == f"refs/heads/{BRANCH}"
    assert git(shop.work, "status", "--porcelain", "--untracked-files=all") == ""
    [(head_repo, head_ref, base_ref, title, body)] = shop.hub.create_calls
    assert (head_repo, head_ref, base_ref) == (BASE_REPO, BRANCH, "main")
    assert (title, body) == ("feat: logical change", b"## Changes\n- logical change\n")
    assert shop.hub.merge_calls == []
    receipt = shop.receipt(result)
    assert (
        receipt.target is not None and receipt.number == 1 and receipt.head_sha == tip
    )
    assert receipt.endpoint == "pr" and receipt.status == "COMPLETE"
    publication = result["publication"]
    assert isinstance(publication, dict)
    assert publication["pushed_now"] is True and publication["created_now"] is True


def test_full_lifecycle_lands_the_logical_commits_and_cleans_up(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()

    result, code = shop.ship(
        shop.request(plan=plan, endpoint="clean", decision=lifecycle_decision(plan))
    )

    assert (code, result["status"]) == (0, "COMPLETE"), result
    [commit] = result["confirmed_commits"]  # type: ignore[misc]
    assert shop.hub.merge_calls == [(1, commit, "squash")]
    landing = ref(shop.bare, "refs/heads/main")
    assert landing is not None and landing != shop.base
    assert git(shop.bare, "rev-parse", f"{landing}^{{tree}}") == git(
        shop.work, "rev-parse", f"{commit}^{{tree}}"
    )
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert ref(shop.work, f"refs/heads/{BRANCH}") is None
    assert git(shop.work, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert git(shop.work, "rev-parse", "HEAD") == landing
    assert (shop.work / "new.txt").read_text() == "new\n"
    assert not (shop.work / "old.txt").exists()


def test_crash_after_pr_creation_resumes_to_the_same_pr(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.create_mode = "interrupt_after"

    first, code = shop.ship(shop.request(plan=plan))

    assert (code, first["status"], first["cancelled"]) == (130, "WAITING", True)
    pending = shop.receipt(first)
    assert pending.publication is not None and pending.publication.create is not None
    assert pending.publication.create.outcome == "PENDING"
    assert pending.target is None
    resumed, code = shop.ship(shop.request(plan=plan), run_of(first))

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert shop.receipt(resumed).number == 1


def pending_creation(shop: Shop, result: Result) -> tuple[str, int | None]:
    publication = shop.receipt(result).publication
    assert publication is not None and publication.create is not None
    return publication.create.outcome, publication.create.number


def test_aged_unknown_creation_without_a_listed_match_is_never_resent(
    shop: Shop,
) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.create_mode = "lost"
    first, code = shop.ship(shop.request(plan=plan, wait_timeout=0.2))
    assert (code, first["status"]) == (3, "WAITING"), first
    assert pending_creation(shop, first) == ("PENDING", None)
    store = shop.store()
    aged = store.load(run_of(first))
    assert aged.publication is not None and aged.publication.create is not None
    aged.publication.create.created_at = "2026-10-01T00:00:00+00:00"
    with store.mutation_lock():
        store.save(aged)
    lookups = len(shop.hub.lookups)

    resumed, code = shop.ship(shop.request(wait_timeout=0.2), run_of(first))

    assert (code, resumed["status"]) == (3, "WAITING"), resumed
    assert len(shop.hub.create_calls) == 1 and shop.hub.entries == {}
    assert len(shop.hub.lookups) > lookups  # it looked, found nothing, and waited
    assert pending_creation(shop, resumed) == ("PENDING", None)
    publication = resumed["publication"]
    assert isinstance(publication, dict)
    assert publication["pr"] == {"outcome": "PENDING", "number": None}
    tip = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    fresh = Binding(
        Decision(("ci",), ("tests",), "squash", (), (), (), (), False),
        None,
        tip,
        "main",
        shop.base,
    )

    other, code = shop.ship(shop.request(branch=BRANCH, decision=fresh))

    assert (code, other["status"]) == (4, "NEEDS_JUDGMENT"), other
    assert run_of(first) in str(other["blocker"])
    assert len(shop.hub.create_calls) == 1 and shop.hub.entries == {}


def test_unknown_creation_resumes_to_the_same_pr_once_it_is_listed(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.create_mode = "accepted_unlisted"
    first, code = shop.ship(shop.request(plan=plan, wait_timeout=0.2))
    assert (code, first["status"]) == (3, "WAITING"), first
    unlisted, code = shop.ship(shop.request(wait_timeout=0.2), run_of(first))
    assert (code, unlisted["status"]) == (3, "WAITING"), unlisted
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert pending_creation(shop, unlisted) == ("PENDING", None)
    shop.hub.entries[1].listed = True

    resumed, code = shop.ship(shop.request(), run_of(first))

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert pending_creation(shop, resumed) == ("CONFIRMED", 1)
    receipt = shop.receipt(resumed)
    assert receipt.number == 1
    assert receipt.head_sha == git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")


def test_refused_creation_is_final_and_a_later_resume_creates_exactly_once(
    shop: Shop,
) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.create_mode = "refused"
    first, code = shop.ship(shop.request(plan=plan))
    assert (code, first["status"]) == (5, "BLOCKED"), first
    assert pending_creation(shop, first) == ("REJECTED", None)
    assert shop.hub.entries == {}
    shop.hub.create_mode = "ok"  # the refusal's cause was resolved

    resumed, code = shop.ship(shop.request(), run_of(first))

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert len(shop.hub.create_calls) == 2 and list(shop.hub.entries) == [1]
    assert pending_creation(shop, resumed) == ("CONFIRMED", 1)


def test_unknown_push_outcome_is_reconciled_from_the_remote_not_resent(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirty(shop)
    plan = shop.plan()
    pushed: list[str] = []
    real_push = GitRepository.push_head

    def response_lost(
        self: GitRepository,
        remote: str,
        branch: str,
        new_oid: str,
        expected_old: str | None,
    ) -> None:
        pushed.append(new_oid)
        real_push(self, remote, branch, new_oid, expected_old)
        if len(pushed) == 1:
            raise GitError("the push response was lost", uncertain=True)

    monkeypatch.setattr(GitRepository, "push_head", response_lost)
    first, code = shop.ship(shop.request(plan=plan))
    assert (code, first["status"]) == (3, "WAITING"), first
    tip = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == tip
    pending = shop.receipt(first).publication
    assert pending is not None and pending.push is not None
    assert pending.push.outcome == "PENDING" and shop.hub.create_calls == []

    resumed, code = shop.ship(shop.request(), run_of(first))

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert pushed == [tip]
    confirmed = shop.receipt(resumed).publication
    assert confirmed is not None and confirmed.push is not None
    assert (confirmed.push.old, confirmed.push.new, confirmed.push.outcome) == (
        None,
        tip,
        "CONFIRMED",
    )
    assert len(shop.hub.create_calls) == 1


def test_flagged_outgoing_secret_scan_blocks_before_any_push(shop: Shop) -> None:
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\nhand-made\n")
    git(shop.work, "commit", "-q", "-am", "feat: hand-made commit")
    tip = git(shop.work, "rev-parse", "HEAD")
    flagged = parse_gates(
        {
            "schema_version": 1,
            "sources": ["test policy: repository gates"],
            "gates": [
                {
                    "name": "unit",
                    "argv": [sys.executable, "-c", RECORDER, str(shop.marker)],
                }
            ],
            "secret_scan": {"argv": [sys.executable, "-c", "raise SystemExit(1)"]},
        }
    )
    decision = Binding(
        Decision(("ci",), ("tests",), "squash", (), (), (), (), False),
        None,
        tip,
        "main",
        shop.base,
    )

    result, code = shop.ship(
        shop.request(branch=BRANCH, gates=flagged, decision=decision)
    )

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert shop.gate_heads() == [tip]  # commits it did not create are gated too
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.create_calls == []
    publication = result["publication"]
    assert isinstance(publication, dict) and publication["push"] is None


def test_permission_denied_creation_is_an_honest_blocker(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.create_mode = "forbidden"

    result, code = shop.ship(shop.request(plan=plan))

    assert (code, result["status"]) == (5, "BLOCKED")
    publication = result["publication"]
    assert isinstance(publication, dict)
    assert publication["push"] == {
        "old": None,
        "new": git(shop.work, "rev-parse", f"refs/heads/{BRANCH}"),
        "outcome": "CONFIRMED",
    }
    assert publication["pr"] == {"outcome": "REJECTED", "number": None}
    assert shop.hub.entries == {}


def test_decision_bound_to_another_plan_cannot_authorize_the_published_head(
    shop: Shop,
) -> None:
    dirty(shop)
    plan = shop.plan()
    foreign = replace(lifecycle_decision(plan), plan="f" * 64)

    result, code = shop.ship(
        shop.request(plan=plan, endpoint="clean", decision=foreign)
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert shop.hub.merge_calls == []
    assert shop.hub.create_calls == []
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None


def test_fork_head_and_base_namespaces_stay_distinct(shop: Shop) -> None:
    git(shop.work, "remote", "add", "fork", str(shop.fork))
    dirty(shop)
    plan = shop.plan()

    result, code = shop.ship(shop.request(plan=plan, head_repo=FORK_REPO))

    assert (code, result["status"]) == (0, "COMPLETE"), result
    tip = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    assert ref(shop.fork, f"refs/heads/{BRANCH}") == tip
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.create_calls[0][:3] == (FORK_REPO, BRANCH, "main")
    assert all(lookup[0] == FORK_REPO for lookup in shop.hub.lookups)
    receipt = shop.receipt(result)
    assert (receipt.repo, receipt.head_repo) == (BASE_REPO, FORK_REPO)
    assert ref(shop.bare, "refs/pull/1/head") == tip


def test_dry_run_preview_plans_publication_without_writes(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    refs_before = git(shop.work, "for-each-ref")

    preview = publish.preview(shop.repo(), shop.hub, shop.request(plan=plan))

    assert preview["status"] == "PLANNED"
    actions = preview["actions"]
    assert isinstance(actions, list)
    assert [action["action"] for action in actions] == [
        "commit",
        "push",
        "create-pr",
        "lifecycle",
    ]
    assert git(shop.work, "for-each-ref") == refs_before
    assert not (shop.work / ".git" / "armory").exists()
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.create_calls == []


# -- existing local history and published branches -----------------------------------


def test_published_branch_with_new_local_commits_reuses_its_open_pr(shop: Shop) -> None:
    number, published = feature_pr(shop)
    (shop.work / "a.txt").write_text("alpha\npublished\nfollow-up\n")
    git(shop.work, "commit", "-q", "-am", "fix: follow-up")
    local = git(shop.work, "rev-parse", "HEAD")

    result, code = shop.ship(shop.request(number=number, title=None, body=None))

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == local
    assert git(shop.work, "rev-parse", f"{local}^") == published
    assert shop.hub.create_calls == [] and list(shop.hub.entries) == [number]
    assert shop.gate_heads() == [local]
    assert shop.receipt(result).head_sha == local


def test_open_pr_with_uncommitted_work_is_not_a_completed_no_op(shop: Shop) -> None:
    number, published = feature_pr(shop)
    (shop.work / "a.txt").write_text("alpha\npublished\nunsaved\n")

    result, code = shop.ship(shop.request(number=number))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert shop.hub.merge_calls == [] and shop.hub.create_calls == []


def test_open_pr_without_local_work_continues_exactly_through_the_lifecycle(
    shop: Shop,
) -> None:
    number, published = feature_pr(shop)

    result, code = shop.ship(shop.request(number=number))

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert result["confirmed_prs"] == [f"https://{HOST}/{BASE_REPO}/pull/{number}"]
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert shop.hub.create_calls == [] and shop.hub.merge_calls == []


def test_diverged_published_history_is_never_rewritten(shop: Shop) -> None:
    other = shop.root / "other"
    git(shop.root, "clone", "-q", str(shop.bare), str(other))
    git(other, "switch", "-q", "-c", BRANCH)
    (other / "a.txt").write_text("alpha\nsomeone else\n")
    git(other, "commit", "-q", "-am", "remote work")
    git(other, "push", "-q", "origin", BRANCH)
    remote = git(other, "rev-parse", "HEAD")
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\nmine\n")
    git(shop.work, "commit", "-q", "-am", "local work")
    local = git(shop.work, "rev-parse", "HEAD")
    git(shop.work, "fetch", "-q", "origin")
    decision = Binding(
        Decision(("ci",), ("tests",), "squash", (), (), (), (), False),
        None,
        local,
        "main",
        shop.base,
    )

    result, code = shop.ship(shop.request(branch=BRANCH, decision=decision))

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert "diverged" in str(result["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == remote
    assert shop.hub.create_calls == []


def test_ambiguous_open_prs_block_before_any_push_or_create(shop: Shop) -> None:
    number, published = feature_pr(shop)
    shop.hub.open_pr(BASE_REPO, BRANCH)
    (shop.work / "a.txt").write_text("alpha\npublished\nmore\n")
    git(shop.work, "commit", "-q", "-am", "more")

    result, code = shop.ship(shop.request(branch=BRANCH))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert "several open PRs" in str(result["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert shop.hub.create_calls == [] and number == 1


def test_inaccessible_pr_evidence_is_not_treated_as_absence(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.lookup_error = ProviderError(
        "find-prs: HTTP 403", kind="BLOCKED", operation="find-prs", http_status=403
    )

    result, code = shop.ship(shop.request(plan=plan))

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.create_calls == []


def test_resumed_narrow_publication_never_widens_to_merge(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    result, code = shop.ship(shop.request(plan=plan))
    assert code == 0
    endpoint: Endpoint = "clean"

    widened, code = shop.ship(
        shop.request(endpoint=endpoint, decision=lifecycle_decision(plan)),
        run_of(result),
    )

    assert (code, widened["status"]) == (4, "NEEDS_JUDGMENT"), widened
    assert shop.hub.merge_calls == []
    assert shop.receipt(result).endpoint == "pr"


# -- guarded push primitive -----------------------------------------------------------


def test_push_lease_and_forward_history_guard_the_published_ref(shop: Shop) -> None:
    repo = GitRepository(shop.work)
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\none\n")
    git(shop.work, "commit", "-q", "-am", "one")
    first = git(shop.work, "rev-parse", "HEAD")
    repo.push_head("origin", BRANCH, first, None)
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == first

    with pytest.raises(GitRefused):
        repo.push_head("origin", BRANCH, first, None)  # expected absent, but present
    (shop.work / "a.txt").write_text("alpha\none\ntwo\n")
    git(shop.work, "commit", "-q", "-am", "two")
    second = git(shop.work, "rev-parse", "HEAD")
    with pytest.raises(GitRefused):
        repo.push_head("origin", BRANCH, second, shop.base)  # stale expected old
    sibling = git(
        shop.work, "commit-tree", f"{shop.base}^{{tree}}", "-p", shop.base, "-m", "x"
    )
    with pytest.raises(GitRefused, match="rewriting"):
        repo.push_head("origin", BRANCH, sibling, first)  # not a fast-forward
    with pytest.raises(GitRefused, match="default branch"):
        repo.push_head("origin", "main", second, shop.base)
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == first
    assert ref(shop.bare, "refs/heads/main") == shop.base

    repo.push_head("origin", BRANCH, second, first)

    assert ref(shop.bare, f"refs/heads/{BRANCH}") == second


def existing_decision(shop: Shop, head: str) -> Binding:
    return Binding(
        Decision(("fixture CI",), ("tests",), "squash", (), (), (), (), False),
        None,
        head,
        "main",
        shop.base,
    )


def test_pending_creation_prevents_publishing_later_local_commits(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.create_mode = "lost"
    first, code = shop.ship(shop.request(plan=plan, wait_timeout=0.2))
    assert (code, first["status"]) == (3, "WAITING"), first
    published = ref(shop.bare, f"refs/heads/{BRANCH}")
    assert published is not None
    (shop.work / "a.txt").write_text("alpha\nstaged\nunstaged\nnew local work\n")
    git(shop.work, "commit", "-q", "-am", "feat: retain later local work")
    local = git(shop.work, "rev-parse", "HEAD")

    resumed, code = shop.ship(shop.request(wait_timeout=0.2), run_of(first))

    assert (code, resumed["status"]) == (3, "WAITING"), resumed
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert git(shop.work, "rev-parse", "HEAD") == local
    assert pending_creation(shop, resumed) == ("PENDING", None)
    assert len(shop.hub.create_calls) == 1


def test_saved_publication_obeys_a_later_other_run_pending_creation(shop: Shop) -> None:
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\nexisting local work\n")
    git(shop.work, "commit", "-q", "-am", "feat: preserve reasonable local commit")
    local = git(shop.work, "rev-parse", "HEAD")
    decision = existing_decision(shop, local)
    failing = replace(
        shop.gates,
        gates=(
            replace(
                shop.gates.gates[0], argv=(sys.executable, "-c", "raise SystemExit(1)")
            ),
        ),
    )
    saved, code = shop.ship(
        shop.request(branch=BRANCH, decision=decision, gates=failing)
    )
    assert (code, saved["status"]) == (4, "NEEDS_JUDGMENT"), saved
    assert shop.receipt(saved).publication is not None
    shop.hub.create_mode = "lost"
    other, code = shop.ship(
        shop.request(branch=BRANCH, decision=decision, wait_timeout=0.2)
    )
    assert (code, other["status"]) == (3, "WAITING"), other
    assert pending_creation(shop, other) == ("PENDING", None)

    resumed, code = shop.ship(
        shop.request(branch=BRANCH, decision=decision, wait_timeout=0.2), run_of(saved)
    )

    assert (code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed
    assert run_of(other) in str(resumed["blocker"])
    assert len(shop.hub.create_calls) == 1
    assert pending_creation(shop, other) == ("PENDING", None)


def test_peer_intent_appearing_during_outgoing_gates_blocks_push(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\nexisting local work\n")
    git(shop.work, "commit", "-q", "-am", "feat: preserve reasonable local commit")
    local = git(shop.work, "rev-parse", "HEAD")
    original = publish._Publish._validate_outgoing
    peer_id = uuid.uuid4().hex

    def concurrent(
        controller: publish._Publish,
        publication: publish.PublicationRecord,
        located: publish._Located,
        start: str,
    ) -> None:
        original(controller, publication, located, start)
        peer = copy.deepcopy(controller.record)
        peer.run_id = peer_id
        assert peer.publication is not None
        peer.publication.push = PushRecord(None, local)
        store = shop.store()
        with store.mutation_lock():
            store.save(peer)

    monkeypatch.setattr(publish._Publish, "_validate_outgoing", concurrent)
    result, code = shop.ship(
        shop.request(branch=BRANCH, decision=existing_decision(shop, local))
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert peer_id in str(result["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.create_calls == []
    assert shop.store().load(peer_id).publication is not None


def test_peer_creation_intent_after_discovery_blocks_creation(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\nalready published local work\n")
    git(shop.work, "commit", "-q", "-am", "feat: preserve published local commit")
    local = git(shop.work, "rev-parse", "HEAD")
    git(shop.work, "push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}")
    original = publish._Publish._match
    peer_id = uuid.uuid4().hex

    def concurrent(
        controller: publish._Publish,
        located: publish._Located,
        *,
        creation: bool = False,
    ) -> PullRequest | None:
        found = original(controller, located, creation=creation)
        peer = copy.deepcopy(controller.record)
        peer.run_id = peer_id
        assert peer.publication is not None
        peer.publication.create = CreateRecord(
            publish._identity(b"feat: peer"),
            publish._identity(b"peer body"),
            "2026-10-12T00:00:00+00:00",
        )
        store = shop.store()
        with store.mutation_lock():
            store.save(peer)
        return found

    monkeypatch.setattr(publish._Publish, "_match", concurrent)
    result, code = shop.ship(
        shop.request(branch=BRANCH, decision=existing_decision(shop, local))
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert peer_id in str(result["blocker"])
    assert shop.hub.create_calls == [] and shop.hub.merge_calls == []
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == local
    pending = shop.store().load(peer_id).publication
    assert pending is not None and pending.create is not None
    assert pending.create.outcome == "PENDING"


@pytest.mark.parametrize("selected", [False, True])
def test_closed_unmerged_pr_is_not_successful_publication(
    shop: Shop, selected: bool
) -> None:
    number, published = feature_pr(shop)
    shop.hub.entries[number].closed = True
    result, code = shop.ship(
        shop.request(
            branch=None if selected else BRANCH,
            number=number if selected else None,
            decision=existing_decision(shop, published),
        )
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert str(number) in str(result["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert shop.hub.create_calls == [] and shop.hub.merge_calls == []
    if not selected:
        assert shop.receipt(result).target is None


def test_wrong_head_binding_cannot_authorize_a_push(shop: Shop) -> None:
    _, published = feature_pr(shop)
    (shop.work / "a.txt").write_text("alpha\npublished\nnew local work\n")
    git(shop.work, "commit", "-q", "-am", "feat: retain later local work")
    local = git(shop.work, "rev-parse", "HEAD")
    result, code = shop.ship(
        shop.request(branch=BRANCH, decision=existing_decision(shop, published))
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert git(shop.work, "rev-parse", "HEAD") == local
    assert shop.hub.create_calls == [] and shop.hub.merge_calls == []


@pytest.mark.parametrize(
    "title", ["", " ", "x" * 257, "feat: one\nsecond", "feat:\tchange"]
)
def test_invalid_creation_title_stops_before_commits_refs_or_journals(
    shop: Shop, title: str
) -> None:
    dirty(shop)
    plan = shop.plan()
    snapshot = shop.repo().snapshot().fingerprint
    with pytest.raises(ValueError):
        shop.ship(shop.request(plan=plan, title=title))
    assert shop.repo().snapshot().fingerprint == snapshot
    assert ref(shop.work, f"refs/heads/{BRANCH}") is None
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert not shop.store().list_runs()
    assert shop.hub.create_calls == []


@pytest.mark.parametrize("transplant", [False, True])
def test_wide_endpoint_requires_residual_checkout_disposition_before_publication(
    shop: Shop, transplant: bool
) -> None:
    if transplant:
        git(shop.work, "switch", "-q", "-c", "feat/unrelated")
        (shop.work / "README.md").write_text("unrelated committed feature\n")
        git(shop.work, "commit", "-q", "-am", "feat: retain unrelated history")
        exclude: tuple[bytes, ...] = ()
    else:
        (shop.work / "README.md").write_text("excluded staged user work\n")
        git(shop.work, "add", "README.md")
        exclude = (b"README.md",)
    dirty(shop)
    readme_index = git(shop.work, "ls-files", "--stage", "--", "README.md")
    readme_bytes = (shop.work / "README.md").read_bytes()
    plan = shop.plan(exclude=exclude)

    result, code = shop.ship(
        shop.request(plan=plan, endpoint="clean", decision=lifecycle_decision(plan))
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.create_calls == [] and shop.hub.merge_calls == []
    assert git(shop.work, "ls-files", "--stage", "--", "README.md") == readme_index
    assert (shop.work / "README.md").read_bytes() == readme_bytes


# -- journals, the run's own PR, merged reuse, applicability, creation inputs ----------


def advance_base(shop: Shop) -> str:
    """Another contributor lands on the provider's base; the local base stays behind."""
    other = shop.root / "upstream"
    git(shop.root, "clone", "-q", str(shop.bare), str(other))
    (other / "upstream.txt").write_text("upstream\n")
    git(other, "add", "upstream.txt")
    git(other, "commit", "-q", "-m", "upstream change")
    git(other, "push", "-q", "origin", "main")
    return git(other, "rev-parse", "HEAD")


def divergent_feature(shop: Shop) -> tuple[str, str]:
    """A hand-made feature commit on the old base, and the provider's newer base tip."""
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\nhand-made\n")
    git(shop.work, "commit", "-q", "-am", "feat: hand-made commit")
    feature = git(shop.work, "rev-parse", "HEAD")
    upstream = advance_base(shop)
    git(shop.work, "fetch", "-q", "origin")
    assert not shop.repo().is_ancestor(upstream, feature)
    return feature, upstream


def interrupt_binding_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interrupt once after a creation is confirmed and before the PR is bound."""
    real = publish._Publish._bind
    interrupted: list[int] = []

    def interrupt(
        controller: publish._Publish, located: publish._Located, pr: PullRequest
    ) -> Policy | None:
        if not interrupted:
            interrupted.append(pr.number)
            raise KeyboardInterrupt
        return real(controller, located, pr)

    monkeypatch.setattr(publish._Publish, "_bind", interrupt)


@pytest.mark.parametrize("intent", ["create", "push"])
def test_another_controllers_intent_on_the_same_run_survives_own_enumeration(
    shop: Shop, monkeypatch: pytest.MonkeyPatch, intent: str
) -> None:
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\nexisting local work\n")
    git(shop.work, "commit", "-q", "-am", "feat: preserve reasonable local commit")
    local = git(shop.work, "rev-parse", "HEAD")
    decision = existing_decision(shop, local)
    failing = replace(
        shop.gates,
        gates=(
            replace(
                shop.gates.gates[0], argv=(sys.executable, "-c", "raise SystemExit(1)")
            ),
        ),
    )
    saved, code = shop.ship(
        shop.request(branch=BRANCH, decision=decision, gates=failing)
    )
    assert (code, saved["status"]) == (4, "NEEDS_JUDGMENT"), saved
    run_id = run_of(saved)
    original = publish._Publish._validate_outgoing

    def concurrent(
        controller: publish._Publish,
        publication: publish.PublicationRecord,
        located: publish._Located,
        start: str,
    ) -> None:
        original(controller, publication, located, start)
        other = shop.store()  # a second controller on the same run's journal
        peer = other.load(run_id)
        assert peer.publication is not None
        if intent == "create":
            peer.publication.create = CreateRecord(
                publish._identity(b"feat: other"),
                publish._identity(b"other body"),
                "2026-10-12T00:00:00+00:00",
            )
        else:
            peer.publication.push = PushRecord(None, located.head)
        with other.mutation_lock():
            other.save(peer)

    monkeypatch.setattr(publish._Publish, "_validate_outgoing", concurrent)
    resumed, code = shop.ship(shop.request(branch=BRANCH, decision=decision), run_id)

    assert (code, resumed["status"]) == (5, "BLOCKED"), resumed
    assert "outside this controller" in str(resumed["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.create_calls == []
    journaled = shop.store().load(run_id).publication
    assert journaled is not None
    if intent == "create":
        assert journaled.create is not None and journaled.create.outcome == "PENDING"
        assert journaled.create.title_identity == publish._identity(b"feat: other")
    else:
        assert journaled.push == PushRecord(None, local)


@pytest.mark.parametrize("state", ["closed", "merged"])
def test_closed_or_merged_saved_pr_blocks_replacement_before_any_new_work(
    shop: Shop, state: str
) -> None:
    dirty(shop)
    first, code = shop.ship(shop.request(plan=shop.plan()))
    assert (code, first["status"]) == (0, "COMPLETE"), first
    published = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    if state == "closed":
        shop.hub.entries[1].closed = True
    else:
        shop.hub.merge(1, published, "squash")
    merges = list(shop.hub.merge_calls)
    (shop.work / "extra.txt").write_text("extra\n")
    follow_up = shop.plan(mode="current")

    result, code = shop.ship(shop.request(plan=follow_up), run_of(first))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert "PR 1" in str(result["blocker"])
    assert git(shop.work, "rev-parse", f"refs/heads/{BRANCH}") == published
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    status = git(shop.work, "status", "--porcelain", "--untracked-files=all")
    assert status == "?? extra.txt"
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert shop.hub.merge_calls == merges
    assert pending_creation(shop, result) == ("CONFIRMED", 1)
    assert shop.receipt(first).number == 1


@pytest.mark.parametrize("state", ["closed", "merged"])
def test_confirmed_but_unbound_creation_is_never_replaced_either(
    shop: Shop, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    dirty(shop)
    interrupt_binding_once(monkeypatch)
    first, code = shop.ship(shop.request(plan=shop.plan()))
    assert (code, first["status"], first["cancelled"]) == (130, "WAITING", True)
    assert pending_creation(shop, first) == ("CONFIRMED", 1)
    assert shop.receipt(first).target is None
    published = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    if state == "closed":
        shop.hub.entries[1].closed = True
    else:
        shop.hub.merge(1, published, "squash")
    (shop.work / "later.txt").write_text("later local work\n")
    git(shop.work, "add", "later.txt")
    git(shop.work, "commit", "-q", "-m", "feat: later local work")
    later = git(shop.work, "rev-parse", "HEAD")

    result, code = shop.ship(shop.request(), run_of(first))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert "PR 1" in str(result["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert git(shop.work, "rev-parse", "HEAD") == later
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert pending_creation(shop, result) == ("CONFIRMED", 1)
    assert shop.receipt(result).target is None


def test_saved_pr_missing_from_exact_discovery_is_never_replaced(shop: Shop) -> None:
    dirty(shop)
    first, code = shop.ship(shop.request(plan=shop.plan()))
    assert (code, first["status"]) == (0, "COMPLETE"), first
    published = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    shop.hub.entries[1].listed = False  # still open, but listings lag behind
    (shop.work / "later.txt").write_text("later local work\n")
    git(shop.work, "add", "later.txt")
    git(shop.work, "commit", "-q", "-m", "feat: later local work")

    result, code = shop.ship(shop.request(), run_of(first))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert "PR 1" in str(result["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert pending_creation(shop, result) == ("CONFIRMED", 1)
    assert shop.receipt(first).number == 1


def test_exact_merged_pr_is_reused_without_republishing_its_deleted_branch(
    shop: Shop,
) -> None:
    number, published = feature_pr(shop)
    shop.hub.merge(number, published, "squash")
    git(shop.bare, "update-ref", "-d", f"refs/heads/{BRANCH}")  # auto-deleted head
    merges = list(shop.hub.merge_calls)

    result, code = shop.ship(
        shop.request(
            branch=BRANCH,
            endpoint="merged",
            decision=existing_decision(shop, published),
            title=None,
            body=None,
        )
    )

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.gate_heads() == [] and shop.hub.create_calls == []
    assert shop.hub.merge_calls == merges
    assert result["confirmed_prs"] == [f"https://{HOST}/{BASE_REPO}/pull/{number}"]
    publication = result["publication"]
    assert isinstance(publication, dict)
    assert publication["push"] is None and publication["pushed_now"] is False
    receipt = shop.receipt(result)
    assert receipt.number == number and receipt.merge_verified


def test_merged_pr_of_an_unbound_creation_continues_without_republishing(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirty(shop)
    interrupt_binding_once(monkeypatch)
    first, code = shop.ship(shop.request(plan=shop.plan()))
    assert (code, first["status"]) == (130, "WAITING"), first
    published = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    shop.hub.merge(1, published, "squash")
    git(shop.bare, "update-ref", "-d", f"refs/heads/{BRANCH}")  # auto-deleted head
    gated = shop.gate_heads()

    result, code = shop.ship(shop.request(), run_of(first))

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.gate_heads() == gated
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    publication = result["publication"]
    assert isinstance(publication, dict) and publication["pushed_now"] is False
    assert shop.receipt(result).number == 1


def test_preview_plans_no_push_for_an_exact_merged_pr(shop: Shop) -> None:
    number, published = feature_pr(shop)
    shop.hub.merge(number, published, "squash")
    git(shop.bare, "update-ref", "-d", f"refs/heads/{BRANCH}")

    preview = publish.preview(
        shop.repo(), shop.hub, shop.request(branch=BRANCH, title=None, body=None)
    )

    actions = preview["actions"]
    assert isinstance(actions, list)
    assert [action["action"] for action in actions] == ["reuse-pr", "lifecycle"]
    assert actions[0]["number"] == number


def test_plan_decision_binds_the_confirmed_prs_current_base(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    upstream = advance_base(shop)  # the provider base is ahead of the plan's base
    assert plan.base_oid == shop.base != upstream

    result, code = shop.ship(
        shop.request(plan=plan, endpoint="merged", decision=lifecycle_decision(plan))
    )

    assert (code, result["status"]) == (0, "COMPLETE"), result
    [commit] = result["confirmed_commits"]  # type: ignore[misc]
    assert shop.hub.merge_calls == [(1, commit, "squash")]
    assert shop.receipt(result).base_sha == upstream
    assert git(shop.work, "rev-parse", f"refs/heads/{BRANCH}") == commit


def test_current_explicit_packet_lands_a_feature_without_the_base_tip(
    shop: Shop,
) -> None:
    feature, upstream = divergent_feature(shop)
    current = replace(existing_decision(shop, feature), base_oid=upstream)

    result, code = shop.ship(
        shop.request(branch=BRANCH, endpoint="merged", decision=current)
    )

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert shop.hub.merge_calls == [(1, feature, "squash")]
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == feature
    assert git(shop.work, "rev-parse", f"refs/heads/{BRANCH}") == feature
    assert shop.receipt(result).base_sha == upstream


def test_stale_explicit_packet_is_refused_before_publication_until_refreshed(
    shop: Shop,
) -> None:
    feature, upstream = divergent_feature(shop)
    stale = existing_decision(shop, feature)  # names the base the feature began from

    bounded, code = shop.ship(
        shop.request(branch=BRANCH, endpoint="merged", decision=stale)
    )

    assert (code, bounded["status"]) == (4, "NEEDS_JUDGMENT"), bounded
    assert "stale" in str(bounded["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None  # nothing was pushed
    assert shop.hub.create_calls == [] and shop.hub.merge_calls == []
    assert shop.gate_heads() == []
    refreshed = replace(stale, base_oid=upstream)

    resumed, code = shop.ship(
        shop.request(branch=BRANCH, endpoint="merged", decision=refreshed),
        run_of(bounded),
    )

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == feature
    assert shop.hub.merge_calls == [(1, feature, "squash")]
    assert git(shop.work, "rev-parse", f"refs/heads/{BRANCH}") == feature
    journal = shop.receipt(resumed).publication
    assert journal is not None and journal.base_oid == upstream


@pytest.mark.parametrize("kind", ["binding", "policy"])
def test_stale_explicit_decision_is_refused_before_publishing_into_an_open_pr(
    shop: Shop, kind: str
) -> None:
    number, published = feature_pr(shop)
    (shop.work / "a.txt").write_text("alpha\npublished\nfollow-up\n")
    git(shop.work, "commit", "-q", "-am", "fix: follow-up")
    local = git(shop.work, "rev-parse", "HEAD")
    upstream = advance_base(shop)  # the open PR's base moved on after it was opened
    decision = Decision(("fixture CI",), ("tests",), "squash", (), (), (), (), False)

    def packet(base: str) -> Binding | Policy:
        if kind == "binding":
            return Binding(decision, None, local, "main", base)
        return decision.bound(local, base)

    bounded, code = shop.ship(
        shop.request(number=number, decision=packet(shop.base), title=None, body=None)
    )

    assert (code, bounded["status"]) == (4, "NEEDS_JUDGMENT"), bounded
    assert "stale" in str(bounded["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert shop.gate_heads() == [] and shop.hub.create_calls == []

    resumed, code = shop.ship(
        shop.request(number=number, decision=packet(upstream), title=None, body=None),
        run_of(bounded),
    )

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == local
    assert shop.hub.create_calls == [] and list(shop.hub.entries) == [number]


@pytest.mark.parametrize("state", ["closed", "merged"])
@pytest.mark.parametrize("work", ["commit", "dirty"])
def test_resume_without_a_plan_never_completes_over_unpublished_work_of_a_saved_pr(
    shop: Shop, state: str, work: str
) -> None:
    dirty(shop)
    first, code = shop.ship(shop.request(plan=shop.plan()))
    assert (code, first["status"]) == (0, "COMPLETE"), first
    published = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    if state == "closed":
        shop.hub.entries[1].closed = True
    else:
        shop.hub.merge(1, published, "squash")
    merges = list(shop.hub.merge_calls)
    if work == "commit":
        (shop.work / "later.txt").write_text("later local work\n")
        git(shop.work, "add", "later.txt")
        git(shop.work, "commit", "-q", "-m", "feat: later local work")
    else:
        (shop.work / "a.txt").write_text("alpha\nstaged\nunstaged\nuncommitted\n")
    local = git(shop.work, "rev-parse", "HEAD")
    status = git(shop.work, "status", "--porcelain", "--untracked-files=all")
    content = (shop.work / "a.txt").read_bytes()

    result, code = shop.ship(shop.request(), run_of(first))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert git(shop.work, "rev-parse", "HEAD") == local
    assert git(shop.work, "rev-parse", f"refs/heads/{BRANCH}") == local
    assert git(shop.work, "status", "--porcelain", "--untracked-files=all") == status
    assert (shop.work / "a.txt").read_bytes() == content
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert shop.hub.merge_calls == merges


def test_selected_merged_pr_with_new_local_commits_is_never_silently_completed(
    shop: Shop,
) -> None:
    number, published = feature_pr(shop)
    shop.hub.merge(number, published, "squash")
    (shop.work / "a.txt").write_text("alpha\npublished\nfollow-up\n")
    git(shop.work, "commit", "-q", "-am", "fix: follow-up")
    local = git(shop.work, "rev-parse", "HEAD")
    merges = list(shop.hub.merge_calls)

    result, code = shop.ship(shop.request(number=number))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert "cannot take new local work" in str(result["blocker"])
    assert git(shop.work, "rev-parse", f"refs/heads/{BRANCH}") == local
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert shop.hub.create_calls == [] and shop.hub.merge_calls == merges
    assert result["run_id"] is None and not shop.store().list_runs()


def test_unrelated_history_is_never_published_against_the_named_base(
    shop: Shop,
) -> None:
    git(shop.work, "switch", "-q", "--orphan", BRANCH)
    git(shop.work, "rm", "-rfq", "--ignore-unmatch", ".")
    (shop.work / "unrelated.txt").write_text("unrelated root\n")
    git(shop.work, "add", "unrelated.txt")
    git(shop.work, "commit", "-q", "-m", "feat: unrelated root")
    root = git(shop.work, "rev-parse", "HEAD")

    result, code = shop.ship(
        shop.request(branch=BRANCH, decision=existing_decision(shop, root))
    )

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert "shares no history" in str(result["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.create_calls == []


def test_explicit_base_off_the_providers_base_branch_is_still_refused(
    shop: Shop,
) -> None:
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\nfirst\n")
    git(shop.work, "commit", "-q", "-am", "feat: first")
    side = git(shop.work, "rev-parse", "HEAD")
    (shop.work / "a.txt").write_text("alpha\nfirst\nsecond\n")
    git(shop.work, "commit", "-q", "-am", "feat: second")
    head = git(shop.work, "rev-parse", "HEAD")
    decision = replace(existing_decision(shop, head), base_oid=side)

    result, code = shop.ship(shop.request(branch=BRANCH, decision=decision))

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert "not on the current base branch" in str(result["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.create_calls == []


@pytest.mark.parametrize(
    "given", [(None, None), ("feat: only a title", None), (None, b"only a body")]
)
def test_missing_creation_inputs_stop_a_plan_before_commits_or_journals(
    shop: Shop, given: tuple[str | None, bytes | None]
) -> None:
    dirty(shop)
    plan = shop.plan()
    snapshot = shop.repo().snapshot().fingerprint
    title, body = given

    result, code = shop.ship(shop.request(plan=plan, title=title, body=body))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert "title and body" in str(result["blocker"])
    assert shop.repo().snapshot().fingerprint == snapshot
    assert ref(shop.work, f"refs/heads/{BRANCH}") is None
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert result["run_id"] is None and not shop.store().list_runs()
    assert shop.hub.create_calls == [] and shop.gate_heads() == []


@pytest.mark.parametrize(
    "given", [(None, None), ("feat: only a title", None), (None, b"only a body")]
)
def test_missing_creation_inputs_stop_an_existing_branch_before_any_push(
    shop: Shop, given: tuple[str | None, bytes | None]
) -> None:
    git(shop.work, "switch", "-q", "-c", BRANCH)
    (shop.work / "a.txt").write_text("alpha\nexisting local work\n")
    git(shop.work, "commit", "-q", "-am", "feat: preserve reasonable local commit")
    local = git(shop.work, "rev-parse", "HEAD")
    title, body = given

    result, code = shop.ship(
        shop.request(
            branch=BRANCH,
            decision=existing_decision(shop, local),
            title=title,
            body=body,
        )
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert "title and body" in str(result["blocker"])
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert result["run_id"] is None and not shop.store().list_runs()
    assert shop.hub.create_calls == [] and shop.gate_heads() == []


def test_valid_title_and_body_reach_creation_as_plain_data(shop: Shop) -> None:
    title = 'fix: "quotes", $(subst), `ticks`, ; & | <angle> \\ cases'
    body = b"## Why\n$(not run)\n`ticks`\n"
    dirty(shop)

    result, code = shop.ship(shop.request(plan=shop.plan(), title=title, body=body))

    assert (code, result["status"]) == (0, "COMPLETE"), result
    [(_, _, _, created_title, created_body)] = shop.hub.create_calls
    assert (created_title, created_body) == (title, body)
    publication = shop.receipt(result).publication
    assert publication is not None and publication.create is not None
    assert publication.create.title_identity == publish._identity(title.encode())
    assert publication.create.body_identity == publish._identity(body)


# -- admission before mutation, retargeted PRs, controller source upgrades -------------

OLD_SOURCES = "0" * 64
UNREVIEWED_HEAD = "a" * 40


def untracked(shop: Shop, name: str = "extra.txt") -> None:
    (shop.work / name).write_text(f"{name}\n")


def commit_later(shop: Shop, name: str = "later.txt") -> str:
    (shop.work / name).write_text("later local work\n")
    git(shop.work, "add", name)
    git(shop.work, "commit", "-q", "-m", "feat: later local work")
    return git(shop.work, "rev-parse", "HEAD")


def retarget(shop: Shop, number: int, base: str = "release") -> None:
    """The provider moved an open PR to another base branch at the same commit."""
    git(shop.bare, "branch", base, shop.base)
    shop.hub.entries[number].base_ref = base


def assert_untouched(shop: Shop, fingerprint: str, tip: str | None) -> None:
    """No checkout, index, ref, journal, gate or creation changed."""
    assert shop.repo().snapshot().fingerprint == fingerprint
    assert ref(shop.work, f"refs/heads/{BRANCH}") == tip
    assert not shop.store().list_runs()
    assert shop.gate_heads() == []
    assert shop.hub.create_calls == []


def age_controller(shop: Shop, run_id: str) -> None:
    """The saved actions were written by earlier controller sources."""
    store = shop.store()
    saved = store.load(run_id)
    saved.code_identity = OLD_SOURCES
    with store.mutation_lock():
        store.save(saved)


def journal(receipt: Receipt) -> tuple[object, ...]:
    """Authority and operation identities of a saved run, without advisory text."""
    return (
        receipt.code_identity,
        receipt.policy_identity,
        receipt.validation_sha,
        receipt.validation_policy,
        receipt.target,
        receipt.changeset,
        receipt.publication,
        receipt.intents,
    )


def lose_next_push_response(
    monkeypatch: pytest.MonkeyPatch, *, deliver: bool = True
) -> list[str]:
    """Record every push; the first one's response is lost (after delivery or not)."""
    pushed: list[str] = []
    real_push = GitRepository.push_head

    def response_lost(
        self: GitRepository,
        remote: str,
        branch: str,
        new_oid: str,
        expected_old: str | None,
    ) -> None:
        pushed.append(new_oid)
        if len(pushed) == 1:
            if deliver:
                real_push(self, remote, branch, new_oid, expected_old)
            raise GitError("the push response was lost", uncertain=True)
        real_push(self, remote, branch, new_oid, expected_old)

    monkeypatch.setattr(GitRepository, "push_head", response_lost)
    return pushed


@pytest.mark.parametrize("state", ["closed", "merged"])
def test_closed_or_merged_selected_pr_stops_a_plan_before_any_local_mutation(
    shop: Shop, state: str
) -> None:
    number, published = feature_pr(shop)
    if state == "closed":
        shop.hub.entries[number].closed = True
    else:
        shop.hub.merge(number, published, "squash")
    merges = list(shop.hub.merge_calls)
    untracked(shop)
    plan = shop.plan(mode="current")
    fingerprint = shop.repo().snapshot().fingerprint

    result, code = shop.ship(shop.request(plan=plan, number=number))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert_untouched(shop, fingerprint, published)
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert shop.hub.merge_calls == merges


@pytest.mark.parametrize("contradiction", ["branch", "base"])
def test_plan_placement_contradicting_the_selected_pr_stops_before_any_local_mutation(
    shop: Shop, contradiction: str
) -> None:
    number, published = feature_pr(shop)
    if contradiction == "branch":
        git(shop.work, "switch", "-q", "main")
        untracked(shop)
        plan = shop.plan(branch="feat/other")
    else:
        retarget(shop, number)
        untracked(shop)
        plan = shop.plan(mode="current")
    fingerprint = shop.repo().snapshot().fingerprint

    result, code = shop.ship(shop.request(plan=plan, number=number))

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert_untouched(shop, fingerprint, published)
    assert ref(shop.work, "refs/heads/feat/other") is None
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published


def test_head_namespace_contradicting_the_selected_pr_stops_a_plan_before_any_commit(
    shop: Shop,
) -> None:
    number, published = feature_pr(shop)
    untracked(shop)
    plan = shop.plan(mode="current")
    fingerprint = shop.repo().snapshot().fingerprint

    with pytest.raises(ReceiptInputError):
        shop.ship(shop.request(plan=plan, number=number, head_repo=FORK_REPO))

    assert_untouched(shop, fingerprint, published)


@pytest.mark.parametrize("kind", ["foreign-plan", "explicit-head", "legacy-head"])
def test_decision_that_cannot_bind_the_planned_commits_stops_before_any_commit(
    shop: Shop, kind: str
) -> None:
    dirty(shop)
    plan = shop.plan()
    fingerprint = shop.repo().snapshot().fingerprint
    decision: Policy | Binding
    if kind == "foreign-plan":
        decision = replace(lifecycle_decision(plan), plan="f" * 64)
    elif kind == "explicit-head":
        decision = existing_decision(shop, UNREVIEWED_HEAD)
    else:
        decision = Decision(
            ("fixture CI",), ("tests",), "squash", (), (), (), (), False
        ).bound(UNREVIEWED_HEAD, shop.base)

    result, code = shop.ship(shop.request(plan=plan, decision=decision))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert_untouched(shop, fingerprint, None)
    assert ref(shop.bare, f"refs/heads/{BRANCH}") is None
    assert shop.hub.merge_calls == []


@pytest.mark.parametrize("later", [False, True])
def test_confirmed_plan_resumes_under_an_explicit_refreshed_packet(
    shop: Shop, later: bool
) -> None:
    dirty(shop)
    plan = shop.plan()
    first, code = shop.ship(shop.request(plan=plan))
    assert (code, first["status"]) == (0, "COMPLETE"), first
    head = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    if later:
        head = commit_later(shop)
    gated = shop.gate_heads()

    result, code = shop.ship(
        shop.request(plan=plan, decision=existing_decision(shop, head)), run_of(first)
    )

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == head
    assert git(shop.work, "rev-parse", f"refs/heads/{BRANCH}") == head
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert shop.gate_heads() == (gated + [head] if later else gated)


def test_selected_open_pr_takes_a_plan_without_a_replacement(shop: Shop) -> None:
    number, published = feature_pr(shop)
    untracked(shop)
    plan = shop.plan(mode="current")

    result, code = shop.ship(shop.request(plan=plan, number=number))

    assert (code, result["status"]) == (0, "COMPLETE"), result
    [commit] = result["confirmed_commits"]  # type: ignore[misc]
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == commit
    assert git(shop.work, "rev-parse", f"{commit}^") == published
    assert shop.hub.create_calls == [] and list(shop.hub.entries) == [number]
    assert shop.receipt(result).number == number


def test_direct_path_never_rebinds_a_plan_decision_to_a_retargeted_pr(
    shop: Shop,
) -> None:
    dirty(shop)
    plan = shop.plan()
    first, code = shop.ship(shop.request(plan=plan, endpoint="merged"))
    assert (code, first["status"]) == (4, "NEEDS_JUDGMENT"), first
    retarget(shop, 1)  # the placement base commit is still reachable from release

    result, code = shop.ship(
        shop.request(endpoint="merged", decision=lifecycle_decision(plan)),
        run_of(first),
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert shop.hub.merge_calls == [] and shop.hub.entries[1].merged is None
    assert ref(shop.bare, "refs/heads/release") == shop.base
    receipt = shop.receipt(result)
    assert not receipt.merge_verified
    assert [op for op in receipt.intents if op["kind"] == "merge"] == []


def test_direct_path_never_rebinds_an_explicit_packet_to_a_retargeted_pr(
    shop: Shop,
) -> None:
    number, published = feature_pr(shop)
    retarget(shop, number)  # the packet's base commit is still the release tip

    result, code = shop.ship(
        shop.request(
            number=number,
            endpoint="merged",
            decision=existing_decision(shop, published),
            title=None,
            body=None,
        )
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert shop.hub.merge_calls == [] and shop.hub.entries[number].merged is None
    assert ref(shop.bare, "refs/heads/release") == shop.base
    receipt = shop.receipt(result)
    assert not receipt.merge_verified
    assert [op for op in receipt.intents if op["kind"] == "merge"] == []


def test_pending_push_across_source_versions_settles_only_under_a_refreshed_decision(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirty(shop)
    plan = shop.plan()
    pushed = lose_next_push_response(monkeypatch)
    first, code = shop.ship(shop.request(plan=plan))
    assert (code, first["status"]) == (3, "WAITING"), first
    run_id = run_of(first)
    tip = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == tip
    age_controller(shop, run_id)
    saved = journal(shop.receipt(first))

    bounded, code = shop.ship(shop.request(), run_id)

    assert (code, bounded["status"]) == (4, "NEEDS_JUDGMENT"), bounded
    assert journal(shop.receipt(first)) == saved
    assert pushed == [tip] and shop.hub.create_calls == []

    resumed, code = shop.ship(shop.request(decision=lifecycle_decision(plan)), run_id)

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert pushed == [tip]  # the delivered push was settled, never sent again
    receipt = shop.receipt(resumed)
    assert receipt.code_identity == lifecycle.code_identity()
    assert receipt.publication is not None
    assert receipt.publication.push == PushRecord(None, tip, "CONFIRMED")
    assert len(shop.hub.create_calls) == 1 and receipt.number == 1


def test_same_packet_never_refreshes_a_saved_run_but_a_changed_one_settles_its_push(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirty(shop)
    plan = shop.plan()
    original = lifecycle_decision(plan)
    first, code = shop.ship(shop.request(plan=plan, decision=original))
    assert (code, first["status"]) == (0, "COMPLETE"), first
    run_id = run_of(first)
    published = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    recorded = shop.receipt(first).policy_identity
    assert recorded is not None
    local = commit_later(shop)
    pushed = lose_next_push_response(monkeypatch)
    refreshed = existing_decision(shop, local)
    waiting, code = shop.ship(shop.request(decision=refreshed), run_id)
    assert (code, waiting["status"]) == (3, "WAITING"), waiting
    assert pushed == [local] and ref(shop.bare, f"refs/heads/{BRANCH}") == local
    age_controller(shop, run_id)
    saved = journal(shop.receipt(first))

    for packet in (None, original):  # no decision, and the one the authority came from
        bounded, code = shop.ship(shop.request(decision=packet), run_id)
        assert (code, bounded["status"]) == (4, "NEEDS_JUDGMENT"), bounded
        assert journal(shop.receipt(first)) == saved
    assert pushed == [local]

    resumed, code = shop.ship(shop.request(decision=refreshed), run_id)

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert pushed == [local]
    receipt = shop.receipt(resumed)
    assert receipt.code_identity == lifecycle.code_identity()
    assert receipt.policy_identity not in (None, recorded)
    assert receipt.publication is not None
    assert receipt.publication.push == PushRecord(published, local, "CONFIRMED")
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]


def test_accepted_unlisted_creation_across_source_versions_is_settled_not_recreated(
    shop: Shop,
) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.create_mode = "accepted_unlisted"
    first, code = shop.ship(shop.request(plan=plan, wait_timeout=0.2))
    assert (code, first["status"]) == (3, "WAITING"), first
    run_id = run_of(first)
    age_controller(shop, run_id)
    saved = journal(shop.receipt(first))
    lookups = len(shop.hub.lookups)

    bounded, code = shop.ship(shop.request(wait_timeout=0.2), run_id)

    assert (code, bounded["status"]) == (4, "NEEDS_JUDGMENT"), bounded
    assert len(shop.hub.lookups) == lookups  # nothing settled under unreviewed sources
    assert journal(shop.receipt(first)) == saved
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]

    refreshed = lifecycle_decision(plan)
    waiting, code = shop.ship(
        shop.request(decision=refreshed, wait_timeout=0.2), run_id
    )

    assert (code, waiting["status"]) == (3, "WAITING"), waiting
    assert pending_creation(shop, waiting) == ("PENDING", None)
    assert shop.receipt(waiting).code_identity == lifecycle.code_identity()
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    shop.hub.entries[1].listed = True

    resumed, code = shop.ship(shop.request(), run_id)

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert pending_creation(shop, resumed) == ("CONFIRMED", 1)
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert shop.receipt(resumed).number == 1


def test_refresh_validates_the_outgoing_range_again_after_an_undelivered_push(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    number, published = feature_pr(shop)
    (shop.work / "a.txt").write_text("alpha\npublished\nfollow-up\n")
    git(shop.work, "commit", "-q", "-am", "fix: follow-up")
    local = git(shop.work, "rev-parse", "HEAD")
    original = existing_decision(shop, local)
    pushed = lose_next_push_response(monkeypatch, deliver=False)
    first, code = shop.ship(
        shop.request(number=number, decision=original, title=None, body=None)
    )
    assert (code, first["status"]) == (3, "WAITING"), first
    run_id = run_of(first)
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert shop.gate_heads() == [local]
    age_controller(shop, run_id)
    reviewed = replace(
        original, decision=replace(original.decision, sources=("reviewed CI",))
    )

    resumed, code = shop.ship(
        shop.request(number=number, decision=reviewed, title=None, body=None), run_id
    )

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == local
    assert pushed == [local, local]  # the first one provably never reached the remote
    assert shop.gate_heads() == [local, local]  # the old validation was not trusted
    assert shop.receipt(resumed).code_identity == lifecycle.code_identity()


def test_refresh_leaves_an_unresolved_merge_to_lifecycle_reconciliation(
    shop: Shop,
) -> None:
    dirty(shop)
    plan = shop.plan()
    first, code = shop.ship(shop.request(plan=plan, decision=lifecycle_decision(plan)))
    assert (code, first["status"]) == (0, "COMPLETE"), first
    run_id = run_of(first)
    published = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    local = commit_later(shop)
    store = shop.store()
    saved = store.load(run_id)
    saved.code_identity = OLD_SOURCES
    saved.status = "WAITING"
    saved.intents.append(
        {
            "key": "merge:1",
            "kind": "merge",
            "resource": "pull/1",
            "expected_oid": published,
            "outcome": "PENDING",
            "actual_oid": None,
            "created_at": "2026-10-12T00:00:00Z",
            "namespace": None,
            "required": True,
            "ref": None,
            "proof": None,
        }
    )
    with store.mutation_lock():
        store.save(saved)
    before = journal(shop.receipt(first))
    gated = shop.gate_heads()

    result, code = shop.ship(
        shop.request(decision=existing_decision(shop, local)), run_id
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert journal(shop.receipt(first)) == before
    assert ref(shop.bare, f"refs/heads/{BRANCH}") == published
    assert shop.gate_heads() == gated and shop.hub.merge_calls == []


def test_refresh_never_overwrites_a_concurrent_controllers_journal_change(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirty(shop)
    plan = shop.plan()
    pushed = lose_next_push_response(monkeypatch)
    first, code = shop.ship(shop.request(plan=plan))
    assert (code, first["status"]) == (3, "WAITING"), first
    run_id = run_of(first)
    age_controller(shop, run_id)
    mine = shop.store()
    handle = mine.load(run_id)
    peer = shop.store()
    concurrent = peer.load(run_id)
    concurrent.issue = "a peer controller recorded this"
    with peer.mutation_lock():
        peer.save(concurrent)

    result, code = publish.ship(
        shop.repo(),
        shop.hub,
        mine,
        shop.request(decision=lifecycle_decision(plan)),
        handle,
    )

    assert (code, result["status"]) == (5, "BLOCKED"), result
    on_disk = shop.store().load(run_id)
    assert on_disk.issue == "a peer controller recorded this"
    assert on_disk.code_identity == OLD_SOURCES
    assert on_disk.publication is not None and on_disk.publication.push is not None
    assert on_disk.publication.push.outcome == "PENDING"
    assert pushed == [on_disk.publication.push.new] and shop.hub.create_calls == []


@pytest.mark.parametrize(
    "mismatch",
    ["plan", "head", "base_ref", "base_oid", "legacy_head", "legacy_base_oid"],
)
@pytest.mark.parametrize("with_plan", [False, True])
def test_foreign_refresh_never_adopts_sources_or_rewrites_the_saved_receipt(
    shop: Shop, monkeypatch: pytest.MonkeyPatch, mismatch: str, with_plan: bool
) -> None:
    dirty(shop)
    plan = shop.plan()
    pushed = lose_next_push_response(monkeypatch)
    first, code = shop.ship(shop.request(plan=plan))
    assert (code, first["status"]) == (3, "WAITING"), first
    run_id = run_of(first)
    tip = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
    age_controller(shop, run_id)
    path = shop.store().directory / f"{run_id}.json"
    saved = path.read_bytes()
    packet = (
        replace(lifecycle_decision(plan), plan="f" * 64)
        if mismatch == "plan"
        else existing_decision(shop, tip)
    )
    if mismatch == "head":
        packet = replace(packet, head=UNREVIEWED_HEAD)
    elif mismatch == "base_ref":
        packet = replace(packet, base_ref="release")
    elif mismatch == "base_oid":
        packet = replace(packet, base_oid=UNREVIEWED_HEAD)
    elif mismatch == "legacy_head":
        packet = replace(packet.bind(tip, shop.base), head_sha=UNREVIEWED_HEAD)
    elif mismatch == "legacy_base_oid":
        packet = replace(packet.bind(tip, shop.base), base_sha=UNREVIEWED_HEAD)

    refused, code = shop.ship(
        shop.request(plan=plan if with_plan else None, decision=packet), run_id
    )

    assert code != 0
    assert refused["mutation_attempted"] is False
    assert refused["mutation_performed"] is False
    assert path.read_bytes() == saved
    assert pushed == [tip] and shop.hub.create_calls == []
    without_packet, code = shop.ship(shop.request(), run_id)
    assert (code, without_packet["status"]) == (4, "NEEDS_JUDGMENT")
    assert path.read_bytes() == saved
    assert pushed == [tip] and shop.hub.create_calls == []


def test_a_second_source_upgrade_requires_a_new_admitted_decision(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.create_mode = "accepted_unlisted"
    first, code = shop.ship(shop.request(plan=plan, wait_timeout=0.2))
    assert (code, first["status"]) == (3, "WAITING"), first
    run_id = run_of(first)
    age_controller(shop, run_id)
    packet = lifecycle_decision(plan)
    waiting, code = shop.ship(shop.request(decision=packet, wait_timeout=0.2), run_id)
    assert (code, waiting["status"]) == (3, "WAITING"), waiting
    age_controller(shop, run_id)
    path = shop.store().directory / f"{run_id}.json"
    saved = path.read_bytes()

    refused, code = shop.ship(shop.request(decision=packet, wait_timeout=0.2), run_id)

    assert (code, refused["status"]) == (4, "NEEDS_JUDGMENT"), refused
    assert path.read_bytes() == saved
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]


def test_bound_frontier_cannot_bypass_the_admitted_source_decision(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirty(shop)
    plan = shop.plan()
    shop.hub.create_mode = "accepted_unlisted"
    first, code = shop.ship(shop.request(plan=plan, wait_timeout=0.2))
    assert (code, first["status"]) == (3, "WAITING"), first
    run_id = run_of(first)
    age_controller(shop, run_id)
    packet = lifecycle_decision(plan)
    shop.hub.entries[1].listed = True

    def interrupt_lifecycle(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as paused:
        paused.setattr(lifecycle, "execute", interrupt_lifecycle)
        bound, code = shop.ship(shop.request(decision=packet), run_id)
    assert (code, bound["status"]) == (130, "WAITING"), bound
    assert shop.receipt(bound).number == 1
    age_controller(shop, run_id)
    path = shop.store().directory / f"{run_id}.json"
    saved = path.read_bytes()

    refused, code = shop.ship(shop.request(decision=packet), run_id)

    assert (code, refused["status"]) == (4, "NEEDS_JUDGMENT"), refused
    assert path.read_bytes() == saved
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]


def test_confirmed_plan_refresh_cannot_adopt_a_different_local_head(shop: Shop) -> None:
    dirty(shop)
    plan = shop.plan()
    original = lifecycle_decision(plan)
    first, code = shop.ship(shop.request(plan=plan, decision=original))
    assert (code, first["status"]) == (0, "COMPLETE"), first
    run_id = run_of(first)
    local = commit_later(shop)
    age_controller(shop, run_id)
    path = shop.store().directory / f"{run_id}.json"
    saved = path.read_bytes()
    reviewed = replace(
        original, decision=replace(original.decision, sources=("reviewed new sources",))
    )

    refused, code = shop.ship(shop.request(plan=plan, decision=reviewed), run_id)

    assert code != 0
    assert refused["mutation_attempted"] is False
    assert refused["mutation_performed"] is False
    assert path.read_bytes() == saved
    assert ref(shop.work, f"refs/heads/{BRANCH}") == local
    assert len(shop.hub.create_calls) == 1
