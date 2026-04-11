---
name: concept-to-image
description: 'Turn concepts into static HTML visuals exported as PNG or SVG files via HTML/CSS/SVG. Triggers on: "create an image of", "export as PNG", "save as SVG", "concept to image", "screenshot this HTML". NOT for interactive HTML, use static-web-artifacts-builder.'
metadata:
  version: 1.2.1
  category: business
  tags: [image-generation, html-to-png, svg, visual-design]
  difficulty: intermediate
---

# Concept to Image

Creates polished visuals from concepts using HTML/CSS/SVG as a refineable intermediate, then exports to PNG or SVG.

## Reference Files

| File                         | Purpose                                                                              |
| ---------------------------- | ------------------------------------------------------------------------------------ |
| `references/design-guide.md` | Design patterns, anti-patterns, color palettes, typography choices, layout examples  |
| `scripts/render_to_image.py` | Playwright-based export script — takes HTML in, PNG or SVG out                       |
| `assets/template.html`       | Base HTML template with `.canvas` container and CSS custom properties pre-configured |

## Why HTML as intermediate

HTML is the refineable layer between idea and image. Unlike direct canvas rendering, the user can see the HTML artifact, request changes ("make the title bigger", "swap the colors", "add a third column"), and only export once satisfied. This makes the workflow iterative and controllable.

## Workflow

```text
Concept → HTML artifact (view + refine) → PNG or SVG export
```

1. **Interpret** the user's concept — determine what kind of visual best fits (diagram, infographic, card, chart, etc.)
2. **Design** a self-contained HTML file using inline CSS and inline SVG — zero external dependencies
3. **Present** the HTML as an artifact so the user can preview and request refinements
4. **Iterate** on the HTML based on user feedback (colors, layout, content, sizing)
5. **Export** to PNG and/or SVG when the user is satisfied, using `scripts/render_to_image.py`

## Step 1: Interpret the concept

Determine the best visual format:

| User intent              | Visual format                 | Approach                           |
| ------------------------ | ----------------------------- | ---------------------------------- |
| Explain a process/flow   | Flowchart or pipeline diagram | SVG paths + boxes                  |
| Compare items            | Side-by-side or matrix        | CSS Grid                           |
| Show hierarchy           | Tree or layered diagram       | Nested containers + SVG connectors |
| Present data             | Chart or infographic          | SVG shapes + data labels           |
| Social/marketing graphic | Card or poster                | Typography-forward HTML/CSS        |
| Icon, logo, badge        | Compact symbol                | Pure SVG                           |
| Educational concept      | Annotated diagram             | SVG + positioned labels            |

## Step 2: Design the HTML

Read `references/design-guide.md` for detailed design patterns and anti-patterns.

Core rules:

- **Single file, self-contained**: All CSS inline in `<style>`, all graphics as inline `<svg>`. No external resources.
- **Fixed viewport**: Set explicit `width` and `height` on the root container matching the intended export size. This is critical — Playwright screenshots the element at this exact size.
- **Anti-AI-slop**: Avoid centered-everything layouts, purple gradients, uniform rounded corners, and Inter/system font defaults. See design guide for alternatives.
- **SVG-first for shapes**: Use inline SVG for icons, connectors, shapes, and any element that should scale cleanly. CSS for layout and typography.
- **Color with intention**: 3-4 hues max + neutrals. Define as CSS custom properties. Every color encodes meaning.
- **Start from the template**: Use `assets/template.html` as the base structure.

### Sizing guidelines

| Use case               | Recommended size   |
| ---------------------- | ------------------ |
| Social media graphic   | 1200×630           |
| Infographic (portrait) | 800×1200           |
| Presentation slide     | 1920×1080          |
| Square post            | 1080×1080          |
| Icon/badge             | 256×256 or 512×512 |
| Wide diagram           | 1600×900           |

Set the `.canvas` container to the chosen size. The export script captures this element.

## Step 3: Present and iterate

Present the HTML file to the user. They'll see it rendered as an artifact. Common refinement requests:

- Color/theme changes → update CSS custom properties
- Layout adjustments → modify grid/flexbox
- Content changes → edit text/SVG elements
- Size changes → update `.canvas` dimensions

Each iteration is a quick HTML edit, not a full re-render. This is the key advantage over direct image generation.

## Step 4: Export to image

Once the user is satisfied, run the export script:

```bash
python3 scripts/render_to_image.py <input.html> <output.png|.svg> [--width 1200] [--height 630] [--scale 2] [--selector ".canvas"]
```

### Parameters

| Param         | Default    | Description                                             |
| ------------- | ---------- | ------------------------------------------------------- |
| `input`       | (required) | Path to HTML file                                       |
| `output`      | (required) | Output path. Extension determines format (.png or .svg) |
| `--width`     | auto       | Viewport width (overrides HTML-defined size)            |
| `--height`    | auto       | Viewport height (overrides HTML-defined size)           |
| `--scale`     | 2          | Device scale factor for PNG (2 = retina quality)        |
| `--selector`  | `.canvas`  | CSS selector for the element to capture                 |
| `--full-page` | false      | Capture the full page instead of a specific element     |

### PNG export

Uses Playwright to launch headless Chromium and screenshot the `.canvas` element at the specified scale factor. Scale 2 produces retina-quality output (e.g., 1200×630 CSS pixels → 2400×1260 PNG).

### SVG export

Two strategies, chosen automatically:

1. **SVG-native content**: If the `.canvas` element contains a single root `<svg>`, extracts it directly as a clean SVG file. This produces a true vector SVG.
2. **HTML-based content**: If the content is CSS/HTML-heavy, falls back to PNG export with a note that true SVG requires SVG-native design. The script will warn and suggest redesigning with SVG elements if vector output is needed.

### Delivering the output

Present the output file to the user. Always deliver both the HTML (for future editing) and the image (final output).

## Error Handling

| Error                        | Cause                                                       | Resolution                                                                                                          |
| ---------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `playwright` not found       | Playwright package not installed                            | Run `npx playwright install chromium` or `pip install playwright && playwright install chromium`                    |
| Browser launch failure       | Headless Chromium fails to start                            | Verify `--headless` mode is supported; check available memory (Chromium needs ~200 MB)                              |
| `.canvas` selector not found | HTML does not contain an element matching `.canvas`         | Verify `assets/template.html` was used as the base; check the root container has `class="canvas"`                   |
| Render timeout               | Complex HTML takes too long to render before screenshot     | Increase the timeout via `--timeout` flag in the script, or simplify the HTML (reduce DOM depth, inline fewer SVGs) |
| SVG export falls back to PNG | `.canvas` element contains HTML/CSS content, not a root SVG | See SVG export section; redesign with a single root `<svg>` if vector output is required                            |

## Limitations

- **Playwright + Chromium required** — the export script cannot run without a working Chromium installation.
- **macOS and Linux only** for headless browser export. Windows Subsystem for Linux works; native Windows Playwright may require separate setup.
- **SVG export is best-effort** — complex HTML/CSS layouts fall back to PNG. True vector SVG requires a single root `<svg>` as the `.canvas` child.
- **Max viewport 4096×4096** — Chromium refuses screenshots larger than this. Use `--scale` to achieve higher effective resolution within this limit.
- **No animation support** — exported images are static snapshots. CSS animations and JavaScript-driven transitions are frozen at their initial state.

## Output Example

After a successful export, the script prints the output path and file stats:

```text
Exported: concept-diagram.png
  Size:       2400 × 1260 px  (2× scale from 1200 × 630 canvas)
  File size:  ~180 KB
  Format:     PNG (RGBA)
```

Filename pattern follows whatever was passed as the output argument. Typical file sizes:

- Simple diagrams (text + shapes): 80–200 KB
- Dense infographics with gradients: 300–600 KB
- Full 1920×1080 at 2× scale: 500 KB–1.5 MB

## Design anti-patterns to avoid

These produce generic "AI-generated" looking output:

- Centered everything with equal spacing
- Purple/blue gradient backgrounds
- Uniform border-radius on all elements
- Generic icon libraries (use custom inline SVG)
- System font stack without typographic intention
- Drop shadows on everything
- Low information density (too much whitespace)

## Font handling

Since this environment has limited font access, use web-safe font stacks with intentional fallbacks:

- **Technical/mono**: `'Courier New', 'Consolas', monospace`
- **Clean sans**: `'Helvetica Neue', 'Arial', sans-serif`
- **Editorial serif**: `'Georgia', 'Times New Roman', serif`
- **Display**: Use SVG text with custom paths for display typography when needed
