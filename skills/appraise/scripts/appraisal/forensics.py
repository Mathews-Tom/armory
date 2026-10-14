"""Per-repository discovery: revision pinning, identity, lineage, ownership, sampling.

All history work happens in the private mirror; see gitio.py for the
read-only guarantee on local checkouts.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import TOOL_NAME, TOOL_VERSION
from .blame import BLAME_OPTIONS, AttributionContext, blame
from .exclusions import (
    CODE_CATEGORIES,
    EXCLUDED,
    Attributes,
    classify,
    language_of,
    subsystem_of,
)
from .gitio import GitError, Mirror, inspect_local, run_git
from .history import Commit, load_history
from .hosting import NO_HOST, HostAdapter, HostRef, parse_locator
from .identity import (
    MATCH_CONFIDENCE,
    RANK,
    Identifier,
    Identity,
    Resolution,
    classify_kind,
    parse_mailmap,
    redact_email,
    resolve,
)
from .injection import scan_text
from .lineage import LineageResult, analyze
from .sampling import (
    content_signals,
    path_signals,
    python_central_modules,
    sample_commits,
    sample_files,
)

_BULK_FILES = 100
_BULK_LINES = 20_000
_MAX_BLOB = 1_000_000
_CONF = ("low", "medium", "high")


class DiscoveryBlocked(RuntimeError):
    """A repository could not be analysed at all (unreachable, not Git, bad revision)."""


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_json(doc: Any) -> str:
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _downgrade(level: str, steps: int = 1) -> str:
    return _CONF[max(0, _CONF.index(level) - steps)]


def _lim(code: str, message: str, impact: str) -> dict[str, str]:
    return {"code": code, "message": message, "impact": impact}


@dataclass
class Source:
    locator: str
    kind: str
    fetch: str
    host: HostRef
    dirty: bool | None = None
    note: str = ""


def resolve_source(locator: str) -> Source:
    path = Path(locator).expanduser()
    if path.exists():
        try:
            local = inspect_local(path)
        except GitError as exc:
            raise DiscoveryBlocked(
                f"{locator}: not a Git repository ({exc.stderr[:200]})"
            ) from exc
        host = (
            parse_locator(local.origin_url, allow_shorthand=False)
            if local.origin_url
            else NO_HOST
        )
        if local.dirty is None:
            note = "bare repository; no working tree"
        elif local.dirty:
            note = (
                "working tree has uncommitted changes; they are excluded from analysis"
            )
        else:
            note = "clean working tree"
        return Source(
            str(local.top_level), "local", str(local.top_level), host, local.dirty, note
        )
    host = parse_locator(locator, allow_shorthand=True)
    if host.fetch_url is None:
        raise DiscoveryBlocked(
            f"{locator}: not an existing path or a recognised Git URL"
        )
    return Source(
        locator, "remote", host.fetch_url, host, None, "remote source; no working tree"
    )


@dataclass
class RepoState:
    """In-memory analysis products shared by discovery stages."""

    repo_id: str
    mirror: Mirror
    revision: str
    commits: dict[str, Commit]
    identities: dict[str, Identity]
    resolution: Resolution
    lineage: LineageResult
    limitations: list[dict[str, str]] = field(default_factory=list)


def expand_self(
    identifiers: list[Identifier], host: HostAdapter
) -> tuple[list[Identifier], list[str]]:
    if not any(i.kind == "self" for i in identifiers):
        return identifiers, []
    notes: list[str] = []
    out = [i for i in identifiers if i.kind != "self"]
    login = host.authenticated_login()
    if login.ok and login.value:
        out.append(Identifier("github", str(login.value), "self_gh_login"))
        notes.append(
            f"`self` resolved to GitHub login {login.value} via the authenticated GitHub CLI."
        )
    try:
        email = run_git(["config", "--global", "--get", "user.email"]).strip()
    except GitError:
        email = ""
    if email:
        out.append(Identifier("email", email, "self_git_config"))
        notes.append("`self` also matched the global git user.email (value withheld).")
    if len(out) == len([i for i in identifiers if i.kind != "self"]):
        notes.append(
            "`self` could not be mapped: no authenticated GitHub login and no global git user.email."
        )
    return out, notes


def build_identities(commits: dict[str, Commit]) -> dict[str, Identity]:
    identities: dict[str, Identity] = {}
    for c in sorted(commits.values(), key=lambda c: (c.commit_time, c.sha)):
        if c.is_merge:
            continue
        ident = identities.get(c.author_key)
        if ident is None:
            ident = identities[c.author_key] = Identity(c.author_key, c.author_email)
        ident.names[c.author_name] += 1
        ident.commits += 1
        ident.latest_sha = c.sha
    for ident in identities.values():
        ident.kind = classify_kind(ident.display, ident.email)
    return identities


def discover_repo(
    index: int,
    spec: dict[str, Any],
    identifiers: list[Identifier],
    run_dir: Path,
    host: HostAdapter,
    budgets: dict[str, int],
    depth: str,
    now: str,
) -> dict[str, Any]:
    repo_id = f"R{index}"
    source = resolve_source(spec["locator"])
    mirror = Mirror.create(run_dir / "mirrors" / f"{repo_id}.git")
    try:
        mirror.fetch_source(source.fetch)
    except GitError as exc:
        raise DiscoveryBlocked(
            f"{spec['locator']}: fetch failed ({exc.stderr[:300]})"
        ) from exc
    if spec.get("revision"):
        revision = mirror.resolve(
            f"refs/appraise/heads/{spec['revision']}"
        ) or mirror.resolve(spec["revision"])
        revision_source = "declared"
    else:
        revision = mirror.resolve(Mirror.CANDIDATE_HEAD)
        revision_source = "head"
    if revision is None:
        raise DiscoveryBlocked(
            f"{spec['locator']}: revision {spec.get('revision') or 'HEAD'} not found"
        )

    limitations: list[dict[str, str]] = []
    host_meta: dict[str, Any] | None = None
    host_block: dict[str, Any] = {
        "available": False,
        "error": None,
        "fork": None,
        "parent": None,
        "source": None,
        "template": None,
        "archived": None,
        "default_branch": None,
    }
    slug = source.host.slug if source.host.kind == "github" else None
    if slug:
        res = host.repo_metadata(slug)
        if res.ok:
            host_meta = res.value
            host_block.update(
                {
                    k: res.value.get(k)
                    for k in (
                        "fork",
                        "parent",
                        "source",
                        "template",
                        "archived",
                        "default_branch",
                    )
                }
            )
            host_block["available"] = True
        else:
            host_block["error"] = res.error
            limitations.append(
                _lim(
                    "host_metadata_unavailable",
                    f"Host metadata unavailable: {res.error}. Fork/template status could not be checked with the host.",
                    "lineage",
                )
            )
    else:
        host_block["error"] = "no supported hosting provider for this locator"
        limitations.append(
            _lim(
                "host_metadata_unavailable",
                "No GitHub remote; fork/template metadata, PRs and reviews are unavailable.",
                "lineage",
            )
        )

    commits = load_history(mirror, revision)
    identities = build_identities(commits)
    if host_block["available"]:
        _link_logins(
            identities,
            host,
            slug,
            budgets["host_identity_lookups"],
            limitations,
            commits,
            [i.value for i in identifiers if i.kind == "github"],
        )
    mailmap_blob = mirror.read_blob(revision, ".mailmap")
    mailmap = (
        parse_mailmap(mailmap_blob.decode("utf-8", "replace")) if mailmap_blob else []
    )
    resolution = resolve(identifiers, identities, mailmap)
    candidate_keys = set(resolution.matched)

    tree = mirror.ls_tree(revision)
    tree_paths = [p for p, _, _ in tree]
    lineage = analyze(
        mirror,
        revision,
        commits,
        candidate_keys,
        host_meta,
        spec.get("upstream"),
        tree_paths,
    )
    limitations.extend(lineage.limitations)
    shallow = mirror.is_shallow()
    if shallow:
        limitations.append(
            _lim(
                "shallow_history",
                "History is shallow; lines attributed to boundary commits are counted as unknown authorship.",
                "attribution",
            )
        )
    if source.dirty:
        limitations.append(
            _lim(
                "uncommitted_changes_excluded",
                "The local checkout has uncommitted changes; only committed history at the pinned revision is analysed.",
                "freshness",
            )
        )

    included_paths, bulk = _bulk_imports(
        commits, candidate_keys, tree, mirror, revision
    )
    ctx = AttributionContext(
        mirror,
        revision,
        candidate_keys,
        lineage.fork_only,
        lineage.baseline_rev,
        bulk,
        mirror.shallow_commits(),
    )
    for c in commits.values():
        ctx._coauthors[c.sha] = c.coauthor_keys
    candidate_paths = {
        p
        for c in commits.values()
        if not c.is_merge
        and (c.author_key in candidate_keys or c.coauthor_keys & candidate_keys)
        for p, _, _ in c.files
    }
    files, exclusions, injection_flags, surviving, blame_info = _ownership(
        mirror,
        revision,
        tree,
        ctx,
        budgets["blame_files"],
        limitations,
        candidate_paths,
    )

    state = RepoState(
        repo_id, mirror, revision, commits, identities, resolution, lineage, limitations
    )
    attribution = _attribution(
        state, candidate_keys, surviving, bulk, included_paths, blame_info, source
    )
    candidate_login = _candidate_login(identifiers, identities, candidate_keys)
    collaboration, host_evidence, ci = _host_signals(
        repo_id,
        slug,
        candidate_login,
        host,
        revision,
        identities,
        candidate_keys,
        commits,
        lineage,
        tree_paths,
        limitations if host_block["available"] else [],
    )

    candidate_commits = [
        c
        for c in commits.values()
        if not c.is_merge
        and c.author_key in candidate_keys
        and c.sha not in bulk
        and (lineage.fork_only is None or c.sha in lineage.fork_only)
    ]
    file_samples = sample_files(
        repo_id, files, budgets["sample_files"], budgets["read_lines_per_item"]
    )
    commit_samples = sample_commits(
        repo_id,
        candidate_commits,
        included_paths,
        budgets["sample_commits"],
        len(file_samples) + 1,
        budgets["read_lines_per_item"],
    )
    notes = []
    if depth == "quick":
        notes.append(
            "quick depth: shallow sample; conclusions are provisional and say so"
        )
    if not candidate_commits:
        notes.append("no candidate-authored, non-inherited commits to sample")

    show_names = resolution.status == "needs_candidate"
    first = min((c.author_time for c in commits.values()), default=None)
    last = max((c.author_time for c in commits.values()), default=None)
    return {
        "repo_id": repo_id,
        "locator": source.locator,
        "source_kind": source.kind,
        "host": {
            "kind": source.host.kind,
            "owner": source.host.owner,
            "name": source.host.name,
            "web_url": source.host.web_url,
        },
        "mirror": str(Path("mirrors") / f"{repo_id}.git"),
        "revision": revision,
        "revision_source": revision_source,
        "revision_time": iso(
            int(mirror.git("show", "-s", "--format=%ct", revision).strip() or 0)
        ),
        "analyzed_at": now,
        "working_tree": {"dirty": source.dirty, "note": source.note},
        "history": {
            "commit_count": len(commits),
            "non_merge_commits": sum(1 for c in commits.values() if not c.is_merge),
            "merge_commits": sum(1 for c in commits.values() if c.is_merge),
            "first_commit_at": iso(first) if first else None,
            "last_commit_at": iso(last) if last else None,
            "is_shallow": shallow,
            "root_commits": sorted(c.sha for c in commits.values() if not c.parents),
        },
        "host_metadata": host_block,
        "lineage": lineage.data,
        "identity": {
            "status": resolution.status,
            "basis_confidence": resolution.basis_confidence,
            "matched": [
                {
                    "key": k,
                    "display": identities[k].display,
                    "email_redacted": redact_email(identities[k].email),
                    "match": how,
                    "commits": identities[k].commits,
                    "login": identities[k].login,
                }
                for k, how in sorted(resolution.matched.items())
            ],
            "unconfirmed_aliases": resolution.unconfirmed,
            "notes": resolution.notes
            + [
                f"{identities[k].display}: {len(identities[k].names)} display names ({', '.join(sorted(identities[k].names))}) share one email and are one identity."
                for k in sorted(resolution.matched)
                if len(identities[k].names) > 1
            ],
        },
        "contributors": [
            {
                "key": k,
                "display": i.display
                if (show_names or k in candidate_keys)
                else f"contributor-{k[3:9]}",
                "email_redacted": redact_email(i.email)
                if (show_names or k in candidate_keys)
                else "withheld",
                "kind": i.kind,
                "commits": i.commits,
                "is_candidate": k in candidate_keys,
                "login": i.login if (show_names or k in candidate_keys) else None,
            }
            for k, i in sorted(
                identities.items(), key=lambda kv: (-kv[1].commits, kv[0])
            )
        ],
        "attribution": attribution,
        "subsystems": _subsystems(files),
        "languages": _languages(files),
        "exclusions": exclusions,
        "files": files,
        "sampling": {
            "depth": depth,
            "files": file_samples,
            "commits": commit_samples,
            "notes": notes,
        },
        "injection_flags": injection_flags,
        "collaboration": collaboration,
        "ci": ci,
        "host_evidence": host_evidence,
        "limitations": limitations,
    }


def _link_logins(
    identities: dict[str, Identity],
    host: HostAdapter,
    slug: str | None,
    budget: int,
    limitations: list[dict[str, str]],
    commits: dict[str, Commit],
    candidate_logins: list[str],
) -> None:
    if not slug:
        return
    # Declared GitHub handles are linked directly, so a candidate outside the most active identities is never missed.
    for login in candidate_logins:
        res = host.commits_by_login(slug, login)
        if res.ok:
            for sha in res.value:
                commit = commits.get(sha)
                if commit is not None and commit.author_key in identities:
                    identities[commit.author_key].login = login
    humans = sorted(
        (i for i in identities.values() if i.kind == "human"),
        key=lambda i: (-i.commits, i.key),
    )
    errors = 0
    for ident in humans[:budget]:
        if ident.login:
            continue
        res = host.commit_login(slug, ident.latest_sha)
        if res.ok:
            ident.login = res.value
        else:
            errors += 1
    if errors:
        limitations.append(
            _lim(
                "host_identity_links_partial",
                f"{errors} identity-to-login lookups failed; those identities are matched by email only.",
                "identity",
            )
        )
    if len(humans) > budget:
        limitations.append(
            _lim(
                "host_identity_links_capped",
                f"Only the {budget} most active of {len(humans)} human identities were linked to host logins.",
                "identity",
            )
        )


def _bulk_imports(
    commits: dict[str, Commit],
    candidate_keys: set[str],
    tree: list[tuple[str, str, int]],
    mirror: Mirror,
    revision: str,
) -> tuple[set[str], set[str]]:
    attrs_blob = mirror.read_blob(revision, ".gitattributes")
    attrs = (
        Attributes.parse(attrs_blob.decode("utf-8", "replace")) if attrs_blob else None
    )
    included = {p for p, _, size in tree if classify(p, size, attrs) not in EXCLUDED}
    bulk: set[str] = set()
    for c in commits.values():
        if c.is_merge:
            continue
        touched = [
            (p, a)
            for p, a, _ in c.files
            if a > 0 and classify(p, 0, attrs) not in EXCLUDED
        ]
        if len(touched) >= _BULK_FILES or sum(a for _, a in touched) >= _BULK_LINES:
            bulk.add(c.sha)
    return included, bulk


def _ownership(
    mirror: Mirror,
    revision: str,
    tree: list[tuple[str, str, int]],
    ctx: AttributionContext,
    blame_budget: int,
    limitations: list[dict[str, str]],
    candidate_paths: set[str],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, object]],
    Counter[str],
    dict[str, Any],
]:
    attrs_blob = mirror.read_blob(revision, ".gitattributes")
    attrs = (
        Attributes.parse(attrs_blob.decode("utf-8", "replace")) if attrs_blob else None
    )
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    pre: list[tuple[str, str, int]] = []
    for path, oid, size in tree:
        cat = classify(path, size, attrs)
        if cat in EXCLUDED:
            counts[cat] += 1
            examples.setdefault(cat, [])
            if len(examples[cat]) < 5:
                examples[cat].append(path)
        elif size > _MAX_BLOB:
            counts["data"] += 1
        else:
            pre.append((path, oid, size))
    contents = dict(mirror.read_blobs([oid for _, oid, _ in pre]))
    entry_modules = _entry_modules(contents, pre)
    candidates: list[tuple[str, str, str]] = []
    for path, oid, size in pre:
        data = contents.get(oid, b"")
        cat = classify(path, size, attrs, head=data[:4096])
        if cat in EXCLUDED:
            counts[cat] += 1
            examples.setdefault(cat, [])
            if len(examples[cat]) < 5:
                examples[cat].append(path)
            continue
        candidates.append((path, oid, cat))

    injection: list[dict[str, object]] = []
    texts: dict[str, str] = {}
    for path, oid, _ in candidates:
        text = contents.get(oid, b"").decode("utf-8", "replace")
        texts[path] = text
        if len(injection) < 50:
            injection.extend(scan_text(path, text, limit=50 - len(injection)))

    # Files the candidate ever touched are blamed first, so a budget cut only affects other people's code.
    ordered = sorted(
        candidates,
        key=lambda c: (
            c[0] not in candidate_paths,
            c[2] not in CODE_CATEGORIES,
            -texts[c[0]].count("\n"),
            c[0],
        ),
    )
    to_blame = ordered if blame_budget == 0 else ordered[:blame_budget]
    blamed: dict[str, Counter[str]] = {}

    def work(path: str) -> tuple[str, Counter[str]]:
        try:
            return path, Counter(ctx.classify(path, blame(mirror, revision, path)))
        except GitError:
            return path, Counter()

    with ThreadPoolExecutor(max_workers=8) as pool:
        for blamed_path, blamed_counts in pool.map(work, [p for p, _, _ in to_blame]):
            blamed[blamed_path] = blamed_counts
    if len(to_blame) < len(candidates):
        limitations.append(
            _lim(
                "blame_budget_reached",
                f"Line ownership computed for {len(to_blame)} of {len(candidates)} eligible files; repository-level shares are estimates.",
                "attribution",
            )
        )

    files: list[dict[str, Any]] = []
    surviving: Counter[str] = Counter()
    categories = {path: cat for path, _, cat in candidates}
    central = python_central_modules(
        {p: t for p, t in texts.items() if categories.get(p) == "source"}
    )
    for path, _, cat in sorted(candidates):
        text = texts[path]
        lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        counter = blamed.get(path)
        if counter is not None and cat in CODE_CATEGORIES | {"docs", "config"}:
            surviving.update(counter)
        signals = sorted(
            set(path_signals(path, cat, entry_modules))
            | (set(content_signals(text)) if cat == "source" else set())
            | ({"central"} if path in central else set())
        )
        files.append(
            {
                "path": path,
                "category": cat,
                "lines": lines,
                "subsystem": subsystem_of(path),
                "candidate_lines": counter["candidate"] if counter else 0,
                "inherited_lines": counter["inherited"] if counter else 0,
                "blamed": counter is not None,
                "candidate_touched": path in candidate_paths,
                "signals": signals,
            }
        )
    exclusions = {
        "counts": dict(sorted(counts.items())),
        "examples": dict(sorted(examples.items())),
    }
    blamed_paths = {p for p, _, _ in to_blame}
    blame_info = {
        "files_eligible": len(candidates),
        "files_blamed": len(to_blame),
        "complete": len(to_blame) == len(candidates),
        "candidate_files_unblamed": sum(
            1
            for p, _, _ in candidates
            if p in candidate_paths and p not in blamed_paths
        ),
        "options": BLAME_OPTIONS,
    }
    return files, exclusions, injection, surviving, blame_info


def _entry_modules(
    contents: dict[str, bytes], pre: list[tuple[str, str, int]]
) -> set[str]:
    """Map `[project.scripts]` targets in pyproject.toml to module paths."""
    by_path = {p: oid for p, oid, _ in pre}
    oid = by_path.get("pyproject.toml")
    if oid is None:
        return set()
    try:
        data = tomllib.loads(contents.get(oid, b"").decode("utf-8", "replace"))
    except tomllib.TOMLDecodeError:
        return set()
    modules: set[str] = set()
    for target in (data.get("project", {}).get("scripts", {}) or {}).values():
        module = str(target).split(":")[0].replace(".", "/")
        for prefix in ("", "src/"):
            for candidate in (
                f"{prefix}{module}.py",
                f"{prefix}{module}/__main__.py",
                f"{prefix}{module}/__init__.py",
            ):
                if candidate in by_path:
                    modules.add(candidate)
    return modules


def _attribution(
    state: RepoState,
    candidate_keys: set[str],
    surviving: Counter[str],
    bulk: set[str],
    included_paths: set[str],
    blame_info: dict[str, Any],
    source: Source,
) -> dict[str, Any]:
    commits = state.commits
    lineage = state.lineage
    own = [
        c
        for c in commits.values()
        if not c.is_merge and (lineage.fork_only is None or c.sha in lineage.fork_only)
    ]
    humans = {k for k, i in state.identities.items() if i.kind == "human"}
    human_commits = [c for c in own if c.author_key in humans]
    cand = [c for c in human_commits if c.author_key in candidate_keys]
    coauth = [
        c
        for c in human_commits
        if c.author_key not in candidate_keys and c.coauthor_keys & candidate_keys
    ]
    added_total = sum(
        c.added(included_paths) for c in human_commits if c.sha not in bulk
    )
    added_cand = sum(c.added(included_paths) for c in cand if c.sha not in bulk)
    total = sum(surviving.values())
    attributable = total - surviving["inherited"] - surviving["unknown"]
    share = (
        round(surviving["candidate"] / attributable, 4) if attributable > 0 else None
    )
    other_human = len(human_commits) - len(cand)
    upstream_only = not cand and bool(lineage.data.get("candidate_upstream_commits"))
    if total == 0:
        role = "unknown"
    elif upstream_only:
        role = "upstream_contributor_only"
    elif share is None or (share == 0 and not cand):
        role = "none"
    elif share >= 0.95 and other_human == 0:
        role = "exclusive_author"
    elif share >= 0.5:
        role = "primary_author"
    elif share >= 0.2:
        role = "significant_contributor"
    elif share > 0 or cand:
        role = "minor_contributor"
    else:
        role = "none"

    confidence = state.resolution.basis_confidence or "low"
    reasons = 0
    if state.mirror.is_shallow():
        reasons += 1
    if (
        lineage.data.get("upstream_available") is False
        or lineage.data.get("delta_kind") == "unknown"
    ):
        reasons += 1
    roots = [c.sha for c in commits.values() if not c.parents]
    imported_by_candidate = any(
        commits[s].author_key in candidate_keys for s in [*roots, *bulk] if s in commits
    )
    if (
        lineage.data["relationship"] == "none"
        and lineage.data["hints"]
        and imported_by_candidate
    ):
        # An undeclared origin only clouds the candidate's lines if the candidate made the initial or bulk import.
        reasons += 1
    if surviving["bulk_import"] > 0.3 * max(
        1, surviving["candidate"] + surviving["bulk_import"]
    ):
        reasons += 1
        state.limitations.append(
            _lim(
                "bulk_import_suspected",
                f"{surviving['bulk_import']} candidate-attributed lines come from bulk commits ({len(bulk)} commit(s) adding ≥{_BULK_FILES} files or ≥{_BULK_LINES} lines); their origin is uncertain.",
                "attribution",
            )
        )
    if blame_info["candidate_files_unblamed"]:
        reasons += 1
    confidence = _downgrade(confidence, reasons)
    if (
        any(MATCH_CONFIDENCE[how] == "low" for how in state.resolution.matched.values())
        and RANK[confidence] > 0
    ):
        confidence = _downgrade(confidence)
    return {
        "candidate_commits": len(cand),
        "candidate_coauthored_commits": len(coauth),
        "human_commits": len(human_commits),
        "candidate_commit_share": round(len(cand) / len(human_commits), 4)
        if human_commits
        else None,
        "surviving_lines": {
            "total": total,
            "candidate": surviving["candidate"],
            "inherited": surviving["inherited"],
            "bulk_import": surviving["bulk_import"],
            "unknown": surviving["unknown"],
        },
        "candidate_surviving_share": share,
        "added_lines": {"total": added_total, "candidate": added_cand},
        "candidate_added_share": round(added_cand / added_total, 4)
        if added_total
        else None,
        "role": role,
        "ai_assisted_commits": sum(1 for c in cand if c.ai_assisted),
        "ai_mentioned_commits": sum(
            1 for c in cand if c.ai_mentioned and not c.ai_assisted
        ),
        "bulk_import_commits": sorted(bulk),
        "attribution_confidence": confidence,
        "blame": blame_info,
    }


def _candidate_login(
    identifiers: list[Identifier], identities: dict[str, Identity], keys: set[str]
) -> str | None:
    for idf in identifiers:
        if idf.kind == "github":
            return idf.value
    logins = Counter(
        {
            identities[k].login: identities[k].commits
            for k in keys
            if identities[k].login
        }
    )
    return str(logins.most_common(1)[0][0]) if logins else None


def _host_signals(
    repo_id: str,
    slug: str | None,
    login: str | None,
    host: HostAdapter,
    revision: str,
    identities: dict[str, Identity],
    candidate_keys: set[str],
    commits: dict[str, Commit],
    lineage: LineageResult,
    tree_paths: list[str],
    limitations: list[dict[str, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    humans = {k for k, i in identities.items() if i.kind == "human"}

    def anchor(key: str) -> str:
        login_name = identities[key].login
        return f"login:{login_name.lower()}" if login_name else key

    candidate_anchors = {anchor(k) for k in candidate_keys}
    clusters = {anchor(k) for k in humans if anchor(k) not in candidate_anchors} | (
        {"candidate"} if candidate_keys else set()
    )
    other_commits = sum(
        1
        for c in commits.values()
        if not c.is_merge
        and c.author_key in humans
        and c.author_key not in candidate_keys
    )
    evidence: list[dict[str, Any]] = []
    prs_authored = prs_merged = reviews = None
    host_complete = False

    def add(kind: str, url: str | None, observation: str, attribution: str) -> None:
        evidence.append(
            {
                "id": f"H-{repo_id}-{len(evidence) + 1:03d}",
                "kind": kind,
                "url": url,
                "observation": observation[:400],
                "candidate_attribution": attribution,
            }
        )

    if slug and login:
        authored = host.search_issues(f"repo:{slug} type:pr author:{login}")
        merged = host.search_issues(f"repo:{slug} type:pr author:{login} is:merged")
        reviewed = host.search_issues(
            f"repo:{slug} type:pr reviewed-by:{login} -author:{login}"
        )
        results = [authored, merged, reviewed]
        host_complete = all(r.ok and r.complete for r in results)
        if authored.ok:
            prs_authored = int(authored.value["total"])
        if merged.ok:
            prs_merged = int(merged.value["total"])
        if reviewed.ok:
            reviews = int(reviewed.value["total"])
            for item in reviewed.value["items"][:10]:
                add(
                    "review",
                    item.get("url"),
                    f"Reviewed pull request #{item.get('number')} '{item.get('title')}' authored by another contributor.",
                    "verified",
                )
        if prs_authored:
            add(
                "pull_request",
                f"https://github.com/{slug}/pulls?q=author%3A{login}",
                f"{prs_authored} pull request(s) authored in {slug}; {prs_merged if prs_merged is not None else 'unknown'} merged (host search).",
                "verified",
            )
        parent = (
            lineage.data.get("upstream_locator")
            if lineage.data["relationship"] in {"host_fork", "template"}
            else None
        )
        if parent and "/" in str(parent) and lineage.data.get("upstream_available"):
            upstream = host.search_issues(
                f"repo:{parent} type:pr author:{login} is:merged"
            )
            if upstream.ok:
                for item in upstream.value["items"][:10]:
                    add(
                        "pull_request",
                        item.get("url"),
                        f"Merged upstream pull request #{item.get('number')} '{item.get('title')}' in {parent}.",
                        "verified",
                    )
        failed = [r.error for r in results if not r.ok]
        if failed:
            limitations.append(
                _lim(
                    "host_activity_unavailable",
                    f"Pull request / review data unavailable: {failed[0]}",
                    "collaboration",
                )
            )
        elif not host_complete:
            limitations.append(
                _lim(
                    "host_activity_incomplete",
                    "Host search results were incomplete or paginated beyond the first page.",
                    "collaboration",
                )
            )
    elif slug and not login:
        limitations.append(
            _lim(
                "candidate_login_unknown",
                "No GitHub login is linked to the candidate; pull requests and reviews were not collected.",
                "collaboration",
            )
        )

    ci_names = {".gitlab-ci.yml", ".travis.yml", "Jenkinsfile", "azure-pipelines.yml"}
    ci_files = sorted(
        p
        for p in tree_paths
        if p.startswith((".github/workflows/", ".circleci/")) or p in ci_names
    )
    check = {"available": False, "conclusions": {}, "error": None}
    if slug:
        runs = host.check_runs(slug, revision)
        if runs.ok:
            check = {
                "available": True,
                "conclusions": dict(sorted(runs.value.items())),
                "error": None,
            }
            tally = Counter(str(v) for v in runs.value.values())
            add(
                "ci_run",
                f"https://github.com/{slug}/commit/{revision}/checks",
                "Host-reported check runs at the analysed revision: "
                + ", ".join(f"{n} {k}" for k, n in sorted(tally.items()))
                + ". Reported by CI, not executed by the appraisal.",
                "not_applicable",
            )
        else:
            check["error"] = runs.error

    if other_commits > 0 or (reviews or 0) > 0:
        opportunity: bool | None = True
    elif host_complete or slug is None:
        opportunity = False
    else:
        opportunity = None
    collaboration = {
        "human_contributors": len(clusters),
        "other_human_commits": other_commits,
        "prs_authored": prs_authored,
        "prs_merged": prs_merged,
        "reviews_given": reviews,
        "opportunity": opportunity,
        "host_complete": host_complete,
    }
    return collaboration, evidence, {"workflow_files": ci_files, "check_runs": check}


def _subsystems(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, list[int]] = {}
    for f in files:
        if f["category"] not in CODE_CATEGORIES:
            continue
        row = agg.setdefault(f["subsystem"], [0, 0, 0])
        row[0] += 1
        row[1] += f["lines"]
        row[2] += f["candidate_lines"]
    return [
        {
            "name": name,
            "files": n,
            "lines": lines,
            "candidate_lines": cand,
            "share": round(cand / lines, 4) if lines else None,
        }
        for name, (n, lines, cand) in sorted(
            agg.items(), key=lambda kv: (-kv[1][1], kv[0])
        )
    ]


def _languages(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, list[int]] = {}
    for f in files:
        lang = language_of(f["path"])
        if lang is None or f["category"] not in CODE_CATEGORIES:
            continue
        row = agg.setdefault(lang, [0, 0])
        row[0] += f["lines"]
        row[1] += f["candidate_lines"]
    return [
        {"language": k, "lines": v[0], "candidate_lines": v[1]}
        for k, v in sorted(agg.items(), key=lambda kv: (-kv[1][0], kv[0]))
    ]


def candidate_block(
    identifiers: list[Identifier],
    display: str | None,
    repos: list[dict[str, Any]],
    notes: list[str],
) -> dict[str, Any]:
    statuses = [r["identity"]["status"] for r in repos]
    if "needs_candidate" in statuses:
        status = "needs_candidate"
    elif all(s == "unresolved" for s in statuses):
        status = "unresolved"
    elif "provisional" in statuses:
        status = "provisional"
    else:
        status = "resolved"
    return {
        "display": display
        or next((i.value for i in identifiers if i.kind == "github"), None)
        or next((i.value for i in identifiers if i.kind == "name"), None),
        "status": status,
        "identifiers": [
            {
                "kind": i.kind,
                "value": i.value if i.kind != "email" else redact_email(i.value),
                "source": i.source,
            }
            for i in identifiers
        ],
        "notes": notes,
    }


def tool_block() -> dict[str, str]:
    return {"name": TOOL_NAME, "version": TOOL_VERSION}
