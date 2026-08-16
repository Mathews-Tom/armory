# Claim Protocol

```text
Owner        = visible tracker ownership
SessionClaim = concurrency arbitration
```

A ticket requires both visible ownership and an uncontested session claim before substantive work. Assignment alone is not exclusive because multiple sessions can share the same GitHub identity.

## GitHub arbitration

1. Select one frontier ticket.
2. Add visible ownership with `gh issue edit N --add-assignee @me`.
3. Post a comment whose first line is `decision-map claim`, followed by `session: <id>` and `claimed-at: <ISO-8601>`.
4. Re-read comments and assignees with `gh issue view N --json comments,assignees`.
5. Ignore malformed and stale claim comments. Derive the database comment identifier from the `#issuecomment-N` suffix of the comment URL; the lowest remaining database identifier wins because it is server-assigned and monotonic.
6. The winner works. The loser posts a one-line withdrawal, removes its own assignee when it added one, recomputes the frontier, and chooses another ticket.

This is advisory ownership plus optimistic arbitration, not a lock. A claim older than 24 hours, or the `Claim TTL` configured in map Notes, is stale. A successor can preempt it only by recording the stale session identifier and the preemption reason in its claim comment.

## Local exclusion

Write the complete session identifier and timestamp to a private temporary file, then atomically link it to `.scratch/<effort>/claims/<ticket>.lock`. The link is exclusive: a second creator fails rather than arbitrating, and the visible lock is always complete. Apply the same TTL before a documented stale-lock preemption and remove the lock when resolution is recorded.
