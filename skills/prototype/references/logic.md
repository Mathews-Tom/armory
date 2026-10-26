# Logic Prototype

Load when the deciding uncertainty is business logic, legal transitions or data shape: the kind of thing that looks reasonable on paper and only feels wrong when pushed through real cases. The artifact is **one self-contained HTML file** anyone can open by double-clicking, including a designer, product manager or domain expert who never reads code.

## Shape of the file

All HTML, CSS and JavaScript inline. No server, framework, bundler, remote font, CDN or installation; opening the file is the whole setup, and it survives being emailed. Lay it out top to bottom:

1. **Title, question and assumptions.** The one-sentence question from SKILL.md step 1 and the assumptions, in visible text (not a comment), in domain language.
2. **Current state panel.** Every piece of state relevant to the question, as labelled fields in domain language ("Refunded amount: €40 of €100"), re-rendered after every action. Call out what just changed. When an action is rejected, show the rejection and its reason in the panel. A raw JSON dump alone is not enough.
3. **Free play.** One button per relevant action, always visible, usable in any order, plus a **Reset** button. Illegal actions stay clickable: the point is to see why the model rejects them, not to hide the disputed transition.
4. **Guided scenarios,** one per tab. Each tab holds a plain-language description (the situation and what to watch for), the **expected observation**, and the ordered steps as real buttons: clicking a step performs that action and advances to the next. Starting a scenario resets to a known initial state so it runs the same way every time.

Scenarios must cover at least:

- the normal path;
- the awkward ordering or edge case the question is about;
- an attempted illegal action.

State which scenario distinguishes the competing answers.

**Free play during a scenario.** A free-play action taken while a guided scenario is in progress interrupts it: the step list shows "Interrupted — restart scenario", its step buttons stop advancing, and restarting the scenario resets to its known initial state. Reset always clears scenario progress. This keeps every guided run reproducible.

Completion is one openable file covering every stated scenario, not several disconnected demos and not a static diagram.

**Competing rules.** When the competing answers are rival rules, implement each as its own model and drive them with the same actions: side by side (preferred, so one click shows the divergence) or behind a policy selector that resets state when switched. Label each model with whose position it represents.

## Separate the decision logic from the page

Put the logic that answers the question in its own `<script>` section as a small pure model, and keep the page a thin shell that calls into it. Nothing flows the other way: the model never touches `document`, the DOM or event handlers. This makes the rule inspectable on its own and easy to discuss. It is **not** an invitation to copy the model into production; the verdict feeds separate implementation work.

Pick the shape that fits the question, not the one easiest to wire:

| Shape | Fits when |
|---|---|
| Pure reducer `(state, action) => { state, rejected? }` | Actions are discrete events and state is one value |
| Explicit state machine (states plus allowed transitions) | "Which actions are legal right now" is part of the question |
| Small set of pure functions over plain data | No implicit current state, only transformations |

## Skeleton

Adapt names and labels to the domain. Keep the structure: model, render, free play, scenarios.

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Prototype: QUESTION</title>
<style>
  body{font:15px/1.5 system-ui,sans-serif;max-width:56rem;margin:2rem auto;padding:0 1rem;color:#1f2933}
  .panel{border:1px solid #cbd5e1;border-radius:8px;padding:1rem;margin:1rem 0}
  .changed{background:#ecfdf5}.rejected{color:#b91c1c}
  button{margin:.2rem;padding:.35rem .8rem}.tabs button[aria-selected=true]{font-weight:700;border-bottom:2px solid #047857}
</style></head>
<body>
<h1>QUESTION</h1><p id="assumptions">Assumptions: …</p>
<section class="panel" id="state" aria-live="polite"></section>
<section class="panel"><h2>Free play</h2><div id="actions"></div><button id="reset">Reset</button></section>
<section class="panel"><h2>Guided scenarios</h2><div class="tabs" id="tabs"></div><div id="scenario"></div></section>
<script>
// ---- Model: pure, no DOM ----
const initial = () => ({ status: "Paid", refunded: 0, total: 100 });
function step(state, action) {
  if (action.type === "refund") {
    if (state.refunded + action.amount > state.total)
      return { state, rejected: "Refund would exceed the amount paid" };
    return { state: { ...state, refunded: state.refunded + action.amount } };
  }
  return { state, rejected: "Unknown action" };
}
// ---- Page shell ----
let current = initial(), last = null;
const ACTIONS = [{ label: "Refund €40", action: { type: "refund", amount: 40 } }];
const SCENARIOS = [
  { name: "Normal refund", about: "One partial refund.", expect: "Refunded shows €40 of €100.",
    steps: [ACTIONS[0]] },
];
function dispatch(a) { const prev = current; const r = step(current, a.action);
  current = r.state; last = { label: a.label, rejected: r.rejected, prev }; render(); }
function render() { /* labelled fields; mark changed ones with .changed; show last.rejected with .rejected */ }
// build free-play buttons, reset, tabs; starting a tab sets current = initial() then shows step buttons in order
</script>
</body></html>
```

The `render`, button and tab wiring are left as comments in the skeleton only; the delivered file implements all of them.

## Style

Clean typography, generous spacing, one accent colour. No animation or decoration that competes with the state panel and the buttons.

## Anti-patterns

- **Tests for the prototype.** A prototype that needs tests is no longer a prototype.
- **Real database or persistence.** In-memory state unless persistence is the question, and then disposable scratch storage only.
- **Generalising.** No "what if we later support X". One question.
- **Logic blurred into the page.** If the model references `document` or handlers, the rule is no longer inspectable on its own.
- **Framework, bundler or server.** One file the recipient double-clicks.
- **Hidden illegal actions.** Disabling the disputed button hides the very behaviour under test; let it be clicked and show the rejection.
