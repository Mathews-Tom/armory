---
name: chart-clarity
description: 'Create, review, and restyle data visualizations using Edward Tufte principles: high data-ink ratio, direct labels, range-frame axes, small multiples, accessible color, responsive charts, and honest comparisons. Triggers on: "create a chart", "style this chart", "review this graph", "Tufte chart", "data visualization", "Recharts", "Plotly", "matplotlib", "Chart.js", "ECharts", "D3". Use when generating or critiquing charts, dashboards, sparklines, and data tables.'
metadata:
  version: 1.0.0
  category: visualization
  tags: [charts, data-viz, tufte, accessibility, visualization]
  difficulty: intermediate
  complements:
    - static-web-artifacts-builder
    - ux-expert
---

# Chart Clarity

Create and critique charts that make quantitative comparisons obvious without decorative chartjunk. This skill adapts Caylent's MIT-licensed `tufte-data-viz` skill into armory under the broader `chart-clarity` name. It applies Edward Tufte's core data visualization principles and adds screen-first requirements for accessibility, responsiveness, dark mode, progressive disclosure, and human-readable numbers.

Use this skill whenever the user asks for a chart, graph, plot, dashboard visualization, sparkline, slopegraph, data table, or visualization review. It covers Recharts, ECharts, Chart.js, matplotlib, Plotly, seaborn, D3.js, SVG, and HTML.

## When to Use

| User need | Use `chart-clarity` | Use instead |
|---|---:|---|
| Generate chart code in Recharts, Plotly, matplotlib, Chart.js, ECharts, D3, SVG, or HTML | Yes | — |
| Review an existing chart for misleading design, clutter, accessibility, or readability | Yes | — |
| Restyle dashboard charts while keeping the dashboard structure unchanged | Yes | `ux-expert` for broader dashboard UX |
| Build a static infographic or rich HTML artifact around charts | No | `static-web-artifacts-builder` |
| Design a slide deck or presentation using charts | No | `html-presentation`, `marp-slides`, or `pptx` |
| Design logos, posters, icons, or non-data visuals | No | `concept-to-image` or `canvas-design` |

## Trigger Families

- Chart creation: "create a chart", "plot this data", "make a graph", "build a sparkline", "generate a slopegraph".
- Chart review: "review this visualization", "what is wrong with this graph", "make this chart clearer", "remove chartjunk".
- Tufte-specific: "Tufte chart", "high data-ink ratio", "range-frame axes", "small multiples", "direct labels".
- Library-specific: "Recharts", "ECharts", "Chart.js", "matplotlib", "seaborn", "Plotly", "D3", "SVG chart".

## Workflow

Follow this order for every chart task.

1. **Identify the message.** Determine the finding the chart needs to make visible. A useful title states the finding: "Revenue Beat Target by 24% in Q2", not "Revenue by Month".
2. **Identify comparison context.** Add a baseline, prior period, target, average, peer group, or distribution. A number without comparison context is weak evidence.
3. **Choose the chart type.** Use the data shape to select line, horizontal bar, scatter, small multiple, sparkline, slopegraph, heatmap, or table. Refuse pie charts by default; use sorted horizontal bars unless the user explicitly asks for a pie chart.
4. **Apply the universal rules.** Remove decorative ink, direct-label series, use gray-first color, annotate notable features, format numbers for humans, and ensure the chart earns its space.
5. **Read one library reference.** For implementation code, read exactly one matching library file from `references/rules/` unless the task compares multiple libraries.
6. **Validate before presenting.** Run the checklist at the end of this file against the final chart or review output.

## Universal Rules

1. Remove top and right borders, spines, frames, and plot boxes.
2. Use direct labels instead of legends. Remove legend components unless the user explicitly requires one.
3. Remove gridlines by default. If precision reading requires gridlines, use horizontal-only rules at 8-12% opacity.
4. Use range-frame axes where the axis spans the data range rather than arbitrary empty space.
5. Use two-dimensional marks only. No 3D, shadows, bevels, gradients, or perspective effects.
6. Avoid pie charts. If explicitly requested, use no more than four slices, direct percentage labels, and 2D rendering only.
7. Aim for an aspect ratio near 1.5:1 for ordinary charts. Sparklines and small multiples are exceptions.
8. Start with gray data marks and one accent color for the key point, line, or series. Use no more than four distinct colors.
9. Use off-white light backgrounds (`#fffff8`) and intentional dark backgrounds (`#151515`). Avoid pure white and pure black.
10. Use serif fonts for titles, labels, annotations, and data values. Small axis ticks can use system sans-serif.
11. Do not use dual y-axes. Use small multiples with shared x-axis or shared scales.
12. Annotate peaks, troughs, inflection points, event boundaries, and outliers directly on the chart.
13. Show comparison context with a reference line, target, prior-period series, shaded band, or peer group.
14. Keep tooltips plain: label, value, unit, and minimal context. No shadows, arrows, decorative panels, or color blocks.
15. Use progressive disclosure. Keep the overview clean and reveal details through hover, focus, tap, or click.
16. Make charts accessible: 3:1 contrast for chart elements, 4.5:1 for text, text alternatives, keyboard access, and no color-only encoding.
17. Make charts responsive by changing layout, tick density, or chart type across viewport widths. Do not merely shrink dense desktop charts.
18. Animate data transformations only. Respect `prefers-reduced-motion`.
19. Treat dark mode as a separate palette. Never invert colors mechanically.
20. Make titles assert findings, not describe axes.
21. Format numbers for humans: `$1.2M`, `12,450`, consistent precision, units stated once.
22. Do not chart one or two numbers. Use a sentence or table when that communicates more clearly.

## Library Quick Reference

Read one matching reference file for concrete implementation details:

| Library | Reference | Essential defaults |
|---|---|---|
| Recharts | `references/rules/recharts.md` | Hide grid, remove `<Legend />`, direct labels, no top/right axes, minimal tooltip |
| ECharts | `references/rules/echarts.md` | `splitLine.show: false`, `legend.show: false`, `grid.show: false`, `endLabel` |
| Chart.js | `references/rules/chartjs.md` | `grid.display: false`, `plugins.legend.display: false`, direct labels plugin |
| matplotlib/seaborn | `references/rules/matplotlib.md` | Hide top/right spines, set spine bounds, serif fonts, off-white figure background |
| Plotly | `references/rules/plotly.md` | `showgrid=False`, `showlegend=False`, `plot_bgcolor='#fffff8'`, `zeroline=False` |
| D3/SVG/HTML | `references/rules/svg-html.md` | Minimal domains, no plot backgrounds, direct SVG text labels, accessible roles |

Cross-cutting references:

| Topic | Reference |
|---|---|
| Anti-pattern detection and one-line fixes | `references/rules/anti-patterns.md` |
| Accessibility, responsiveness, animation, dark mode | `references/rules/interactive-and-accessible.md` |
| Full palettes, font stacks, numeric typography | `references/rules/typography-and-color.md` |
| Small multiples, sparklines, slopegraphs | `references/rules/small-multiples-sparklines.md` |
| Working examples | `references/examples/` |
| Interactive before/after demo, CDN-backed and reference-only | `references/interactive-demo.html` |
| Upstream license and provenance | `references/upstream/` |

## Chart Type Guidance

| Type | Default treatment |
|---|---|
| Line | 1.5-2px stroke, no dots unless fewer than seven points, direct label at endpoint, annotate notable events |
| Bar | Prefer horizontal bars for categories, sort descending, label values directly, use gray with one accent |
| Scatter | Small gray dots, highlight key cluster or outlier, add regression line only when analytically justified |
| Time series | Label events on the chart, compare against target or prior period, avoid dual axes |
| Small multiples | Same scale across panels, shared labels, no panel borders, direct panel titles |
| Sparkline | Word-sized, no axes or labels, min/max dots, endpoint value when useful |
| Table | Whitespace and thin rules, right-aligned numbers, no zebra striping, highlight meaningful outlier only |
| Slopegraph | Before/after endpoints labeled with names and values, gray slopes plus one highlight |
| Heatmap | Sequential or diverging palette, cell values where readable, companion table for accessibility |

## Review Checklist

Before presenting code or critique, verify:

- No top or right border/spine/frame.
- No legend where direct labels work.
- Gridlines are absent or horizontal-only at opacity no greater than 0.12.
- Aspect ratio fits the data and target viewport.
- Background uses `#fffff8` or an intentional dark palette, not pure white or black.
- Data labels and titles use a serif font stack.
- Default series color is gray; accent color is selective.
- No 3D, decorative gradients, shadows, gauges, or chartjunk.
- No dual y-axis.
- The chart includes comparison context.
- The most important peak, trough, outlier, event, or inflection point is annotated.
- Tooltips are plain and accessible.
- Hover details have tap or focus alternatives.
- Text alternatives exist through `aria-label`, nearby summary text, or data table.
- Colors meet contrast requirements and are not the sole encoding.
- Animation is purposeful and respects reduced motion.
- The chart remains usable at narrow and wide viewports.
- The title states a finding.
- Numbers use readable units and consistent precision.
- The chart is warranted; a sentence or table would not communicate better.
