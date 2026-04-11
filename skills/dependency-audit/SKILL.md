---
name: dependency-audit
description: 'Audits direct and transitive dependencies for license compliance, maintenance health, CVEs, abandoned packages, and bloat. Triggers on: "audit dependencies", "license check", "dependency health", "abandoned packages", "unused dependencies", "license compliance", "supply chain", "dependency risk".'
metadata:
  version: 1.1.1
  category: review
  tags: [dependencies, vulnerabilities, licenses, supply-chain]
  difficulty: intermediate
  phase: review
---

# Dependency Audit

Comprehensive dependency risk assessment: license compatibility analysis, maintenance
health scoring, CVE detection, bloat identification, and transitive dependency risk
mapping. Produces an actionable report with prioritized remediation steps organized by
urgency (security → license → maintenance → bloat).

## Reference Files

| File                                  | Contents                                                                   | Load When                |
| ------------------------------------- | -------------------------------------------------------------------------- | ------------------------ |
| `references/license-compatibility.md` | License compatibility matrix, copyleft detection, commercial-safe licenses | Always                   |
| `references/health-metrics.md`        | Maintenance health indicators, scoring criteria, abandonment detection     | Always                   |
| `references/bloat-detection.md`       | Identifying unused deps, duplicate functionality, heavy transitive trees   | Bloat analysis requested |
| `references/cve-sources.md`           | CVE databases, advisory sources, vulnerability severity interpretation     | Security audit requested |

## Prerequisites

- Access to the project's dependency files (`pyproject.toml`, `requirements.txt`,
  `package.json`, `Cargo.toml`, `go.mod`)
- Lock file (for exact versions and transitive dependencies)
- Project license (to determine compatibility requirements)

## Workflow

### Phase 1: Parse Dependency Tree

1. **Direct dependencies** — Packages explicitly declared in the project.
2. **Transitive dependencies** — Dependencies of dependencies. Often 10-50x the
   direct count.
3. **Version constraints** — Pinned (`==1.2.3`), ranged (`>=1.0,<2.0`), or floating (`*`).
4. **Development vs production** — Separate dev/test dependencies from production.

Tools:

- Python: `uv pip list`, `pip-audit`, `pipdeptree`
- Node.js: `npm list --all`, `npm audit`
- Rust: `cargo tree`, `cargo audit`

### Phase 2: Audit Licenses

For each dependency:

1. **Identify the license** — Check package metadata, LICENSE file, pyproject.toml.
2. **Classify compatibility** — Against the project's own license:

   | License                   | Commercial OK            | Copyleft         | Risk Level |
   | ------------------------- | ------------------------ | ---------------- | ---------- |
   | MIT, BSD, ISC, Apache 2.0 | Yes                      | No               | Low        |
   | LGPL                      | With care                | Weak             | Medium     |
   | GPL-2.0, GPL-3.0          | No (unless GPL project)  | Strong           | High       |
   | AGPL                      | No (unless AGPL project) | Strong + network | Critical   |
   | Unknown                   | Cannot determine         | Unknown          | Critical   |

3. **Flag issues** — Copyleft licenses in proprietary projects, unknown licenses,
   license changes between versions.

### Phase 3: Assess Maintenance Health

For each dependency, evaluate maintenance signals:

| Indicator            | Healthy        | Warning     | Abandoned                |
| -------------------- | -------------- | ----------- | ------------------------ |
| Last release         | < 6 months     | 6-18 months | > 18 months              |
| Commits (90 days)    | 10+            | 1-9         | 0                        |
| Open issues response | < 2 weeks      | 2-8 weeks   | > 8 weeks or no response |
| Bus factor           | 3+ maintainers | 2           | 1                        |
| CI status            | Passing        | Flaky       | Failing or absent        |

### Phase 4: Check Security

1. **Known CVEs** — Check against advisory databases:
   - Python: `pip-audit`, PyPI advisory database
   - Node.js: `npm audit`, GitHub Advisory Database
   - General: NVD (National Vulnerability Database)

2. **Severity classification** — CVSS score interpretation:

   | CVSS Score | Severity | Action                 |
   | ---------- | -------- | ---------------------- |
   | 9.0-10.0   | Critical | Upgrade immediately    |
   | 7.0-8.9    | High     | Upgrade within days    |
   | 4.0-6.9    | Medium   | Upgrade within weeks   |
   | 0.1-3.9    | Low      | Upgrade at convenience |

3. **Fix availability** — Is there a patched version? If not, what's the workaround?

### Phase 5: Detect Bloat

1. **Unused dependencies** — Dependencies imported nowhere in the codebase.
2. **Duplicate functionality** — Multiple packages doing the same thing (2 HTTP clients,
   2 JSON parsers).
3. **Heavy transitive trees** — Packages that pull in dozens of sub-dependencies for
   a simple feature.
4. **Size analysis** — Large packages used for small functionality.

### Phase 6: Report

Produce a prioritized report with action items.

## Output Format

```text
## Dependency Audit: {Project Name}

### Summary
| Metric | Count |
|--------|-------|
| Direct dependencies | {N} |
| Transitive dependencies | {N} |
| License issues | {N} |
| Maintenance concerns | {N} |
| Security vulnerabilities | {N} |
| Bloat candidates | {N} |

### License Compliance

| Package | Version | License | Compatible | Issue |
|---------|---------|---------|------------|-------|
| {pkg} | {ver} | MIT | Yes | None |
| {pkg} | {ver} | GPL-3.0 | No | Copyleft in proprietary project |
| {pkg} | {ver} | Unknown | Unknown | License not identifiable |

### Maintenance Health

| Package | Last Release | Commits (90d) | Maintainers | Status |
|---------|-------------|---------------|-------------|--------|
| {pkg} | {date} | {N} | {N} | {Healthy/Warning/Abandoned} |

### Security Vulnerabilities

| Package | Version | CVE | Severity | Fix Available | Fixed In |
|---------|---------|-----|----------|---------------|----------|
| {pkg} | {ver} | {CVE-ID} | {severity} | {Yes/No} | {version} |

### Bloat Analysis

| Package | Install Size | Used By | Recommendation |
|---------|-------------|---------|----------------|
| {pkg} | {size} | {usage description} | {Remove/Replace/Keep} |

### Action Items

#### Immediate (Security)
1. Upgrade {pkg} to {version} — fixes {CVE-ID} ({severity})

#### Short-term (License)
1. Review {pkg} GPL usage — may require license change or removal

#### Medium-term (Maintenance)
1. Find alternative to {pkg} — abandoned since {date}

#### Long-term (Bloat)
1. Remove {pkg} — unused in codebase
2. Replace {pkg} with lighter alternative

### Transitive Risk
- {direct-dep} depends on {transitive-dep} which has {issue}
```

## Calibration Rules

1. **Production dependencies first.** Dev/test dependencies have lower risk since they
   don't ship to users. Audit production dependencies with higher scrutiny.
2. **Transitive risk is real.** A direct dependency with MIT license may pull in a GPL
   transitive dependency. Always check the full tree.
3. **Abandoned is not broken.** A mature, stable library that hasn't been updated in a
   year may be perfectly fine. Evaluate based on whether the library is "done" vs "neglected."
4. **Security is non-negotiable.** Critical and High CVEs must be addressed immediately.
   Medium CVEs should be tracked. Low CVEs can wait for the next dependency update cycle.

## Error Handling

| Problem                                 | Resolution                                                                                             |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| No lock file available                  | Audit based on declared dependencies. Note that transitive analysis is incomplete without a lock file. |
| License metadata missing                | Check the package's repository for LICENSE file. Note packages where license cannot be determined.     |
| Package registry unavailable            | Work from cached metadata and local lockfile data.                                                     |
| Too many dependencies to audit manually | Prioritize: production deps first, then direct deps, then transitive deps with known issues.           |

## When NOT to Audit

Push back if:

- The project is a prototype that won't ship — defer audit until production decision
- The user wants dependency updates, not audit — different task (dependabot, renovate)
- The project has no dependencies (pure standard library) — nothing to audit

## Rationalizations

| Rationalization | Reality |
|---|---|
| "It's a trusted package" | Trust is not a security model — trusted packages get compromised (event-stream, ua-parser-js, colors.js) |
| "Only a minor version bump" | Minor versions can introduce vulnerabilities, change behavior, or add transitive dependencies — semver is a promise, not a guarantee |
| "We don't use the vulnerable function" | Transitive dependencies might — and attack surface includes any code loaded into the process |
| "The CVE is low severity" | Low severity in isolation can be critical in your context — a "low" SSRF in an internal service with cloud metadata access is critical |
| "We'll update when there's a known exploit" | Known exploits mean you're already behind — patch within SLA, not after breach |
| "Too many dependencies to audit" | That's the problem, not an excuse — high dependency count IS a risk finding |

## Red Flags

- Auditing only direct dependencies while ignoring transitive dependency tree
- Dismissing CVEs without checking if the vulnerable code path is reachable
- No license compatibility check — GPL in a proprietary codebase is a legal finding
- Accepting "no known vulnerabilities" from a single scanner without cross-referencing
- Ignoring dependency age — unmaintained packages with no updates in 2+ years are a risk
- Skipping lockfile analysis (pinned vs. floating versions)

## Verification

- [ ] Both direct and transitive dependencies scanned
- [ ] Vulnerability scanner output captured: `npm audit` / `pip-audit` / `cargo audit`
- [ ] Each CVE finding includes: severity, affected version range, upgrade path, reachability assessment
- [ ] License compatibility verified against project license
- [ ] Dependency age and maintenance status checked for top-level deps
- [ ] Lockfile present and version pinning verified — no floating ranges in production
