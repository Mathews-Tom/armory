---
name: migration-risk-analyzer
description: 'Analyzes database migration scripts for lock contention, downtime, rollback strategy, and deployment risk. Triggers on: "analyze this migration", "migration risk", "is this migration safe", "schema change risk", "DDL risk", "rollback strategy", "migration review".'
metadata:
  version: 1.1.1
  category: review
  tags: [database, migration, ddl, rollback]
  difficulty: advanced
  phase: review
---

# Migration Risk Analyzer

Systematic risk assessment for database migrations: parse DDL/DML operations, classify
lock types and durations, estimate downtime, design rollback strategies, identify
irreversible changes, and produce deployment recommendations with pre/post validation
queries.

## Reference Files

| File                               | Contents                                                | Load When                   |
| ---------------------------------- | ------------------------------------------------------- | --------------------------- |
| `references/lock-matrix.md`        | Operation-to-lock-type mapping for PostgreSQL, MySQL    | Always                      |
| `references/safe-patterns.md`      | Online DDL patterns, zero-downtime migration techniques | Risk mitigation needed      |
| `references/rollback-templates.md` | Rollback scripts for common DDL operations              | Rollback strategy requested |
| `references/validation-queries.md` | Pre/post migration validation SQL templates             | Always                      |

## Prerequisites

- The migration SQL or migration file (Alembic, Django, Flyway, etc.)
- Target database engine (PostgreSQL, MySQL)
- Approximate table sizes for affected tables (for duration estimation)

## Workflow

### Phase 1: Parse Migration

Extract all operations from the migration script:

1. **DDL operations** — CREATE TABLE, ALTER TABLE (ADD/DROP/MODIFY COLUMN, ADD/DROP INDEX),
   DROP TABLE, RENAME TABLE
2. **DML operations** — UPDATE, INSERT, DELETE on existing data
3. **Index operations** — CREATE INDEX, DROP INDEX, REINDEX
4. **Constraint operations** — ADD/DROP FOREIGN KEY, ADD/DROP CHECK, ADD/DROP NOT NULL

### Phase 2: Assess Lock Risk

For each operation, determine the lock type and impact:

| Lock Level     | Impact                      | Examples                                         |
| -------------- | --------------------------- | ------------------------------------------------ |
| No lock        | Zero impact                 | CREATE TABLE, CREATE INDEX CONCURRENTLY (PG)     |
| Share lock     | Blocks writes, allows reads | CREATE INDEX (non-concurrent)                    |
| Exclusive lock | Blocks all access           | ALTER TABLE ADD COLUMN (MySQL < 8.0), DROP TABLE |
| Row-level lock | Blocks affected rows only   | UPDATE with WHERE clause                         |

Consider:

- Table size (locks on 10-row tables are negligible; locks on 100M-row tables are critical)
- Concurrent query patterns (OLTP with high write rates vs. OLAP with batch queries)
- Lock timeout settings

### Phase 3: Estimate Duration

Estimate based on operation type and table size:

| Operation                 | Small Table (<100K) | Medium (100K-10M) | Large (>10M)                |
| ------------------------- | ------------------- | ----------------- | --------------------------- |
| ADD COLUMN (nullable)     | < 1s                | < 1s              | < 1s (PG) / minutes (MySQL) |
| ADD COLUMN (with default) | < 1s                | seconds           | minutes (table rewrite)     |
| CREATE INDEX              | < 1s                | seconds           | minutes-hours               |
| ADD NOT NULL              | seconds             | minutes           | hours (full scan)           |
| Backfill UPDATE           | seconds             | minutes           | hours                       |

### Phase 4: Design Rollback

For each operation, determine reversibility:

| Operation     | Reversible | Rollback                     |
| ------------- | ---------- | ---------------------------- |
| ADD COLUMN    | Yes        | DROP COLUMN                  |
| DROP COLUMN   | No         | Data is lost                 |
| ADD INDEX     | Yes        | DROP INDEX                   |
| DROP TABLE    | No         | Data is lost                 |
| RENAME COLUMN | Yes        | RENAME back                  |
| ALTER TYPE    | Sometimes  | May lose precision           |
| UPDATE data   | Sometimes  | Only if old values preserved |

For irreversible operations, recommend backup strategies.

### Phase 5: Generate Report

Produce a risk assessment with deployment recommendation.

## Output Format

````
## Migration Risk Analysis

### Summary
- **Operations:** {N} DDL, {M} DML
- **Tables affected:** {list with row counts}
- **Overall risk:** {High | Medium | Low}
- **Estimated duration:** {range}
- **Requires downtime:** {Yes | No}

### Operation Risk Table

| # | Operation | Risk | Lock Type | Est. Duration | Reversible |
|---|-----------|------|-----------|---------------|------------|
| 1 | {SQL operation} | {High/Med/Low} | {lock type} | {time} | {Yes/No} |

### Lock Analysis
- **Exclusive locks:** {list of operations that block all access}
- **Maximum lock duration:** {estimated time}
- **Affected queries:** {types of queries that will be blocked}

### Rollback Strategy

#### Reversible Operations
```sql
-- Rollback for operation 1: {description}
{rollback SQL}
````

#### Irreversible Operations

- **{operation}** — IRREVERSIBLE. Mitigation:
  ```sql
  -- Backup before migration
  {backup SQL}
  ```

### Pre-Migration Checklist

- [ ] Database backup completed
- [ ] Rollback scripts tested in staging
- [ ] Traffic reduction confirmed (if needed)
- [ ] Monitoring and alerting configured
- [ ] Stakeholders notified
- [ ] Connection pool sized for lock wait

### Post-Migration Validation

```sql
-- Verify structural changes
{validation queries}

-- Verify data integrity
{integrity checks}
```

### Deployment Recommendation

**Strategy:** {Online | Low-Traffic Window | Maintenance Window}
**Estimated downtime:** {time or "None with proper execution"}
**Rollback time:** {time}
**Risk mitigation:** {specific recommendations}

```text

## Calibration Rules

1. **Assume large tables.** If table size is unknown, assume it's large enough for
   locks to matter. Overestimating risk is safer than underestimating.
2. **Engine-specific analysis.** PostgreSQL and MySQL handle DDL very differently.
   PostgreSQL can add nullable columns without table rewrite; MySQL often cannot.
   Always target the specific engine.
3. **Irreversible means irreversible.** DROP COLUMN destroys data. No amount of
   rollback scripting recovers it. Flag every irreversible operation prominently.
4. **Test the rollback.** Rollback scripts must be tested in staging before the
   migration runs in production. Untested rollback is no rollback.
5. **Sequence matters.** The order of operations affects lock duration. Adding a
   column then backfilling then adding NOT NULL is safer than adding a NOT NULL
   column with a default.

## Error Handling

| Problem | Resolution |
|---------|------------|
| Database engine not specified | Ask. Lock behavior differs significantly between engines. |
| Table sizes unknown | Analyze without duration estimates. Flag that estimates require row counts. |
| ORM migration format (not raw SQL) | Parse the ORM migration file. Translate operations to SQL equivalents for analysis. |
| Migration has data-dependent logic | Flag conditional operations. Risk depends on data state at migration time. |
| Multiple migrations in sequence | Analyze each independently and as a group. Cross-migration lock accumulation is a risk. |

## When NOT to Analyze

Push back if:
- The migration is for a development/staging database — risk analysis is for production
- The migration only creates new tables (no ALTER, no existing data) — low risk by definition
- The user wants migration execution, not analysis — this skill assesses risk, it doesn't run migrations

## Rationalizations

| Rationalization | Reality |
|---|---|
| "It's backwards compatible" | Backwards compatible at the schema level doesn't mean backwards compatible at the application level — query plans, ORM mappings, and application code all interact |
| "We can roll back" | Rollback is not free — data written after migration may not survive rollback; DROP COLUMN has no rollback without backup |
| "It's a small table" | Table size is one factor — lock duration, concurrent write rate, and replication lag matter more than row count |
| "We've run this migration type before" | Past success doesn't predict future success — different data distribution, different load, different constraints |
| "Downtime window is long enough" | Estimate based on dev data, not production — migration on 10k rows takes seconds; on 50M rows with indexes, it takes hours |
| "The ORM handles it" | ORMs generate SQL, they don't guarantee safety — `ALTER TABLE` locking behavior is engine-specific and ORM-opaque |

## Red Flags

- No estimate of migration duration based on production data volume
- No rollback plan or rollback plan that doesn't account for data written post-migration
- Analyzing migration SQL without checking the current table size and write rate
- No consideration of replication lag in multi-replica setups
- Assuming zero downtime without verifying lock behavior for the specific DDL operation
- Skipping index analysis — adding an index on a large table can lock writes for minutes to hours

## Verification

- [ ] Production table sizes and row counts documented for all affected tables
- [ ] Lock behavior identified for each DDL statement (exclusive lock, no lock, etc.)
- [ ] Migration duration estimated using production-scale data, not dev fixtures
- [ ] Rollback plan documented with specific steps and data preservation guarantees
- [ ] Concurrent write impact assessed — what happens to in-flight transactions during migration
- [ ] Replication lag impact assessed for multi-replica configurations
