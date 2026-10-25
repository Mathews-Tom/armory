"""Guarded source-only renewal exercised through real refs and provider consumers.

GraphForge is a deterministic provider fixture, not evidence of vendor behavior.
Git capture, per-commit conflict proof, approved trees, replay and leased pushes
all run against a real bare remote and checkout. No production proof is mocked.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import cast

import pytest
import ship
import test_execution as execution
from graph import (
    StackPlan,
    StackPlanError,
    execute_graph,
    inspect_graph,
    journal_plan,
    new_journal,
    parse_stack_plan,
)
from graph_world import Change, GraphWorld, NativeStackForge, build_world, tree_files
from state_store import GraphJournal, ReceiptInputError
from test_cli_stack_plan import snapshot
from test_execution import REPO, git, heads, is_ancestor
from test_graph_execution import (
    CHILD,
    PAIR,
    PARENT,
    gate_policy,
    mutations,
    parent_and_child,
    python_gate,
    rows,
    run_id,
)
from test_graph_git import (
    FIRST_AUTHOR,
    PARENT_AUTHOR,
    commit_parts,
    edit_line,
    git_bytes,
)

isolated_git = execution.isolated_git
pytestmark = pytest.mark.skipif(os.name != "posix", reason="journals require POSIX")

TRUNK_EDIT = {"trunk.txt": "new trunk source\n"}
CONFLICT = Change(
    {"shared.txt": edit_line(5, "line five from PR"), "own.txt": "own source\n"},
    b"renew: own source\n\nStack-Id: stack-7\nStack-Position: 1",
    FIRST_AUTHOR,
)
TAIL = Change({"tail.txt": "tail source\n"}, b"renew: tail\n", PARENT_AUTHOR)


@pytest.fixture
def world(tmp_path: Path) -> GraphWorld:
    return build_world(tmp_path)


def commits(world: GraphWorld, below: str, tip: str) -> list[str]:
    return git(world.work, "rev-list", "--reverse", f"{below}..{tip}").splitlines()


def preserved(world: GraphWorld, original: list[str], replayed: list[str]) -> None:
    """Slice length and each author/message/encoding are part of the guarantee."""
    assert len(replayed) == len(original)
    assert [commit_parts(world.work, oid) for oid in replayed] == [
        commit_parts(world.work, oid) for oid in original
    ]


def source_only(world: GraphWorld, expected: dict[str, str]) -> None:
    """Prove refs still exist, rather than relying on an absent delete-call log."""
    assert heads(world.bare) == {
        f"refs/heads/{name}": oid for name, oid in expected.items()
    }
    for name in expected:
        if name != "main":
            assert world.local(name) is not None
    assert world.forge.merge_calls == []
    for pull in world.forge.pulls.values():
        assert pull.state in ("OPEN", "MERGED")


def conflict_world(
    world: GraphWorld, *, tail: bool = True
) -> tuple[str, str, list[str], str]:
    changes = [CONFLICT, TAIL] if tail else [CONFLICT]
    old = world.open_pr(11, "stack/p", "main", changes)
    originals = commits(world, world.base, old)
    onto = world.actor_push(
        "main",
        {"shared.txt": edit_line(5, "line five from trunk"), **TRUNK_EDIT},
        "trunk: concurrent source",
    )
    git(world.work, "fetch", "-q", "origin")
    # Independent, explicitly reviewed result preserves both contributors. The
    # approval applies to the first conflicting commit only, not the clean tail.
    reviewed = world.write(
        onto,
        Change(
            {
                "shared.txt": edit_line(5, "line five from trunk and PR"),
                "own.txt": "own source\n",
            },
            b"review-only tree carrier\n",
            FIRST_AUTHOR,
        ),
    )
    tree = git(world.work, "rev-parse", f"{reviewed}^{{tree}}")
    return old, onto, originals, tree


def approval(
    world: GraphWorld, old: str, onto: str, original: str, tree: str
) -> dict[str, object]:
    return {
        "fork": world.base,
        "old_head": old,
        "onto": onto,
        "commits": [{"old": original, "tree": tree}],
        "sources": ["review/renewal-source.diff", "reviewer: approved combined source"],
    }


def reviewed_packet(
    world: GraphWorld, resolution: dict[str, object]
) -> dict[str, object]:
    packet = world.packet({11: None}, {11}, forks={11: world.base})
    cast(list[dict[str, object]], packet["nodes"])[0]["resolution"] = resolution
    return packet


def assert_refusal(
    world: GraphWorld, packet: dict[str, object], old: str, onto: str
) -> None:
    before = world.forge.current(11)
    try:
        plan = parse_stack_plan(packet)
    except StackPlanError:
        pass
    else:
        result, code = world.run(plan, "renewed")
        assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert mutations(world) == ([], [], [], [])
    assert world.forge.current(11) == before
    source_only(world, {"main": onto, "stack/p": old})


@pytest.mark.parametrize("encoded", [False, True])
def test_open_parent_and_child_are_renewed_parent_first_without_landing(
    world: GraphWorld, encoded: bool
) -> None:
    parent, child = parent_and_child(world)
    if encoded:
        raw = git_bytes(world.work, "cat-file", "commit", child)
        header, _, _ = raw.partition(b"\n\n")
        raw = (
            header
            + b"\nencoding ISO-8859-1\n\nchild: caf\xe9\n\nStack-Id: stack-7\nStack-Position: 2"
        )
        child = (
            git_bytes(
                world.work, "hash-object", "-t", "commit", "-w", "--stdin", stdin=raw
            )
            .decode("ascii")
            .strip()
        )
        git(world.work, "branch", "-f", "stack/c", child)
        git(world.work, "push", "-q", "--force", "origin", "stack/c")
    old_child_slice = commits(world, parent, child)
    onto = world.actor_push("main", TRUNK_EDIT, "trunk: advance")
    metadata = world.forge.metadata()
    plan = world.plan(PAIR, {11, 12}, forks={11: world.base})

    result, code = world.run(plan, "renewed")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    new_parent = world.remote("stack/p")
    new_child = world.remote("stack/c")
    assert new_parent is not None and new_child is not None
    assert world.local("stack/p") == new_parent
    assert world.local("stack/c") == new_child
    assert new_parent != parent and new_child != child
    assert git(world.work, "rev-parse", f"{new_parent}^") == onto
    assert is_ancestor(world.work, new_parent, new_child)
    preserved(world, [parent], commits(world, onto, new_parent))
    preserved(world, old_child_slice, commits(world, new_parent, new_child))
    assert tree_files(world.work, new_child) == {
        **tree_files(world.work, child),
        **TRUNK_EDIT,
    }
    assert world.git.pushes == [
        ("stack/p", parent, new_parent),
        ("stack/c", child, new_child),
    ]
    assert world.forge.current(11).state == world.forge.current(12).state == "OPEN"
    assert world.forge.current(11).base_ref == "main"
    assert world.forge.current(12).base_ref == "stack/p"
    assert world.forge.retarget_calls == []
    assert world.forge.metadata() == metadata
    journal = world.journal(run_id(result))
    assert journal.endpoint == "renewed" and journal.status == "COMPLETE"
    assert journal.renewal is not None
    assert journal.renewal["completed"] == [
        {"pr": 11, "head": new_parent, "base": "main", "onto": onto},
        {"pr": 12, "head": new_child, "base": "stack/p", "onto": new_parent},
    ]
    assert all(intent.kind != "merge" for intent in journal.intents)
    source_only(world, {"main": onto, "stack/p": new_parent, "stack/c": new_child})


def test_unselected_open_parent_requires_scope_judgment_before_publication(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)
    onto = world.actor_push("main", TRUNK_EDIT, "trunk: advance")

    result, code = world.run(world.plan(PAIR, {12}), "renewed")

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert mutations(world) == ([], [], [], [])
    assert world.forge.current(12).base_ref == "stack/p"
    source_only(world, {"main": onto, "stack/p": parent, "stack/c": child})


@pytest.mark.parametrize("boundary", ["missing", "unrelated", "valid"])
def test_already_current_root_requires_a_provable_source_boundary(
    world: GraphWorld, boundary: str
) -> None:
    old = world.open_pr(11, "stack/p", "main", [PARENT])
    fork = world.base
    if boundary == "missing":
        fork = "f" * 40
    elif boundary == "unrelated":
        fork = world.write(
            world.base,
            Change(
                {"unrelated.txt": "other source\n"}, b"other source\n", PARENT_AUTHOR
            ),
        )
        assert not is_ancestor(world.work, fork, old)
    before = heads(world.bare)

    result, code = world.run(world.plan({11: None}, {11}, forks={11: fork}), "renewed")

    if boundary == "valid":
        assert (code, result["status"]) == (0, "COMPLETE"), result
        stored = snapshot(world.work, world.bare)
        resumed, resumed_code = world.resume(run_id(result), "renewed")
        assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
        assert snapshot(world.work, world.bare) == stored
    else:
        assert code != 0 and result["status"] != "COMPLETE", result
    assert heads(world.bare) == before
    source_only(world, {"main": world.base, "stack/p": old})


def test_conflict_without_review_refuses_before_push(world: GraphWorld) -> None:
    old, onto, _, _ = conflict_world(world)
    packet = world.packet({11: None}, {11}, forks={11: world.base})
    assert_refusal(world, packet, old, onto)


def test_reviewed_conflict_tree_and_clean_tail_preserve_both_sources(
    world: GraphWorld,
) -> None:
    old, onto, originals, tree = conflict_world(world)
    resolution = approval(world, old, onto, originals[0], tree)
    plan = parse_stack_plan(reviewed_packet(world, resolution))

    result, code = world.run(plan, "renewed")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    new = world.remote("stack/p")
    assert new is not None and new != old
    assert world.local("stack/p") == new
    replayed = commits(world, onto, new)
    preserved(world, originals, replayed)
    assert git(world.work, "rev-parse", f"{replayed[0]}^{{tree}}") == tree
    assert tree_files(world.work, new) == {
        **tree_files(world.work, onto),
        "shared.txt": edit_line(5, "line five from trunk and PR"),
        "own.txt": "own source\n",
        "tail.txt": "tail source\n",
    }
    assert world.git.pushes == [("stack/p", old, new)]
    saved = world.journal(run_id(result))
    assert journal_plan(saved).identity == plan.identity
    assert journal_plan(saved).canonical() == plan.canonical()
    source_only(world, {"main": onto, "stack/p": new})


@pytest.mark.parametrize(
    "wrong",
    [
        "fork",
        "old_head",
        "onto",
        "commit",
        "duplicate",
        "nonconflicting",
        "extraneous",
        "missing",
        "missing-tree",
        "nonexistent-tree",
        "blob-tree",
        "no-sources",
        "reordered",
    ],
)
def test_invalid_review_evidence_cannot_publish(world: GraphWorld, wrong: str) -> None:
    old, onto, originals, tree = conflict_world(world)
    resolution = approval(world, old, onto, originals[0], tree)
    entries = cast(list[dict[str, object]], resolution["commits"])
    if wrong == "fork":
        resolution["fork"] = originals[0]
    elif wrong == "old_head":
        resolution["old_head"] = originals[0]
    elif wrong == "onto":
        resolution["onto"] = world.base
    elif wrong == "commit":
        entries[0]["old"] = world.base
    elif wrong == "duplicate":
        entries.append(dict(entries[0]))
    elif wrong == "nonconflicting":
        entries[:] = [{"old": originals[1], "tree": tree}]
    elif wrong == "extraneous":
        entries.append({"old": originals[1], "tree": tree})
    elif wrong == "missing":
        entries.clear()
    elif wrong == "missing-tree":
        del entries[0]["tree"]
    elif wrong == "nonexistent-tree":
        entries[0]["tree"] = "f" * 40
    elif wrong == "blob-tree":
        entries[0]["tree"] = git(world.work, "rev-parse", f"{onto}:README.md")
    elif wrong == "no-sources":
        resolution["sources"] = []
    else:
        entries.insert(0, {"old": originals[1], "tree": tree})
    assert_refusal(world, reviewed_packet(world, resolution), old, onto)


def test_review_cannot_replace_a_mechanically_clean_replay(world: GraphWorld) -> None:
    old = world.open_pr(11, "stack/p", "main", [PARENT])
    onto = world.actor_push("main", TRUNK_EDIT, "trunk: advance")
    git(world.work, "fetch", "-q", "origin")
    tree = git(world.work, "rev-parse", f"{onto}^{{tree}}")
    # This would erase the PR if an approval could override a clean proof.
    resolution = approval(world, old, onto, old, tree)
    assert_refusal(world, reviewed_packet(world, resolution), old, onto)


def test_unselected_node_cannot_carry_review_authority(world: GraphWorld) -> None:
    parent, child = parent_and_child(world)
    packet = world.packet(PAIR, {12})
    cast(list[dict[str, object]], packet["nodes"])[0]["resolution"] = approval(
        world,
        parent,
        world.base,
        parent,
        git(world.work, "rev-parse", f"{parent}^{{tree}}"),
    )
    with pytest.raises(StackPlanError):
        parse_stack_plan(packet)
    assert mutations(world) == ([], [], [], [])
    source_only(world, {"main": world.base, "stack/p": parent, "stack/c": child})


def historical(
    world: GraphWorld, *, reachable: bool, native: bool = False
) -> tuple[StackPlan, str, str, str]:
    if native:
        forge = NativeStackForge(world.bare)
        forge.stacks[7] = [10, 11]
        world.forge = forge
    world.open_pr(
        10,
        "stack/a",
        "main",
        [Change({"ancestor.txt": "ancestor\n"}, b"ancestor\n", PARENT_AUTHOR)],
    )
    parent = world.open_pr(11, "stack/p", "stack/a", [PARENT])
    child = world.open_pr(12, "stack/c", "stack/p", CHILD)
    parent_merge = world.forge.land(11, "merge")
    if reachable:
        trunk = world.forge.land(10, "merge")
    else:
        # Observe #10 as landed first, but its historical nontrunk child merge
        # remains off trunk. A state label alone must not authorize adoption.
        pull = world.forge.pulls[10]
        original = git(world.work, "rev-parse", "stack/a")
        tree = git(world.bare, "rev-parse", f"{original}^{{tree}}")
        trunk = git(
            world.bare, "commit-tree", tree, "-p", world.base, "-m", "ancestor squash"
        )
        git(world.bare, "update-ref", "refs/heads/main", trunk)
        pull.state, pull.landed = "MERGED", (original, world.base, trunk)
    plan = world.plan({10: None, 11: 10, 12: 11}, {12})
    return plan, parent, child, parent_merge


@pytest.mark.parametrize("native", [False, True])
def test_historical_nontrunk_merged_ancestor_is_adopted_from_exact_observation(
    world: GraphWorld, native: bool
) -> None:
    plan, parent, child, merge = historical(world, reachable=True, native=native)
    trunk = world.remote("main")
    assert trunk is not None and is_ancestor(world.bare, merge, trunk)
    original = world.forge.current(11)
    preview = inspect_graph(world.git, world.forge, plan, "renewed")
    assert preview["findings"] == [], preview

    result, code = world.run(plan, "renewed")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    new = world.remote("stack/c")
    assert new is not None and new != child
    assert world.local("stack/c") == new
    preserved(world, commits(world, parent, child), commits(world, trunk, new))
    assert tree_files(world.work, new) == tree_files(world.work, child)
    assert world.forge.current(11) == original
    assert world.forge.current(12).state == "OPEN"
    assert world.forge.current(12).base_ref == "main"
    assert world.forge.patches == [(12, "main")]
    journal = world.journal(run_id(result))
    assert journal.renewal is not None
    ancestors = cast(list[dict[str, object]], journal.renewal["ancestors"])
    assert next(row for row in ancestors if row["pr"] == 11) == {
        "pr": 11,
        "head": original.head_sha,
        "base": original.base_ref,
        "merge": merge,
        "trunk": trunk,
    }
    assert all(intent.kind != "merge" for intent in journal.intents)
    source_only(
        world,
        {
            "main": trunk,
            "stack/a": cast(str, world.remote("stack/a")),
            "stack/p": parent,
            "stack/c": new,
        },
    )


@pytest.mark.parametrize("native", [False, True])
def test_off_trunk_historical_merge_is_not_adopted(
    world: GraphWorld, native: bool
) -> None:
    plan, parent, child, merge = historical(world, reachable=False, native=native)
    trunk = world.remote("main")
    assert trunk is not None and not is_ancestor(world.bare, merge, trunk)
    before = heads(world.bare)

    result, code = world.run(plan, "renewed")

    assert code != 0 and result["status"] != "COMPLETE", result
    assert heads(world.bare) == before
    assert world.local("stack/p") == parent and world.local("stack/c") == child
    assert mutations(world) == ([], [], [], [])


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("moved", ["head", "base", "merge"])
def test_historical_adoption_resume_rejects_changed_original_identity(
    world: GraphWorld, moved: str, native: bool
) -> None:
    plan, _, _, _ = historical(world, reachable=True, native=native)
    world.git.push_fault = "applied_lost"
    result, code = world.run(plan, "renewed")
    assert (code, result["status"]) == (3, "WAITING"), result
    pull = world.forge.pulls[11]
    assert pull.landed is not None
    head, base, merge = pull.landed
    if moved == "head":
        pull.landed = (world.base, base, merge)
    elif moved == "base":
        pull.base_ref = "main"
    else:
        pull.landed = (head, base, cast(str, world.remote("main")))
    before = mutations(world)
    published = heads(world.bare)

    resumed, resumed_code = world.resume(run_id(result), "renewed")

    assert resumed_code != 0 and resumed["status"] != "COMPLETE", resumed
    assert mutations(world) == before
    assert heads(world.bare) == published
    assert world.forge.current(12).base_ref == "stack/p"


def test_renewed_dry_run_does_not_write_objects_refs_journal_or_provider(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)
    world.actor_push("main", TRUNK_EDIT, "trunk: advance")
    git(world.work, "fetch", "-q", "origin")
    plan = world.plan(PAIR, {11, 12}, forks={11: world.base})
    before = snapshot(world.work, world.bare)

    preview = inspect_graph(world.git, world.forge, plan, "renewed")

    assert preview["status"] == "PLANNED", preview
    assert snapshot(world.work, world.bare) == before
    assert mutations(world) == ([], [], [], [])
    assert world.remote("stack/p") == parent and world.remote("stack/c") == child
    assert world.forge.current(11).state == world.forge.current(12).state == "OPEN"


def test_local_gates_run_on_proposal_and_refuse_before_publication(
    world: GraphWorld,
) -> None:
    old = world.open_pr(11, "stack/p", "main", [PARENT])
    onto = world.actor_push("main", TRUNK_EDIT, "trunk: advance")
    marker = world.root / "gate-observations.txt"
    gate = (
        "import pathlib,subprocess,sys; "
        "head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(); "
        "remote=subprocess.check_output(['git','--git-dir',sys.argv[2],'rev-parse','refs/heads/stack/p'],text=True).strip(); "
        "pathlib.Path(sys.argv[1]).write_text(head+' '+remote); sys.exit(7)"
    )
    gates = gate_policy(python_gate("reject_source", gate, marker, world.bare))
    plan = world.plan({11: None}, {11}, forks={11: world.base})

    result, code = world.run(plan, "renewed", gates=gates)

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    proposed, published = marker.read_text().split()
    assert proposed != old and published == old
    assert git(world.work, "rev-parse", f"{proposed}^") == onto
    assert tree_files(world.work, proposed) == {
        **tree_files(world.work, old),
        **TRUNK_EDIT,
    }
    assert mutations(world) == ([], [], [], [])
    source_only(world, {"main": onto, "stack/p": old})


def test_push_applied_lost_response_resumes_without_resend_or_merge(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)
    landing = world.forge.land(11, "squash")
    world.git.push_fault = "applied_lost"
    plan = world.plan(PAIR, {12})

    result, code = world.run(plan, "renewed")

    assert (code, result["status"]) == (3, "WAITING"), result
    new = world.remote("stack/c")
    assert new is not None and new != child
    assert world.local("stack/c") == child
    assert world.forge.current(12).base_ref == "stack/p"
    assert world.forge.retarget_calls == [] and world.forge.merge_calls == []
    [pending] = rows(result, "pending_intents")
    assert (
        pending["kind"],
        pending["outcome"],
        pending["expected_old"],
        pending["new"],
    ) == ("rewrite-push", "PENDING", child, new)

    resumed, resumed_code = world.resume(run_id(result), "renewed")

    assert (resumed_code, resumed["status"]) == (0, "COMPLETE"), resumed
    assert world.local("stack/c") == new
    assert world.git.pushes == [("stack/c", child, new)]
    assert world.forge.patches == [(12, "main")]
    assert world.forge.current(12).state == "OPEN"
    assert git(world.work, "rev-parse", f"{new}~2") == landing
    confirmed = [
        intent
        for intent in world.journal(run_id(result)).intents
        if intent.kind == "rewrite-push"
    ]
    assert [(intent.outcome, intent.actual) for intent in confirmed] == [
        ("CONFIRMED", new)
    ]
    source_only(world, {"main": landing, "stack/p": parent, "stack/c": new})


@pytest.mark.parametrize("change", ["endpoint", "resolution", "sources"])
def test_resume_cannot_change_frozen_endpoint_or_review_authority(
    world: GraphWorld, change: str
) -> None:
    old, onto, originals, tree = conflict_world(world)
    packet = reviewed_packet(world, approval(world, old, onto, originals[0], tree))
    plan = parse_stack_plan(packet)
    world.git.push_fault = "applied_lost"
    result, code = world.run(plan, "renewed")
    assert (code, result["status"]) == (3, "WAITING"), result
    journal = world.journal(run_id(result))
    if change != "endpoint":
        changed = copy.deepcopy(packet)
        resolution = cast(
            dict[str, object],
            cast(list[dict[str, object]], changed["nodes"])[0]["resolution"],
        )
        if change == "resolution":
            cast(list[dict[str, object]], resolution["commits"])[0]["tree"] = git(
                world.work, "rev-parse", f"{old}^{{tree}}"
            )
        else:
            resolution["sources"] = ["different reviewer authority"]
        plan = parse_stack_plan(changed)
        assert plan.identity != journal.plan_identity
    calls = mutations(world)
    refs = heads(world.bare)

    stored = snapshot(world.work, world.bare)
    with pytest.raises(StackPlanError):
        execute_graph(
            world.git,
            world.forge,
            plan,
            "merged" if change == "endpoint" else "renewed",
            120.0,
            world.store(),
            journal,
        )

    assert snapshot(world.work, world.bare) == stored
    assert mutations(world) == calls and heads(world.bare) == refs
    assert world.forge.current(11).state == "OPEN"


@pytest.mark.parametrize("move", ["none", "head", "base", "parent"])
def test_completed_resume_reverifies_live_head_base_and_parent_without_mutation(
    world: GraphWorld, move: str
) -> None:
    parent_and_child(world)
    world.actor_push("main", TRUNK_EDIT, "trunk: advance")
    result, code = world.run(
        world.plan(PAIR, {11, 12}, forks={11: world.base}), "renewed"
    )
    assert (code, result["status"]) == (0, "COMPLETE"), result
    if move == "head":
        world.actor_push(
            "stack/c", {"external.txt": "external\n"}, "external: child move"
        )
    elif move == "base":
        world.forge.pulls[12].base_ref = "main"
    elif move == "parent":
        world.actor_push(
            "stack/p", {"external.txt": "external\n"}, "external: parent move"
        )
    before = mutations(world)
    refs = heads(world.bare)
    stored = snapshot(world.work, world.bare)

    resumed, resumed_code = world.resume(run_id(result), "renewed")

    expected = (0, "COMPLETE") if move == "none" else (4, "NEEDS_JUDGMENT")
    assert (resumed_code, resumed["status"]) == expected, resumed
    assert mutations(world) == before and heads(world.bare) == refs
    assert world.forge.current(11).state == world.forge.current(12).state == "OPEN"
    if move == "none":
        assert snapshot(world.work, world.bare) == stored


def test_journal_cannot_claim_renewed_complete_without_renewal_evidence(
    world: GraphWorld,
) -> None:
    parent_and_child(world)
    plan = world.plan(PAIR, {11, 12}, forks={11: world.base})
    journal = new_journal(
        plan,
        run_id="a" * 32,
        endpoint="pr",
        code_identity="b" * 64,
        created_at="2026-10-21T00:00:00+00:00",
    )
    raw = journal.serialize()
    raw["endpoint"] = "renewed"
    raw["status"] = "COMPLETE"
    with pytest.raises(ReceiptInputError):
        GraphJournal.parse(raw)


@pytest.mark.parametrize("native", [False, True])
def test_cli_renewed_refuses_nonstack_and_native_without_ref_changes(
    world: GraphWorld,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    native: bool,
) -> None:
    if native:
        forge = NativeStackForge(world.bare)
        world.forge = forge
    head = world.open_pr(11, "stack/p", "main", [PARENT])
    args = ["--until", "renewed", "--wait-timeout", "1"]
    if native:
        forge.stacks[7] = [11]
        path = world.root / "native-plan.json"
        path.write_text(
            json.dumps(world.packet({11: None}, {11}, forks={11: world.base}))
        )
        args.extend(["--stack-plan", str(path)])
    else:
        args.extend(["--pr", "11", "--repo", REPO])
    monkeypatch.chdir(world.work)
    monkeypatch.setattr(ship, "GitRepository", lambda *a, **kw: world.git)
    monkeypatch.setattr(ship, "GitHub", lambda *a, **kw: world.forge)
    monkeypatch.setattr(sys, "argv", ["ship.py", *args])
    before = heads(world.bare)

    code = ship.main()

    captured = capsys.readouterr()
    assert code != 0, captured.out
    assert "renewed" in (captured.out + captured.err).lower()
    if native:
        result = json.loads(captured.out)
        assert result["status"] == "BLOCKED"
        assert forge.requests == []
    assert heads(world.bare) == before
    assert world.remote("stack/p") == world.local("stack/p") == head
    assert world.forge.current(11).state == "OPEN"
    assert mutations(world) == ([], [], [], [])


@pytest.mark.parametrize(
    "review", ["ordered", "reversed", "missing-first", "missing-second"]
)
def test_multiple_conflicts_use_original_order_and_one_destination_binding(
    world: GraphWorld,
    review: str,
) -> None:
    second = Change(
        {
            "shared.txt": edit_line(
                6, "line six from PR", CONFLICT.files["shared.txt"]
            ),
            "second-own.txt": "second own source\n",
        },
        b"renew: second conflict\n\nStack-Id: stack-7\nStack-Position: 1\n",
        PARENT_AUTHOR,
    )
    old = world.open_pr(11, "stack/p", "main", [CONFLICT, second])
    originals = commits(world, world.base, old)
    trunk_text = edit_line(
        6, "line six from trunk", edit_line(5, "line five from trunk")
    )
    onto = world.actor_push(
        "main", {"shared.txt": trunk_text, **TRUNK_EDIT}, "trunk: two conflicts"
    )
    git(world.work, "fetch", "-q", "origin")
    first_text = edit_line(5, "line five from trunk and PR", trunk_text)
    first = world.write(
        onto,
        Change(
            {"shared.txt": first_text, "own.txt": "own source\n"},
            b"review carrier one\n",
            FIRST_AUTHOR,
        ),
    )
    final_text = edit_line(6, "line six from trunk and PR", first_text)
    final = world.write(
        first,
        Change(
            {"shared.txt": final_text, "second-own.txt": "second own source\n"},
            b"review carrier two\n",
            FIRST_AUTHOR,
        ),
    )
    entries = [
        {"old": original, "tree": git(world.work, "rev-parse", f"{reviewed}^{{tree}}")}
        for original, reviewed in zip(originals, [first, final], strict=True)
    ]
    resolution = approval(world, old, onto, originals[0], entries[0]["tree"])
    if review == "reversed":
        entries.reverse()
    elif review == "missing-first":
        entries.pop(0)
    elif review == "missing-second":
        entries.pop()
    resolution["commits"] = entries
    packet = reviewed_packet(world, resolution)
    if review != "ordered":
        assert_refusal(world, packet, old, onto)
        return

    result, code = world.run(parse_stack_plan(packet), "renewed")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    new = world.remote("stack/p")
    assert new is not None
    replayed = commits(world, onto, new)
    preserved(world, originals, replayed)
    assert [git(world.work, "rev-parse", f"{oid}^{{tree}}") for oid in replayed] == [
        entry["tree"] for entry in entries
    ]
    assert tree_files(world.work, new) == tree_files(world.work, final)
    assert world.git.pushes == [("stack/p", old, new)]
    source_only(world, {"main": onto, "stack/p": new})


def test_already_present_patch_refuses_instead_of_implicitly_dropping_a_commit(
    world: GraphWorld,
) -> None:
    first = Change({"same.txt": "already on trunk\n"}, b"own: first\n", FIRST_AUTHOR)
    second = Change({"own.txt": "still own\n"}, b"own: second", PARENT_AUTHOR)
    old = world.open_pr(11, "stack/p", "main", [first, second])
    originals = commits(world, world.base, old)
    onto = world.actor_push("main", first.files, "trunk: independently identical patch")

    result, code = world.run(
        world.plan({11: None}, {11}, forks={11: world.base}), "renewed"
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert len(originals) == 2
    assert commits(world, world.base, old) == originals
    assert mutations(world) == ([], [], [], [])
    assert world.local("stack/p") == old
    source_only(world, {"main": onto, "stack/p": old})


def test_dirty_invoking_checkout_preserves_user_source_and_refuses_publication(
    world: GraphWorld,
) -> None:
    old = world.open_pr(11, "stack/p", "main", [PARENT])
    onto = world.actor_push("main", TRUNK_EDIT, "trunk: advance")
    (world.work / "README.md").write_text("uncommitted user source\n")
    before = git_bytes(world.work, "diff", "--binary")

    result, code = world.run(
        world.plan({11: None}, {11}, forks={11: world.base}), "renewed"
    )

    assert (code, result["status"]) == (4, "NEEDS_JUDGMENT"), result
    assert git_bytes(world.work, "diff", "--binary") == before
    assert (world.work / "README.md").read_text() == "uncommitted user source\n"
    assert mutations(world) == ([], [], [], [])
    source_only(world, {"main": onto, "stack/p": old})


def test_child_conflict_can_continue_with_new_exact_parent_bound_authority(
    world: GraphWorld,
) -> None:
    parent, child = parent_and_child(world)
    child_originals = commits(world, parent, child)
    trunk_shared = edit_line(
        5, "line five from trunk", edit_line(1, "line one from trunk")
    )
    onto = world.actor_push(
        "main", {"shared.txt": trunk_shared, **TRUNK_EDIT}, "trunk: both conflicts"
    )
    git(world.work, "fetch", "-q", "origin")
    parent_shared = edit_line(1, "line one from parent and trunk", trunk_shared)
    parent_review = world.write(
        onto,
        Change(
            {"shared.txt": parent_shared, "parent.txt": "parent work\n"},
            b"parent review carrier\n",
            PARENT_AUTHOR,
        ),
    )
    packet = world.packet(PAIR, {11, 12}, forks={11: world.base})
    cast(list[dict[str, object]], packet["nodes"])[0]["resolution"] = approval(
        world,
        parent,
        onto,
        parent,
        git(world.work, "rev-parse", f"{parent_review}^{{tree}}"),
    )

    partial, partial_code = world.run(parse_stack_plan(packet), "renewed")

    assert partial_code != 0 and partial["status"] != "COMPLETE", partial
    renewed_parent = world.remote("stack/p")
    assert renewed_parent is not None and renewed_parent != parent
    assert world.remote("stack/c") == child
    old_run = run_id(partial)
    old_evidence = world.journal(old_run).serialize()
    assert all(intent.outcome != "PENDING" for intent in world.journal(old_run).intents)
    child_shared = edit_line(5, "line five from child and trunk", parent_shared)
    child_review = world.write(
        renewed_parent,
        Change(
            {"shared.txt": child_shared, "child.txt": "child one\n"},
            b"child review carrier\n",
            FIRST_AUTHOR,
        ),
    )
    replacement = world.packet(PAIR, {11, 12}, forks={11: onto, 12: parent})
    resolution = approval(
        world,
        child,
        renewed_parent,
        child_originals[0],
        git(world.work, "rev-parse", f"{child_review}^{{tree}}"),
    )
    resolution["fork"] = parent
    cast(list[dict[str, object]], replacement["nodes"])[1]["resolution"] = resolution

    complete, complete_code = world.run(parse_stack_plan(replacement), "renewed")

    assert (complete_code, complete["status"]) == (0, "COMPLETE"), complete
    assert world.remote("stack/p") == renewed_parent
    renewed_child = world.remote("stack/c")
    assert renewed_child is not None and renewed_child != child
    assert [ref for ref, _, _ in world.git.pushes] == ["stack/p", "stack/c"]
    assert world.journal(old_run).serialize() == old_evidence
    preserved(world, [parent], commits(world, onto, renewed_parent))
    preserved(world, child_originals, commits(world, renewed_parent, renewed_child))
    assert tree_files(world.work, renewed_child)["shared.txt"] == child_shared
    assert world.forge.current(12).base_ref == "stack/p"
    assert world.forge.current(11).state == world.forge.current(12).state == "OPEN"
    source_only(
        world, {"main": onto, "stack/p": renewed_parent, "stack/c": renewed_child}
    )
