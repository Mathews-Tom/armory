---
name: content-ops
type: preset
description: "DEPRECATED: Superseded by the content-strategist agent, which orchestrates content skills (humanize, linkedin-post-style, html-presentation, md-to-pdf, tavily, youtube-analysis) with per-channel adaptation, audience-aware tone, and automated quality passes. Use content-strategist agent instead."
metadata:
  version: 1.1.0
  status: deprecated
preset:
  packages:
    skills:
      - name: humanize
      - name: linkedin-post-style
      - name: manuscript-review
      - name: manuscript-provenance
      - name: changelog-composer
      - name: md-to-pdf
      - name: doc-condenser
      - name: to-markdown
  compatibility:
    platforms: [darwin, linux]
---

# Content Ops

> **DEPRECATED** — The `content-strategist` agent supersedes this preset. It creates and
> adapts content across channels with audience-aware tone, runs humanize passes
> automatically, and manages the full content lifecycle. Install `content-strategist`
> instead.

An end-to-end content lifecycle toolkit for drafting, refining, reviewing, publishing, and exporting documents.

## Included Skills

| Skill                  | Purpose                                      | Output                              |
| ---------------------- | -------------------------------------------- | ----------------------------------- |
| `humanize`             | De-AI text, restore natural writing voice     | Rewritten prose free of AI patterns |
| `linkedin-post-style`  | Format content for LinkedIn and social media  | Platform-ready social posts         |
| `manuscript-review`    | Pre-submission readiness audit                | Structured review with action items |
| `manuscript-provenance`| Verify authorship and computational origins   | Provenance verification report      |
| `changelog-composer`   | Generate release notes from commit history    | Formatted changelog / release notes |
| `md-to-pdf`            | Export markdown documents to PDF              | PDF file                            |
| `doc-condenser`        | Summarize and condense lengthy documents      | Condensed summary document          |
| `to-markdown`          | Convert various formats to markdown           | Markdown file                       |

## Workflow

1. **Draft** — Write or import raw content. Use `to-markdown` to convert source material
   from other formats into markdown for a consistent working format.
2. **Refine** — Use `humanize` to remove AI-sounding patterns and restore natural voice.
   Use `doc-condenser` to tighten verbose sections or produce executive summaries.
3. **Review** — Use `manuscript-review` for a structured audit of formatting, structure,
   and prose quality. Use `manuscript-provenance` to verify that all figures, tables, and
   numbers trace to their computational origins.
4. **Publish** — Use `linkedin-post-style` to produce social media announcements. Use
   `changelog-composer` to generate release notes from commit history.
5. **Export** — Use `md-to-pdf` to produce final PDF deliverables from markdown sources.

## Choosing the Right Skill

| Task                                          | Skill                  |
| --------------------------------------------- | ---------------------- |
| Text sounds too robotic or AI-generated       | `humanize`             |
| Need a LinkedIn or social media post          | `linkedin-post-style`  |
| Preparing a manuscript for submission         | `manuscript-review`    |
| Confirming data/figures match source code     | `manuscript-provenance`|
| Writing release notes for a new version       | `changelog-composer`   |
| Exporting a document as PDF                   | `md-to-pdf`            |
| Shortening a long document or extracting key points | `doc-condenser`  |
| Converting HTML, DOCX, or other formats to MD | `to-markdown`          |

## When to Use

- Technical writing projects requiring draft-to-PDF workflows.
- Open source projects needing automated release notes and changelogs.
- Manuscript preparation pipelines from raw draft through submission audit.
- Content marketing workflows producing blog posts, social announcements, and summaries.
- Document conversion and standardization across mixed-format source material.
- Any project where content passes through multiple refinement stages before publication.
