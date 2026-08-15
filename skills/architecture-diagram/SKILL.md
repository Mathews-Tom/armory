---
name: architecture-diagram
description: 'Generate architecture diagrams as fully editable SVG with native AWS, Azure, and GCP icons for cloud diagrams, or hand-drawn generic icons for everything else. Deterministic layout computes zone nesting and orthogonal routing instead of hand-placed coordinates. Triggers on: "architecture diagram", "infra diagram", "system diagram", "deployment diagram", "topology diagram", "draw architecture", "AWS diagram", "Azure diagram", "GCP diagram", "cloud infrastructure diagram", "VPC diagram", "draw my AWS setup". Use when a user wants a static architecture diagram they can still edit afterward in Figma, Illustrator, or Inkscape. NOT for architecture reviews, use architecture-reviewer.'
metadata:
  version: 2.0.0
  category: visualization
  tags: [architecture, diagram, svg, aws, azure, gcp, cloud, icons]
  difficulty: intermediate
  phase: build
---

# Architecture Diagram Generator

Produces standalone, fully editable `.svg` files: real inlined vector icons (AWS/Azure/GCP official architecture icons, or a hand-drawn generic set for anything else), deterministic zone-aware layout, orthogonal connection routing, real `<text>` labels. Zero raster images, zero `<use>` clones — every icon is inlined per node so the output opens cleanly as an editable layer tree in Figma, Illustrator, Inkscape, or draw.io.

## When to use this

| Situation | Use this skill? |
|---|---|
| "Draw our AWS/Azure/GCP architecture" | **Yes** |
| "System topology diagram for docs" | **Yes** |
| "I need to edit this diagram afterward in Figma" | **Yes** — this is the differentiator vs. every raster-output alternative |
| Multi-cloud or hybrid (cloud + on-prem) diagram | **Yes** — mix `provider:` per node freely |
| Interactive, click-through, or animated diagram | No — use `static-web-artifacts-builder` |
| Hand-drawn / whiteboard-style sketch | No — use `tldraw` |
| Data chart, plot, or dashboard | No — use `chart-clarity` |
| Reviewing or critiquing an existing architecture | No — use `architecture-reviewer` |
| Single-frame concept illustration with no components/connections | No — use `concept-to-image` |

## Prerequisites

- `python3` with `pyyaml` installed (`uv run --with pyyaml python3 scripts/render.py ...` if not already available).
- **Cloud-provider icons need a one-time, per-machine network fetch.** Icons are never bundled in this skill — AWS, Azure, and GCP's own terms permit using their icons to build diagrams but none grant redistribution rights, so nothing is vendored. The first time a diagram needs a given provider's icons, run:

  ```bash
  python3 scripts/fetch_icons.py --provider aws    # ~5s, 1037 icons
  python3 scripts/fetch_icons.py --provider gcp    # ~5s, 297 icons
  python3 scripts/fetch_icons.py --provider azure  # ~60s, 704 icons
  # or: --provider all
  ```

  This builds a local cache (default `~/.cache/armory/cloud-icons`, override with `--cache-dir` or `$XDG_CACHE_HOME`) pinned to a specific `jgraph/drawio` commit, so output is reproducible. Subsequent renders reuse the cache — no network needed after the first fetch per provider. `provider: generic` needs no fetch at all; it uses the bundled hand-drawn icon set in `references/icons-generic.md`.

## Workflow

1. **Parse** the user's request: components (with descriptions), containment hierarchy (zones — VPC/Region/Resource Group/Subnet), connections (with semantic types if specified), and cloud provider(s).
2. **Resolve services to icons.** For each cloud component, read `references/services-aws.yaml`, `references/services-azure.yaml`, or `references/services-gcp.yaml` (whichever matches its provider) — or `references/icons-generic.md` for non-cloud — and note the exact slug to use as that node's `service` field. If a service genuinely has no icon in that provider's set (documented per-provider in each table), either pick the closest sibling category or leave `service` unset — the renderer falls back to a labeled placeholder rather than a wrong icon.
3. **Ensure the icon cache is warm** for every provider used (see Prerequisites). Skip this for `provider: generic`.
4. **Author the spec** — a small YAML file per `references/spec-format.md`: `title`, `direction` (`LR`/`TB`), `zones` (with `parent` for nesting), `nodes` (`id`, `label`, `service`, `zone`, `color`), `edges` (`from`, `to`, `label`, `type`).
5. **Render:**
   ```bash
   python3 scripts/render.py spec.yaml -o diagram.svg
   ```
   Read every line printed to stderr. `error:` lines mean the spec is invalid (fix and rerun). `warning:` lines mean the diagram rendered but something needs attention — a missing icon, an overflowing label, overlapping zones. Fix the spec's node/zone data, not the SVG output directly.
6. **Verify before handing off** — see Verification below. Do not skip this step; a diagram with unresolved warnings looks unprofessional even though the file is technically valid SVG.
7. **Output** the final `.svg` to the working directory or user-specified path. Mention the icon-cache prerequisite only if this was the first render for a given provider.

## Spec fields at a glance

Full schema and worked examples: `references/spec-format.md`. Summary:

```yaml
title: string
direction: LR | TB        # default LR
provider: aws | azure | gcp | generic   # default provider for nodes that omit it
zones:
  - id: string
    label: string
    parent: string | null # nesting — omit for a top-level zone
nodes:
  - id: string             # unique
    label: string
    sublabel: string       # optional secondary line
    service: string        # icon cache slug — see services-aws.yaml / services-azure.yaml / services-gcp.yaml
    provider: string       # overrides the top-level provider for this node
    zone: string | null    # zone id this node belongs to
    color: "#RRGGBB"       # icon fill color
edges:
  - from: string            # node id
    to: string              # node id
    label: string           # optional
    type: realtime | batch | event | control | default
```

## Connection type semantics

| type | color | style | use for |
|---|---|---|---|
| `realtime` | blue | solid | REST, gRPC, synchronous requests |
| `batch` | red | dashed | SFTP, file transfer, scheduled jobs |
| `event` | green | solid | pub-sub, webhooks, event-driven triggers |
| `control` | orange | solid | management plane, monitoring, config push |
| `default` | gray | solid | when semantics are unspecified or only one flow type exists |

A legend renders automatically whenever more than one connection type is used in a diagram; it's omitted entirely when every edge is `default`.

## Unsupported / partial coverage

- **Kubernetes and on-premises providers** have no dedicated icon set yet — model them with `provider: generic` (server, container, database, queue, and 31 other hand-drawn glyphs in `references/icons-generic.md`, 35 total) until a future milestone adds native K8s/on-prem icon coverage.
- **GCP and Azure icon coverage is narrower than AWS's** (297 and ~700 icons vs. 1037). `references/services-aws.yaml`, `references/services-azure.yaml`, and `references/services-gcp.yaml` each document that provider's specific gaps (e.g. GCP has no dedicated Vertex AI or Artifact Registry icon; Azure has no dedicated Pipelines/Boards/Artifacts icon) rather than silently substituting a misleading icon.
- **Interactive elements** (click-through, animation, mode toggles) are out of scope — this skill produces one static SVG. Use `static-web-artifacts-builder` for that.
- **PNG/PDF export** isn't built in. Pipe the SVG through a converter afterward if a raster format is needed: `rsvg-convert diagram.svg -o diagram.png` or `cairosvg diagram.svg -o diagram.pdf`.

## Common patterns

### AWS serverless API

```yaml
title: Serverless API — us-east-1
provider: aws
direction: LR
zones:
  - id: vpc
    label: VPC 10.0.0.0/16
nodes:
  - id: cf
    label: CloudFront
    service: cloudfront
    color: "#8C4FFF"
  - id: apigw
    label: API Gateway
    service: api-gateway
    zone: vpc
    color: "#E7157B"
  - id: fn
    label: Lambda
    service: lambda
    zone: vpc
    color: "#ED7100"
  - id: ddb
    label: DynamoDB
    zone: vpc
    service: dynamodb
    color: "#C925D1"
edges:
  - {from: cf, to: apigw, label: HTTPS, type: realtime}
  - {from: apigw, to: fn, label: invoke, type: realtime}
  - {from: fn, to: ddb, label: query, type: realtime}
```

### Azure web app (top-to-bottom)

```yaml
title: Azure Web App
provider: azure
direction: TB
nodes:
  - {id: user, label: User, color: "#6B7280"}
  - {id: gw, label: App Gateway, service: application-gateways, color: "#0078D4"}
  - {id: app, label: App Service, service: app-services, color: "#0078D4"}
  - {id: db, label: SQL Database, service: sql-database, color: "#0078D4"}
edges:
  - {from: user, to: gw, label: HTTPS}
  - {from: gw, to: app}
  - {from: app, to: db, label: TDS}
```

### Multi-cloud pipeline

Mix providers freely — set `provider` per node instead of at the top level:

```yaml
title: Multi-Cloud Data Pipeline
direction: LR
nodes:
  - {id: ingest, label: Kinesis, provider: aws, service: kinesis, color: "#8C4FFF"}
  - {id: transform, label: Dataflow, provider: gcp, service: cloud-dataflow, color: "#4285F4"}
  - {id: notify, label: Logic Apps, provider: azure, service: logic-apps, color: "#0078D4"}
edges:
  - {from: ingest, to: transform, label: stream, type: event}
  - {from: transform, to: notify, label: alert, type: event}
```

### Vendor-neutral / on-prem

Omit `service` (or set `provider: generic`) for nodes with no cloud icon — they render as a colored placeholder with the label's first letter:

```yaml
title: On-Prem 3-Tier
provider: generic
direction: LR
nodes:
  - {id: lb, label: Nginx, color: "#3A3A3A"}
  - {id: app, label: App Servers, color: "#3A3A3A"}
  - {id: db, label: PostgreSQL, color: "#3A3A3A"}
edges:
  - {from: lb, to: app}
  - {from: app, to: db}
```

## Handling ambiguity

- Infer zone nesting from naming conventions (Region > VPC > Subnet, Resource Group > VNet > Subnet).
- Default to `default` connection type and no legend when the user doesn't specify flow semantics.
- Default to `LR` direction for request/data-flow diagrams, `TB` for hierarchical or layered ones.
- Use `provider: generic` and the hand-drawn icon set when no cloud provider is specified or the architecture is vendor-neutral.
- Ask for clarification only when the component list or topology is fundamentally unclear — never when a single icon is missing (fall back per Unsupported above).

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `error: could not fetch <provider> icons` | No network on first use, or a transient GitHub/CDN timeout | Rerun `fetch_icons.py` for that provider — it retries individual file fetches automatically; a full retry from scratch is cheap since already-cached icons are skipped |
| `warning: no icon for node 'x'` | The `service` slug doesn't exist in that provider's cache, or the icon cache for that provider was never fetched | Check `references/services-aws.yaml` (or the `-azure`/`-gcp` equivalent) for the exact slug; run `fetch_icons.py --provider aws` (or `azure`/`gcp`) if the cache is cold |
| `warning: zone overlap` | Two zones' member nodes are interleaved in rank/order so their bounding boxes collide | Reorder the spec's `nodes` list so each zone's members are listed together, or check the zone assignments are correct |
| `warning: label may overflow its node box` | A node or edge label is too long for the fixed-width node box | Shorten the label, or move detail into `sublabel` |
| Diagram looks fine locally but breaks when reopened elsewhere | Should not happen — `render.py` never emits `<image>`, `<use>`, or external `href`s (enforced by `check_editability`, run automatically on every render) | If this happens anyway, file it as a bug — it means the invariant broke |
| Icons render as plain colored squares with an initial letter, no glyph | The node has no `service` set, or the slug wasn't found — this is the deliberate fallback, not a crash | Add the correct `service` slug from the provider's reference table |

## Verification

Before handing a diagram to the user, confirm:

- [ ] `render.py` exited 0 (a nonzero exit means an editability violation slipped through — treat as a bug, not something to work around)
- [ ] Every `warning:` line printed to stderr has been addressed or is a deliberate, explainable tradeoff (e.g. "no icon exists for this service, using a placeholder")
- [ ] Zone containment matches the described architecture (open the SVG or render it to PNG and look — `rsvg-convert diagram.svg -o /tmp/check.png`)
- [ ] Every node the user asked for is present and labeled
- [ ] Connection types match the described data flows, and the legend appears only when more than one type is used

## Output

Write the final SVG to the working directory (or the user-specified path) and report:

- The output path
- Any warnings that were left unresolved and why
- Whether this was the first render for a given provider (mention the icon-cache fetch cost only once, not on every subsequent render)

## Reference table

| File | Contents | Read when |
|---|---|---|
| `references/spec-format.md` | Full YAML spec schema, field-by-field, with edge cases | Always, before authoring a spec |
| `references/services-aws.yaml` | AWS service name → icon slug + color, ~70 entries, documented gaps | Diagramming AWS components |
| `references/services-azure.yaml` | Azure service name → icon slug + color, ~45 entries, documented gaps | Diagramming Azure components |
| `references/services-gcp.yaml` | GCP service name → icon slug + color, ~35 entries, documented gaps | Diagramming GCP components |
| `references/icons-generic.md` | 35 hand-drawn generic icons (server, database, queue, user, …) for non-cloud diagrams | `provider: generic`, or any node with no cloud equivalent |
| `references/editability.md` | Why the output never uses `<use>`/raster/outlined text, and what "editable" actually verifies | Understanding or modifying the renderer's output contract |

## Scripts

| File | Purpose |
|---|---|
| `scripts/render.py` | Spec → SVG. The tool you actually run. |
| `scripts/fetch_icons.py` | Builds the local icon cache (one-time per provider). |
| `scripts/stencil2svg.py` | AWS/GCP stencil-to-SVG converter — internal, not invoked directly. |
| `scripts/svg_inline.py` | Azure real-SVG inliner/namespacer — internal, not invoked directly. |

## Assets

| File | Contents |
|---|---|
| `assets/example-serverless.yaml` | A complete, real spec (AWS, zones, mixed connection types) — copy as a starting point |
| `assets/example-serverless.svg` | That spec's actual rendered output, committed for reference |
| `assets/generic-icons.json` | The data `BundledGenericIconLookup` reads; `references/icons-generic.md` is this same content in agent-readable form |
