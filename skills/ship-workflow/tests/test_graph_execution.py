"""Consumer-visible manual stack-graph execution against real Git.

The repository is real Git: a bare remote, the invoking clone and an external
actor's clone. ``graph_world.GraphForge`` is a stateful multi-PR provider model
that lands PRs with real commits and injects provider faults; it makes no claim
about vendor behaviour. Lifecycle monitoring polls skip their window, so a node
waiting on provider evidence stops WAITING at once instead of sleeping. Each test
asserts the resulting refs, trees, commits, PR states, journal and receipts, the
status and exit code, and what stayed untouched.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

import lifecycle
import pytest
import test_execution as execution
from graph import inspect_graph, journal_plan
from graph_world import (
    STACK_POLICY,
    Change,
    GraphWorld,
    LifecycleClock,
    Result,
    build_world,
    messages,
    tree_files,
)
from lifecycle import Endpoint
from state_store import GraphIntent, GraphJournal, Promotion, Receipt, ReceiptInputError
from test_cli_stack_plan import snapshot
from test_execution import REPO, git, heads
from test_graph_git import (
    FIRST_AUTHOR,
    FIRST_AUTHOR_LINE,
    PARENT_AUTHOR,
    SECOND_AUTHOR,
    commit_parts,
    edit_line,
    git_bytes,
)

isolated_git = execution.isolated_git

pytestmark = pytest.mark.skipif(os.name != "posix", reason="journals require POSIX")

PARENT_SHARED = edit_line(1, "line 1 parent")
CHILD_SHARED = edit_line(5, "line 5 child", PARENT_SHARED)
PARENT_MESSAGE = b"parent: add work\n\nStack-Id: stack-7\nStack-Position: 1\n"
FIRST_MESSAGE = b"child: edit line five\n\nStack-Id: stack-7\nStack-Position: 2\n"
# No trailing newline: the replay must keep the published message byte-for-byte.
SECOND_MESSAGE = b"child: add second file\n\nStack-Id: stack-7\nStack-Position: 2"
PARENT = Change(
    {"shared.txt": PARENT_SHARED, "parent.txt": "parent work\n"},
    PARENT_MESSAGE,
    PARENT_AUTHOR,
)
CHILD = [
    Change(
        {"shared.txt": CHILD_SHARED, "child.txt": "child one\n"},
        FIRST_MESSAGE,
        FIRST_AUTHOR,
    ),
    Change({"child2.txt": "child two\n"}, SECOND_MESSAGE, SECOND_AUTHOR),
]
FOLLOW_UP = Change(
    {"parent.txt": "parent work\nparent follow-up\n"},
    b"parent: follow up\n",
    PARENT_AUTHOR,
)
SIBLING = Change(
    {"sibling.txt": "sibling\n"},
    b"sibling: add file\n\nStack-Id: stack-7\nStack-Position: 2\n",
    SECOND_AUTHOR,
)
RETAINED = Change({"retained.txt": "retained\n"}, b"retained: add\n", SECOND_AUTHOR)
GRANDCHILD = Change(
    {
        "shared.txt": edit_line(9, "line 9 grandchild", CHILD_SHARED),
        "grandchild.txt": "grandchild\n",
    },
    b"grandchild: edit line nine\n\nStack-Id: stack-7\nStack-Position: 3\n",
    FIRST_AUTHOR,
)
LANDED = {
    ".stack-prs.yaml": STACK_POLICY,
    "README.md": "base\n",
    "shared.txt": CHILD_SHARED,
    "parent.txt": "parent work\n",
    "child.txt": "child one\n",
    "child2.txt": "child two\n",
}
PAIR: dict[int, int | None] = {11: None, 12: 11}
WAITING_CI = "expected jobs have not produced current evidence"


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> LifecycleClock:
    """No real sleeps: every lifecycle monitoring poll ends its window."""
    monkeypatch.setattr(lifecycle, "POLL_INTERVAL", 0.0)
    skipping = LifecycleClock()
    monkeypatch.setattr(lifecycle, "time", skipping)
    return skipping


@pytest.fixture
def world(tmp_path: Path) -> GraphWorld:
    return build_world(tmp_path)


def run_id(result: Result) -> str:
    return cast(str, result["run_id"])


def rows(result: Result, key: str) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", result[key])


def outcomes(journal: GraphJournal) -> list[tuple[str, int, str]]:
    return [(intent.kind, intent.pr, intent.outcome) for intent in journal.intents]


def promotion(journal: GraphJournal, number: int) -> Promotion:
    found = journal.node(number).promotion
    assert found is not None, f"#{number} has no journaled promotion"
    return found


def parent_and_child(world: GraphWorld) -> tuple[str, str]:
    """#11 ``stack/p`` on main and its two-commit child #12 ``stack/c``."""
    parent = world.open_pr(11, "stack/p", "main", [PARENT])
    child = world.open_pr(12, "stack/c", "stack/p", CHILD)
    return parent, child


def mutations(world: GraphWorld) -> tuple[object, ...]:
    """Every provider mutation request and rewrite push dispatched so far."""
    return (
        list(world.forge.merge_calls),
        list(world.forge.retarget_calls),
        list(world.forge.patches),
        list(world.git.pushes),
    )


def stamp(path: Path) -> tuple[bytes, int, int]:
    info = path.stat()
    return path.read_bytes(), info.st_mtime_ns, info.st_ino


def state(directory: Path) -> dict[str, tuple[bytes, int, int]]:
    """Bytes, modification time and inode of every file below ``directory``."""
    return {
        str(path.relative_to(directory)): stamp(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def deletions(receipt: Receipt) -> list[str]:
    """When each ref deletion of a node's cleanup was journaled."""
    return [
        str(operation["created_at"])
        for operation in receipt.intents
        if operation["kind"] in ("delete_local", "delete_remote")
    ]


def marked(marker: Path) -> list[str]:
    """The checkout head recorded by each post-merge command run."""
    return [line.split("\t")[0] for line in marker.read_text().splitlines()]


# -- promotion after a landed parent ---------------------------------------------------


@pytest.mark.parametrize("method", ["squash", "merge", "rebase"])
def test_child_of_a_landed_parent_is_promoted_retargeted_and_landed(
    world: GraphWorld, method: str
) -> None:
    parent, child = parent_and_child(world)
    landing = world.forge.land(11, method)

    result, code = world.run(world.plan(PAIR, {11, 12}), "merged")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    journal = world.journal(run_id(result))
    proof = promotion(journal, 12)
    new = proof.new_head
    assert (proof.fork, proof.old_head, proof.landing) == (parent, child, landing)
    assert proof.commits == 2
    # Published once under the exact expected-old lease, then retargeted once.
    assert world.git.pushes == [("stack/c", child, new)]
    assert world.remote("stack/c") == new
    assert world.forge.patches == [(12, "main")]
    assert world.forge.current(12).base_ref == "main"
    assert world.forge.merge_calls == [(12, new, "squash")]
    # Gates were only ever evaluated for the promoted head on its new base.
    assert set(world.forge.contexts) == {(12, new, landing)}
    receipt = world.receipt(journal.node(12).run_id)
    assert (receipt.head_sha, receipt.base_sha) == (new, landing)
    assert receipt.base_ref == "main"
    final = world.forge.landing(12)
    assert git(world.bare, "rev-parse", f"{final}^") == landing
    assert tree_files(world.bare, final) == LANDED
    assert git(world.bare, "rev-parse", f"{new}^{{tree}}") == proof.expected_tree
    # The landed parent and its branches are untouched: `merged` deletes nothing.
    assert world.remote("stack/p") == world.local("stack/p") == parent
    assert world.local("stack/c") == new
    assert outcomes(journal) == [
        ("capture", 12, "CONFIRMED"),
        ("rewrite-push", 12, "CONFIRMED"),
        ("advance-local", 12, "CONFIRMED"),
        ("retarget", 12, "CONFIRMED"),
    ]
    assert journal.status == "COMPLETE"
    merges = {row["pr"]: row["landing"] for row in rows(result, "confirmed_merges")}
    assert merges == {11: landing, 12: final}


def test_promoted_child_holds_exactly_its_own_commits_and_trailers(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)
    landing = world.forge.land(11, "squash")

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    new = world.remote("stack/c")
    assert new is not None
    original = git(world.bare, "rev-list", "--reverse", f"{parent}..{child}")
    replayed = git(world.bare, "rev-list", "--reverse", f"{landing}..{new}")
    assert len(replayed.splitlines()) == len(original.splitlines()) == 2
    assert git(world.bare, "rev-list", "--merges", f"{landing}..{new}") == ""
    parts = [commit_parts(world.bare, oid) for oid in replayed.splitlines()]
    assert parts == [commit_parts(world.bare, oid) for oid in original.splitlines()]
    assert parts[0][0] == FIRST_AUTHOR_LINE
    assert parts[1][1] == SECOND_MESSAGE
    # The net change is the child's own; the squash-landed parent is not re-added.
    own = git(world.bare, "diff", parent, child)
    assert git(world.bare, "diff", landing, new) == own
    for oid in replayed.splitlines():
        touched = git(world.bare, "show", "--name-only", "--format=", oid)
        assert "parent.txt" not in touched.splitlines()
    span = f"{world.base}..{world.forge.landing(12)}"
    history = git(world.bare, "log", "--format=%H", span, "--", "parent.txt")
    assert history.splitlines() == [landing]


def test_unrelated_trunk_changes_survive_the_three_way_promotion(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)
    world.forge.land(11, "squash")
    trunk_shared = edit_line(9, "line 9 trunk", PARENT_SHARED)
    tip = world.actor_push(
        "main",
        {"shared.txt": trunk_shared, "trunk.txt": "trunk\n"},
        "trunk: later change",
    )

    result, code = world.run(world.plan(PAIR, {12}), "clean")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    proof = promotion(world.journal(run_id(result)), 12)
    assert (proof.fork, proof.old_head, proof.landing) == (parent, child, tip)
    expected = {
        **LANDED,
        "shared.txt": edit_line(5, "line 5 child", trunk_shared),
        "trunk.txt": "trunk\n",
    }
    assert tree_files(world.bare, proof.new_head) == expected
    assert tree_files(world.bare, world.forge.landing(12)) == expected
    # The child's blob is not reproduced literally: the three-way tree is the proof.
    promoted = git(world.bare, "rev-parse", f"{proof.new_head}:shared.txt")
    assert promoted != git(world.bare, "rev-parse", f"{child}:shared.txt")
    # Only the landed child's proven-stale refs went; the unselected parent's stay.
    assert set(heads(world.bare)) == {"refs/heads/main", "refs/heads/stack/p"}
    assert set(heads(world.work)) == {"refs/heads/main", "refs/heads/stack/p"}
    assert world.remote("stack/p") == world.local("stack/p") == parent


def test_overlapping_trunk_change_needs_judgment_before_any_publication(
    world: GraphWorld,
) -> None:
    _, child = parent_and_child(world)
    world.forge.land(11, "squash")
    clash = edit_line(5, "line 5 trunk", PARENT_SHARED)
    tip = world.actor_push("main", {"shared.txt": clash}, "trunk: rewrite line five")

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert world.git.pushes == []
    assert world.forge.retarget_calls == [] and world.forge.merge_calls == []
    assert world.remote("stack/c") == world.local("stack/c") == child
    assert world.forge.current(12).base_ref == "stack/p"
    assert world.remote("main") == tip
    journal = world.journal(run_id(result))
    assert outcomes(journal) == [("capture", 12, "CONFIRMED")]
    assert journal.node(12).promotion is None
    assert journal.status == "NEEDS_JUDGMENT"


@pytest.mark.parametrize(
    ("stale", "reason"),
    [
        ("head", WAITING_CI),
        ("base", "current tested base association is missing or stale"),
    ],
)
def test_green_checks_of_the_old_context_are_never_transplanted(
    world: GraphWorld, stale: str, reason: str
) -> None:
    _, child = parent_and_child(world)
    landing = world.forge.land(11, "squash")
    world.forge.held.add(12)
    world.forge.report_ci(12)  # green for the old head on the old base
    if stale == "base":
        # CI reran on the promoted head while its base was still the parent branch.
        world.forge.on_retarget = world.forge.report_ci

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (3, "WAITING"), result

    new = world.remote("stack/c")
    assert new is not None and new != child
    assert world.forge.merge_calls == []
    assert set(world.forge.contexts) == {(12, new, landing)}

    world.forge.report_ci(12)
    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert world.forge.merge_calls == [(12, new, "squash")]
    assert world.git.pushes == [("stack/c", child, new)]
    assert world.forge.patches == [(12, "main")]


# -- branching and linear graphs -------------------------------------------------------


def test_siblings_land_from_one_fork_while_the_retained_one_keeps_its_base(
    world: GraphWorld,
) -> None:
    parent = world.open_pr(11, "stack/p", "main", [PARENT])
    first = world.open_pr(12, "stack/c1", "stack/p", [CHILD[0]])
    second = world.open_pr(13, "stack/c2", "stack/p", [SIBLING])
    retained = world.open_pr(14, "stack/s", "stack/p", [RETAINED])
    landing = world.forge.land(11, "squash")
    untouched = world.forge.current(14)
    plan = world.plan({11: None, 12: 11, 13: 11, 14: 11}, {11, 12, 13})

    result, code = world.run(plan, "clean")

    assert (code, result["status"]) == (5, "BLOCKED"), result

    [dependent] = rows(result, "dependents")
    assert dependent == {
        "landed": 11,
        "pr": 14,
        "url": f"https://github.com/{REPO}/pull/14",
        "namespace": REPO,
        "ref": "stack/p",
    }
    journal = world.journal(run_id(result))
    one, two = promotion(journal, 12), promotion(journal, 13)
    assert (one.fork, two.fork) == (parent, parent)
    assert (one.old_head, two.old_head) == (first, second)
    # Each sibling is promoted onto the trunk tip current when it is next.
    assert (one.landing, two.landing) == (landing, world.forge.landing(12))
    assert world.forge.merge_calls == [
        (12, one.new_head, "squash"),
        (13, two.new_head, "squash"),
    ]
    assert world.forge.patches == [(12, "main"), (13, "main")]
    # The unselected sibling is untouched and still bases on the parent branch.
    assert world.forge.current(14) == untouched
    assert world.remote("stack/s") == world.local("stack/s") == retained
    assert all(push[0] != "stack/s" for push in world.git.pushes)
    assert all(call[0] != 14 for call in world.forge.retarget_calls)
    # The parent's branch stays while #14 uses it; the landed siblings' refs went.
    assert world.remote("stack/p") == world.local("stack/p") == parent
    for gone in ("stack/c1", "stack/c2"):
        assert world.remote(gone) is None and world.local(gone) is None
    assert {row["pr"] for row in rows(result, "confirmed_merges")} == {11, 12, 13}
    final = tree_files(world.bare, world.forge.landing(13))
    assert final["sibling.txt"] == "sibling\n"
    assert "retained.txt" not in final
    assert rows(result, "retained_changes") == []

    # The retained sibling's owner keeps working and retargets it: outside every
    # selected node's ancestry that is reported, never a stop.
    revised = {"retained.txt": "retained, revised\n"}
    moved = world.actor_push("stack/s", revised, "retained: revise")
    world.forge.pulls[14].base_ref = "main"
    resumed, resumed_code = world.resume(run_id(result), "clean")

    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert [row["pr"] for row in rows(resumed, "retained_changes")] == [14]
    assert len(world.forge.merge_calls) == 2
    assert world.remote("stack/p") is None and world.local("stack/p") is None
    assert world.remote("stack/s") == moved
    assert world.local("stack/s") == retained
    assert world.forge.current(14).state == "OPEN"
    receipt = world.receipt(journal.node(11).run_id)
    removed = {
        (row["kind"], row["ref"]): row["proof"]
        for row in receipt.cleanup["removed"]
        if row["kind"] in ("local", "remote")
    }
    assert set(removed) == {
        ("local", "refs/heads/stack/p"),
        ("remote", "refs/heads/stack/p"),
    }
    assert all(str(proof).startswith("landed-head:") for proof in removed.values())


@pytest.mark.parametrize("endpoint", ["merged", "clean"])
def test_linear_chain_lands_parent_first_with_gates_on_each_new_context(
    world: GraphWorld, endpoint: Endpoint
) -> None:
    parent, child = parent_and_child(world)
    grandchild = world.open_pr(13, "stack/d", "stack/c", [GRANDCHILD])
    plan = world.plan({11: None, 12: 11, 13: 12}, {11, 12, 13})

    result, code = world.run(plan, endpoint)

    assert (code, result["status"]) == (0, "COMPLETE"), result
    journal = world.journal(run_id(result))
    middle, upper = promotion(journal, 12), promotion(journal, 13)
    first = world.forge.landing(11)
    second = world.forge.landing(12)
    third = world.forge.landing(13)
    assert world.forge.merge_calls == [
        (11, parent, "squash"),
        (12, middle.new_head, "squash"),
        (13, upper.new_head, "squash"),
    ]
    # Each slice was captured before its parent changed, then replayed onto the
    # trunk tip its parent's landing produced.
    assert (middle.fork, middle.old_head, middle.landing) == (parent, child, first)
    assert (upper.fork, upper.old_head, upper.landing) == (child, grandchild, second)
    receipts = [world.receipt(journal.node(number).run_id) for number in (11, 12, 13)]
    assert [(r.head_sha, r.base_sha, r.base_ref) for r in receipts] == [
        (parent, world.base, "main"),
        (middle.new_head, first, "main"),
        (upper.new_head, second, "main"),
    ]
    assert len({r.run_id for r in receipts}) == 3
    assert outcomes(journal) == [
        ("capture", 12, "CONFIRMED"),
        ("capture", 13, "CONFIRMED"),
        ("rewrite-push", 12, "CONFIRMED"),
        ("advance-local", 12, "CONFIRMED"),
        ("retarget", 12, "CONFIRMED"),
        ("rewrite-push", 13, "CONFIRMED"),
        ("advance-local", 13, "CONFIRMED"),
        ("retarget", 13, "CONFIRMED"),
    ]
    expected = {
        **LANDED,
        "shared.txt": GRANDCHILD.files["shared.txt"],
        "grandchild.txt": "grandchild\n",
    }
    assert tree_files(world.bare, third) == expected
    usable = cast("dict[str, object]", result["usable_checkout"])
    assert (usable["path"], usable["branch"], usable["head"]) == (
        str(world.work),
        "main",
        third,
    )
    if endpoint == "merged":
        assert heads(world.bare) == {
            "refs/heads/main": third,
            "refs/heads/stack/p": parent,
            "refs/heads/stack/c": middle.new_head,
            "refs/heads/stack/d": upper.new_head,
        }
        assert heads(world.work) == heads(world.bare)
        return
    assert set(heads(world.bare)) == {"refs/heads/main"}
    assert set(heads(world.work)) == {"refs/heads/main"}
    # Each parent branch was deleted only after its child stopped using it.
    retargeted = [i.created_at for i in journal.intents if i.kind == "retarget"]
    for number, moved in zip((11, 12), retargeted, strict=True):
        deleted = deletions(world.receipt(journal.node(number).run_id))
        assert deleted and min(deleted) > moved


def test_completed_graph_rerun_is_an_evidence_backed_no_op(world: GraphWorld) -> None:
    parent_and_child(world)
    result, code = world.run(world.plan(PAIR, {11, 12}), "clean")
    assert (code, result["status"]) == (0, "COMPLETE"), result
    saved = state(world.common() / "armory")
    refs = (git(world.bare, "for-each-ref"), git(world.work, "for-each-ref"))
    calls = mutations(world)

    again, again_code = world.resume(run_id(result), "clean")

    assert (again_code, again["status"]) == (0, "COMPLETE"), again
    assert (again["mutation_attempted"], again["mutation_performed"]) == (False, False)
    assert state(world.common() / "armory") == saved
    assert (git(world.bare, "for-each-ref"), git(world.work, "for-each-ref")) == refs
    assert mutations(world) == calls
    statuses = {row["pr"]: row["status"] for row in rows(again, "nodes")}
    assert statuses == {11: "COMPLETE", 12: "COMPLETE"}


# -- fork boundaries -------------------------------------------------------------------


def test_child_off_the_parent_head_stops_before_the_parent_merge(
    world: GraphWorld,
) -> None:
    world.open_pr(11, "stack/p", "main", [PARENT])
    child = world.open_pr(12, "stack/c", "stack/p", CHILD)
    advanced = world.extend("stack/p", [FOLLOW_UP])

    result, code = world.run(world.plan(PAIR, {11, 12}), "clean")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result

    assert world.forge.merge_calls == []
    assert world.git.pushes == [] and world.forge.retarget_calls == []
    assert world.remote("main") == world.base
    assert (world.remote("stack/p"), world.remote("stack/c")) == (advanced, child)
    journal = world.journal(run_id(result))
    assert journal.intents == []
    assert [row.run_id for row in journal.nodes] == [None, None]
    assert world.store().list_runs() == ()


def test_explicit_fork_lands_the_child_of_an_advanced_parent(world: GraphWorld) -> None:
    fork = world.open_pr(11, "stack/p", "main", [PARENT])
    child = world.open_pr(12, "stack/c", "stack/p", CHILD)
    advanced = world.extend("stack/p", [FOLLOW_UP])
    plan = world.plan(PAIR, {11, 12}, forks={12: fork})

    result, code = world.run(plan, "merged")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    proof = promotion(world.journal(run_id(result)), 12)
    assert (proof.fork, proof.old_head, proof.commits) == (fork, child, 2)
    assert proof.landing == world.forge.landing(11)
    assert world.forge.merge_calls == [
        (11, advanced, "squash"),
        (12, proof.new_head, "squash"),
    ]
    landed = {**LANDED, "parent.txt": FOLLOW_UP.files["parent.txt"]}
    assert tree_files(world.bare, world.forge.landing(12)) == landed


# -- local state ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local", "reason"),
    [
        ("exact", None),
        ("extra-commit", "it holds another revision"),
        ("checked-out-dirty", "it is checked out"),
    ],
)
def test_local_child_branch_moves_only_when_exactly_at_the_old_head(
    world: GraphWorld, local: str, reason: str | None
) -> None:
    _, child = parent_and_child(world)
    world.forge.land(11, "squash")
    kept = child
    tree = world.root / "child-tree"
    if local == "extra-commit":
        wip = Change({"notes.txt": "unpushed\n"}, b"wip: local only\n", FIRST_AUTHOR)
        kept = world.write(child, wip)
        git(world.work, "branch", "-f", "stack/c", kept)
    elif local == "checked-out-dirty":
        git(world.work, "worktree", "add", "-q", str(tree), "stack/c")
        (tree / "child.txt").write_text("unsaved edit\n")

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    journal = world.journal(run_id(result))
    new = promotion(journal, 12).new_head
    assert world.remote("stack/c") == new
    if reason is None:
        assert world.local("stack/c") == new
        assert rows(result, "retained_local") == []
        return
    assert world.local("stack/c") == kept
    assert "advance-local" not in [intent.kind for intent in journal.intents]
    [retained] = rows(result, "retained_local")
    assert retained == {
        "pr": 12,
        "ref": "refs/heads/stack/c",
        "oid": kept,
        "reason": f"local refs/heads/stack/c is retained: {reason}",
        "next_action": f"preserve its work, then move it to {new} or keep it",
    }
    if local == "checked-out-dirty":
        assert git(tree, "rev-parse", "HEAD") == child
        assert git(tree, "symbolic-ref", "--short", "HEAD") == "stack/c"
        assert (tree / "child.txt").read_text() == "unsaved edit\n"


def test_dirty_invoking_checkout_stops_before_the_parent_merge(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)
    (world.work / "README.md").write_text("user edit\n")
    (world.work / "notes.txt").write_text("untracked\n")

    result, code = world.run(world.plan(PAIR, {11, 12}), "clean")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert world.forge.merge_calls == []
    assert world.git.pushes == [] and world.forge.retarget_calls == []
    assert world.remote("main") == world.base
    assert (world.remote("stack/p"), world.remote("stack/c")) == (parent, child)
    assert (world.work / "README.md").read_text() == "user edit\n"
    assert (world.work / "notes.txt").read_text() == "untracked\n"
    assert git(world.work, "symbolic-ref", "--short", "HEAD") == "main"
    journal = world.journal(run_id(result))
    assert outcomes(journal) == [("capture", 12, "CONFIRMED")]
    assert world.receipt(journal.node(11).run_id).intents == []


def spoil(world: GraphWorld, local: str) -> None:
    """Leave user work in the invoking checkout: an edit, or a conflicted pick."""
    if local == "dirty":
        (world.work / "README.md").write_text("user edit\n")
        return
    side = Change({"README.md": "side\n"}, b"side: readme\n", FIRST_AUTHOR)
    pick = Change({"README.md": "picked\n"}, b"pick: readme\n", FIRST_AUTHOR)
    picked = world.write(world.write(world.base, side), pick)
    git(world.work, "cherry-pick", picked, check=False)
    assert (world.work / ".git" / "CHERRY_PICK_HEAD").is_file()


def checkout_state(world: GraphWorld) -> tuple[str, bytes]:
    """The invoking checkout's status and README bytes."""
    status = git(world.work, "status", "--porcelain=v2", "--untracked-files=all")
    return status, (world.work / "README.md").read_bytes()


@pytest.mark.parametrize(
    ("local", "status", "code"),
    [("dirty", "NEEDS_JUDGMENT", 4), ("conflict", "BLOCKED", 5)],
)
def test_user_work_stops_the_child_of_a_landed_parent_before_its_push(
    world: GraphWorld,
    local: str,
    status: str,
    code: int,
) -> None:
    _, child = parent_and_child(world)
    world.forge.land(11, "squash")
    spoil(world, local)
    before = checkout_state(world)

    result, result_code = world.run(world.plan(PAIR, {12}), "merged")

    assert (result_code, result["status"]) == (code, status), result
    assert mutations(world) == ([], [], [], [])
    assert world.remote("stack/c") == world.local("stack/c") == child
    assert world.forge.current(12).base_ref == "stack/p"
    assert checkout_state(world) == before
    journal = world.journal(run_id(result))
    assert journal.intents == []
    assert journal.node(12).promotion is None
    assert journal.status == status


def test_dirty_checkout_after_an_unknown_retarget_stops_before_the_next_one(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    world.forge.land(11, "squash")
    world.forge.retarget_fault = "lost"
    result, code = world.run(world.plan(PAIR, {12}), "merged")
    assert (code, result["status"]) == (3, "WAITING"), result
    spoil(world, "dirty")

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed

    assert len(world.forge.retarget_calls) == 1
    assert world.forge.patches == [] and world.forge.merge_calls == []
    assert world.forge.current(12).base_ref == "stack/p"
    assert (world.work / "README.md").read_text() == "user edit\n"
    assert outcomes(world.journal(run_id(result))) == [
        ("capture", 12, "CONFIRMED"),
        ("rewrite-push", 12, "CONFIRMED"),
        ("advance-local", 12, "CONFIRMED"),
        ("retarget", 12, "REJECTED"),
    ]


def test_local_advance_reported_failed_after_it_applied_is_confirmed(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    world.forge.land(11, "squash")
    world.git.advance_fault = True

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    journal = world.journal(run_id(result))
    new = promotion(journal, 12).new_head
    assert world.local("stack/c") == world.remote("stack/c") == new
    advances = [intent for intent in journal.intents if intent.kind == "advance-local"]
    assert [(intent.outcome, intent.actual) for intent in advances] == [
        ("CONFIRMED", new)
    ]
    assert rows(result, "retained_local") == []
    assert world.forge.merge_calls == [(12, new, "squash")]


def sign_on(world: GraphWorld, ref: str) -> str:
    """Publish one more commit on ``ref`` that carries a signature header."""
    tip = git(world.work, "rev-parse", "--verify", f"refs/heads/{ref}")
    unsigned = Change({"signed.txt": "signed\n"}, b"child: signed\n", FIRST_AUTHOR)
    tree = git(world.work, "rev-parse", f"{world.write(tip, unsigned)}^{{tree}}")
    raw = (
        f"tree {tree}\nparent {tip}\n"
        "author Child Author <child@example.invalid> 1700000200 +0200\n"
        "committer Child Author <child@example.invalid> 1700000200 +0200\n"
        "gpgsig -----BEGIN PGP SIGNATURE-----\n \n iQEzBAABCAAdFiEE\n"
        " -----END PGP SIGNATURE-----\n\nchild: signed change\n"
    ).encode()
    stored = git_bytes(
        world.work, "hash-object", "-t", "commit", "-w", "--stdin", stdin=raw
    )
    signed = stored.decode("ascii").strip()
    git(world.work, "branch", "-f", ref, signed)
    git(world.work, "push", "-q", "origin", ref)
    return signed


def objects(world: GraphWorld) -> list[str]:
    """Every path below the invoking repository's object store."""
    store = world.common() / "objects"
    return sorted(str(path.relative_to(store)) for path in store.rglob("*"))


@pytest.mark.parametrize("signing", ["configured", "signed-commit"])
def test_signing_refuses_the_promotion_before_any_object_or_dispatch(
    world: GraphWorld, signing: str
) -> None:
    _, head = parent_and_child(world)
    if signing == "signed-commit":
        head = sign_on(world, "stack/c")
    world.forge.land(11, "squash")
    # Every object is already local, so the run itself fetches nothing.
    git(world.work, "fetch", "-q", "origin")
    if signing == "configured":
        git(world.work, "config", "commit.gpgsign", "true")
    untouched = world.forge.current(12)
    stored = objects(world)

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    if signing == "configured":
        assert git(world.work, "config", "--get", "commit.gpgsign") == "true"
    assert objects(world) == stored
    assert mutations(world) == ([], [], [], [])
    assert world.remote("stack/c") == world.local("stack/c") == head
    assert world.forge.current(12) == untouched
    journal = world.journal(run_id(result))
    assert outcomes(journal) == [("capture", 12, "CONFIRMED")]
    assert journal.node(12).promotion is None


# -- rewrite push outcomes -------------------------------------------------------------


def test_stale_lease_keeps_the_actor_commit_and_resume_reports_the_move(
    world: GraphWorld,
) -> None:
    _, child = parent_and_child(world)
    world.forge.land(11, "squash")
    raced: list[str] = []

    def actor() -> None:
        edit = {"child.txt": "child one, revised elsewhere\n"}
        raced.append(world.actor_push("stack/c", edit, "child: concurrent edit"))

    world.git.before_push = actor

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    [moved] = raced

    [(branch, old, _)] = world.git.pushes
    assert (branch, old) == ("stack/c", child)
    assert world.remote("stack/c") == moved
    assert world.local("stack/c") == child
    assert world.forge.retarget_calls == [] and world.forge.merge_calls == []
    assert world.forge.current(12).base_ref == "stack/p"
    journal = world.journal(run_id(result))
    push = journal.intents[-1]
    assert (push.kind, push.outcome) == ("rewrite-push", "REJECTED")
    assert push.actual == moved
    assert journal.node(12).head_sha == child

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed

    assert len(world.git.pushes) == 1
    assert world.remote("stack/c") == moved
    assert world.forge.retarget_calls == [] and world.forge.merge_calls == []


def test_push_applied_but_unreported_is_confirmed_on_resume_without_resend(
    world: GraphWorld,
) -> None:
    _, child = parent_and_child(world)
    world.forge.land(11, "squash")
    world.git.push_fault = "applied_lost"

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (3, "WAITING"), result

    new = world.remote("stack/c")
    [pending] = rows(result, "pending_intents")
    assert (pending["kind"], pending["outcome"]) == ("rewrite-push", "PENDING")
    assert (pending["expected_old"], pending["new"]) == (child, new)
    assert world.forge.retarget_calls == [] and world.forge.merge_calls == []

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert world.git.pushes == [("stack/c", child, new)]
    push = world.journal(run_id(result)).intents[1]
    assert (push.kind, push.outcome, push.actual) == ("rewrite-push", "CONFIRMED", new)
    assert world.forge.patches == [(12, "main")]
    assert world.forge.merge_calls == [(12, new, "squash")]
    assert world.local("stack/c") == new


def test_push_never_applied_is_rejected_on_resume_and_proved_once_more(
    world: GraphWorld,
) -> None:
    _, child = parent_and_child(world)
    world.forge.land(11, "squash")
    world.git.push_fault = "lost"

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (3, "WAITING"), result
    assert world.remote("stack/c") == child
    [first] = world.git.pushes

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    new = world.remote("stack/c")
    assert world.git.pushes == [first, ("stack/c", child, new)]
    journal = world.journal(run_id(result))
    pushes = [intent for intent in journal.intents if intent.kind == "rewrite-push"]
    assert [(intent.outcome, intent.actual) for intent in pushes] == [
        ("REJECTED", child),
        ("CONFIRMED", new),
    ]
    assert pushes[0].detail == "reconciled: the remote still holds the old head"
    assert promotion(journal, 12).new_head == new
    assert world.forge.merge_calls == [(12, new, "squash")]


def test_unknown_push_with_a_third_remote_head_needs_judgment_without_resend(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    world.forge.land(11, "squash")
    world.git.push_fault = "lost"
    result, code = world.run(world.plan(PAIR, {12}), "merged")
    assert (code, result["status"]) == (3, "WAITING"), result
    third = world.actor_push("stack/c", {"child.txt": "third\n"}, "child: third value")

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed

    assert len(world.git.pushes) == 1
    assert world.remote("stack/c") == third
    assert world.forge.retarget_calls == [] and world.forge.merge_calls == []
    assert world.journal(run_id(result)).intents[-1].outcome == "PENDING"


# -- retarget outcomes -----------------------------------------------------------------


def test_retarget_applied_but_unreported_is_confirmed_without_a_second_edit(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    world.forge.land(11, "squash")
    world.forge.retarget_fault = "applied_lost"

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (3, "WAITING"), result

    assert world.forge.current(12).base_ref == "main"
    [pending] = rows(result, "pending_intents")
    assert pending["kind"] == "retarget"
    assert (pending["expected_old"], pending["new"]) == ("stack/p", "main")
    assert world.forge.merge_calls == []

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert len(world.forge.retarget_calls) == 1
    assert world.forge.patches == [(12, "main")]
    retarget = world.journal(run_id(result)).intents[-1]
    assert (retarget.kind, retarget.outcome) == ("retarget", "CONFIRMED")
    assert retarget.actual == "main"
    assert world.forge.merge_calls == [(12, world.remote("stack/c"), "squash")]


def test_retarget_never_applied_is_rejected_on_resume_and_sent_once_more(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    world.forge.land(11, "squash")
    world.forge.retarget_fault = "lost"

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (3, "WAITING"), result
    assert world.forge.current(12).base_ref == "stack/p"
    assert world.forge.patches == []

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert len(world.forge.retarget_calls) == 2
    assert world.forge.patches == [(12, "main")]
    journal = world.journal(run_id(result))
    retargets = [intent for intent in journal.intents if intent.kind == "retarget"]
    assert [(intent.outcome, intent.actual) for intent in retargets] == [
        ("REJECTED", "stack/p"),
        ("CONFIRMED", "main"),
    ]
    assert retargets[0].detail == "reconciled: the base is unchanged"
    assert world.forge.merge_calls == [(12, world.remote("stack/c"), "squash")]


def test_unknown_retarget_with_a_base_changed_by_someone_else_needs_judgment(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    world.forge.land(11, "squash")
    world.forge.retarget_fault = "lost"
    result, code = world.run(world.plan(PAIR, {12}), "merged")
    assert (code, result["status"]) == (3, "WAITING"), result
    git(world.bare, "update-ref", "refs/heads/stack/elsewhere", world.base)
    world.forge.pulls[12].base_ref = "stack/elsewhere"

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed

    assert len(world.forge.retarget_calls) == 1
    assert world.forge.patches == [] and world.forge.merge_calls == []
    assert world.forge.current(12).base_ref == "stack/elsewhere"
    assert world.journal(run_id(result)).intents[-1].outcome == "PENDING"


def test_provider_auto_retarget_and_head_deletion_are_observed_not_repeated(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)
    world.forge.auto_retarget = world.forge.auto_delete = True

    result, code = world.run(world.plan(PAIR, {11, 12}), "clean")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    journal = world.journal(run_id(result))
    proof = promotion(journal, 12)
    assert (proof.fork, proof.old_head) == (parent, child)
    assert proof.landing == world.forge.landing(11)
    assert world.forge.retarget_calls == [] and world.forge.patches == []
    assert [intent.kind for intent in journal.intents] == [
        "capture",
        "rewrite-push",
        "advance-local",
    ]
    assert world.forge.merge_calls == [
        (11, parent, "squash"),
        (12, proof.new_head, "squash"),
    ]
    assert tree_files(world.bare, world.forge.landing(12)) == LANDED
    assert set(heads(world.bare)) == {"refs/heads/main"}
    assert set(heads(world.work)) == {"refs/heads/main"}


# -- graph changes and scope -----------------------------------------------------------


@pytest.mark.parametrize("change", ["closed", "head-moved", "parent-changed"])
def test_graph_change_after_a_stop_needs_judgment_without_any_dispatch(
    world: GraphWorld, change: str
) -> None:
    parent, child = parent_and_child(world)
    retained = world.open_pr(14, "stack/s", "stack/p", [RETAINED])
    world.forge.held.add(11)
    plan = world.plan({11: None, 12: 11, 14: 11}, {11, 12})
    result, code = world.run(plan, "clean")
    assert (code, result["status"]) == (3, "WAITING"), result

    saved = world.journal(run_id(result))
    if change == "closed":
        world.forge.close(12)
        expected = "#12 is closed without a confirmed merge"
    elif change == "head-moved":
        moved = world.actor_push("stack/c", {"child.txt": "moved\n"}, "child: moved")
        expected = f"#12 head moved outside the controller from {child} to {moved}"
    else:
        world.forge.pulls[12].base_ref = "stack/s"
        expected = "#12 base changed from 'stack/p' to 'stack/s'"

    resumed, resumed_code = world.resume(run_id(result), "clean")

    assert (resumed_code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed

    assert world.forge.merge_calls == [] and world.forge.retarget_calls == []
    assert world.git.pushes == []
    assert world.remote("main") == world.base
    assert world.remote("stack/p") == parent
    assert world.remote("stack/s") == retained
    journal = world.journal(run_id(result))
    assert (journal.status, journal.issue) == ("NEEDS_JUDGMENT", expected)
    assert journal.intents == saved.intents


def test_selected_child_of_an_open_unselected_parent_needs_judgment_at_once(
    world: GraphWorld,
) -> None:
    parent_and_child(world)

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result

    assert result["run_id"] is None
    assert not (world.common() / "armory").exists()
    assert world.forge.merge_calls == [] and world.git.pushes == []


# -- post-merge acceptance and inspection ----------------------------------------------


def test_post_merge_failure_keeps_the_landing_and_resume_never_merges_again(
    world: GraphWorld,
) -> None:
    tools = world.root / "tools"
    tools.mkdir()
    checker, marker, flag = tools / "verify.py", tools / "runs.log", tools / "fail"
    checker.write_text(
        """\
import os, subprocess, sys
marker, flag = sys.argv[1:3]
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                      check=True).stdout.strip()
with open(marker, "a") as handle:
    handle.write(head + "\\n")
sys.exit(7 if os.path.exists(flag) else 0)
"""
    )
    flag.write_text("fail\n")
    command = [sys.executable, str(checker), str(marker), str(flag)]
    parent, child = parent_and_child(world)
    decisions: dict[int, dict[str, object]] = {11: {"post_merge_commands": [command]}}
    plan = world.plan(PAIR, {11, 12}, decisions=decisions)

    result, code = world.run(plan, "clean")

    landing = world.forge.landing(11)
    assert (code, result["status"]) == (5, "BLOCKED"), result

    [merge] = rows(result, "confirmed_merges")
    assert merge == {
        "pr": 11,
        "url": f"https://github.com/{REPO}/pull/11",
        "landing": landing,
        "reachable": True,
    }
    assert world.forge.merge_calls == [(11, parent, "squash")]
    assert world.git.pushes == [] and world.forge.retarget_calls == []
    assert world.remote("stack/p") == world.local("stack/p") == parent
    assert world.remote("stack/c") == child
    assert marked(marker) == [landing]
    journal = world.journal(run_id(result))
    assert journal.status == "BLOCKED"
    assert journal.node(12).fork == parent
    receipt = world.receipt(journal.node(11).run_id)
    assert (receipt.status, receipt.merge_sha) == ("BLOCKED", landing)
    assert receipt.merge_verified and receipt.validation_sha is None

    flag.unlink()
    resumed, resumed_code = world.resume(run_id(result), "clean")

    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    new = promotion(world.journal(run_id(result)), 12).new_head
    assert world.forge.merge_calls == [(11, parent, "squash"), (12, new, "squash")]
    assert marked(marker) == [landing, landing, world.forge.landing(12)]
    assert set(heads(world.bare)) == {"refs/heads/main"}
    assert set(heads(world.work)) == {"refs/heads/main"}


def test_dry_run_of_a_waiting_graph_reads_facts_and_writes_nothing(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    landing = world.forge.land(11, "squash")
    world.forge.held.add(12)
    result, code = world.run(world.plan(PAIR, {11, 12}), "merged")
    assert (code, result["status"]) == (3, "WAITING"), result
    journal = world.journal(run_id(result))
    # Mode, modification time and bytes of the whole checkout (its .git with the
    # journal and receipts included) and of the remote.
    before = snapshot(world.work, world.bare)
    calls = mutations(world)

    preview = inspect_graph(
        world.git,
        world.forge,
        journal_plan(journal),
        "merged",
        journal=journal,
    )

    assert (preview["status"], preview["run_id"]) == ("PLANNED", run_id(result))
    actions = rows(preview, "actions")
    assert [(row["action"], row["pr"]) for row in actions] == [
        ("verify-landing", 11),
        ("land", 12),
    ]
    gate = cast("dict[str, object]", actions[1]["gate"])
    assert gate["status"] == "WAITING"
    assert rows(preview, "blockers") == []
    assert preview["observed_revisions"] == {"trunk": landing}
    assert snapshot(world.work, world.bare) == before
    assert mutations(world) == calls


def test_dry_run_proves_a_promotion_whose_tree_exists_without_touching_it(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)
    landing = world.forge.land(11, "squash")
    # Every object is local, so the proof is evaluated; a dry run never fetches.
    git(world.work, "fetch", "-q", "origin")
    # The squash landing's tree is the parent's, so the clean three-way tree is the
    # child head's own tree: an object this repository already stores.
    tree = git(world.work, "rev-parse", f"{child}^{{tree}}")
    assert git(world.work, "cat-file", "-t", tree) == "tree"
    plan = world.plan(PAIR, {12})
    before = snapshot(world.work, world.bare)
    calls = mutations(world)

    preview = inspect_graph(world.git, world.forge, plan, "merged")

    assert (preview["status"], preview["run_id"]) == ("PLANNED", None)
    actions = rows(preview, "actions")
    assert [(row["action"], row["pr"]) for row in actions] == [
        ("promote", 12),
        ("retarget", 12),
        ("land", 12),
    ]
    promote = actions[0]
    assert (promote["fork"], promote["old_head"]) == (parent, child)
    assert (promote["landing"], promote["onto"]) == (landing, landing)
    proof = cast("dict[str, object]", promote["proof"])
    assert (proof["evaluated"], proof["provable"]) == (True, True)
    assert (proof["expected_tree"], proof["commits"]) == (tree, 2)
    assert (actions[1]["from"], actions[1]["to"]) == ("stack/p", "main")
    assert rows(preview, "blockers") == []
    assert snapshot(world.work, world.bare) == before
    assert mutations(world) == calls
    assert not (world.common() / "armory").exists()


def test_dry_run_after_an_unreported_push_plans_its_reconciliation_read_only(
    world: GraphWorld,
) -> None:
    _, child = parent_and_child(world)
    world.forge.land(11, "squash")
    world.git.push_fault = "applied_lost"
    result, code = world.run(world.plan(PAIR, {12}), "merged")
    assert (code, result["status"]) == (3, "WAITING"), result
    new = world.remote("stack/c")
    # The provider model publishes refs/pull/12/head on its next read; let it
    # settle so the snapshot measures only the inspection.
    assert world.forge.current(12).head_sha == new
    journal = world.journal(run_id(result))
    before = snapshot(world.work, world.bare)
    calls = mutations(world)

    preview = inspect_graph(
        world.git,
        world.forge,
        journal_plan(journal),
        "merged",
        journal=journal,
    )

    assert (preview["status"], preview["run_id"]) == ("PLANNED", run_id(result))
    actions = rows(preview, "actions")
    assert actions[0] == {
        "action": "reconcile",
        "pr": 12,
        "intent": journal.intents[1].key,
        "kind": "rewrite-push",
        "expected_old": child,
        "new": new,
        "observed": new,
        "outcome": "CONFIRMED",
    }
    # The reconciled head is the expected one: no "head moved" judgment follows.
    assert [(row["action"], row["pr"]) for row in actions[1:]] == [
        ("retarget", 12),
        ("land", 12),
    ]
    assert rows(preview, "blockers") == []
    assert snapshot(world.work, world.bare) == before
    assert mutations(world) == calls
    assert world.journal(run_id(result)).intents[1].outcome == "PENDING"


# -- native membership ---------------------------------------------------------------


def test_selection_mixing_manual_and_native_members_is_blocked_before_any_write(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    world.forge.pulls[12].native = True

    result, code = world.run(world.plan(PAIR, {11, 12}), "clean")

    assert (code, result["status"]) == (5, "BLOCKED"), result

    assert result["run_id"] is None
    assert world.forge.merge_calls == [] and world.forge.retarget_calls == []
    assert world.git.pushes == []
    assert world.remote("main") == world.base
    assert not (world.common() / "armory").exists()


def test_unselected_native_sibling_is_left_untouched(world: GraphWorld) -> None:
    parent, _ = parent_and_child(world)
    world.open_pr(14, "stack/s", "stack/p", [RETAINED])
    world.forge.pulls[14].native = True
    untouched = world.forge.current(14)
    plan = world.plan({11: None, 12: 11, 14: 11}, {11, 12})

    result, code = world.run(plan, "merged")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    new = promotion(world.journal(run_id(result)), 12).new_head
    assert world.forge.merge_calls == [(11, parent, "squash"), (12, new, "squash")]
    assert world.forge.current(14) == untouched
    assert all(call[0] != 14 for call in world.forge.retarget_calls)
    assert all(push[0] != "stack/s" for push in world.git.pushes)
    roles = {row["pr"]: row["role"] for row in rows(result, "nodes")}
    assert roles == {11: "selected", 12: "selected", 14: "retained"}


def test_selected_node_turning_native_mid_run_is_blocked_before_its_retarget(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)

    def join_native_stack() -> None:
        world.forge.pulls[12].native = True

    world.git.before_push = join_native_stack

    result, code = world.run(world.plan(PAIR, {11, 12}), "merged")

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert "#12 became a native stack member" in str(result["blocker"])
    new = promotion(world.journal(run_id(result)), 12).new_head
    # The promotion push raced the provider change; nothing follows it.
    assert world.git.pushes == [("stack/c", child, new)]
    assert world.forge.merge_calls == [(11, parent, "squash")]
    assert (world.forge.retarget_calls, world.forge.patches) == ([], [])
    current = world.forge.current(12)
    assert (current.state, current.base_ref) == ("OPEN", "stack/p")


# -- controller concurrency, cancellation and sources --------------------------------


def test_held_controller_lock_waits_without_any_journal_or_mutation(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    plan = world.plan(PAIR, {11, 12})

    with world.store().mutation_lock():
        result, code = world.run(plan, "clean")

    assert (code, result["status"]) == (3, "WAITING"), result

    assert result["run_id"] is None
    assert world.forge.merge_calls == [] and world.git.pushes == []
    assert not world.store().graph_directory.exists()
    assert world.store().list_runs() == ()


def test_failed_first_journal_save_names_no_run_and_dispatches_nothing(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    plan = world.plan(PAIR, {11, 12})
    graphs = world.store().graph_directory
    graphs.mkdir(parents=True)
    graphs.chmod(0o777)

    result, code = world.run(plan, "clean")

    assert (code, result["status"]) == (5, "BLOCKED"), result

    assert result["run_id"] is None
    assert list(graphs.iterdir()) == []
    assert world.store().list_runs() == ()
    assert mutations(world) == ([], [], [], [])
    assert world.remote("main") == world.base


def test_corrupt_node_receipt_blocks_the_resume_and_is_left_as_found(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    world.forge.land(11, "squash")
    world.forge.held.add(12)
    result, code = world.run(world.plan(PAIR, {12}), "merged")
    assert (code, result["status"]) == (3, "WAITING"), result
    node_run = world.journal(run_id(result)).node(12).run_id
    assert node_run is not None
    receipt = world.store().directory / f"{node_run}.json"
    receipt.write_bytes(b"{")
    world.forge.report_ci(12)
    calls = mutations(world)

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (5, "BLOCKED"), resumed

    assert mutations(world) == calls
    assert world.forge.current(12).state == "OPEN"
    assert receipt.read_bytes() == b"{"
    journal = world.journal(run_id(result))
    assert (journal.status, journal.issue) == ("BLOCKED", "receipt JSON is malformed")


def fill(journal: GraphJournal, pr: int) -> int:
    """Pad ``journal`` with refused retargets of ``pr`` to the most it can hold.

    The capacity is the journal validator's, found by search, never assumed.
    """
    kept = list(journal.intents)

    def holds(extra: int) -> bool:
        journal.intents = kept + [
            GraphIntent(
                key=str(len(kept) + index + 1),
                kind="retarget",
                pr=pr,
                resource=f"pull/{pr}",
                expected_old="stack/p",
                new="main",
                created_at=kept[-1].created_at,
                outcome="REJECTED",
                actual="stack/p",
                detail="refused by the provider",
            )
            for index in range(extra)
        ]
        try:
            GraphJournal.parse(journal.serialize())
        except ReceiptInputError:
            return False
        return True

    low, high = 0, 1
    while holds(high):
        low, high = high, 2 * high
    while high - low > 1:
        middle = (low + high) // 2
        low, high = (middle, high) if holds(middle) else (low, middle)
    holds(low)
    return len(journal.intents)


def test_full_intent_journal_stops_before_another_dispatch(world: GraphWorld) -> None:
    parent_and_child(world)
    world.forge.land(11, "squash")
    world.forge.retarget_fault = "lost"
    result, code = world.run(world.plan(PAIR, {12}), "merged")
    assert (code, result["status"]) == (3, "WAITING"), result
    store = world.store()
    journal = store.load_graph(run_id(result))
    unknown = journal.intents[-1]
    assert (unknown.kind, unknown.outcome) == ("retarget", "PENDING")
    recorded = len(journal.intents)
    capacity = fill(journal, 12)
    assert capacity > recorded
    store.save_graph(journal)

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed

    assert len(world.forge.retarget_calls) == 1
    assert world.forge.patches == [] and world.forge.merge_calls == []
    assert world.forge.current(12).base_ref == "stack/p"
    saved = world.journal(run_id(result))
    assert len(saved.intents) == capacity
    # The unknown retarget was reconciled from facts; nothing was sent again.
    [reconciled] = [row for row in saved.intents if row.key == unknown.key]
    assert (reconciled.outcome, reconciled.actual) == ("REJECTED", "stack/p")
    assert saved.status == "NEEDS_JUDGMENT"


def test_cancelled_wait_exits_130_and_resume_repeats_no_confirmed_mutation(
    world: GraphWorld, clock: LifecycleClock
) -> None:
    _, child = parent_and_child(world)
    world.forge.land(11, "squash")
    world.forge.held.add(12)
    clock.interrupt = True

    result, code = world.run(world.plan(PAIR, {12}), "merged")

    assert (code, result["status"]) == (130, "WAITING"), result
    assert result["cancelled"] is True
    new = world.remote("stack/c")
    journal = world.journal(run_id(result))
    assert journal.status == "WAITING"
    assert {intent.outcome for intent in journal.intents} == {"CONFIRMED"}
    assert world.receipt(journal.node(12).run_id).intents == []
    assert world.forge.merge_calls == []

    world.forge.report_ci(12)
    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert world.git.pushes == [("stack/c", child, new)]
    assert world.forge.patches == [(12, "main")]
    assert world.forge.merge_calls == [(12, new, "squash")]


def test_controller_source_change_needs_judgment_before_resuming(
    world: GraphWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_and_child(world)
    world.forge.land(11, "squash")
    world.forge.held.add(12)
    result, code = world.run(world.plan(PAIR, {12}), "merged")
    assert (code, result["status"]) == (3, "WAITING"), result
    saved = state(world.common() / "armory")
    calls = mutations(world)
    monkeypatch.setattr(lifecycle, "code_identity", lambda: "0" * 64)
    world.forge.report_ci(12)

    resumed, resumed_code = world.resume(run_id(result), "merged")

    assert (resumed_code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed

    assert state(world.common() / "armory") == saved
    assert mutations(world) == calls


# -- operator metadata and provenance ------------------------------------------------


def test_operator_metadata_and_published_provenance_survive_a_graph_run(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    world.open_pr(14, "stack/s", "stack/p", [RETAINED])
    metadata = world.forge.metadata()
    untouched = world.forge.current(14)
    originals = messages(world.bare)
    plan = world.plan({11: None, 12: 11, 14: 11}, {11, 12})

    result, code = world.run(plan, "merged")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    final = world.forge.landing(12)
    policy = git(world.bare, "rev-parse", f"{world.base}:.stack-prs.yaml")
    assert git(world.bare, "rev-parse", f"{final}:.stack-prs.yaml") == policy
    assert (world.work / ".stack-prs.yaml").read_text() == STACK_POLICY
    assert world.forge.metadata() == metadata
    assert world.forge.current(14) == untouched
    # Every commit message is one the operator published, or the forge's own squash
    # landing: no trailer or lineage was stamped or invented.
    landings = {f"Stack part {number} (#{number})\n".encode() for number in (11, 12)}
    assert messages(world.bare) <= originals | landings
    assert messages(world.work) <= originals | landings
