# Transformation Rules

Structural rewrite strategies for Phase 2. The aim throughout: text shaped by choices for one reader and one subject, not by rule. These are editing techniques judged by readability — none of them target detector metrics.

---

## Paragraph Restructuring

AI text tends toward uniform paragraph length (3-5 sentences each, roughly equal). Writing chosen for a reader varies with the content.

- Split a long paragraph into a short declarative statement + a longer elaboration
- Merge two related short paragraphs into one block
- Allow single-sentence paragraphs at impact positions — when the sentence carries a new fact, not a restatement (see the one-line-closer pattern)
- Break the "topic sentence + support + conclusion" template — not every paragraph needs all three

## Sentence Merging and Splitting

Uniform sentence length reads as generated because no writer choosing for meaning produces it. Let length follow content:

- Merge two short related sentences: "The system is fast. It handles 10K requests." → "The system handles 10K requests per second."
- Split compound sentences where the conjunction adds no meaning: "The team reviewed the code and they found three bugs" → "The team reviewed the code. Three bugs."
- Fold explanations into subordinate clauses when it reduces total words: "X happened. This was because of Y." → "X happened because of Y."
- A dense sentence next to a plain one is fine. Do not redistribute information evenly across sentences — summarizing reactions ("The results were mixed.") may carry one idea while a neighbor carries four.

## List-to-Narrative Conversion

Not all lists should become narrative. Convert when:

- The list is a forced triad (see the rule-of-three pattern)
- The list items are complete sentences disguised as bullets
- The list has inline bold headers (see the boldface pattern)

Keep lists when:

- Items are genuinely parallel (feature comparisons, step-by-step instructions)
- Items are short noun phrases or values
- The context is technical documentation

## Clause Reordering

AI follows predictable clause order: setup → detail → significance. Vary by content:

- Lead with the specific detail, then context: "Three bugs in the auth module. The team found them during Friday's review."
- Start with a consequence, then explain: "The deployment failed. The config file was missing a required field."
- Bury the attribution mid-sentence: "The river supports, according to a 2019 survey, several endemic fish species."

## Sentence Openings

Rotate openings across a paragraph when repetition is accidental (see the repeated-openings pattern — deliberate repetition for rhythm is a human move; keep it when a voice sample shows it).

- Avoid three consecutive sentences starting with "The [noun]..."
- Adverbial openers: "By Friday, the team had..."
- Prepositional openers: "In the auth module, three bugs surfaced."
- Participial openers sparingly — a trailing participle rider is its own AI pattern

## Word Repetition

Reduce accidental repetition by restructuring, never by synonym cycling (a retired pattern — see `historical-patterns.md`):

- If "system" appears 5 times in a paragraph, restructure so 2-3 instances become pronouns or disappear through sentence merging
- Domain-specific terms are NOT varied — "API" stays "API", not "interface" then "endpoint" then "service boundary"
- Common verbs (is, has, does, makes, gets) are invisible to readers — repeating them is fine

## Stock Phrase Breaking

Replace templates with the specific thing they gesture at:

- "plays a role in" → name the action
- "a wide range of" → name the range or delete
- "in terms of" → delete, restructure
- "it is worth noting that" → state the fact
- "serves as a" → "is"
- "has the potential to" → "can" or "might"
- "in the context of" → "in", "for", or delete

## Anti-Compression Rule

Rewriting is not deleting. Cutting a tell must not cut the claim under it — an inflated sentence usually contains one real fact wearing a costume. Strip the costume, keep the fact. When a whole sentence contains no fact (a pure closer, a send-off paragraph, a phantom objection), deletion is correct; when in doubt, keep the claim in plainer words.

## Replies and Follow-Ups

For text that answers something (review responses, comment replies, follow-up emails), structure matters more than sentence-level style (see the re-explaining-shared-context pattern):

- Answer first. The reader asked a question; the first sentence addresses it.
- Cut every restatement of what the reader already said or knows.
- Keep only information that is new to this reader.
- One-line replies are legitimate. Padding an answer to paragraph length is itself a tell.
