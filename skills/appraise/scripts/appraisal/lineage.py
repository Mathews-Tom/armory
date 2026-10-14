"""Fork, template and upstream lineage analysis.

Never fabricates ancestry: a failed merge-base in a shallow mirror is
`unknown`, not `no_common_ancestor`; an unreachable upstream is reported with
`upstream_available: false` and only inspectable history earns credit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .exclusions import classify, is_manifest
from .gitio import GitError, Mirror
from .history import Commit

_HINT = re.compile(
    r"((forked\s+(from|of)|fork\s+of|mirror\s+of)\s+(the\s+)?(\[[^\]]{1,80}\]\(https?://[^)\s]+\)|https?://\S+|[A-Za-z0-9][\w.-]*/[\w.-]+)"
    r"|(based\s+on|derived\s+from|originally\s+(written|created|developed|authored)\s+by|port\s+of|copied\s+from|vendored\s+from)\s+(the\s+)?(\[[^\]]{1,80}\]\(https?://[^)\s]+\)|https?://\S+))"
    r"[^\n]{0,60}",
    re.IGNORECASE,
)
_BASELINE_MIN_OVERLAP = 0.2
_BASELINE_SAMPLES = 64
LOCAL_UPSTREAM_PREFIX = f"{Mirror.REMOTES_PREFIX}/upstream/"


@dataclass
class LineageResult:
    data: dict[str, Any]
    fork_only: set[str] | None = None
    baseline_rev: str | None = None
    limitations: list[dict[str, str]] = field(default_factory=list)


def _limitation(code: str, message: str, impact: str = "lineage") -> dict[str, str]:
    return {"code": code, "message": message, "impact": impact}


def upstream_refs(mirror: Mirror) -> list[str]:
    return mirror.refs(Mirror.UPSTREAM_PREFIX + "/") or mirror.refs(
        LOCAL_UPSTREAM_PREFIX
    )


def fork_only_commits(mirror: Mirror, revision: str, refs: list[str]) -> set[str]:
    """Commits reachable from revision but from no upstream ref."""
    return set(mirror.git("rev-list", revision, *[f"^{r}" for r in refs]).split())


def origin_hints(mirror: Mirror, revision: str, tree_paths: list[str]) -> list[str]:
    hints: list[str] = []
    readmes = sorted(
        p
        for p in tree_paths
        if "/" not in p
        and p.lower().startswith(("readme", "notice", "credits", "acknowledg"))
    )
    for path in readmes[:4]:
        blob = mirror.read_blob(revision, path) or b""
        for m in _HINT.finditer(blob[:200_000].decode("utf-8", "replace")):
            hints.append(f"{path}: {' '.join(m.group(0).split())[:140]}")
            if len(hints) >= 6:
                return hints
    return hints


def _empty(hints: list[str]) -> dict[str, Any]:
    return {
        "relationship": "none",
        "upstream_locator": None,
        "upstream_available": None,
        "ancestry": "not_applicable",
        "fork_point": None,
        "fork_only_commits": None,
        "candidate_fork_only_commits": None,
        "inherited_commits": None,
        "upstream_sync_merges": None,
        "candidate_upstream_commits": None,
        "delta_kind": "not_a_fork",
        "delta": None,
        "content_baseline": None,
        "hints": hints,
        "notes": [],
    }


def analyze(
    mirror: Mirror,
    revision: str,
    commits: dict[str, Commit],
    candidate_keys: set[str],
    host_meta: dict[str, Any] | None,
    declared_upstream: str | None,
    tree_paths: list[str],
) -> LineageResult:
    data = _empty(origin_hints(mirror, revision, tree_paths))
    result = LineageResult(data)
    source: str | None = None
    if declared_upstream:
        data["relationship"], source, data["upstream_locator"] = (
            "declared_upstream",
            declared_upstream,
            declared_upstream,
        )
    elif host_meta and host_meta.get("fork"):
        data["relationship"], source, data["upstream_locator"] = (
            "host_fork",
            host_meta.get("parent_clone_url"),
            host_meta.get("parent"),
        )
    elif host_meta and host_meta.get("template"):
        data["relationship"], source, data["upstream_locator"] = (
            "template",
            host_meta.get("template_clone_url"),
            host_meta.get("template"),
        )
    elif mirror.refs(LOCAL_UPSTREAM_PREFIX):
        data["relationship"], data["upstream_locator"] = (
            "local_upstream_remote",
            "local remote 'upstream'",
        )

    if data["relationship"] == "none":
        if data["hints"]:
            result.limitations.append(
                _limitation(
                    "possible_undeclared_upstream",
                    "Repository text mentions an origin ("
                    + "; ".join(data["hints"][:2])
                    + "). Host metadata declares no fork; rerun with --upstream to separate inherited code.",
                )
            )
        return result

    if source:
        try:
            mirror.fetch_upstream(source)
        except GitError as exc:
            return _unavailable(
                result,
                f"Upstream {data['upstream_locator']} could not be fetched ({exc.stderr[:160]}).",
            )
    elif data["relationship"] != "local_upstream_remote":
        return _unavailable(
            result,
            f"Host declares upstream {data['upstream_locator']} but no fetch URL is available.",
        )
    refs = upstream_refs(mirror)
    if not refs:
        return _unavailable(result, "No upstream refs could be resolved.")
    data["upstream_available"] = True

    head = next((r for r in refs if r.endswith(("/head", "/HEAD"))), refs[0])
    try:
        fork_point = mirror.git("merge-base", revision, head).strip()
    except GitError:
        fork_point = ""
    if fork_point:
        _shared_history(
            mirror, revision, commits, candidate_keys, refs, fork_point, result
        )
    elif mirror.is_shallow():
        data["ancestry"], data["delta_kind"] = "unknown", "unknown"
        result.limitations.append(
            _limitation(
                "shallow_ancestry_unknown",
                "History is shallow and no merge base with the upstream is reachable; ancestry is unknown, not absent.",
                "attribution",
            )
        )
    else:
        _content_baseline(mirror, revision, commits, candidate_keys, head, result)
    return result


def _unavailable(result: LineageResult, message: str) -> LineageResult:
    result.data.update(
        {"upstream_available": False, "ancestry": "unknown", "delta_kind": "unknown"}
    )
    result.limitations.append(
        _limitation(
            "upstream_unavailable",
            message
            + " Credit is limited to inspectable history and attribution confidence is lowered.",
            "attribution",
        )
    )
    return result


def _shared_history(
    mirror: Mirror,
    revision: str,
    commits: dict[str, Commit],
    candidate_keys: set[str],
    refs: list[str],
    fork_point: str,
    result: LineageResult,
) -> None:
    data = result.data
    fork_only = fork_only_commits(mirror, revision, refs)
    inherited = set(commits) - fork_only
    result.fork_only = fork_only
    own = [commits[s] for s in fork_only if s in commits and not commits[s].is_merge]
    sync = sum(
        1
        for s in fork_only
        if s in commits
        and commits[s].is_merge
        and any(p in inherited for p in commits[s].parents[1:])
    )
    data.update(
        {
            "ancestry": "shared_history",
            "fork_point": fork_point,
            "fork_only_commits": len(own),
            "candidate_fork_only_commits": sum(
                1 for c in own if c.author_key in candidate_keys
            ),
            "inherited_commits": len(inherited),
            "upstream_sync_merges": sync,
            "candidate_upstream_commits": sum(
                1
                for s in inherited
                if s in commits
                and not commits[s].is_merge
                and commits[s].author_key in candidate_keys
            ),
        }
    )
    _set_delta(
        data,
        own,
        candidate_keys,
        {p for p, _, _ in mirror.ls_tree(fork_point)},
        {p for p, _, _ in mirror.ls_tree(revision)},
    )
    if sync:
        data["notes"].append(
            f"{sync} merge(s) pulled upstream changes into the fork; those commits are inherited, not candidate work."
        )
    if data["candidate_upstream_commits"]:
        data["notes"].append(
            f"{data['candidate_upstream_commits']} candidate-authored commit(s) are part of upstream history (upstream contributions)."
        )


def _content_baseline(
    mirror: Mirror,
    revision: str,
    commits: dict[str, Commit],
    candidate_keys: set[str],
    upstream_head: str,
    result: LineageResult,
) -> None:
    data = result.data
    data["ancestry"] = "no_common_ancestor"
    roots = sorted(
        (c for c in commits.values() if not c.parents),
        key=lambda c: (c.author_time, c.sha),
    )
    root_blobs = {oid for _, oid, _ in mirror.ls_tree(roots[0].sha)} if roots else set()
    best: tuple[float, str] | None = None
    if root_blobs:
        line = mirror.git("rev-list", "--first-parent", upstream_head).split()
        for sha in line[:: max(1, len(line) // _BASELINE_SAMPLES)]:
            overlap = len(
                root_blobs & {oid for _, oid, _ in mirror.ls_tree(sha)}
            ) / len(root_blobs)
            if best is None or overlap > best[0]:
                best = (overlap, sha)
    if best is None or best[0] < _BASELINE_MIN_OVERLAP:
        data["delta_kind"] = "unknown"
        data["notes"].append(
            "No shared history, and no sampled upstream snapshot shares a meaningful fraction of the initial tree."
        )
        result.limitations.append(
            _limitation(
                "no_content_baseline",
                "Upstream relationship declared but no content baseline was found; inherited code cannot be separated.",
                "attribution",
            )
        )
        return
    overlap, baseline = best
    result.baseline_rev = baseline
    root_shas = {c.sha for c in roots}
    later = [c for c in commits.values() if not c.is_merge and c.sha not in root_shas]
    data.update(
        {
            "content_baseline": {"commit": baseline, "blob_overlap": round(overlap, 4)},
            "fork_only_commits": len(later),
            "candidate_fork_only_commits": sum(
                1 for c in later if c.author_key in candidate_keys
            ),
            "inherited_commits": 0,
            "upstream_sync_merges": 0,
            "candidate_upstream_commits": 0,
        }
    )
    data["notes"].append(
        f"No shared history; the initial tree matches upstream snapshot {baseline[:12]} at {overlap:.0%} blob overlap. Lines identical to that snapshot are treated as inherited."
    )
    pseudo = Commit("", (), "", "", "", "", 0, 0, "")
    for line_text in mirror.git(
        "diff", "--numstat", "--no-renames", baseline, revision
    ).splitlines():
        cols = line_text.split("\t")
        if len(cols) == 3:
            pseudo.files.append(
                (
                    cols[2],
                    int(cols[0]) if cols[0].isdigit() else -1,
                    int(cols[1]) if cols[1].isdigit() else -1,
                )
            )
    _set_delta(
        data,
        [pseudo],
        candidate_keys,
        {p for p, _, _ in mirror.ls_tree(baseline)},
        {p for p, _, _ in mirror.ls_tree(revision)},
        candidate_added=sum(c.added() for c in later if c.author_key in candidate_keys),
    )


def _set_delta(
    data: dict[str, Any],
    changes: list[Commit],
    candidate_keys: set[str],
    base_paths: set[str],
    head_paths: set[str],
    candidate_added: int | None = None,
) -> None:
    files: set[str] = set()
    added = deleted = cand = source_added = 0
    for c in changes:
        for path, a, d in c.files:
            files.add(path)
            added += max(a, 0)
            deleted += max(d, 0)
            if classify(path, 0) in {"source", "test"}:
                source_added += max(a, 0)
            if c.author_key in candidate_keys:
                cand += max(a, 0)
    new_paths = sorted(head_paths - base_paths)
    data["delta"] = {
        "files_changed": len(files),
        "lines_added": added,
        "lines_deleted": deleted,
        "candidate_lines_added": cand if candidate_added is None else candidate_added,
        "new_paths": new_paths[:40],
    }
    if not files:
        kind = "unchanged"
    elif all(is_manifest(p) for p in files):
        kind = "dependency_only"
    elif all(
        is_manifest(p) or classify(p, 0) in {"docs", "config", "ci", "build"}
        for p in files
    ):
        kind = "docs_or_config_only"
    elif source_added >= 2000 or (
        base_paths and len(new_paths) >= max(10, len(base_paths) // 5)
    ):
        kind = "substantial"
    else:
        kind = "modified"
    data["delta_kind"] = kind
