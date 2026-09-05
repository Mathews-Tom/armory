# Spec Format

The input to `python3 -m engine` is a small YAML file. This is the complete schema — every field, its type, default, and what happens when it's omitted or wrong.

## Top level

```yaml
title: string              # optional; omit for no title bar
direction: LR | TB         # optional, default LR
provider: aws | azure | gcp | generic   # optional, default generic — sets the default for nodes that omit their own provider
profile: deployment-ownership            # optional; opt-in deployment validation
sources: [...]              # optional authored source declarations
zones: [...]                # optional
nodes: [...]                 # required, at least one
edges: [...]                 # optional
```

`direction` controls the layout axis: `LR` ranks flow left-to-right (use for request/data-flow diagrams — most architecture diagrams), `TB` ranks flow top-to-bottom (use for hierarchical or layered diagrams — network topology, layered architectures).

### Deployment ownership profile

`profile: deployment-ownership` enables blocking checks over facts explicitly authored in the YAML. Omitting `profile` keeps the default visual-only behavior unchanged. The profile never derives an owner, a storage role, a region, or a boundary mechanism from labels, service slugs, or layout.

With the profile enabled, declare at least one `kind: region` zone and one `kind: security` zone. Every node must resolve through its zone ancestry to exactly one region; every `kind: security` zone and its member nodes must resolve to one region. Every non-external node requires a non-blank `owner`. Mark storage explicitly with `storage: true`; those nodes must be inside a security zone. An edge whose endpoints have different security-zone membership requires a non-blank `label` naming its crossing mechanism.

The zone-kind enum is `generic` (the default), `region`, and `security`. `generic` remains decorative; the profile only enforces the facts above when explicitly enabled.

## `sources`

Source declarations record authored evidence without changing rendering or `compare` results. Every attachment on a node or edge must name one declaration.

```yaml
sources:
  - id: src-api             # required, unique non-blank string
    revision: 0123...cdef   # required, full 40-character hexadecimal Git object id
    path: src/api.py        # required, non-empty relative POSIX path
    lines: [41, 73]         # required, positive inclusive start and end lines
```

`path` cannot be absolute or contain `.` or `..` segments. `lines` must contain exactly two integer values, with `start >= 1` and `end >= start`. This schema declares references only; it does not read a repository or verify that an object, path, or line range exists.

## `nodes`

```yaml
nodes:
  - id: string          # required, unique across the whole spec
    label: string        # optional, defaults to id
    sublabel: string      # optional, second line under label (protocol, environment, etc.)
    service: string        # optional, icon cache slug
    provider: string        # optional, overrides the top-level provider for this node
    zone: string             # optional, id of the zone this node belongs to
    color: "#RRGGBB"          # optional, defaults to "#3A3A3A", the icon square's fill
    owner: string             # required for non-external nodes under deployment-ownership
    external: boolean         # optional, default false; external nodes do not require owner
    storage: boolean          # optional, default false; true requires a security zone under deployment-ownership
    sources: [src-api]       # optional declared source ids, each at most once
```

`service` is the exact cache slug from `references/services-aws.yaml`, `references/services-azure.yaml`, or `references/services-gcp.yaml` (cloud providers) or `references/icons-generic.md` (`provider: generic`) — not a free-text service name. A `service` slug with no matching cache entry produces a `warning: no icon for node` at render time and the node falls back to a labeled placeholder (a colored square with the label's first letter) rather than failing the render. A node with no `service` set at all renders the same placeholder silently — that's the correct default for a component with no natural icon, not an error.

## `zones`

```yaml
zones:
  - id: string          # required, unique
    label: string          # optional, defaults to id
    parent: string           # optional, id of an enclosing zone — omit for a top-level zone
    kind: generic | region | security   # optional, default generic
```

Every zone must have at least one member node (directly assigned via that node's `zone` field) or at least one child zone (another zone whose `parent` points to it). An empty zone — no members, no children — is a spec error, not a warning; fix the spec rather than working around it.

Nesting is unlimited depth via `parent`. A zone's rendered box is the bounding box of everything inside it (member nodes' positions plus child zones' boxes) with padding and a label header — you don't set zone size or position; the layout engine computes it from what's actually inside.

**Keep each zone's members contiguous in the `nodes` list order.** The layout engine assigns rank/order from the node graph, not from zone membership directly; if two zones' members end up interleaved across ranks, their bounding boxes can end up overlapping. `geometry_checks.py` catches this (`warning: zone overlap`) rather than shipping a broken-looking diagram, but the fix is almost always reordering `nodes` so each zone's members sit together, or reconsidering whether the topology genuinely needs that interleaving.

## `edges`

```yaml
edges:
  - id: string          # optional for rendering; required, unique, and stable for `compare`
    from: string        # required, a node id
    to: string            # required, a node id
    label: string           # optional
    type: realtime | batch | event | control | default   # optional, default "default"
    sources: [src-api]       # optional declared source ids, each at most once
```

An edge referencing a node id that doesn't exist in `nodes` is a spec error. Edges do not need to respect zone boundaries — a node inside a zone can connect to one outside it freely; the router treats zones as a purely visual grouping, not a routing constraint.

Under `profile: deployment-ownership`, a labeled cross-security-zone edge names the mechanism used at that boundary. The profile rejects an empty or whitespace-only label; it does not infer one from `type`, a service name, or endpoint labels.

`type` drives both the connector's color/style and whether a legend renders — see the connection type table in `SKILL.md`. Cycles (a connects to b, b connects back to a) are fine; the rank-assignment algorithm terminates on them rather than looping, though a diagram with many cycles will look messier since rank order stops being a clean single flow direction.

## Compare two specifications

Run `python3 -m engine compare base.yaml head.yaml` to emit a deterministic JSON receipt. It matches nodes by their authored `id` and edges by their authored `id`; rendering hashes, generated geometry, labels-as-identifiers, and endpoint-pair matching never participate.
Each node or edge is `added`, `removed`, `unchanged`, or has one or more statuses from disjoint authored field groups: node semantic fields produce `changed`, node `zone` produces `moved`, edge semantic fields (`label`, `type`) produce `changed`, and edge endpoints (`from`, `to`) produce `rerouted`. `changed_fields` records the exact JSON-pointer paths and before/after authored values.

Every receipt includes this limitation: `Authored specification only; no runtime impact, causality, risk, or merge safety is inferred.`

## Verify authored source references

Run `python3 -m engine validate --verify-sources spec.yaml --json` to fail closed unless every declared source names a local Git commit, a blob at the declared path, and an in-bounds inclusive line range. Verification starts from the spec file's directory and requires that checkout to have an `origin` remote; detached HEAD is valid because declarations name immutable commits.

Verification uses only direct local Git object reads. It neither copies source bytes into command output nor performs remote lookups. The verifier accepts uppercase Git object ids and records canonical lowercase ids internally. A tree path, binary blob, absent commit/path, or range beyond the blob's line count is a coded error.

## What the renderer computes for you (don't set these)

There is deliberately no `x`, `y`, `width`, or `height` field anywhere in the spec. Layout — which rank each node lands in, its order within that rank, zone bounding boxes, connector routing and bend points — is entirely computed by the deterministic `pipeline.py` composition of layout and routing modules (rank assignment → crossing-minimizing ordering → position assignment → zone bbox union → orthogonal routing). This is a deliberate design choice: prior art in this space asks the model to compute pixel coordinates by hand and self-check them against a long list of prose rules ("no edge crosses an unrelated icon," "align nodes so edges are straight"). That's fragile. Author the graph structure; let the code place it.

## Minimal valid spec

```yaml
nodes:
  - id: a
  - id: b
edges:
  - {from: a, to: b}
```

This is a complete, valid spec — `title` and `direction` fall back to their defaults, both nodes render as placeholders (no `service` set), and the single edge uses the `default` type with no legend. Every other example in `SKILL.md`'s "Common patterns" section builds up from this shape.

## Errors vs. warnings

`commands.py` distinguishes two severities, both printed to stderr:

- **`error:`** — the spec itself is invalid (missing required field, duplicate id, edge/zone reference to a nonexistent id, empty zone, zone cycle). The render does not happen; exit code 1. Fix the spec.
- **`warning:`** — the spec parsed fine and a diagram was produced, but something in it needs attention (missing icon, overflowing label, overlapping zone boxes). Exit code 0 unless the warning is specifically an editability violation (which should never happen — see `references/editability.md`). Read every warning; don't treat "it produced a file" as "it's done."
