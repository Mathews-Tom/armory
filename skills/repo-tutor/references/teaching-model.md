# Teaching Model

## Purpose

A repo tutor changes the learner's capabilities. After the lesson, the learner should be able to predict where work goes, trace one result, and plan a small change. Recognition of filenames or architecture labels is not enough.

## Curriculum Before Presentation

Build the curriculum in this order:

1. Define the learner's useful destination.
2. Select one representative user journey.
3. Identify the minimum concepts required to explain that journey.
4. Order those concepts by prerequisite.
5. Select one safe developer change that reuses the same concepts.
6. Add checks that make the learner retrieve, predict, trace, and plan.
7. Move secondary facts to the glossary or evidence appendix.

Do not derive lesson order from the repository tree, README headings, dependency graph clusters, or API listing.

## The Five-Part Lesson Grammar

Use all five parts for every core concept.

### 1. Analogy

Introduce responsibility with a familiar model. State where the analogy stops.

Good:

> Think of the request router as a receptionist: it identifies what the caller wants and sends the request to the responsible service. Unlike a receptionist, it also validates machine-readable input before dispatch.

Bad:

> The whole repository is a factory.

A broad metaphor that does not map named parts to real responsibilities decorates rather than teaches.

### 2. Plain Model

Use one or two short sentences. Use the repository's real domain nouns. Define a term before using it. Prefer verbs that describe transformation or responsibility: reads, validates, selects, stores, publishes.

### 3. Concrete Evidence

Show the smallest source fact that proves the plain model:

- a command registration;
- a public function or type;
- a configuration key;
- an interface plus one implementation;
- a focused test;
- a short documentation instruction clearly attributed as documentation.

Do not paste a full file or long README section. Explain why this evidence establishes the claim.

### 4. Why It Matters

Connect the concept to a learner decision:

- where to look when output is wrong;
- which boundary can reject input;
- what state survives restart;
- where an integration plugs in;
- which test protects a change.

### 5. Check Your Understanding

Use one of four exercise types and include a collapsible answer:

| Exercise | Prompt form | What it tests |
|---|---|---|
| Retrieve | “Which component owns X?” | Concept-location link |
| Predict | “What happens if Y is missing?” | Causal model |
| Trace | “Follow Z from entry to result.” | Workflow understanding |
| Plan | “Where would you change A, and what proves it?” | Transfer to engineering work |

A yes/no question or a question whose answer is visible in the same sentence does not count.

## Progressive Disclosure

Each concept has three linked layers.

| Layer | Learner need | Rule |
|---|---|---|
| Beginner | Form the minimum correct model | One responsibility, one reason, one visual or example |
| Deeper | Understand interaction and failure | Boundaries, state, alternatives, and one failure consequence |
| Code | Verify and transfer | Exact symbols, short excerpts, tests, configuration, evidence links |

The layers must explain the same concept. Do not make the beginner layer a marketing summary and the code layer a separate reference manual.

Default view: beginner. A global depth control may expand deeper/code material, but every control must remain keyboard-accessible and preserve reading order without JavaScript.

## The First Ninety Seconds

The Start Here page must answer these before introducing subsystem names:

1. What problem does the repository solve?
2. Who initiates the central action?
3. What does that actor provide?
4. What useful result returns?
5. What will the learner be able to do after the tour?

Use one “input → work → output” concept illustration. This is not the architecture diagram.

## The User Journey

Choose the primary supported path, not the largest or most novel surface. Prefer the repository's quickstart or dominant entry point only after cross-checking it against implementation.

Teach the journey in two passes:

1. **Outside view:** what the user does, sees, and can recover from.
2. **Inside view:** which responsibility accepts, transforms, stores, calls, and returns.

Include at least one failure path that a real user can encounter. Explain where it becomes visible and what evidence supports the recovery instruction.

Do not list every CLI command, endpoint, event, or integration. Secondary surfaces belong in a comparison table or evidence drawer labeled “Other ways in.”

## The Developer Journey

A first engineering change must be:

- permitted by current contribution/governance docs;
- narrow enough to explain end to end;
- grounded in an existing extension seam or local responsibility boundary;
- paired with the repository's real test and debugging surface;
- connected to concepts already taught in the user journey.

Before recommending it, inspect contribution guidance, roadmap freezes, deprecated modules, generated-file rules, and tests. If no safe example exists, state that and teach how to find one; never invent a contribution opportunity.

Teach the change as a prediction before showing files:

1. Ask the learner which responsibility should change.
2. Reveal the source location and interface.
3. Show the smallest edit shape conceptually, not a fabricated patch.
4. Identify the behavior that must remain invariant.
5. Show where the repository verifies that behavior.
6. Explain one debugging observation that distinguishes likely failure locations.

## Jargon Budget

For beginner text:

- introduce at most three new domain terms per section;
- define each term at first use;
- avoid unexplained acronyms;
- use one concept per paragraph;
- keep code excerpts subordinate to explanation;
- prefer a concrete example before a generalized rule.

Necessary technical vocabulary is not a failure. Undefined vocabulary and unnecessary synonyms are failures. Use one stable term for each concept.

## Analogy Safety Test

Before keeping an analogy, answer:

| Check | Pass condition |
|---|---|
| Mapping | Named analogy parts map to named system responsibilities |
| Limit | The lesson states at least one important difference |
| Prediction | The analogy helps predict a real workflow or failure |
| Removal | Removing it would make the concept harder, not merely less colorful |

Delete analogies that fail any check.

## Evidence as Teaching

A citation is not just provenance. Explain what the learner should notice in the evidence. Use short annotations such as:

- “This registration makes the command a user entry point.”
- “This interface is the extension seam; implementations can vary behind it.”
- “This test names the observable behavior that a change must preserve.”

Separate product behavior from project process. Roadmaps, research ledgers, benchmark reports, and decision records can explain why a design exists, but they do not prove the current runtime path.

## Practice Lab Design

Include at least four exercises:

1. one retrieval question from the system map;
2. one prediction about a failure or configuration change;
3. one end-to-end trace using the central journey;
4. one change-planning exercise using the safe extension seam.

Each answer must cite evidence and explain reasoning. Add a short “teach it back” prompt that asks the learner to explain the repository in three sentences: problem, path, extension point.

## Teaching Anti-Patterns

| Anti-pattern | Symptom | Correction |
|---|---|---|
| README karaoke | Page order and wording mirror README | Reorder around learner prerequisites and verify implementation anchors |
| Architecture first | Learner sees every component before knowing the useful result | Teach input/work/output first, then reveal internals along the journey |
| Flat inventory | Commands, folders, or classes receive equal visual weight | Primary path first; secondary surfaces in drawers |
| Jargon avalanche | Several undefined nouns appear in one paragraph | Apply jargon budget and introduce via concrete example |
| Code museum | Excerpts are displayed without a decision they support | Explain what the learner should notice and why it matters |
| False simplicity | Analogy contradicts state, concurrency, or failure behavior | State the analogy limit or remove it |
| False verification | Documented command is presented as run | Mark `Documented, not run` |
| Unsafe first change | Suggested work is broad, frozen, generated, or deprecated | Check governance and choose a smaller permitted seam |
| Quiz theater | Questions repeat visible wording | Use prediction, tracing, and transfer exercises |
| Graph as curriculum | Graph clusters define lesson order | Use graph only for discovery; order lessons by prerequisite |

## Completion Test

The curriculum passes only if a learner can answer, with evidence:

- what problem the system solves and for whom;
- how to obtain one useful result;
- what happens from action to result;
- which major responsibilities exist and why;
- where one realistic change belongs;
- how to test and debug that change;
- which claims are observed, inferred, or unknown.
