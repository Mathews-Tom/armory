---
name: core
type: preset
description: >
  Essential packages for every Claude Code user. Bundles pull request review, code
  refinement, pre-landing checks, git branch protection, and commit message standards
  into a single install. Use this preset when setting up a new project or onboarding a
  teammate who needs a reliable baseline without opinionated language-specific tooling.
  Covers the review-commit lifecycle: review changes, refine code quality, verify
  pre-merge readiness, prevent force-pushes to protected branches, and enforce
  consistent commit messages.
metadata:
  version: 1.0.0
preset:
  packages:
    skills:
      - name: pr-review
      - name: code-refiner
      - name: pre-landing-review
    hooks:
      - name: git-protection
    rules:
      - name: commit-standards
  compatibility:
    platforms: [darwin, linux]
---

# Core Preset

A minimal, opinionated baseline for Claude Code projects. Installs five packages that
cover the review-commit lifecycle without imposing language-specific constraints.

## Included Packages

| Type  | Package            | Role                                            |
| ----- | ------------------ | ----------------------------------------------- |
| Skill | pr-review          | Diff-based code review across five dimensions   |
| Skill | code-refiner       | Structural simplification preserving behavior   |
| Skill | pre-landing-review | Final merge-readiness gate                      |
| Hook  | git-protection     | Blocks force-push and branch deletion on main   |
| Rule  | commit-standards   | Enforces conventional commit message formatting |

## Workflow

1. **Develop** — write code on a feature branch.
2. **Refine** — invoke `code-refiner` to reduce complexity and improve readability.
3. **Review** — run `pr-review` against the diff to catch bugs, silent failures, and
   type issues before opening a PR.
4. **Gate** — `pre-landing-review` performs a final check before merge.
5. **Protect** — `git-protection` prevents accidental force-pushes or branch deletions.
6. **Commit** — `commit-standards` enforces message format on every commit.

## When to Use

- New projects that need a quality baseline from day one.
- Teams onboarding members who are new to Claude Code.
- Any repository where review discipline and commit hygiene matter but
  language-specific enforcement is handled separately.

## Extending

Layer additional presets on top of `core`:

- **python-strict** — adds Python-focused testing, security scanning, and stricter rules.
- **sec-strict** — adds security auditing, dependency scanning, and cost tracking.

## Complementary Agents

These orchestrator agents work well alongside the core preset:

- **codebase-auditor** — unified quality assessment across code, security, and dependencies.
- **release-captain** — ship lifecycle with quality gates, changelog, and PR creation.
- **full-stack-builder** — end-to-end implementation with testing and documentation.
