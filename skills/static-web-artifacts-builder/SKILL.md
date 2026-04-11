---
name: static-web-artifacts-builder
description: 'Build self-contained static HTML artifacts opened in a browser: interactive diagrams, dashboards, infographics. Pure HTML5+CSS3+inline SVG, zero toolchain. Triggers on: "interactive HTML", "open in browser", "HTML artifact", "visual dashboard", "HTML infographic". NOT for PNG/SVG output, use concept-to-image.'
metadata:
  version: 1.1.1
  category: visualization
  tags: [html, interactive, dashboard, svg]
  difficulty: intermediate
---

# Static Web Artifacts Builder

To build high-density static infographic artifacts, follow these steps:

1. Initialize the project scaffold using `scripts/init-artifact.sh`
2. Develop your artifact by editing the generated HTML file(s)
3. Validate and finalize using `scripts/bundle-artifact.sh`
4. Display artifact to user

**Stack**: Vanilla HTML5 + CSS3 (Grid/Flexbox) + inline SVG — zero runtime dependencies

## Design & Style Guidelines

VERY IMPORTANT: To avoid what is often referred to as "AI slop", avoid excessive centered layouts, purple gradients, uniform rounded corners, and Inter font.

### Infographic-Specific Constraints

- **Density**: Content-to-whitespace ratio ≥ 70:30. Maximize signal per pixel.
- **Geometry**: Layered/nested containers, shaped regions (clip-path, border-radius variations), gradient fills, subtle box-shadows — not flat uniform boxes.
- **Iconography**: Inline SVG icons for every major concept. No naked text labels.
- **Color**: Purposeful palette (3-4 hues + neutrals), encoding meaning (category, flow direction, severity). Define as CSS custom properties.
- **Flows**: Directional connectors with SVG arrowheads, curved paths, labeled edges. Architecture diagrams = layered tiers with bidirectional data flows, not flat node graphs.
- **Layout math**: CSS Grid with explicit `grid-template-columns`/`grid-template-rows` fractional allocations. No auto-spacing defaults. Every margin/padding intentional.

## Quick Start

### Step 1: Initialize Project

Run the initialization script to create a new static project:

```bash
bash scripts/init-artifact.sh <project-name>
cd <project-name>
```

This creates a minimal scaffold with:

- ✅ Template HTML with CSS custom properties (theming)
- ✅ CSS Grid + Flexbox layout utilities (inline `<style>`)
- ✅ Print-ready viewport meta configuration
- ✅ No node_modules, no package.json, no build toolchain

### Step 2: Develop Your Artifact

Edit the generated `index.html` directly. Each HTML file = one page = one clear message.

Key patterns:

- Use CSS Grid `grid-template-areas` for named region layouts
- Use `fr` units for proportional spatial allocation
- Embed SVG icons inline (not as external references)
- Use CSS custom properties (`--color-primary`, `--color-accent`, etc.) for palette cohesion
- Use `clip-path`, `border-radius`, gradients, and `box-shadow` for visual depth

### Step 3: Validate and Finalize

```bash
bash scripts/bundle-artifact.sh
```

This validates the artifact is fully self-contained:

- Checks for zero external resource references (no CDN links, no external stylesheets/scripts)
- Verifies inline SVG presence
- Reports file size
- Copies validated output to `bundle.html`

### Step 4: Share Artifact with User

Share the validated HTML file in conversation with the user so they can view it as an artifact.

---

## When to Use This Skill vs Other Visual Skills

| Task                                                            | Use This Skill                      | Use Instead                                         |
| --------------------------------------------------------------- | ----------------------------------- | --------------------------------------------------- |
| Rich infographic with multiple sections, high data density      | Yes                                 | —                                                   |
| Self-contained dashboard with interactive tabs or toggles       | Yes                                 | —                                                   |
| Architecture diagram with bidirectional flows and layered tiers | Yes                                 | `architecture-diagram` for auto-generated from code |
| Simple concept illustration or icon-style image                 | No                                  | `concept-to-image`                                  |
| Slide deck or multi-page presentation                           | No                                  | `html-presentation`                                 |
| Architecture diagram generated from existing codebase           | No                                  | `architecture-diagram`                              |
| Single-page visual where CSS Grid layout control is critical    | Yes                                 | —                                                   |
| Artifact must be screenshot-ready via Playwright                | Yes (with caveat — see Limitations) | —                                                   |

---

## Error Handling

| Error                                           | Cause                                                    | Resolution                                                                                        |
| ----------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| CDN link detected by `bundle-artifact.sh`       | External stylesheet or script reference in HTML          | Inline all CSS and JS — no external URLs allowed in output                                        |
| Content overflow / clipping in browser          | Viewport too small or fixed heights with overflow:hidden | Use `min-height` instead of `height`; test at 1440px wide; use `overflow: auto` on scroll regions |
| Playwright screenshot cuts off content          | Page height exceeds screenshot viewport                  | Set `page.setViewportSize` to match content dimensions; use `fullPage: true`                      |
| `bundle-artifact.sh` reports missing inline SVG | SVG loaded via `<img src>` or external ref               | Replace with inline `<svg>` block directly in HTML                                                |
| File size too large to share as artifact        | Embedded base64 images or verbose SVG                    | Optimize SVG paths; avoid embedding raster images                                                 |

---

## Limitations

- **Browser required for screenshots**: Rendering and Playwright-based screenshot capture require a browser runtime. The HTML file itself has no server-side dependency, but visual validation needs a browser.
- **No server-side rendering**: Output is purely client-side. Dynamic data, API calls, or server-computed content are not supported.
- **No persistent state**: The artifact has no backend. User interactions (form inputs, toggles) reset on page reload and cannot be saved.
- **File size guidance**: Aim for under 500KB. Artifacts above 1MB may not render as inline conversation artifacts in some Claude interfaces.
- **Font availability**: System fonts only (or inline base64-encoded web fonts). Do not reference Google Fonts or other external font CDNs.
- **Print fidelity**: CSS print media queries are supported but browser print rendering varies. Test `@media print` explicitly if print output is a requirement.
