---
name: module-deepening
description: 'Use when looking for shallow modules worth deepening, deciding where a seam belongs, or designing a chosen module''s interface several ways before refactoring. Scan mode renders candidates as an offline HTML report; design mode compares alternative interfaces and recommends one. Asks one question at a time, stops at an agreed decision and never edits code. Triggers on: "find deepening opportunities", "shallow modules", "where should the seam go", "design it twice", "deepen this module", "make this testable through its interface", "AI-navigable codebase". NOT for scored multi-dimension architecture reviews, use architecture-reviewer. NOT for improvement plan backlogs, use codebase-advisor. NOT for local simplification, use code-refiner or /refactor. NOT for domain terminology, use domain-modeling.'
metadata:
  version: 1.0.1
  category: review
  tags: [architecture, deep-modules, seams, testability, interface-design]
  difficulty: advanced
  phase: review
  complements:
    - architecture-reviewer
    - domain-modeling
    - adr-writer
    - codebase-advisor
---

# Module Deepening

Find **deepening opportunities**, refactors that turn shallow modules into deep ones, and decide the shape of one deepened module with the user. A deep module puts a lot of behaviour behind a small interface at a clean seam, so callers get leverage, maintainers get locality, and tests cross the same interface callers do. The aims are testability and AI-navigability: an agent should be able to understand and safely change one concept by reading one module.

This skill decides. It does not implement. Every session ends at an agreed decision (or an explicit rejection) and hands implementation to separate work.

## When to Use

| Situation | Package |
|---|---|
| Find where shallow modules cause friction, or pick what to deepen next | `module-deepening` (scan) |
| Shape the interface of one chosen module, or decide where its seam goes | `module-deepening` (design) |
| Scored review across structure, scalability, security, performance, operations, data | `architecture-reviewer` |
| Prioritized, agent-executable implementation plans for a repository | `codebase-advisor` |
| Simplify a function or file without changing its interface | `code-refiner` or `/refactor` |
| A domain term is ambiguous or code contradicts the domain model | `domain-modeling` |
| Record a decision that already qualifies as an ADR | `adr-writer` |

## Prerequisites and Authority

- **Read-only.** Read code, docs and git history. Never edit source, tests, configuration, `CONTEXT.md` or ADRs. The only file this skill writes is the scan report, and it goes to the OS temp directory, never into the repository.
- **Vocabulary.** Before either mode, read `references/vocabulary.md`. Use its terms exactly (module, interface, implementation, depth, deep, shallow, seam, adapter, leverage, locality) in every question, card and recommendation. Do not drift into "component", "service", "API" or "boundary".
- **Domain language.** Read the project's domain context: `docs/agents/domain.md` when present (it routes to the authoritative files), then `CONTEXT.md` or `CONTEXT-MAP.md` and the context-local `CONTEXT.md` for the area in scope. Name modules after those concepts: "the Order intake module", not "the FooBarHandler" and not "the Order service". If no domain context exists, say so once and use the names the code already uses.
- **Decisions already made.** Read ADRs that touch the area, following the lookup route in `docs/agents/domain.md` or the repository's existing ADR directory. Do not re-litigate them unless the friction is real enough to warrant reopening (see the report's ADR callout rule).
- **Sub-agents.** Exploration and design-it-twice use sub-agents when the harness provides them (for example Claude Code's Task tool with a read-only exploration agent). Without them, follow each reference's sequential fallback and say which path ran.
- **Git.** Scan mode uses `git log` to find hot spots. Outside a git repository, ask the user for a direction, scan those files without history and record that hot-spot evidence is unavailable.

## Interaction Contract (both modes)

1. Ask **one question at a time**, each with the options you see and your recommended answer. Wait for the answer before asking the next. Do not batch a questionnaire.
2. Walk the decision tree in order: constraints, dependencies and their category, the shape of the deepened module, what sits behind the seam, which tests survive.
3. Stop when the user agrees a decision (the candidate, the interface shape, the seam placement) or rejects the candidate. Do not continue into planning or implementation.
4. Never edit code, even if asked mid-session "just do it". Hand off instead (see Decision Handoffs).

## Workflow

### Select the mode

- The user named a module, a picked candidate or a seam question ("where should the seam go in X?") → **design mode**.
- The user asked where to deepen, named only a direction (a subsystem, a pain point) or named nothing → **scan mode**.
- Ambiguous → ask one question: "Do you want me to find candidates, or design the interface of a module you have in mind?"

### Scan mode

1. **Scope before you scan (YAGNI).** Deepening pays off by making future change easier, so weight what changes. If the user named a direction, it is the scope; run `git log --oneline -n 200 --name-only -- <paths in that direction>` only to find the hot spots inside it. Otherwise run `git log --oneline -n 200 --name-only` over the whole repository (widen the window if the history is short or scattered) and list the files and directories that keep recurring. Outside a git repository, skip `git log` entirely: scope to the direction the user gave (ask for one if they gave none), inspect those files directly and record "hot-spot evidence unavailable: not a git repository". Record the scope, the hot spots you chose (or why there are none) and why.
2. **Read the context.** Domain files and ADRs for the scoped area, as in Prerequisites. Note the domain terms that will name candidates.
3. **Explore.** Spawn a read-only exploration sub-agent with the scope, the vocabulary terms and these prompts; without sub-agents, explore directly. Explore organically and note friction:
   - Where does understanding one concept require bouncing between many small modules?
   - Where are modules shallow, with an interface nearly as complex as the implementation?
   - Where were pure functions extracted just for testability while the real bugs hide in how they are called (no locality)?
   - Where do tightly coupled modules leak across their seams?
   - What is untested, or hard to test through its current interface?
4. **Apply the deletion test** to every suspected shallow module: imagine deleting it. If complexity vanishes, it was a pass-through; if complexity reappears across N callers, it was earning its keep. Keep candidates where deleting or merging would *concentrate* complexity. Drop the rest.
5. **Classify each candidate's dependencies** with `references/deepening.md` (in-process, local-substitutable, ports & adapters, true external). The category becomes the card's tag and decides how the deepened module would be tested.
6. **Write the HTML report.** Read `references/report-format.md` first; it defines the offline scaffold, card fields, diagrams, strength badges and tone. Write `architecture-review-<timestamp>.html` to `$TMPDIR` (fallback `/tmp`), open it with the platform opener and print its absolute path.
7. **Ask which candidate to explore:** "Which of these would you like to explore?" The report's cards are the options and its top recommendation is your recommended answer, so this question satisfies the interaction contract as written. Do not propose interfaces before the user picks. Stop here until they answer.
8. **Walk the picked candidate** through the interaction contract, then continue in design mode with it.

**Scan is complete when** the report exists at a printed absolute path, every card carries every required field, the top recommendation names one candidate, and the user has been asked to pick. A candidate list in chat without the report is not completion.

**Zero candidates is also a complete scan.** If nothing passes the deletion test, write the report with the scope and every module examined, each with the reason it was dropped, and no cards or top recommendation. Print its path, say no deepening candidate was found, and stop: skip steps 7–8 and do not ask the user to pick.

### Design mode

1. **Identify the module** and read its implementation, its callers and its tests. Confirm the name in domain language.
2. **Frame the problem space** for the user: the constraints any new interface must satisfy, the dependencies and their category from `references/deepening.md`, and a rough illustrative code sketch that makes the constraints concrete (labelled as a sketch, not a proposal).
3. **Design it twice.** Read `references/design-it-twice.md` and produce at least three radically different interfaces under distinct constraints (minimal interface, maximum flexibility, common caller first, and ports & adapters when a dependency crosses a seam). Each design has the five-part output that reference defines.
4. **Present and compare.** Show each design in turn, then compare them in prose by depth, locality and seam placement.
5. **Recommend.** Name the strongest design and why. Propose a hybrid when parts of different designs combine well. Be opinionated: the user wants a strong read, not a menu.
6. **Walk the decision** through the interaction contract until the user agrees an interface shape and seam placement, or rejects the deepening.

**Design is complete when** the user has made a decision on a specific recommended design:

- **Accepted:** the agreed interface states its invariants, error modes and seam, and the test strategy says which existing tests are replaced.
- **Rejected:** the reason is recorded (and checked against the ADR-candidate test below), and the session stops; no interface or test strategy is required.

Three designs without a recommendation is not completion.

## Decision Handoffs

Handle these inline as decisions crystallize, without leaving the session:

- **Domain terms.** A deepened module named after a concept missing from `CONTEXT.md`, or a fuzzy term sharpened during the conversation, goes to the `domain-modeling` package by name with the proposed term and the scenario that settled it. Do not edit `CONTEXT.md` here. If `domain-modeling` is not installed, list the proposed entry in the output as an unapplied change.
- **ADR candidates.** When the user rejects a candidate, or chooses a design, for a load-bearing reason a future explorer would need, apply `domain-modeling`'s conjunctive ADR-candidate test: the decision is **hard to reverse** (concrete migration or consumer cost), **surprising without context** (a future reader would reasonably expect otherwise) and the result of a **real trade-off** (genuine alternatives weighed and one chosen for specific reasons). All three must hold on actual evidence. Only then offer: "Want this recorded as an ADR so future reviews don't re-suggest it?" and hand the summary to `adr-writer` by name. Skip ephemeral reasons ("not worth it right now") and self-evident ones.
- **Implementation.** After the decision, hand off: to `codebase-advisor` for an agent-executable plan, or to the `/tdd` command to build the agreed interface test-first. Do not implement.

## Output

**Scan mode:**

```text
Report: /absolute/path/architecture-review-20261026-143005.html (opened)
Scope: <named direction | hot spots from git log: paths>
Candidates: <n> — <title> [Strong|Worth exploring|Speculative, dependency category]
Top recommendation: <title>, <one sentence why>
Question: Which of these would you like to explore?
```

**Design mode:** the problem frame, each design (interface, usage example, what hides behind the seam, dependency strategy and adapters, trade-offs), the comparison and the recommendation, then the questions one at a time.

**Decision (either mode, at the stop):**

```text
Decision: <agreed interface and seam | candidate rejected>
Module: <domain name> — files: <paths>
Interface: <entry points, invariants, error modes>
Seam and adapters: <placement; adapters justified (production, test)>
Tests: <new tests at the interface; old shallow-module tests to delete>
Handoffs: domain-modeling <terms | none>; ADR candidate <yes: summary | no: which condition failed>; implementation → codebase-advisor | /tdd
Not done here: code changes
```

## Error Handling

| Situation | Action |
|---|---|
| Not a git repository, or history too short to show hot spots | Ask the user for a direction and scan those files without `git log`; record that scope came from the user and hot-spot evidence is unavailable |
| No `CONTEXT.md`, `CONTEXT-MAP.md` or `docs/agents/domain.md` | Use names from the code; offer `domain-modeling` once if terms are ambiguous |
| Scan finds no candidate that passes the deletion test | Write the zero-candidate report (scope and every module examined with its drop reason), print its path and stop without asking for a pick; do not invent speculative cards to fill the report |
| `$TMPDIR` unset or unwritable | Fall back to `/tmp`; if that fails, stop and report the error rather than writing into the repository |
| No browser opener available (`open`, `xdg-open`, `start`) | Print the absolute path and say the report was not opened |
| No sub-agent support | Explore directly and run design-it-twice sequentially per its fallback; say so in the output |
| User asks for the refactor to be done | Decline the edit; hand off to `codebase-advisor` or `/tdd` with the decision |
| Candidate contradicts an ADR | Surface it only if the friction warrants reopening; mark it with the ADR callout |

## References

| Load when | Reference | Supplies |
|---|---|---|
| Before either mode | `references/vocabulary.md` | Glossary, principles, relationships, rejected framings, designing for testability |
| Classifying dependencies, placing a seam or planning tests | `references/deepening.md` | Four dependency categories, seam discipline, replace-don't-layer testing |
| Design mode step 3 | `references/design-it-twice.md` | Parallel sub-agent briefs, the five-part design output, sequential fallback, comparison |
| Scan mode step 6 | `references/report-format.md` | Offline HTML scaffold, card fields, diagram patterns, tone rules |

For source attribution or a deliberate upstream comparison, read `references/upstream/provenance.md`. The MIT notice is in this package's `LICENSE`.
