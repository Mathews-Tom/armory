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

Build AI agents, run Claude Code programmatically, and execute CLI operations using:

1. **Claude Agent SDK Python** - Programmatic agent creation with custom tools and hooks (wraps Claude Code CLI)
2. **Headless/Print Mode** - Run Claude Code from CLI, scripts, CI/CD (`claude -p`)
3. **CLI Reference** - All commands, flags, and configuration options

**All of these use Claude Code's existing authentication from `~/.claude/` — no API keys required.**

---

## Raw API vs Claude Code SDK Patterns

### Raw Anthropic API — do not use for agent automation

```python
# Avoid — this is the raw Anthropic API, not Claude Code
from anthropic import Anthropic

client = Anthropic(api_key="sk-...")  # Requires separate API key
response = client.messages.create(   # Bypasses agent loop
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "Hello"}]
)
```

**Problems:**

- Requires separate API key authentication
- Bypasses Claude Code's agent loop, tools, and context management
- No access to Read, Write, Bash tools
- No MCP server integration
- No session persistence or resumption
- Must handle tool calling manually

### Claude Code Headless Mode — preferred

```python
# Preferred — Agent SDK wraps Claude Code CLI
from claude_agent_sdk import query, ClaudeAgentOptions
import anyio

async def main():
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Bash"],  # Full tool access
        permission_mode="acceptEdits"
    )
    # Uses ~/.claude/ config — no API key needed
    async for message in query(prompt="Analyze this codebase", options=options):
        print(message)

anyio.run(main)
```

**OR via CLI:**

```bash
# Claude Code headless mode
claude -p "Analyze this codebase" \
  --allowedTools "Read,Write,Bash" \
  --output-format json
```

**Benefits:**

- Uses existing `~/.claude/` authentication
- Full Claude Code agent loop with all tools
- MCP server integration
- Session persistence and resumption
- Context management handled automatically

---

## Documentation Sources

Always fetch current documentation when needed:

- **Agent SDK**: https://github.com/anthropics/claude-agent-sdk-python
- **Headless Mode**: https://code.claude.com/docs/en/headless
- **CLI Reference**: https://code.claude.com/docs/en/cli-reference

## Workflow

When invoked:

1. **Understand the requirement** - What type of agent/automation is needed?
2. **Check dependencies** - Verify Python version, packages, Claude Code installation
3. **Reference live docs** - Fetch relevant documentation if details are unclear
4. **Build confidently** - Write production-ready code with proper error handling
5. **Test immediately** - Run and validate the implementation

---

## 1. Agent SDK Python Patterns

### Installation & Setup

**The Agent SDK wraps Claude Code CLI — it does not use the raw Anthropic API.**

```bash
# Install Claude Code CLI first (if not already installed)
curl -fsSL https://claude.ai/install.sh | bash

# Install the Agent SDK (wraps Claude Code CLI)
uv pip install claude-agent-sdk  # Python 3.10+
```

**Authentication:** Uses existing `~/.claude/` config — no API keys needed.

### Quick Start - Simple Query

**This uses Claude Code CLI under the hood — not the raw Anthropic API.**

```python
import anyio
from claude_agent_sdk import query

async def main():
    # Uses Claude Code CLI — inherits auth from ~/.claude/
    async for message in query(prompt="What is 2 + 2?"):
        print(message)

anyio.run(main)
```

**No API keys needed** — authentication comes from your Claude Code installation.

### Interactive Client

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

options = ClaudeAgentOptions(
    system_prompt="You are a helpful assistant",
    max_turns=10,
    allowed_tools=["Read", "Write", "Bash"],
    permission_mode='acceptEdits',
    cwd="/path/to/project"
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Analyze this codebase")
    async for msg in client.receive_response():
        if msg.type == "assistant":
            for block in msg.content:
                if block.type == "text":
                    print(block.text)
```

### Custom Tools - SDK MCP Server

```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("greet", "Greet a user by name", {"name": str})
async def greet_user(args):
    return {
        "content": [{"type": "text", "text": f"Hello, {args['name']}!"}]
    }

@tool("fetch_data", "Fetch data from API", {"endpoint": str})
async def fetch_data(args):
    # Implementation
    return {"content": [{"type": "text", "text": f"Data from {args['endpoint']}"}]}

server = create_sdk_mcp_server(
    name="custom-tools",
    version="1.0.0",
    tools=[greet_user, fetch_data]
)

options = ClaudeAgentOptions(
    mcp_servers={"tools": server},
    allowed_tools=["mcp__tools__greet", "mcp__tools__fetch_data"]
)
```

### Hooks - Deterministic Control

```python
from claude_agent_sdk import HookMatcher

async def validate_bash_command(input_data, tool_use_id, context):
    if input_data["tool_name"] != "Bash":
        return {}

    command = input_data["tool_input"].get("command", "")
    forbidden = ["rm -rf", "dd if=", "mkfs"]

    for pattern in forbidden:
        if pattern in command:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"Forbidden: {pattern}",
                }
            }
    return {}

options = ClaudeAgentOptions(
    allowed_tools=["Bash"],
    hooks={
        "PreToolUse": [
            HookMatcher(matcher="Bash", hooks=[validate_bash_command]),
        ],
    }
)
```

### Error Handling

```python
from claude_agent_sdk import (
    CLINotFoundError,
    CLIConnectionError,
    ProcessError,
    CLIJSONDecodeError,
)

try:
    async for message in query(prompt="Hello"):
        pass
except CLINotFoundError:
    print("Install Claude Code: curl -fsSL https://claude.ai/install.sh | bash")
except ProcessError as e:
    print(f"Process failed: {e.exit_code}")
except CLIJSONDecodeError as e:
    print(f"JSON parse error: {e}")
```

---

## 2. Headless/Print Mode CLI

### Basic Usage

```bash
# Simple query
claude -p "What does the auth module do?"

# Structured JSON output
claude -p "Summarize this project" --output-format json

# Extract specific data with jq
claude -p "Summarize this project" --output-format json | jq -r '.result'
```

### Structured Output with JSON Schema

```bash
claude -p "Extract function names from auth.py" \
  --output-format json \
  --json-schema '{
    "type": "object",
    "properties": {
      "functions": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["functions"]
  }' | jq '.structured_output'
```

### Streaming Responses

```bash
# Stream with full events
claude -p "Explain recursion" \
  --output-format stream-json \
  --verbose \
  --include-partial-messages

# Extract only text deltas with jq
claude -p "Write a poem" \
  --output-format stream-json \
  --verbose \
  --include-partial-messages | \
  jq -rj 'select(.type == "stream_event" and .event.delta.type? == "text_delta") | .event.delta.text'
```

### Auto-Approve Tools

```bash
# Allow specific tools without prompting
claude -p "Run tests and fix failures" \
  --allowedTools "Bash,Read,Edit"

# Git operations with prefix matching
claude -p "Review staged changes and commit" \
  --allowedTools "Bash(git diff *)" "Bash(git log *)" "Bash(git status *)" "Bash(git commit *)"
```

### Continue Conversations

```bash
# First request
claude -p "Review this codebase for performance issues"

# Continue most recent
claude -p "Focus on database queries" --continue

# Resume specific session
session_id=$(claude -p "Start review" --output-format json | jq -r '.session_id')
claude -p "Continue review" --resume "$session_id"
```

### Custom System Prompts

```bash
# Append to default prompt (recommended)
claude -p "Review this PR" \
  --append-system-prompt "You are a security engineer. Focus on vulnerabilities."

# Replace entire prompt (full control)
claude -p "Analyze code" \
  --system-prompt "You are a Python expert who only writes type-annotated code"

# Load from file
claude -p "Review code" \
  --append-system-prompt-file ./prompts/style-rules.txt
```

---

## 3. CLI Commands & Flags Reference

### Common Commands

```bash
# Interactive REPL
claude
claude "explain this project"

# Headless/print mode
claude -p "query"
cat file | claude -p "analyze"

# Continue conversations
claude -c                          # most recent
claude -c -p "follow-up"          # continue via SDK
claude -r "session-id"            # resume specific

# Update
claude update

# MCP configuration
claude mcp
```

### Essential Flags

| Flag                | Purpose                  | Example                           |
| ------------------- | ------------------------ | --------------------------------- |
| `--allowedTools`    | Auto-approve tools       | `--allowedTools "Bash,Read,Edit"` |
| `--disallowedTools` | Block tools              | `--disallowedTools "Bash(rm *)"`  |
| `--tools`           | Restrict available tools | `--tools "Bash,Edit,Read"`        |
| `--model`           | Set model                | `--model sonnet`                  |
| `--max-turns`       | Limit turns              | `--max-turns 5`                   |
| `--max-budget-usd`  | Cost limit               | `--max-budget-usd 2.00`           |
| `--output-format`   | Output format            | `--output-format json`            |
| `--json-schema`     | Structured output        | `--json-schema '{...}'`           |
| `--permission-mode` | Start in mode            | `--permission-mode plan`          |
| `--add-dir`         | Additional dirs          | `--add-dir ../lib ../apps`        |
| `--agents`          | Custom subagents         | `--agents '{...}'`                |
| `--chrome`          | Browser automation       | `--chrome`                        |
| `--verbose`         | Full logging             | `--verbose`                       |

### Dynamic Subagents

```bash
claude --agents '{
  "code-reviewer": {
    "description": "Expert code reviewer",
    "prompt": "Focus on code quality, security, best practices",
    "tools": ["Read", "Grep", "Glob"],
    "model": "sonnet"
  },
  "debugger": {
    "description": "Debugging specialist",
    "prompt": "Analyze errors, identify root causes",
    "maxTurns": 10
  }
}'
```

### Permission Rule Syntax

```bash
# Tool name only
--allowedTools "Read" "Write"

# With argument pattern (exact match)
--allowedTools "Bash(git status)"

# With prefix matching (note the space before *)
--allowedTools "Bash(git diff *)" "Bash(git log *)"

# Block destructive patterns
--disallowedTools "Bash(rm -rf *)" "Bash(dd *)"
```

---

## Common Use Cases

### 1. CI/CD Test & Fix Pipeline

```python
from claude_agent_sdk import query, ClaudeAgentOptions

options = ClaudeAgentOptions(
    allowed_tools=["Bash", "Read", "Edit"],
    permission_mode="acceptEdits",
    max_turns=20,
    max_budget_usd=5.0
)

async for msg in query(
    prompt="Run the test suite. Fix any failures. Re-run until all pass.",
    options=options
):
    # Process messages
    pass
```

### 2. Automated Code Review

```bash
#!/bin/bash
gh pr diff "$1" | claude -p \
  --append-system-prompt "Security review: check for OWASP top 10, injection, XSS, auth issues" \
  --allowedTools "Read" \
  --output-format json \
  --max-turns 3 | jq -r '.result'
```

### 3. Custom Analysis Tool

```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeSDKClient, ClaudeAgentOptions

@tool("analyze_file", "Analyze file metrics", {"path": str})
async def analyze_file(args):
    # Custom analysis logic
    with open(args["path"]) as f:
        lines = len(f.readlines())
    return {"content": [{"type": "text", "text": f"File has {lines} lines"}]}

server = create_sdk_mcp_server(name="analyzer", version="1.0.0", tools=[analyze_file])

options = ClaudeAgentOptions(
    mcp_servers={"analyzer": server},
    allowed_tools=["mcp__analyzer__analyze_file", "Read"],
    system_prompt="You are a code quality analyzer"
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Analyze all Python files in this directory")
    async for msg in client.receive_response():
        print(msg)
```

### 4. Database Query Agent

```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("query_db", "Execute SQL query", {"query": str})
async def query_database(args):
    # Safe parameterized query execution
    result = execute_query(args["query"])
    return {"content": [{"type": "text", "text": str(result)}]}

@tool("get_schema", "Get database schema", {})
async def get_schema(args):
    schema = fetch_schema()
    return {"content": [{"type": "text", "text": schema}]}

server = create_sdk_mcp_server(
    name="db-tools",
    version="1.0.0",
    tools=[query_database, get_schema]
)
```

---

## Best Practices

### Agent SDK

- Use `claude_agent_sdk` instead of the raw Anthropic API (`anthropic.Anthropic()`)
- No API keys needed — uses Claude Code's `~/.claude/` config
- Use `anyio.run()` for async execution
- Handle errors explicitly with try/except blocks
- Set `max_turns` and `max_budget_usd` for safety
- Use hooks for deterministic control flow
- Prefer SDK MCP servers over external processes for custom tools
- Set `permission_mode='acceptEdits'` for automation

### CLI/Headless

- Use `--output-format json` for parsing responses
- Combine with `jq` for structured data extraction
- Set `--max-turns` to prevent runaway costs
- Use `--allowedTools` with specific patterns for security
- Capture `session_id` for conversation continuation
- Use `--verbose` for debugging

### Security

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

## Example: Complete Agent

**This uses Claude Code CLI via the Agent SDK — not the raw Anthropic API.**

```python
import anyio
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    HookMatcher,
)
# Using claude_agent_sdk (wraps Claude Code CLI)

# Custom tool
@tool("get_config", "Get app configuration", {})
async def get_config(args):
    return {"content": [{"type": "text", "text": "Config: {...}"}]}

# Hook for validation
async def validate_edit(input_data, tool_use_id, context):
    if input_data["tool_name"] != "Edit":
        return {}

    file_path = input_data["tool_input"].get("file_path", "")
    if file_path.endswith(".env"):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Cannot edit .env files",
            }
        }
    return {}

# Setup
server = create_sdk_mcp_server("config-tools", "1.0.0", [get_config])

options = ClaudeAgentOptions(
    system_prompt="You are a configuration management assistant",
    allowed_tools=["Read", "Edit", "mcp__config_tools__get_config"],
    mcp_servers={"config_tools": server},
    hooks={"PreToolUse": [HookMatcher(matcher="Edit", hooks=[validate_edit])]},
    max_turns=10,
    max_budget_usd=1.0,
    cwd="/path/to/project",
)

# Run
async def main():
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Update the app configuration")
        async for msg in client.receive_response():
            if msg.type == "assistant":
                for block in msg.content:
                    if hasattr(block, "text"):
                        print(block.text)

anyio.run(main)
```

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

## Output Format

This skill produces runnable Python files and Bash scripts, not pseudocode or outlines.
Each code artifact includes imports, error handling, and executable entry points.
CLI examples include all required flags with concrete values ready to copy and run.
Custom tool definitions include the `@tool` decorator, argument schema, and return format.
