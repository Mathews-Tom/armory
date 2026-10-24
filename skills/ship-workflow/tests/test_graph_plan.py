"""Stack plan packets: one explicit, bounded graph decision validated before any run."""

from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from graph import (
    PlanNode,
    Provenance,
    StackPlanError,
    decision_identity,
    load_stack_plan,
    parse_stack_plan,
    topology_differences,
)
from lifecycle import parse_decision

Payload = dict[str, object]
Change = Callable[[Payload], object]

PROVENANCE_SOURCES = [
    "published commit trailers Stack-Id and Stack-Position",
    ".stack-prs.yaml (operator-authored)",
]


def oid(number: int) -> str:
    return f"{number:040x}"


def decision(**changes: object) -> Payload:
    value: Payload = {
        "sources": ["CONTRIBUTING.md#merging", "ci/required-checks.md"],
        "expected_checks": ["test", "lint"],
        "merge_method": "squash",
        "post_merge_commands": [["uv", "run", "pytest", "-q"]],
    }
    value.update(changes)
    return value


def node(
    pr: int,
    parent: int | None,
    ref: str,
    base: str,
    *,
    select: bool = True,
    repo: str = "owner/repo",
) -> Payload:
    row: Payload = {
        "pr": pr,
        "parent": parent,
        "select": select,
        "head": {"repo": repo, "ref": ref, "sha": oid(pr)},
        "base": base,
    }
    if select:
        row["decision"] = decision()
        row["provenance"] = {
            "disposition": "preserve",
            "sources": list(PROVENANCE_SOURCES),
        }
    return row


def packet(*nodes: Payload, repository: str = "owner/repo") -> Payload:
    return {
        "schema_version": 1,
        "repository": repository,
        "trunk": "main",
        "nodes": list(nodes),
    }


def linear() -> Payload:
    return packet(
        node(11, None, "feat/a", "main"),
        node(12, 11, "feat/b", "feat/a"),
        node(13, 12, "feat/c", "feat/b"),
    )


def branching() -> Payload:
    """Parent-first order differs from PR numbering; one sibling is unselected."""
    return packet(
        node(42, 41, "feat/a", "feat/right", repo="contrib/repo"),
        node(37, 38, "feat/left-child", "feat/left"),
        node(39, 40, "feat/retained", "feat/root", select=False),
        node(41, 40, "feat/right", "feat/root"),
        node(40, None, "feat/root", "main"),
        node(38, 40, "feat/left", "feat/root"),
    )


def write(directory: Path, data: object, name: str = "stack-plan.json") -> Path:
    path = directory / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def rows(data: Payload) -> list[Payload]:
    return cast("list[Payload]", data["nodes"])


def at(data: Payload, pr: int) -> Payload:
    return next(row for row in rows(data) if row["pr"] == pr)


def numbers(nodes: tuple[PlanNode, ...]) -> list[int]:
    return [item.pr for item in nodes]


# --- valid graphs -------------------------------------------------------------------------


def test_linear_packet_loads_parent_first_with_bound_decisions(tmp_path: Path) -> None:
    plan = load_stack_plan(write(tmp_path, linear()))

    assert (plan.host, plan.repo, plan.trunk) == ("github.com", "owner/repo", "main")
    assert numbers(plan.order()) == [11, 12, 13]
    assert numbers(plan.children(None)) == [11]
    assert numbers(plan.children(11)) == [12]
    assert plan.children(13) == ()
    assert plan.ancestors(13) == (12, 11)
    assert plan.ancestors(11) == ()
    assert plan.unselected_ancestors(13) == ()
    middle = plan.node(12)
    assert (middle.parent, middle.head_ref, middle.head_sha, middle.base_ref) == (
        11,
        "feat/b",
        oid(12),
        "feat/a",
    )
    assert middle.fork is None
    assert middle.decision == parse_decision(decision())
    assert middle.provenance == Provenance("preserve", tuple(PROVENANCE_SOURCES))
    assert re.fullmatch(r"[0-9a-f]{64}", plan.identity)
    assert re.fullmatch(r"[0-9a-f]{64}", plan.topology)
    assert plan.identity != plan.topology


def test_branching_packet_orders_siblings_parent_first(tmp_path: Path) -> None:
    plan = load_stack_plan(write(tmp_path, branching()))

    assert numbers(plan.nodes) == [37, 38, 39, 40, 41, 42]
    assert numbers(plan.order()) == [40, 38, 37, 39, 41, 42]
    assert numbers(plan.children(40)) == [38, 39, 41]
    assert numbers(plan.selected_nodes()) == [40, 38, 37, 41, 42]
    assert plan.ancestors(37) == (38, 40)
    assert plan.ancestors(42) == (41, 40)
    retained = plan.node(39)
    assert (retained.selected, retained.decision, retained.provenance) == (
        False,
        None,
        None,
    )
    fork_child = plan.node(42)
    assert (fork_child.head_repo, fork_child.head_ref) == ("contrib/repo", "feat/a")


def test_selected_child_of_an_unselected_parent_is_recorded_for_the_runtime(
    tmp_path: Path,
) -> None:
    data = packet(
        node(50, None, "feat/landed", "main", select=False),
        node(51, 50, "feat/child", "main"),
        node(52, 51, "feat/grandchild", "feat/child"),
    )

    plan = load_stack_plan(write(tmp_path, data))

    assert plan.unselected_ancestors(52) == (50,)
    assert plan.unselected_ancestors(51) == (50,)
    assert numbers(plan.selected_nodes()) == [51, 52]


def test_explicit_fork_boundary_is_bound_to_its_node(tmp_path: Path) -> None:
    data = linear()
    at(data, 12)["fork"] = oid(1011)

    plan = load_stack_plan(write(tmp_path, data))

    assert plan.node(12).fork == oid(1011)
    assert plan.node(13).fork is None


def test_listing_order_does_not_change_the_plan(tmp_path: Path) -> None:
    shuffled = branching()
    rows(shuffled).reverse()

    first = load_stack_plan(write(tmp_path, branching(), "first.json"))
    second = load_stack_plan(write(tmp_path, shuffled, "second.json"))

    assert first == second


@pytest.mark.parametrize(
    "repository",
    ["owner/repo", "github.com/owner/repo", "GitHub.COM/owner/repo"],
)
def test_default_host_is_github_and_hosts_are_case_normalized(
    tmp_path: Path, repository: str
) -> None:
    data = packet(*rows(linear()), repository=repository)

    plan = load_stack_plan(write(tmp_path, data))

    assert plan == load_stack_plan(write(tmp_path, linear(), "reference.json"))
    assert plan.canonical()["repository"] == "github.com/owner/repo"


def test_enterprise_host_is_a_different_graph(tmp_path: Path) -> None:
    enterprise = packet(*rows(linear()), repository="ghe.example.com/owner/repo")

    plan = load_stack_plan(write(tmp_path, enterprise))
    reference = load_stack_plan(write(tmp_path, linear(), "reference.json"))

    assert plan.host == "ghe.example.com"
    assert plan.topology != reference.topology


def test_sixty_four_nodes_are_supported(tmp_path: Path) -> None:
    data = packet(*(node(pr, None, f"feat/n{pr}", "main") for pr in range(1, 65)))

    plan = load_stack_plan(write(tmp_path, data))

    assert len(plan.nodes) == 64


def test_packet_at_the_size_bound_is_accepted(tmp_path: Path) -> None:
    text = json.dumps(linear())
    path = tmp_path / "padded.json"
    path.write_bytes(text.encode() + b" " * (256 * 1024 - len(text)))

    assert load_stack_plan(path) == parse_stack_plan(linear())


# --- identities ---------------------------------------------------------------------------


def set_decision(pr: int, **changes: object) -> Change:
    return lambda data: at(data, pr).__setitem__("decision", decision(**changes))


def set_head(pr: int, key: str, value: object) -> Change:
    return lambda data: cast("Payload", at(data, pr)["head"]).__setitem__(key, value)


def set_at(pr: int, key: str, value: object) -> Change:
    return lambda data: at(data, pr).__setitem__(key, value)


def drop_at(pr: int, key: str) -> Change:
    return lambda data: at(data, pr).pop(key)


def set_top(key: str, value: object) -> Change:
    return lambda data: data.__setitem__(key, value)


def drop_top(key: str) -> Change:
    return lambda data: data.pop(key)


def changes(*steps: Change) -> Change:
    def apply(data: Payload) -> None:
        for step in steps:
            step(data)

    return apply


def changed(change: Change) -> Payload:
    data = copy.deepcopy(linear())
    change(data)
    return data


@pytest.mark.parametrize(
    "change",
    [
        set_decision(12, merge_method="rebase"),
        set_decision(13, post_merge_commands=[]),
        set_decision(11, expected_checks=["test"]),
        set_head(12, "sha", oid(9012)),
        set_at(13, "provenance", {"disposition": "preserve", "sources": ["PR #13"]}),
    ],
    ids=["merge-method", "post-merge", "checks", "head-sha", "provenance"],
)
def test_identity_tracks_decisions_and_heads_while_topology_holds(
    change: Change,
) -> None:
    frozen = parse_stack_plan(linear())

    refreshed = parse_stack_plan(changed(change))

    assert refreshed.identity != frozen.identity
    assert refreshed.topology == frozen.topology
    assert topology_differences(frozen, refreshed) == ()


def test_decision_identity_changes_only_with_the_decision() -> None:
    plan = parse_stack_plan(linear())
    refreshed = parse_stack_plan(changed(set_decision(12, merge_method="merge")))

    first, second = plan.node(12).decision, refreshed.node(12).decision
    assert first is not None and second is not None
    assert decision_identity(first) != decision_identity(second)
    assert decision_identity(first) == decision_identity(parse_decision(decision()))


@pytest.mark.parametrize(
    ("change", "difference"),
    [
        (
            changes(set_at(13, "parent", 11), set_at(13, "base", "feat/a")),
            "node #13 parent changed from 12 to 11",
        ),
        (
            changes(
                set_at(13, "select", False),
                drop_at(13, "decision"),
                drop_at(13, "provenance"),
            ),
            "node #13 select changed from True to False",
        ),
        (set_head(13, "ref", "feat/c2"), "node #13 head ref changed from 'feat/c'"),
        (
            set_head(13, "repo", "contrib/repo"),
            "node #13 head repository changed from 'owner/repo' to 'contrib/repo'",
        ),
        (
            set_at(12, "base", "main"),
            "node #12 base changed from 'feat/a' to 'main'",
        ),
        (
            set_at(12, "fork", oid(1011)),
            f"node #12 fork changed from None to '{oid(1011)}'",
        ),
        (
            changes(set_top("trunk", "develop"), set_at(11, "base", "develop")),
            "trunk changed from 'main' to 'develop'",
        ),
        (
            lambda data: rows(data).pop(),
            "node #13 is missing",
        ),
        (
            lambda data: rows(data).append(node(14, 13, "feat/d", "feat/c")),
            "node #14 is new",
        ),
    ],
    ids=["parent", "select", "ref", "repo", "base", "fork", "trunk", "gone", "new"],
)
def test_topology_tracks_graph_shape_and_names_the_difference(
    change: Change, difference: str
) -> None:
    frozen = parse_stack_plan(linear())

    refreshed = parse_stack_plan(changed(change))

    assert refreshed.topology != frozen.topology
    differences = topology_differences(frozen, refreshed)
    assert any(item.startswith(difference) for item in differences), differences


def test_repository_case_is_not_a_topology_change() -> None:
    frozen = parse_stack_plan(linear())

    renamed = parse_stack_plan(packet(*rows(linear()), repository="Owner/Repo"))

    assert renamed.topology == frozen.topology
    assert renamed.identity != frozen.identity


@pytest.mark.parametrize("build", [linear, branching], ids=["linear", "branching"])
def test_canonical_form_round_trips_exactly(build: Callable[[], Payload]) -> None:
    plan = parse_stack_plan(build())

    canonical = plan.canonical()

    assert parse_stack_plan(canonical) == plan
    assert parse_stack_plan(json.loads(json.dumps(canonical))) == plan
    assert parse_stack_plan(canonical).canonical() == canonical


def test_omitted_decision_defaults_normalize_to_the_same_identity() -> None:
    explicit = changed(
        set_decision(
            12,
            allowed_skips=[],
            head_only_checks=[],
            protected_refs=[],
            ci_free=False,
        )
    )

    assert parse_stack_plan(explicit) == parse_stack_plan(linear())
    canonical = parse_stack_plan(linear()).canonical()
    middle = next(row for row in rows(canonical) if row["pr"] == 12)
    assert cast("Payload", middle["decision"])["ci_free"] is False


# --- gate decisions through the lifecycle parser ------------------------------------------


def test_ci_free_decision_is_accepted() -> None:
    plan = parse_stack_plan(changed(set_decision(12, expected_checks=[], ci_free=True)))

    bound = plan.node(12).decision
    assert bound is not None
    assert (bound.ci_free, bound.expected_checks) == (True, ())


@pytest.mark.parametrize(
    "changes_",
    [
        {"expected_checks": []},
        {"allowed_skips": ["deploy"]},
        {"merge_method": "fast-forward"},
        {"sources": []},
        {"post_merge_commands": "uv run pytest"},
        {"head_sha": oid(12)},
    ],
    ids=["no-checks", "skip", "method", "sources", "argv", "revision-bound"],
)
def test_invalid_gate_decisions_are_rejected_for_their_node(
    tmp_path: Path, changes_: Payload
) -> None:
    path = write(tmp_path, changed(set_decision(12, **changes_)))

    with pytest.raises(StackPlanError):
        load_stack_plan(path)


# --- packet validation --------------------------------------------------------------------


def chain_with_cycle(data: Payload) -> None:
    at(data, 11)["parent"] = 13
    at(data, 11)["base"] = "feat/c"


def nothing_selected(data: Payload) -> None:
    for row in rows(data):
        row["select"] = False
        row.pop("decision")
        row.pop("provenance")


def oversized_graph(data: Payload) -> None:
    data["nodes"] = [node(pr, None, f"feat/n{pr}", "main") for pr in range(1, 66)]


INVALID: list[tuple[str, Change]] = [
    ("top-unknown", set_top("policy", {})),
    ("top-missing", drop_top("trunk")),
    ("schema-2", set_top("schema_version", 2)),
    ("schema-text", set_top("schema_version", "1")),
    ("schema-bool", set_top("schema_version", True)),
    ("repo-short", set_top("repository", "owner")),
    ("repo-deep", set_top("repository", "h/o/r/x")),
    ("repo-option", set_top("repository", "-o/repo")),
    ("trunk-full-ref", set_top("trunk", "refs/heads/main")),
    ("trunk-option", set_top("trunk", "-main")),
    ("trunk-space", set_top("trunk", "ma in")),
    ("nodes-empty", set_top("nodes", [])),
    ("nodes-object", set_top("nodes", {})),
    ("too-many", oversized_graph),
    (
        "node-scalar",
        lambda data: cast("list[object]", data["nodes"]).__setitem__(1, 12),
    ),
    ("pr-missing", drop_at(12, "pr")),
    ("pr-zero", set_at(12, "pr", 0)),
    ("pr-bool", set_at(12, "pr", True)),
    ("pr-text", set_at(12, "pr", "12")),
    ("select-missing", drop_at(12, "select")),
    ("select-int", set_at(12, "select", 1)),
    ("node-unknown", set_at(12, "labels", [])),
    ("node-missing-base", drop_at(12, "base")),
    ("parent-text", set_at(12, "parent", "11")),
    ("parent-bool", set_at(12, "parent", True)),
    ("head-missing-sha", lambda data: cast("Payload", at(data, 12)["head"]).pop("sha")),
    ("head-unknown", set_head(12, "state", "OPEN")),
    ("head-repo-host", set_head(12, "repo", "github.com/owner/repo")),
    ("head-ref-dots", set_head(12, "ref", "feat..b")),
    ("head-ref-lock", set_head(12, "ref", "feat/b.lock")),
    ("head-sha-short", set_head(12, "sha", "abc123")),
    ("head-sha-upper", set_head(12, "sha", oid(12).upper().replace("0", "A"))),
    ("base-space", set_at(12, "base", "feat/a ")),
    ("fork-symbolic", set_at(12, "fork", "HEAD")),
    ("fork-null", set_at(12, "fork", None)),
    ("fork-is-head", set_at(12, "fork", oid(12))),
    ("no-decision", drop_at(12, "decision")),
    ("no-provenance", drop_at(12, "provenance")),
    ("unselected-decision", set_at(13, "select", False)),
    (
        "unselected-provenance",
        changes(set_at(13, "select", False), drop_at(13, "decision")),
    ),
    (
        "stamp-provenance",
        set_at(12, "provenance", {"disposition": "stamp", "sources": ["x"]}),
    ),
    (
        "provenance-unknown",
        set_at(
            12,
            "provenance",
            {"disposition": "preserve", "sources": ["x"], "trailers": {}},
        ),
    ),
    (
        "sources-empty",
        set_at(12, "provenance", {"disposition": "preserve", "sources": []}),
    ),
    (
        "sources-duplicate",
        set_at(12, "provenance", {"disposition": "preserve", "sources": ["a", "a"]}),
    ),
    (
        "sources-blank",
        set_at(12, "provenance", {"disposition": "preserve", "sources": [" "]}),
    ),
    (
        "sources-control",
        set_at(12, "provenance", {"disposition": "preserve", "sources": ["a\nb"]}),
    ),
    ("decision-scalar", set_at(12, "decision", "squash")),
    ("duplicate-pr", lambda data: rows(data)[2].__setitem__("pr", 12)),
    (
        "duplicate-head",
        changes(set_head(13, "ref", "feat/b"), set_at(13, "base", "feat/b")),
    ),
    (
        "duplicate-head-case",
        changes(set_head(13, "ref", "feat/b"), set_head(13, "repo", "Owner/Repo")),
    ),
    ("head-is-trunk", set_head(11, "ref", "main")),
    ("self-parent", set_at(12, "parent", 12)),
    ("missing-parent", set_at(12, "parent", 99)),
    ("cycle", chain_with_cycle),
    ("root-base", set_at(11, "base", "develop")),
    ("child-base", set_at(13, "base", "feat/a")),
    ("base-on-fork-parent", set_head(12, "repo", "contrib/repo")),
    ("nothing-selected", nothing_selected),
]


@pytest.mark.parametrize(
    "change",
    [change for _, change in INVALID],
    ids=[name for name, _ in INVALID],
)
def test_invalid_packets_are_rejected(tmp_path: Path, change: Change) -> None:
    path = write(tmp_path, changed(change))

    with pytest.raises(StackPlanError):
        load_stack_plan(path)


def test_a_fork_namespace_child_may_still_base_on_its_parent() -> None:
    data = changed(set_head(13, "repo", "contrib/repo"))

    plan = parse_stack_plan(data)

    assert (plan.node(13).head_repo, plan.node(13).base_ref) == (
        "contrib/repo",
        "feat/b",
    )


def test_a_child_already_retargeted_to_the_trunk_is_consistent() -> None:
    plan = parse_stack_plan(changed(set_at(12, "base", "main")))

    assert plan.node(12).base_ref == "main"
    assert plan.ancestors(12) == (11,)


def test_lookups_outside_the_plan_are_contradictions() -> None:
    plan = parse_stack_plan(linear())

    lookups: list[Callable[[int], object]] = [
        plan.node,
        plan.children,
        plan.ancestors,
        plan.unselected_ancestors,
    ]
    for lookup in lookups:
        with pytest.raises(StackPlanError):
            lookup(99)


# --- packet files -------------------------------------------------------------------------


def test_oversized_packet_is_rejected_before_parsing(tmp_path: Path) -> None:
    text = json.dumps(linear())
    path = tmp_path / "padded.json"
    path.write_bytes(text.encode() + b" " * (256 * 1024 + 1 - len(text)))

    with pytest.raises(StackPlanError):
        load_stack_plan(path)


@pytest.mark.parametrize("dangling", [False, True])
def test_symlinked_packet_is_never_followed(tmp_path: Path, dangling: bool) -> None:
    target = tmp_path / "real.json"
    if not dangling:
        target.write_text(json.dumps(linear()))
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(StackPlanError):
        load_stack_plan(link)
    assert link.is_symlink()


def test_directory_is_not_a_packet(tmp_path: Path) -> None:
    with pytest.raises(StackPlanError):
        load_stack_plan(tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
def test_named_pipe_is_refused_without_blocking(tmp_path: Path) -> None:
    pipe = tmp_path / "plan.fifo"
    os.mkfifo(pipe)

    with pytest.raises(StackPlanError):
        load_stack_plan(pipe)


def test_missing_packet_is_reported(tmp_path: Path) -> None:
    with pytest.raises(StackPlanError):
        load_stack_plan(tmp_path / "absent.json")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"\xff\xfe{}", "stack plan is not UTF-8 text"),
        (b'{"schema_version": 1\x00}', "stack plan contains a NUL byte"),
        (b'{"schema_version": 1,', "stack plan is not valid JSON"),
        (b"[]", "stack plan must be a JSON object"),
        (
            json.dumps(linear()).replace('"pr": 12', '"pr": NaN').encode(),
            "stack plan contains the non-finite number NaN",
        ),
        (
            b'{"schema_version": 1, "schema_version": 1}',
            "stack plan repeats the JSON key 'schema_version'",
        ),
        (
            json.dumps(linear())
            .replace('"sha": "', '"sha": "' + oid(1) + '", "sha": "', 1)
            .encode(),
            "stack plan repeats the JSON key 'sha'",
        ),
        (b"[" * 100_000, "stack plan nests JSON values too deeply"),
    ],
    ids=[
        "encoding",
        "nul",
        "truncated",
        "array",
        "nan",
        "top-duplicate",
        "duplicate",
        "deep",
    ],
)
def test_undecodable_packets_are_rejected(
    tmp_path: Path, content: bytes, message: str
) -> None:
    path = tmp_path / "plan.json"
    path.write_bytes(content)

    with pytest.raises(StackPlanError):
        load_stack_plan(path)


def test_pure_parser_rejects_non_objects() -> None:
    with pytest.raises(StackPlanError):
        parse_stack_plan([linear()])
