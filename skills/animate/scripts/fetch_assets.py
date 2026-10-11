"""Phase 4 — Pluggable asset sourcing for animate storyboards.

Adapters: local (directory of SVGs/PNGs/JPGs), iconfinder (API-key gated),
none (text-only mode). Reads storyboard JSON, resolves each scene's assets,
writes a resolved mapping JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICONFINDER_SEARCH_URL = "https://api.iconfinder.com/v4/icons/search"
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".svg", ".png", ".jpg", ".jpeg")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AssetResolutionError(RuntimeError):
    """Raised when one or more required assets cannot be resolved."""

    missing: list[str]

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            f"Failed to resolve {len(missing)} required asset(s): {missing}"
        )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AssetAdapter(Protocol):
    name: str

    def resolve(self, query: str, kind: str) -> Path | None: ...


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def _normalise_query(query: str) -> str:
    """Lowercase, collapse whitespace to hyphens for filename matching."""
    return re.sub(r"[\s_]+", "-", query.strip().lower())


class LocalAssetAdapter:
    """Searches a root directory for asset files by filename stem match."""

    name = "local"

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise ValueError(f"asset-dir does not exist or is not a directory: {root}")
        self._root = root

    def resolve(self, query: str, kind: str) -> Path | None:
        del kind
        normalised = _normalise_query(query)
        for candidate in self._root.iterdir():
            if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            stem = _normalise_query(candidate.stem)
            if stem == normalised:
                return candidate.resolve()
        return None


class IconFinderAdapter:
    """Resolves assets via the IconFinder API (API-key gated)."""

    name = "iconfinder"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError(
                "ICONFINDER_API_KEY is not set; "
                "IconFinderAdapter requires an API key at construction time"
            )
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> IconFinderAdapter:
        key = os.environ.get("ICONFINDER_API_KEY", "")
        return cls(key)

    def resolve(self, query: str, kind: str) -> Path | None:
        del kind
        params = urllib.parse.urlencode({"query": query, "count": 1, "vector": 1})
        url = f"{ICONFINDER_SEARCH_URL}?{params}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                body: dict[str, Any] = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"IconFinder API returned HTTP {exc.code} for query '{query}'"
            ) from exc

        icons: list[dict[str, Any]] = body.get("icons", [])
        if not icons:
            return None

        # Prefer the first vector (SVG) download URL
        icon = icons[0]
        raster_sizes: list[dict[str, Any]] = icon.get("raster_sizes", [])
        vector_sizes: list[dict[str, Any]] = icon.get("vector_sizes", [])

        download_url: str | None = None
        if vector_sizes:
            formats: list[dict[str, Any]] = vector_sizes[0].get("formats", [])
            if formats:
                download_url = formats[0].get("download_url")
        if download_url is None and raster_sizes:
            formats = raster_sizes[-1].get("formats", [])
            if formats:
                download_url = formats[0].get("download_url")

        if download_url is None:
            return None

        dl_req = urllib.request.Request(
            download_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        suffix = Path(download_url.split("?")[0]).suffix or ".svg"
        dest = Path(os.environ.get("TMPDIR", "/tmp")) / (
            _normalise_query(query) + suffix
        )
        try:
            with urllib.request.urlopen(dl_req) as dl_resp:
                dest.write_bytes(dl_resp.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"IconFinder download returned HTTP {exc.code} for query '{query}'"
            ) from exc

        return dest


class NoneAdapter:
    """Always returns None; used for text-only storyboards."""

    name = "none"

    def resolve(self, query: str, kind: str) -> Path | None:
        del query, kind
        return None


# ---------------------------------------------------------------------------
# Storyboard validation (minimal — full validation lives in plan_storyboard.py)
# ---------------------------------------------------------------------------

_VALID_KINDS: frozenset[str] = frozenset({"icon", "image", "text"})


def _require(obj: dict[str, Any], key: str, path: str) -> Any:
    if key not in obj:
        raise ValueError(f"storyboard missing required field '{path}.{key}'")
    return obj[key]


def _validate_storyboard(data: Any) -> None:
    if not isinstance(data, dict):
        raise ValueError("storyboard JSON must be a top-level object")
    _require(data, "scenes", "root")
    scenes = data["scenes"]
    if not isinstance(scenes, list) or len(scenes) == 0:
        raise ValueError("storyboard 'scenes' must be a non-empty array")
    for i, scene in enumerate(scenes):
        base = f"scenes[{i}]"
        if not isinstance(scene, dict):
            raise ValueError(f"{base} must be an object")
        _require(scene, "index", base)
        assets_raw = scene.get("assets")
        if assets_raw is None:
            raise ValueError(f"{base} missing required field 'assets'")
        if not isinstance(assets_raw, list):
            raise ValueError(f"{base}.assets must be an array")
        for j, asset in enumerate(assets_raw):
            abase = f"{base}.assets[{j}]"
            if not isinstance(asset, dict):
                raise ValueError(f"{abase} must be an object")
            for field in ("kind", "query", "required"):
                _require(asset, field, abase)
            if asset["kind"] not in _VALID_KINDS:
                raise ValueError(
                    f"{abase}.kind must be one of {sorted(_VALID_KINDS)}, "
                    f"got '{asset['kind']}'"
                )
            if not isinstance(asset["query"], str) or not asset["query"].strip():
                raise ValueError(f"{abase}.query must be a non-empty string")
            if not isinstance(asset["required"], bool):
                raise ValueError(f"{abase}.required must be a boolean")


# ---------------------------------------------------------------------------
# Core resolution logic
# ---------------------------------------------------------------------------

ResolvedMapping = dict[int, dict[str, str | None]]


def resolve_storyboard(
    storyboard: dict[str, Any],
    adapter: AssetAdapter,
) -> ResolvedMapping:
    """Resolve all assets in *storyboard* using *adapter*.

    Returns ``{scene_index: {asset_query: resolved_path_or_null}}``.
    Raises :class:`AssetResolutionError` if any ``required: true`` asset
    cannot be resolved — no silent skipping.
    """
    _validate_storyboard(storyboard)
    result: ResolvedMapping = {}
    missing: list[str] = []

    for scene in storyboard["scenes"]:
        idx: int = scene["index"]
        scene_map: dict[str, str | None] = {}
        for asset in scene.get("assets", []):
            query: str = asset["query"]
            kind: str = asset["kind"]
            required: bool = asset["required"]

            resolved = adapter.resolve(query, kind)
            scene_map[query] = str(resolved) if resolved is not None else None

            if resolved is None and required:
                missing.append(query)

        result[idx] = scene_map

    if missing:
        raise AssetResolutionError(missing)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_adapter(
    adapter_name: str,
    asset_dir: Path | None,
) -> AssetAdapter:
    if adapter_name == "local":
        if asset_dir is None:
            raise ValueError("--asset-dir is required when --adapter=local")
        return LocalAssetAdapter(asset_dir)
    if adapter_name == "iconfinder":
        return IconFinderAdapter.from_env()
    if adapter_name == "none":
        return NoneAdapter()
    raise ValueError(f"unknown adapter '{adapter_name}'")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Resolve storyboard assets to local file paths."
    )
    parser.add_argument("storyboard", type=Path, help="Path to storyboard.json")
    parser.add_argument(
        "--adapter",
        choices=["local", "iconfinder", "none"],
        default="none",
        help="Asset resolution backend (default: none)",
    )
    parser.add_argument(
        "--asset-dir",
        type=Path,
        default=None,
        help="Root directory for local adapter",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write resolved JSON to this path (default: stdout)",
    )
    args = parser.parse_args(argv)

    raw = args.storyboard.read_text(encoding="utf-8")
    try:
        storyboard: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed storyboard JSON: {exc}") from exc

    adapter = _build_adapter(args.adapter, args.asset_dir)
    resolved = resolve_storyboard(storyboard, adapter)

    # Serialise with string keys for JSON compat
    output = json.dumps({str(k): v for k, v in resolved.items()}, indent=2)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output + "\n")


if __name__ == "__main__":
    main()
