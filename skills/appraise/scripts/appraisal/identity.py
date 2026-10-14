"""Candidate identity resolution.

Identities are keyed by email address. Names never merge identities on their
own: a different email with the same display name stays an *unconfirmed alias*
until corroborated by the hosting provider (same linked login), a repository
`.mailmap` (repository-claimed), or an identifier the requester declared.
Raw email addresses never leave this module's callers' memory; outputs carry
a digest key and a redacted form.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field

_BOT_NAMES = re.compile(
    r"(\[bot\]$|^dependabot|^renovate|^github-actions|^pre-commit-ci|^snyk-bot|^greenkeeper|^mergify|^imgbot|^allcontributors|^codecov|^semantic-release-bot|^web-flow$)",
    re.IGNORECASE,
)
_BOT_EMAILS = re.compile(
    r"(\[bot\]@|^bot@|^noreply@github\.com$|^actions@github\.com$|@dependabot\.com$|@renovateapp\.com$)",
    re.IGNORECASE,
)
_AUTOMATION_EMAIL = re.compile(
    r"^(no-?reply|automation|ci|build|deploy|bot)@", re.IGNORECASE
)
_GITHUB_NOREPLY = re.compile(
    r"^(?:(\d+)\+)?([A-Za-z0-9-]+)@users\.noreply\.github\.com$", re.IGNORECASE
)
_AI_COAUTHOR = re.compile(
    r"(claude|anthropic|copilot|codex|openai|chatgpt|gpt-?\d|gemini|cursor|devin|aider|openhands|sweep|codeium|windsurf|jules)",
    re.IGNORECASE,
)
_TRAILER = re.compile(r"^\s*(?P<name>.*?)\s*<(?P<email>[^>]+)>\s*$")

MATCH_CONFIDENCE = {
    "declared_email": "high",
    "github_noreply": "high",
    "host_linked": "high",
    "mailmap": "medium",
    "sole_contributor": "medium",
    "declared_name": "low",
}
RANK = {"low": 0, "medium": 1, "high": 2}


def email_key(email: str) -> str:
    return "id:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]


def redact_email(email: str) -> str:
    local, _, domain = email.strip().partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain.lower()}"


@dataclass
class Identity:
    key: str
    email: str
    names: Counter[str] = field(default_factory=Counter)
    commits: int = 0
    kind: str = "human"
    login: str | None = None
    latest_sha: str = ""

    @property
    def display(self) -> str:
        if not self.names:
            return redact_email(self.email)
        return min(self.names.items(), key=lambda kv: (-kv[1], kv[0]))[0]


@dataclass(frozen=True)
class Identifier:
    kind: str
    value: str
    source: str = "declared"


@dataclass
class Resolution:
    status: str
    matched: dict[str, str]
    basis_confidence: str | None
    unconfirmed: list[dict[str, object]]
    notes: list[str]


def classify_kind(name: str, email: str) -> str:
    if _BOT_NAMES.search(name.strip()) or _BOT_EMAILS.search(email.strip()):
        return "bot"
    if _AUTOMATION_EMAIL.search(email.strip()) and not _GITHUB_NOREPLY.match(
        email.strip()
    ):
        return "automation_suspected"
    return "human"


def parse_coauthors(trailers: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for chunk in re.split(r"[\x1d\n]", trailers):
        m = _TRAILER.match(chunk)
        if m:
            found.append((m.group("name"), m.group("email").strip().lower()))
    return found


def is_ai_coauthor(name: str, email: str) -> bool:
    return bool(_AI_COAUTHOR.search(name) or _AI_COAUTHOR.search(email.split("@")[-1]))


def parse_mailmap(text: str) -> list[tuple[str, str]]:
    """Return (canonical_email, alias_email) links declared by `.mailmap`."""
    links: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        emails = re.findall(r"<([^>]+)>", line)
        if len(emails) == 2:
            links.append((emails[0].strip().lower(), emails[1].strip().lower()))
    return links


def parse_candidate(spec: str | None) -> list[Identifier]:
    """Parse `github:H,email:a@b,name:Full Name,self`; a bare token is a handle or an email."""
    if not spec:
        return []
    out: list[Identifier] = []
    for token in (t.strip() for t in spec.split(",")):
        if not token:
            continue
        if token == "self":
            out.append(Identifier("self", "self"))
            continue
        kind, sep, value = token.partition(":")
        if not sep:
            kind, value = (
                ("email", token) if "@" in token else ("github", token.lstrip("@"))
            )
        kind = kind.strip().lower()
        if kind not in {"github", "email", "name"}:
            raise ValueError(f"unknown candidate identifier kind: {kind!r}")
        if not value.strip():
            raise ValueError(f"empty candidate identifier: {token!r}")
        out.append(Identifier(kind, value.strip()))
    return out


def resolve(
    identifiers: list[Identifier],
    identities: dict[str, Identity],
    mailmap: list[tuple[str, str]],
) -> Resolution:
    humans = {k: i for k, i in identities.items() if i.kind == "human"}
    matched: dict[str, str] = {}
    notes: list[str] = []

    if not identifiers:
        clusters = _clusters(humans)
        if len(clusters) == 1:
            for key in next(iter(clusters.values())):
                matched[key] = "sole_contributor"
            notes.append(
                "No candidate declared; exactly one human contributor exists, so attribution proceeds provisionally on that identity."
            )
            return Resolution("provisional", matched, "medium", [], notes)
        notes.append(
            f"No candidate declared and {len(clusters)} human contributor identities exist; candidate identity is required."
        )
        return Resolution("needs_candidate", {}, None, [], notes)

    for key, ident in humans.items():
        email = ident.email.lower()
        noreply = _GITHUB_NOREPLY.match(email)
        for idf in identifiers:
            value = idf.value.lower()
            if idf.kind == "email" and email == value:
                _better(matched, key, "declared_email")
            elif idf.kind == "github":
                if noreply and noreply.group(2).lower() == value:
                    _better(matched, key, "github_noreply")
                if ident.login and ident.login.lower() == value:
                    _better(matched, key, "host_linked")
            elif idf.kind == "name" and any(
                n.casefold() == idf.value.casefold() for n in ident.names
            ):
                _better(matched, key, "declared_name")

    by_email = {i.email.lower(): k for k, i in humans.items()}
    changed = True
    while changed:
        changed = False
        for canonical, alias in mailmap:
            ck, ak = by_email.get(canonical), by_email.get(alias)
            if ck and ak and (ck in matched) != (ak in matched):
                matched[ak if ck in matched else ck] = "mailmap"
                changed = True

    if not matched:
        notes.append(
            "None of the declared identifiers matched a commit author in this repository."
        )
        return Resolution(
            "unresolved", {}, None, _unconfirmed(identifiers, humans, matched), notes
        )

    weight: Counter[str] = Counter()
    for key, how in matched.items():
        weight[MATCH_CONFIDENCE[how]] += max(humans[key].commits, 1)
    total = sum(weight.values())
    if weight["high"] / total >= 0.5:
        basis = "high"
    elif (weight["high"] + weight["medium"]) / total >= 0.5:
        basis = "medium"
    else:
        basis = "low"
    if "declared_name" in matched.values():
        notes.append(
            "Some identities matched only by a declared display name; their attribution confidence is low."
        )
    return Resolution(
        "resolved", matched, basis, _unconfirmed(identifiers, humans, matched), notes
    )


def _better(matched: dict[str, str], key: str, how: str) -> None:
    current = matched.get(key)
    if current is None or RANK[MATCH_CONFIDENCE[how]] > RANK[MATCH_CONFIDENCE[current]]:
        matched[key] = how


def _clusters(humans: dict[str, Identity]) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = {}
    for key, ident in humans.items():
        anchor = f"login:{ident.login.lower()}" if ident.login else key
        clusters.setdefault(anchor, []).append(key)
    return clusters


def _unconfirmed(
    identifiers: list[Identifier], humans: dict[str, Identity], matched: dict[str, str]
) -> list[dict[str, object]]:
    names = {n.casefold() for k in matched for n in humans[k].names}
    names |= {i.value.casefold() for i in identifiers if i.kind == "name"}
    handles = {i.value.lower() for i in identifiers if i.kind == "github"}
    out: list[dict[str, object]] = []
    for key, ident in sorted(humans.items()):
        if key in matched:
            continue
        reason = None
        if any(n.casefold() in names for n in ident.names):
            reason = "same display name as a candidate identity, different email, no corroborating link"
        elif ident.email.split("@")[0].lower() in handles:
            reason = (
                "email local part equals the candidate handle, no corroborating link"
            )
        if reason:
            out.append(
                {
                    "key": key,
                    "display": ident.display,
                    "email_redacted": redact_email(ident.email),
                    "reason": reason,
                    "commits": ident.commits,
                }
            )
    return out


def weakest(confidences: list[str]) -> str:
    return min(confidences, key=lambda c: RANK[c]) if confidences else "low"
