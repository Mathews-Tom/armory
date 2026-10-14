"""Line-level attribution at a pinned revision.

Each surviving line is classified as one of:

- ``candidate``   authored by a candidate identity
- ``coauthored``  authored by someone else in a commit naming the candidate as co-author
- ``bulk_import`` authored by the candidate in a suspected bulk import commit
- ``inherited``   reachable from upstream history, or identical to the content baseline
- ``unknown``     attributed to a shallow-history boundary commit
- ``other``       authored by another identity
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .gitio import GitError, Mirror
from .identity import email_key, parse_coauthors

CATEGORIES = ("candidate", "coauthored", "bulk_import", "inherited", "unknown", "other")
BLAME_OPTIONS = "git blame --line-porcelain -w --root"


@dataclass
class BlameLine:
    sha: str
    author_key: str
    boundary: bool
    text: str


def blame(
    mirror: Mirror,
    revision: str,
    path: str,
    start: int | None = None,
    end: int | None = None,
) -> list[BlameLine]:
    args = ["blame", "--line-porcelain", "-w", "--root"]
    if start is not None and end is not None:
        args += ["-L", f"{start},{end}"]
    out = mirror.git(*args, revision, "--", path, timeout=900)
    lines: list[BlameLine] = []
    sha = ""
    mail = ""
    boundary = False
    for raw in out.split("\n"):
        if not raw:
            continue
        if raw.startswith("\t"):
            lines.append(BlameLine(sha, email_key(mail), boundary, raw[1:]))
            sha, mail, boundary = "", "", False
        elif not sha:
            sha = raw.split(" ", 1)[0]
        elif raw.startswith("author-mail "):
            mail = raw[len("author-mail ") :].strip().strip("<>")
        elif raw == "boundary":
            boundary = True
    return lines


@dataclass
class AttributionContext:
    mirror: Mirror
    revision: str
    candidate_keys: set[str]
    fork_only: set[str] | None
    baseline_rev: str | None
    bulk_shas: set[str]
    shallow_shas: set[str]
    _coauthors: dict[str, set[str]] = field(default_factory=dict)
    _baseline_cache: dict[str, Counter[str]] = field(default_factory=dict)

    def coauthor_keys(self, sha: str) -> set[str]:
        if sha not in self._coauthors:
            try:
                trailers = self.mirror.git(
                    "show",
                    "-s",
                    "--format=%(trailers:key=Co-authored-by,valueonly,separator=%x1d)",
                    sha,
                )
            except GitError:
                trailers = ""
            self._coauthors[sha] = {email_key(e) for _, e in parse_coauthors(trailers)}
        return self._coauthors[sha]

    def _baseline_lines(self, path: str) -> Counter[str]:
        if path not in self._baseline_cache:
            blob = (
                self.mirror.read_blob(self.baseline_rev, path)
                if self.baseline_rev
                else None
            )
            text = blob.decode("utf-8", "replace") if blob else ""
            self._baseline_cache[path] = Counter(
                line.strip() for line in text.splitlines() if line.strip()
            )
        return self._baseline_cache[path]

    def classify(self, path: str, lines: list[BlameLine]) -> list[str]:
        baseline = Counter(self._baseline_lines(path)) if self.baseline_rev else None
        out: list[str] = []
        for line in lines:
            out.append(self._classify_line(line, baseline))
        return out

    def _classify_line(self, line: BlameLine, baseline: Counter[str] | None) -> str:
        if line.sha in self.shallow_shas:
            return "unknown"
        if self.fork_only is not None and line.sha not in self.fork_only:
            return "inherited"
        if baseline:
            stripped = line.text.strip()
            if not stripped:
                return "inherited"  # whitespace in a file that exists upstream carries no authorship
            if baseline[stripped] > 0:
                baseline[stripped] -= 1
                return "inherited"
        if line.author_key in self.candidate_keys:
            return "bulk_import" if line.sha in self.bulk_shas else "candidate"
        if self.coauthor_keys(line.sha) & self.candidate_keys:
            return "coauthored"
        return "other"

    def attribute(
        self, path: str, start: int | None = None, end: int | None = None
    ) -> Counter[str]:
        lines = blame(self.mirror, self.revision, path, start, end)
        return Counter(self.classify(path, lines))
