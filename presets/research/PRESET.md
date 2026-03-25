---
name: research
type: preset
description: "DEPRECATED: Superseded by the research-analyst agent, which orchestrates literature-review, tavily, youtube-analysis, competitive-analyzer, and web-fetch with parallel multi-source investigation, cross-referencing, and confidence-rated synthesis. Use research-analyst agent instead."
metadata:
  version: 1.1.0
  status: deprecated
preset:
  packages:
    skills:
      - name: literature-review
      - name: research-critique
      - name: manuscript-review
      - name: manuscript-provenance
    utilities:
      - name: arxiv-search
  compatibility:
    platforms: [darwin, linux]
---

# Research Preset

> **DEPRECATED** — The `research-analyst` agent supersedes this preset. It conducts
> multi-source investigation with parallel Agent spawning across web, academic, video,
> and competitive sources, cross-references findings with confidence ratings, and
> produces cited synthesis reports. Install `research-analyst` instead.

An end-to-end scholarly workflow for discovering, evaluating, synthesizing, and publishing
academic research.

## Included Packages

| Type    | Package               | Role                                                      |
| ------- | --------------------- | --------------------------------------------------------- |
| Utility | arxiv-search          | Search arXiv for papers, retrieve structured metadata     |
| Skill   | literature-review     | Systematic review: search, screen, extract, synthesize    |
| Skill   | research-critique     | Critical analysis of a single paper's merit               |
| Skill   | manuscript-review     | Pre-publication audit of formatting, structure, citations |
| Skill   | manuscript-provenance | Verify manuscript numbers trace to computational outputs  |

## Workflow

1. **Discover** — Use `arxiv-search` to find papers on a topic. Query by keyword,
   author, category, or specific arXiv IDs.
2. **Survey** — Use `literature-review` to systematically screen, extract, and synthesize
   findings across the discovered papers. Produces thematic reviews, comparison tables,
   or gap analyses.
3. **Evaluate** — Use `research-critique` for deep analysis of individual papers —
   methodology, claims-evidence alignment, contribution significance.
4. **Write** — Draft manuscript with the context and citations gathered in prior steps.
5. **Audit** — Use `manuscript-review` for a 24-checkpoint pre-submission audit covering
   structure, citation hygiene, prose quality, and AI-pattern detection.
6. **Verify** — Use `manuscript-provenance` to confirm every number, table, and figure
   in the manuscript traces to code and computational outputs.

## When to Use

- Research projects requiring systematic literature surveys.
- Academic writing workflows from literature review to submission.
- Thesis chapters or dissertation work.
- Conference/journal paper preparation.
- Grant proposal background research.

## Dependencies

The `arxiv-search` utility requires the `arxiv` Python package:

```bash
uv pip install arxiv
```

All other packages are prompt-only skills with no additional dependencies.
