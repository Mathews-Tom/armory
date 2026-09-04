# Attributions

Tools, libraries, and projects that armory packages wrap, depend on, or were inspired by.

---

## Installation & Distribution

| Upstream                       | Repo                                                                    | Used by                                        |
| ------------------------------ | ----------------------------------------------------------------------- | ---------------------------------------------- |
| **skills CLI** (Vercel Labs)   | [vercel-labs/skills](https://github.com/vercel-labs/skills)             | `npx skills add` install method                |
| **agent-skills** (Vercel Labs) | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | Skill format conventions, SKILL.md spec origin |

## Direct Library & Tool Dependencies

| Upstream                                 | Repo                                                                                                          | License                   | Used by (armory skill)               |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------- | ------------------------------------ |
| **Manim** (3Blue1Brown / ManimCommunity) | [3b1b/manim](https://github.com/3b1b/manim) / [ManimCommunity/manim](https://github.com/ManimCommunity/manim) | MIT                       | `concept-to-video`                   |
| **Remotion**                             | [remotion-dev/remotion](https://github.com/remotion-dev/remotion)                                             | Custom (Remotion License) | `remotion-video`                     |
| **MarkItDown** (Microsoft)               | [microsoft/markitdown](https://github.com/microsoft/markitdown)                                               | MIT                       | `to-markdown`                        |
| **notebooklm-py** (teng-lin)             | [teng-lin/notebooklm-py](https://github.com/teng-lin/notebooklm-py)                                           | MIT                       | `notebooklm`                         |
| **yt-dlp**                               | [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp)                                                             | Unlicense                 | `youtube-search`, `youtube-analysis` |
| **youtube-transcript-api** (jdepoix)     | [jdepoix/youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)                           | MIT                       | `youtube-analysis`                   |
| **Reveal.js**                            | [hakimel/reveal.js](https://github.com/hakimel/reveal.js)                                                     | MIT                       | `html-presentation`                  |
| **Lightpanda Browser**                   | [lightpanda-io/browser](https://github.com/lightpanda-io/browser)                                             | AGPL-3.0                  | `lightpanda-browser`                 |
| **agent-browser** (Lightpanda)           | [lightpanda-io/agent-skill](https://github.com/lightpanda-io/agent-skill)                                     | —                         | `lightpanda-browser`                 |
| **Tavily API**                           | [tavily-ai/tavily-python](https://github.com/tavily-ai/tavily-python)                                         | MIT                       | `tavily`                             |
| **Puppeteer** (Google)                   | [puppeteer/puppeteer](https://github.com/puppeteer/puppeteer)                                                 | Apache-2.0                | `lightpanda-browser` (CDP client)    |
| **gitleaks**                             | [gitleaks/gitleaks](https://github.com/gitleaks/gitleaks)                                                     | MIT                       | `repo-sentinel`, `secret-scanner`    |
| **arXiv API**                            | [lukasschwab/arxiv.py](https://github.com/lukasschwab/arxiv.py)                                               | MIT                       | `arxiv-search`                       |
| **pytest**                               | [pytest-dev/pytest](https://github.com/pytest-dev/pytest)                                                     | MIT                       | `test-harness`                       |
| **KaTeX**                                | [KaTeX/KaTeX](https://github.com/KaTeX/KaTeX)                                                                 | MIT                       | `md-to-pdf`                          |
| **Mermaid**                              | [mermaid-js/mermaid](https://github.com/mermaid-js/mermaid)                                                   | MIT                       | `md-to-pdf`                          |
| **draw.io** (jgraph)                     | [jgraph/drawio](https://github.com/jgraph/drawio)                                                             | Apache-2.0                | `architecture-diagram` (icon geometry, fetched at runtime — see Vendoring Records) |
| **Playwright** (Microsoft)               | [microsoft/playwright](https://github.com/microsoft/playwright)                                               | Apache-2.0                | `qa-systematic`                      |
| **Marp** (marp-team)                     | [marp-team/marpit](https://github.com/marp-team/marpit) · [marp-team/marp-core](https://github.com/marp-team/marp-core) · [marp-team/marp-cli](https://github.com/marp-team/marp-cli) | MIT                       | `marp-slides`                        |

## Vendoring Records

Records of upstream content that was copied or adapted directly into armory skills, with pinned commits and re-sync policies. Each record documents exactly what was taken, what was reimplemented from paper descriptions, and what was skipped.

### Code2Video — used by `concept-to-video`

**Paper:** [Code2Video: A Code-Centric Paradigm for Educational Video Generation](https://arxiv.org/abs/2510.01174)
**Authors:** Anno Yanzhe Chen et al., Show Lab, National University of Singapore
**Venue:** NeurIPS 2025 Workshop on Deep Learning for Code (DL4C)
**Upstream repo:** [showlab/Code2Video](https://github.com/showlab/Code2Video)
**License:** MIT (text preserved at `skills/concept-to-video/references/code2video/LICENSE`)
**Pinned commit:** `f579f1e527f9d6684eb581853f8739b6b39f2914`

**What we vendored (prompt logic only — no code):**

The three prompt templates in `skills/concept-to-video/references/code2video/` are adapted from the following upstream files, with variable names and output schemas rewritten for armory's `concept-to-video` schema:

| Armory file  | Upstream source(s)                       |
|--------------|------------------------------------------|
| `planner.md` | `prompts/stage1.py`, `prompts/stage2.py` |
| `coder.md`   | `prompts/stage3.py`                      |
| `critic.md`  | `prompts/stage4.py`                      |

The upstream repo structures prompts as Python functions returning f-strings. We extracted the prompt text, adapted variable names to match our schema, and reformatted as markdown template files. No upstream Python code is included.

**What we reimplemented (described in paper, no code copied):**

- **Auto-fix loop** (paper §3.3): captures `manim render` stderr, extracts offending line range, calls the coder fixup prompt, patches the scene file in-place, retries up to N times. Lives in `scripts/render_video.py`, uses Python `subprocess`.
- **VLM critic loop** (paper §3.4): samples rendered frames, sends to a vision model with the critic prompt, receives anchor-based layout patches, re-renders. Calls Claude vision or Gemini via the existing Anthropic SDK — not Code2Video's custom wrapper.

**What we skipped:**

- **MMMC benchmark** (`eval_TQ.py`, `eval_AES.py`): research evaluation harness, not relevant to a production skill. Would belong in `evals/skillsbench/` if ever adopted.
- **TeachQuiz metric**: research artifact — no end-user value.
- **IconFinder integration**: broke October 2025 per the upstream README. Replaced by the pluggable asset sourcing design in P4 (`scripts/fetch_assets.py`), which defaults to local SVG directories with IconFinder as an optional API-key-gated adapter.
- **Shell entry points** (`run_agent.sh`, `run_agent_single.sh`): our entry point is the SKILL.md workflow, not shell scripts.
- **3D ThreeDScene support**: excluded upstream and here; unreliable in headless containers.

**Re-sync policy:** Prompt templates are pinned to the commit SHA above. Re-sync opportunistically when the upstream repo makes substantive prompt changes — do not auto-update. Compare diffs against the pinned commit before merging any upstream changes.


### tufte-data-viz — used by `chart-clarity`

**Upstream repo:** [caylent/tufte-data-viz](https://github.com/caylent/tufte-data-viz)
**License:** MIT (text preserved at `skills/chart-clarity/references/upstream/LICENSE`)
**Pinned commit:** `ae7ca0de7819db83241b24a2618810d5f1171145`

**What we vendored:**

- Core chart guidance from upstream `SKILL.md`, adapted into `skills/chart-clarity/SKILL.md`.
- Library-specific rules from upstream `rules/`, copied into `skills/chart-clarity/references/rules/`.
- Working examples from upstream `examples/`, copied into `skills/chart-clarity/references/examples/`.
- Interactive demo from upstream `docs/index.html`, copied into `skills/chart-clarity/references/interactive-demo.html`.
- Showcase images from upstream `_docs/`, copied into `skills/chart-clarity/assets/showcase/`.

**What we adapted:**

- Package name changed from `tufte-data-viz` to `chart-clarity`.
- Frontmatter, trigger language, local references, TypeScript example types, and chart titles were adjusted for armory conventions.
- Evals and provenance metadata were added.

**What we skipped:**

- `_docs/generate_showcase.py`: upstream-local showcase generator with a machine-specific absolute output path.
- Upstream README installation instructions: not applicable to armory's manifest-driven packaging.

**Re-sync policy:** Compare upstream against the pinned commit before merging updates. Do not auto-sync.

### improve — used by `codebase-advisor`

**Upstream repo:** [shadcn/improve](https://github.com/shadcn/improve)
**License:** MIT (text preserved at `skills/codebase-advisor/references/upstream/LICENSE`)
**Pinned commit:** `03369ee6d7cafbfcecc4346539b05b3dc0a603bb`

**What we vendored:**

- Senior-advisor workflow from upstream `skills/improve/SKILL.md`, adapted into `skills/codebase-advisor/SKILL.md`.
- Audit categories from upstream `skills/improve/references/audit-playbook.md`, adapted into `skills/codebase-advisor/references/audit-playbook.md`.
- Plan and backlog structure from upstream `skills/improve/references/plan-template.md`, adapted into `skills/codebase-advisor/references/plan-template.md`.
- Execute/reconcile/issue-publishing flow from upstream `skills/improve/references/closing-the-loop.md`, adapted into `skills/codebase-advisor/references/closing-the-loop.md`.

**What we adapted:**

- Package name changed from `improve` to `codebase-advisor` to avoid generic trigger collisions and clarify the role beside `codebase-auditor`.
- Trigger language and scope boundaries were rewritten for armory routing: `codebase-auditor` remains the report-only quality gate; `codebase-advisor` owns implementation-plan backlogs.
- Armory metadata and eval coverage were added.

**What we skipped:**

- Upstream Claude plugin marketplace manifests under `.claude-plugin/`; armory generates its own manifest.
- The upstream example plan under `examples/`; useful as a demonstration, not needed for the installed skill package.

**Re-sync policy:** Compare upstream against the pinned commit before merging updates. Preserve armory's `codebase-advisor` naming and routing boundary unless `codebase-auditor` is formally deprecated.

### Knowledge-graph curriculum and governance patterns — used by `kg-builder`

`kg-builder` vendors **no** upstream text, code, or assets. It is written independently. Two bodies of prior work informed its content and are recorded here for provenance.

**Field grounding — Southeast University graduate Knowledge Graph course**

**Course:** 东南大学《知识图谱》研究生课程, Prof. 汪鹏 (Peng Wang)
**Repo:** [npubird/KnowledgeGraphCourse](https://github.com/npubird/KnowledgeGraphCourse)
**License:** **No license file.** The GitHub API reports `license: null` and the repository root contains no `LICENSE` or `COPYING`. No derivative-work permission is established.

Because no license grants derivative rights, nothing from that repository is reproduced here. `kg-builder` uses only the field's standard, non-copyrightable pipeline decomposition — ontology modeling, entity/relation/event extraction, knowledge fusion, KG×LLM serving — which is common to the published knowledge-graph literature and predates that course. No lecture text, slide content, translated outline, or PDF is included, and the skill deliberately carries no per-lecture curriculum map.

A third-party redistribution of an English distillation of that course exists at [codejunkie99/graph-engineering](https://github.com/codejunkie99/graph-engineering) (MIT). It was evaluated and **not** ingested: its scope conflates knowledge graphs with agent task graphs, its task-graph half duplicates `task-decomposer`, `milestone-runner`, `pr-swarm`, `team-lead`, and `project-planner`, and it relicenses a derivative of an unlicensed upstream. No content was taken from it.

**Governance patterns — Kosha**

**Repo:** [Mathews-Tom/Kosha](https://github.com/Mathews-Tom/Kosha) (`kosha-okf`)
**License:** Apache-2.0
**Referenced at:** v0.1.0

`references/provenance-and-supersession.md` describes a claim-ledger design — append-only supersession, `supersedes`/`contradicts` lineage, bitemporal validity, a checkable no-silent-overwrite invariant, and a human gate on irreversible steps — for which Kosha is a reference implementation (`src/kosha/model.py`, `assert_no_silent_overwrite` in `src/kosha/contradiction/escalate.py`). The pattern is described, not copied; no Kosha code or documentation text is included, and `kg-builder` takes no dependency on `kosha-okf`.

Kosha's pre-registered real-model Gate-0 evaluation is also cited, as a measured finding rather than a claim: an LLM-adjudicated dedup-and-contradiction loop trailed a prompt-only baseline by 0.28–0.33 on detection and safety across every provider cell tested (108 held-out contradictions, 2 embedding × 2 generation models). `kg-builder` uses this to require that any model adjudicator be measured against a prompt-only baseline before it is trusted. Kosha's governance guarantee held under the same evaluation; its decision-quality claim did not, and the skill states the distinction.

**Re-sync policy:** Neither upstream is vendored, so there is nothing to diff. Revisit the Kosha citation if a later pre-registered Gate-0 run records a GO verdict, and revisit the OKF question separately — OKF bundles are linked Markdown documents with untyped links, not typed property graphs, so they are out of scope for this skill.

### draw.io icon geometry and provider icon terms — used by `architecture-diagram`

**Geometry source:** [jgraph/drawio](https://github.com/jgraph/drawio), Apache-2.0, pinned commit `a1f615b7f5a5237da71de2ce2f057b5fa70b0aeb` (`dev` branch, verified 2026-08-15).

**Not traditional vendoring — no cloud icon files are copied into this repository.** `engine/stencil2svg.py` converts draw.io AWS/GCP stencil geometry and `engine/svg_inline.py` inlines/namespaces draw.io Azure SVG geometry only in a user-local cache. `engine/fetch_icons.py` records a SHA-256 digest, source path, and the provider-specific terms below for every cache entry; `engine/render.py` rejects a requested entry whose digest differs.

| Provider | Official source and permitted use | Cache ledger |
| --- | --- | --- |
| AWS | [Architecture icons](https://aws.amazon.com/architecture/icons/): AWS allows customers and partners to use its toolkits and assets to create architecture diagrams, whitepapers, presentations, data sheets, and posters. | `license_note.aws`, each AWS cache entry's source path and digest |
| Azure | [Azure Icons](https://learn.microsoft.com/en-us/azure/architecture/icons/): Microsoft permits copying, distributing, and displaying icons only in architectural diagrams, training materials, or documentation; use icons as published and do not crop, flip, rotate, distort, or change their shape. | `license_note.azure`, each Azure cache entry's source path and digest |
| Google Cloud | [Google Cloud product icons](https://cloud.google.com/icons): official icons for diagrams and technical documentation. | `license_note.gcp`, each Google Cloud cache entry's source path and digest |

The pinned commit governs which draw.io geometry is converted. Rebuild a provider cache with `python3 -m engine.fetch_icons --provider <provider> --force` after a digest failure or a pin bump; this does not fetch implicit `dev`-branch churn.

## Conceptual Inspiration

| Concept                                        | Source                                                                                                                  | Used by                                  |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Sequential Thinking MCP Server                 | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) (sequential-thinking)                   | `sequential-thinking` (deprecated)       |
| Fetch MCP Server                               | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) (fetch)                                 | `web-fetch` (replacement)                |
| Filesystem MCP Server                          | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) (filesystem)                            | `filesystem` (replacement)               |
| Artificial Immune Systems / Negative Selection | Academic literature (Forrest, Hofmeyr, Dasgupta)                                                                        | `immune`                                 |
| Porter's Five Forces / Lean Canvas / JTBD      | Standard business frameworks                                                                                            | `competitive-analyzer`, `idea-validator` |
| OWASP Top 10                                   | [OWASP Foundation](https://owasp.org/www-project-top-ten/)                                                              | `security-reviewer`                      |
| ADR format                                     | [joelparkerhenderson/architecture-decision-record](https://github.com/joelparkerhenderson/architecture-decision-record) | `adr-writer`                             |
| Four-principle LLM coding guidelines           | [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876); Claude-Code packaging by [forrestchang/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (MIT) | `intent-discipline`                      |

## Community & Research

| Source                                                                                                     | Author                                             |
| ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| [claude-code-skills](https://github.com/notmanas/claude-code-skills)                                       | [@notmanas](https://github.com/notmanas)           |
| [EvoSkills: Self-Evolving Agent Skills via Co-Evolutionary Verification](https://arxiv.org/abs/2604.01687) | Zhang, Fan, Zou, Chen et al.                       |
| [Memento-Skills: Let Agents Design Agents](https://arxiv.org/abs/2603.18743)                               | Zhou, Guo, Liu, Yu et al.                          |
| [gitagent](https://github.com/open-gitagent/gitagent)                                                      | [@shreyaskapale](https://github.com/shreyaskapale) |

## Notes

- Remotion's license has commercial use restrictions. Lightpanda is AGPL-3.0 — armory wraps these as skills without distributing their binaries.
- Skills that are pure prompt engineering (e.g., `humanize`, `code-refiner`, `architecture-reviewer`) have no upstream library dependency.
- The `immune` skill's Cheatsheet/Immune pattern draws from Stephanie Forrest's original Artificial Immune Systems research and aligns with Memento-Skills' stateful-prompt concept (arXiv 2603.18743) — cheatsheet entries act as positive-pattern memory, antibodies as negative-pattern memory.
