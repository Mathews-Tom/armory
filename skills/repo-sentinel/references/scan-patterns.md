# Scan Patterns Reference

All detection commands for each attack surface. Run these during audits.

---

## Surface 0 — Git Object Store (History)

The most critical scan — catches secrets in ALL commits, not just HEAD.

### With dedicated tools (preferred)

```bash
# trufflehog — verified secret detection with entropy analysis
trufflehog git file://. --only-verified --json 2>/dev/null

# gitleaks — pattern + entropy based detection
gitleaks detect --source . --verbose --report-format json --report-path gitleaks-report.json

# git-secrets — AWS-focused but extensible
git secrets --scan-history
```

### Without tools (fallback)

```bash
# Scan all commits for high-signal secret patterns
git log --all -p --diff-filter=ACM | grep -nE \
  '(api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|secret[_-]?key|private[_-]?key|password|passwd|credential)\s*[:=]\s*["'"'"'][^\s"'"'"']{8,}'

# Find all files EVER committed (including deleted)
git log --all --diff-filter=A --name-only --format="" | sort -u | \
  grep -iE '\.(env|pem|key|p12|pfx|credentials|keystore|jks|sqlite|sql|dump)$'

# High-entropy strings across history (novel secret formats)
git log --all -p --diff-filter=ACM | grep -oE '[A-Za-z0-9+/=_-]{40,}' | \
  sort -u | head -50
```

---

## Surface 1 — Source Code

```bash
# Hardcoded secrets — high-signal patterns
git grep -nE '(api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|secret[_-]?key|private[_-]?key|password|passwd|credential)\s*[:=]\s*["\x27][^\s"'\'']{8,}' \
  -- '*.ts' '*.js' '*.py' '*.go' '*.rs' '*.rb' '*.java' '*.cs' '*.php'

# Internal/private IPs and hostnames
git grep -nE '(10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+|\.internal|\.corp\.|\.local[^h])' \
  -- ':!*.lock' ':!node_modules'

# AWS account IDs (12-digit numeric in relevant context)
git grep -nE '\b\d{12}\b' -- '*.ts' '*.js' '*.py' '*.yaml' '*.yml' '*.json' '*.tf' | \
  grep -iE '(account|arn|aws)'

# Cloud resource identifiers (AWS, GCP, Azure)
git grep -nE '(arn:aws:|projects/[a-z][\w-]+/|/subscriptions/[0-9a-f-]{36})' -- ':!*.lock'

# Unparameterized connection strings
git grep -nE '(mongodb|postgres|mysql|redis|amqp|mssql)(\+\w+)?://[^${\s]+@' \
  -- '*.ts' '*.js' '*.py' '*.go' '*.env*'

# JWT tokens (often hardcoded in tests)
git grep -nE 'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.' -- ':!*.lock' ':!node_modules'

# GitHub/GitLab personal access tokens
git grep -nE '(ghp_[A-Za-z0-9]{36}|glpat-[A-Za-z0-9\-]{20,})' -- ':!*.lock'

# Slack tokens and webhooks
git grep -nE '(xox[bporas]-[A-Za-z0-9-]+|hooks\.slack\.com/services/)' -- ':!*.lock'

# High-entropy strings (catches novel secret formats)
git grep -noE '[A-Za-z0-9+/=]{40,}' -- '*.py' '*.js' '*.ts' '*.go' '*.rb' '*.java' | head -30
```

---

## Surface 2 — Documentation

```bash
# Internal URLs in docs
git grep -nE 'https?://[^\s)>]*\.(internal|corp|local|intranet|private)' \
  -- '*.md' '*.rst' '*.txt' '*.adoc'

# Ticket references to private trackers
git grep -nE '(JIRA|LINEAR|ASANA|SHORTCUT|CLUBHOUSE|NOTION)-?\s*[A-Z]*-?\d+' \
  -- '*.md' '*.rst' '*.txt'

# Person names after @ or contact verbs
git grep -nE '(@[a-zA-Z][\w-]+|(ask|contact|ping|reach out to)\s+[A-Z][a-z]+)' \
  -- '*.md' '*.rst' '*.txt'

# TODO/FIXME/HACK with sensitive context
git grep -nE '(TODO|FIXME|HACK|XXX|SECURITY|VULNERABILITY):?\s' \
  -- '*.md' '*.ts' '*.js' '*.py' '*.go' '*.rs' '*.rb'

# Sensitive TODO/FIXME with security keywords
git grep -rnE '(TODO|FIXME|HACK|XXX)\b.*\b(security|auth|bypass|vulnerability|exploit|hack|password|credential|secret|token|admin)' \
  -- ':!*.lock'
```

---

## Surface 3 — Configuration Files

```bash
# Tracked .env files (non-example/template)
git ls-files | grep -iE '\.env(\.|$)' | grep -v '\.example$\|\.template$'

# Tracked credential files
git ls-files | grep -iE '\.(pem|key|p12|pfx|keystore|jks|credentials)$'

# Secrets in non-.env config files
git grep -nE '(password|token|key|secret|credential)\s*[:=]\s*["\x27][^\s"'\'']{8,}' \
  -- '*.yaml' '*.yml' '*.json' '*.toml' '*.ini' '*.cfg' ':!*.lock'

# .env.example containing real values (should show only placeholders)
if [ -f .env.example ]; then
  grep -E '=' .env.example | grep -vE '=(your-|placeholder|changeme|xxx|example|TODO|REPLACE|""|\x27\x27|$)'
fi

# Editor configs with absolute paths
git grep -nE '(/home/|/Users/|C:\\\\Users|/var/|/etc/)' -- '.vscode/' '.idea/' '*.code-workspace'
```

---

## Surface 4 — .gitignore Reconnaissance

```bash
# Comments in .gitignore (attacker documentation)
grep -n '^#' .gitignore 2>/dev/null

# Specific filenames that reveal internal tools/services
grep -nE '^[^*#/].*\.' .gitignore 2>/dev/null | grep -vE '^\d+:\.'

# Tracked-but-ignored contradictions
git ls-files -i --exclude-standard 2>/dev/null

# .claude/ tracked check
git ls-files | grep '\.claude/'

# CLAUDE.md tracked check
git ls-files | grep -i 'claude\.md'

# Missing critical entries
for pattern in '.claude/' 'CLAUDE.md' '.env' '*.pem' '*.key' '*.p12' '*.pfx' '*.tfstate'; do
  grep -q "$pattern" .gitignore 2>/dev/null || echo "MISSING: $pattern not in .gitignore"
done
```

---

## Surface 5 — CI/CD Pipelines

```bash
# Secrets in workflow files
git grep -nE '(password|token|key|secret|credential)\s*[:=]\s*[^\s${\[]' \
  -- '.github/workflows/*.yml' '.gitlab-ci.yml' 'Jenkinsfile' '.circleci/config.yml'

# Hardcoded IPs in CI
git grep -nE '\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b' \
  -- '.github/workflows/*.yml' '.gitlab-ci.yml'

# Internal runner labels
git grep -nE 'runs-on:\s*(self-hosted|[a-z]+-prod|[a-z]+-internal)' \
  -- '.github/workflows/*.yml'

# Actions pinned to mutable refs (supply chain risk)
git grep -nE 'uses:\s+\S+@(main|master|v\d+)\s*$' -- '.github/workflows/*.yml'

# Overly permissive workflow permissions
git grep -nE 'permissions:\s*(write-all|read-all)' -- '.github/workflows/*.yml'

# Private registries in CI
git grep -nE '(registry|image):\s*[^\s]*\.(internal|corp|private)' \
  -- '.github/workflows/*.yml' '.gitlab-ci.yml' 'Jenkinsfile'
```

---

## Surface 6 — Container & IaC

```bash
# Secrets in Dockerfiles
git grep -nE '(ENV|ARG)\s+\w*(PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL)\w*\s*=' -- 'Dockerfile*'

# COPY of secret files in Dockerfiles
git grep -nE 'COPY\s+.*(\.env|credentials|\.key|\.pem|secret)' -- 'Dockerfile*'

# Internal base images
git grep -nE 'FROM\s+[^\s]*\.(internal|corp|private)' -- 'Dockerfile*'

# Inline secrets in docker-compose
git grep -nE '(password|token|key|secret):\s*["\x27]?[^\s${\[]+["\x27]?' \
  -- 'docker-compose*.yml' 'docker-compose*.yaml' 'compose*.yml' 'compose*.yaml'

# Terraform state files tracked
git ls-files | grep -iE '\.tfstate(\.backup)?$'

# Terraform variable files with real values tracked
git ls-files | grep -iE '\.tfvars$' | grep -v '\.example'

# Hardcoded values in Terraform
git grep -nE '(account_id|project_id|subscription_id)\s*=\s*"[^${\s]' -- '*.tf'
```

---

## Surface 7 — Dependencies & Lock Files

```bash
# Private registries in lock files
git grep -nE '(registry\.internal|private-npm|artifactory\.|nexus\.|\.corp\.com)' \
  -- '*lock*' '*.lock' 'go.sum' 'Pipfile.lock'

# Internal scoped packages
git grep -nE '@(internal|corp|private)/' \
  -- 'package.json' 'package-lock.json' 'yarn.lock' 'pnpm-lock.yaml'

# Git+SSH dependencies (private repos)
git grep -nE 'git(\+ssh)?://|git@github\.com:[^/]+/[^/]*(private|internal)' \
  -- 'package.json' 'Pipfile' 'go.mod' 'Cargo.toml' 'pyproject.toml'

# Private PyPI indices
git grep -nE '(index-url|extra-index-url)\s*=\s*https?://[^\s]*(internal|corp|private)' \
  -- 'pip.conf' 'setup.cfg' 'pyproject.toml' 'requirements*.txt'

# Private npm registry config
git grep -nE 'registry\s*=\s*https?://[^\s]*(internal|corp|private|artifactory)' \
  -- '.npmrc' '.yarnrc' '.yarnrc.yml'
```

---

## Surface 8 — Binary & Large File Artifacts

```bash
# Binary/non-text files that shouldn't be tracked
git ls-files | xargs file 2>/dev/null | grep -vE '(ASCII|UTF-8|empty|JSON|XML|SVG)' | \
  grep -vE '\.(svg|png|jpg|jpeg|gif|ico|woff2?|ttf|eot|webp):'

# Jupyter notebook outputs with potential secrets
git grep -nE '(api[_-]?key|token|password|sk-|Bearer|authorization)' -- '*.ipynb'

# Database files
git ls-files | grep -iE '\.(sql|sqlite|sqlite3|db|dump|bak|mdb|accdb)$'

# Archive files that might bundle secrets
git ls-files | grep -iE '\.(zip|tar|tar\.gz|tgz|rar|7z)$'

# Large files (>1MB) — potential data dumps
git ls-files | while read f; do
  size=$(git cat-file -s "HEAD:$f" 2>/dev/null)
  [ "${size:-0}" -gt 1048576 ] && echo "$f ($(( size / 1024 / 1024 ))MB)"
done

# PDF/image metadata containing internal paths (requires exiftool)
git ls-files | grep -iE '\.(pdf|docx?|xlsx?)$' | while read f; do
  exiftool -Author -Creator -Producer -Company "$f" 2>/dev/null | grep -v '^$'
done
```

---

## Surface 9 — Metadata

```bash
# Commit messages referencing vulnerabilities
git log --all --oneline | grep -iE '(bypass|exploit|vulnerability|hack|backdoor|auth.?fix|security.?hole)'

# Commit messages with credentials
git log --all --format="%H %s" | grep -iE '(password|token|secret|credential|api.?key)'

# Error messages in commit messages containing paths
git log --all --format="%s" | grep -nE '(/home/|/Users/|C:\\\\|/var/|/etc/|\.internal)'

# Branch names revealing internal features
git branch -a | grep -iE '(secret|internal|acquisition|unreleased|confidential)'
```

---

## Surface 10 — Platform-Specific (GitHub/GitLab)

```bash
# CODEOWNERS with individual names (should use team handles)
grep -nE '^\s*[^@#]' CODEOWNERS 2>/dev/null
grep -nE '@[a-zA-Z][\w-]+[^/]' CODEOWNERS 2>/dev/null | grep -v '@.*/'

# FUNDING.yml exposure check
cat .github/FUNDING.yml 2>/dev/null

# Dependabot with private registries
git grep -nE '(registry-url|url):\s*https?://[^\s]*(internal|corp|private)' \
  -- '.github/dependabot.yml'

# Actions pinned to mutable refs (already in Surface 5, repeated for completeness)
git grep -nE 'uses:\s+\S+@(main|master|v\d+)\s*$' -- '.github/workflows/*.yml'

# Wiki existence check (separately cloneable)
echo "NOTE: Check if wiki is enabled and contains sensitive content at repo settings"
```

---

## Surface 11 — License & Legal

```bash
# Missing LICENSE file
[ ! -f LICENSE ] && [ ! -f LICENSE.md ] && [ ! -f LICENSE.txt ] && \
  [ ! -f LICENCE ] && echo "WARNING: No LICENSE file found"

# Internal copyright headers
git grep -rnE 'Copyright.*\b(internal|confidential|proprietary)\b' -- ':!LICENSE*' ':!NOTICE*'

# License compatibility check (Node.js projects)
npx license-checker --summary 2>/dev/null || echo "license-checker not available"

# License compatibility check (Python projects)
pip-licenses --format=table 2>/dev/null || echo "pip-licenses not available"

# Missing NOTICE file for Apache 2.0 projects
if grep -q 'Apache' LICENSE 2>/dev/null && [ ! -f NOTICE ]; then
  echo "WARNING: Apache 2.0 license detected but NOTICE file missing"
fi
```

---

## Surface 12 — Community Surface

```bash
# Missing SECURITY.md
[ ! -f SECURITY.md ] && [ ! -f .github/SECURITY.md ] && \
  echo "WARNING: No SECURITY.md found — add responsible disclosure policy"

# Issue templates prompting for credentials
git grep -nE '(paste|provide|include).*(token|password|key|credential|secret|api)' \
  -- '.github/ISSUE_TEMPLATE/' '.github/issue_template*'

# PR template referencing internal processes
git grep -nE '(internal|corp|private|jira|linear|asana)' \
  -- '.github/PULL_REQUEST_TEMPLATE*' '.github/pull_request_template*'

# Bot configs leaking internal policies
git ls-files | grep -iE '(\.github/(stale|probot|semantic|release)\.yml|\.probot)'
```

---

## Fast-Path Audit (Staged Changes Only)

Use this for quick checks before committing. Scans only staged files.

```bash
#!/bin/bash
# Fast-path: scan staged changes only
STAGED=$(git diff --cached --name-only --diff-filter=ACM)
[ -z "$STAGED" ] && echo "No staged changes." && exit 0

echo "=== REPO SENTINEL FAST-PATH ==="
echo "Scanning $(echo "$STAGED" | wc -l | tr -d ' ') staged files..."
echo ""

# Secrets
echo "[Checking: hardcoded secrets]"
echo "$STAGED" | xargs git grep --cached -nE \
  '(api[_-]?key|secret[_-]?key|access[_-]?token|password|private[_-]?key)\s*[:=]\s*["\x27][^\s"'\'']{8,}' \
  -- 2>/dev/null

# Internal URLs
echo "[Checking: internal URLs]"
echo "$STAGED" | xargs git grep --cached -nE \
  '(10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+|\.internal|\.corp\.)' \
  -- 2>/dev/null

# Connection strings
echo "[Checking: connection strings]"
echo "$STAGED" | xargs git grep --cached -nE \
  '(mongodb|postgres|mysql|redis|amqp)://[^${\s]+@' \
  -- 2>/dev/null

# .env files
echo "[Checking: .env files]"
echo "$STAGED" | grep -iE '\.env(\.|$)' | grep -v '\.example$\|\.template$'

# Credential files
echo "[Checking: credential files]"
echo "$STAGED" | grep -iE '\.(pem|key|p12|pfx|credentials|keystore|jks)$'

# .claude/ or CLAUDE.md
echo "[Checking: .claude/ and CLAUDE.md]"
echo "$STAGED" | grep -iE '(\.claude/|claude\.md)'

echo ""
echo "=== FAST-PATH COMPLETE ==="
```

---

## Full Repo Audit (20+ checks)

Run all surface scans in sequence. Use the commands above per-surface, in order 0-12. The
SKILL.md output format template defines how to present findings.

### Execution sequence summary

| Check | Surface | What                                          |
| ----- | ------- | --------------------------------------------- |
| 1     | 0       | History scan (trufflehog/gitleaks or git log) |
| 2     | 1       | Hardcoded secrets in code                     |
| 3     | 1       | Internal URLs/IPs                             |
| 4     | 1       | Cloud resource IDs                            |
| 5     | 1       | Connection strings                            |
| 6     | 1       | JWT tokens and platform tokens                |
| 7     | 1       | High-entropy strings                          |
| 8     | 2       | Internal URLs in docs                         |
| 9     | 2       | Private tracker references                    |
| 10    | 2       | Person names in docs                          |
| 11    | 2       | Sensitive TODO/FIXME                          |
| 12    | 3       | Tracked .env and credential files             |
| 13    | 4       | .gitignore comments and reconnaissance        |
| 14    | 4       | Tracked-but-ignored contradictions            |
| 15    | 4       | Missing critical .gitignore entries           |
| 16    | 5       | CI/CD inline secrets and mutable action refs  |
| 17    | 6       | Container and IaC secrets                     |
| 18    | 7       | Private registries and internal packages      |
| 19    | 8       | Binary files, notebooks, database dumps       |
| 20    | 9       | Commit message and branch name leaks          |
| 21    | 10      | Platform metadata (CODEOWNERS, FUNDING, etc.) |
| 22    | 11      | License and legal compliance                  |
| 23    | 12      | Community surface (SECURITY.md, templates)    |

---

## Quick-Reference Scan Commands

The most critical inline checks. Full pattern set is elsewhere in this file.

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
