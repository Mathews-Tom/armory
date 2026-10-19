# Domain language versus implementation decisions

Load when modeling raises a technical or architectural choice. Canonical vocabulary belongs in context files; mechanisms and their rationale belong outside those definitions. This skill can identify a qualified ADR candidate but does not author ADRs or create ADR directories.

## All-three candidate gate

A candidate exists only when every condition is supported by actual session/repository evidence:

| Condition | Required evidence |
| --- | --- |
| **Hard to reverse** | A concrete, meaningful cost of changing this particular decision later, such as migrating retained records and external consumers; “architecture is important” is not evidence. |
| **Surprising without context** | The reasonable expectation a future reader would have and why the selected approach differs without the missing context. Novel terminology alone is insufficient. |
| **Real trade-off chosen** | Genuine alternatives actually weighed, the selected alternative, and the specific reasons for accepting its costs over those alternatives. Merely listing hypothetical options or using the only permitted mechanism is insufficient. |

All three are conjunctive. A missing, false or unknown condition means **no ADR candidate**. Keep an ordinary implementation note in the response if useful; do not offer “a draft ADR anyway,” create a proposed ADR placeholder, or call a tentative choice a qualified candidate. Ask a missing factual question only when resolving it serves the current modeling scope, not to manufacture a candidate.

## Distinct outcomes

| Situation | Result |
| --- | --- |
| A canonical term is agreed | Capture its business meaning in its owning context; terminology agreement alone is not an ADR candidate. |
| Meaningful migration cost and a surprising choice, but no alternatives were weighed | No candidate: real trade-off is missing. |
| Meaningful migration cost and alternatives weighed, but the choice is unsurprising without context | No candidate: surprise is missing. |
| Surprising choice and alternatives weighed, but a local reversible setting changes it at negligible cost | No candidate: meaningful reversal cost is missing. |
| One or more conditions are unknown | No candidate; label missing evidence rather than filling it in. |
| All three have concrete evidence | Surface a candidate summary outside the vocabulary and offer an authorized adr-writer handoff. |

For example, the owner has selected immutable cancellation events over mutable order rows after weighing audit reconstruction against projection/storage cost; reversing the choice would require migrating years of retained records and external consumers, and a future reader would otherwise expect simple CRUD for a small ordering product. If those are actual confirmed facts, all three hold. If they are only suggestions made by the agent, the gate is not satisfied.

## Qualified handoff, not writing authority

Return only a candidate summary: decision/context, reversal cost, why it would surprise a future reader, actual alternatives and chosen trade-off, evidence sources and the existing ADR lookup route. Keep this in the conversation or authorized handoff, not in `Language` or a new ADR file. Do not allocate an ADR number, choose a template or write an ADR here.

The existing `adr-writer` capability is the authoring owner, under its own workflow and explicit writing authority. If it is not available or authority has not been granted, leave the qualified summary for the user/authorized owner. Finish all independently agreed vocabulary updates; missing ADR-writing authority is not a blocker for domain modeling. A request solely to write a specified ADR belongs to that capability rather than this skill.
