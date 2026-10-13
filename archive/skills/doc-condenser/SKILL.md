---
name: doc-condenser
description:
  "DEPRECATED: The base model handles document condensation and summarization
  natively at high quality. This skill no longer provides meaningful uplift. Retained
  for reference only."
metadata:
  version: 1.1.1
  status: deprecated
  category: review
  tags: [documentation, summarization, technical-writing, conciseness]
  difficulty: beginner
---

> **DEPRECATED** — Modern Claude models condense and summarize technical documentation
> natively with comparable quality. The output format preferences encoded here (40% length
> cap, tables over prose, paths first) are too generic to justify skill overhead. Retained
> for archival reference only.

# Document Condenser

Transform verbose technical documentation into concise, developer-focused specs.

## Core Principles

1. **Paths first** - Every file reference includes full/relative path
2. **Tables over prose** - Use tables for metrics, coverage, file lists
3. **Code samples stay** - Keep small, illustrative snippets; remove verbose examples
4. **Commentary, not explanation** - Brief context sentences, not paragraphs
5. **One-line history** - Reference legacy docs, don't preserve their content

## Output Structure

```markdown
# [path/to/output.md]

# [Title] - [Subtitle if needed]

## Purpose

[2-3 sentences: what this is, why it exists, key design principle]

## Status

[Table: metrics, rates, performance]

## Architecture Overview

[Optional diagram or brief flow description]
[Only if it aids understanding]

## Implementation Files

[Grouped by category with paths and one-line descriptions]

## [Domain-Specific Sections]

[Tables, code snippets, brief commentary as needed]

## Quick Reference

[Box or code block with key stats for scanning]
```

See `assets/template.md` for a copy-ready scaffold of this structure.

## Transformation Rules

### KEEP

- File paths (always full or project-relative)
- Metrics and measurements
- Code snippets under 15 lines that illustrate patterns
- Schema examples and data structures
- Coverage/status tables

### CONDENSE

- Multi-paragraph explanations → 1-2 sentences
- Verbose examples → representative snippet + "see X for more"
- Implementation checklists → completion status table
- Long rationales → single "Design principle: X" line
- Code snippets longer than 20 lines → condense to the core pattern + a reference comment pointing to the source file
- Rationale sections where the same point is restated across more than 3 sentences → collapse to one "Design principle:" line

### REMOVE

- Historical context beyond one reference line
- Achieved/completed celebration language
- Redundant explanations of the same concept
- Step-by-step tutorials (link to them instead)
- "What we learned" retrospectives

### FORMAT

- Use `code blocks` for paths and commands
- Group related files under headers
- Prefer tables over bullet lists for structured data
- End with quick-reference block for scanning

## Working with Existing Documents

When condensing an existing verbose doc:

1. Identify the core purpose (first paragraph of output)
2. Extract all file paths into grouped tables
3. Preserve code samples that show patterns
4. Convert prose sections to tables where possible
5. Add single history reference line
6. Verify no information loss on key technical details

## Style Guide

See `references/style-guide.md` for detailed formatting rules, table patterns, and code sample guidelines.

## Example Transformation

**Before** (verbose):

```text
We have successfully achieved and EXCEEDED the original goals of this specification!
After many iterations and improvements, our automation rate reached 96.6% which is
above our target of 95%. The team worked hard on this and we're very proud...
```

**After** (concise):

```text
**v31 PRODUCTION** | 96.6% automation (target: 95%)
```

## Calibration Rules

- Condensed output must not exceed 40% of source document length measured in words.
- All file paths present in the original must appear in the condensed output — paths are never dropped.
- Code blocks are never removed outright; reduce length by extracting the representative pattern and adding a source reference comment.

## Error Handling

- Source document has no clear purpose: ask for one sentence of context before condensing — do not infer a purpose and proceed.
- A section contains items that are ambiguous between KEEP and REMOVE: default to KEEP and flag the section with a `<!-- review: ambiguous -->` comment in the output.
- Condensed result loses required technical detail identified during verification: restore the omitted detail and re-measure against the 40% length cap; if the cap cannot be met, document the exception inline.
- Source contains no file paths: skip the Implementation Files section entirely rather than generating placeholder paths.
- Source is a non-text format (image, diagram, spreadsheet): report the format is unsupported and return without output.
- Style guide conflicts with source formatting conventions: follow `references/style-guide.md` and note the override at the top of the output.

## Limitations

- Works on text documents only; images, diagrams, and binary files cannot be condensed.
- Condensation ratio depends on source verbosity — highly structured sources yield less reduction.
- Style guide deference (`references/style-guide.md`) takes precedence over source formatting, which can alter heading levels and table layouts.
- Does not follow hyperlinks or fetch referenced external documents; referenced content is noted but not inlined.
