---
name: literature-review
description: 'Systematic literature review workflow: scope, search (arXiv, Semantic Scholar, Google Scholar), screen, extract, synthesize, and identify gaps. Triggers on: "literature review", "survey the literature", "related work", "systematic review", "synthesize the research", "find papers about", "research gap analysis".'
metadata:
  version: 1.0.1
  complements:
    [arxiv-search, research-critique, manuscript-review, manuscript-provenance]
  category: review
  tags: [academic, literature, synthesis, citations]
  difficulty: intermediate
---

# Literature Review

Systematic discovery, extraction, and synthesis of academic research on a defined topic.

## When to use this skill vs. others

| Need                                                  | Skill                              |
| ----------------------------------------------------- | ---------------------------------- |
| Survey a research area, synthesize multiple papers    | **literature-review** (this skill) |
| Critique a single paper's methodology and claims      | research-critique                  |
| Audit a manuscript's formatting, structure, citations | manuscript-review                  |
| Verify a manuscript's numbers trace to code           | manuscript-provenance              |
| Search arXiv for papers matching a query              | arxiv-search (utility)             |

## Workflow

### Phase 1: Scope Definition

Before searching, establish the review boundaries:

1. **Research question** — What specific question does the review answer? Vague topics produce vague reviews. "What techniques exist for X" is weaker than "How do methods for X compare on metric Y across domains Z?"
2. **Inclusion criteria** — Define what counts:
   - Date range (e.g., 2020–present)
   - Publication type (peer-reviewed, preprints, both)
   - Domains/categories (e.g., cs.CL, cs.AI)
   - Minimum relevance threshold
3. **Exclusion criteria** — Define what does not count:
   - Tangentially related work
   - Non-primary sources (blog posts, tutorials) unless explicitly included
   - Duplicate or superseded versions
4. **Expected output** — What form should the review take? Narrative synthesis, tabular comparison, gap analysis, annotated bibliography, or related-work section?

Present the scope to the user for confirmation before proceeding.

### Phase 2: Search & Discovery

Execute searches across available sources. Use multiple queries with varying specificity to avoid single-query blind spots.

**Primary source: arXiv (via arxiv-search utility)**

```bash
uv run --with arxiv python scripts/arxiv_search.py "QUERY" --max-results 30 --sort-by relevance
```

Vary queries systematically:

- Broad topic query: `"retrieval augmented generation"`
- Field-scoped query: `ti:retrieval AND abs:generation AND cat:cs.CL`
- Author-anchored query: `au:lewis AND abs:retrieval` (when key authors are known)
- Recency query: same terms with `--sort-by submitted`

**Secondary sources (via web search/fetch):**

- Semantic Scholar API: `https://api.semanticscholar.org/graph/v1/paper/search?query=QUERY&limit=20&fields=title,authors,abstract,year,citationCount,externalIds`
- Google Scholar (via web search): `site:scholar.google.com QUERY`
- Connected Papers (for citation graph exploration): `https://www.connectedpapers.com/search?q=QUERY`

**Snowball strategy:**

- Forward snowball: find papers that cite a key paper (Semantic Scholar citations endpoint)
- Backward snowball: follow the references of key papers
- Use citation count as a signal for influence, not quality

### Phase 3: Screening & Filtering

For each discovered paper, apply the inclusion/exclusion criteria from Phase 1.

Produce a **screening table**:

| #   | ID         | Title       | Authors       | Year | Relevant? | Reason                          |
| --- | ---------- | ----------- | ------------- | ---- | --------- | ------------------------------- |
| 1   | 2301.07041 | Paper Title | Author et al. | 2023 | Yes       | Directly addresses RQ           |
| 2   | 2302.12345 | Other Paper | Author B      | 2023 | No        | Tangential — focuses on X not Y |

Rules:

- Screen on title + abstract first. Read full paper only for borderline cases.
- When uncertain, include. It is cheaper to drop a paper later than to miss it.
- Track exclusion reasons — they inform the review's limitations section.
- Flag papers that appear in multiple search queries as likely high-relevance.

### Phase 4: Data Extraction

For each included paper, extract a structured record:

```yaml
- id: "2301.07041"
  title: "Paper Title"
  authors: ["Author One", "Author Two"]
  year: 2023
  venue: "NeurIPS 2023"
  research_question: "How does X affect Y?"
  methodology: "Controlled experiment with N=1000"
  key_findings:
    - "Finding 1 with quantitative result"
    - "Finding 2 with effect size"
  limitations: "Single-domain evaluation"
  relevance_to_rq: "Directly compares methods A and B on metric Y"
  citation_count: 142
```

Extraction discipline:

- Record what the paper demonstrates, not what it claims to demonstrate.
- Distinguish empirical findings (data-backed) from interpretive claims (author's framing).
- Note methodology details that enable cross-paper comparison (datasets, metrics, baselines).
- If the paper is available via `pdf_url`, read it for extraction. Do not extract from abstracts alone for included papers.

### Phase 5: Synthesis

Transform extracted records into structured analysis. The synthesis method depends on the output format requested in Phase 1.

**Thematic synthesis** — Group papers by theme, approach, or finding:

- Identify recurring themes across papers
- Note where papers agree, disagree, or address different aspects
- Highlight methodological trends (what approaches are gaining/losing traction)

**Comparative synthesis** — Build comparison tables:

| Method   | Paper(s) | Dataset | Metric | Result | Limitations     |
| -------- | -------- | ------- | ------ | ------ | --------------- |
| Method A | [1], [3] | D1      | F1     | 0.85   | Domain-specific |
| Method B | [2], [4] | D1, D2  | F1     | 0.82   | Requires X      |

**Chronological synthesis** — Map the evolution of the field:

- What was the state of knowledge at time T?
- What shifted and why?
- Where is the field heading?

**Gap analysis** — Identify what is missing:

- Questions raised but not answered by existing work
- Methodological gaps (no one has tried approach X on problem Y)
- Domain gaps (studied in domain A but not B)
- Contradictions between studies that remain unresolved

### Phase 6: Output

Produce the review document in the format specified in Phase 1.

**Standard structure for a narrative review:**

1. **Introduction** — Research question, scope, and motivation for the review
2. **Search methodology** — Databases searched, queries used, inclusion/exclusion criteria, screening results (N found → N screened → N included)
3. **Findings** — Thematic or chronological synthesis of included papers
4. **Discussion** — Cross-cutting analysis, trends, contradictions, gaps
5. **Limitations of this review** — Search scope restrictions, potential biases, papers not accessible
6. **References** — Full citation list for all included papers

**Standard structure for a tabular review:**

1. Summary table (all included papers with key metadata)
2. Comparison matrix (methods × metrics × results)
3. Gap analysis table (questions × coverage)
4. Reference list

**Citation format:**
Default to `Author et al. (Year)` in-text with full references at the end. Adapt to the user's specified format (APA, Chicago, IEEE) if requested.

## Quality Checks

Before delivering the review, verify:

- [ ] Every included paper has a structured extraction record
- [ ] Every claim in the synthesis is traceable to at least one extracted finding
- [ ] The gap analysis identifies at least one concrete research opportunity
- [ ] The review acknowledges its own limitations (search scope, access, biases)
- [ ] Citation format is consistent throughout
- [ ] No paper is cited that was excluded during screening
- [ ] Contradictions between papers are noted, not silently resolved by picking a side

## Edge Cases

| Situation                                             | Adaptation                                                                                                                                                                        |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Very few papers found (<5)                            | The field may be nascent. Note this explicitly. Broaden search terms or check if the topic goes by different terminology. Consider adjacent fields.                               |
| Too many papers found (>100)                          | Tighten inclusion criteria. Consider limiting to top venues, recent years, or high-citation papers. Produce a scoping review rather than exhaustive review.                       |
| User provides a paper list instead of a topic         | Skip Phase 2 (Search). Start from Phase 3 (Screening) with the provided list.                                                                                                     |
| User wants a related-work section for their own paper | Tailor synthesis to position the user's contribution. Organize by approaches the user's work builds on, alternatives it competes with, and gaps it fills.                         |
| No full-text access to key papers                     | Extract from abstracts and note the limitation. Do not fabricate methodology details. Flag which papers were abstract-only in the extraction records.                             |
| Interdisciplinary topic                               | Search across multiple category prefixes. Note when different fields use different terminology for the same concept.                                                              |
| User asks for a "quick" literature review             | Reduce Phase 2 to a single search query, Phase 3 to title-only screening, Phase 4 to abstract-only extraction. Label the output as a preliminary survey, not a systematic review. |
