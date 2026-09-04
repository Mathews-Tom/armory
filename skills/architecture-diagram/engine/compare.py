"""Canonical authored-spec comparison."""

from __future__ import annotations

from .model import Spec
from .spec import SpecError, _spec_error

_NODE_SEMANTIC_FIELDS = (
    "label",
    "service",
    "sublabel",
    "color",
    "provider",
    "owner",
    "external",
    "storage",
)
_NODE_SCOPE_FIELDS = ("zone",)
_EDGE_SEMANTIC_FIELDS = ("label", "type")
_EDGE_ROUTE_FIELDS = ("from", "to")


def _comparison_error(
    code: str,
    message: str,
    subject: dict[str, object],
    evidence: dict[str, object],
    supported_fixes: tuple[str, ...],
) -> SpecError:
    return _spec_error(code, message, subject, evidence, supported_fixes)


def _canonical_nodes(spec: Spec) -> dict[str, dict[str, object]]:
    nodes: dict[str, dict[str, object]] = {}
    for node in spec.nodes:
        if not isinstance(node.id, str) or not node.id:
            raise _comparison_error(
                "compare/invalid-node-id",
                "comparison requires every node to have a non-blank string id",
                {"node": node.id},
                {"id": node.id},
                ("set each node `id` to a non-blank string",),
            )
        nodes[node.id] = {
            "label": node.label,
            "service": node.service,
            "sublabel": node.sublabel,
            "color": node.color,
            "provider": node.provider,
            "owner": node.owner,
            "external": node.external,
            "storage": node.storage,
            "zone": node.zone,
        }
    return nodes


def _canonical_edges(spec: Spec) -> dict[str, dict[str, object]]:
    edges: dict[str, dict[str, object]] = {}
    for edge in spec.edges:
        if not isinstance(edge.id, str) or not edge.id:
            raise _comparison_error(
                "compare/missing-edge-id",
                "comparison requires every edge to have a non-blank authored id",
                {"edge": {"from": edge.src, "to": edge.dst}},
                {"id": edge.id},
                ("set a unique non-blank `id` on every edge",),
            )
        if edge.id in edges:
            raise _comparison_error(
                "compare/duplicate-edge-id",
                f"comparison found duplicate edge id {edge.id!r}",
                {"edge": edge.id},
                {"id": edge.id},
                ("make every edge `id` unique within its specification",),
            )
        edges[edge.id] = {
            "from": edge.src,
            "to": edge.dst,
            "label": edge.label,
            "type": edge.type,
        }
    return edges


def _field_changes(
    base: dict[str, object], head: dict[str, object], fields: tuple[str, ...]
) -> list[dict[str, object]]:
    return [
        {"path": f"/{field}", "base": base[field], "head": head[field]}
        for field in fields
        if base[field] != head[field]
    ]


def _compare_entities(
    base: dict[str, dict[str, object]],
    head: dict[str, dict[str, object]],
    semantic_fields: tuple[str, ...],
    relocation_fields: tuple[str, ...],
    relocation_status: str,
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for entity_id in sorted(base.keys() | head.keys()):
        before = base.get(entity_id)
        after = head.get(entity_id)
        if before is None:
            changes.append(
                {
                    "id": entity_id,
                    "status": ["added"],
                    "changed_fields": [],
                    "before": None,
                    "after": after,
                }
            )
            continue
        if after is None:
            changes.append(
                {
                    "id": entity_id,
                    "status": ["removed"],
                    "changed_fields": [],
                    "before": before,
                    "after": None,
                }
            )
            continue

        semantic_changes = _field_changes(before, after, semantic_fields)
        relocation_changes = _field_changes(before, after, relocation_fields)
        status = []
        if semantic_changes:
            status.append("changed")
        if relocation_changes:
            status.append(relocation_status)
        changes.append(
            {
                "id": entity_id,
                "status": status or ["unchanged"],
                "changed_fields": semantic_changes + relocation_changes,
            }
        )
    return changes


def compare_specs(base: Spec, head: Spec) -> dict[str, list[dict[str, object]]]:
    """Compare canonical authored IR only; no generated geometry participates."""
    return {
        "nodes": _compare_entities(
            _canonical_nodes(base),
            _canonical_nodes(head),
            _NODE_SEMANTIC_FIELDS,
            _NODE_SCOPE_FIELDS,
            "moved",
        ),
        "edges": _compare_entities(
            _canonical_edges(base),
            _canonical_edges(head),
            _EDGE_SEMANTIC_FIELDS,
            _EDGE_ROUTE_FIELDS,
            "rerouted",
        ),
    }
