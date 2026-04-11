---
name: html-presentation
description: 'Converts documents, outlines, or notes into self-contained HTML slide decks with horizontal (Reveal.js) or vertical scroll navigation and multiple themes. Triggers on: "create a presentation", "slide deck", "pitch deck", "HTML presentation", "web-based slides", "reveal.js deck", "convert document into slides".'
metadata:
  version: 1.1.1
  category: visualization
  tags: [slides, presentation, reveal-js, html]
  difficulty: intermediate
---

# HTML Presentation Skill

Convert documents, outlines, or freeform content into polished, self-contained HTML slide presentations with keyboard and scroll navigation.

## When This Skill Triggers

- User provides a document and asks for a "presentation", "slides", or "deck" as HTML
- User asks to convert notes/outline/content into browser-presentable slides
- User wants a Reveal.js or scroll-based HTML presentation
- User references wanting to present from a browser rather than PowerPoint

## Step 0: Gather Requirements

Before generating anything, check whether the user has specified the following. If any are missing, ask for clarification in a single concise message. Do NOT ask more than once — use sensible defaults for anything the user declines to specify.

**Required context (ask if missing):**

| Parameter                  | What to ask                                                                                                                                                                                                                  | Default if not specified            |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| **Navigation mode**        | "Should slides go left-to-right (horizontal) or top-to-bottom (vertical scroll)?"                                                                                                                                            | `horizontal`                        |
| **Theme**                  | "Which visual style? Options: `dark-editorial` (dark bg, serif headlines, editorial feel), `light-minimal` (clean white, sans-serif), `corporate` (navy/white, professional), `hacker` (terminal green-on-black, monospace)" | `dark-editorial`                    |
| **Audience & tone**        | "Who is this for? (e.g., investors, engineers, conference talk, internal team)"                                                                                                                                              | Infer from content                  |
| **Slide count preference** | "Roughly how many slides?"                                                                                                                                                                                                   | Auto-determine from content density |
| **Branding**               | "Any logo text, tagline, or accent color to use in the header?"                                                                                                                                                              | None                                |
| **CTA / closing**          | "Any call-to-action, links, or contact info for the final slide?"                                                                                                                                                            | None                                |

If the user provides a document and says something like "make this a presentation", ask all missing parameters in one shot. If they say "just make it look good", use defaults and proceed.

## Step 1: Analyze the Source Document

Read the uploaded document or provided content. Identify:

1. **Logical sections** — these become slides or slide groups
2. **Key data points** — numbers, metrics, percentages → use metric/stat slide layouts
3. **Lists and comparisons** — feature lists, pros/cons → use card grids or comparison tables
4. **Quotes or testimonials** — use quote-block layouts
5. **Sequential processes** — workflows, timelines → use workflow/timeline slide layouts
6. **Title and conclusion** — first and last slides get special treatment

Create a mental outline mapping content sections to slide types before writing any HTML.

## Step 2: Select Slide Layouts

Each slide should use one of these layout patterns. Mix them for visual variety — never use the same layout for more than 2 consecutive slides.

| Layout               | When to Use                                     | CSS Class                                       |
| -------------------- | ----------------------------------------------- | ----------------------------------------------- |
| **Title**            | Opening slide, section dividers                 | `slide--section slide--center`                  |
| **Split**            | Text + supporting content side-by-side          | `split` or `split--60-40`                       |
| **Grid Cards**       | 3-6 related items (features, risks, components) | `grid-2`, `grid-3`, `grid-4`                    |
| **Metrics**          | Key numbers/stats to emphasize                  | `metrics` with `metric` items                   |
| **Quote**            | Expert quotes, testimonials, key statements     | `quote-block`                                   |
| **Workflow**         | Sequential process, pipeline, architecture      | `workflow` with arrow connectors                |
| **Comparison Table** | Feature comparison, before/after                | `comparison-table`                              |
| **Timeline**         | Chronological events, roadmap phases            | `timeline`                                      |
| **List**             | Ordered or unordered key points                 | `list`, `list--check`, `list--numbered`         |
| **CTA / Closing**    | Final slide with links and contact              | `slide--section slide--center` + `contact-grid` |

## Step 3: Generate the HTML

Read the appropriate theme and template files from this skill's references directory before writing code:

1. **Always read** `references/THEMES.md` to get the CSS variables and styles for the selected theme
2. **Always read** `references/TEMPLATES.md` to get the HTML patterns for each slide layout
3. **Always read** `references/NAVIGATION.md` to get the correct JS initialization for the selected navigation mode

Then assemble the presentation as a single self-contained HTML file:

### File Structure

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <!-- Meta, fonts, Reveal.js CDN (horizontal) or custom CSS (vertical) -->
    <!-- All styles inline in <style> block -->
  </head>
  <body>
    <!-- Slides markup -->
    <!-- Scripts: Reveal.js init (horizontal) or custom scroll handler (vertical) -->
  </body>
</html>
```

### Key Rules

1. **Single file** — everything inline. No external CSS/JS files except CDN resources (Google Fonts, Reveal.js, Lucide icons).
2. **CDN dependencies** (horizontal mode):
   - `https://cdn.jsdelivr.net/npm/reveal.js@4.5.0/dist/reveal.css`
   - `https://cdn.jsdelivr.net/npm/reveal.js@4.5.0/dist/reveal.js`
   - `https://cdn.jsdelivr.net/npm/reveal.js@4.5.0/plugin/highlight/highlight.js` (if code blocks present)
   - `https://cdn.jsdelivr.net/npm/reveal.js@4.5.0/plugin/highlight/monokai.css` (if code blocks present)
   - `https://unpkg.com/lucide@latest` (for icons)
3. **Vertical scroll mode** — zero CDN dependencies for Reveal.js. Uses custom CSS scroll-snap and vanilla JS for keyboard/scroll navigation.
4. **Google Fonts** — load fonts matching the theme. Always use `<link rel="preconnect">` for performance.
5. **Responsive** — include media queries for 1400px, 1024px, and 768px breakpoints.
6. **Fragment animations** — use `class="fragment"` for progressive reveal in horizontal mode. For vertical mode, use intersection observer fade-in animations.
7. **Slide numbers** — always show current slide number.
8. **Kicker text** — each content slide gets a numbered kicker like `01 // Section Name` for editorial feel.
9. **Header bar** — each content slide (not title/section slides) gets a header with an icon and section label.

### Horizontal Mode: Reveal.js Config

```javascript
Reveal.initialize({
  hash: true,
  slideNumber: true,
  controls: true,
  controlsLayout: "bottom-right",
  progress: true,
  center: false,
  transition: "slide",
  width: "100%",
  height: "100%",
  margin: 0.04,
  navigationMode: "linear",
  autoAnimate: true,
  autoAnimateDuration: 0.7,
  plugins: [RevealHighlight], // only if code blocks present
});
```

### Vertical Scroll Mode: Navigation Behavior

- Each slide is a full-viewport section with `scroll-snap-align: start`
- Arrow keys (Up/Down/Left/Right) all navigate between slides
- Mouse wheel scrolls between slides (debounced)
- Page Up/Down, Home/End supported
- Progress bar at bottom shows position
- Smooth scroll transitions between slides
- Touch swipe support for mobile

## Step 4: Write to Output

1. Create the HTML file at an appropriate output path (e.g., `./presentation.html` or a user-specified location)
2. Present the file to the user

If the content is large (>15 slides), build iteratively — write the skeleton first, then append slide content in chunks.

## Error Handling

| Problem                                             | Cause                                        | Fix                                                                                                                                                                      |
| --------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CDN fails to load (Reveal.js, Lucide, Google Fonts) | Network unavailable or CDN outage            | Switch to inline styles/scripts: embed Reveal.js core inline, replace Lucide icons with inline SVG paths, use system font stack (`system-ui, -apple-system, sans-serif`) |
| Content overflows slide viewport                    | Too much text or too many elements per slide | Split the slide into two: move supporting detail to a follow-up slide or convert prose to a bullet list                                                                  |
| Fonts render incorrectly or fail to load            | Google Fonts CDN blocked or slow             | Add system font fallback in the font-family stack: `'Font Name', system-ui, Georgia, serif`                                                                              |
| Reveal.js fails to initialize                       | Script load order issue or missing plugin    | Verify CDN script tags appear before `Reveal.initialize()`; check browser console for 404s                                                                               |

## Quality Checklist

Before delivering, verify:

- [ ] All slides render without overflow (content fits viewport)
- [ ] Navigation works with arrow keys AND mouse scroll
- [ ] Slide numbers are visible
- [ ] Fragment animations work (horizontal) or fade-in works (vertical)
- [ ] Links are clickable (`pointer-events: auto` in Reveal.js)
- [ ] Code blocks have syntax highlighting (if present)
- [ ] Responsive at all three breakpoints
- [ ] No broken icon references (Lucide icons initialized)
- [ ] Consistent kicker numbering across all slides
- [ ] Title slide and closing slide have distinct visual treatment
