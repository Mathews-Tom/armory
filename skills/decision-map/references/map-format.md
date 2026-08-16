# Map Format

A decision map is a tracker parent and an index of resolved decisions. It never stores a ticket's question, evidence, or resolution text. Open tickets are discovered from tracker relationships rather than copied into the map.

```markdown
# Decision Map — Billing migration

## Destination
Choose a safe billing migration approach that preserves subscriptions and reporting.

## Notes
Claim TTL: 24h. The migration must retain auditability. `Unresolved contradiction:` is absent.

## Decisions so far
- [Payment history retention](https://example.invalid/issues/12) — retain immutable ledger rows.

## Not yet specified
- Whether regulatory retention differs by region.

## Out of scope
- [Tax engine replacement](https://example.invalid/issues/9) — separate programme; it does not unblock this migration.
```

`Not yet specified` contains only questions that cannot yet be phrased precisely. Remove a patch when it becomes a ticket, decision, or deliberate scope boundary. `Out of scope` contains a reason and a link to a closed ticket; it never appears in `Decisions so far` because a boundary is not progress on the route.

Native tracker mode keeps no child index in the map. A degraded backend maintains a `## Generated child index` section solely to emulate missing parent-child relationships; parse child identifiers only from that section, mark it generated, and do not add decision content to it.
