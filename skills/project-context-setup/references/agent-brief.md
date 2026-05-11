# Agent Brief Contract

An agent brief is the durable handoff placed on an issue when it becomes `ready-for-agent`.
It is the implementation contract for an AFK agent.

## Principles

- Describe behavior, not procedural file edits.
- Prefer stable interfaces, types, config shapes, CLI commands, and acceptance criteria.
- Avoid line numbers and fragile file paths unless the file identity itself is the contract.
- State out-of-scope work explicitly.
- Make each acceptance criterion independently verifiable.

## Template

```markdown
## Agent Brief

**Category:** bug | enhancement
**Summary:** one-line description

**Current behavior:**
What happens now. For bugs, describe the broken behavior. For enhancements, describe the status quo.

**Desired behavior:**
What must be true after implementation, including edge cases and error behavior.

**Key interfaces:**
- `TypeName` - expected contract change
- `command` or endpoint - expected input/output behavior
- Config shape - any new required or optional setting

**Acceptance criteria:**
- [ ] Specific, testable criterion
- [ ] Specific, testable criterion
- [ ] Validation command or manual verification path is documented

**Out of scope:**
- Adjacent capability that must not be changed
- Follow-up work that belongs in a separate issue
```

## Readiness Rules

Move an issue to `ready-for-agent` only when:

- The desired behavior is clear enough for a new agent to implement without private context.
- Required decisions have been made or explicitly scoped out.
- The acceptance criteria can be checked by tests, commands, or a concrete manual procedure.
- External access requirements are listed.

Use `ready-for-human` when product judgment, credentials, stakeholder negotiation, or manual release authority is still required.
