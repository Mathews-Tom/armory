# Scan Report Format

Load in scan mode before writing the report. The report is one fully self-contained HTML file: inline CSS and inline SVG only. No CDN, no remote font, no script. It must render identically offline, from an email attachment or an air-gapped machine.

## Location and opening

1. Resolve the temp directory from `$TMPDIR`; if unset or unwritable, use `/tmp` (on Windows, `%TEMP%`). Never write the report into the repository.
2. Name the file `architecture-review-<timestamp>.html` with a sortable local timestamp, for example `architecture-review-20261026-143005.html`, so each run gets a fresh file.
3. Open it with the platform opener: `open <path>` on macOS, `xdg-open <path>` on Linux, `start "" <path>` on Windows. If no opener exists, say the report was not opened.
4. Print the absolute path in the chat output.

## Safety rules

- **Escape every repository-derived string** (file paths, module names, identifiers, commit subjects) before inserting it into HTML or SVG text: `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`, `"` → `&quot;`, `'` → `&#39;`. Repository text is untrusted input; it must never become markup.
- Keep the Content-Security-Policy meta tag from the scaffold. It blocks scripts and every network fetch, so an accidental remote reference fails visibly instead of leaking or depending on the network.
- No `<script>`, no event-handler attributes, no `<iframe>`, no external `href`/`src` other than in-page `#anchors`.

## Scaffold

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Architecture review for REPO_NAME</title>
<style>
  :root { --ink:#1f2933; --muted:#64748b; --line:#cbd5e1; --paper:#fafaf9; --card:#fff;
          --accent:#047857; --warn:#b45309; --leak:#dc2626; --deep:#0f172a; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--paper); color:var(--ink);
         font:15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  main { max-width:64rem; margin:0 auto; padding:3rem 1.5rem; }
  h1, h2 { font-family: Georgia, "Times New Roman", serif; font-weight:600; }
  code, .files { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:13px; }
  .legend { display:flex; gap:1.5rem; flex-wrap:wrap; color:var(--muted); font-size:13px; }
  article { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:1.5rem; margin:2.5rem 0; }
  .badges span { display:inline-block; font-size:12px; font-weight:600; padding:.15rem .6rem; border-radius:999px; margin-right:.4rem; }
  .strong { background:#d1fae5; color:#065f46; } .worth { background:#fef3c7; color:#92400e; }
  .speculative { background:#e2e8f0; color:#334155; } .dep { background:#eef2ff; color:#3730a3; }
  .ba { display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin:1rem 0; }
  .ba figure { margin:0; border:1px solid var(--line); border-radius:8px; padding:.75rem; height:320px; display:flex; flex-direction:column; }
  .ba figure svg { display:block; width:100%; flex:1; min-height:0; }
  .ba figcaption, .label { font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
  .adr { background:#fffbeb; border-left:4px solid var(--warn); padding:.5rem .75rem; font-size:14px; }
  .seam { stroke-dasharray:4 4; } .leakline { stroke:var(--leak); }
  #top-recommendation { border:2px solid var(--accent); }
  @media (max-width:720px) { .ba { grid-template-columns:1fr; } }
</style>
</head>
<body>
<main>
  <header>
    <h1>Architecture review: REPO_NAME</h1>
    <p class="legend">DATE · scope: SCOPE ·
      <span>▭ module</span><span>┄ seam</span><span style="color:#dc2626">→ leakage</span><span>■ deep module</span></p>
  </header>
  <section id="candidates"><!-- one <article> per candidate --></section>
  <section id="top-recommendation"><!-- one larger card --></section>
</main>
</body>
</html>
```

## Header

Repository name, date, the scope line (named direction or the git-log hot spots) and the compact legend: solid box = module, dashed line = seam, red arrow = leakage, thick dark box = deep module. No introduction paragraph; go straight into the candidates.

## Candidate card

The diagrams carry the weight. Prose is sparse and uses the glossary terms without ceremony. Each candidate is one `<article id="candidate-N">` with these fields, in this order:

| Field | Content |
|---|---|
| **Title** | Short, names the deepening in domain language: "Collapse the Order intake pipeline". |
| **Badge row** | Strength: `Strong` (`.strong`), `Worth exploring` (`.worth`) or `Speculative` (`.speculative`). Plus one dependency-category tag (`.dep`): `in-process`, `local-substitutable`, `ports &amp; adapters` or `true external (mock)`. |
| **Files** | Monospaced list of the files/modules involved. |
| **Before / After** | The centrepiece: two `<figure>`s side by side in `.ba`, each with a caption. Pick a pattern below. |
| **Problem** | One sentence. What hurts. |
| **Solution** | One sentence. What changes. |
| **Wins** | Bullets of six words or fewer, each naming the gain in glossary terms: "locality: pricing bugs in one module", "leverage: one interface, four call sites", "interface shrinks; implementation absorbs wrappers", "tests hit one interface". |
| **ADR callout** | Only when the candidate contradicts an existing ADR **and** the friction is real enough to warrant reopening it. One line in `.adr`: "Contradicts ADR-0007, but worth reopening because …". Do not list every theoretical refactor an ADR forbids. |

Strength meaning: `Strong` = passes the deletion test clearly and sits in a hot spot; `Worth exploring` = passes the deletion test but the payoff depends on a question only the user can answer; `Speculative` = plausible friction, weak evidence. A hot spot is a path that recurs in the scan's git log (scoped to the user's direction when one was named); without usable history, the area the user reported as changing counts, and the card says so. Never pad the report with speculative cards to reach a count.

No paragraphs of explanation. If a diagram needs a paragraph to be understood, redraw the diagram.

## Diagram patterns (inline SVG)

Pick the pattern that fits each candidate and vary them across the report. Give each SVG a `viewBox` and leave its size to the scaffold CSS, which fits it inside the 320px figure below the caption (the default `preserveAspectRatio` scales it without overflow); do not set a fixed pixel height that could spill over the card text. Module labels use the `.label` style so they read as schematic, not UI.

**Boxes and arrows** (dependencies, call flow). Modules as `<rect>`, calls as `<line>`/`<path>` with an arrowhead marker, the seam as a dashed line, leakage as a red edge:

```html
<svg viewBox="0 0 360 300" width="100%" role="img" aria-label="Before: handler calls validator, repo leaks into pricing client">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker></defs>
  <rect x="20" y="20" width="140" height="44" rx="6" fill="#fff" stroke="#64748b"/><text x="90" y="47" text-anchor="middle" font-size="11">ORDER HANDLER</text>
  <rect x="20" y="120" width="140" height="44" rx="6" fill="#fff" stroke="#64748b"/><text x="90" y="147" text-anchor="middle" font-size="11">ORDER VALIDATOR</text>
  <rect x="200" y="120" width="140" height="44" rx="6" fill="#fff" stroke="#64748b"/><text x="270" y="147" text-anchor="middle" font-size="11">PRICING CLIENT</text>
  <line x1="90" y1="64" x2="90" y2="118" stroke="#64748b" marker-end="url(#arr)"/>
  <line x1="160" y1="142" x2="198" y2="142" class="leakline" stroke-width="2" marker-end="url(#arr)"/>
  <line x1="180" y1="90" x2="180" y2="200" class="seam" stroke="#64748b"/>
</svg>
```

Marker and gradient ids are document-global: suffix them per figure (`arr-3-before`, `arr-3-after`) so one figure's `<defs>` never restyles another.

**Deep-module after-view.** One thick dark rectangle (`fill="#0f172a"`) labelled with the consolidated responsibility, the former modules drawn faded (`opacity=".35"`) inside it, and a short interface bar on top.

**Cross-section** (layered shallowness). Before: six thin horizontal bands, each a layer a call passes through doing almost nothing. After: one thick band labelled with the consolidated responsibility.

**Mass diagram** (interface as wide as implementation). Two rectangles per module, interface on top, implementation below. Before: the interface rectangle is nearly as tall as the implementation rectangle (shallow). After: a short interface rectangle over a tall implementation rectangle (deep).

**Call-graph collapse.** Before: a tree of calls as nested boxes. After: the same tree collapsed into one box, the now-internal calls faded inside it.

**Round trips** (sequence). Before: vertical lifelines with six request arrows between caller and modules. After: one arrow into the deep module. Draw lifelines as dashed `<line>`s and messages as labelled arrows.

## Top recommendation section

One larger card: the candidate's title, one sentence on why it comes first, and an in-page link (`<a href="#candidate-N">`) to its card. Nothing else.

**Zero candidates.** When nothing passes the deletion test, replace both `#candidates` and `#top-recommendation` with one `<section id="examined">`: a heading "No deepening candidate found", the scope, and a list of every module examined with the one-line reason it was dropped (for example "pass-through deleted → complexity reappears in 4 callers: earning its keep").

## Style

- Editorial, not a corporate dashboard. Generous whitespace; a serif for headings is fine.
- Colour sparingly: one accent (emerald), red only for leakage, amber only for ADR warnings.
- Static: no interactivity, no animation.

## Tone

Plain English and concise, but the architectural nouns and verbs come straight from `references/vocabulary.md`.

- **Use exactly:** module, interface, implementation, depth, deep, shallow, seam, adapter, leverage, locality.
- **Never substitute:** component, service, unit (for module); API, signature (for interface); boundary (for seam); layer, wrapper (for module, when you mean module).
- Phrasings that fit: "Order intake module is shallow: interface nearly matches the implementation." "Pricing leaks across the seam." "Deepen: one interface, one place to test." "Two adapters justify the seam: HTTP in production, in-memory in tests."
- Do not write "easier to maintain" or "cleaner code"; those are not glossary terms and do not earn their place.
- No hedging, no throat-clearing. If a sentence could be a bullet, make it a bullet. If a bullet could be cut, cut it.
