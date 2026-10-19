# Mission format

Load before creating or changing `MISSION.md`. It is the compass for one related
learning goal, not a course syllabus or evidence of ability. All paths below are
relative to the user-authorized learning root, never to the skill installation or
current target repository.

## Format: schema version 1

```markdown
---
schema_version: 1
workspace_id: csv-reporting
mission_revision: 1
confirmed_on: 2026-10-19
---
# Mission: Trustworthy CSV summaries

## Why
I need to prepare a weekly customer summary without miscounting repeated rows.

## Success looks like
- SC1: Given a small export, identify duplicate records and explain the key used.
- SC2: Produce a summary with one contribution per customer and justify its count.

## Constraints and preferences
- Offline examples; no subscriptions or production customer data.
- Prefer short written exercises and text descriptions of diagrams.

## Out of scope
- Database deployment and production data cleanup.
```

Required frontmatter: integer `schema_version: 1`; stable local slug
`workspace_id`; positive integer `mission_revision`; actual date `confirmed_on`
(`YYYY-MM-DD`). Use the actual session date, not the example's date. Required
sections: Why, Success looks like, Constraints and preferences, Out of scope.
Give success criteria stable IDs (`SC1`, `SC2`) so lessons and records can trace
back to them. Unknown constraints stay explicitly unknown, not invented.

## Create and revise

1. Confirm the root separately from the learning goal. Show the proposed mission
   and ask for approval when the user has not already approved that exact text.
   Until approval, keep it in chat; do not create `MISSION.md` or scaffolding.
2. After approval, write only the mission and any substantive requested lesson or
   resource entry. Authorizing a mission does not authorize network access or
   operations against a repository being studied.
3. When a goal changes, show the exact proposed change and what remains unchanged.
   A hypothetical interest, learner difficulty, or an out-of-scope lesson request
   is not confirmation. Keep the current mission in force while awaiting a reply.
4. After confirmation, increment the revision, retain unchanged criterion IDs,
   assign new IDs for new criteria, and write a linked `mission_change` record as
   defined in [learning state](learning-record-format.md). It records the old and
   new wording and approval evidence. Preserve the prior revision through that
   record; do not rewrite old lesson/record mission references to the new number.
5. Treat previous evidence as still historical evidence. Re-evaluate its relevance
   to the new criteria; mission revision does not confer or erase ability. For an
   unrelated mission, propose a separately authorized workspace instead of mixing
   the records.

Completion: the approved text, revision and confirmation source agree; every
changed/retired success criterion is accounted for in the change record. If one
of the writes fails, report the actual partial state and finish/repair only the
approved change; do not claim a synchronized revision that was not saved.

## Other persistent preferences

Keep mission-relevant preferences here unless a substantive existing preference
file already owns them. Do not create a general biography, global learner profile,
or unbounded scratchpad. Ask before persisting sensitive information. A request
to change teaching format can be recorded as a preference without inventing a new
mission; changes to the goal or success criteria follow confirmation above.
