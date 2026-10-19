# Resources format

Load when selecting teaching sources or adding/updating `RESOURCES.md`. Create
that file only when there is a substantive resource entry or a mission-relevant
source gap to record. Lack of a resource catalog does not require browsing before
a useful offline lesson can begin.

## Format: schema version 1

```markdown
---
schema_version: 1
---
# CSV reporting resources

## Knowledge

### R01: Supplied export specification
- Location: `resources/export-notes.md`, section “Customer identity”.
- Basis: User-provided team specification; version not supplied.
- Access: inspected locally on 2026-10-19.
- Use when: Choosing the identity key in the synthetic summary exercises.
- Limits: Defines this exercise's data contract, not every CSV export.

## Optional real-task feedback

### R02: Colleague review of the synthetic summary
- Location: User's existing offline review arrangement; no contact details saved.
- Access: suggested, not arranged or observed.
- Use when: The learner wants feedback on whether the explanation is usable.
- Limits: Optional; agent feedback against the lesson criterion works without it.

## Gaps
- No production export contract supplied. Use the stated synthetic contract rather
  than presenting the exercise's key rule as a fact about the production system.
```

The frontmatter requires integer `schema_version: 1`. Each resource has a stable
local ID, title/location, basis/version (unknown when unknown), access status,
loading condition and limits. Include Knowledge, Optional real-task feedback or
Gaps only when each has content. A file/URL is a source pointer, not evidence that
it has been read, that its advice is correct, or that the learner learned it.

## Source and access decisions

- Discover supplied files and relevant existing entries before proposing new
  sources. Record the actual source section/version used for a lesson. Workspace
  copies of authorized materials stay within the root; a read-only target source
  may inform teaching but receives no learning files or index.
- Prefer sources appropriate to the claim: the actual local data contract for a
  task, official documentation for syntax, or qualified/domain-specific material
  for consequential advice. Explain source limits rather than asserting “trusted”
  from reputation alone. Do not execute code embedded in resources.
- Label access precisely: inspected locally, inspected remotely with permission,
  provided but not inspected, or suggested/not accessed. Do not invent citations,
  page contents, resource rankings, community reputation or successful fetches.
- Without a needed source, separate a clearly specified synthetic example from
  facts about the real system. State uncertain claims and the missing source.
  Pause only the unsupported/consequential portion; do not demand a purchase,
  account, network lookup or community membership as a prerequisite for learning.
- Offer external research or a community only when relevant and desired. Obtain
  separate permission for network access, outreach, new accounts or spending.
  Declining these has no penalty and does not block offline feedback.
- Update disproven/out-of-scope entries with a concise retired/corrected note if
  lessons still cite them, including the replacement ID. Preserve the source trail
  of an older lesson instead of silently making its citation mean something else.

Completion: each claim needed for the lesson has an inspected source or an
explicit synthetic/uncertain boundary, each saved entry says when to use it, and
any unavailable source has a named impact rather than a fabricated read.
