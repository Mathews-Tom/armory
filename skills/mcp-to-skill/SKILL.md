---
name: mcp-to-skill
description: 'Converts MCP servers into on-demand skills to cut context window usage, classifying each tool by replacement strategy and generating the skill package. Triggers on: "convert MCP", "MCP to skill", "reduce context size", "too many tools", "tool token bloat", "MCP migration".'
metadata:
  version: 1.1.1
  category: data
  tags: [mcp, skill-conversion, context-optimization, token-reduction]
  difficulty: intermediate
  phase: build
---

# MCP-to-Skill Converter

Convert MCP servers into on-demand skills. MCP tool schemas sit in the system prompt
on every turn (~500-2000 tokens per tool, regardless of whether they're used). Skills
cost zero tokens until loaded via `view`. For a typical setup with 4-5 MCP servers
exposing 20-40 tools, this reclaims 10,000-30,000 tokens of context per turn.

This matters because that's 10-30% of the context window burned before the conversation
even starts — and it compounds: every turn re-injects the full schema.

## Decision Framework: Convert vs. Keep

Not every MCP should become a skill. Apply this heuristic:

**Convert when** the MCP wraps a REST API (use curl/web_fetch), wraps a CLI tool
(gh, aws, gcloud — invoke directly), implements a reasoning/planning pattern
(capture as methodology), or when you use fewer than half its tools regularly.

**Keep as MCP when** it maintains persistent server-side state (DB connections,
WebSocket sessions), handles binary protocols or streaming, provides real-time event
subscriptions, or is tiny (1-2 tools, under 500 tokens — negligible overhead).

**Hybrid approach** — convert the stateless tools to a skill, keep stateful ones as
a slimmed-down MCP. This is often the sweet spot for large MCP servers.

---

## Conversion Workflow

Proceed through 5 phases. Present findings at each phase boundary and wait for
user confirmation before continuing. The user knows their usage patterns better
than any analysis can infer — lean on their input.

### Phase 1: Discovery

Acquire the MCP's tool definitions. Try these sources in order:

1. **Active session tools** — Inspect tools visible in the current conversation.
   Ask the user to identify which tools belong to the target MCP. This is the
   most reliable source because you see the exact schema consuming context.

2. **MCP config file** — Parse the user's MCP configuration:
   - Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Cursor: `.cursor/mcp.json` in the project root
   - Claude Code: `~/.claude/settings.json` or project `.mcp.json`
   - Config files give server names and connection details, not tool schemas.

3. **MCP server source code** — If the user points to a repo or local path, look for
   tool definitions: FastMCP `@mcp.tool()` decorators, SDK `server.setRequestHandler`,
   or similar patterns. Extract name, description, parameter schemas, return types.

4. **Package registry** — For published MCPs: `npm info <pkg>` or `pip show <pkg>`,
   then fetch the README or source to find tool definitions.

5. **User-provided schema** — Ask the user to paste or upload tool definitions.

Produce a structured inventory for each tool:

```text
Tool: tool_name
Description: what it does
Parameters: param list with types
Returns: return type/shape
Estimated tokens: rough schema size
```

Present this and ask: "Are these all the tools? Did I miss any?"

### Phase 2: Classification

Classify each tool along two dimensions. This classification drives the entire
replacement strategy, so getting it right matters.

**Replacement category:**

| Category        | Signals                                    | Replacement Approach    |
| --------------- | ------------------------------------------ | ----------------------- |
| `REST_API`      | HTTP endpoints, URL patterns, auth headers | curl or web_fetch       |
| `CLI_WRAPPER`   | Wraps known CLI (git, gh, aws, docker)     | Direct CLI invocation   |
| `LOGIC_PATTERN` | Structures reasoning, no external calls    | Methodology in SKILL.md |
| `FILE_OP`       | Reads/writes/transforms local files        | bash commands or Python |
| `STATEFUL`      | Maintains connections, sessions, caches    | Keep as MCP (flag it)   |
| `COMPOSITE`     | Orchestrates multiple sub-operations       | Multi-step workflow     |

**Usage frequency** — Ask the user directly:

| Frequency      | Action                                         |
| -------------- | ---------------------------------------------- |
| `ESSENTIAL`    | Must be in the generated skill                 |
| `NICE_TO_HAVE` | Include if the replacement is clean            |
| `RARELY_USED`  | Skip — user can fall back to manual invocation |

Present a classification table and ask: "Does this look right? Which tools do
you actually use regularly?"

Flag any `STATEFUL` tools explicitly — these are the ones that may not convert
cleanly, and the user should understand the trade-off.

### Phase 3: Replacement Strategy

For each tool marked ESSENTIAL or NICE_TO_HAVE, design the concrete replacement.

**Read `references/replacement-patterns.md`** — it contains detailed patterns for
each category: REST API wrappers, CLI mappings, logic patterns, file operations,
stateful workarounds, composite workflows, auth patterns, and output parsing.

For each tool, determine:

- The exact command (curl, CLI, or methodology) that replaces it
- How MCP tool parameters map to command arguments
- How to parse the output into a useful format
- Common error cases and their fixes

Also identify **multi-tool workflows** — sequences of tools the user commonly
chains. These become "Common Workflows" sections in the generated skill, which
is where skills often provide more value than the MCP because workflows make
the multi-step pattern explicit rather than relying on the agent to discover it.

Ask the user:

- "What CLI tools are available in your environment?"
- "Are there common sequences where you use multiple tools together?"
- "How do you handle authentication?" (env vars, config files, OAuth tokens)

If the target environment is unclear, **read `references/environment-guide.md`**
for environment-specific constraints (Claude.ai vs Claude Code vs Cursor vs API).

### Phase 4: Generation

Generate the complete skill package.

**Read `references/skill-template.md`** for the output template, sizing guide,
frontmatter checklist, and quality checklist.

The generated skill structure:

```text
skill-name/
  SKILL.md
    Frontmatter (name, description with aggressive triggers)
    Quick Reference table (old tool name to new command mapping)
    Prerequisites (CLI tools, env vars, auth setup)
    Core Operations (one subsection per essential tool)
    Common Workflows (multi-step patterns)
    Error Handling and Troubleshooting
  references/                        (only if SKILL.md exceeds ~400 lines)
    api-reference.md                 (overflow for complex tool replacements)
```

Generation rules — these exist to ensure the generated skill actually triggers
and works correctly in practice:

- **Frontmatter description must be pushy.** Include original MCP tool names as
  trigger phrases, the service name, action verbs, and explicit "Use this skill
  when..." language. Skills undertrigger by default; compensate with a broad net.
- **Quick Reference table at the top.** Users and agents scan this first.
- **Each Core Operation shows** what it replaces, the replacement command, parameter
  mapping, a concrete example, and error handling.
- **Keep SKILL.md under 500 lines.** Move detailed patterns to references/ if needed.
- **Auth via env vars or config, never hardcoded.** Generated skills must not embed
  credentials.
- **Prerequisites include install commands** for every required CLI tool.

### Phase 5: Validation

After generating, validate the skill and estimate savings.

**Run the token estimation** using `scripts/estimate_tokens.py`:

```bash
python3 scripts/estimate_tokens.py --mcp-tools TOOL_COUNT --avg-schema-chars AVG_CHARS
```

This shows before/after token savings per turn and across a typical conversation.

**Generate 2-3 test scenarios** — realistic prompts that would trigger the new skill
and show the replacement commands in action. Present them to the user.

**Migration checklist:**

- Generated skill reviewed and any edits applied
- Required CLI tools installed and authenticated
- Skill placed in the target skills directory
- MCP removed from configuration
- Test scenarios validated

**Validate the generated skill structure:**

Verify the generated skill directory contains a valid SKILL.md with frontmatter (`name`, `description`),
and that all file references in the body resolve to existing files within the skill directory.

Present the complete package to the user. Offer to iterate on any section.

---

## Limitations

Conversions succeed best for stateless tools and REST/CLI wrappers. Inherent constraints:

- **Stateful tools don't convert cleanly** — MCPs maintaining persistent connections,
  sessions, or real-time subscriptions should stay as MCPs. See "Keep as MCP when" in
  the Decision Framework.
- **Binary protocols and streaming** — If the MCP handles binary data or WebSocket streams,
  conversion requires additional infrastructure outside Claude's scope.
- **API fabrication risk** — Replacement strategy only works if the underlying API or CLI
  is known. Unknown APIs must be researched first; guessing produces broken skills.
- **Auth complexity** — Conversions with multi-step OAuth or credential management are
  possible but require explicit env var and config setup. See Phase 3 for auth patterns.
- **Partial coverage acceptable** — A 90% conversion with one stateful MCP remaining is
  preferable to a broken attempt at 100%. Acknowledge trade-offs honestly.

---

## Constraints

These exist to prevent common failure modes in generated skills:

- **Never fabricate API endpoints.** If the underlying API is unknown, ask the user
  or research the MCP's source code. Guessing at URLs produces broken skills.
- **Acknowledge limitations honestly.** A partial conversion (80% of tools) with one
  remaining small MCP is better than a broken skill that claims full coverage.
- **Test mentally before presenting.** Trace through each replacement command: would it
  actually work? Does curl need specific headers? Does the CLI tool require auth setup?
- **Preserve error handling quality.** Many MCPs provide helpful error messages. The
  generated skill should include equivalent troubleshooting guidance.
