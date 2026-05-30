# Metadata Format

`.stack-prs.yaml` is optional. Use it only when stack inference is ambiguous or the team wants durable topology.

## Schema

```yaml
stack_id: auth-refactor-a1b2c3
base: main
provider: github
branches:
  - name: feat/parser-core
    parent: main
    pr_title: "feat(parser): add core parser API"
  - name: feat/parser-cache
    parent: feat/parser-core
    pr_title: "feat(parser): add parser cache"
  - name: feat/parser-cli
    parent: feat/parser-cache
    pr_title: "feat(parser): expose parser CLI"
```

## Required Fields

| Field | Required | Rule |
| --- | --- | --- |
| `stack_id` | no | Stable slug plus random suffix, e.g. `auth-refactor-a1b2c3`. Minted once per stack. When absent, mint in-memory at creation time and stamp commits and PRs anyway. |
| `base` | yes | Default branch or explicit base branch |
| `provider` | no | Defaults from remote URL when omitted |
| `branches` | yes | Non-empty ordered list |
| `branches[*].name` | yes | Local branch name |
| `branches[*].parent` | yes | Base branch or previous stack branch |
| `branches[*].pr_title` | no | Provider PR title |

## Validation Rules

- `stack_id`, when present, must match `^[a-z0-9][a-z0-9-]*-[a-z0-9]{4,8}$` and must be identical across every commit trailer and PR body in the stack. Mismatch stops mutation.
- `base` must not appear in `branches`.
- Branch names must be unique.
- Every `parent` must be `base` or another listed branch.
- Exactly one branch must have `parent: <base>`.
- The parent graph must be a single linear chain for this release.
- Provider PR bases must match metadata; conflicting provider state stops mutation.

## Stack Identity

`stack_id` is the canonical stack identity. It is copied into:

- every commit trailer (`Stack-Id`, `Stack-Position`)
- every PR body (`Stack-Id`, `Depends on`, `Upstack`)

Minting: `<purpose-slug>-<random 6-char base36>`. The slug is derived from the
user's stated stack purpose or the base branch name; never inferred from
unrelated branch names. The random suffix prevents collisions between stacks
sharing a slug. Once minted, the ID is immutable for the life of the stack.

## Commit Policy

Commit `.stack-prs.yaml` only for long-running team stacks. For one-off stacks, prefer explicit branch order in the user request and avoid adding repository metadata.
