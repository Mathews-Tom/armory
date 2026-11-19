#!/usr/bin/env python3
"""Collect one Reddit thread through the existing agent-browser CLI, without OAuth."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_HOSTS = {
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "new.reddit.com",
    "np.reddit.com",
    "m.reddit.com",
}
_SESSION_ENV = "REDDIT_BROWSER_SESSION"
_GATE_REASONS = {
    "network_security",
    "human_verification",
    "rate_limit",
    "login_required",
    "private_or_banned",
}
_ENV_BLOCK_REASONS = {
    "network_security",
    "human_verification",
    "rate_limit",
    "login_required",
    "access_gate",
}
_DOM = Path(__file__).with_name("reddit_dom.js").read_text(encoding="utf-8")


class CollectionError(Exception):
    """A browser boundary failed; collected evidence must remain partial."""


def post_id(url: str) -> str:
    """Accept public Reddit permalinks, not arbitrary browser destinations."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or "\\" in url
    ):
        raise ValueError("Use an HTTPS Reddit post permalink without credentials")
    if parsed.hostname == "redd.it":
        match = re.fullmatch(r"/([a-z0-9]+)/?", parsed.path, re.IGNORECASE)
    elif parsed.hostname in _HOSTS:
        match = re.match(
            r"^/(?:r/[A-Za-z0-9_]+/)?comments/([a-z0-9]+)(?:/|\.json$|$)",
            parsed.path,
            re.IGNORECASE,
        )
    else:
        match = None
    if not match:
        raise ValueError(
            "Expected a Reddit post permalink, not a listing or share link"
        )
    return "t3_" + match[1].lower()


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CollectionError("Browser returned a non-object response")
    return dict(value)


def _excerpt(value: Any, limit: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit] if cleaned else None


def _extract_links(text: str | None) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for match in re.finditer(r"https?://[^\s<>\"'\]]+", text):
        url = match.group(0)
        while url:
            trimmed = url.rstrip(".,;:!?")
            if trimmed.endswith(")") and trimmed.count(")") > trimmed.count("("):
                trimmed = trimmed[:-1]
            if trimmed == url:
                break
            url = trimmed
        if url and url not in found:
            found.append(url)
    return found


def _iso_utc(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), UTC).isoformat()
    return None


def parse_json_listing(identity: str, payload: Any, source_url: str) -> dict[str, Any]:
    """Convert a Reddit post/comment Listing JSON array into a Thread.merge snapshot."""
    if not isinstance(payload, list) or len(payload) < 2:
        raise CollectionError(
            "Unsupported or unrendered Reddit JSON; expected [post, comments] listing"
        )
    post_listing = _object(payload[0])
    post_children = _object(post_listing.get("data")).get("children")
    if not isinstance(post_children, list) or not post_children:
        raise CollectionError("Reddit JSON listing contains no post record")
    post_node = _object(post_children[0])
    post_data = _object(post_node.get("data"))
    raw_post_id = post_data.get("name")
    if not isinstance(raw_post_id, str) and isinstance(post_data.get("id"), str):
        raw_post_id = f"t3_{post_data['id'].lower()}"
    if not isinstance(raw_post_id, str) or raw_post_id.lower() != identity:
        raise CollectionError("Reddit JSON post ID does not match requested post")
    raw_body = post_data.get("selftext")
    body_text = raw_body.strip() if isinstance(raw_body, str) else ""
    num_comments = post_data.get("num_comments")
    reported_count = (
        num_comments
        if isinstance(num_comments, int) and not isinstance(num_comments, bool)
        else None
    )
    score = post_data.get("score")
    post = {
        "id": identity,
        "title": post_data.get("title"),
        "author": post_data.get("author"),
        "subreddit": post_data.get("subreddit_name_prefixed"),
        "created_at": _iso_utc(post_data.get("created_utc")),
        "score": str(score) if score is not None else None,
        "body_text": body_text or None,
        "links": _extract_links(body_text or None),
        "content_url": post_data.get("url"),
        "body_expanded": True,
        "reported_comment_count": reported_count,
    }
    comment_listing = _object(payload[1])
    root_children = _object(comment_listing.get("data")).get("children")
    if not isinstance(root_children, list):
        raise CollectionError("Reddit JSON listing contains invalid comments")
    comments: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    seen_action_keys: set[str] = set()
    post_short = identity[3:]
    stack: list[Any] = list(reversed(root_children))
    while stack:
        item = stack.pop()
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        if kind == "t1":
            raw_cid = data.get("name")
            if not isinstance(raw_cid, str) and isinstance(data.get("id"), str):
                raw_cid = f"t1_{data['id']}"
            if not isinstance(raw_cid, str):
                raise CollectionError("Reddit comment is missing its stable fullname")
            cid = raw_cid.lower()
            if not re.fullmatch(r"t1_[a-z0-9]+", cid):
                raise CollectionError("Reddit comment is missing its stable fullname")
            link_id = data.get("link_id")
            if isinstance(link_id, str) and link_id.lower() != identity:
                continue
            raw_parent = data.get("parent_id")
            parent_id = raw_parent.lower() if isinstance(raw_parent, str) else None
            c_body = data.get("body")
            c_text = c_body.strip() if isinstance(c_body, str) else ""
            c_score = data.get("score")
            comments.append(
                {
                    "id": cid,
                    "parent_id": parent_id,
                    "author": data.get("author"),
                    "created_at": _iso_utc(data.get("created_utc")),
                    "score": str(c_score) if c_score is not None else None,
                    "body_text": c_text or None,
                    "links": _extract_links(c_text or None),
                    "permalink": (
                        f"https://www.reddit.com/comments/{post_short}"
                        f"/comment/{cid[3:]}/"
                    ),
                }
            )
            replies = data.get("replies")
            if isinstance(replies, dict):
                reply_data = replies.get("data")
                if isinstance(reply_data, dict):
                    reply_children = reply_data.get("children")
                    if isinstance(reply_children, list):
                        stack.extend(reversed(reply_children))
        elif kind == "more":
            more_children = data.get("children")
            if isinstance(more_children, list) and more_children:
                for child_id in more_children:
                    if not isinstance(child_id, str):
                        continue
                    short = child_id.lower()
                    if not re.fullmatch(r"[a-z0-9]+", short):
                        continue
                    key = f"more:{short}"
                    if key in seen_action_keys:
                        continue
                    seen_action_keys.add(key)
                    actions.append(
                        {
                            "kind": "navigate",
                            "key": key,
                            "comment_id": f"t1_{short}",
                            "href": (
                                f"https://www.reddit.com/comments/{post_short}"
                                f"/_/{short}.json?limit=500&sort=old&raw_json=1"
                            ),
                        }
                    )
            else:
                raw_parent = data.get("parent_id")
                if isinstance(raw_parent, str) and re.fullmatch(
                    r"t1_[a-z0-9]+", raw_parent, re.IGNORECASE
                ):
                    parent_short = raw_parent[3:].lower()
                    key = f"continue:{parent_short}"
                    if key not in seen_action_keys:
                        seen_action_keys.add(key)
                        actions.append(
                            {
                                "kind": "navigate",
                                "key": key,
                                "href": (
                                    f"https://www.reddit.com/comments/{post_short}"
                                    f"/_/{parent_short}.json"
                                    "?limit=500&sort=old&raw_json=1"
                                ),
                            }
                        )
    return {
        "source_url": source_url,
        "blocked": False,
        "gate_reason": None,
        "unavailable": False,
        "error": None,
        "post": post,
        "comments": comments,
        "actions": actions,
    }


def resolve_session(
    cli_session: str | None, env_session: str | None = None
) -> tuple[str | None, str]:
    """Resolve an optional borrowed session from CLI or REDDIT_BROWSER_SESSION."""
    if cli_session is not None:
        cleaned = cli_session.strip()
        if not cleaned:
            raise ValueError("--session must not be empty")
        return cleaned, "cli"
    raw_env = os.environ.get(_SESSION_ENV) if env_session is None else env_session
    cleaned = raw_env.strip() if raw_env else ""
    if cleaned:
        return cleaned, "env"
    return None, "ephemeral"


class Browser:
    def __init__(self, session: str, deadline: float) -> None:
        executable = shutil.which("agent-browser")
        if not executable:
            raise CollectionError("agent-browser is required; see references/reddit.md")
        self.command = [executable, "--session", session, "--json"]
        self.deadline = deadline

    def call(self, *args: str, script: str | None = None) -> dict[str, Any]:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CollectionError("Time budget reached")
        try:
            result = subprocess.run(
                [*self.command, *args],
                input=script,
                text=True,
                capture_output=True,
                timeout=min(40, remaining),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CollectionError(
                f"Browser command failed: {type(exc).__name__}"
            ) from exc
        try:
            envelope = _object(json.loads(result.stdout))
        except (ValueError, CollectionError) as exc:
            raise CollectionError("agent-browser returned invalid JSON") from exc
        if result.returncode or envelope.get("success") is not True:
            raise CollectionError(
                str(envelope.get("error") or "Browser command failed")
            )
        if envelope.get("warning"):
            print(f"agent-browser: {envelope['warning']}", file=sys.stderr)
        return _object(envelope.get("data"))

    def snapshot(
        self, identity: str, action: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = json.dumps({"postId": identity, "action": action})
        return _object(
            self.call("eval", "--stdin", script=f"({_DOM})({payload})").get("result")
        )

    def wait_for_post(self, identity: str) -> None:
        payload = json.dumps({"postId": identity, "mode": "ready"})
        self.call("wait", "--fn", f"({_DOM})({payload})")

    def wait_for_json(self, identity: str) -> None:
        payload = json.dumps({"postId": identity, "mode": "json_ready"})
        self.call("wait", "--fn", f"({_DOM})({payload})")

    def json_snapshot(self, identity: str) -> dict[str, Any]:
        payload = json.dumps({"postId": identity, "mode": "json"})
        return _object(
            self.call("eval", "--stdin", script=f"({_DOM})({payload})").get("result")
        )


class Thread:
    def __init__(
        self,
        identity: str,
        max_comments: int,
        *,
        session_mode: str = "ephemeral",
        backend: str = "dom",
    ) -> None:
        self.identity = identity
        self.max_comments = max_comments
        self.session_mode = session_mode
        self.backend = backend
        self.post: dict[str, Any] | None = None
        self.comments: dict[str, dict[str, Any]] = {}
        self.issues: list[str] = []
        self.pending: list[dict[str, Any]] = []
        self.continuations: list[str] = []
        self.pages: list[str] = []
        self.actions = 0
        self.status = "error"
        self.block_reason: str | None = None
        self.gate_detail: str | None = None

    def merge(self, snapshot: dict[str, Any]) -> None:
        source = str(snapshot.get("source_url", "")).strip()
        if snapshot.get("blocked"):
            if source and source not in self.pages:
                self.pages.append(source)
            self.status = "blocked"
            raw_reason = snapshot.get("gate_reason")
            reason = (
                raw_reason
                if isinstance(raw_reason, str) and raw_reason in _GATE_REASONS
                else None
            )
            self.block_reason = reason or "access_gate"
            detail = _excerpt(snapshot.get("error")) or _excerpt(
                snapshot.get("page_title")
            )
            if detail:
                self.gate_detail = detail
            suffix = f" ({reason})" if reason else ""
            raise CollectionError(
                f"Reddit access/verification gate{suffix}; no bypass attempted"
            )
        if snapshot.get("unavailable"):
            if source and source not in self.pages:
                self.pages.append(source)
            detail = _excerpt(snapshot.get("error")) or _excerpt(
                snapshot.get("page_title")
            )
            if detail:
                self.gate_detail = detail
            raise CollectionError("Reddit post unavailable (not_found)")
        if post_id(source) != self.identity:
            raise CollectionError("Browser left the requested Reddit post")
        if source not in self.pages:
            self.pages.append(source)
        incoming = snapshot.get("post")
        if not isinstance(incoming, dict) or incoming.get("id") != self.identity:
            detail = _excerpt(snapshot.get("error")) or _excerpt(
                snapshot.get("page_title")
            )
            if detail:
                self.gate_detail = detail
            raise CollectionError(
                "Unsupported or unrendered Reddit page; no post extracted"
            )
        if self.post is None:
            self.post = dict(incoming)
        else:
            replace_body = bool(incoming.get("body_text")) and (
                not self.post.get("body_text")
                or incoming.get("body_expanded")
                or not self.post.get("body_expanded")
            )
            for key, value in incoming.items():
                if key in ("body_text", "links", "body_expanded") and not replace_body:
                    continue
                if value is not None:
                    self.post[key] = value
        comments = snapshot.get("comments")
        if not isinstance(comments, list):
            raise CollectionError("Browser returned invalid comments")
        for raw in comments:
            comment = _object(raw)
            identity = comment.get("id")
            if not isinstance(identity, str) or not re.fullmatch(
                r"t1_[a-z0-9]+", identity
            ):
                raise CollectionError("Reddit comment is missing its stable fullname")
            if (
                identity not in self.comments
                and len(self.comments) >= self.max_comments
            ):
                self.issues.append("Comment budget reached")
                break
            previous = self.comments.get(identity)
            if previous is None or comment.get("body_text"):
                self.comments[identity] = comment
        actions = snapshot.get("actions")
        if not isinstance(actions, list):
            raise CollectionError("Browser returned invalid expansion controls")
        self.pending = [_object(action) for action in actions]

    def finish(self) -> None:
        if self.post:
            reported = self.post.get("reported_comment_count")
            if isinstance(reported, int) and reported > len(self.comments):
                self.issues.append("Reported comment count exceeds captured comments")
            if not self.post.get("body_expanded"):
                self.issues.append("Post body still has a Read more control")
        resolved: set[str] = set()
        for identity, comment in self.comments.items():
            parent = comment.get("parent_id")
            if parent != self.identity and parent not in self.comments:
                self.issues.append(f"Unresolved parent for {identity}: {parent}")
            if not comment.get("body_text"):
                self.issues.append(f"Unavailable comment body: {identity}")
            seen = {identity}
            while parent in self.comments and parent not in resolved:
                if parent in seen:
                    self.issues.append(f"Cyclic comment parent: {identity}")
                    break
                seen.add(parent)
                parent = self.comments[parent].get("parent_id")
            resolved.update(seen)
        self.issues = list(dict.fromkeys(self.issues))
        if self.status != "blocked":
            self.status = (
                "partial"
                if self.post and self.issues
                else ("browser_exhausted" if self.post else "error")
            )

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source": "reddit_browser",
            "backend": self.backend,
            "post_id": self.identity,
            "source_url": f"https://www.reddit.com/comments/{self.identity[3:]}/",
            "captured_at": datetime.now(UTC).isoformat(),
            "status": self.status,
            "block_reason": self.block_reason,
            "gate_detail": self.gate_detail,
            "session_mode": self.session_mode,
            "complete": False,
            "completeness_note": "Browser-visible capture, not proof of all Reddit comments",
            "captured_comment_count": len(self.comments),
            "post": self.post,
            "comments": list(self.comments.values()),
            "issues": self.issues,
            "pending_controls": self.pending,
            "visited_pages": self.pages,
            "unvisited_continuations": self.continuations,
            "expansion_actions": self.actions,
        }


def collect_json(browser: Browser, thread: Thread, max_actions: int) -> None:
    root = (
        f"https://www.reddit.com/comments/{thread.identity[3:]}.json"
        "?limit=500&sort=old&raw_json=1"
    )
    queue: list[tuple[str, str | None]] = []
    visited = {root}
    current = root
    while True:
        browser.call("open", current)
        browser.wait_for_json(thread.identity)
        raw = browser.json_snapshot(thread.identity)
        if raw.get("blocked") or raw.get("unavailable"):
            thread.merge(raw)
        payload = raw.get("payload")
        if payload is None:
            detail = _excerpt(raw.get("error")) or _excerpt(raw.get("page_title"))
            if detail:
                thread.gate_detail = detail
            raise CollectionError(
                "Unsupported or unrendered Reddit JSON; no post extracted"
            )
        source_url = str(raw.get("source_url") or current)
        snapshot = parse_json_listing(thread.identity, payload, source_url)
        thread.merge(snapshot)
        if thread.issues:
            return
        for action in thread.pending:
            if action.get("kind") != "navigate":
                continue
            href = str(action.get("href", ""))
            if post_id(href) != thread.identity:
                raise CollectionError("Continuation leaves the requested post")
            target_comment = action.get("comment_id")
            if isinstance(target_comment, str) and target_comment in thread.comments:
                continue
            if href not in visited and all(existing != href for existing, _ in queue):
                queue.append(
                    (href, target_comment if isinstance(target_comment, str) else None)
                )
        while queue and queue[0][1] is not None and queue[0][1] in thread.comments:
            queue.pop(0)
        thread.continuations = [href for href, _ in queue]
        if not queue:
            thread.pending = []
            return
        if thread.actions >= max_actions:
            thread.issues.append("Expansion action budget reached")
            thread.pending = [{"kind": "navigate", "href": queue[0][0]}]
            return
        thread.actions += 1
        current, _ = queue.pop(0)
        visited.add(current)
        thread.continuations = [href for href, _ in queue]


def collect(browser: Browser, thread: Thread, max_actions: int) -> None:
    root = f"https://www.reddit.com/comments/{thread.identity[3:]}/?sort=old"
    browser.call("open", root)
    browser.wait_for_post(thread.identity)
    queue = thread.continuations
    visited = {root}
    scrolled = False
    attempted: set[str] = set()
    while True:
        snapshot = browser.snapshot(thread.identity)
        previous_count = len(thread.comments)
        thread.merge(snapshot)
        if len(thread.comments) > previous_count:
            attempted.clear()
        if thread.issues:
            return
        clickable: list[dict[str, Any]] = []
        for action in thread.pending:
            if action.get("kind") == "navigate":
                href = str(action.get("href", ""))
                if post_id(href) != thread.identity:
                    raise CollectionError("Continuation leaves the requested post")
                if href not in visited and href not in queue:
                    queue.append(href)
            else:
                clickable.append(action)
        if clickable:
            action = clickable[0]
            key = str(action.get("key"))
            if key in attempted:
                thread.issues.append("Expansion stalled; a supported control remains")
                return
            attempted.add(key)
        elif not scrolled:
            action = {"kind": "scroll"}
            scrolled = True
        elif queue:
            action = {"kind": "navigate", "href": queue[0]}
        else:
            thread.pending = []
            return
        if thread.actions >= max_actions:
            thread.issues.append("Expansion action budget reached")
            thread.pending = [action, *thread.pending]
            return
        thread.actions += 1
        if action["kind"] == "navigate":
            href = action["href"]
            visited.add(href)
            browser.call("open", href)
            browser.wait_for_post(thread.identity)
            queue.pop(0)
            scrolled = False
            attempted.clear()
        else:
            browser.snapshot(thread.identity, action)


def markdown(document: dict[str, Any]) -> str:
    lines = [
        "# Reddit thread capture",
        "",
        f"Status: {document['status']}",
    ]
    if document.get("block_reason"):
        lines.append(f"Block reason: {document['block_reason']}")
    lines.extend(
        [
            document["completeness_note"],
            "",
            document["source_url"],
            "",
        ]
    )
    lines.extend(f"- {issue}" for issue in document["issues"])
    if document.get("gate_detail"):
        lines.extend(
            [
                "",
                "Gate excerpt (untrusted page text):",
                *["> " + line for line in str(document["gate_detail"]).splitlines()],
            ]
        )
    post = document["post"]
    if post:
        lines.extend(
            [
                "",
                "## Post",
                "",
                f"ID: {post['id']}",
                f"Author: {post.get('author')}",
                "",
            ]
        )
        for value in (post.get("title"), post.get("body_text")):
            lines.extend(
                "> " + line for line in str(value or "[unavailable]").splitlines()
            )
            lines.append("")
    comments = {comment["id"]: comment for comment in document["comments"]}
    children: dict[str, list[str]] = {}
    for identity, comment in comments.items():
        parent = comment.get("parent_id")
        key = (
            parent
            if parent in comments or parent == document["post_id"]
            else "unresolved"
        )
        children.setdefault(key, []).append(identity)
    lines.extend(["## Comments", ""])
    stack = [
        (identity, 0) for identity in reversed(children.get(document["post_id"], []))
    ]
    emitted: set[str] = set()
    while stack:
        identity, depth = stack.pop()
        if identity in emitted:
            continue
        emitted.add(identity)
        comment = comments[identity]
        lines.extend(
            [
                f"### {identity} — depth {depth}",
                "",
                f"Author: {comment.get('author')} | Parent: {comment.get('parent_id')}",
                comment["permalink"],
                "",
            ]
        )
        lines.extend(
            "> " + line
            for line in str(comment.get("body_text") or "[unavailable]").splitlines()
        )
        lines.append("")
        stack.extend(
            (child, depth + 1) for child in reversed(children.get(identity, []))
        )
    for identity, comment in comments.items():
        if identity not in emitted:
            lines.extend(
                [
                    f"### {identity} — unresolved hierarchy",
                    "",
                    f"Parent: {comment.get('parent_id')}",
                    "",
                ]
            )
            lines.extend(
                "> " + line
                for line in str(
                    comment.get("body_text") or "[unavailable]"
                ).splitlines()
            )
            lines.append("")
    return "\n".join(lines) + "\n"


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def _write_thread_files(output_dir: Path, document: dict[str, Any]) -> None:
    for name, content in (
        ("thread.json", json.dumps(document, ensure_ascii=False, indent=2) + "\n"),
        ("thread.md", markdown(document)),
    ):
        path = output_dir / name
        with path.open("x", encoding="utf-8") as stream:
            path.chmod(0o600)
            stream.write(content)


def _run_one(
    browser: Browser,
    identity: str,
    *,
    max_comments: int,
    max_actions: int,
    session_mode: str,
    borrowed_session: str | None,
    backend: str,
) -> Thread:
    thread = Thread(identity, max_comments, session_mode=session_mode, backend=backend)
    try:
        if backend == "browser-json":
            collect_json(browser, thread, max_actions)
        else:
            collect(browser, thread, max_actions)
    except (CollectionError, ValueError, KeyError) as exc:
        thread.issues.append(str(exc))
        if (
            thread.status == "blocked"
            and borrowed_session is None
            and thread.block_reason in _ENV_BLOCK_REASONS
        ):
            thread.issues.append(
                "Standalone headless browser hit a Reddit gate; ask the user upfront "
                "before configuring a dedicated --session or REDDIT_BROWSER_SESSION "
                "(see references/reddit.md)"
            )
    return thread


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+", help="One or more Reddit post permalinks")
    parser.add_argument(
        "--output", required=True, type=Path, help="New private output directory"
    )
    parser.add_argument(
        "--session",
        help=(
            "Existing, dedicated agent-browser session "
            "(falls back to REDDIT_BROWSER_SESSION); never closes its browser"
        ),
    )
    parser.add_argument(
        "--backend",
        choices=("browser-json", "dom"),
        default="browser-json",
        help="Capture backend: browser-json (default) or dom",
    )
    parser.add_argument("--max-comments", type=_positive, default=10000)
    parser.add_argument("--max-actions", type=_positive, default=500)
    parser.add_argument(
        "--timeout", type=_positive, default=300, help="Collection budget in seconds"
    )
    args = parser.parse_args()
    try:
        identities: list[str] = []
        for raw_url in args.urls:
            identity = post_id(raw_url)
            if identity not in identities:
                identities.append(identity)
        borrowed_session, session_mode = resolve_session(args.session)
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    single_mode = len(identities) == 1
    browser: Browser | None = None
    target: str | None = None
    threads: list[Thread] = []
    skipped: list[str] = []
    cleanup_error: str | None = None
    stopped_early = False
    try:
        browser = Browser(
            borrowed_session or f"armory-reddit-{uuid.uuid4().hex}",
            time.monotonic() + args.timeout,
        )
        tab = browser.call("tab", "new", "about:blank")
        target = str(tab["targetId"])
        for index, identity in enumerate(identities):
            thread = _run_one(
                browser,
                identity,
                max_comments=args.max_comments,
                max_actions=args.max_actions,
                session_mode=session_mode,
                borrowed_session=borrowed_session,
                backend=args.backend,
            )
            threads.append(thread)
            if (
                not single_mode
                and thread.status == "blocked"
                and thread.block_reason in _ENV_BLOCK_REASONS
                and index + 1 < len(identities)
            ):
                stopped_early = True
                skipped.extend(identities[index + 1 :])
                break
    except (CollectionError, ValueError, KeyError) as exc:
        if not threads:
            failed = Thread(
                identities[0],
                args.max_comments,
                session_mode=session_mode,
                backend=args.backend,
            )
            failed.issues.append(str(exc))
            threads.append(failed)
            if len(identities) > 1:
                stopped_early = True
                skipped.extend(identities[1:])
        else:
            threads[-1].issues.append(str(exc))
    finally:
        if browser:
            # Cleanup has its own budget; only the tab we created can be closed in a borrowed session.
            browser.deadline = time.monotonic() + 15
            try:
                if borrowed_session:
                    if target:
                        browser.call("tab", "close", target)
                else:
                    browser.call("close")
            except CollectionError as exc:
                cleanup_error = f"Browser cleanup failed: {exc}"

    if cleanup_error and threads:
        threads[-1].issues.append(cleanup_error)

    if single_mode:
        thread = threads[0]
        thread.finish()
        document = thread.document()
        try:
            _write_thread_files(args.output, document)
        except OSError as exc:
            print(f"Cannot save capture: {exc}", file=sys.stderr)
            return 1
        summary: dict[str, Any] = {
            "status": thread.status,
            "comments": len(thread.comments),
            "output": str(args.output),
            "backend": args.backend,
            "complete": False,
        }
        if thread.block_reason:
            summary["block_reason"] = thread.block_reason
        print(json.dumps(summary))
        return 0 if thread.status == "browser_exhausted" else 2

    batch_results: list[dict[str, Any]] = []
    try:
        for thread in threads:
            thread.finish()
            document = thread.document()
            subdir = args.output / thread.identity[3:]
            subdir.mkdir(mode=0o700, exist_ok=False)
            _write_thread_files(subdir, document)
            entry: dict[str, Any] = {
                "post_id": thread.identity,
                "status": thread.status,
                "comments": len(thread.comments),
                "output": str(subdir),
                "complete": False,
            }
            if thread.block_reason:
                entry["block_reason"] = thread.block_reason
            batch_results.append(entry)
        batch_doc = {
            "schema_version": 1,
            "source": "reddit_browser",
            "backend": args.backend,
            "session_mode": session_mode,
            "complete": False,
            "stopped_early": stopped_early,
            "results": batch_results,
            "skipped": skipped,
        }
        batch_path = args.output / "batch.json"
        with batch_path.open("x", encoding="utf-8") as stream:
            batch_path.chmod(0o600)
            stream.write(json.dumps(batch_doc, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        print(f"Cannot save capture: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "output": str(args.output),
                "backend": args.backend,
                "stopped_early": stopped_early,
                "results": batch_results,
                "skipped": skipped,
                "complete": False,
            }
        )
    )
    all_exhausted = not skipped and all(
        entry["status"] == "browser_exhausted" for entry in batch_results
    )
    return 0 if all_exhausted else 2


if __name__ == "__main__":
    raise SystemExit(main())
