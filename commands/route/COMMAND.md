---
name: route
type: command
description: >-
  Skill router that maps user tasks to the best armory packages. Provides a
  decision-tree organized by development lifecycle phase (define, plan, build,
  verify, review, ship) plus cross-cutting domains (research, content, business).
  Triggers on: "/route", "which skill", "what package", "find the right skill",
  "help me pick a skill", "discover packages". Use this command when unsure
  which armory skill, agent, or command to use for a task.
metadata:
  version: 1.0.0
  category: operations
  tags: [discovery, routing, meta, navigation]
  difficulty: beginner
  phase: plan
command:
  syntax: /route [task-description]
  handler: inline
  dependencies: []
---
# Route — Skill & Package Discovery

When the user invokes `/route [task]`, match their task to the best armory package(s) using the decision tree below. If the task is ambiguous, ask one clarifying question before recommending.

## How to Use This Router

1. Read the user's task description
2. Match to the most specific category below
3. Recommend the **primary** package and any **complementary** packages
4. If the MCP armory server is available, cross-reference with `search_packages` for confirmation
5. **Outcome-weighted routing (optional):** if `dist/router_index.json` exists
   and the user wants rankings by historical pass rate rather than the static
   tree, delegate to the `skill-router` agent. The agent falls back to this
   static tree when the index is missing or confidence is low. See
   `agents/skill-router/AGENT.md`.

---

## Define Phase — "I have an idea"

| Task | Primary Package | Complements |
|------|----------------|-------------|
| Validate a business idea | `idea-validator` skill | `market-analyzer`, `competitive-analyzer`, `feasibility-assessor` |
| Market research | `market-analyzer` skill | `competitive-analyzer` |
| Competitive analysis | `competitive-analyzer` skill | `market-analyzer` |
| Feasibility assessment | `feasibility-assessor` skill | `estimate-calibrator` |
| Full business validation pipeline | `idea-scout` agent | (orchestrates all four above) |
| Set up repo-local agent context | `project-context-setup` skill | `adr-writer`, `github` |

## Plan Phase — "I need to plan the work"

| Task | Primary Package | Complements |
|------|----------------|-------------|
| Break down a project into tasks | `task-decomposer` skill | `estimate-calibrator` |
| Estimate effort/timeline | `estimate-calibrator` skill | `task-decomposer` |
| Configure issue tracker, triage labels, glossary, and ADR lookup | `project-context-setup` skill | `task-decomposer`, `project-planner` |
| Design system architecture | `project-architect` agent | `architecture-diagram` skill |
| Record architecture decisions | `adr-writer` skill | `architecture-reviewer` skill |
| Plan a full project | `project-planner` agent | `task-decomposer`, `estimate-calibrator` |

## Build Phase — "I need to write code"

| Task | Primary Package | Complements |
|------|----------------|-------------|
| Write tests first (TDD) | `/tdd` command | `test-harness` skill |
| Generate test suite for existing code | `test-harness` skill | — |
| Debug a failing test or error | `debug-investigator` skill | — |
| Optimize SQL queries | `sql-optimizer` skill | `benchmark-runner` |
| Optimize GPU/ML workloads | `gpu-optimizer` skill | `benchmark-runner` |
| Build a full feature end-to-end | `full-stack-builder` agent | `test-harness`, `pr-review` |
| Prompt engineering / iteration | `prompt-lab` skill | `rag-auditor` |
| Audit RAG pipeline | `rag-auditor` skill | `prompt-lab` |
| Build an MCP server or agent skill | `agent-builder` skill | `mcp-to-skill` |
| Convert MCP tool to skill | `mcp-to-skill` skill | `agent-builder` |
| Validate environment setup | `env-validator` skill | — |

## Verify Phase — "I need to validate quality"

| Task | Primary Package | Complements |
|------|----------------|-------------|
| Run benchmarks | `benchmark-runner` skill | `sql-optimizer`, `gpu-optimizer` |
| Systematic QA testing | `qa-systematic` skill | `test-harness` |
| Audit RAG quality | `rag-auditor` skill | — |
| Validate environment config | `env-validator` skill | — |

## Review Phase — "I need a code review"

| Task | Primary Package | Complements |
|------|----------------|-------------|
| Review a PR | `pr-review` skill | `code-refiner` |
| Full codebase audit | `codebase-auditor` agent | (orchestrates multiple reviewers) |
| Architecture review | `architecture-reviewer` skill | `architecture-diagram` |
| Security review | `security-reviewer` agent | `secret-scanner` agent |
| Scan for secrets/credentials | `secret-scanner` agent | — |
| Security scan (command) | `/security-scan` command | `security-reviewer` agent |
| Refactor/simplify code | `code-refiner` skill | — |
| Refactor (command) | `/refactor` command | `code-refiner` skill |
| Dependency vulnerabilities | `dependency-audit` skill | — |
| Migration risk assessment | `migration-risk-analyzer` skill | — |
| Pre-merge gate check | `pre-landing-review` skill | `pr-review` |
| Evaluate a package/library | `package-evaluator` skill | `dependency-audit` |
| Monitor repo health | `repo-sentinel` skill | `dependency-audit` |
| UX review | `ux-expert` skill | — |
| Devil's advocate / challenge assumptions | `devils-advocate` skill | — |

## Ship Phase — "I need to ship"

| Task | Primary Package | Complements |
|------|----------------|-------------|
| Ship workflow (PR + changelog) | `ship-workflow` skill | `changelog-composer` |
| Generate changelog | `changelog-composer` skill | — |
| Generate API documentation | `api-docs-generator` skill | — |
| Full release lifecycle | `release-captain` agent | `ship-workflow`, `changelog-composer` |
| Engineering retrospective | `engineering-retro` skill | — |
| Review before creating PR | `plan-review` agent | `pr-review` |

## Research — "I need to investigate"

| Task | Primary Package | Complements |
|------|----------------|-------------|
| Deep multi-source research | `research-analyst` agent | — |
| Literature review (academic) | `literature-review` skill | `arxiv-search` utility |
| Search arXiv papers | `arxiv-search` utility | `literature-review` |
| YouTube content analysis | `youtube-analysis` skill | `youtube-search` skill |
| Search YouTube | `youtube-search` skill | `youtube-analysis` |
| Critique research methodology | `research-critique` skill | `literature-review` |
| NotebookLM-style analysis | `notebooklm` skill | — |
| Web fetch / scrape | `web-fetch` skill | `lightpanda-browser` |
| Convert academic paper to skill | `paper-to-skill` skill | `skill-distiller` |

## Content & Media — "I need to create content"

| Task | Primary Package | Complements |
|------|----------------|-------------|
| LinkedIn post | `linkedin-post-style` skill | `humanize` skill |
| Blog post / article | `content-strategist` agent | `humanize` |
| Slide presentation (HTML) | `html-presentation` skill | — |
| Architecture diagram | `architecture-diagram` skill | `architecture-reviewer` |
| Generate image from concept | `concept-to-image` skill | — |
| Generate video from concept | `concept-to-video` skill | `remotion-video` |
| Programmatic video (Remotion) | `remotion-video` skill | — |
| Build static website | `static-web-artifacts-builder` skill | — |
| Convert to Markdown | `to-markdown` skill | — |
| Convert Markdown to PDF | `md-to-pdf` skill | — |
| Humanize AI text | `humanize` skill | — |
| Media production (auto-format) | `media-producer` agent | — |
| Write a proposal | `proposal-writer` agent | `estimate-calibrator` |

## Orchestration — "I need to coordinate work"

| Task | Primary Package | Complements |
|------|----------------|-------------|
| Coordinate multi-agent work | `team-lead` agent | (delegates to specialized agents) |
| Evolve/improve a skill | `test-engineer` agent | `surrogate-verifier`, `skill-distiller` |
| Full skill evolution pipeline | `/evolve` command | `test-engineer` agent |

---

## Presets — Pre-Configured Bundles

If the user wants a curated set of packages for a role or workflow:

| Preset | Purpose |
|--------|---------|
| `core` | Essential packages for any project |
| `python-strict` | Python development with strict typing and testing |
| `sec-strict` | Security-focused development |
| `research` | Academic and technical research |
| `eng-ops` | Engineering operations and shipping |
| `content-ops` | Content creation and publishing |
| `biz-validation` | Business idea validation pipeline |
| `media-craft` | Visual and video content creation |
| `terse-mode` | Minimal output style |
| `ai-builder` | AI/ML development |
| `skill-evolution` | Skill creation and refinement |
