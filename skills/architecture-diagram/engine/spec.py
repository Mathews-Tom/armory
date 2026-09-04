"""YAML specification parsing and authored-input diagnostics."""

from __future__ import annotations

import yaml

from .diagnostics import Diagnostic, SEVERITY_ERROR
from .model import Edge, Node, Spec, Zone


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
    )
