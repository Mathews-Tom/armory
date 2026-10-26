---
name: prototype
description: 'Use when a design question is cheaper to answer by clicking a throwaway artifact than by debating it: whether a state model or business rule behaves right, or which of several structurally different UI layouts works. Builds one scratch-only artifact (a self-contained shareable state demo, or switchable UI variants), observes it in a browser and reports evidence with a verdict or "inconclusive". Production routes, data and code stay untouched. Triggers on: "prototype this", "throwaway prototype", "clickable state demo", "does this state model feel right", "try a few UI variants", "compare layouts before committing". NOT for working a decision-map ticket, use decision-map. NOT for finished HTML deliverables such as dashboards or infographics, use static-web-artifacts-builder. NOT for UX audits or redesigns, use ux-expert.'
metadata:
  version: 1.0.0
  category: development
  tags: [prototyping, throwaway, state-model, ui-variants, design-questions]
  difficulty: intermediate
  phase: define
  complements:
    - decision-map
    - ux-expert
---

# Prototype

A prototype is **throwaway code that answers one question**. The question decides the shape, the artifact lives in scratch space, and the answer comes from observing the artifact, not from reading its source. The verdict feeds separate implementation work; the prototype itself never becomes production code.

## When to Use

| Situation | Package |
|---|---|
| "Does this state model / rule / transition logic hold up?" | `prototype` (logic branch) |
| "What should this screen look like? Show me a few structurally different options" | `prototype` (UI branch) |
| Working a `decision-map:prototype` ticket (claim, ticket evidence, frontier) | `decision-map`, which builds the artifact with this package |
| A finished, polished HTML deliverable: dashboard, infographic, interactive diagram | `static-web-artifacts-builder` |
| Audit or redesign an existing page against UX criteria | `ux-expert` |

## Prerequisites and Authority

These boundaries hold in every branch:

- **Scratch only.** The artifact lives in a scratch location discovered from the repository (step 3), never in production paths or tracked implementation files.
- **No production-route edits.** To show a variant in its real surroundings, build a scratch copy or read-only reproduction of the host page and record the realism you gave up. Never modify a live route, layout or shared component to host the experiment.
- **Synthetic, in-memory data.** Representative, non-sensitive data held in memory. No production database, credentials, persistence, live mutations or dependency installation. If the question is about persistence itself, use explicitly disposable scratch storage, say so, and never connect production storage; if the question cannot be answered under these rules, stop and report the missing prerequisite.
- **No branch or commit by default.** Commit the prototype only if the user explicitly asks, and then only to a new throwaway branch (see Output).
- **Never lift prototype logic into production.** No extraction, winner promotion or automatic cutover. The verdict is input to separately authorized implementation work.
- **Browser before verdict.** An empirical verdict requires observing the actual artifact in a browser (any authorized browser automation or a browser the user drives and reports back from). Anything not exercised is labelled **not observed**.
- **Skip the polish.** Only the structure and error handling needed to run the experiment. No framework, reusable architecture or test suite for the prototype.

## Workflow

### 1. Bound the question

Read the request and the relevant surrounding code. Write down, before building anything:

- the exact question, in one sentence;
- the competing answers;
- the scenario or comparison that would distinguish them;
- the assumptions you are making.

These go visibly at the top of the artifact as well. Keep a mixed question bounded to its deciding uncertainty; list other questions it raises as follow-ups instead of prototyping them too.

**Check that the answers actually diverge.** Name at least one scenario where the competing answers predict different visible outcomes. If none exists (the positions are compatible, or one is too underspecified to predict an outcome), there is nothing for a prototype to distinguish: ask the clarifying question that would make them diverge ("When a hold arrives after a granted renewal, is that renewal revoked?") and build only once a diverging scenario exists. If the user is unavailable, stop with verdict `inconclusive` and that question; do not invent the missing rule.

**Complete when** the question, competing answers, at least one diverging scenario and the assumptions are written down.

### 2. Pick exactly one branch

| Deciding uncertainty | Branch | Reference |
|---|---|---|
| Business logic, legal transitions, representable data shapes | **Logic**: one self-contained shareable HTML file | `references/logic.md` |
| Layout, information hierarchy, primary interaction | **UI**: 3 structurally different variants (2–5) on one comparison surface | `references/ui.md` |

If the question is too vague to choose, ask one discriminator: **"Are we testing what the state model permits, or how the interface presents it?"** If the user is unavailable, choose only when the surrounding code clearly supports it (a backend module suggests logic; a page or component suggests UI) and state that assumption at the top of the artifact. Otherwise stop with verdict `inconclusive` and the exact clarification needed. Getting the branch wrong wastes the whole prototype.

### 3. Establish the scratch boundary

Discover where scratch work belongs from the repository's own configuration. Search the repository root (`git rev-parse --show-toplevel`, or the working directory outside git) and each directory between it and the code in question, never above the root, for, in this order: repository instructions (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`), ignored scratch directories in `.gitignore`, and for a UI branch the routing setup and task-runner scripts (`package.json` scripts, `Makefile`, `justfile`, `pyproject.toml`). A file that does not exist is skipped, not a blocker. Record the chosen location and the file that justified it. Name the artifact so a casual reader sees it is a prototype (include `prototype` in the file or directory name).

If no safe project scratch location exists, create a dedicated temporary directory (`mktemp -d`) and report that it is temporary.

**Complete when** the location, its source and its lifetime are recorded.

### 4. Build the artifact

Load the branch reference and follow it completely:

- Logic: read `references/logic.md`. It defines the single-file layout, the domain-language state panel, free play with reset, tabbed guided scenarios including an illegal action, and the separation of decision logic from the DOM.
- UI: read `references/ui.md`. It defines variant count and structural difference, the `?variant=` parameter, the floating previous/name/next switcher, keyboard cycling that ignores focused inputs, reload stability, and host-page realism without touching production.

### 5. Observe in a browser

Open the **actual generated artifact** and exercise it:

- Logic: run every guided scenario from its reset, the reset control itself, and every free-play action relevant to the question, including the illegal attempt.
- UI: view every variant, switch with the buttons and the arrow keys, reload on a non-default variant, and perform the decision-relevant task on each variant at the viewport sizes that matter.

For each scenario or variant record: artifact path or URL, the scenario or variant key, actions taken, visible before/after state, and outcome. Screenshots may supplement this record but cannot prove transitions that were not performed.

If browser access or another runnable prerequisite is missing, name it, hand over the artifact with its open/start instructions, and label every scenario or variant **not observed**. Source inspection, a narrated walkthrough or a proposed screenshot is not a browser observation. Even when observed, the prototype shows only what the synthetic artifact did: production correctness, persistence, integration, performance, accessibility and real-user preference stay inferred or untested.

### 6. Report and stop

Produce the Output below. Hand the verdict to whoever owns the next step (the user, or the calling `decision-map` ticket); do not start implementing it.

## Output

```text
Question: <one sentence>
Competing answers: <A> | <B>
Branch: logic | UI (reason)
Assumptions: <list>
Artifact: <absolute path or URL>; open/start: <exact instruction and its source>; location source: <config file>; lifetime: <scratch dir | temporary>
Evidence:
  - <scenario or variant key>: actions <...>; observed <before → after>; outcome <...>   (or: not observed — <missing prerequisite>)
Not observed: <scenarios/variants/viewports not exercised>
Inferred or untested: <production behaviour, persistence, accessibility, real-user preference, ...>
Verdict: <answer + the evidence that decides it> | inconclusive — <precise unresolved point> | awaiting human judgment — <what the human must decide>
Follow-up questions: <questions raised but not prototyped>
```

A verdict needs browser evidence for the distinguishing scenario or for every variant. Without it the verdict is `inconclusive`. When the user (or a calling ticket) reserves the judgment for a human, present the evidence and report `awaiting human judgment` instead of choosing.

**Keeping the prototype.** Only when the user explicitly asks to keep it in git: create a new throwaway branch (for example `prototype/<topic>`) from the current commit, commit only the prototype files there, switch back, and report the branch name. Never commit to the main or current feature branch.

## Error Handling

| Situation | Action |
|---|---|
| Question too vague and the user is unavailable | Stop before building; verdict `inconclusive` with the exact clarification needed |
| No browser access | Build if otherwise possible, give open instructions, mark everything `not observed`, verdict `inconclusive` |
| User asks to declare the result proven without observation | Decline; report `inconclusive` and the missing observation |
| Question requires production data, credentials or live persistence | Use disposable scratch storage only if that answers the question; otherwise stop with the missing prerequisite |
| Existing runner cannot serve a scratch surface without changing production config | Use a self-contained scratch HTML comparison and record the realism tradeoff |
| Building would require installing dependencies | Do not install; use plain HTML/CSS/JS |
| No ignored scratch location in the repository | Use `mktemp -d` and report the artifact as temporary |
| User asks to merge the prototype or wire it to production | Decline; the verdict feeds separate implementation work |

## References

| Load when | Reference | Supplies |
|---|---|---|
| Branch is logic | `references/logic.md` | Single-file layout, state panel, free play, guided scenarios, logic/DOM separation, skeleton |
| Branch is UI | `references/ui.md` | Variant rules, comparison surface, switcher behaviour, host realism, runner discovery |

For source attribution or a deliberate upstream comparison, read `references/upstream/provenance.md`. The MIT notice is in this package's `LICENSE`.
