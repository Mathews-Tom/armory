# Design It Twice

Load in design mode, after framing the problem space. Based on Ousterhout's "design it twice": the first idea is unlikely to be the best, so produce several radically different interfaces and compare them before choosing. Uses the terms in `references/vocabulary.md` and the categories in `references/deepening.md`.

## 1. Show the problem frame, then start immediately

Present the user-facing frame from design-mode step 2 (constraints, dependencies and their category, an illustrative sketch). Do not wait for a reply: start the designs straight away while the user reads.

## 2. Write one technical brief per design

The brief is separate from the user-facing frame. Each brief contains:

- the module's file paths, its callers and the coupling between them;
- the dependency category and what would sit behind the seam;
- the architecture glossary terms (module, interface, implementation, depth, seam, adapter, leverage, locality) with one-line definitions pasted from `references/vocabulary.md`, because a sub-agent cannot be assumed to read this package;
- the relevant domain terms from `CONTEXT.md` / `CONTEXT-MAP.md`, so every design names things in the project's language;
- **one distinct design constraint**:

| Design | Constraint |
|---|---|
| 1 | Minimize the interface: aim for 1–3 entry points. Maximize leverage per entry point. |
| 2 | Maximize flexibility: support many use cases and extension. |
| 3 | Optimize for the most common caller: make the default case trivial. |
| 4 (when a dependency crosses a seam) | Design around ports & adapters for the cross-seam dependencies. |

Each brief instructs: read-only, no file edits, return only the five-part output below.

## 3. Produce the designs

**With sub-agents:** spawn at least three in parallel, one per brief. Each must return a radically different interface; if two come back near-identical, rerun one with an explicit instruction to avoid the other's shape.

**Sequential fallback (no sub-agent support):** write the designs yourself, one per brief, in order. Finish each design completely before starting the next, and do not revise an earlier design after writing a later one; the point is independent attempts, not one design polished three times. Label the output "designed sequentially (no sub-agents)".

Each design has exactly five parts:

1. **Interface**: types, entry points and parameters, plus invariants, ordering constraints and error modes.
2. **Usage example**: how a typical caller uses it.
3. **What the implementation hides** behind the seam.
4. **Dependency strategy and adapters**: which category, where the seam sits, which adapters exist (production, test) and why each is justified.
5. **Trade-offs**: where leverage is high and where it is thin.

## 4. Present and compare

Present the designs one after another so the user can absorb each. Then compare them in prose on three axes:

- **Depth**: leverage at the interface.
- **Locality**: where change and bugs would concentrate.
- **Seam placement**: where the seam sits and whether its adapters are real.

## 5. Recommend

Say which design is strongest and why. If elements from different designs combine well, propose the hybrid explicitly ("Design 1's single entry point with Design 4's port for the billing gateway"). Be opinionated; a neutral menu is not a recommendation.

Then return to the interaction contract in `SKILL.md`: one question at a time until the user agrees or rejects a shape.
