"""Publish local work as the intended PR, then hand it to the one lifecycle controller.

Entry routing resolves exactly one target: an explicit ``--pr``, an explicit
``--branch``, the branch a commit plan places work on, a resumed run, or the
current branch. Nothing is inferred from names, activity or PR numbers.

Publication pushes only the intended branch with an explicit expected-old (or
expected-absent) lease and a forward-history proof, after the outgoing range
passed the source-provenanced gates and secret scan. PRs are matched exactly on
host, base repository/ref and head repository/ref over complete paginated
evidence; one match is reused, several or unreadable evidence is never treated
as none. Every push and PR creation is journaled first and reconciled from
provider facts after an uncertain outcome; nothing is resent blindly. A
confirmed PR is bound to the receipt and continues through ``lifecycle.execute``,
so ``pr``, ``merged`` and ``clean`` keep their exact M1 meaning. A run's own PR is
immutable: once it is closed, or merged beyond the exact local head, new local work
stops for one explicit decision instead of publishing a replacement, and an exact
merged PR is continued without pushing its auto-deleted branch again. An explicit
head/base decision whose base is no longer the PR's (or the base branch's) current
tip is refused before anything is pushed or created and is never widened.

A commit plan is admitted only after everything knowable from provider facts and
the journal agrees with it: the selected PR is open, its head branch, head
namespace and base ref are the plan's, and the decision names this plan (or the
exact head a confirmed plan already produced). A contradiction stops before any
commit, index or ref update. A decision binds a PR only when that PR targets the
base ref the plan or packet was written for, so a retargeted PR is never rebound by
ancestry. Saved actions written by other controller sources resume only under an
explicit, changed source-backed decision, which replaces the old validation
authority; pending pushes and PR creations are then reconciled from provider facts
before anything new is committed, pushed, created or merged.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import lifecycle
from changeset import (
    ChangesetStop,
    GatePolicy,
    Plan,
    check_outgoing,
    execute_changeset,
    take_inventory,
    validate,
)
from git_ops import GitError, GitRefused, GitRepository
from github_ops import GitHub, ProviderError, PullRequest, validate_pr_title
from lifecycle import EXIT_CODES, Binding, Endpoint, Policy, Status
from state_store import (
    ChangesetRecord,
    CreateRecord,
    LockBusy,
    PublicationRecord,
    PushRecord,
    Receipt,
    ReceiptInputError,
    StateError,
    Store,
    Target,
)

PUSH_TIMEOUT = 1800.0
_RANKS = {"pr": 0, "merged": 1, "clean": 2}


@dataclass(frozen=True)
class Request:
    """One explicit invocation: selectors, endpoint and source-backed decisions."""

    host: str
    base_repo: str
    head_repo: str | None
    number: int | None
    branch: str | None
    endpoint: Endpoint
    plan: Plan | None
    gates: GatePolicy | None
    decision: Policy | Binding | None
    title: str | None
    body: bytes | None
    wait_timeout: float

    def __post_init__(self) -> None:
        if self.title is not None:
            validate_pr_title(self.title)


@dataclass
class _Located:
    branch: str
    head: str
    head_repo: str
    remote: str
    base_ref: str
    base_oid: str | None
    pr: PullRequest | None


@dataclass
class _Placement:
    """The PR and base a publication targets, resolved without any local head."""

    pr: PullRequest | None
    base_ref: str
    base_oid: str | None


class _Stop(RuntimeError):
    def __init__(self, status: Status, reason: str, next_action: str) -> None:
        super().__init__(reason)
        self.status: Status = status
        self.next_action = next_action


def _identity(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pending(receipt: Receipt | None) -> bool:
    """Whether a journaled commit, push or PR creation awaits reconciliation."""
    if receipt is None:
        return False
    changeset, publication = receipt.changeset, receipt.publication
    return (
        changeset is not None
        and changeset.update is not None
        and changeset.update.outcome == "PENDING"
    ) or (
        publication is not None
        and any(
            record is not None and record.outcome == "PENDING"
            for record in (publication.push, publication.create)
        )
    )


def local_work(
    git: GitRepository, provider: GitHub, number: int
) -> tuple[PullRequest, str | None]:
    """The selected PR, and its local branch when that branch holds unpublished work.

    Only a branch tracking the PR head namespace/ref, or the checked-out branch
    of that name, is the PR's local branch. ``None`` means the PR continues
    exactly as before: no local branch, or nothing beyond the published head. A
    closed or merged PR is judged the same way, so a direct lifecycle run never
    completes while newer commits or uncommitted work on its head branch exist.
    """
    pr = provider.read_pr(number)
    if not pr.head_repo:
        return pr, None
    branch = pr.head_ref
    tip = git.resolve_ref(f"refs/heads/{branch}")
    if tip is None:
        return pr, None
    remote = git.remote_for(provider.host, pr.head_repo)
    snapshot = git.snapshot()
    tracks = remote is not None and git.branch_upstream(branch) == (
        remote,
        f"refs/heads/{branch}",
    )
    if not tracks and snapshot.branch != branch:
        return pr, None
    dirty = any(
        GitRepository(tree.path).snapshot().dirty
        for tree in snapshot.worktrees
        if tree.branch == branch and not tree.prunable
    )
    if dirty:
        return pr, branch
    if tip == pr.head_sha:
        return pr, None
    if git.resolve_ref(pr.head_sha) == pr.head_sha and git.is_ancestor(
        tip, pr.head_sha
    ):
        return pr, None  # the local branch is only behind the published head
    return pr, branch


def _plan_applies(
    decision: Binding, head_sha: str, receipt: Receipt | None
) -> ChangesetRecord | None:
    """The receipt's changeset when it is exactly the plan ``decision`` binds here."""
    changeset = None if receipt is None else receipt.changeset
    update = None if changeset is None else changeset.update
    if (
        changeset is not None
        and changeset.plan_identity == decision.plan
        and update is not None
        and update.outcome == "CONFIRMED"
        and update.new == head_sha
    ):
        return changeset
    return None


def _applicable(
    decision: Policy | Binding | None,
    pr: PullRequest,
    receipt: Receipt | None,
    provider: GitHub,
) -> Policy | None:
    """The lifecycle decision bound once against the confirmed PR's head and base.

    Placement ancestry is not applicability: M1 evaluates the PR's actual base tip.
    A plan decision names only its placement base, so it resolves to the PR's
    current base after the provider proves that placement base is that base or one
    of its ancestors. An explicit head/base packet states the revisions it was
    written for and binds them literally: a stale one stays stale for M1 to refuse
    instead of being silently widened to a new revision. Both are written for one
    base ref: a PR retargeted to another base ref is never rebound, even when the
    named base commit happens to be reachable from that branch. ``None`` for a
    binding means it does not apply to this PR.
    """
    if not isinstance(decision, Binding):
        return decision
    if decision.plan is not None:
        changeset = _plan_applies(decision, pr.head_sha, receipt)
        if changeset is None or changeset.base_ref != pr.base_ref:
            return None
        if (
            pr.state == "OPEN"
            and changeset.base_oid != pr.base_sha
            and not provider.landing_reachable(changeset.base_oid, pr.base_sha)
        ):
            return None
        return decision.bind(pr.head_sha, pr.base_sha)
    if (
        decision.head == pr.head_sha
        and decision.base_oid is not None
        and decision.base_ref == pr.base_ref
    ):
        return decision.bind(pr.head_sha, decision.base_oid)
    return None


def _bound_identity(decision: Policy | Binding, receipt: Receipt) -> str:
    """The fingerprint lifecycle records once ``decision`` governs the run's PR.

    Lifecycle keeps the fingerprint of the bound policy, not of the packet, so a
    schema 2 packet is compared as it would bind: literally to its own head and
    base, or, for a plan, to the plan's head and the run's last observed base. A
    packet that cannot be bound yet retains its own admitted identity until
    lifecycle resolves the confirmed target.
    """
    if isinstance(decision, Policy):
        return decision.fingerprint
    if decision.plan is None:
        if decision.head is not None and decision.base_oid is not None:
            return decision.bind(decision.head, decision.base_oid).fingerprint
        return decision.fingerprint
    changeset = receipt.changeset
    update = None if changeset is None else changeset.update
    target = receipt.target
    if (
        changeset is None
        or update is None
        or changeset.plan_identity != decision.plan
        or target is None
    ):
        return decision.fingerprint
    return decision.bind(update.new, target.base_sha).fingerprint


def _unchanged_decision(decision: Policy | Binding | None, receipt: Receipt) -> bool:
    """Compare both the admitted packet and its resolved lifecycle representation."""
    if decision is None:
        return True
    bound = _bound_identity(decision, receipt)
    publication = receipt.publication
    recorded = None if publication is None else publication.decision_identity
    return bound == receipt.policy_identity or (
        recorded is not None and recorded in (decision.fingerprint, bound)
    )


class _Publish:
    def __init__(
        self,
        git: GitRepository,
        provider: GitHub,
        store: Store,
        request: Request,
        receipt: Receipt | None,
    ) -> None:
        self.git = git
        self.provider = provider
        self.store = store
        self.request = request
        self.receipt = receipt
        self.code = lifecycle.code_identity()
        self.deadline = time.monotonic() + request.wait_timeout
        self.attempted = False
        self.performed = False
        self.cancelled = False
        self.changeset_result: dict[str, object] | None = None
        self.pushed = False
        self.created = False

    # -- journal ------------------------------------------------------------------

    @property
    def record(self) -> Receipt:
        if self.receipt is None:
            raise StateError("publication has no journal")
        return self.receipt

    @property
    def publication(self) -> PublicationRecord:
        publication = self.record.publication
        if publication is None:
            raise StateError("publication has no journaled identities")
        return publication

    def _save(self) -> None:
        if lifecycle.code_identity() != self.code:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "controller source changed during execution",
                "review the current controller and resume with refreshed decisions",
            )
        self.store.save(self.record)

    # -- scope ----------------------------------------------------------------------

    def _check_scope(self) -> None:
        receipt = self.receipt
        if receipt is None:
            return
        if receipt.code_identity != self.code and not self._reviewed_refresh(receipt):
            raise _Stop(
                "NEEDS_JUDGMENT",
                "saved actions belong to different controller sources",
                "review the new sources and resume with --policy naming a refreshed, "
                "changed source-backed decision; saved pushes and PR creations are "
                "then reconciled from provider facts and never sent again",
            )
        if _RANKS[self.request.endpoint] > _RANKS[receipt.endpoint]:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "resumption cannot expand the saved endpoint",
                "start a new explicitly authorized run for the broader endpoint",
            )
        if any(
            op["kind"] == "merge" and op["outcome"] in ("PENDING", "ACCEPTED")
            for op in receipt.intents
        ):
            raise _Stop(
                "NEEDS_JUDGMENT",
                "a dispatched merge is unresolved",
                "reconcile the original merge outcome before publishing new commits",
            )
        publication = receipt.publication
        if publication is not None:
            if self.request.branch not in (None, publication.head_ref):
                raise ReceiptInputError("--branch does not match the saved run")
            if self.request.head_repo not in (None, publication.head_repo):
                raise ReceiptInputError("--head-repo does not match the saved run")
            if (self.request.host, self.request.base_repo.lower()) != (
                publication.host,
                publication.base_repo.lower(),
            ):
                raise ReceiptInputError("--repo does not match the saved run")
        if receipt.code_identity != self.code:
            self._adopt_sources(receipt)

    def _reviewed_refresh(self, receipt: Receipt) -> bool:
        """Only a changed decision admitted for this run may adopt new sources."""
        decision = self.request.decision
        if _unchanged_decision(decision, receipt):
            return False
        assert decision is not None
        own = self._inspect_own()
        plan = self.request.plan
        if plan is not None:
            self._admit_plan(plan)
        changeset = receipt.changeset
        confirmed_plan = (
            plan is not None
            and changeset is not None
            and changeset.plan_identity == plan.identity
            and changeset.update is not None
            and changeset.update.outcome == "CONFIRMED"
        )
        if (
            plan is None
            or confirmed_plan
            or not (isinstance(decision, Binding) and decision.plan is not None)
        ):
            located = self._locate()
            self._check_decision(located)
            publication = receipt.publication
            if publication is not None:
                self._check_publication_scope(
                    publication, located.head_repo, located.branch, located.base_ref
                )
            pr = located.pr or own
            if pr is not None:
                prospective = (
                    replace(pr, head_sha=located.head) if pr.state == "OPEN" else pr
                )
                if _applicable(decision, prospective, receipt, self.provider) is None:
                    return False
                if pr.state == "OPEN":
                    self._require_current(pr.base_sha)
            else:
                self._verify_base(located)
        return True

    def _adopt_sources(self, receipt: Receipt) -> None:
        """Adopt the current controller sources for a run under a refreshed decision.

        Journaled identities, outcomes, target and endpoint stay exactly as saved,
        and pending pushes and PR creations are reconciled from provider facts next,
        never sent again. Only authority derived from the old sources is dropped:
        the outgoing range is validated again and lifecycle acceptance restarts from
        the refreshed decision. The save is the store's compare-and-swap.
        """
        publication = receipt.publication
        decision = self.request.decision
        if decision is None:
            raise StateError("source adoption requires an admitted decision")
        with self.store.mutation_lock():
            if publication is not None:
                publication.validated_head = None
                publication.decision_identity = decision.fingerprint
            receipt.policy_identity = _bound_identity(decision, receipt)
            receipt.validation_sha = None
            receipt.validation_policy = None
            receipt.code_identity = self.code
            receipt.status = "WAITING"
            self._save()

    # -- changeset --------------------------------------------------------------------

    def _changeset(self) -> tuple[dict[str, object], int] | None:
        plan = self.request.plan
        if plan is None:
            changeset = None if self.receipt is None else self.receipt.changeset
            update = None if changeset is None else changeset.update
            if update is not None and update.outcome == "PENDING":
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "a journaled changeset update is pending",
                    "resume with the original --plan so it is reconciled first",
                )
            return None
        if self.request.gates is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "a commit plan needs its source-backed gate decision",
                "pass the --gates packet that names the repository gates",
            )
        if self.request.branch not in (None, plan.branch):
            raise ReceiptInputError("--branch does not match the plan placement")
        self._admit_plan(plan)
        outcome = execute_changeset(
            self.git,
            self.store,
            plan,
            self.request.gates,
            self.request.endpoint,
            self.receipt,
        )
        self.attempted |= outcome.mutation_attempted
        self.performed |= outcome.mutation_performed
        self.receipt = outcome.receipt
        result = outcome.result()
        self.changeset_result = result
        if outcome.status != "COMPLETE":
            return result, 130 if outcome.cancelled else EXIT_CODES[outcome.status]
        return None

    def _admit_plan(self, plan: Plan) -> None:
        """Refuse a plan that provider facts or the journal already contradict.

        Everything checked here is known before the first commit: a closed or
        merged selected PR, another head branch, namespace or base ref, or a
        decision for another plan stops with the checkout, index, refs and journal
        exactly as they were.
        """
        branch, head_repo, selected = self._branch_and_namespace()
        self._check_plan_branch(branch)
        placement = self._placement(branch, head_repo, selected)
        publication = None if self.receipt is None else self.receipt.publication
        if publication is not None:
            self._check_publication_scope(
                publication, head_repo, branch, placement.base_ref
            )
        self._check_plan_packet(plan)

    def _check_plan_packet(self, plan: Plan) -> None:
        """A decision must name this plan, or the exact head it already produced."""
        decision = self.request.decision
        if decision is None:
            return
        if isinstance(decision, Binding) and decision.plan is not None:
            if decision.plan != plan.identity:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "the decision is bound to a different commit plan than the one "
                    "to execute",
                    "refresh the decision for this plan's identity; nothing was "
                    "committed",
                )
            return
        changeset = None if self.receipt is None else self.receipt.changeset
        update = None if changeset is None else changeset.update
        if (
            changeset is not None
            and changeset.plan_identity == plan.identity
            and update is not None
            and update.outcome == "CONFIRMED"
        ):
            return  # no commit follows; the confirmed head is checked before any push
        raise _Stop(
            "NEEDS_JUDGMENT",
            "a decision naming an explicit head cannot bind commits this plan has "
            "not produced yet",
            "bind the decision to the plan's identity, or refresh the packet for the "
            "head once the plan's commits are confirmed; nothing was committed",
        )

    # -- the run's own PR -------------------------------------------------------------

    def _own_number(self) -> int | None:
        """The PR this run already owns: its bound target, else a confirmed creation."""
        receipt = self.receipt
        if receipt is None:
            return None
        if receipt.target is not None:
            return receipt.target.number
        publication = receipt.publication
        create = None if publication is None else publication.create
        if create is not None and create.outcome == "CONFIRMED":
            return create.number
        return None

    def _merged_reuse(self, own: PullRequest, branch: str) -> bool:
        """Whether ``own`` merged exactly the local head, so nothing is published."""
        head = self.git.resolve_ref(f"refs/heads/{branch}")
        plan = self.request.plan
        if plan is None:
            return head in (None, own.head_sha)  # a missing branch is stopped by locate
        if head != own.head_sha:
            return False
        changeset = None if self.receipt is None else self.receipt.changeset
        update = None if changeset is None else changeset.update
        return (
            changeset is not None
            and changeset.plan_identity == plan.identity
            and update is not None
            and update.outcome == "CONFIRMED"
            and update.new == own.head_sha
        )

    def _inspect_own(self) -> PullRequest | None:
        """Read the run's own PR before any local commit or publication mutation.

        A saved target or confirmed creation names its PR for good. While that PR is
        open the run keeps publishing into it; a PR merged at exactly the local head
        is reused as is. A closed PR, or one merged short of new local work, is never
        replaced: the run stops, before committing, pushing or creating, for one
        explicit decision.
        """
        number = self._own_number()
        if number is None:
            return None
        if self.request.number not in (None, number):
            raise ReceiptInputError("--pr does not match the saved run")
        own = self.provider.read_pr(number)
        branch, head_repo, _ = self._branch_and_namespace()
        if (own.head_ref, own.head_repo.lower()) != (branch, head_repo.lower()):
            raise _Stop(
                "BLOCKED",
                f"PR {number} of this run does not use {head_repo}:{branch}",
                "resume with the selector of that PR's own branch, or start a new "
                "run; nothing was committed or published",
            )
        if own.state == "OPEN" or (
            own.state == "MERGED" and self._merged_reuse(own, branch)
        ):
            return own
        what = (
            "closed without a confirmed merge"
            if own.state == "CLOSED"
            else "merged and cannot take new local work"
        )
        raise _Stop(
            "NEEDS_JUDGMENT",
            f"PR {number} of this run is {what}",
            f"choose exactly one: reopen PR {number} and resume this run, start a new "
            "run to publish a replacement, or select another run; nothing was "
            "committed, pushed or created",
        )

    def _expect_own(self, pr: PullRequest | None) -> None:
        """The PR found for the head must be the one the run already owns."""
        number = self._own_number()
        if number is not None and (pr is None or pr.number != number):
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"PR {number} of this run is not the exact PR of its head and base",
                "inspect the PRs for this head; a replacement is never created for a "
                "saved PR",
            )

    def _preflight(self, own: PullRequest | None) -> None:
        """Stop before any commit, push or creation that a new PR could not follow."""
        request = self.request
        if own is not None or (request.title is not None and request.body is not None):
            return
        branch, head_repo, selected = self._branch_and_namespace()
        if selected is not None:
            return  # an explicitly selected PR is reused, never created
        head = (
            None
            if request.plan is not None
            else self.git.resolve_ref(f"refs/heads/{branch}")
        )
        base_ref = self._base_binding()[0]
        if any(
            pr.state == "OPEN" or (head is not None and pr.head_sha == head)
            for pr in self.provider.find_prs(head_repo, branch, base_ref)
        ):
            return  # exact PR evidence exists; its own checks follow
        raise _Stop(
            "NEEDS_JUDGMENT",
            "a new PR needs its title and body",
            "write the title and body (actual changes, exercised verification, "
            "issue references) and resume with --title and --body-file; nothing was "
            "committed, pushed or created",
        )

    # -- target location --------------------------------------------------------------

    def _base_binding(self) -> tuple[str | None, str | None]:
        receipt = self.receipt
        plan = self.request.plan
        decision = self.request.decision
        if plan is not None:
            return plan.base_ref, plan.base_oid
        if isinstance(decision, Binding) and decision.base_ref is not None:
            # An explicit packet is the current decision; a saved base is only the
            # one the publication was first written for.
            return decision.base_ref, decision.base_oid
        if receipt is not None and receipt.publication is not None:
            return receipt.publication.base_ref, receipt.publication.base_oid
        if receipt is not None and receipt.changeset is not None:
            return receipt.changeset.base_ref, receipt.changeset.base_oid
        return None, None

    def _branch_and_namespace(self) -> tuple[str, str, PullRequest | None]:
        request = self.request
        receipt = self.receipt
        if request.number is not None:
            selected = self.provider.read_pr(request.number)
            if not selected.head_repo:
                raise _Stop(
                    "BLOCKED",
                    "the selected PR has no readable head repository",
                    "resolve the head namespace; nothing is published",
                )
            if (
                request.head_repo is not None
                and request.head_repo.lower() != selected.head_repo.lower()
            ):
                raise ReceiptInputError("--head-repo does not match the selected PR")
            return selected.head_ref, selected.head_repo, selected
        publication = None if receipt is None else receipt.publication
        target = None if receipt is None else receipt.target
        branch: str | None
        if request.plan is not None:
            branch = request.plan.branch
        elif publication is not None:
            branch = publication.head_ref
        elif target is not None:
            branch = target.head_ref
        elif receipt is not None and receipt.changeset is not None:
            branch = receipt.changeset.branch
        elif request.branch is not None:
            branch = request.branch
        else:
            branch = self.git.snapshot().branch
        if branch is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "a detached checkout has no identifiable target branch",
                "select the branch or PR to ship explicitly",
            )
        head_repo = (
            request.head_repo
            or (publication.head_repo if publication is not None else None)
            or (target.head_repo if target is not None and target.head_repo else None)
            or request.base_repo
        )
        return branch, head_repo, None

    def _check_plan_branch(self, branch: str) -> None:
        plan = self.request.plan
        if plan is not None and plan.branch != branch:
            raise _Stop(
                "BLOCKED",
                "the plan places commits on a different branch than the selected PR",
                "author the plan with current placement on the PR head branch",
            )

    def _placement(
        self, branch: str, head_repo: str, selected: PullRequest | None
    ) -> _Placement:
        """The PR and base of this publication, from provider facts and the journal.

        It needs no local head, so a plan is checked against it before its first
        commit as well as afterwards.
        """
        base_ref, base_oid = self._base_binding()
        open_prs = [
            pr for pr in self.provider.find_prs(head_repo, branch) if pr.state == "OPEN"
        ]
        if (
            selected is not None
            and selected.state == "MERGED"
            and selected.number == self._own_number()
            and self._merged_reuse(selected, branch)
        ):
            open_prs.append(selected)
        elif selected is not None:
            open_prs = [pr for pr in open_prs if pr.number == selected.number]
            if not open_prs:
                if selected.state != "OPEN":
                    raise _Stop(
                        "NEEDS_JUDGMENT",
                        f"selected PR {selected.number} is {selected.state.lower()} "
                        "and cannot take new local work",
                        "reopen it, or publish a replacement by selecting the branch "
                        "in a new run; nothing was committed, pushed or created",
                    )
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "the selected PR is not an open exact match for its head",
                    "inspect the PR state; nothing is published",
                )
        if len(open_prs) > 1:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"several open PRs use {head_repo}:{branch}: "
                f"{sorted(pr.number for pr in open_prs)}",
                "select the intended PR with --pr",
            )
        pr = open_prs[0] if open_prs else None
        if pr is not None:
            if base_ref is not None and base_ref != pr.base_ref:
                raise _Stop(
                    "BLOCKED",
                    f"the PR targets {pr.base_ref}, not the intended {base_ref}",
                    "resolve the intended base; a PR is never retargeted implicitly",
                )
            base_ref = pr.base_ref
        if base_ref is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "the intended base of a new PR is unknown",
                "bind the base through a commit plan or a schema 2 decision",
            )
        if branch == base_ref:
            raise _Stop(
                "BLOCKED",
                "the selected branch is the intended base",
                "commit the work onto a feature branch first",
            )
        return _Placement(pr, base_ref, base_oid)

    def _locate(self) -> _Located:
        branch, head_repo, selected = self._branch_and_namespace()
        self._check_plan_branch(branch)
        head = self.git.resolve_ref(f"refs/heads/{branch}")
        if head is None:
            raise _Stop(
                "BLOCKED",
                f"local branch {branch} does not exist",
                "select an existing local branch or create its commits with a plan",
            )
        remote = self.git.remote_for(self.request.host, head_repo)
        if remote is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"no unambiguous remote publishes {head_repo}",
                "add or select the remote of the intended head namespace and resume",
            )
        placement = self._placement(branch, head_repo, selected)
        return _Located(
            branch,
            head,
            head_repo,
            remote,
            placement.base_ref,
            placement.base_oid,
            placement.pr,
        )

    def _dirty_check(self, located: _Located) -> None:
        changeset = None if self.receipt is None else self.receipt.changeset
        residual = None if changeset is None else changeset.residual_snapshot
        invoking = self.git.snapshot()
        if invoking.dirty and self.request.endpoint != "pr":
            raise _Stop(
                "NEEDS_JUDGMENT",
                "the authorized lifecycle needs a clean retained checkout; original "
                "excluded or transplanted user work is still present",
                f"select a clean retained checkout of {located.base_ref} without "
                "discarding, stashing or resetting the original files and index",
            )
        for tree in invoking.worktrees:
            if tree.branch != located.branch or tree.prunable:
                continue
            current = (
                invoking
                if os.path.realpath(tree.path) == os.path.realpath(invoking.root)
                else GitRepository(tree.path).snapshot()
            )
            if not current.dirty:
                continue
            if residual is not None and current.fingerprint == residual:
                if self.request.endpoint == "clean":
                    raise _Stop(
                        "NEEDS_JUDGMENT",
                        f"retained user work still occupies required feature {located.branch}",
                        "preserve that work on an explicitly selected retained branch "
                        "and use a clean base checkout before publication",
                    )
                continue  # PR-only publication preserves the explicit residual state.
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"uncommitted work on {located.branch} has no disposition",
                "inventory it and resume with a commit plan; an open PR is never a "
                "no-op while local work is unaccounted for",
            )

    def _named_base(self) -> str | None:
        """The base an explicit decision was written for; plans resolve later."""
        decision = self.request.decision
        if isinstance(decision, Binding):
            return None if decision.plan is not None else decision.base_oid
        return None if decision is None else decision.base_sha

    def _require_current(self, current: str) -> None:
        """Refuse a stale explicit decision before any push or creation.

        It is never widened to the new base: the caller must refresh it.
        """
        named = self._named_base()
        if named is not None and named != current:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"the explicit decision is stale: it names base {named} but the "
                f"current base is {current}",
                "refresh the source-backed decision for the current base; nothing was "
                "pushed or created",
            )

    def _verify_base(self, located: _Located) -> None:
        """Placement of a new PR: a named base related to the head and current."""
        if located.base_oid is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "a new PR needs a bound base commit",
                "bind the base through a commit plan or a schema 2 decision",
            )
        if not self.git.is_ancestor(located.base_oid, located.head):
            # Existing feature history need not descend from the current named
            # base; only history that shares nothing with it is refused.
            related = self.git.run(
                "merge-base", located.base_oid, located.head, check=False
            )
            if related.returncode == 1:
                raise _Stop(
                    "BLOCKED",
                    "the local branch shares no history with the intended base commit",
                    "unrelated history is never published into this PR",
                )
            if related.returncode != 0:
                raise GitError(f"git merge-base failed (exit {related.returncode})")
        tip = self.provider.base_tip(located.base_ref)
        if tip != located.base_oid and not self.provider.landing_reachable(
            located.base_oid, tip
        ):
            raise _Stop(
                "BLOCKED",
                "the intended base commit is not on the current base branch",
                "re-plan onto the current base; nothing was published",
            )
        self._require_current(tip)

    # -- push -------------------------------------------------------------------------

    def _unresolved_elsewhere(self, located: _Located) -> None:
        """Another run's unknown push or PR creation for this head blocks new ones."""
        own = None if self.receipt is None else self.receipt.run_id
        wanted = (
            self.request.host,
            self.request.base_repo.lower(),
            located.head_repo.lower(),
            located.branch,
        )
        for record in self.store.list_runs(exclude=own):
            other = record.publication
            if other is None:
                continue
            if (
                other.host,
                other.base_repo.lower(),
                other.head_repo.lower(),
                other.head_ref,
            ) != wanted:
                continue
            if any(
                step is not None and step.outcome == "PENDING"
                for step in (other.push, other.create)
            ):
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"run {record.run_id} has an unresolved push or PR creation for "
                    f"{located.head_repo}:{located.branch}",
                    f"resume run {record.run_id}; nothing is pushed or created again "
                    "while its outcome is unknown",
                )

    def _ensure_publication(self, located: _Located) -> PublicationRecord:
        self._unresolved_elsewhere(located)
        if self.receipt is None:
            self.receipt = Receipt(
                uuid.uuid4().hex,
                self.request.endpoint,
                self.code,
                None,
                self.git.snapshot().fingerprint,
                None,
            )
        publication = self.receipt.publication
        if publication is None:
            publication = PublicationRecord(
                host=self.request.host,
                base_repo=self.request.base_repo,
                base_ref=located.base_ref,
                base_oid=located.base_oid,
                head_repo=located.head_repo,
                head_ref=located.branch,
                remote=located.remote,
                head=located.head,
            )
            self.receipt.publication = publication
            with self.store.mutation_lock():
                self._save()
        else:
            self._check_publication_scope(
                publication, located.head_repo, located.branch, located.base_ref
            )
            if publication.base_oid != located.base_oid:
                # A refreshed explicit packet names the actual current base; the saved
                # one is only the base the publication was first written for.
                with self.store.mutation_lock():
                    publication.base_oid = located.base_oid
                    self._save()
        return publication

    def _check_publication_scope(
        self,
        publication: PublicationRecord,
        head_repo: str,
        branch: str,
        base_ref: str,
    ) -> None:
        if (
            publication.head_repo.lower(),
            publication.head_ref,
            publication.base_ref,
        ) != (head_repo.lower(), branch, base_ref):
            raise _Stop(
                "BLOCKED",
                "the saved publication names a different head or base",
                "resume the run of that publication, or start a new run",
            )

    def _reconcile_push(self, publication: PublicationRecord) -> None:
        push = publication.push
        if push is None or push.outcome != "PENDING":
            return
        observed = self.git.remote_head(publication.remote, publication.head_ref)
        with self.store.mutation_lock():
            if observed == push.new:
                push.outcome = "CONFIRMED"
                self.pushed = True
            elif observed == push.old:
                push.outcome = "REJECTED"
            else:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "the pending push left neither the expected old nor new remote head",
                    "inspect the remote branch; nothing is pushed again blindly",
                )
            self._save()

    def _validate_outgoing(
        self, publication: PublicationRecord, located: _Located, start: str
    ) -> None:
        if publication.validated_head == located.head:
            return
        gates = self.request.gates
        if gates is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "outgoing revisions need the source-backed gate and secret-scan decision",
                "pass the --gates packet; nothing was pushed",
            )
        changeset = self.record.changeset
        created = set() if changeset is None else set(changeset.confirmed)
        outgoing = (
            self.git.run("rev-list", "--reverse", f"{start}..{located.head}")
            .stdout.decode("ascii", "replace")
            .split()
        )
        check_outgoing(
            self.git,
            gates,
            start,
            located.head,
            run_gates=any(commit not in created for commit in outgoing),
        )
        with self.store.mutation_lock():
            publication.validated_head = located.head
            self._save()

    def _publish_head(self, publication: PublicationRecord, located: _Located) -> None:
        remote_head = self.git.remote_head(located.remote, located.branch)
        if remote_head == located.head:
            return
        if remote_head is not None:
            if self.git.resolve_ref(remote_head) != remote_head:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"published {located.branch} holds commits that are not local",
                    "fetch and decide how to combine them; nothing was pushed",
                )
            if self.git.is_ancestor(located.head, remote_head):
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    f"local {located.branch} is behind its published branch",
                    "update the local branch deliberately; nothing was pushed",
                )
            if not self.git.is_ancestor(remote_head, located.head):
                raise _Stop(
                    "BLOCKED",
                    f"local and published {located.branch} diverged",
                    "rewriting published history is not authorized; nothing was pushed",
                )
        start = remote_head if remote_head is not None else located.base_oid
        if start is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "the outgoing range has no published or bound base",
                "bind the intended base commit before publishing",
            )
        self._validate_outgoing(publication, located, start)
        pusher = GitRepository(self.git.path, timeout=PUSH_TIMEOUT)
        with self.store.mutation_lock():
            self._unresolved_elsewhere(located)
            if self.git.remote_head(located.remote, located.branch) != remote_head:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "the published branch moved while the outgoing range was validated",
                    "re-observe and resume; nothing was pushed",
                )
            push = PushRecord(remote_head, located.head)
            publication.head = located.head
            publication.push = push
            self._save()
            self.attempted = True
            try:
                pusher.push_head(
                    located.remote, located.branch, located.head, remote_head
                )
            except GitRefused as error:
                push.outcome = "REJECTED"
                self._save()
                raise _Stop(
                    "BLOCKED",
                    f"the push was refused: {lifecycle._safe_error(error)}",
                    "resolve the lease, hook or permission refusal; nothing was forced",
                ) from error
            except GitError as error:
                if not error.uncertain:
                    push.outcome = "REJECTED"
                    self._save()
                    raise
                raise _Stop(
                    "WAITING",
                    "the push outcome is unknown",
                    "resume this run; the remote head is reconciled before any retry",
                ) from error
            push.outcome = "CONFIRMED"
            self.performed = True
            self.pushed = True
            self._save()

    # -- PR ---------------------------------------------------------------------------

    def _match(
        self, located: _Located, *, creation: bool = False
    ) -> PullRequest | None:
        """Resolve exact creation evidence separately from usable PR publication."""
        expected = located.head
        publication = self.record.publication
        if creation and publication is not None:
            expected = publication.head
        candidates = [
            pr
            for pr in self.provider.find_prs(
                located.head_repo, located.branch, located.base_ref
            )
            if pr.state == "OPEN" or pr.head_sha == expected
        ]
        if len(candidates) > 1:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"several PRs match {located.head_repo}:{located.branch} -> "
                f"{located.base_ref}: {sorted(pr.number for pr in candidates)}",
                "select the intended PR with --pr; no duplicate is created",
            )
        if candidates and candidates[0].state == "CLOSED" and not creation:
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"PR {candidates[0].number} is closed without a confirmed merge",
                "explicitly choose whether to reopen that PR or publish a replacement; "
                "a closed unmerged PR is not successful publication",
            )
        return candidates[0] if candidates else None

    def _sleep(self, reason: str, next_action: str) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Stop("WAITING", reason, next_action)
        # No cooperative lock is held while waiting for provider replication.
        time.sleep(min(lifecycle.POLL_INTERVAL, remaining))

    def _await_settle(
        self, publication: PublicationRecord, located: _Located
    ) -> PullRequest | None:
        """Resolve a creation of unknown outcome only from an exact provider match.

        The request may have been accepted, so neither an empty lookup nor the
        time elapsed since dispatch proves it was refused. The creation stays
        PENDING and is never sent again; the run waits for the exact PR.
        """
        create = publication.create
        if create is None or create.outcome != "PENDING":
            return None
        while True:
            found = self._match(located, creation=True)
            if found is not None:
                with self.store.mutation_lock():
                    create.outcome = "CONFIRMED"
                    create.number = found.number
                    self._save()
                return found
            self._sleep(
                "a PR creation with an unknown outcome is not observable for "
                f"{located.head_repo}:{located.branch} -> {located.base_ref}",
                "resume this run once the exact PR is listed (a PR opened deliberately "
                "for this head and base also resolves it); nothing is created again "
                "while the outcome is unknown",
            )

    def _create(self, publication: PublicationRecord, located: _Located) -> PullRequest:
        existing = publication.create
        if self._own_number() is not None or (
            existing is not None and existing.outcome != "REJECTED"
        ):
            raise _Stop(
                "NEEDS_JUDGMENT",
                "this run already owns a PR or an unreconciled creation",
                "a replacement is never created for a saved PR: reopen or select it, "
                "or start a new run",
            )
        title, body = self.request.title, self.request.body
        if title is None or body is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "a new PR needs its title and body",
                "write the title and body (actual changes, exercised verification, "
                "issue references) and resume with --title and --body-file",
            )
        uncertain: ProviderError | None = None
        with tempfile.TemporaryDirectory(prefix="ship-pr-") as temp:
            body_file = Path(temp) / "body.md"
            descriptor = os.open(body_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(body)
            with self.store.mutation_lock():
                self._unresolved_elsewhere(located)
                create = CreateRecord(
                    _identity(title.encode("utf-8")),
                    _identity(body),
                    datetime.now(UTC).isoformat(),
                )
                publication.create = create
                self._save()
                self.attempted = True
                try:
                    pr = self.provider.create_pr(
                        located.head_repo,
                        located.branch,
                        located.base_ref,
                        title,
                        body_file,
                    )
                except ProviderError as error:
                    if error.uncertain:
                        uncertain = error  # stays PENDING; resolved outside the lock
                    elif error.detail != "pr-already-exists":
                        create.outcome = "REJECTED"
                        self._save()
                        raise
                    else:
                        found = self._match(located, creation=True)
                        if found is not None:
                            create.outcome = "CONFIRMED"
                            create.number = found.number
                            self._save()
                            return found
                        create.outcome = "REJECTED"
                        self._save()
                        raise _Stop(
                            "NEEDS_JUDGMENT",
                            "GitHub reports an existing PR the exact lookup cannot match",
                            "inspect the PRs for this head; no duplicate is created",
                        ) from error
                else:
                    create.outcome = "CONFIRMED"
                    create.number = pr.number
                    self.performed = True
                    self.created = True
                    self._save()
                    return pr
        # The request may have reached GitHub: wait, without the lock, for the
        # exact PR to be listed instead of sending a second creation.
        found = self._await_settle(publication, located)
        if found is None:
            raise StateError("a pending PR creation lost its journal") from uncertain
        return found

    def _bind(self, located: _Located, pr: PullRequest) -> Policy | None:
        current = self.provider.read_pr(pr.number)
        while current.state == "OPEN" and current.head_sha != located.head:
            self._sleep(
                "the PR does not yet report the published head",
                "resume this run once the provider reflects the push",
            )
            current = self.provider.read_pr(pr.number)
        if (
            current.head_repo.lower() != located.head_repo.lower()
            or current.head_ref != located.branch
            or current.base_ref != located.base_ref
            or current.base_repo.lower() != self.request.base_repo.lower()
        ):
            raise _Stop(
                "BLOCKED",
                "the PR head/base identities changed during publication",
                "inspect the PR; its scope is never rebound implicitly",
            )
        if current.state == "CLOSED":
            raise _Stop(
                "NEEDS_JUDGMENT",
                f"PR {current.number} is closed without a confirmed merge",
                "explicitly choose whether to reopen that PR or publish a replacement",
            )
        if current.state == "MERGED" and current.head_sha != located.head:
            raise _Stop(
                "BLOCKED",
                "the PR was merged at a different head than the local one",
                "inspect the actual landing; nothing further is published",
            )
        decision = self.request.decision
        policy = _applicable(decision, current, self.record, self.provider)
        if decision is not None and policy is None:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "the decision does not apply to the confirmed PR's head and base",
                "refresh the source-backed decision for the actual published head "
                "and base",
            )
        receipt = self.record
        with self.store.mutation_lock():
            target = receipt.target
            if target is None:
                target = Target(
                    self.request.host,
                    current.base_repo,
                    current.number,
                    current.head_sha,
                    current.base_sha,
                    current.head_ref,
                    current.head_repo,
                    current.base_ref,
                )
                receipt.target = target
            elif target.number != current.number:
                raise _Stop(
                    "BLOCKED",
                    "the run is bound to a different PR",
                    "resume the run of that PR, or start a new run",
                )
            if current.state == "OPEN":
                target.head_sha = current.head_sha
                target.base_sha = current.base_sha
            if (
                policy is not None
                and decision is not None
                and receipt.publication is not None
            ):
                receipt.publication.decision_identity = decision.fingerprint
            self._save()
        return policy

    def _check_decision(self, located: _Located) -> None:
        """Refuse a decision that cannot apply to the head about to be published."""
        decision = self.request.decision
        if decision is None:
            return
        if not isinstance(decision, Binding):
            if decision.head_sha != located.head:
                raise _Stop(
                    "NEEDS_JUDGMENT",
                    "the decision is bound to a different head than the local one",
                    "refresh the source-backed decision before publishing this head",
                )
            return
        applies = (
            _plan_applies(decision, located.head, self.receipt) is not None
            if decision.plan is not None
            else (
                decision.head == located.head
                and decision.base_oid is not None
                and decision.base_ref == located.base_ref
            )
        )
        if not applies:
            raise _Stop(
                "NEEDS_JUDGMENT",
                "the decision is bound to a different head or base than the published one",
                "refresh the source-backed decision for the actual published head",
            )

    # -- driver -----------------------------------------------------------------------

    def _run(self) -> tuple[dict[str, object], int]:
        self._check_scope()
        saved = None if self.receipt is None else self.receipt.publication
        if saved is not None and any(
            step is not None and step.outcome == "PENDING"
            for step in (saved.push, saved.create)
        ):
            pending = self._locate()
            self._check_publication_scope(
                saved, pending.head_repo, pending.branch, pending.base_ref
            )
            self._reconcile_push(saved)
            self._await_settle(saved, pending)
        own = self._inspect_own()
        self._preflight(own)
        stopped = self._changeset()
        if stopped is not None:
            return stopped
        located = self._locate()
        self._dirty_check(located)
        self._check_decision(located)
        publication = self._ensure_publication(located)
        self._reconcile_push(publication)
        pr = located.pr or self._match(located)
        self._expect_own(pr)
        if pr is None:
            self._verify_base(located)
        elif pr.state == "OPEN" and self._named_base() is not None:
            self._require_current(self.provider.read_pr(pr.number).base_sha)
        if pr is None or pr.state == "OPEN":
            # A PR merged at this exact head is reused: its head branch is gone or
            # landed, and republishing would resurrect it and re-run outgoing gates.
            self._publish_head(publication, located)
        if pr is None:
            pr = self._create(publication, located)
        policy = self._bind(located, pr)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Stop(
                "WAITING",
                "the monitoring window ended after publication",
                "resume this run to continue the confirmed PR",
            )
        result, code = lifecycle.execute(
            self.git,
            self.provider,
            pr.number,
            self.request.endpoint,
            policy,
            remaining,
            self.store,
            self.record,
        )
        return self._merge(result), code

    def _publication_result(self) -> dict[str, object] | None:
        publication = None if self.receipt is None else self.receipt.publication
        if publication is None:
            return None
        push, create = publication.push, publication.create
        return {
            "host": publication.host,
            "base": {"repository": publication.base_repo, "ref": publication.base_ref},
            "head": {
                "repository": publication.head_repo,
                "ref": publication.head_ref,
                "revision": publication.head,
            },
            "push": None
            if push is None
            else {"old": push.old, "new": push.new, "outcome": push.outcome},
            "pr": None
            if create is None
            else {"outcome": create.outcome, "number": create.number},
            "pushed_now": self.pushed,
            "created_now": self.created,
        }

    def _merge(self, result: dict[str, object]) -> dict[str, object]:
        changeset = None if self.receipt is None else self.receipt.changeset
        merged = dict(result)
        merged["confirmed_commits"] = (
            [] if changeset is None else list(changeset.confirmed)
        )
        merged["changeset"] = self.changeset_result
        merged["publication"] = self._publication_result()
        merged["mutation_attempted"] = (
            bool(result.get("mutation_attempted")) or self.attempted
        )
        merged["mutation_performed"] = (
            bool(result.get("mutation_performed")) or self.performed
        )
        return merged

    def _finish(
        self, status: Status, reason: str, next_action: str
    ) -> tuple[dict[str, object], int]:
        if (
            self.receipt is not None
            and self.receipt.code_identity == self.code
            and lifecycle.code_identity() == self.code
        ):
            receipt = self.receipt
            receipt.status = status
            receipt.issue = reason
            receipt.next_action = next_action
            try:
                with self.store.mutation_lock():
                    self.store.save(receipt)
            except (StateError, OSError) as error:
                status = "WAITING" if isinstance(error, LockBusy) else "BLOCKED"
                reason = f"receipt preservation failed: {lifecycle._safe_error(error)}"
        target = None if self.receipt is None else self.receipt.target
        result: dict[str, object] = {
            "schema_version": 1,
            "run_id": None if self.receipt is None else self.receipt.run_id,
            "status": status,
            "target": {
                "repository": self.request.base_repo,
                "pr": None if target is None else target.number,
                "endpoint": self.request.endpoint,
            },
            "blocker": reason,
            "next_action": next_action,
            "cancelled": self.cancelled,
        }
        return self._merge(result), 130 if self.cancelled else EXIT_CODES[status]

    def run(self) -> tuple[dict[str, object], int]:
        try:
            return self._run()
        except KeyboardInterrupt:
            self.cancelled = True
            return self._finish(
                "WAITING",
                "execution cancelled; reconcile before resuming",
                "resume this run; journaled pushes and PR creations are reconciled first",
            )
        except (_Stop, ChangesetStop) as stop:
            return self._finish(stop.status, str(stop), stop.next_action)
        except LockBusy as error:
            return self._finish(
                "WAITING",
                lifecycle._safe_error(error),
                "resume when the controller lock is free",
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


def ship(
    git: GitRepository,
    provider: GitHub,
    store: Store,
    request: Request,
    receipt: Receipt | None,
) -> tuple[dict[str, object], int]:
    """Execute one explicit request from local work through the authorized endpoint.

    A PR without unpublished local work continues exactly through the existing
    lifecycle; everything else is published first.
    """
    target = None if receipt is None else receipt.target
    if (
        request.plan is None
        and not _pending(receipt)
        and (receipt is None or target is not None)
        and not (
            receipt is not None
            and receipt.publication is not None
            and receipt.code_identity != lifecycle.code_identity()
            and _unchanged_decision(request.decision, receipt)
        )
    ):
        number = (
            request.number
            if request.number is not None
            else (None if target is None else target.number)
        )
        if number is not None:
            pr, branch = local_work(git, provider, number)
            if branch is None:
                return lifecycle.execute(
                    git,
                    provider,
                    pr.number,
                    request.endpoint,
                    _applicable(request.decision, pr, receipt, provider),
                    request.wait_timeout,
                    store,
                    receipt,
                )
    return _Publish(git, provider, store, request, receipt).run()


def preview(
    git: GitRepository, provider: GitHub, request: Request
) -> dict[str, object]:
    """Read-only plan of the actions an execution would take; writes nothing."""
    actions: list[dict[str, object]] = []
    head: str | None = None
    head_repo = request.head_repo or request.base_repo
    if request.plan is not None:
        if request.gates is None:
            raise ReceiptInputError("a commit plan needs its --gates decision")
        prepared = validate(git, request.plan, take_inventory(git), request.gates)
        actions.append(
            {
                "action": "commit",
                "plan": request.plan.identity,
                "branch": request.plan.branch,
                "mode": prepared.mode,
                "groups": [group.id for group in request.plan.groups],
            }
        )
        branch: str | None = request.plan.branch
    elif request.number is not None:
        pr, local = local_work(git, provider, request.number)
        if local is None:
            return lifecycle.inspection(
                git,
                provider,
                pr.number,
                request.endpoint,
                _applicable(request.decision, pr, None, provider),
            )
        if pr.state != "OPEN":
            raise ReceiptInputError(
                f"PR {pr.number} is {pr.state.lower()} and cannot take new local "
                "work; reopen it or publish a replacement from a new run"
            )
        branch = local
        head = git.resolve_ref(f"refs/heads/{local}")
        head_repo = pr.head_repo
    else:
        branch = request.branch or git.snapshot().branch
        if branch is not None:
            head = git.resolve_ref(f"refs/heads/{branch}")
    if branch is None:
        raise ReceiptInputError("no unambiguous branch is selected")
    remote = git.remote_for(request.host, head_repo)
    remote_head = None if remote is None else git.remote_head(remote, branch)
    prs = provider.find_prs(head_repo, branch)
    open_prs = sorted(pr.number for pr in prs if pr.state == "OPEN")
    candidates = [
        pr
        for pr in prs
        if pr.state == "OPEN" or (head is not None and pr.head_sha == head)
    ]
    merged = [pr.number for pr in candidates if pr.state == "MERGED"]
    reuse_merged = len(candidates) == 1 and len(merged) == 1
    if not reuse_merged and (head is None or remote_head != head):
        actions.append(
            {
                "action": "push",
                "remote": remote,
                "branch": branch,
                "expected_old": remote_head,
                "new": head,
            }
        )
    if len(open_prs) == 1:
        actions.append({"action": "reuse-pr", "number": open_prs[0]})
    elif reuse_merged:
        actions.append({"action": "reuse-pr", "number": merged[0]})
    elif not open_prs:
        actions.append({"action": "create-pr", "head": f"{head_repo}:{branch}"})
    else:
        actions.append({"action": "select-pr", "candidates": open_prs})
    actions.append({"action": "lifecycle", "endpoint": request.endpoint})
    return {
        "schema_version": 1,
        "run_id": None,
        "status": "PLANNED",
        "target": {
            "repository": request.base_repo,
            "branch": branch,
            "endpoint": request.endpoint,
        },
        "actions": actions,
        "remote_reads": ["git ls-remote", "GET pulls?head"],
        "mutation_performed": False,
    }
