---
name: usage-audit
description: >
  Audit a Claude Code setup for token waste and context bloat. Runs /context
  for real overhead, then audits MCP servers, CLAUDE.md rules, installed
  skills, settings.json, and file permissions against five bloat filters.
  Returns a health score with specific cuts. Triggers on: "audit my context",
  "usage audit", "context audit", "token audit", "why is Claude slow",
  "context bloat", "cleanup my setup", "check my CLAUDE.md", "audit settings".
  Use when a session feels heavy, after installing new packages, or on a
  recurring cadence to catch drift. NOT for auditing a codebase (use
  codebase-auditor) or a single package (use package-evaluator).
metadata:
  version: 1.0.0
  category: review
  tags: [context, tokens, audit, claude-code, bloat]
  difficulty: intermediate
---

# Usage Audit

Bloated context costs twice: you burn usage limits faster and output quality
drops because models attend most to the start and end of context. This skill
finds the waste and tells you what to cut.

Credit: adapted from the `context-audit` skill in the Claude Code Context
Cleanup Guide (2026). Armory port adds package-aware checks and treats the
scoring rubric as an overridable reference, not a verdict.

## Step 1: Get /context Data

Check the conversation for recent `/context` output. If the user has not run
it in this session, ask:

> "Run `/context` in this terminal and paste the output. I can't run slash
> commands myself — once I can see the breakdown I'll audit everything it
> flags."

**STOP HERE.** Do not proceed to Step 2 until real `/context` data is
available. The breakdown determines what to audit and in what order. Without
it, the audit is guessing. Output the message above and wait.

## Step 2: Audit What's Bloated

Work the categories from largest to smallest in the `/context` output. Run
independent checks in parallel.

### MCP Servers

Each connected server loads full tool definitions into context every turn
(~15,000-20,000 tokens each), whether you invoke a tool or not.

- Count configured servers in `settings.json` and `~/.claude/settings.json`.
- Report total MCP overhead from `/context`.
- Flag any server with a CLI equivalent (Playwright, GitHub, Google Workspace,
  Notion, Slack, etc.) — the CLI costs zero tokens when idle.
- Cross-reference installed armory packages: if `mcp-to-skill` is installed,
  recommend it explicitly for the heaviest server.

### CLAUDE.md Files

Read every CLAUDE.md in scope (project root, `.claude/`, `~/.claude/`). For
each file: count lines, then test every rule against the five filters.

| Filter | Flag when... |
|--------|-------------|
| **Default** | Claude already does this without being told ("write clean code", "handle errors") |
| **Contradiction** | Conflicts with another rule in the same or a different file |
| **Redundancy** | Repeats something already covered elsewhere |
| **Bandaid** | Added to fix one specific bad output, not improve outputs generally |
| **Vague** | Interpreted differently every time ("be natural", "use good tone") |

If a CLAUDE.md exceeds 200 lines, check for progressive-disclosure
opportunities: rules that only apply to specific tasks (API conventions,
deploy steps, testing) should move to reference files with one-line pointers
from the core file. A lean CLAUDE.md under 200 lines with universal context
is fine as a single file — do not split for the sake of splitting.

### Rules Packages (armory-specific)

Armory `rules/` packages load into every session like CLAUDE.md does — they
are the real silent base tax. Higher priority than skill bloat.

- Enumerate installed rules packages via `~/.claude/settings.json` or the
  armory installer registry if present.
- For each rules package, read its `RULE.md` body, count lines, apply the
  same five filters.
- Flag any rules package over 300 lines. These hit every turn.

### Installed Skills

Scan `~/.claude/skills/*/SKILL.md` and any project-local skills. For each:

- **Measure SKILL.md body lines only** — do NOT count files under
  `references/`, `scripts/`, or `evals/`. Those load on demand, not on
  trigger. Penalizing total package LOC misattributes cost.
- Flag SKILL.md body > 200 lines (warn) or > 500 lines (critical).
- Run the five filters on skill instructions: restated goals, hedging ("you
  may want to"), synonymous instructions ("be concise" + "keep it short" +
  "don't be verbose").
- **Frontmatter description audit:** count words in each skill's `description`
  field. Flag any over 60 words. Skill descriptions load into the router on
  every session and should be trigger-focused, not prose.

### Settings

Check `settings.json` for these keys:

| Setting | Flag if | Recommended |
|---------|---------|-------------|
| `autocompact_percentage_override` | Missing or > 80 | `75` |
| `env.BASH_MAX_OUTPUT_LENGTH` | At default (30-50K) | `150000` |

### File Permissions

Check `permissions.deny` in `settings.json`. If missing, inspect the project
and flag bloat directories that should be denied:

| If this exists... | Should deny... |
|-------------------|---------------|
| `package.json` | `node_modules`, `dist`, `build`, `.next`, `coverage` |
| `Cargo.toml` | `target` |
| `go.mod` | `vendor` |
| `pyproject.toml` / `requirements.txt` | `__pycache__`, `.venv`, `*.egg-info` |

## Step 3: Score and Report

The rubric below is a **reference default**, not gospel. A "reference" skill
that wraps a large CLI surface (e.g., `github`, `agent-builder`) may
legitimately exceed line thresholds — judge the body, not the file count.
Users can override any deduction in their project CLAUDE.md.

Score starts at 100. Deduct per issue:

| Issue | Points |
|-------|--------|
| CLAUDE.md > 200 lines | -10 |
| CLAUDE.md > 500 lines | -20 |
| Rules package > 300 lines (body) | -10 each |
| Per 5 rules flagged by filters | -5 |
| Contradictions between files | -10 |
| Missing `autocompact_percentage_override` | -10 |
| Missing `BASH_MAX_OUTPUT_LENGTH` override | -5 |
| Skill body > 200 lines | -5 each |
| Skill body > 500 lines | -10 each |
| Skill description > 60 words | -2 each |
| Per connected MCP server with CLI equivalent | -5 each |
| No `permissions.deny` and bloat dirs exist | -10 |

Floor at 0. Output this format:

```
# Usage Audit

Score: {N}/100 [{CLEAN|NEEDS WORK|BLOATED|CRITICAL}]

## Context Breakdown (from /context)
{Paste the key numbers}

## Issues Found

### [{CRITICAL|WARNING|INFO}] {Category}
{What's wrong}
Fix: {One-line actionable fix}

### Rules to Cut
{Each flagged rule: quoted text, which filter, one-line reason}

### Conflicts
{Contradictions between files, with paths}

## Top 3 Fixes
1. {Highest-impact fix}
2. {Second}
3. {Third}
```

Score labels: 90-100 CLEAN, 70-89 NEEDS WORK, 50-69 BLOATED, 0-49 CRITICAL.
Severity: CRITICAL > 10pts, WARNING 5-10pts, INFO < 5pts.

## Step 4: Offer to Fix

After the report, offer targeted fixes:

> "Want me to apply any of these? I can:
> - Add missing `settings.json` keys (`autocompact_percentage_override`, `BASH_MAX_OUTPUT_LENGTH`)
> - Add `permissions.deny` rules for detected bloat directories
> - Show a cleaned-up CLAUDE.md diff with flagged rules removed
> - Compress fat skill frontmatter descriptions
> - Recommend specific MCP servers to disconnect this session"

Auto-apply the settings and permissions changes (safe, reversible). Show a
diff and wait for confirmation before modifying any instruction file
(CLAUDE.md, RULE.md, SKILL.md) — instruction edits are load-bearing and
users need final say.
