# armory

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![packages: 92](https://img.shields.io/badge/packages-92-informational)](manifest.yaml) [![evals: 100%](https://img.shields.io/badge/eval_coverage-100%25-success)](skills/)

Curated, production-grade skills, agents, hooks, rules, commands, utilities, and presets for AI coding agents. No magic, no demos — battle-tested workflows built for developers who use AI seriously.

---

## Overview

`armory` is a collection of packages for [Claude Code](https://claude.ai/code) and Claude.ai. Each package is a self-contained prompt or automation unit that extends Claude with a repeatable, opinionated workflow for a specific task domain. Packages span seven types: skills, agents, hooks, rules, commands, utilities, and presets.

**Philosophy:** Packages in this collection are practical and context-free. They define the _how_, not just the _what_ — covering inputs, outputs, edge cases, and failure modes. They are tested in real workloads, not constructed as examples.

Intended for developers who treat AI coding agents as a serious part of their workflow.

---

## Package Catalog

### Agents — Orchestrators

Orchestrator agents compose skills and other agents into multi-phase workflows. Each can run solo or be spawned by another agent via the Agent tool.

| Agent                                              | Model  | Description                                                                                                     |
| -------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------- |
| [team-lead](agents/team-lead/)                     | opus   | Meta-orchestrator — decomposes multi-domain requests, delegates to specialized agents, synthesizes results       |
| [codebase-auditor](agents/codebase-auditor/)       | sonnet | Unified quality assessment — spawns code-reviewer, security-reviewer, secret-scanner in parallel, merges report |
| [project-architect](agents/project-architect/)     | opus   | Phased requirements discovery producing architecture documents with diagrams and tech stack justification        |
| [project-planner](agents/project-planner/)         | sonnet | Task decomposition with dependency mapping, three-point estimates, milestone timelines, and risk logs            |
| [research-analyst](agents/research-analyst/)       | opus   | Multi-source investigation with parallel agents across web, academic, video, and competitive sources             |
| [idea-scout](agents/idea-scout/)                   | opus   | Business idea validation — Lean Canvas, parallel market/competitive/feasibility research, weighted scorecard     |
| [full-stack-builder](agents/full-stack-builder/)   | opus   | End-to-end implementation from spec — scaffolding, sprints, quality passes, documentation, pre-delivery review   |
| [release-captain](agents/release-captain/)         | sonnet | Ship lifecycle with quality gates — pre-flight, secret scan, changelog, version bump, PR creation               |
| [proposal-writer](agents/proposal-writer/)         | opus   | Technical proposals with ROI calculations, three-tier pricing, and Problem-Agitate-Solve framing                |
| [content-strategist](agents/content-strategist/)   | sonnet | Multi-channel content creation with per-channel adaptation and automated quality passes                          |
| [media-producer](agents/media-producer/)           | sonnet | Visual and video format router — selects the right skill based on concept type and output needs                  |

### Agents — Analyzers

| Agent                                          | Model  | Description                                           |
| ---------------------------------------------- | ------ | ----------------------------------------------------- |
| [code-reviewer](agents/code-reviewer/)         | sonnet | Multi-phase code review with severity-ranked findings |
| [security-reviewer](agents/security-reviewer/) | sonnet | OWASP Top 10 vulnerability scanning                   |
| [secret-scanner](agents/secret-scanner/)       | haiku  | Pre-commit detection of hardcoded credentials         |

### Skills — Development & Tooling

| Skill                                            | Description                                                                                                                                                 |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [agent-builder](skills/agent-builder/)           | Build AI agents using the Claude Agent SDK and headless CLI mode — covers tool definitions, MCP servers, and programmatic orchestration                     |
| [github](skills/github/)                         | GitHub CLI operations via `gh` — issues, PRs, CI/Actions, releases, search, REST/GraphQL API, with error handling and automation workflows                  |
| [filesystem](skills/filesystem/)                 | File and directory operations via Claude Code built-in tools — replaces the Filesystem MCP server with native Read, Write, Edit, Glob, Grep                 |
| [mcp-to-skill](skills/mcp-to-skill/)             | Convert MCP servers into on-demand skills to reduce active context window token usage                                                                       |
| [gpu-optimizer](skills/gpu-optimizer/)           | GPU optimization for consumer GPUs (8-24GB VRAM) — PyTorch, XGBoost, CuPy/RAPIDS, memory management, and CUDA tuning                                        |
| [tavily](skills/tavily/)                         | AI-optimized web search and content extraction via Tavily API with structured output parsing                                                                |
| [test-harness](skills/test-harness/)             | Comprehensive pytest suite generation — happy path, edge cases, error conditions, fixtures, mocks, async, parametrized tests                                |
| [debug-investigator](skills/debug-investigator/) | Systematic debugging framework — hypothesis-driven investigation with bisection, log analysis, instrumentation, and minimal reproduction                    |
| [to-markdown](skills/to-markdown/)               | Convert any file or URL to clean Markdown via MarkItDown — PDF, DOCX, XLSX, PPTX, HTML, images, audio, CSV, JSON, XML, YouTube, EPub                        |
| [web-fetch](skills/web-fetch/)                   | Web content fetching via curl and WebFetch — replaces the Fetch MCP server with native HTTP operations and jq parsing                                       |
| [lightpanda-browser](skills/lightpanda-browser/) | Lightweight headless browser automation via Lightpanda + agent-browser CDP — 9x lower memory, 11x faster, for scraping, DOM extraction, and form automation |
| [skill-library](skills/skill-library/)           | Agent-native catalog for browsing, installing, updating, syncing, and removing armory skills from within a Claude Code session                              |

### Skills — Research & Analysis

| Skill                                          | Description                                                                                                                                                       |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [literature-review](skills/literature-review/) | Systematic literature review — search, screen, extract, and synthesize academic research with gap analysis and structured citations                               |
| [youtube-search](skills/youtube-search/)       | Search YouTube by keyword via yt-dlp — returns structured metadata (title, URL, channel, views, duration, date) for discovery and source curation                 |
| [youtube-analysis](skills/youtube-analysis/)   | YouTube video transcript extraction and structured concept analysis — multi-level summaries, key concepts, takeaways, no API keys required                        |
| [notebooklm](skills/notebooklm/)               | Google NotebookLM automation via notebooklm-py — create notebooks, add sources, chat, generate podcasts, videos, infographics, quizzes, flashcards, and more      |
| [research-critique](skills/research-critique/) | Critical analysis of research papers — methodology evaluation, claims-evidence alignment, contribution assessment with collegial analytical posture               |
| [immune](skills/immune/)                       | Hybrid adaptive memory with Cheatsheet (positive patterns) and Immune (negative patterns) — Hot/Cold tiered memory, multi-domain antibody scanning, auto-learning |

### Skills — Review & Quality

| Skill                                                  | Description                                                                                                                                         |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| [architecture-reviewer](skills/architecture-reviewer/) | Architecture reviews across 7 scored dimensions — structural integrity, scalability, security, performance, enterprise readiness, operations, data  |
| [code-refiner](skills/code-refiner/)                   | Deep code simplification and refactoring — structural complexity analysis, anti-pattern detection, idiomatic rewrites across Python, Go, TS, Rust   |
| [pr-review](skills/pr-review/)                         | Diff-based PR review across 5 dimensions — code quality, test coverage, silent failures, type design, comment quality with severity-ranked output   |
| [pre-landing-review](skills/pre-landing-review/)       | Gate-oriented safety audit with two-pass severity triage — CRITICAL (SQL, races, trust) blocks landing, INFORMATIONAL is advisory                   |
| [plan-review](skills/plan-review/)                     | Pre-implementation plan audit stress-testing scope, assumptions, risks, and failure modes with product and engineering lenses                       |
| [manuscript-review](skills/manuscript-review/)         | Pre-publication manuscript audit with 24 diagnostic dimensions, citation hygiene, and cross-element coherence                                       |
| [manuscript-provenance](skills/manuscript-provenance/) | Computational provenance audit verifying every number, table, and figure in a manuscript traces back to code                                        |
| [repo-sentinel](skills/repo-sentinel/)                 | Security audit and enforcement for public repos — 12 attack surfaces, pre-release readiness, history scrubbing, CI gates                            |
| [package-evaluator](skills/package-evaluator/)         | Evaluate package quality across 6 weighted dimensions with type-specific signals — frontmatter, triggers, structure, depth, consistency, compliance |
| [dependency-audit](skills/dependency-audit/)           | Dependency risk assessment — license compliance, maintenance health scoring, CVE detection, bloat identification, supply chain analysis             |
| [qa-systematic](skills/qa-systematic/)                 | Systematic web QA testing with 8-category health scoring, issue taxonomy, and regression tracking — full, quick, and regression modes               |

### Skills — Visualization & Documents

| Skill                                                                | Description                                                                                                          |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| [architecture-diagram](skills/architecture-diagram/)                 | Layered architecture diagrams as self-contained HTML with inline SVG icons and CSS Grid layout                       |
| [concept-to-image](skills/concept-to-image/)                         | Turn concepts into polished HTML visuals, export as PNG or SVG                                                       |
| [concept-to-video](skills/concept-to-video/)                         | Turn concepts into animated explainer videos using Manim — MP4/GIF output with audio overlay, templates, multi-scene |
| [remotion-video](skills/remotion-video/)                             | Production motion graphics using Remotion (React) — branded content, data-driven video, audio sync, TailwindCSS      |
| [html-presentation](skills/html-presentation/)                       | Convert documents and outlines into self-contained HTML slide presentations                                          |
| [static-web-artifacts-builder](skills/static-web-artifacts-builder/) | Self-contained interactive HTML artifacts — infographics, dashboards, diagrams                                       |
| [md-to-pdf](skills/md-to-pdf/)                                       | Markdown to styled PDF with Mermaid diagrams, KaTeX math, and syntax highlighting                                    |

### Skills — Documentation & Release

| Skill                                            | Description                                                                                                                 |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| [changelog-composer](skills/changelog-composer/) | Structured changelogs from git history — conventional commit parsing, audience filtering, breaking change detection         |
| [ship-workflow](skills/ship-workflow/)           | Automated release pipeline — merge main, run tests, pre-landing review, version bump, changelog, bisectable commits, PR     |
| [engineering-retro](skills/engineering-retro/)   | Git-based engineering retrospective — commit analysis, velocity metrics, session patterns, health scoring over time windows |
| [adr-writer](skills/adr-writer/)                 | Architecture Decision Records — context capture, alternatives analysis, consequence projection, status lifecycle            |
| [api-docs-generator](skills/api-docs-generator/) | API documentation audit and enhancement — FastAPI docstrings, Pydantic examples, OpenAPI spec enrichment, coverage reports  |

### Skills — Backend & Data

| Skill                                                      | Description                                                                                                |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| [sql-optimizer](skills/sql-optimizer/)                     | SQL performance analysis — EXPLAIN interpretation, anti-pattern detection, index recommendations, rewrites |
| [migration-risk-analyzer](skills/migration-risk-analyzer/) | Database migration risk assessment — lock analysis, downtime estimation, rollback strategies, validation   |
| [benchmark-runner](skills/benchmark-runner/)               | Structured benchmark design — metric selection, test case matrix, environment capture, statistical rigor   |

### Skills — Business Validation

| Skill                                                | Description                                                                                                                                   |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| [idea-validator](skills/idea-validator/)             | Full business idea validation orchestrator — Lean Canvas, JTBD, parallel market/competitive/feasibility agents, SWOT/PESTLE, weighted scoring |
| [market-analyzer](skills/market-analyzer/)           | Market sizing and trend analysis — TAM/SAM/SOM calculation, Rogers adoption curve, data triangulation, timing assessment                      |
| [competitive-analyzer](skills/competitive-analyzer/) | Competitive landscape analysis — Porter's Five Forces, feature/pricing matrices, positioning maps, moat taxonomy                              |
| [feasibility-assessor](skills/feasibility-assessor/) | Financial and technical feasibility — unit economics (CAC/LTV), revenue modeling, break-even, technical risk scoring, build-vs-buy            |

### Skills — AI/ML & Planning

| Skill                                              | Description                                                                                                   |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| [prompt-lab](skills/prompt-lab/)                   | Systematic prompt engineering — variant generation, evaluation rubrics, failure mode analysis, test suites    |
| [rag-auditor](skills/rag-auditor/)                 | RAG pipeline evaluation — retrieval metrics, generation quality, failure taxonomy, diagnostic queries         |
| [task-decomposer](skills/task-decomposer/)         | Feature decomposition — phased task breakdown, dependency mapping, edge case enumeration, sizing              |
| [estimate-calibrator](skills/estimate-calibrator/) | Calibrated three-point estimates — PERT ranges, unknown identification, confidence intervals, bias correction |

### Skills — Writing

| Skill                                              | Description                                                                                                                                                         |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [humanize](skills/humanize/)                       | Detect and remove AI-generated writing patterns — 24 lexical patterns + 12 statistical signals, 6 domain profiles, 5-phase pipeline with semantic preservation      |
| [linkedin-post-style](skills/linkedin-post-style/) | Write LinkedIn posts in a specific technical voice with visual companion support — carousels via md-to-pdf, images via concept-to-image, video via concept-to-video |

### Skills — Deprecated

Skills below are superseded by base model capabilities. They remain installable but receive no further updates.

| Skill                                              | Reason                                           |
| -------------------------------------------------- | ------------------------------------------------ |
| [doc-condenser](skills/doc-condenser/)             | Base model handles summarization natively        |
| [regex-builder](skills/regex-builder/)             | Base model generates regex at equivalent quality |
| [sequential-thinking](skills/sequential-thinking/) | Base model handles chain-of-thought natively     |

## Rules

| Rule                                            | Description                                    |
| ----------------------------------------------- | ---------------------------------------------- |
| [commit-standards](rules/commit-standards/)     | Conventional commit format, branch naming      |
| [test-standards](rules/test-standards/)         | Coverage thresholds, test quality requirements |
| [security-standards](rules/security-standards/) | Secret management, input validation, auth      |

## Commands

| Command                                  | Description                      |
| ---------------------------------------- | -------------------------------- |
| [tdd](commands/tdd/)                     | Test-driven development workflow |
| [security-scan](commands/security-scan/) | Security vulnerability audit     |
| [refactor](commands/refactor/)           | Code simplification workflow     |

## Hooks

| Hook                                      | Description                    |
| ----------------------------------------- | ------------------------------ |
| [git-protection](hooks/git-protection/)   | Block dangerous git operations |
| [pre-edit-backup](hooks/pre-edit-backup/) | Backup files before edits      |
| [cost-tracker](hooks/cost-tracker/)       | Log session cost/token usage   |

## Utilities

| Utility                                                 | Description                                              |
| ------------------------------------------------------- | -------------------------------------------------------- |
| [arxiv-search](utilities/arxiv-search/)                 | Search arXiv for papers, output structured JSON metadata |
| [dependency-tree](utilities/dependency-tree/)           | Visualize project dependency graph                       |
| [test-coverage-report](utilities/test-coverage-report/) | Coverage summary for changed files                       |

## Presets

Presets install curated bundles of passive packages (rules, hooks, commands) in one command. For active workflow orchestration, use agents instead.

| Preset                                    | Packages                                          | Description                                                                                              |
| ----------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| [core](presets/core/)                     | 3 skills, 1 hook, 1 rule                          | Baseline review-commit lifecycle. Start here.                                                            |
| [sec-strict](presets/sec-strict/)         | 5 skills, 3 agents, 2 rules, 2 hooks, 1 command   | Audit-grade security stack with codebase-auditor. Superset of `core`.                                    |
| [python-strict](presets/python-strict/)   | 4 skills, 2 agents, 3 rules, 2 hooks, 2 commands  | Full Python enforcement — TDD, type checking, test coverage, security standards.                         |
| [ai-builder](presets/ai-builder/)         | 6 skills                                          | AI/ML development toolkit — agent building, prompt engineering, GPU optimization, RAG auditing.           |

### Deprecated Presets

Superseded by orchestrator agents that provide autonomous workflow orchestration instead of manual skill invocation.

| Preset | Replacement |
| ------ | ----------- |
| ~~biz-validation~~ | `idea-scout` agent |
| ~~media-craft~~ | `media-producer` agent |
| ~~content-ops~~ | `content-strategist` agent |
| ~~research~~ | `research-analyst` agent |
| ~~eng-ops~~ | `release-captain` + `full-stack-builder` agents |

---

## Installation

**Option 1 — Skills CLI (recommended)**

Install any package directly using [`npx skills`](https://github.com/vercel-labs/skills):

```bash
# Install all packages
npx skills add Mathews-Tom/armory

# Install a specific skill or agent
npx skills add Mathews-Tom/armory -s architecture-reviewer
npx skills add Mathews-Tom/armory -s codebase-auditor

# List available packages without installing
npx skills add Mathews-Tom/armory -l
```

**Option 2 — Profile installer**

```bash
git clone https://github.com/Mathews-Tom/armory.git
cd armory

# Install by profile
just install-profile core
just install-profile python-strict

# Install by type
uv run scripts/install.py --type skills
uv run scripts/install.py --type agents

# Interactive TUI
uv run scripts/install.py
```

Displays a version-aware table of all packages, detects installed versions, and lets you select which to install or upgrade. Profiles install curated bundles of packages across all types.

**Option 3 — Manual**

Clone the repo and symlink individual package folders:

```bash
git clone https://github.com/Mathews-Tom/armory.git

# Skills
ln -s "$(pwd)/armory/skills/architecture-reviewer" ~/.claude/skills/architecture-reviewer

# Agents
ln -s "$(pwd)/armory/agents/codebase-auditor" ~/.claude/agents/codebase-auditor
```

Or download `.skill` / `.agent` archives from the [Releases](../../releases) page.

---

## Usage

Packages activate when Claude detects a matching intent. Each package defines trigger phrases in its frontmatter description — check the definition file (`SKILL.md`, `AGENT.md`, etc.) in each folder.

**Example triggers:**

```text
"Run a security audit before I push this to GitHub"
-> activates: repo-sentinel (skill)

"Review this code for quality issues"
-> activates: code-reviewer (agent)

"Evaluate the quality of this package"
-> activates: package-evaluator (skill)
```

**Commands** are invoked explicitly via slash syntax:

```text
/tdd calculate_discount    -> TDD workflow for a function
/security-scan src/        -> security vulnerability audit
/refactor src/utils.py     -> code simplification
```

**Hooks** fire automatically on Claude Code lifecycle events (PreToolUse, PostToolUse, Stop, SessionStart). **Rules** load as context when relevant. **Presets** install bundles via `just install-profile`.

---

## Package Quality

Every package is evaluated against 6 shared dimensions using the [package-evaluator](skills/package-evaluator/), with type-specific signals for agents, hooks, rules, commands, utilities, and presets:

| Dimension               | Weight | What it measures                                                 |
| ----------------------- | ------ | ---------------------------------------------------------------- |
| Frontmatter Quality     | 20%    | Description length, trigger phrases, "Use when" clause           |
| Trigger Coverage        | 18%    | Synonym breadth, implied contexts, interrogative forms           |
| Structural Completeness | 20%    | Workflow, error handling, output format, type-specific metadata  |
| Content Depth           | 22%    | Decision frameworks, multi-step workflows, type-specific signals |
| Consistency & Integrity | 12%    | Name matching, file references, description-body alignment       |
| CONTRIBUTING Compliance | 8%     | Naming conventions, length limits, YAML validity                 |

---

## Eval Coverage

Every package has eval cases in `{type}/<name>/evals/cases.yaml` — positive triggers (should activate) and negative triggers (should not). Deprecated packages enforce 0 positive + 2 negative cases.

**Validation:**

```bash
uv run scripts/validate_evals.py    # Schema validation for all eval files
uv run scripts/generate_manifest.py # Regenerate manifest.yaml
```

**CI pipeline** (`.github/workflows/evals.yml`):

- **PR gate**: validates manifest sync + eval schema on every pull request across all 7 type directories
- **Weekly cron**: Monday runs for model drift detection

**Pre-commit hook**: auto-regenerates `manifest.yaml` when any package definition file changes.

---

## Packaging

Each package can be archived for distribution. Archive type is auto-detected from the directory:

```bash
uv run scripts/package.py skills/architecture-reviewer  # produces .skill
uv run scripts/package.py agents/code-reviewer           # produces .agent
uv run scripts/package.py hooks/git-protection            # produces .hook
```

---

## Portability

These packages are Claude-native (Claude Code and Claude.ai).

Adapters for other agent surfaces are planned in `adapters/`:

- **Cursor** — `.cursorrules`
- **OpenAI Codex** — `AGENTS.md`
- **Gemini CLI** — `GEMINI.md`

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on submitting new packages or improving existing ones.

---

## License

MIT. See [LICENSE](LICENSE) for details.

---

> **Migrated from praxis-skills.** If you had skills installed from the previous repo,
> re-run the installer to update paths. Existing skills continue to work — the content
> is unchanged.
