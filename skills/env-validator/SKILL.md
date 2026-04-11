---
name: env-validator
description: 'Validates .env files against code references and manifests for missing vars, type mismatches, insecure defaults, and unused entries. Triggers on: "validate env file", "check environment variables", "missing env vars", "check .env", "dotenv validation". NOT for secret scanning, use repo-sentinel.'
metadata:
  version: 1.0.1
  category: operations
  tags: [env, configuration, validation, dotenv, deployment]
  difficulty: intermediate
  phase: build
---

# Env Validator

Validates environment variable configurations by cross-referencing `.env` files against
project requirements. Catches missing variables, type errors, insecure defaults, and
orphaned entries before they cause runtime failures.

## Reference Files

| File                                 | Contents                                          | Load When              |
| ------------------------------------ | ------------------------------------------------- | ---------------------- |
| `references/validation-rules.md`     | Built-in validation rules and severity definitions | Always                |

## Prerequisites

- A `.env` file (or equivalent) in the project
- Optionally: `.env.example`, `docker-compose.yml`, or deployment manifests for cross-referencing

## Workflow

### Phase 1: Discovery

Locate environment configuration sources in the project:

1. **Primary file:** Find `.env` in the project root. If absent, check for `.env.local`, `.env.development`, `.env.production`
2. **Schema file:** Find `.env.example` or `.env.template` — this defines the expected variables
3. **Code references:** Grep for `os.environ`, `process.env`, `env::var`, `os.Getenv` patterns to find variables referenced in code
4. **Deployment manifests:** Check `docker-compose.yml`, `Dockerfile`, `k8s/` manifests for `${VAR}` or `ENV VAR` patterns

Report what was found before proceeding.

### Phase 2: Schema Extraction

Build the expected variable schema from discovered sources:

For each variable found across all sources, record:

| Field       | Source                                                    |
| ----------- | --------------------------------------------------------- |
| Name        | Variable name (e.g., `DATABASE_URL`)                      |
| Required    | Present in code references or marked required in example   |
| Type hint   | Inferred from usage (URL, integer, boolean, string, path) |
| Default     | Value in `.env.example` if present                         |
| Used in     | List of files that reference this variable                 |

### Phase 3: Validation

Run these checks against the primary `.env` file:

1. **Missing required variables** (CRITICAL)
   - Variable referenced in code but absent from `.env`
   - Variable in `.env.example` without a default but absent from `.env`

2. **Type mismatches** (HIGH)
   - `PORT=abc` when code does `int(os.environ["PORT"])`
   - `DEBUG=yes` when code expects boolean (`true`/`false`)
   - URL variables without valid URL format

3. **Insecure defaults** (HIGH)
   - `SECRET_KEY=changeme`, `PASSWORD=password`, `API_KEY=xxx`
   - `DEBUG=true` or `DEBUG=1` in production-targeted files
   - Empty values for security-critical variables

4. **Unreferenced variables** (MEDIUM)
   - Variables in `.env` not referenced anywhere in code or manifests
   - May indicate stale configuration

5. **Format issues** (LOW)
   - Lines without `KEY=VALUE` format
   - Trailing whitespace in values
   - Inconsistent quoting (mixing single/double/no quotes)
   - Duplicate variable definitions (last wins, but likely a mistake)

See `references/validation-rules.md` for the complete rule catalog.

### Phase 4: Report

Produce a structured validation report:

```markdown
# Environment Validation Report

**File:** `.env`
**Schema:** `.env.example` + code references
**Verdict:** PASS | FAIL

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | N     |
| HIGH     | N     |
| MEDIUM   | N     |
| LOW      | N     |

## CRITICAL

### [ENV-001] Missing required variable: DATABASE_URL

- **Referenced in:** `src/db.py:12`, `docker-compose.yml:8`
- **Expected type:** URL (postgresql://...)
- **Fix:** Add `DATABASE_URL=postgresql://user:pass@localhost:5432/dbname` to `.env`

## HIGH

...

## Unreferenced Variables

| Variable        | In .env | In Code | In Manifests | Status       |
|-----------------|---------|---------|--------------|--------------|
| LEGACY_API_KEY  | Yes     | No      | No           | Unreferenced |

## Recommendations

1. [Highest priority fix]
2. [Second fix]
```

## Error Handling

| Error                             | Resolution                                            |
| --------------------------------- | ----------------------------------------------------- |
| No .env file found                | Report absence; check for alternative env sources     |
| No .env.example or schema         | Validate based on code references only                |
| Binary or very large .env         | Skip; report as unsupported format                    |
| No code references found          | Validate format and security only; skip completeness  |

## Limitations

- Cannot validate runtime-injected variables (from vault, AWS SSM, etc.)
- Type inference is heuristic — may misclassify complex values
- Does not check variable values against external services (e.g., valid API key format)
- Production vs. development distinction requires file naming conventions
