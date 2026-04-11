Common agent-builder use cases: CI/CD test pipeline, automated code review, custom analysis tools, and database query agents.

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
