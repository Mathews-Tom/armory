"""GitHub-native stack execution: one async merge request for a selected prefix.

:func:`graph.execute_graph` hands a selection of members of one native stack to
:class:`NativeRun`. It reuses the manual coordinator (journal, common-directory
lock, deadline, per-node lifecycle landing, cleanup deferral and result) and
replaces only the contradiction check, the journal record and the per-step action.

* Every step reads every plan node, the stack (``GitHub.read_native_stack``) and,
  while the request is still to be sent, the merge policy of the stack trunk
  (``GitHub.native_trunk_policy``). The request is for the highest selected
  member, and ``merge-async`` merges every open member below it: an open lower
  member that is not selected is BLOCKED before anything is sent. Every open
  member above the selection must be an unselected plan node; it is retained.
* Under the lock, after renewed gates and an unchanged clean checkout, the
  original facts of every scope and retained member are journaled (head, review
  base, full tree and own-slice identity; a retained member's fork is the selected
  head), the request is journaled DISPATCHING and ``start_native_merge`` is
  called exactly once: ``merge_queue`` sends no method (the queue rules select
  it) and ``direct_merge`` sends the selected node's decided method, which the
  trunk policy must allow. The provider's ``sha`` guard protects only the
  selected head; lower members are verified by the refresh before the request
  and by their landing proofs after it.
* An uncertain outcome is UNKNOWN and needs judgment; it is never sent again. A
  definite refusal is REJECTED; a request the client never sent (too little of
  the window left, no ``gh``) stays PLANNED. A 409 naming an existing request is
  adopted only when it echoes exactly the journaled options.
* Pull request states, not the request status, decide what landed: ``enqueued``
  is not a merge and queue groups may land members at different times. Each
  landed member is proved parent-first: its landing reachable from the trunk tip
  and after the landing of the member below, and its landed tree equal to the
  clean three-way tree of its own slice over the trunk before the landing
  (:meth:`GitRepository.landing_bases`). A
  ``failed`` request keeps every proved landing and stops BLOCKED with the
  provider's message; nothing is retried.
* Once the scope has landed, each retained member must sit, as the provider left
  it, on the trunk or on the member below it with its exact tree and own slice;
  Armory never rewrites it. That proof is made once: afterwards a retained
  member's changes are only reported. Then every selected node runs through
  :func:`lifecycle.execute` with its :class:`lifecycle.NativeLanding` context for
  post-merge acceptance and cleanup, which keeps the refs open PRs still use.

:func:`inspect_native` previews the same decisions without any write.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import cast

import lifecycle
from git_ops import GitRefused, GitRepository
from github_ops import (
    MIN_MUTATION_WINDOW,
    GitHub,
    NativeMergeInProgress,
    NativeMergeResult,
    NativeStack,
    NativeTrunkPolicy,
    ProviderError,
    PullRequest,
)
from graph import (
    _CONTROL,
    _DETAIL_LIMIT,
    _REFRESH,
    Finding,
    PlanNode,
    StackPlan,
    _detail,
    _expected,
    _GraphRun,
    _identity_problem,
    _now,
    _scope,
    _Stop,
    membership,
    route_finding,
)
from lifecycle import Endpoint, Status
from state_store import (
    GraphJournal,
    NativeMember,
    NativeRecord,
    NativeRequest,
    StateError,
    Store,
)

GUARD = (
    "the provider's sha guard protects only the selected head; every lower member "
    "is verified by this controller's refresh before the request and by its "
    "landing proof after it"
)
QUEUE_METHOD = (
    "the merge queue rules select the method; the packet's merge method was not sent"
)
RETAINED_PROTECTION = (
    "an open unselected member above the selected prefix: the provider rebases "
    "and retargets it, this controller only verifies its exact tree and own slice "
    "and never rewrites it, and its refs stay retained while it is open"
)
_NEVER_RESENT = "the async merge request is never sent again"
# Provider refusals raised before anything was sent: the request stays PLANNED.
_NOT_SENT = ("native-merge-not-dispatched", "missing-gh")


@dataclass(frozen=True)
class Route:
    """What the one request of a native selection merges, from current facts.

    ``scope`` is the open prefix the request merges, bottom to top, ending at
    ``selected`` (empty once the selected member has landed), and ``retained``
    the members above it.
    ``action``/``method`` are the request options, resolved from ``policy`` only
    while a request is still to be sent.
    """

    stack: NativeStack
    selected: int
    scope: tuple[int, ...]
    retained: tuple[int, ...]
    action: str | None
    method: str | None


def stack_identity(
    plan: StackPlan, prs: Mapping[int, PullRequest]
) -> tuple[int | None, list[Finding]]:
    """The one native stack of the selected members, or the findings against it.

    An unknown stack identity stays unknown: it is BLOCKED and never manual.
    """
    numbers: set[int] = set()
    findings: list[Finding] = []
    for node in plan.selected_nodes():
        pr = prs[node.pr]
        number = pr.native_stack_number
        if (
            number is None
            or pr.native_stack_position is None
            or pr.native_stack_size is None
            or pr.native_stack_base is None
        ):
            findings.append(
                Finding(
                    "BLOCKED",
                    node.pr,
                    f"the native stack identity of #{node.pr} is unknown; it is "
                    "never treated as a manual node",
                    "resume once the provider reports its stack number, position, "
                    "size and base",
                )
            )
            continue
        numbers.add(number)
    if not findings and len(numbers) > 1:
        names = ", ".join(str(number) for number in sorted(numbers))
        findings.append(
            Finding(
                "BLOCKED",
                None,
                f"the selection spans native stacks {names}; one async request "
                "merges a prefix of one stack",
                "select members of one native stack",
            )
        )
    if findings:
        return None, findings
    return numbers.pop(), findings


def request_options(
    node: PlanNode, policy: NativeTrunkPolicy
) -> tuple[str | None, str | None, Finding | None]:
    """The request action and method for the highest selected ``node``.

    An unknown policy is BLOCKED, never a licence to merge directly. A queue
    request sends no method; a direct request sends the node's decided method,
    which the trunk must allow. The server ``default`` action is never chosen.
    """
    if not policy.policy_known or policy.action is None:
        issues = "; ".join(policy.issues) or "no detail"
        return (
            None,
            None,
            Finding(
                "BLOCKED",
                node.pr,
                f"the merge policy of the stack trunk {policy.trunk!r} is unknown "
                f"({issues})",
                "resolve the provider policy evidence and resume; nothing is "
                "requested without a known merge action",
            ),
        )
    if policy.action == "merge_queue":
        return "merge_queue", None, None
    decision = node.decision
    if policy.action != "direct_merge" or decision is None:
        return (
            None,
            None,
            Finding(
                "BLOCKED",
                node.pr,
                f"the trunk policy resolves the merge action {policy.action!r}; "
                "only an explicit direct or queue action is requested",
                "resolve the provider policy evidence and resume",
            ),
        )
    if decision.merge_method not in policy.methods:
        allowed = ", ".join(policy.methods) or "none"
        return (
            "direct_merge",
            None,
            Finding(
                "BLOCKED",
                node.pr,
                f"the decided merge method {decision.merge_method!r} of #{node.pr} "
                f"is not allowed on the trunk {policy.trunk!r} (allowed: {allowed})",
                "refresh the --stack-plan packet with an allowed method; nothing "
                "was requested",
            ),
        )
    return "direct_merge", decision.merge_method, None


def _parent_name(number: int | None) -> str:
    return "the trunk" if number is None else f"#{number}"


def _member_problem(
    plan: StackPlan,
    node: PlanNode,
    pr: PullRequest,
    expected: tuple[str, str],
    lower_merged: bool,
    provider_moved: bool,
) -> str | None:
    """How a stack member contradicts its last confirmed identity, if it does.

    A landed member keeps its review base, so its base is never required to be
    the trunk; an open member may already sit on the trunk once every member
    below it landed. ``provider_moved`` marks a retained member after the request,
    whose head and base the provider changes and the retention proof decides.
    """
    head, base = expected
    label = f"#{node.pr}"
    if pr.base_repo.lower() != plan.repo.lower():
        return f"{label} targets {pr.base_repo}, not {plan.repo}"
    if (pr.head_repo.lower(), pr.head_ref) != (node.head_repo.lower(), node.head_ref):
        return (
            f"{label} head is {pr.head_repo}:{pr.head_ref}, not the planned "
            f"{node.head_repo}:{node.head_ref}"
        )
    if pr.state == "CLOSED":
        return f"{label} is closed without a confirmed merge"
    if provider_moved:
        return None
    if pr.head_sha != head:
        return f"{label} head moved outside the controller from {head} to {pr.head_sha}"
    if pr.base_ref != base and not (lower_merged and pr.base_ref == plan.trunk):
        return f"{label} base changed from {base!r} to {pr.base_ref!r}"
    return None


def retention_proved(journal: GraphJournal | None) -> bool:
    """Whether the native run of ``journal`` already proved its landings and retention.

    A selected node's lifecycle run id is journaled only after every scope landing
    and every retained member was proved (:meth:`NativeRun._step`). From then on a
    retained member belongs to the provider and its operator: a later change of it
    is reported as context, never verified again or a reason to stop.
    """
    return (
        journal is not None
        and journal.native is not None
        and any(row.selected and row.run_id is not None for row in journal.nodes)
    )


def _bound_members(
    stack: NativeStack, native: NativeRecord | None, proved: bool
) -> frozenset[int]:
    """The stack members this run still binds; proved retained ones are context."""
    released = set(native.retained) if proved and native is not None else set()
    return frozenset(pr.number for pr in stack.members if pr.number not in released)


def context(
    plan: StackPlan,
    prs: Mapping[int, PullRequest],
    expected: Mapping[int, tuple[str, str]],
    members: frozenset[int],
) -> tuple[dict[str, object], ...]:
    """Changes of plan nodes outside the stack that no selected landing needs.

    They are reported, never mutated and never a reason to stop.
    """
    scope = _scope(plan)
    changes: list[dict[str, object]] = []
    for node in plan.order():
        if node.pr in members or node.pr in scope:
            continue
        problem = _identity_problem(plan, node, prs, expected[node.pr])
        if problem is not None:
            changes.append({"pr": node.pr, "reason": problem})
    return tuple(changes)


def survey(
    provider: GitHub,
    plan: StackPlan,
    prs: Mapping[int, PullRequest],
    expected: Mapping[int, tuple[str, str]],
    stack: NativeStack,
    dispatched: bool,
    proved: bool,
) -> tuple[Route | None, list[Finding]]:
    """The route of the selection through ``stack`` and every finding against it.

    ``expected`` holds the last confirmed head and base of every node. Once the
    request is dispatched the retained members belong to the provider's rebase
    and the request options to the journal, so neither is read again here; once
    their retention is ``proved`` (:func:`retention_proved`) they are not
    checked at all.
    """
    if stack.base_ref != plan.trunk:
        return None, [
            Finding(
                "NEEDS_JUDGMENT",
                None,
                f"native stack {stack.number} is based on {stack.base_ref!r}, not "
                f"the trunk {plan.trunk!r}",
                _REFRESH,
            )
        ]
    members = stack.members
    index = {pr.number: position for position, pr in enumerate(members)}
    selected = [node.pr for node in plan.selected_nodes()]
    outside = [number for number in selected if number not in index]
    if outside:
        return None, [
            Finding(
                "NEEDS_JUDGMENT",
                outside[0],
                f"#{outside[0]} is not a member of native stack {stack.number}",
                _REFRESH,
            )
        ]
    top = max(selected, key=index.__getitem__)
    below, above = members[: index[top] + 1], members[index[top] + 1 :]
    planned = {node.pr for node in plan.nodes}
    findings: list[Finding] = []
    for node in plan.order():
        if node.pr not in index:
            if node.pr in _scope(plan):
                findings.append(
                    Finding(
                        "NEEDS_JUDGMENT",
                        node.pr,
                        f"#{node.pr} is not a member of native stack {stack.number}",
                        _REFRESH,
                    )
                )
            continue
        position = index[node.pr]
        lower = members[position - 1] if position else None
        parent = lower.number if lower is not None and lower.number in planned else None
        if node.parent != parent:
            findings.append(
                Finding(
                    "NEEDS_JUDGMENT",
                    node.pr,
                    f"#{node.pr} has the plan parent {_parent_name(node.parent)}, "
                    f"not the stack member below it ({_parent_name(parent)})",
                    _REFRESH,
                )
            )
            continue
        if proved and position > index[top]:
            continue
        problem = _member_problem(
            plan,
            node,
            prs[node.pr],
            expected[node.pr],
            all(member.state == "MERGED" for member in members[:position]),
            dispatched and position > index[top],
        )
        if problem is not None:
            findings.append(Finding("NEEDS_JUDGMENT", node.pr, problem, _REFRESH))
    broad = [
        pr.number for pr in below if pr.state == "OPEN" and pr.number not in selected
    ]
    if broad:
        findings.append(
            Finding(
                "BLOCKED",
                broad[0],
                f"the async request for #{top} would also merge the open unselected "
                f"#{broad[0]}: it merges every open member below the selected one",
                f"select #{broad[0]} or land it first; nothing is requested with an "
                "implicitly broader prefix",
            )
        )
    for pr in members:
        if pr.state == "CLOSED" and pr.number not in planned:
            findings.append(
                Finding(
                    "NEEDS_JUDGMENT",
                    pr.number,
                    f"stack member #{pr.number} is closed without a merge",
                    _REFRESH,
                )
            )
    if not dispatched:
        for pr in above:
            if pr.number not in planned:
                findings.append(
                    Finding(
                        "NEEDS_JUDGMENT",
                        pr.number,
                        f"open member #{pr.number} above the selected #{top} is not "
                        "a node of the plan, so its retention cannot be bound",
                        "add every member above the selection to the --stack-plan "
                        "packet as an unselected node",
                    )
                )
    scope = tuple(pr.number for pr in below if pr.state == "OPEN")
    action: str | None = None
    method: str | None = None
    if scope and not dispatched:
        action, method, problem_finding = request_options(
            plan.node(top), provider.native_trunk_policy(stack)
        )
        if problem_finding is not None:
            findings.append(problem_finding)
    route = Route(
        stack=stack,
        selected=top,
        scope=scope,
        retained=tuple(pr.number for pr in above),
        action=action,
        method=method,
    )
    return route, findings


def _record_findings(record: NativeRecord, route: Route, proved: bool) -> list[Finding]:
    """How current stack facts contradict the journaled request record.

    Once retention is ``proved``, the members above the selection are context.
    """
    if route.selected != record.selected:
        return [
            Finding(
                "NEEDS_JUDGMENT",
                route.selected,
                f"the highest selected member is #{route.selected}, but the journaled "
                f"request is for #{record.selected}",
                "start a new graph run from current facts",
            )
        ]
    if proved:
        return []
    if record.request.state == "PLANNED":
        if not route.scope:
            return [
                Finding(
                    "NEEDS_JUDGMENT",
                    record.selected,
                    f"#{record.selected} landed before this run sent its request",
                    "start a new graph run from current facts",
                )
            ]
        return []
    changed = route.retained != tuple(record.retained)
    if changed or not set(route.scope) <= set(record.scope):
        return [
            Finding(
                "NEEDS_JUDGMENT",
                record.selected,
                f"the membership of native stack {record.stack} changed after the "
                "request",
                "inspect the provider stack; " + _NEVER_RESENT,
            )
        ]
    return []


def _request_findings(
    record: NativeRecord, prs: Mapping[int, PullRequest]
) -> list[Finding]:
    """Stops an execution makes on the journaled request outcome, for the preview."""
    waiting = any(prs[number].state == "OPEN" for number in record.scope)
    landed = any(prs[number].state == "MERGED" for number in record.scope)
    if record.request.state == "REJECTED":
        if landed:
            number = next(
                number for number in record.scope if prs[number].state == "MERGED"
            )
            return [
                Finding(
                    "NEEDS_JUDGMENT",
                    number,
                    f"#{number} landed although the async merge request was refused",
                    "inspect the provider landings; " + _NEVER_RESENT,
                )
            ]
        return [
            Finding(
                "BLOCKED",
                record.selected,
                f"the async merge request of #{record.selected} was refused: "
                f"{record.request.detail}",
                "start a new graph run from current facts; the refused request "
                "merged nothing and " + _NEVER_RESENT,
            )
        ]
    if waiting and record.request.status == "failed":
        return [
            Finding(
                "BLOCKED",
                record.selected,
                f"GitHub reported the async merge request of #{record.selected} "
                f"failed: {record.request.message}",
                "inspect the provider's reason; proved landings are kept and nothing "
                "is retried",
            )
        ]
    if waiting and not landed and record.request.state in ("DISPATCHING", "UNKNOWN"):
        return [
            Finding(
                "NEEDS_JUDGMENT",
                record.selected,
                f"the async merge request of #{record.selected} has an unknown "
                "outcome and no member has landed",
                "inspect the provider for the request; " + _NEVER_RESENT,
            )
        ]
    return []


def _message(text: str) -> str:
    """A bounded single-line provider message; never a decision input."""
    cleaned = _CONTROL.sub(" ", text)[:_DETAIL_LIMIT].strip()
    return cleaned or "the provider gave no message"


class NativeRun(_GraphRun):
    """The native stack owner: one async request for the selected prefix.

    It overrides the contradiction check (:meth:`_check`), the refresh of a
    resumed packet (:meth:`_refresh`), the journal record (:meth:`_native_record`),
    the step before the per-node landing (:meth:`_step`), the open-node
    preparation (:meth:`_prepare`, which a native member never reaches), the
    native landing context and the result (:meth:`_result` adds the ``native``
    block). Landing, acceptance, cleanup, deferral and locking are the manual
    coordinator's.
    """

    native_owner = True

    def __init__(
        self,
        git: GitRepository,
        provider: GitHub,
        plan: StackPlan,
        endpoint: Endpoint,
        wait_timeout: float,
        store: Store,
        journal: GraphJournal | None,
    ) -> None:
        super().__init__(git, provider, plan, endpoint, wait_timeout, store, journal)
        self.route: Route | None = None
        self.landed = False
        self.gate_rows: dict[int, dict[str, object]] = {}
        self.retained_rows: dict[int, dict[str, object]] = {}
        self.request_read: str | None = None

    # -- observation -----------------------------------------------------------------

    def _check(
        self,
        prs: Mapping[int, PullRequest],
        expected: Mapping[int, tuple[str, str]],
        pending: tuple[Finding, ...],
    ) -> None:
        """Stop on the first native finding; outside context is only reported."""
        record = None if self.journal is None else self.journal.native
        dispatched = record is not None and record.request.state != "PLANNED"
        number, findings = stack_identity(self.plan, prs)
        findings[:0] = pending
        self.route = None
        self.changes = ()
        proved = retention_proved(self.journal)
        if number is not None and record is not None and record.stack != number:
            findings.append(
                Finding(
                    "NEEDS_JUDGMENT",
                    record.selected,
                    f"the journaled native stack {record.stack} is now stack {number}",
                    "start a new graph run from current facts",
                )
            )
        elif number is not None:
            stack = self.provider.read_native_stack(number)
            self.route, found = survey(
                self.provider, self.plan, prs, expected, stack, dispatched, proved
            )
            findings.extend(found)
            members = _bound_members(stack, record, proved)
            self.changes = context(self.plan, prs, expected, members)
            if self.route is not None and record is not None:
                findings.extend(_record_findings(record, self.route, proved))
        self.findings = tuple(findings)
        if findings:
            first = findings[0]
            raise _Stop(first.status, first.reason, first.next_action)

    def _current_route(self) -> Route:
        if self.route is None:
            raise StateError("the native stack was not observed in this step")
        return self.route

    def _native(self) -> NativeRecord:
        native = self.record.native
        if native is None:
            raise StateError("the graph run has no native request record")
        return native

    def _refresh(self, journal: GraphJournal) -> None:
        """A dispatched request binds every head it captured, except retained ones.

        The provider moves retained heads; their retention proof decides them.
        """
        native = journal.native
        if native is not None and native.request.state != "PLANNED":
            for row, node in zip(journal.nodes, self.plan.nodes, strict=True):
                if node.pr not in native.retained and node.head_sha != row.head_sha:
                    raise _Stop(
                        "NEEDS_JUDGMENT",
                        f"#{row.pr} is bound by the journaled native request; the "
                        f"refreshed head {node.head_sha} cannot rebind it",
                        "start a new graph run with the refreshed packet",
                    )
        super()._refresh(journal)

    def _landing_context(
        self, node: PlanNode, pr: PullRequest
    ) -> lifecycle.NativeLanding | None:
        number, position = pr.native_stack_number, pr.native_stack_position
        if not pr.native or number is None or position is None:
            raise _Stop(
                "BLOCKED",
                f"#{node.pr} has no complete native stack identity",
                "resume once the provider reports it; a native member never takes "
                "the ordinary path",
            )
        return lifecycle.NativeLanding(self.plan.trunk, number, position)

    # -- steps -----------------------------------------------------------------------

    def _step(self, prs: dict[int, PullRequest]) -> bool:
        """Request, await and prove the native landings, then land per node.

        A run whose landings and retention an earlier step already proved
        (:func:`retention_proved`) goes straight to the per-node landings.
        """
        native = self.record.native
        if native is not None and not self.landed and not retention_proved(self.record):
            if native.request.state == "PLANNED":
                self._dispatch()
            elif not self._await():
                # Observed again before any node runs through its lifecycle.
                self.landed = True
            return True
        return super()._step(prs)

    def _prepare(
        self, node: PlanNode, pr: PullRequest, prs: dict[int, PullRequest]
    ) -> bool:
        raise StateError(
            f"open native member #{node.pr} is never captured, rewritten or merged "
            "by the manual coordinator"
        )

    def _native_record(self) -> NativeRecord | None:
        """The record of a new native run, captured before its journal exists."""
        route = self._current_route()
        if not route.scope:
            return None
        return self._freeze(route)

    def _gates(self, scope: tuple[int, ...]) -> list[tuple[int, lifecycle.Gate]]:
        """Renewed gates of every open scope member at its observed identity."""
        rows: list[tuple[int, lifecycle.Gate]] = []
        for number in scope:
            decision = self.plan.node(number).decision
            if decision is None:
                raise StateError(f"selected #{number} has no decision")
            observed = self.provider.observe(number)
            known = self.prs[number]
            if (observed.pr.state, observed.pr.head_sha, observed.pr.base_ref) != (
                known.state,
                known.head_sha,
                known.base_ref,
            ):
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"#{number} changed while its gates were read; nothing was "
                    "requested",
                    "resume this graph run to re-evaluate the current facts",
                )
            gate = lifecycle.evaluate(
                observed,
                decision.bound(observed.pr.head_sha, observed.pr.base_sha),
                native_stack=True,
            )
            self.gate_rows[number] = {"pr": number, **asdict(gate)}
            rows.append((number, gate))
        return rows

    def _dispatch(self) -> None:
        """Send the one request once every gate is READY and the checkout clean."""
        route = self._current_route()
        if not route.scope:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"#{route.selected} landed before this run sent its request",
                "start a new graph run to verify and clean up the landed members",
            )
        for number, gate in self._gates(route.scope):
            if gate.status == "WAITING":
                self._sleep(f"#{number}: {gate.reason}")
                return
            if gate.status != "READY":
                raise _Stop(
                    cast("Status", gate.status),
                    f"#{number}: {gate.reason}",
                    "resolve the bounded gate and resume with a source-backed packet",
                )
        snapshot = self.git.snapshot()
        if snapshot.dirty or snapshot.conflicts or snapshot.operations:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "local changes or Git operations need disposition before the native "
                "merge request",
                "preserve the changes and resolve their intended scope, then resume; "
                "nothing was requested",
            )
        with self.store.mutation_lock():
            if self.git.snapshot().fingerprint != snapshot.fingerprint:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "external local snapshot changed",
                    "re-inventory current work before the native merge request; "
                    "nothing was requested",
                )
            for number, gate in self._gates(route.scope):
                if gate.status != "READY":
                    raise _Stop(
                        cast("Status", gate.status),
                        f"#{number}: {gate.reason}",
                        "resume from fresh current-context evidence; nothing was "
                        "requested",
                    )
            native = self._freeze(route)
            if self.deadline - time.monotonic() < MIN_MUTATION_WINDOW:
                raise _Stop(
                    "WAITING",
                    f"fewer than {MIN_MUTATION_WINDOW:g}s of the monitoring window "
                    "remain for the async merge request",
                    "resume this graph run; nothing was requested",
                )
            native.request.state = "DISPATCHING"
            native.request.dispatched_at = _now()
            self.record.native = native
            self._save()
            self.mutation_attempted = True
            self._send(native)

    def _freeze(self, route: Route) -> NativeRecord:
        """Freeze every scope and retained member's facts (the lock is held).

        Each head is fetched when missing. The lowest member's own slice starts at
        its single fork point with its current base; every other member's starts
        at the head of the member below it, which must be a strict ancestor.
        """
        if route.action is None:
            raise StateError("a native request has no resolved merge action")
        order = (*route.scope, *route.retained)
        stacked = {pr.number: pr for pr in route.stack.members}
        position = {
            pr.number: index + 1 for index, pr in enumerate(route.stack.members)
        }
        current = {number: self._unchanged(stacked[number]) for number in order}
        tip = self._trunk()
        for pr in current.values():
            if self.git.resolve_ref(pr.head_sha) is None:
                self._fetch_head(pr)
        below = self._slice_start(current[route.scope[0]])
        selected = current[route.selected]
        rows: list[NativeMember] = []
        for index, number in enumerate(order):
            pr = current[number]
            if index and (
                below == pr.head_sha or not self.git.is_ancestor(below, pr.head_sha)
            ):
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"#{number} does not sit on the head {below} of the stack member "
                    "below it",
                    f"sync #{number} onto the member below it first; nothing was "
                    "requested",
                )
            rows.append(
                NativeMember(
                    pr=number,
                    position=position[number],
                    head_ref=pr.head_ref,
                    head_sha=pr.head_sha,
                    base_ref=pr.base_ref,
                    base_sha=pr.base_sha,
                    tree=self.git.commit_tree(pr.head_sha),
                    slice_base=below,
                    slice_identity=self._slice(number, below, pr.head_sha),
                    fork=selected.head_sha if number in route.retained else None,
                )
            )
            below = pr.head_sha
        return NativeRecord(
            stack=route.stack.number,
            base_ref=self.plan.trunk,
            base_sha=tip,
            size=len(route.stack.members),
            selected=route.selected,
            scope=list(route.scope),
            retained=list(route.retained),
            members=rows,
            request=NativeRequest(
                action=route.action,
                method=route.method,
                expected_head=selected.head_sha,
            ),
        )

    def _slice_start(self, pr: PullRequest) -> str:
        """The single fork point of the lowest open member with its base (locked)."""
        if self.git.resolve_ref(pr.base_sha) is None:
            if pr.base_ref == self.plan.trunk:
                raise _Stop(
                    "WAITING",
                    f"the trunk moved from {pr.base_sha} while #{pr.number} was "
                    "observed",
                    "resume this graph run to use the current trunk",
                )
            remote = self._remote(self.plan.repo)
            self.mutation_attempted = True
            try:
                self.git.fetch_commit(remote, pr.base_ref, pr.base_sha)
            except GitRefused as error:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"the base of #{pr.number} is not {pr.base_sha}: {_detail(error)}",
                    _REFRESH,
                ) from error
            self.mutation_confirmed = True
        start = self.git.merge_base(pr.base_sha, pr.head_sha)
        if start is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"#{pr.number} has no single fork point with its base {pr.base_sha}",
                f"sync #{pr.number} onto its base first; nothing was requested",
            )
        return start

    def _slice(self, number: int, base: str, head: str) -> str:
        try:
            return self.git.slice_identity(base, head)
        except GitRefused as error:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"#{number} has no own change over {base}: {_detail(error)}",
                "resolve the empty member first; nothing was requested",
            ) from error

    def _send(self, native: NativeRecord) -> None:
        """Dispatch the journaled request once and journal its outcome (locked)."""
        request = native.request
        try:
            result = self.provider.start_native_merge(
                native.selected, request.expected_head, request.method, request.action
            )
        except ValueError as error:
            # The client refused the journaled options before sending anything.
            request.state, request.detail = "REJECTED", _detail(error)
            self._save()
            raise _Stop(
                "BLOCKED",
                f"the async merge request of #{native.selected} has invalid options: "
                f"{request.detail}",
                "start a new graph run from a corrected packet; nothing was requested "
                "and " + _NEVER_RESENT,
            ) from error
        except NativeMergeInProgress as error:
            existing = error.existing
            if existing.matches(request.action, request.method, request.expected_head):
                self._accept(native, existing, adopted=True)
                return
            request.state, request.detail = "REJECTED", _detail(error)
            self._save()
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"GitHub already has async merge request {existing.uuid} for "
                f"#{native.selected} with other options; nothing was requested",
                "inspect that provider request; it is never adopted or replaced, "
                "and " + _NEVER_RESENT,
            ) from error
        except ProviderError as error:
            if error.uncertain:
                request.state, request.detail = "UNKNOWN", _detail(error)
                self._save()
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"the async merge request of #{native.selected} has an unknown "
                    "outcome",
                    "inspect the provider for the request, then resume this graph "
                    "run: landings are reconciled from pull request facts and "
                    + _NEVER_RESENT,
                ) from error
            status: Status = "WAITING" if error.kind == "WAITING" else "BLOCKED"
            if error.detail in _NOT_SENT:
                request.state, request.dispatched_at = "PLANNED", None
                self._save()
                raise _Stop(
                    status,
                    f"the async merge request of #{native.selected} was not sent: "
                    f"{_detail(error)}",
                    "resolve the prerequisite and resume this graph run; nothing "
                    "was requested",
                ) from error
            request.state, request.detail = "REJECTED", _detail(error)
            self._save()
            raise _Stop(
                status,
                f"GitHub refused the async merge request of #{native.selected}: "
                f"{request.detail}",
                "resolve the refusal, then start a new graph run from current facts; "
                "nothing was merged and " + _NEVER_RESENT,
            ) from error
        self._accept(native, result, adopted=False)

    def _accept(
        self, native: NativeRecord, result: NativeMergeResult, *, adopted: bool
    ) -> None:
        """Journal a provider answer to the request (the lock is held).

        Only an identified request echoing exactly the journaled options, or the
        provider's immediate ``merged``/``enqueued`` answer, is ACCEPTED. A
        ``failed`` answer is a definite refusal; any other answer is UNKNOWN.
        ``adopted`` marks an existing request this process did not send.
        """
        request = native.request
        exact = result.uuid is not None and result.matches(
            request.action, request.method, request.expected_head
        )
        immediate = result.uuid is None and result.status in ("merged", "enqueued")
        if exact or immediate:
            request.state, request.uuid = "ACCEPTED", result.uuid
            request.status, request.message = result.status, _message(result.message)
            request.sha = result.sha
            if exact:
                request.echo_action = result.merge_action
                request.echo_method = result.merge_method
                request.echo_head = result.expected_head_sha
            self._save()
            self.mutation_confirmed |= not adopted
            return
        if result.status == "failed":
            request.state, request.status = "REJECTED", "failed"
            request.message = request.detail = _message(result.message)
            self._save()
            raise _Stop(
                "BLOCKED",
                f"GitHub reported the async merge request of #{native.selected} "
                f"failed: {request.message}",
                "inspect the provider's reason; nothing was merged and nothing is "
                "retried",
            )
        request.state = "UNKNOWN"
        request.detail = "the provider's answer does not echo the exact request options"
        self._save()
        raise _Stop(
            "NEEDS_JUDGMENT",
            f"the answer to the async merge request of #{native.selected} does not "
            "echo its exact options",
            "inspect the provider request; " + _NEVER_RESENT,
        )

    # -- completion ------------------------------------------------------------------

    def _await(self) -> bool:
        """Follow the request until every scope member landed and is proved.

        ``True`` while this step slept or recorded nothing final yet; ``False``
        once the scope landed and every retained member is verified. Pull request
        facts decide: a request status is never evidence that a member landed.
        """
        native = self._native()
        request = native.request
        if request.state == "DISPATCHING":
            with self.store.mutation_lock():
                request.state = "UNKNOWN"
                request.detail = "the dispatched request left no recorded outcome"
                self._save()
        if request.uuid is not None:
            self._read_request(native, request.uuid)
        current = {number: self.provider.read_pr(number) for number in native.scope}
        self.prs.update(current)
        if request.state == "REJECTED":
            landed = [number for number, pr in current.items() if pr.state == "MERGED"]
            if landed:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"#{landed[0]} landed although the async merge request was refused",
                    "inspect the provider landings; " + _NEVER_RESENT,
                )
            raise _Stop(
                "BLOCKED",
                f"the async merge request of #{native.selected} was refused: "
                f"{request.detail}",
                "start a new graph run from current facts; the refused request "
                "merged nothing and " + _NEVER_RESENT,
            )
        waiting: int | None = None
        below: str | None = None
        for number in native.scope:
            pr, member = current[number], native.member(number)
            if pr.state == "MERGED":
                if waiting is not None:
                    raise _Stop(
                        "NEEDS_JUDGMENT",
                        f"#{number} landed above the open #{waiting}",
                        "inspect the provider landings; " + _NEVER_RESENT,
                    )
                if not member.verified:
                    self._prove_landing(member, pr, below)
                below = member.landing
            elif pr.state == "CLOSED":
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"#{number} was closed without a merge after the request",
                    "inspect the provider; no replacement request is sent",
                )
            elif pr.head_sha != member.head_sha:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"the head of #{number} changed after the request from "
                    f"{member.head_sha} to {pr.head_sha}",
                    "reconcile the original request; no replacement request is sent",
                )
            elif waiting is None:
                waiting = number
        if waiting is None:
            return self._retain()
        if request.status == "failed":
            raise _Stop(
                "BLOCKED",
                f"GitHub reported the async merge request of #{native.selected} "
                f"failed: {request.message}",
                "inspect the provider's reason; proved landings are kept and nothing "
                "is retried",
            )
        if request.state == "UNKNOWN" and below is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"the async merge request of #{native.selected} has an unknown "
                "outcome and no member has landed",
                "inspect the provider for the request; " + _NEVER_RESENT,
            )
        self._sleep(
            f"#{waiting} has not landed; the request is "
            f"{request.status or 'of unknown outcome'}"
        )
        return True

    def _read_request(self, native: NativeRecord, uuid: str) -> None:
        """Journal the request's current status; an expired request is not news."""
        request = native.request
        try:
            result = self.provider.read_native_merge(native.selected, uuid)
        except ProviderError as error:
            if error.http_status != 404:
                raise
            self.request_read = (
                "the provider no longer reports the request (results expire); "
                "pull request facts decide"
            )
            return
        message = _message(result.message)
        if (result.status, message, result.sha) == (
            request.status,
            request.message,
            request.sha,
        ):
            return
        with self.store.mutation_lock():
            request.status, request.message, request.sha = (
                result.status,
                message,
                result.sha,
            )
            self._save()

    def _prove_landing(
        self, member: NativeMember, pr: PullRequest, below: str | None
    ) -> None:
        """Prove one landed member on the trunk and journal it (takes the lock).

        The landing must be reachable from the fetched trunk tip, follow the
        landing ``below`` of the member below it and carry exactly the clean
        three-way tree of the member's own slice (base its slice base, ours the
        trunk before the landing, theirs its frozen head). The trunk before the
        landing is its first parent, or for a rebase landing of N commits the
        parent of the N-th commit back (:meth:`GitRepository.landing_bases`).
        Unrelated trunk commits between landings are allowed when that tree still
        holds. The landing is journaled either way; only a proved one is
        ``verified``.
        """
        number, landing = member.pr, pr.merge_commit_sha
        if landing is None:
            raise _Stop(
                "BLOCKED",
                f"#{number} is MERGED without an authoritative landing",
                "resolve the provider landing identity; nothing is cleaned up",
            )
        if pr.head_sha != member.head_sha:
            raise _Stop(
                "BLOCKED",
                f"the provider merged #{number} at {pr.head_sha}, not the requested "
                f"head {member.head_sha}",
                "inspect the actual landing; every ref is preserved",
            )
        with self.store.mutation_lock():
            self._unchanged(pr)
            tip = self._trunk()
            if self.git.resolve_ref(landing) is None or not self.git.is_ancestor(
                landing, tip
            ):
                raise _Stop(
                    "BLOCKED",
                    f"the landing {landing} of #{number} is not reachable from the "
                    f"trunk tip {tip}",
                    "resolve the trunk history; nothing is cleaned up",
                )
            if below is not None and (
                landing == below or not self.git.is_ancestor(below, landing)
            ):
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"the landing {landing} of #{number} does not follow the landing "
                    f"{below} of the member below it",
                    "inspect the trunk history; nothing is cleaned up",
                )
            landed_tree = self.git.commit_tree(landing)
            bases = self.git.landing_bases(member.slice_base, member.head_sha, landing)
            member.landing = landing
            member.landed_tree = landed_tree
            member.verified = any(
                self.git.three_way_tree(member.slice_base, base, member.head_sha)
                == landed_tree
                for base in bases
            )
            self._save()
        if not member.verified:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"the landing {landing} of #{number} is not proved: the landed tree "
                f"{landed_tree} is not the clean three-way tree of its own slice over "
                "the trunk before its landing",
                "inspect the landing; nothing is cleaned up or rewritten",
            )

    def _retain(self) -> bool:
        """Verify every retained member as the provider left it; ``True`` on lag.

        The lowest retained member must be retargeted onto the trunk and either
        rebased onto it, or left untouched when its fork (the selected head) is
        already on the trunk, as after a merge landing. A higher one must sit on
        the current head of the member below it, untouched or rebased. Every
        rebase keeps its exact tree and own slice; an untouched head keeps both
        by definition. Armory never rewrites a retained member.
        """
        native = self._native()
        landing = native.member(native.selected).landing
        if landing is None:
            raise StateError("the selected native member has no proved landing")
        below: str | None = None
        for index, number in enumerate(native.retained):
            member = native.member(number)
            pr = self.provider.read_pr(number)
            self.prs[number] = pr
            if pr.state != "OPEN":
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"retained #{number} is {pr.state} after the request",
                    f"inspect #{number}; a retained member is never landed or "
                    "closed by this run",
                )
            moved = pr.base_ref == self.plan.trunk and index == 0
            if pr.base_ref != member.base_ref and not moved:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"retained #{number} changed its base to {pr.base_ref!r}",
                    f"inspect #{number}; it is left untouched and nothing is cleaned "
                    "up",
                )
            if pr.head_sha == member.head_sha:
                onto = "the trunk" if below is None else "the member below it"
                if not self._in_place(member, pr, below):
                    self._sleep(
                        f"the provider has not rebased retained #{number} onto "
                        f"{onto} yet"
                    )
                    return True
                self.retained_rows[number] = {
                    "pr": number,
                    "head": pr.head_sha,
                    "base": pr.base_ref,
                    "verification": f"untouched on {onto}",
                }
                below = pr.head_sha
                continue
            self._rebased(member, pr, landing if index == 0 else None, below)
            if index == 0 and pr.base_ref != self.plan.trunk:
                self._sleep(
                    f"the provider has not retargeted retained #{number} onto the "
                    "trunk yet"
                )
                return True
            below = pr.head_sha
        return False

    def _in_place(
        self, member: NativeMember, pr: PullRequest, below: str | None
    ) -> bool:
        """Whether an untouched retained head already sits where it must.

        The lowest one (``below`` None) must be on the trunk with its fork, the
        selected head it was frozen on, contained in the fetched trunk tip; a
        higher one must contain ``below``, the current head of the member below.
        """
        if below is not None:
            return self.git.is_ancestor(below, pr.head_sha)
        if pr.base_ref != self.plan.trunk:
            return False
        with self.store.mutation_lock():
            self._unchanged(pr)
            tip = self._trunk()
        return self.git.is_ancestor(member.slice_base, tip)

    def _rebased(
        self,
        member: NativeMember,
        pr: PullRequest,
        landing: str | None,
        below: str | None,
    ) -> None:
        """Prove a provider-rebased retained member and journal its head (locked).

        For the lowest one ``landing`` (the selected member's) must be in its new
        head, which sits on B, the single merge base of the trunk tip and that
        head; a higher one sits on ``below``, the head of the member below it. The
        new head's tree must equal the clean three-way tree (base the frozen fork
        or lower head, ours B, theirs the frozen old head) and its own slice over
        B must have the frozen identity: nothing missing, nothing extra.
        """
        number = member.pr
        with self.store.mutation_lock():
            current = self._unchanged(pr)
            head = current.head_sha
            if self.git.resolve_ref(head) is None:
                self._fetch_head(current)
            problem: str | None = None
            onto = below
            if landing is not None:
                onto = self.git.merge_base(self._trunk(), head)
                if not self.git.is_ancestor(landing, head):
                    problem = f"the trunk landing {landing} is not in its new head"
            if onto is None or onto == head or not self.git.is_ancestor(onto, head):
                problem = problem or "its new head sits on no single proved base"
            elif problem is None:
                expected = self.git.three_way_tree(
                    member.slice_base, onto, member.head_sha
                )
                actual = self.git.commit_tree(head)
                try:
                    identity: str | None = self.git.slice_identity(onto, head)
                except GitRefused:
                    identity = None
                if expected != actual:
                    problem = (
                        f"its tree {actual} is not the expected tree {expected} of "
                        "its own slice"
                    )
                elif identity != member.slice_identity:
                    problem = "its own slice over its new base changed"
            if problem is not None:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"retained #{number} was not rebased with its exact tree and own "
                    f"slice: {problem}",
                    f"inspect #{number}; it is left untouched and nothing is cleaned "
                    "up",
                )
            row = self.record.node(number)
            row.head_sha, row.base_ref = head, current.base_ref
            self._save()
        self.retained_rows[number] = {
            "pr": number,
            "head": head,
            "base": current.base_ref,
            "onto": onto,
            "verification": "rebased with its exact tree and own slice",
        }

    # -- result ----------------------------------------------------------------------

    def _result(
        self, status: Status, reason: str | None, next_action: str
    ) -> dict[str, object]:
        result = super()._result(status, reason, next_action)
        result["native"] = self._report()
        return result

    def _report(self) -> dict[str, object] | None:
        """The native block of the result: request, landings and retention."""
        native = None if self.journal is None else self.journal.native
        route = self.route
        if native is not None:
            stack, selected = native.stack, native.selected
            scope, retained = list(native.scope), list(native.retained)
            action: str | None = native.request.action
            method: str | None = native.request.method
            request: dict[str, object] | None = asdict(native.request)
            landings = [
                {
                    "pr": member.pr,
                    "position": member.position,
                    "head": member.head_sha,
                    "landing": member.landing,
                    "landed_tree": member.landed_tree,
                    "verified": member.verified,
                }
                for member in native.members
                if member.pr in native.scope
            ]
        elif route is not None:
            stack, selected = route.stack.number, route.selected
            scope, retained = list(route.scope), list(route.retained)
            action, method, request, landings = route.action, route.method, None, []
        else:
            return None
        return {
            **_options(self.plan, selected, action, method),
            "stack": stack,
            "trunk": self.plan.trunk,
            "selected": selected,
            "scope": scope,
            "retained": retained,
            "request": request,
            "request_read": self.request_read,
            "landings": landings,
            "retained_verification": list(self.retained_rows.values()),
            "gates": list(self.gate_rows.values()),
        }


def _options(
    plan: StackPlan, selected: int, action: str | None, method: str | None
) -> dict[str, object]:
    """The request options as reported: what is sent and what the server guards."""
    decision = plan.node(selected).decision
    return {
        "merge_action": action,
        "merge_method": method,
        "method_sent": method is not None,
        "packet_merge_method": None if decision is None else decision.merge_method,
        "method_note": QUEUE_METHOD if action == "merge_queue" else None,
        "guard": GUARD,
    }


# -- read-only inspection --------------------------------------------------------------


def inspect_native(
    git: GitRepository,
    provider: GitHub,
    plan: StackPlan,
    endpoint: Endpoint,
    journal: GraphJournal | None,
    prs: dict[int, PullRequest],
) -> dict[str, object]:
    """The native actions :func:`graph.execute_graph` would take next; writes nothing.

    Provider reads and read-only Git queries only: no fetch, lock, journal, ref,
    index or object write. It reports the prefix the one request would merge, the
    selected head it guards, the request action and method (none for a queue),
    every finding against the selection (an implicitly broader prefix, unknown
    policy, contradictions), each scope member's gate, every retained member and
    why it is protected, and a journaled request classified as execution would
    reconcile it, without recording anything.
    """
    snapshot = git.snapshot()
    tip = provider.base_tip(plan.trunk)
    native = None if journal is None else journal.native
    dispatched = native is not None and native.request.state != "PLANNED"
    proved = retention_proved(journal)
    expected = _expected(plan, journal)
    findings: list[Finding] = []
    route_problem = route_finding(plan, prs, journal)
    if route_problem is not None:
        findings.append(route_problem)
    if git.remote_for(provider.host, plan.repo) is None:
        findings.insert(
            0,
            Finding(
                "NEEDS_JUDGMENT",
                None,
                f"{plan.repo} has no unambiguous associated Git remote",
                "associate the plan repository with exactly one remote",
            ),
        )
    number, problems = stack_identity(plan, prs)
    findings.extend(problems)
    route: Route | None = None
    changes: tuple[dict[str, object], ...] = ()
    if number is not None and native is not None and native.stack != number:
        findings.append(
            Finding(
                "NEEDS_JUDGMENT",
                native.selected,
                f"the journaled native stack {native.stack} is now stack {number}",
                "start a new graph run from current facts",
            )
        )
    elif number is not None:
        stack = provider.read_native_stack(number)
        route, found = survey(provider, plan, prs, expected, stack, dispatched, proved)
        findings.extend(found)
        changes = context(plan, prs, expected, _bound_members(stack, native, proved))
    gates: list[dict[str, object]] = []
    retained: list[dict[str, object]] = []
    if route is not None:
        if native is not None:
            findings.extend(_record_findings(native, route, proved))
            findings.extend(_request_findings(native, prs))
        if not dispatched and route.scope:
            gates = _preview_gates(provider, plan, route)
            retained = _preview_retained(git, route, prs, findings)
    if snapshot.conflicts or snapshot.operations:
        findings.append(
            Finding(
                "BLOCKED",
                None,
                "a Git operation or conflict must be resolved before execution",
                "resolve it without discarding work",
            )
        )
    elif (
        snapshot.dirty
        and endpoint != "pr"
        and route is not None
        and route.scope
        and not dispatched
    ):
        findings.append(
            Finding(
                "NEEDS_JUDGMENT",
                None,
                "local changes need explicit changeset disposition",
                "preserve the changes and resolve their intended scope before "
                "execution",
            )
        )
    actions = (
        []
        if endpoint == "pr" or route is None
        else _preview_actions(plan, route, None if proved else native, prs, endpoint)
    )
    if findings:
        next_action = findings[0].next_action
    else:
        next_action = "execute the planned native actions" if actions else "none"
    return {
        "schema_version": 1,
        "run_id": None if journal is None else journal.run_id,
        "status": "PLANNED",
        "target": {
            "kind": "stack",
            "host": plan.host,
            "repository": plan.repo,
            "trunk": plan.trunk,
            "endpoint": endpoint,
            "selected": [node.pr for node in plan.selected_nodes()],
        },
        "observed_revisions": {"trunk": tip},
        "local_snapshot": snapshot.fingerprint,
        "nodes": [
            {
                "pr": node.pr,
                "role": "selected" if node.selected else "retained",
                "parent": node.parent,
                "state": prs[node.pr].state,
                "membership": membership(prs[node.pr]),
                "head": prs[node.pr].head_sha,
                "base": prs[node.pr].base_ref,
                "landing": prs[node.pr].merge_commit_sha,
            }
            for node in plan.order()
        ],
        "actions": actions,
        "blockers": [asdict(finding) for finding in findings],
        "retained_changes": list(changes),
        "confirmed_prs": [pr.url for pr in prs.values()],
        "confirmed_merges": [
            {"pr": pr.number, "url": pr.url, "landing": pr.merge_commit_sha}
            for pr in prs.values()
            if pr.state == "MERGED"
        ],
        "cleanup": {"removed": [], "retained": [], "failed": []},
        "next_action": next_action,
        "mutation_performed": False,
        "native": _preview_report(plan, route, native, gates, retained),
    }


def _preview_gates(
    provider: GitHub, plan: StackPlan, route: Route
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for number in route.scope:
        decision = plan.node(number).decision
        if decision is None:
            continue
        observed = provider.observe(number)
        gate = lifecycle.evaluate(
            observed,
            decision.bound(observed.pr.head_sha, observed.pr.base_sha),
            native_stack=True,
        )
        rows.append({"pr": number, **asdict(gate)})
    return rows


def _preview_retained(
    git: GitRepository,
    route: Route,
    prs: Mapping[int, PullRequest],
    findings: list[Finding],
) -> list[dict[str, object]]:
    """Check the available head chain and describe its retained members; read-only."""
    stacked = {pr.number: pr for pr in route.stack.members}
    fork = stacked[route.selected].head_sha
    rows: list[dict[str, object]] = []
    below: str | None = None
    for number in (*route.scope, *route.retained):
        pr = prs.get(number, stacked[number])
        if below is None:
            below = pr.head_sha
            continue
        if git.resolve_ref(below) is None or git.resolve_ref(pr.head_sha) is None:
            proof = "not evaluated: an object is not local and a dry run never fetches"
        elif below != pr.head_sha and git.is_ancestor(below, pr.head_sha):
            proof = "strict ancestor"
        else:
            proof = "not a strict ancestor"
            findings.append(
                Finding(
                    "NEEDS_JUDGMENT",
                    number,
                    f"#{number} does not sit on the head {below} of the stack member "
                    "below it",
                    f"sync #{number} onto the member below it first",
                )
            )
        if number in route.retained:
            rows.append(
                {
                    "pr": number,
                    "head": pr.head_sha,
                    "base": pr.base_ref,
                    "fork": fork,
                    "below": below,
                    "proof": proof,
                    "protection": RETAINED_PROTECTION,
                }
            )
        below = pr.head_sha
    return rows


def _preview_actions(
    plan: StackPlan,
    route: Route,
    native: NativeRecord | None,
    prs: Mapping[int, PullRequest],
    endpoint: Endpoint,
) -> list[dict[str, object]]:
    """The native request (or its reconciliation), then every per-node action.

    ``native`` is None once the landings and retention were proved: only the
    per-node actions remain.
    """
    actions: list[dict[str, object]] = []
    state = None if native is None else native.request.state
    if native is not None and state in ("DISPATCHING", "UNKNOWN"):
        landed = [number for number in native.scope if prs[number].state == "MERGED"]
        if len(landed) == len(native.scope):
            outcome = "landed"
        elif landed:
            outcome = "partially landed"
        else:
            outcome = "unknown: inspect the provider; " + _NEVER_RESENT
        actions.append(
            {
                "action": "reconcile-request",
                "pr": native.selected,
                "state": state,
                "landed": landed,
                "outcome": outcome,
            }
        )
    elif native is not None and state == "ACCEPTED":
        actions.append(
            {
                "action": "await-landings",
                "pr": native.selected,
                "uuid": native.request.uuid,
                "status": native.request.status,
            }
        )
    elif state != "REJECTED" and route.scope:
        actions.append(
            {
                "action": "native-merge",
                "pr": route.selected,
                "prefix": list(route.scope),
                "expected_head": prs[route.selected].head_sha,
                **_options(plan, route.selected, route.action, route.method),
            }
        )
    for node in plan.selected_nodes():
        actions.append(
            {
                "action": "verify-landing",
                "pr": node.pr,
                "landing": prs[node.pr].merge_commit_sha,
            }
        )
    if native is not None or route.scope:
        for number in route.retained:
            actions.append({"action": "verify-retained", "pr": number})
    if endpoint == "clean":
        for node in plan.selected_nodes():
            actions.append({"action": "cleanup", "pr": node.pr})
    return actions


def _preview_report(
    plan: StackPlan,
    route: Route | None,
    native: NativeRecord | None,
    gates: list[dict[str, object]],
    retained: list[dict[str, object]],
) -> dict[str, object] | None:
    if route is None:
        return None
    action = route.action if native is None else native.request.action
    method = route.method if native is None else native.request.method
    return {
        **_options(plan, route.selected, action, method),
        "stack": route.stack.number,
        "trunk": plan.trunk,
        "selected": route.selected,
        "scope": list(route.scope if native is None else native.scope),
        "retained": list(route.retained),
        "request": None if native is None else asdict(native.request),
        "gates": gates,
        "retained_preview": retained,
    }
