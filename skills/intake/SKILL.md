---
name: intake
description: Use when preparing an asynchronous discovery questionnaire for one external recipient whose expertise the sender needs, including clarifying the recipient or needed decisions before drafting; not live interrogation, survey analytics or repository onboarding.
metadata:
  version: 1.0.0
  category: business
  tags: [questionnaire, discovery, async, recipient]
  difficulty: intermediate
---

# Intake

Turn the sender's knowledge gaps into **one recipient-specific Markdown questionnaire** for someone else to answer asynchronously. External means a recipient other than the current user, including a colleague; it does not require a different organization. The current user is the sender, not a substitute for the recipient's expertise.

## Scope and authority

Use supplied conversation and documents as context. This workflow needs no network, credentials, hosted model calls or integrations. Discover the active working directory and any requested output location from the current environment before writing; do not assume a repository layout or an upstream filename. Read only supplied relevant local material. The deliverable is a draft for the sender to hand off: no sending, tracker creation, recipient lookup, scheduling or response analytics.

A live interview with the current user, an onboarding/tutoring request, or analysis of survey responses is a different task. Do not recast it as intake. If several recipients are named, select one with the sender before drafting rather than producing a generic form or several questionnaires.

## 1. Select the branch

Extract two things from available context:

- **Recipient:** a named person or specific role, plus their expertise and enough audience context to choose vocabulary. Use the relationship when supplied; a personal name is not required.
- **Needed outcomes:** the concrete decisions or facts the sender needs this recipient to help resolve, and how the answers will inform those outcomes.

**Missing metadata branch:** If either is missing or materially ambiguous, ask the current user only for the missing recipient/expertise or needed decisions/facts in one concise exchange. For example: “Who will receive this, what do they know about the topic, and which decisions or facts do you need their help with?” Omit parts already answered. Ask which recipient to target if necessary. Stop this turn after that clarification; do not manufacture an audience or a generic questionnaire. This branch is complete when the missing fields and the question requesting them are explicit. Resume with the drafting branch when supplied.

**Drafting branch:** When both are concrete, draft immediately. Do not make the sender answer questions whose answers are the reason for contacting the recipient. Unknown domain facts become recipient questions, not sender prerequisites. Missing sender name, deadline or effort does not block drafting: use “Sender” for an unnamed sender and omit unknown optional logistics or label them unknown. Never invent a deadline, completion-time estimate, relationship, promised confidentiality or answer-use commitment.

## 2. Map outcomes to questions

For drafting, read [references/question-design.md](references/question-design.md) for question design and the sender-only coverage format. Assign each input decision/fact an outcome ID. Split compound requests into separately traceable outcomes without losing the original request. Identify the recipient knowledge needed for each, then assign stable question IDs.

Put high-consequence or blocking questions first: an async recipient may only answer the opening section. Use plain language calibrated to this recipient's expertise. One question asks one idea; separate policy, exceptions, quantities and rationale when they require different answers. Keep neutral wording and avoid presupposing unknown domain answers. Related questions may share a theme, but theme grouping must not bury a higher-priority decision beneath optional detail.

This step is complete when every outcome has at least one explicit, answerable question. A catch-all cannot count as coverage. If an outcome is outside this recipient's known expertise, keep a targeted question inviting a partial answer or the appropriate source; mark the expertise limit in the sender matrix rather than silently dropping the outcome or inventing another recipient.

## 3. Draft the recipient document

Read [templates/questionnaire.md](templates/questionnaire.md) only on the drafting branch, then replace its authoring fields with the actual recipient-specific content. It supplies the required recipient layout, not a form to ship with placeholders.

Include context, purpose, from/to, how answers will be used, importance-ordered one-idea questions, and an answer stub directly beneath each question. Explicitly welcome partial answers, “I don't know” and uncertain responses. Explain why a question matters only where that helps the recipient answer. Include a closing catch-all with its own stub. Retain deadline/effort only when actually supplied; none is required. Keep the sender's coverage matrix out of the recipient document, including hidden comments or appendices.

Write exactly one questionnaire Markdown file to the requested destination, or `intake-<topic>.md` in the active working directory when no destination is supplied. Use a short topic slug; inspect an existing target before writing and preserve unrelated content, selecting an unused descriptive filename rather than overwriting it. Do not create ancillary questionnaires, trackers or response stores. If the destination is unavailable or cannot be written, report the exact missing filesystem prerequisite and the unsaved state; do not claim a delivered file.

## 4. Hand off to the sender

Report the questionnaire path and give the **sender-only coverage matrix in the chat**, separately labeled as not for forwarding. It maps every input outcome to final question IDs and flags any expertise limitation. State which optional logistics remain unknown or were omitted. Do not claim the recipient has seen, approved or answered it.

Drafting is complete only when the single recipient document exists, all required framing and answer stubs are present, every input outcome maps to a concrete final question, and no invented logistics or recipient-held answers appear. A well-written subset or an empty template is not completion.

## Package references

- For drafting, [references/question-design.md](references/question-design.md) supplies outcome coverage and question-splitting rules; [templates/questionnaire.md](templates/questionnaire.md) supplies recipient layout.
- For adaptation history, licensing or a proposed upstream refresh, read [references/upstream/provenance.md](references/upstream/provenance.md) and the package-local `LICENSE`. No upstream synchronization is automatic.
