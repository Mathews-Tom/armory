---
name: marp-slides
description: 'Author MARP markdown slide decks exportable to PDF, PPTX, and HTML via marp-cli. Covers Marpit directives, custom CSS themes, SVG chart recipes, and dashboard components. Triggers on: "marp", "marp deck", "markdown slides", "slides from markdown", "marp-cli", "pdf from markdown", "pptx from markdown".'
metadata:
  version: 1.0.1
  category: visualization
  tags: [slides, presentation, marp, markdown, pdf, pptx]
  difficulty: intermediate
---

# MARP Slides Skill

Author slide decks as plain Markdown using the MARP ecosystem (Marpit + Marp Core + marp-cli) and export to PDF, PowerPoint, or self-contained HTML. Decks are single `.md` files, git-friendly, and themable with plain CSS.

## When This Skill Triggers

- User asks for a **MARP** deck by name
- User wants "markdown slides" or "slides from markdown"
- User wants a `.md` file they can commit to git and regenerate deterministically
- User mentions `marp-cli`, Marpit directives, or asks to theme slides with CSS
- User wants CLI-exportable PDF or PPTX sourced from a text document

## When NOT to Use This Skill

| User wants | Use instead |
|---|---|
| Reveal.js / browser-native HTML presentation with scroll nav | `html-presentation` |
| Edit a binary `.pptx` with native PowerPoint features (animations, transitions set in PowerPoint) | `document-skills:pptx` |
| Static poster or single-page visual | `concept-to-image` |
| Animated Manim explainer video | `animate` |

## Step 0: Gather Requirements

Before generating anything, confirm in a single message. Use defaults silently for anything the user declines to specify — never ask twice.

| Parameter | Options | Default |
|---|---|---|
| **Export target** | `pdf`, `pptx`, `html`, `all` | `pdf` |
| **Theme** | `dark-dashboard`, `light-editorial`, or MARP built-in (`default`, `gaia`, `uncover`) | `dark-dashboard` |
| **Aspect ratio** | `16:9`, `4:3` | `16:9` |
| **Slide count** | integer or `auto` | `auto` |
| **Visual density** | `minimal` (text-first), `standard` (mixed), `dashboard` (charts + metric cards) | `standard` |
| **Branding** | logo path, accent color hex | none |

## Step 1: Load References On-Demand

**Do NOT read all reference files up front.** Based on user intent, load only what is needed. This keeps the skill within armory's token-efficiency budget.

| User intent | Load |
|---|---|
| Any deck (always required) | `references/DIRECTIVES.md` — Marpit directives, frontmatter schema, image syntax |
| Custom theme or CSS styling | `references/THEMES.md` — `dark-dashboard` and `light-editorial` starter CSS |
| Charts, dashboards, metric cards, SVG visuals | `references/COMPONENTS.md` — SVG chart recipes, cards, status tags, icons |
| Export to PDF/PPTX/HTML or image | `references/EXPORT.md` — marp-cli flags, Chrome dependency, `--html` flag |
| User wants a concrete example to match | `references/examples/` — 3 curated decks: `dashboard.md`, `editorial.md`, `technical.md` |

## Step 2: Compose the Deck

1. **Start with frontmatter.** Every deck begins with a YAML front-matter block setting `theme`, `paginate`, `header`, `footer`, and optionally global `style`. See `DIRECTIVES.md` for the full schema.
2. **Split slides with `---`.** A horizontal rule on its own line creates a new slide. Frontmatter must come before the first slide break.
3. **First slide = title.** Use `<!-- _class: lead -->` to center the title slide, and `<!-- _paginate: skip -->` to hide it from the page count.
4. **Middle slides = content.** Prefer one idea per slide. If density is `dashboard`, use metric cards and SVG charts from `COMPONENTS.md`. If density is `minimal`, use large headings and whitespace.
5. **Last slide = summary/CTA.** Mirror the lead class on the closing slide for visual symmetry.
6. **Background images use extended syntax:** `![bg](url)`, `![bg left:40%](url)`, `![bg brightness:0.3 blur:2px](url)`. Multiple `![bg]` tags on one slide arrange horizontally; add `vertical` for a column layout.

## Step 3: Verify Before Handoff

- Frontmatter block present and valid YAML
- `theme:` matches a known name (built-in or custom in the file's global `style:` block)
- Every slide break is `---` on its own line with blank lines around it
- Relative image paths only (MARP's `--allow-local-files` requires this for PDF export)
- If using raw HTML (SVG, custom divs), confirm the export command uses `--html`
- Run the export command once locally to confirm no directive warnings

## Step 4: Export

See `references/EXPORT.md` for the full command reference. Minimal invocation:

```bash
npx @marp-team/marp-cli@latest slides.md --pdf --allow-local-files --html
```

This skill wraps the MIT-licensed [MARP ecosystem](https://marp.app). See root [`ATTRIBUTIONS.md`](../../ATTRIBUTIONS.md) for upstream credits.

## Design Rules

1. **One idea per slide.** MARP clips overflow silently — there is no warning for content that runs off the bottom.
2. **Paginate: skip** on title and divider slides. **paginate: hold** on appendix slides.
3. **Relative paths only** for images. Absolute paths break in VS Code preview and PDF export.
4. **`--html` is required** for any SVG, `<div>`, `<details>`, or inline styling. Without it, MARP escapes HTML tags to text.
5. **Cap lists at 6 rows** on content slides. Use `details` collapsibles or a second slide for more.
6. **Headings carry meaning:** `h1` for slide title, `h2` for subtitle, `h3` for uppercase section labels. Consistent hierarchy = consistent visual rhythm.
7. **Never hardcode theme CSS into every slide.** Define it once in the global `<!-- style: | -->` directive or a separate `.css` file loaded via `theme:`.
