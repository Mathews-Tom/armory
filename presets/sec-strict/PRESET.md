---
name: sec-strict
type: preset
description: >
  Security-focused preset for projects requiring audit-grade protection. Extends the
  core review-commit lifecycle with security-specific review agents, secret scanning,
  dependency vulnerability auditing, repository configuration sentinel, cost tracking,
  and security coding standards. Use this preset for applications handling sensitive
  data, regulated environments, or any codebase where security posture is a primary
  concern. Bundles 12 packages across skills, agents, rules, hooks, and commands.
metadata:
  version: 1.0.0
preset:
  packages:
    skills:
      - name: pr-review
      - name: code-refiner
      - name: pre-landing-review
      - name: repo-sentinel
      - name: dependency-audit
    agents:
      - name: security-reviewer
      - name: secret-scanner
      - name: codebase-auditor
    rules:
      - name: security-standards
      - name: commit-standards
    hooks:
      - name: git-protection
      - name: cost-tracker
    commands:
      - name: security-scan
  compatibility:
    platforms: [darwin, linux]
---

# Sec Strict Preset

An audit-grade security stack for projects where security posture is a primary concern.
Installs 12 packages providing layered defense across the development lifecycle.

## Included Packages

| Type    | Package            | Role                                            |
| ------- | ------------------ | ----------------------------------------------- |
| Skill   | pr-review          | Diff-based code review across five dimensions   |
| Skill   | code-refiner       | Structural simplification preserving behavior   |
| Skill   | pre-landing-review | Final merge-readiness gate                      |
| Skill   | repo-sentinel      | Repository configuration and policy monitoring  |
| Skill   | dependency-audit   | Dependency vulnerability and license scanning   |
| Agent   | security-reviewer  | Security-focused automated code review          |
| Agent   | secret-scanner     | Detects leaked credentials and API keys         |
| Agent   | codebase-auditor   | Unified multi-dimensional quality assessment    |
| Rule    | security-standards | Enforces secure coding patterns                 |
| Rule    | commit-standards   | Enforces conventional commit message formatting |
| Hook    | git-protection     | Blocks force-push and branch deletion on main   |
| Hook    | cost-tracker       | Monitors and logs API usage costs               |
| Command | security-scan      | On-demand security vulnerability scanning       |

## Defense Layers

1. **Prevention** — `security-standards` rule enforces secure coding patterns at write
   time. `secret-scanner` agent catches leaked credentials before they reach a commit.
2. **Detection** — `security-reviewer` agent performs security-focused review on every
   PR. `dependency-audit` skill identifies vulnerable transitive dependencies.
3. **Monitoring** — `repo-sentinel` skill watches repository configuration for policy
   drift. `cost-tracker` hook logs API usage to detect anomalous consumption.
4. **Response** — `security-scan` command provides on-demand deep scanning when an
   incident is suspected or before a release.
5. **Comprehensive Audit** — `codebase-auditor` agent spawns code-reviewer,
   security-reviewer, and secret-scanner in parallel, then aggregates findings
   into a unified severity-ranked report with pass/fail verdict.
6. **Baseline** — `pr-review`, `code-refiner`, `pre-landing-review`, `git-protection`,
   and `commit-standards` provide the same review-commit lifecycle as the core preset.

## When to Use

- Applications handling PII, financial data, or health records.
- Projects in regulated environments (SOC 2, HIPAA, PCI-DSS).
- Open-source libraries where supply chain security matters.
- Any codebase where a security incident would cause significant damage.

## Relationship to Core

This preset is a superset of `core`. Installing `sec-strict` provides everything
in `core` plus security-specific tooling. There is no need to install both.
