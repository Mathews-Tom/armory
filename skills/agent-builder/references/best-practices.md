Best practices for the Agent SDK and CLI/Headless mode.

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
