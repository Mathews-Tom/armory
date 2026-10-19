# Worked two-session transition

This is authored **synthetic example data**, not an exercised learner session or
proof of skill effectiveness. It illustrates the state schema and a decision that
changes because of evidence. The complete example below is usable on its own.
The source repository also contains equivalent evaluation inputs at
`evals/fixtures/two-session.yaml`; that source-only fixture is excluded from
installed packages and is not needed to follow this example. Neither the example
nor the fixture is an operational workspace or authorizes writes to its directory.

## Starting authority and mission

The learner explicitly selects a dedicated workspace outside the repository being
studied and approves the mission text from the [mission format](mission-format.md).
Its ID is `csv-reporting`, revision 1. SC1 concerns customer keys; SC2 concerns a
summary with one contribution per customer. No network or actual customer data is
needed. In a real invocation, resolve the actual user-provided root; there is no
built-in default root.

## Session S01: claims, an error and coverage are different

Learner: “I use GROUP BY already, but I am unsure how repeated customer rows affect
the weekly count.” Save the claim, not an invented demonstration:

```markdown
---
schema_version: 1
id: LR-0001
kind: observation
recorded_on: 2026-10-19
session_id: S01
mission_revision: 1
concept_id: aggregation
scope: Building a weekly one-per-customer summary
evidence_kind: self_reported
result: not_assessed
status: active
supersedes: []
superseded_by: null
misconception_id: null
misconception_state: none
lesson_id: null
---
# Claimed grouping experience

## Evidence
Task/criterion: Not assessed.
Reported response: "I use GROUP BY already."
Source: Learner statement in S01; claimed practical familiarity, depth untested.
Support: No work inspected.

## Feedback and implications
Do not require a full beginner grouping lesson solely because evidence is absent;
use a small mission-linked diagnostic once customer identity is clear.

## Next decision
Diagnose customer-key selection first because the learner reported uncertainty;
aggregation remains self-reported only.
```

Deliver `lessons/0001-customer-keys.md` (L-0001) using the
[lesson format's complete example](lesson-format.md). The learner answers its
three-row task: “Three customers; each row is another customer.” Save
`learning-records/0002-duplicate-key-attempt.md` using the
[complete incorrect-attempt record](learning-record-format.md). It identifies
MC-01, result incorrect, and no hints. Explain why the correct count is two and
invite a fresh example. That explanation is **coverage**, not a corrected belief.
No extra glossary, resources, assets or scratchpad is needed.

State after S01:

| Concept / scope | Evidence state | Consequence |
| --- | --- | --- |
| duplicate-key-selection, three-row export | LR-0002: inspected incorrect attempt; MC-01 open; L-0001 covered the explanation | Needs practice; correction unconfirmed |
| aggregation, weekly summary | LR-0001: self-report; no work inspected | Do not claim demonstrated grouping ability |
| window-functions | No lesson, report or attempt | Unknown, not a failed prerequisite |

Next decision: a changed customer-key task before aggregation. Rationale: MC-01
blocks SC1 and SC2. Merely advancing to GROUP BY because the explanation was
shown would be a false transition.

## Session S02: resume, retrieve, correct and change the next task

Synthetic date: 2026-10-22. The learner explicitly resumes the same authorized
root. Read its mission, L-0001 and record metadata/history; a new conversation does
not turn the prior claim into a demonstration.

Because the relevant concept was introduced in S01, offer a short recall attempt
without notes, with an optional hint. Use a changed export: (C,5), (D,7), (C,11),
(E,2), where the first value is customer_id. Ask for the customer count and key,
and why the second C does not add a customer. The learner answers without hints:
“Three customers: C, D and E. customer_id is the key; both C rows belong to the same
customer.” Save `learning-records/0003-customer-key-correction.md`:

```markdown
---
schema_version: 1
id: LR-0003
kind: observation
recorded_on: 2026-10-22
session_id: S02
mission_revision: 1
concept_id: duplicate-key-selection
scope: Customer identity in a changed four-row CSV export
evidence_kind: demonstrated
result: correct
status: active
supersedes: [LR-0002]
superseded_by: null
misconception_id: MC-01
misconception_state: corrected
lesson_id: L-0001
---
# Applied the customer key on a fresh export

## Evidence
Task: Count customers in (C,5), (D,7), (C,11), (E,2); explain repeated C.
Criterion: Three customers; customer_id key; both C rows are one customer.
Observed response: "Three customers: C, D and E. customer_id is the key; both C
rows belong to the same customer."
Source: Learner response to the changed S02 task.
Support: Task visible; no notes or hints used, as observed in this synthetic input.

## Feedback and implications
The response satisfies every part of the criterion and addresses the row-equals-
customer claim in LR-0002. This supports customer-key selection on these examples,
not every data contract or durable mastery. Revisit later in a summary task.

## Next decision
Move to a small aggregation diagnostic for SC2 because MC-01 is addressed and
LR-0001's grouping claim remains unobserved. Require one contribution per customer
on a new export, plus an explanation of the selected contribution rule.
```

Then edit only LR-0002's metadata to `status: superseded` and
`superseded_by: LR-0003`. Its wrong answer and feedback remain unchanged. LR-0001
stays active and self-reported. Do not revise the mission; evidence changed, not
the learner's goal.

State after S02:

| Concept / scope | Evidence state | Consequence |
| --- | --- | --- |
| duplicate-key-selection, observed examples | LR-0003 correct without hints; LR-0002 preserved as superseded; MC-01 corrected in this scope | Proceed with scoped evidence, retain later revisit opportunity |
| aggregation, weekly summary | LR-0001 still self-reported, not demonstrated | Next lesson is a diagnostic, not an assumed advanced exercise |
| window-functions | Still unknown | No change inferred from unrelated success |

The next lesson changes from **repair customer identity** to **diagnose
aggregation**. A substantive L-0002 could ask the learner to select each customer's
latest invoice using a supplied date rule and then sum those selected amounts.
This interleaves the now-introduced key distinction with grouping because the
summary task needs both. Explain the selection rule first if it is new. Its
delivery records coverage only; wait for the learner's actual work before adding
a demonstration. A suggested revisit at the next weekly-summary attempt reflects
the mission's opportunity, not a measured retention effect.

## Counterfactuals that prevent false progress

- If S02 only says “I understand now,” record self-report; MC-01 remains unresolved
  and the next task stays a changed customer-key attempt.
- If the agent supplies the three-customer answer, that is coverage, not LR-0003.
- If the learner used the answer key, retain that support and avoid claiming an
  unaided correction; choose a fresh task if independent application matters.
- If a later task repeats the error, add a new open event and adapt the next
  lesson. Do not erase the earlier correct attempt or call either one mastery.
- If the root is absent, a target-repository path, or an escaping symlink, keep
  these proposed contents in chat; the example never grants write authority.
