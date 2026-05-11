---
name: project-context-setup
description: 'Scaffolds per-repository agent context so coding agents share the same issue tracker rules, triage label vocabulary, domain glossary, ADR layout, and handoff conventions. Triggers on: "set up project context", "configure agent docs", "create CONTEXT.md", "setup agent workflow", "agent issue tracker setup", "triage labels", "domain glossary for agents". Use when a repo needs durable context files before planning, triage, debugging, TDD, architecture review, or multi-agent implementation.'
metadata:
  version: 1.0.0
  category: development
  tags: [agent-context, project-setup, domain-glossary, triage]
  difficulty: intermediate
  phase: define
---

# Project Context Setup

Scaffold the repo-local context files that make agent workflows consistent across sessions:
issue tracker rules, triage labels, domain glossary layout, ADR layout, agent brief format,
and out-of-scope memory.

## When To Use

| Use this skill | Use another package |
| -------------- | ------------------- |
| A repo lacks `docs/agents/` context files | `adr-writer` for one architecture decision |
| Agents need consistent domain vocabulary | `task-decomposer` for an already-scoped feature |
| Triage or issue publishing needs label conventions | `github` for direct GitHub CLI operations |
| Multi-agent work needs durable issue briefs | `handoff` for session-local continuation notes |

## Reference Files

| File | Contents | Load When |
| ---- | -------- | --------- |
| `references/context-format.md` | `CONTEXT.md` and `CONTEXT-MAP.md` glossary format | Creating or editing domain docs |
| `references/agent-brief.md` | Durable `ready-for-agent` issue brief contract | Preparing issue handoff |
| `references/out-of-scope.md` | Persistent memory for rejected enhancements | Triage includes `wontfix` decisions |

## Core Workflow

### 1. Explore

Inspect the actual repo state before writing:

- `git remote -v` and `.git/config` for issue tracker hints
- root `AGENTS.md` and `CLAUDE.md`
- root `CONTEXT.md` and `CONTEXT-MAP.md`
- `docs/adr/` and context-scoped ADR directories
- existing `docs/agents/`
- existing `.out-of-scope/`

Report what exists and what is missing. Do not overwrite existing files blindly.

### 2. Choose Setup Values

Resolve these values with the user or from clear repo evidence:

| Decision | Default | Output |
| -------- | ------- | ------ |
| Issue tracker | GitHub if a GitHub remote exists, otherwise local markdown | `docs/agents/issue-tracker.md` |
| Triage labels | Canonical labels equal role names | `docs/agents/triage-labels.md` |
| Domain docs | Single root context | `docs/agents/domain.md` |
| Agent instructions file | Existing `AGENTS.md`, else existing `CLAUDE.md` | Updated `## Agent context` block |

If both `AGENTS.md` and `CLAUDE.md` exist, update `AGENTS.md` for cross-agent portability.
If neither exists, ask before creating one.

### 3. Write Context Files

Create or update these files:

```text
docs/agents/
├── issue-tracker.md
├── triage-labels.md
└── domain.md
```

Use these conventions:

- Keep issue tracker instructions operational: exact CLI, label mutation policy, and whether agents may comment or close issues.
- Map canonical triage roles to real labels. Do not create duplicate labels when the repo already has equivalents.
- Document whether the repo uses a single root `CONTEXT.md` or `CONTEXT-MAP.md` with per-context glossaries.
- Record ADR lookup rules. Use `docs/adr/` for global decisions and context-local `docs/adr/` directories where present.

### 4. Add Agent Context Block

Add or update this block in the chosen instructions file:

```markdown
## Agent context

### Issue tracker

See `docs/agents/issue-tracker.md` for where issues live and which operations agents may perform.

### Triage labels

See `docs/agents/triage-labels.md` for canonical triage roles and their concrete label strings.

### Domain docs

See `docs/agents/domain.md` for `CONTEXT.md`, `CONTEXT-MAP.md`, and ADR lookup rules.
```

Update the existing block in place if it already exists. Do not append duplicates.

### 5. Optional Domain Glossary

Create `CONTEXT.md` only when the user has resolved at least one domain term. Use
`references/context-format.md`. Do not fill it with generic programming concepts.

Create `CONTEXT-MAP.md` only for multi-context repos where separate glossaries are needed.

## Verification

- `docs/agents/issue-tracker.md` exists and states the tracker, allowed operations, and required tools.
- `docs/agents/triage-labels.md` maps `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`.
- `docs/agents/domain.md` states single-context or multi-context layout and ADR lookup rules.
- The chosen instructions file contains exactly one `## Agent context` block.
- Existing user-authored content outside that block is preserved.
