---
name: paper-to-skill
description: 'Converts research papers into executable skill packages via document conversion, critical analysis, and co-evolutionary refinement. Triggers on: "convert this paper to a skill", "paper-to-skill", "extract methodology from paper", "make a skill from this paper". NOT for literature review, use research-critique.'
metadata:
  version: 1.0.1
  category: research
  tags: [paper, arxiv, research, skill-generation, methodology-extraction]
  difficulty: advanced
  phase: build
---

# Paper-to-Skill Pipeline

Transform research papers into production-grade skill packages. The pipeline extracts
the actionable methodology from a paper, structures it as a skill specification, and
feeds it through co-evolutionary refinement to produce a validated package.

This closes the loop between research and practice: a paper published today can become
an executable skill tomorrow, without manual authoring.

## Reference Files

| File                                  | Contents                                          | Load When |
| ------------------------------------- | ------------------------------------------------- | --------- |
| `references/extraction-patterns.md`   | Patterns for extracting methodology from papers   | Always    |

## Prerequisites

- The `to-markdown` skill (for PDF/document conversion)
- The `research-critique` skill (for paper analysis)
- The `test-engineer` agent (for co-evolutionary skill generation)

## Workflow

### Phase 1: Paper Intake

Accept the paper in any supported format:

| Input Format          | Action                                                     |
| --------------------- | ---------------------------------------------------------- |
| arXiv ID (e.g., 2604.01687) | Fetch via `https://arxiv.org/abs/<id>`, convert PDF  |
| arXiv URL             | Extract ID, fetch and convert                              |
| PDF file path         | Convert using `to-markdown` skill                          |
| URL to paper          | Fetch via `WebFetch`, convert if PDF                       |
| Pasted text           | Use directly                                               |

For PDF conversion, invoke the `to-markdown` skill:
> Convert this PDF to clean markdown, preserving section structure, tables, equations,
> and algorithm pseudocode. Drop references section but keep inline citations.

### Phase 2: Critical Analysis

Invoke the `research-critique` skill on the converted paper:

> Analyze this paper focusing on:
> 1. Core contribution: what is the novel methodology?
> 2. Algorithm description: extract the step-by-step procedure
> 3. Input/output specification: what goes in, what comes out?
> 4. Key parameters and their valid ranges
> 5. Claimed results and the evidence supporting them
> 6. Failure modes and limitations acknowledged by the authors
> 7. Prerequisites and dependencies (tools, data, compute)

The critique output becomes the foundation for the skill specification.

### Phase 3: Skill Specification Extraction

From the critique output, build a structured skill specification:

```yaml
specification:
  name: <kebab-case derived from paper's methodology name>
  domain: <paper's application domain>
  source_paper:
    title: <paper title>
    arxiv_id: <if available>
    url: <paper URL>
    authors: <first author et al.>
    date: <publication date>
  
  capabilities:
    - <capability 1 derived from the methodology>
    - <capability 2>
    - <capability 3>
  
  input_format: <what the skill accepts>
  output_format: <what the skill produces>
  
  algorithm_steps:
    - step: 1
      description: <from paper's algorithm>
      parameters: [<key params with ranges>]
    - step: 2
      description: <next step>
  
  failure_modes:
    - <from paper's limitations section>
  
  example_tasks:
    - <task 1 the methodology would solve>
    - <task 2>
    - <task 3>
```

**Extraction rules:**
- Prefer the paper's own algorithm pseudocode over prose descriptions
- Include parameter ranges from the paper's experiments (e.g., "learning rate: 0.001-0.01")
- Map the paper's terminology to armory conventions (e.g., "module" → "skill", "pipeline" → "workflow")
- If the paper describes multiple variants, extract the best-performing one

See `references/extraction-patterns.md` for patterns specific to common paper types.

### Phase 4: Skill Generation

Hand off the specification to the `test-engineer` agent for co-evolutionary generation:

> Evolve a skill for: [specification.domain]
>
> Capabilities: [specification.capabilities]
> Algorithm: [specification.algorithm_steps]
> Input: [specification.input_format]
> Output: [specification.output_format]
> Failure modes: [specification.failure_modes]
> Example tasks: [specification.example_tasks]
>
> Source: [specification.source_paper.title] ([specification.source_paper.url])

The test-engineer runs its full co-evolutionary loop (generate → verify → oracle → refine)
using the specification as the task description.

### Phase 5: Attribution and Finalization

Ensure the generated skill properly attributes the source paper:

1. **Frontmatter:** Add `source: <paper_url>` to the metadata
2. **Body:** Include an attribution section at the end of SKILL.md:
   ```markdown
   ## Attribution

   This skill implements the methodology from:
   > <paper title>
   > <authors>
   > <venue/arxiv, date>
   > <URL>
   ```
3. **References:** If the paper has supplementary materials (code, datasets), create a
   source materials reference file in the generated skill's `references/` directory linking to them
4. Verify the skill name does not conflict with existing packages in `manifest.yaml`

## Output

The complete skill package at `skills/<name>/`:
- `SKILL.md` with attribution and paper-derived workflow
- `evals/cases.yaml` with assertions generated by the co-evolutionary loop
- `references/` with extraction patterns and source materials
- `evals/evolution-log.yaml` from the test-engineer's refinement process

## Error Handling

| Error                                | Resolution                                                |
| ------------------------------------ | --------------------------------------------------------- |
| Paper has no clear algorithm         | Extract the methodology from the experiments section      |
| Paper is purely theoretical          | Report: no actionable methodology; suggest literature-review instead |
| PDF conversion fails                 | Try alternative: fetch HTML version or request user paste text |
| Paper methodology requires data/compute | Note in skill's prerequisites; skill may be a workflow template only |
| test-engineer budget exhausted       | Return best-scoring iteration with manual review warning  |

## Limitations

- Cannot extract visual methodologies (circuit diagrams, neural architecture figures)
  — works on textual algorithm descriptions only
- Papers with multiple interdependent contributions may produce overly complex skills
  — consider splitting into multiple skills
- Non-English papers require translation before processing
- The generated skill's quality depends on the paper's clarity of methodology description
