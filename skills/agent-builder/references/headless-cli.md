Headless/print-mode CLI usage for `claude -p`: basic queries, structured output, streaming, tool approval, session continuation, and custom system prompts.

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
