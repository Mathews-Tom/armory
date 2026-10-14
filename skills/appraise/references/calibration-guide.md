# Calibration Guide

You propose. The engine disposes. This file explains what the engine does with your proposals, so your proposals are honest and your report explains the outcome correctly.

## Score anchors (0–5)

| Score | Meaning |
|---|---|
| 0 | A demonstrated serious deficiency: unsafe or fundamentally incorrect execution. Requires directly inspected or executed `weakness` evidence. Never use 0 for missing evidence. |
| 1 | Foundational: limited, bounded execution |
| 2 | Developing: routine scoped work with some independent competence |
| 3 | Proficient: independently reliable on moderately complex work |
| 4 | Advanced: strong judgment and execution across challenging constraints |
| 5 | Exceptional: rare depth, scope and repeatable consequential impact; one elegant function is never enough |
| `null` | Not observable. Add `not_observable_reason` (`no_opportunity`, `no_evidence`, `access_limited` or `not_sampled`) when you know it; the engine recomputes opportunity for collaboration. |

Rate each of the 14 rubric competencies: problem_solving, code_quality, architecture, system_design, testing, security, operations, technical_depth, engineering_judgment, learning (technical); ownership, product_thinking (delivery); collaboration, technical_leadership (influence).

## What the engine enforces

| Rule | Effect |
|---|---|
| No verified, attributable evidence | Score withdrawn → `not_observable` (`evidence_rejected`, `insufficient_attribution` or `no_evidence`) |
| Only self-reports | `self_reported`, capped at 3, excluded from every band |
| Score 4 with fewer than 2 independent sources | Capped at 3. An independent source is a distinct file, commit or host record whose attribution is `verified` or `probable`, whose polarity is not `weakness`, and whose verification is not `repository_claimed` |
| Score 5 with fewer than 3 sources or fewer than 2 subsystems/repositories | Capped at 4 or below |
| Score 4+ without `counterevidence_reviewed: true` | Capped at 3 |
| Score 0 without a verified deficiency | Not observable |
| Your confidence above the evidence breadth | Lowered (high needs 3+ independent verified/probable sources) |
| Evidence overlapping evaluator-directed text, or contested authorship that cannot be verified | Cannot support |

Every cap appears in the competency's `adjustments` and in the report. Do not pre-empt the caps by inflating proposals; the plausible range uses the uncapped value to show what further evidence could change.

Host records can be cited by id. `H-R<n>-…` pull-request and review records are attributed `verified` to the candidate's login, so they can support collaboration, ownership or learning. CI check-run records are `not_applicable`: they describe the project, not the person, and support nothing.

Self-corrections: when the candidate retracted or fixed their own earlier error (a reverted change, a corrected benchmark, an amended claim), cite the fix as a `strength` for learning or judgment, and cite the original lapse as counterevidence. Both stay visible.

## How levels are derived

The rubric declares clauses per level for two bands:

- **Technical capability:** what the candidate's own engineering decisions show. For example, Senior needs at least five technical competencies at 3+, architecture or system design at 4+, and judgment, testing, ownership and an operational dimension at 3+, with no core dimension below 2.
- **Scope / influence:** collaboration, technical leadership, ownership and product thinking feed this band. Staff, Principal and Distinguished **require** it. `scope_influence_status` is:
  - `observed` when collaboration or technical leadership is observed;
  - `partial` when only ownership or product thinking is (common for solo work: the band can reach Senior on sustained ownership but cannot clear Staff's collaboration and leadership requirements);
  - `not_observable` otherwise.

  When scope blocks, the overall level stops at the highest level that does not require scope, and the plausible range keeps the technical upper bound visible.

Principal needs evidence that spans at least two repositories. Distinguished needs verified external corroboration, so it is unreachable from repositories alone. No average is taken anywhere.

The engine evaluates every clause three ways:

- **Normal:** gives the recommended level.
- **Conservative:** low-confidence scores −1 and unknowns fail; gives the lower bound.
- **Optimistic:** low-confidence and capped scores get +1, and unknown clauses (those blocked only by not-observable competencies) pass. Separately, medium-confidence scores get +1, but that can lift the upper bound by at most one level above the recommendation. Together they give the upper bound: a competency at 3 with medium confidence keeps the next level visible without pretending that every medium judgment is simultaneously understated. Label confidence honestly; it moves the range, not the recommended level.

The result is `inconclusive` when fewer than 4 technical competencies are observable, fewer than 5 supporting evidence items verify, or no repository holds attributable candidate work. It then lists the reasons.

Confidence is the weakest of attribution, evidence and coverage confidence, capped by the width of the range (1 level → at most medium; 2 or more → low).

## Writing the summary

`summary` (at most 2,400 characters) is rendered under "Assessor summary". Write it the way an experienced reviewer would brief a colleague, in four short paragraphs separated by blank lines:

1. What the person built or changed, and under which constraints.
2. What the work shows they do well.
3. Where it falls short or carries risk.
4. What can't be judged from this work, and why.

Style rules:

- Use plain sentences with active verbs. No enumerations like "(1) … (2) …", no "Strongest patterns:" or "Confirmed weaknesses:" labels, and no lists of five ids.
- Cite one to three evidence ids per claim, in parentheses after the claim, such as `(E-005, E-019)`. The report turns each into a small linked superscript, so pick the ids that best prove the point.
- Name concrete things, such as the retrieval ranking guard or the migration test, rather than abstractions like "rigorous methodology".
- A line starting with `- ` renders as a bullet; use bullets only for a short list of risks.

Never name a level, a percentile or a comparison with other people. The engine's determination and its plain-language reasons sit directly above your summary.

The same voice applies to competency rationales, plan items and questions: write for the person who will read the report, not for the engine.

## Development plan

Use at least three items, ordered by priority. Each item states:

- `category`: `confirmed_weakness`, `plausible_risk`, `evidence_gap` or `next_level_opportunity`
- the competencies it addresses and the source evidence ids
- why it matters
- a concrete action
- a measurable success criterion (artifact, metric or observable behaviour)
- effort (`S`, `M` or `L`), priority (`P1`–`P3`) and horizon in days

Draw `next_level_opportunity` items from the engine's `next_level_blockers` after a first `assess`. For self and promotion modes, make P1 items achievable within 90 days.
