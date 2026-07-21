#!/usr/bin/env python3
"""
md_to_pdf.py — Convert Markdown to professionally styled PDF.

Full pipeline:
  1. Extract and render Mermaid diagrams to SVG (via mmdc + Puppeteer)
  2. Convert Markdown → HTML via pandoc (with --katex for math preservation)
  3. Server-side KaTeX rendering of all math expressions (via Node.js)
  4. Inject KaTeX CSS (local fonts) + professional document CSS
  5. Render HTML → PDF via Playwright (headless Chromium)

Usage:
    python3 md_to_pdf.py input.md output.pdf [OPTIONS]

Requirements:
    - pandoc, mmdc (mermaid-cli), node + katex (npm), playwright (Python)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent

# Puppeteer config for mmdc (Mermaid CLI)
# Searches common locations for the Chrome/Chromium binary
CHROME_SEARCH_PATHS = [
    Path.home() / ".cache/puppeteer/chrome",
    Path("/opt/google/chrome/chrome"),
    Path("/opt/pw-browsers"),
    Path("/usr/bin/chromium-browser"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/google-chrome"),
]

# Default professional CSS for the PDF document
DEFAULT_CSS = """
/* === MD-TO-PDF: Professional Document Styles === */

@page {
    size: {page_format};
    margin: {margin_top} {margin_right} {margin_bottom} {margin_left};
}

body {
    font-family: 'Georgia', 'Times New Roman', 'DejaVu Serif', serif;
    font-size: 11pt;
    line-height: 1.65;
    color: #1a1a1a;
    max-width: none;
    padding: 0;
    margin: 0;
}

/* Headings */
h1 {
    font-size: 22pt;
    font-weight: 700;
    color: #111;
    border-bottom: 2.5px solid #333;
    padding-bottom: 6px;
    margin-top: 0;
    margin-bottom: 0.6em;
}
h2 {
    font-size: 16pt;
    font-weight: 600;
    color: #1a1a1a;
    border-bottom: 1px solid #ccc;
    padding-bottom: 4px;
    margin-top: 1.6em;
    margin-bottom: 0.5em;
}
h3 {
    font-size: 13pt;
    font-weight: 600;
    color: #2a2a2a;
    margin-top: 1.3em;
    margin-bottom: 0.4em;
}
h4, h5, h6 {
    font-size: 11pt;
    font-weight: 600;
    color: #333;
    margin-top: 1em;
}

/* Tables */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 10pt;
    page-break-inside: avoid;
}
thead th {
    background-color: #f0f0f0;
    font-weight: 700;
    text-align: left;
    padding: 8px 12px;
    border: 1px solid #bbb;
    border-bottom: 2px solid #999;
}
td {
    padding: 6px 12px;
    border: 1px solid #ddd;
    vertical-align: top;
}
tbody tr:nth-child(even) {
    background-color: #fafafa;
}

/* Code */
code {
    font-family: 'Courier New', 'DejaVu Sans Mono', monospace;
    font-size: 9.5pt;
    background: #f5f5f5;
    padding: 1px 4px;
    border-radius: 3px;
    border: 1px solid #e8e8e8;
}
pre {
    background: #f8f8f8;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 14px 16px;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.45;
    page-break-inside: avoid;
    margin: 1em 0;
}
pre code {
    background: none;
    padding: 0;
    border: none;
    border-radius: 0;
}

/* Mermaid diagrams */
.mermaid-diagram {
    text-align: center;
    margin: 1.5em auto;
    page-break-inside: avoid;
}
.mermaid-diagram svg {
    max-width: 100%;
    height: auto;
}

/* Math */
.katex-display {
    margin: 1em 0;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0.25em 0;
}
.katex {
    font-size: 1.1em;
}

/* Lists */
ul, ol {
    padding-left: 1.8em;
    margin: 0.5em 0;
}
li {
    margin-bottom: 0.25em;
}
li > p {
    margin: 0.25em 0;
}

/* Blockquotes */
blockquote {
    border-left: 3px solid #999;
    margin: 1em 0;
    padding: 0.5em 0 0.5em 1.2em;
    color: #444;
    background: #fcfcfc;
}
blockquote p {
    margin: 0.3em 0;
}

/* Horizontal rules */
hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 2em 0;
}

/* Links */
a {
    color: #1a5276;
    text-decoration: none;
}

/* Images */
img {
    max-width: 100%;
    height: auto;
}

/* Definition lists */
dt { font-weight: bold; margin-top: 0.5em; }
dd { margin-left: 1.5em; margin-bottom: 0.5em; }

/* Footnotes */
.footnotes { font-size: 9pt; border-top: 1px solid #ccc; margin-top: 2em; padding-top: 0.5em; }
.footnote-ref { font-size: 8pt; vertical-align: super; }

/* Print helpers */
.page-break { page-break-before: always; }
"""

HEADER_FOOTER_CSS = """
@page {
    @bottom-center {
        content: counter(page);
        font-size: 9pt;
        color: #888;
        font-family: 'Helvetica Neue', Arial, sans-serif;
    }
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_chrome_binary() -> str | None:
    """Locate a Chrome/Chromium binary for Puppeteer (used by mmdc)."""
    # Check Puppeteer's cache first (most reliable)
    puppeteer_cache = Path.home() / ".cache/puppeteer/chrome"
    if puppeteer_cache.exists():
        for chrome in puppeteer_cache.rglob("chrome"):
            if chrome.is_file() and os.access(str(chrome), os.X_OK):
                return str(chrome)

    # Check Playwright's Chromium
    for pw_dir in [Path("/opt/pw-browsers"), Path.home() / ".cache/ms-playwright",
                   Path.home() / "Library/Caches/ms-playwright"]:
        if pw_dir.exists():
            for pattern in ["chrome", "Chromium"]:
                for chrome in pw_dir.rglob(pattern):
                    if chrome.is_file() and os.access(str(chrome), os.X_OK):
                        return str(chrome)

    # Check system Chrome
    for p in ["/opt/google/chrome/chrome", "/usr/bin/chromium-browser",
              "/usr/bin/chromium", "/usr/bin/google-chrome"]:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    return None


def create_puppeteer_config(tmpdir: Path) -> Path:
    """Create a Puppeteer config JSON pointing to the discovered Chrome binary."""
    chrome_path = find_chrome_binary()
    if not chrome_path:
        print("WARNING: No Chrome/Chromium binary found. Mermaid rendering may fail.", file=sys.stderr)
        chrome_path = "chromium"

    config = {
        "executablePath": chrome_path,
        "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
    }
    config_path = tmpdir / "puppeteer-config.json"
    config_path.write_text(json.dumps(config))
    return config_path


def find_katex_css() -> tuple[str, str]:
    """Locate KaTeX CSS and fonts directory from the npm installation."""
    try:
        katex_dist = subprocess.run(
            ["node", "-e", "console.log(require.resolve('katex').replace(/katex\\.js$/, ''))"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        katex_dist = ""

    if not katex_dist or not Path(katex_dist).exists():
        # Fallback: search common global paths
        for prefix in [Path.home() / ".npm-global/lib/node_modules/katex/dist",
                       Path("/usr/local/lib/node_modules/katex/dist"),
                       Path("/usr/lib/node_modules/katex/dist")]:
            if prefix.exists():
                katex_dist = str(prefix)
                break

    if not katex_dist:
        return "", ""

    css_path = os.path.join(katex_dist, "katex.min.css")
    fonts_dir = os.path.join(katex_dist, "fonts")

    if os.path.isfile(css_path) and os.path.isdir(fonts_dir):
        return css_path, fonts_dir
    return "", ""


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def render_mermaid_blocks(md_content: str, tmpdir: Path, puppeteer_config: Path,
                          mermaid_config: str | None = None) -> str:
    """Extract ```mermaid code blocks, render each to SVG, replace inline."""
    pattern = re.compile(r'```mermaid\n(.*?)```', re.DOTALL)
    matches = list(pattern.finditer(md_content))

    if not matches:
        return md_content

    print(f"  Mermaid: found {len(matches)} diagram(s)")

    # Build mmdc base args
    mmdc_base = ["mmdc", "-p", str(puppeteer_config), "-b", "transparent", "-w", "800"]
    if mermaid_config and Path(mermaid_config).is_file():
        mmdc_base.extend(["-c", mermaid_config])

    # Process in reverse order to preserve string positions
    result = md_content
    for i, match in enumerate(reversed(matches)):
        mermaid_code = match.group(1).strip()
        mmd_file = tmpdir / f"mermaid_{i}.mmd"
        svg_file = tmpdir / f"mermaid_{i}.svg"

        mmd_file.write_text(mermaid_code)

        try:
            proc = subprocess.run(
                mmdc_base + ["-i", str(mmd_file), "-o", str(svg_file)],
                capture_output=True, text=True, timeout=30
            )
            if svg_file.exists():
                svg_content = svg_file.read_text()
                # Remove XML declaration if present (not needed inline)
                svg_content = re.sub(r'<\?xml[^?]*\?>\s*', '', svg_content)
                replacement = f'\n<div class="mermaid-diagram">\n{svg_content}\n</div>\n'
                result = result[:match.start()] + replacement + result[match.end():]
                print(f"    Diagram {len(matches) - i}/{len(matches)}: OK ({len(svg_content)} chars)")
            else:
                err = proc.stderr[:300] if proc.stderr else "unknown error"
                print(f"    Diagram {len(matches) - i}/{len(matches)}: FAILED — {err}", file=sys.stderr)
                # Leave original code block on failure
        except subprocess.TimeoutExpired:
            print(f"    Diagram {len(matches) - i}/{len(matches)}: TIMEOUT", file=sys.stderr)

    return result


def markdown_to_html(md_path: Path, title: str = "") -> str:
    """Convert Markdown to HTML5 via pandoc with --katex (preserves LaTeX source in spans)."""
    cmd = [
        "pandoc", str(md_path),
        "-f", "markdown+pipe_tables+fenced_code_blocks+backtick_code_blocks+fenced_divs"
              "+tex_math_dollars+yaml_metadata_block+strikeout+footnotes+definition_lists"
              "+smart+autolink_bare_uris+lists_without_preceding_blankline",
        "-t", "html5",
        "--katex",
        "--standalone",
        "--highlight-style", "pygments",
    ]
    if title:
        cmd.extend(["--metadata", f"title={title}"])
    else:
        cmd.extend(["--metadata", "title= "])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"  pandoc warning: {result.stderr[:500]}", file=sys.stderr)
    return result.stdout


def render_katex(html_path: Path, output_path: Path) -> dict:
    """Run server-side KaTeX rendering via Node.js script."""
    katex_script = SCRIPT_DIR / "katex_render.js"
    if not katex_script.exists():
        print("  WARNING: katex_render.js not found, math will not be rendered", file=sys.stderr)
        shutil.copy(str(html_path), str(output_path))
        return {"inline": 0, "display": 0, "errors": 0}

    result = subprocess.run(
        ["node", str(katex_script), str(html_path), str(output_path)],
        capture_output=True, text=True, timeout=30
    )

    # Parse stats from last line of stdout
    stats = {"inline": 0, "display": 0, "errors": 0}
    for line in result.stdout.strip().split("\n"):
        try:
            stats = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            pass

    if result.stderr:
        print(f"  KaTeX warnings:\n{result.stderr[:500]}", file=sys.stderr)

    return stats


def inject_css(html: str, page_format: str, margins: dict,
               header_footer: bool, custom_css_path: str | None) -> str:
    """Inject KaTeX CSS, default styles, and optional custom CSS into the HTML."""

    # Load KaTeX CSS with local font paths
    katex_css_path, katex_fonts_dir = find_katex_css()
    katex_css = ""
    if katex_css_path:
        katex_css = Path(katex_css_path).read_text()
        # Rewrite font URLs to absolute file:// paths
        katex_css = katex_css.replace("fonts/", f"file://{katex_fonts_dir}/")

    # Build document CSS with page format and margins
    doc_css = DEFAULT_CSS.replace("{page_format}", page_format) \
        .replace("{margin_top}", margins["top"]) \
        .replace("{margin_right}", margins["right"]) \
        .replace("{margin_bottom}", margins["bottom"]) \
        .replace("{margin_left}", margins["left"])

    if header_footer:
        doc_css += HEADER_FOOTER_CSS

    # Load custom CSS if provided
    custom_css = ""
    if custom_css_path and Path(custom_css_path).is_file():
        custom_css = Path(custom_css_path).read_text()

    # Inject before </head>
    injection = f"""
<style>/* KaTeX */\n{katex_css}</style>
<style>/* Document */\n{doc_css}</style>
"""
    if custom_css:
        injection += f'<style>/* Custom */\n{custom_css}</style>\n'

    html = html.replace("</head>", f"{injection}</head>")

    # Remove pandoc's KaTeX CDN script/link tags (we rendered server-side)
    html = re.sub(r'<link[^>]*katex[^>]*/?>', '', html)
    html = re.sub(r'<script[^>]*katex[^>]*>[\s\S]*?</script>', '', html)

    return html


def html_to_pdf(html_path: Path, pdf_path: Path, page_format: str,
                margins: dict, landscape: bool, header_footer: bool) -> None:
    """Render HTML to PDF using Playwright headless Chromium."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
            '--disable-software-rasterizer',
        ])
        context = browser.new_context()
        page = context.new_page()

        # Use file:// URL so local font paths resolve correctly
        page.goto(f"file://{html_path}", wait_until="networkidle")
        page.wait_for_timeout(800)  # Allow rendering to settle

        pdf_options = {
            "path": str(pdf_path),
            "format": page_format,
            "margin": margins,
            "print_background": True,
            "landscape": landscape,
            "display_header_footer": header_footer,
        }

        if header_footer:
            pdf_options["footer_template"] = (
                '<div style="font-size:9px; color:#888; text-align:center; width:100%;">'
                '<span class="pageNumber"></span> / <span class="totalPages"></span>'
                '</div>'
            )
            pdf_options["header_template"] = '<div></div>'

        page.pdf(**pdf_options)
        browser.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_margins(margin_str: str) -> dict:
    """Parse margin string: single value or 'top,right,bottom,left'."""
    parts = [m.strip() for m in margin_str.split(",")]
    if len(parts) == 1:
        return {"top": parts[0], "right": parts[0], "bottom": parts[0], "left": parts[0]}
    elif len(parts) == 4:
        return {"top": parts[0], "right": parts[1], "bottom": parts[2], "left": parts[3]}
    else:
        print(f"WARNING: Invalid margin format '{margin_str}', using default.", file=sys.stderr)
        return {"top": "0.75in", "right": "0.75in", "bottom": "0.75in", "left": "0.75in"}


def main():
    parser = argparse.ArgumentParser(
        description="Convert Markdown to PDF with Mermaid diagrams and LaTeX math support"
    )
    parser.add_argument("input", help="Path to input Markdown file")
    parser.add_argument("output", help="Path to output PDF file")
    parser.add_argument("--format", default="A4", choices=["A4", "Letter", "Legal", "A3"],
                        help="Page format (default: A4)")
    parser.add_argument("--margin", default="0.75in",
                        help="Margins: single value or 'top,right,bottom,left' (default: 0.75in)")
    parser.add_argument("--no-mermaid", action="store_true", help="Skip Mermaid diagram rendering")
    parser.add_argument("--no-math", action="store_true", help="Skip KaTeX math rendering")
    parser.add_argument("--css", default=None, help="Path to additional custom CSS file")
    parser.add_argument("--landscape", action="store_true", help="Use landscape orientation")
    parser.add_argument("--header-footer", action="store_true", help="Show page numbers in footer")

    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    margins = parse_margins(args.margin)

    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Converting: {input_path.name} → {output_path.name}")
    print(f"  Format: {args.format} | Landscape: {args.landscape} | Page numbers: {args.header_footer}")

    with tempfile.TemporaryDirectory(prefix="md2pdf_") as tmpdir:
        tmpdir = Path(tmpdir)

        # ---- Read input ----
        md_content = input_path.read_text(encoding="utf-8")

        # ---- Extract title from YAML frontmatter ----
        title = ""
        title_match = re.match(r'^---\s*\n.*?title:\s*(.+?)\n.*?---', md_content, re.DOTALL)
        if title_match:
            title = title_match.group(1).strip().strip('"').strip("'")

        # ---- Step 1: Mermaid rendering ----
        if not args.no_mermaid:
            puppeteer_config = create_puppeteer_config(tmpdir)
            mermaid_config = os.environ.get("MERMAID_CONFIG")
            md_content = render_mermaid_blocks(md_content, tmpdir, puppeteer_config, mermaid_config)
        else:
            print("  Mermaid: skipped (--no-mermaid)")

        # ---- Step 2: Markdown → HTML via pandoc ----
        modified_md = tmpdir / "modified.md"
        modified_md.write_text(md_content, encoding="utf-8")
        html = markdown_to_html(modified_md, title=title)
        print(f"  Pandoc: {len(html):,} chars HTML")

        # ---- Step 3: KaTeX server-side math rendering ----
        if not args.no_math:
            pre_katex = tmpdir / "pre_katex.html"
            post_katex = tmpdir / "post_katex.html"
            pre_katex.write_text(html, encoding="utf-8")
            stats = render_katex(pre_katex, post_katex)
            html = post_katex.read_text(encoding="utf-8")
            print(f"  KaTeX: {stats['inline']} inline + {stats['display']} display "
                  f"({stats['errors']} errors)")
        else:
            print("  KaTeX: skipped (--no-math)")

        # ---- Step 4: Inject CSS ----
        html = inject_css(html, args.format, margins, args.header_footer, args.css)

        final_html = tmpdir / "final.html"
        final_html.write_text(html, encoding="utf-8")
        print(f"  CSS injected: {len(html):,} chars final HTML")

        # ---- Step 5: HTML → PDF via Playwright ----
        html_to_pdf(final_html, output_path, args.format, margins, args.landscape, args.header_footer)

    size = output_path.stat().st_size
    print(f"\nDone: {output_path}")
    print(f"  Size: {size:,} bytes ({size / 1024:.1f} KB)")
    return str(output_path)


if __name__ == "__main__":
    main()
