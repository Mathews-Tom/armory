"""YAML specification parsing and authored-input diagnostics."""

from __future__ import annotations

import re

import yaml

from .diagnostics import Diagnostic, SEVERITY_ERROR
from .model import Edge, Node, SourceReference, Spec, Zone


class SpecError(ValueError):
    """A spec the renderer cannot answer with a coded diagnostic."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _spec_error(
    code: str,
    message: str,
    subject: dict[str, object] | None = None,
    evidence: dict[str, object] | None = None,
    supported_fixes: tuple[str, ...] = (),
) -> SpecError:
    return SpecError(
        Diagnostic(
            code=code,
            severity=SEVERITY_ERROR,
            message=message,
            subject=subject or {},
            evidence=evidence or {},
            supported_fixes=supported_fixes,
        )
    )


_SOURCE_REVISION = re.compile(r"[0-9a-fA-F]{40}\Z")


def _source_error(
    code: str,
    message: str,
    subject: dict[str, object],
    evidence: dict[str, object],
    supported_fixes: tuple[str, ...],
) -> SpecError:
    return _spec_error(code, message, subject, evidence, supported_fixes)


def _parse_sources(data: dict[str, object]) -> list[SourceReference]:
    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        raise _source_error(
            "source/invalid-declarations",
            "`sources` must be a YAML list",
            {"sources": raw_sources},
            {"type": type(raw_sources).__name__},
            ("declare source references as a YAML list",),
        )

    sources: list[SourceReference] = []
    source_ids: set[str] = set()
    for raw in raw_sources:
        if not isinstance(raw, dict):
            raise _source_error(
                "source/invalid-declaration",
                "each source declaration must be a mapping",
                {"source": raw},
                {"type": type(raw).__name__},
                ("declare `id`, `revision`, `path`, and `lines` for every source",),
            )

        source_id = raw.get("id")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id.strip() != source_id
        ):
            raise _source_error(
                "source/invalid-id",
                "source declarations require a non-blank string `id`",
                {"source": source_id},
                {"id": source_id},
                ("set `id` to a non-blank string without surrounding whitespace",),
            )
        if source_id in source_ids:
            raise _source_error(
                "source/duplicate-id",
                f"duplicate source id: {source_id!r}",
                {"source": source_id},
                {"id": source_id},
                ("give every source declaration a unique `id`",),
            )

        revision = raw.get("revision")
        if (
            not isinstance(revision, str)
            or _SOURCE_REVISION.fullmatch(revision) is None
        ):
            raise _source_error(
                "source/invalid-revision",
                f"source {source_id!r} requires a 40-character hexadecimal `revision`",
                {"source": source_id},
                {"revision": revision},
                ("set `revision` to a full 40-character Git object id",),
            )

        path = raw.get("path")
        path_parts = path.split("/") if isinstance(path, str) else []
        if (
            not isinstance(path, str)
            or not path
            or path.strip() != path
            or path.startswith("/")
            or "\\" in path
            or ":" in path
            or any(part in ("", ".", "..") for part in path_parts)
        ):
            raise _source_error(
                "source/invalid-path",
                f"source {source_id!r} requires a relative POSIX `path`",
                {"source": source_id},
                {"path": path},
                ("use a non-empty relative POSIX path without `.` or `..` segments",),
            )

        lines = raw.get("lines")
        if (
            not isinstance(lines, list)
            or len(lines) != 2
            or any(
                not isinstance(line, int) or isinstance(line, bool) for line in lines
            )
        ):
            raise _source_error(
                "source/invalid-lines",
                f"source {source_id!r} requires `lines: [start, end]` with integers",
                {"source": source_id},
                {"lines": lines},
                ("set `lines` to two integer line numbers",),
            )
        start_line, end_line = lines
        if start_line < 1 or end_line < start_line:
            raise _source_error(
                "source/invalid-line-range",
                f"source {source_id!r} has an invalid inclusive line range",
                {"source": source_id},
                {"lines": lines},
                ("use positive line numbers with start less than or equal to end",),
            )

        source_ids.add(source_id)
        sources.append(
            SourceReference(
                id=source_id,
                revision=revision,
                path=path,
                lines=(start_line, end_line),
            )
        )
    return sources


def _parse_source_attachments(
    raw: dict[str, object],
    subject: dict[str, object],
    source_ids: set[str],
) -> tuple[str, ...]:
    attachments = raw.get("sources", [])
    if not isinstance(attachments, list):
        raise _source_error(
            "source/invalid-attachments",
            "`sources` attachments must be a YAML list",
            subject,
            {"sources": attachments, "type": type(attachments).__name__},
            ("list zero or more declared source ids under `sources`",),
        )

    parsed: list[str] = []
    for source_id in attachments:
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id.strip() != source_id
        ):
            raise _source_error(
                "source/invalid-attachment",
                "source attachments must be non-blank string ids",
                subject,
                {"source": source_id},
                ("reference a declared source id",),
            )
        if source_id in parsed:
            raise _source_error(
                "source/duplicate-attachment",
                f"source {source_id!r} is attached more than once",
                subject,
                {"source": source_id},
                ("list each source id at most once per node or edge",),
            )
        if source_id not in source_ids:
            raise _source_error(
                "source/unknown-attachment",
                f"source attachment {source_id!r} is not declared",
                subject,
                {"source": source_id, "known_sources": sorted(source_ids)},
                ("declare the source under top-level `sources`",),
            )
        parsed.append(source_id)
    return tuple(parsed)


def load_spec(text: str) -> Spec:
    """Parse and validate one authored YAML specification."""
    data = yaml.safe_load(text) or {}
    if "nodes" not in data or not data["nodes"]:
        raise _spec_error(
            "spec/no-nodes",
            "spec has no nodes",
            supported_fixes=("add at least one entry under `nodes`",),
        )

    provider = data.get("provider", "generic")
    profile = data.get("profile")
    if profile not in (None, "deployment-ownership"):
        raise _spec_error(
            "spec/unknown-profile",
            f"unknown profile: {profile!r}",
            evidence={"profile": profile},
            supported_fixes=(
                "omit `profile` for the default visual-only validation",
                "set `profile: deployment-ownership`",
            ),
        )

    sources = _parse_sources(data)
    source_ids = {source.id for source in sources}

    node_ids = set()
    nodes = []
    for raw in data["nodes"]:
        if "id" not in raw:
            raise _spec_error(
                "spec/node-missing-id",
                f"node missing id: {raw}",
                evidence={"node": raw},
                supported_fixes=("give the node a unique `id`",),
            )
        for field_name in ("external", "storage"):
            value = raw.get(field_name, False)
            if not isinstance(value, bool):
                raise _spec_error(
                    "spec/invalid-node-boolean",
                    f"node {raw['id']!r} field {field_name!r} must be boolean",
                    subject={"node": raw["id"]},
                    evidence={"field": field_name, "value": value},
                    supported_fixes=(
                        f"set `{field_name}` to true or false without quotes",
                    ),
                )

        if raw["id"] in node_ids:
            raise _spec_error(
                "spec/duplicate-node-id",
                f"duplicate node id: {raw['id']}",
                subject={"node": raw["id"]},
                supported_fixes=(
                    "rename one of the nodes so every `id` is unique",
                    "delete the duplicate node entry",
                ),
            )
        node_ids.add(raw["id"])
        nodes.append(
            Node(
                id=raw["id"],
                label=raw.get("label", raw["id"]),
                service=raw.get("service"),
                sublabel=raw.get("sublabel", ""),
                zone=raw.get("zone"),
                color=raw.get("color", "#3A3A3A"),
                provider=raw.get("provider", provider),
                owner=raw.get("owner"),
                external=raw.get("external", False),
                storage=raw.get("storage", False),
                sources=_parse_source_attachments(raw, {"node": raw["id"]}, source_ids),
            )
        )

    zone_ids = set()
    zones = []
    for raw in data.get("zones", []) or []:
        if "id" not in raw:
            raise _spec_error(
                "spec/zone-missing-id",
                f"zone missing id: {raw}",
                evidence={"zone": raw},
                supported_fixes=("give the zone a unique `id`",),
            )
        zone_ids.add(raw["id"])
        kind = raw.get("kind", "generic")
        if kind not in ("generic", "region", "security"):
            raise _spec_error(
                "spec/invalid-zone-kind",
                f"zone {raw['id']!r} has invalid kind {kind!r}",
                subject={"zone": raw["id"]},
                evidence={
                    "kind": kind,
                    "allowed_kinds": ["generic", "region", "security"],
                },
                supported_fixes=(
                    "omit `kind` for a visual-only generic zone",
                    "set `kind` to `generic`, `region`, or `security`",
                ),
            )

        zones.append(
            Zone(
                id=raw["id"],
                label=raw.get("label", raw["id"]),
                parent=raw.get("parent"),
                kind=kind,
            )
        )
    for node in nodes:
        if node.zone is not None and node.zone not in zone_ids:
            raise _spec_error(
                "spec/unknown-zone",
                f"node {node.id!r} references unknown zone {node.zone!r}",
                subject={"node": node.id},
                evidence={"zone": node.zone, "known_zones": sorted(zone_ids)},
                supported_fixes=(
                    "declare the zone under `zones`",
                    "point the node's `zone` at an existing zone id",
                    "drop the node's `zone` field",
                ),
            )
    for zone in zones:
        if zone.parent is not None and zone.parent not in zone_ids:
            raise _spec_error(
                "spec/unknown-zone-parent",
                f"zone {zone.id!r} references unknown parent {zone.parent!r}",
                subject={"zone": zone.id},
                evidence={"parent": zone.parent, "known_zones": sorted(zone_ids)},
                supported_fixes=(
                    "declare the parent zone under `zones`",
                    "point `parent` at an existing zone id",
                    "drop `parent` to make this a top-level zone",
                ),
            )
        if zone.parent == zone.id:
            raise _spec_error(
                "spec/zone-self-parent",
                f"zone {zone.id!r} cannot be its own parent",
                subject={"zone": zone.id},
                supported_fixes=(
                    "drop `parent` to make this a top-level zone",
                    "point `parent` at the enclosing zone",
                ),
            )

    edges = []
    for raw in data.get("edges", []) or []:
        if raw.get("from") not in node_ids or raw.get("to") not in node_ids:
            raise _spec_error(
                "spec/unknown-edge-node",
                f"edge references unknown node: {raw}",
                evidence={"edge": raw, "known_nodes": sorted(node_ids)},
                supported_fixes=(
                    "point `from` and `to` at existing node ids",
                    "declare the missing node under `nodes`",
                ),
            )
        edges.append(
            Edge(
                src=raw["from"],
                dst=raw["to"],
                id=raw.get("id"),
                label=raw.get("label", ""),
                type=raw.get("type", "default"),
                sources=_parse_source_attachments(
                    raw,
                    {"edge": raw.get("id", {"from": raw["from"], "to": raw["to"]})},
                    source_ids,
                ),
            )
        )

    return Spec(
        title=data.get("title", ""),
        direction=data.get("direction", "LR").upper(),
        provider=provider,
        nodes=nodes,
        zones=zones,
        edges=edges,
        profile=profile,
        sources=sources,
    )
