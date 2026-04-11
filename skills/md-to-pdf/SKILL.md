---
name: md-to-pdf
description: 'Convert Markdown to styled PDFs with Mermaid diagrams, LaTeX/KaTeX math, tables, and code highlighting. Triggers on: "convert markdown to pdf", "make a pdf from this md", "export markdown as pdf", "pdf from markdown with equations".'
license: MIT. See LICENSE.txt for complete terms.
metadata:
  version: 1.2.1
  category: visualization
  tags: [pdf, markdown, mermaid, latex]
  difficulty: intermediate
---
# Markdown to PDF Converter

Converts Markdown files to professionally styled PDFs with full rendering of Mermaid diagrams,
LaTeX math (via KaTeX), tables, syntax-highlighted code blocks, and all standard Markdown features.

## Architecture

````text
Input .md file
     │
     ├─ Step 1: Extract ```mermaid blocks → render to SVG via mmdc (Mermaid CLI + Puppeteer)
     │          Replace mermaid code blocks with inline <svg> in the markdown source
     │
     ├─ Step 2: pandoc converts modified markdown → standalone HTML5
     │          (--katex flag preserves raw LaTeX in <span class="math ..."> elements)
     │
     ├─ Step 3: Node.js KaTeX server-side rendering
     │          Replaces math spans with fully rendered KaTeX HTML (no client-side JS needed)
     │
     ├─ Step 4: CSS injection
     │          KaTeX stylesheet (with local font paths) + professional document styles + optional custom CSS
     │
     └─ Step 5: Playwright (headless Chromium) prints final HTML → PDF
                 ↓
           Output .pdf file
````

## Supported Features

| Feature              | Rendering Engine                 | Notes                                                                 |
| -------------------- | -------------------------------- | --------------------------------------------------------------------- |
| Mermaid diagrams     | mmdc (mermaid-cli) via Puppeteer | flowchart, sequence, class, state, ER, gantt, pie, git, mindmap, etc. |
| LaTeX math (inline)  | KaTeX server-side                | `$E=mc^2$` syntax                                                     |
| LaTeX math (display) | KaTeX server-side                | `$$\int f(x) dx$$` syntax                                             |
| Tables               | pandoc + CSS                     | Full GFM pipe-table support with professional styling                 |
| Code blocks          | pandoc + CSS                     | Syntax highlighting via pandoc, monospace styling                     |
| Images               | pandoc + Playwright              | Local `file://` and remote `https://` images                          |
| Links                | pandoc                           | Rendered as styled text                                               |
| Lists / blockquotes  | pandoc                           | Ordered, unordered, nested, blockquotes                               |
| YAML frontmatter     | pandoc                           | `title` used as PDF title metadata                                    |
| Footnotes            | pandoc + CSS                     | `[^1]` syntax, rendered at page bottom                                |
| Definition lists     | pandoc + CSS                     | Term / definition pairs                                               |
| Strikethrough        | pandoc                           | `~~deleted~~` syntax                                                  |
| Horizontal rules     | pandoc + CSS                     | `---` rendered as styled separators                                   |

## Prerequisites

Run the setup checker before first use:

```bash
bash <SKILL_DIR>/scripts/setup.sh
```

This validates that all required tools are present and working. The standard Claude computer-use
environment has everything pre-installed. For other environments, the required stack is:

| Dependency                       | Purpose         | Install                                                 |
| -------------------------------- | --------------- | ------------------------------------------------------- |
| `pandoc`                         | Markdown → HTML | `apt install pandoc`                                    |
| `mmdc` (@mermaid-js/mermaid-cli) | Mermaid → SVG   | `npm install -g @mermaid-js/mermaid-cli`                |
| `katex` (npm)                    | LaTeX → HTML    | `npm install -g katex`                                  |
| `playwright` (Python)            | HTML → PDF      | `pip install playwright && playwright install chromium` |
| Chrome/Chromium                  | Browser engine  | Installed by Playwright or Puppeteer                    |

## Usage

### Basic

```bash
python3 <SKILL_DIR>/scripts/md_to_pdf.py <input.md> <output.pdf>
```

### Full Options

```bash
python3 <SKILL_DIR>/scripts/md_to_pdf.py <input.md> <output.pdf> [OPTIONS]
```

| Parameter         | Default      | Description                                                 |
| ----------------- | ------------ | ----------------------------------------------------------- |
| `input`           | _(required)_ | Path to input Markdown file                                 |
| `output`          | _(required)_ | Path to output PDF file                                     |
| `--format`        | `A4`         | Page size: `A4`, `Letter`, `Legal`, `A3`                    |
| `--margin`        | `0.75in`     | Margins — single value (uniform) or `top,right,bottom,left` |
| `--no-mermaid`    | `false`      | Skip Mermaid rendering (keeps raw code blocks)              |
| `--no-math`       | `false`      | Skip KaTeX math rendering                                   |
| `--css`           | _(none)_     | Path to additional custom CSS file to layer on top          |
| `--landscape`     | `false`      | Landscape orientation                                       |
| `--header-footer` | `false`      | Show page numbers in footer (page / total)                  |

### Examples

```bash
# Standard A4 conversion
python3 scripts/md_to_pdf.py report.md report.pdf

# US Letter, landscape, with page numbers
python3 scripts/md_to_pdf.py report.md report.pdf --format Letter --landscape --header-footer

# Custom margins and extra CSS
python3 scripts/md_to_pdf.py report.md report.pdf --margin "1in,0.75in,1in,0.75in" --css brand.css

# Plain mode (skip Mermaid + math for speed)
python3 scripts/md_to_pdf.py report.md report.pdf --no-mermaid --no-math
```

## Workflow for Claude

When a user asks to convert Markdown to PDF:

1. Determine the input file path (uploaded file or user-specified path)
2. Run setup check if this is the first use in the session:
   ```bash
   bash <SKILL_DIR>/scripts/setup.sh
   ```
3. Execute conversion:
   ```bash
   python3 <SKILL_DIR>/scripts/md_to_pdf.py /path/to/input.md /path/to/output.pdf [OPTIONS]
   ```
4. Present the output file to the user

### Handling Failures

| Symptom                       | Likely Cause                          | Fix                                                   |
| ----------------------------- | ------------------------------------- | ----------------------------------------------------- |
| "mmdc FAILED" in Mermaid step | Invalid Mermaid syntax                | Check diagram syntax; mmdc stderr has the parse error |
| Raw LaTeX visible in PDF      | KaTeX couldn't parse expression       | Check LaTeX syntax; KaTeX falls back gracefully       |
| "No Chrome binary found"      | Puppeteer/Playwright Chromium missing | Run `playwright install chromium`                     |
| Blank/missing diagrams        | SVG too large or complex              | Try `--no-mermaid` and render diagrams separately     |

## Customization

### Custom CSS

Pass `--css path/to/custom.css` to inject styles **after** the defaults. Your rules take precedence.

Example — dark theme override:

```css
body {
  background: #1a1a2e;
  color: #e0e0e0;
}
h1,
h2,
h3 {
  color: #e0e0e0;
  border-color: #444;
}
table th {
  background: #2a2a4a;
}
pre {
  background: #0d0d1a;
  border-color: #333;
}
```

### Mermaid Theming

Set the `MERMAID_CONFIG` environment variable to a JSON config file:

```bash
MERMAID_CONFIG=/path/to/.mermaidrc python3 scripts/md_to_pdf.py input.md output.pdf
```

Example `.mermaidrc`:

```json
{
  "theme": "neutral",
  "themeVariables": {
    "primaryColor": "#e1f5fe",
    "lineColor": "#333"
  }
}
```

## Limitations

- **Mermaid diagram rendering** requires either network access for CDN-based mmdc or a local `@mermaid-js/mermaid-cli` install. Offline environments must use `--no-mermaid` and render diagrams separately.
- **Large documents** (100+ pages or many high-resolution images) may hit Playwright's memory limits. Split into multiple input files and merge the resulting PDFs.
- **Custom CSS** may not render identically across PDF viewers — layout is determined by Chromium at render time; Acrobat Reader, Preview, and browsers can display the same PDF differently.
- **Page breaks** require explicit CSS markers (`page-break-before: always` or `break-before: page`) or manual `<div style="page-break-before: always">` in the source. Pandoc does not infer page breaks from heading structure.
- **KaTeX coverage** is broad but not complete — obscure LaTeX macros or packages not in KaTeX's supported set will fail to render and fall back to raw LaTeX.

## File Structure

```text
md-to-pdf/
├── SKILL.md                    # This file — skill documentation
├── LICENSE.txt                 # MIT license
├── README.md                   # Distribution / standalone usage docs
├── scripts/
│   ├── md_to_pdf.py            # Main conversion pipeline (Python)
│   ├── katex_render.js         # Server-side KaTeX math renderer (Node.js)
│   └── setup.sh                # Dependency checker / installer
└── tests/
    └── test_document.md        # Comprehensive test covering all features
```
