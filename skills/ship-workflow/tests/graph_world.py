"""A real Git universe for manual stack-graph execution regressions.

A bare repository is the remote, one clone is the invoking checkout and another
clone plays an external actor. :class:`GraphForge` models many pull requests over
the bare repository: open heads and bases are its refs, it lands PRs with real
squash, merge or rebase commits, keeps ``refs/pull/N/head`` and injects the
provider faults a graph run must reconcile. It is a behavioural model for
transition and error coverage only, not evidence of vendor behaviour.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import graph
from git_ops import GitError
from github_ops import (
    Check,
    GitHub,
    Observation,
    ProviderError,
    PullRequest,
    QueueState,
    Repository,
)
from graph import StackPlan, parse_stack_plan
from lifecycle import Endpoint
from state_store import GraphJournal, Receipt, Store
from test_execution import HOST, MERGED_AT, REPO, MappedGit, git, heads, is_ancestor
from test_graph_git import SHARED, author_env, git_bytes

TRUNK = "main"
AUTHOR_FORMAT = "--format=%an%x00%ae%x00%ad"
STACK_POLICY = (
    "# Operator-authored stack metadata; the controller cites it, never edits it.\n"
    "stack: stack-7\n"
    "trunk: main\n"
    "branches: [stack/p, stack/c]\n"
)
DECISION: dict[str, object] = {
    "sources": ["CONTRIBUTING.md#merging"],
    "expected_checks": ["tests"],
    "merge_method": "squash",
    "post_merge_commands": [],
}
PROVENANCE: dict[str, object] = {
    "disposition": "preserve",
    "sources": [
        "published Stack-Id and Stack-Position commit trailers",
        ".stack-prs.yaml",
    ],
}

Result = dict[str, object]
PushFault = Literal["none", "lost", "applied_lost"]
RetargetFault = Literal["none", "lost", "applied_lost"]


@dataclass(frozen=True)
class Change:
    """One commit: the full contents of the files it writes, its exact message and
    author (name, email, Git date)."""

    files: dict[str, str]
    message: bytes
    author: tuple[str, str, str]


def commit(repo: Path, index: Path, parent: str, change: Change) -> str:
    """Write ``change`` on top of ``parent`` with plumbing; no checkout moves."""
    env = {"GIT_INDEX_FILE": str(index)}
    git_bytes(repo, "read-tree", parent, env=env)
    for name, text in change.files.items():
        blob = git_bytes(repo, "hash-object", "-w", "--stdin", stdin=text.encode())
        entry = f"100644,{blob.decode('ascii').strip()},{name}"
        git_bytes(repo, "update-index", "--add", "--cacheinfo", entry, env=env)
    tree = git_bytes(repo, "write-tree", env=env).decode("ascii").strip()
    index.unlink()
    oid = git_bytes(
        repo,
        "commit-tree",
        tree,
        "-p",
        parent,
        "-F",
        "-",
        stdin=change.message,
        env=author_env(change.author),
    )
    return oid.decode("ascii").strip()


def tree_files(repo: Path, rev: str) -> dict[str, str]:
    """Every file of ``rev`` with its text."""
    names = git(repo, "ls-tree", "-r", "--name-only", rev).splitlines()
    return {name: git_bytes(repo, "show", f"{rev}:{name}").decode() for name in names}


def messages(repo: Path) -> set[bytes]:
    """The raw message of every commit reachable from any ref of ``repo``."""
    found: set[bytes] = set()
    for oid in git(repo, "rev-list", "--all").splitlines():
        raw = git_bytes(repo, "cat-file", "commit", oid)
        found.add(raw.partition(b"\n\n")[2])
    return found


@dataclass
class Pull:
    """One modelled PR; an open PR's head and base live in the bare repository."""

    head_ref: str
    base_ref: str
    title: str
    body: str
    labels: tuple[str, ...]
    state: Literal["OPEN", "MERGED", "CLOSED"] = "OPEN"
    landed: tuple[str, str, str] | None = None
    closed_head: str | None = None
    native: bool = False


class GraphForge(GitHub):
    """Stateful multi-PR provider model over a bare repository.

    ``held`` PRs report CI only for contexts recorded with :meth:`report_ci`
    (head and the base it was tested against); every other PR is green for its
    current head and base. Mutations are logged: ``merge_calls`` per dispatched
    merge, ``retarget_calls`` per base-edit request and ``patches`` per base edit
    that took effect.
    """

    def __init__(self, bare: Path) -> None:
        super().__init__(HOST, REPO)
        self.bare = bare
        self.pulls: dict[int, Pull] = {}
        self.merge_calls: list[tuple[int, str, str]] = []
        self.retarget_calls: list[tuple[int, str, str, str]] = []
        self.patches: list[tuple[int, str]] = []
        self.contexts: list[tuple[int, str, str]] = []
        self.held: set[int] = set()
        self.runs: dict[tuple[int, str], str] = {}
        self.retarget_fault: RetargetFault = "none"
        self.auto_retarget = False
        self.auto_delete = False
        self.on_retarget: Callable[[int], None] | None = None

    def _rev(self, ref: str) -> str:
        return git(self.bare, "rev-parse", "--verify", ref)

    def _publish_head(self, number: int, head: str) -> None:
        """Keep ``refs/pull/N/head`` at the PR head, as the provider does."""
        ref = f"refs/pull/{number}/head"
        if git(self.bare, "rev-parse", "--verify", "-q", ref, check=False) != head:
            git(self.bare, "update-ref", ref, head)

    def register(self, number: int, head_ref: str, base_ref: str, title: str) -> None:
        self.pulls[number] = Pull(
            head_ref, base_ref, title, f"Body of #{number}.\n", ("stack",)
        )
        self._publish_head(number, self._rev(f"refs/heads/{head_ref}"))

    def landing(self, number: int) -> str:
        landed = self.pulls[number].landed
        if landed is None:
            raise AssertionError(f"#{number} has not landed")
        return landed[2]

    def metadata(self) -> dict[int, tuple[str, str, tuple[str, ...]]]:
        """Operator-owned PR metadata: title, body and labels."""
        return {
            number: (pull.title, pull.body, pull.labels)
            for number, pull in self.pulls.items()
        }

    def current(self, number: int) -> PullRequest:
        """The PR as the provider reports it now, without logging a read."""
        pull = self.pulls[number]
        url = f"https://{HOST}/{REPO}/pull/{number}"
        if pull.state == "MERGED":
            if pull.landed is None:
                raise AssertionError(f"merged #{number} has no landing")
            head, base, landing = pull.landed
            return PullRequest(
                number,
                url,
                "MERGED",
                head,
                pull.head_ref,
                REPO,
                base,
                pull.base_ref,
                REPO,
                landing,
                MERGED_AT,
                False,
                None,
                pull.native,
            )
        base = self._rev(f"refs/heads/{pull.base_ref}")
        if pull.state == "CLOSED":
            if pull.closed_head is None:
                raise AssertionError(f"closed #{number} has no head")
            return PullRequest(
                number,
                url,
                "CLOSED",
                pull.closed_head,
                pull.head_ref,
                REPO,
                base,
                pull.base_ref,
                REPO,
                None,
                None,
                False,
                None,
                pull.native,
            )
        head = self._rev(f"refs/heads/{pull.head_ref}")
        self._publish_head(number, head)
        return PullRequest(
            number,
            url,
            "OPEN",
            head,
            pull.head_ref,
            REPO,
            base,
            pull.base_ref,
            REPO,
            None,
            None,
            False,
            True,
            pull.native,
        )

    def close(self, number: int) -> None:
        """Someone closes open PR ``number`` without merging it."""
        pull = self.pulls[number]
        pull.closed_head = self._rev(f"refs/heads/{pull.head_ref}")
        pull.state = "CLOSED"

    def report_ci(self, number: int) -> None:
        """CI reports green for the PR's current head, tested on its current base."""
        pr = self.current(number)
        self.runs[(number, pr.head_sha)] = pr.base_sha

    def _merge_tree(self, ours: str, theirs: str, base: str | None = None) -> str:
        options = [] if base is None else [f"--merge-base={base}"]
        result = subprocess.run(
            ["git", "merge-tree", "--write-tree", *options, ours, theirs],
            cwd=self.bare,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError("the model lands only conflict-free pull requests")
        return result.stdout.decode("ascii").splitlines()[0]

    def _replay(self, commit_oid: str, onto: str) -> str:
        tree = self._merge_tree(onto, commit_oid, base=f"{commit_oid}^")
        fields = git(self.bare, "show", "-s", "--date=raw", AUTHOR_FORMAT, commit_oid)
        name, email, date = fields.split("\0")
        message = git_bytes(self.bare, "log", "-1", "--format=%B", commit_oid)
        oid = git_bytes(
            self.bare,
            "commit-tree",
            tree,
            "-p",
            onto,
            "-F",
            "-",
            stdin=message,
            env=author_env((name, email, date)),
        )
        return oid.decode("ascii").strip()

    def land(self, number: int, method: str) -> str:
        """Land open PR ``number`` on its base with real commits, as ``method`` does.

        Also the external actor's path: it is not logged as a dispatched merge.
        """
        pull = self.pulls[number]
        if pull.state != "OPEN":
            raise AssertionError(f"#{number} is not open")
        head = self._rev(f"refs/heads/{pull.head_ref}")
        tip = self._rev(f"refs/heads/{pull.base_ref}")
        if method == "rebase":
            landing = tip
            replayed = f"{tip}..{head}"
            listing = git(self.bare, "rev-list", "--reverse", "--no-merges", replayed)
            for oid in listing.splitlines():
                landing = self._replay(oid, landing)
        elif method in ("squash", "merge"):
            tree = self._merge_tree(tip, head)
            parents = ("-p", tip, "-p", head) if method == "merge" else ("-p", tip)
            message = f"{pull.title} (#{number})"
            landing = git(self.bare, "commit-tree", tree, *parents, "-m", message)
        else:
            raise AssertionError(f"unknown merge method {method!r}")
        git(self.bare, "update-ref", f"refs/heads/{pull.base_ref}", landing, tip)
        self._publish_head(number, head)
        pull.state, pull.landed = "MERGED", (head, tip, landing)
        if self.auto_retarget:
            for other in self.pulls.values():
                if other.state == "OPEN" and other.base_ref == pull.head_ref:
                    other.base_ref = pull.base_ref
        if self.auto_delete:
            git(self.bare, "update-ref", "-d", f"refs/heads/{pull.head_ref}", head)
        return landing

    # -- the provider interface the graph and lifecycle consume ------------------------

    def read_pr(self, number: int) -> PullRequest:
        return self.current(number)

    def observe(self, number: int) -> Observation:
        pr = self.current(number)
        self.contexts.append((number, pr.head_sha, pr.base_sha))
        tested: str | None = pr.base_sha
        if number in self.held:
            tested = self.runs.get((number, pr.head_sha))
        checks: tuple[Check, ...] = ()
        if tested is not None:
            checks = (
                Check(
                    "tests",
                    pr.head_sha,
                    tested,
                    "completed",
                    "success",
                    "github-actions",
                    "https://example.com/check",
                    MERGED_AT,
                ),
            )
        return Observation(
            repo=Repository(REPO, HOST, TRUNK, ("merge", "squash", "rebase")),
            pr=pr,
            checks=checks,
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
        pr = self.current(number)
        if pr.state != "OPEN":
            raise ProviderError(
                "merge: PR is not open",
                kind="BLOCKED",
                operation="merge",
                detail="not-open",
            )
        if pr.head_sha != expected_head:
            raise ProviderError(
                "merge: head changed",
                kind="BLOCKED",
                operation="merge",
                detail="merge-head-changed",
            )
        self.land(number, method)

    def retarget_pr(
        self, number: int, base_ref: str, expected_head: str, expected_old_base: str
    ) -> PullRequest:
        self.retarget_calls.append((number, base_ref, expected_head, expected_old_base))
        if self.on_retarget is not None:
            self.on_retarget(number)
        pull = self.pulls[number]
        pr = self.current(number)
        if pr.state != "OPEN" or pr.head_sha != expected_head:
            raise ProviderError(
                "retarget: the pull request changed",
                kind="BLOCKED",
                operation="retarget",
                detail="retarget-head-changed",
            )
        if pull.base_ref == base_ref:
            return pr
        if pull.base_ref != expected_old_base:
            raise ProviderError(
                "retarget: the base changed",
                kind="BLOCKED",
                operation="retarget",
                detail="retarget-base-changed",
            )
        fault, self.retarget_fault = self.retarget_fault, "none"
        if fault == "lost":
            raise ProviderError(
                "retarget: timed out",
                kind="WAITING",
                operation="retarget",
                uncertain=True,
            )
        pull.base_ref = base_ref
        self.patches.append((number, base_ref))
        if fault == "applied_lost":
            raise ProviderError(
                "retarget: connection lost",
                kind="BLOCKED",
                operation="retarget",
                uncertain=True,
            )
        return self.current(number)

    def base_tip(self, base_ref: str) -> str:
        return self._rev(f"refs/heads/{base_ref}")

    def landing_reachable(self, landing: str, base_tip: str) -> bool:
        return is_ancestor(self.bare, landing, base_tip)

    def list_prs(
        self, state: Literal["open", "closed"], full_name: str | None = None
    ) -> tuple[PullRequest, ...]:
        if (full_name or REPO).lower() != REPO:
            return ()
        wanted = ("OPEN",) if state == "open" else ("MERGED", "CLOSED")
        listed = (self.current(number) for number in sorted(self.pulls))
        return tuple(pr for pr in listed if pr.state in wanted)

    def branch_protected(self, full_name: str, ref: str) -> bool:
        return ref == TRUNK


class GraphGit(MappedGit):
    """The invoking checkout's real Git; records every rewrite push and can lose
    its report once (``push_fault``) or let an actor race it (``before_push``).
    ``advance_fault`` once reports a definite failure after a local branch
    compare-and-swap that did apply."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.pushes: list[tuple[str, str, str]] = []
        self.push_fault: PushFault = "none"
        self.before_push: Callable[[], None] | None = None
        self.advance_fault = False

    def push_rewrite(
        self, remote: str, branch: str, new_oid: str, expected_old: str
    ) -> None:
        self.pushes.append((branch, expected_old, new_oid))
        hook, self.before_push = self.before_push, None
        if hook is not None:
            hook()
        fault, self.push_fault = self.push_fault, "none"
        if fault == "lost":
            raise GitError("the push timed out without any report", uncertain=True)
        super().push_rewrite(remote, branch, new_oid, expected_old)
        if fault == "applied_lost":
            raise GitError("the push report was lost after it applied", uncertain=True)

    def advance_local_branch(
        self, branch: str, expected_old: str, new_oid: str
    ) -> bool:
        fault, self.advance_fault = self.advance_fault, False
        advanced = super().advance_local_branch(branch, expected_old, new_oid)
        if fault:
            raise GitError("git update-ref reported a failure after the update")
        return advanced


class LifecycleClock:
    """``lifecycle``'s clock: each monitoring poll skips the rest of its window.

    A node waiting on provider evidence therefore stops WAITING after one poll
    instead of sleeping; ``interrupt`` turns the next poll into Ctrl-C.
    """

    def __init__(self) -> None:
        self.skipped = 0.0
        self.polls = 0
        self.interrupt = False

    def monotonic(self) -> float:
        return time.monotonic() + self.skipped

    def sleep(self, seconds: float) -> None:
        self.polls += 1
        if self.interrupt:
            self.interrupt = False
            raise KeyboardInterrupt
        self.skipped += 86_400.0


@dataclass
class GraphWorld:
    root: Path
    bare: Path
    work: Path
    forge: GraphForge
    git: GraphGit
    base: str

    def common(self) -> Path:
        return Path(
            git(self.work, "rev-parse", "--path-format=absolute", "--git-common-dir")
        )

    def store(self) -> Store:
        return Store(self.common())

    def remote(self, branch: str) -> str | None:
        return heads(self.bare).get(f"refs/heads/{branch}")

    def local(self, branch: str) -> str | None:
        return heads(self.work).get(f"refs/heads/{branch}")

    def write(self, parent: str, change: Change) -> str:
        """A commit of ``change`` on ``parent`` in the invoking repository."""
        return commit(self.work, self.root / "scratch.index", parent, change)

    def extend(self, ref: str, changes: list[Change]) -> str:
        """Commit ``changes`` onto local ``ref`` and publish it; returns the head."""
        tip = git(self.work, "rev-parse", "--verify", f"refs/heads/{ref}")
        for change in changes:
            tip = self.write(tip, change)
        git(self.work, "branch", "-f", ref, tip)
        git(self.work, "push", "-q", "-u", "origin", ref)
        return tip

    def open_pr(
        self, number: int, ref: str, base_ref: str, changes: list[Change]
    ) -> str:
        """Branch ``ref`` off local ``base_ref``, publish it and open PR ``number``."""
        start = git(self.work, "rev-parse", "--verify", f"refs/heads/{base_ref}")
        git(self.work, "branch", ref, start)
        head = self.extend(ref, changes)
        self.forge.register(number, ref, base_ref, f"Stack part {number}")
        return head

    def actor_push(self, branch: str, files: dict[str, str], message: str) -> str:
        """An external actor commits ``files`` on remote ``branch`` and pushes."""
        actor = self.root / "actor"
        if not actor.exists():
            git(self.root, "clone", "-q", str(self.bare), str(actor))
        git(actor, "fetch", "-q", "origin")
        git(actor, "switch", "-q", "-C", branch, f"origin/{branch}")
        for name, text in files.items():
            (actor / name).write_text(text)
        git(actor, "add", "-A")
        git(actor, "commit", "-q", "-m", message)
        git(actor, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        return git(actor, "rev-parse", "HEAD")

    def packet(
        self,
        parents: dict[int, int | None],
        selected: set[int],
        *,
        forks: dict[int, str] | None = None,
        decisions: dict[int, dict[str, object]] | None = None,
    ) -> dict[str, object]:
        """The explicit stack decision packet binding the current provider facts."""
        nodes: list[dict[str, object]] = []
        for number, parent in parents.items():
            pr = self.forge.current(number)
            row: dict[str, object] = {
                "pr": number,
                "parent": parent,
                "select": number in selected,
                "head": {"repo": REPO, "ref": pr.head_ref, "sha": pr.head_sha},
                "base": pr.base_ref,
            }
            if forks is not None and number in forks:
                row["fork"] = forks[number]
            if number in selected:
                overrides = {} if decisions is None else decisions.get(number, {})
                row["decision"] = {**DECISION, **overrides}
                row["provenance"] = dict(PROVENANCE)
            nodes.append(row)
        return {
            "schema_version": 1,
            "repository": f"{HOST}/{REPO}",
            "trunk": TRUNK,
            "nodes": nodes,
        }

    def plan(
        self,
        parents: dict[int, int | None],
        selected: set[int],
        *,
        forks: dict[int, str] | None = None,
        decisions: dict[int, dict[str, object]] | None = None,
    ) -> StackPlan:
        return parse_stack_plan(
            self.packet(parents, selected, forks=forks, decisions=decisions)
        )

    def run(
        self, plan: StackPlan, endpoint: Endpoint, *, wait: float = 120.0
    ) -> tuple[Result, int]:
        """A new graph run, exactly as ``--stack-plan`` starts one."""
        return graph.execute_graph(
            self.git, self.forge, plan, endpoint, wait, self.store()
        )

    def resume(
        self, run_id: str, endpoint: Endpoint, *, wait: float = 120.0
    ) -> tuple[Result, int]:
        """Resume graph run ``run_id`` from its journal, as ``--resume`` does."""
        store = self.store()
        journal = store.load_graph(run_id)
        plan = graph.journal_plan(journal)
        return graph.execute_graph(
            self.git, self.forge, plan, endpoint, wait, store, journal
        )

    def journal(self, run_id: str) -> GraphJournal:
        return self.store().load_graph(run_id)

    def receipt(self, run_id: str | None) -> Receipt:
        if run_id is None:
            raise AssertionError("the node has no preassigned run id")
        return self.store().load(run_id)


def build_world(tmp_path: Path) -> GraphWorld:
    """``main`` holds README.md, shared.txt and the operator's .stack-prs.yaml."""
    root = tmp_path.resolve()
    bare = root / "remote.git"
    work = root / "work"
    git(root, "init", "-q", "--bare", "-b", TRUNK, str(bare))
    work.mkdir()
    git(work, "init", "-q", "-b", TRUNK)
    git(work, "remote", "add", "origin", str(bare))
    (work / "README.md").write_text("base\n")
    (work / "shared.txt").write_text(SHARED)
    (work / ".stack-prs.yaml").write_text(STACK_POLICY)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    git(work, "push", "-q", "-u", "origin", TRUNK)
    base = git(work, "rev-parse", "HEAD")
    return GraphWorld(root, bare, work, GraphForge(bare), GraphGit(work), base)
