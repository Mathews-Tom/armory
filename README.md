# armory

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![skills: 50](https://img.shields.io/badge/skills-50-informational)](skills/) [![evals: 100%](https://img.shields.io/badge/eval_coverage-100%25-success)](skills/)

Curated, production-grade skills for AI coding agents. No magic, no demos — battle-tested workflows built for developers who use AI seriously.

---

## Overview

`armory` is a collection of custom skills for [Claude Code](https://claude.ai/code) and Claude.ai. Each skill is a self-contained prompt package that extends Claude with a repeatable, opinionated workflow for a specific task domain.

**Philosophy:** Skills in this collection are practical and context-free. They define the _how_, not just the _what_ — covering inputs, outputs, edge cases, and failure modes. They are tested in real workloads, not constructed as examples.

Intended for developers who treat AI coding agents as a serious part of their workflow.

---

## Skill Catalog

### Development & Tooling

| Skill                                            | Description                                                                                                                                 |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| [agent-builder](skills/agent-builder/)           | Build AI agents using the Claude Agent SDK and headless CLI mode — covers tool definitions, MCP servers, and programmatic orchestration     |
| [github](skills/github/)                         | GitHub CLI operations via `gh` — issues, PRs, CI/Actions, releases, search, REST/GraphQL API, with error handling and automation workflows  |
| [filesystem](skills/filesystem/)                 | File and directory operations via Claude Code built-in tools — replaces the Filesystem MCP server with native Read, Write, Edit, Glob, Grep |
| [mcp-to-skill](skills/mcp-to-skill/)             | Convert MCP servers into on-demand skills to reduce active context window token usage                                                       |
| [gpu-optimizer](skills/gpu-optimizer/)           | GPU optimization for consumer GPUs (8-24GB VRAM) — PyTorch, XGBoost, CuPy/RAPIDS, memory management, and CUDA tuning                        |
| [tavily](skills/tavily/)                         | AI-optimized web search and content extraction via Tavily API with structured output parsing                                                |
| [test-harness](skills/test-harness/)             | Comprehensive pytest suite generation — happy path, edge cases, error conditions, fixtures, mocks, async, parametrized tests                |
| [debug-investigator](skills/debug-investigator/) | Systematic debugging framework — hypothesis-driven investigation with bisection, log analysis, instrumentation, and minimal reproduction    |
| [to-markdown](skills/to-markdown/)               | Convert any file or URL to clean Markdown via MarkItDown — PDF, DOCX, XLSX, PPTX, HTML, images, audio, CSV, JSON, XML, YouTube, EPub       |
| [web-fetch](skills/web-fetch/)                   | Web content fetching via curl and WebFetch — replaces the Fetch MCP server with native HTTP operations and jq parsing                       |
| [skill-library](skills/skill-library/)           | Agent-native catalog for browsing, installing, updating, syncing, and removing armory skills from within a Claude Code session              |

### Research & Analysis

| Skill                                        | Description                                                                                                                                                       |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [youtube-search](skills/youtube-search/)     | Search YouTube by keyword via yt-dlp — returns structured metadata (title, URL, channel, views, duration, date) for discovery and source curation                 |
| [youtube-analysis](skills/youtube-analysis/) | YouTube video transcript extraction and structured concept analysis — multi-level summaries, key concepts, takeaways, no API keys required                        |
| [notebooklm](skills/notebooklm/)             | Google NotebookLM automation via notebooklm-py — create notebooks, add sources, chat, generate podcasts, videos, infographics, quizzes, flashcards, and more      |
| [immune](skills/immune/)                     | Hybrid adaptive memory with Cheatsheet (positive patterns) and Immune (negative patterns) — Hot/Cold tiered memory, multi-domain antibody scanning, auto-learning |

### Review & Quality

| Skill                                                  | Description                                                                                                                                        |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| [architecture-reviewer](skills/architecture-reviewer/) | Architecture reviews across 7 scored dimensions — structural integrity, scalability, security, performance, enterprise readiness, operations, data |
| [code-refiner](skills/code-refiner/)                   | Deep code simplification and refactoring — structural complexity analysis, anti-pattern detection, idiomatic rewrites across Python, Go, TS, Rust  |
| [pr-review](skills/pr-review/)                         | Diff-based PR review across 5 dimensions — code quality, test coverage, silent failures, type design, comment quality with severity-ranked output  |
| [pre-landing-review](skills/pre-landing-review/)       | Gate-oriented safety audit with two-pass severity triage — CRITICAL (SQL, races, trust) blocks landing, INFORMATIONAL is advisory                  |
| [plan-review](skills/plan-review/)                     | Pre-implementation plan audit stress-testing scope, assumptions, risks, and failure modes with product and engineering lenses                       |
| [manuscript-review](skills/manuscript-review/)         | Pre-publication manuscript audit with 24 diagnostic dimensions, citation hygiene, and cross-element coherence                                      |
| [manuscript-provenance](skills/manuscript-provenance/) | Computational provenance audit verifying every number, table, and figure in a manuscript traces back to code                                       |
| [repo-sentinel](skills/repo-sentinel/)                 | Security audit and enforcement for public repos — 12 attack surfaces, pre-release readiness, history scrubbing, CI gates                           |
| [skill-evaluator](skills/skill-evaluator/)             | Evaluate skill quality across 6 weighted dimensions — frontmatter, triggers, structure, depth, consistency, compliance                             |
| [dependency-audit](skills/dependency-audit/)           | Dependency risk assessment — license compliance, maintenance health scoring, CVE detection, bloat identification, supply chain analysis            |
| [qa-systematic](skills/qa-systematic/)                 | Systematic web QA testing with 8-category health scoring, issue taxonomy, and regression tracking — full, quick, and regression modes              |

### Visualization & Documents

| Skill                                                                | Description                                                                                                          |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| [architecture-diagram](skills/architecture-diagram/)                 | Layered architecture diagrams as self-contained HTML with inline SVG icons and CSS Grid layout                       |
| [concept-to-image](skills/concept-to-image/)                         | Turn concepts into polished HTML visuals, export as PNG or SVG                                                       |
| [concept-to-video](skills/concept-to-video/)                         | Turn concepts into animated explainer videos using Manim — MP4/GIF output with audio overlay, templates, multi-scene |
| [remotion-video](skills/remotion-video/)                             | Production motion graphics using Remotion (React) — branded content, data-driven video, audio sync, TailwindCSS      |
| [html-presentation](skills/html-presentation/)                       | Convert documents and outlines into self-contained HTML slide presentations                                          |
| [static-web-artifacts-builder](skills/static-web-artifacts-builder/) | Self-contained interactive HTML artifacts — infographics, dashboards, diagrams                                       |
| [md-to-pdf](skills/md-to-pdf/)                                       | Markdown to styled PDF with Mermaid diagrams, KaTeX math, and syntax highlighting                                    |

### Documentation & Release

| Skill                                            | Description                                                                                                                |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| [changelog-composer](skills/changelog-composer/) | Structured changelogs from git history — conventional commit parsing, audience filtering, breaking change detection        |
| [ship-workflow](skills/ship-workflow/)           | Automated release pipeline — merge main, run tests, pre-landing review, version bump, changelog, bisectable commits, PR  |
| [engineering-retro](skills/engineering-retro/)   | Git-based engineering retrospective — commit analysis, velocity metrics, session patterns, health scoring over time windows |
| [adr-writer](skills/adr-writer/)                 | Architecture Decision Records — context capture, alternatives analysis, consequence projection, status lifecycle           |
| [api-docs-generator](skills/api-docs-generator/) | API documentation audit and enhancement — FastAPI docstrings, Pydantic examples, OpenAPI spec enrichment, coverage reports |

### Backend & Data

| Skill                                                      | Description                                                                                                |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| [sql-optimizer](skills/sql-optimizer/)                     | SQL performance analysis — EXPLAIN interpretation, anti-pattern detection, index recommendations, rewrites |
| [migration-risk-analyzer](skills/migration-risk-analyzer/) | Database migration risk assessment — lock analysis, downtime estimation, rollback strategies, validation   |
| [benchmark-runner](skills/benchmark-runner/)               | Structured benchmark design — metric selection, test case matrix, environment capture, statistical rigor   |

### AI/ML & Planning

| Skill                                              | Description                                                                                                   |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| [prompt-lab](skills/prompt-lab/)                   | Systematic prompt engineering — variant generation, evaluation rubrics, failure mode analysis, test suites    |
| [rag-auditor](skills/rag-auditor/)                 | RAG pipeline evaluation — retrieval metrics, generation quality, failure taxonomy, diagnostic queries         |
| [task-decomposer](skills/task-decomposer/)         | Feature decomposition — phased task breakdown, dependency mapping, edge case enumeration, sizing              |
| [estimate-calibrator](skills/estimate-calibrator/) | Calibrated three-point estimates — PERT ranges, unknown identification, confidence intervals, bias correction |

### Writing

| Skill                                              | Description                                                                                                                                                         |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [humanize](skills/humanize/)                       | Detect and remove AI-generated writing patterns — 24 lexical patterns + 12 statistical signals, 6 domain profiles, 5-phase pipeline with semantic preservation |
| [linkedin-post-style](skills/linkedin-post-style/) | Write LinkedIn posts in a specific technical voice with visual companion support — carousels via md-to-pdf, images via concept-to-image, video via concept-to-video |

### Deprecated

Skills below are superseded by base model capabilities. They remain installable but receive no further updates.

| Skill                                              | Reason                                           |
| -------------------------------------------------- | ------------------------------------------------ |
| [doc-condenser](skills/doc-condenser/)             | Base model handles summarization natively        |
| [regex-builder](skills/regex-builder/)             | Base model generates regex at equivalent quality |
| [sequential-thinking](skills/sequential-thinking/) | Base model handles chain-of-thought natively     |

---

## Installation

**Option 1 — Skills CLI (recommended)**

Install any skill directly using [`npx skills`](https://github.com/vercel-labs/skills):

```bash
# Install all skills
npx skills add Mathews-Tom/armory

# Install a specific skill
npx skills add Mathews-Tom/armory -s architecture-reviewer

# List available skills without installing
npx skills add Mathews-Tom/armory -l
```

**Option 2 — TUI Installer**

```bash
git clone https://github.com/Mathews-Tom/armory.git
cd armory
uv run scripts/install_skills.py
```

Displays a version-aware table of all skills, detects installed versions, and lets you select which to install or upgrade.

**Option 3 — Manual**

Clone the repo and symlink individual skill folders:

```bash
git clone https://github.com/Mathews-Tom/armory.git
ln -s "$(pwd)/armory/skills/architecture-reviewer" ~/.claude/skills/architecture-reviewer
```

Or download `.skill` archives from the [Releases](../../releases) page.

---

## Usage

Skills activate when Claude detects a matching intent in your message. Each skill defines trigger phrases in its frontmatter description — check the `SKILL.md` in each folder for the full list.

**Example triggers:**

```text
"Create an architecture diagram for my microservices setup"
→ activates: architecture-diagram

"Run a security audit before I push this to GitHub"
→ activates: repo-sentinel

"Convert this markdown file to PDF with the Mermaid diagrams rendered"
→ activates: md-to-pdf

"Build an agent that monitors a directory for changes"
→ activates: agent-builder

"Evaluate the quality of this skill"
→ activates: skill-evaluator
```

Skills do not require explicit invocation — Claude matches your intent against the skill's trigger definition and loads it automatically when relevant.

---

## Skill Quality

Every skill is evaluated against 6 dimensions using the [skill-evaluator](skills/skill-evaluator/):

| Dimension               | Weight | What it measures                                            |
| ----------------------- | ------ | ----------------------------------------------------------- |
| Frontmatter Quality     | 20%    | Description length, trigger phrases, "Use when" clause      |
| Trigger Coverage        | 18%    | Synonym breadth, implied contexts, interrogative forms      |
| Structural Completeness | 20%    | Workflow, error handling, output format, limitations        |
| Content Depth           | 22%    | Decision frameworks, multi-step workflows, output templates |
| Consistency & Integrity | 12%    | Name matching, file references, description-body alignment  |
| CONTRIBUTING Compliance | 8%     | Naming conventions, length limits, YAML validity            |

---

## Eval Coverage

Every skill has eval cases in `skills/<name>/evals/cases.yaml` — positive triggers (should activate) and negative triggers (should not). Deprecated skills enforce 0 positive + 2 negative cases.

**Validation:**

```bash
uv run scripts/validate_evals.py    # Schema validation for all eval files
uv run scripts/generate_manifest.py # Regenerate skills.yaml manifest
```

**CI pipeline** (`.github/workflows/skill-evals.yml`):

- **PR gate**: validates manifest sync + eval schema on every pull request
- **Weekly cron**: Monday runs for model drift detection

**Pre-commit hook**: auto-regenerates `skills.yaml` when skill files change.

---

## Packaging

Each skill can be packaged into a `.skill` archive for distribution:

```bash
uv run scripts/package_skill.py skills/architecture-reviewer
```

---

## Portability

These skills are Claude-native (Claude Code and Claude.ai).

Adapters for other agent surfaces are planned in `adapters/`:

- **Cursor** — `.cursorrules`
- **OpenAI Codex** — `AGENTS.md`
- **Gemini CLI** — `GEMINI.md`

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on submitting new skills or improving existing ones.

---

## License

MIT. See [LICENSE](LICENSE) for details.

---

> **Migrated from praxis-skills.** If you had skills installed from the previous repo,
> re-run the installer to update paths. Existing skills continue to work — the content
> is unchanged.
