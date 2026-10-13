"""Consumer-visible --stack-plan selection, inspection and graph resumption.

The repository is real Git (a bare remote and clones). The provider is a small
stateful read model whose PR facts derive from the bare repository's refs; it lands
a PR only when a test squashes it, and every provider mutation fails the test. It
makes no claim about vendor behaviour. "No write" is the mode, inode, modification
time and content of every path of the inspected checkout and its Git directory.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import lifecycle
import pytest
import ship
import test_execution as execution
from github_ops import Check, GitHub, Observation, PullRequest, Repository
from graph import MAX_STACK_PLAN_BYTES, load_stack_plan, new_journal
from state_store import GraphIntent, Promotion, Receipt, Store, Target
from test_execution import HOST, MERGED_AT, REPO, MappedGit, git

isolated_git = execution.isolated_git

pytestmark = pytest.mark.skipif(os.name != "posix", reason="journals require POSIX")

GRAPH_RUN = "0123456789abcdef0123456789abcdef"
RECEIPT_RUN = "00112233445566778899aabbccddeeff"
NOW = "2026-10-13T12:00:00+00:00"
README = "base\none\ntwo\nthree\nfour\n"
DECISION: dict[str, object] = {
    "sources": ["CONTRIBUTING.md#merging"],
    "expected_checks": ["tests"],
    "merge_method": "squash",
    "post_merge_commands": [],
}
PROVENANCE: dict[str, object] = {
    "disposition": "preserve",
    "sources": ["published Stack-Id and Stack-Position trailers"],
}

Result = dict[str, object]
Rows = list[dict[str, object]]
State = dict[str, tuple[int, int, int, bytes]]


@dataclass
class Pull:
    """One modelled PR; its head and base live in the bare remote until it lands."""

    head_ref: str
    base_ref: str
    landed: tuple[str, str, str] | None = None
    native: bool = False


class StackForge(GitHub):
    """Stateful read model of stacked PRs over a bare repository."""

    def __init__(self, bare: Path) -> None:
        super().__init__(HOST, REPO)
        self.bare = bare
        self.pulls: dict[int, Pull] = {}
        self.reads: list[int] = []

    def _rev(self, ref: str) -> str:
        return git(self.bare, "rev-parse", "--verify", ref)

    def _pull(self, number: int) -> PullRequest:
        pull = self.pulls[number]
        url = f"https://{HOST}/{REPO}/pull/{number}"
        if pull.landed is None:
            return PullRequest(
                number=number,
                url=url,
                state="OPEN",
                head_sha=self._rev(f"refs/heads/{pull.head_ref}"),
                head_ref=pull.head_ref,
                head_repo=REPO,
                base_sha=self._rev(f"refs/heads/{pull.base_ref}"),
                base_ref=pull.base_ref,
                base_repo=REPO,
                merge_commit_sha=None,
                merged_at=None,
                draft=False,
                mergeable=True,
                native=pull.native,
            )
        head, base, landing = pull.landed
        return PullRequest(
            number=number,
            url=url,
            state="MERGED",
            head_sha=head,
            head_ref=pull.head_ref,
            head_repo=REPO,
            base_sha=base,
            base_ref=pull.base_ref,
            base_repo=REPO,
            merge_commit_sha=landing,
            merged_at=MERGED_AT,
            draft=False,
            mergeable=None,
            native=pull.native,
        )

    def squash(self, number: int) -> str:
        """Land ``number`` as one squash commit on its base, as a squash merge does."""
        pull = self.pulls[number]
        head = self._rev(f"refs/heads/{pull.head_ref}")
        base = self._rev(f"refs/heads/{pull.base_ref}")
        landing = git(
            self.bare, "commit-tree", f"{head}^{{tree}}", "-p", base, "-m", "squash"
        )
        git(self.bare, "update-ref", f"refs/heads/{pull.base_ref}", landing, base)
        pull.landed = (head, base, landing)
        return landing

    def read_pr(self, number: int) -> PullRequest:
        self.reads.append(number)
        return self._pull(number)

    def observe(self, number: int) -> Observation:
        pr = self._pull(number)
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

    def base_tip(self, base_ref: str) -> str:
        return self._rev(f"refs/heads/{base_ref}")

    def list_prs(
        self, state: Literal["open", "closed"], full_name: str | None = None
    ) -> tuple[PullRequest, ...]:
        wanted = "OPEN" if state == "open" else "MERGED"
        pulls = (self._pull(number) for number in sorted(self.pulls))
        return tuple(pr for pr in pulls if pr.state == wanted)

    def merge(self, number: int, expected_head: str, method: str) -> None:
        raise AssertionError(f"a merge of #{number} was dispatched")

    def retarget_pr(
        self, number: int, base_ref: str, expected_head: str, expected_old_base: str
    ) -> PullRequest:
        raise AssertionError(f"a retarget of #{number} was dispatched")


@dataclass
class Stack:
    root: Path
    bare: Path
    work: Path
    forge: StackForge

    def head(self, branch: str) -> str:
        return git(self.bare, "rev-parse", f"refs/heads/{branch}")

    def common(self) -> Path:
        return Path(
            git(self.work, "rev-parse", "--path-format=absolute", "--git-common-dir")
        )

    def store(self) -> Store:
        return Store(self.common())


def commit(work: Path, name: str, text: str, message: str) -> None:
    (work / name).write_text(text)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", message)


@pytest.fixture
def stack(tmp_path: Path) -> Stack:
    """main <- feat/a #11 <- {feat/b #12 (selected), feat/c #13 (retained)}."""
    root = tmp_path.resolve()
    bare = root / "remote.git"
    work = root / "work"
    git(root, "init", "-q", "--bare", "-b", "main", str(bare))
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    git(work, "remote", "add", "origin", str(bare))
    commit(work, "README.md", README, "base")
    git(work, "switch", "-q", "-c", "feat/a")
    commit(work, "a.txt", "alpha\n", "add a")
    git(work, "switch", "-q", "-c", "feat/b")
    (work / "b.txt").write_text("beta\n")
    commit(work, "README.md", README + "child\n", "add b\n\nStack-Position: 2\n")
    git(work, "switch", "-q", "-c", "feat/c", "feat/a")
    commit(work, "c.txt", "gamma\n", "add c")
    git(work, "switch", "-q", "main")
    git(work, "push", "-q", "origin", "main", "feat/a", "feat/b", "feat/c")
    forge = StackForge(bare)
    forge.pulls = {
        11: Pull("feat/a", "main"),
        12: Pull("feat/b", "feat/a"),
        13: Pull("feat/c", "feat/a"),
    }
    return Stack(root, bare, work, forge)


def node(
    stack: Stack, pr: int, parent: int | None, ref: str, base: str, select: bool
) -> dict[str, object]:
    row: dict[str, object] = {
        "pr": pr,
        "parent": parent,
        "select": select,
        "head": {"repo": REPO, "ref": ref, "sha": stack.head(ref)},
        "base": base,
    }
    if select:
        row["decision"] = dict(DECISION)
        row["provenance"] = dict(PROVENANCE)
    return row


def packet(stack: Stack, *, select_c: bool = False) -> dict[str, object]:
    return {
        "schema_version": 1,
        "repository": f"{HOST}/{REPO}",
        "trunk": "main",
        "nodes": [
            node(stack, 11, None, "feat/a", "main", True),
            node(stack, 12, 11, "feat/b", "feat/a", True),
            node(stack, 13, 11, "feat/c", "feat/a", select_c),
        ],
    }


def write(stack: Stack, data: object, name: str = "stack.json") -> Path:
    """The packet lives outside the repository, as an operator's file would."""
    directory = stack.root / "packets"
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(data))
    return path


def files(root: Path) -> dict[str, bytes]:
    """Every file below ``root`` with its bytes: objects, refs, index and journals."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def snapshot(*roots: Path) -> State:
    """Mode, inode, modification time and content of every path below ``roots``.

    Directories and links count too, so a created, removed or rewritten object,
    ref, index, lock, directory or journal changes it, even one replaced by an
    identical copy, and so does an existing object Git merely freshens by
    writing it again.
    """
    found: State = {}
    for root in roots:
        for path in sorted([root, *root.rglob("*")]):
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                content = path.read_bytes()
            elif stat.S_ISLNK(info.st_mode):
                content = os.fsencode(os.readlink(path))
            else:
                content = b""
            found[str(path)] = (info.st_mode, info.st_ino, info.st_mtime_ns, content)
    return found


def cli(
    stack: Stack,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
    cwd: Path | None = None,
) -> tuple[int, Result]:
    monkeypatch.chdir(cwd or stack.work)
    monkeypatch.setattr(ship, "GitRepository", MappedGit)
    monkeypatch.setattr(ship, "GitHub", lambda host, repo, deadline: stack.forge)
    monkeypatch.setattr(sys, "argv", ["ship.py", *argv])
    capsys.readouterr()
    code = ship.main()
    return code, json.loads(capsys.readouterr().out)


def rows(result: Result, key: str) -> Rows:
    return cast("Rows", result[key])


def steps(result: Result) -> list[tuple[object, object]]:
    return [(row["action"], row["pr"]) for row in rows(result, "actions")]


def other_clone(stack: Stack) -> Path:
    other = stack.root / "other"
    if not other.exists():
        git(stack.root, "clone", "-q", str(stack.bare), str(other))
    git(other, "fetch", "-q", "origin")
    return other


def push_change(stack: Stack, branch: str, name: str, text: str) -> str:
    """Someone else commits ``text`` as ``name`` on ``branch`` and publishes it."""
    other = other_clone(stack)
    git(other, "switch", "-q", "-C", branch, f"origin/{branch}")
    (other / name).write_text(text)
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", f"change {name} on {branch}")
    git(other, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    return git(other, "rev-parse", "HEAD")


def saved_graph(stack: Stack, path: Path) -> bytes:
    """A graph run journaled before any action, through the public store."""
    journal = new_journal(
        load_stack_plan(path),
        run_id=GRAPH_RUN,
        endpoint="clean",
        code_identity=lifecycle.code_identity(),
        created_at=NOW,
    )
    store = stack.store()
    store.save_graph(journal)
    return (store.graph_directory / f"{GRAPH_RUN}.json").read_bytes()


OPEN_PARENT_STEPS = [
    ("capture", 12),
    ("land", 11),
    ("cleanup", 11),
    ("promote", 12),
    ("retarget", 12),
    ("land", 12),
    ("cleanup", 12),
]


# --- selection ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        ("--pr", "12"),
        ("--branch", "feat/b"),
        ("--head-repo", "owner/repo"),
        ("--policy", "policy.json"),
        ("--plan", "plan.json"),
        ("--gates", "gates.json"),
        ("--title", "t", "--body-file", "body.md"),
        ("--inventory",),
    ],
)
def test_stack_plan_refuses_single_pr_selectors_before_any_read(
    stack: Stack,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: tuple[str, ...],
) -> None:
    path = write(stack, packet(stack))
    before = snapshot(stack.work)
    monkeypatch.chdir(stack.work)
    monkeypatch.setattr(sys, "argv", ["ship.py", "--stack-plan", str(path), *extra])

    with pytest.raises(SystemExit) as stopped:
        ship.main()

    assert stopped.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert snapshot(stack.work) == before
    assert stack.forge.reads == []


def corrupt_text(data: dict[str, object]) -> str:
    return json.dumps(data)[:-1]


def oversize(data: dict[str, object]) -> str:
    return json.dumps(data) + " " * MAX_STACK_PLAN_BYTES


def unknown_field(data: dict[str, object]) -> str:
    return json.dumps({**data, "extra": 1})


def nodes_of(data: dict[str, object]) -> Rows:
    return cast("Rows", data["nodes"])


def cycle(data: dict[str, object]) -> str:
    nodes_of(data)[0]["parent"] = 12
    nodes_of(data)[0]["base"] = "feat/b"
    return json.dumps(data)


def no_decision(data: dict[str, object]) -> str:
    del nodes_of(data)[1]["decision"]
    return json.dumps(data)


def stamped(data: dict[str, object]) -> str:
    nodes_of(data)[1]["provenance"] = {"disposition": "stamp", "sources": ["x"]}
    return json.dumps(data)


def foreign_base(data: dict[str, object]) -> str:
    nodes_of(data)[1]["base"] = "feat/elsewhere"
    return json.dumps(data)


@pytest.mark.parametrize(
    ("change", "named"),
    [
        (corrupt_text, "not valid JSON"),
        (oversize, "exceeds"),
        (unknown_field, "unknown"),
        (cycle, "cycle"),
        (no_decision, "decision and provenance"),
        (stamped, "preserve"),
        (foreign_base, "neither the trunk"),
    ],
)
def test_invalid_stack_plan_exits_2_with_a_json_diagnostic_and_no_write(
    stack: Stack,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change: Callable[[dict[str, object]], str],
    named: str,
) -> None:
    directory = stack.root / "packets"
    directory.mkdir()
    path = directory / "stack.json"
    path.write_text(change(packet(stack)))
    before = snapshot(stack.work)

    code, result = cli(stack, monkeypatch, capsys, "--stack-plan", str(path))

    assert code == 2
    assert set(result) == {"schema_version", "status", "error"}
    assert (result["schema_version"], result["status"]) == (1, "BLOCKED")
    assert named in cast(str, result["error"])
    assert snapshot(stack.work) == before
    assert stack.forge.reads == []


def test_symlinked_stack_plan_is_refused(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = write(stack, packet(stack))
    link = target.with_name("link.json")
    link.symlink_to(target)

    code, result = cli(stack, monkeypatch, capsys, "--stack-plan", str(link))

    assert (code, result["status"]) == (2, "BLOCKED")
    assert "link" in cast(str, result["error"])
    assert not (stack.common() / "armory").exists()


def test_repo_must_name_the_stack_plan_repository(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(stack, packet(stack))

    code, result = cli(
        stack, monkeypatch, capsys, "--stack-plan", str(path), "--repo", "other/repo"
    )

    assert (code, result["status"]) == (2, "BLOCKED")
    assert "--repo" in cast(str, result["error"])
    assert stack.forge.reads == []


# --- read-only inspection -------------------------------------------------------------


def test_dry_run_plans_the_graph_parent_first_and_writes_nothing(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(stack, packet(stack))
    common = stack.common()
    before = snapshot(stack.work)

    code, result = cli(
        stack, monkeypatch, capsys, "--stack-plan", str(path), "--dry-run"
    )

    assert (code, result["status"]) == (0, "PLANNED"), result
    assert result["run_id"] is None and result["mutation_performed"] is False
    assert steps(result) == OPEN_PARENT_STEPS
    capture, land = rows(result, "actions")[0], rows(result, "actions")[1]
    assert (capture["fork"], capture["old_head"], capture["proof"]) == (
        stack.head("feat/a"),
        stack.head("feat/b"),
        "strict ancestor",
    )
    assert cast("dict[str, object]", land["gate"])["status"] == "READY"
    assert rows(result, "actions")[4] == {
        "action": "retarget",
        "pr": 12,
        "from": "feat/a",
        "to": "main",
    }
    roles = {row["pr"]: row["role"] for row in rows(result, "nodes")}
    assert roles == {11: "selected", 12: "selected", 13: "retained"}
    assert rows(result, "blockers") == []
    assert snapshot(stack.work) == before
    assert not (common / "armory").exists()


def landed_parent(stack: Stack, trunk_text: str | None) -> tuple[str, str]:
    """#11 squash-lands, then optional unrelated work lands on main; the clone
    fetches them, so every object a proof needs is local."""
    landing = stack.forge.squash(11)
    tip = landing
    if trunk_text is not None:
        tip = push_change(stack, "main", "README.md", trunk_text)
    git(stack.work, "fetch", "-q", "origin")
    return landing, tip


def replayed(stack: Stack) -> tuple[str, str]:
    """#12's own commit applied by Git itself on the current main: commit and tree.

    The commit reaches the invoking clone through a scratch branch, as a promotion
    leaves it: present in the repository, not published on #12's branch.
    """
    other = other_clone(stack)
    git(other, "switch", "-q", "-C", "main", "origin/main")
    git(other, "cherry-pick", stack.head("feat/b"))
    commit = git(other, "rev-parse", "HEAD")
    git(other, "push", "-q", "origin", f"{commit}:refs/heads/scratch/replayed")
    git(stack.work, "fetch", "-q", "origin")
    return commit, git(other, "rev-parse", "HEAD^{tree}")


LANDED_PARENT_STEPS = [
    ("verify-landing", 11),
    ("cleanup", 11),
    ("promote", 12),
    ("retarget", 12),
    ("land", 12),
    ("cleanup", 12),
]


@pytest.mark.parametrize(
    "trunk_text",
    [README.replace("base", "BASE"), None],
    ids=["unrelated-trunk-change", "expected-tree-already-stored"],
)
def test_dry_run_proves_the_child_of_a_squash_landed_parent_without_any_write(
    stack: Stack,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    trunk_text: str | None,
) -> None:
    landing, tip = landed_parent(stack, trunk_text)
    _, expected_tree = replayed(stack)
    if trunk_text is None:
        # Without a trunk change the expected tree is #12's own tree, already in
        # the repository: writing it there again would only freshen the object.
        own = git(stack.work, "rev-parse", f"{stack.head('feat/b')}^{{tree}}")
        assert own == expected_tree
    path = write(stack, packet(stack))
    before = snapshot(stack.work)

    code, result = cli(
        stack, monkeypatch, capsys, "--stack-plan", str(path), "--dry-run"
    )

    assert (code, result["status"]) == (0, "PLANNED"), result
    assert steps(result) == LANDED_PARENT_STEPS
    promote = rows(result, "actions")[2]
    assert (promote["fork"], promote["old_head"], promote["landing"]) == (
        stack.head("feat/a"),
        stack.head("feat/b"),
        landing,
    )
    assert promote["onto"] == tip
    proof = cast("dict[str, object]", promote["proof"])
    assert (proof["evaluated"], proof["provable"]) == (True, True)
    assert (proof["expected_tree"], proof["commits"]) == (expected_tree, 1)
    assert "only at execution" in cast(str, proof["limits"])
    assert rows(result, "confirmed_merges") == [
        {"pr": 11, "url": f"https://{HOST}/{REPO}/pull/11", "landing": landing}
    ]
    assert rows(result, "blockers") == []
    assert snapshot(stack.work) == before


def test_dry_run_reports_a_conflicting_promotion_as_judgment_without_writes(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    landed_parent(stack, README + "trunk\n")
    path = write(stack, packet(stack))
    before = snapshot(stack.work)

    code, result = cli(
        stack, monkeypatch, capsys, "--stack-plan", str(path), "--dry-run"
    )

    assert (code, result["status"]) == (0, "PLANNED"), result
    proof = cast("dict[str, object]", rows(result, "actions")[2]["proof"])
    assert (proof["evaluated"], proof["provable"]) == (True, False)

    [blocker] = rows(result, "blockers")
    assert (blocker["status"], blocker["pr"]) == ("NEEDS_JUDGMENT", 12)

    assert snapshot(stack.work) == before


def test_dry_run_reports_configured_commit_signing_as_a_promotion_blocker(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    landed_parent(stack, None)
    git(stack.work, "config", "commit.gpgsign", "true")
    path = write(stack, packet(stack))
    before = snapshot(stack.work)

    code, result = cli(
        stack, monkeypatch, capsys, "--stack-plan", str(path), "--dry-run"
    )

    assert (code, result["status"]) == (0, "PLANNED"), result
    assert steps(result) == LANDED_PARENT_STEPS
    [blocker] = rows(result, "blockers")
    assert (blocker["status"], blocker["pr"]) == ("NEEDS_JUDGMENT", 12)

    assert snapshot(stack.work) == before


def test_dry_run_reports_a_dirty_checkout_before_any_planned_mutation(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    landed_parent(stack, None)
    (stack.work / "notes.txt").write_text("unsaved\n")
    path = write(stack, packet(stack))
    before = snapshot(stack.work)

    code, result = cli(
        stack, monkeypatch, capsys, "--stack-plan", str(path), "--dry-run"
    )

    assert (code, result["status"]) == (0, "PLANNED"), result
    [blocker] = rows(result, "blockers")
    assert (blocker["status"], blocker["pr"]) == ("NEEDS_JUDGMENT", None)

    assert (stack.work / "notes.txt").read_text() == "unsaved\n"
    assert snapshot(stack.work) == before


def test_dry_run_works_from_a_retained_linked_worktree(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    retained = stack.root / "retained"
    git(stack.work, "worktree", "add", "-q", str(retained), "feat/c")
    path = write(stack, packet(stack))
    before = snapshot(stack.work, retained)

    code, result = cli(
        stack, monkeypatch, capsys, "--stack-plan", str(path), "--dry-run", cwd=retained
    )

    assert (code, result["status"]) == (0, "PLANNED"), result
    assert steps(result) == OPEN_PARENT_STEPS
    assert cast("dict[str, object]", result["target"])["repository"] == REPO
    assert git(retained, "symbolic-ref", "--short", "HEAD") == "feat/c"
    assert snapshot(stack.work, retained) == before


# --- execution before any mutation ----------------------------------------------------


def test_moved_head_needs_judgment_before_any_journal_or_mutation(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(stack, packet(stack))
    moved = push_change(stack, "feat/b", "b.txt", "beta two\n")
    before = snapshot(stack.work)

    code, result = cli(stack, monkeypatch, capsys, "--stack-plan", str(path))

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result

    assert result["run_id"] is None and result["mutation_performed"] is False
    assert snapshot(stack.work) == before
    assert stack.head("feat/b") == moved


def test_mixed_native_and_manual_selection_is_blocked_without_any_write(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stack.forge.pulls[11].native = True
    path = write(stack, packet(stack))
    before = snapshot(stack.work)

    code, result = cli(stack, monkeypatch, capsys, "--stack-plan", str(path))

    assert (code, result["status"]) == (5, "BLOCKED"), result

    assert result["mutation_attempted"] is False
    assert snapshot(stack.work) == before


def test_pr_endpoint_only_observes_the_graph(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(stack, packet(stack))
    before = snapshot(stack.work)

    code, result = cli(
        stack, monkeypatch, capsys, "--stack-plan", str(path), "--until", "pr"
    )

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert result["run_id"] is None and result["mutation_performed"] is False
    states = {row["pr"]: row["state"] for row in rows(result, "nodes")}
    assert states == {11: "OPEN", 12: "OPEN", 13: "OPEN"}
    assert snapshot(stack.work) == before


# --- resumption -----------------------------------------------------------------------


def test_resume_dry_run_reads_the_graph_journal_without_writing(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    saved_graph(stack, write(stack, packet(stack)))
    before = snapshot(stack.work)

    code, result = cli(stack, monkeypatch, capsys, "--resume", GRAPH_RUN, "--dry-run")

    assert (code, result["status"]) == (0, "PLANNED"), result
    assert result["run_id"] == GRAPH_RUN
    assert cast("dict[str, object]", result["target"])["kind"] == "stack"
    assert steps(result) == OPEN_PARENT_STEPS
    assert snapshot(stack.work) == before


def test_unique_resume_selects_the_graph_run_of_the_packet(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(stack, packet(stack))
    saved_graph(stack, path)

    code, result = cli(
        stack, monkeypatch, capsys, "--stack-plan", str(path), "--resume", "--dry-run"
    )

    assert (code, result["status"]) == (0, "PLANNED"), result
    assert result["run_id"] == GRAPH_RUN


def test_resume_refuses_a_packet_with_another_topology(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    journal = saved_graph(stack, write(stack, packet(stack)))
    widened = write(stack, packet(stack, select_c=True), "widened.json")
    before = snapshot(stack.work)

    code, result = cli(
        stack, monkeypatch, capsys, "--resume", GRAPH_RUN, "--stack-plan", str(widened)
    )

    assert (code, result["status"]) == (2, "BLOCKED"), result
    assert "node #13 select changed" in cast(str, result["error"])
    assert snapshot(stack.work) == before
    assert (stack.store().graph_directory / f"{GRAPH_RUN}.json").read_bytes() == journal
    assert stack.forge.reads == []


def test_resume_accepts_a_refreshed_decision_of_the_same_topology(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    saved_graph(stack, write(stack, packet(stack)))
    refreshed = packet(stack)
    for row in nodes_of(refreshed)[:2]:
        row["decision"] = {**DECISION, "sources": ["ci/required-checks.md"]}
    path = write(stack, refreshed, "refreshed.json")

    code, result = cli(
        stack,
        monkeypatch,
        capsys,
        "--resume",
        GRAPH_RUN,
        "--stack-plan",
        str(path),
        "--dry-run",
    )

    assert (code, result["status"]) == (0, "PLANNED"), result
    assert result["run_id"] == GRAPH_RUN
    assert steps(result) == OPEN_PARENT_STEPS


def test_resume_keeps_the_saved_endpoint_without_writing(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    saved_graph(stack, write(stack, packet(stack)))
    before = snapshot(stack.work)

    code, result = cli(
        stack, monkeypatch, capsys, "--resume", GRAPH_RUN, "--until", "merged"
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert result["run_id"] == GRAPH_RUN
    assert snapshot(stack.work) == before


def test_resumed_graph_records_an_external_head_move_without_mutation(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    saved_graph(stack, write(stack, packet(stack)))
    push_change(stack, "feat/b", "b.txt", "beta two\n")

    code, result = cli(stack, monkeypatch, capsys, "--resume", GRAPH_RUN)

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert result["mutation_attempted"] is False
    store = stack.store()
    journal = store.load_graph(GRAPH_RUN)
    assert journal.status == "NEEDS_JUDGMENT"
    assert "#12 head moved outside the controller" in cast(str, journal.issue)
    assert journal.intents == []
    assert [row.run_id for row in journal.nodes] == [None, None, None]
    assert store.list_runs() == ()


def unsafe_graph_directory(stack: Stack) -> Path:
    """A graph journal directory another account could write to."""
    graphs = stack.store().graph_directory
    graphs.mkdir(parents=True, exist_ok=True)
    graphs.chmod(0o777)
    return graphs


@pytest.mark.parametrize("graphs", ["absent", "unsafe"])
def test_receipt_run_id_still_resumes_through_the_single_pr_path(
    stack: Stack,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    graphs: str,
) -> None:
    store = stack.store()
    store.save(
        Receipt(
            run_id=RECEIPT_RUN,
            endpoint="clean",
            code_identity=lifecycle.code_identity(),
            policy_identity=None,
            inventory_identity="f" * 64,
            target=Target(
                host=HOST,
                repo=REPO,
                number=11,
                head_sha=stack.head("feat/a"),
                base_sha=stack.head("main"),
                head_ref="feat/a",
                head_repo=REPO,
                base_ref="main",
            ),
        )
    )
    if graphs == "unsafe":
        # A graph journal problem concerns only graph resumption.
        unsafe_graph_directory(stack)
    before = snapshot(stack.work)

    code, result = cli(stack, monkeypatch, capsys, "--resume", RECEIPT_RUN, "--dry-run")

    assert (code, result["status"]) == (0, "PLANNED"), result
    assert result["target"] == {"repository": REPO, "pr": 11, "endpoint": "clean"}
    assert snapshot(stack.work) == before


def test_unknown_run_id_keeps_the_single_pr_diagnostic(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = snapshot(stack.work)

    code, result = cli(stack, monkeypatch, capsys, "--resume", GRAPH_RUN, "--dry-run")

    assert code == 2
    assert result == {
        "schema_version": 1,
        "status": "BLOCKED",
        "error": "missing receipt: provide --pr, --repo and --until to reconstruct "
        "scope",
    }
    assert snapshot(stack.work) == before
    assert stack.forge.reads == []


def test_unsafe_graph_directory_blocks_a_graph_resumption(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    unsafe_graph_directory(stack)
    before = snapshot(stack.work)

    code, result = cli(stack, monkeypatch, capsys, "--resume", GRAPH_RUN, "--dry-run")

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert "writable by another account" in cast(str, result["error"])
    assert snapshot(stack.work) == before
    assert stack.forge.reads == []


def test_failed_first_journal_save_names_no_run_and_dispatches_nothing(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    graphs = unsafe_graph_directory(stack)
    path = write(stack, packet(stack))
    heads = {branch: stack.head(branch) for branch in ("main", "feat/a", "feat/b")}

    code, result = cli(stack, monkeypatch, capsys, "--stack-plan", str(path))

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert result["run_id"] is None

    assert list(graphs.iterdir()) == []
    assert result["mutation_attempted"] is False
    assert {branch: stack.head(branch) for branch in heads} == heads


def pending_push_graph(
    stack: Stack, path: Path, landing: str, replay: tuple[str, str]
) -> tuple[str, str]:
    """A graph run whose rewrite push of #12 was dispatched with an unknown outcome.

    #12's fork was captured at #11's head and its slice proved and replayed onto
    ``landing``; returns the old and the new head of #12.
    """
    new, tree = replay
    fork, old = stack.head("feat/a"), stack.head("feat/b")
    journal = new_journal(
        load_stack_plan(path),
        run_id=GRAPH_RUN,
        endpoint="clean",
        code_identity=lifecycle.code_identity(),
        created_at=NOW,
    )
    row = journal.node(12)
    row.fork, row.old_head, row.captured_at = fork, old, NOW
    row.promotion = Promotion(
        fork=fork,
        old_head=old,
        landing=landing,
        expected_tree=tree,
        new_head=new,
        commits=1,
        slice_identity=None,
        verified=True,
    )
    row.state = "PROMOTED"
    journal.intents = [
        GraphIntent(
            key="1",
            kind="capture",
            pr=12,
            resource="pull/12",
            expected_old=old,
            new=fork,
            created_at=NOW,
            outcome="CONFIRMED",
            actual=fork,
        ),
        GraphIntent(
            key="2",
            kind="rewrite-push",
            pr=12,
            resource="refs/heads/feat/b",
            expected_old=old,
            new=new,
            created_at=NOW,
        ),
    ]
    stack.store().save_graph(journal)
    return old, new


@pytest.mark.parametrize("remote", ["applied", "not-applied", "foreign"])
def test_resume_dry_run_classifies_a_pending_push_without_recording_it(
    stack: Stack,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    remote: str,
) -> None:
    landing, _ = landed_parent(stack, None)
    replay = replayed(stack)
    old, new = pending_push_graph(stack, write(stack, packet(stack)), landing, replay)
    observed = old
    if remote == "applied":
        observed = new
        other = other_clone(stack)
        git(other, "push", "-q", "-f", "origin", f"{new}:refs/heads/feat/b")
    elif remote == "foreign":
        observed = push_change(stack, "feat/b", "b.txt", "beta elsewhere\n")
    before = snapshot(stack.work)

    code, result = cli(stack, monkeypatch, capsys, "--resume", GRAPH_RUN, "--dry-run")

    assert (code, result["status"]) == (0, "PLANNED"), result
    assert result["run_id"] == GRAPH_RUN
    assert snapshot(stack.work) == before
    planned = rows(result, "actions")
    if remote == "foreign":
        assert "reconcile" not in [row["action"] for row in planned]
        blocker = rows(result, "blockers")[0]
        assert (blocker["status"], blocker["pr"]) == ("NEEDS_JUDGMENT", 12)

        return
    assert rows(result, "blockers") == []
    outcome = "CONFIRMED" if remote == "applied" else "REJECTED"
    assert planned[0] == {
        "action": "reconcile",
        "pr": 12,
        "intent": "2",
        "kind": "rewrite-push",
        "expected_old": old,
        "new": new,
        "observed": observed,
        "outcome": outcome,
    }
    if remote == "applied":
        # The published promotion is adopted: no second proof or push is planned.
        assert steps(result)[1:] == [
            ("verify-landing", 11),
            ("cleanup", 11),
            ("retarget", 12),
            ("land", 12),
            ("cleanup", 12),
        ]
        return
    assert steps(result)[1:] == LANDED_PARENT_STEPS
    proof = cast("dict[str, object]", planned[3]["proof"])
    assert (proof["provable"], proof["expected_tree"]) == (True, replay[1])
