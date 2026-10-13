"""Consumer-visible native stack execution through ``--stack-plan`` against real Git.

The repository is real Git: a bare remote, the invoking clone and an external
actor's clone. ``graph_world.NativeStackForge`` models a GitHub-native stack over
the bare repository: ``merge-async`` requests land members with real commits and
rebase the retained members with real Git. It makes no claim about vendor
behaviour. Monitoring polls skip their window, so a run waiting on the provider
stops WAITING at once and is resumed. Each test asserts the status and exit code,
the requests sent and the refs, trees, PR states, journal records or receipts
that its outcome changes or must leave untouched.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal, cast

import graph
import lifecycle
import native_stack
import pytest
import ship
import test_execution as execution
from graph import inspect_graph, journal_plan
from graph_world import (
    STACK_POLICY,
    Change,
    GraphWorld,
    LifecycleClock,
    NativeStackForge,
    Result,
    build_world,
    tree_files,
)
from lifecycle import Endpoint
from state_store import NativeRecord
from test_cli_stack_plan import snapshot
from test_execution import REPO, MappedGit, git, is_ancestor
from test_graph_execution import state
from test_graph_git import FIRST_AUTHOR, PARENT_AUTHOR, SECOND_AUTHOR, SHARED

isolated_git = execution.isolated_git

pytestmark = pytest.mark.skipif(os.name != "posix", reason="journals require POSIX")

TRUNK = "main"
STACK = 7
LOWER = Change({"lower.txt": "lower layer\n"}, b"lower: add\n", PARENT_AUTHOR)
UPPER = Change({"upper.txt": "upper layer\n"}, b"upper: add\n", FIRST_AUTHOR)
TOP = Change({"top.txt": "top layer\n"}, b"top: add\n", SECOND_AUTHOR)
# A second lower commit editing the same line: a rebase landing of #11 overlaps.
LOWER_AGAIN = Change(
    {"lower.txt": "lower layer, revised\n"}, b"lower: revise\n", PARENT_AUTHOR
)
FOURTH = Change({"fourth.txt": "fourth layer\n"}, b"fourth: add\n", FIRST_AUTHOR)
BASE_FILES = {
    ".stack-prs.yaml": STACK_POLICY,
    "README.md": "base\n",
    "shared.txt": SHARED,
}
LANDED_FILES = {
    **BASE_FILES,
    "lower.txt": "lower layer\n",
    "upper.txt": "upper layer\n",
}
PARENTS: dict[int, int | None] = {11: None, 12: 11, 13: 12}
SELECTED = {11, 12}


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> LifecycleClock:
    """No real sleeps: every graph or lifecycle monitoring poll ends its window."""
    monkeypatch.setattr(lifecycle, "POLL_INTERVAL", 0.0)
    skipping = LifecycleClock()
    monkeypatch.setattr(lifecycle, "time", skipping)
    monkeypatch.setattr(graph, "time", skipping)
    monkeypatch.setattr(native_stack, "time", skipping)
    return skipping


def stack_world(tmp_path: Path, lower: list[Change]) -> GraphWorld:
    """Native stack 7 on main: #11 stack/layer1 (``lower``), #12 stack/layer2 and
    #13 stack/layer3."""
    world = build_world(tmp_path)
    forge = NativeStackForge(world.bare)
    world.forge = forge
    world.open_pr(11, "stack/layer1", TRUNK, lower)
    world.open_pr(12, "stack/layer2", "stack/layer1", [UPPER])
    world.open_pr(13, "stack/layer3", "stack/layer2", [TOP])
    forge.stacks = {STACK: [11, 12, 13]}
    return world


@pytest.fixture
def world(tmp_path: Path) -> GraphWorld:
    return stack_world(tmp_path, [LOWER])


def native(world: GraphWorld) -> NativeStackForge:
    return cast(NativeStackForge, world.forge)


def run_id(result: Result) -> str:
    return cast(str, result["run_id"])


def rows(result: Result, key: str) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", result[key])


def block(result: Result) -> dict[str, object]:
    return cast("dict[str, object]", result["native"])


def record(world: GraphWorld, run: str) -> NativeRecord:
    found = world.journal(run).native
    assert found is not None, "the graph run journaled no native request"
    return found


def landings(world: GraphWorld, run: str) -> dict[int, tuple[str | None, bool]]:
    """Every journaled scope landing and whether it was proved."""
    native_record = record(world, run)
    return {
        member.pr: (member.landing, member.verified)
        for member in native_record.members
        if member.pr in native_record.scope
    }


def start(
    world: GraphWorld, endpoint: Endpoint = "clean", *, selected: set[int] = SELECTED
) -> tuple[Result, int]:
    return world.run(world.plan(PARENTS, selected), endpoint)


def untouched(world: GraphWorld) -> tuple[object, ...]:
    """Remote and local refs and the trunk: nothing landed, pushed or deleted."""
    return (
        git(world.bare, "for-each-ref", "refs/heads"),
        git(world.work, "for-each-ref", "refs/heads"),
    )


def assert_never_rewritten(world: GraphWorld) -> None:
    """This controller pushed, retargeted and edited no pull request."""
    assert world.git.pushes == []
    assert (world.forge.retarget_calls, world.forge.patches) == ([], [])


def assert_retained_upper_verified(world: GraphWorld, old_top: str) -> None:
    """#13 stays open on the trunk with its exact own slice and nothing else, at
    exactly the head the provider's rebase wrote; this run rewrote nothing."""
    upper = world.forge.current(13)
    tip = world.remote(TRUNK)
    assert tip is not None
    assert (upper.state, upper.base_ref) == ("OPEN", TRUNK)
    assert upper.head_sha != old_top
    assert is_ancestor(world.bare, tip, upper.head_sha)
    expected = {**tree_files(world.bare, tip), "top.txt": "top layer\n"}
    assert tree_files(world.bare, upper.head_sha) == expected
    assert world.remote("stack/layer3") == native(world).rebased[13]
    assert world.local("stack/layer3") == old_top
    assert_never_rewritten(world)


# -- the one request ----------------------------------------------------------------


def test_direct_prefix_lands_through_one_request_and_retains_the_upper(
    world: GraphWorld,
) -> None:
    forge = native(world)
    upper_head = world.remote("stack/layer2")
    top_head = world.remote("stack/layer3")
    assert upper_head is not None and top_head is not None

    result, code = start(world)

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert forge.puts == [(12, upper_head, "squash", "direct_merge")]
    assert forge.merge_calls == []
    first, second = forge.landing(11), forge.landing(12)
    tip = world.remote(TRUNK)
    assert git(world.bare, "rev-parse", f"{second}^") == first
    assert tip == second
    assert tree_files(world.bare, second) == LANDED_FILES
    assert_retained_upper_verified(world, top_head)
    assert result["usable_checkout"] == {
        "path": str(world.work),
        "head": tip,
        "branch": TRUNK,
    }
    for branch in ("stack/layer1", "stack/layer2"):
        assert (world.remote(branch), world.local(branch)) == (None, None)
    run = run_id(result)
    native_record = record(world, run)
    assert native_record.request.state == "ACCEPTED"
    assert native_record.request.uuid == forge.requests[0].uuid
    assert landings(world, run) == {11: (first, True), 12: (second, True)}
    journal = world.journal(run)
    for number in (11, 12):
        receipt = world.receipt(journal.node(number).run_id)
        assert (receipt.status, receipt.merge_sha) == (
            "COMPLETE",
            forge.landing(number),
        )
    report = block(result)
    assert (report["scope"], report["retained"]) == ([11, 12], [13])
    assert (report["merge_action"], report["method_sent"]) == ("direct_merge", True)
    verified = cast("list[dict[str, object]]", report["retained_verification"])
    assert [(row["pr"], row["head"]) for row in verified] == [
        (13, world.forge.current(13).head_sha)
    ]


def test_queue_landing_spans_resumes_and_enqueued_is_never_a_landing(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.queue, forge.auto_tick = True, False
    upper_head = world.remote("stack/layer2")
    top_head = world.remote("stack/layer3")
    assert upper_head is not None and top_head is not None

    first, code = start(world)

    assert (code, first["status"]) == (3, "WAITING"), first
    assert forge.puts == [(12, upper_head, None, "merge_queue")]
    run = run_id(first)
    forge.tick()  # the request is queued; nothing has landed
    queued, code = world.resume(run, "clean")
    assert (code, queued["status"]) == (3, "WAITING"), queued
    assert record(world, run).request.status == "enqueued"
    assert landings(world, run) == {11: (None, False), 12: (None, False)}
    assert world.remote(TRUNK) == world.base

    forge.tick()  # the first merge group lands #11 alone
    partial, code = world.resume(run, "clean")
    assert (code, partial["status"]) == (3, "WAITING"), partial
    assert landings(world, run) == {11: (forge.landing(11), True), 12: (None, False)}

    forge.tick()  # the second, independent group lands #12
    final, code = world.resume(run, "clean")

    assert (code, final["status"]) == (0, "COMPLETE"), final
    assert len(forge.puts) == 1
    assert record(world, run).request.status == "enqueued"
    assert landings(world, run) == {
        11: (forge.landing(11), True),
        12: (forge.landing(12), True),
    }
    assert tree_files(world.bare, forge.landing(12)) == LANDED_FILES
    assert_retained_upper_verified(world, top_head)
    report = block(final)
    assert (report["merge_action"], report["merge_method"]) == ("merge_queue", None)
    assert (report["method_sent"], report["packet_merge_method"]) == (False, "squash")


def test_unrelated_trunk_move_between_queue_groups_still_proves_each_landing(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.queue, forge.auto_tick = True, False
    first, _ = start(world)
    run = run_id(first)
    forge.tick()
    forge.tick()  # #11 lands
    unrelated = world.actor_push(TRUNK, {"unrelated.txt": "other work\n"}, "other")
    forge.tick()  # #12 lands on top of the unrelated commit

    result, code = world.resume(run, "clean")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert git(world.bare, "rev-parse", f"{forge.landing(12)}^") == unrelated
    assert landings(world, run) == {
        11: (forge.landing(11), True),
        12: (forge.landing(12), True),
    }
    assert tree_files(world.bare, forge.landing(12)) == {
        **LANDED_FILES,
        "unrelated.txt": "other work\n",
    }


def test_landed_tree_beyond_the_own_slice_needs_judgment_before_cleanup(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.landing_fault[12] = {"lower.txt": "rewritten by the landing\n"}
    lower_head = world.remote("stack/layer1")

    result, code = start(world)

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    run = run_id(result)
    assert landings(world, run) == {
        11: (forge.landing(11), True),
        12: (forge.landing(12), False),
    }
    assert world.store().list_runs() == ()
    assert world.remote("stack/layer1") == lower_head
    assert len(forge.puts) == 1


def test_open_lower_member_outside_the_selection_is_never_requested(
    world: GraphWorld,
) -> None:
    forge = native(world)
    before = untouched(world)

    result, code = start(world, selected={12})

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert result["run_id"] is None
    assert forge.puts == []
    assert untouched(world) == before
    assert not world.store().graph_directory.exists()


def test_selected_head_moved_at_dispatch_is_refused_and_never_resent(
    world: GraphWorld,
) -> None:
    forge = native(world)
    moved: list[str] = []

    def late_push() -> None:
        moved.append(world.actor_push("stack/layer2", {"upper.txt": "late\n"}, "late"))

    forge.before_put = late_push

    result, code = start(world)

    assert (code, result["status"]) == (3, "WAITING"), result
    run = run_id(result)
    assert record(world, run).request.state == "REJECTED"
    assert forge.requests == []
    assert world.remote(TRUNK) == world.base
    assert world.remote("stack/layer2") == moved[0]

    again, code = world.resume(run, "clean")

    assert (code, again["status"]) == (4, "NEEDS_JUDGMENT"), again
    assert len(forge.puts) == 1
    assert forge.current(12).state == "OPEN"


def test_uncertain_request_is_reconciled_from_facts_and_never_resent(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.put_fault = "applied_lost"
    forge.auto_tick = False
    top_head = world.remote("stack/layer3")
    assert top_head is not None

    first, code = start(world)

    assert (code, first["status"]) == (4, "NEEDS_JUDGMENT"), first
    run = run_id(first)
    assert (record(world, run).request.state, record(world, run).request.uuid) == (
        "UNKNOWN",
        None,
    )
    assert len(forge.requests) == 1

    unseen, code = world.resume(run, "clean")

    assert (code, unseen["status"]) == (4, "NEEDS_JUDGMENT"), unseen
    assert len(forge.puts) == 1
    forge.tick()  # the lost request lands the prefix after all

    landed, code = world.resume(run, "clean")

    assert (code, landed["status"]) == (0, "COMPLETE"), landed
    assert len(forge.puts) == 1
    assert record(world, run).request.state == "UNKNOWN"
    assert landings(world, run) == {
        11: (forge.landing(11), True),
        12: (forge.landing(12), True),
    }
    assert_retained_upper_verified(world, top_head)


@pytest.mark.parametrize(
    ("method", "adopted"), [("squash", True), ("merge", False)], ids=["same", "other"]
)
def test_request_already_in_flight_is_adopted_only_with_the_exact_options(
    world: GraphWorld, method: str, adopted: bool
) -> None:
    forge = native(world)
    upper_head = world.remote("stack/layer2")
    assert upper_head is not None
    existing = forge.existing(12, upper_head, method, "direct_merge")

    result, code = start(world)

    assert len(forge.puts) == 1
    assert forge.requests == [existing]
    run = run_id(result)
    request = record(world, run).request
    if adopted:
        assert (code, result["status"]) == (0, "COMPLETE"), result
        assert (request.state, request.uuid) == ("ACCEPTED", existing.uuid)
        assert forge.current(12).state == "MERGED"
    else:
        assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
        assert (request.state, request.uuid) == ("REJECTED", None)
        assert forge.current(12).state == "OPEN"
        assert world.remote(TRUNK) == world.base

        again, code = world.resume(run, "clean")

        assert (code, again["status"]) == (5, "BLOCKED"), again
        assert len(forge.puts) == 1
        assert forge.current(12).state == "OPEN"
        forge.tick()  # the other actor's request lands the prefix after all
        journal = world.journal(run)
        before = snapshot(world.work, world.bare)
        preview = inspect_graph(
            world.git, world.forge, journal_plan(journal), "clean", journal=journal
        )
        assert [(row["status"], row["pr"]) for row in rows(preview, "blockers")] == [
            ("NEEDS_JUDGMENT", 11)
        ]
        assert snapshot(world.work, world.bare) == before

        landed, code = world.resume(run, "clean")

        assert (code, landed["status"]) == (4, "NEEDS_JUDGMENT"), landed
        assert len(forge.puts) == 1
        assert world.store().list_runs() == ()


def test_failed_request_keeps_the_proved_landing_and_is_never_retried(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.fail_after = 1
    upper_head = world.remote("stack/layer2")

    result, code = start(world)

    assert (code, result["status"]) == (5, "BLOCKED"), result
    run = run_id(result)
    request = record(world, run).request
    assert (request.status, request.message) == ("failed", forge.fail_message)
    assert landings(world, run) == {11: (forge.landing(11), True), 12: (None, False)}
    assert forge.current(12).state == "OPEN"
    assert world.remote("stack/layer2") == upper_head

    again, code = world.resume(run, "clean")

    assert (code, again["status"]) == (5, "BLOCKED"), again
    assert len(forge.puts) == 1
    assert len(forge.requests) == 1
    assert landings(world, run)[11] == (forge.landing(11), True)


@pytest.mark.parametrize("fault", ["drift", "extra"])
def test_retained_upper_that_lost_its_exact_slice_needs_judgment_before_cleanup(
    world: GraphWorld, fault: str
) -> None:
    forge = native(world)
    forge.rebase_fault = "drift" if fault == "drift" else "extra"
    lower_head = world.remote("stack/layer1")
    upper_head = world.remote("stack/layer2")

    result, code = start(world)

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    rebased = forge.current(13)
    assert (rebased.state, world.remote("stack/layer3")) == ("OPEN", rebased.head_sha)
    run = run_id(result)
    assert landings(world, run) == {
        11: (forge.landing(11), True),
        12: (forge.landing(12), True),
    }
    assert world.store().list_runs() == ()
    assert (world.remote("stack/layer1"), world.remote("stack/layer2")) == (
        lower_head,
        upper_head,
    )
    assert world.journal(run).node(13).head_sha != rebased.head_sha


def test_post_merge_failure_keeps_the_landing_and_resumes_without_a_request(
    world: GraphWorld,
) -> None:
    forge = native(world)
    flag = world.root / "accepted.flag"
    check = "import pathlib, sys; sys.exit(not pathlib.Path(sys.argv[1]).exists())"
    command = [sys.executable, "-c", check, str(flag)]
    plan = world.plan(
        PARENTS, SELECTED, decisions={11: {"post_merge_commands": [command]}}
    )
    lower_head = world.remote("stack/layer1")

    first, code = world.run(plan, "clean")

    assert (code, first["status"]) == (5, "BLOCKED"), first
    run = run_id(first)
    assert (forge.current(11).state, forge.current(12).state) == ("MERGED", "MERGED")
    receipt = world.receipt(world.journal(run).node(11).run_id)
    assert (receipt.merge_verified, receipt.validation_sha) == (True, None)
    assert world.remote("stack/layer1") == lower_head
    flag.write_text("accepted\n")

    resumed, code = world.resume(run, "clean")

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert len(forge.puts) == 1
    assert len(forge.requests) == 1
    assert world.remote("stack/layer1") is None


def test_completed_native_run_reverifies_without_any_write(world: GraphWorld) -> None:
    forge = native(world)
    result, code = start(world)
    assert (code, result["status"]) == (0, "COMPLETE"), result
    saved = state(world.common() / "armory")
    refs = (git(world.bare, "for-each-ref"), git(world.work, "for-each-ref"))

    again, code = world.resume(run_id(result), "clean")

    assert (code, again["status"]) == (0, "COMPLETE"), again
    assert (again["mutation_attempted"], again["mutation_performed"]) == (False, False)
    assert state(world.common() / "armory") == saved
    assert (git(world.bare, "for-each-ref"), git(world.work, "for-each-ref")) == refs
    assert len(forge.puts) == 1


def test_pr_endpoint_only_observes_a_native_selection(world: GraphWorld) -> None:
    forge = native(world)
    before = snapshot(world.work, world.bare)

    result, code = start(world, "pr")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert result["run_id"] is None
    assert forge.puts == []
    assert snapshot(world.work, world.bare) == before
    assert block(result)["scope"] == [11, 12]


def queued(world: GraphWorld) -> str:
    """A queue request for #12 is sent and nothing has landed; the run id."""
    forge = native(world)
    forge.queue, forge.auto_tick = True, False
    first, code = start(world)
    assert (code, first["status"]) == (3, "WAITING"), first
    assert len(forge.puts) == 1
    return run_id(first)


def test_crash_after_dispatch_is_reconciled_as_unknown_and_never_resent(
    world: GraphWorld,
) -> None:
    forge = native(world)

    def interrupt() -> None:
        raise KeyboardInterrupt

    forge.before_put = interrupt

    first, code = start(world)

    assert (code, first["status"]) == (130, "WAITING"), first
    run = run_id(first)
    assert record(world, run).request.state == "DISPATCHING"

    again, code = world.resume(run, "clean")

    assert (code, again["status"]) == (4, "NEEDS_JUDGMENT"), again
    request = record(world, run).request
    assert (request.state, request.uuid) == ("UNKNOWN", None)
    assert len(forge.puts) == 1
    assert forge.current(12).state == "OPEN"
    assert world.remote(TRUNK) == world.base


def test_request_the_provider_no_longer_reports_is_decided_by_pull_requests(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.auto_tick = False
    first, code = start(world)
    assert (code, first["status"]) == (3, "WAITING"), first
    run = run_id(first)
    forge.expired = True
    forge.tick()  # the request lands the prefix; its status read is now a 404

    result, code = world.resume(run, "clean")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert block(result)["request_read"] is not None
    assert record(world, run).request.status == "pending"
    assert landings(world, run) == {
        11: (forge.landing(11), True),
        12: (forge.landing(12), True),
    }
    assert len(forge.puts) == 1


def test_too_short_a_window_sends_nothing_and_the_request_stays_planned(
    world: GraphWorld,
) -> None:
    forge = native(world)

    result, code = world.run(world.plan(PARENTS, SELECTED), "clean", wait=5.0)

    assert (code, result["status"]) == (3, "WAITING"), result
    run = run_id(result)
    request = record(world, run).request
    assert (request.state, request.dispatched_at) == ("PLANNED", None)
    assert forge.puts == []

    again, code = world.resume(run, "clean")

    assert (code, again["status"]) == (0, "COMPLETE"), again
    assert len(forge.puts) == 1


def test_immediate_enqueued_answer_without_an_id_is_followed_by_pull_requests(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.queue, forge.auto_tick, forge.immediate = True, False, True

    first, code = start(world)

    assert (code, first["status"]) == (3, "WAITING"), first
    run = run_id(first)
    request = record(world, run).request
    assert (request.state, request.uuid, request.status) == (
        "ACCEPTED",
        None,
        "enqueued",
    )
    for _ in range(3):
        forge.tick()  # queued, then one merge group per member

    final, code = world.resume(run, "clean")

    assert (code, final["status"]) == (0, "COMPLETE"), final
    assert len(forge.puts) == 1
    assert landings(world, run) == {
        11: (forge.landing(11), True),
        12: (forge.landing(12), True),
    }


def test_answer_without_the_exact_options_is_unknown_and_never_resent(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.echo_fault, forge.auto_tick = True, False

    result, code = start(world)

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    run = run_id(result)
    request = record(world, run).request
    assert (request.state, request.uuid) == ("UNKNOWN", None)

    again, code = world.resume(run, "clean")

    assert (code, again["status"]) == (4, "NEEDS_JUDGMENT"), again
    assert len(forge.puts) == 1
    assert forge.current(12).state == "OPEN"


# -- landing and retention proofs -------------------------------------------------


def test_multi_commit_rebase_landing_is_proved_over_the_trunk_before_it(
    tmp_path: Path,
) -> None:
    world = stack_world(tmp_path, [LOWER, LOWER_AGAIN])
    forge = native(world)
    upper_head = world.remote("stack/layer2")
    plan = world.plan(PARENTS, SELECTED, decisions={12: {"merge_method": "rebase"}})

    result, code = world.run(plan, "clean")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert forge.puts == [(12, upper_head, "rebase", "direct_merge")]
    first = forge.landing(11)
    assert git(world.bare, "rev-list", "--count", f"{world.base}..{first}") == "2"
    assert tree_files(world.bare, forge.landing(12)) == {
        **LANDED_FILES,
        "lower.txt": "lower layer, revised\n",
    }
    assert landings(world, run_id(result)) == {
        11: (first, True),
        12: (forge.landing(12), True),
    }


def test_retained_upper_the_provider_has_not_rebased_yet_is_awaited(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.rebase_fault = "lag"
    top_head = world.remote("stack/layer3")
    assert top_head is not None

    first, code = start(world)

    assert (code, first["status"]) == (3, "WAITING"), first
    run = run_id(first)
    assert landings(world, run) == {
        11: (forge.landing(11), True),
        12: (forge.landing(12), True),
    }
    assert world.store().list_runs() == ()
    forge.rebase_fault = "none"
    forge.rebase_open(12)

    final, code = world.resume(run, "clean")

    assert (code, final["status"]) == (0, "COMPLETE"), final
    assert len(forge.puts) == 1
    assert_retained_upper_verified(world, top_head)


def test_retargeted_upper_whose_fork_landed_by_merge_is_kept_untouched(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.rebase_fault = "retarget"
    top_head = world.remote("stack/layer3")
    plan = world.plan(PARENTS, SELECTED, decisions={12: {"merge_method": "merge"}})

    result, code = world.run(plan, "clean")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    upper = forge.current(13)
    assert (upper.state, upper.base_ref, upper.head_sha) == ("OPEN", TRUNK, top_head)
    verified = rows(block(result), "retained_verification")
    assert [(row["pr"], row["verification"]) for row in verified] == [
        (13, "untouched on the trunk")
    ]
    assert_never_rewritten(world)


@pytest.mark.parametrize(
    ("fault", "code", "status"),
    [("none", 0, "COMPLETE"), ("lowest", 3, "WAITING")],
    ids=["chain-rebased", "upper-left-behind"],
)
def test_higher_retained_member_must_sit_on_the_member_below_it(
    world: GraphWorld, fault: Literal["none", "lowest"], code: int, status: str
) -> None:
    forge = native(world)
    fourth = world.open_pr(14, "stack/layer4", "stack/layer3", [FOURTH])
    forge.stacks = {STACK: [11, 12, 13, 14]}
    forge.rebase_fault = fault

    result, exit_code = world.run(world.plan({**PARENTS, 14: 13}, SELECTED), "clean")

    assert (exit_code, result["status"]) == (code, status), result
    assert world.journal(run_id(result)).node(13).head_sha == forge.rebased[13]
    if fault == "none":
        assert world.journal(run_id(result)).node(14).head_sha == forge.rebased[14]
        files = tree_files(world.bare, forge.rebased[14])
        assert (files["top.txt"], files["fourth.txt"]) == (
            "top layer\n",
            "fourth layer\n",
        )
    else:
        assert world.remote("stack/layer4") == fourth
        assert world.store().list_runs() == ()
    assert len(forge.puts) == 1
    assert_never_rewritten(world)


def test_retained_member_off_the_selected_head_is_refused_before_any_request(
    world: GraphWorld,
) -> None:
    forge = native(world)
    lower = world.local("stack/layer1")
    assert lower is not None
    off = world.write(lower, TOP)
    git(world.work, "push", "-q", "-f", "origin", f"{off}:refs/heads/stack/layer3")
    plan = world.plan(PARENTS, SELECTED)
    before = snapshot(world.work, world.bare)

    preview = inspect_graph(world.git, world.forge, plan, "clean")

    blockers = rows(preview, "blockers")
    assert [(row["status"], row["pr"]) for row in blockers] == [("NEEDS_JUDGMENT", 13)]
    retained = rows(block(preview), "retained_preview")
    assert [(row["pr"], row["proof"]) for row in retained] == [
        (13, "not a strict ancestor")
    ]
    assert snapshot(world.work, world.bare) == before

    result, code = world.run(plan, "clean")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert result["run_id"] is None
    assert forge.puts == []
    assert world.remote(TRUNK) == world.base


@pytest.mark.parametrize("gap", ["selected", "retained"])
def test_unrestacked_native_chain_has_same_stop_in_preview_and_execution(
    world: GraphWorld, gap: str
) -> None:
    forge = native(world)
    parents = dict(PARENTS)
    if gap == "retained":
        world.open_pr(14, "stack/layer4", "stack/layer3", [FOURTH])
        forge.stacks = {STACK: [11, 12, 13, 14]}
        parents[14] = 13
    changed_ref = "stack/layer1" if gap == "selected" else "stack/layer3"
    old = world.remote(changed_ref)
    assert old is not None
    changed = world.write(
        old,
        Change({"extra.txt": "new lower head\n"}, b"lower: advance\n", FIRST_AUTHOR),
    )
    git(world.work, "push", "-q", "-f", "origin", f"{changed}:refs/heads/{changed_ref}")
    plan = world.plan(parents, SELECTED)
    before = snapshot(world.work, world.bare)
    stopped_pr = 12 if gap == "selected" else 14

    preview = inspect_graph(world.git, world.forge, plan, "clean")

    assert [(row["status"], row["pr"]) for row in rows(preview, "blockers")] == [
        ("NEEDS_JUDGMENT", stopped_pr)
    ]
    assert snapshot(world.work, world.bare) == before

    result, code = world.run(plan, "clean")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert result["run_id"] is None
    assert forge.puts == []
    assert world.remote(TRUNK) == world.base


def test_retained_member_changed_after_its_proof_never_blocks_the_cleanup(
    world: GraphWorld,
) -> None:
    forge = native(world)
    flag = world.root / "accepted.flag"
    check = "import pathlib, sys; sys.exit(not pathlib.Path(sys.argv[1]).exists())"
    command = [sys.executable, "-c", check, str(flag)]
    plan = world.plan(
        PARENTS, SELECTED, decisions={11: {"post_merge_commands": [command]}}
    )
    first, code = world.run(plan, "clean")
    assert (code, first["status"]) == (5, "BLOCKED"), first
    run = run_id(first)
    # The operator keeps working on the retained PR after its retention was proved.
    revised = world.actor_push("stack/layer3", {"top.txt": "top, revised\n"}, "rev")
    flag.write_text("accepted\n")

    resumed, code = world.resume(run, "clean")

    assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert [row["pr"] for row in rows(resumed, "retained_changes")] == [13]
    assert (world.remote("stack/layer3"), forge.current(13).state) == (revised, "OPEN")
    assert len(forge.puts) == 1
    assert_never_rewritten(world)


# -- contradictions after the request ---------------------------------------------


@pytest.mark.parametrize(
    "case",
    ["stack-number", "membership", "landed-above-open", "head-moved"],
)
def test_contradiction_after_the_request_needs_judgment_without_a_resend(
    world: GraphWorld, case: str
) -> None:
    forge = native(world)
    run = queued(world)
    if case == "stack-number":
        forge.stacks = {STACK + 1: [11, 12, 13]}
    elif case == "membership":
        world.open_pr(14, "stack/layer4", "stack/layer3", [FOURTH])
        forge.stacks[STACK].append(14)
    elif case == "landed-above-open":
        upper = forge.current(12)
        forge.pulls[12].state = "MERGED"
        forge.pulls[12].landed = (upper.head_sha, upper.base_sha, upper.head_sha)
    else:
        world.actor_push("stack/layer1", {"lower.txt": "moved\n"}, "moved")

    result, code = world.resume(run, "clean")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert len(forge.puts) == 1
    assert forge.merge_calls == []
    assert world.store().list_runs() == ()


def test_native_run_whose_selection_stopped_being_native_never_runs_manually(
    world: GraphWorld,
) -> None:
    forge = native(world)
    run = queued(world)
    forge.stacks = {}

    result, code = world.resume(run, "clean")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert len(forge.puts) == 1
    assert forge.merge_calls == []
    assert world.git.pushes == []


def test_manual_run_whose_selection_became_native_never_runs_natively(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.stacks = {}
    forge.held.add(11)
    first, code = start(world)
    assert (code, first["status"]) == (3, "WAITING"), first
    run = run_id(first)
    assert world.journal(run).intents
    forge.stacks = {STACK: [11, 12, 13]}

    result, code = world.resume(run, "clean")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert (forge.puts, forge.merge_calls) == ([], [])
    assert world.journal(run).native is None


# -- refused before any write -------------------------------------------------------


@pytest.mark.parametrize("case", ["mixed", "two-stacks", "unknown-identity"])
def test_unclassifiable_selection_is_blocked_before_any_write(
    world: GraphWorld, case: str
) -> None:
    forge = native(world)
    if case == "mixed":
        forge.stacks = {STACK: [11]}
    elif case == "two-stacks":
        forge.stacks = {STACK: [11], STACK + 1: [12, 13]}
    else:
        forge.unknown = {12}
    before = untouched(world)

    result, code = start(world)

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert result["run_id"] is None
    assert (forge.puts, forge.merge_calls) == ([], [])
    assert untouched(world) == before
    assert not world.store().graph_directory.exists()


@pytest.mark.parametrize("case", ["unknown-policy", "method-not-allowed"])
def test_unresolved_trunk_policy_is_blocked_before_any_write(
    world: GraphWorld, case: str
) -> None:
    forge = native(world)
    if case == "unknown-policy":
        forge.policy_known = False
    else:
        forge.methods = ("merge",)
    before = untouched(world)

    result, code = start(world)

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert result["run_id"] is None
    assert forge.puts == []
    assert untouched(world) == before


# -- read-only inspection ------------------------------------------------------------


@pytest.mark.parametrize(
    ("queue", "action", "method"),
    [(False, "direct_merge", "squash"), (True, "merge_queue", None)],
    ids=["direct", "queue"],
)
def test_dry_run_previews_the_native_request_without_any_write(
    world: GraphWorld, queue: bool, action: str, method: str | None
) -> None:
    forge = native(world)
    forge.queue = queue
    upper_head = world.remote("stack/layer2")
    before = snapshot(world.work, world.bare)

    preview = inspect_graph(
        world.git, world.forge, world.plan(PARENTS, SELECTED), "clean"
    )

    assert preview["status"] == "PLANNED"
    assert rows(preview, "blockers") == []
    actions = rows(preview, "actions")
    assert [(row["action"], row["pr"]) for row in actions] == [
        ("native-merge", 12),
        ("verify-landing", 11),
        ("verify-landing", 12),
        ("verify-retained", 13),
        ("cleanup", 11),
        ("cleanup", 12),
    ]
    request = actions[0]
    assert (request["prefix"], request["expected_head"]) == ([11, 12], upper_head)
    assert (request["merge_action"], request["merge_method"]) == (action, method)
    retained = cast("list[dict[str, object]]", block(preview)["retained_preview"])
    assert [(row["pr"], row["proof"]) for row in retained] == [(13, "strict ancestor")]
    assert forge.puts == []
    assert snapshot(world.work, world.bare) == before


@pytest.mark.parametrize(
    ("case", "first_action", "code", "status"),
    [
        (
            "unknown-landed",
            {"action": "reconcile-request", "state": "UNKNOWN", "outcome": "landed"},
            0,
            "COMPLETE",
        ),
        (
            "unknown-unseen",
            {"action": "reconcile-request", "state": "UNKNOWN", "landed": []},
            4,
            "NEEDS_JUDGMENT",
        ),
        ("failed", {"action": "await-landings", "status": "failed"}, 5, "BLOCKED"),
    ],
)
def test_dry_run_of_a_journaled_request_reports_the_stop_its_resume_makes(
    world: GraphWorld,
    case: str,
    first_action: dict[str, object],
    code: int,
    status: str,
) -> None:
    forge = native(world)
    if case == "failed":
        forge.fail_after = 1  # #11 lands, then the request fails with #12 open
    else:
        forge.put_fault, forge.auto_tick = "applied_lost", False
    first, _ = start(world)
    run = run_id(first)
    if case == "unknown-landed":
        forge.tick()  # the lost request lands the prefix after all
    journal = world.journal(run)
    saved = state(world.common() / "armory")
    before = snapshot(world.work, world.bare)

    preview = inspect_graph(
        world.git, world.forge, journal_plan(journal), "clean", journal=journal
    )

    assert (preview["status"], preview["run_id"]) == ("PLANNED", run)
    request = rows(preview, "actions")[0]
    assert {key: request[key] for key in first_action} == first_action
    blockers = rows(preview, "blockers")
    stops = [] if status == "COMPLETE" else [(status, 12)]
    assert [(row["status"], row["pr"]) for row in blockers] == stops
    if case == "failed":
        assert forge.fail_message in str(blockers[0]["reason"])
    assert snapshot(world.work, world.bare) == before
    assert state(world.common() / "armory") == saved

    result, exit_code = world.resume(run, "clean")

    assert (exit_code, result["status"]) == (code, status), result
    assert len(forge.puts) == 1
    assert len(forge.requests) == 1


def test_planned_request_whose_prefix_landed_elsewhere_has_same_preview_stop(
    world: GraphWorld,
) -> None:
    forge = native(world)
    first, code = world.run(world.plan(PARENTS, SELECTED), "clean", wait=5.0)
    assert (code, first["status"]) == (3, "WAITING"), first
    run = run_id(first)
    journal = world.journal(run)
    assert record(world, run).request.state == "PLANNED"
    forge.rebase_fault = "lag"
    forge.existing(12, forge.current(12).head_sha, "squash", "direct_merge")
    forge.tick()
    before = snapshot(world.work, world.bare)
    saved = state(world.common() / "armory")

    preview = inspect_graph(
        world.git, world.forge, journal_plan(journal), "clean", journal=journal
    )

    assert [(row["status"], row["pr"]) for row in rows(preview, "blockers")] == [
        ("NEEDS_JUDGMENT", 12)
    ]
    assert snapshot(world.work, world.bare) == before
    assert state(world.common() / "armory") == saved

    result, code = world.resume(run, "clean")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert forge.puts == []
    assert len(forge.requests) == 1
    assert world.store().list_runs() == ()


def test_dry_run_of_a_prefix_another_request_landed_checks_no_retained_member(
    world: GraphWorld,
) -> None:
    forge = native(world)
    forge.auto_tick = False
    upper_head = world.remote("stack/layer2")
    assert upper_head is not None
    forge.existing(12, upper_head, "squash", "direct_merge")
    forge.tick()  # another actor's request lands #11 and #12; #13 is rebased
    rebased = forge.rebased[13]
    # Every head is local, so a retained check would prove #13 off the old head.
    git(world.work, "fetch", "-q", "origin")
    plan = world.plan(PARENTS, SELECTED)
    before = snapshot(world.work, world.bare)

    preview = inspect_graph(world.git, world.forge, plan, "clean")

    assert preview["status"] == "PLANNED"
    assert rows(preview, "blockers") == []
    report = block(preview)
    assert (report["scope"], report["gates"], report["retained_preview"]) == (
        [],
        [],
        [],
    )
    assert [(row["action"], row["pr"]) for row in rows(preview, "actions")] == [
        ("verify-landing", 11),
        ("verify-landing", 12),
        ("cleanup", 11),
        ("cleanup", 12),
    ]
    assert snapshot(world.work, world.bare) == before

    result, code = world.run(plan, "clean")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert (forge.puts, forge.merge_calls) == ([], [])
    retained = forge.current(13)
    assert (retained.state, retained.head_sha) == ("OPEN", rebased)
    for branch in ("stack/layer1", "stack/layer2"):
        assert world.remote(branch) is None
    assert_never_rewritten(world)


# -- the development CLI in the target checkout ---------------------------------------


def cli(
    world: GraphWorld,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, Result]:
    """``ship.main`` in process, with the target checkout as working directory.

    Git and the provider are patched to this world's stateful models, so the
    script's own by-path bootstrap is not exercised here.
    """
    monkeypatch.chdir(world.work)
    monkeypatch.setattr(ship, "GitRepository", MappedGit)
    monkeypatch.setattr(ship, "GitHub", lambda host, repo, deadline: world.forge)
    monkeypatch.setattr(sys, "argv", ["ship.py", *argv])
    capsys.readouterr()
    code = ship.main()
    return code, json.loads(capsys.readouterr().out)


def test_cli_lands_and_inspects_a_native_stack_from_the_target_checkout(
    world: GraphWorld,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forge = native(world)
    packets = world.root / "packets"
    packets.mkdir()
    path = packets / "native.json"
    path.write_text(json.dumps(world.packet(PARENTS, SELECTED)))

    code, result = cli(
        world, monkeypatch, capsys, "--stack-plan", str(path), "--until", "merged"
    )

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert len(forge.puts) == 1
    assert block(result)["selected"] == 12
    run = run_id(result)
    before = snapshot(world.work, world.bare)

    code, preview = cli(world, monkeypatch, capsys, "--resume", run, "--dry-run")

    assert (code, preview["status"]) == (0, "PLANNED"), preview
    assert preview["run_id"] == run
    request = cast("dict[str, object]", block(preview)["request"])
    assert request["state"] == "ACCEPTED"
    assert snapshot(world.work, world.bare) == before
    assert len(forge.puts) == 1


def test_single_pr_path_keeps_an_open_native_member_blocked(
    world: GraphWorld,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forge = native(world)
    pr = forge.current(11)
    policy = world.root / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": ["CONTRIBUTING.md#merging"],
                "expected_checks": ["tests"],
                "merge_method": "squash",
                "post_merge_commands": [],
                "head_sha": pr.head_sha,
                "base_sha": pr.base_sha,
            }
        )
    )
    before = untouched(world)

    code, result = cli(
        world,
        monkeypatch,
        capsys,
        "--pr",
        "11",
        "--repo",
        REPO,
        "--until",
        "merged",
        "--policy",
        str(policy),
    )

    assert (code, result["status"]) == (5, "BLOCKED"), result
    assert (forge.puts, forge.merge_calls) == ([], [])
    assert forge.current(11).state == "OPEN"
    assert untouched(world) == before
    assert world.store().list_runs() == ()
