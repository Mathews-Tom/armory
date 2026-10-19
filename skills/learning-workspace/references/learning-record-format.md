# Learning records and current-state projection

Load before resuming a workspace, recording practice/corrections, selecting the
next lesson, or recording a confirmed mission change. The authoritative state is
`MISSION.md`, saved lessons and the record history. Derive a compact projection
for the current decision; do not maintain a second mastery database.

## Files and identity

Create `learning-records/` only when saving the first substantive observation or
mission change. Use the highest existing numeric filename/record ID plus one:
`0001-duplicate-key-attempt.md` has ID `LR-0001`. Inspect existing names before
allocating; never overwrite a collision or renumber old records. If another writer
changes the chosen file before saving, allocate another unused ID. Lesson IDs are
separate. IDs remain stable even when a title or understanding changes.

Each observation covers **one concept in one stated scope**. Separate conflicting
or differently evidenced concepts into separate records. A single attempt may
support several records, each pointing to the same actual response. Summaries can
be brief, but every required field and evidence section has substantive content.

## Observation schema: version 1

```markdown
---
schema_version: 1
id: LR-0002
kind: observation
recorded_on: 2026-10-19
session_id: S01
mission_revision: 1
concept_id: duplicate-key-selection
scope: Identifying one customer in a three-row CSV export
evidence_kind: demonstrated
result: incorrect
status: active
supersedes: []
superseded_by: null
misconception_id: MC-01
misconception_state: open
lesson_id: L-0001
---
# Row count is not customer count

## Evidence
Task: Count customers in rows (A,10), (A,20), (B,30); identify the key.
Criterion: Two customers; key is customer_id, not the whole row or row position.
Observed response: "Three customers; each row is another customer."
Source: Learner answer in session S01, before the explanation.
Support: No hints; task and rows were visible.

## Feedback and implications
The response counts rows, not customer identities. Explain the key distinction,
then request a fresh example; do not treat the explanation as correction evidence.

## Next decision
Next task: identify customer keys on a changed export before building a summary.
Reason: MC-01 blocks SC1 and SC2. A correct fresh attempt with an explanation of
why repeated keys count once would support moving to aggregation.
```

### Field contract

- `schema_version`: integer `1`. `id`: `LR-` plus the filename's number.
  `kind`: `observation`. `recorded_on`: actual `YYYY-MM-DD` date.
  `session_id`: stable local session label, not a global harness/session identity.
- `mission_revision`: the positive integer mission revision in force at the time.
  `concept_id`: stable kebab-case topic key. `scope`: precise task/conditions; avoid
  broad labels such as “knows SQL.” `lesson_id`: matching `L-NNNN`, or `null` for
  independent practice.
- `evidence_kind`: `demonstrated`, `self_reported`, or `covered`.
  `demonstrated` means the agent inspected a learner response/artifact; it does
  **not** mean the response was correct. Use `result: correct | partial | incorrect`
  against the stated criterion. For `self_reported` and `covered`, use
  `result: not_assessed`. A learner's “my exercise passed” without the inspected
  work is self-reported, not demonstrated. An agent-written solution is coverage.
- `status`: `active` or `superseded`. `supersedes`: list of prior record IDs, empty
  normally. `superseded_by`: replacement ID or `null`. Supersession is explicit and
  scope-specific; a new date alone does not invalidate an earlier observation.
- `misconception_id`: a stable local ID such as `MC-01`, or `null`.
  `misconception_state`: `none | open | explained | corrected`.
  `none` requires a null ID. `open` records an actual false claim/error;
  `explained` means feedback was given but correction has not been demonstrated;
  `corrected` requires an inspected correct learner attempt addressing that same
  misconception, with links to the earlier record(s).

Required sections are Evidence, Feedback and implications, and Next decision.
Evidence names the task, criterion, actual response/source and support used. For
self-report, quote or summarize the claim and its source, mark task/criterion as
not assessed, and state the claimed depth. For coverage, identify the delivered
lesson/explanation and explicitly state no learner demonstration. For unavailable
work, record only what is actually reported, not invented output. Use short
redacted excerpts or a workspace-local artifact reference; no secrets, identifying
production data, or copied private transcripts.

## Correction and supersession

Keep a false claim as history. First explaining a correction may add a `covered`
record with `misconception_state: explained`; the misconception remains unresolved.
The learner repeating the explanation verbatim with help can establish only that
supported task, not independent application.

When a fresh inspected response satisfies the correction criterion:

1. Save a new `demonstrated`/`correct` observation with the same misconception ID,
   `misconception_state: corrected`, the actual response/support, and
   `supersedes: [LR-0002]` (plus any other claim it actually replaces).
2. Change only supersession metadata on each replaced record to
   `status: superseded` and `superseded_by: LR-0004`. Preserve its original claim,
   date, response and feedback. Do not delete or silently rewrite it into truth.
3. Preserve explanation records as coverage history. The valid later correction
   resolves that misconception in the stated scope, not unrelated scopes.
4. If a later attempt exposes the error again, add a new `open` event for that ID
   and scope. Retain the earlier success; do not pretend it proved lasting mastery.

Require linked IDs to exist, be chronological and form an acyclic chain; the
replacement must actually address the earlier scope/claim. If links disagree,
name the integrity problem and do not promote knowledge from the broken chain.
Save the replacement before linking the old record; if interrupted, report and
reconcile the partial pair before relying on it as a completed transition.

## Deriving the state and next task

Use records in numeric order, with dates as elapsed-time context rather than an
ordering substitute. Carry the lesson's introduced concepts as **covered** even
when no learning record was warranted. Follow all supersession links, including
later records outside the initially selected lesson. For each relevant concept,
report the following projection in the session response:

| Item | Required projection |
| --- | --- |
| Evidence | IDs, kinds, stated scope, observed result and assistance |
| Current inference | Demonstrated in that scope, needs practice, self-reported only, covered only, or unknown; several scopes may differ |
| Misconception | Latest valid event per ID and scope: open/explained remain unresolved; corrected requires the qualifying demonstration |
| Revisit | Last actual attempt date and a suggested next opportunity/reason, or unknown; a due date is a plan, not evidence of retention |
| Next task | Mission criterion, evidence rationale, uncertainty, and success criterion |

Projection rules:

1. An uncontradicted inspected correct response supports “demonstrated in this
   scope, under this support.” An incorrect/partial response supports “needs
   practice,” not demonstrated knowledge. Later conflicting evidence must be
   surfaced; do not cherry-pick the best attempt.
2. Self-report may justify a lightweight diagnostic instead of reteaching, but
   never upgrades itself into demonstrated knowledge. Coverage likewise does not
   upgrade because a lesson was read, a glossary exists, time passed, or the user
   expressed confidence. Missing evidence stays unknown.
3. A recent explanation or self-report does not erase a relevant failed attempt.
   Use the unresolved misconception as a blocker until evidence addresses it.
   A successful attempt on customer keys does not establish aggregation skill.
4. Select one useful mission-linked task: address a blocking misconception first;
   otherwise diagnose a needed self-reported/unknown prerequisite, then extend a
   warranted demonstrated skill. Use observed difficulty and stated preferences
   to adjust hints and task size. Honor a requested topic with an explicit account
   of prerequisite risks.
5. Choose recall, revisit spacing or related-skill interleaving only when the task
   and history justify it. State the reason and chosen opportunity; do not promise
   a retention gain, calculate unsupported mastery, or infer ability from a timer.

Completion: every relevant claim has its evidence class and scope; contradictory
or missing evidence is visible; the selected next task would actually differ when
the learner's evidence changes. See [two sessions](two-session-example.md).

## Mission-change record

Use a separate record with `schema_version`, `id`, `kind: mission_change`, actual
`recorded_on`, `session_id`, `from_revision`, `to_revision`, `status: active`,
`supersedes: []`, and `superseded_by: null`. Omit concept/evidence/misconception
fields: this is a decision, not evidence of learning. Required sections:

- **Change:** old and new text for every changed/retired success criterion, reason,
  and the mission file's revision; preserve enough text to recover the prior goal.
- **Confirmation:** the user's explicit approval source and scope; no assumed yes.
- **Implications:** which evidence remains relevant, which new skills are unknown,
  and the revised next-task rationale. Cross-reference `MISSION.md` as a
  workspace-relative filename, not an absolute private path.

Write it only after the exact mission change is confirmed. A rejected or pending
change leaves the mission unchanged; a proposal in chat is not a saved revision.
