# Questions and Recalibration

## Writing questions (5–10)

Questions reduce uncertainty. They do not test trivia. Each one:

- is anchored in specific evidence (`evidence_ids`) or a specific gap (a competency marked not observable);
- asks about a decision, a tradeoff, a rejected alternative, a production outcome, personal authorship, an incident, or evolution under changed requirements;
- can only be answered well by someone who did the work and understood it;
- states in `would_change` which competency, attribution or level blocker an answer could move.

Aim questions at the engine's `next_level_blockers`, at low- and medium-confidence competencies that sit one point below a blocking threshold, and at `possible` attributions. Include one question about how AI-assisted or pair-programmed changes were validated when `ai_assisted_commits > 0` or `ai_mentioned_commits > 0` (messages that mention AI tools without a co-author trailer). Never infer authorship from the mention itself.

| Mode | Framing |
|---|---|
| `review` | Interview questions for the candidate |
| `self` | Self-reflection prompts ("What evidence would show…", "Which alternative did you reject and why?") |
| `promotion` | Questions a promotion panel will ask about the target-level requirements |
| `manager` | Conversation prompts for a development discussion; never a test |

Bad: "What is a Python decorator?" Good: "`store.py:40-78` checks the schema version on load but never migrates. What happens to existing users when the format changes, and why was migration deferred?"

## Recording answers

Add each answer to a new judgments file as a self-report:

```json
{"id": "SR-01", "question_id": "Q-03", "answer": "verbatim or faithful summary",
 "competencies": ["architecture"], "contradicts_evidence_ids": ["E-012"], "corroborating_evidence_ids": []}
```

Self-reports are kept verbatim and labelled `self_reported`. They never raise a band on their own. When an answer points to verifiable material (an ADR, a PR, a commit), inspect it and add it as normal evidence. That evidence, not the answer, moves the score.

When an answer disagrees with source evidence, keep both: list the evidence in `contradicts_evidence_ids`, keep the evidence-based score, and say so in the summary.

## Disputes

```json
{"evidence_id": "E-007", "claim": "not_authored", "note": "pair-programmed with a colleague"}
```

| Claim | Engine resolution |
|---|---|
| `not_authored` on `verified`/`probable` attribution with high identity confidence | `retained_verified_attribution`: still supports scores, marked contested |
| `not_authored` otherwise | `excluded_from_scoring` |
| `misinterpreted`, `outdated`, `other` | `flagged_for_review`: re-read the item and revise the interpretation or score yourself |

## Rerunning

```bash
cp "$RUN/assessment.json" "$RUN/assessment.v1.json"
python3 "<skill-dir>/scripts/appraise.py" assess --run "$RUN" --judgments "$RUN/judgments.v2.json" \
  --previous "$RUN/assessment.v1.json"
```

`changes.md` lists the level, range, confidence and competency changes, the added or removed evidence, and any revision drift. Report whether confidence improved and which answers drove the change.

For progress over time, run a fresh `discover` on the current revisions and compare: `appraise.py compare OLD/assessment.json NEW/assessment.json --out progress.md`.
