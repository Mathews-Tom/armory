"""Guarded source-only graph renewal; deliberately no lifecycle landing calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

import graph
from git_ops import GitRepository
from github_ops import GitHub, PullRequest
from lifecycle import Status
from state_store import (
    GraphJournal,
    Promotion,
    RenewalAncestor,
    RenewalCompletion,
    RenewalEvidence,
    StateError,
)


def _native_source(plan: graph.StackPlan, pr: PullRequest) -> bool:
    """An unselected landed ancestor supplies evidence, not a native operation."""
    return pr.native and (plan.node(pr.number).selected or pr.state != "MERGED")


class RenewalRun(graph._GraphRun):
    """Reuse graph leases, frozen proposals, validation, locks and reconciliation."""

    @property
    def renewal(self) -> RenewalEvidence:
        evidence = self.record.renewal
        if evidence is None:
            raise StateError("source renewal has no saved evidence")
        return evidence

    def _owner(self, prs: Mapping[int, PullRequest]) -> graph._GraphRun:
        if self.journal is not None and self.record.native is not None:
            raise graph._Stop(
                "BLOCKED",
                "native source renewal is unsupported",
                "retain the native stack unchanged",
            )
        if any(_native_source(self.plan, prs[number]) for number in self.scope):
            raise graph._Stop(
                "BLOCKED",
                "native source renewal is unsupported",
                "retain the native stack unchanged",
            )
        return self

    def _refresh(self, journal: GraphJournal) -> None:
        raise graph._Stop(
            "NEEDS_JUDGMENT",
            "source renewal keeps immutable resume authority",
            "resume with the saved packet or start a new run",
        )

    def _unchanged(self, pr: PullRequest) -> PullRequest:
        current = super()._unchanged(pr)
        node = self.plan.node(pr.number)
        if _native_source(self.plan, current) or (
            current.head_repo.lower(),
            current.base_repo.lower(),
        ) != (
            node.head_repo.lower(),
            self.plan.repo.lower(),
        ):
            raise graph._Stop(
                "BLOCKED",
                f"#{pr.number} changed source namespace or became native",
                "retain all refs and resolve the source identity",
            )
        if not node.selected and current.merge_commit_sha != pr.merge_commit_sha:
            raise graph._Stop(
                "BLOCKED",
                f"external ancestor #{pr.number} changed merge identity",
                "resolve exact external landing evidence",
            )
        return current

    def _guard_scope(self) -> None:
        prs = self._observe()
        self._check(prs, graph._expected(self.plan, self.record), ())
        for saved in self.renewal["ancestors"]:
            current = prs[saved["pr"]]
            if current.merge_commit_sha != saved["merge"]:
                raise graph._Stop(
                    "BLOCKED",
                    "external ancestor merge identity changed",
                    "resolve exact external evidence",
                )

    def _finish(
        self, status: Status, reason: str | None, next_action: str, *, save: bool = True
    ) -> tuple[dict[str, object], int]:
        if self.journal is not None and self.journal.status == "COMPLETE":
            save = False
        return super()._finish(status, reason, next_action, save=save)

    def _check(
        self,
        prs: Mapping[int, PullRequest],
        expected: Mapping[int, tuple[str, str]],
        pending: tuple[graph.Finding, ...],
    ) -> None:
        self._owner(prs)
        findings = list(pending)
        for node in self.plan.order():
            if node.pr not in self.scope:
                continue
            pr = prs[node.pr]
            head, base = expected[node.pr]
            if (
                pr.head_repo.lower(),
                pr.head_ref,
                pr.base_repo.lower(),
                pr.head_sha,
                pr.base_ref,
            ) != (
                node.head_repo.lower(),
                node.head_ref,
                self.plan.repo.lower(),
                head,
                base,
            ):
                findings.append(
                    graph.Finding(
                        "NEEDS_JUDGMENT",
                        node.pr,
                        f"#{node.pr} source identity changed outside the controller",
                        graph._REFRESH,
                    )
                )
            if node.selected and pr.state != "OPEN":
                findings.append(
                    graph.Finding(
                        "BLOCKED",
                        node.pr,
                        f"selected #{node.pr} must remain OPEN for source renewal",
                        "refresh the source-only scope",
                    )
                )
            if node.selected and node.parent is None and node.fork is None:
                findings.append(
                    graph.Finding(
                        "NEEDS_JUDGMENT",
                        node.pr,
                        f"root #{node.pr} renewal requires an explicit fork",
                        "provide the exact source boundary",
                    )
                )
            if not node.selected and pr.state != "MERGED":
                findings.append(
                    graph.Finding(
                        "NEEDS_JUDGMENT",
                        node.pr,
                        f"open unselected ancestor #{node.pr} needs scope judgment",
                        "select the ancestor explicitly; scope never widens",
                    )
                )
            if not node.selected and pr.merge_commit_sha is None:
                findings.append(
                    graph.Finding(
                        "BLOCKED",
                        node.pr,
                        f"ancestor #{node.pr} has no merge identity",
                        "resolve the external landing evidence",
                    )
                )
        self.changes = graph.context_changes(self.plan, prs, expected)
        self.findings = tuple(findings)
        if findings:
            first = findings[0]
            raise graph._Stop(first.status, first.reason, first.next_action)

    def _initialize(self) -> bool:
        completed = super()._initialize()
        if not completed and self.record.renewal is None:
            with self.store.mutation_lock():
                self.record.renewal = {"completed": [], "ancestors": []}
                self._save()
        return completed

    def _adopt(self) -> None:
        with self.store.mutation_lock():
            tip = self._trunk()
            for node in self.plan.order():
                if node.pr not in self.scope or node.selected:
                    continue
                pr = self._unchanged(self.prs[node.pr])
                merge = pr.merge_commit_sha
                if (
                    merge is None
                    or self.git.resolve_ref(merge) != merge
                    or not self.git.is_ancestor(merge, tip)
                ):
                    raise graph._Stop(
                        "BLOCKED",
                        f"external ancestor #{node.pr} merge is not provably reachable from trunk {tip}",
                        "retain every ref and resolve the external landing evidence",
                    )
                observed: RenewalAncestor = {
                    "pr": node.pr,
                    "head": pr.head_sha,
                    "base": pr.base_ref,
                    "merge": merge,
                    "trunk": tip,
                }
                saved = next(
                    (
                        item
                        for item in self.renewal["ancestors"]
                        if item["pr"] == node.pr
                    ),
                    None,
                )
                if saved is not None:
                    if (saved["head"], saved["base"], saved["merge"]) != (
                        observed["head"],
                        observed["base"],
                        observed["merge"],
                    ):
                        raise graph._Stop(
                            "BLOCKED",
                            f"external ancestor #{node.pr} changed its landing identity",
                            "resolve the external evidence",
                        )
                else:
                    self.renewal["ancestors"].append(observed)
                    self._save()

    def _destination(
        self, node: graph.PlanNode, *, fetch: bool = True
    ) -> tuple[str, str]:
        if fetch:
            self._guard_scope()
        if node.parent is not None and self.prs[node.parent].state == "OPEN":
            parent = self.prs[node.parent]
            self._unchanged(parent)
            if fetch and self.git.resolve_ref(parent.head_sha) is None:
                self._fetch_head(parent)
            return parent.head_sha, parent.head_ref
        return (
            self._trunk() if fetch else self.provider.base_tip(self.plan.trunk)
        ), self.plan.trunk

    def _root_boundary(self, node: graph.PlanNode, source_head: str) -> None:
        """Prove a root's original source boundary even when no replay is needed."""
        if node.parent is not None:
            return
        fork = node.fork
        if (
            fork is None
            or fork == source_head
            or self.git.resolve_ref(fork) != fork
            or self.git.resolve_ref(source_head) != source_head
            or not self.git.is_ancestor(fork, source_head)
        ):
            raise graph._Stop(
                "NEEDS_JUDGMENT",
                f"root #{node.pr} has an unprovable original source boundary",
                "provide an available strict-ancestor fork of the original source head",
            )

    def _step(self, prs: dict[int, PullRequest]) -> bool:
        self._adopt()
        for node in self.plan.selected_nodes():
            saved = next(
                (item for item in self.renewal["completed"] if item["pr"] == node.pr),
                None,
            )
            if saved is not None:
                self._verify_completed(node, saved)
                continue
            pr = prs[node.pr]
            children = [
                child
                for child in self.plan.children(node.pr)
                if child.selected and self.record.node(child.pr).fork is None
            ]
            if children:
                self._capture(pr, children)
                return True
            with self.store.mutation_lock():
                self._unchanged(pr)
                onto, base = self._destination(node)
                if self.git.resolve_ref(pr.head_sha) is None:
                    self._fetch_head(pr)
            row = self.record.node(node.pr)
            self._root_boundary(node, row.old_head or pr.head_sha)
            if not self.git.is_ancestor(onto, pr.head_sha):
                self._renew(node, pr, onto)
                return True
            if node.resolution is not None and row.promotion is None:
                raise graph._Stop(
                    "NEEDS_JUDGMENT",
                    f"#{node.pr} has extraneous resolution evidence without replay",
                    "start a new run with exact conflict evidence",
                )
            if pr.base_ref != base:
                if (
                    base != self.plan.trunk
                    or row.promotion is None
                    or not any(
                        intent.pr == node.pr
                        and intent.kind == "rewrite-push"
                        and intent.outcome == "CONFIRMED"
                        for intent in self.record.intents
                    )
                ):
                    raise graph._Stop(
                        "NEEDS_JUDGMENT",
                        f"#{node.pr} retarget requires its confirmed guarded renewal push",
                        "resolve the source-only base without widening authority",
                    )
                self._retarget(node, pr)
                return True
            self._advance_local(node)
            with self.store.mutation_lock():
                self._unchanged(pr)
                current, current_base = self._destination(node)
                if (onto, base) != (current, current_base):
                    raise graph._Stop(
                        "WAITING",
                        "renewal destination moved",
                        "resume from current facts",
                    )
                self.renewal["completed"].append(
                    {"pr": node.pr, "head": pr.head_sha, "base": base, "onto": onto}
                )
                self._save()
            return True
        return False

    def _verify_completed(self, node: graph.PlanNode, saved: RenewalCompletion) -> None:
        pr = self.prs[node.pr]
        onto, base = self._destination(node, fetch=False)
        if (pr.state, pr.head_sha, pr.base_ref, onto, base) != (
            "OPEN",
            saved["head"],
            saved["base"],
            saved["onto"],
            saved["base"],
        ):
            raise graph._Stop(
                "BLOCKED",
                f"saved source renewal no longer matches #{node.pr} head/base/parent",
                "start a new renewal from current facts",
            )
        if self.git.resolve_ref(onto) != onto or not self.git.is_ancestor(
            onto, pr.head_sha
        ):
            raise graph._Stop(
                "BLOCKED",
                f"saved source ancestry of #{node.pr} is unavailable or changed",
                "restore the exact objects before resuming",
            )
        remote = self._remote(pr.head_repo, pr.number)
        self._require_published(node, pr, remote)
        row = self.record.node(node.pr)
        self._root_boundary(node, row.old_head or pr.head_sha)
        if row.promotion is not None:
            proof = self._frozen(row, row.promotion.fork, row.promotion.old_head, onto)
            if proof is None or proof.new_head != pr.head_sha:
                raise graph._Stop(
                    "BLOCKED",
                    f"saved replay proof of #{node.pr} no longer verifies",
                    "restore the exact replay objects and evidence",
                )

    def _noop(self) -> tuple[dict[str, object], int]:
        evidence = self.renewal
        self._check(self.prs, graph._expected(self.plan, self.record), ())
        for saved in evidence["ancestors"]:
            pr = self.prs[saved["pr"]]
            tip = self.provider.base_tip(self.plan.trunk)
            if (
                (pr.state, pr.head_sha, pr.base_ref, pr.merge_commit_sha)
                != ("MERGED", saved["head"], saved["base"], saved["merge"])
                or self.git.resolve_ref(tip) != tip
                or not self.git.is_ancestor(saved["merge"], tip)
            ):
                raise graph._Stop(
                    "BLOCKED",
                    "external ancestor adoption no longer verifies",
                    "restore exact external landing evidence",
                )
        for node in self.plan.selected_nodes():
            completed = next(
                item for item in evidence["completed"] if item["pr"] == node.pr
            )
            self._verify_completed(node, completed)
        return self._finish("COMPLETE", None, "none", save=False)

    def _renew(self, node: graph.PlanNode, pr: PullRequest, onto: str) -> None:
        row = self.record.node(node.pr)
        remote = self._remote(pr.head_repo, pr.number)
        with self.store.mutation_lock():
            self._require_clean(node.pr, "pushed")
            self._unchanged(pr)
            self._require_room(2 if row.fork is None else 1)
            if row.fork is None:
                fork = (
                    node.fork
                    if node.fork is not None
                    else (
                        self.prs[node.parent].head_sha
                        if node.parent is not None
                        else None
                    )
                )
                if fork is None:
                    raise graph._Stop(
                        "NEEDS_JUDGMENT",
                        f"#{node.pr} requires an explicit source fork",
                        "provide the exact source slice boundary",
                    )
                self._require_fork(
                    node,
                    pr,
                    fork,
                    self.prs[node.parent] if node.parent is not None else pr,
                )
                self._record_capture(row, pr.head_sha, fork)
                self._save()
            fork = row.fork
            if fork is None:
                raise StateError("source renewal has no captured fork")
            if row.old_head != pr.head_sha:
                raise StateError("renewal head differs from the captured source slice")
            current, _ = self._destination(node)
            if current != onto:
                raise graph._Stop(
                    "WAITING", "renewal destination moved", "resume from current facts"
                )
            proof = self._frozen(row, fork, pr.head_sha, onto)
            if proof is None:
                proof = self._prove(node, fork, pr.head_sha, onto)
            self._require_published(node, pr, remote)
            row.promotion = Promotion(**asdict(proof), verified=True)
            row.state = "PROMOTED"
            self._save()
        self.local_validation[node.pr] = self._validate(onto, proof.new_head)
        with self.store.mutation_lock():
            self._require_clean(node.pr, "pushed")
            self._unchanged(pr)
            self._require_published(node, pr, remote)
            current, _ = self._destination(node)
            if current != onto:
                raise graph._Stop(
                    "WAITING",
                    "renewal destination moved during validation",
                    "resume to renew on the current destination",
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

    def _retarget_guard(self, node: graph.PlanNode, pr: PullRequest) -> None:
        self._guard_scope()
        onto, base = self._destination(node)
        row = self.record.node(node.pr)
        if (
            row.promotion is None
            or row.promotion.landing != onto
            or base != self.plan.trunk
        ):
            raise graph._Stop(
                "WAITING",
                "retarget destination no longer matches the guarded renewal",
                "resume from current facts",
            )

    def _result(
        self, status: Status, reason: str | None, next_action: str
    ) -> dict[str, object]:
        result = super()._result(status, reason, next_action)
        result["source_renewal"] = (
            self.journal.renewal if self.journal is not None else None
        )
        result["merge_readiness"] = "not evaluated: source-only renewal"
        return result

    def _merges(self) -> dict[int, dict[str, object]]:
        # External landings live only in renewal.ancestors, not this run's merges.
        return {}

    def _land(self, node: graph.PlanNode, pr: PullRequest) -> None:
        raise StateError("source renewal never lands pull requests")

    def _settle(self) -> bool:
        raise StateError("source renewal never cleans up refs")


def inspect_renewal(
    git: GitRepository,
    provider: GitHub,
    plan: graph.StackPlan,
    journal: GraphJournal | None,
    prs: Mapping[int, PullRequest],
) -> dict[str, object]:
    expected, reconciliations, pending = graph._projected(
        git, provider.host, plan, journal, prs
    )
    findings = list(pending)
    if any(_native_source(plan, prs[number]) for number in graph._scope(plan)):
        findings.append(
            graph.Finding(
                "BLOCKED",
                None,
                "native source renewal is unsupported",
                "retain the native stack unchanged",
            )
        )
    actions = list(reconciliations)
    for node in plan.order():
        if node.pr not in graph._scope(plan):
            continue
        pr = prs[node.pr]
        head, base = expected[node.pr]
        if (
            pr.head_sha,
            pr.base_ref,
            pr.head_ref,
            pr.head_repo.lower(),
            pr.base_repo.lower(),
        ) != (head, base, node.head_ref, node.head_repo.lower(), plan.repo.lower()):
            findings.append(
                graph.Finding(
                    "NEEDS_JUDGMENT", node.pr, "source identity changed", graph._REFRESH
                )
            )
        if node.selected:
            if pr.state != "OPEN":
                findings.append(
                    graph.Finding(
                        "BLOCKED",
                        node.pr,
                        "selected source renewal requires OPEN PR",
                        "refresh the scope",
                    )
                )
            if node.parent is None and node.fork is None:
                findings.append(
                    graph.Finding(
                        "NEEDS_JUDGMENT",
                        node.pr,
                        "root renewal requires an explicit fork",
                        "provide the exact source boundary",
                    )
                )
            action = (
                "reverify-source-renewal"
                if journal is not None and journal.status == "COMPLETE"
                else "renew-source"
            )
            actions.append(
                {
                    "action": action,
                    "pr": node.pr,
                    "parent": node.parent,
                    "head": head,
                    "base": base,
                    "resolution": node.resolution is not None,
                    "proof": "per-commit replay, local guards and gates evaluated at execution",
                }
            )
        else:
            if pr.state != "MERGED" or pr.merge_commit_sha is None:
                findings.append(
                    graph.Finding(
                        "NEEDS_JUDGMENT",
                        node.pr,
                        "unselected ancestor is not authoritatively MERGED",
                        "decide the source-only scope",
                    )
                )
            actions.append(
                {
                    "action": "adopt-external-ancestor",
                    "pr": node.pr,
                    "head": head,
                    "base": base,
                    "merge": pr.merge_commit_sha,
                    "proof": "exact identity and trunk reachability required at execution",
                }
            )
    return {
        "schema_version": 1,
        "status": "PLANNED",
        "target": {
            "kind": "stack",
            "host": plan.host,
            "repository": plan.repo,
            "trunk": plan.trunk,
            "endpoint": "renewed",
            "selected": [node.pr for node in plan.selected_nodes()],
        },
        "actions": actions,
        "findings": [asdict(item) for item in findings],
        "merge_readiness": "not evaluated: source-only renewal",
        "mutation_attempted": False,
        "mutation_confirmed": False,
    }
