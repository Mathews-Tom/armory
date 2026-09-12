# Artifact Contract

## Delivery Shape

Produce one UTF-8 HTML file that opens directly from disk and behaves as a six-page learning application. It must not require a server, network connection, package install, build tool, external font, CDN, stylesheet, script, image, or iframe.

Stage the file and all temporary Mermaid/Markdown sources outside the target repository. The final response attaches or links the HTML file; it does not paste its full source.

## Required Virtual Pages

Use hash routes so browser back/forward works from a local file:

| Route | Page title | Required content |
|---|---|---|
| `#start` | Start Here | problem, audience, input/work/output visual, learning goals, provenance |
| `#use` | Use It | prerequisites, documented first-result path, user example, recovery path |
| `#flow` | Follow the Work | outside-view workflow, inside-view workflow, sequence explanation, failure path |
| `#inside` | Inside the System | responsibility architecture, boundary explanations, state/integrations |
| `#build` | Build on It | developer setup as documented, safe change journey, test/debug path, invariants |
| `#practice` | Practice Lab | glossary, four exercise types, collapsible evidence-backed answers, teach-back prompt |

Keep every route in the document. Without JavaScript, all sections remain readable in source order. With JavaScript, only the active route is presented. Unknown evidence becomes explicit page content, not a missing route.

## Document Structure

Required landmarks and controls:

- one skip link to main content;
- `header` with repository name, frozen revision, and global depth control;
- `nav` with all six routes and `aria-current` on the active route;
- `main` containing six route sections;
- previous/next controls on each route;
- visible progress text, not color alone;
- `aside` or modal-free drawer for glossary and evidence;
- `footer` with provenance, generation timestamp, limitations, and offline status.

Use native buttons, links, `details`, and `summary`. Do not recreate them with generic `div` elements. All controls need visible focus and accurate accessible names.

## Visual Direction

Design it as a repository-specific field guide, not a generic dashboard. Derive visual language from the system's domain without copying brand assets blindly. Use a restrained palette with semantic colors for `Observed`, `Inferred`, and `Unknown`.

Avoid purple-on-white gradients, repeated floating cards, excessive centered text, identical rounded rectangles, decorative glass effects, and dense dashboard chrome. Vary page composition according to the lesson: journey, map, workshop, and lab should not look like the same card grid.

Use system fonts unless a font is legally embedded as data. Respect `prefers-reduced-motion`. Motion may clarify route transitions or focus; it must not animate diagrams continuously.

## Mermaid Contract

Architecture and workflow diagrams originate as Mermaid. This includes component maps, request/data flows, sequences, state transitions, and user/system workflows.

For every Mermaid diagram:

1. Write the `.mmd` source in temporary staging.
2. Generate opaque node IDs such as `N1`; never derive Mermaid identifiers from repository text.
3. Reduce diagram labels to a reviewed teaching vocabulary. For unavoidable repository-controlled labels, normalize control characters and allow only letters, digits, spaces, `_`, `.`, `,`, `:`, `/`, `+`, and `-`; put the exact original spelling in the evidence card instead.
4. Quote every label and configure Mermaid with `securityLevel: "strict"` and `htmlLabels: false`.
5. Use the real Mermaid engine to parse it. A regex or visual inspection is not validation.
6. Render with the same major Mermaid version used for validation.
7. Sanitize and inline the resulting SVG into the HTML using the allowlist below.
8. Add a descriptive title and text alternative adjacent to the SVG.
9. Store the HTML-escaped Mermaid source inside a collapsed `details` element labeled “Mermaid source.”
10. Remove temporary sources after the final artifact passes.

Preferred render paths, in order:

1. an available browser page with a pinned Mermaid module and `mermaid.render()`;
2. an already-installed Mermaid CLI;
3. a pinned temporary Mermaid CLI invocation outside the target repository.

Do not add Mermaid to the target's dependencies. Do not leave a CDN reference in final HTML. Preserve required third-party notices when the rendering path embeds any runtime code; prefer pre-rendered inline SVG so no runtime is shipped.
SVG sanitization is allowlist-based. Retain only the SVG elements and geometry/text/ARIA attributes required by the render. Remove `script`, `foreignObject`, animation elements, every `on*` attribute, and every external reference. Permit `href`/`xlink:href` only for local `#fragment` references. Reject `javascript:`, `data:`, CSS `@import`, and CSS `url()` values; if retained Mermaid styles contain any of them, fail the artifact instead of trying to repair the value.

A failed diagram blocks delivery. Do not redraw architecture or workflow directly as SVG to bypass Mermaid.

## Markdown Table Contract

Author every table as GitHub-style Markdown in temporary staging before converting it. Preserve the exact HTML-escaped Markdown source in:

```html
<script type="text/markdown" data-table-source="table-id">
...
</script>
```

Render the visible version as semantic HTML:

- `table` with a `caption` stating the learner question;
- `thead` and `tbody`;
- `th scope="col"` for column headers;
- `th scope="row"` where rows have meaningful labels;
- a scroll wrapper on narrow screens.

Do not encode tabular data as positioned SVG text or a collection of cards.

## Other SVG Visuals

Use hand-authored inline SVG only for non-workflow teaching visuals such as:

- input/work/output concept illustrations;
- annotated comparisons;
- timelines;
- layered concept maps without process arrows;
- state or confidence legends;
- debugging decision aids that are not flows.

Every SVG needs `role="img"`, a unique `aria-labelledby`, `title`, and `desc`. Repository-controlled strings placed in SVG must be escaped. Ensure text remains legible at 200% zoom. Do not use SVG for long prose or tables.

## Evidence Markup

Give every technical claim a stable ID and visible status badge. Link the claim to an embedded evidence card so local artifacts remain useful offline.

```html
<article class="claim" id="claim-C01" data-status="observed">
  <p>...</p>
  <a href="#inside/evidence-C01">Evidence C01</a>
</article>

<article class="evidence" id="evidence-C01">
  <h3>C01 — Entry point</h3>
  <p><code>src/...:12-24</code> at <code>COMMIT</code></p>
  <pre><code>short escaped excerpt</code></pre>
  <p>What to notice: ...</p>
</article>
```

Remote sources may also link to commit-pinned host URLs. External links supplement the embedded evidence card; they never replace it.

Rules:

- escape by output context: HTML-encode text nodes; encode attributes; JSON-serialize script data; escape Markdown pipes/backticks/newlines; use the restricted Mermaid-label rule above; and XML-encode hand-authored SVG text;
- never inject raw repository strings through `innerHTML`, template interpolation into executable script, or unsanitized SVG;
- keep excerpts short and necessary for teaching;
- identify documentation evidence as documentation;
- use `Documented, not run` beside commands not executed;
- make `Observed`, `Inferred`, and `Unknown` distinguishable by text/icon as well as color.

## Interaction Contract

Required interactions:

- hash-route navigation with back/forward support; parse only the first hash segment as the route so namespaced targets such as `#inside/evidence-C01` keep the `inside` page active;
- previous and next page actions;
- keyboard shortcuts that do not override browser or screen-reader conventions;
- global Beginner/Deeper/Code depth control;
- per-concept `details` fallback;
- exercise answer reveal;
- glossary/evidence navigation with focus returned to the invoking control where applicable;
- evidence and glossary deep links use `#<route>/<target-id>` or button-controlled drawers; bare `#evidence-*`/`#glossary-*` hashes are prohibited because they collide with route selection.

Persisting progress in `localStorage` is optional. If used, namespace the key by repository basename/URL hash and recorded commit/snapshot basis; the artifact must still work when storage is unavailable.

Do not require drag, hover, canvas, or pointer precision to access information.

## Self-Containment Checks

Before opening the browser, inspect the final HTML for:

- exactly one HTML document;
- all six route IDs and navigation links;
- at least two Mermaid-source blocks: one architecture and one workflow;
- corresponding inline SVG renders;
- at least one non-Mermaid teaching SVG;
- Markdown source for each visible table;
- semantic tables and captions;
- no `http://` or `https://` resource in `src`, stylesheet `href`, CSS `url()`, module import, fetch, worker, iframe, or form action;
- no absolute local filesystem paths in visible content or link targets; local provenance uses the repository basename plus commit/snapshot basis, while the final chat may report the canonical path;
- no unescaped repository content;
- no placeholder text, unresolved template token, fake command output, or fabricated example result.

Remote commit-pinned evidence anchors may use `https://` links. They must be ordinary optional anchors, not runtime resources.

## Browser Acceptance Checks

When browser automation is available, open the actual file in a real browser and record the checks performed. If it is unavailable, perform every static/content check, disclose `Browser checks not performed — <reason>` in the artifact and final response, list the skipped checks, and never claim browser verification.

### Functional

1. Load `#start` directly.
2. Visit all six navigation routes.
3. Use browser back and forward.
4. Use every next/previous control.
5. Change Beginner/Deeper/Code depth and verify content/focus.
6. Open Mermaid source, evidence, glossary, and all answer disclosures.
7. Reload a non-start route.
8. Disable network and reload.
9. Confirm zero console errors.

### Visual

Check at minimum:

| Viewport | Focus |
|---|---|
| 1440 × 900 | hierarchy, line length, diagram labels, navigation |
| 1024 × 768 | grids, evidence drawer, code/table overflow |
| 390 × 844 | menu/navigation access, focus, horizontal overflow, touch targets |

Inspect every page, not only the cover. No content may overlap, clip, hide behind sticky navigation, or become readable only through hover.

### Accessibility

- keyboard reaches every interactive element in logical order;
- focus is visible;
- active route is announced;
- headings form one logical hierarchy;
- diagrams have text alternatives;
- color is not the sole status signal;
- reduced-motion mode removes nonessential animation;
- 200% zoom preserves content and controls.

### Content

- the central user journey and safe developer journey are consistent across pages;
- every claim link resolves to an evidence card;
- every evidence location exists under the recorded provenance basis; dirty and non-Git inputs include a digest for each cited file;
- exercises require retrieval, prediction, tracing, or transfer;
- limitations and unknowns remain visible;
- documented-but-unrun commands are labeled accurately.

## Final Delivery Note

Report the artifact path/link, repository provenance basis, user and developer teaching spines, material unknowns, and exact browser surfaces checked. If browser automation was unavailable, report the skipped checks instead. Do not call the result browser-verified if any route, Mermaid render, evidence target, offline check, or target-integrity check failed or was not exercised.
