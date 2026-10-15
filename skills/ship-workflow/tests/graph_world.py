"""A real Git universe for manual stack-graph execution regressions.

A bare repository is the remote, one clone is the invoking checkout and another
clone plays an external actor. :class:`GraphForge` models many pull requests over
the bare repository: open heads and bases are its refs, it lands PRs with real
squash, merge or rebase commits, keeps ``refs/pull/N/head`` and injects the
provider faults a graph run must reconcile. :class:`NativeStackForge` adds
GitHub-native stacks over the same bare repository: stack listings, the trunk
merge policy and ``merge-async`` requests with the prefix, guard, queue-option
and in-progress semantics observed on GitHub and a modelled request expiry,
landing each member with real Git commits and rebasing the open members above
the landed prefix. Both are behavioural models for transition and error coverage
only, not evidence of vendor behaviour.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import graph
from changeset import GatePolicy
from git_ops import GitError
from github_ops import (
    Check,
    GitHub,
    NativeMergeInProgress,
    NativeMergeResult,
    NativeStack,
    NativeTrunkPolicy,
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
PutFault = Literal["none", "lost", "applied_lost"]
RebaseFault = Literal["none", "drift", "extra", "lag", "retarget", "lowest"]
PROVIDER_AUTHOR = ("Provider", "provider@example.invalid", "@1700000200 +0000")
QUEUE_REFUSAL = (
    "Custom merge params (merge_method, commit_title, commit_message) are not "
    "supported with the merge_queue merge action"
)


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

    def observe(self, number: int, *, assurance: str = "routine") -> Observation:
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
            assurance=assurance,
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


@dataclass
class AsyncRequest:
    """One modelled ``merge-async`` request: its options, prefix and progress."""

    uuid: str
    action: str
    method: str | None
    expected_head: str
    prefix: tuple[int, ...]
    status: str = "pending"
    message: str = "Merge request accepted"
    sha: str | None = None
    landed: int = 0


class NativeStackForge(GraphForge):
    """GraphForge whose ``stacks`` (number -> PRs bottom to top) are native stacks.

    ``start_native_merge`` merges the open prefix ending at the requested PR; its
    ``sha`` guards only that PR's head. A queue trunk refuses a request carrying
    a method (422) and keeps a request ``enqueued`` while each :meth:`tick` lands
    one member as its own merge group; a direct request lands the whole prefix on
    the next tick and reports ``merged``. Every landed member keeps its review
    base. Once a prefix landed, :meth:`rebase_open` rebases the open members
    above it. ``auto_tick`` ticks on every request status read; ``expired`` makes
    every status read a 404. ``echo_fault`` answers a new request with another
    method; ``immediate`` answers it ``enqueued`` without an id (it is still
    queued). An ordinary merge of a native member is logged in ``merge_calls``
    and fails the test. ``puts`` logs every request sent; ``existing`` models a
    request someone else sent.
    """

    def __init__(self, bare: Path) -> None:
        super().__init__(bare)
        self.stacks: dict[int, list[int]] = {}
        self.unknown: set[int] = set()
        self.queue = False
        self.queue_method = "squash"
        self.methods: tuple[str, ...] = ("merge", "squash", "rebase")
        self.policy_known = True
        self.puts: list[tuple[int, str, str | None, str]] = []
        self.requests: list[AsyncRequest] = []
        self.put_fault: PutFault = "none"
        self.before_put: Callable[[], None] | None = None
        self.auto_tick = True
        self.expired = False
        self.fail_after: int | None = None
        self.fail_message = "Merge conflict detected in the merge group"
        self.landing_fault: dict[int, dict[str, str]] = {}
        self.rebase_fault: RebaseFault = "none"
        self.rebased: dict[int, str] = {}
        self.echo_fault = False
        self.immediate = False

    def _stack_of(self, number: int) -> tuple[int, list[int]] | None:
        for stack, order in self.stacks.items():
            if number in order:
                return stack, order
        return None

    def current(self, number: int) -> PullRequest:
        pr = super().current(number)
        found = self._stack_of(number)
        if found is None:
            return pr
        if number in self.unknown:
            return replace(pr, native=True)
        stack, order = found
        return replace(
            pr,
            native=True,
            native_stack_number=stack,
            native_stack_position=order.index(number) + 1,
            native_stack_size=len(order),
            native_stack_base=TRUNK,
        )

    def merge(self, number: int, expected_head: str, method: str) -> None:
        if self._stack_of(number) is not None:
            self.merge_calls.append((number, expected_head, method))
            raise AssertionError(f"native member #{number} reached the ordinary merge")
        super().merge(number, expected_head, method)

    def read_native_stack(self, number: int) -> NativeStack:
        order = self.stacks.get(number)
        if order is None:
            raise ProviderError(
                f"native-stack:{REPO}#{number}: no such stack",
                kind="BLOCKED",
                operation="native-stack",
                http_status=404,
                detail="native-stack-unknown",
            )
        return NativeStack(number, TRUNK, tuple(self.current(n) for n in order))

    def native_trunk_policy(self, stack: NativeStack) -> NativeTrunkPolicy:
        if not self.policy_known:
            return NativeTrunkPolicy(
                TRUNK, None, (), False, ("rules-unavailable: main rulesets unreadable",)
            )
        if self.queue:
            return NativeTrunkPolicy(
                TRUNK, "merge_queue", (self.queue_method,), True, ()
            )
        return NativeTrunkPolicy(TRUNK, "direct_merge", self.methods, True, ())

    def _answer(self, request: AsyncRequest) -> NativeMergeResult:
        return NativeMergeResult(
            status=request.status,
            uuid=request.uuid,
            message=request.message,
            sha=request.sha,
            expected_head_sha=request.expected_head,
            merge_action=request.action,
            merge_method=request.method or "default",
            bypass_rules=False,
        )

    def existing(
        self, number: int, head: str, method: str | None, action: str
    ) -> AsyncRequest:
        """A request for ``number`` that another actor already sent."""
        return self._request(number, head, method, action)

    def _request(
        self, number: int, head: str, method: str | None, action: str
    ) -> AsyncRequest:
        found = self._stack_of(number)
        if found is None:
            raise AssertionError(f"#{number} is not a native member")
        order = found[1]
        prefix = tuple(
            n for n in order[: order.index(number) + 1] if self.pulls[n].state == "OPEN"
        )
        request = AsyncRequest(
            f"00000000-0000-4000-8000-{len(self.requests) + 1:012d}",
            action,
            method,
            head,
            prefix,
        )
        self.requests.append(request)
        return request

    def start_native_merge(
        self, number: int, expected_head: str, method: str | None, action: str
    ) -> NativeMergeResult:
        self.puts.append((number, expected_head, method, action))
        hook, self.before_put = self.before_put, None
        if hook is not None:
            hook()
        op = f"native-merge:{REPO}#{number}"
        active = [
            request
            for request in self.requests
            if request.prefix[-1] == number
            and request.status in ("pending", "enqueued")
        ]
        if active:
            raise NativeMergeInProgress(
                f"{op}: an async merge request is already in progress",
                operation=op,
                existing=self._answer(active[-1]),
            )
        refusal: str | None = None
        if self.current(number).state != "OPEN":
            refusal = "the pull request is not open"
        elif action == "merge_queue" and method is not None:
            refusal = QUEUE_REFUSAL
        elif (action == "merge_queue") != self.queue:
            refusal = "the merge action does not match the base branch rules"
        if refusal is not None:
            raise ProviderError(
                f"{op}: HTTP 422 GitHub refused the async merge: {refusal}",
                kind="BLOCKED",
                operation=op,
                http_status=422,
                detail="native-merge-rejected",
            )
        if self.current(number).head_sha != expected_head:
            raise ProviderError(
                f"{op}: GitHub refused the async merge: the pull request head no "
                "longer matches the expected head; nothing was merged",
                kind="WAITING",
                operation=op,
                http_status=422,
                detail="native-merge-head-changed",
            )
        fault, self.put_fault = self.put_fault, "none"
        if fault == "lost":
            raise ProviderError(
                f"{op}: gh did not finish; do not retry it",
                kind="WAITING",
                operation=op,
                uncertain=True,
                detail="native-merge-uncertain-timeout",
            )
        request = self._request(number, expected_head, method, action)
        if fault == "applied_lost":
            raise ProviderError(
                f"{op}: the connection was lost; do not retry it",
                kind="WAITING",
                operation=op,
                uncertain=True,
                detail="native-merge-uncertain-transport",
            )
        if self.immediate:
            return NativeMergeResult("enqueued", None, "Already queued", None, None)
        if self.echo_fault:
            return replace(self._answer(request), merge_method="rebase")
        return self._answer(request)

    def read_native_merge(self, number: int, uuid: str) -> NativeMergeResult:
        if self.auto_tick:
            self.tick()
        found = [
            request
            for request in self.requests
            if request.uuid == uuid and request.prefix[-1] == number
        ]
        if not found or self.expired:
            op = f"native-merge-status:{REPO}#{number}"
            raise ProviderError(
                f"{op}: GitHub does not know async merge request {uuid}",
                kind="BLOCKED",
                operation=op,
                http_status=404,
                detail="native-merge-request-unknown",
            )
        return self._answer(found[0])

    def tick(self) -> None:
        """One background step of the oldest unfinished request."""
        for request in self.requests:
            unfinished = request.landed < len(request.prefix)
            if unfinished and request.status in ("pending", "enqueued"):
                self._advance(request)
                return

    def _advance(self, request: AsyncRequest) -> None:
        if self.queue and request.status == "pending":
            request.status = "enqueued"
            return
        count = 1 if self.queue else len(request.prefix) - request.landed
        for number in request.prefix[request.landed : request.landed + count]:
            if self.fail_after is not None and request.landed >= self.fail_after:
                request.status, request.message = "failed", self.fail_message
                return
            self._land_member(number, request.method or self.queue_method)
            request.landed += 1
        if request.landed == len(request.prefix):
            if not self.queue:
                request.status = "merged"
                request.sha = self.landing(request.prefix[-1])
            self.rebase_open(request.prefix[-1])

    def _commit_on(self, parent: str, files: dict[str, str], message: str) -> str:
        index = self.bare.parent / "provider.index"
        change = Change(files, message.encode(), PROVIDER_AUTHOR)
        return commit(self.bare, index, parent, change)

    def _land_member(self, number: int, method: str) -> None:
        """Land member ``number``'s own slice on the trunk; it keeps its review base."""
        pull = self.pulls[number]
        head = self._rev(f"refs/heads/{pull.head_ref}")
        review = self._rev(f"refs/heads/{pull.base_ref}")
        below = None if pull.base_ref == TRUNK else review
        tip = self._rev(f"refs/heads/{TRUNK}")
        message = f"{pull.title} (#{number})"
        if method == "rebase":
            landing = tip
            listing = git(self.bare, "rev-list", "--reverse", f"{review}..{head}")
            for oid in listing.splitlines():
                landing = self._replay(oid, landing)
        else:
            tree = self._merge_tree(tip, head, base=below)
            parents = ("-p", tip, "-p", head) if method == "merge" else ("-p", tip)
            landing = git(self.bare, "commit-tree", tree, *parents, "-m", message)
        fault = self.landing_fault.get(number)
        if fault is not None:
            tampered = self._commit_on(landing, fault, "tampered")
            tree = git(self.bare, "rev-parse", f"{tampered}^{{tree}}")
            landing = git(self.bare, "commit-tree", tree, "-p", tip, "-m", message)
        git(self.bare, "update-ref", f"refs/heads/{TRUNK}", landing, tip)
        self._publish_head(number, head)
        pull.state, pull.landed = "MERGED", (head, review, landing)

    def rebase_open(self, selected: int) -> None:
        """Rebase the open members above landed ``selected``, as ``rebase_fault`` says.

        Each is replayed commit by commit with real Git: the lowest onto the trunk
        tip, then retargeted to the trunk, and each higher one onto the new head
        of the member below it; ``rebased`` records every head written. ``drift``
        and ``extra`` add a commit to the lowest one; ``lag`` leaves them all,
        ``retarget`` only retargets the lowest and ``lowest`` rebases only it.
        """
        found = self._stack_of(selected)
        if found is None or self.rebase_fault == "lag":
            return
        order = found[1]
        above = order[order.index(selected) + 1 :]
        if not above or self.pulls[above[0]].state != "OPEN":
            return
        if self.rebase_fault == "retarget":
            self.pulls[above[0]].base_ref = TRUNK
            return
        fork = self.landed_head(selected)
        onto = self._rev(f"refs/heads/{TRUNK}")
        for position, number in enumerate(above):
            pull = self.pulls[number]
            if pull.state != "OPEN" or (position and self.rebase_fault == "lowest"):
                return
            old = self._rev(f"refs/heads/{pull.head_ref}")
            rebased = onto
            listing = git(self.bare, "rev-list", "--reverse", f"{fork}..{old}")
            for oid in listing.splitlines():
                rebased = self._replay(oid, rebased)
            if not position and self.rebase_fault == "drift":
                rebased = self._commit_on(rebased, {"top.txt": "drifted\n"}, "drift")
            elif not position and self.rebase_fault == "extra":
                rebased = self._commit_on(rebased, {"extra.txt": "extra\n"}, "extra")
            git(self.bare, "update-ref", f"refs/heads/{pull.head_ref}", rebased, old)
            self._publish_head(number, rebased)
            self.rebased[number] = rebased
            if not position:
                pull.base_ref = TRUNK
            fork, onto = old, rebased

    def landed_head(self, number: int) -> str:
        landed = self.pulls[number].landed
        if landed is None:
            raise AssertionError(f"#{number} has not landed")
        return landed[0]


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
        self,
        plan: StackPlan,
        endpoint: Endpoint,
        *,
        wait: float = 120.0,
        gates: GatePolicy | None = None,
    ) -> tuple[Result, int]:
        """A new graph run, exactly as ``--stack-plan`` starts one."""
        return graph.execute_graph(
            self.git, self.forge, plan, endpoint, wait, self.store(), gates=gates
        )

    def resume(
        self,
        run_id: str,
        endpoint: Endpoint,
        *,
        wait: float = 120.0,
        gates: GatePolicy | None = None,
    ) -> tuple[Result, int]:
        """Resume graph run ``run_id`` from its journal, as ``--resume`` does."""
        store = self.store()
        journal = store.load_graph(run_id)
        plan = graph.journal_plan(journal)
        return graph.execute_graph(
            self.git, self.forge, plan, endpoint, wait, store, journal, gates=gates
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
