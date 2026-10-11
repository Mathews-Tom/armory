---
name: opus-4-7-migration
description: 'Scan a repository for Opus-4.6-era patterns that break or degrade on Opus 4.7 — fixed-budget Extended Thinking parameters, retired model ID aliases, and prompts that assumed verbose default output or eager sub-agent delegation. Produces a categorized report with file:line references and migration actions. Triggers on: "opus 4.7 migration", "migrate to opus 4.7", "audit for opus 4.7", "opus 4.6 to 4.7", "scan for budget_tokens", "find retired model IDs", "adapt repo to opus 4.7". NOT for implementing migrations — this skill identifies candidates.'
metadata:
  version: 1.0.1
  category: review
  tags: [opus-4-7, migration, audit, model-refresh, budget-tokens]
  difficulty: intermediate
  phase: review
---

# Opus 4.7 Migration Scanner

Identify patterns in a repository that break or silently degrade when the Anthropic platform routes to Opus 4.7. Produces a categorized report with file:line references so a maintainer can plan a scoped migration PR rather than chasing symptoms after the fact.

## Reference Files

| File                          | Contents                                                      | Load When                          |
| ----------------------------- | ------------------------------------------------------------- | ---------------------------------- |
| `scripts/scan.py`             | Repo scanner producing a categorized findings report          | Always                             |
| `references/migration-map.md` | Per-category migration actions with before/after code samples | When a category returns findings   |

## When to Run

- Before upgrading a service or agent stack to Opus 4.7
- When an existing Anthropic SDK integration starts returning errors after the platform rolled out 4.7
- Periodically in a CI or weekly audit to prevent drift as the repo grows
- Before publishing a package that downstream users will run against 4.7

## Scope — What the Scanner Flags

The scanner is intentionally narrow. It reports three categories of **deterministic** patterns plus two **heuristic** categories that require manual review.

### Category A — Fixed-budget Extended Thinking (deterministic)

Opus 4.7 does not support Extended Thinking with a fixed `budget_tokens` value. Code that still passes `thinking={"type": "enabled", "budget_tokens": N}` fails or is ignored depending on SDK version.

Patterns flagged:

- Literal `budget_tokens=` in Python source
- `"budget_tokens"` keys inside `thinking={...}` dict literals
- `.thinking.budget_tokens` attribute references

### Category B — Retired model ID aliases (deterministic)

Dated or superseded Claude model aliases that no longer map to the current model. Using them is not broken but defeats the platform's model routing.

Patterns flagged:

- `claude-opus-4-5`, `claude-opus-4-4`, `claude-opus-4-3`, `claude-opus-4-2`, `claude-opus-4-1`, `claude-opus-4-0`
- `claude-sonnet-4-5`, `claude-sonnet-4-4`, `claude-sonnet-4-3`, `claude-sonnet-4-2`, `claude-sonnet-4-1`, `claude-sonnet-4-0`
- Dated format aliases: `claude-*-20250514`, `claude-*-20241022`, etc.
- `claude-3-*` family (superseded)

### Category C — Hardcoded model references outside config (deterministic)

Per the armory convention "model refs in config files only," any `claude-*` literal in `.py` / `.ts` / `.js` source code outside of `config.toml`, `.env`, or test-only sentinel strings is a candidate for extraction.

### Category D — Opus-4.6-verbosity-assuming prompts (heuristic)

Opus 4.7 is less default-verbose than 4.6. Prompts that relied on Opus 4.6's eager output or never needed a depth cue may produce shorter-than-expected responses on 4.7.

Patterns flagged (review required):

- Prompts requesting "detailed" or "comprehensive" output without matching length directive
- Prompts that exceeded Opus 4.6's defaults by relying on implicit verbosity
- Absence of first-turn specification completeness in agent prompts

### Category E — Non-explicit parallel sub-agent dispatch (heuristic)

Opus 4.7 delegates more judiciously than 4.6. Agent prompts instructing "spawn in parallel" without the phrase "in a single message" or stating sub-task independence often serialize on 4.7.

Patterns flagged (review required):

- `Spawn` + `parallel` language in agent prompts without "single message" or "independent"
- `subagent_type` dispatches in loops or sequential blocks where parallelism was intended

## Workflow

### Phase 1: Run the Scanner

Execute:

```bash
python3 scripts/scan.py /path/to/repo
```

Optional flags:

- `--categories A,B,C` — run only deterministic categories (skip heuristics)
- `--exclude tests/,vendor/,node_modules/` — path exclusion
- `--format json` — machine-readable output for CI integration
- `--exit-code` — exit 1 if any findings (useful for pre-commit hooks)

### Phase 2: Triage Findings

Group findings by category and sort by severity. Deterministic categories (A, B, C) are always actionable. Heuristic categories (D, E) require reading the surrounding prompt context before editing.

Priority order for a migration PR:

1. **Category A** first — these either error out or silently do the wrong thing on 4.7
2. **Category B** — rename to current logical aliases (`claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5`) or to the platform's auto-routing name
3. **Category C** — extract to `config.toml` per repo convention
4. **Category D, E** — manual review; fix those that materially change behavior

### Phase 3: Write the Migration PR

For each category with findings, apply the actions documented in `references/migration-map.md`. Prefer small PRs grouped by category over one large PR.

Pair the migration with:

- Unit tests or integration tests that exercise the updated code paths on Opus 4.7
- A short CHANGELOG entry noting "Opus 4.7 compatibility: removed `budget_tokens` from …"
- A rollout plan if the service is production-critical (`high`/`xhigh` effort level on the targeted agents)

## Output Format

The scanner produces a categorized report:

```
Opus 4.7 Migration Scan — /path/to/repo

Category A: Fixed-budget Extended Thinking       2 findings
  src/agent/reasoner.py:47   budget_tokens=8000
  src/agent/planner.py:112   thinking={"type": "enabled", "budget_tokens": 4096}

Category B: Retired model ID aliases             3 findings
  tests/test_agent.py:89     claude-opus-4-5
  config/dev.yaml:14         claude-sonnet-4-5
  src/llm/client.py:23       claude-sonnet-4-20250514

Category C: Hardcoded model refs outside config  1 finding
  scripts/bulk_process.py:8  DEFAULT_MODEL = "claude-sonnet-4-6"

Category D: Verbosity-assuming prompts          0 findings (heuristics disabled)
Category E: Non-explicit parallel dispatch      0 findings (heuristics disabled)

Total: 6 deterministic findings across 3 categories.
```

## Error Handling

| Condition                                    | Action                                                                |
| -------------------------------------------- | --------------------------------------------------------------------- |
| Repo path does not exist                     | Exit 2 with a clear error message                                     |
| No Python / TypeScript / JS files in repo    | Skip Category A, C; continue with B, D, E on other file types          |
| Regex error in scanner                        | Exit 3; file a bug with the offending pattern                          |
| False positives from Category B on changelogs | Exclude `CHANGELOG.md` by default; override with `--include-changelogs` |

## Limitations

- Categories D and E are heuristic and will produce false positives on carefully written prompts. Review before changing.
- The scanner does not exercise the code — it only does static pattern matching. A `budget_tokens` variable that is never passed to the Anthropic SDK will still be flagged.
- The scanner cannot detect runtime dynamic model selection (e.g., `model = config["models"][stage]`) — those need integration tests, not static analysis.
- Cross-language analysis is limited to Python, TypeScript, JavaScript, YAML, TOML, and Markdown. Other languages are skipped.

## Related

- `rules/adaptive-thinking-control/RULE.md` — prompt-level controls that replace fixed thinking budgets
- `skills/usage-audit/SKILL.md` — broader context-bloat audit (complementary)
- `skills/mcp-to-skill/SKILL.md` — MCP-to-skill conversion (relevant when migration surfaces heavy MCP usage)
