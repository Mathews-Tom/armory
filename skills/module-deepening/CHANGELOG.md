# Changelog

## 1.0.0 — 2026-10-26

- Add `module-deepening`, adapted from Matt Pocock's `improve-codebase-architecture` and `codebase-design` at `5beb35b040e3de97e54fa9e386d7e42d15c295c2`.
- Scan mode: scope by user direction or `git log` hot spots, read domain context and ADRs, apply the deletion test, classify dependencies, write an offline HTML report to the temp directory and ask which candidate to explore.
- Design mode: frame constraints and the dependency category, design the interface at least three ways (parallel sub-agents or a sequential fallback), compare by depth, locality and seam placement, and recommend one design or a hybrid.
- Both modes ask one question at a time, stop at an agreed decision, never edit code, and hand off to `domain-modeling`, `adr-writer` (only after the conjunctive ADR-candidate test), `codebase-advisor` or `/tdd`.
- Report uses inline CSS and inline SVG under a no-script Content-Security-Policy; no Tailwind or Mermaid CDN.
