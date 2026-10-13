"""Execution lifecycle against real Git state and a stateful provider model.

The provider is a behavioural model, not GitHub: it lands PRs by really squashing
into a bare repository (``commit-tree`` + compare-and-swap ``update-ref``), keeps
``refs/pull/N/head`` and advertises PR metadata derived from those refs. It makes
no claim about vendor behaviour; vendor qualification is out of scope here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

import lifecycle
import pytest
from git_ops import GitRepository, Snapshot
from github_ops import (
    Check,
    GitHub,
    Observation,
    ProviderError,
    PullRequest,
    QueueState,
    Repository,
)
from lifecycle import Endpoint, Policy, execute
from state_store import Receipt, Store

REPO = "owner/repo"
HOST = "github.com"
CANONICAL_URL = "https://github.com/owner/repo.git"
MERGED_AT = "2026-10-12T00:00:00Z"
FEATURE = "feat/x"
OPEN_PR_REASON = "an open PR uses this namespace/ref as head or base"
UNPROVED_REASON = "whole landing/current feature identity is unproved or changed"

Result = dict[str, object]
MergeMode = Literal[
    "land", "queue", "uncertain_after", "uncertain_before", "cancel_after", "forbidden"
]

CHECKER = """\
import os, subprocess, sys
marker, flag = sys.argv[1:3]
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                      check=True).stdout.strip()
tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                         check=True).stdout.split()
bodies = ",".join(name + "=" + open(name).read().strip() for name in tracked)
with open(marker, "a") as handle:
    handle.write(head + "\\t" + os.getcwd() + "\\t" + bodies + "\\n")
sys.exit(7 if os.path.exists(flag) else 0)
"""
LANDED_FILES = "README.md=base,a.txt=alpha two,pkg/c.txt=gamma"


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
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture
def fast_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "POLL_INTERVAL", 0.0)


def git(cwd: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {args} failed: {result.stderr.decode(errors='replace')}"
        )
    return os.fsdecode(result.stdout).rstrip("\n")


def exists(repo: Path, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "-q", ref],
            cwd=repo,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=repo,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def heads(repo: Path) -> dict[str, str]:
    listing = git(
        repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"
    )
    return {line.split()[0]: line.split()[1] for line in listing.splitlines()}


class MappedGit(GitRepository):
    """Real Git transport over temp paths, presented under the canonical namespace."""

    def remote_for(self, host: str, full_name: str) -> str | None:
        return "origin" if (host.lower(), full_name.lower()) == (HOST, REPO) else None

    def snapshot(self) -> Snapshot:
        real = super().snapshot()
        return replace(real, remotes={name: CANONICAL_URL for name in real.remotes})


class Forge(GitHub):
    """Stateful PR model over a bare repository; it lands PRs with real Git objects."""

    def __init__(self, bare: Path) -> None:
        super().__init__(HOST, REPO)
        self.bare = bare
        self.number = 1
        self.head_ref = FEATURE
        self.base_ref = "main"
        self.merged: tuple[str, str, str] | None = None
        self.merge_mode: MergeMode = "land"
        self.merge_calls: list[tuple[int, str, str]] = []
        self.queued = False
        self.land_on_poll: int | None = None
        self.queue_polls = 0
        self.read_log: list[tuple[str, int]] = []
        self.extra_open: list[PullRequest] = []
        self.protected_refs = {"main"}
        self.on_closed_listing: Callable[[], None] | None = None

    @property
    def pull_ref(self) -> str:
        return f"refs/pull/{self.number}/head"

    def _rev(self, ref: str) -> str:
        return git(self.bare, "rev-parse", "--verify", ref)

    def _pr(self) -> PullRequest:
        url = f"https://github.com/{REPO}/pull/{self.number}"
        if self.merged is None:
            head = self._rev(f"refs/heads/{self.head_ref}")
            base = self._rev(f"refs/heads/{self.base_ref}")
            git(self.bare, "update-ref", self.pull_ref, head)
            return PullRequest(
                self.number,
                url,
                "OPEN",
                head,
                self.head_ref,
                REPO,
                base,
                self.base_ref,
                REPO,
                None,
                None,
                False,
                True,
                False,
            )
        head, base, landing = self.merged
        return PullRequest(
            self.number,
            url,
            "MERGED",
            head,
            self.head_ref,
            REPO,
            base,
            self.base_ref,
            REPO,
            landing,
            MERGED_AT,
            False,
            None,
            False,
        )

    def land(self) -> str:
        """Squash the PR head onto the base branch exactly as a squash merge would."""
        head = self._rev(f"refs/heads/{self.head_ref}")
        base = self._rev(f"refs/heads/{self.base_ref}")
        assert is_ancestor(self.bare, base, head), "model needs a head based on the tip"
        tree = self._rev(f"{head}^{{tree}}")
        landing = git(
            self.bare,
            "commit-tree",
            tree,
            "-p",
            base,
            "-m",
            f"Ship feature (#{self.number})",
        )
        git(self.bare, "update-ref", f"refs/heads/{self.base_ref}", landing, base)
        self.merged = (head, base, landing)
        self.queued = False
        return landing

    def read_pr(self, number: int) -> PullRequest:
        assert number == self.number
        pr = self._pr()
        self.read_log.append((pr.state, self.queue_polls))
        return pr

    def observe(self, number: int) -> Observation:
        assert number == self.number
        pr = self._pr()
        return Observation(
            repo=Repository(REPO, HOST, "main", ("merge", "squash")),
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
        assert number == self.number and self.merged is None
        self.queue_polls += 1
        if not self.queued:
            return "IDLE"
        if self.land_on_poll is not None and self.queue_polls >= self.land_on_poll:
            self.land()
        return "QUEUED"

    def merge(self, number: int, expected_head: str, method: str) -> None:
        self.merge_calls.append((number, expected_head, method))
        assert self.merge_mode != "forbidden", "merge was dispatched again"
        if self.merged is not None:
            raise ProviderError(
                "merge: PR is not open",
                kind="BLOCKED",
                operation="merge",
                detail="not-open",
            )
        if self._rev(f"refs/heads/{self.head_ref}") != expected_head:
            raise ProviderError(
                "merge: head changed",
                kind="BLOCKED",
                operation="merge",
                detail="merge-head-changed",
            )
        if self.merge_mode == "queue":
            self.queued = True
            return
        if self.merge_mode == "uncertain_before":
            raise ProviderError(
                "merge: timed out", kind="WAITING", operation="merge", uncertain=True
            )
        self.land()
        if self.merge_mode == "uncertain_after":
            raise ProviderError(
                "merge: connection lost",
                kind="BLOCKED",
                operation="merge",
                uncertain=True,
            )
        if self.merge_mode == "cancel_after":
            raise KeyboardInterrupt

    def base_tip(self, base_ref: str) -> str:
        return self._rev(f"refs/heads/{base_ref}")

    def landing_reachable(self, landing: str, base_tip: str) -> bool:
        return is_ancestor(self.bare, landing, base_tip)

    def list_prs(
        self, state: Literal["open", "closed"], full_name: str | None = None
    ) -> tuple[PullRequest, ...]:
        if (full_name or REPO).lower() != REPO:
            return ()
        pr = self._pr()
        if state == "open":
            return ((pr,) if pr.state == "OPEN" else ()) + tuple(self.extra_open)
        hook, self.on_closed_listing = self.on_closed_listing, None
        if hook is not None:
            hook()
        return (pr,) if pr.state == "MERGED" else ()

    def branch_protected(self, full_name: str, ref: str) -> bool:
        return ref in self.protected_refs


@dataclass
class World:
    root: Path
    bare: Path
    work: Path
    forge: Forge
    marker: Path
    flag: Path
    policy: Policy
    head: str
    base: str

    def git(self) -> MappedGit:
        return MappedGit(self.work)

    def store(self) -> Store:
        common = Path(
            git(self.work, "rev-parse", "--path-format=absolute", "--git-common-dir")
        )
        return Store(common)

    def run(
        self, endpoint: Endpoint, *, run_id: str | None = None, wait: float = 30.0
    ) -> tuple[Result, int]:
        store = self.store()
        receipt = store.load(run_id) if run_id is not None else None
        return execute(
            self.git(), self.forge, 1, endpoint, self.policy, wait, store, receipt
        )

    def receipt(self, run_id: str) -> Receipt:
        return self.store().load(run_id)

    def marker_lines(self) -> list[list[str]]:
        if not self.marker.exists():
            return []
        return [line.split("\t") for line in self.marker.read_text().splitlines()]

    def advance_base(self) -> str:
        """Another PR lands on the remote base: a real commit pushed from a second clone."""
        other = self.root / "other"
        if not other.exists():
            git(self.root, "clone", "-q", str(self.bare), str(other))
        git(other, "pull", "-q", "--ff-only", "origin", "main")
        (other / "later.txt").write_text("later\n")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "unrelated base work")
        git(other, "push", "-q", "origin", "main")
        return git(other, "rev-parse", "HEAD")

    def post_merge_work(self, where: Literal["local", "remote", "both"]) -> str:
        """Someone adds a commit to the feature branch after it was merged."""
        new = git(
            self.work,
            "commit-tree",
            f"{self.head}^{{tree}}",
            "-p",
            self.head,
            "-m",
            "post-merge work",
        )
        if where in ("local", "both"):
            git(self.work, "branch", "-f", FEATURE, new)
        if where in ("remote", "both"):
            git(self.work, "push", "-q", "origin", f"{new}:refs/heads/{FEATURE}")
        return new


@pytest.fixture
def world(tmp_path: Path) -> World:
    root = tmp_path.resolve()
    bare = root / "remote.git"
    work = root / "work"
    git(root, "init", "-q", "--bare", "-b", "main", str(bare))
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    git(work, "remote", "add", "origin", str(bare))
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    git(work, "push", "-q", "-u", "origin", "main")
    base = git(work, "rev-parse", "HEAD")
    git(work, "switch", "-q", "-c", FEATURE)
    (work / "a.txt").write_text("alpha\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "add a")
    (work / "pkg").mkdir()
    (work / "pkg" / "c.txt").write_text("gamma\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "add c")
    (work / "a.txt").write_text("alpha two\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "revise a")
    git(work, "push", "-q", "-u", "origin", FEATURE)
    head = git(work, "rev-parse", "HEAD")

    tools = root / "tools"
    tools.mkdir()
    checker = tools / "verify.py"
    checker.write_text(CHECKER)
    marker = tools / "runs.log"
    flag = tools / "fail.flag"
    policy = Policy(
        ("ci workflow at the current base",),
        ("tests",),
        "squash",
        ((sys.executable, str(checker), str(marker), str(flag)),),
        head,
        base,
    )
    forge = Forge(bare)
    assert forge.read_pr(1).head_sha == head  # also publishes refs/pull/1/head
    forge.read_log.clear()
    return World(root, bare, work, forge, marker, flag, policy, head, base)


def rows(result: Result, section: str, name: str) -> list[dict[str, object]]:
    return cast(dict[str, list[dict[str, object]]], result[section])[name]


def kinds(receipt: Receipt) -> list[str]:
    return [cast(str, op["kind"]) for op in receipt.intents]


def merge_outcome(receipt: Receipt) -> object:
    return [op for op in receipt.intents if op["kind"] == "merge"][-1]["outcome"]


def run_id(result: Result) -> str:
    return cast(str, result["run_id"])


def assert_feature_untouched(world: World) -> None:
    assert heads(world.work)[f"refs/heads/{FEATURE}"] == world.head
    assert heads(world.bare)[f"refs/heads/{FEATURE}"] == world.head
    assert git(world.bare, "rev-parse", world.forge.pull_ref) == world.head


def assert_feature_gone(world: World) -> None:
    assert f"refs/heads/{FEATURE}" not in heads(world.work)
    assert f"refs/heads/{FEATURE}" not in heads(world.bare)
    assert not exists(world.work, f"refs/remotes/origin/{FEATURE}")
    assert git(world.bare, "rev-parse", world.forge.pull_ref) == world.head


# -- normal endpoint --------------------------------------------------------------


def test_multi_commit_squash_runs_configured_command_on_landing_and_cleans_refs(
    world: World,
) -> None:
    result, code = world.run("clean")
    assert (code, result["status"]) == (0, "COMPLETE"), result

    landing = git(world.bare, "rev-parse", "refs/heads/main")
    assert landing != world.base
    assert git(world.bare, "rev-list", "--count", f"{world.base}..{world.head}") == "3"
    assert git(world.bare, "rev-list", "--count", "main") == "2"
    assert git(world.bare, "log", "-1", "--format=%P", "main") == world.base
    assert git(world.bare, "log", "-1", "--format=%s", "main") == "Ship feature (#1)"
    assert git(world.bare, "rev-parse", "main^{tree}") == git(
        world.bare, "rev-parse", f"{world.head}^{{tree}}"
    )
    assert not is_ancestor(world.bare, world.head, landing)
    assert world.forge.merge_calls == [(1, world.head, "squash")]

    assert git(world.work, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(world.work, "rev-parse", "HEAD") == landing
    assert git(world.work, "status", "--porcelain", "--untracked-files=all") == ""
    assert (world.work / "pkg" / "c.txt").read_text() == "gamma\n"

    # The configured command ran once, inside the retained checkout, on the landed code.
    [(command_head, command_cwd, files)] = world.marker_lines()
    assert (command_head, Path(command_cwd).resolve(), files) == (
        landing,
        world.work,
        LANDED_FILES,
    )

    assert_feature_gone(world)
    assert set(heads(world.bare)) == {"refs/heads/main"}
    assert set(heads(world.work)) == {"refs/heads/main"}

    assert rows(result, "cleanup", "failed") == []
    assert result["usable_checkout"] == {
        "path": str(world.work),
        "head": landing,
        "branch": "main",
    }
    assert result["confirmed_merges"] == [
        {
            "url": "https://github.com/owner/repo/pull/1",
            "landing": landing,
            "reachable": True,
        }
    ]

    record = world.receipt(run_id(result))
    assert (record.status, record.merge_sha, record.merge_verified) == (
        "COMPLETE",
        landing,
        True,
    )
    assert record.validation_sha == landing
    assert {op["outcome"] for op in record.intents} == {"CONFIRMED"}
    assert (
        next(op for op in record.intents if op["kind"] == "merge")["actual_oid"]
        == landing
    )


# -- post-merge command failure ----------------------------------------------------


def test_failed_post_merge_command_keeps_every_ref_and_resume_does_not_remerge(
    world: World,
) -> None:
    world.flag.write_text("fail\n")
    result, code = world.run("clean")
    landing = git(world.bare, "rev-parse", "refs/heads/main")

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert result["blocker"] == "post-merge command 0 failed (exit 7)"
    assert result["confirmed_merges"] == [
        {
            "url": "https://github.com/owner/repo/pull/1",
            "landing": landing,
            "reachable": True,
        }
    ]
    [failure] = cast(list[dict[str, object]], result["verification"])
    assert (failure["outcome"], failure["returncode"], failure["sha"]) == (
        "FAILED",
        7,
        landing,
    )
    assert_feature_untouched(world)
    assert exists(world.work, f"refs/remotes/origin/{FEATURE}")
    assert rows(result, "cleanup", "removed") == []
    assert [line[0] for line in world.marker_lines()] == [landing]
    assert git(world.work, "rev-parse", "HEAD") == landing

    saved = world.receipt(run_id(result))
    assert (saved.status, saved.merge_sha, saved.merge_verified) == (
        "BLOCKED",
        landing,
        True,
    )
    assert saved.validation_sha is None
    assert kinds(saved) == ["merge", "fetch", "checkout", "verify"]
    assert saved.intents[-1]["outcome"] == "REJECTED"

    world.flag.unlink()
    resumed, resumed_code = world.run("clean", run_id=run_id(result))
    assert (resumed_code, resumed["status"], resumed["run_id"]) == (
        0,
        "COMPLETE",
        run_id(result),
    )
    assert world.forge.merge_calls == [(1, world.head, "squash")]
    assert [line[0] for line in world.marker_lines()] == [landing, landing]
    assert [
        row["outcome"] for row in cast(list[dict[str, object]], resumed["verification"])
    ] == [
        "FAILED",
        "PASSED",
    ]
    assert_feature_gone(world)


# -- merge queue ---------------------------------------------------------------


def test_accepted_queue_is_awaited_until_provider_reports_merged(
    world: World, fast_polls: None
) -> None:
    world.forge.merge_mode = "queue"
    world.forge.land_on_poll = 3
    result, code = world.run("clean")
    assert (code, result["status"]) == (0, "COMPLETE"), result

    assert world.forge.merge_calls == [(1, world.head, "squash")]
    assert world.forge.queue_polls == 3
    assert {state for state, polls in world.forge.read_log if polls < 3} == {"OPEN"}
    assert world.forge.read_log[-1][0] == "MERGED"
    landing = git(world.bare, "rev-parse", "refs/heads/main")
    assert [line[0] for line in world.marker_lines()] == [landing]
    assert merge_outcome(world.receipt(run_id(result))) == "CONFIRMED"
    assert_feature_gone(world)


def test_queue_wait_timeout_then_actual_merge_resumes_once(
    world: World, fast_polls: None
) -> None:
    world.forge.merge_mode = "queue"
    result, code = world.run("clean", wait=0.01)
    assert (code, result["status"]) == (3, "WAITING"), result
    assert result["blocker"] == "accepted merge is not MERGED yet (QUEUED)"
    assert world.forge.queue_polls >= 1
    assert git(world.bare, "rev-parse", "refs/heads/main") == world.base
    assert world.marker_lines() == []
    assert_feature_untouched(world)
    assert merge_outcome(world.receipt(run_id(result))) == "ACCEPTED"

    world.forge.land()
    landing = git(world.bare, "rev-parse", "refs/heads/main")
    resumed, resumed_code = world.run("clean", run_id=run_id(result))
    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert world.forge.merge_calls == [(1, world.head, "squash")]
    assert [line[0] for line in world.marker_lines()] == [landing]
    assert merge_outcome(world.receipt(run_id(result))) == "CONFIRMED"
    assert_feature_gone(world)


# -- uncertain / cancelled dispatch ------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "status", "code"),
    [("uncertain_after", "BLOCKED", 5), ("cancel_after", "WAITING", 130)],
)
def test_lost_merge_report_reconciles_the_actual_merge_without_redispatch(
    world: World, mode: MergeMode, status: str, code: int
) -> None:
    world.forge.merge_mode = mode
    result, first_code = world.run("clean")
    assert (first_code, result["status"]) == (code, status), result
    assert result["mutation_attempted"] is True
    assert result["cancelled"] is (mode == "cancel_after")
    landing = git(world.bare, "rev-parse", "refs/heads/main")
    assert landing != world.base  # the merge really happened
    assert world.marker_lines() == []
    assert_feature_untouched(world)
    assert merge_outcome(world.receipt(run_id(result))) == "PENDING"

    world.forge.merge_mode = "forbidden"
    resumed, resumed_code = world.run("clean", run_id=run_id(result))
    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert len(world.forge.merge_calls) == 1
    [(command_head, _cwd, files)] = world.marker_lines()
    assert (command_head, files) == (landing, LANDED_FILES)
    record = world.receipt(run_id(result))
    [merge] = [op for op in record.intents if op["kind"] == "merge"]
    assert (merge["outcome"], merge["actual_oid"]) == ("CONFIRMED", landing)
    assert record.merge_sha == landing
    assert_feature_gone(world)


def test_unknown_merge_with_open_idle_pr_is_never_retried(world: World) -> None:
    world.forge.merge_mode = "uncertain_before"
    result, code = world.run("clean")
    assert (code, result["status"]) == (3, "WAITING"), result
    assert world.forge.merge_calls == [(1, world.head, "squash")]

    for _attempt in range(2):
        resumed, resumed_code = world.run("clean", run_id=run_id(result))
        assert (resumed_code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed
        assert resumed["blocker"] == "merge outcome remains unknown while PR is open"
    assert world.forge.merge_calls == [(1, world.head, "squash")]
    assert world.forge.queue_polls == 2
    assert git(world.bare, "rev-parse", "refs/heads/main") == world.base
    assert merge_outcome(world.receipt(run_id(result))) == "PENDING"
    assert world.marker_lines() == []
    assert_feature_untouched(world)


# -- completed runs ---------------------------------------------------------------


def journal_state(world: World) -> dict[str, tuple[bytes, int, int]]:
    directory = world.store().directory
    return {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
        for path in sorted(directory.iterdir())
    }


def test_completed_resume_leaves_receipt_refs_and_commands_untouched(
    world: World,
) -> None:
    result, code = world.run("clean")
    assert (code, result["status"]) == (0, "COMPLETE"), result
    journal = journal_state(world)
    refs = (git(world.bare, "for-each-ref"), git(world.work, "for-each-ref"))
    marker = world.marker.read_bytes()

    again, again_code = world.run("clean", run_id=run_id(result))
    assert (again_code, again["status"]) == (0, "COMPLETE"), again
    assert again["mutation_attempted"] is False
    assert again["mutation_performed"] is False
    assert journal_state(world) == journal
    assert (git(world.bare, "for-each-ref"), git(world.work, "for-each-ref")) == refs
    assert world.marker.read_bytes() == marker
    assert world.forge.merge_calls == [(1, world.head, "squash")]


def test_completed_cleanup_is_not_authority_over_a_recreated_feature_branch(
    world: World,
) -> None:
    result, _ = world.run("clean")
    assert result["status"] == "COMPLETE", result
    new = world.post_merge_work("remote")

    again, code = world.run("clean", run_id=run_id(result))
    assert (code, again["status"]) == (5, "BLOCKED"), again
    assert again["blocker"] == "completed cleanup absence proof changed"
    assert heads(world.bare)[f"refs/heads/{FEATURE}"] == new
    assert world.forge.merge_calls == [(1, world.head, "squash")]


# -- changed feature refs --------------------------------------------------------


@pytest.mark.parametrize("where", ["local", "remote", "both"])
def test_feature_ref_with_new_work_after_merge_is_preserved(
    world: World, where: Literal["local", "remote", "both"]
) -> None:
    first, first_code = world.run("merged")
    assert (first_code, first["status"]) == (0, "COMPLETE"), first
    assert heads(world.bare)[f"refs/heads/{FEATURE}"] == world.head
    new = world.post_merge_work(where)

    result, code = world.run("clean")
    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert result["blocker"] == "required cleanup targets remain unsafe or failed"
    changed = {"local", "remote"} if where == "both" else {where}
    failed = rows(result, "cleanup", "failed")
    assert {row["kind"] for row in failed} == changed
    assert all(
        row["reason"] == UNPROVED_REASON and row["expected_oid"] == new
        for row in failed
    )
    if where in ("local", "both"):
        assert heads(world.work)[f"refs/heads/{FEATURE}"] == new
    if where in ("remote", "both"):
        assert heads(world.bare)[f"refs/heads/{FEATURE}"] == new
    assert git(world.bare, "rev-parse", world.forge.pull_ref) == world.head
    assert world.forge.merge_calls == [(1, world.head, "squash")]
    if where == "both":
        assert "delete_local" not in kinds(world.receipt(run_id(result)))
        assert "delete_remote" not in kinds(world.receipt(run_id(result)))


# -- safety boundaries ---------------------------------------------------------------


def test_local_changes_stop_before_any_merge_dispatch(world: World) -> None:
    (world.work / "README.md").write_text("user edit\n")
    (world.work / "notes.txt").write_text("untracked\n")
    result, code = world.run("clean")
    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert world.forge.merge_calls == []
    assert git(world.bare, "rev-parse", "refs/heads/main") == world.base
    assert (world.work / "README.md").read_text() == "user edit\n"
    assert (world.work / "notes.txt").read_text() == "untracked\n"
    assert git(world.work, "rev-parse", "--abbrev-ref", "HEAD") == FEATURE
    assert kinds(world.receipt(run_id(result))) == []
    assert_feature_untouched(world)


def test_open_stacked_pr_keeps_its_base_branch_until_it_is_closed(world: World) -> None:
    world.forge.extra_open.append(
        PullRequest(
            2,
            "https://github.com/owner/repo/pull/2",
            "OPEN",
            world.head,
            "child",
            REPO,
            world.head,
            FEATURE,
            REPO,
            None,
            None,
            False,
            True,
            False,
        )
    )
    result, code = world.run("clean")
    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert {
        (row["kind"], row["reason"]) for row in rows(result, "cleanup", "failed")
    } == {
        ("local", OPEN_PR_REASON),
        ("remote", OPEN_PR_REASON),
    }
    landing = git(world.bare, "rev-parse", "refs/heads/main")
    assert landing != world.base
    assert_feature_untouched(world)
    assert exists(world.work, f"refs/remotes/origin/{FEATURE}")
    assert not {"delete_local", "delete_remote"} & set(
        kinds(world.receipt(run_id(result)))
    )

    world.forge.extra_open.clear()
    resumed, resumed_code = world.run("clean", run_id=run_id(result))
    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert [line[0] for line in world.marker_lines()] == [landing]
    assert world.forge.merge_calls == [(1, world.head, "squash")]
    assert_feature_gone(world)


def test_base_advance_after_validation_waits_then_revalidates_before_cleanup(
    world: World,
) -> None:
    advanced: list[str] = []
    world.forge.on_closed_listing = lambda: advanced.append(world.advance_base())
    result, code = world.run("clean")
    assert (code, result["status"]) == (3, "WAITING"), result
    assert result["blocker"] == "intended base advanced after post-merge validation"
    landing = world.receipt(run_id(result)).merge_sha
    [new_tip] = advanced
    assert landing is not None and new_tip != landing
    assert_feature_untouched(world)
    assert [line[0] for line in world.marker_lines()] == [landing]

    resumed, resumed_code = world.run("clean", run_id=run_id(result))
    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert [line[0] for line in world.marker_lines()] == [landing, new_tip]
    assert git(world.work, "rev-parse", "HEAD") == new_tip
    assert git(world.work, "rev-parse", "main") == new_tip
    assert world.forge.merge_calls == [(1, world.head, "squash")]
    assert_feature_gone(world)


def test_feature_worktree_with_a_live_process_is_never_removed(world: World) -> None:
    git(world.work, "switch", "-q", "main")
    tree = world.root / "feature-tree"
    git(world.work, "worktree", "add", "-q", str(tree), FEATURE)
    occupant = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"], cwd=tree
    )
    try:
        result, code = world.run("clean")
        assert (code, result["status"]) == (5, "BLOCKED"), result
        assert occupant.poll() is None
        assert tree.is_dir() and (tree / "a.txt").read_text() == "alpha two\n"
        assert str(tree) in git(world.work, "worktree", "list", "--porcelain")
        assert_feature_untouched(world)
        assert rows(result, "cleanup", "failed") != []
        assert not {"remove_worktree", "delete_local", "delete_remote"} & set(
            kinds(world.receipt(run_id(result)))
        )
    finally:
        occupant.kill()
        occupant.wait()


def test_rejected_resume_expansion_preserves_completed_goal_and_noop(
    world: World,
) -> None:
    completed, code = world.run("merged")
    assert (code, completed["status"]) == (0, "COMPLETE"), completed
    saved = journal_state(world)
    refs = (git(world.work, "for-each-ref"), git(world.bare, "for-each-ref"))
    marker = world.marker.read_bytes()
    rejected, code = world.run("clean", run_id=run_id(completed))
    assert (code, rejected["status"]) == (4, "NEEDS_JUDGMENT"), rejected
    assert journal_state(world) == saved
    resumed, code = world.run("merged", run_id=run_id(completed))
    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert journal_state(world) == saved
    assert refs == (git(world.work, "for-each-ref"), git(world.bare, "for-each-ref"))
    assert world.marker.read_bytes() == marker


@pytest.mark.parametrize("mode", ["uncertain_before", "queue"])
def test_narrowing_cannot_abandon_an_unresolved_merge(
    world: World,
    fast_polls: None,
    mode: MergeMode,
) -> None:
    world.forge.merge_mode = mode
    waiting, code = world.run("clean", wait=0.002)
    assert (code, waiting["status"]) == (3, "WAITING"), waiting
    saved = journal_state(world)
    rejected, code = world.run("pr", run_id=run_id(waiting))
    assert (code, rejected["status"]) == (4, "NEEDS_JUDGMENT"), rejected
    assert journal_state(world) == saved
    assert world.receipt(run_id(waiting)).endpoint == "clean"
    world.forge.land()
    completed, code = world.run("clean", run_id=run_id(waiting))
    assert (code, completed["status"]) == (0, "COMPLETE"), completed
    assert world.forge.merge_calls == [(1, world.head, "squash")]


def test_optional_same_named_local_ref_with_different_upstream_can_remain(
    world: World,
) -> None:
    git(world.work, "push", "origin", f"{FEATURE}:feat/unrelated")
    git(world.work, "branch", "--set-upstream-to=origin/feat/unrelated", FEATURE)
    completed, code = world.run("clean")
    assert (code, completed["status"]) == (0, "COMPLETE"), completed
    assert heads(world.work)[f"refs/heads/{FEATURE}"] == world.head
    assert heads(world.bare)["refs/heads/feat/unrelated"] == world.head
    assert f"refs/heads/{FEATURE}" not in heads(world.bare)
    before = journal_state(world)
    resumed, code = world.run("clean", run_id=run_id(completed))
    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert journal_state(world) == before
