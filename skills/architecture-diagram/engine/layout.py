"""Deterministic rank ordering, node placement, and zone geometry."""

from __future__ import annotations

from dataclasses import dataclass

from .model import Spec
from .spec import _spec_error

ICON = 64
NODE_W = 120
NODE_H = 118
COL_GAP = 90
ROW_GAP = 44
MARGIN = 32
TITLE_H = 44
ZONE_PAD = 22
ZONE_LABEL_H = 26

EDGE_LABEL_FONT_SIZE = 10.0
NODE_LABEL_FONT_SIZE = 12.0
NODE_SUBLABEL_FONT_SIZE = 10.5
NODE_TEXT_PADDING = 8.0
MIN_NODE_TEXT_FONT_SIZE = 6.0

_NARROW = set("iIl.,:;'|!")
_WIDE = set("MWm@%")


def text_width(text: str, font_size: float) -> float:
    """Estimate the rendered width of text in the system UI font stack."""
    total = 0.0
    for character in text:
        if character in _NARROW:
            total += 0.32
        elif character in _WIDE:
            total += 0.82
        else:
            total += 0.56
    return total * font_size


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    def overlaps(self, other: Box) -> bool:
        return (
            self.x < other.x2
            and self.x2 > other.x
            and self.y < other.y2
            and self.y2 > other.y
        )


def box_evidence(box: Box) -> dict[str, float]:
    """Serialize one box for receipts and coded diagnostics."""
    return {"x": box.x, "y": box.y, "width": box.w, "height": box.h}


def icon_box(box: Box) -> Box:
    """Return the visible icon square within a label-reserving node box."""
    return Box(box.x + (NODE_W - ICON) / 2, box.y, ICON, ICON)


def assign_ranks(spec: Spec) -> dict[str, int]:
    """Compute bounded longest-path layers without hanging on graph cycles."""
    rank = {node.id: 0 for node in spec.nodes}
    for _ in range(len(spec.nodes) + 1):
        changed = False
        for edge in spec.edges:
            if rank[edge.dst] < rank[edge.src] + 1:
                rank[edge.dst] = rank[edge.src] + 1
                changed = True
        if not changed:
            break
    return rank


def order_within_ranks(spec: Spec, rank: dict[str, int]) -> dict[str, int]:
    """Use two deterministic barycenter sweeps to reduce crossings."""
    by_rank: dict[int, list[str]] = {}
    for node in spec.nodes:
        by_rank.setdefault(rank[node.id], []).append(node.id)
    for ids in by_rank.values():
        ids.sort()

    order: dict[str, int] = {}
    for rank_id in sorted(by_rank):
        for index, node_id in enumerate(by_rank[rank_id]):
            order[node_id] = index

    predecessors: dict[str, list[str]] = {}
    successors: dict[str, list[str]] = {}
    for edge in spec.edges:
        predecessors.setdefault(edge.dst, []).append(edge.src)
        successors.setdefault(edge.src, []).append(edge.dst)

    def sweep(ranks_in_order: list[int], neighbor_map: dict[str, list[str]]) -> None:
        for rank_id in ranks_in_order:
            ids = by_rank[rank_id]

            def barycenter(node_id: str) -> float:
                neighbors = neighbor_map.get(node_id, [])
                if not neighbors:
                    return order[node_id]
                return sum(order[node_id] for node_id in neighbors) / len(neighbors)

            ids.sort(key=barycenter)
            for index, node_id in enumerate(ids):
                order[node_id] = index

    ranks_sorted = sorted(by_rank)
    sweep(ranks_sorted[1:], predecessors)
    sweep(list(reversed(ranks_sorted[:-1])), successors)
    return order


def compute_positions(
    spec: Spec, rank: dict[str, int], order: dict[str, int]
) -> dict[str, Box]:
    """Place node boxes from authored direction and computed rank/order."""
    deepest_zone = max(
        (len(zone_ancestors(spec, zone.id)) + 1 for zone in spec.zones),
        default=0,
    )
    top_offset = MARGIN + TITLE_H + deepest_zone * (ZONE_PAD + ZONE_LABEL_H)
    boxes: dict[str, Box] = {}
    for node in spec.nodes:
        rank_id, order_id = rank[node.id], order[node.id]
        if spec.direction == "TB":
            x = MARGIN + order_id * (NODE_W + COL_GAP)
            y = top_offset + rank_id * (NODE_H + ROW_GAP)
        else:
            x = MARGIN + rank_id * (NODE_W + COL_GAP)
            y = top_offset + order_id * (NODE_H + ROW_GAP)
        boxes[node.id] = Box(x, y, NODE_W, NODE_H)
    return boxes


def compute_zone_boxes(spec: Spec, node_boxes: dict[str, Box]) -> dict[str, Box]:
    """Contain direct members and nested zones with deterministic padding."""
    members: dict[str, list[str]] = {zone.id: [] for zone in spec.zones}
    for node in spec.nodes:
        if node.zone is not None:
            members[node.zone].append(node.id)
    children: dict[str, list[str]] = {zone.id: [] for zone in spec.zones}
    for zone in spec.zones:
        if zone.parent is not None:
            children[zone.parent].append(zone.id)

    boxes: dict[str, Box] = {}

    def resolve(zone_id: str, stack: frozenset[str] = frozenset()) -> Box:
        if zone_id in boxes:
            return boxes[zone_id]
        if zone_id in stack:
            raise _spec_error(
                "spec/zone-cycle",
                f"zone cycle detected at {zone_id!r}",
                subject={"zone": zone_id},
                evidence={"chain": sorted(stack)},
                supported_fixes=(
                    "break the cycle so every zone's `parent` chain ends at a top-level zone",
                ),
            )
        parts = [node_boxes[node_id] for node_id in members[zone_id]]
        parts += [
            resolve(child_id, stack | {zone_id}) for child_id in children[zone_id]
        ]
        if not parts:
            raise _spec_error(
                "spec/empty-zone",
                f"zone {zone_id!r} has no member nodes or child zones",
                subject={"zone": zone_id},
                supported_fixes=(
                    "assign at least one node to the zone via that node's `zone` field",
                    "nest a child zone under it",
                    "delete the zone",
                ),
            )
        x0 = min(part.x for part in parts) - ZONE_PAD
        y0 = min(part.y for part in parts) - ZONE_PAD - ZONE_LABEL_H
        x1 = max(part.x2 for part in parts) + ZONE_PAD
        y1 = max(part.y2 for part in parts) + ZONE_PAD
        box = Box(x0, y0, x1 - x0, y1 - y0)
        boxes[zone_id] = box
        return box

    for zone in spec.zones:
        resolve(zone.id)
    return boxes


def zone_ancestors(spec: Spec, zone_id: str) -> set[str]:
    """Return the ancestor IDs of an already-validated zone."""
    by_id = {zone.id: zone for zone in spec.zones}
    ancestors = set()
    current = by_id[zone_id].parent
    while current is not None:
        if current in ancestors:
            break
        ancestors.add(current)
        current = by_id[current].parent
    return ancestors
