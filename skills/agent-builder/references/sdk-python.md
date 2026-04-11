Python patterns for the Claude Agent SDK: installation, query, interactive client, custom tools, hooks, and error handling.

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
