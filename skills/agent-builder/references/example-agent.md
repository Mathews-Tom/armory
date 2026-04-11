Complete end-to-end example agent combining custom tools, hooks, and the ClaudeSDKClient lifecycle.

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
