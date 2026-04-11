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

| File                          | When to read                                                                 |
| ----------------------------- | ---------------------------------------------------------------------------- |
| `references/scan-patterns.md` | When running any audit (fast-path or full) — contains all detection commands |
| `references/templates.md`     | When setting up enforcement, generating .gitignore, or creating CI gates     |
| `references/remediation.md`   | When fixing findings or scrubbing history — contains all fix procedures      |

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

Each surface defines what belongs, what doesn't, why it leaks, and how to detect it. Scan
commands are in `references/scan-patterns.md`; remediation procedures in `references/remediation.md`.

### Surface 0 — Git Object Store (History)

The most dangerous and most commonly missed surface. `git grep` only scans HEAD. An attacker
with clone access gets the entire commit history. A file deleted in commit N remains in the
object store forever unless explicitly scrubbed.

**What leaks:** Any secret, credential, internal URL, PII, or sensitive file that was ever
committed — even if removed in a subsequent commit. Squash merges don't help; the original
commits persist in reflog and may exist in forks.

**Audit approach:** Run history scans BEFORE working-tree scans. Use `trufflehog` or `gitleaks`
for verified secret detection with entropy analysis. Fall back to `git log -p` grep if tools
are unavailable. See `references/scan-patterns.md § Surface 0`.

### Surface 1 — Source Code

**Belongs:** Application logic, algorithms, public API contracts, type definitions, tests with
synthetic data, utility libraries, schema-only migrations.

**Does NOT belong:**

| Category                | Examples                                                | Why                   |
| ----------------------- | ------------------------------------------------------- | --------------------- |
| Hardcoded credentials   | `API_KEY = "sk-..."`                                    | Direct access grant   |
| Internal URLs/IPs       | `10.0.x.x`, `*.internal`, `*.corp`                      | Network topology      |
| Cloud resource IDs      | AWS account IDs, GCP project IDs, ARNs, S3 bucket names | Resource targeting    |
| PII / seed data         | Real emails, names, phone numbers in fixtures           | Privacy violation     |
| Cryptographic material  | Private keys, certs, JWTs, signing secrets              | Auth bypass           |
| Business logic comments | `// HACK: bypass rate limit for enterprise`             | Reveals security gaps |
| Licensing/billing logic | Entitlement checks, license key validation              | Revenue loss          |
| Debug/admin endpoints   | `/admin/reset-all`, `/__debug/dump-state`               | Privileged access     |
| Vendor workarounds      | `// Workaround for Stripe API bug #4521`                | Stack disclosure      |

### Surface 2 — Documentation

**Belongs:** Setup instructions with placeholders, architecture overviews (external-appropriate
abstraction), public API reference, contributing guidelines, license, feature-level changelog.

**Does NOT belong:** Internal URLs, private tracker references (JIRA-xxx, Linear ENG-xxx),
team/individual names, deployment runbooks, unredacted postmortems, security architecture
details, environment-specific configs.

**CLAUDE.md and .claude/ — unconditional exclusion.** Both contain comprehensive reconnaissance
payloads. Always in `.gitignore`. No exceptions. No conditional logic.

### Surface 3 — Configuration Files

**Belongs:** `.env.example` with placeholder values only, toolchain config (tsconfig, eslint,
prettier), deployment configs with parameterized values, IaC with variable-only resource names.

**Does NOT belong:** `.env` and all `.env.*` (non-example), configs with embedded secrets,
IaC with hardcoded identifiers, SSH config, cloud CLI config, editor config with paths,
private registry references in `.npmrc`.

### Surface 4 — .gitignore as Reconnaissance Vector

The `.gitignore` itself is a public file that leaks information.

**Rules:** Zero comments (comments are attacker documentation). Extension globs over filenames
(`*.credentials` not `oauth-credentials.json`). No environment names in paths. No internal doc
names. Directory patterns absorb children. Always verify with `git ls-files -i --exclude-standard`.

**.claude/ and CLAUDE.md** — always in `.gitignore`, unconditional.

### Surface 5 — CI/CD Pipeline Definitions

**Belongs:** Workflow definitions, build/test commands, matrix strategies, caching configs.

**Does NOT belong:** Inline secrets, internal runner labels, private artifact registries,
deployment target IPs/hostnames, hardcoded cloud identifiers. All secrets via platform
secret store (`${{ secrets.X }}` for GitHub Actions).

### Surface 6 — Container & IaC Definitions

**Dockerfiles — safe:** Public base images, build steps, EXPOSE ports, multi-stage patterns,
non-secret ARG/ENV.

**Dockerfiles — exclude:** ARG/ENV with credentials, COPY of secret files, internal base
images, infrastructure-revealing comments.

**Docker Compose:** All secrets via `env_file` or external secret management. Service names
are public — don't reveal non-public capabilities. Volume mounts must not reference secret paths.

**Terraform/IaC:** All identifiers via variables with no real defaults. State files
(`*.tfstate`) ALWAYS excluded. Variable files (`*.tfvars`) excluded with example templates.

### Surface 7 — Dependencies & Lock Files

Often overlooked. Lock files and manifests leak internal infrastructure.

**What leaks:**

| Category               | Examples                                         | Why                   |
| ---------------------- | ------------------------------------------------ | --------------------- |
| Private registry URLs  | `registry.internal.corp` in lock files           | Internal infra        |
| Internal package names | `@corp-internal/auth-sdk` in package.json        | Org structure         |
| Git+SSH dependencies   | `git+ssh://...private-org/internal-lib.git`      | Private repo exposure |
| Pinned internal forks  | Version pins revealing upstream vuln workarounds | Patch intelligence    |

### Surface 8 — Binary & Large File Artifacts

**What leaks:**

| Category                 | Examples                                            | Why                    |
| ------------------------ | --------------------------------------------------- | ---------------------- |
| Compiled binaries        | May embed paths, credentials at compile time        | Credential extraction  |
| Database dumps           | `.sql`, `.sqlite`, `.db` with real data             | Data exposure          |
| Jupyter notebook outputs | API responses, tokens, internal URLs in cell output | Credential + topology  |
| Image/PDF metadata       | EXIF data, PDF author fields, internal paths        | Author/org enumeration |
| Archive files            | `.zip`, `.tar.gz` bundling secrets                  | Nested secret exposure |

### Surface 9 — Metadata & Git History

**Commit messages:** Don't reference what was vulnerable (`Fix auth bypass in /admin/reset`),
only what changed. Don't paste error messages with credentials or internal stack traces.

**PR descriptions / issue templates:** Don't prompt users to paste credentials. PR templates
should not reference internal processes. Bug reports: sanitized repro steps, not raw logs.

**Branch names:** Avoid names revealing unannounced features or internal codenames.

**Release assets:** Must not bundle config files, `.env`, or credentials.

### Surface 10 — Platform-Specific Metadata (GitHub/GitLab)

| Artifact                          | Risk                                                   | Mitigation                        |
| --------------------------------- | ------------------------------------------------------ | --------------------------------- |
| `CODEOWNERS`                      | Leaks team structure and responsibility mapping        | Use team handles, not individuals |
| `.github/FUNDING.yml`             | Exposes financial platform accounts                    | Verify intentional disclosure     |
| GitHub Actions `@main` refs       | Supply chain attack vector                             | Pin to full SHA, not tag          |
| Workflow `permissions: write-all` | Over-privilege                                         | Use minimum required permissions  |
| Wiki pages                        | Separately cloneable, often contain sensitive runbooks | Audit or disable                  |
| GitHub Discussions                | Accidental leak surface                                | Monitor or disable                |
| `dependabot.yml`                  | Private registry references                            | Parameterize registries           |
| Repository topics/description     | Internal project codenames                             | Review before public              |
| GitHub Pages config               | Reveals deployment targets                             | Verify intentional                |

### Surface 11 — License & Legal Compliance

| Check                      | Risk                                  | Fix                                     |
| -------------------------- | ------------------------------------- | --------------------------------------- |
| Missing LICENSE file       | Defaults to "all rights reserved"     | Add explicit license                    |
| License incompatibility    | GPL dep in MIT project                | Audit with license-checker/pip-licenses |
| Internal copyright headers | Reveals parent company/acquisition    | Genericize or remove                    |
| Missing NOTICE file        | Required by Apache 2.0                | Generate from dependencies              |
| CLA/DCO requirements       | Legal risk for external contributions | Add if accepting PRs                    |
| Third-party attribution    | License violation                     | Audit dependency licenses               |

**Dependency license audit commands:**

```bash
# Node
npx license-checker --summary 2>/dev/null
# Python
pip-licenses 2>/dev/null
# Rust
cargo license 2>/dev/null
```

Flag GPL/AGPL contamination if the target license is permissive (MIT, BSD, Apache).

**Private registry search patterns** — grep lock files and configs:

```text
Files: package-lock.json, poetry.lock, Cargo.lock, pip.conf, pyproject.toml, .npmrc, .yarnrc
Grep for: @company, internal-registry, private-pypi, artifactory, nexus, verdaccio
```

**Copyright header check:** If the license requires file-level headers (Apache 2.0: recommended;
MIT: not required), verify presence in source files and genericize internal copyright notices
that reveal parent company or acquisition history.

### Surface 12 — Community Surface

Required for credible open-source projects accepting contributions:

| Artifact          | Purpose                                      | Risk if missing/wrong           |
| ----------------- | -------------------------------------------- | ------------------------------- |
| `SECURITY.md`     | Responsible disclosure policy                | Signals immaturity to attackers |
| Issue templates   | Guide reporters away from pasting secrets    | Accidental credential leaks     |
| PR templates      | Warn contributors about sensitive data       | Topology leaks in diffs         |
| `CONTRIBUTING.md` | Set expectations without revealing internals | Internal tooling exposure       |
| Bot configs       | `.github/stale.yml`, Probot                  | Internal policy leakage         |

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
Read `references/scan-patterns.md § Full Audit` for the complete 20-check sequence.

#### Quick-Reference Scan Commands

The most critical inline checks. Full pattern set is in `references/scan-patterns.md`.

```bash
# 1. Secrets in code
git grep -rnE '(api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|secret[_-]?key|private[_-]?key|password|passwd|credential)\s*[:=]\s*["\x27][^\s"'\'']{8,}' -- ':!*.lock' ':!node_modules' ':!vendor'

# 2. Internal URLs
git grep -rnE 'https?://[^\s)>"]*\.(internal|corp|local|intranet|private)' -- ':!*.lock'

# 3. Private IPs
git grep -rnE '(10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+)' -- ':!*.lock' ':!node_modules'

# 4. Cloud resource identifiers
git grep -rnE '(arn:aws:|projects/[a-z][\w-]+/locations|/subscriptions/[0-9a-f-]{36})' -- ':!*.lock'

# 5. Connection strings
git grep -rnE '(mongodb|postgres|mysql|redis|amqp|mssql)(\+\w+)?://[^${\s]+@' -- ':!*.lock'

# 6. .env files tracked
git ls-files | grep -iE '\.env(\.|$)' | grep -v '\.example$\|\.template$'

# 7. Credential files tracked
git ls-files | grep -iE '\.(pem|key|p12|pfx|keystore|jks|credentials)$'

# 8. .gitignore leakage
grep -n '^#\|secret\|credential\|oauth\|service.account\|password\|token' .gitignore 2>/dev/null

# 9. .claude/ tracked
git ls-files | grep '\.claude/'

# 10. Tracked files contradicting .gitignore
git ls-files -i --exclude-standard 2>/dev/null

# 11. Sensitive TODO/FIXME/HACK comments
git grep -rnE '(TODO|FIXME|HACK|XXX)\b.*\b(security|auth|bypass|vulnerability|exploit|hack|password|credential|secret|token|admin)' -- ':!*.lock'

# 12. CI/CD secrets inline
git grep -rnE '(password|token|key|secret)\s*[:=]\s*[^\s${\[]' -- '.github/workflows/' '.gitlab-ci.yml' 'Jenkinsfile' '.circleci/'

# 13. Internal URLs in docs
git grep -nE 'https?://[^\s)>]*\.(internal|corp|local|intranet|private)' -- '*.md' '*.rst' '*.txt' '*.adoc'

# 14. Private tracker references in docs
git grep -nE '(JIRA|LINEAR|ASANA|SHORTCUT|CLUBHOUSE|NOTION)-?\s*[A-Z]*-?\d+' -- '*.md' '*.rst' '*.txt'

# 15. Person names in docs
git grep -nE '(@[a-zA-Z][\w-]+|(ask|contact|ping|reach out to)\s+[A-Z][a-z]+)' -- '*.md' '*.rst' '*.txt'

# 16. CI hardcoded IPs
git grep -nE '\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b' -- '.github/workflows/*.yml' '.gitlab-ci.yml'

# 17. .env.example real values
grep -E '=' .env.example 2>/dev/null | grep -vE '=(your-|placeholder|changeme|xxx|example|TODO|REPLACE|""|\x27\x27|$)'

# 18. AWS account IDs
git grep -nE '\b\d{12}\b' -- '*.ts' '*.js' '*.py' '*.yaml' '*.yml' '*.json' '*.tf' | grep -iE '(account|arn|aws)'
```

**Output format:**

```text
REPO SENTINEL AUDIT — <repo> — <date>

[CRITICAL — Direct credential exposure]
  src/config.ts:14 — API_KEY = "sk-live-..." → parameterize
  .env.production — tracked, contains real values → git rm --cached + history scrub

[HIGH — Infrastructure disclosure]
  docker-compose.yml:8 — redis://admin:pass@10.0.3.42:6379 → parameterize
  package-lock.json:892 — resolved: "https://registry.internal.corp/..." → remove internal dep

[MEDIUM — Information leakage]
  .gitignore:24 — oauth-credentials.json → replace with *.credentials.json
  README.md:45 — "See https://wiki.internal.corp/auth-design" → remove
  CODEOWNERS:3 — @john-smith → replace with @team-handle

[LOW — Hygiene]
  .gitignore:1-8 — verbose comment header → remove all comments
  LICENSE — missing → add appropriate license file

[TRACKED-BUT-IGNORED CONTRADICTIONS]
  .env.local — in .gitignore but tracked → git rm --cached

[MISSING FROM .gitignore]
  .claude/ — directory exists, not ignored
  *.sqlite — database files present, not ignored

[LICENSE COMPLIANCE]
  GPL-3.0 dependency in MIT-licensed project: package-x → evaluate compatibility

[ENFORCEMENT STATUS]
  Pre-commit hooks: NOT CONFIGURED → see references/templates.md
  CI secret scanning: NOT CONFIGURED → see references/templates.md
  GitHub secret scanning: UNKNOWN → enable in repo settings
```

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

Run stages sequentially. Report results in a structured audit table at the end.

### Continuous Enforcement Setup

Shift-left prevention is the highest-leverage action. Read `references/templates.md` for
ready-to-use pre-commit config, GitHub Actions workflow, and .gitignore generator.

## Pre-Release Readiness Checklist

Run during Stage 4 of the Pre-Release Audit Mode, or standalone before any public release.
All items are soft blockers — failures produce advisory output, not hard halts.

### §4.1 Documentation Completeness

| File                               | Required    | Check                                   |
| ---------------------------------- | ----------- | --------------------------------------- |
| `README.md`                        | YES         | Has install + quickstart sections       |
| `CONTRIBUTING.md`                  | YES         | Fork/branch strategy, dev setup         |
| `CODE_OF_CONDUCT.md`               | YES         | Adopted standard (Contributor Covenant) |
| `CHANGELOG.md`                     | RECOMMENDED | Keep-a-changelog format                 |
| `LICENSE`                          | YES         | Verified in Surface 11                  |
| `SECURITY.md`                      | RECOMMENDED | Disclosure process + contact            |
| `ARCHITECTURE.md` or `docs/`       | RECOMMENDED | Module overview                         |
| `.github/ISSUE_TEMPLATE/`          | RECOMMENDED | Bug + feature templates                 |
| `.github/PULL_REQUEST_TEMPLATE.md` | RECOMMENDED | PR checklist                            |

### §4.2 Code Quality Gates

- Linter config: `.eslintrc*`, `ruff.toml`, `pyproject.toml [tool.ruff]`, `.clippy.toml`
- Formatter config: `.prettierrc*`, `pyproject.toml [tool.black]`, `rustfmt.toml`
- Pre-commit: `.pre-commit-config.yaml`
- Type checking: `tsconfig.json` (strict), `py.typed` marker, mypy/pyright config

### §4.3 Test Infrastructure

- Test runner configured and documented
- CI pipeline exists (`.github/workflows/`, `.gitlab-ci.yml`)
- Test data is synthetic (not production-derived)
- Smoke test or single-command verify path documented

### §4.4 API Surface

- Public API explicitly demarcated (`__all__`, `exports`, `pub`)
- No internal implementation leaked across module boundaries
- Configuration via env vars / config files, not hardcoded constants

### §4.5 Package Metadata

Check manifest completeness across: `package.json`, `pyproject.toml`, `Cargo.toml`, `*.csproj`

Required fields: `name`, `version`, `description`, `repository`, `homepage`, `keywords`,
`author`, `license`

### §4.6 Reproducible Builds

- Lock files committed
- Toolchain versions documented: `.tool-versions`, `.python-version`, `.nvmrc`, `rust-toolchain.toml`
- CI runner images pinned

### §4.7 Binary Asset Policy

- No files >1MB without Git LFS
- No build artifacts committed
- `.gitattributes` for LFS if needed

### §4.8 Community Setup

- Issue labels defined: `good-first-issue`, `help-wanted`, `bug`, `enhancement`
- Discussions or external channel linked
- Maintainer expectations documented

---

### History Contamination Remediation

When secrets have already been committed. Read `references/remediation.md` for the full
triage decision tree, git filter-repo commands, and post-scrub protocol.

#### Quick-Reference Remediation

**Triage decision table:**

| Pushed to public remote? | Contains real credentials? | Action                                                       |
| ------------------------ | -------------------------- | ------------------------------------------------------------ |
| No                       | Any                        | `git rm --cached` + fix `.gitignore`                         |
| Yes                      | No (placeholder)           | `git rm --cached` + fix `.gitignore`. Scrub optional.        |
| Yes                      | Yes                        | Full history scrub + credential rotation. Assume compromise. |

**git filter-repo (preferred):**

```bash
cp -r .git .git-backup

# By path
git filter-repo --invert-paths --path <file> --force

# By glob
git filter-repo --invert-paths --path-glob '*.pem' --force

# By regex
git filter-repo --invert-paths --path-regex '.*secret.*' --force

# Re-add remote (filter-repo strips it)
git remote add origin <url>
git push --force --all && git push --force --tags
```

**BFG Repo-Cleaner (fallback):**

```bash
java -jar bfg.jar --delete-files <filename> .git
git reflog expire --expire=now --all && git gc --prune=now --aggressive
```

**Post-scrub protocol (non-optional):**

1. Rotate every exposed credential — scrubbing does not un-expose. GitHub caches objects ~90 days. Mirrors and forks retain indefinitely.
2. Verify: `git log --all --full-history -- <path>` must return empty.
3. Update all ignore/exclude rules before next commit.
4. For severe exposure: consider repo deletion + recreation. Contact GitHub support for cache invalidation.
5. Rotate CI/CD secrets independently — pipeline stores are unaffected by git history operations.
6. Document incident internally: what was exposed, how long, which remotes, what was rotated.

### .gitignore Generation

Generate a complete, opinionated `.gitignore` tailored to detected project type with all
hygiene rules baked in. Read `references/templates.md § .gitignore Generator`.

---

## Limitations

- History scrubbing does not guarantee removal of exposure. Force-push is required, and external mirrors (forks, GitHub Archive, Software Heritage) retain history indefinitely regardless of local operations.
- External mirrors, caches, and search engine indexes cannot be verified as de-indexed after content removal.
- Single-repo scope only — not designed for monorepo audits without adaptation. Cross-package secret propagation requires separate analysis per package root.
- GitHub-specific checks (branch protection, secret scanning alerts, security advisories) require the `gh` CLI with authenticated access. Without it, Surface 10 coverage is reduced.
- Secret scanning depth depends on available tooling. `trufflehog` and `gitleaks` provide verified detection with entropy analysis; manual regex patterns used as fallback have higher false-positive rates and miss obfuscated credentials.
- Artifact decisions for package registry publishing (npm, PyPI, crates) have ecosystem-specific norms that differ from source repo inclusion rules — apply ecosystem conventions when auditing published artifacts.
