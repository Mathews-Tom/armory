"""Post-landing verification of native stack members against real Git.

A bare repository is the remote and one clone the invoking checkout.
:class:`NativeForge` extends ``graph_world.GraphForge`` with native stack
membership: it lands an open prefix the way the provider was observed to, by
putting each member's own slice on the trunk while the landed member keeps its
review base, then retargets the lowest member left open to the trunk and rebases
its head. It never merges a member through the ordinary path. It is a
behavioural model for transition coverage only, not evidence of vendor behaviour.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

import lifecycle
import pytest
import test_execution as execution
from github_ops import PullRequest
from graph_world import Change, GraphForge, GraphWorld, Result, build_world
from lifecycle import Endpoint, NativeLanding, Policy, evaluate
from state_store import Receipt
from test_execution import git, heads, is_ancestor
from test_graph_git import FIRST_AUTHOR, PARENT_AUTHOR, SECOND_AUTHOR

isolated_git = execution.isolated_git

pytestmark = pytest.mark.skipif(os.name != "posix", reason="journals require POSIX")

TRUNK = "main"
STACK = 7
LOWER = Change({"lower.txt": "lower layer\n"}, b"lower: add\n", PARENT_AUTHOR)
UPPER = Change({"upper.txt": "upper layer\n"}, b"upper: add\n", FIRST_AUTHOR)
TOP = Change({"top.txt": "top layer\n"}, b"top: add\n", SECOND_AUTHOR)
CHECKER = """\
import os, subprocess, sys
def rev(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout.strip()
with open(sys.argv[1], "a") as handle:
    fields = (rev("rev-parse", "HEAD"), rev("rev-parse", "--abbrev-ref", "HEAD"),
              os.getcwd())
    handle.write("\\t".join(fields) + "\\n")
"""
CLEANUP_KINDS = {"delete_local", "delete_remote", "remove_worktree", "prune_tracking"}


class NativeForge(GraphForge):
    """GraphForge whose ``order`` PRs are members of native stack ``STACK``."""

    def __init__(self, bare: Path) -> None:
        super().__init__(bare)
        self.order: list[int] = []

    def current(self, number: int) -> PullRequest:
        pr = super().current(number)
        if number not in self.order:
            return pr
        return replace(
            pr,
            native=True,
            native_stack_number=STACK,
            native_stack_position=self.order.index(number) + 1,
            native_stack_size=len(self.order),
            native_stack_base=TRUNK,
        )

    def merge(self, number: int, expected_head: str, method: str) -> None:
        self.merge_calls.append((number, expected_head, method))
        raise AssertionError(f"native member #{number} reached the ordinary merge")

    def _onto_trunk(self, head: str, below: str, message: str) -> str:
        """``head``'s own slice over ``below`` as one commit on the trunk tip."""
        tip = self._rev(f"refs/heads/{TRUNK}")
        tree = self._merge_tree(tip, head, base=below)
        return git(self.bare, "commit-tree", tree, "-p", tip, "-m", message)

    def land_native(self, *numbers: int) -> None:
        """The provider lands the open prefix ``numbers``, bottom to top."""
        for number in numbers:
            pull = self.pulls[number]
            head = self._rev(f"refs/heads/{pull.head_ref}")
            below = self._rev(f"refs/heads/{pull.base_ref}")
            tip = self._rev(f"refs/heads/{TRUNK}")
            landing = self._onto_trunk(head, below, f"{pull.title} (#{number})")
            git(self.bare, "update-ref", f"refs/heads/{TRUNK}", landing, tip)
            self._publish_head(number, head)
            pull.state, pull.landed = "MERGED", (head, below, landing)
        remaining = [n for n in self.order if self.pulls[n].state == "OPEN"]
        if remaining:
            pull = self.pulls[remaining[0]]
            old = self._rev(f"refs/heads/{pull.head_ref}")
            below = self._rev(f"refs/heads/{pull.base_ref}")
            rebased = self._onto_trunk(old, below, f"{pull.title} (rebased)")
            git(self.bare, "update-ref", f"refs/heads/{pull.head_ref}", rebased, old)
            pull.base_ref = TRUNK


@pytest.fixture
def world(tmp_path: Path) -> GraphWorld:
    """Native stack 7 on main: #11 stack/layer1, #12 stack/layer2, #13 stack/layer3."""
    world = build_world(tmp_path)
    forge = NativeForge(world.bare)
    world.forge = forge
    world.open_pr(11, "stack/layer1", TRUNK, [LOWER])
    world.open_pr(12, "stack/layer2", "stack/layer1", [UPPER])
    world.open_pr(13, "stack/layer3", "stack/layer2", [TOP])
    forge.order = [11, 12, 13]
    tools = world.root / "tools"
    tools.mkdir()
    (tools / "verify.py").write_text(CHECKER)
    return world


def native(world: GraphWorld) -> NativeForge:
    return cast(NativeForge, world.forge)


def policy(world: GraphWorld, pr: PullRequest) -> Policy:
    tools = world.root / "tools"
    command = (sys.executable, str(tools / "verify.py"), str(tools / "runs.log"))
    return Policy(
        ("CONTRIBUTING.md#merging",),
        ("tests",),
        "squash",
        (command,),
        pr.head_sha,
        pr.base_sha,
    )


def execute_node(
    world: GraphWorld,
    number: int,
    context: NativeLanding | None,
    *,
    endpoint: Endpoint = "clean",
    receipt: Receipt | None = None,
) -> tuple[Result, int]:
    bound = policy(world, world.forge.current(number))
    return lifecycle.execute(
        world.git,
        world.forge,
        number,
        endpoint,
        bound,
        30.0,
        world.store(),
        receipt,
        native=context,
    )


def validations(world: GraphWorld) -> list[list[str]]:
    log = world.root / "tools" / "runs.log"
    if not log.exists():
        return []
    return [line.split("\t") for line in log.read_text().splitlines()]


def refs(world: GraphWorld) -> tuple[object, ...]:
    return (
        heads(world.work),
        heads(world.bare),
        git(world.work, "rev-parse", "HEAD"),
        git(world.work, "status", "--porcelain", "--untracked-files=all"),
    )


def receipt_path(world: GraphWorld, run_id: str) -> Path:
    return world.common() / "armory" / "ship" / f"{run_id}.json"


UPPER_LANDING = NativeLanding(TRUNK, STACK, 2)


def test_merged_native_member_completes_on_the_trunk_and_keeps_its_review_base(
    world: GraphWorld,
) -> None:
    lower_head = world.remote("stack/layer1")
    upper_head = world.remote("stack/layer2")
    top_head = world.local("stack/layer3")
    native(world).land_native(11, 12)
    tip = world.remote(TRUNK)

    result, code = execute_node(world, 12, UPPER_LANDING)

    assert (code, result["status"]) == (0, "COMPLETE"), result
    landing = world.forge.landing(12)
    assert tip is not None and is_ancestor(world.bare, landing, tip)
    assert result["usable_checkout"] == {
        "path": str(world.work),
        "head": tip,
        "branch": TRUNK,
    }
    assert git(world.work, "rev-parse", "--abbrev-ref", "HEAD") == TRUNK
    assert git(world.work, "rev-parse", "HEAD") == tip
    [(checked, branch, cwd)] = validations(world)
    assert (checked, branch, Path(cwd).resolve()) == (tip, TRUNK, world.work)
    receipt = world.receipt(cast(str, result["run_id"]))
    assert (receipt.base_ref, receipt.head_sha, receipt.merge_sha) == (
        "stack/layer1",
        upper_head,
        landing,
    )
    assert (receipt.merge_verified, receipt.validation_sha) == (True, tip)
    # The member's own head is gone; the lower and the retained heads stay.
    assert world.local("stack/layer2") is None
    assert world.remote("stack/layer2") is None
    assert world.local("stack/layer1") == lower_head
    assert world.remote("stack/layer1") == lower_head
    assert world.local("stack/layer3") == top_head
    retained = world.forge.current(13)
    assert (retained.state, retained.base_ref) == ("OPEN", TRUNK)
    assert world.remote("stack/layer3") == retained.head_sha != top_head


def test_merged_native_member_without_the_context_is_blocked_and_writes_nothing(
    world: GraphWorld,
) -> None:
    native(world).land_native(11, 12)
    before = refs(world)

    result, code = execute_node(world, 12, None)

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert (result["run_id"], result["mutation_attempted"]) == (None, False)
    assert refs(world) == before
    assert world.store().list_runs() == ()
    assert validations(world) == []


@pytest.mark.parametrize("endpoint", ["merged", "clean"])
def test_open_native_member_is_never_merged_even_with_the_context(
    world: GraphWorld, endpoint: Endpoint
) -> None:
    before = refs(world)

    result, code = execute_node(world, 12, UPPER_LANDING, endpoint=endpoint)

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert world.forge.current(12).state == "OPEN"
    assert world.forge.merge_calls == []
    assert refs(world) == before
    assert world.store().list_runs() == ()


@pytest.mark.parametrize(
    ("number", "context"),
    [
        (12, NativeLanding(TRUNK, STACK, 1)),
        (12, NativeLanding(TRUNK, STACK + 1, 2)),
        (12, NativeLanding("release/next", STACK, 2)),
        (11, UPPER_LANDING),
    ],
)
def test_mismatched_native_context_is_blocked_before_any_receipt(
    world: GraphWorld, number: int, context: NativeLanding
) -> None:
    native(world).land_native(11, 12)
    before = refs(world)

    result, code = execute_node(world, number, context)

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert refs(world) == before
    assert world.store().list_runs() == ()


def test_native_landing_off_the_trunk_is_blocked_before_validation_or_cleanup(
    world: GraphWorld,
) -> None:
    upper_head = world.remote("stack/layer2")
    native(world).land_native(11, 12)
    git(world.work, "fetch", "-q", "origin")
    # The trunk is rewound past the upper landing after the provider reported it.
    lower_landing, upper_landing = world.forge.landing(11), world.forge.landing(12)
    git(world.bare, "update-ref", f"refs/heads/{TRUNK}", lower_landing, upper_landing)

    result, code = execute_node(world, 12, UPPER_LANDING)

    assert (code, result["status"]) == (5, "BLOCKED"), result
    receipt = world.receipt(cast(str, result["run_id"]))
    assert receipt.merge_verified is False
    assert receipt.validation_sha is None
    assert not {op["kind"] for op in receipt.intents} & (CLEANUP_KINDS | {"verify"})
    assert world.local("stack/layer2") == upper_head
    assert world.remote("stack/layer2") == upper_head
    assert validations(world) == []


def test_completed_native_member_reverifies_only_through_its_context(
    world: GraphWorld,
) -> None:
    native(world).land_native(11, 12)
    first, _ = execute_node(world, 12, UPPER_LANDING)
    run_id = cast(str, first["run_id"])
    saved = receipt_path(world, run_id).read_bytes()
    after_first = refs(world)

    again, code = execute_node(
        world, 12, UPPER_LANDING, receipt=world.store().load(run_id)
    )

    assert (code, again["status"]) == (0, "COMPLETE"), again
    assert (again["mutation_attempted"], again["mutation_performed"]) == (False, False)
    assert again["usable_checkout"] == first["usable_checkout"]
    assert len(validations(world)) == 1
    assert refs(world) == after_first

    blocked, code = execute_node(world, 12, None, receipt=world.store().load(run_id))

    assert (code, blocked["status"]) == (5, "BLOCKED"), blocked
    assert receipt_path(world, run_id).read_bytes() == saved
    assert refs(world) == after_first


def test_completed_native_member_whose_landing_left_the_trunk_is_blocked(
    world: GraphWorld,
) -> None:
    native(world).land_native(11, 12)
    first, _ = execute_node(world, 12, UPPER_LANDING)
    run_id = cast(str, first["run_id"])
    lower_landing, upper_landing = world.forge.landing(11), world.forge.landing(12)
    git(world.bare, "update-ref", f"refs/heads/{TRUNK}", lower_landing, upper_landing)

    again, code = execute_node(
        world, 12, UPPER_LANDING, receipt=world.store().load(run_id)
    )

    assert (code, again["status"]) == (5, "BLOCKED"), again
    assert again["mutation_attempted"] is False


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [("green", "READY"), ("pending", "WAITING"), ("rebased", "WAITING")],
)
def test_open_native_member_gates_evaluate_like_a_manual_member(
    world: GraphWorld, scenario: str, expected: str
) -> None:
    forge = native(world)
    if scenario != "green":
        forge.held.add(12)
    if scenario == "rebased":
        # CI passed on the reviewed context, then the provider rebased the head.
        forge.report_ci(12)
        forge.land_native(11)
    observed = forge.observe(12)
    bound = policy(world, observed.pr)
    manual = replace(observed, pr=replace(observed.pr, native=False))

    gate = evaluate(observed, bound, native_stack=True)

    assert observed.pr.native is True
    assert gate == evaluate(manual, bound)
    assert gate.status == expected
    assert evaluate(observed, bound).status == "BLOCKED"
    assert evaluate(manual, bound, native_stack=True).status == "BLOCKED"
