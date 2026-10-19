# Prototype Decision Evidence

A prototype is throwaway evidence for **one ticket's question**, not a product deliverable. Enter only after ownership and the session claim are verified. Preserve the selected local or GitHub backend and the ticket's authoritative interaction label; a HITL verdict belongs to the human. Chart mode creates questions, not prototypes.

## 1. Bound the question

Read the ticket and relevant surrounding code. Write the exact question, competing answers and the scenario or comparison that could distinguish them before coding. Put the question and assumptions visibly in the artifact as well. If it is too vague to choose a branch, ask one discriminator: **Are we testing what the state model permits, or how the interface presents it?** If the user is unavailable, choose only when the ticket/context supports a clear assumption and disclose it; otherwise record the missing clarification and use the unresolved outcome in step 5. A mixed question stays bounded to its deciding uncertainty; record newly independent questions as evidence for later ticketing, not extra experiments or a second ticket during an unresolved invocation.

Choose exactly one artifact strategy:

| Deciding uncertainty | Artifact | Completion evidence |
|---|---|---|
| Business logic, legal transitions, or representable data shapes | One self-contained shareable HTML file | Visible state changes through guided scenarios and free play |
| Layout, information hierarchy, or primary interaction | Multiple meaningfully different UI variants on one comparison surface | Comparable browser observations for every variant and a justified preference or unresolved verdict |

## 2. Establish a scratch boundary

Discover the repository's scratch/ignored-workspace convention, routing setup and relevant task-runner scripts from actual configuration before choosing a location or invocation. Record the chosen location and source of any run command. Use an explicitly named prototype artifact outside production paths and tracked implementation. If no safe project scratch location exists, use a dedicated temporary directory and report its limited lifetime. Keep a durable evidence summary in the selected ticket; do not imply a temporary path is a permanent archive.

Keep the artifact minimal and runnable, with in-memory synthetic state and representative, non-sensitive data. No production database, credentials, persistence, live mutations, dependency installation, branch or commit is part of this workflow. If the question requires persistence, restrict it to explicitly disposable scratch storage, state that boundary, and never connect production storage. A question that cannot be answered safely with these constraints stays open with its missing prerequisite recorded.

Experimental code stays scratch-only: no extraction into production, winner promotion, automatic cutover or promise that its logic is production-ready. Record the decision for later separately authorized implementation. Keep only structure and error handling needed for the experiment; avoid a framework, reusable architecture or test suite merely for the prototype.

## 3A. Logic and state: one shareable HTML

Use one HTML file containing all HTML/CSS/JavaScript inline: no server, framework, bundler, remote assets or installation. Opening the file must suffice. Keep the decision logic separate from DOM rendering in a small reducer, explicit transition function or similarly direct model; this is for inspectability, not production reuse.

The file contains all of:

- A visible question, assumptions and explanation in domain language a non-developer can use.
- A readable panel showing **all state relevant to the question**, refreshed after every action, with the change or rejected action explained. A raw JSON dump alone is insufficient.
- Free-play controls for each relevant action and a reset. Illegal actions must be inspectable: show why they are rejected rather than silently hiding the disputed transition.
- Tabbed guided scenarios with real step controls, a known-state reset on scenario start and expected observations. Cover the normal path, the question's awkward ordering/edge case and an attempted illegal action. State exactly which scenario distinguishes the competing answers.

Completion is one openable, shareable file covering every stated scenario, not several disconnected demos or a static diagram.

## 3B. UI: meaningfully different variants

Default to three variants (at least two, no more than five), each with a stated hypothesis. Differences must change layout, information hierarchy or primary affordance: for example, a dense comparison table, a task-first guided flow and a spatial overview. Recolors, copy changes or repeated card grids do not test different designs. Use the same representative data and task so differences remain interpretable.

Use one scratch comparison surface, with named variants selectable via `?variant=` and a visible floating previous/name/next switcher. Selection must survive reload and have a shareable URL; support keyboard switching without intercepting typing controls. Show relevant UI state on switches. Match realistic surrounding header/sidebar, density and component conventions using a scratch copy or read-only reproduction of an existing page when possible; use a new scratch page only when no plausible host exists and explain why. Never alter the live production route to host the experiment. Reuse an existing local runner only when its actual configuration supports the scratch surface; otherwise a self-contained scratch HTML comparison is sufficient. Record the exact start/open instructions.

Keep interactions simulated and in memory. Compare every variant against the same question; do not declare a winner merely because one screenshot is prettier. Completion includes distinguishable hypotheses, working selection and evidence for each variant, or explicit unobserved gaps.

## 4. Observe before concluding

When authorized browser tools are available, open the **actual generated artifact** and record its path/URL, variant or scenario, actions taken, visible before/after state and outcome. For logic, exercise every authored guided scenario, reset and relevant free-play action; for UI, inspect every variant, switch/reload behavior and the decision-relevant task at relevant viewport sizes. Record what was not exercised. Screenshots may supplement this record but cannot prove transitions that were not performed.

If browser access or a runnable prerequisite is missing, name it, hand over the artifact and sourced instructions, and label execution **not observed**. Source inspection, a proposed screenshot or a narrated walkthrough is not a browser observation. A browser demo establishes only what the synthetic prototype showed: production correctness, persistence, integration, performance, accessibility and real-user preference remain inferred or untested unless separately observed with appropriate evidence. Do not manufacture an empirical verdict from an unrun artifact.

## 5. Record one ticket's result and stop

Read `references/tracker-operations.md` and write the record as a GitHub issue comment or a local `## Evidence` append with every evidence line quoted. Preserve the original question and backend metadata: GitHub type/interaction labels stay outside the body, while local `Type:`, `Interaction:`, `Status:`, and `Blocked by:` headers remain required and unchanged for an unresolved result. Record:

- **Question and assumptions**: the single uncertainty tested and chosen branch.
- **Artifact pointer**: file or URL, start/open instructions, scenario/variant keys, and any scratch lifetime or access limit.
- **Evidence**: actual observations per scenario/variant, failures and missing prerequisites; separate source-based inferences and untested consequences.
- **Verdict**: the answer and its evidence, or `inconclusive`/`awaiting human judgment` with the precise unresolved point. For HITL, present the evidence and obtain the human's judgment before resolving.

Choose a closure path only when its conditions hold. Otherwise report `UNRESOLVED_WITH_EVIDENCE`: ticket `OPEN`, existing claim held, the precise missing human/browser/input prerequisite, and continuation on this same ticket. Preserve the claim comment or local lock and its original timestamp; pausing has no claim-release operation. Re-verify the existing claim before continuing when the prerequisite arrives; the normal 24-hour default stale-claim/preemption rule still applies. Do not create or work a second ticket, close automatically, or add a resolution pointer for this unresolved outcome. After legitimate closure, put only a resolution pointer in the parent map. For either outcome recompute frontier/state and stop: an empty frontier with the claimed open ticket is `WAITING` (other actionable tickets retain `ACTIVE`), never false completion. Retain the scratch artifact long enough for the stated handoff; do not delete the sole evidence while claiming it remains available.

## Adaptation boundary

Adapted from Matt Pocock's `prototype/SKILL.md`, `LOGIC.md` and `UI.md` at [49dd158d1076134a641b33efb035946536778336](https://github.com/mattpocock/skills/tree/49dd158d1076134a641b33efb035946536778336/skills/engineering/prototype). Question-first branching, shareable state demos and structural UI comparison are retained. Upstream's adjacent production routes, logic extraction, winner adoption and throwaway-branch/commit capture are deliberately replaced by scratch-only artifacts and decision-ticket evidence. Existing wayfinder attribution remains separate; package-local provenance governs deliberate manual resync, not automatic upstream synchronization.

For attribution details or a deliberate upstream comparison, read `references/upstream/prototype-provenance.md`; it records this source separately from the original wayfinder pin.
