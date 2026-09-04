"""Verified local and bundled icon lookup implementations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from . import fetch_icons
from .data import data_path
from .diagnostics import Diagnostic, SEVERITY_ERROR


@dataclass
class IconRef:
    view_box: str
    body: str


class IconLookup(Protocol):
    def __call__(self, provider: str, service_slug: str) -> IconRef | None: ...


class IconCacheError(RuntimeError):
    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


@dataclass
class CacheIconLookup:
    """Resolve cache entries only after validating their manifest digest."""

    cache_dir: Path
    sha: str

    def _error(
        self,
        code: str,
        message: str,
        provider: str,
        service_slug: str,
        evidence: dict[str, object],
    ) -> IconCacheError:
        return IconCacheError(
            Diagnostic(
                code=code,
                severity=SEVERITY_ERROR,
                message=message,
                subject={"provider": provider, "service": service_slug},
                evidence=evidence,
                supported_fixes=(
                    f"rebuild the {provider} icon cache: "
                    f"fetch_icons.py --provider {provider} --force",
                ),
                suppresses=("icon/not-found",),
            )
        )

    def __call__(self, provider: str, service_slug: str) -> IconRef | None:
        cache_root = self.cache_dir / self.sha
        path = cache_root / provider / f"{service_slug}.json"
        if not path.exists():
            return None
        manifest_path = cache_root / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text())
            payload = path.read_bytes()
        except (OSError, json.JSONDecodeError) as exc:
            raise self._error(
                "icon/cache-unverified",
                f"icon cache entry {path} has no readable integrity manifest",
                provider,
                service_slug,
                {"path": str(path), "error": str(exc)},
            ) from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("format_version") != fetch_icons.CACHE_MANIFEST_VERSION
            or manifest.get("sha") != self.sha
            or not isinstance(manifest.get("providers"), dict)
        ):
            raise self._error(
                "icon/cache-unverified",
                f"icon cache entry {path} has an unsupported integrity manifest",
                provider,
                service_slug,
                {"path": str(path)},
            )
        provider_stats = manifest["providers"].get(provider)
        if not isinstance(provider_stats, dict) or not isinstance(
            provider_stats.get("icons"), dict
        ):
            raise self._error(
                "icon/cache-unverified",
                f"icon cache entry {path} is absent from its integrity manifest",
                provider,
                service_slug,
                {"path": str(path)},
            )
        record = provider_stats["icons"].get(path.name)
        expected_digest = record.get("sha256") if isinstance(record, dict) else None
        actual_digest = hashlib.sha256(payload).hexdigest()
        if not isinstance(expected_digest, str):
            raise self._error(
                "icon/cache-unverified",
                f"icon cache entry {path} has no recorded content digest",
                provider,
                service_slug,
                {"path": str(path)},
            )
        if actual_digest != expected_digest:
            raise self._error(
                "icon/digest-mismatch",
                f"icon cache entry {path} does not match its recorded digest",
                provider,
                service_slug,
                {
                    "path": str(path),
                    "expected_sha256": expected_digest,
                    "actual_sha256": actual_digest,
                },
            )
        try:
            data = json.loads(payload)
            return IconRef(view_box=data["viewBox"], body=data["body"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise self._error(
                "icon/cache-unverified",
                f"verified icon cache entry {path} is not a usable icon",
                provider,
                service_slug,
                {"path": str(path), "error": str(exc)},
            ) from exc


@dataclass
class BundledGenericIconLookup:
    """Resolve the always-available generic icon catalog without a network cache."""

    path: Path = field(
        default_factory=lambda: data_path("assets", "generic-icons.json")
    )

    def __call__(self, provider: str, service_slug: str) -> IconRef | None:
        if provider != "generic" or not self.path.exists():
            return None
        data = json.loads(self.path.read_text())
        entry = data.get(service_slug)
        if entry is None:
            return None
        return IconRef(view_box=entry["viewBox"], body=entry["body"])


@dataclass
class CompositeIconLookup:
    """Return the first result from the configured lookup sequence."""

    lookups: list[IconLookup]

    def __call__(self, provider: str, service_slug: str) -> IconRef | None:
        for lookup in self.lookups:
            reference = lookup(provider, service_slug)
            if reference is not None:
                return reference
        return None
