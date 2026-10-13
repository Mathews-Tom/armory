# Metadata Format

`.stack-prs.yaml` is optional, operator-authored topology evidence. Use it only when stack inference is ambiguous or the team wants durable topology. It may describe a linear chain or a branching graph.

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
  - name: feat/parser-docs
    parent: feat/parser-core
    pr_title: "docs(parser): document parser API"
```

## Required Fields

| Field | Required | Rule |
| --- | --- | --- |
| `stack_id` | no | Stable slug plus random suffix, e.g. `auth-refactor-a1b2c3`. Minted once per stack when the skill creates it; when absent at creation, mint in-memory and stamp commits and PRs anyway. Never minted for an existing published stack that lacks one (`references/provenance.md`). |
| `base` | yes | Default branch or explicit trunk branch |
| `provider` | no | Defaults from remote URL when omitted |
| `branches` | yes | Non-empty list, each parent listed before its children |
| `branches[*].name` | yes | Local branch name |
| `branches[*].parent` | yes | `base` or another listed branch |
| `branches[*].pr_title` | no | Provider PR title |

## Validation Rules

- `stack_id`, when present, must match `^[a-z0-9][a-z0-9-]*-[a-z0-9]{4,8}$` and must be identical to every `Stack-Id` the stack's commit trailers and PR bodies carry. Mismatch stops mutation.
- `base` must not appear in `branches`.
- Branch names must be unique.
- Every `parent` must be `base` or another listed branch; an unknown parent stops mutation.
- At least one branch has `parent: <base>`. Several branches may share a parent (siblings), including `base`.
- The parent relation must be acyclic.
- Provider PR heads and bases must match metadata. When metadata conflicts with provider facts or with an explicit stack decision packet, the provider facts and packet are authoritative and the conflict stops mutation; the file is not edited to agree.

## Use By The Executable

The executable manual graph path (`references/stack-model.md` § Explicit Stack Decision Packet) does not parse this file into execution decisions and no tool here hand-parses YAML into topology. When the operator consulted the file, it is cited as a `sources` entry of a selected node's `decision` or `provenance` in the packet; the packet carries the topology explicitly.

Existing files are preserved untouched. Landing, syncing, promoting or cleaning up a stack never rewrites, restamps, reorders or regenerates `.stack-prs.yaml`, and no lineage or provenance field is invented to fill a gap.

## Stack Identity

`stack_id` is the canonical stack identity. When the skill creates a stack, it is copied into:

- every commit trailer (`Stack-Id`, `Stack-Position`)
- every PR body (`Stack-Id`, `Depends on`, `Upstack`)

Minting: `<purpose-slug>-<random 6-char base36>`. The slug is derived from the
user's stated stack purpose or the base branch name; never inferred from
unrelated branch names. The random suffix prevents collisions between stacks
sharing a slug. Once minted, the ID is immutable for the life of the stack.

`Stack-Position: <n>/<total>` is an advisory label assigned when the stack is created: `n` is the node's topological position and `total` the node count at creation, so siblings carry distinct positions. Positions of an existing published stack are never recomputed or rewritten, even after nodes land, siblings are added, or the graph changes shape.

## Commit Policy

Commit `.stack-prs.yaml` only for long-running team stacks. For one-off stacks, prefer explicit branch order in the user request and avoid adding repository metadata.
