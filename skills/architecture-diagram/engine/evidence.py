"""Fail-closed local verification of authored Git source references."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit, urlunsplit

from .diagnostics import SEVERITY_ERROR, Diagnostic
from .model import SourceReference, Spec


@dataclass(frozen=True)
class VerifiedSource:
    """A source reference proven against one local Git repository."""

    id: str
    revision: str
    path: str
    lines: tuple[int, int]
    line_count: int


@dataclass(frozen=True)
class SourceEvidence:
    """Verified references and the repository origin needed by a later receipt."""

    origin: str
    sources: tuple[VerifiedSource, ...]


def _error(
    code: str,
    message: str,
    source: SourceReference | None = None,
    evidence: dict[str, object] | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=SEVERITY_ERROR,
        message=message,
        subject={"source": source.id} if source is not None else {},
        evidence=evidence or {},
        supported_fixes=(
            "run from a local checkout with an `origin` remote and correct source references",
        ),
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=False,
    )


def _line_count(blob: bytes) -> int:
    if not blob:
        return 0
    return blob.count(b"\n") + (0 if blob.endswith(b"\n") else 1)


def _verify_source(
    repository: Path, source: SourceReference
) -> tuple[VerifiedSource | None, Diagnostic | None]:
    commit = _git(repository, "cat-file", "-e", f"{source.revision}^{{commit}}")
    if commit.returncode:
        return None, _error(
            "source/missing-commit",
            f"source {source.id!r} does not name an available commit",
            source,
            {"revision": source.revision},
        )

    canonical = _git(repository, "rev-parse", f"{source.revision}^{{commit}}")
    if canonical.returncode:
        return None, _error(
            "source/missing-commit",
            f"source {source.id!r} does not name an available commit",
            source,
            {"revision": source.revision},
        )
    revision = canonical.stdout.decode("ascii").strip().lower()
    object_name = f"{revision}:{source.path}"
    object_type = _git(repository, "cat-file", "-t", object_name)
    if object_type.returncode:
        return None, _error(
            "source/missing-path",
            f"source {source.id!r} path is absent at its declared revision",
            source,
            {"revision": revision, "path": source.path},
        )
    if object_type.stdout.strip() != b"blob":
        return None, _error(
            "source/non-blob-path",
            f"source {source.id!r} path does not name a blob",
            source,
            {"revision": revision, "path": source.path},
        )

    blob = _git(repository, "cat-file", "blob", object_name)
    if blob.returncode:
        return None, _error(
            "source/missing-path",
            f"source {source.id!r} path cannot be read at its declared revision",
            source,
            {"revision": revision, "path": source.path},
        )
    if b"\0" in blob.stdout:
        return None, _error(
            "source/binary-blob",
            f"source {source.id!r} names a binary blob without line semantics",
            source,
            {"revision": revision, "path": source.path},
        )

    line_count = _line_count(blob.stdout)
    if source.lines[1] > line_count:
        return None, _error(
            "source/line-range-out-of-bounds",
            f"source {source.id!r} line range is outside its blob",
            source,
            {"lines": list(source.lines), "line_count": line_count},
        )
    return (
        VerifiedSource(
            id=source.id,
            revision=revision,
            path=source.path,
            lines=source.lines,
            line_count=line_count,
        ),
        None,
    )


def verify_sources(
    spec: Spec, spec_path: Path
) -> tuple[SourceEvidence | None, list[Diagnostic]]:
    """Verify every declared source against the local checkout containing the spec."""
    repository = _git(spec_path.parent, "rev-parse", "--show-toplevel")
    if repository.returncode:
        return None, [
            _error(
                "source/no-repository",
                "source verification requires a local Git repository",
            )
        ]
    repository_path = Path(repository.stdout.decode("utf-8").strip())

    origin = _git(repository_path, "remote", "get-url", "origin")
    if origin.returncode:
        return None, [
            _error(
                "source/no-origin", "source verification requires an `origin` remote"
            )
        ]

    verified: list[VerifiedSource] = []
    for source in spec.sources:
        verified_source, diagnostic = _verify_source(repository_path, source)
        if diagnostic is not None:
            return None, [diagnostic]
        assert verified_source is not None
        verified.append(verified_source)
    return SourceEvidence(origin.stdout.decode("utf-8").strip(), tuple(verified)), []


def summary(spec: Spec, evidence: SourceEvidence | None) -> dict[str, object]:
    """Build the compact verification-mode receipt field."""
    return {
        "mode": "verified",
        "verified_sources": len(evidence.sources) if evidence is not None else 0,
        "sourced_nodes": sum(bool(node.sources) for node in spec.nodes),
        "sourced_edges": sum(bool(edge.sources) for edge in spec.edges),
    }


def redact_origin(origin: str) -> str:
    """Remove credentials from HTTP(S) and SSH-style remote URLs."""
    parsed = urlsplit(origin)
    if parsed.scheme and parsed.netloc:
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunsplit(
            (parsed.scheme, host, parsed.path, parsed.query, parsed.fragment)
        )
    if "@" in origin and ":" in origin.split("@", 1)[1]:
        return origin.split("@", 1)[1]
    return origin


def sidecar_bytes(evidence: SourceEvidence, artifact: Path, svg: bytes) -> bytes:
    """Serialize the durable evidence receipt without source content or local paths."""
    payload = {
        "schema_version": 1,
        "artifact": {
            "path": artifact.name,
            "sha256": hashlib.sha256(svg).hexdigest(),
            "bytes": len(svg),
        },
        "repository": {"origin": redact_origin(evidence.origin)},
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": [
            {
                "id": source.id,
                "revision": source.revision,
                "path": source.path,
                "lines": list(source.lines),
                "line_count": source.line_count,
            }
            for source in evidence.sources
        ],
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
