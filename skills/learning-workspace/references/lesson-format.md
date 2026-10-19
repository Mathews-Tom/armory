# Lesson format

Load before writing a lesson or reusable reference material. Workspace lesson
files use the next unused number: `lessons/0001-customer-keys.md`, with lesson ID
`L-0001`. Create the directory only when the first actual lesson is written. Check
existing names; preserve unrelated edits and never reuse an existing lesson ID.

## Markdown lesson: schema version 1

```markdown
---
schema_version: 1
lesson_id: L-0001
mission_revision: 1
created_on: 2026-10-19
concepts_introduced: [duplicate-key-selection]
---
# Count customers, not export rows

## Mission and decision
Supports SC1. Prior evidence: LR-0001 is self-report, not an inspected attempt.
We need to find whether choosing a customer key needs practice.

## Task and success criterion
Prepare the count for a weekly summary. The exercise contract says customer_id
identifies a customer; one customer may have several invoice rows. Success:
state the customer count, name the key, and explain why another row may not add
another customer.

## Just enough explanation
A row describes an invoice here, not necessarily a new customer. A repeated
customer_id still names the same customer. This is the synthetic task contract,
not a claim about every export.

## Try it
Rows: (A,10), (A,20), (B,30), where the pair is (customer_id, invoice_amount).
What count belongs in the customer summary, and why? Reply with your reasoning,
or a small table. Ask for a hint or consult the explanation if useful; tell me
which support you used. No runtime or production data is needed.

## Feedback loop
Send your response. I will compare the count, chosen key and explanation against
the criterion, point to a specific mismatch if any, and offer a changed example
for another attempt. Until then this lesson is covered/pending, not demonstrated.

## Sources and follow-up
The data contract above defines this synthetic example. No external source was
inspected or needed. Ask about any unclear term; a shorter or nonvisual task is
available. The next lesson depends on your attempt, not merely opening this file.
```

Required fields: integer `schema_version: 1`, unique `lesson_id: L-NNNN`, positive
integer `mission_revision`, actual `created_on` date, and a list of stable
`concepts_introduced` IDs (possibly empty for a pure revisit). Those IDs record
**coverage**, not learning. An authoring date is not an attempt date. Preserve the
lesson's evidence assumptions even when later records change the next task.

Every lesson supplies: mission criterion and evidence-based selection reason; one
manageable realistic task; explicit success criteria; sufficient explanation;
an accessible way to attempt; a feedback channel and retry path; source/uncertainty
boundaries; and what observation will influence the next decision. Keep answers
apart from the first attempt where practical, but offer hints and an open-resource
path without calling it failure. Record the support actually used. For multiple
choice, use plausible options without accidental formatting/position cues; natural
language clarity matters, not equal character or word counts.

## Real-task feedback

Use synthetic or redacted data to rehearse the action the learner actually needs:
explain a summary, diagnose a count, choose between methods, produce a small
artifact. Compare the learner's response to the criterion, not just to a memorized
phrase. Show the concrete match/mismatch and why it matters, then ask for a fresh
variant when needed. Mark feedback on inspected work as observed; an account of
external practice without the work remains self-report. Do not run tools, mutate
production data, or contact a reviewer on the learner's behalf without separate
authority. Consequential physical/medical/legal tasks need appropriate boundaries;
text feedback is not professional supervision or assurance of safety.

## Portability and access

Markdown is the default: readable without a browser, build step, account or font
download. Use semantic headings, meaningful link labels, small readable tables,
plain-language instructions and text alternatives for diagrams. Fit the learner's
stated language, assistive needs and available input mode. Offer a text response
instead of a drag/click-only task. Keep exercise materials inside the lesson or
local root, and use workspace-relative links; external citations are optional
reading, not runtime dependencies.

Use HTML only when an interaction/visualization materially answers the lesson's
learning task (for example changing row keys and observing count changes), not
for decoration. Make it self-contained offline: no remote scripts/styles/fonts,
tracking, external form submissions or network calls. Use native keyboard-operable
controls, visible labels/focus, adequate contrast, non-color-only feedback and a
textual task/feedback equivalent. Escape learner/source strings as text, not HTML
or executable code. Keep metadata equivalent to the Markdown schema in a visible
or non-executable text block. If browser checks are authorized and available,
exercise the actual keyboard/control paths; otherwise state not browser-checked
and provide the usable Markdown/text alternative. Do not auto-open a browser or
install a runtime merely to deliver a lesson.

## Optional reference material

Create `reference/` only for material the learner will actually reuse. Prefer
short Markdown cheat sheets or `reference/glossary.md`; link them relatively from
lessons. A glossary may define newly introduced terms, with source and any scoped
meaning/aliases. It is a vocabulary aid, **not** proof of comprehension: only the
learning records can establish demonstrated use. Keep old incorrect learner
claims in records rather than as current glossary definitions. When a definition
changes, note the correction source/record if earlier lessons depend on it.
Reuse existing substantive local material; shared assets are warranted only by
actual reuse, never required scaffolding.

Completion: the learner can perform the stated task offline in an accessible
format, return evidence through the stated channel, and receive criterion-based
feedback. Delivery alone creates coverage; it does not create an observed result.
