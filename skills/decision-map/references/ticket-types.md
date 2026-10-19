# Ticket Types

The initial content is one question plus backend-required metadata. GitHub uses authoritative type/interaction labels outside the body; its body adds only degraded `Blocked by:` lines when needed. Local tickets require `Type:`, `Interaction:`, `Status:`, and `Blocked by:` headers before the question, because these headers are the local backend's metadata rather than duplicate GitHub labels.

```markdown
## Question
Which immutable record layout preserves subscription history through the migration?
```

For a local ticket, prepend the existing metadata headers (with the appropriate values):

```markdown
# Choose the record layout

Type: decision-map:discussion
Interaction: decision-map:hitl
Status: OPEN
Blocked by:

## Question
Which immutable record layout preserves subscription history through the migration?
```

Later evidence and verdict use the concrete GitHub-comment or local quoted-append procedure in `references/tracker-operations.md`, preserving the original question and backend metadata.

| Type | Label | Typical interaction | Resolution path |
|---|---|---|---|
| `discussion` | `decision-map:discussion` | HITL | Ask the human using `references/elicitation.md`. |
| `research` | `decision-map:research` | AFK | Use `references/research-resolution.md`; link findings. |
| `prototype` | `decision-map:prototype` | HITL | Follow `references/prototyping.md` for bounded logic/state or structurally different UI evidence and a justified verdict; obtain human judgment when HITL. |
| `unblock` | `decision-map:unblock` | Either | Produce minimal evidence, access, measurement, setup, or experiment. |

Interaction is exactly one authoritative GitHub label or local `Interaction:` header: `decision-map:hitl` or `decision-map:afk`. GitHub ticket bodies do not repeat labels; local bodies must contain their required headers.

An `unblock` ticket exists only to make a decision answerable. Good: obtain sandbox credentials to evaluate authentication approaches; measure table cardinality before selecting a migration method. Bad: implement OAuth login; build the database migration. Feature implementation belongs outside a decision map.

Ticket a question once it is sharp, even when another ticket blocks its answer. Keep it in fog only when the question cannot yet be stated precisely. Never pre-slice fog into speculative work.
