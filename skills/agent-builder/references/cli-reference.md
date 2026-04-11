Reference for Claude Code CLI commands, essential flags, dynamic subagents, and permission rule syntax.

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
