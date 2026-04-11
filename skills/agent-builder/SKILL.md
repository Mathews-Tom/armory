---
name: agent-builder
description: 'Build AI agents and automate Claude Code programmatically via the Claude Agent SDK and headless CLI mode. Covers Python SDK, claude -p, SDK MCP servers, hooks, sessions. Triggers on: "build an agent", "agent SDK", "headless mode", "automate Claude", "programmatic agent".'
metadata:
  version: 1.1.1
  category: development
  tags: [agent-sdk, headless, automation, mcp]
  difficulty: intermediate
  phase: build
---

# Agent Builder - Claude SDK & CLI Expert

**Triggers:**

- "build agent", "create agent", "agent sdk", "claude sdk"
- "headless mode", "programmatic", "cli command"
- "claude -p", "query programmatically"
- "custom tools", "mcp server", "sdk mcp"
- "claude code api", "agent options"

---

## Prefer Claude Code Headless Mode

This skill covers Claude Code's headless mode and the Agent SDK — not the raw Anthropic API.

```text
Preferred: Claude Code CLI headless mode (claude -p)
Preferred: Claude Agent SDK (wraps Claude Code CLI)
Avoid:     Raw Anthropic API (anthropic.Anthropic())
Avoid:     Direct API calls with API keys
```

**Why this matters:**

- The Agent SDK wraps the Claude Code CLI — it does not use the raw Anthropic API
- Authentication comes from existing `~/.claude/` config — no API keys needed
- All settings, MCP servers, and configuration inherit from your Claude Code setup
- You get Claude Code's full agent loop, tools, and context management

**Rule:** If code uses `anthropic.Anthropic()`, `anthropic.messages.create()`, or requires `ANTHROPIC_API_KEY`, that is the wrong approach. Use `claude -p` or `claude_agent_sdk` instead.

---

## Core Capabilities

1. **Claude Agent SDK Python** - Programmatic agent creation with custom tools and hooks (wraps Claude Code CLI)
2. **Headless/Print Mode** - Run Claude Code from CLI, scripts, CI/CD (`claude -p`)
3. **CLI Reference** - All commands, flags, and configuration options

**All use Claude Code's existing authentication from `~/.claude/` — no API keys required.**

---

## Documentation Sources

- **Agent SDK**: https://github.com/anthropics/claude-agent-sdk-python
- **Headless Mode**: https://code.claude.com/docs/en/headless
- **CLI Reference**: https://code.claude.com/docs/en/cli-reference

---

## Workflow

1. **Understand the requirement** - What type of agent/automation is needed?
2. **Check dependencies** - Verify Python version, packages, Claude Code installation
3. **Reference live docs** - Fetch relevant documentation if details are unclear
4. **Build confidently** - Write production-ready code with proper error handling
5. **Test immediately** - Run and validate the implementation

---

## Reference Files

Load only the reference file relevant to the current task.

| Task | Load |
|---|---|
| Distinguishing raw Anthropic API from Claude Code SDK patterns | `references/api-vs-sdk.md` |
| Writing a Python agent with the Agent SDK (install, query, client, tools, hooks, errors) | `references/sdk-python.md` |
| Using headless `claude -p` mode (basic, JSON schema, streaming, tool approval, sessions, system prompts) | `references/headless-cli.md` |
| CLI commands, flags table, dynamic subagents, permission rule syntax | `references/cli-reference.md` |
| Use-case templates: CI/CD pipeline, code review, custom analysis tool, database query agent | `references/use-cases.md` |
| Agent SDK and CLI/Headless best practices | `references/best-practices.md` |
| Complete end-to-end agent example (tools + hooks + client) | `references/example-agent.md` |
| Output format conventions for produced artifacts | `references/output-format.md` |

---

## Security

- Do not use `--dangerously-skip-permissions` in production
- Validate inputs in custom tools
- Use permission rules to block destructive commands
- Set budget limits with `--max-budget-usd`
- Implement hooks for sensitive operations
- Review allowed tools before automation

---

## Quick Decision Tree

**Need to...**

- Run one-off query → `claude -p "query"`
- Build custom agent → Agent SDK with `ClaudeSDKClient`
- Add custom tools → SDK MCP server with `@tool` decorator
- Control execution → Hooks with `HookMatcher`
- Stream responses → `--output-format stream-json`
- Get structured data → `--json-schema`
- Continue conversation → `--continue` or `--resume`
- Run in CI/CD → `claude -p` with `--allowedTools`
- Integrate with app → Python SDK with `query()` or `ClaudeSDKClient`

---

## When to Fetch Docs

Fetch live documentation when:

- API signatures or parameters are unclear
- New features or flags are mentioned
- Error messages reference unknown configuration
- Implementing complex hooks or MCP servers
- User asks about specific capabilities

Use `WebFetch` tool to pull latest documentation from source URLs.

---

## Implementation Checklist

Before writing code:

- [ ] **Verify:** Using Claude Code headless mode (`claude -p` or `claude_agent_sdk`) — not raw Anthropic API
- [ ] **Verify:** No API keys in code — authentication comes from `~/.claude/` config
- [ ] Confirm Python version (3.10+)
- [ ] Verify Claude Code CLI installation (`which claude`)
- [ ] Check required packages with `uv pip list`
- [ ] Understand the specific use case
- [ ] Determine if SDK or CLI approach is needed

After writing code:

- [ ] **Verify:** Code uses `claude_agent_sdk` or `claude -p` — not `anthropic.Anthropic()`
- [ ] **Verify:** No `ANTHROPIC_API_KEY` or `api_key=` parameters in code
- [ ] Add error handling for all SDK exceptions
- [ ] Test with actual Claude Code installation
- [ ] Validate tool permissions and security
- [ ] Set appropriate limits (turns, budget)
- [ ] Document custom tools and their purposes

---

## Skill Invocation

This skill provides:

- Complete Agent SDK implementation guidance
- Headless/CLI command construction
- Custom tool creation with MCP servers
- Hook implementation for control flow
- Security best practices
- Live documentation fetching when needed

Ask specific questions about building agents, running headless commands, or CLI usage.

---

## Limitations

- The Agent SDK is Python-only (Python 3.10+); no JavaScript or other language bindings are covered here.
- Requires Claude Code CLI installed and authenticated via `~/.claude/` before any SDK or headless usage works.
- This skill does not cover raw Anthropic API usage (`anthropic.Anthropic()`); see the Anthropic API docs for that.
- Agent processes launched via the SDK are ephemeral by default; session persistence requires explicit `--resume` or session ID capture.
- MCP server patterns in this skill use stdio transport; HTTP-based MCP transports require separate configuration not covered here.
