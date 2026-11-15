#!/usr/bin/env python3
"""Collect one Reddit thread through the existing agent-browser CLI, without OAuth."""

from __future__ import annotations

import argparse
import json
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
            r"^/(?:r/[A-Za-z0-9_]+/)?comments/([a-z0-9]+)(?:/|$)",
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


class Thread:
    def __init__(self, identity: str, max_comments: int) -> None:
        self.identity = identity
        self.max_comments = max_comments
        self.post: dict[str, Any] | None = None
        self.comments: dict[str, dict[str, Any]] = {}
        self.issues: list[str] = []
        self.pending: list[dict[str, Any]] = []
        self.continuations: list[str] = []
        self.pages: list[str] = []
        self.actions = 0
        self.status = "error"

    def merge(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("blocked"):
            self.status = "blocked"
            raise CollectionError(
                "Reddit access/verification gate; no bypass attempted"
            )
        source = str(snapshot.get("source_url", ""))
        if post_id(source) != self.identity:
            raise CollectionError("Browser left the requested Reddit post")
        if source not in self.pages:
            self.pages.append(source)
        incoming = snapshot.get("post")
        if not isinstance(incoming, dict) or incoming.get("id") != self.identity:
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
            "post_id": self.identity,
            "source_url": f"https://www.reddit.com/comments/{self.identity[3:]}/",
            "captured_at": datetime.now(UTC).isoformat(),
            "status": self.status,
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
        document["completeness_note"],
        "",
        document["source_url"],
        "",
    ]
    lines.extend(f"- {issue}" for issue in document["issues"])
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument(
        "--output", required=True, type=Path, help="New private output directory"
    )
    parser.add_argument(
        "--session",
        help="Existing, dedicated agent-browser session; never closes its browser",
    )
    parser.add_argument("--max-comments", type=_positive, default=10000)
    parser.add_argument("--max-actions", type=_positive, default=500)
    parser.add_argument(
        "--timeout", type=_positive, default=300, help="Collection budget in seconds"
    )
    args = parser.parse_args()
    try:
        identity = post_id(args.url)
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    thread = Thread(identity, args.max_comments)
    browser: Browser | None = None
    target: str | None = None
    try:
        browser = Browser(
            args.session or f"armory-reddit-{uuid.uuid4().hex}",
            time.monotonic() + args.timeout,
        )
        tab = browser.call("tab", "new", "about:blank")
        target = str(tab["targetId"])
        collect(browser, thread, args.max_actions)
    except (CollectionError, ValueError, KeyError) as exc:
        thread.issues.append(str(exc))
    finally:
        if browser:
            # Cleanup has its own budget; only the tab we created can be closed in a borrowed session.
            browser.deadline = time.monotonic() + 15
            try:
                if args.session:
                    if target:
                        browser.call("tab", "close", target)
                else:
                    browser.call("close")
            except CollectionError as exc:
                thread.issues.append(f"Browser cleanup failed: {exc}")
    thread.finish()
    document = thread.document()
    try:
        for name, content in (
            ("thread.json", json.dumps(document, ensure_ascii=False, indent=2) + "\n"),
            ("thread.md", markdown(document)),
        ):
            path = args.output / name
            with path.open("x", encoding="utf-8") as stream:
                path.chmod(0o600)
                stream.write(content)
    except OSError as exc:
        print(f"Cannot save capture: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": thread.status,
                "comments": len(thread.comments),
                "output": str(args.output),
                "complete": False,
            }
        )
    )
    return 0 if thread.status == "browser_exhausted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
