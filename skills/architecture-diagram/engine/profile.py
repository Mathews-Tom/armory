"""Fail-closed authored deployment-ownership profile checks."""

from __future__ import annotations

from .diagnostics import Diagnostic, SEVERITY_ERROR
from .layout import zone_ancestors
from .model import Node, Spec


def _zone_membership(spec: Spec, node: Node) -> set[str]:
    if node.zone is None:
        return set()
    return {node.zone, *zone_ancestors(spec, node.zone)}


def _profile_diagnostic(
    code: str,
    message: str,
    subject: dict[str, object],
    evidence: dict[str, object],
    supported_fixes: tuple[str, ...],
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=SEVERITY_ERROR,
        message=message,
        subject=subject,
        evidence=evidence,
        supported_fixes=supported_fixes,
    )


def check_deployment_profile(spec: Spec) -> list[Diagnostic]:
    """Validate authored deployment facts without assigning missing facts."""
    if spec.profile != "deployment-ownership":
        return []

    memberships = {node.id: _zone_membership(spec, node) for node in spec.nodes}
    region_ids = {zone.id for zone in spec.zones if zone.kind == "region"}
    security_ids = {zone.id for zone in spec.zones if zone.kind == "security"}
    findings: list[Diagnostic] = []

    missing_kinds = [
        kind
        for kind, present in (("region", region_ids), ("security", security_ids))
        if not present
    ]
    if missing_kinds:
        findings.append(
            _profile_diagnostic(
                "profile/missing-required-zone-kinds",
                f"deployment profile requires zone kinds: {', '.join(missing_kinds)}",
                {"profile": spec.profile},
                {
                    "missing_kinds": missing_kinds,
                    "declared_zones": [
                        {"id": zone.id, "kind": zone.kind} for zone in spec.zones
                    ],
                },
                (
                    "add at least one `kind: region` zone",
                    "add at least one `kind: security` zone",
                ),
            )
        )

    for node in spec.nodes:
        if not node.external and (
            not isinstance(node.owner, str) or not node.owner.strip()
        ):
            findings.append(
                _profile_diagnostic(
                    "profile/missing-owner",
                    f"node {node.id!r} has no non-blank owner",
                    {"node": node.id},
                    {"external": node.external, "owner": node.owner},
                    (
                        "set the node's `owner` to the accountable team or service",
                        "set `external: true` only for an externally owned node",
                    ),
                )
            )

        node_regions = sorted(memberships[node.id] & region_ids)
        if not node_regions:
            findings.append(
                _profile_diagnostic(
                    "profile/missing-region-scope",
                    f"node {node.id!r} is not contained by a region zone",
                    {"node": node.id},
                    {
                        "zone": node.zone,
                        "zone_membership": sorted(memberships[node.id]),
                    },
                    ("assign the node to a zone nested under one `kind: region` zone",),
                )
            )
        elif len(node_regions) > 1:
            findings.append(
                _profile_diagnostic(
                    "profile/ambiguous-region",
                    f"node {node.id!r} is contained by multiple region zones",
                    {"node": node.id},
                    {"regions": node_regions},
                    ("nest the node under exactly one `kind: region` zone",),
                )
            )

        if node.storage and not (memberships[node.id] & security_ids):
            findings.append(
                _profile_diagnostic(
                    "profile/storage-outside-security-zone",
                    f"storage node {node.id!r} is outside a security zone",
                    {"node": node.id},
                    {
                        "zone": node.zone,
                        "zone_membership": sorted(memberships[node.id]),
                    },
                    (
                        "assign the storage node to a zone nested under `kind: security`",
                    ),
                )
            )

    for security_id in sorted(security_ids):
        security_regions = sorted(zone_ancestors(spec, security_id) & region_ids)
        if len(security_regions) != 1:
            findings.append(
                _profile_diagnostic(
                    "profile/inconsistent-security-zone-region",
                    f"security zone {security_id!r} does not resolve to one region",
                    {"zone": security_id},
                    {
                        "regions": security_regions,
                        "parent": next(
                            zone.parent for zone in spec.zones if zone.id == security_id
                        ),
                    },
                    ("nest the security zone under exactly one `kind: region` zone",),
                )
            )

    for edge in spec.edges:
        source_security = memberships[edge.src] & security_ids
        destination_security = memberships[edge.dst] & security_ids
        if source_security != destination_security and not edge.label.strip():
            findings.append(
                _profile_diagnostic(
                    "profile/missing-boundary-crossing-mechanism",
                    f"edge {edge.src!r}->{edge.dst!r} crosses a security boundary without a mechanism",
                    {"edge": {"from": edge.src, "to": edge.dst}},
                    {
                        "from_security_zones": sorted(source_security),
                        "to_security_zones": sorted(destination_security),
                        "from_node": edge.src,
                        "to_node": edge.dst,
                    },
                    (
                        "set a non-blank edge `label` naming the boundary-crossing mechanism",
                    ),
                )
            )
    return findings
