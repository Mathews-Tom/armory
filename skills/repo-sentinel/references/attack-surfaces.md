# Attack Surfaces Reference

Definitions for the 12 attack surfaces audited by repo-sentinel — what belongs, what doesn't, why it leaks, and how to detect it.

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
