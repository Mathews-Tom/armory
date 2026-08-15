#!/usr/bin/env python3
"""Fetch and convert cloud provider architecture icons into a local cache.

Icons are never vendored into this skill package (see
`references/editability.md` for why). AWS, Azure, and GCP's own terms permit
using their icons to build architecture diagrams, but none of them grant
redistribution rights for the raw icon files, so this repository ships zero
icon assets. Instead this script builds a **per-user cache** on first use,
converting draw.io's Apache-2.0 vector stencil/icon libraries
(`stencil2svg.py` for AWS/GCP, `svg_inline.py` for Azure) into small
per-service JSON entries that `render.py` reads at diagram time.

The source commit is pinned (`DRAWIO_SHA`) so output is reproducible across
runs and machines; bumping the pin is a deliberate, reviewable change to this
file, not something that happens implicitly on `dev` branch churn.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import Protocol

from stencil2svg import convert_body, iter_shapes, slug
from svg_inline import inline_svg

DRAWIO_REPO = "jgraph/drawio"
DRAWIO_SHA = (
    "a1f615b7f5a5237da71de2ce2f057b5fa70b0aeb"  # dev branch, verified 2026-08-15
)
STENCIL_PATHS = {
    "aws": "src/main/webapp/stencils/aws4.xml",
    "gcp": "src/main/webapp/stencils/gcp2.xml",
}
AZURE_TREE_PREFIX = "src/main/webapp/img/lib/azure2"
LICENSE_NOTE = (
    "Vector geometry sourced from jgraph/drawio (Apache-2.0): "
    "https://github.com/jgraph/drawio/blob/dev/LICENSE. "
    "AWS/Azure/GCP retain ownership of the underlying icon designs; this "
    "cache exists for building your own diagrams under each provider's "
    "'use in architecture diagrams' terms, not for redistribution."
)


class Source(Protocol):
    def fetch_text(self, path: str) -> str: ...

    def list_tree(self, prefix: str, suffix: str) -> list[str]: ...


@dataclass
class GitHubSource:
    """Real network source: pinned-commit raw file fetch + recursive tree listing.

    Fetching Azure's icon set means ~700 individual small file requests. A
    fresh `urllib.request.urlopen` call per file pays a full TCP+TLS
    handshake every time, which under any real-world latency or transient
    congestion turns a one-time cache build into a multi-minute hang (verified
    against the live GitHub CDN while building this cache — a handshake alone
    can exceed the request timeout under load). Each worker thread keeps one
    persistent HTTP/1.1 keep-alive connection per host instead, with a
    reconnect-and-retry on any failure.
    """

    sha: str
    repo: str = DRAWIO_REPO
    timeout: float = 30.0
    retries: int = 3
    _local: threading.local = field(
        default_factory=threading.local, repr=False, compare=False
    )

    def _connection(self, host: str) -> http.client.HTTPSConnection:
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = {}
            self._local.conns = conns
        conn = conns.get(host)
        if conn is None:
            conn = http.client.HTTPSConnection(
                host, timeout=self.timeout, context=ssl.create_default_context()
            )
            conns[host] = conn
        return conn

    def _drop_connection(self, host: str) -> None:
        conns = getattr(self._local, "conns", None)
        if conns and host in conns:
            try:
                conns[host].close()
            except OSError:
                pass
            del conns[host]

    def _get(self, host: str, path: str, headers: dict[str, str]) -> bytes:
        last_exc: Exception = urllib.error.URLError(
            f"no attempts made for {host}{path}"
        )
        for attempt in range(self.retries):
            conn = self._connection(host)
            try:
                conn.request(
                    "GET", path, headers={**headers, "Connection": "keep-alive"}
                )
                resp = conn.getresponse()
                body = resp.read()
                if resp.status >= 400:
                    raise urllib.error.HTTPError(
                        path, resp.status, resp.reason, Message(), None
                    )
                return body
            except (OSError, urllib.error.HTTPError) as exc:
                last_exc = exc
                self._drop_connection(host)
                if attempt < self.retries - 1:
                    time.sleep(0.5 * (attempt + 1))
        raise last_exc

    def fetch_text(self, path: str) -> str:
        body = self._get(
            "raw.githubusercontent.com",
            f"/{self.repo}/{self.sha}/{path}",
            {"User-Agent": "armory-architecture-diagram"},
        )
        return body.decode("utf-8")

    def list_tree(self, prefix: str, suffix: str) -> list[str]:
        body = self._get(
            "api.github.com",
            f"/repos/{self.repo}/git/trees/{self.sha}?recursive=1",
            {
                "User-Agent": "armory-architecture-diagram",
                "Accept": "application/vnd.github+json",
            },
        )
        data = json.loads(body)
        return [
            e["path"]
            for e in data["tree"]
            if e["path"].startswith(prefix) and e["path"].endswith(suffix)
        ]


@dataclass
class IconEntry:
    slug: str
    name: str
    view_box: str
    body: str
    source: str
    warnings: list[str] = field(default_factory=list)


def convert_stencil_provider(source: Source, provider: str) -> list[IconEntry]:
    """AWS/GCP path: one stencil XML file holds every shape for the provider."""
    path = STENCIL_PATHS[provider]
    root = ET.fromstring(source.fetch_text(path))
    entries: list[IconEntry] = []
    for shape in iter_shapes(root):
        name = shape.get("name", "")
        if not name:
            continue
        view_box, body, warnings = convert_body(shape)
        entries.append(
            IconEntry(
                slug=slug(name),
                name=name,
                view_box=view_box,
                body=body,
                source=path,
                warnings=warnings,
            )
        )
    return entries


def convert_azure(source: Source, max_workers: int = 16) -> list[IconEntry]:
    """Azure path: one real SVG file per icon, fetched concurrently."""
    files = source.list_tree(AZURE_TREE_PREFIX, ".svg")

    def _one(path: str) -> IconEntry:
        name = Path(path).stem
        icon_slug = slug(name)
        view_box, body, warnings = inline_svg(source.fetch_text(path), icon_slug)
        return IconEntry(
            slug=icon_slug,
            name=name,
            view_box=view_box,
            body=body,
            source=path,
            warnings=warnings,
        )

    entries: list[IconEntry] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for future in as_completed({pool.submit(_one, p): p for p in files}):
            entries.append(future.result())
    return entries


def write_cache(
    cache_dir: Path, sha: str, provider: str, entries: list[IconEntry]
) -> dict[str, object]:
    provider_dir = cache_dir / sha / provider
    provider_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, int] = {}
    warned = 0
    for entry in entries:
        # Two shapes can normalize to the same slug (e.g. "S3" and "s3 " after
        # trimming). Suffix the collision rather than silently overwriting an
        # earlier icon's cache file.
        key = entry.slug
        if key in seen:
            seen[key] += 1
            key = f"{key}-{seen[key]}"
        else:
            seen[key] = 0
        payload = {
            "name": entry.name,
            "slug": entry.slug,
            "viewBox": entry.view_box,
            "body": entry.body,
            "source": entry.source,
            "warnings": entry.warnings,
        }
        (provider_dir / f"{key}.json").write_text(json.dumps(payload, indent=2))
        if entry.warnings:
            warned += 1
    return {
        "count": len(entries),
        "warned": warned,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def update_manifest(
    cache_dir: Path, sha: str, provider: str, stats: dict[str, object]
) -> None:
    manifest_path = cache_dir / sha / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        manifest: dict[str, object] = json.loads(manifest_path.read_text())
    else:
        manifest = {"sha": sha, "license_note": LICENSE_NOTE, "providers": {}}
    providers = manifest.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        manifest["providers"] = providers
    providers[provider] = stats
    manifest_path.write_text(json.dumps(manifest, indent=2))


def default_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "armory" / "cloud-icons"


def fetch_provider(
    source: Source, cache_dir: Path, sha: str, provider: str, force: bool
) -> dict[str, object]:
    provider_dir = cache_dir / sha / provider
    if provider_dir.exists() and any(provider_dir.glob("*.json")) and not force:
        return {"skipped": True, "count": len(list(provider_dir.glob("*.json")))}
    if provider == "azure":
        entries = convert_azure(source)
    elif provider in ("aws", "gcp"):
        entries = convert_stencil_provider(source, provider)
    else:
        raise ValueError(f"unknown provider: {provider}")
    stats = write_cache(cache_dir, sha, provider, entries)
    update_manifest(cache_dir, sha, provider, stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=["aws", "azure", "gcp", "all"], default="all"
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--sha", default=DRAWIO_SHA)
    parser.add_argument(
        "--force",
        action="store_true",
        help="refetch even if the cache is already populated",
    )
    args = parser.parse_args(argv)

    cache_dir = args.cache_dir or default_cache_dir()
    providers = ["aws", "azure", "gcp"] if args.provider == "all" else [args.provider]
    source: Source = GitHubSource(sha=args.sha)

    for provider in providers:
        try:
            stats = fetch_provider(source, cache_dir, args.sha, provider, args.force)
        except urllib.error.URLError as exc:
            print(
                f"error: could not fetch {provider} icons ({exc}).\n"
                f"Cache dir: {cache_dir / args.sha / provider}\n"
                f"Retry with: python3 fetch_icons.py --provider {provider} --cache-dir {cache_dir}",
                file=sys.stderr,
            )
            return 1
        if stats.get("skipped"):
            print(
                f"{provider}: cached ({stats['count']} icons) — pass --force to refetch"
            )
        else:
            warn_note = (
                f", {stats['warned']} with conversion warnings"
                if stats.get("warned")
                else ""
            )
            print(f"{provider}: fetched {stats['count']} icons{warn_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
