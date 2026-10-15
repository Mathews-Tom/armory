"""Stack-graph master journals: strict schema, private CAS storage beside receipts."""

from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from graph import (
    StackPlan,
    StackPlanError,
    decision_identity,
    journal_plan,
    new_journal,
    parse_stack_plan,
    resumed_plan,
)
from state_store import (
    GraphIntent,
    GraphJournal,
    Promotion,
    Receipt,
    ReceiptInputError,
    StateError,
    Store,
    Target,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="journals require POSIX")

GRAPH_RUN = "0123456789abcdef0123456789abcdef"
OTHER_GRAPH = "fedcba9876543210fedcba9876543210"
RECEIPT_RUN = "00112233445566778899aabbccddeeff"
ROOT_RUN = "a" * 32
CHILD_RUN = "b" * 32
CODE = "c" * 64
NOW = "2026-10-13T12:00:00+00:00"

Payload = dict[str, object]
Change = Callable[[Payload], object]


@pytest.fixture(autouse=True)
def isolated_environment(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)
    home = tmp_path_factory.mktemp("home")
    config = home / "gitconfig"
    config.write_text("[gc]\nauto = 0\n[maintenance]\nauto = false\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Ship Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "ship@example.invalid")
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"git {args} failed: {result.stderr.decode(errors='replace')}"
        )
    return os.fsdecode(result.stdout).rstrip("\n")


def common_dir_of(checkout: Path) -> Path:
    return Path(
        git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / "tracked.txt").write_text("one\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return path


@pytest.fixture
def common(repo: Path) -> Path:
    return common_dir_of(repo)


def oid(number: int) -> str:
    return f"{number:040x}"


def stack_packet() -> Payload:
    """Root 11 with a selected child 12 and an unselected sibling 13."""

    def row(pr: int, parent: int | None, ref: str, base: str, select: bool) -> Payload:
        value: Payload = {
            "pr": pr,
            "parent": parent,
            "select": select,
            "head": {"repo": "owner/repo", "ref": ref, "sha": oid(pr)},
            "base": base,
        }
        if select:
            value["decision"] = {
                "sources": ["CONTRIBUTING.md#merging"],
                "expected_checks": ["test"],
                "merge_method": "squash",
                "post_merge_commands": [["uv", "run", "pytest", "-q"]],
            }
            value["provenance"] = {
                "disposition": "preserve",
                "sources": ["published Stack-Id trailers"],
            }
        return value

    return {
        "schema_version": 1,
        "repository": "owner/repo",
        "trunk": "main",
        "nodes": [
            row(11, None, "feat/root", "main", True),
            row(12, 11, "feat/child", "feat/root", True),
            row(13, 11, "feat/sibling", "feat/root", False),
        ],
    }


def stack_plan() -> StackPlan:
    return parse_stack_plan(stack_packet())


def fresh(run_id: str = GRAPH_RUN, endpoint: str = "clean") -> GraphJournal:
    return new_journal(
        stack_plan(),
        run_id=run_id,
        endpoint=endpoint,
        code_identity=CODE,
        created_at=NOW,
    )


def progressed(run_id: str = GRAPH_RUN) -> GraphJournal:
    """Root landed, child promoted and pushed, retarget outcome still unknown."""
    journal = fresh(run_id)
    root, child, sibling = journal.nodes
    root.run_id, root.state = ROOT_RUN, "LANDED"
    for node in (child, sibling):
        node.fork, node.old_head, node.captured_at = oid(11), oid(node.pr), NOW
    child.run_id = CHILD_RUN
    child.promotion = Promotion(
        fork=oid(11),
        old_head=oid(12),
        landing=oid(500),
        expected_tree=oid(501),
        new_head=oid(502),
        commits=2,
        slice_identity="d" * 64,
        verified=True,
    )
    child.head_sha, child.state = oid(502), "PROMOTED"
    journal.intents = [
        GraphIntent(
            key=f"capture-{pr}",
            kind="capture",
            pr=pr,
            resource=f"pull/{pr}",
            expected_old=oid(pr),
            new=oid(11),
            created_at=NOW,
            outcome="CONFIRMED",
            actual=oid(11),
        )
        for pr in (12, 13)
    ]
    journal.intents += [
        GraphIntent(
            key="push-12",
            kind="rewrite-push",
            pr=12,
            resource="refs/heads/feat/child",
            expected_old=oid(12),
            new=oid(502),
            created_at=NOW,
            outcome="CONFIRMED",
            actual=oid(502),
            detail="lease refs/heads/feat/child at the captured old head",
        ),
        GraphIntent(
            key="retarget-12",
            kind="retarget",
            pr=12,
            resource="pull/12",
            expected_old="feat/root",
            new="main",
            created_at=NOW,
        ),
        GraphIntent(
            key="advance-12",
            kind="advance-local",
            pr=12,
            resource="refs/heads/feat/child",
            expected_old=oid(12),
            new=oid(502),
            created_at=NOW,
            outcome="REJECTED",
            actual=oid(777),
            detail="local branch has extra commits; retained untouched",
        ),
    ]
    journal.issue = "retarget outcome unknown after dispatch"
    journal.next_action = "reconcile PR #12 base from provider facts"
    return journal


def receipt(run_id: str = RECEIPT_RUN) -> Receipt:
    return Receipt(
        run_id=run_id,
        endpoint="merged",
        code_identity=CODE,
        policy_identity=None,
        inventory_identity="f" * 64,
        target=Target(
            host="github.com",
            repo="owner/repo",
            number=12,
            head_sha=oid(12),
            base_sha=oid(11),
            head_ref="feat/child",
            head_repo="owner/repo",
            base_ref="feat/root",
        ),
    )


def graphs_dir(common_dir: Path) -> Path:
    directory = common_dir / "armory" / "ship" / "graphs"
    directory.mkdir(parents=True, exist_ok=True)
    for path in (common_dir / "armory", common_dir / "armory" / "ship", directory):
        path.chmod(0o700)
    return directory


def plant(common_dir: Path, run_id: str, content: bytes, mode: int = 0o600) -> Path:
    """Put raw bytes where graph journals live, without the Store under test."""
    target = graphs_dir(common_dir) / f"{run_id}.json"
    target.write_bytes(content)
    target.chmod(mode)
    return target


def journal_path(common_dir: Path, run_id: str = GRAPH_RUN) -> Path:
    return common_dir / "armory" / "ship" / "graphs" / f"{run_id}.json"


# --- schema and round trip ----------------------------------------------------------------


def test_progressed_journal_survives_a_save_and_a_fresh_load(common: Path) -> None:
    journal = progressed()
    Store(common).save_graph(journal)

    loaded = Store(common).load_graph(GRAPH_RUN)

    assert loaded == journal
    assert journal_plan(loaded) == stack_plan()
    child = loaded.node(12)
    assert child.promotion is not None and child.promotion.new_head == oid(502)
    assert [intent.outcome for intent in loaded.intents] == [
        "CONFIRMED",
        "CONFIRMED",
        "CONFIRMED",
        "PENDING",
        "REJECTED",
    ]


def test_saved_graph_bytes_are_canonical_private_json(common: Path) -> None:
    os.umask(0)
    journal = progressed()

    Store(common).save_graph(journal)

    path = journal_path(common)
    data = json.loads(path.read_bytes())
    assert data["schema_version"] == 2
    assert data["kind"] == "stack-graph"
    assert (
        path.read_bytes()
        == (json.dumps(data, sort_keys=True, ensure_ascii=True) + "\n").encode()
    )
    for directory in (common / "armory", common / "armory" / "ship", path.parent):
        assert stat.S_IMODE(directory.lstat().st_mode) == 0o700
    assert stat.S_IMODE(path.lstat().st_mode) == 0o600
    assert sorted(item.name for item in path.parent.iterdir()) == [path.name]


def test_new_journal_binds_every_node_to_the_packet() -> None:
    plan = stack_plan()

    journal = fresh()

    rows = [
        (node.pr, node.parent, node.selected, node.head_sha, node.base_ref, node.state)
        for node in journal.nodes
    ]
    assert rows == [
        (11, None, True, oid(11), "main", "PENDING"),
        (12, 11, True, oid(12), "feat/root", "PENDING"),
        (13, 11, False, oid(13), "feat/root", "RETAINED"),
    ]
    root_decision = plan.node(11).decision
    assert root_decision is not None
    assert journal.node(11).decision_identity == decision_identity(root_decision)
    assert journal.node(13).decision_identity is None
    assert all(node.run_id is None and node.fork is None for node in journal.nodes)
    assert (journal.plan_identity, journal.topology) == (plan.identity, plan.topology)
    assert (journal.status, journal.intents) == ("WAITING", [])
    with pytest.raises(StateError):
        journal.node(99)


def test_new_journal_refuses_an_unsupported_endpoint() -> None:
    with pytest.raises(ReceiptInputError):
        fresh(endpoint="landed")


def node_row(data: Payload, pr: int) -> Payload:
    return next(row for row in cast("list[Payload]", data["nodes"]) if row["pr"] == pr)


def intent_row(data: Payload, key: str) -> Payload:
    intents = cast("list[Payload]", data["intents"])
    return next(row for row in intents if row["key"] == key)


def top(key: str, value: object) -> Change:
    return lambda data: data.__setitem__(key, value)


def drop(key: str) -> Change:
    return lambda data: data.pop(key)


def on_node(pr: int, key: str, value: object) -> Change:
    return lambda data: node_row(data, pr).__setitem__(key, value)


def on_promotion(key: str, value: object) -> Change:
    def apply(data: Payload) -> None:
        cast("Payload", node_row(data, 12)["promotion"])[key] = value

    return apply


def many_nodes(data: Payload) -> None:
    data["nodes"] = [node_row(data, 13) for _ in range(65)]


def many_intents(data: Payload) -> None:
    data["intents"] = [intent_row(data, "push-12") for _ in range(1025)]


def root_fork(data: Payload) -> None:
    node_row(data, 11).update(fork=oid(5), old_head=oid(11), captured_at=NOW)


def promoted_sibling(data: Payload) -> None:
    node_row(data, 13)["promotion"] = copy.deepcopy(node_row(data, 12)["promotion"])


def complete_before_the_child_landed(data: Payload) -> None:
    data["status"] = "COMPLETE"
    intent_row(data, "retarget-12").update(outcome="CONFIRMED", actual="main")


def on_intent(name: str, **values: object) -> Change:
    return lambda data: intent_row(data, name).update(values)


def append_intent(name: str, source: str) -> Change:
    def apply(data: Payload) -> None:
        row = copy.deepcopy(intent_row(data, source))
        row["key"] = name
        cast("list[Payload]", data["intents"]).append(row)

    return apply


def node_list(change: Callable[[list[Payload]], object]) -> Change:
    return lambda data: change(cast("list[Payload]", data["nodes"]))


def drop_intent(name: str) -> Change:
    return lambda data: cast("list[Payload]", data["intents"]).remove(
        intent_row(data, name)
    )


SCHEMA_REJECTS: list[tuple[str, Change, str]] = [
    ("schema-3", top("schema_version", 3), "unsupported graph journal schema version"),
    ("schema-missing", drop("schema_version"), "unsupported graph journal schema"),
    ("schema-bool", top("schema_version", True), "unsupported graph journal schema"),
    ("unknown-field", top("receipts", []), "graph journal fields are missing"),
    ("missing-field", drop("topology"), "graph journal fields are missing"),
    ("kind", top("kind", "receipt"), "journal is not a stack-graph journal"),
    ("run-id", top("run_id", "../escape"), "run id must be exactly 32 lowercase"),
    ("host-case", top("host", "GitHub.com"), "invalid graph provider namespace"),
    ("repo", top("repo", "owner"), "invalid graph provider namespace"),
    (
        "trunk",
        top("trunk", "refs/heads/main"),
        "graph trunk must be a short branch name Git accepts",
    ),
    ("endpoint", top("endpoint", "landed"), "unsupported graph endpoint or status"),
    ("status", top("status", "PLANNED"), "unsupported graph endpoint or status"),
    ("plan-id", top("plan_identity", "abc"), "plan_identity must be a SHA-256"),
    ("topology", top("topology", "Z" * 64), "topology must be a SHA-256 identity"),
    ("code", top("code_identity", None), "code_identity must be a nonempty"),
    ("plan-list", top("plan", []), "graph plan must be a JSON object"),
    ("plan-nan", top("plan", {"x": float("nan")}), "unsupported JSON data"),
    ("nodes-empty", top("nodes", []), "graph journal needs between 1 and 64 nodes"),
    ("nodes-many", many_nodes, "graph journal needs between 1 and 64 nodes"),
    ("intents-many", many_intents, "graph journal holds at most 1024 intents"),
    ("node-field", on_node(12, "merged", True), "graph node fields are missing"),
    (
        "node-missing",
        lambda data: node_row(data, 12).pop("state"),
        "graph node fields are missing",
    ),
    ("node-pr", on_node(12, "pr", True), "graph node pr must be a positive PR"),
    (
        "dangling-parent",
        on_node(12, "parent", 99),
        "graph node #12 parent is not another node",
    ),
    ("self-parent", on_node(12, "parent", 12), "graph node #12 parent is not another"),
    ("cycle", on_node(11, "parent", 13), "graph parent relation has a cycle"),
    (
        "unsorted",
        node_list(lambda nodes: nodes.reverse()),
        "graph nodes must be unique and ordered by PR number",
    ),
    (
        "duplicate-node",
        node_list(lambda nodes: nodes.__setitem__(2, copy.deepcopy(nodes[1]))),
        "graph nodes must be unique and ordered by PR number",
    ),
    (
        "selected-flag",
        on_node(12, "selected", "yes"),
        "graph node #12 selected flag must be a boolean",
    ),
    (
        "head-repo",
        on_node(12, "head_repo", "a/b/c"),
        "graph node #12 head repository is invalid",
    ),
    (
        "head-ref",
        on_node(12, "head_ref", "-x"),
        "graph node #12 head ref must be a short branch name Git accepts",
    ),
    (
        "base-ref",
        on_node(12, "base_ref", "feat root"),
        "graph node #12 base ref must be a short branch name",
    ),
    (
        "head-sha",
        on_node(12, "head_sha", "abc"),
        "graph node #12 head must be a full object identity",
    ),
    ("state", on_node(12, "state", "MERGED"), "graph node #12 has an unsupported"),
    (
        "selected-retained",
        on_node(12, "state", "RETAINED"),
        "graph node #12: exactly unselected nodes are RETAINED",
    ),
    (
        "unselected-pending",
        on_node(13, "state", "PENDING"),
        "graph node #13: exactly unselected nodes are RETAINED",
    ),
    (
        "landed-without-run",
        on_node(11, "run_id", None),
        "graph node #11 is LANDED only through its node run",
    ),
    (
        "partial-capture",
        on_node(12, "captured_at", None),
        "graph node #12 records fork, old head and time together",
    ),
    (
        "root-fork",
        root_fork,
        "graph node #11 fork needs a parent and a nonempty slice",
    ),
    (
        "empty-slice",
        on_node(12, "old_head", oid(11)),
        "graph node #12 fork needs a parent and a nonempty slice",
    ),
    (
        "captured-text",
        on_node(12, "captured_at", "yesterday"),
        "graph node #12 captured_at must be an ISO-8601 timestamp",
    ),
    (
        "captured-naive",
        on_node(12, "captured_at", "2026-10-13T12:00:00"),
        "graph node #12 captured_at must be a timezone-aware ISO-8601 timestamp",
    ),
    (
        "unselected-decision",
        on_node(13, "decision_identity", "e" * 64),
        "graph node #13: exactly selected nodes carry a decision and a node run id",
    ),
    (
        "selected-undecided",
        on_node(12, "decision_identity", None),
        "graph node #12: exactly selected nodes carry a decision",
    ),
    (
        "unselected-run",
        on_node(13, "run_id", "e" * 32),
        "graph node #13: exactly selected nodes carry a decision and a node run id",
    ),
    (
        "node-run-is-graph-run",
        on_node(12, "run_id", GRAPH_RUN),
        "per-node run ids must differ from each other and from the graph run",
    ),
    (
        "shared-node-run",
        on_node(12, "run_id", ROOT_RUN),
        "per-node run ids must differ from each other and from the graph run",
    ),
    (
        "promotion-unselected",
        promoted_sibling,
        "graph node #13 promotion must start from the selected node's captured fork",
    ),
    (
        "promotion-fork",
        on_promotion("fork", oid(99)),
        "graph node #12 promotion must start from the selected node's captured fork",
    ),
    (
        "promotion-noop",
        on_promotion("new_head", oid(12)),
        "graph node #12 must move a nonempty slice to a new head",
    ),
    (
        "commits-zero",
        on_promotion("commits", 0),
        "graph node #12 must replay a bounded nonempty slice",
    ),
    (
        "commits-bool",
        on_promotion("commits", True),
        "graph node #12 must replay a bounded nonempty slice",
    ),
    (
        "commits-huge",
        on_promotion("commits", 10_001),
        "graph node #12 must replay a bounded nonempty slice",
    ),
    (
        "verified-text",
        on_promotion("verified", "yes"),
        "graph node #12 verified flag must be a boolean",
    ),
    (
        "promotion-field",
        on_promotion("tree", oid(501)),
        "graph node #12 fields are missing or unsupported",
    ),
    (
        "promoted-unverified",
        on_promotion("verified", False),
        "graph node #12 is PROMOTED only by a verified promotion",
    ),
    (
        "intent-kind",
        on_intent("capture-12", kind="merge"),
        "graph intent capture-12 has an unsupported kind or outcome",
    ),
    (
        "intent-outcome",
        on_intent("capture-12", outcome="ACCEPTED"),
        "graph intent capture-12 has an unsupported kind or outcome",
    ),
    (
        "intent-key",
        on_intent("capture-12", key="bad key"),
        "graph intent key is not a supported identifier",
    ),
    (
        "intent-field",
        on_intent("capture-12", proof="tree"),
        "graph intent fields are missing or unsupported",
    ),
    (
        "duplicate-key",
        on_intent("retarget-12", key="push-12"),
        "graph intent keys must be unique",
    ),
    (
        "outside-pr",
        on_intent("advance-12", pr=99),
        "graph intent advance-12 names a PR outside the graph",
    ),
    (
        "capture-resource",
        on_intent("capture-12", resource="refs/heads/feat/child"),
        "graph intent capture-12 resource must be pull/12",
    ),
    (
        "push-short-ref",
        on_intent("push-12", resource="feat/child"),
        "graph intent push-12 resource must be a full branch ref",
    ),
    (
        "push-branch-identity",
        on_intent("push-12", expected_old="feat/root"),
        "graph intent push-12 expected old must be a full object identity",
    ),
    (
        "push-other-ref",
        on_intent("push-12", resource="refs/heads/feat/sibling"),
        "graph intent push-12 must push the node's own head ref",
    ),
    (
        "push-noop",
        on_intent("push-12", new=oid(12), actual=oid(12)),
        "graph intent push-12 must change its resource",
    ),
    (
        "push-unproven",
        on_intent("push-12", new=oid(600), actual=oid(600)),
        "graph intent push-12 must move exactly a verified promotion",
    ),
    (
        "advance-unproven",
        on_intent("advance-12", outcome="PENDING", actual=None, new=oid(600)),
        "graph intent advance-12 must move exactly a verified promotion",
    ),
    (
        "pending-observed",
        on_intent("retarget-12", actual="main"),
        "graph intent retarget-12: only a reconciled intent has an observed outcome",
    ),
    (
        "confirmed-elsewhere",
        on_intent("push-12", actual=oid(12)),
        "graph intent push-12: only a reconciled intent has an observed outcome",
    ),
    (
        "rejected-applied",
        on_intent("advance-12", actual=oid(502)),
        "graph intent advance-12: only a reconciled intent has an observed outcome",
    ),
    (
        "repeated-pending",
        append_intent("retarget-12-again", "retarget-12"),
        "graph intent retarget-12-again repeats an unreconciled intent for pull/12",
    ),
    (
        "second-capture",
        append_intent("capture-12-again", "capture-12"),
        "graph intent capture-12-again: a node has one confirmed capture",
    ),
    (
        "capture-mismatch",
        on_intent("capture-12", new=oid(98), actual=oid(98)),
        "graph intent capture-12 is not the node's recorded capture",
    ),
    (
        "capture-root",
        on_intent("capture-12", pr=11, resource="pull/11", expected_old=oid(11)),
        "graph intent capture-12 must change its resource",
    ),
    (
        "capture-trunk-node",
        on_intent("capture-12", pr=11, resource="pull/11"),
        "graph intent capture-12 captures a fork of a trunk-based node",
    ),
    (
        "retarget-unselected",
        on_intent("retarget-12", pr=13, resource="pull/13"),
        "graph intent retarget-12 mutates only a selected child node",
    ),
    (
        "retarget-root",
        on_intent("retarget-12", pr=11, resource="pull/11"),
        "graph intent retarget-12 mutates only a selected child node",
    ),
    (
        "retarget-off-trunk",
        on_intent("retarget-12", new="develop"),
        "graph intent retarget-12 must retarget onto the trunk",
    ),
    (
        "retarget-foreign-base",
        on_intent("retarget-12", expected_old="feat/sibling"),
        "graph intent retarget-12 must retarget from the parent's head ref",
    ),
    (
        "advance-other-ref",
        on_intent("advance-12", resource="refs/heads/feat/sibling"),
        "graph intent advance-12 must advance the node's own head ref",
    ),
    (
        "capture-pending",
        on_intent("capture-12", outcome="PENDING", actual=None),
        "graph intent capture-12: a capture is only ever CONFIRMED",
    ),
    (
        "capture-rejected",
        on_intent("capture-12", outcome="REJECTED", actual=oid(12)),
        "graph intent capture-12: a capture is only ever CONFIRMED",
    ),
    (
        "capture-unjournaled",
        drop_intent("capture-13"),
        "graph node #13 capture is not journaled by a capture intent",
    ),
    (
        "complete-with-pending",
        top("status", "COMPLETE"),
        "a complete graph run has no unreconciled intent",
    ),
    (
        "complete-unlanded",
        complete_before_the_child_landed,
        "a complete graph run has landed every selected node; #12 is PROMOTED",
    ),
    (
        "pr-endpoint-mutation",
        top("endpoint", "pr"),
        "a pr-endpoint graph run is observation-only",
    ),
    (
        "detail-control",
        on_intent("push-12", detail="line\nbreak"),
        "graph intent push-12 detail must be plain text of at most 512 characters",
    ),
    (
        "detail-long",
        on_intent("push-12", detail="x" * 513),
        "graph intent push-12 detail must be plain text of at most 512 characters",
    ),
    (
        "intent-time",
        on_intent("retarget-12", created_at="now"),
        "graph intent retarget-12 created_at must be an ISO-8601 timestamp",
    ),
    (
        "journal-time",
        top("updated_at", "2026-10-13"),
        "updated_at must be a timezone-aware ISO-8601 timestamp",
    ),
]


def corrupted(change: Change) -> Payload:
    data = progressed().serialize()
    change(data)
    return data


def test_the_reference_journal_is_itself_valid() -> None:
    assert GraphJournal.parse(progressed().serialize()) == progressed()


@pytest.mark.parametrize(
    ("change", "message"),
    [(change, message) for _, change, message in SCHEMA_REJECTS],
    ids=[name for name, _, _ in SCHEMA_REJECTS],
)
def test_parse_rejects_each_corrupted_graph_journal(
    change: Change, message: str
) -> None:
    with pytest.raises(ReceiptInputError):
        GraphJournal.parse(corrupted(change))


@pytest.mark.parametrize(
    ("change", "message"),
    [(change, message) for _, change, message in SCHEMA_REJECTS],
    ids=[name for name, _, _ in SCHEMA_REJECTS],
)
def test_a_corrupted_graph_journal_at_rest_is_never_loaded(
    common: Path, change: Change, message: str
) -> None:
    target = plant(common, GRAPH_RUN, json.dumps(corrupted(change)).encode())
    before = target.read_bytes()

    with pytest.raises(ReceiptInputError):
        Store(common).load_graph(GRAPH_RUN)
    with pytest.raises(ReceiptInputError):
        Store(common).list_graphs()
    assert target.read_bytes() == before


def test_a_rejected_retarget_may_observe_the_unchanged_base() -> None:
    journal = progressed()
    retarget = next(item for item in journal.intents if item.key == "retarget-12")
    retarget.outcome, retarget.actual = "REJECTED", "feat/root"

    assert GraphJournal.parse(journal.serialize()) == journal


def test_a_rejected_push_may_observe_a_deleted_remote_branch() -> None:
    journal = progressed()
    push = next(item for item in journal.intents if item.key == "push-12")
    push.outcome, push.actual = "REJECTED", None

    assert GraphJournal.parse(journal.serialize()) == journal


def test_a_complete_observation_run_has_no_mutation_intents() -> None:
    journal = replace(fresh(endpoint="pr"), status="COMPLETE")

    assert GraphJournal.parse(journal.serialize()) == journal


def test_oversized_graph_journal_is_rejected(common: Path) -> None:
    plant(common, GRAPH_RUN, b" " * (2 * 1024 * 1024 + 1))

    with pytest.raises(ReceiptInputError):
        Store(common).load_graph(GRAPH_RUN)


def test_malformed_graph_journal_is_rejected(common: Path) -> None:
    plant(common, GRAPH_RUN, b"{")

    with pytest.raises(ReceiptInputError):
        Store(common).load_graph(GRAPH_RUN)


def test_graph_journal_must_match_its_filename(common: Path) -> None:
    plant(common, GRAPH_RUN, json.dumps(progressed(OTHER_GRAPH).serialize()).encode())

    with pytest.raises(ReceiptInputError):
        Store(common).load_graph(GRAPH_RUN)


# --- plan cross-check ---------------------------------------------------------------------


def test_journal_plan_refuses_an_identity_that_is_not_the_plan() -> None:
    journal = replace(progressed(), plan_identity="e" * 64)

    with pytest.raises(ReceiptInputError):
        journal_plan(journal)


def test_journal_plan_refuses_a_node_bound_to_another_decision() -> None:
    journal = progressed()
    journal.node(12).decision_identity = "e" * 64

    with pytest.raises(ReceiptInputError):
        journal_plan(journal)


def test_journal_plan_refuses_an_invalid_frozen_plan() -> None:
    journal = progressed()
    journal.plan = {**journal.plan, "trunk": "-main"}

    with pytest.raises(ReceiptInputError):
        journal_plan(journal)


def test_journal_plan_refuses_a_capture_contradicting_an_explicit_fork() -> None:
    packet = stack_packet()
    node_row(packet, 12)["fork"] = oid(11)
    plan = parse_stack_plan(packet)
    journal = new_journal(
        plan, run_id=GRAPH_RUN, endpoint="merged", code_identity=CODE, created_at=NOW
    )
    child = journal.node(12)
    child.fork, child.old_head, child.captured_at = oid(98), oid(12), NOW

    with pytest.raises(ReceiptInputError):
        journal_plan(journal)
    child.fork = oid(11)
    assert journal_plan(journal) == plan


def test_refreshed_decisions_keep_the_frozen_topology() -> None:
    journal = progressed()
    packet = stack_packet()
    decision = cast("Payload", node_row(packet, 12)["decision"])
    decision["merge_method"] = "rebase"
    refreshed = parse_stack_plan(packet)
    refreshed_decision = refreshed.node(12).decision
    assert refreshed_decision is not None

    journal.plan = refreshed.canonical()
    journal.plan_identity = refreshed.identity
    journal.node(12).decision_identity = decision_identity(refreshed_decision)

    assert refreshed.topology == journal.topology
    assert journal_plan(GraphJournal.parse(journal.serialize())) == refreshed


def test_resumption_accepts_a_packet_refreshing_decisions_and_heads() -> None:
    journal = progressed()
    packet = stack_packet()
    cast("Payload", node_row(packet, 11)["decision"])["expected_checks"] = ["lint"]
    cast("Payload", node_row(packet, 13)["head"])["sha"] = oid(913)
    refreshed = parse_stack_plan(packet)

    assert resumed_plan(journal, None) == stack_plan()
    assert resumed_plan(journal, refreshed) == refreshed


def test_resumption_refuses_a_packet_with_another_topology() -> None:
    journal = progressed()
    packet = stack_packet()
    cast("Payload", node_row(packet, 13)["head"])["ref"] = "feat/elsewhere"

    with pytest.raises(StackPlanError) as raised:
        resumed_plan(journal, parse_stack_plan(packet))

    assert str(raised.value) == (
        "the stack plan contradicts the resumed graph run: node #13 head ref "
        "changed from 'feat/sibling' to 'feat/elsewhere'"
    )


def test_a_case_only_refresh_keeps_the_journal_resumable() -> None:
    journal = progressed()
    packet = stack_packet()
    packet["repository"] = "Owner/Repo"
    for row in cast("list[Payload]", packet["nodes"]):
        cast("Payload", row["head"])["repo"] = "Owner/Repo"
    refreshed = parse_stack_plan(packet)
    assert resumed_plan(journal, refreshed) == refreshed

    # The refreshed packet replaces the frozen plan; the node rows keep the
    # namespace spelling the run started with.
    journal.plan = refreshed.canonical()
    journal.plan_identity = refreshed.identity

    reloaded = GraphJournal.parse(journal.serialize())
    assert (reloaded.repo, reloaded.node(12).head_repo) == ("owner/repo", "owner/repo")
    assert journal_plan(reloaded) == refreshed


def test_journal_plan_accepts_only_the_planned_base_or_the_trunk() -> None:
    journal = progressed()
    journal.node(12).base_ref = "main"
    assert journal_plan(journal) == stack_plan()

    journal.node(12).base_ref = "feat/sibling"
    with pytest.raises(ReceiptInputError):
        journal_plan(journal)


# --- the runtime's journal transitions ----------------------------------------------------


def test_every_runtime_journal_transition_saves_and_reloads(common: Path) -> None:
    """Each shape the graph runtime journals, in the order it journals them.

    The child is captured before its root lands. It is then promoted with a push
    whose outcome stays unknown, reconciled as refused, promoted again, pushed,
    advanced locally, retargeted and landed. Every intermediate journal must be
    preserved: a refused save would lose the run's durable intent.
    """
    store = Store(common)
    journal = fresh()
    root, child, _ = journal.nodes

    def save(step: str) -> None:
        store.save_graph(journal)
        assert Store(common).load_graph(GRAPH_RUN) == journal, step

    def promote(new_head: str) -> Promotion:
        return Promotion(
            fork=oid(11),
            old_head=oid(12),
            landing=oid(500),
            expected_tree=oid(501),
            new_head=new_head,
            commits=1,
            slice_identity="d" * 64,
            verified=True,
        )

    def intent(kind: str, resource: str, change: tuple[str, str]) -> GraphIntent:
        row = GraphIntent(
            key=str(len(journal.intents) + 1),
            kind=kind,
            pr=12,
            resource=resource,
            expected_old=change[0],
            new=change[1],
            created_at=NOW,
        )
        journal.intents.append(row)
        return row

    save("created")
    child.fork, child.old_head, child.captured_at = oid(11), oid(12), NOW
    capture = intent("capture", "pull/12", (oid(12), oid(11)))
    capture.outcome, capture.actual = "CONFIRMED", oid(11)
    save("child captured")
    root.run_id = ROOT_RUN
    save("root run preassigned")
    root.state = "LANDED"
    save("root landed")
    child.promotion, child.state = promote(oid(502)), "PROMOTED"
    push = intent("rewrite-push", "refs/heads/feat/child", (oid(12), oid(502)))
    save("push journaled")
    journal.status = "WAITING"
    journal.issue = "the rewrite push of #12 has an unknown outcome"
    save("push outcome unknown")
    push.outcome, push.actual = "REJECTED", oid(12)
    push.detail = "reconciled: the remote still holds the old head"
    save("push reconciled as refused")
    child.promotion = promote(oid(503))
    push = intent("rewrite-push", "refs/heads/feat/child", (oid(12), oid(503)))
    save("second push journaled")
    child.head_sha = oid(503)
    push.outcome, push.actual = "CONFIRMED", oid(503)
    save("second push confirmed")
    local = intent("advance-local", "refs/heads/feat/child", (oid(12), oid(503)))
    save("local advance journaled")
    local.outcome, local.actual = "CONFIRMED", oid(503)
    save("local branch advanced")
    retarget = intent("retarget", "pull/12", ("feat/root", "main"))
    save("retarget journaled")
    child.base_ref = "main"
    retarget.outcome, retarget.actual = "CONFIRMED", "main"
    save("retarget confirmed")
    child.run_id = CHILD_RUN
    save("child run preassigned")
    child.state = "LANDED"
    journal.status, journal.issue, journal.next_action = "COMPLETE", None, "none"
    save("complete")

    assert journal_plan(Store(common).load_graph(GRAPH_RUN)) == stack_plan()


# --- separation from lifecycle receipts ---------------------------------------------------


def test_receipt_enumeration_never_meets_graph_journals(common: Path) -> None:
    store = Store(common)
    store.save(receipt())
    receipt_path = common / "armory" / "ship" / f"{RECEIPT_RUN}.json"
    receipt_bytes = receipt_path.read_bytes()

    store.save_graph(progressed())
    store.save_graph(fresh(OTHER_GRAPH))

    reader = Store(common)
    assert reader.list_runs() == (receipt(),)
    assert receipt_path.read_bytes() == receipt_bytes
    assert reader.load(RECEIPT_RUN) == receipt()
    assert [journal.run_id for journal in reader.list_graphs()] == [
        GRAPH_RUN,
        OTHER_GRAPH,
    ]
    with pytest.raises(FileNotFoundError):
        reader.load(GRAPH_RUN)
    with pytest.raises(FileNotFoundError):
        reader.load_graph(RECEIPT_RUN)


def test_list_graphs_skips_foreign_files_and_sorts(common: Path) -> None:
    store = Store(common)
    store.save_graph(fresh(OTHER_GRAPH))
    store.save_graph(fresh(GRAPH_RUN))
    (common / "armory" / "ship" / "graphs" / f".{GRAPH_RUN}.stray").write_bytes(b"x")

    assert [journal.run_id for journal in Store(common).list_graphs()] == [
        GRAPH_RUN,
        OTHER_GRAPH,
    ]


def test_excluded_graph_is_never_read_so_its_save_baseline_holds(
    common: Path,
) -> None:
    controller = Store(common)
    controller.save_graph(fresh(OTHER_GRAPH))
    controller.save_graph(fresh(GRAPH_RUN))
    held = controller.load_graph(GRAPH_RUN)
    other = Store(common)
    newer = other.load_graph(GRAPH_RUN)
    newer.next_action = "another controller's journaled intent"
    other.save_graph(newer)
    newer_bytes = journal_path(common).read_bytes()

    others = controller.list_graphs(exclude=GRAPH_RUN)

    assert [journal.run_id for journal in others] == [OTHER_GRAPH]
    held.next_action = "overwrite from a stale view"
    with pytest.raises(StateError):
        controller.save_graph(held)
    assert journal_path(common).read_bytes() == newer_bytes


def test_exclusion_skips_even_an_unreadable_graph(common: Path) -> None:
    Store(common).save_graph(fresh(OTHER_GRAPH))
    plant(common, GRAPH_RUN, b"{")

    with pytest.raises(ReceiptInputError):
        Store(common).list_graphs()
    remaining = Store(common).list_graphs(exclude=GRAPH_RUN)
    assert [journal.run_id for journal in remaining] == [OTHER_GRAPH]
    with pytest.raises(ReceiptInputError):
        Store(common).list_graphs(exclude="../" + GRAPH_RUN)


def test_kind_of_names_the_document_without_adopting_it(common: Path) -> None:
    store = Store(common)
    assert store.kind_of(GRAPH_RUN) is None
    store.save(receipt())
    Store(common).save_graph(progressed())

    assert store.kind_of(RECEIPT_RUN) == "receipt"
    assert store.kind_of(GRAPH_RUN) == "graph"
    assert store.kind_of(OTHER_GRAPH) is None
    with pytest.raises(StateError):
        store.save_graph(progressed())  # kind_of read nothing: still a blind create
    with pytest.raises(ReceiptInputError):
        store.kind_of("not-a-run")


def test_one_run_id_never_names_two_documents(common: Path) -> None:
    store = Store(common)
    store.save(receipt())

    with pytest.raises(StateError):
        store.save_graph(fresh(RECEIPT_RUN))
    assert not journal_path(common, RECEIPT_RUN).exists()

    planted = json.dumps(fresh(RECEIPT_RUN).serialize()).encode()
    plant(common, RECEIPT_RUN, planted)
    with pytest.raises(StateError):
        store.kind_of(RECEIPT_RUN)


def test_linked_worktrees_share_graph_journals(repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "-b", "feature", str(linked))

    Store(common_dir_of(repo)).save_graph(progressed())
    seen = Store(common_dir_of(linked)).load_graph(GRAPH_RUN)

    assert seen == progressed()
    assert journal_path(repo / ".git").is_file()
    assert not list((repo / ".git" / "worktrees").rglob("armory"))
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""
    assert git(linked, "status", "--porcelain", "--untracked-files=all") == ""


# --- private storage ----------------------------------------------------------------------


def test_missing_graph_reads_create_nothing(common: Path) -> None:
    store = Store(common)

    assert store.list_graphs() == ()
    with pytest.raises(FileNotFoundError):
        store.load_graph(GRAPH_RUN)
    assert store.kind_of(GRAPH_RUN) is None
    assert not (common / "armory").exists()

    store.save(receipt())
    assert store.list_graphs() == ()
    with pytest.raises(FileNotFoundError):
        store.load_graph(GRAPH_RUN)
    assert not (common / "armory" / "ship" / "graphs").exists()


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o606])
def test_graph_journal_readable_by_others_is_rejected_and_kept(
    common: Path, mode: int
) -> None:
    Store(common).save_graph(progressed())
    target = journal_path(common)
    target.chmod(mode)
    before = target.read_bytes()

    with pytest.raises(StateError):
        Store(common).load_graph(GRAPH_RUN)
    with pytest.raises(StateError):
        Store(common).list_graphs()
    with pytest.raises(StateError):
        Store(common).save_graph(progressed())
    assert target.read_bytes() == before


def test_hardlinked_graph_journal_is_rejected(common: Path, tmp_path: Path) -> None:
    Store(common).save_graph(progressed())
    os.link(journal_path(common), tmp_path / "alias.json")

    with pytest.raises(StateError):
        Store(common).load_graph(GRAPH_RUN)


def test_symlinked_graph_journal_is_never_followed(
    common: Path, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.json"
    victim.write_bytes(json.dumps(progressed().serialize()).encode())
    victim.chmod(0o600)
    link = graphs_dir(common) / f"{GRAPH_RUN}.json"
    link.symlink_to(victim)
    before = victim.read_bytes()

    with pytest.raises((StateError, OSError)):
        Store(common).load_graph(GRAPH_RUN)
    with pytest.raises((StateError, OSError)):
        Store(common).save_graph(progressed())
    assert link.is_symlink()
    assert victim.read_bytes() == before


@pytest.mark.parametrize("mode", [0o777, 0o770, 0o707])
def test_graph_directory_writable_by_others_is_rejected(
    common: Path, mode: int
) -> None:
    Store(common).save(receipt())
    Store(common).save_graph(progressed())
    directory = common / "armory" / "ship" / "graphs"
    directory.chmod(mode)
    before = sorted(path.name for path in directory.iterdir())

    for operation in (
        lambda: Store(common).load_graph(GRAPH_RUN),
        lambda: Store(common).list_graphs(),
        lambda: Store(common).save_graph(fresh(OTHER_GRAPH)),
        lambda: Store(common).kind_of(GRAPH_RUN),
    ):
        with pytest.raises(StateError):
            operation()
    assert sorted(path.name for path in directory.iterdir()) == before
    assert Store(common).list_runs() == (receipt(),)


def test_symlinked_graph_directory_is_rejected(common: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    planted = elsewhere / f"{GRAPH_RUN}.json"
    planted.write_bytes(json.dumps(progressed().serialize()).encode())
    planted.chmod(0o600)
    Store(common).save(receipt())
    (common / "armory" / "ship" / "graphs").symlink_to(elsewhere)

    with pytest.raises(StateError):
        Store(common).load_graph(GRAPH_RUN)
    with pytest.raises(StateError):
        Store(common).list_graphs()
    with pytest.raises(StateError):
        Store(common).save_graph(fresh(OTHER_GRAPH))
    assert sorted(path.name for path in elsewhere.iterdir()) == [planted.name]


# --- compare-and-swap saves ---------------------------------------------------------------


def test_stale_graph_writer_cannot_overwrite_a_newer_journal(common: Path) -> None:
    first = Store(common)
    second = Store(common)
    first.save_graph(fresh())
    stale = second.load_graph(GRAPH_RUN)
    current = first.load_graph(GRAPH_RUN)
    current.next_action = "newer decision"
    current.status = "BLOCKED"
    first.save_graph(current)
    newer_bytes = journal_path(common).read_bytes()

    stale.next_action = "stale decision"
    with pytest.raises(StateError):
        second.save_graph(stale)

    assert journal_path(common).read_bytes() == newer_bytes
    reloaded = Store(common).load_graph(GRAPH_RUN)
    assert (reloaded.next_action, reloaded.status) == ("newer decision", "BLOCKED")
    assert sorted(path.name for path in journal_path(common).parent.iterdir()) == [
        f"{GRAPH_RUN}.json"
    ]


def test_graph_changed_outside_any_controller_is_not_overwritten(
    common: Path,
) -> None:
    store = Store(common)
    store.save_graph(fresh())
    held = store.load_graph(GRAPH_RUN)
    outside = progressed().serialize()
    journal_path(common).write_bytes(json.dumps(outside).encode())

    held.issue = "from the stale view"
    with pytest.raises(StateError):
        store.save_graph(held)

    assert json.loads(journal_path(common).read_bytes()) == outside


def test_blind_graph_create_cannot_overwrite_an_existing_journal(common: Path) -> None:
    Store(common).save_graph(progressed())
    original = journal_path(common).read_bytes()

    with pytest.raises(StateError):
        Store(common).save_graph(fresh())

    assert journal_path(common).read_bytes() == original


def test_deleted_graph_journal_is_not_silently_recreated(common: Path) -> None:
    store = Store(common)
    journal = progressed()
    store.save_graph(journal)
    journal_path(common).unlink()

    with pytest.raises(StateError):
        store.save_graph(journal)

    assert not journal_path(common).exists()


def test_graph_and_receipt_baselines_do_not_collide(common: Path) -> None:
    store = Store(common)
    store.save(receipt())
    store.save_graph(fresh())
    journal = store.load_graph(GRAPH_RUN)
    record = store.load(RECEIPT_RUN)

    journal.next_action = "continue the graph"
    record.next_action = "continue the node"
    store.save_graph(journal)
    store.save(record)

    assert Store(common).load_graph(GRAPH_RUN).next_action == "continue the graph"
    assert Store(common).load(RECEIPT_RUN).next_action == "continue the node"
