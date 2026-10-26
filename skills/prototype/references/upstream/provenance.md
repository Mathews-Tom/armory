# Prototype provenance

## Source

- Repository: https://github.com/mattpocock/skills
- Commit read: `5beb35b040e3de97e54fa9e386d7e42d15c295c2` (fresh clone, 2026-10-26).
- Sources: `skills/engineering/prototype/SKILL.md`, `skills/engineering/prototype/LOGIC.md` and `skills/engineering/prototype/UI.md`.
- Source tree: https://github.com/mattpocock/skills/tree/5beb35b040e3de97e54fa9e386d7e42d15c295c2/skills/engineering/prototype
- Delta against the earlier pin `49dd158d1076134a641b33efb035946536778336`, which decision-map 1.1.0 adapted: `git diff --stat 49dd158 5beb35b -- skills/engineering/prototype` is empty, so the source files are byte-identical. No upstream changes needed accepting or omitting.
- License: MIT, Copyright (c) 2026 Matt Pocock. The verbatim notice is this package's `LICENSE` (compared byte-for-byte with upstream's `LICENSE` using `cmp`).

## Lineage

This package's artifact-building protocol first shipped inside `decision-map` 1.1.0 (`references/prototyping.md`, sections 1–4, with a separate prototype provenance record). Decision-map 2.0.0 moved that protocol here and kept only its ticket wrapper (claim precondition, HITL verdict ownership, evidence record, unresolved path, frontier recompute). The adaptation record below carries forward decision-map's prototype provenance and extends it for standalone use.

### Reversal of the earlier no-package decision

The 2026-10-19 skill-enhancement plan (Armory's local planning notes) listed "no ... prototype ... package" among its boundaries and embedded prototyping in decision-map instead. This package reverses that decision because:

- decision-map's prototyping reference is reachable only after a decision-ticket claim, and decision-map's description excludes general UI generation, so a plain "prototype this" or "try a few UI variants" request had no route to the protocol;
- upstream's own wayfinder workflow calls prototype as a separate skill, so a standalone package matches the source's structure;
- decision-map now delegates artifact building to this package by name, so the protocol has one authoritative home rather than two copies.

## What was vendored

| Upstream | Armory |
|---|---|
| `prototype/SKILL.md` (pick a branch, rules for both) | `SKILL.md` steps 1–2, authority boundaries |
| `prototype/LOGIC.md` | `references/logic.md` |
| `prototype/UI.md` | `references/ui.md` |

## What was adapted

Carried forward from decision-map 1.1.0:

- Question-first branching between logic/state and UI, with the discriminator question and a disclosed assumption when the user is unavailable.
- One self-contained shareable logic HTML with a readable domain-language state panel, free play with reset, and tabbed guided scenarios including an illegal action; inspectable rejected actions rather than hidden ones.
- Structurally different UI variants (default three, two to five) on one comparison surface with `?variant=`, a floating previous/name/next switcher, typing-safe keyboard cycling and reload-stable selection.
- Assumed repository paths and commands replaced by discovery of actual scratch conventions, routing and runner configuration, recorded with their source.
- Synthetic in-memory data; no production database, credentials, persistence, live mutations or dependency installation.
- Actual browser observation of the generated artifact before any empirical verdict; explicit `not observed` labels when prerequisites are missing; production behaviour, accessibility and real-user preference kept as inferred or untested.

New in this package:

- **Standalone output** (question, competing answers, assumptions, artifact pointer, per-scenario/variant evidence, verdict, `inconclusive` or `awaiting human judgment`) so the package works without a decision map, and so decision-map can record the same block as ticket evidence.
- **Host realism without production edits.** Upstream mounts variants on the existing production route (its preferred sub-shape A). Here variants live in a scratch copy or read-only reproduction of the host page, and the realism given up is recorded.
- **Capture only on request.** Upstream always commits the prototype to a throwaway branch and links it from the implementation issue. Here a throwaway-branch commit happens only when the user explicitly asks, never on main or the current feature branch.
- **No production lift.** Upstream folds the validated reducer or winning variant into the real code. Here prototype logic is never extracted or promoted; the verdict feeds separate implementation work. The logic/DOM separation is kept for inspectability, not reuse.
- Plain-JS switcher and logic skeleton added so a self-contained comparison or demo needs no framework.

## What was skipped

- `agents/openai.yaml` (non-Armory harness metadata).
- Production-route hosting, the `NODE_ENV` production gate it requires, winner promotion and folding prototype code into production.
- Unconditional throwaway-branch capture and issue context pointers.
- Dependency installation and project task-runner additions for the prototype.

## Re-sync policy

Manual only. Do not auto-sync. Compare upstream changes against `5beb35b040e3de97e54fa9e386d7e42d15c295c2` for the three source files, review them against the scratch-only, observation-before-verdict and no-production-lift boundaries recorded here, record the new pin with accepted and omitted changes, and run Armory validation before adopting anything. Decision-map's original wayfinder provenance is a separate lineage and is not affected by changes here.
