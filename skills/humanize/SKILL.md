---
name: humanize
description: 'Detects and removes AI-generated writing patterns while preserving meaning and facts. Triggers on: "humanize text", "make this sound human", "remove AI patterns", "rewrite to sound natural", "make this less AI", "de-slop this", "not sound like ChatGPT", "human pass".'
metadata:
  version: 1.0.1
  category: review
  tags: [writing, ai-detection, natural-language, rewriting]
  difficulty: intermediate
---

# Humanize: AI Pattern Detection and Removal

Remove AI-generated writing patterns from text. Produce natural, human-sounding output that preserves meaning.

This is not a generic rewriter. It targets specific, documented AI-writing patterns catalogued by Wikipedia's WikiProject AI Cleanup from thousands of observed instances.

## Workflow

Five phases. Each phase has a clear input, transformation, and output. Do not skip phases.

### Phase 1: Detection Scan

Read the input text. Load `references/detection-patterns.md`. Scan for two categories of signals:

**A. Lexical patterns** (the 24 catalogued AI-writing patterns):

| Category          | Patterns                                                                                                                                    | Priority                                |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Content inflation | Significance puffing, notability claims, superficial -ing analyses, promotional language, vague attributions, formulaic challenges sections | HIGH — loudest AI tells                 |
| Vocabulary        | AI-frequency words, copula avoidance, filler phrases, excessive hedging                                                                     | HIGH — statistically detectable         |
| Structure         | Rule of three, negative parallelisms, elegant variation, false ranges, inline-header lists                                                  | MEDIUM — structural fingerprints        |
| Style             | Em dash overuse, boldface overuse, title case headings, emoji decoration, curly quotes                                                      | MEDIUM — formatting tells               |
| Communication     | Chatbot artifacts, knowledge-cutoff disclaimers, sycophantic tone, generic conclusions                                                      | LOW — obvious, usually caught by author |

**B. Statistical regularity signals** (see `references/statistical-signals.md`):

| Signal                          | What to look for                                                                               |
| ------------------------------- | ---------------------------------------------------------------------------------------------- |
| Sentence length uniformity      | Sentences clustering within a narrow word-count range                                          |
| Low clause density variation    | Every sentence has the same number of clauses                                                  |
| Flat information density        | Every sentence carries roughly the same amount of detail                                       |
| High-frequency phrase templates | Stock collocations and common bigrams/trigrams dominating the text                             |
| Excessive transition markers    | Formal connectives appearing more than 8 per 1,000 words                                       |
| Structural symmetry             | Paragraphs and sentences following balanced, mirror-like patterns                              |
| Uniform inter-sentence cohesion | Every sentence tightly follows the previous with no topic shifts or digressions                |
| Generic function word usage     | Connectors and prepositions used in textbook-standard distribution with no personal tendencies |

Output a detection report using the detection report template (see Output Format).

**Instance severity rating:**

| Severity | Criteria                                                                                                        |
| -------- | --------------------------------------------------------------------------------------------------------------- |
| HIGH     | 3+ patterns co-occurring in a single paragraph, or any paragraph saturated with AI vocabulary (5+ signal words) |
| MEDIUM   | 1-2 patterns in a paragraph, or a statistical signal present across 3+ consecutive sentences                    |
| LOW      | Isolated single instance of any pattern, or a borderline statistical signal                                     |

### Phase 2: Structural Rewrite

Transform document structure to break AI-typical organization:

- Convert uniform paragraph lengths to varied blocks
- Merge or split sentences to break rhythmic uniformity
- Reorder clauses where meaning permits
- Convert formulaic list structures to narrative where appropriate
- Remove tripartite constructions unless the content genuinely has three parts

Do not change factual content. Do not add information. Do not remove cited sources, data, or technical terms.

### Phase 3: Vocabulary and Style Pass

Apply pattern-specific rewrites from the detection report:

- Replace AI-frequency vocabulary with natural alternatives
- Restore simple copulas (is/are/has) where the text uses elaborate substitutes
- Remove filler phrases and excessive hedging
- Cut promotional language and significance inflation
- Replace vague attributions with specific ones (or remove if no source exists)

Load the appropriate style profile from `references/style-guide.md` based on the target domain. Apply domain-specific voice calibration.

### Phase 4: Entropy and Variation

Human writing has burstiness — irregular rhythm, varied sentence lengths, uneven information density. AI text is statistically smooth. This phase breaks that smoothness.

Load `references/statistical-signals.md` for target ranges. Apply:

- **Sentence length variance**: mix short declarative with longer explanatory. Target visible variance across any 5-sentence window.
- **Clause density variation**: alternate simple sentences (one clause) with compound/complex (2-3 clauses). Do not settle on a uniform clause count.
- **Information density variation**: let some sentences carry heavy detail while others are light — a summary statement, a reaction, a pivot. Uniform density reads as generated.
- **Phrase template breaking**: replace stock collocations with specific phrasings. "Play a role in" -> name the specific action. "In terms of" -> delete or restructure.
- **Inter-sentence cohesion variation**: not every sentence should tightly follow the previous. Allow small topic expansions, brief asides, or contextual jumps that a thinking human would make.
- **Function word personalization**: vary connector usage. Use "but" in one place, "still" in another, nothing in a third. Do not default to the same conjunction pattern throughout.
- **Paragraph length variance**: mix single-sentence paragraphs with 4-5 sentence blocks.
- **Controlled imperfection**: fragments at impact positions, parenthetical asides, concessive turns. Sparingly — seasoning, not structure.

### Phase 5: Validation and Output

Two checks before delivering:

**Semantic check:** Compare rewrite against original. Every factual claim, data point, argument, and technical term in the original must be present in the rewrite. If anything was lost, restore it.

**Self-audit:** Ask internally: "What still sounds AI-generated about this text?" If residual patterns remain, fix them. One pass only — do not loop indefinitely.

Output the final text followed by a brief changes summary.

## Output Format

### Full Rewrite / Targeted Fix / Style Shift

```
[Humanized text]

---
Changes: [2-4 bullet summary of what was changed and why]
Patterns detected: [list of pattern numbers/names found]
Domain: [detected or specified domain]
```

For short texts (under 100 words), skip the changes summary unless the user requests it.

### Detection Only

```
## Detection Report

**Domain:** [detected or specified]
**Overall severity:** [HIGH / MEDIUM / LOW]
**Patterns found:** [count]

### Findings

| Location | Pattern | Severity | Evidence |
|----------|---------|----------|----------|
| Para 1 | #7 AI vocabulary | HIGH | "delve", "intricate", "pivotal" in same sentence |
| Para 2 | #8 Copula avoidance | MEDIUM | "serves as" instead of "is" |
| Para 1-4 | Sentence length uniformity | MEDIUM | All sentences 18-22 words, SD < 3 |
| ... | ... | ... | ... |

### Statistical Signals

| Signal | Status | Detail |
|--------|--------|--------|
| Sentence length variance | FLAG | SD ~3 words (human typical: 7-15) |
| Transition frequency | OK | 5 per 1,000 words |
| ... | ... | ... |

### Summary
[1-2 sentences: overall assessment and highest-priority patterns to fix first]
```

## Reference Files

| File                                 | Purpose                                              | Load When                            |
| ------------------------------------ | ---------------------------------------------------- | ------------------------------------ |
| `references/detection-patterns.md`   | 24 AI-writing patterns with examples                 | Always (Phase 1)                     |
| `references/statistical-signals.md`  | 12 statistical regularity signals with target ranges | Phase 1 (scan) and Phase 4 (targets) |
| `references/style-guide.md`          | Domain-specific voice profiles and calibration rules | Phase 3 (match to domain)            |
| `references/transformation-rules.md` | Structural rewrite strategies and entropy techniques | Phase 2 and Phase 4                  |
| `examples/academic.md`               | Before/after pairs for academic writing              | When domain is academic              |
| `examples/blog.md`                   | Before/after pairs for blog/casual writing           | When domain is blog or social        |
| `examples/professional.md`           | Before/after pairs for professional/business writing | When domain is professional          |

## Domain Detection

If the user does not specify a domain, infer from:

1. Vocabulary density and jargon type
2. Citation patterns
3. Sentence complexity
4. Register (formal/informal markers)

Default to **professional** if ambiguous.

Supported domains: `academic`, `technical`, `blog`, `social`, `professional`, `marketing`

## Behavioral Constraints

1. **Never fabricate.** Do not add facts, citations, quotes, statistics, or claims not in the original.
2. **Never remove data.** Numbers, dates, names, URLs, and cited sources must survive the rewrite.
3. **Preserve argument structure.** If the original makes points A, B, C in that order with that logic, the rewrite must preserve the logical flow.
4. **Do not over-humanize.** Some text is meant to be neutral and informational. A technical specification does not need personality. Match the appropriate register.
5. **Respect code blocks and structured data.** Do not humanize code, tables, JSON, YAML, or any structured/machine-readable content. Pass these through unchanged.
6. **One pass through the pipeline.** Do not run the 5-phase pipeline recursively. If the output still has tells after Phase 5, note them in the changes summary rather than looping.

## Scope Modes

| Mode               | Trigger                                                        | Behavior                                                     |
| ------------------ | -------------------------------------------------------------- | ------------------------------------------------------------ |
| **Full rewrite**   | "humanize this", "rewrite naturally"                           | Run all 5 phases                                             |
| **Detection only** | "check for AI patterns", "does this sound AI"                  | Run Phase 1 only, output detection report                    |
| **Targeted fix**   | "fix the AI-sounding parts", "just clean up the obvious stuff" | Run Phase 1, then apply fixes only to HIGH-priority patterns |
| **Style shift**    | "make this more casual/academic/professional"                  | Run Phases 3-4 with specified domain profile                 |

## Error Handling

| Problem                                | Cause                                                           | Resolution                                                                                                                                                        |
| -------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Input under 20 words                   | Insufficient signal for pattern detection                       | Report: "Text too short for reliable pattern detection." Apply vocabulary fixes only (Phase 3) if obvious patterns are present. Skip statistical signal analysis. |
| Input is entirely code/structured data | No prose to humanize                                            | Report: "Input is structured data — no humanization applicable." Return input unchanged.                                                                          |
| Mixed human + AI text                  | Partial AI generation or human-edited AI output                 | Run Phase 1 on full text. Flag only paragraphs/sections with detected patterns. Apply Phases 2-4 selectively to flagged sections. Leave clean sections untouched. |
| Domain ambiguous after detection       | Input mixes registers (e.g., academic citations in a blog post) | Default to **professional**. Note the ambiguity in the output: "Domain defaulted to professional — specify if another profile is preferred."                      |
| Semantic drift detected in Phase 5     | Rewrite altered meaning during structural/vocabulary changes    | Restore the drifted factual claim from the original. Do not re-run the full pipeline. Note the restoration in the changes summary.                                |
| Input contains fabricated citations    | Original text has hallucinated sources                          | Not detectable — this skill humanizes style, not factual accuracy. Pass through unchanged. Note in limitations if the user asks about accuracy.                   |
| All patterns are LOW severity          | Text is mostly human-written with minor tells                   | In targeted fix mode, report findings but recommend no changes. In full rewrite mode, apply light-touch fixes only — do not over-edit clean text.                 |

## Integration Point

Other writing skills can import `references/detection-patterns.md` as a pattern library for their own anti-pattern sweeps. The detection patterns are the shared asset; the pipeline is this skill's domain.

## Limitations

- Cannot verify factual accuracy of the original text. Garbage in, humanized garbage out.
- Effectiveness depends on input length. Very short texts (under 20 words) have insufficient signal for pattern detection.
- Style profiles are guidelines, not voice cloning. The output will sound natural but will not match a specific author's voice without additional calibration.
- Does not interact with external AI-detection APIs. Assessment is heuristic, not benchmark-verified.
