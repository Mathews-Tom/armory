Comparison of the raw Anthropic API against Claude Code headless mode / Agent SDK patterns.

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
