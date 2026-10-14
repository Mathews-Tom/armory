"""Verify agent judgments into a deduplicated evidence register.

Nothing the agent asserts about location or authorship is trusted:
- unknown repositories, paths absent at the pinned revision, out-of-range
  lines, unknown or unreachable commits, and undeclared artifacts are rejected;
- attribution is recomputed from blame over the cited span, then capped by
  identity confidence, bulk-import status and path category;
- `executed` claims need a log inside the run directory, else they are
  downgraded to `directly_inspected`;
- spans overlapping evaluator-directed text cannot support a score.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .blame import AttributionContext
from .exclusions import EXCLUDED, classify, subsystem_of
from .gitio import GitError, Mirror
from .lineage import fork_only_commits, upstream_refs

ATTRIBUTION_ORDER = ["unlikely", "possible", "probable", "verified"]
SUPPORT_BLOCKED = "support_blocked:"
PATH_KINDS = {
    "source_code",
    "test_code",
    "ci_config",
    "design_doc",
    "documentation",
    "benchmark_methodology",
    "benchmark_result",
}
COMMIT_KINDS = {"commit", "diff"}
URL_KINDS = {"pull_request", "review", "issue", "ci_run", "host_metadata", "release"}
_IDENTITY_CAP = {"high": "verified", "medium": "probable", "low": "possible"}


def _cap(value: str, ceiling: str) -> str:
    if value not in ATTRIBUTION_ORDER:
        return value
    return ATTRIBUTION_ORDER[
        min(ATTRIBUTION_ORDER.index(value), ATTRIBUTION_ORDER.index(ceiling))
    ]


def _span_attribution(counts: Counter[str]) -> tuple[str, float | None]:
    total = sum(counts.values())
    if total == 0:
        return "unknown", None
    if counts["inherited"] / total >= 0.5:
        return "inherited", round(
            (counts["candidate"] + 0.5 * counts["coauthored"]) / total, 4
        )
    if counts["unknown"] / total >= 0.5:
        return "unknown", None
    share = (
        counts["candidate"] + counts["bulk_import"] + 0.5 * counts["coauthored"]
    ) / total
    if counts["bulk_import"] / total >= 0.5:
        return ("possible" if share > 0 else "unlikely"), round(share, 4)
    if share >= 0.9:
        return "verified", round(share, 4)
    if share >= 0.5:
        return "probable", round(share, 4)
    if share > 0:
        return "possible", round(share, 4)
    return "unlikely", 0.0


class RepoView:
    """Lazy verification context for one repository of the run."""

    def __init__(self, run_dir: Path, repo: dict[str, Any]) -> None:
        self.repo = repo
        self.mirror = Mirror(run_dir / repo["mirror"])
        self.revision: str = repo["revision"]
        self.keys = {m["key"] for m in repo["identity"]["matched"]}
        self.identity_conf = repo["identity"]["basis_confidence"] or "low"
        self._ctx: AttributionContext | None = None
        self._fork_only: set[str] | None = None
        self.injection = {(f["path"], f["line"]) for f in repo["injection_flags"]}

    @property
    def ctx(self) -> AttributionContext:
        if self._ctx is None:
            lineage = self.repo["lineage"]
            if lineage["ancestry"] == "shared_history":
                self._fork_only = fork_only_commits(
                    self.mirror, self.revision, upstream_refs(self.mirror)
                )
            baseline = (lineage.get("content_baseline") or {}).get("commit")
            self._ctx = AttributionContext(
                self.mirror,
                self.revision,
                self.keys,
                self._fork_only,
                baseline,
                set(self.repo["attribution"]["bulk_import_commits"]),
                self.mirror.shallow_commits(),
            )
        return self._ctx

    def permalink(
        self, path: str | None, start: int | None, end: int | None, commit: str | None
    ) -> str | None:
        web = self.repo["host"]["web_url"]
        if not web:
            return None
        if path and not commit:
            anchor = (
                f"#L{start}-L{end}" if start is not None and end is not None else ""
            )
            return f"{web}/blob/{self.revision}/{path}{anchor}"
        if commit:
            return f"{web}/commit/{commit}"
        return None


def verify(
    run_dir: Path,
    forensics: dict[str, Any],
    judgments: dict[str, Any],
    input_doc: dict[str, Any],
    forensics_sha: str,
    judgments_sha: str,
) -> dict[str, Any]:
    views = {r["repo_id"]: RepoView(run_dir, r) for r in forensics["repositories"]}
    artifacts = {a["path"]: a for a in input_doc["additional_artifacts"]}
    records: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    duplicates: list[dict[str, str]] = []
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    ids: set[str] = set()

    for item in judgments["evidence"]:
        if item["id"] in ids:
            rejected.append({"id": item["id"], "reasons": ["duplicate evidence id"]})
            continue
        ids.add(item["id"])
        record, reasons = _verify_item(item, views, artifacts, run_dir)
        if reasons:
            rejected.append({"id": item["id"], "reasons": reasons})
            continue
        assert record is not None
        key = (
            record["repository"],
            record["path"],
            record["line_start"],
            record["line_end"],
            record["commit"],
            record["url"],
            record["kind"],
            # A weakness on the same lines as a strength is a different claim, not a duplicate.
            record["polarity"],
        )
        if key in seen:
            first = seen[key]
            duplicates.append({"id": record["id"], "duplicate_of": first["id"]})
            first["competencies"] = sorted(
                set(first["competencies"]) | set(record["competencies"])
            )
            continue
        seen[key] = record
        records.append(record)

    for repo in forensics["repositories"]:
        for h in repo["host_evidence"]:
            records.append(
                {
                    "id": h["id"],
                    "source": "engine",
                    "kind": h["kind"],
                    "repository": repo["repo_id"],
                    "revision": repo["revision"],
                    "path": None,
                    "line_start": None,
                    "line_end": None,
                    "commit": None,
                    "url": h["url"],
                    "span_sha256": None,
                    "subsystem": None,
                    "polarity": "neutral",
                    "candidate_attribution": h["candidate_attribution"],
                    "attribution_share": None,
                    "attribution_basis": "hosting provider record linked to the candidate login"
                    if h["candidate_attribution"] == "verified"
                    else "project-level record; not attributable to one person",
                    "verification": "ci_reported"
                    if h["kind"] == "ci_run"
                    else "host_reported",
                    "status": "verified",
                    "observation": h["observation"],
                    "interpretation": "Engine-collected host record; cite it where relevant.",
                    "competencies": [],
                    "confidence": "high",
                    "caveats": [],
                    "adjustments": [],
                    "contested": None,
                }
            )

    known = {r["id"] for r in records}
    for sr in judgments["self_reports"]:
        caveats = [
            f"contradicts {i}" for i in sr["contradicts_evidence_ids"] if i in known
        ]
        caveats += [
            f"corroborated by {i}"
            for i in sr["corroborating_evidence_ids"]
            if i in known
        ]
        records.append(
            {
                "id": sr["id"],
                "source": "self_report",
                "kind": "self_report",
                "repository": None,
                "revision": None,
                "path": None,
                "line_start": None,
                "line_end": None,
                "commit": None,
                "url": None,
                "span_sha256": hashlib.sha256(sr["answer"].encode()).hexdigest(),
                "subsystem": None,
                "polarity": "neutral",
                "candidate_attribution": "self_reported",
                "attribution_share": None,
                "attribution_basis": "candidate's own account"
                + (
                    f" (answer to {sr['question_id']})" if sr.get("question_id") else ""
                ),
                "verification": "self_report",
                "status": "unverified",
                "observation": sr["answer"],
                "interpretation": "Self-report; preserved as stated and never counted toward level bands.",
                "competencies": sorted(set(sr["competencies"])),
                "confidence": "low",
                "caveats": caveats,
                "adjustments": [],
                "contested": None,
            }
        )

    by_id = {r["id"]: r for r in records}
    for ch in judgments["challenges"]:
        target = by_id.get(ch["evidence_id"])
        if target is None:
            rejected.append(
                {
                    "id": ch["evidence_id"],
                    "reasons": ["challenge targets unknown evidence id"],
                }
            )
            continue
        if ch["claim"] == "not_authored":
            identity_high = (
                target["repository"] is not None
                and views[target["repository"]].identity_conf == "high"
            )
            if (
                target["candidate_attribution"] in {"verified", "probable"}
                and identity_high
            ):
                resolution = "retained_verified_attribution"
            else:
                resolution = "excluded_from_scoring"
                target["adjustments"].append(
                    f"{SUPPORT_BLOCKED} authorship contested and not verifiable at high confidence"
                )
        else:
            resolution = "flagged_for_review"
        target["contested"] = {
            "claim": ch["claim"],
            "note": ch["note"],
            "resolution": resolution,
        }

    inspected, coverage = _coverage(
        views, judgments["inspected"], load_show_log(run_dir)
    )
    return {
        "schema_version": "1.0",
        "run_id": forensics["run_id"],
        "provenance": {
            "forensics_sha256": forensics_sha,
            "judgments_sha256": judgments_sha,
        },
        "evidence": records,
        "rejected": rejected,
        "duplicates": duplicates,
        "inspected": inspected,
        "coverage": {"repositories": coverage},
    }


def _base_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "source": "agent",
        "kind": item["kind"],
        "repository": item.get("repo"),
        "revision": None,
        "path": item.get("path"),
        "line_start": item.get("line_start"),
        "line_end": item.get("line_end"),
        "commit": item.get("commit"),
        "url": item.get("url"),
        "span_sha256": None,
        "subsystem": None,
        "polarity": item["polarity"],
        "candidate_attribution": "unknown",
        "attribution_share": None,
        "attribution_basis": "",
        "verification": item["verification"],
        "status": "verified",
        "observation": item["observation"],
        "interpretation": item["interpretation"],
        "competencies": sorted(set(item["competencies"])),
        "confidence": item["confidence"],
        "caveats": list(item["caveats"]),
        "adjustments": [],
        "contested": None,
    }


def _verify_item(
    item: dict[str, Any],
    views: dict[str, RepoView],
    artifacts: dict[str, Any],
    run_dir: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    rec = _base_record(item)
    kind = item["kind"]
    reasons: list[str] = []

    if kind == "external_artifact" or item.get("artifact"):
        art = item.get("artifact")
        if not art or art not in artifacts:
            return None, ["artifact is not declared in input.json additional_artifacts"]
        art_path = Path(art).expanduser()
        if not art_path.is_file():
            return None, [f"declared artifact {art} does not exist"]
        rec.update(
            {
                "repository": item.get("repo"),
                "path": art,
                "span_sha256": hashlib.sha256(art_path.read_bytes()).hexdigest(),
                "candidate_attribution": "unknown",
                "attribution_basis": "requester-supplied artifact; authorship not verifiable from history",
            }
        )
        if rec["verification"] in {"directly_inspected", "executed"}:
            rec["verification"] = "repository_claimed"
            rec["adjustments"].append(
                "artifact content is a claim by its author; verification set to repository_claimed"
            )
        return _finish(rec), []

    repo_id = item.get("repo")
    if repo_id is None or repo_id not in views:
        return None, [f"unknown repository {repo_id!r}"]
    view = views[repo_id]
    rec["revision"] = view.revision

    if kind in URL_KINDS:
        url = item.get("url")
        if not url:
            return None, [f"{kind} evidence requires a url"]
        web = view.repo["host"]["web_url"]
        host_urls = {h["url"] for h in view.repo["host_evidence"]}
        if url in host_urls:
            rec["candidate_attribution"] = next(
                h["candidate_attribution"]
                for h in view.repo["host_evidence"]
                if h["url"] == url
            )
            rec["attribution_basis"] = "matches an engine-collected host record"
        else:
            rec["status"] = "unverified"
            rec["candidate_attribution"] = "unknown"
            rec["attribution_basis"] = (
                "host reference not confirmed by engine-collected records"
            )
            if web and not url.startswith(web):
                return None, [f"url {url} does not belong to repository {web}"]
        if kind == "ci_run" and rec["verification"] not in {
            "ci_reported",
            "host_reported",
        }:
            rec["adjustments"].append(
                f"verification {rec['verification']} invalid for ci_run; set to ci_reported"
            )
            rec["verification"] = "ci_reported"
        return _finish(rec), []

    if kind in COMMIT_KINDS:
        sha = item.get("commit")
        if not sha:
            return None, [f"{kind} evidence requires a commit"]
        full = view.mirror.resolve(sha)
        if full is None:
            return None, [f"commit {sha} does not exist in the repository"]
        if not view.mirror.is_ancestor(full, view.revision):
            return None, [f"commit {sha} is not reachable from the analysed revision"]
        rec["commit"] = full
        author_key = _commit_author_key(view.mirror, full)
        ctx = view.ctx
        if ctx.fork_only is not None and full not in ctx.fork_only:
            attribution = "inherited"
        elif author_key in view.keys:
            attribution = "possible" if full in ctx.bulk_shas else "verified"
        elif ctx.coauthor_keys(full) & view.keys:
            attribution = "possible"
        else:
            attribution = "unlikely"
        rec["candidate_attribution"] = _cap(
            attribution, _IDENTITY_CAP[view.identity_conf]
        )
        rec["attribution_basis"] = "commit author identity" + (
            " (bulk import)" if full in ctx.bulk_shas else ""
        )
        adds = dels = 0
        for line in view.mirror.git(
            "show", "--numstat", "--format=", full
        ).splitlines():
            cols = line.split("\t")
            if len(cols) == 3 and cols[0].isdigit() and cols[1].isdigit():
                adds, dels = adds + int(cols[0]), dels + int(cols[1])
        if dels > 20 and dels > 3 * adds:
            rec["attribution_basis"] += (
                f"; mostly deletions (+{adds}/-{dels}): the candidate authored the change, not necessarily the removed lines"
            )
            rec["caveats"].append(
                "deletion-dominated commit (revert or removal); credit is for the decision, not for the removed code"
            )
        if item.get("path"):
            touched = view.mirror.git(
                "show", "--format=", "--name-only", full, "--", item["path"]
            ).strip()
            if not touched:
                return None, [f"commit {sha} does not touch {item['path']}"]
            rec["subsystem"] = subsystem_of(item["path"])
        rec["url"] = rec["url"] or view.permalink(None, None, None, full)
        rec["span_sha256"] = hashlib.sha256(
            view.mirror.git("show", "--format=%H%n%T", "--stat", full).encode()
        ).hexdigest()
        return _finish(_claimed(rec, item)), []

    if kind in PATH_KINDS:
        path = item.get("path")
        if not path:
            return None, [f"{kind} evidence requires a path"]
        blob = view.mirror.read_blob(view.revision, path)
        if blob is None:
            return None, [
                f"path {path} does not exist at revision {view.revision[:12]}"
            ]
        text_lines = blob.decode("utf-8", "replace").splitlines()
        start, end = item.get("line_start"), item.get("line_end")
        if (start is None) != (end is None):
            return None, ["line_start and line_end must be given together"]
        if start is not None and end is not None:
            if start > end:
                reasons.append(f"line_start {start} > line_end {end}")
            if end > len(text_lines):
                reasons.append(
                    f"line_end {end} beyond end of file ({len(text_lines)} lines)"
                )
            if reasons:
                return None, reasons
            span = "\n".join(text_lines[start - 1 : end])
        else:
            span = "\n".join(text_lines)
            rec["caveats"].append("whole-file citation")
        rec["span_sha256"] = hashlib.sha256(span.encode()).hexdigest()
        rec["subsystem"] = subsystem_of(path)
        rec["url"] = rec["url"] or view.permalink(path, start, end, None)
        if item.get("commit"):
            if view.mirror.resolve(item["commit"]) is None:
                return None, [
                    f"commit {item['commit']} does not exist in the repository"
                ]
            rec["commit"] = view.mirror.resolve(item["commit"])
        try:
            counts = view.ctx.attribute(path, start, end)
        except GitError:
            counts = Counter()
        attribution, share = _span_attribution(counts)
        category = classify(path, len(blob), None, head=blob[:4096])
        basis = (
            f"blame over {'lines ' + str(start) + '-' + str(end) if start else 'whole file'}: "
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
        computed = attribution
        attribution = _cap(attribution, _IDENTITY_CAP[view.identity_conf])
        if attribution != computed:
            basis += f"; capped {computed}->{attribution} by {view.identity_conf} identity confidence"
        if category in EXCLUDED:
            ceiling = (
                "unlikely"
                if category in {"vendored", "generated", "build_output", "minified"}
                else "possible"
            )
            before = attribution
            attribution = _cap(attribution, ceiling)
            if attribution != before:
                basis += f"; capped {before}->{attribution} because the path is classified {category}"
            rec["caveats"].append(
                f"path is classified {category} and excluded from authorship inference"
            )
        rec["candidate_attribution"] = attribution
        rec["attribution_share"] = share
        rec["attribution_basis"] = basis
        lo, hi = (
            (start, end)
            if start is not None and end is not None
            else (1, len(text_lines))
        )
        if any(p == path and lo <= line <= hi for p, line in view.injection):
            rec["adjustments"].append(
                f"{SUPPORT_BLOCKED} span overlaps text addressed to evaluators (prompt-injection flag)"
            )
        if rec["verification"] == "executed":
            _check_execution(rec, item, run_dir)
        elif rec["verification"] in {"host_reported", "ci_reported"}:
            rec["adjustments"].append(
                f"verification {rec['verification']} invalid for a file citation; set to directly_inspected"
            )
            rec["verification"] = "directly_inspected"
        return _finish(_claimed(rec, item)), []

    return None, [f"unsupported evidence kind {kind!r} for repository evidence"]


def _commit_author_key(mirror: Mirror, sha: str) -> str:
    from .identity import email_key

    return email_key(mirror.git("show", "-s", "--format=%ae", sha).strip())


def _check_execution(rec: dict[str, Any], item: dict[str, Any], run_dir: Path) -> None:
    execution = item.get("execution")
    if not execution:
        rec["verification"] = "directly_inspected"
        rec["adjustments"].append(
            "claimed executed without an execution record; downgraded to directly_inspected"
        )
        return
    log = (run_dir / execution["log_path"]).resolve()
    if not log.is_file() or run_dir.resolve() not in log.parents:
        rec["verification"] = "directly_inspected"
        rec["adjustments"].append(
            "execution log missing or outside the run directory; downgraded to directly_inspected"
        )
        return
    digest = hashlib.sha256(log.read_bytes()).hexdigest()
    rec["caveats"].append(
        f"executed: `{execution['command']}` exit {execution['exit_code']} log sha256 {digest[:16]}"
    )


def _claimed(rec: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    claimed = item.get("claimed_attribution")
    computed = rec["candidate_attribution"]
    if (
        claimed in ATTRIBUTION_ORDER
        and computed in ATTRIBUTION_ORDER
        and ATTRIBUTION_ORDER.index(claimed) > ATTRIBUTION_ORDER.index(computed)
    ):
        rec["adjustments"].append(
            f"claimed attribution {claimed} exceeds computed {computed}; computed value kept"
        )
    elif claimed and claimed != computed and computed not in ATTRIBUTION_ORDER:
        rec["adjustments"].append(
            f"claimed attribution {claimed}; computed {computed} kept"
        )
    return rec


def _finish(rec: dict[str, Any]) -> dict[str, Any]:
    if rec["adjustments"] and rec["status"] == "verified":
        rec["status"] = "downgraded"
        if rec["confidence"] == "high":
            rec["confidence"] = "medium"
    return rec


def load_show_log(run_dir: Path) -> list[dict[str, Any]]:
    """Entries appended by `appraise.py show`; used to audit self-declared inspection."""
    log = run_dir / "show-log.jsonl"
    if not log.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _coverage(
    views: dict[str, RepoView],
    inspected: list[dict[str, Any]],
    show_log: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Audited coverage against each sample item's read budget.

    A line counts as read only when it is both declared in `inspected` and was
    printed by `appraise.py show` (show-log.jsonl). A file item earns
    min(1, read lines / read_budget); a commit item earns
    min(1, printed patch lines within any declared range / read_budget).
    """
    rows: list[dict[str, Any]] = []
    declared: dict[str, dict[str, set[int]]] = {rid: {} for rid in views}
    declared_commits: dict[str, dict[str, set[int] | None]] = {rid: {} for rid in views}
    for item in inspected:
        repo_id = item["repo"]
        view = views.get(repo_id)
        target = item.get("path") or item.get("commit") or "?"
        start, end = item.get("line_start"), item.get("line_end")
        if start and end:
            target += f"#L{start}-L{end}"
        valid = False
        if view is not None and item.get("path"):
            blob = view.mirror.read_blob(view.revision, item["path"])
            if blob is not None:
                valid = True
                n = max(1, len(blob.decode("utf-8", "replace").splitlines()))
                lines = (
                    set(range(max(1, start), min(end, n) + 1))
                    if start and end
                    else set(range(1, n + 1))
                )
                declared[repo_id].setdefault(item["path"], set()).update(lines)
        elif view is not None and item.get("commit"):
            full = view.mirror.resolve(item["commit"])
            if full is not None:
                valid = True
                current = declared_commits[repo_id].get(full, set())
                if start and end and current is not None:
                    declared_commits[repo_id][full] = current | set(
                        range(start, end + 1)
                    )
                else:
                    declared_commits[repo_id][full] = (
                        None  # declared without a range: whatever was printed
                    )
        rows.append(
            {
                "repo": repo_id,
                "target": target,
                "sample_id": item.get("sample_id"),
                "valid": valid,
                "candidate_lines": 0,
            }
        )

    shown: dict[str, dict[str, set[int]]] = {rid: {} for rid in views}
    shown_commits: dict[str, dict[str, set[int]]] = {rid: {} for rid in views}
    for entry in show_log:
        rid = entry.get("repo")
        if rid not in views:
            continue
        span = range(int(entry["line_start"]), int(entry["line_end"]) + 1)
        if entry.get("path"):
            shown[rid].setdefault(entry["path"], set()).update(span)
        elif entry.get("commit"):
            shown_commits[rid].setdefault(entry["commit"], set()).update(span)

    read: dict[str, dict[str, set[int]]] = {
        rid: {p: lines & shown[rid].get(p, set()) for p, lines in declared[rid].items()}
        for rid in views
    }
    for row in rows:
        path = row["target"].split("#")[0]
        view = views.get(row["repo"])
        if view is None or path not in read[row["repo"]]:
            continue
        f = next((x for x in view.repo["files"] if x["path"] == path), None)
        if f and f["lines"]:
            row["candidate_lines"] = round(
                f["candidate_lines"]
                * min(1.0, len(read[row["repo"]][path]) / f["lines"])
            )

    coverage = []
    for rid, view in views.items():
        files = {f["path"]: f for f in view.repo["files"]}
        fractions: list[float] = []
        declared_items = audited_items = 0
        for s in view.repo["sampling"]["files"]:
            got = len(read[rid].get(s["path"], set()))
            fractions.append(min(1.0, got / s["read_budget"]))
            declared_items += s["path"] in declared[rid]
            audited_items += got > 0
        for s in view.repo["sampling"]["commits"]:
            printed = shown_commits[rid].get(s["commit"], set())
            wanted = declared_commits[rid].get(s["commit"], set())
            got = len(printed if wanted is None else printed & wanted)
            fractions.append(min(1.0, got / s["read_budget"]))
            declared_items += s["commit"] in declared_commits[rid]
            audited_items += got > 0
        cand_total = view.repo["attribution"]["surviving_lines"]["candidate"]
        cand_seen = 0
        for path, lines in read[rid].items():
            f = files.get(path)
            if f and f["lines"]:
                cand_seen += round(
                    f["candidate_lines"] * min(1.0, len(lines) / f["lines"])
                )
        cand_seen = min(cand_seen, cand_total)
        coverage.append(
            {
                "repo": rid,
                "sample_items": len(fractions),
                "sample_items_inspected": declared_items,
                "sample_items_audited": audited_items,
                "sample_coverage": round(sum(fractions) / len(fractions), 4)
                if fractions
                else 0.0,
                "candidate_lines_total": cand_total,
                "candidate_lines_inspected": cand_seen,
                "candidate_line_coverage": round(cand_seen / cand_total, 4)
                if cand_total
                else 0.0,
            }
        )
    return rows, coverage
