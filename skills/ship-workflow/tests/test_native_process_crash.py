"""Hard process death at native intent boundaries against real Git.

The provider is the existing stateful stand-in, not vendor evidence. Killing the
controller bypasses KeyboardInterrupt handling: only its durable journal remains.
"""

from __future__ import annotations

import os
import signal
from typing import Literal

import pytest
import test_native_stack as native_cases
from graph_world import GraphWorld
from state_store import GraphJournal, Store
from test_execution import git

isolated_git = native_cases.isolated_git
clock = native_cases.clock
world = native_cases.world

pytestmark = pytest.mark.skipif(os.name != "posix", reason="process death needs POSIX")


@pytest.mark.parametrize("boundary", ["PLANNED", "DISPATCHING"])
def test_native_hard_death_resumes_only_definitely_undispatched_intent(
    world: GraphWorld, boundary: Literal["PLANNED", "DISPATCHING"]
) -> None:
    forge = native_cases.native(world)
    old_refs = git(world.bare, "for-each-ref")
    old_heads = {number: forge.current(number).head_sha for number in (11, 12, 13)}
    dispatch_witness = world.root / "child-native-dispatch"
    child = os.fork()
    if child == 0:
        forge.before_put = dispatch_witness.touch
        save_graph = Store.save_graph

        def save_and_die(store: Store, journal: GraphJournal) -> None:
            save_graph(store, journal)
            if journal.native is not None and journal.native.request.state == boundary:
                os.kill(os.getpid(), signal.SIGKILL)

        Store.save_graph = save_and_die
        try:
            native_cases.start(world)
        finally:
            os._exit(71)

    _, termination = os.waitpid(child, 0)
    assert os.WIFSIGNALED(termination) and os.WTERMSIG(termination) == signal.SIGKILL
    graphs = world.store().list_graphs()
    assert len(graphs) == 1
    interrupted = graphs[0]
    assert interrupted.native is not None
    assert interrupted.native.request.state == boundary
    assert interrupted.native.request.uuid is None
    assert git(world.bare, "for-each-ref") == old_refs
    assert not dispatch_witness.exists()

    if boundary == "DISPATCHING":
        saved = native_cases.state(world.common() / "armory")
        before = native_cases.snapshot(world.work, world.bare)
        preview = native_cases.inspect_graph(
            world.git,
            world.forge,
            native_cases.journal_plan(interrupted),
            "clean",
            journal=interrupted,
        )
        assert [
            (row["status"], row["pr"]) for row in native_cases.rows(preview, "blockers")
        ] == [("NEEDS_JUDGMENT", 12)]
        assert native_cases.snapshot(world.work, world.bare) == before
        assert native_cases.state(world.common() / "armory") == saved
        assert (
            native_cases.record(world, interrupted.run_id).request.state
            == "DISPATCHING"
        )

    resumed, code = world.resume(interrupted.run_id, "clean")

    if boundary == "PLANNED":
        assert (code, resumed["status"]) == (0, "COMPLETE"), resumed
        assert len(forge.puts) == 1 and len(forge.requests) == 1
        assert (forge.current(11).state, forge.current(12).state) == (
            "MERGED",
            "MERGED",
        )
        assert forge.current(13).state == "OPEN"
        assert world.remote("stack/layer1") is None
        assert world.remote("stack/layer2") is None
    else:
        assert (code, resumed["status"]) == (4, "NEEDS_JUDGMENT"), resumed
        settled = native_cases.record(world, interrupted.run_id).request
        assert (settled.state, settled.uuid) == ("UNKNOWN", None)
        assert forge.puts == [] and forge.requests == []
        assert git(world.bare, "for-each-ref") == old_refs
        assert {
            number: forge.current(number).head_sha for number in (11, 12, 13)
        } == old_heads
        assert (forge.current(11).state, forge.current(12).state) == ("OPEN", "OPEN")
