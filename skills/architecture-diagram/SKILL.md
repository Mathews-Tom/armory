---
name: architecture-diagram
description: 'Generate layered architecture diagrams as self-contained HTML with inline SVG icons, CSS Grid containers, and connection overlays. Triggers on: "architecture diagram", "infra diagram", "system diagram", "deployment diagram", "topology", "draw architecture". NOT for architecture reviews, use architecture-reviewer.'
metadata:
  version: 1.1.1
  category: review
  tags: [architecture, diagram, visualization, svg]
  difficulty: intermediate
---

# Architecture Diagram Generator

Produces self-contained `.html` files: inline SVG icons, CSS Grid nested zones, JS-driven SVG connection overlay with color-coded semantic line types and arrowhead markers. Zero external dependencies.

## Workflow

1. **Parse** user input → extract: components (with descriptions), containment hierarchy (zones/nesting), connections (with semantic types), and any provider context
2. **Read** `references/icons.md` — select or create icons for each component
3. **Read** `references/layout-patterns.md` — choose topology pattern, set grid-template-columns
4. **Read** `references/connections.md` — define connection array with types, side-forcing, routing
5. **Start from** `assets/template.html` — use its CSS/JS structure as the base
6. **Assemble** the HTML:
   - Set `{{DIAGRAM_TITLE}}`, `{{BG_COLOR}}`, `{{MAX_WIDTH}}`
   - Populate `{{LEGEND_ITEMS}}` — one entry per connection type used
   - Build zone hierarchy as nested `div.zone > span.zone-label + div.zone-content`
   - Place nodes with `data-node-id`, each containing: `.node-icon` (inline SVG), `.node-title`, `.node-desc`
   - Populate the `connections` JS array
   - Apply provider theming if applicable
7. **Output** final `.html` to the working directory or user-specified path

## Node construction

Every node must have:

- Unique `data-node-id` (semantic: `fusion-hcm`, `edi-adaptor`, not `node-7`)
- `.node-icon` with inline SVG from the icon registry (or custom-generated following registry constraints)
- `.node-title` — short name (1–3 words, bold)
- `.node-desc` — extended description text (protocols, module lists, capabilities). Populate this whenever the user provides detail beyond just a name. This is critical for professional-quality diagrams.

## Key structural invariants

- Every `div.zone` has exactly one `span.zone-label` and one `div.zone-content`
- Every `div.zone-content` has explicit `style="grid-template-columns: ..."`
- Zone depth class (`zone-depth-0` to `zone-depth-3`) matches actual nesting level
- All SVG icons are inline inside `.node-icon` — no external image references
- Connection overlay SVG with `<defs>` (arrow markers for each color) sits after the diagram div
- Connection renderer `<script>` is last before `</body>`
- Legend div sits above the diagram div, containing only types actually used

## Connection type selection

Match connection semantics to the appropriate type:

- **`realtime`** (blue solid): REST, SOAP, API calls, synchronous requests, real-time data
- **`batch`** (red dashed): SFTP, file transfers, EDI, scheduled batch jobs, bulk data
- **`event`** (green solid): event-driven triggers, pub-sub, webhooks, callbacks, business events
- **`control`** (orange dashed): management plane, monitoring, config push, admin flows
- **`default`** (blue solid): when semantic type is ambiguous or only one flow type exists

When the user doesn't specify flow semantics, default all connections to `default` type and omit the legend.

## Design defaults

- Background: `#f0ece4` (warm neutral) or `#e8eef5` (cool blue-gray) — choose based on provider/context
- Zone borders: dashed, colored by depth (warm browns → reds)
- Icons: 44×44px, `--icon-color: #3a3a3a` (or provider-specific)
- Node title: 12px bold, node desc: 10.5px regular #555
- Connections: 2px stroke, curved by default
- Font: Segoe UI / system-ui stack
- Max-width: 1400px typical, increase for complex diagrams

## Handling ambiguity

- Infer zone nesting from naming conventions (Region > VPC > Subnet, etc.)
- Default to `default` connections and no legend if flow types are unspecified
- Place management/observability services outside the main data-path zones
- Use generic icon set and warm-neutral background unless provider is specified
- Ask for clarification only when component list or topology is fundamentally ambiguous

## Error Handling

| Problem                                               | Cause                                           | Fix                                                                                                                                                              |
| ----------------------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `assets/template.html` missing                        | File deleted or skill directory incomplete      | Regenerate from skill defaults: reconstruct the CSS/JS skeleton using the structure documented in this SKILL.md and the reference files                          |
| Icon reference not found in `references/icons.md`     | Component type not in the registry              | Fall back to the generic box icon defined in `references/icons.md § Generic Fallback`; log the missing icon name in a comment                                    |
| Connection lines overlap or route through nodes       | Dense graph with auto-routing conflicts         | Adjust zone layout: increase `grid-template-columns` spacing, add intermediate waypoint nodes, or use `side-forcing` attributes from `references/connections.md` |
| Playwright render failure during HTML-to-image export | Chromium not installed or script error          | Run `playwright install chromium`; check browser console via `--headed` flag; verify no JS syntax errors in the connection renderer script                       |
| Zone nesting exceeds depth-3 styling                  | Architecture has more than 4 containment levels | Flatten by combining the deepest two levels into a single zone, or split into two separate diagrams linked by description                                        |

## References

- `references/icons.md` — 28+ SVG icon definitions, custom icon rules, provider color table
- `references/layout-patterns.md` — node structure, zone nesting, 5 topology patterns, interior grid guidance, sizing table
- `references/connections.md` — connection schema, 6 semantic types with colors, side-forcing, route modes, legend markup
- `assets/template.html` — complete HTML skeleton: CSS, legend, zone/node styles, marker defs for all colors, connection renderer JS with auto side-detection
