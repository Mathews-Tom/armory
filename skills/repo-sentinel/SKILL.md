---
name: repo-sentinel
description: 'Full security audit for public repositories across 12 attack surfaces: git history, secrets, CI/CD, containers, dependencies, licenses. Triggers on: "push to GitHub", "make repo public", "open source this", "is this safe to push", "release audit", "secret leaks".'
metadata:
  version: 1.1.1
  category: review
  tags: [security, public-repo, secret-scanning, audit]
  difficulty: advanced
  phase: review
---

# Repo Sentinel

Everything in a public repo is permanent attacker surface. This skill defines what belongs in a
public repo, what does not, how to detect violations across 12 attack surfaces, how to remediate
when the boundary is violated, and how to enforce continuously.

## Reference files

This skill uses bundled reference files for detailed patterns and templates. Read them as needed:

| File                                  | When to read                                                                    |
| ------------------------------------- | ------------------------------------------------------------------------------- |
| `references/attack-surfaces.md`       | When auditing any surface — full definitions for Surfaces 0–12                  |
| `references/scan-patterns.md`         | When running any audit (fast-path or full) — contains all detection commands    |
| `references/pre-release-checklist.md` | When running the Pre-Release Audit (Stage 4) — §4.1–§4.8 readiness checklist    |
| `references/templates.md`             | When setting up enforcement, generating .gitignore, or creating CI gates        |
| `references/remediation.md`           | When fixing findings or scrubbing history — contains all fix procedures         |

---

## Prerequisites

- `gh` CLI installed and authenticated (`gh auth status` must pass) — required for GitHub-specific surface checks (Surface 10)
- Active git repository context — the skill operates on `git` objects; non-git directories are out of scope
- `trufflehog` or `gitleaks` — optional but strongly recommended for Surface 0 (git history) secret detection with entropy analysis; without them, fall back to `git log -p` grep patterns from `references/scan-patterns.md`
- Read access to the full git object store — shallow clones (`--depth N`) will miss history secrets; warn the user if a shallow clone is detected

## Calibration Rules

- **Public vs. private visibility:** Apply stricter severity ratings for public repos — findings classified MEDIUM in a private repo (e.g., internal URL in a comment) escalate to HIGH in a public repo. Confirm repo visibility before scoring.
- **Stack-scoped surfaces:** Scope the audit to attack surfaces relevant to the detected tech stack. A static HTML repo has no meaningful Surface 6 (containers) or Surface 7 (lock files) exposure — mark those surfaces N/A rather than penalizing.
- **N/A handling:** Surfaces scored N/A are not penalized and do not lower the overall risk posture. Document N/A surfaces explicitly so the user understands what was skipped.
- **Tool availability:** If `trufflehog`/`gitleaks` are unavailable, note this in the audit header and describe the reduced confidence in Surface 0 coverage.
- **False positive discipline:** Flag a finding only when there is evidence of actual exposure, not just pattern proximity. A variable named `api_key` with a placeholder value is LOW, not CRITICAL.

## Foundational Principle

**The public/private boundary is a one-way valve.** Once a byte reaches a public remote — via
push, PR, issue, wiki, release asset, or GitHub Pages — assume it is indexed, cached, mirrored,
and archived permanently. `git push --force`, PR deletion, issue edits, and release removal do
NOT guarantee erasure. Scraping infrastructure (GitHub Archive, GH Torrent, Software Heritage,
Google Cache, Wayback Machine, and dozens of proprietary security scanners) operates continuously
with sub-hour latency.

**Decision framework for every artifact:**

| Question                                                              | If YES →                    | If NO →  |
| --------------------------------------------------------------------- | --------------------------- | -------- |
| Could this help an attacker who has no other access?                  | EXCLUDE                     | Continue |
| Does this reveal internal topology not inferable from public signals? | EXCLUDE                     | Continue |
| Does this contain values that grant access to anything?               | EXCLUDE                     | Continue |
| Does this violate a license obligation or expose legal risk?          | EXCLUDE                     | Continue |
| Would removing this reduce the repo's utility to legitimate users?    | INCLUDE (if above = all NO) | EXCLUDE  |

When in doubt, exclude. False negatives (leaked secrets) are catastrophic and irreversible.
False positives (over-redaction) are trivially correctable.

---

## The 12 Attack Surfaces

Full definitions — what belongs, what doesn't, why it leaks, detection approach — for Surfaces 0
through 12 are in `references/attack-surfaces.md`. Read that file when scoping or scoring any
audit. Scan commands per surface live in `references/scan-patterns.md`; remediation procedures
in `references/remediation.md`.

---

## Severity Classification

All findings are classified by severity. The classification drives action priority:

| Severity     | Criteria                                            | Action                       |
| ------------ | --------------------------------------------------- | ---------------------------- |
| **CRITICAL** | Active credential exposure, private key, auth token | Block push. Fix immediately. |
| **HIGH**     | Infrastructure/topology enabling targeted attack    | Resolve before push.         |
| **MEDIUM**   | Information leakage aiding reconnaissance           | Fix in next commit.          |
| **LOW**      | Hygiene, style, redundancy issues                   | Fix at convenience.          |

CRITICAL and HIGH in git history → full history scrub + credential rotation required.

---

## Operations

### Fast-Path Audit (Staged Changes Only)

Use when pushing a single file or small changeset. Scans only staged changes, not the full repo.
Read `references/scan-patterns.md § Fast-Path` for the commands.

### Full Repo Audit (20+ checks)

Run before making any repo public or before first push to a public remote.
Read `references/scan-patterns.md § Full Audit` for the complete 20-check sequence, the
Quick-Reference Scan Commands block, and the audit output format.

### Pre-Release Audit Mode (4-Stage DAG)

When preparing a repo for open-source release, run this 4-stage pre-release audit instead of
the surface-based audit. Each stage emits **PASS** / **WARN** / **FAIL** with actionable
remediation. Hard blockers in stages 1–3 halt the pipeline. Stage 4 produces advisory output.

```text
Stage 1: Sensitive Assets        [HARD BLOCKER] → Surfaces 0–4, 8–9
Stage 2: Legal & Compliance      [HARD BLOCKER] → Surface 11
Stage 3: Public Surface Hygiene  [HARD BLOCKER] → Surfaces 4–7, 9–10
Stage 4: Contribution & Release  [SOFT BLOCKER] → Surface 12 + Pre-Release Checklist
```

Run stages sequentially. Report results in a structured audit table at the end. Stage 4
checklist items (§4.1–§4.8) are in `references/pre-release-checklist.md`.

### Continuous Enforcement Setup

Shift-left prevention is the highest-leverage action. Read `references/templates.md` for
ready-to-use pre-commit config, GitHub Actions workflow, and .gitignore generator.

### History Contamination Remediation

When secrets have already been committed. Read `references/remediation.md` for the full
triage decision tree, git filter-repo commands, BFG fallback, post-scrub protocol, and
.gitignore generation guidance.

---

## Limitations

- History scrubbing does not guarantee removal of exposure. Force-push is required, and external mirrors (forks, GitHub Archive, Software Heritage) retain history indefinitely regardless of local operations.
- External mirrors, caches, and search engine indexes cannot be verified as de-indexed after content removal.
- Single-repo scope only — not designed for monorepo audits without adaptation. Cross-package secret propagation requires separate analysis per package root.
- GitHub-specific checks (branch protection, secret scanning alerts, security advisories) require the `gh` CLI with authenticated access. Without it, Surface 10 coverage is reduced.
- Secret scanning depth depends on available tooling. `trufflehog` and `gitleaks` provide verified detection with entropy analysis; manual regex patterns used as fallback have higher false-positive rates and miss obfuscated credentials.
- Artifact decisions for package registry publishing (npm, PyPI, crates) have ecosystem-specific norms that differ from source repo inclusion rules — apply ecosystem conventions when auditing published artifacts.
