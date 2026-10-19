# Outcome coverage and recipient questions

Read when the recipient and needed outcomes are known, before drafting. The sender supplies the gap; the recipient supplies the domain answers.

## Build a complete outcome inventory

Give each requested decision or fact a stable ID, preserving the sender's meaning. For “decide whether to launch in June and how many support staff we need,” record both the launch decision and the staffing decision. Shared questions may support both, but each outcome must remain visible in the matrix.

For each outcome, ask what information this particular recipient can contribute. A finance reviewer may supply budget constraints, while an operations lead may supply staffing limits. Do not assume either can answer the other's questions. When an explicit input exceeds this recipient's expertise, still include a narrowly worded question accepting “unknown” or a source suggestion, and flag that limit for the sender. Do not resolve the gap yourself or silently change the audience.

## Question design

- Prioritize the decisions with the highest consequence or blocking effect. When the sender gives no ranking, use dependency and consequence visible in the supplied context, not a claimed sender preference.
- Ask one idea at a time. “What daily volume should we plan for, and what happens during a peak?” becomes a volume question and a separate peak-behavior question.
- Request facts as facts and decisions as decisions. Distinguish a recipient's recommendation from an established policy rather than presenting one as the other.
- Avoid leading assumptions. “Which checks, if any, must precede release?” leaves policy open; “Why must compliance approve every release?” invents policy.
- Use the recipient's vocabulary and define sender-specific jargon from supplied context. Avoid forcing a nontechnical audience to translate implementation details.
- Add a short explanation only when needed to make a useful answer possible. Avoid a paragraph of sender reasoning beneath every question.
- Keep answer stubs empty. Illustrative answers can bias discovery and must not masquerade as supplied facts.
- A final “anything else?” question is useful but cannot replace an explicit question for a named outcome.

## Sender-only matrix

Deliver this in the sender-facing chat, not in the recipient file. Use the final document's actual question IDs, not a draft numbering scheme.

| Outcome ID | Sender's needed decision or fact | Question IDs | Coverage / expertise limit |
| --- | --- | --- | --- |
| D1 | Each named outcome in the sender's terms | Q1, Q3 | How these questions support it; note any expertise limit |

One row per outcome. Coverage means that a recipient could respond to an explicit question relevant to this outcome; it does not mean the outcome is resolved or that an answer will arrive. Keep sensitive sender rationale out of the recipient document unless the sender supplied it for that audience.

### Worked design example — not recipient answers

Synthetic sender: Kai, a product lead. Recipient: Morgan, the warehouse operations lead, familiar with daily dispatch but not software architecture. Needed outcomes: choose a dispatch cut-off; identify which packing events must be recorded; learn the usual daily parcel count. No deadline or effort estimate was supplied.

Candidate questions, in importance order:

- **Q1:** What is the latest order cut-off that the warehouse can reliably support for same-day dispatch?
- **Q2:** Which packing events need a record for your team to trace a parcel?
- **Q3:** How many parcels does the warehouse typically dispatch in a day?
- **Q4:** What else should we know before choosing these dispatch requirements?

Each gets its own empty answer stub in the recipient document. The framing identifies Kai and Morgan, explains the dispatch-requirements purpose, and states that answers will inform the cut-off and recording requirements. The recipient instructions allow partial and uncertain replies. Unknown deadline and effort are omitted, not guessed as “Friday” or “five minutes.”

The separate sender-facing coverage is:

| Outcome ID | Sender's needed decision or fact | Question IDs | Coverage / expertise limit |
| --- | --- | --- | --- |
| D1 | Choose a dispatch cut-off | Q1 | Asks operations for a supportable boundary; no boundary assumed |
| D2 | Identify packing events to record | Q2 | Asks for operational traceability needs, not a database schema |
| D3 | Learn the usual daily parcel count | Q3 | Requests the missing quantity; no invented volume |

Q4 is a catch-all, not a coverage shortcut. These are authored design examples, not evidence of a recipient response or an exercised agent run.
