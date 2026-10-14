"""Rubric-driven calibration over verified evidence.

The agent proposes competency scores; this module disposes. Scores lose
support they cannot cite, are capped by the rubric's evidence policy, and
never count self-reports toward a band. Levels come from declarative rubric
clauses evaluated three ways (conservative / normal / optimistic) to produce a
recommended level and an evidence-bounded plausible range. No arithmetic mean
is taken anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .evidence import SUPPORT_BLOCKED

CONF = ("low", "medium", "high")
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
NO_REASON_TEXT: dict[str | None, str] = {
    "no_opportunity": "can't be observed: no one else committed and no reviews of others' work were found",
    "no_evidence": "wasn't shown by anything inspected",
    "evidence_rejected": "has no evidence that survived verification",
    "insufficient_attribution": "has evidence that isn't attributable to the candidate",
    "access_limited": "couldn't be checked because review data was unavailable",
    "not_sampled": "wasn't reached by the sample",
    None: "rests only on the candidate's own account",
}


def _crank(c: str) -> int:
    return CONF.index(c)


def _cmin(*cs: str) -> str:
    return min(cs, key=_crank)


@dataclass
class Rated:
    id: str
    name: str
    group: str
    score: int | None
    status: str
    reason: str | None
    confidence: str
    proposed: int | None
    capped: bool
    support: list[dict[str, Any]] = field(default_factory=list)
    supporting_ids: list[str] = field(default_factory=list)
    counter_ids: list[str] = field(default_factory=list)
    self_report_ids: list[str] = field(default_factory=list)
    independent: int = 0
    adjustments: list[str] = field(default_factory=list)
    rationale: str = ""


class Calibrator:
    def __init__(
        self,
        rubric: dict[str, Any],
        forensics: dict[str, Any],
        register: dict[str, Any],
        judgments: dict[str, Any],
    ) -> None:
        self.rubric = rubric
        self.policy = rubric["evidence_policy"]
        self.forensics = forensics
        self.register = register
        self.judgments = judgments
        self.evidence = {e["id"]: e for e in register["evidence"]}
        self.rejected = {r["id"]: r["reasons"] for r in register["rejected"]}
        self.alias = {d["id"]: d["duplicate_of"] for d in register["duplicates"]}
        self.levels = rubric["levels"]
        self.level_ids = [lv["id"] for lv in self.levels]
        self.comp = {c["id"]: c for c in rubric["competencies"]}
        opp = [r["collaboration"]["opportunity"] for r in forensics["repositories"]]
        self.opportunity: bool | None = (
            True if True in opp else (None if None in opp else False)
        )
        self.notes: list[str] = []

    # ---- evidence predicates -------------------------------------------------

    def supports(self, e: dict[str, Any]) -> bool:
        return (
            e["status"] in {"verified", "downgraded"}
            and e["source"] in {"agent", "engine"}
            and e["candidate_attribution"] in self.policy["support_attribution"]
            and not any(a.startswith(SUPPORT_BLOCKED) for a in e["adjustments"])
        )

    def independent(self, e: dict[str, Any]) -> bool:
        """Counts toward high-score thresholds: attributable, not a weakness, not a repository's claim about itself."""
        return (
            self.supports(e)
            and e["candidate_attribution"] in self.policy["independent_attribution"]
            and e["polarity"] != "weakness"
            and e["verification"] != "repository_claimed"
        )

    @staticmethod
    def source_key(e: dict[str, Any]) -> tuple[Any, ...]:
        if e["path"]:
            return (e["repository"], "path", e["path"])
        if e["commit"]:
            return (e["repository"], "commit", e["commit"])
        return (e["repository"], "url", e["url"])

    @staticmethod
    def scope_key(e: dict[str, Any]) -> tuple[Any, ...]:
        return (e["repository"], e["subsystem"] or "(repository)")

    # ---- competency rating ---------------------------------------------------

    def rate(self) -> dict[str, Rated]:
        by_id = {j["id"]: j for j in self.judgments["competencies"]}
        unknown_ids = sorted(set(by_id) - set(self.comp))
        if unknown_ids:
            self.notes.append(
                f"Ignored ratings for competencies not in the rubric: {', '.join(unknown_ids)}"
            )
        self_reports = [
            e for e in self.evidence.values() if e["source"] == "self_report"
        ]
        return {
            cid: self._rate_one(c, by_id.get(cid), self_reports)
            for cid, c in self.comp.items()
        }

    def _no_reason(self, c: dict[str, Any], hint: str | None) -> str:
        if c["requires_opportunity"] == "collaborators":
            if self.opportunity is False:
                return "no_opportunity"
            if self.opportunity is None:
                return "access_limited"
        return hint or "no_evidence"

    def _rate_one(
        self,
        c: dict[str, Any],
        j: dict[str, Any] | None,
        self_reports: list[dict[str, Any]],
    ) -> Rated:
        sr_ids = [e["id"] for e in self_reports if c["id"] in e["competencies"]]
        rated = Rated(
            c["id"],
            c["name"],
            c["group"],
            None,
            "not_observable",
            None,
            "low",
            None,
            False,
            self_report_ids=sr_ids,
        )
        if j is None:
            rated.reason = self._no_reason(c, None)
            return rated
        rated.proposed = j["score"]
        rated.rationale = j["rationale"]
        # A citation of a merged duplicate counts as its canonical item, once.
        rated.supporting_ids = list(
            dict.fromkeys(self.alias.get(i, i) for i in j["supporting_evidence_ids"])
        )
        rated.counter_ids = list(
            dict.fromkeys(self.alias.get(i, i) for i in j["counterevidence_ids"])
        )
        for eid in rated.supporting_ids + rated.counter_ids:
            if eid not in self.evidence:
                why = "; ".join(
                    self.rejected.get(eid, ["not in the evidence register"])
                )
                rated.adjustments.append(f"cited {eid} dropped: {why}")
        if j["score"] is None:
            rated.reason = self._no_reason(c, j.get("not_observable_reason"))
            return rated

        cited = [
            self.evidence[i]
            for i in dict.fromkeys(rated.supporting_ids + rated.counter_ids)
            if i in self.evidence
        ]
        usable = [e for e in cited if self.supports(e)]
        for e in cited:
            if e not in usable:
                rated.adjustments.append(
                    f"{e['id']} cannot support a score (attribution {e['candidate_attribution']}, status {e['status']})"
                )
        if not usable:
            if sr_ids:
                cap = self.policy["self_report_score_cap"]
                rated.score = min(j["score"], cap)
                rated.status = "self_reported"
                rated.adjustments.append(
                    f"only self-report supports this competency; score capped at {cap} and excluded from level bands"
                )
                return rated
            insufficient = any(
                e["candidate_attribution"] not in self.policy["support_attribution"]
                for e in cited
            )
            if insufficient:
                rated.reason = "insufficient_attribution"
            elif rated.supporting_ids or rated.counter_ids:
                rated.reason = "evidence_rejected"
            else:
                rated.reason = self._no_reason(c, None)
            rated.adjustments.append(
                f"proposed score {j['score']} withdrawn: no verified, attributable evidence"
            )
            return rated

        score: int = j["score"]
        weakness = [
            e
            for e in usable
            if e["polarity"] == "weakness"
            and e["verification"] in {"directly_inspected", "executed"}
        ]
        if (
            score == 0
            and self.policy["zero_requires_verified_weakness"]
            and not weakness
        ):
            rated.reason = "no_evidence"
            rated.adjustments.append(
                "score 0 requires a directly verified deficiency; none cited, so the competency is not observable rather than zero"
            )
            return rated
        strength = [e for e in usable if self.independent(e)]
        rated.support = usable
        rated.independent = len({self.source_key(e) for e in strength})
        scopes = len({self.scope_key(e) for e in strength})
        for threshold in sorted(
            (int(k) for k in self.policy["independent_sources_for_score"]), reverse=True
        ):
            need = self.policy["independent_sources_for_score"][str(threshold)]
            if score >= threshold and rated.independent < need:
                rated.adjustments.append(
                    f"score {score} needs {need} independent attributable sources for {threshold}; found {rated.independent}; capped at {threshold - 1}"
                )
                score, rated.capped = threshold - 1, True
        for threshold in sorted(
            (int(k) for k in self.policy["distinct_scopes_for_score"]), reverse=True
        ):
            need = self.policy["distinct_scopes_for_score"][str(threshold)]
            if score >= threshold and scopes < need:
                rated.adjustments.append(
                    f"score {threshold} needs evidence across {need} distinct subsystems or repositories; found {scopes}; capped at {threshold - 1}"
                )
                score, rated.capped = threshold - 1, True
        review_from = self.policy["counterevidence_review_from_score"]
        if score >= review_from and not j["counterevidence_reviewed"]:
            rated.adjustments.append(
                f"scores of {review_from}+ require an explicit counterevidence review; capped at {review_from - 1}"
            )
            score, rated.capped = review_from - 1, True

        attributions = {e["candidate_attribution"] for e in usable}
        inspected = any(
            e["verification"] in {"directly_inspected", "executed"} for e in usable
        )
        if (
            rated.independent >= 3
            and attributions <= {"verified", "probable"}
            and inspected
        ):
            computed = "high"
        elif rated.independent >= 2 or (
            rated.independent >= 1 and "verified" in attributions
        ):
            computed = "medium"
        else:
            computed = "low"
        rated.confidence = _cmin(j["confidence"], computed)
        if rated.confidence != j["confidence"]:
            rated.adjustments.append(
                f"confidence {j['confidence']} lowered to {rated.confidence} by evidence breadth"
            )
        rated.score = score
        rated.status = "observed"
        return rated

    # ---- level rules ---------------------------------------------------------

    def _members(self, selector: Any) -> list[str]:
        if isinstance(selector, str):
            group = selector.split(":", 1)[1]
            return [cid for cid, c in self.comp.items() if c["group"] == group]
        return [cid for cid in selector if cid in self.comp]

    def _view(
        self, rated: dict[str, Rated], mode: str
    ) -> dict[str, tuple[int | None, str]]:
        view: dict[str, tuple[int | None, str]] = {}
        for cid, r in rated.items():
            if r.status != "observed" or r.score is None:
                view[cid] = (None, "low")
            elif mode == "conservative":
                view[cid] = (
                    max(0, r.score - 1) if r.confidence == "low" else r.score,
                    r.confidence,
                )
            elif mode.startswith("optimistic"):
                # "optimistic": low-confidence or capped scores may sit one anchor higher.
                # "optimistic_medium": medium-confidence scores too; callers limit its reach to one level.
                bump = (
                    r.capped
                    or r.confidence == "low"
                    or (mode == "optimistic_medium" and r.confidence == "medium")
                )
                view[cid] = (min(5, r.score + 1) if bump else r.score, "high")
            else:
                view[cid] = (r.score, r.confidence)
        return view

    def clause(
        self,
        cl: dict[str, Any],
        view: dict[str, tuple[int | None, str]],
        rated: dict[str, Rated],
        mode: str,
    ) -> tuple[str, str, str, list[str]]:
        kind = cl["type"]
        if kind == "evidence_kind":
            n = sum(
                1
                for e in self.evidence.values()
                if e["kind"] in cl["kinds"]
                and e["verification"] in cl["verification"]
                and self.supports(e)
            )
            label = f"≥{cl['n']} verified {'/'.join(cl['kinds'])} evidence"
            return label, (PASS if n >= cl["n"] else FAIL), f"found {n}", []
        members = self._members(cl["of"])
        of_label = cl["of"] if isinstance(cl["of"], str) else ", ".join(members)
        if kind == "at_least":
            min_conf = (
                cl.get("min_confidence") if not mode.startswith("optimistic") else None
            )
            hits = [
                m
                for m in members
                if view[m][0] is not None
                and view[m][0] >= cl["score"]
                and (min_conf is None or _crank(view[m][1]) >= _crank(min_conf))
            ]
            unknown = [m for m in members if view[m][0] is None]
            label = f"≥{cl['n']} of [{of_label}] at score ≥{cl['score']}" + (
                f" with {cl['min_confidence']}+ confidence"
                if cl.get("min_confidence")
                else ""
            )
            if len(hits) >= cl["n"]:
                outcome = PASS
            elif len(hits) + len(unknown) >= cl["n"]:
                outcome = UNKNOWN
            else:
                outcome = FAIL
            detail = (
                f"met by {', '.join(f'{m}={view[m][0]}' for m in hits) or 'none'}"
                + (
                    f"; not observable: {', '.join(unknown)}"
                    if unknown and outcome != PASS
                    else ""
                )
            )
            return label, outcome, detail, hits
        if kind == "none_below":
            low = [
                m
                for m in members
                if view[m][0] is not None and view[m][0] < cl["score"]
            ]
            label = f"no observed [{of_label}] below {cl['score']}"
            return (
                label,
                (FAIL if low else PASS),
                (
                    f"below: {', '.join(f'{m}={view[m][0]}' for m in low)}"
                    if low
                    else "no observed score below threshold"
                ),
                low,
            )
        support = [
            e
            for m in members
            if view[m][0] is not None
            for e in rated[m].support
            if self.independent(e)
        ]
        if kind == "min_distinct_scopes":
            keys = {self.scope_key(e) for e in support}
            label = f"evidence for [{of_label}] spans ≥{cl['n']} subsystems"
        else:
            keys = {(e["repository"],) for e in support}
            label = f"evidence for [{of_label}] spans ≥{cl['n']} repositories"
        return (
            label,
            (PASS if len(keys) >= cl["n"] else FAIL),
            f"found {len(keys)}",
            members,
        )

    def band(
        self, band: str, rated: dict[str, Rated], mode: str
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return (index of highest consecutive passing level or -1, trace for every level)."""
        view = self._view(rated, mode)
        trace: list[dict[str, Any]] = []
        best = -1
        still = True
        for i, lv in enumerate(self.levels):
            clauses = [self.clause(cl, view, rated, mode) for cl in lv[band]]
            outcomes = [o for _, o, _, _ in clauses]
            outcome = (
                FAIL if FAIL in outcomes else (UNKNOWN if UNKNOWN in outcomes else PASS)
            )
            passed = outcome == PASS or (
                mode.startswith("optimistic") and outcome == UNKNOWN
            )
            if still and passed:
                best = i
            else:
                still = False
            trace.append(
                {
                    "level": lv["id"],
                    "band": band,
                    "outcome": outcome,
                    "clauses": [
                        {
                            "clause": lab,
                            "outcome": o,
                            "detail": d,
                            "explanation": self.explain(definition, rated, lv["label"])
                            if mode == "normal"
                            else "",
                            "competencies": comps,
                        }
                        for definition, (lab, o, d, comps) in zip(
                            lv[band], clauses, strict=True
                        )
                    ],
                }
            )
        return best, trace

    def overall(self, rated: dict[str, Rated], mode: str) -> int:
        tech, _ = self.band("technical", rated, mode)
        scope, _ = self.band("scope", rated, mode)
        best = -1
        for i, lv in enumerate(self.levels):
            if i > tech:
                break
            if lv["requires_scope"] and i > scope:
                break
            best = i
        return best

    def scope_members(self) -> set[str]:
        members: set[str] = set()
        for lv in self.levels:
            for cl in lv["scope"]:
                if "of" in cl:
                    members |= set(self._members(cl["of"]))
        return members

    # ---- result --------------------------------------------------------------

    def calibrate(self, target_level: str | None) -> dict[str, Any]:
        rated = self.rate()
        tech, tech_trace = self.band("technical", rated, "normal")
        scope, scope_trace = self.band("scope", rated, "normal")
        status = self.scope_status(rated)
        rec = self.overall(rated, "normal")
        lower = self.overall(rated, "conservative")
        medium_reach = min(self.overall(rated, "optimistic_medium"), rec + 1)
        upper = max(self.overall(rated, "optimistic"), medium_reach, rec)
        lower = min(lower, rec)

        supporting = {
            e["id"]
            for r in rated.values()
            if r.status == "observed"
            for e in r.support
            if e["polarity"] != "weakness"
        }
        observed = {cid for cid, r in rated.items() if r.status == "observed"}
        inconclusive: list[str] = []
        for cl in self.rubric["inconclusive_when"]:
            if cl["type"] == "observed_below":
                n = len(observed & set(self._members(cl["of"])))
                if n < cl["n"]:
                    inconclusive.append(
                        f"only {n} competencies in {cl['of']} are observable (minimum {cl['n']})"
                    )
            elif cl["type"] == "supporting_evidence_below":
                if len(supporting) < cl["n"]:
                    inconclusive.append(
                        f"only {len(supporting)} verified, attributable supporting evidence items (minimum {cl['n']})"
                    )
            elif cl["type"] == "attributable_repositories_below":
                n = sum(
                    1
                    for r in self.forensics["repositories"]
                    if r["attribution"]["role"] not in {"none", "unknown"}
                )
                if n < cl["n"]:
                    inconclusive.append(
                        f"no analysed repository contains attributable candidate work (found {n})"
                    )
        if rec < 0 and not inconclusive:
            inconclusive.append(
                "no level's technical requirements are met by verified evidence"
            )

        level_of = self._level_id
        recommended = "inconclusive" if inconclusive else level_of(rec)
        lower_id, upper_id = level_of(lower), level_of(upper)
        plausible = self.level_ids[max(lower, 0) : upper + 1] if upper >= 0 else []

        factors = self._confidence(supporting, observed, lower, upper)
        confidence = "low" if inconclusive else factors["overall"]
        blockers = (
            self._blockers(rec + 1, tech_trace, scope_trace)
            if rec + 1 < len(self.levels)
            else []
        )
        determination = self._determination(rec, blockers, inconclusive)
        target = None
        if target_level:
            t = self.level_ids.index(target_level)
            if inconclusive:
                outcome = "inconclusive"
            else:
                outcome = "meets" if rec == t else ("above" if rec > t else "below")
            target = {
                "target_level": target_level,
                "outcome": outcome,
                "blockers": self._blockers(t, tech_trace, scope_trace)
                if rec < t or inconclusive
                else [],
            }
        return {
            "rated": rated,
            "result": {
                "recommended_level": recommended,
                "technical_capability_level": level_of(tech),
                "scope_influence_level": level_of(scope)
                if status[0] != "not_observable"
                else None,
                "scope_influence_status": status[0],
                "plausible_levels": plausible,
                "plausible_range": {"lower": lower_id, "upper": upper_id},
                "confidence": confidence,
                "confidence_factors": {
                    k: v for k, v in factors.items() if k != "overall"
                },
                "inconclusive_reasons": inconclusive,
                "determination": determination,
                "decision_trace": tech_trace + scope_trace,
                "next_level_blockers": blockers,
                "target_level_comparison": target,
            },
        }

    def _level_id(self, index: int) -> str | None:
        return self.level_ids[index] if index >= 0 else None

    def _blockers(
        self,
        index: int,
        tech_trace: list[dict[str, Any]],
        scope_trace: list[dict[str, Any]],
    ) -> list[str]:
        """Plain-language reasons a level is not reached (failed or unresolved requirements)."""
        lv = self.levels[index]
        traces = [tech_trace[index]] + (
            [scope_trace[index]] if lv["requires_scope"] else []
        )
        return [
            cl["explanation"]
            for t in traces
            for cl in t["clauses"]
            if cl["outcome"] != PASS
        ]

    def scope_status(self, rated: dict[str, Rated]) -> tuple[str, list[str], list[str]]:
        """observed: an influence competency is observed; partial: only other scope inputs (e.g. ownership) are."""
        members = self.scope_members()
        observed = sorted(m for m in members if rated[m].status == "observed")
        influence = sorted(m for m in members if self.comp[m]["group"] == "influence")
        if not observed:
            return "not_observable", observed, influence
        if influence and not set(observed) & set(influence):
            return "partial", observed, influence
        return "observed", observed, influence

    def _determination(
        self, rec: int, blockers: list[str], inconclusive: list[str]
    ) -> str:
        if inconclusive:
            return "No level can be recommended yet: " + "; ".join(inconclusive) + "."
        label = self.levels[rec]["label"]
        text = f"{label}. Every {label} requirement is met by verified, attributable evidence."
        if rec + 1 < len(self.levels) and blockers:
            nxt = self.levels[rec + 1]["label"]
            text += f" {nxt} is not reached: " + " ".join(blockers)
        return text

    # ---- plain-language explanations -----------------------------------------------

    def _name(self, cid: str) -> str:
        return str(self.comp[cid]["name"]).lower()

    def _state(self, cid: str, rated: dict[str, Rated]) -> str:
        r = rated[cid]
        if r.status == "observed" and r.score is not None:
            return f"{self._name(cid)} is {r.score} ({r.confidence} confidence)"
        return f"{self._name(cid)} {NO_REASON_TEXT.get(r.reason if r.status == 'not_observable' else None)}"

    def explain(self, cl: dict[str, Any], rated: dict[str, Rated], level: str) -> str:
        kind = cl["type"]
        if kind == "evidence_kind":
            found = sum(
                1
                for e in self.evidence.values()
                if e["kind"] in cl["kinds"]
                and e["verification"] in cl["verification"]
                and self.supports(e)
            )
            return f"{level} needs {cl['n']} verified external corroborations (such as recognition outside these repositories); {found} found."
        members = self._members(cl["of"])
        observed = [
            m
            for m in members
            if rated[m].status == "observed" and rated[m].score is not None
        ]
        if kind == "at_least":
            need = f"{cl['score']} or more" + (
                f" with at least {cl['min_confidence']} confidence"
                if cl.get("min_confidence")
                else ""
            )
            if len(members) == 1:
                state = self._state(members[0], rated)
                return f"{state[0].upper()}{state[1:]}; {level} needs {need}."
            if isinstance(cl["of"], str):
                group = cl["of"].split(":", 1)[1]
                hits = [m for m in observed if (rated[m].score or 0) >= cl["score"]]
                tail = (
                    f" with at least {cl['min_confidence']} confidence."
                    if cl.get("min_confidence")
                    else "."
                )
                return f"{len(hits)} of the {len(members)} {group} competencies score {cl['score']} or more; {level} needs {cl['n']}{tail}"
            names = (
                " or ".join(self._name(m) for m in members)
                if cl["n"] == 1
                else ", ".join(self._name(m) for m in members)
            )
            want = f"one of {names}" if cl["n"] == 1 else f"{cl['n']} of {names}"
            return (
                f"{level} needs {want} at {need}. Currently "
                + "; ".join(self._state(m, rated) for m in members)
                + "."
            )
        if kind == "none_below":
            low = [m for m in observed if (rated[m].score or 0) < cl["score"]]
            scope = (
                "technical competency"
                if isinstance(cl["of"], str)
                else " / ".join(self._name(m) for m in members)
            )
            if low:
                return (
                    f"{level} allows no {scope} below {cl['score']}; "
                    + ", ".join(self._state(m, rated) for m in low)
                    + "."
                )
            return f"No observed {scope} score is below {cl['score']}."
        support = [e for m in observed for e in rated[m].support if self.independent(e)]
        if kind == "min_distinct_scopes":
            found = len({self.scope_key(e) for e in support})
            return f"Independent evidence for {', '.join(self._name(m) for m in members)} spans {found} subsystems; {level} needs {cl['n']}."
        found = len({e["repository"] for e in support})
        return f"Independent evidence spans {found} repositor{'y' if found == 1 else 'ies'}; {level} needs {cl['n']}, showing the work across more than one system."

    def _confidence(
        self, supporting: set[str], observed: set[str], lower: int, upper: int
    ) -> dict[str, Any]:
        pol = self.rubric["confidence_policy"]
        repos = self.forensics["repositories"]
        contributing = {
            self.evidence[i]["repository"]
            for i in supporting
            if self.evidence[i]["repository"]
        }
        attr_levels = [
            r["attribution"]["attribution_confidence"]
            for r in repos
            if r["repo_id"] in contributing
        ] or [r["attribution"]["attribution_confidence"] for r in repos]
        attribution = _cmin(*attr_levels)
        n_sup, n_obs = len(supporting), len(observed)
        if (
            n_sup >= pol["evidence"]["high"]["min_supporting_evidence"]
            and n_obs >= pol["evidence"]["high"]["min_observed"]
        ):
            evidence = "high"
        elif (
            n_sup >= pol["evidence"]["medium"]["min_supporting_evidence"]
            and n_obs >= pol["evidence"]["medium"]["min_observed"]
        ):
            evidence = "medium"
        else:
            evidence = "low"
        cov_rows = [
            c
            for c in self.register["coverage"]["repositories"]
            if c["sample_items"] > 0
        ]
        mean_cov = (
            sum(c["sample_coverage"] for c in cov_rows) / len(cov_rows)
            if cov_rows
            else 0.0
        )
        coverage = (
            "high"
            if mean_cov >= pol["coverage"]["high"]
            else ("medium" if mean_cov >= pol["coverage"]["medium"] else "low")
        )
        width = max(0, upper - max(lower, -1)) if upper >= 0 else 0
        base = _cmin(attribution, evidence, coverage)
        overall = base
        for key in sorted(pol["range_width_caps"], key=int):
            if width >= int(key):
                overall = _cmin(overall, pol["range_width_caps"][key])
        if width == 0:
            settled = "the level is settled (the plausible range is a single level)"
        else:
            span = (
                f"{self._level_label(lower)} to {self._level_label(upper)}"
                if lower >= 0
                else f"up to {self._level_label(upper)}"
            )
            settled = f"the level is not settled: the evidence allows {span}"
        why = (
            f"Overall confidence is {overall}. It is the weakest of four checks: attribution is {attribution}, evidence is {evidence}, "
            f"sample coverage is {coverage}, and {settled}."
        )
        if overall != base:
            why += f" An unsettled level caps confidence at {overall} even when the other three checks are {base}."
        notes = [
            why,
            f"{n_sup} supporting evidence items across {n_obs} observed competencies; mean sample coverage {mean_cov:.1%}.",
        ]
        return {
            "attribution": attribution,
            "evidence": evidence,
            "coverage": coverage,
            "range_width": width,
            "notes": notes + self.notes,
            "overall": overall,
        }

    def _level_label(self, index: int) -> str:
        return str(self.levels[index]["label"]) if index >= 0 else "no level"
