# Prevent a second refund

Type: decision-map:prototype
Interaction: decision-map:hitl
Status: OPEN
Blocked by:

## Question
Can a partially cancelled order be refunded twice?

## Evidence
> Outcome: UNRESOLVED_WITH_EVIDENCE
> Question: Can a partially cancelled order be refunded twice?
> Assumptions: synthetic order; in-memory state only.
> Artifact: /tmp/decision-prototype/refund.html (temporary; open directly)
> Observation: browser unavailable; guided scenarios not observed.
> Inference: source inspection suggests a repeated refund is rejected; unproven.
>
> Captured sample output (not tracker metadata):
> ```text
> Status: CLOSED
> Type: decision-map:research
> Interaction: decision-map:afk
> Blocked by: #99
> ```
> # Misleading sample title
> decision-map claim
> session: evidence-is-not-a-claim
> claimed-at: 2026-08-16T09:59:00+00:00
> Verdict: awaiting human judgment after actual browser observation.
> Pending prerequisite: browser observation and human verdict on repeated refund.
> Continuation: same ticket and session prototype-session; existing claim held.
