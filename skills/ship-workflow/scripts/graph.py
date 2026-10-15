"""Manual stack graphs: the explicit ``--stack-plan`` packet, its model and journal.

A stack plan is an explicit caller decision loaded only from the path given with
``--stack-plan``; it is never discovered from repository files and is not a
repository policy language. It binds one repository (host and base repository),
the explicit trunk base ref, the parent relation of every node (acyclic, rooted at
the trunk), the selected PR set, the observed exact head identity and the expected
current provider base of every node, an optional explicit fork boundary, and for
every selected node a revision-free gate :class:`~lifecycle.Decision` plus a
source-backed provenance decision.

The packet never declares a node merged: current provider facts decide that, and
the runtime refuses a packet that contradicts what it observes. A selected node is
authorized to be landed if it is not already landed. Unselected nodes are context
that is preserved untouched. Provenance is only ever ``preserve``: published commit
trailers, PR metadata and an operator-authored ``.stack-prs.yaml`` are cited as
sources and are never parsed, stamped or rewritten here.

Two identities are derived from the normalized packet. ``identity`` covers all of
it, including decisions and head revisions. ``topology`` covers only the graph
shape (repository, trunk and each node's PR, parent, selection, head namespace and
ref, base ref and fork), so a refreshed packet that changes only decisions or head
revisions keeps the topology of the run it resumes.

:func:`execute_graph` continues the selected nodes parent-first from current
provider and Git facts: observe, decide one action, act, observe again. Before a
node is rewritten or merged, each open selected child's fork (the node head its own
slice sits on) is captured. After a parent lands, a child's own slice is proved by
the clean three-way tree (base fork, ours trunk tip, theirs old head), replayed with
plumbing and pushed only under an explicit expected-old lease, then retargeted to
the trunk. Every such mutation holds the common-directory lock, re-observes, journals
a durable intent before dispatch and reconciles the actual outcome; an unknown
outcome is reconciled from facts on resumption and never resent. Landing, renewed
gates, post-merge acceptance and cleanup stay with :func:`lifecycle.execute`, one
preassigned per-node receipt each. :func:`inspect_graph` reports the same plan
without any write.

:func:`membership` classifies every node at one point. A selection of manual nodes
runs here; a selection of members of one GitHub-native stack is handed to the
native stack owner (``native_stack``), which reuses this coordinator's journal,
locking, deadline and per-node lifecycle landing; a mixed selection is BLOCKED
before any write. A graph run never changes from one kind to the other.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NoReturn, cast

import lifecycle
from changeset import (
    ChangesetStop,
    GatePolicy,
    PlanError,
    check_outgoing,
    digest,
    parse_gates,
)
from git_ops import GitError, GitRefused, GitRepository
from git_ops import Promotion as SliceProof
from github_ops import GitHub, ProviderError, PullRequest
from lifecycle import Decision, Endpoint, Policy, Status, parse_decision
from state_store import (
    GRAPH_MAX_INTENTS,
    GraphIntent,
    GraphJournal,
    GraphNode,
    LockBusy,
    NativeRecord,
    Promotion,
    Receipt,
    ReceiptInputError,
    StateError,
    Store,
    validate_branch,
)

STACK_PLAN_SCHEMA_VERSION = 1
MAX_STACK_PLAN_BYTES = 256 * 1024
MAX_STACK_NODES = 64
MAX_PR_NUMBER = 2**31 - 1
MAX_PROVENANCE_SOURCES = 64
MAX_SOURCE_CHARS = 1024
PROVENANCE_DISPOSITIONS = ("preserve",)
_PLAN_KEYS = frozenset({"schema_version", "repository", "trunk", "nodes"})
_NODE_KEYS = frozenset({"pr", "parent", "select", "head", "base"})
_OPTIONAL_NODE_KEYS = frozenset({"fork"})
_SELECTED_KEYS = frozenset({"decision", "provenance"})
_HEAD_KEYS = frozenset({"repo", "ref", "sha"})
_PROVENANCE_KEYS = frozenset({"disposition", "sources"})
_DECISION_KEYS = frozenset(Decision.__dataclass_fields__)
_NONE: frozenset[str] = frozenset()
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TOPOLOGY_FIELDS = ("parent", "select", "head repository", "head ref", "base", "fork")


class StackPlanError(ValueError):
    """A stack plan packet is malformed, unsupported or contradictory (exit 2)."""


@dataclass(frozen=True)
class Provenance:
    """How a selected node's published provenance is treated: only ever preserved."""

    disposition: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class PlanNode:
    """One PR of the graph as the packet binds it.

    ``head_repo``/``head_ref``/``head_sha`` are the exact observed head identity and
    ``base_ref`` the expected current provider base: the trunk, or the parent's head
    ref when the parent's head lives in the base repository. ``fork`` is an explicit
    source-backed old parent head (the boundary the node's own slice sits on).
    ``decision`` and ``provenance`` are present exactly for selected nodes.
    """

    pr: int
    parent: int | None
    selected: bool
    head_repo: str
    head_ref: str
    head_sha: str
    base_ref: str
    fork: str | None
    decision: Decision | None
    provenance: Provenance | None


@dataclass(frozen=True)
class StackPlan:
    """A validated, immutable stack graph; ``nodes`` are sorted by PR number."""

    host: str
    repo: str
    trunk: str
    nodes: tuple[PlanNode, ...]
    identity: str
    topology: str

    def node(self, pr: int) -> PlanNode:
        """The node for ``pr``; a PR outside the plan is a contradiction."""
        for node in self.nodes:
            if node.pr == pr:
                return node
        raise StackPlanError(f"PR #{pr} is not a node of this stack plan")

    def children(self, pr: int | None) -> tuple[PlanNode, ...]:
        """Direct children of ``pr`` in PR-number order; ``None`` names the trunk."""
        if pr is not None:
            self.node(pr)
        return tuple(node for node in self.nodes if node.parent == pr)

    def order(self) -> tuple[PlanNode, ...]:
        """Every node parent-first; among ready nodes the lowest PR number first."""
        placed: set[int] = set()
        result: list[PlanNode] = []
        while len(result) < len(self.nodes):
            ready = next(
                node
                for node in self.nodes
                if node.pr not in placed
                and (node.parent is None or node.parent in placed)
            )
            placed.add(ready.pr)
            result.append(ready)
        return tuple(result)

    def ancestors(self, pr: int) -> tuple[int, ...]:
        """Ancestor PR numbers of ``pr``, nearest parent first."""
        result: list[int] = []
        parent = self.node(pr).parent
        while parent is not None:
            result.append(parent)
            parent = self.node(parent).parent
        return tuple(result)

    def unselected_ancestors(self, pr: int) -> tuple[int, ...]:
        """Ancestors of ``pr`` the plan does not select, nearest first.

        Each of them must be observed MERGED before ``pr`` may land: parent-first
        scope is never silently expanded to land an unselected node.
        """
        return tuple(
            ancestor
            for ancestor in self.ancestors(pr)
            if not self.node(ancestor).selected
        )

    def selected_nodes(self) -> tuple[PlanNode, ...]:
        """Selected nodes in :meth:`order`."""
        return tuple(node for node in self.order() if node.selected)

    def canonical(self) -> dict[str, object]:
        """The normalized packet; :func:`parse_stack_plan` rebuilds an equal plan."""
        return _canonical(self.host, self.repo, self.trunk, self.nodes)


def decision_identity(decision: Decision) -> str:
    """SHA-256 identity of a revision-free decision in its normalized JSON form."""
    return digest(_decision_json(decision))


def load_stack_plan(path: Path) -> StackPlan:
    """Read and validate the explicit packet at ``path``; links are refused."""
    data = _read_packet(path)
    if b"\x00" in data:
        raise StackPlanError("stack plan contains a NUL byte")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StackPlanError("stack plan is not UTF-8 text") from error
    try:
        raw: object = json.loads(
            text, object_pairs_hook=_unique_keys, parse_constant=_constant
        )
    except StackPlanError:
        raise
    except RecursionError as error:
        raise StackPlanError("stack plan nests JSON values too deeply") from error
    except ValueError as error:
        raise StackPlanError("stack plan is not valid JSON") from error
    return parse_stack_plan(raw)


def parse_stack_plan(raw: object) -> StackPlan:
    """Validate an already-decoded packet (a loaded file or a journaled plan)."""
    data = _object(raw, "stack plan")
    _keys(data, _PLAN_KEYS, _NONE, "stack plan")
    version = data["schema_version"]
    if type(version) is not int or version != STACK_PLAN_SCHEMA_VERSION:
        raise StackPlanError("unsupported stack plan schema_version")
    host, repo = _repository(data["repository"])
    trunk = _branch(data["trunk"], "trunk")
    rows = data["nodes"]
    if not isinstance(rows, list) or not rows:
        raise StackPlanError("nodes must be a nonempty list")
    if len(rows) > MAX_STACK_NODES:
        raise StackPlanError(f"stack plan supports at most {MAX_STACK_NODES} nodes")
    nodes = [_node(row, index) for index, row in enumerate(rows)]
    by_pr: dict[int, PlanNode] = {}
    heads: dict[tuple[str, str], int] = {}
    for node in nodes:
        if node.pr in by_pr:
            raise StackPlanError(f"PR #{node.pr} appears more than once")
        by_pr[node.pr] = node
        head = (node.head_repo.lower(), node.head_ref)
        if head in heads:
            raise StackPlanError(
                f"node #{node.pr} reuses the head {node.head_repo}:{node.head_ref} "
                f"of node #{heads[head]}"
            )
        heads[head] = node.pr
        if head == (repo.lower(), trunk):
            raise StackPlanError(f"node #{node.pr} head is the trunk itself")
    for node in nodes:
        if node.parent == node.pr:
            raise StackPlanError(f"node #{node.pr} cannot be its own parent")
        if node.parent is not None and node.parent not in by_pr:
            raise StackPlanError(
                f"node #{node.pr} parent #{node.parent} is not a node of this plan"
            )
    _acyclic(by_pr)
    for node in nodes:
        _check_base(node, by_pr, repo, trunk)
    if not any(node.selected for node in nodes):
        raise StackPlanError("stack plan selects no node")
    ordered = tuple(sorted(nodes, key=lambda node: node.pr))
    return StackPlan(
        host=host,
        repo=repo,
        trunk=trunk,
        nodes=ordered,
        identity=digest(_canonical(host, repo, trunk, ordered)),
        topology=digest(
            {
                "host": host,
                "repo": repo.lower(),
                "trunk": trunk,
                "nodes": [[node.pr, *_topology_row(node)] for node in ordered],
            }
        ),
    )


def topology_differences(frozen: StackPlan, refreshed: StackPlan) -> tuple[str, ...]:
    """Every graph-shape difference between two plans, each naming what changed.

    The result is empty exactly when both topologies are equal, which is when a
    refreshed packet may replace a frozen one (decisions and head revisions only).
    """
    differences: list[str] = []
    if (frozen.host, frozen.repo.lower()) != (refreshed.host, refreshed.repo.lower()):
        differences.append(
            f"repository changed from {frozen.host}/{frozen.repo} "
            f"to {refreshed.host}/{refreshed.repo}"
        )
    if frozen.trunk != refreshed.trunk:
        differences.append(
            f"trunk changed from {frozen.trunk!r} to {refreshed.trunk!r}"
        )
    before = {node.pr: node for node in frozen.nodes}
    after = {node.pr: node for node in refreshed.nodes}
    for pr in sorted(before.keys() - after.keys()):
        differences.append(f"node #{pr} is missing")
    for pr in sorted(after.keys() - before.keys()):
        differences.append(f"node #{pr} is new")
    for pr in sorted(before.keys() & after.keys()):
        for label, old, new in zip(
            _TOPOLOGY_FIELDS,
            _topology_row(before[pr]),
            _topology_row(after[pr]),
            strict=True,
        ):
            if old != new:
                differences.append(
                    f"node #{pr} {label} changed from {old!r} to {new!r}"
                )
    return tuple(differences)


# -- stack plan packet -----------------------------------------------------------------


def _read_packet(path: Path) -> bytes:
    try:
        if stat.S_ISLNK(path.lstat().st_mode):
            raise StackPlanError("stack plan must be a regular file, not a link")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as error:
        raise StackPlanError(f"cannot open the stack plan: {_reason(error)}") from error
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise StackPlanError("stack plan must be a regular file")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(MAX_STACK_PLAN_BYTES + 1)
    except OSError as error:
        raise StackPlanError(f"cannot read the stack plan: {_reason(error)}") from error
    finally:
        os.close(fd)
    if len(data) > MAX_STACK_PLAN_BYTES:
        raise StackPlanError(f"stack plan exceeds {MAX_STACK_PLAN_BYTES} bytes")
    return data


def _reason(error: OSError) -> str:
    return error.strerror or type(error).__name__


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StackPlanError(f"stack plan repeats the JSON key {key[:40]!r}")
        result[key] = value
    return result


def _constant(name: str) -> NoReturn:
    raise StackPlanError(f"stack plan contains the non-finite number {name}")


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise StackPlanError(f"{label} must be a JSON object")
    return cast("dict[str, object]", value)


def _keys(
    raw: dict[str, object],
    required: frozenset[str],
    optional: frozenset[str],
    label: str,
) -> None:
    missing = sorted(required - raw.keys())
    unknown = sorted(raw.keys() - required - optional)
    if missing or unknown:
        problems = []
        if missing:
            problems.append("missing " + ", ".join(missing))
        if unknown:
            problems.append("unknown " + ", ".join(repr(key[:40]) for key in unknown))
        raise StackPlanError(f"{label} fields: {'; '.join(problems)}")


def _pr(value: object, label: str) -> int:
    if type(value) is not int or not 0 < value <= MAX_PR_NUMBER:
        raise StackPlanError(f"{label} must be a positive PR number")
    return value


def _oid(value: object, label: str) -> str:
    if not isinstance(value, str) or _OID.fullmatch(value) is None:
        raise StackPlanError(f"{label} must be a full lowercase object id")
    return value


def _branch(value: object, label: str) -> str:
    try:
        return validate_branch(value, label)
    except ReceiptInputError as error:
        raise StackPlanError(str(error)) from error


def _owner_repo(value: object, label: str) -> str:
    parts = value.split("/") if isinstance(value, str) else []
    if len(parts) != 2 or any(_NAME.fullmatch(part) is None for part in parts):
        raise StackPlanError(f"{label} must be OWNER/REPO")
    return "/".join(parts)


def _repository(value: object) -> tuple[str, str]:
    """``[HOST/]OWNER/REPO`` normalized as ``ship.repository_selector`` does.

    The default host is github.com and the host is lower-cased; it must also be a
    DNS-style name (no underscore) that the graph journal can record.
    """
    parts = value.split("/") if isinstance(value, str) else []
    host = "github.com"
    if len(parts) == 3:
        host, parts = parts[0], parts[1:]
    if (
        len(parts) != 2
        or _HOST.fullmatch(host) is None
        or any(_NAME.fullmatch(part) is None for part in parts)
    ):
        raise StackPlanError("repository must be OWNER/REPO or HOST/OWNER/REPO")
    return host.lower(), "/".join(parts)


def _decision(value: object, label: str) -> Decision:
    raw = _object(value, label)
    _keys(raw, _NONE, _DECISION_KEYS, label)
    try:
        return parse_decision(raw)
    except (ValueError, TypeError) as error:
        raise StackPlanError(f"{label}: {error}") from error


def _provenance(value: object, label: str) -> Provenance:
    raw = _object(value, label)
    _keys(raw, _PROVENANCE_KEYS, _NONE, label)
    if raw["disposition"] not in PROVENANCE_DISPOSITIONS:
        raise StackPlanError(
            f"{label}.disposition must be 'preserve'; stamping or rewriting "
            "published provenance is unsupported"
        )
    sources = raw["sources"]
    if not isinstance(sources, list) or not sources:
        raise StackPlanError(f"{label}.sources must be a nonempty list")
    if len(sources) > MAX_PROVENANCE_SOURCES:
        raise StackPlanError(
            f"{label}.sources supports at most {MAX_PROVENANCE_SOURCES} entries"
        )
    if any(
        not isinstance(source, str)
        or not source.strip()
        or len(source) > MAX_SOURCE_CHARS
        or _CONTROL.search(source)
        for source in sources
    ):
        raise StackPlanError(
            f"{label}.sources entries must be nonempty plain strings of at most "
            f"{MAX_SOURCE_CHARS} characters"
        )
    names = tuple(cast("list[str]", sources))
    if len(set(names)) != len(names):
        raise StackPlanError(f"{label}.sources must be unique")
    return Provenance("preserve", names)


def _node(value: object, index: int) -> PlanNode:
    raw = _object(value, f"nodes[{index}]")
    if "pr" not in raw:
        raise StackPlanError(f"nodes[{index}] needs its pr number")
    pr = _pr(raw["pr"], f"nodes[{index}].pr")
    label = f"node #{pr}"
    selected = raw.get("select")
    if not isinstance(selected, bool):
        raise StackPlanError(f"{label}.select must be true or false")
    present = _SELECTED_KEYS & raw.keys()
    if selected and present != _SELECTED_KEYS:
        raise StackPlanError(
            f"selected {label} needs both a source-backed decision and provenance"
        )
    if not selected and present:
        raise StackPlanError(
            f"unselected {label} must not carry decision or provenance"
        )
    _keys(raw, _NODE_KEYS | present, _OPTIONAL_NODE_KEYS, label)
    parent = None if raw["parent"] is None else _pr(raw["parent"], f"{label}.parent")
    head = _object(raw["head"], f"{label}.head")
    _keys(head, _HEAD_KEYS, _NONE, f"{label}.head")
    fork: str | None = None
    if "fork" in raw:
        if parent is None:
            raise StackPlanError(
                f"{label}.fork needs a parent; a trunk-based node has no fork boundary"
            )
        fork = _oid(raw["fork"], f"{label}.fork")
    node = PlanNode(
        pr=pr,
        parent=parent,
        selected=selected,
        head_repo=_owner_repo(head["repo"], f"{label}.head.repo"),
        head_ref=_branch(head["ref"], f"{label}.head.ref"),
        head_sha=_oid(head["sha"], f"{label}.head.sha"),
        base_ref=_branch(raw["base"], f"{label}.base"),
        fork=fork,
        decision=_decision(raw["decision"], f"{label}.decision") if selected else None,
        provenance=(
            _provenance(raw["provenance"], f"{label}.provenance") if selected else None
        ),
    )
    if node.fork == node.head_sha:
        raise StackPlanError(
            f"{label}.fork is its own head; a fork boundary must be an older commit"
        )
    return node


def _acyclic(by_pr: dict[int, PlanNode]) -> None:
    for start in sorted(by_pr):
        path: list[int] = []
        current: int | None = start
        while current is not None:
            if current in path:
                cycle = [*path[path.index(current) :], current]
                raise StackPlanError(
                    "parent relation has a cycle: "
                    + " -> ".join(f"#{pr}" for pr in cycle)
                )
            path.append(current)
            current = by_pr[current].parent


def _check_base(
    node: PlanNode, by_pr: dict[int, PlanNode], repo: str, trunk: str
) -> None:
    if node.base_ref == trunk:
        return
    if node.parent is None:
        raise StackPlanError(
            f"node #{node.pr} base {node.base_ref!r} must be the trunk {trunk!r}"
        )
    parent = by_pr[node.parent]
    if parent.head_repo.lower() != repo.lower() or node.base_ref != parent.head_ref:
        raise StackPlanError(
            f"node #{node.pr} base {node.base_ref!r} is neither the trunk {trunk!r} "
            f"nor the head ref of parent #{parent.pr} in {repo}"
        )


def _decision_json(decision: Decision) -> dict[str, object]:
    row: dict[str, object] = {
        "sources": list(decision.sources),
        "expected_checks": list(decision.expected_checks),
        "merge_method": decision.merge_method,
        "post_merge_commands": [list(argv) for argv in decision.post_merge_commands],
        "allowed_skips": list(decision.allowed_skips),
        "head_only_checks": list(decision.head_only_checks),
        "protected_refs": list(decision.protected_refs),
        "ci_free": decision.ci_free,
    }
    # Only a stricter level is spelled out, so every routine (and every historical)
    # decision keeps the identity it was saved with; an absent key is "routine".
    if decision.assurance != "routine":
        row["assurance"] = decision.assurance
    if (
        decision.assurance == "routine"
        and not decision.expected_checks
        and not decision.ci_free
    ):
        row.pop("expected_checks")
    return row


def _node_json(node: PlanNode) -> dict[str, object]:
    row: dict[str, object] = {
        "pr": node.pr,
        "parent": node.parent,
        "select": node.selected,
        "head": {"repo": node.head_repo, "ref": node.head_ref, "sha": node.head_sha},
        "base": node.base_ref,
    }
    if node.fork is not None:
        row["fork"] = node.fork
    if node.decision is not None:
        row["decision"] = _decision_json(node.decision)
    if node.provenance is not None:
        row["provenance"] = {
            "disposition": node.provenance.disposition,
            "sources": list(node.provenance.sources),
        }
    return row


def _canonical(
    host: str, repo: str, trunk: str, nodes: tuple[PlanNode, ...]
) -> dict[str, object]:
    return {
        "schema_version": STACK_PLAN_SCHEMA_VERSION,
        "repository": f"{host}/{repo}",
        "trunk": trunk,
        "nodes": [_node_json(node) for node in nodes],
    }


def _topology_row(node: PlanNode) -> tuple[object, ...]:
    return (
        node.parent,
        node.selected,
        node.head_repo.lower(),
        node.head_ref,
        node.base_ref,
        node.fork,
    )


# -- graph journal binding -------------------------------------------------------------


def new_journal(
    plan: StackPlan,
    *,
    run_id: str,
    endpoint: str,
    code_identity: str,
    created_at: str,
) -> GraphJournal:
    """A fresh, strictly validated journal for ``plan``.

    Selected nodes start PENDING and unselected context nodes RETAINED. Node
    heads/bases start at the packet's observed identities; per-node run ids,
    captures and promotions are recorded later, each before its mutation.
    """
    journal = GraphJournal(
        run_id=run_id,
        host=plan.host,
        repo=plan.repo,
        trunk=plan.trunk,
        endpoint=endpoint,
        plan_identity=plan.identity,
        topology=plan.topology,
        plan=plan.canonical(),
        code_identity=code_identity,
        nodes=[
            GraphNode(
                pr=node.pr,
                parent=node.parent,
                selected=node.selected,
                head_repo=node.head_repo,
                head_ref=node.head_ref,
                head_sha=node.head_sha,
                base_ref=node.base_ref,
                decision_identity=(
                    None if node.decision is None else decision_identity(node.decision)
                ),
                state="PENDING" if node.selected else "RETAINED",
            )
            for node in plan.nodes
        ],
        created_at=created_at,
        updated_at=created_at,
    )
    GraphJournal.parse(journal.serialize())
    return journal


def journal_plan(journal: GraphJournal) -> StackPlan:
    """The frozen plan of ``journal``, cross-checked against the journal itself.

    ``state_store`` validates only the journal's structure; this rebuilds the plan
    with :func:`parse_stack_plan` and requires its identities, repository, trunk and
    every node's parent, selection, head namespace/ref and decision identity to be
    the journal's. Namespaces compare case-insensitively, as provider namespaces
    and the topology do, so a refreshed packet that only changes their case still
    resumes. A journal base is the planned base or, once retargeted, the trunk. A
    journal fork may differ from the plan only where the plan has no explicit fork
    (a fork captured from facts).
    """
    try:
        plan = parse_stack_plan(journal.plan)
    except StackPlanError as error:
        raise ReceiptInputError(f"graph journal plan is invalid: {error}") from error
    if (plan.identity, plan.topology) != (journal.plan_identity, journal.topology):
        raise ReceiptInputError(
            "graph journal plan identity or topology does not match its plan"
        )
    where = (journal.host, journal.repo.lower(), journal.trunk)
    if (plan.host, plan.repo.lower(), plan.trunk) != where:
        raise ReceiptInputError(
            "graph journal repository or trunk does not match its plan"
        )
    if [row.pr for row in journal.nodes] != [node.pr for node in plan.nodes]:
        raise ReceiptInputError("graph journal nodes are not the plan's nodes")
    for row, node in zip(journal.nodes, plan.nodes, strict=True):
        expected = None if node.decision is None else decision_identity(node.decision)
        recorded = (row.parent, row.selected, row.head_repo.lower(), row.head_ref)
        planned = (node.parent, node.selected, node.head_repo.lower(), node.head_ref)
        if recorded != planned or row.decision_identity != expected:
            raise ReceiptInputError(
                f"graph journal node #{row.pr} does not match its plan"
            )
        if row.base_ref not in (node.base_ref, plan.trunk):
            raise ReceiptInputError(
                f"graph journal node #{row.pr} base {row.base_ref!r} is neither its "
                f"planned base {node.base_ref!r} nor the trunk"
            )
        if node.fork is not None and row.fork is not None and row.fork != node.fork:
            raise ReceiptInputError(
                f"graph journal node #{row.pr} fork contradicts the plan"
            )
    return plan


def resumed_plan(journal: GraphJournal, refreshed: StackPlan | None) -> StackPlan:
    """The plan a resumed graph run continues.

    Without a packet it is the journal's frozen plan (:func:`journal_plan`). A
    refreshed packet is accepted only with the frozen topology, so only decisions
    and head revisions change; anything else is a contradictory or new plan.
    """
    frozen = journal_plan(journal)
    if refreshed is None:
        return frozen
    differences = topology_differences(frozen, refreshed)
    if differences:
        raise StackPlanError(
            "the stack plan contradicts the resumed graph run: "
            + "; ".join(differences)
        )
    return refreshed


# -- graph runtime ---------------------------------------------------------------------

MAX_GRAPH_STEPS = 512
_DETAIL_LIMIT = 512
_REFRESH = "refresh the --stack-plan packet from current facts or resolve the change"
# Journaled detail of an intent that reconciliation found not applied.
_RECONCILED = {
    "rewrite-push": "reconciled: the remote still holds the old head",
    "retarget": "reconciled: the base is unchanged",
    "advance-local": "reconciled: the local branch was not advanced",
}
# What a read-only promotion proof leaves to the plumbing replay at execution.
_REPLAY_LIMITS = (
    "the per-commit replay (a conflict at an intermediate commit, a commit that "
    "becomes empty) and the repository's own merge configuration are proven only "
    "at execution"
)


class _Stop(RuntimeError):
    def __init__(self, status: Status, reason: str, next_action: str) -> None:
        super().__init__(reason)
        self.status: Status = status
        self.next_action = next_action


@dataclass(frozen=True)
class Finding:
    """A fact that stops the graph before any mutation, and the next safe action."""

    status: Status
    pr: int | None
    reason: str
    next_action: str


def membership(pr: PullRequest) -> Literal["manual", "native"]:
    """The single manual/native classification point of a graph node.

    A PR carrying a provider stack object is ``native``, even when parts of its
    stack identity are unknown; nothing converts it into a manual node, and no
    native member ever receives an ordinary merge.
    """
    return "native" if pr.native else "manual"


def selection(
    plan: StackPlan, prs: Mapping[int, PullRequest]
) -> Literal["manual", "native", "mixed"]:
    """The membership of the selected nodes; ``mixed`` is BLOCKED by every owner."""
    kinds = {membership(prs[node.pr]) for node in plan.selected_nodes()}
    if len(kinds) != 1:
        return "mixed"
    return "native" if kinds == {"native"} else "manual"


def route_finding(
    plan: StackPlan, prs: Mapping[int, PullRequest], journal: GraphJournal | None
) -> Finding | None:
    """Why the observed selection cannot continue ``journal``; ``None`` when it can.

    A mixed selection is BLOCKED. A journal that recorded a native request stays
    native, and a manual journal that recorded graph intents, or whose selection
    still has an open node, never becomes native.
    """
    kind = selection(plan, prs)
    if kind == "mixed":
        return Finding(
            "BLOCKED",
            None,
            "the selection mixes native stack members with manual nodes",
            "select only manual nodes or only members of one native stack; "
            "nothing is converted from one kind to the other",
        )
    native = journal is not None and journal.native is not None
    if kind == "manual" and native:
        return Finding(
            "NEEDS_JUDGMENT",
            None,
            "this graph run recorded a native stack request, but its selection is "
            "no longer native",
            "inspect the provider facts; a native run never continues as a manual one",
        )
    open_selected = any(prs[node.pr].state == "OPEN" for node in plan.selected_nodes())
    if (
        kind == "native"
        and journal is not None
        and not native
        and (journal.intents or open_selected)
    ):
        return Finding(
            "NEEDS_JUDGMENT",
            None,
            "a manual graph run never continues as a native stack run",
            "start a new graph run from current facts",
        )
    return None


def contradictions(
    plan: StackPlan,
    prs: Mapping[int, PullRequest],
    expected: Mapping[int, tuple[str, str]],
) -> tuple[Finding, ...]:
    """Every observed fact contradicting the plan where a selected landing needs it.

    That scope is every selected node and each of its ancestors. ``expected`` maps
    each node to its last confirmed head OID and base ref. A node whose parent
    landed may already sit on the trunk (provider retargeting); every other change
    of namespace, state, head or base is a judgment that blocks every graph
    mutation. A selected node with an open unselected ancestor needs judgment:
    parent-first scope never widens. Retained nodes outside the scope are reported
    by :func:`context_changes` instead. Execution reaches this check only for a
    manual selection (:func:`selection`); a dry run also lists it for a mixed one.
    """
    findings: list[Finding] = []
    relevant = _scope(plan)
    for node in plan.order():
        if node.pr not in relevant:
            continue
        problem = _identity_problem(plan, node, prs, expected[node.pr])
        if problem is not None:
            findings.append(Finding("NEEDS_JUDGMENT", node.pr, problem, _REFRESH))
            continue
        if not node.selected:
            continue
        scope = [
            ancestor
            for ancestor in plan.unselected_ancestors(node.pr)
            if prs[ancestor].state != "MERGED"
        ]
        if scope:
            findings.append(
                Finding(
                    "NEEDS_JUDGMENT",
                    node.pr,
                    f"#{node.pr} needs its open unselected ancestor #{scope[0]} "
                    "landed first",
                    f"select #{scope[0]} or land it first; scope never widens",
                )
            )
    return tuple(findings)


def context_changes(
    plan: StackPlan,
    prs: Mapping[int, PullRequest],
    expected: Mapping[int, tuple[str, str]],
) -> tuple[dict[str, object], ...]:
    """Changes of retained nodes outside every selected node's ancestry.

    No selected landing depends on those nodes and the graph never mutates them, so
    a moved head, another base or a closed PR there is reported and never stops the
    graph. Their refs stay retained while an open PR uses them (lifecycle cleanup).
    """
    scope = _scope(plan)
    changes: list[dict[str, object]] = []
    for node in plan.order():
        if node.pr in scope:
            continue
        problem = _identity_problem(plan, node, prs, expected[node.pr])
        if problem is not None:
            changes.append({"pr": node.pr, "reason": problem})
    return tuple(changes)


def _scope(plan: StackPlan) -> frozenset[int]:
    """Selected nodes and their ancestors: the nodes a selected landing depends on."""
    return frozenset(
        number
        for node in plan.selected_nodes()
        for number in (node.pr, *plan.ancestors(node.pr))
    )


def _identity_problem(
    plan: StackPlan,
    node: PlanNode,
    prs: Mapping[int, PullRequest],
    expected: tuple[str, str],
) -> str | None:
    pr = prs[node.pr]
    head, base = expected
    label = f"#{node.pr}"
    parent_merged = node.parent is not None and prs[node.parent].state == "MERGED"
    if pr.base_repo.lower() != plan.repo.lower():
        return f"{label} targets {pr.base_repo}, not {plan.repo}"
    if (pr.head_repo.lower(), pr.head_ref) != (node.head_repo.lower(), node.head_ref):
        return (
            f"{label} head is {pr.head_repo}:{pr.head_ref}, not the planned "
            f"{node.head_repo}:{node.head_ref}"
        )
    if pr.state == "CLOSED":
        return f"{label} is closed without a confirmed merge"
    if pr.head_sha != head:
        return f"{label} head moved outside the controller from {head} to {pr.head_sha}"
    if pr.base_ref != base and not (parent_merged and pr.base_ref == plan.trunk):
        return f"{label} base changed from {base!r} to {pr.base_ref!r}"
    if pr.state == "MERGED" and pr.base_ref != plan.trunk:
        return f"{label} landed into {pr.base_ref!r}, not the trunk {plan.trunk!r}"
    if pr.state == "MERGED" and node.parent is not None and not parent_merged:
        return f"{label} landed before its parent #{node.parent}"
    return None


def _expected(
    plan: StackPlan, journal: GraphJournal | None
) -> dict[int, tuple[str, str]]:
    """Last confirmed head and base of every node: the journal's, else the packet's."""
    if journal is None:
        return {node.pr: (node.head_sha, node.base_ref) for node in plan.nodes}
    return {row.pr: (row.head_sha, row.base_ref) for row in journal.nodes}


def _classify(
    git: GitRepository,
    host: str,
    plan: StackPlan,
    intent: GraphIntent,
    pr: PullRequest,
    head: str,
) -> tuple[Literal["CONFIRMED", "REJECTED"], str | None]:
    """How PENDING ``intent`` is reconciled from current facts; reads only.

    The new identity observed confirms it and the expected old one rejects it, so it
    is evaluated afresh; anything else stops as a judgment, because the outcome is
    not the controller's. A local compare-and-swap that did not land never lands
    later, so an ``advance-local`` at anything but its new head is rejected. ``pr``
    is the intent's PR as observed now and ``head`` its last confirmed head; the
    result is the outcome and the observed identity.
    """
    if intent.kind == "rewrite-push":
        node = plan.node(intent.pr)
        remote = git.remote_for(host, node.head_repo)
        if remote is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"#{intent.pr} head {node.head_repo} has no unambiguous associated "
                "Git remote",
                "associate that namespace with exactly one remote and resume",
            )
        observed = git.remote_head(remote, node.head_ref)
        if observed == intent.new:
            return "CONFIRMED", observed
        if observed == intent.expected_old:
            return "REJECTED", observed
        raise _Stop(
            "NEEDS_JUDGMENT",
            f"the pending rewrite push of #{intent.pr} left neither the expected "
            f"old nor the new head; the remote holds {observed}",
            "inspect the remote branch; nothing is pushed again blindly",
        )
    if intent.kind == "retarget":
        if pr.base_ref == intent.new:
            return "CONFIRMED", pr.base_ref
        if (pr.state, pr.base_ref, pr.head_sha) == ("OPEN", intent.expected_old, head):
            return "REJECTED", pr.base_ref
        raise _Stop(
            "NEEDS_JUDGMENT",
            f"the pending retarget of #{intent.pr} left the base "
            f"{pr.base_ref!r} at head {pr.head_sha}",
            "inspect the PR base and head; nothing is retargeted again blindly",
        )
    if intent.kind == "advance-local":
        current = git.local_heads().get(intent.resource)
        if current == intent.new:
            return "CONFIRMED", current
        return "REJECTED", current
    raise StateError(f"graph intent {intent.key} cannot be pending")


def _projected(
    git: GitRepository,
    host: str,
    plan: StackPlan,
    journal: GraphJournal | None,
    prs: Mapping[int, PullRequest],
) -> tuple[dict[int, tuple[str, str]], list[dict[str, object]], list[Finding]]:
    """Last confirmed identities as reconciliation would leave them; writes nothing.

    Each PENDING intent of ``journal`` is classified by :func:`_classify`, exactly
    as execution records it, and reported as a ``reconcile`` action (or a finding
    when it needs judgment). A confirmed rewrite push the provider does not report
    yet is a WAITING finding, as execution waits for it. Returns the projected
    identities, the actions and the findings.
    """
    expected = _expected(plan, journal)
    actions: list[dict[str, object]] = []
    findings: list[Finding] = []
    if journal is None:
        return expected, actions, findings
    for intent in journal.intents:
        head, base = expected[intent.pr]
        pr = prs[intent.pr]
        if intent.outcome == "CONFIRMED" and intent.kind == "rewrite-push":
            lagging = (pr.state, pr.head_sha, head)
            if lagging == ("OPEN", intent.expected_old, intent.new):
                expected[intent.pr] = (pr.head_sha, base)
                findings.append(
                    Finding(
                        "WAITING",
                        intent.pr,
                        f"the provider still reports the old head of #{intent.pr}",
                        "resume once the provider reports the pushed head",
                    )
                )
            continue
        if intent.outcome != "PENDING":
            continue
        try:
            outcome, observed = _classify(git, host, plan, intent, pr, head)
        except _Stop as stop:
            findings.append(
                Finding(stop.status, intent.pr, str(stop), stop.next_action)
            )
            continue
        except GitError as error:
            findings.append(
                Finding(
                    "BLOCKED",
                    intent.pr,
                    f"the pending {intent.kind} of #{intent.pr} is not evaluated: "
                    f"{_detail(error)}",
                    "resume once its remote is observable; nothing is sent again "
                    "blindly",
                )
            )
            continue
        if outcome == "CONFIRMED" and intent.kind == "rewrite-push":
            expected[intent.pr] = (intent.new, base)
        elif outcome == "CONFIRMED" and intent.kind == "retarget":
            expected[intent.pr] = (head, intent.new)
        actions.append(
            {
                "action": "reconcile",
                "pr": intent.pr,
                "intent": intent.key,
                "kind": intent.kind,
                "expected_old": intent.expected_old,
                "new": intent.new,
                "observed": observed,
                "outcome": outcome,
            }
        )
    return expected, actions, findings


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _detail(error: Exception) -> str:
    """A bounded, single-line, credential-free reason fit for a journal intent.

    Never empty (the journal refuses an empty detail): an error without a message
    is named by its type.
    """
    detail = _CONTROL.sub(" ", lifecycle._safe_error(error))[:_DETAIL_LIMIT].strip()
    return detail or type(error).__name__


def _bind(decision: Decision, pr: PullRequest, receipt: Receipt | None) -> Policy:
    """The node decision bound only to confirmed facts.

    A landed node keeps the binding its receipt records, so resuming its
    verification or cleanup is never a refreshed decision; otherwise the decision
    binds the freshly observed head and base, so every gate is renewed for them.
    """
    if pr.state == "MERGED" and receipt is not None and receipt.target is not None:
        recorded = decision.bound(receipt.head_sha, receipt.base_sha)
        if recorded.fingerprint == receipt.policy_identity:
            return recorded
    return decision.bound(pr.head_sha, pr.base_sha)


def _deferred_rows(receipt: Receipt) -> list[dict[str, object]] | None:
    """The failed cleanup rows of a landing whose cleanup waits on open dependents.

    That is a verified landing whose post-merge acceptance passed and whose every
    failed required cleanup target is retained only because an open PR still uses
    it as head or base; ``None`` for any other state.
    """
    failed = receipt.cleanup["failed"]
    if (
        receipt.status != "BLOCKED"
        or not receipt.merge_verified
        or receipt.validation_sha is None
        or not failed
        or any(row.get("reason") != lifecycle.OPEN_DEPENDENT_REASON for row in failed)
    ):
        return None
    return failed


def execute_graph(
    git: GitRepository,
    provider: GitHub,
    plan: StackPlan,
    endpoint: Endpoint,
    wait_timeout: float,
    store: Store,
    journal: GraphJournal | None = None,
    *,
    gates: GatePolicy | None = None,
) -> tuple[dict[str, object], int]:
    """Continue the selected nodes of ``plan`` parent-first through ``endpoint``.

    ``journal`` is the compare-and-swap loaded journal of the run being resumed;
    ``plan`` is then its frozen plan or a refreshed packet of the same topology
    (:func:`resumed_plan`). Returns the structured result and its exit code
    (``lifecycle.EXIT_CODES``; 130 after a cancellation whose journal was
    preserved). Ordinary failures become statuses. ``pr`` only observes, writing
    nothing; a completed run is re-verified without any write. ``gates`` is the
    explicit local validation decision: it runs before each rewrite push, is saved
    in the journal and, absent on a resume, is reused from it; a different one than
    the saved run's is refused.
    """
    if (provider.host, provider.full_name.lower()) != (plan.host, plan.repo.lower()):
        raise ValueError("the provider is not bound to the stack plan repository")
    if journal is not None:
        resumed_plan(journal, plan)
    return _GraphRun(
        git, provider, plan, endpoint, wait_timeout, store, journal, gates
    ).run()


class _GraphRun:
    """One explicit graph continuation: observe, decide one action, act, re-observe.

    Every graph mutation holds the common-directory lock, re-observes its exact
    preconditions, journals a durable intent before dispatch and reconciles the
    actual outcome after it. Landing, renewed gates, post-merge acceptance and
    cleanup of every node stay with :func:`lifecycle.execute`. A native selection
    is continued by the native stack owner (``native_stack.NativeRun``), a
    subclass that replaces the contradiction check, the refresh of a resumed
    packet, the journal record, the per-step action, the open-node preparation,
    the landing context and the result.
    """

    # Whether this coordinator owns native stack selections.
    native_owner = False

    def __init__(
        self,
        git: GitRepository,
        provider: GitHub,
        plan: StackPlan,
        endpoint: Endpoint,
        wait_timeout: float,
        store: Store,
        journal: GraphJournal | None,
        gates: GatePolicy | None = None,
    ) -> None:
        self.git = git
        self.provider = provider
        self.plan = plan
        self.endpoint: Endpoint = endpoint
        self.store = store
        self.journal = journal
        self.code = lifecycle.code_identity()
        self.deadline = time.monotonic() + wait_timeout
        self.prs: dict[int, PullRequest] = {}
        self.results: dict[int, dict[str, object]] = {}
        self.finished: dict[int, str] = {}
        self.settled: set[int] = set()
        self.dependents: dict[int, list[dict[str, object]]] = {}
        self.local: dict[tuple[int, str], dict[str, object]] = {}
        self.findings: tuple[Finding, ...] = ()
        self.changes: tuple[dict[str, object], ...] = ()
        self.scope = _scope(plan)
        self.checkout: dict[str, object] | None = None
        self.trunk_tip: str | None = None
        self.stopped: int | None = None
        self.initialized = False
        self.mutation_attempted = False
        self.gates = gates
        self.local_validation: dict[int, list[dict[str, object]]] = {}
        self.mutation_confirmed = False
        self.cancelled = False

    @property
    def record(self) -> GraphJournal:
        if self.journal is None:
            raise StateError("the graph run has no initialized journal")
        return self.journal

    # -- driver ----------------------------------------------------------------------

    def run(self) -> tuple[dict[str, object], int]:
        try:
            prs = self._observe()
            self._remote(self.plan.repo)
            owner = self._owner(prs)
            if owner is not self:
                return owner.run()
            if self.endpoint == "pr":
                # Observation only: pending intents are classified, never recorded.
                expected, _, pending = _projected(
                    self.git, self.provider.host, self.plan, self.journal, prs
                )
                self._check(prs, expected, tuple(pending))
                return self._finish("COMPLETE", None, "none", save=False)
            if self.journal is None:
                self._check(prs, _expected(self.plan, None), ())
            completed = self._initialize()
            self.initialized = True
            if completed:
                return self._noop()
            self._loop()
            return self._finish("COMPLETE", None, "none")
        except KeyboardInterrupt:
            self.cancelled = True
            return self._finish(
                "WAITING",
                "execution cancelled; reconcile before resuming",
                "resume this graph run; do not repeat an uncertain mutation",
            )
        except _Stop as error:
            return self._finish(error.status, str(error), error.next_action)
        except LockBusy as error:
            return self._finish(
                "WAITING",
                lifecycle._safe_error(error),
                "resume when the controller lock is free",
                save=False,
            )
        except ProviderError as error:
            status: Status = "WAITING" if error.kind == "WAITING" else "BLOCKED"
            return self._finish(
                status,
                lifecycle._safe_error(error),
                "reconcile current provider facts and resolve the exact prerequisite",
            )
        except (GitError, StateError, OSError) as error:
            return self._finish(
                "BLOCKED",
                lifecycle._safe_error(error),
                "resolve the reported safety/permission prerequisite and resume",
            )
        except ReceiptInputError as error:
            # A journal or node receipt the strict validators refuse (on load or
            # before a save): nothing invalid is written and the run stops here.
            return self._finish(
                "BLOCKED",
                lifecycle._safe_error(error),
                "inspect the private graph journal and node receipts before "
                "resumption; nothing invalid was written",
            )

    def _observe(self) -> dict[int, PullRequest]:
        self.prs = {node.pr: self.provider.read_pr(node.pr) for node in self.plan.nodes}
        return self.prs

    def _owner(self, prs: Mapping[int, PullRequest]) -> _GraphRun:
        """The coordinator of the observed selection: this run or the native owner.

        Imported here, not at module level: ``native_stack`` builds on this module.
        """
        finding = route_finding(self.plan, prs, self.journal)
        if finding is not None:
            raise _Stop(finding.status, finding.reason, finding.next_action)
        native = selection(self.plan, prs) == "native"
        if native == self.native_owner:
            return self
        if not native:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "the selection stopped being native while it was observed",
                "resume this graph run to re-evaluate the current facts",
            )
        import native_stack

        owner = native_stack.NativeRun(
            self.git,
            self.provider,
            self.plan,
            self.endpoint,
            0.0,
            self.store,
            self.journal,
            gates=self.gates,
        )
        owner.deadline = self.deadline
        return owner

    def _native_record(self) -> NativeRecord | None:
        """The native record a new journal starts with (the lock is held)."""
        return None

    def _landing_context(
        self, node: PlanNode, pr: PullRequest
    ) -> lifecycle.NativeLanding | None:
        """The native landing authority :func:`lifecycle.execute` gets for ``node``."""
        return None

    def _check(
        self,
        prs: Mapping[int, PullRequest],
        expected: Mapping[int, tuple[str, str]],
        pending: tuple[Finding, ...],
    ) -> None:
        """Stop on the first finding; changes outside the scope are only reported.

        A selected node that became a native stack member during this manual run
        is BLOCKED here, every step, before any capture, push or retarget.
        """
        native = [
            node.pr
            for node in self.plan.selected_nodes()
            if membership(prs[node.pr]) == "native"
        ]
        if native:
            raise _Stop(
                "BLOCKED",
                f"#{native[0]} became a native stack member during this manual graph "
                "run; it is never pushed, retargeted or merged on the manual path",
                "inspect the provider stack and start a new graph run from current "
                "facts; nothing is converted from one kind to the other",
            )
        self.changes = context_changes(self.plan, prs, expected)
        self.findings = (*pending, *contradictions(self.plan, prs, expected))
        if self.findings:
            first = self.findings[0]
            raise _Stop(first.status, first.reason, first.next_action)

    def _initialize(self) -> bool:
        """Create or adopt the journal; ``True`` when it records a completed run."""
        if self.journal is None:
            journal = new_journal(
                self.plan,
                run_id=uuid.uuid4().hex,
                endpoint=self.endpoint,
                code_identity=self.code,
                created_at=_now(),
            )
            journal.assurance = self._assurance()
            journal.gates = None if self.gates is None else self.gates.canonical()
            for row in journal.nodes:
                if not row.selected:
                    row.state = "RETAINED"
            with self.store.mutation_lock():
                journal.native = self._native_record()
                # Adopted only while the lock is held and kept only once saved: a
                # busy lock or a failed first save names no run id, as none exists.
                self.journal = journal
                try:
                    self._save()
                except BaseException:
                    self.journal = None
                    raise
            return False
        journal = self.journal
        if journal.endpoint != self.endpoint:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "a resumed graph run keeps its saved endpoint",
                f"resume with --until {journal.endpoint} or start a new graph run",
            )
        refreshed = self.plan.identity != journal.plan_identity
        if journal.code_identity != self.code and not refreshed:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "saved graph actions belong to different controller sources",
                "review the new sources and resume with a refreshed --stack-plan",
            )
        if journal.status == "COMPLETE":
            if refreshed or (
                self.gates is not None and self.gates.canonical() != journal.gates
            ):
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "a completed graph cannot adopt new policy or unexercised gates",
                    "resume with its saved inputs to reverify, or start a new run",
                )
            return True
        changed = self._admit_assurance(journal)
        changed = self._admit_gates(journal) or changed
        if not refreshed:
            if changed:
                with self.store.mutation_lock():
                    self._save()
            return journal.status == "COMPLETE"
        self._refresh(journal)
        with self.store.mutation_lock():
            self._save()
        return False

    def _assurance(self) -> str:
        """The highest assurance any selected node's decision asks for."""
        high = any(
            node.decision is not None and node.decision.assurance == "high"
            for node in self.plan.selected_nodes()
        )
        return "high" if high else "routine"

    def _admit_assurance(self, journal: GraphJournal) -> bool:
        """Never narrow any saved node decision; a historical run must be decided.

        A journal that predates assurance levels was validated under checkout
        attestation: it resumes only when every selected decision explicitly asks
        for ``high``. Otherwise each selected node keeps at least the level its
        saved decision had, node by node: one node staying ``high`` never excuses
        another's downgrade. A routine run is only ever raised. ``True`` when the
        journal's recorded level changed.
        """
        selected = self.plan.selected_nodes()
        if journal.assurance is None:
            routine = [
                node.pr
                for node in selected
                if node.decision is None or node.decision.assurance != "high"
            ]
            if routine:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "this graph run predates assurance levels and was validated "
                    "under checkout attestation; the decisions of "
                    + ", ".join(f"#{number}" for number in routine)
                    + ' do not explicitly set assurance to "high"',
                    "resume with a stack plan whose every selected decision sets "
                    'assurance to "high", or start a new graph run',
                )
        else:
            saved_high = {
                node.pr
                for node in journal_plan(journal).selected_nodes()
                if node.decision is not None and node.decision.assurance == "high"
            }
            narrowed = [
                node.pr
                for node in selected
                if node.pr in saved_high
                and (node.decision is None or node.decision.assurance != "high")
            ]
            if narrowed:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "this graph run saved high assurance for "
                    + ", ".join(f"#{number}" for number in narrowed)
                    + "; a decision must not narrow it",
                    "resume with a stack plan whose decisions keep assurance "
                    '"high", or start a new graph run',
                )
        wanted = self._assurance()
        if journal.assurance == wanted:
            return False
        journal.assurance = wanted
        return True

    def _admit_gates(self, journal: GraphJournal) -> bool:
        """Reuse the saved local validation decision; refuse a different one.

        No ``--gates`` on a resume keeps the saved decision, so validation never
        silently disappears. A run saved without gates adopts a supplied decision
        (strictly more validation). A supplied decision whose identity differs from
        the saved one is refused: the run already promised the saved one. ``True``
        when the journal changed.
        """
        try:
            saved = None if journal.gates is None else parse_gates(journal.gates)
        except PlanError as error:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"the saved gate decision is unusable: {_detail(error)}",
                "start a new graph run with an explicit --gates decision",
            ) from error
        if self.gates is None:
            self.gates = saved
            return False
        if saved is None:
            journal.gates = self.gates.canonical()
            return True
        if saved.identity != self.gates.identity:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "the supplied gate decision differs from the one this graph run saved",
                "resume without --gates to keep the saved decision, or start a new "
                "graph run with the new one; nothing was pushed",
            )
        return False

    def _refresh(self, journal: GraphJournal) -> None:
        """Adopt a refreshed packet of the same topology: decisions and head revisions.

        A node head the packet changes is rebound only while the node has neither a
        captured fork nor a pending mutation; the controller's confirmed head and
        the captured old head are not changes.
        """
        for row, node in zip(journal.nodes, self.plan.nodes, strict=True):
            row.decision_identity = (
                None if node.decision is None else decision_identity(node.decision)
            )
            if node.head_sha in (row.head_sha, row.old_head):
                continue
            pending = any(
                intent.pr == row.pr and intent.outcome == "PENDING"
                for intent in journal.intents
            )
            if row.fork is not None or pending:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"#{row.pr} has a captured fork or a pending mutation; the "
                    f"refreshed head {node.head_sha} cannot rebind it",
                    "start a new graph run with the refreshed packet",
                )
            row.head_sha = node.head_sha
        journal.plan = self.plan.canonical()
        journal.plan_identity = self.plan.identity
        journal.code_identity = self.code
        journal.status = "WAITING"

    def _noop(self) -> tuple[dict[str, object], int]:
        """Re-verify a completed graph through every node's lifecycle no-op."""
        for node in self.plan.selected_nodes():
            pr = self.prs[node.pr]
            row = self.record.node(node.pr)
            run_id = row.run_id
            if pr.state != "MERGED" or pr.head_sha != row.head_sha or run_id is None:
                raise _Stop(
                    "BLOCKED",
                    f"the saved graph completion no longer matches #{node.pr}",
                    "reconcile the actual graph; a journal is not authoritative",
                )
            outcome = self._execute(node, pr, self._receipt(run_id), run_id)
            if outcome != "COMPLETE":
                raise _Stop(
                    "BLOCKED",
                    f"#{node.pr} no longer has a completed cleanup",
                    "inspect the retained refs; completion is not deletion authority",
                )
        return self._finish("COMPLETE", None, "none", save=False)

    def _loop(self) -> None:
        for _ in range(MAX_GRAPH_STEPS):
            # A node's landing ends its own monitoring window (lifecycle clears the
            # provider deadline after a merge); the graph window bounds every step.
            self.provider.deadline = self.deadline
            prs = self._observe()
            if self._reconcile():
                continue
            lagging = self._lagging(prs)
            if lagging is not None:
                self._sleep(f"the provider still reports the old head of #{lagging}")
                continue
            self._check(prs, _expected(self.plan, self.journal), ())
            for row in self.record.nodes:
                if row.pr in self.scope:
                    row.base_ref = prs[row.pr].base_ref
            if not self._step(prs):
                return
        raise _Stop(
            "WAITING", "the graph step bound was reached", "resume this graph run"
        )

    def _step(self, prs: dict[int, PullRequest]) -> bool:
        """Perform the next parent-first action; ``False`` once nothing remains."""
        for node in self.plan.selected_nodes():
            if node.pr in self.finished:
                continue
            pr = prs[node.pr]
            if pr.state == "OPEN":
                waiting = [
                    ancestor
                    for ancestor in self.plan.ancestors(node.pr)
                    if prs[ancestor].state != "MERGED"
                ]
                if waiting:
                    raise StateError(
                        f"#{node.pr} is next while its ancestor #{waiting[0]} is open"
                    )
                if self._prepare(node, pr, prs):
                    return True
            self._land(node, pr)
            return True
        return self._settle()

    def _prepare(
        self, node: PlanNode, pr: PullRequest, prs: dict[int, PullRequest]
    ) -> bool:
        """Capture, promote or retarget before ``node`` lands; ``False`` once ready."""
        children = [
            child
            for child in self.plan.children(node.pr)
            if child.selected
            and prs[child.pr].state == "OPEN"
            and self.record.node(child.pr).fork is None
        ]
        if children:
            self._capture(pr, children)
            return True
        if node.parent is None:
            return False
        parent = prs[node.parent]
        if parent.merge_commit_sha is None:
            raise _Stop(
                "BLOCKED",
                f"parent #{parent.number} is MERGED without an authoritative landing",
                "resolve the provider landing identity; nothing was rewritten",
            )
        if not self._contains(pr, parent.merge_commit_sha):
            self._promote(node, pr, parent)
            return True
        if pr.base_ref != self.plan.trunk:
            self._retarget(node, pr)
            return True
        self._advance_local(node)
        return False

    def _settle(self) -> bool:
        """Resume each deferred cleanup once; ``False`` when the graph is complete."""
        for node in self.plan.selected_nodes():
            if self.finished.get(node.pr) == "DEFERRED" and node.pr not in self.settled:
                self.settled.add(node.pr)
                self._land(node, self.prs[node.pr])
                return True
        retained = [pr for pr, state in self.finished.items() if state == "DEFERRED"]
        if retained:
            names = ", ".join(f"#{number}" for number in retained)
            raise _Stop(
                "BLOCKED",
                f"landed {names} keep branches that open PRs still use",
                "land or retarget the dependent PRs, then resume this graph run "
                "for cleanup only",
            )
        return False

    # -- reconciliation --------------------------------------------------------------

    def _reconcile(self) -> bool:
        """Reconcile every PENDING intent from current facts; ``True`` if any was."""
        pending = [item for item in self.record.intents if item.outcome == "PENDING"]
        if not pending:
            return False
        with self.store.mutation_lock():
            for intent in pending:
                self._reconcile_one(intent)
            self._save()
        return True

    def _reconcile_one(self, intent: GraphIntent) -> None:
        """Record what current facts say about ``intent`` (the lock is held)."""
        row = self.record.node(intent.pr)
        current = self.provider.read_pr(intent.pr)
        outcome, observed = _classify(
            self.git, self.provider.host, self.plan, intent, current, row.head_sha
        )
        intent.outcome, intent.actual = outcome, observed
        if outcome == "REJECTED":
            intent.detail = _RECONCILED[intent.kind]
            if intent.kind == "advance-local" and observed != intent.expected_old:
                self._retain_local(intent.pr, intent.resource, observed, "it moved")
        elif intent.kind == "rewrite-push":
            row.head_sha = intent.new
        elif intent.kind == "retarget":
            row.base_ref = intent.new

    def _lagging(self, prs: Mapping[int, PullRequest]) -> int | None:
        """A node whose confirmed rewrite push the provider does not report yet."""
        for intent in self.record.intents:
            if intent.kind != "rewrite-push" or intent.outcome != "CONFIRMED":
                continue
            pr = prs[intent.pr]
            row = self.record.node(intent.pr)
            if (pr.state, pr.head_sha, row.head_sha) == (
                "OPEN",
                intent.expected_old,
                intent.new,
            ):
                return intent.pr
        return None

    # -- graph mutations -------------------------------------------------------------

    def _capture(self, pr: PullRequest, children: list[PlanNode]) -> None:
        """Record each open selected child's fork before ``pr`` changes or lands.

        The fork is the child's explicit packet fork, else ``pr``'s current head,
        and must be an available strict ancestor of the child's head; otherwise
        ``pr`` is neither rewritten nor merged.
        """
        with self.store.mutation_lock():
            self._unchanged(pr)
            self._require_room(len(children))
            captures: list[tuple[GraphNode, str, str]] = []
            for child in children:
                current = self._unchanged(self.prs[child.pr])
                fork = child.fork if child.fork is not None else pr.head_sha
                self._require_fork(child, current, fork, pr)
                captures.append((self.record.node(child.pr), current.head_sha, fork))
            for row, old_head, fork in captures:
                self._record_capture(row, old_head, fork)
            self._save()

    def _require_fork(
        self, node: PlanNode, pr: PullRequest, fork: str, parent: PullRequest
    ) -> None:
        """``fork`` must be an available strict ancestor of ``pr``'s head (locked)."""
        if self.git.resolve_ref(pr.head_sha) is None:
            self._fetch_head(pr)
        if (
            self.git.resolve_ref(fork) is None
            and parent.state == "OPEN"
            and fork == parent.head_sha
        ):
            self._fetch_head(parent)
        if self.git.resolve_ref(fork) is None:
            problem = f"{fork} is not an available commit"
        elif fork == pr.head_sha or not self.git.is_ancestor(fork, pr.head_sha):
            problem = f"{fork} is not a strict ancestor of its head {pr.head_sha}"
        else:
            return
        raise _Stop(
            "NEEDS_JUDGMENT",
            f"#{node.pr} has an unprovable fork boundary: {problem}",
            f"sync #{node.pr} onto #{parent.number} or give its explicit fork; "
            "nothing was rewritten or merged",
        )

    def _record_capture(self, row: GraphNode, old_head: str, fork: str) -> None:
        now = _now()
        row.fork, row.old_head, row.captured_at = fork, old_head, now
        self.record.intents.append(
            GraphIntent(
                key=str(len(self.record.intents) + 1),
                kind="capture",
                pr=row.pr,
                resource=f"pull/{row.pr}",
                expected_old=old_head,
                new=fork,
                created_at=now,
                outcome="CONFIRMED",
                actual=fork,
            )
        )

    def _contains(self, pr: PullRequest, landing: str) -> bool:
        """Whether ``pr``'s head already holds ``landing``, fetching objects first."""
        missing = self.git.resolve_ref(landing) is None
        if missing or self.git.resolve_ref(pr.head_sha) is None:
            with self.store.mutation_lock():
                self._unchanged(pr)
                if self.git.resolve_ref(landing) is None:
                    self._trunk()
                if self.git.resolve_ref(pr.head_sha) is None:
                    self._fetch_head(pr)
        if self.git.resolve_ref(landing) is None:
            raise _Stop(
                "BLOCKED",
                f"the parent landing {landing} of #{pr.number} is not on the trunk",
                "resolve the trunk history; nothing was rewritten",
            )
        return self.git.is_ancestor(landing, pr.head_sha)

    def _promote(self, node: PlanNode, pr: PullRequest, parent: PullRequest) -> None:
        """Prove ``node``'s own slice on the current trunk tip, then publish it once.

        The proposal is frozen in the journal before any validation or push. A
        later attempt against the same fork, old head and trunk tip (after a
        definite refusal or a failed gate) reuses those exact commit objects once
        they re-verify, so a retry never mints a new commit id from a new committer
        timestamp. Requested local gates run between the freeze and the push, in
        this process: never inside a Git hook and never under a Git deadline.
        """
        row = self.record.node(node.pr)
        remote = self._remote(pr.head_repo, pr.number)
        landing = parent.merge_commit_sha
        if landing is None:
            raise StateError(f"parent #{parent.number} has no landing commit")
        with self.store.mutation_lock():
            self._require_clean(node.pr, "pushed")
            self._unchanged(pr)
            self._require_room(2 if row.fork is None else 1)
            if row.fork is None:
                fork = node.fork if node.fork is not None else parent.head_sha
                self._require_fork(node, pr, fork, parent)
                self._record_capture(row, pr.head_sha, fork)
                self._save()
            captured = row.fork
            if captured is None or row.old_head != pr.head_sha:
                raise StateError(f"#{node.pr} fork was not captured at {pr.head_sha}")
            tip = self._trunk()
            if self.git.resolve_ref(landing) is None or not self.git.is_ancestor(
                landing, tip
            ):
                raise _Stop(
                    "BLOCKED",
                    f"the landing {landing} of #{parent.number} is not reachable "
                    f"from the trunk tip {tip}",
                    "resolve the trunk history; nothing was rewritten",
                )
            if self.git.resolve_ref(pr.head_sha) is None:
                self._fetch_head(pr)
            proof = self._frozen(row, captured, pr.head_sha, tip)
            if proof is None:
                proof = self._prove(node, captured, pr.head_sha, tip)
            self._require_published(node, pr, remote)
            row.promotion = Promotion(
                fork=proof.fork,
                old_head=proof.old_head,
                landing=proof.landing,
                expected_tree=proof.expected_tree,
                new_head=proof.new_head,
                commits=proof.commits,
                slice_identity=proof.slice_identity,
                verified=True,
            )
            row.state = "PROMOTED"
            self._save()
        self.local_validation[node.pr] = self._validate(proof.landing, proof.new_head)
        with self.store.mutation_lock():
            self._require_clean(node.pr, "pushed")
            self._unchanged(pr)
            self._require_published(node, pr, remote)
            if self._trunk() != proof.landing:
                raise _Stop(
                    "WAITING",
                    f"the trunk changed while #{node.pr}'s replay was validated; "
                    "nothing was pushed",
                    "resume to rebuild and validate the proposal on the current trunk",
                )
            self._require_room(1)
            intent = self._intent(
                "rewrite-push",
                node.pr,
                f"refs/heads/{pr.head_ref}",
                (pr.head_sha, proof.new_head),
            )
            self._push(intent, remote)
        self._advance_local(node)

    def _require_published(self, node: PlanNode, pr: PullRequest, remote: str) -> None:
        """The remote still publishes exactly ``pr``'s head (the lock is held)."""
        published = self.git.remote_head(remote, pr.head_ref)
        if published != pr.head_sha:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"the published head of #{node.pr} is {published}, not "
                f"{pr.head_sha}; nothing was pushed",
                _REFRESH,
            )

    def _frozen(
        self, row: GraphNode, fork: str, head: str, tip: str
    ) -> SliceProof | None:
        """The journaled proposal when it still is this slice on this trunk tip.

        It is reused only when its fork, old head and landing are unchanged and its
        objects, provenance and tree re-verify; anything else is proved afresh.
        """
        saved = row.promotion
        if (
            saved is None
            or not saved.verified
            or self.git.signing_required()
            or (saved.fork, saved.old_head, saved.landing) != (fork, head, tip)
        ):
            return None
        proof = SliceProof(
            fork=saved.fork,
            old_head=saved.old_head,
            landing=saved.landing,
            expected_tree=saved.expected_tree,
            new_head=saved.new_head,
            commits=saved.commits,
            slice_identity=saved.slice_identity,
        )
        try:
            self.git.verify_promotion(proof)
        except GitRefused:
            return None
        return proof

    def _validate(self, base: str, head: str) -> list[dict[str, object]]:
        """Run the requested local gates on ``base..head``; ``[]`` when none were.

        Never inside a Git hook or under the mutation lock. A failing gate stops
        the run before any dispatch. The elapsed time extends the monitoring
        deadline, so validation never consumes the provider-evidence window.
        """
        if self.gates is None:
            return []
        started = time.monotonic()
        try:
            return check_outgoing(self.git, self.gates, base, head, run_gates=True)
        except ChangesetStop as stop:
            raise _Stop(stop.status, str(stop), stop.next_action) from stop
        finally:
            self.deadline += time.monotonic() - started
            self.provider.deadline = self.deadline

    def _prove(self, node: PlanNode, fork: str, head: str, tip: str) -> SliceProof:
        """Replay and re-verify the slice ``fork..head`` onto ``tip``; never resolve."""
        try:
            proof = self.git.promote_slice(fork, head, tip)
            self.git.verify_promotion(proof)
        except GitRefused as error:
            # Also a configured or present commit signature: a plumbing replay
            # cannot sign, and the caller's signing is never disabled.
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"#{node.pr} cannot be promoted onto {tip}: {_detail(error)}",
                "resolve the child slice by hand (sync, split, sign or give its "
                "explicit fork); nothing was rewritten",
            ) from error
        return proof

    def _push(self, intent: GraphIntent, remote: str) -> None:
        """Dispatch the journaled rewrite push once and record its actual outcome."""
        branch = intent.resource.removeprefix("refs/heads/")
        self.mutation_attempted = True
        try:
            self.git.push_rewrite(remote, branch, intent.new, intent.expected_old)
        except GitRefused as error:
            observed = self.git.remote_head(remote, branch)
            if observed != intent.new:
                self._resolve(intent, "REJECTED", observed, _detail(error))
                if observed == intent.expected_old:
                    raise _Stop(
                        "BLOCKED",
                        f"the rewritten head of #{intent.pr} was not published",
                        "resolve the hook, transport or protection failure and resume; "
                        "the frozen promotion is re-verified before any new push",
                    ) from error
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"the published head of #{intent.pr} moved to {observed}; "
                    "nothing was pushed",
                    _REFRESH,
                ) from error
        except GitError as error:
            if error.uncertain:
                raise _Stop(
                    "WAITING",
                    f"the rewrite push of #{intent.pr} has an unknown outcome",
                    "resume this graph run; the pending push is reconciled from the "
                    "remote and never resent blind",
                ) from error
            self._resolve(intent, "REJECTED", None, _detail(error))
            raise
        self.record.node(intent.pr).head_sha = intent.new
        self._resolve(intent, "CONFIRMED", intent.new)
        self.mutation_confirmed = True

    def _advance_local(self, node: PlanNode) -> None:
        """Move an untouched local copy of ``node``'s branch to its published head.

        Only a branch exactly at the promotion's old head and held by no worktree,
        rebase or bisect moves, by compare-and-swap; any other local state stays
        untouched and is reported with the remaining action.
        """
        row = self.record.node(node.pr)
        promotion = row.promotion
        if promotion is None or row.head_sha != promotion.new_head:
            return
        ref = f"refs/heads/{node.head_ref}"
        local = self.git.local_heads().get(ref)
        if local is None or local == promotion.new_head:
            return
        if local != promotion.old_head:
            self._retain_local(node.pr, ref, local, "it holds another revision")
            return
        if any(tree.branch == node.head_ref for tree in self.git.snapshot().worktrees):
            self._retain_local(node.pr, ref, local, "it is checked out")
            return
        with self.store.mutation_lock():
            self._require_room(1)
            intent = self._intent(
                "advance-local", node.pr, ref, (promotion.old_head, promotion.new_head)
            )
            self.mutation_attempted = True
            try:
                advanced = self.git.advance_local_branch(
                    node.head_ref, promotion.old_head, promotion.new_head
                )
            except GitError as error:
                if error.uncertain:
                    raise
                current = self.git.local_heads().get(ref)
                if current != promotion.new_head:
                    self._resolve(intent, "REJECTED", current, _detail(error))
                    raise
                # A definite failure that still left the branch at the new head:
                # the observed identity confirms the intent.
                advanced = True
            current = self.git.local_heads().get(ref)
            if advanced or current == promotion.new_head:
                self._resolve(intent, "CONFIRMED", promotion.new_head)
                self.mutation_confirmed = True
                return
            self._resolve(intent, "REJECTED", current, "the branch was held or moved")
        self._retain_local(node.pr, ref, current, "it could not be advanced")

    def _retain_local(
        self, number: int, ref: str, oid: str | None, reason: str
    ) -> None:
        promotion = self.record.node(number).promotion
        target = None if promotion is None else promotion.new_head
        self.local[(number, ref)] = {
            "pr": number,
            "ref": ref,
            "oid": oid,
            "reason": f"local {ref} is retained: {reason}",
            "next_action": f"preserve its work, then move it to {target} or keep it",
        }

    def _retarget(self, node: PlanNode, pr: PullRequest) -> None:
        """Move ``node``'s PR base onto the trunk once, under a durable intent.

        The provider documents no atomic head/base guard for a base edit: the
        locked re-observation and the provider's own reads before and after narrow
        the race without removing it. Gates are renewed for the new base afterwards.
        """
        row = self.record.node(node.pr)
        with self.store.mutation_lock():
            self._require_clean(node.pr, "retargeted")
            self._unchanged(pr)
            self._require_room(1)
            intent = self._intent(
                "retarget", node.pr, f"pull/{node.pr}", (pr.base_ref, self.plan.trunk)
            )
            self.mutation_attempted = True
            try:
                self.provider.retarget_pr(
                    node.pr, self.plan.trunk, pr.head_sha, pr.base_ref
                )
            except ProviderError as error:
                if error.uncertain:
                    raise _Stop(
                        "WAITING",
                        f"the retarget of #{node.pr} has an unknown outcome",
                        "resume this graph run; the pending retarget is reconciled "
                        "from provider facts and never resent blind",
                    ) from error
                self._resolve(intent, "REJECTED", None, _detail(error))
                raise
            row.base_ref = self.plan.trunk
            self._resolve(intent, "CONFIRMED", self.plan.trunk)
            self.mutation_confirmed = True

    # -- landing through the lifecycle owner -----------------------------------------

    def _land(self, node: PlanNode, pr: PullRequest) -> None:
        """Land or re-verify ``node`` through :func:`lifecycle.execute`.

        Its run id is journaled before the first dispatch, so a crash never orphans
        a receipt. A landed node whose cleanup still waits on open dependents is
        not re-run until they are gone.
        """
        row = self.record.node(node.pr)
        run_id = row.run_id
        if run_id is None:
            run_id = uuid.uuid4().hex
            with self.store.mutation_lock():
                row.run_id = run_id
                self._save()
        receipt = self._receipt(run_id)
        if pr.state == "MERGED" and receipt is not None:
            rows = _deferred_rows(receipt)
            if rows is not None:
                self.dependents[node.pr] = self._dependents(rows)
                if self.dependents[node.pr]:
                    self.finished[node.pr] = "DEFERRED"
                    return
        self.finished[node.pr] = self._execute(node, pr, receipt, run_id)
        if row.state != "LANDED":
            with self.store.mutation_lock():
                row.state = "LANDED"
                self._save()

    def _receipt(self, run_id: str) -> Receipt | None:
        kind = self.store.kind_of(run_id)
        if kind == "graph":
            raise StateError("a node run id names a graph journal")
        return self.store.load(run_id) if kind == "receipt" else None

    def _execute(
        self, node: PlanNode, pr: PullRequest, receipt: Receipt | None, run_id: str
    ) -> str:
        """``COMPLETE``, or ``DEFERRED`` when only open dependents block cleanup."""
        decision = node.decision
        if decision is None:
            raise StateError(f"selected #{node.pr} has no decision")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Stop(
                "WAITING",
                f"the monitoring window ended before #{node.pr} was reconciled",
                "resume this graph run",
            )
        self.stopped = node.pr
        self.provider.deadline = self.deadline
        result, code = lifecycle.execute(
            self.git,
            self.provider,
            node.pr,
            self.endpoint,
            _bind(decision, pr, receipt),
            remaining,
            self.store,
            receipt,
            run_id=run_id,
            native=self._landing_context(node, pr),
        )
        self.results[node.pr] = result
        checkout = result.get("usable_checkout")
        if isinstance(checkout, dict):
            self.checkout = checkout
        self.mutation_attempted |= result.get("mutation_attempted") is True
        self.mutation_confirmed |= result.get("mutation_performed") is True
        if code == 130:
            self.cancelled = True
            raise _Stop(
                "WAITING",
                f"#{node.pr} was cancelled; reconcile before resuming",
                "resume this graph run; no uncertain mutation is repeated",
            )
        status = result.get("status")
        rows: list[dict[str, object]] | None = None
        if status != "COMPLETE":
            saved = self._receipt(run_id)
            rows = None if saved is None else _deferred_rows(saved)
            if rows is None:
                if status not in ("WAITING", "NEEDS_JUDGMENT", "BLOCKED"):
                    raise StateError(f"#{node.pr} returned an unsupported status")
                raise _Stop(
                    status,
                    f"#{node.pr}: {result.get('blocker')}",
                    str(result.get("next_action")),
                )
        self.stopped = None
        observed = result.get("observed_revisions")
        if isinstance(observed, dict) and isinstance(observed.get("base"), str):
            self.trunk_tip = observed["base"]
        if rows is None:
            return "COMPLETE"
        self.dependents[node.pr] = self._dependents(rows)
        return "DEFERRED"

    def _dependents(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        """Open PRs that still use a retained ref of ``rows`` as head or base."""
        refs: set[tuple[str, str]] = set()
        for row in rows:
            namespace, ref = row.get("namespace"), row.get("ref")
            if isinstance(namespace, str) and isinstance(ref, str):
                refs.add((namespace.lower(), ref.removeprefix("refs/heads/")))
        found: list[dict[str, object]] = []
        for namespace in sorted({self.plan.repo.lower(), *(name for name, _ in refs)}):
            for pr in self.provider.list_prs("open", full_name=namespace):
                uses = {
                    (pr.head_repo.lower(), pr.head_ref),
                    (pr.base_repo.lower(), pr.base_ref),
                }
                found.extend(
                    {"pr": pr.number, "url": pr.url, "namespace": name, "ref": ref}
                    for name, ref in sorted(refs & uses)
                )
        return found

    # -- locked observation helpers --------------------------------------------------

    def _require_clean(self, number: int, action: str) -> None:
        """The invoking checkout holds no work before a graph push or retarget.

        The statuses are :func:`lifecycle.inspection`'s: local changes need
        judgment, a conflict or an in-progress Git operation blocks. The lifecycle
        owner applies the same rule before every merge, so a dirty checkout stops
        every provider and remote mutation of an authorized run. The lock is held.
        """
        snapshot = self.git.snapshot()
        untouched = f"#{number} was not {action}"
        if snapshot.conflicts or snapshot.operations:
            raise _Stop(
                "BLOCKED",
                f"a Git operation or conflict must be resolved before #{number} is "
                f"{action}",
                f"resolve it without discarding work, then resume; {untouched}",
            )
        if snapshot.dirty:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"local changes need explicit changeset disposition before #{number} "
                f"is {action}",
                "preserve the changes and resolve their intended scope, then resume; "
                f"{untouched}",
            )

    def _unchanged(self, pr: PullRequest) -> PullRequest:
        """Re-read ``pr`` under the lock; any change stops before the mutation."""
        current = self.provider.read_pr(pr.number)
        if (current.state, current.head_sha, current.head_ref, current.base_ref) != (
            pr.state,
            pr.head_sha,
            pr.head_ref,
            pr.base_ref,
        ):
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"#{pr.number} changed before the graph mutation; nothing dispatched",
                "resume this graph run to re-evaluate the current facts",
            )
        self.prs[pr.number] = current
        return current

    def _remote(self, full_name: str, number: int | None = None) -> str:
        remote = self.git.remote_for(self.provider.host, full_name)
        if remote is None:
            owner = "the plan repository" if number is None else f"#{number} head"
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"{owner} {full_name} has no unambiguous associated Git remote",
                "associate that namespace with exactly one remote and resume",
            )
        return remote

    def _trunk(self) -> str:
        """Fetch the provider's current trunk tip; the caller holds the lock."""
        remote = self._remote(self.plan.repo)
        tip = self.provider.base_tip(self.plan.trunk)
        tracking = f"refs/remotes/{remote}/{self.plan.trunk}"
        if self.git.resolve_ref(tracking) != tip or self.git.resolve_ref(tip) is None:
            self.mutation_attempted = True
            try:
                self.git.fetch_base(remote, self.plan.trunk, tip)
            except GitRefused as error:
                raise _Stop(
                    "WAITING",
                    f"the trunk moved while it was fetched: {_detail(error)}",
                    "resume this graph run to use the current trunk tip",
                ) from error
            self.mutation_confirmed = True
        self.trunk_tip = tip
        return tip

    def _fetch_head(self, pr: PullRequest) -> None:
        """Fetch the objects of ``pr``'s exact head; the caller holds the lock."""
        remote = self._remote(pr.head_repo, pr.number)
        self.mutation_attempted = True
        try:
            self.git.fetch_commit(remote, pr.head_ref, pr.head_sha)
            self.mutation_confirmed = True
        except GitRefused as error:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"the published head of #{pr.number} is not {pr.head_sha}: "
                f"{_detail(error)}",
                _REFRESH,
            ) from error

    # -- journal ---------------------------------------------------------------------

    def _save(self) -> None:
        """Persist the journal; the caller holds the common-directory lock."""
        if lifecycle.code_identity() != self.code:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "controller source changed during execution",
                "review the current controller and refresh the --stack-plan packet",
            )
        self.record.updated_at = _now()
        self.store.save_graph(self.record)

    def _intent(
        self, kind: str, pr: int, resource: str, change: tuple[str, str]
    ) -> GraphIntent:
        """Journal a PENDING ``(expected_old, new)`` change before its dispatch."""
        intent = GraphIntent(
            key=str(len(self.record.intents) + 1),
            kind=kind,
            pr=pr,
            resource=resource,
            expected_old=change[0],
            new=change[1],
            created_at=_now(),
        )
        self.record.intents.append(intent)
        self._save()
        return intent

    def _require_room(self, needed: int) -> None:
        """Stop before a mutation whose ``needed`` intents the journal cannot hold.

        Checked under the lock before anything changes in memory, so the journal
        saved by the stop stays valid and nothing is dispatched.
        """
        if len(self.record.intents) + needed > GRAPH_MAX_INTENTS:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "journal intent limit reached; start a new graph run",
                "start a new graph run from current facts; nothing was dispatched",
            )

    def _resolve(
        self,
        intent: GraphIntent,
        outcome: str,
        actual: str | None,
        detail: str | None = None,
    ) -> None:
        """Journal what was actually observed for ``intent`` (the lock is held)."""
        intent.outcome = outcome
        intent.actual = actual
        intent.detail = detail
        self._save()

    def _sleep(self, reason: str) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Stop("WAITING", reason, "resume this graph run once it advances")
        with self.store.mutation_lock():
            self.record.status = "WAITING"
            self.record.issue = reason
            self.record.next_action = "resume monitoring this graph run"
            self._save()
        # No cooperative mutation lock is held while waiting.
        time.sleep(min(lifecycle.POLL_INTERVAL, remaining))

    def _finish(
        self, status: Status, reason: str | None, next_action: str, *, save: bool = True
    ) -> tuple[dict[str, object], int]:
        if lifecycle.code_identity() != self.code:
            status = "NEEDS_JUDGMENT"
            reason = "controller sources changed; pending graph actions are invalidated"
            next_action = "review current sources and resume with a refreshed packet"
        if save and self.journal is not None and self.initialized:
            self.journal.status = status
            self.journal.issue = reason
            self.journal.next_action = next_action
            try:
                with self.store.mutation_lock():
                    self.journal.updated_at = _now()
                    self.store.save_graph(self.journal)
            except (StateError, OSError, ReceiptInputError) as error:
                status = "WAITING" if isinstance(error, LockBusy) else "BLOCKED"
                reason = (
                    f"graph journal preservation failed: {lifecycle._safe_error(error)}"
                )
                next_action = (
                    "inspect current facts and the private graph journal before "
                    "resumption"
                )
        code = 130 if self.cancelled else lifecycle.EXIT_CODES[status]
        return self._result(status, reason, next_action), code

    # -- result ----------------------------------------------------------------------

    def _result(
        self, status: Status, reason: str | None, next_action: str
    ) -> dict[str, object]:
        journal = self.journal
        intents: list[GraphIntent] = [] if journal is None else journal.intents
        merges = self._merges()
        stopped = None if self.stopped is None else self.results.get(self.stopped)
        return {
            "schema_version": 1,
            "run_id": None if journal is None else journal.run_id,
            "status": status,
            "target": {
                "kind": "stack",
                "host": self.plan.host,
                "repository": self.plan.repo,
                "trunk": self.plan.trunk,
                "endpoint": self.endpoint,
                "selected": [node.pr for node in self.plan.selected_nodes()],
            },
            "nodes": self._node_rows(merges),
            "observed_revisions": {"trunk": self.trunk_tip},
            "confirmed_commits": [
                {
                    "pr": intent.pr,
                    "ref": intent.resource,
                    "old": intent.expected_old,
                    "new": intent.new,
                }
                for intent in intents
                if intent.kind == "rewrite-push" and intent.outcome == "CONFIRMED"
            ],
            "confirmed_prs": [pr.url for pr in self.prs.values()],
            "local_validation": [
                {"pr": number, "gates": rows}
                for number, rows in self.local_validation.items()
            ],
            "confirmed_merges": list(merges.values()),
            "verification": self._rows("verification"),
            "cleanup": {
                key: self._rows("cleanup", key)
                for key in ("removed", "retained", "failed")
            },
            "dependents": [
                {"landed": number, **row}
                for number, rows in self.dependents.items()
                for row in rows
            ],
            "retained_local": list(self.local.values()),
            "retained_changes": list(self.changes),
            "findings": [asdict(finding) for finding in self.findings],
            "pending_intents": [
                asdict(intent) for intent in intents if intent.outcome == "PENDING"
            ],
            "node_result": stopped,
            "usable_checkout": self.checkout,
            "blocker": reason,
            "next_action": next_action,
            "diagnostic": None if stopped is None else stopped.get("diagnostic"),
            "mutation_attempted": self.mutation_attempted,
            "mutation_performed": self.mutation_confirmed,
            "cancelled": self.cancelled,
        }

    def _merges(self) -> dict[int, dict[str, object]]:
        """Every provider-confirmed landing: observed, or confirmed by a node run."""
        merges: dict[int, dict[str, object]] = {
            number: {
                "pr": number,
                "url": pr.url,
                "landing": pr.merge_commit_sha,
                "reachable": None,
            }
            for number, pr in self.prs.items()
            if pr.state == "MERGED"
        }
        for number, result in self.results.items():
            confirmed = result.get("confirmed_merges")
            if isinstance(confirmed, list) and confirmed:
                first = confirmed[0]
                if isinstance(first, dict):
                    merges[number] = {"pr": number, **first}
        return merges

    def _rows(self, field: str, key: str | None = None) -> list[object]:
        """Node result rows of ``field`` (or ``field[key]``), each naming its PR."""
        rows: list[object] = []
        for number, result in self.results.items():
            value = result.get(field)
            if key is not None:
                value = value.get(key) if isinstance(value, dict) else None
            if isinstance(value, list):
                rows.extend(
                    {"pr": number, **row} for row in value if isinstance(row, dict)
                )
        return rows

    def _node_rows(
        self, merges: dict[int, dict[str, object]]
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for node in self.plan.order():
            pr = self.prs.get(node.pr)
            row = None if self.journal is None else self.journal.node(node.pr)
            result = self.results.get(node.pr, {})
            merge = merges.get(node.pr)
            rows.append(
                {
                    "pr": node.pr,
                    "role": "selected" if node.selected else "retained",
                    "parent": node.parent,
                    "state": "MERGED"
                    if merge is not None
                    else (None if pr is None else pr.state),
                    "run_id": None if row is None else row.run_id,
                    "head": None if pr is None else pr.head_sha,
                    "base": None if pr is None else pr.base_ref,
                    "status": self.finished.get(node.pr, result.get("status")),
                    "blocker": result.get("blocker"),
                    "landing": None if merge is None else merge.get("landing"),
                    "promotion": None
                    if row is None or row.promotion is None
                    else asdict(row.promotion),
                    "cleanup": result.get("cleanup"),
                }
            )
        return rows


# -- read-only inspection --------------------------------------------------------------


def inspect_graph(
    git: GitRepository,
    provider: GitHub,
    plan: StackPlan,
    endpoint: Endpoint,
    *,
    journal: GraphJournal | None = None,
) -> dict[str, object]:
    """The ordered actions :func:`execute_graph` would take next; writes nothing.

    Provider and remote reads only: no fetch, prune, lock, directory, journal, ref,
    index or object write in the repository. A promotion proof needs every object
    already local; it checks the structure read-only (landing reachable from the
    trunk tip, the fork a strict ancestor of the head, a linear replayable slice)
    and computes the cumulative clean three-way tree in an isolated temporary
    repository (:meth:`GitRepository.preview_three_way`); the per-commit replay is
    proven only at execution. Whatever cannot be proven this way is reported as not
    evaluated. ``journal`` supplies a resumed run's last confirmed identities,
    captured forks and pending intents, which are classified as execution would
    reconcile them, without recording anything. Contradictions and blockers are
    listed and the status stays ``PLANNED``. A native selection is previewed by
    the native stack owner (``native_stack.inspect_native``), equally write-free.
    """
    prs = {node.pr: provider.read_pr(node.pr) for node in plan.nodes}
    if selection(plan, prs) == "native":
        import native_stack

        return native_stack.inspect_native(git, provider, plan, endpoint, journal, prs)
    return _Preview(git, provider, plan, journal, prs).result(endpoint)


class _Preview:
    """The read-only action plan of :func:`inspect_graph`."""

    def __init__(
        self,
        git: GitRepository,
        provider: GitHub,
        plan: StackPlan,
        journal: GraphJournal | None,
        prs: dict[int, PullRequest],
    ) -> None:
        self.git = git
        self.provider = provider
        self.plan = plan
        self.journal = journal
        self.snapshot = git.snapshot()
        self.prs = prs
        self.tip = provider.base_tip(plan.trunk)
        expected, self.reconciled, pending = _projected(
            git, provider.host, plan, journal, self.prs
        )
        route = route_finding(plan, prs, journal)
        self.findings = [
            *([] if route is None else [route]),
            *pending,
            *contradictions(plan, self.prs, expected),
        ]
        self.changes = context_changes(plan, self.prs, expected)
        self.signing: bool | None = None

    def result(self, endpoint: Endpoint) -> dict[str, object]:
        if self.git.remote_for(self.provider.host, self.plan.repo) is None:
            self.findings.insert(
                0,
                Finding(
                    "NEEDS_JUDGMENT",
                    None,
                    f"{self.plan.repo} has no unambiguous associated Git remote",
                    "associate the plan repository with exactly one remote",
                ),
            )
        if self.snapshot.conflicts or self.snapshot.operations:
            self.findings.append(
                Finding(
                    "BLOCKED",
                    None,
                    "a Git operation or conflict must be resolved before execution",
                    "resolve it without discarding work",
                )
            )
        elif self.snapshot.dirty and endpoint != "pr" and self._open_selected():
            self.findings.append(
                Finding(
                    "NEEDS_JUDGMENT",
                    None,
                    "local changes need explicit changeset disposition",
                    "preserve the changes and resolve their intended scope before "
                    "execution",
                )
            )
        actions = [] if endpoint == "pr" else self.reconciled + self.actions(endpoint)
        if self.findings:
            next_action = self.findings[0].next_action
        else:
            next_action = "execute the planned graph actions" if actions else "none"
        return {
            "schema_version": 1,
            "run_id": None if self.journal is None else self.journal.run_id,
            "status": "PLANNED",
            "target": {
                "kind": "stack",
                "host": self.plan.host,
                "repository": self.plan.repo,
                "trunk": self.plan.trunk,
                "endpoint": endpoint,
                "selected": [node.pr for node in self.plan.selected_nodes()],
            },
            "observed_revisions": {"trunk": self.tip},
            "local_snapshot": self.snapshot.fingerprint,
            "nodes": [
                {
                    "pr": node.pr,
                    "role": "selected" if node.selected else "retained",
                    "parent": node.parent,
                    "state": self.prs[node.pr].state,
                    "membership": membership(self.prs[node.pr]),
                    "head": self.prs[node.pr].head_sha,
                    "base": self.prs[node.pr].base_ref,
                    "landing": self.prs[node.pr].merge_commit_sha,
                }
                for node in self.plan.order()
            ],
            "actions": actions,
            "blockers": [asdict(finding) for finding in self.findings],
            "retained_changes": list(self.changes),
            "confirmed_prs": [pr.url for pr in self.prs.values()],
            "confirmed_merges": [
                {"pr": pr.number, "url": pr.url, "landing": pr.merge_commit_sha}
                for pr in self.prs.values()
                if pr.state == "MERGED"
            ],
            "cleanup": {"removed": [], "retained": [], "failed": []},
            "next_action": next_action,
            "mutation_performed": False,
        }

    def actions(self, endpoint: Endpoint) -> list[dict[str, object]]:
        """Selected nodes parent-first, as if each landed in turn."""
        planned: list[dict[str, object]] = []
        for node in self.plan.selected_nodes():
            pr = self.prs[node.pr]
            if pr.state == "MERGED":
                planned.append(
                    {
                        "action": "verify-landing",
                        "pr": node.pr,
                        "landing": pr.merge_commit_sha,
                    }
                )
            elif pr.state == "OPEN":
                planned.extend(self._open(node, pr))
            else:
                continue
            if endpoint == "clean":
                planned.append({"action": "cleanup", "pr": node.pr})
        return planned

    def _open_selected(self) -> bool:
        """Whether execution would still push, retarget or merge a selected node."""
        return any(
            self.prs[node.pr].state == "OPEN" for node in self.plan.selected_nodes()
        )

    def _open(self, node: PlanNode, pr: PullRequest) -> list[dict[str, object]]:
        planned = [
            self._capture(child, pr)
            for child in self.plan.children(node.pr)
            if child.selected
            and self.prs[child.pr].state == "OPEN"
            and self._captured(child) is None
        ]
        ready = node.parent is None and pr.base_ref == self.plan.trunk
        if node.parent is not None:
            parent = self.prs[node.parent]
            if parent.state == "MERGED":
                promotion = self._promotion(node, pr, parent)
                if promotion is not None:
                    planned.append(promotion)
                ready = promotion is None and pr.base_ref == self.plan.trunk
            else:
                planned.append(
                    {
                        "action": "promote",
                        "pr": node.pr,
                        "after": node.parent,
                        "fork": self._captured(node) or node.fork or parent.head_sha,
                        "old_head": pr.head_sha,
                        "proof": {
                            "evaluated": False,
                            "reason": f"evaluated once #{node.parent} has landed",
                        },
                    }
                )
                self._signing(node.pr)
        if pr.base_ref != self.plan.trunk:
            planned.append(
                {
                    "action": "retarget",
                    "pr": node.pr,
                    "from": pr.base_ref,
                    "to": self.plan.trunk,
                }
            )
        decision = node.decision
        planned.append(
            {
                "action": "land",
                "pr": node.pr,
                "merge_method": None if decision is None else decision.merge_method,
                "gate": self._gate(node, pr) if ready else None,
            }
        )
        return planned

    def _captured(self, node: PlanNode) -> str | None:
        return None if self.journal is None else self.journal.node(node.pr).fork

    def _capture(self, child: PlanNode, parent: PullRequest) -> dict[str, object]:
        head = self.prs[child.pr].head_sha
        fork = child.fork if child.fork is not None else parent.head_sha
        if self.git.resolve_ref(fork) is None or self.git.resolve_ref(head) is None:
            proof = "not evaluated: an object is not local and a dry run never fetches"
        elif fork != head and self.git.is_ancestor(fork, head):
            proof = "strict ancestor"
        else:
            proof = "not a strict ancestor"
            self.findings.append(
                Finding(
                    "NEEDS_JUDGMENT",
                    child.pr,
                    f"#{child.pr} has an unprovable fork boundary: {fork} is not a "
                    f"strict ancestor of its head {head}",
                    f"sync #{child.pr} onto #{parent.number} or give its explicit "
                    "fork before the parent lands",
                )
            )
        return {
            "action": "capture",
            "pr": child.pr,
            "parent": parent.number,
            "fork": fork,
            "old_head": head,
            "proof": proof,
        }

    def _promotion(
        self, node: PlanNode, pr: PullRequest, parent: PullRequest
    ) -> dict[str, object] | None:
        """The promotion a node of a landed parent needs; ``None`` when it has none."""
        landing = parent.merge_commit_sha
        local = (
            landing is not None
            and self.git.resolve_ref(landing) is not None
            and self.git.resolve_ref(pr.head_sha) is not None
        )
        if landing is not None and local and self.git.is_ancestor(landing, pr.head_sha):
            return None
        fork = self._captured(node) or node.fork or parent.head_sha
        action: dict[str, object] = {
            "action": "promote",
            "pr": node.pr,
            "fork": fork,
            "old_head": pr.head_sha,
            "landing": landing,
            "onto": self.tip,
        }
        if landing is None:
            self.findings.append(
                Finding(
                    "BLOCKED",
                    parent.number,
                    f"#{parent.number} is MERGED without an authoritative landing",
                    "resolve the provider landing identity",
                )
            )
            action["proof"] = {"evaluated": False, "reason": "the landing is unknown"}
        elif not local:
            action["proof"] = {
                "evaluated": False,
                "reason": "the landing or head is not local; a dry run never fetches",
            }
        else:
            action["proof"] = self._proof(node, fork, pr.head_sha, landing)
        self._signing(node.pr)
        return action

    def _proof(
        self, node: PlanNode, fork: str, head: str, landing: str
    ) -> dict[str, object]:
        """The promotion proof as far as it holds without any repository write.

        Read-only structure in the repository: the landing reachable from the trunk
        tip and ``fork..head`` one linear chain of replayable commits after a strict
        ancestor fork (:meth:`GitRepository.slice_commits`). Then the cumulative
        clean three-way tree (base ``fork``, ours the trunk tip, theirs ``head``)
        in an isolated temporary repository. The per-commit replay is left to
        execution, which proves it before anything is published.
        """
        missing = [
            oid for oid in (fork, head, self.tip) if self.git.resolve_ref(oid) is None
        ]
        if missing:
            return {
                "evaluated": False,
                "reason": f"{missing[0]} is not local; a dry run never fetches",
            }
        if not self.git.is_ancestor(landing, self.tip):
            self.findings.append(
                Finding(
                    "BLOCKED",
                    node.pr,
                    f"the landing {landing} of #{node.parent} is not reachable from "
                    f"the trunk tip {self.tip}",
                    "resolve the trunk history; nothing is rewritten",
                )
            )
            return {
                "evaluated": True,
                "provable": False,
                "reason": "the landing is not reachable from the trunk tip",
            }
        try:
            commits = self.git.slice_commits(fork, head)
        except GitRefused as error:
            return self._unprovable(node, _detail(error))
        except GitError as error:
            return {"evaluated": False, "reason": _detail(error)}
        try:
            tree = self.git.preview_three_way(fork, self.tip, head)
        except GitError as error:
            return {
                "evaluated": False,
                "reason": f"the three-way tree is not proven: {_detail(error)}",
                "commits": len(commits),
            }
        if tree is None:
            return self._unprovable(
                node,
                f"replaying {fork}..{head} onto {self.tip} is a conflict; it is "
                "never resolved automatically",
            )
        return {
            "evaluated": True,
            "provable": True,
            "expected_tree": tree,
            "commits": len(commits),
            "limits": _REPLAY_LIMITS,
        }

    def _unprovable(self, node: PlanNode, reason: str) -> dict[str, object]:
        """Record a promotion execution would refuse, as the judgment it stops on."""
        self.findings.append(
            Finding(
                "NEEDS_JUDGMENT",
                node.pr,
                f"#{node.pr} cannot be promoted onto {self.tip}: {reason}",
                "resolve the child slice by hand; nothing is rewritten",
            )
        )
        return {"evaluated": True, "provable": False, "reason": reason}

    def _signing(self, number: int) -> None:
        """Report configured commit signing for a planned promotion (read once).

        A promotion replays the slice with plumbing and cannot sign it; execution
        refuses it before writing any object and never disables signing.
        """
        if self.signing is None:
            self.signing = self.git.signing_required()
        if self.signing:
            self.findings.append(
                Finding(
                    "NEEDS_JUDGMENT",
                    number,
                    f"#{number} cannot be promoted while commit.gpgsign is "
                    "configured: a plumbing replay cannot sign the rewritten slice",
                    f"rewrite and sign #{number} onto the trunk by hand, then refresh "
                    "the --stack-plan packet",
                )
            )

    def _gate(self, node: PlanNode, pr: PullRequest) -> dict[str, object] | None:
        decision = node.decision
        if decision is None:
            return None
        observed = self.provider.observe(node.pr, assurance=decision.assurance)
        return asdict(
            lifecycle.evaluate(observed, decision.bound(pr.head_sha, pr.base_sha))
        )
