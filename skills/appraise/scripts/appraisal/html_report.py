"""Self-contained HTML report rendered from assessment.json, evidence.json and forensics.json.

One file, no network: no external fonts, stylesheets, scripts or images. Every
repository- or agent-supplied string is HTML-escaped; links are emitted only
for http(s) URLs. The tiny inline script only filters the evidence table by
toggling `hidden` on existing rows (no HTML injection). Output is
deterministic for identical inputs.
"""

from __future__ import annotations

import html
import re
from typing import Any

from .calibration import NO_REASON_TEXT

_ID = r"E-\d{3,}|H-R\d+-\d{3,}|SR-\d{2,}"
LIMITATION_TITLES = {
    "ai_assistance_undeclared": "AI assistance isn't declared",
    "ai_assisted_commits": "Some commits declare AI assistance",
    "no_collaboration_opportunity": "No chance to show collaboration here",
    "collaboration_unassessed": "Collaboration couldn't be checked",
    "candidate_line_coverage_low": "Only a small share of the candidate's code was read",
    "low_sample_coverage": "Less than half of the planned sample was read",
    "inspection_self_declared": "Some reading wasn't done through the audit log",
    "host_metadata_unavailable": "GitHub data wasn't available",
    "possible_undeclared_upstream": "The project may have started from another repository",
    "upstream_unavailable": "The upstream repository couldn't be fetched",
    "shallow_history": "History is incomplete (shallow clone)",
    "bulk_import_suspected": "Large imported commits weaken attribution",
    "evaluator_directed_text": "The repository contains text aimed at evaluators",
    "evidence_rejected": "Some cited evidence failed verification",
    "finding_dropped": "A finding was dropped for lack of evidence",
    "uncommitted_changes_excluded": "Uncommitted changes were ignored",
    "quick_depth": "Quick depth: a shallow look",
    "blame_budget_reached": "Line ownership is estimated",
}
NO_REASON_SHORT: dict[str | None, str] = {
    "no_opportunity": "no other contributors or reviews to show it",
    "no_evidence": "not shown in what was read",
    "evidence_rejected": "cited evidence failed verification",
    "insufficient_attribution": "evidence isn't the candidate's",
    "access_limited": "review data unavailable",
    "not_sampled": "outside the sample",
}

CONF_RANK = {"low": 1, "medium": 2, "high": 3}
OUTCOME_CLASS = {"pass": "ok", "fail": "bad", "unknown": "warn"}
MODE_TITLES = {
    "review": "Candidate review",
    "self": "Self-appraisal",
    "promotion": "Promotion evidence pack",
    "manager": "Development appraisal",
}
QUESTION_TITLES = {
    "review": "Interview questions",
    "self": "Self-reflection prompts",
    "promotion": "Questions a promotion panel is likely to ask",
    "manager": "Conversation prompts",
}
ATTRIBUTION_CLASS = {
    "verified": "ok",
    "probable": "ok",
    "possible": "warn",
    "unlikely": "bad",
    "inherited": "bad",
    "unknown": "void",
    "self_reported": "warn",
    "not_applicable": "void",
}
STATUS_CLASS = {"verified": "ok", "downgraded": "warn", "unverified": "void"}


def e(value: Any) -> str:
    return html.escape("—" if value is None else str(value), quote=True)


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    if 0.995 <= value < 1 or 0 < value < 0.005:
        return f"{value:.2%}"
    if value < 0.1:
        return f"{value:.1%}"
    return f"{value:.0%}"


def _link(url: str | None, text: str) -> str:
    if url and url.startswith(("https://", "http://")):
        return f'<a href="{e(url)}" rel="noreferrer">{text}</a>'
    return text


def _chip(text: str, cls: str) -> str:
    return f'<span class="chip {cls}">{e(text)}</span>'


def _ev_refs(ids: list[str], known: set[str]) -> str:
    if not ids:
        return '<span class="none">none</span>'
    return " ".join(
        f'<a class="ref" href="#ev-{e(i)}">{e(i)}</a>'
        if i in known
        else f'<span class="ref dead">{e(i)}</span>'
        for i in ids
    )


class Report:
    def __init__(
        self,
        a: dict[str, Any],
        evidence: dict[str, Any],
        forensics: dict[str, Any],
        rubric: dict[str, Any],
    ) -> None:
        self.a = a
        self.ev = evidence
        self.f = forensics
        self.rubric = rubric
        self.levels = rubric["levels"]
        self.label = {lv["id"]: lv["label"] for lv in self.levels}
        self.label["inconclusive"] = "Inconclusive"
        self.known = {x["id"] for x in evidence["evidence"]}
        self.by_id = {x["id"]: x for x in evidence["evidence"]}
        self.sections: list[tuple[str, str]] = []

    def lab(self, level: str | None) -> str:
        return "not observable" if level is None else self.label.get(level, level)

    # ---- page --------------------------------------------------------------

    def render(self) -> str:
        a = self.a
        body = [
            self._masthead(),
            self._section("basis", "What this rests on", self._basis()),
            self._section("result", "Result", self._result()),
        ]
        if a["mode"] == "promotion" and a["result"]["target_level_comparison"]:
            body.append(
                self._section("promotion", "Promotion evidence pack", self._promotion())
            )
        if a["mode"] in {"self", "manager", "promotion"}:
            body.append(self._section("plan", "Development plan", self._plan()))
        body.append(self._section("competencies", "Competencies", self._competencies()))
        body.append(self._section("trace", "How the level was decided", self._trace()))
        body.append(
            self._section(
                "findings", "Strengths, weaknesses and risks", self._findings()
            )
        )
        if a["mode"] == "review":
            body.append(self._section("plan", "Development plan", self._plan()))
        body.append(
            self._section("questions", QUESTION_TITLES[a["mode"]], self._questions())
        )
        body.append(self._section("evidence", "Evidence register", self._evidence()))
        body.append(
            self._section("repositories", "Repository forensics", self._repositories())
        )
        if a["self_reports"] or a["contested_evidence"] or a["changes"]:
            body.append(
                self._section(
                    "revisions", "Answers, disputes and changes", self._revisions()
                )
            )
        body.append(
            self._section("contest", "How to contest this appraisal", self._contest())
        )
        nav = "".join(
            f'<li><a href="#{sid}">{e(title)}</a></li>' for sid, title in self.sections
        )
        title = f"{MODE_TITLES[a['mode']]}: {a['subject']['candidate_id']}"
        return (
            "<!doctype html>\n"
            '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:\">\n"
            f"<title>{e(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
            '<a class="skip" href="#main">Skip to report</a>\n'
            f'<div class="layout">\n<nav class="toc" aria-label="Report sections"><p class="toc-title">{e(a["subject"]["candidate_id"])}</p><ol>{nav}</ol></nav>\n'
            f'<main id="main">\n{"".join(body)}\n{self._footer()}\n</main>\n</div>\n'
            f"<script>{SCRIPT}</script>\n</body>\n</html>\n"
        )

    def _section(self, sid: str, title: str, inner: str) -> str:
        if sid not in {s for s, _ in self.sections}:
            self.sections.append((sid, title))
        return f'<section id="{sid}" aria-labelledby="{sid}-h"><h2 id="{sid}-h">{e(title)}</h2>{inner}</section>\n'

    # ---- masthead ----------------------------------------------------------

    def _masthead(self) -> str:
        a = self.a
        s = a["subject"]
        notes = []
        if a["mode"] == "manager":
            notes.append(
                "Prepared with the subject informed. Share it in full; any evidence item can be contested and must trigger a recalculation."
            )
        if a["mode"] == "self":
            notes.append(
                "Your identity was resolved from your own accounts, not from repository ownership. The development plan is the main output; the level is context."
            )
        notes.append(
            "Levels are generic capability anchors from the rubric, not an organization's official title and not a hiring decision."
        )
        repos = ", ".join(r["locator"] for r in a["repositories"])
        spec = f" ({e(s['specialization'])})" if s["specialization"] else ""
        return (
            '<header class="masthead">'
            f'<p class="kind">{e(MODE_TITLES[a["mode"]])}{spec}</p>'
            f"<h1>{e(s['candidate_id'])}</h1>"
            f'<p class="lede">Appraised from {len(a["repositories"])} {"repository" if len(a["repositories"]) == 1 else "repositories"}: {e(repos)}</p>'
            '<dl class="facts">'
            f"<div><dt>Identity</dt><dd>{'verified' if s['identity_verified'] else 'not fully verified'} ({e(', '.join(s['identity_basis']) or 'none')})</dd></div>"
            f"<div><dt>Rubric</dt><dd>{e(a['provenance']['rubric_id'])} {e(a['provenance']['rubric_version'])}</dd></div>"
            f"<div><dt>Generated</dt><dd>{e(a['generated_at'])}</dd></div>"
            f"<div><dt>Assessment</dt><dd><code>{e(a['assessment_id'][:16])}</code></dd></div>"
            "</dl>"
            + "".join(f'<p class="notice">{e(n)}</p>' for n in notes)
            + "</header>\n"
        )

    # ---- basis ------------------------------------------------------------

    def _basis(self) -> str:
        a = self.a
        rows = []
        for r in a["repositories"]:
            lineage = (
                "original, no declared upstream"
                if r["relationship"] == "none"
                else f"{r['relationship']}, {r['ancestry']}, delta {r['upstream_diff_status']}"
            )
            rows.append(
                "<tr>"
                f'<th scope="row">{e(r["repo_id"])}</th>'
                f"<td>{_link(r['locator'], e(r['locator']))}<br><code>{e(r['revision'][:12])}</code></td>"
                f"<td>{e(r['candidate_role'].replace('_', ' '))}</td>"
                f'<td class="num">{_pct(r["candidate_surviving_share"])}</td>'
                f"<td>{_chip(r['attribution_confidence'], {'high': 'ok', 'medium': 'warn', 'low': 'bad'}[r['attribution_confidence']])}</td>"
                f"<td>{e(lineage)}</td>"
                f'<td class="num">{_pct(r["sample_coverage"])}</td>'
                "</tr>"
            )
        table = (
            '<div class="scroll"><table><caption>Pinned revisions and what is attributable to the candidate</caption>'
            '<thead><tr><th scope="col">Repo</th><th scope="col">Source and revision</th><th scope="col">Role</th>'
            '<th scope="col">Surviving lines</th><th scope="col">Attribution</th><th scope="col">Lineage</th><th scope="col">Sample read</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
        lims = (
            "".join(
                f'<li><span class="code-label">{e(LIMITATION_TITLES.get(lim["code"], lim["code"].replace("_", " ").capitalize()))}</span> <span class="impact">{e(lim["impact"])}{" in " + e(lim["repo"]) if lim["repo"] else ""}</span><p>{e(lim["message"])}</p></li>'
                for lim in a["limitations"]
            )
            or "<li>No limitations recorded.</li>"
        )
        return (
            table
            + f'<h3>Limitations to weigh before the result</h3><ul class="limits">{lims}</ul>'
        )

    # ---- result -----------------------------------------------------------

    def _scale(self) -> str:
        r = self.a["result"]
        ids = [lv["id"] for lv in self.levels]
        n = len(ids)
        w, left, right = 960, 80, 80
        step = (w - left - right) / max(1, n - 1)

        def x(level: str | None) -> float | None:
            return left + ids.index(level) * step if level in ids else None

        parts = [
            f'<svg class="scale" viewBox="0 0 {w} 190" role="img" aria-labelledby="scale-t scale-d">'
        ]
        parts.append('<title id="scale-t">Level scale</title>')
        desc = (
            f"Recommended {self.lab(r['recommended_level'])}; technical capability {self.lab(r['technical_capability_level'])}; "
            f"scope and influence {self.lab(r['scope_influence_level'])} ({r['scope_influence_status']}); plausible range "
            f"{self.lab(r['plausible_range']['lower'])} to {self.lab(r['plausible_range']['upper'])}."
        )
        parts.append(f'<desc id="scale-d">{e(desc)}</desc>')
        lo, hi = x(r["plausible_range"]["lower"]), x(r["plausible_range"]["upper"])
        if hi is not None:
            lo_x = lo if lo is not None else left
            parts.append(
                f'<rect class="range" x="{lo_x - 24:.1f}" y="77" width="{hi - lo_x + 48:.1f}" height="36" rx="18"/>'
            )
        parts.append(
            f'<line class="axis" x1="{left}" y1="95" x2="{w - right}" y2="95"/>'
        )
        for i, lid in enumerate(ids):
            cx = left + i * step
            parts.append(
                f'<line class="tick" x1="{cx:.1f}" y1="87" x2="{cx:.1f}" y2="103"/>'
            )
            parts.append(
                f'<text class="level" x="{cx:.1f}" y="160" text-anchor="middle">{e(self.label[lid])}</text>'
            )
        tx = x(r["technical_capability_level"])
        if tx is not None:
            parts.append(f'<path class="mark-tech" d="M{tx:.1f},72 l-10,-18 h20 z"/>')
        sx = x(r["scope_influence_level"])
        if sx is not None:
            cls = (
                "mark-scope partial"
                if r["scope_influence_status"] == "partial"
                else "mark-scope"
            )
            parts.append(f'<path class="{cls}" d="M{sx:.1f},118 l-10,18 h20 z"/>')
        rx = x(r["recommended_level"])
        if rx is not None:
            parts.append(f'<circle class="mark-rec" cx="{rx:.1f}" cy="95" r="13"/>')
        parts.append("</svg>")
        partial = r["scope_influence_status"] == "partial"

        def glyph(shape: str) -> str:
            return f'<svg class="scale" viewBox="0 0 28 18" width="28" height="18" aria-hidden="true">{shape}</svg>'

        scope_cls = "mark-scope partial" if partial else "mark-scope"
        items = []
        if rx is not None:
            items.append(
                (
                    glyph('<circle class="mark-rec" cx="14" cy="9" r="7"/>'),
                    "recommended",
                )
            )
        if tx is not None:
            items.append(
                (
                    glyph('<path class="mark-tech" d="M14,16l-7,-12h14z"/>'),
                    "technical capability",
                )
            )
        if sx is not None:
            items.append(
                (
                    glyph(f'<path class="{scope_cls}" d="M14,3l-7,12h14z"/>'),
                    "scope and influence" + (" (partial)" if partial else ""),
                )
            )
        if hi is not None:
            items.append(
                (
                    glyph(
                        '<rect class="range" x="1" y="3" width="26" height="12" rx="6"/>'
                    ),
                    "plausible range",
                )
            )
        legend = (
            '<ul class="scale-legend">'
            + "".join(f"<li>{g}{e(t)}</li>" for g, t in items)
            + "</ul>"
        )
        return f'<div class="scale-wrap">{"".join(parts)}</div>{legend}'

    def _result(self) -> str:
        r = self.a["result"]
        cf = r["confidence_factors"]
        rec = r["recommended_level"]
        headline = (
            f'<p class="verdict"><span class="verdict-level">{e(self.lab(rec))}</span>'
            f'<span class="verdict-conf">confidence {e(r["confidence"])}</span></p>'
        )
        meters = []
        width = cf["range_width"]
        settled = "high" if width == 0 else ("medium" if width == 1 else "low")
        for label, value, word in (
            ("Attribution", cf["attribution"], cf["attribution"]),
            ("Evidence", cf["evidence"], cf["evidence"]),
            ("Coverage", cf["coverage"], cf["coverage"]),
            (
                "Level settled",
                settled,
                "yes" if width == 0 else f"no ({width + 1} levels)",
            ),
        ):
            rank = CONF_RANK[value]
            bars = "".join(
                f'<i class="{"on" if k <= rank else ""}"></i>' for k in (1, 2, 3)
            )
            meters.append(
                f'<div class="meter"><span>{label}</span><span class="bars" aria-hidden="true">{bars}</span><b>{e(word)}</b></div>'
            )
        bands = (
            '<dl class="bands">'
            f"<div><dt>Technical capability</dt><dd>{e(self.lab(r['technical_capability_level']))}</dd></div>"
            f"<div><dt>Scope and influence</dt><dd>{e(self.lab(r['scope_influence_level']))} <small>({e(r['scope_influence_status'].replace('_', ' '))})</small></dd></div>"
            f"<div><dt>Plausible range</dt><dd>{e(self.lab(r['plausible_range']['lower']))} to {e(self.lab(r['plausible_range']['upper']))}</dd></div>"
            "</dl>"
        )
        extra = ""
        if r["inconclusive_reasons"]:
            extra += (
                '<p class="callout bad">No level can be recommended yet: '
                + e("; ".join(r["inconclusive_reasons"]))
                + ".</p>"
            )
        if r["target_level_comparison"]:
            t = r["target_level_comparison"]
            extra += f'<p class="callout">Against the target level <strong>{e(self.lab(t["target_level"]))}</strong>: {e(t["outcome"])}.</p>'
        return (
            f'<div class="hero">{headline}{self._scale()}</div>{bands}{extra}'
            f"{self._reasons()}"
            f"<h3>Why confidence is {e(r['confidence'])}</h3><p>{e(cf['notes'][0])}</p>"
            f'<div class="meters">{"".join(meters)}</div>'
            + "".join(f'<p class="fine">{e(n)}</p>' for n in cf["notes"][1:])
            + '<h3>Assessor summary</h3><p class="fine">Written by the assessing model. The level above is computed by the engine; this text neither restates nor overrides it. Superscripts link to the evidence register.</p>'
            f'<div class="summary">{self._prose(self.a["summary"])}</div>'
        )

    def _reasons(self) -> str:
        """Plain-language reasons for the recommended level and what blocks the next one."""
        r = self.a["result"]
        ids = [lv["id"] for lv in self.levels]
        rec = r["recommended_level"]
        if rec not in ids:
            return ""
        i = ids.index(rec)
        lv = self.levels[i]
        met = [
            cl["explanation"]
            for t in r["decision_trace"]
            if t["level"] == rec and (t["band"] == "technical" or lv["requires_scope"])
            for cl in t["clauses"]
        ]
        out = (
            f'<div class="reasons"><div><h3>Why {e(lv["label"])}</h3><ul class="met">'
            + "".join(f"<li>{e(m)}</li>" for m in met)
            + "</ul></div>"
        )
        if i + 1 < len(self.levels) and r["next_level_blockers"]:
            nxt = self.levels[i + 1]["label"]
            out += (
                f'<div><h3>What keeps it from {e(nxt)}</h3><ul class="blockers">'
                + "".join(f"<li>{e(b)}</li>" for b in r["next_level_blockers"])
                + "</ul></div>"
            )
        return out + "</div>"

    def _prose(self, text: str) -> str:
        """Paragraphs (blank lines) and '- ' bullets; evidence ids become linked superscripts."""
        out = []
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            prose: list[str] = []
            bullets: list[str] = []
            for ln in lines + [""]:
                is_bullet = ln.startswith(("- ", "* "))
                if (not is_bullet or not ln) and bullets:
                    out.append(
                        "<ul>"
                        + "".join(f"<li>{self._cite(b)}</li>" for b in bullets)
                        + "</ul>"
                    )
                    bullets = []
                if is_bullet:
                    if prose:
                        out.append(f"<p>{self._cite(' '.join(prose))}</p>")
                        prose = []
                    bullets.append(ln[2:])
                elif ln:
                    prose.append(ln)
            if prose:
                out.append(f"<p>{self._cite(' '.join(prose))}</p>")
        return "".join(out)

    def _cite(self, text: str) -> str:
        escaped = e(text)

        def sup(ids: list[str]) -> str:
            links = []
            alias = {d["id"]: d["duplicate_of"] for d in self.ev["duplicates"]}
            for i in dict.fromkeys(alias.get(i, i) for i in ids):
                short = i.removeprefix("E-").lstrip("0") or "0"
                if not i.startswith("E-"):
                    short = i
                record = self.by_id.get(i)
                tip = (
                    f' title="{e(i + ": " + record["observation"][:160])}"'
                    if record
                    else ""
                )
                links.append(
                    f'<a href="#ev-{e(i)}"{tip}>{e(short)}</a>'
                    if record
                    else f'<span class="dead">{e(short)}</span>'
                )
            return f'<sup class="cites">{",".join(links)}</sup>'

        pattern = re.compile(
            rf"\s?\(\s*((?:{_ID})(?:\s*,\s*(?:{_ID}))*)\s*\)|(?<![\w-])({_ID})(?![\w-])"
        )
        return pattern.sub(
            lambda m: sup(
                re.split(r"\s*,\s*", m.group(1)) if m.group(1) else [m.group(2)]
            ),
            escaped,
        )

    # ---- competencies -----------------------------------------------------

    def _competencies(self) -> str:
        groups: dict[str, list[dict[str, Any]]] = {}
        for c in self.a["competencies"]:
            groups.setdefault(c["group"], []).append(c)
        out = [
            '<p class="fine">Bars run from 0 to 5. Solid fill means high confidence, lighter fill medium, hatched low. A hollow notch marks the score the assessor proposed when the engine capped it. Not observable is never a zero.</p>'
        ]
        for group, comps in groups.items():
            desc = self.rubric["groups"].get(group, "")
            out.append(
                f'<h3>{e(group.capitalize())}</h3><p class="fine">{e(desc)}</p><div class="comps">'
            )
            for c in comps:
                out.append(self._comp_row(c))
            out.append("</div>")
        return "".join(out)

    def _comp_row(self, c: dict[str, Any]) -> str:
        if c["score"] is None:
            reason = (
                c["not_observable_reason"] if c["status"] == "not_observable" else None
            )
            short = NO_REASON_SHORT.get(reason, "only the candidate's own account")
            meter = f'<div class="track no" title="{e(NO_REASON_TEXT.get(reason, ""))}"><span>Not observable: {e(short)}</span></div>'
            score = '<span class="score void">N/O</span>'
        else:
            width = c["score"] / 5 * 100
            ghost = ""
            if c["proposed_score"] is not None and c["proposed_score"] != c["score"]:
                ghost = f'<i class="ghost" style="left:{c["proposed_score"] / 5 * 100:.0f}%" title="proposed {c["proposed_score"]}"></i>'
            status = " self" if c["status"] == "self_reported" else ""
            meter = f'<div class="track" role="img" aria-label="score {c["score"]} of 5, {e(c["confidence"])} confidence"><i class="fill c-{e(c["confidence"])}{status}" style="width:{width:.0f}%"></i>{ghost}</div>'
            score = f'<span class="score">{c["score"]}</span>'
        detail = (
            f"<p>{e(c['rationale']) if c['rationale'] else '<span class=none>No rationale given.</span>'}</p>"
            f"<p><b>Supporting</b> {_ev_refs(c['supporting_evidence_ids'], self.known)}</p>"
            f"<p><b>Counterevidence</b> {_ev_refs(c['counterevidence_ids'], self.known)}</p>"
            + (
                f"<p><b>Self-reports</b> {_ev_refs(c['self_report_ids'], self.known)}</p>"
                if c["self_report_ids"]
                else ""
            )
            + f"<p><b>Independent sources</b> {c['independent_sources']}</p>"
            + (
                "<p><b>Engine adjustments</b></p><ul>"
                + "".join(f"<li>{e(x)}</li>" for x in c["adjustments"])
                + "</ul>"
                if c["adjustments"]
                else ""
            )
        )
        flag = ' <span class="flag">adjusted</span>' if c["adjustments"] else ""
        return (
            f'<details class="comp"><summary><span class="cname">{e(c["name"])}{flag}</span>{meter}{score}'
            f'<span class="cconf">{e(c["confidence"])}</span></summary><div class="cdetail">{detail}</div></details>'
        )

    # ---- trace --------------------------------------------------------------

    def _trace(self) -> str:
        r = self.a["result"]
        requires = {lv["id"]: lv["requires_scope"] for lv in self.levels}
        by_level: dict[str, list[dict[str, Any]]] = {}
        for t in r["decision_trace"]:
            by_level.setdefault(t["level"], []).append(t)
        rec_idx = next(
            (
                i
                for i, lv in enumerate(self.levels)
                if lv["id"] == r["recommended_level"]
            ),
            -1,
        )
        out = [
            '<p class="fine">Each level has declarative rules for two bands. Staff and above also need the scope band. Unknown means the rule can only be settled by evidence that is currently not observable.</p>'
        ]
        for i, lv in enumerate(self.levels):
            traces = by_level.get(lv["id"], [])
            tech = next((t for t in traces if t["band"] == "technical"), None)
            scope = next((t for t in traces if t["band"] == "scope"), None)
            chips = ""
            if tech:
                chips += _chip(
                    f"technical {tech['outcome']}", OUTCOME_CLASS[tech["outcome"]]
                )
            if scope:
                chips += _chip(
                    f"scope {scope['outcome']}{'' if requires[lv['id']] else ' (not required)'}",
                    OUTCOME_CLASS[scope["outcome"]] if requires[lv["id"]] else "void",
                )
            open_attr = " open" if i in {rec_idx, rec_idx + 1} else ""
            rows = []
            for t in traces:
                for cl in t["clauses"]:
                    rows.append(
                        f'<tr><td>{e(t["band"])}</td><td>{e(cl["explanation"])}<br><small class="rule">Rule: {e(cl["clause"])}</small></td><td>{_chip(cl["outcome"], OUTCOME_CLASS[cl["outcome"]])}</td></tr>'
                    )
            out.append(
                f'<details class="level-rule"{open_attr}><summary><span class="lname">{e(lv["label"])}</span>{chips}<span class="ldesc">{e(lv["description"])}</span></summary>'
                '<div class="scroll"><table><thead><tr><th scope="col">Band</th><th scope="col">Requirement, in plain words</th><th scope="col">Outcome</th></tr></thead>'
                f"<tbody>{''.join(rows)}</tbody></table></div></details>"
            )
        return "".join(out)

    # ---- promotion ---------------------------------------------------------

    def _promotion(self) -> str:
        t = self.a["result"]["target_level_comparison"]
        level = next(lv for lv in self.levels if lv["id"] == t["target_level"])
        comps = {c["id"]: c for c in self.a["competencies"]}
        rows = []
        for trace in self.a["result"]["decision_trace"]:
            if trace["level"] != level["id"] or (
                trace["band"] == "scope" and not level["requires_scope"]
            ):
                continue
            for cl in trace["clauses"]:
                ev = sorted(
                    {
                        i
                        for cid in cl["competencies"]
                        if cid in comps
                        for i in comps[cid]["supporting_evidence_ids"]
                    }
                )
                rows.append(
                    f"<tr><td>{e(trace['band'])}</td><td>{e(cl['clause'])}</td><td>{_chip(cl['outcome'], OUTCOME_CLASS[cl['outcome']])}</td><td>{e(cl['detail'])}</td><td>{_ev_refs(ev, self.known)}</td></tr>"
                )
        blockers = "".join(f"<li>{e(b)}</li>" for b in t["blockers"])
        return (
            f'<p class="callout">Target <strong>{e(level["label"])}</strong>: {e(t["outcome"])}. {e(level["description"])}</p>'
            '<div class="scroll"><table><thead><tr><th scope="col">Band</th><th scope="col">Requirement</th><th scope="col">Outcome</th><th scope="col">Detail</th><th scope="col">Evidence</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>"
            + (
                f'<h3>Unmet or unresolved</h3><ul class="blockers">{blockers}</ul>'
                if blockers
                else ""
            )
        )

    # ---- findings ----------------------------------------------------------

    def _findings(self) -> str:
        cols = []
        for key, title, cls in (
            ("strengths", "Strengths", "ok"),
            ("confirmed_weaknesses", "Confirmed weaknesses", "bad"),
            ("potential_risks", "Potential risks", "warn"),
        ):
            items = (
                "".join(
                    f'<li><p>{e(f["summary"])}</p><p class="refs">{_ev_refs(f["evidence_ids"], self.known)}'
                    + (
                        f' <span class="dropped">dropped: {e(", ".join(f["dropped_evidence_ids"]))}</span>'
                        if f["dropped_evidence_ids"]
                        else ""
                    )
                    + "</p></li>"
                    for f in self.a[key]
                )
                or '<li class="none">None with verified, attributable evidence.</li>'
            )
            cols.append(
                f'<div class="finding {cls}"><h3>{title}</h3><ul>{items}</ul></div>'
            )
        gaps = (
            "".join(
                f"<li><b>{e(g['competency'].replace('_', ' '))}</b>: {e(g['reason'])} {e(g['resolution'])}</li>"
                for g in self.a["evidence_gaps"]
            )
            or "<li>None.</li>"
        )
        return f'<div class="findings">{"".join(cols)}</div><h3>Evidence gaps</h3><ul class="gaps">{gaps}</ul>'

    # ---- plan ----------------------------------------------------------------

    def _plan(self) -> str:
        plan = self.a["development_plan"]
        if not plan:
            return "<p>No plan items.</p>"
        horizon = max(p["horizon_days"] for p in plan)
        rows = []
        for p in plan:
            width = p["horizon_days"] / horizon * 100
            rows.append(
                f'<article class="plan-item p-{e(p["priority"])}">'
                f'<header><span class="pid">{e(p["id"])}</span><h3>{e(p["title"])}</h3>{_chip(p["priority"], "accent")}{_chip(p["category"].replace("_", " "), "void")}{_chip("effort " + p["effort"], "void")}</header>'
                f'<div class="horizon" aria-label="horizon {p["horizon_days"]} days"><i style="width:{width:.0f}%"></i><span>{p["horizon_days"]} days</span></div>'
                f"<dl><div><dt>Why</dt><dd>{e(p['why'])}</dd></div><div><dt>Action</dt><dd>{e(p['action'])}</dd></div>"
                f"<div><dt>Done when</dt><dd>{e(p['success_criterion'])}</dd></div>"
                f"<div><dt>Competencies</dt><dd>{e(', '.join(c.replace('_', ' ') for c in p['competencies']))}</dd></div>"
                f"<div><dt>Source</dt><dd>{_ev_refs(p['source_evidence_ids'], self.known)}</dd></div></dl></article>"
            )
        return '<div class="plan">' + "".join(rows) + "</div>"

    # ---- questions -------------------------------------------------------------

    def _questions(self) -> str:
        items = "".join(
            f'<li><p class="q">{e(q["question"])}</p><p class="fine">Targets {e(", ".join(c.replace("_", " ") for c in q["competencies"]))}. '
            f"Grounded in {_ev_refs(q['evidence_ids'], self.known)}. Could change: {e(q['would_change'])}</p></li>"
            for q in self.a["interview_questions"]
        )
        return f'<p class="fine">Answers are recorded as self-reports. They can raise confidence or expose a disagreement, but never raise a level band on their own.</p><ol class="questions">{items}</ol>'

    # ---- evidence ---------------------------------------------------------------

    def _evidence(self) -> str:
        records = self.ev["evidence"]
        kinds = sorted({x["kind"] for x in records})
        attrs = sorted({x["candidate_attribution"] for x in records})

        def options(values: list[str]) -> str:
            return '<option value="">all</option>' + "".join(
                f'<option value="{e(v)}">{e(v.replace("_", " "))}</option>'
                for v in values
            )

        filters = (
            '<form class="filters" role="search" aria-label="Filter evidence">'
            f'<label>Kind <select data-filter="kind">{options(kinds)}</select></label>'
            f'<label>Attribution <select data-filter="attr">{options(attrs)}</select></label>'
            '<label>Contains <input type="search" data-filter="text" placeholder="path, id or words"></label>'
            '<output class="count" aria-live="polite"></output></form>'
        )
        rows = []
        for x in records:
            loc = (
                x["path"]
                or (x["commit"][:12] if x["commit"] else None)
                or x["url"]
                or "—"
            )
            if x["path"] and x["line_start"]:
                loc += f":{x['line_start']}-{x['line_end']}"
            loc_html = _link(x["url"], f"<code>{e(loc)}</code>")
            search = " ".join(
                str(v)
                for v in (
                    x["id"],
                    x["path"],
                    x["commit"],
                    x["observation"],
                    x["interpretation"],
                    " ".join(x["competencies"]),
                )
                if v
            ).lower()
            caveats = "".join(f"<li>{e(c)}</li>" for c in x["caveats"])
            adjust = "".join(f"<li>{e(c)}</li>" for c in x["adjustments"])
            contested = (
                f'<p class="callout warn">Contested ({e(x["contested"]["claim"])}): {e(x["contested"]["note"])}. Resolution: {e(x["contested"]["resolution"].replace("_", " "))}.</p>'
                if x["contested"]
                else ""
            )
            rows.append(
                f'<tr id="ev-{e(x["id"])}" data-kind="{e(x["kind"])}" data-attr="{e(x["candidate_attribution"])}" data-text="{e(search)}" class="pol-{e(x["polarity"])}">'
                f'<th scope="row">{e(x["id"])}</th><td>{e(x["kind"].replace("_", " "))}<br><small>{e(x["repository"])}</small></td>'
                f"<td>{loc_html}</td>"
                f"<td>{_chip(x['candidate_attribution'], ATTRIBUTION_CLASS.get(x['candidate_attribution'], 'void'))}<br><small>{e(x['verification'].replace('_', ' '))}</small></td>"
                f"<td>{_chip(x['status'], STATUS_CLASS.get(x['status'], 'void'))}</td>"
                f'<td><details><summary><span class="obs">{e(x["observation"])}</span></summary>'
                f"<p><b>Interpretation</b> {e(x['interpretation'])}</p>"
                f"<p><b>Competencies</b> {e(', '.join(c.replace('_', ' ') for c in x['competencies']) or 'none')}; polarity {e(x['polarity'])}; confidence {e(x['confidence'])}</p>"
                f"<p><b>Attribution basis</b> {e(x['attribution_basis'])}</p>"
                + (f"<p><b>Caveats</b></p><ul>{caveats}</ul>" if caveats else "")
                + (
                    f"<p><b>Engine adjustments</b></p><ul>{adjust}</ul>"
                    if adjust
                    else ""
                )
                + contested
                + (
                    f'<p class="hash">span sha256 <code>{e(x["span_sha256"][:16])}</code></p>'
                    if x["span_sha256"]
                    else ""
                )
                + "</details></td></tr>"
            )
        table = (
            '<div class="scroll"><table class="evidence"><thead><tr><th scope="col">ID</th><th scope="col">Kind</th><th scope="col">Location</th>'
            '<th scope="col">Attribution</th><th scope="col">Status</th><th scope="col">Observation</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
        rejected = ""
        if self.ev["rejected"]:
            rejected = (
                '<h3>Rejected by verification</h3><ul class="rejected">'
                + "".join(
                    f"<li><b>{e(r['id'])}</b> {e('; '.join(r['reasons']))}</li>"
                    for r in self.ev["rejected"]
                )
                + "</ul>"
            )
        dups = ""
        if self.ev["duplicates"]:
            dups = (
                '<p class="fine">Merged duplicates: '
                + e(
                    ", ".join(
                        f"{d['id']} into {d['duplicate_of']}"
                        for d in self.ev["duplicates"]
                    )
                )
                + ".</p>"
            )
        return filters + table + rejected + dups

    # ---- repositories ---------------------------------------------------------

    def _repositories(self) -> str:
        cov = {c["repo"]: c for c in self.a["coverage"]["repositories"]}
        out = []
        for r in self.f["repositories"]:
            att, lin, col = r["attribution"], r["lineage"], r["collaboration"]
            sl = att["surviving_lines"]
            total = max(1, sl["total"])
            other = max(
                0,
                sl["total"]
                - sl["candidate"]
                - sl["inherited"]
                - sl["bulk_import"]
                - sl["unknown"],
            )
            segs = [
                ("candidate", sl["candidate"], "seg-cand"),
                ("inherited", sl["inherited"], "seg-inh"),
                ("bulk import", sl["bulk_import"], "seg-bulk"),
                ("unknown", sl["unknown"], "seg-unk"),
                ("others", other, "seg-other"),
            ]
            stack = "".join(
                f'<i class="{cls}" style="width:{v / total * 100:.2f}%" title="{e(name)} {v}"></i>'
                for name, v, cls in segs
                if v
            )
            legend = "".join(
                f'<li><i class="{cls}"></i>{e(name)} <span class="num">{v:,}</span></li>'
                for name, v, cls in segs
            )
            unknown_subs = {
                f["subsystem"]
                for f in r["files"]
                if f["candidate_touched"] and not f["blamed"]
            }
            subs = "".join(
                f'<tr><th scope="row"><code>{e(s["name"])}</code></th><td class="num">{s["files"]}</td><td class="num">{s["lines"]:,}</td>'
                + (
                    f'<td><div class="mini"><i style="width:{(s["share"] or 0) * 100:.0f}%"></i></div></td><td class="num">{_pct(s["share"])}</td></tr>'
                    if s["name"] not in unknown_subs
                    else '<td colspan="2" class="num fine">unknown: candidate files not blamed</td></tr>'
                )
                for s in r["subsystems"][:15]
            )
            langs = (
                ", ".join(
                    f"{e(lg['language'])} {lg['candidate_lines']:,}/{lg['lines']:,}"
                    for lg in r["languages"][:8]
                )
                or "—"
            )
            excl = (
                ", ".join(
                    f"{e(k.replace('_', ' '))} {v}"
                    for k, v in r["exclusions"]["counts"].items()
                )
                or "none"
            )
            ids = (
                "".join(
                    f"<li>{e(m['display'])} ({e(m['match'].replace('_', ' '))}, {m['commits']} commits)</li>"
                    for m in r["identity"]["matched"]
                )
                or "<li>none</li>"
            )
            aliases = "".join(
                f"<li>{e(a['display'])}: {e(a['reason'])}</li>"
                for a in r["identity"]["unconfirmed_aliases"]
            )
            notes = "".join(
                f"<li>{e(n)}</li>"
                for n in r["identity"]["notes"] + lin["notes"] + lin["hints"]
            )
            host = (
                "".join(
                    f"<li>{_link(h['url'], e(h['id']))}: {e(h['observation'])}</li>"
                    for h in r["host_evidence"]
                )
                or "<li>none collected</li>"
            )
            by_path: dict[str, list[dict[str, Any]]] = {}
            for fl in r["injection_flags"]:
                by_path.setdefault(fl["path"], []).append(fl)
            flags = "".join(
                "".join(
                    f"<li><code>{e(fl['path'])}:{fl['line']}</code> {e(fl['pattern'].replace('_', ' '))}: “{e(fl['excerpt'])}”</li>"
                    for fl in group[:3]
                )
                + (
                    f'<li class="fine">{len(group) - 3} more in <code>{e(path)}</code></li>'
                    if len(group) > 3
                    else ""
                )
                for path, group in by_path.items()
            )
            c = cov.get(r["repo_id"], {})
            checks = ", ".join(
                f"{e(k)} {e(v)}"
                for k, v in r["ci"]["check_runs"]["conclusions"].items()
            ) or (
                e(r["ci"]["check_runs"]["error"])
                if r["ci"]["check_runs"]["error"]
                else "not collected"
            )
            out.append(
                f'<article class="repo"><h3>{e(r["repo_id"])}: {_link(r["host"]["web_url"], e(r["host"]["web_url"] or r["locator"]))}</h3>'
                f'<p class="fine">Revision <code>{e(r["revision"])}</code> committed {e(r["revision_time"])}. {e(r["working_tree"]["note"])}. '
                f"{r['history']['commit_count']:,} commits ({r['history']['merge_commits']:,} merges), {e(r['history']['first_commit_at'])} to {e(r['history']['last_commit_at'])}{', shallow history' if r['history']['is_shallow'] else ''}.</p>"
                f'<h4>Surviving lines at the revision</h4><div class="stack" role="img" aria-label="line ownership">{stack}</div><ul class="legend">{legend}</ul>'
                '<dl class="grid">'
                f"<div><dt>Role</dt><dd>{e(att['role'].replace('_', ' '))}</dd></div>"
                f"<div><dt>Candidate commits</dt><dd>{att['candidate_commits']:,} of {att['human_commits']:,} human ({_pct(att['candidate_commit_share'])}); {att['candidate_coauthored_commits']} co-authored</dd></div>"
                f"<div><dt>Lines added</dt><dd>{att['added_lines']['candidate']:,} of {att['added_lines']['total']:,} ({_pct(att['candidate_added_share'])})</dd></div>"
                f"<div><dt>AI assistance</dt><dd>{att['ai_assisted_commits']} declared, {att['ai_mentioned_commits']} mentioned</dd></div>"
                f"<div><dt>Lineage</dt><dd>{e(lin['relationship'].replace('_', ' '))}; ancestry {e(lin['ancestry'].replace('_', ' '))}; delta {e(lin['delta_kind'].replace('_', ' '))}</dd></div>"
                f"<div><dt>Collaboration</dt><dd>{col['human_contributors']} human contributor(s); {col['other_human_commits']} commits by others; PRs {e(col['prs_authored'])} authored, {e(col['prs_merged'])} merged; {e(col['reviews_given'])} reviews of others</dd></div>"
                f"<div><dt>Blame</dt><dd>{att['blame']['files_blamed']} of {att['blame']['files_eligible']} files{'' if att['blame']['complete'] else ' (budget reached)'}</dd></div>"
                f"<div><dt>Coverage</dt><dd>{_pct(c.get('sample_coverage'))} of the sample budget; {c.get('sample_items_audited', 0)} of {c.get('sample_items', 0)} items read through show; {_pct(c.get('candidate_line_coverage'))} of candidate lines</dd></div>"
                f"<div><dt>CI at revision</dt><dd>{checks}</dd></div>"
                f"<div><dt>Languages (candidate/total lines)</dt><dd>{langs}</dd></div>"
                f"<div><dt>Excluded from authorship</dt><dd>{excl}</dd></div>"
                "</dl>"
                f'<h4>Subsystem ownership</h4><div class="scroll"><table class="subs"><thead><tr><th scope="col">Subsystem</th><th scope="col">Files</th><th scope="col">Lines</th><th scope="col">Candidate share</th><th scope="col"></th></tr></thead><tbody>{subs}</tbody></table></div>'
                f"<h4>Identity</h4><ul>{ids}</ul>"
                + (
                    f"<h4>Unconfirmed aliases (not credited)</h4><ul>{aliases}</ul>"
                    if aliases
                    else ""
                )
                + (f"<h4>Notes</h4><ul>{notes}</ul>" if notes else "")
                + f"<h4>Host records</h4><ul>{host}</ul>"
                + (
                    f'<h4>Text addressed to evaluators (treated as data)</h4><ul class="flags">{flags}</ul>'
                    if flags
                    else ""
                )
                + "</article>"
            )
        return "".join(out)

    # ---- revisions --------------------------------------------------------------

    def _revisions(self) -> str:
        out = []
        if self.a["self_reports"]:
            out.append(
                "<h3>Self-reports</h3><ul>"
                + "".join(
                    f'<li id="ev-{e(s["id"])}-sr"><b>{e(s["id"])}</b> {e(s["observation"])} <small>{e("; ".join(s["caveats"]))}</small></li>'
                    for s in self.a["self_reports"]
                )
                + "</ul>"
            )
        if self.a["contested_evidence"]:
            out.append(
                "<h3>Contested evidence</h3><ul>"
                + "".join(
                    f'<li><a class="ref" href="#ev-{e(c["id"])}">{e(c["id"])}</a> {e(c["claim"])}: {e(c["note"])} ({e(c["resolution"].replace("_", " "))})</li>'
                    for c in self.a["contested_evidence"]
                )
                + "</ul>"
            )
        ch = self.a["changes"]
        if ch:
            out.append(
                f"<h3>Changes since assessment <code>{e(ch['previous_assessment_id'][:16])}</code></h3><ul>"
                + "".join(f"<li>{e(s)}</li>" for s in ch["summary"] + ch["freshness"])
                + "</ul>"
            )
        return "".join(out)

    def _contest(self) -> str:
        return (
            "<p>Any evidence item or attribution can be challenged. Add an entry to <code>challenges</code> with the claim "
            "<code>not_authored</code>, <code>misinterpreted</code>, <code>outdated</code> or <code>other</code>, or record answers as "
            "<code>self_reports</code>, then rerun <code>assess --previous</code> on this assessment.</p>"
            "<p>Authorship verified through a high-confidence identity survives a <code>not_authored</code> challenge but is marked contested. "
            "Self-reports are kept next to the evidence they dispute and never raise a level on their own.</p>"
        )

    def _footer(self) -> str:
        p = self.a["provenance"]
        rows = "".join(
            f"<div><dt>{e(k.replace('_', ' '))}</dt><dd><code>{e(v)}</code></dd></div>"
            for k, v in p.items()
        )
        return (
            '<footer class="provenance"><h2>Provenance</h2>'
            f'<p class="fine">Generated by {e(self.a["tool"]["name"])} {e(self.a["tool"]["version"])}, run <code>{e(self.a["run_id"])}</code>. '
            "Identical forensics, judgments and rubric reproduce this assessment id. This file works offline and loads nothing from the network.</p>"
            f'<dl class="grid hashes">{rows}</dl></footer>'
        )


def assessment_html(
    assessment: dict[str, Any],
    evidence: dict[str, Any],
    forensics: dict[str, Any],
    rubric: dict[str, Any],
) -> str:
    return Report(assessment, evidence, forensics, rubric).render()


SCRIPT = (
    "(function(){var f=document.querySelector('.filters');if(!f)return;"
    "var rows=[].slice.call(document.querySelectorAll('table.evidence tbody tr'));var out=f.querySelector('.count');"
    "function apply(){var k=f.querySelector('[data-filter=kind]').value,a=f.querySelector('[data-filter=attr]').value,"
    "t=f.querySelector('[data-filter=text]').value.trim().toLowerCase(),n=0;"
    "rows.forEach(function(r){var ok=(!k||r.dataset.kind===k)&&(!a||r.dataset.attr===a)&&(!t||r.dataset.text.indexOf(t)>-1);"
    "r.hidden=!ok;if(ok)n++;});out.textContent=n+' of '+rows.length+' shown';}"
    "f.addEventListener('input',apply);f.addEventListener('submit',function(ev){ev.preventDefault();});apply();"
    "if(location.hash.indexOf('#ev-')===0){var r=document.getElementById(location.hash.slice(1));if(r){var d=r.querySelector('details');if(d)d.open=true;}}"
    "window.addEventListener('hashchange',function(){var r=document.getElementById(location.hash.slice(1));if(r&&r.hidden){f.reset();apply();}"
    "if(r){var d=r.querySelector('details');if(d)d.open=true;}});})();"
)

CSS = """
:root{--paper:#f2f4f3;--panel:#ffffff;--ink:#1e2b33;--muted:#5b6a72;--rule:#d3dbde;--scale:#284b63;--ok:#12756e;--warn:#a66b14;--bad:#9e3443;--void:#8e989e;
--serif:Charter,"Bitstream Charter","Iowan Old Style","Sitka Text",Cambria,Georgia,serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--paper:#11171b;--panel:#182027;--ink:#dce4e7;--muted:#9aa8b0;--rule:#2b3740;--scale:#8fb5d4;--ok:#4fb3a9;--warn:#d9a24a;--bad:#e07a88;--void:#6e7a82}}
*{box-sizing:border-box}html{scroll-behavior:smooth}@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 var(--sans);font-variant-numeric:tabular-nums}
a{color:var(--scale)}a:focus-visible,summary:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid var(--scale);outline-offset:2px}
code{font:0.86em/1.3 var(--mono);overflow-wrap:anywhere}
.skip{position:absolute;left:-999px}.skip:focus{left:1rem;top:1rem;background:var(--panel);padding:.5rem 1rem;z-index:9}
.layout{display:grid;grid-template-columns:15rem minmax(0,1fr);max-width:84rem;margin:0 auto}
.toc{position:sticky;top:0;align-self:start;height:100vh;overflow:auto;padding:2rem 1.25rem;border-right:1px solid var(--rule)}
.toc-title{font:600 1.05rem/1.3 var(--serif);margin:0 0 1rem}.toc ol{list-style:none;margin:0;padding:0}.toc li{margin:.15rem 0}
.toc a{display:block;padding:.3rem .5rem;border-radius:4px;text-decoration:none;color:var(--muted);font-size:.9rem}.toc a:hover{background:var(--panel);color:var(--ink)}
main{padding:2.5rem 3rem 4rem;min-width:0}
section{padding:2.25rem 0;border-top:1px solid var(--rule)}
h1,h2,h3,h4{font-family:var(--serif);font-weight:600;line-height:1.2;letter-spacing:-.005em}
h1{font-size:2.6rem;margin:.1rem 0 .5rem}h2{font-size:1.65rem;margin:0 0 1rem}h3{font-size:1.2rem;margin:1.75rem 0 .6rem}h4{font-size:1rem;margin:1.25rem 0 .4rem}
p{max-width:none;margin:.5rem 0}.fine{color:var(--muted);font-size:.9rem}.none{color:var(--muted)}main{max-width:76rem}
.kind{color:var(--scale);font-weight:600;margin:0}.lede{font-size:1.1rem;color:var(--muted);margin:0 0 1.25rem;overflow-wrap:anywhere}
.facts,.bands,.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(14rem,1fr));gap:.75rem 1.5rem;margin:1rem 0}
dt{color:var(--muted);font-size:.85rem}dd{margin:.1rem 0 0;overflow-wrap:anywhere}
.notice{border-left:3px solid var(--scale);padding:.2rem 0 .2rem .9rem;color:var(--muted);font-size:.95rem}
table{border-collapse:collapse;width:100%;font-size:.92rem;background:var(--panel)}caption{text-align:left;color:var(--muted);font-size:.85rem;padding:0 0 .5rem}
th,td{text-align:left;vertical-align:top;padding:.55rem .7rem;border-bottom:1px solid var(--rule)}thead th{font-weight:600;color:var(--muted);font-size:.82rem;background:var(--paper)}
.num{text-align:right;white-space:nowrap}.scroll{overflow-x:auto}
.chip{display:inline-block;padding:.05rem .5rem;border-radius:999px;font-size:.8rem;border:1px solid currentColor;white-space:nowrap;margin:.1rem .25rem .1rem 0}
.chip.ok{color:var(--ok)}.chip.warn{color:var(--warn)}.chip.bad{color:var(--bad)}.chip.void{color:var(--void)}.chip.accent{color:var(--scale)}
.comp summary:hover,.level-rule summary:hover{background:var(--paper)}
.limits{list-style:none;padding:0;margin:0;display:grid;gap:.6rem}.limits li{background:var(--panel);border:1px solid var(--rule);border-radius:6px;padding:.6rem .9rem}
.limits p{margin:.25rem 0 0;font-size:.92rem}.code-label{font-weight:600}.impact{color:var(--muted);font-size:.85rem;margin-left:.4rem}
.hero{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:1.5rem 1.5rem .5rem}
.verdict{display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap;margin:0}
.verdict-level{font:600 3.2rem/1 var(--serif);color:var(--scale)}.verdict-conf{color:var(--muted)}
.scale{width:100%;height:auto;display:block;margin-top:.5rem}.scale-wrap{overflow-x:auto}.scale-wrap>.scale{min-width:34rem}
.scale .axis{stroke:var(--ink);stroke-width:2}.scale .tick{stroke:var(--ink);stroke-width:2}
.scale .level{fill:var(--ink);font:600 15px var(--serif)}.scale .range{fill:var(--scale);fill-opacity:.12;stroke:var(--scale);stroke-opacity:.7;stroke-dasharray:5 4}
.scale-legend{display:flex;flex-wrap:wrap;gap:.4rem 1.4rem;list-style:none;padding:0;margin:.25rem 0 .75rem;color:var(--muted);font-size:.85rem}
.scale-legend svg{display:inline-block;width:28px;height:18px;margin:0 .4rem 0 0;vertical-align:-4px}
.scale .mark-rec{fill:var(--scale);stroke:var(--panel);stroke-width:4}.scale .mark-tech{fill:var(--ok)}.scale .mark-scope{fill:var(--warn)}.scale .mark-scope.partial{fill:none;stroke:var(--warn);stroke-width:2}
.determination{font:1.15rem/1.5 var(--serif);margin:1.25rem 0 .5rem}
.meters{display:grid;grid-template-columns:repeat(auto-fill,minmax(15rem,1fr));gap:.5rem 1.5rem;margin:1rem 0}
.meter{display:flex;align-items:center;gap:.6rem}.meter span:first-child{min-width:6.5rem;color:var(--muted);font-size:.88rem}.meter b{white-space:nowrap}
.bars{display:inline-flex;gap:3px}.bars i{width:16px;height:8px;border-radius:2px;background:var(--rule)}.bars i.on{background:var(--scale)}
.callout{background:var(--panel);border:1px solid var(--rule);border-left:4px solid var(--scale);padding:.6rem .9rem;border-radius:4px}
.callout.bad{border-left-color:var(--bad)}.callout.warn{border-left-color:var(--warn)}
.blockers li,.gaps li,.met li{margin:.4rem 0}
.reasons{display:grid;grid-template-columns:repeat(auto-fit,minmax(20rem,1fr));gap:0 2rem;margin-top:.5rem}
.reasons ul{padding-left:1.1rem}.met li::marker{color:var(--ok)}.reasons .blockers li::marker{color:var(--warn)}
.summary{padding:.5rem 1.5rem;background:var(--panel);border:1px solid var(--rule);border-left:3px solid var(--scale);border-radius:4px;font:1.02rem/1.65 var(--serif)}
.summary p{margin:.9rem 0}.summary ul{margin:.6rem 0;padding-left:1.2rem}.summary li{margin:.35rem 0}
.cites{font:600 .68em/1 var(--sans);margin-left:.12em;white-space:nowrap}.cites a{text-decoration:none;padding:0 .08em}.cites a:hover{text-decoration:underline}.cites .dead{color:var(--void)}
small.rule{color:var(--muted)}
.comps{display:grid;gap:2px}
.comp{background:var(--panel);border:1px solid var(--rule);border-radius:6px}
.comp summary{display:grid;grid-template-columns:minmax(10rem,14rem) minmax(8rem,1fr) 2.5rem 4.5rem;align-items:center;gap:1rem;padding:.55rem .9rem;cursor:pointer;list-style:none}
.comp summary::-webkit-details-marker{display:none}.comp[open] summary{border-bottom:1px solid var(--rule)}
.cname{font-weight:600}.flag{font-weight:400;font-size:.75rem;color:var(--warn);margin-left:.3rem}
.track{position:relative;height:14px;border-radius:7px;background:repeating-linear-gradient(90deg,var(--rule) 0 1px,transparent 1px 20%);border:1px solid var(--rule)}
.track .fill{position:absolute;left:0;top:0;bottom:0;border-radius:7px;background:var(--scale)}
.fill.c-medium{opacity:.62}.fill.c-low{background:repeating-linear-gradient(135deg,var(--scale) 0 5px,transparent 5px 9px);opacity:.75}.fill.self{background:var(--warn)}
.ghost{position:absolute;top:-4px;bottom:-4px;width:3px;margin-left:-1.5px;border:1px solid var(--bad);background:var(--panel)}
.track.no{background:repeating-linear-gradient(135deg,transparent 0 6px,var(--rule) 6px 7px);display:flex;align-items:center;padding-left:.5rem;height:22px;border-radius:4px}
.track.no span{font-size:.78rem;color:var(--muted)}
.score{font:600 1.2rem var(--serif);text-align:right}.score.void{color:var(--void);font-size:.95rem}.cconf{color:var(--muted);font-size:.82rem}
.cdetail{padding:.5rem 1rem 1rem}.cdetail p{margin:.4rem 0}
.ref{display:inline-block;font:.8rem var(--mono);padding:0 .3rem;border-radius:3px;background:var(--paper);text-decoration:none;margin:.1rem 0}.ref.dead{color:var(--void);text-decoration:line-through}
.level-rule{background:var(--panel);border:1px solid var(--rule);border-radius:6px;margin:.4rem 0}
.level-rule summary{padding:.6rem .9rem;cursor:pointer;display:flex;flex-wrap:wrap;gap:.4rem .75rem;align-items:baseline}
.lname{font:600 1.05rem var(--serif);min-width:7rem}.ldesc{flex-basis:100%;color:var(--muted);font-size:.88rem}
.level-rule table{border-top:1px solid var(--rule)}
.findings{display:grid;grid-template-columns:repeat(auto-fit,minmax(16rem,1fr));gap:1rem}
.finding{border-top:4px solid var(--rule);background:var(--panel);padding:0 1rem .5rem;border-radius:0 0 6px 6px}
.finding.ok{border-top-color:var(--ok)}.finding.bad{border-top-color:var(--bad)}.finding.warn{border-top-color:var(--warn)}
.finding ul{list-style:none;padding:0}.finding li{margin:0 0 .8rem}.finding li p{margin:.1rem 0}.dropped{color:var(--void);font-size:.8rem}
.plan{display:grid;gap:.9rem}.plan-item{background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:.9rem 1.1rem}
.plan-item header{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem}.plan-item h3{margin:0;font-size:1.1rem;flex:1 1 16rem}.pid{font:.85rem var(--mono);color:var(--muted)}
.plan-item.p-P1{border-left:4px solid var(--scale)}
.horizon{position:relative;height:6px;background:var(--rule);border-radius:3px;margin:.75rem 0 2rem;max-width:32rem}
.horizon i{position:absolute;left:0;top:0;bottom:0;background:var(--scale);border-radius:3px}.horizon span{position:absolute;top:9px;font-size:.78rem;color:var(--muted)}
.plan-item dl{display:grid;grid-template-columns:7rem 1fr;gap:.3rem 1rem;margin:0}.plan-item dl div{display:contents}
.questions li{margin:0 0 1rem}.q{font:1.05rem/1.5 var(--serif);margin:0 0 .2rem}
.filters{display:flex;flex-wrap:wrap;gap:.75rem 1.25rem;align-items:end;margin:0 0 1rem}.filters label{display:grid;gap:.2rem;font-size:.85rem;color:var(--muted)}
.filters select,.filters input{font:inherit;padding:.35rem .5rem;border:1px solid var(--rule);border-radius:4px;background:var(--panel);color:var(--ink)}
.count{color:var(--muted);font-size:.85rem}
table.evidence summary{cursor:pointer}table.evidence tr:target{outline:2px solid var(--scale)}table.evidence details p{margin:.35rem 0}
table.evidence details:not([open]) .obs{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
table.evidence th[scope=row]{white-space:nowrap}
table.evidence summary{list-style:none;display:flex;gap:.45rem}table.evidence summary::-webkit-details-marker{display:none}
table.evidence summary::before{content:"▸";color:var(--muted);flex:none}table.evidence details[open] summary::before{content:"▾"}
table.evidence td:nth-child(3){min-width:12rem}table.evidence td:nth-child(6){min-width:16rem}
tr.pol-weakness th{box-shadow:inset 3px 0 var(--bad)}tr.pol-strength th{box-shadow:inset 3px 0 var(--ok)}
.hash{color:var(--muted);font-size:.8rem}
.repo{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:.25rem 1.25rem 1rem;margin:0 0 1.25rem}.repo h3{overflow-wrap:anywhere}
.stack{display:flex;height:16px;border-radius:4px;overflow:hidden;background:var(--rule)}
.seg-cand{background:var(--scale)}.seg-inh{background:var(--bad)}.seg-bulk{background:var(--warn)}.seg-unk{background:var(--void)}.seg-other{background:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:.25rem 1.25rem;list-style:none;padding:0;font-size:.85rem;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:.35rem;vertical-align:-1px}
.mini{height:8px;background:var(--rule);border-radius:4px;min-width:6rem}.mini i{display:block;height:100%;background:var(--scale);border-radius:4px}
.flags li{color:var(--bad)}
.provenance{border-top:1px solid var(--rule);padding-top:2rem;margin-top:1rem}.provenance h2{font-size:1.2rem}.hashes dd{font-size:.82rem}
@media (max-width:60rem){.layout{grid-template-columns:1fr}.toc{position:static;height:auto;border-right:0;border-bottom:1px solid var(--rule)}.toc ol{columns:2}
main{padding:1.5rem 1.1rem 3rem}h1{font-size:2rem}.verdict-level{font-size:2.4rem}
.comp summary{grid-template-columns:1fr 2.5rem;grid-template-areas:"n s" "t t" "c c"}.cname{grid-area:n}.score{grid-area:s}.track{grid-area:t}.cconf{grid-area:c}}
@media print{.toc,.filters,.skip{display:none}.layout{display:block}details{display:block}details>*{display:block}body{background:#fff}}
"""
