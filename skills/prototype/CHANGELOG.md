# Changelog

## 1.0.0 — 2026-10-26

- Add `prototype` as a standalone package, adapted from Matt Pocock's `prototype` skill at `5beb35b040e3de97e54fa9e386d7e42d15c295c2` and from decision-map 1.1.0's prototyping protocol.
- Logic branch: one self-contained shareable HTML with a domain-language state panel, free play, reset, tabbed guided scenarios including an illegal action, and decision logic separated from the DOM.
- UI branch: three structurally different variants by default (two to five) on one scratch comparison surface, `?variant=` selection, a floating previous/name/next switcher, typing-safe keyboard cycling and reload-stable selection.
- Scratch-only location discovered from repository config, no production-route edits, synthetic in-memory data, browser observation before any verdict, and `not observed` labels for anything unexercised.
- Standalone output with question, assumptions, artifact pointer, per-scenario/variant evidence and a verdict or `inconclusive`; throwaway-branch commit only on explicit request; no production lift.
