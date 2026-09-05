---
name: architecture-diagram
description: 'Generate architecture diagrams as fully editable SVG with native AWS, Azure, and GCP icons for cloud diagrams, or hand-drawn generic icons for everything else. Deterministic layout computes zone nesting and orthogonal routing instead of hand-placed coordinates. Triggers on: "architecture diagram", "infra diagram", "system diagram", "deployment diagram", "topology diagram", "draw architecture", "AWS diagram", "Azure diagram", "GCP diagram", "cloud infrastructure diagram", "VPC diagram", "draw my AWS setup". Use when a user wants a static architecture diagram they can still edit afterward in Figma, Illustrator, or Inkscape. NOT for architecture reviews, use architecture-reviewer.'
metadata:
  version: 2.4.0
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

Run the following commands from this skill directory (`skills/architecture-diagram` in a checkout).

- `python3` with `pyyaml` installed (`uv run --with pyyaml python3 -m engine ...` if not already available).
- **Cloud-provider icons need a one-time, per-machine network fetch.** Icons are never bundled in this skill; their providers publish diagram-use terms, so `architecture-diagram` records each provider's source and terms in the local cache rather than redistributing icon assets. The first time a diagram needs a given provider's icons, run:

  ```bash
  python3 -m engine.fetch_icons --provider aws    # ~5s, 1037 icons
  python3 -m engine.fetch_icons --provider gcp    # ~5s, 297 icons
  python3 -m engine.fetch_icons --provider azure  # ~60s, 704 icons
  # or: --provider all
  ```

  This builds a local cache (default `~/.cache/armory/cloud-icons`, override with `--cache-dir` or `$XDG_CACHE_HOME`) pinned to a specific `jgraph/drawio` commit, so output is reproducible. Each rendered cloud icon is verified against its manifest SHA-256 digest; `icon/digest-mismatch` fails closed and requires the provider cache to be rebuilt with `python3 -m engine.fetch_icons --provider <provider> --force`. Subsequent renders reuse the verified cache — no network needed after the first fetch per provider. `provider: generic` needs no fetch at all; it uses the bundled hand-drawn icon set in `references/icons-generic.md`.

## Workflow

1. **Parse** the user's request: components (with descriptions), containment hierarchy (zones — VPC/Region/Resource Group/Subnet), connections (with semantic types if specified), and cloud provider(s).
2. **Resolve services to icons.** For each cloud component, read `references/services-aws.yaml`, `references/services-azure.yaml`, or `references/services-gcp.yaml` (whichever matches its provider) — or `references/icons-generic.md` for non-cloud — and note the exact slug to use as that node's `service` field. If a service genuinely has no icon in that provider's set (documented per-provider in each table), either pick the closest sibling category or leave `service` unset — the renderer falls back to a labeled placeholder rather than a wrong icon.
3. **Ensure the icon cache is warm** for every provider used (see Prerequisites). Skip this for `provider: generic`.
4. **Author the spec** — a small YAML file per `references/spec-format.md`: `title`, `direction` (`LR`/`TB`), `zones` (with `parent` for nesting), `nodes` (`id`, `label`, `service`, `zone`, `color`), `edges` (`id`, `from`, `to`, `label`, `type`).
5. **Validate without writing an artifact:**
   ```bash
   python3 -m engine validate spec.yaml --quality showcase --json
   ```
   The receipt contains exact spec and candidate-artifact SHA-256 digests, validation counts, quality profile, composition status, and coded diagnostics. `validate` never touches an output path.
   For declared `sources`, add `--verify-sources`; it fail-closes against local Git commits, blobs, and inclusive line ranges from the spec's checkout. It requires an `origin` remote and never copies source content or contacts a remote service.
   Use `--layout-json` instead of `--json` when an agent needs the exact emitted node boxes, zone membership and boxes, routed edge waypoints, and edge-label rectangles for review. It also never writes SVG output.
6. **Deliver only a clean candidate:**
   ```bash
   python3 -m engine deliver spec.yaml -o diagram.svg --quality showcase --json
   ```
   `deliver` stages the exact spec and candidate SVG beside the target, then atomically replaces the target only after every check passes. With `--verify-sources`, it delivers `diagram.svg` and `diagram.sources.json`; the SVG carries local `VERIFIED SRC n` badges and source-id metadata, while the sidecar binds verified references to the delivered SVG digest. Caught write or replacement failures restore the prior pair; process termination between replacements is outside that rollback contract.
7. **Compare authored revisions when needed:**
   ```bash
   python3 -m engine compare base.yaml head.yaml
   ```
   `compare` emits a JSON receipt keyed only by authored node and edge ids. It reports added, removed, changed, moved, and rerouted entities with exact field paths. Its mandatory limitation is: `Authored specification only; no runtime impact, causality, risk, or merge safety is inferred.`
8. **Output** the final `.svg` to the working directory or user-specified path. Mention the icon-cache prerequisite only if this was the first render for a given provider.

## Spec fields at a glance

Full schema and worked examples: `references/spec-format.md`. Summary:

```yaml
title: string
direction: LR | TB        # default LR
provider: aws | azure | gcp | generic   # default provider for nodes that omit it
profile: deployment-ownership             # opt-in blocking deployment checks
sources:
  - id: string               # unique authored reference id
    revision: 40-char hex    # declared Git object id
    path: relative POSIX path
    lines: [start, end]      # positive inclusive range
zones:
  - id: string
    label: string
    parent: string | null # nesting — omit for a top-level zone
    kind: generic | region | security # default generic
nodes:
  - id: string             # unique
    label: string
    sublabel: string       # optional secondary line
    service: string        # icon cache slug — see services-aws.yaml / services-azure.yaml / services-gcp.yaml
    provider: string       # overrides the top-level provider for this node
    zone: string | null    # zone id this node belongs to
    color: "#RRGGBB"       # icon fill color
    owner: string          # required for non-external nodes under deployment-ownership
    external: boolean      # default false
    storage: boolean       # true requires a security zone under deployment-ownership
    sources: [source-id]     # optional declared source ids
edges:
  - id: string              # required and stable when using compare
    from: string            # node id
    to: string              # node id
    label: string           # required for security-boundary crossings under deployment-ownership
    type: realtime | batch | event | control | default
    sources: [source-id]     # optional declared source ids
```

### Deployment ownership validation

Set `profile: deployment-ownership` only when the spec is a deployment ownership record rather than a visual-only diagram. The profile fails closed: every node must resolve to exactly one `kind: region`, every non-external node needs a non-blank `owner`, every `storage: true` node must be inside `kind: security`, and a cross-security-zone edge needs a non-blank label naming its mechanism. It never infers those facts from labels, icons, service slugs, or layout. Omit `profile` to preserve existing behavior.

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

## Exit codes and diagnostics

Every finding is a coded diagnostic carrying `code`, `severity`, `message`, `subject` (what it is about), `evidence` (the numbers that locate it), `supported_fixes` (spec-level moves), and sometimes `suppresses`. The exit code is the verdict:

| Exit | Meaning | Action |
|---|---|---|
| 0 | `validate` completed with no error findings, or `deliver` atomically committed a validated SVG | Hand off the receipt or SVG; any warnings are deliberate, explainable tradeoffs |
| 1 | A blocking finding or operational delivery failure | Apply a diagnostic's `supported_fixes`, or correct the output path or filesystem permissions |
| 2 | Usage error — missing subcommand, unreadable spec path, unknown flag or profile value | Correct the command |

`--json` prints the receipt and nothing else on stdout. It contains `input` and `artifact` SHA-256/byte records, `output.written`, `validation.checks_passed`/`checks_total`, quality, composition status, severity counts, and diagnostics. `--quality showcase` raises `composition/*` route-geometry findings to errors; the default `standard` keeps them as warnings.

| Code | Meaning | Fix |
|---|---|---|
| `spec/*` | The spec is unanswerable: no nodes, duplicate or missing ids, unknown zone/parent/edge endpoint, zone cycle, empty zone | Each diagnostic's `supported_fixes` names the field to change |
| `icon/not-found` | The `service` slug is absent from that provider's cache, or the cache was never fetched | Use the exact slug from that provider's reference service map, or run `fetch_icons.py --provider <name>`; drop `service` to take the labeled placeholder deliberately |
| `layout/node-overlap` | Two node boxes collide | Separate the nodes across ranks, or remove the duplicate |
| `layout/zone-overlap` | Two unrelated zone boxes collide because their member nodes are interleaved | List each zone's members contiguously in `nodes`, or fix the `zone` assignments |
| `layout/label-overflow` | A `label` or `sublabel` cannot fit in its node box at the hard 6px minimum (blocking) | Shorten it, or move detail into `sublabel` |
| `editability/*` | The output contains raster, `<use>`, or an external reference | Renderer bug — a spec cannot cause this; report it |
| `usage/spec-unreadable` | The spec path does not exist or cannot be read | Pass an existing, readable YAML path |

A fetch failure (`could not fetch <provider> icons`) is a network problem, not a spec problem: rerun `fetch_icons.py` for that provider, which skips already-cached icons.

## Output

Report the output path, any warning-severity findings left unresolved and why, and — only on the first render for a given provider — the icon-cache fetch cost.

## Reference table

| File | Contents | Read when |
|---|---|---|
| `references/spec-format.md` | Full YAML spec schema, field-by-field, with edge cases | Always, before authoring a spec |
| `references/services-aws.yaml` | AWS service name → icon slug + color, ~70 entries, documented gaps | Diagramming AWS components |
| `references/services-azure.yaml` | Azure service name → icon slug + color, ~45 entries, documented gaps | Diagramming Azure components |
| `references/services-gcp.yaml` | GCP service name → icon slug + color, ~35 entries, documented gaps | Diagramming GCP components |
| `references/icons-generic.md` | 35 hand-drawn generic icons (server, database, queue, user, …) for non-cloud diagrams | `provider: generic`, or any node with no cloud equivalent |
| `references/editability.md` | Why the output never uses `<use>`/raster/outlined text, and what "editable" actually verifies | Understanding or modifying the renderer's output contract |

## Engine

| File | Purpose |
|---|---|
| `engine/__main__.py` | `python3 -m engine` entry point for validate, deliver, and compare. |
| `engine/pipeline.py` | Deterministic spec → SVG composition and render result. |
| `engine/commands.py` | Validation, delivery, comparison receipts, staging, and CLI dispatch. |
| `engine/fetch_icons.py` | Local icon-cache builder; invoke with `python3 -m engine.fetch_icons`. |
| `engine/stencil2svg.py` | AWS/GCP stencil-to-SVG converter — internal. |
| `engine/svg_inline.py` | Azure real-SVG inliner/namespacer — internal. |
| `engine/data.py` | Single resolver for bundled assets and reference data. |

## Assets

| File | Contents |
|---|---|
| `assets/example-serverless.yaml` | A complete, real spec (AWS, zones, mixed connection types) — copy as a starting point |
| `assets/example-serverless.svg` | That spec's actual rendered output, committed for reference |
| `assets/generic-icons.json` | The data `BundledGenericIconLookup` reads; `references/icons-generic.md` is this same content in agent-readable form |
