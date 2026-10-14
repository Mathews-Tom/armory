"""Hosting-provider adapters.

`GhHost` reuses the user's authenticated GitHub CLI (`gh api`), so no tokens
are handled here. `NullHost` represents offline or unsupported hosts: every
capability reports itself unavailable instead of failing the run.
`FixtureHost` replays a JSON document for deterministic tests and demos.
Every call returns a `HostResult`; failures become recorded limitations.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

_GITHUB_PATTERNS = (
    re.compile(
        r"^https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$"
    ),
    re.compile(r"^git@github\.com:(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?$"),
    re.compile(
        r"^ssh://git@github\.com/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?$"
    ),
)
_SHORTHAND = re.compile(r"^(?P<owner>[A-Za-z0-9][\w.-]*)/(?P<name>[\w.-]+)$")


@dataclass(frozen=True)
class HostRef:
    kind: str
    owner: str | None
    name: str | None
    web_url: str | None
    fetch_url: str | None

    @property
    def slug(self) -> str | None:
        return f"{self.owner}/{self.name}" if self.owner and self.name else None


NO_HOST = HostRef("none", None, None, None, None)


def parse_locator(locator: str, *, allow_shorthand: bool) -> HostRef:
    text = locator.strip()
    for pattern in _GITHUB_PATTERNS:
        m = pattern.match(text)
        if m:
            owner, name = m.group("owner"), m.group("name")
            return HostRef(
                "github",
                owner,
                name,
                f"https://github.com/{owner}/{name}",
                f"https://github.com/{owner}/{name}.git",
            )
    if allow_shorthand:
        m = _SHORTHAND.match(text)
        if m:
            owner, name = m.group("owner"), m.group("name")
            return HostRef(
                "github",
                owner,
                name,
                f"https://github.com/{owner}/{name}",
                f"https://github.com/{owner}/{name}.git",
            )
    if re.match(r"^(https?|ssh|git|file)://", text) or re.match(
        r"^[\w.-]+@[\w.-]+:", text
    ):
        return HostRef("other", None, None, None, text)
    return NO_HOST


@dataclass(frozen=True)
class HostResult:
    ok: bool
    value: Any = None
    error: str | None = None
    complete: bool = True


class HostAdapter(Protocol):
    def authenticated_login(self) -> HostResult: ...

    def repo_metadata(self, slug: str) -> HostResult: ...

    def commit_login(self, slug: str, sha: str) -> HostResult: ...

    def commits_by_login(self, slug: str, login: str) -> HostResult: ...

    def search_issues(self, query: str) -> HostResult: ...

    def check_runs(self, slug: str, sha: str) -> HostResult: ...


def normalize_repo(raw: dict[str, Any]) -> dict[str, Any]:
    def node(key: str) -> dict[str, Any]:
        value = raw.get(key)
        return value if isinstance(value, dict) else {}

    return {
        "fork": bool(raw.get("fork")),
        "parent": node("parent").get("full_name"),
        "source": node("source").get("full_name"),
        "template": node("template_repository").get("full_name"),
        "archived": bool(raw.get("archived")),
        "default_branch": raw.get("default_branch"),
        "parent_clone_url": node("parent").get("clone_url"),
        "template_clone_url": node("template_repository").get("clone_url"),
    }


class NullHost:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def _fail(self) -> HostResult:
        return HostResult(False, None, self.reason, False)

    def authenticated_login(self) -> HostResult:
        return self._fail()

    def repo_metadata(self, slug: str) -> HostResult:
        return self._fail()

    def commit_login(self, slug: str, sha: str) -> HostResult:
        return self._fail()

    def commits_by_login(self, slug: str, login: str) -> HostResult:
        return self._fail()

    def search_issues(self, query: str) -> HostResult:
        return self._fail()

    def check_runs(self, slug: str, sha: str) -> HostResult:
        return self._fail()


class GhHost:
    def __init__(self, gh: str) -> None:
        self.gh = gh

    @classmethod
    def detect(cls) -> GhHost | NullHost:
        gh = shutil.which("gh")
        if gh is None:
            return NullHost(
                "GitHub CLI `gh` is not installed; host metadata unavailable"
            )
        return cls(gh)

    def _api(self, path: str) -> HostResult:
        try:
            proc = subprocess.run(
                [self.gh, "api", "-H", "Accept: application/vnd.github+json", path],
                capture_output=True,
                timeout=45,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return HostResult(False, None, f"timeout calling GitHub API {path}", False)
        if proc.returncode != 0:
            lines = (proc.stderr or proc.stdout).decode(
                "utf-8", "replace"
            ).strip().splitlines() or ["error"]
            return HostResult(
                False,
                None,
                f"GitHub API {path.split('?')[0]}: {lines[-1][:300]}",
                False,
            )
        try:
            return HostResult(
                True, json.loads(proc.stdout.decode("utf-8", "replace") or "null")
            )
        except json.JSONDecodeError:
            return HostResult(
                False, None, f"GitHub API {path.split('?')[0]}: invalid JSON", False
            )

    def authenticated_login(self) -> HostResult:
        res = self._api("user")
        return HostResult(True, res.value.get("login")) if res.ok else res

    def repo_metadata(self, slug: str) -> HostResult:
        res = self._api(f"repos/{slug}")
        return HostResult(True, normalize_repo(res.value)) if res.ok else res

    def commits_by_login(self, slug: str, login: str) -> HostResult:
        """SHAs of commits GitHub attributes to a login (first page, newest first)."""
        res = self._api(f"repos/{slug}/commits?author={quote(login)}&per_page=100")
        if not res.ok:
            return res
        return HostResult(True, [c.get("sha") for c in res.value if c.get("sha")])

    def commit_login(self, slug: str, sha: str) -> HostResult:
        res = self._api(f"repos/{slug}/commits/{sha}")
        if not res.ok:
            return res
        return HostResult(True, (res.value.get("author") or {}).get("login"))

    def search_issues(self, query: str) -> HostResult:
        res = self._api(f"search/issues?per_page=100&q={quote(query)}")
        if not res.ok:
            return res
        items = [
            {
                "number": it.get("number"),
                "title": str(it.get("title", ""))[:200],
                "url": it.get("html_url"),
                "state": it.get("state"),
                "merged": bool((it.get("pull_request") or {}).get("merged_at")),
                "created_at": it.get("created_at"),
            }
            for it in res.value.get("items", [])
        ]
        total = int(res.value.get("total_count", len(items)))
        # Totals are exact; only the itemised list is truncated to the first page.
        complete = not res.value.get("incomplete_results", False)
        return HostResult(True, {"total": total, "items": items}, None, complete)

    def check_runs(self, slug: str, sha: str) -> HostResult:
        res = self._api(f"repos/{slug}/commits/{sha}/check-runs?per_page=100")
        if not res.ok:
            return res
        runs = res.value.get("check_runs", [])
        conclusions = {str(r.get("name")): r.get("conclusion") for r in runs}
        return HostResult(
            True,
            conclusions,
            None,
            int(res.value.get("total_count", len(runs))) <= len(runs),
        )


class FixtureHost:
    """Replays recorded host responses. Unknown lookups behave like missing endpoints."""

    def __init__(self, path: Path) -> None:
        self.data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    def _error(self, method: str) -> HostResult | None:
        message = self.data.get("errors", {}).get(method)
        return HostResult(False, None, str(message), False) if message else None

    def authenticated_login(self) -> HostResult:
        err = self._error("authenticated_login")
        if err:
            return err
        login = self.data.get("authenticated_login")
        return HostResult(
            login is not None,
            login,
            None if login else "no authenticated login recorded",
            login is not None,
        )

    def repo_metadata(self, slug: str) -> HostResult:
        err = self._error("repo_metadata")
        if err:
            return err
        raw = self.data.get("repos", {}).get(slug)
        if raw is None:
            return HostResult(
                False, None, f"GitHub API repos/{slug}: HTTP 404 Not Found", False
            )
        return HostResult(True, normalize_repo(raw))

    def commit_login(self, slug: str, sha: str) -> HostResult:
        err = self._error("commit_login")
        if err:
            return err
        logins: dict[str, str | None] = self.data.get("commit_logins", {})
        return HostResult(True, logins.get(sha))

    def commits_by_login(self, slug: str, login: str) -> HostResult:
        err = self._error("commits_by_login")
        if err:
            return err
        logins: dict[str, str | None] = self.data.get("commit_logins", {})
        return HostResult(True, [sha for sha, who in logins.items() if who == login])

    def search_issues(self, query: str) -> HostResult:
        err = self._error("search_issues")
        if err:
            return err
        for pattern, value in self.data.get("search", {}).items():
            if pattern in query:
                return HostResult(
                    True,
                    {"total": value["total"], "items": value.get("items", [])},
                    None,
                    not value.get("incomplete", False),
                )
        return HostResult(True, {"total": 0, "items": []})

    def check_runs(self, slug: str, sha: str) -> HostResult:
        err = self._error("check_runs")
        if err:
            return err
        runs = self.data.get("check_runs", {}).get(slug)
        if runs is None:
            return HostResult(False, None, "no check runs recorded", False)
        return HostResult(True, runs)
