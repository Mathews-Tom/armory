---
name: stack-workflow
type: preset
description: 'Bundles stacked pull request workflow packages for teams that regularly ship dependent PR chains. Triggers on: "stack workflow preset", "install stacked PR workflow", "stacked PR team setup", "enable stack guard", "stack-pr preset", "stacked branch workflow". Installs stacked-prs topology policy, ship-workflow lifecycle execution, /stack-pr, stack-guard, git-protection and PR review packages as one workflow.'
packages:
  - skills/stacked-prs
  - skills/ship-workflow
  - commands/stack-pr
  - hooks/git-protection
  - hooks/stack-guard
  - skills/pre-landing-review
  - skills/pr-review
metadata:
  version: 0.2.0
  category: development
  tags: [git, pull-requests, stacked-prs, preset]
  difficulty: advanced
  phase: ship
preset:
  packages:
    skills:
      - { name: stacked-prs }
      - { name: ship-workflow }
      - { name: pre-landing-review }
      - { name: pr-review }
    commands:
      - { name: stack-pr }
    hooks:
      - { name: git-protection }
      - { name: stack-guard }
---

# Stack Workflow

Installs the packages needed for repeated stacked PR work: stack modeling, slash-command dispatch, guarded lifecycle execution, force-push protection, stack-specific warnings, and review gates.

## Included Packages

| Type | Package | Role |
| --- | --- | --- |
| Skill | stacked-prs | Inspect, publish, sync, validate and split stacks; author topology/provenance policy for lifecycle execution |
| Skill | ship-workflow | Execute explicit selected stacks through current gates, guarded landing, post-merge acceptance and proof-based cleanup |
| Command | stack-pr | Provides `/stack-pr` command syntax |
| Hook | git-protection | Blocks broadly destructive Git operations |
| Hook | stack-guard | Blocks plain force pushes and warns on stack topology risks |
| Skill | pre-landing-review | Final merge-readiness gate |
| Skill | pr-review | Diff-based PR review |

## Workflow

1. Use `stacked-prs` or `/stack-pr inspect` to model the current stack.
2. Use `/stack-pr publish` or `/stack-pr split` to create reviewable PR slices.
3. Let `git-protection` block destructive Git operations.
4. Let `stack-guard` warn when commands conflict with `.stack-prs.yaml`.
5. Use `pr-review` on individual PR diffs.
6. Use `pre-landing-review` before merging each stack slice.
7. Pass the explicitly reviewed selection to `ship-workflow` through `/stack-pr merge` or `/stack-pr cleanup`; the controller owns parent-first landing and proof-based cleanup. A narrower request keeps its endpoint, and installing the preset grants no mutation authority.

## When To Use

Use this preset for teams that frequently maintain dependent PR chains or long-running feature stacks.

Do not install it just to open occasional single PRs. The `stacked-prs` skill is request-scoped and does not force stack behavior, but global hooks add friction that simple-branch projects do not need.

## Output

The preset installs packages only. It does not create `.stack-prs.yaml`, branch stacks, PRs, or repository metadata by itself.

## Error Handling

| Problem | Resolution |
| --- | --- |
| User needs one normal PR | Use the normal PR workflow instead of this preset |
| Team has no stack metadata | `stack-guard` still blocks plain force push and otherwise stays quiet |
| Existing project already has `git-protection` | Keep one installed copy; do not duplicate hooks |
| Hosted provider is not GitHub | Use `stacked-prs` local inspection and add an adapter before PR mutation |

