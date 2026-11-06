#!/usr/bin/env python3
"""Private evidence and approval records; never writes audited targets."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

Record = dict[str, Any]
HEX = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}\Z")
LF_LINES = re.compile(r"[^\n]*\n|[^\n]+\Z")
HARNESS = ("claude", "omp", "codex", "other")


class AuditError(ValueError):
    """A boundary failure with a message that contains no private input."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def record(value: object) -> Record:
    require(isinstance(value, dict), "expected an object")
    return cast(Record, value)


def rows(value: object) -> list[Any]:
    require(isinstance(value, list), "expected an array")
    return cast(list[Any], value)


def text(value: object) -> str:
    require(isinstance(value, str), "expected text")
    return cast(str, value)


def nonempty(value: object) -> str:
    result = text(value)
    require(bool(result.strip()), "expected nonempty text")
    return result


def keys(value: Record, expected: str) -> None:
    require(set(value) == set(expected.split()), "unexpected or missing object fields")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fingerprint(value: Record) -> str:
    return sha(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    )


def seal(value: Record, field: str) -> Record:
    return {**value, field: fingerprint(value)}


def unseal(value: Record, field: str) -> Record:
    supplied = text(value.get(field))
    result = {key: item for key, item in value.items() if key != field}
    require(
        hmac.compare_digest(supplied, fingerprint(result)),
        "record fingerprint mismatch",
    )
    return result


def unique_pairs(pairs: list[tuple[str, Any]]) -> Record:
    result: Record = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise AuditError("non-finite JSON number")


def read_bytes(path: Path) -> bytes:
    require(path.is_absolute(), "input paths must be absolute")
    require(
        path.resolve(strict=True) == path,
        "input aliases are not supported; select the canonical file",
    )
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        require(
            stat.S_ISREG(os.fstat(stream.fileno()).st_mode),
            "input must be a regular file",
        )
        return stream.read()


def load(path: Path) -> Record:
    return record(
        json.loads(
            read_bytes(path),
            object_pairs_hook=unique_pairs,
            parse_constant=reject_constant,
        )
    )


def outside_repository(path: Path) -> None:
    canonical = path.resolve()
    require(
        not any(
            (parent / ".git").exists() for parent in (canonical, *canonical.parents)
        ),
        "outputs must be outside Git repositories",
    )


def private_parent(path: Path) -> None:
    require(path.is_absolute(), "output paths must be absolute")
    require(
        path.parent.resolve(strict=True) == path.parent,
        "output parent must be canonical",
    )
    outside_repository(path)
    info = path.parent.stat()
    require(
        info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
        "output parent must be owner-only",
    )


def protect_sources(output: Path, sources: list[Record]) -> None:
    require(
        output.resolve() not in {Path(source["path"]) for source in sources},
        "artifact output must not be an audited target",
    )


def write_private(path: Path, content: str) -> None:
    private_parent(path)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.write(content)


def save(path: Path, value: Record) -> None:
    write_private(
        path, json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
    )


def source_rows(value: object) -> list[Record]:
    result = [record(item) for item in rows(value)]
    require(bool(result), "at least one explicit source is required")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for source in result:
        keys(source, "source_id path sha256 characters lines format syntax")
        identity = nonempty(source["source_id"])
        path = text(source["path"])
        require(bool(IDENTIFIER.fullmatch(identity)), "invalid source identifier")
        require(Path(path).is_absolute(), "source paths must be absolute")
        require(identity not in seen_ids and path not in seen_paths, "duplicate source")
        require(
            bool(HEX.fullmatch(text(source["sha256"]))), "invalid source fingerprint"
        )
        for field, minimum in (("characters", 0), ("lines", 1)):
            require(
                type(source[field]) is int and source[field] >= minimum,
                "invalid source count",
            )
        require(source["format"] in ("text", "json", "toml"), "invalid source format")
        require(
            source["syntax"] in ("valid", "invalid", "not_checked"),
            "invalid syntax status",
        )
        seen_ids.add(identity)
        seen_paths.add(path)
    return result


def current_sources(sources: list[Record]) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in sources:
        raw = read_bytes(Path(source["path"]))
        require(
            sha(raw) == source["sha256"], "source changed; capture and review again"
        )
        result[source["source_id"]] = raw.decode("utf-8")
    return result


def capture(harness: str, paths: list[Path], output: Path) -> None:
    require(harness in HARNESS, "unsupported harness")
    sources: list[Record] = []
    for index, path in enumerate(paths, 1):
        raw = read_bytes(path)
        body = raw.decode("utf-8")
        kind, syntax = "text", "not_checked"
        if path.suffix.lower() in (".json", ".toml"):
            kind, syntax = path.suffix.lower()[1:], "valid"
            try:
                if kind == "json":
                    json.loads(
                        body,
                        object_pairs_hook=unique_pairs,
                        parse_constant=reject_constant,
                    )
                else:
                    tomllib.loads(body)
            except (ValueError, tomllib.TOMLDecodeError):
                syntax = "invalid"
        sources.append(
            {
                "source_id": f"s{index:03d}",
                "path": str(path),
                "sha256": sha(raw),
                "characters": len(body),
                "lines": max(1, len(LF_LINES.findall(body))),
                "format": kind,
                "syntax": syntax,
            }
        )
    source_rows(sources)
    protect_sources(output, sources)
    save(
        output,
        seal(
            {
                "schema_version": 1,
                "harness": harness,
                "created_at": datetime.now(UTC).isoformat(),
                "sources": sources,
            },
            "snapshot_digest",
        ),
    )


def validate_coverage(value: object) -> list[Record]:
    result = [record(item) for item in rows(value)]
    seen: set[str] = set()
    for item in result:
        keys(item, "area status detail")
        area = nonempty(item["area"])
        nonempty(item["detail"])
        require(area not in seen, "duplicate coverage area")
        require(
            item["status"] in ("available", "partial", "unavailable"),
            "invalid coverage status",
        )
        seen.add(area)
    require(bool(result), "declare coverage and evidence limits")
    return result


def validate_findings(
    value: object, sources: list[Record], bodies: dict[str, str] | None
) -> list[Record]:
    catalog = {source["source_id"]: source for source in sources}
    result = [record(item) for item in rows(value)]
    identities: set[str] = set()
    targets: set[str] = set()
    for finding in result:
        keys(
            finding,
            "id category priority problem consequence recommendation confidence evidence change",
        )
        identity = nonempty(finding["id"])
        require(
            bool(IDENTIFIER.fullmatch(identity)) and identity not in identities,
            "invalid or duplicate finding identifier",
        )
        identities.add(identity)
        require(
            finding["category"]
            in ("instructions", "settings", "connectors", "tasks", "skills"),
            "invalid finding category",
        )
        require(finding["priority"] in ("high", "medium", "low"), "invalid priority")
        require(finding["confidence"] in ("observed", "inferred"), "invalid confidence")
        for field in ("problem", "consequence", "recommendation"):
            nonempty(finding[field])
        evidence = [record(item) for item in rows(finding["evidence"])]
        require(bool(evidence), "findings require source evidence")
        for item in evidence:
            keys(item, "source_id line_start line_end observation")
            require(text(item["source_id"]) in catalog, "unknown evidence source")
            nonempty(item["observation"])
            start, end = item["line_start"], item["line_end"]
            require(
                type(start) is int
                and type(end) is int
                and 1 <= start <= end <= catalog[item["source_id"]]["lines"],
                "evidence outside source line bounds",
            )
        if finding["change"] is None:
            continue
        require(
            finding["category"] not in ("connectors", "tasks"),
            "connector and task findings are report-only",
        )
        change = record(finding["change"])
        keys(
            change,
            "source_id replacement"
            if bodies is not None
            else "source_id path before_sha256 after_sha256 replacement diff",
        )
        source_id = text(change["source_id"])
        require(
            source_id in catalog and source_id not in targets,
            "unknown or repeated change target",
        )
        require(
            source_id in {item["source_id"] for item in evidence},
            "change target requires its own evidence",
        )
        targets.add(source_id)
        replacement = text(change["replacement"])
        after = sha(replacement.encode("utf-8"))
        source = catalog[source_id]
        require(after != source["sha256"], "change has no effect")
        if bodies is not None:
            before = bodies[source_id]
            lines = difflib.unified_diff(
                LF_LINES.findall(before),
                LF_LINES.findall(replacement),
                fromfile=source["path"],
                tofile=source["path"],
                n=0,
            )
            diff = "".join(
                line
                if line.endswith("\n")
                else line + "\n\\ No newline at end of file\n"
                for line in lines
            )
            finding["change"] = {
                "source_id": source_id,
                "path": source["path"],
                "before_sha256": source["sha256"],
                "after_sha256": after,
                "replacement": replacement,
                "diff": diff,
            }
        else:
            require(
                change["path"] == source["path"]
                and change["before_sha256"] == source["sha256"]
                and change["after_sha256"] == after,
                "change fingerprint or target mismatch",
            )
            nonempty(change["diff"])
    return result


def version(value: Record) -> None:
    require(
        type(value.get("schema_version")) is int and value["schema_version"] == 1,
        "unsupported schema version",
    )


def review(snapshot_path: Path, findings_path: Path, output: Path) -> None:
    snapshot = unseal(load(snapshot_path), "snapshot_digest")
    keys(snapshot, "schema_version harness created_at sources")
    version(snapshot)
    require(snapshot["harness"] in HARNESS, "unsupported harness")
    nonempty(snapshot["created_at"])
    sources = source_rows(snapshot["sources"])
    bodies = current_sources(sources)
    authored = load(findings_path)
    keys(authored, "coverage findings")
    coverage = validate_coverage(authored["coverage"])
    findings = validate_findings(authored["findings"], sources, bodies)
    bundle = seal(
        {**snapshot, "coverage": coverage, "findings": findings}, "bundle_digest"
    )
    projection = json.loads(json.dumps(bundle))
    for finding in projection["findings"]:
        if finding["change"] is not None:
            del finding["change"]["replacement"]
    payload = (
        json.dumps(projection, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    template = (Path(__file__).resolve().parents[1] / "assets/review.html").read_text(
        encoding="utf-8"
    )
    require(template.count("__AUDIT_DATA__") == 1, "invalid review template")
    for artifact in (output, output / "bundle.json", output / "review.html"):
        protect_sources(artifact, sources)
    private_parent(output)
    output.mkdir(mode=0o700)
    save(output / "bundle.json", bundle)
    write_private(output / "review.html", template.replace("__AUDIT_DATA__", payload))


def read_bundle(path: Path) -> Record:
    bundle = load(path)
    data = unseal(bundle, "bundle_digest")
    keys(data, "schema_version harness created_at sources coverage findings")
    version(data)
    require(data["harness"] in HARNESS, "unsupported harness")
    nonempty(data["created_at"])
    sources = source_rows(data["sources"])
    validate_coverage(data["coverage"])
    validate_findings(data["findings"], sources, None)
    return bundle


def check(
    bundle_path: Path, selection_path: Path, confirmation: str, output: Path
) -> None:
    bundle = read_bundle(bundle_path)
    selection = load(selection_path)
    keys(selection, "schema_version bundle_digest selected comments")
    version(selection)
    require(
        selection["bundle_digest"] == bundle["bundle_digest"] == confirmation,
        "approval does not match this review",
    )
    selected = [text(item) for item in rows(selection["selected"])]
    require(len(selected) == len(set(selected)), "duplicate selection")
    catalog = {finding["id"]: finding for finding in bundle["findings"]}
    for identity in selected:
        require(
            identity in catalog and catalog[identity]["change"] is not None,
            "selection is not a proposed file change",
        )
    comments = record(selection["comments"])
    for identity, comment in comments.items():
        require(identity in catalog, "comment references unknown finding")
        text(comment)
    current_sources(source_rows(bundle["sources"]))
    protect_sources(output, bundle["sources"])
    changes = [
        {"finding_id": identity, **catalog[identity]["change"]} for identity in selected
    ]
    save(
        output,
        seal(
            {
                "schema_version": 1,
                "bundle_digest": confirmation,
                "sources": bundle["sources"],
                "changes": changes,
                "comments": comments,
            },
            "authorization_digest",
        ),
    )


def verify(authorization_path: Path, output: Path) -> bool:
    authorization = load(authorization_path)
    data = unseal(authorization, "authorization_digest")
    keys(data, "schema_version bundle_digest sources changes comments")
    version(data)
    require(
        bool(HEX.fullmatch(text(data["bundle_digest"]))), "invalid review fingerprint"
    )
    record(data["comments"])
    sources = source_rows(data["sources"])
    protect_sources(output, sources)
    catalog = {source["source_id"]: source for source in sources}
    expected: dict[str, str] = {}
    for value in rows(data["changes"]):
        change = record(value)
        keys(
            change,
            "finding_id source_id path before_sha256 after_sha256 replacement diff",
        )
        identity = text(change["source_id"])
        require(
            identity in catalog and identity not in expected,
            "unknown or repeated authorization target",
        )
        require(
            change["path"] == catalog[identity]["path"]
            and change["before_sha256"] == catalog[identity]["sha256"],
            "authorization target mismatch",
        )
        after = sha(text(change["replacement"]).encode("utf-8"))
        require(
            after == change["after_sha256"] and after != change["before_sha256"],
            "authorization content mismatch",
        )
        expected[identity] = after
    results: list[Record] = []
    for source in sources:
        identity = source["source_id"]
        try:
            observed = sha(read_bytes(Path(source["path"])))
            if observed == expected.get(identity, source["sha256"]):
                status = "applied" if identity in expected else "unchanged"
            else:
                status = (
                    "not_applied"
                    if identity in expected and observed == source["sha256"]
                    else "drift"
                )
        except (OSError, AuditError):
            status = "unavailable"
        results.append({"source_id": identity, "status": status})
    passed = all(item["status"] in ("applied", "unchanged") for item in results)
    save(
        output,
        {
            "schema_version": 1,
            "authorization_digest": authorization["authorization_digest"],
            "status": "verified" if passed else "incomplete",
            "selected_changes": len(expected),
            "results": results,
        },
    )
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser(
        "capture", help="hash explicitly selected files without storing their contents"
    )
    capture_parser.add_argument("--harness", required=True, choices=HARNESS)
    capture_parser.add_argument("--file", required=True, action="append", type=Path)
    capture_parser.add_argument("--out", required=True, type=Path)
    review_parser = commands.add_parser(
        "review", help="seal authored findings and render an offline review"
    )
    review_parser.add_argument("--snapshot", required=True, type=Path)
    review_parser.add_argument("--findings", required=True, type=Path)
    review_parser.add_argument("--out-dir", required=True, type=Path)
    check_parser = commands.add_parser(
        "check", help="validate selected changes after separate chat authorization"
    )
    check_parser.add_argument("--bundle", required=True, type=Path)
    check_parser.add_argument("--selection", required=True, type=Path)
    check_parser.add_argument("--confirm", required=True)
    check_parser.add_argument("--out", required=True, type=Path)
    verify_parser = commands.add_parser(
        "verify", help="observe native-tool edits and unselected source drift"
    )
    verify_parser.add_argument("--authorization", required=True, type=Path)
    verify_parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        require(
            os.name == "posix",
            "Audit refused: helper requires a POSIX platform (macOS/Linux); "
            "use report-only analysis.",
        )
        if args.command == "capture":
            capture(args.harness, args.file, args.out)
        elif args.command == "review":
            review(args.snapshot, args.findings, args.out_dir)
        elif args.command == "check":
            check(args.bundle, args.selection, args.confirm, args.out)
        elif not verify(args.authorization, args.out):
            print(
                "Verification incomplete; inspect the private receipt.", file=sys.stderr
            )
            return 2
    except (
        AuditError,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
    ) as error:
        # OS/parser exceptions can include credentials, source text or private paths.
        print(
            str(error)
            if isinstance(error, AuditError)
            else "Audit refused: unreadable, malformed, or conflicting input/output.",
            file=sys.stderr,
        )
        return 2
    print("Private audit artifact created. No audited targets were written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
