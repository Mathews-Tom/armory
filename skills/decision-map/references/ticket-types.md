# Ticket Types

Every ticket body contains only its question. Type and interaction are labels, not body metadata.

```markdown
## Question
Which immutable record layout preserves subscription history through the migration?
```

| Type | Label | Typical interaction | Resolution path |
|---|---|---|---|
| `discussion` | `decision-map:discussion` | HITL | Ask the human using `references/elicitation.md`. |
| `research` | `decision-map:research` | AFK | Use `references/research-resolution.md`; link findings. |
| `prototype` | `decision-map:prototype` | HITL | Link a cheap outline, stub, or sketch artifact. |
| `unblock` | `decision-map:unblock` | Either | Produce minimal evidence, access, measurement, setup, or experiment. |

Interaction is exactly one authoritative label: `decision-map:hitl` or `decision-map:afk`. Never repeat it in the body.

An `unblock` ticket exists only to make a decision answerable. Good: obtain sandbox credentials to evaluate authentication approaches; measure table cardinality before selecting a migration method. Bad: implement OAuth login; build the database migration. Feature implementation belongs outside a decision map.

Ticket a question once it is sharp, even when another ticket blocks its answer. Keep it in fog only when the question cannot yet be stated precisely. Never pre-slice fog into speculative work.
