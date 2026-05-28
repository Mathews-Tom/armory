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
| **Mermaid**                              | [mermaid-js/mermaid](https://github.com/mermaid-js/mermaid)                                                   | MIT                       | `md-to-pdf`, `architecture-diagram`  |
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
