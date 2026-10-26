# Prototype Tickets

A `decision-map:prototype` ticket is answered with throwaway evidence for **that ticket's question**, not a product deliverable. The `prototype` package builds and observes the artifact; this reference governs everything around it: preconditions, who owns the verdict, how the evidence is recorded, and how the invocation ends.

## 1. Preconditions

1. **The prototype package is available.** Before acquiring a claim on a prototype ticket, confirm the `prototype` package is installed. If it is absent, stop and report `BLOCKED: install prototype`: build nothing, leave the ticket untouched and take no claim. On a continuation where this session already holds the claim, keep the claim held and record the missing package as the pending prerequisite through the unresolved path in step 4.
2. **Ownership and claim are verified.** Enter only after visible ownership and the session claim are verified (`references/claim-protocol.md`). Chart mode creates questions, not prototypes.
3. **Backend and authority are preserved.** Keep the selected local or GitHub backend and the ticket's authoritative interaction label. A HITL verdict belongs to the human; an AFK verdict may be given by the agent only on observed evidence.

## 2. Build the artifact with the prototype package

Hand the `prototype` package:

- the ticket's question, verbatim, as the question to bound;
- the ticket's context and any linked evidence;
- for HITL tickets, that the verdict is reserved for a human, so it reports `awaiting human judgment` instead of choosing.

Keep the experiment bounded to this ticket's deciding uncertainty. Record newly independent questions it raises as evidence for later ticketing, not as extra experiments or a second ticket in this invocation. Decision-map work never creates a branch or commit, so do not ask the prototype package to keep the artifact in git. If the prototype package returns `inconclusive` because the question is too vague and the owner is unreachable, record the exact clarification needed through the unresolved path.

Keep the scratch artifact long enough for the stated handoff; do not delete the sole evidence while claiming it remains available.

## 3. Record the evidence on the ticket

Read `references/tracker-operations.md` and write the record as a GitHub issue comment or a local `## Evidence` append with every evidence line quoted. Preserve the original question and backend metadata: GitHub type/interaction labels stay outside the body, while local `Type:`, `Interaction:`, `Status:`, and `Blocked by:` headers remain required and unchanged for an unresolved result. Map the prototype package's output into:

- **Question and assumptions**: the single uncertainty tested and the chosen branch (logic or UI).
- **Artifact pointer**: file or URL, start/open instructions, scenario/variant keys, and any scratch lifetime or access limit.
- **Evidence**: actual observations per scenario/variant, items marked not observed, failures and missing prerequisites; source-based inferences and untested consequences kept separate.
- **Verdict**: the answer and its evidence, or `inconclusive` / `awaiting human judgment` with the precise unresolved point. For HITL, present the evidence and obtain the human's judgment before resolving.

An artifact alone does not justify closure.

## 4. Choose the outcome

Choose a closure path only when all of these hold: the prototype package's evidence covers every observation it requires (logic: every guided scenario, the reset and the question-relevant free-play actions; UI: every variant, switching, reload and the decision-relevant task) with no `not observed` item among them; its verdict is an answer, not `inconclusive`; and the verdict comes from the right authority (the human for HITL). Otherwise report `UNRESOLVED_WITH_EVIDENCE`: ticket `OPEN`, existing claim held, the precise missing human/browser/input prerequisite, and continuation on this same ticket. Preserve the claim comment or local lock and its original timestamp; pausing has no claim-release operation. Re-verify the existing claim before continuing when the prerequisite arrives; the normal 24-hour default stale-claim/preemption rule still applies. Do not create or work a second ticket, close automatically, or add a resolution pointer for this unresolved outcome. After legitimate closure, put only a resolution pointer in the parent map.

## 5. Recompute and stop

For either outcome recompute frontier and state with `frontier.py` and stop. An empty frontier with the claimed open ticket is `WAITING` (other actionable tickets retain `ACTIVE`), never false completion.
