---
name: media-craft
type: preset
description: "DEPRECATED: Superseded by the media-producer agent, which orchestrates the same skills (concept-to-image, concept-to-video, remotion-video, html-presentation, static-web-artifacts-builder, architecture-diagram) with intelligent format routing based on content type. Use media-producer agent instead."
metadata:
  version: 1.1.0
  status: deprecated
preset:
  packages:
    skills:
      - name: concept-to-image
      - name: concept-to-video
      - name: remotion-video
      - name: html-presentation
      - name: static-web-artifacts-builder
      - name: architecture-diagram
  compatibility:
    platforms: [darwin, linux]
---

# Media Craft

> **DEPRECATED** — The `media-producer` agent supersedes this preset. It orchestrates the
> same six skills with intelligent format selection based on content type — users describe
> what they want to visualize and the agent routes to the right skill. Install
> `media-producer` instead.

A concept-to-deliverable pipeline for generating images, videos, presentations, interactive visuals, and diagrams.

## Included Skills

| Skill                        | Purpose                                      | Output Format |
| ---------------------------- | -------------------------------------------- | ------------- |
| concept-to-image             | Generate illustrations from descriptions     | PNG, SVG      |
| concept-to-video             | Produce animated explainers and motion clips  | MP4, GIF      |
| remotion-video               | Build branded, programmatic video content     | MP4           |
| html-presentation            | Author slide decks from structured content   | HTML          |
| static-web-artifacts-builder | Create interactive data visuals and widgets   | HTML          |
| architecture-diagram         | Render system topology and architecture maps | SVG, PNG      |

## Workflow

1. **Concept → Image** — Describe a visual concept in plain language. `concept-to-image` renders it as a PNG or SVG using HTML/CSS techniques.
2. **Concept → Video** — Provide a narrative or sequence. `concept-to-video` produces an MP4 or GIF animation via Manim. For branded or React-based video, use `remotion-video` instead.
3. **Concept → Presentation** — Supply an outline or topic. `html-presentation` generates a full slide deck with transitions and speaker notes.
4. **Concept → Interactive HTML** — Describe a data visualization or interactive widget. `static-web-artifacts-builder` outputs a self-contained HTML artifact.
5. **Concept → Diagram** — Specify system components and relationships. `architecture-diagram` renders topology diagrams for documentation or review.

## Choosing the Right Skill

| If you need...                              | Use                          |
| ------------------------------------------- | ---------------------------- |
| A static illustration, icon, or graphic     | concept-to-image             |
| An animated explainer or math visualization | concept-to-video             |
| A branded marketing or product video        | remotion-video               |
| A conference talk or lecture deck           | html-presentation            |
| An interactive chart, dashboard, or widget  | static-web-artifacts-builder |
| A system architecture or infrastructure map | architecture-diagram         |

## When to Use

- Generating visual assets for blog posts, documentation, or social media.
- Producing explainer videos or animated walkthroughs of technical concepts.
- Building branded video content with React/Remotion pipelines.
- Creating conference presentations or internal slide decks from outlines.
- Designing interactive data visualizations or dashboards as standalone HTML.
- Rendering architecture diagrams for system design reviews or RFCs.
