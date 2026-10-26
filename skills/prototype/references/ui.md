# UI Prototype

Load when the deciding uncertainty is layout, information hierarchy or primary interaction. Build several **structurally different** variants of one screen on one comparison surface, switchable by URL parameter and a floating bar, so the user can flip between them in a browser and pick (or combine).

## 1. Plan the variants

Default to **three** variants; at least two, at most five (beyond five they stop being different and become noise). Write the plan in one line at the top of the comparison surface, for example: "Three variants of the incident dashboard, switchable via `?variant=`, in a scratch copy of the operations page."

Give each variant:

- a short key (`A`, `B`, `C`) and a name (`Dense comparison table`);
- a one-line **hypothesis**: what this structure bets on ("operators compare incidents side by side before acting").

Variants must differ in **layout, information hierarchy or primary affordance**: for example a dense comparison table, a task-first guided flow and a spatial overview. Recolours, copy changes and three slightly different card grids do not test different designs. If two drafts come out similar, redo one with an explicit constraint ("no card grid"). A shared header is fine; a shared layout defeats the point.

All variants use the **same representative synthetic data and the same task**, so differences stay interpretable.

## 2. Choose the comparison surface

A variant judged in a vacuum always looks fine; real header, sidebar, density and components expose problems. In order of preference:

1. **Scratch copy or read-only reproduction of the existing host page.** Reproduce its header, sidebar, density and component conventions in the scratch location and mount the variants where the new content would live. Never edit the live route, its layout or shared components to host the experiment.
2. **New scratch page,** only when no plausible host page exists. Say why.

Record the **realism tradeoff**: what the scratch copy omits compared with the real page (live data, auth state, real component behaviour).

**Runner.** Reuse the project's existing local runner (dev server, storybook, task-runner script) only when its actual configuration can serve the scratch surface without changing production configuration; cite the config file and script you read. Otherwise build a self-contained scratch HTML comparison that opens directly. Record the exact start or open instruction.

## 3. Wire the switcher

- **URL parameter.** `?variant=A` selects the variant. Missing or unknown keys fall back to the first variant. Switching updates the URL in place (`history.replaceState`, or the framework router's replace) so the selection is shareable and survives reload.
- **Floating bar.** Fixed at bottom centre with three parts: **previous** arrow, the **current key and name** (`B · Task-first flow`), **next** arrow. Arrows wrap around. Visually distinct from the design under test (high-contrast pill, shadow) so nobody mistakes it for part of the design.
- **Keyboard.** `←` and `→` cycle variants, except when focus is in an `input`, `textarea`, `select` or `[contenteditable]` element, so typing in a variant is never hijacked.
- **State on switch.** Show the UI state relevant to the question when switching (selected item, open panel, filter), so the user sees what each variant does with the same situation.
- **Interactions** are simulated and in memory. Anything that would mutate data calls a stub.

Plain-JS switcher for a self-contained comparison:

```html
<nav id="proto-switcher" style="position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#111;color:#fff;border-radius:999px;padding:6px 14px;box-shadow:0 4px 14px rgba(0,0,0,.3);z-index:9999">
  <button id="prev" aria-label="Previous variant">←</button>
  <span id="label"></span>
  <button id="next" aria-label="Next variant">→</button>
</nav>
<script>
const VARIANTS = [["A","Dense comparison table"],["B","Task-first flow"],["C","Spatial overview"]];
const keys = VARIANTS.map(v => v[0]);
function current() { const k = new URLSearchParams(location.search).get("variant"); return keys.includes(k) ? k : keys[0]; }
function show(k) {
  const url = new URL(location.href); url.searchParams.set("variant", k); history.replaceState(null, "", url);
  document.querySelectorAll("[data-variant]").forEach(el => { el.hidden = el.dataset.variant !== k; });
  document.getElementById("label").textContent = k + " · " + VARIANTS[keys.indexOf(k)][1];
}
function move(d) { const i = keys.indexOf(current()); show(keys[(i + d + keys.length) % keys.length]); }
document.getElementById("prev").onclick = () => move(-1);
document.getElementById("next").onclick = () => move(1);
document.addEventListener("keydown", e => {
  const t = e.target; if (t.closest("input,textarea,select,[contenteditable]")) return;
  if (e.key === "ArrowLeft") move(-1); if (e.key === "ArrowRight") move(1);
});
show(current());
</script>
```

Each variant is a sibling element with `data-variant="A"` and so on. In a framework scratch copy, implement the same behaviour with the framework's router and one shared switcher component in the scratch location.

## 4. Completion

Distinguishable hypotheses for every variant, working selection by URL, buttons and keys, reload stability, and browser evidence for each variant on the same task, or explicit `not observed` gaps. Do not declare a winner because one screenshot is prettier: compare every variant against the question. The interesting feedback is often a combination ("B's header with C's sidebar"); report it as such.

## Anti-patterns

- **Variants that differ only in colour or copy.** A tweak, not a prototype.
- **Too much shared code.** A shared layout component forces every variant into the same structure.
- **Wiring variants to real mutations.** The question is how it looks and flows, not whether the backend works.
- **Editing the live route to host variants.** Use a scratch copy; record what realism that costs.
- **Promoting the winning variant directly.** Prototype code was written without tests or error handling; implementation rewrites it properly as separate work.
