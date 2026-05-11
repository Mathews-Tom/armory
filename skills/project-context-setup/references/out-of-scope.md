# Out-of-Scope Memory

Use `.out-of-scope/` to preserve durable records of rejected enhancements. This prevents
agents from re-litigating the same feature request in future triage sessions.

## Directory Shape

```text
.out-of-scope/
├── dark-mode.md
├── graphql-api.md
└── plugin-system.md
```

Use one file per rejected concept, not one file per issue.

## File Format

```markdown
# Dark Mode

This project does not support runtime theming.

## Why this is out of scope

Supporting runtime themes would require replacing the current static theme contract,
threading theme state through every rendered surface, and adding persistence for user
preferences. The project treats theming as a downstream embedding concern.

## Prior requests

- #42 - Add dark mode
- #87 - Night theme for accessibility
```

## Triage Rules

- Read `.out-of-scope/*.md` before rejecting or accepting similar enhancement requests.
- Match by concept, not exact wording.
- If the maintainer confirms the rejection still applies, append the new issue to the prior requests list.
- If the maintainer reopens the decision, update or delete the out-of-scope file and continue normal triage.
- Do not use `.out-of-scope/` for bugs. Bugs are fixed, marked unreproducible with evidence, or closed by policy.
