# Remediation Reference

Procedures for fixing findings across all surfaces, including history contamination.

---

## Quick Remediation Table

| Found                           | Replace with                                                                             |
| ------------------------------- | ---------------------------------------------------------------------------------------- |
| Hardcoded credential            | Env var reference (`os.environ["X"]`, `process.env.X`) + `.env.example` with placeholder |
| Internal URL                    | Env var or config injection. In docs: `https://api.example.com`                          |
| Real PII in fixtures            | Faker-generated or synthetic data (`user@example.com`, `Jane Doe`)                       |
| Cloud resource ID               | Env var. In IaC: parameterize. Never hardcode account/project IDs                        |
| Business logic comment          | Remove entirely. `// HACK: bypass rate limit` → delete the comment                       |
| Debug endpoint                  | Gate behind env check + remove from public route definitions                             |
| Private tracker reference       | Remove or use public issue link. `JIRA-4521` → `#123` (public issue)                     |
| Person name in docs             | Use role or team handle. `Ask @john` → `Ask the maintainers`                             |
| Internal copyright              | Genericize. `© CorpName Internal` → `© Project Contributors`                             |
| Specific filename in .gitignore | Extension glob. `oauth-creds.json` → `*.credentials.json`                                |
| Comment in .gitignore           | Delete. Every comment is attacker documentation                                          |
| Mutable action ref              | Pin to SHA. `@v4` → `@<full-commit-sha>`                                                 |
| `permissions: write-all`        | Minimum required: `contents: read`, `pull-requests: write`, etc.                         |
| Service name in compose         | Genericize. `fraud-detector` → `analyzer`                                                |
| Private registry in lock file   | Remove internal dep, replace with public equivalent or vendor                            |
| Jupyter notebook output         | Clear outputs: `jupyter nbconvert --clear-output --inplace *.ipynb`                      |

---

## History Contamination Decision Tree

### Triage

| Pushed to public remote? | Contains real credentials? | Action                                                |
| ------------------------ | -------------------------- | ----------------------------------------------------- |
| No                       | Any                        | `git rm --cached` + fix `.gitignore`. Done.           |
| Yes                      | No (template/placeholder)  | `git rm --cached` + fix `.gitignore`. Scrub optional. |
| Yes                      | Yes                        | **Full protocol below.** Assume compromise.           |

### Full History Scrub Protocol

#### Step 1: Backup

```bash
cp -r .git .git-backup
```

#### Step 2: Scrub with git filter-repo (preferred)

```bash
# Install if needed
pip install git-filter-repo

# By exact path
git filter-repo --invert-paths --path <file> --force

# By glob pattern
git filter-repo --invert-paths --path-glob '*.pem' --force

# By regex
git filter-repo --invert-paths --path-regex '.*secret.*' --force

# By content (replace secret values in-place across all history)
git filter-repo --blob-callback '
  blob.data = blob.data.replace(b"sk-live-actual-secret", b"REDACTED")
' --force

# Re-add remote (filter-repo strips it)
git remote add origin <url>
git push --force --all && git push --force --tags
```

#### Step 3: Scrub with BFG Repo-Cleaner (fallback)

```bash
# By filename
java -jar bfg.jar --delete-files <filename> .git

# By content pattern
echo 'sk-live-actual-secret' > passwords.txt
java -jar bfg.jar --replace-text passwords.txt .git
rm passwords.txt

# Cleanup
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

#### Step 4: Post-scrub protocol (non-optional, all steps)

1. **Rotate every exposed credential immediately.**
   Scrubbing history does NOT un-expose. GitHub caches git objects for ~90 days. Mirrors,
   forks, and security scanners may have already indexed the content. Assume compromise.

2. **Verify scrub:**

   ```bash
   git log --all --full-history -- <path>
   # Must return empty

   git log --all -p | grep -c '<secret-value>'
   # Must return 0
   ```

3. **Update all ignore/exclude rules** before next commit.

4. **Force-push all branches and tags:**

   ```bash
   git push --force --all
   git push --force --tags
   ```

5. **GitHub-specific actions:**
   - For severe exposure: consider repo deletion + recreation
   - Contact GitHub support for cache invalidation if deletion is not viable
   - Request GitHub to run garbage collection: support ticket
   - Check GitHub's secret scanning alerts for automated detection

6. **Invalidate all forks:**
   Forks retain the original objects. If the repo has public forks, the secret is
   permanently exposed via those forks regardless of your scrub. Factor this into
   your rotation urgency.

7. **Rotate CI/CD secrets independently.**
   Pipeline secret stores are unaffected by git history operations. If the leaked
   credential was also used in CI, rotate it there too.

8. **Audit third-party integrations.**
   If the credential granted access to external services (Stripe, AWS, Slack, etc.),
   check those services' audit logs for unauthorized use during the exposure window.

9. **Document the incident internally:**
   - What was exposed
   - How long it was exposed (first commit → scrub timestamp)
   - Which remotes had the data
   - What was rotated
   - Who was notified
   - Timeline of actions taken

---

## Credential Rotation Quick Reference

| Credential Type         | Rotation Procedure                                                                 |
| ----------------------- | ---------------------------------------------------------------------------------- |
| AWS Access Keys         | IAM Console → Create new key → Update all references → Deactivate old → Delete old |
| GCP Service Account Key | IAM Console → Create new JSON key → Update → Delete old                            |
| Azure Service Principal | `az ad sp credential reset` → Update references                                    |
| GitHub PAT              | Settings → Developer Settings → Regenerate → Update                                |
| GitLab PAT              | User Settings → Access Tokens → Revoke + Create new                                |
| Stripe API Key          | Dashboard → API Keys → Roll Key → Update                                           |
| Database Password       | Change password in DB → Update all connection strings → Restart services           |
| JWT Signing Secret      | Generate new secret → Deploy to all services → Invalidate existing tokens          |
| SSH Key                 | Generate new keypair → Update authorized_keys → Remove old public key              |
| OAuth Client Secret     | Provider dashboard → Regenerate secret → Update all clients                        |
| Slack Token             | Slack API → Regenerate token → Update all integrations                             |

**Critical:** After rotation, verify the OLD credential no longer works. Don't just create a new
one — explicitly revoke/disable the old one.

---

## .env File Remediation

When a `.env` file with real values is tracked:

```bash
# 1. Remove from tracking (keeps local file)
git rm --cached .env
git rm --cached .env.local
git rm --cached .env.production

# 2. Ensure .gitignore covers it
echo '.env' >> .gitignore
echo '.env.*' >> .gitignore
echo '!.env.example' >> .gitignore
echo '!.env.template' >> .gitignore

# 3. Create safe example
grep -E '^[A-Z_]+=' .env | sed 's/=.*/=your-value-here/' > .env.example

# 4. Commit the fix
git add .gitignore .env.example
git commit -m "chore: remove tracked .env files, add .env.example"

# 5. If pushed to public remote: full history scrub + rotate ALL values in .env
```

---

## Jupyter Notebook Remediation

Notebooks frequently contain secrets in cell outputs (API responses, connection details).

```bash
# Clear all outputs from all notebooks
find . -name '*.ipynb' -exec jupyter nbconvert --clear-output --inplace {} \;

# Or use nbstripout for pre-commit integration
pip install nbstripout
nbstripout --install  # Adds as git filter

# Verify no secrets remain in notebook JSON
git grep -nE '(api[_-]?key|token|password|sk-|Bearer)' -- '*.ipynb'
```

Add to `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/kynan/nbstripout
  rev: 0.7.1
  hooks:
    - id: nbstripout
```

---

## Actions SHA Pinning

Replace mutable tag references with SHA pins to prevent supply chain attacks.

```bash
# Find current SHA for a given action and tag
# Visit: https://github.com/<org>/<action>/commits/<tag>
# Use the full 40-character commit SHA

# Before (vulnerable):
# uses: actions/checkout@v4

# After (pinned):
# uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
```

Always add a comment with the human-readable version for maintainability.

---

## License Remediation

### Adding a LICENSE file

1. Choose an appropriate license (MIT, Apache 2.0, GPL, etc.)
2. Create `LICENSE` file in repo root with full license text
3. If Apache 2.0: also create `NOTICE` file
4. Add license field to package manifest (`package.json`, `pyproject.toml`, `Cargo.toml`)
5. Optionally add SPDX identifier to source file headers

### Resolving license incompatibility

| Your license | Dependency license        | Compatible?          | Action                             |
| ------------ | ------------------------- | -------------------- | ---------------------------------- |
| MIT          | MIT, BSD, Apache 2.0, ISC | ✅                   | None                               |
| MIT          | GPL-2.0, GPL-3.0          | ❌ (if distributing) | Replace dep or change your license |
| Apache 2.0   | MIT, BSD, Apache 2.0      | ✅                   | None                               |
| Apache 2.0   | GPL-2.0                   | ❌                   | Replace dep                        |
| Apache 2.0   | GPL-3.0                   | ✅ (one-way)         | Document in NOTICE                 |
| GPL-3.0      | Any OSS                   | ✅                   | Attribute in NOTICE                |
| Proprietary  | GPL                       | ❌                   | Replace dep immediately            |

---

## Quick-Reference Remediation

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

## .gitignore Generation

Generate a complete, opinionated `.gitignore` tailored to detected project type with all
hygiene rules baked in. Read `references/templates.md § .gitignore Generator`.
