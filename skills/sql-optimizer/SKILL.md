---
name: sql-optimizer
description: 'Analyzes SQL queries for missing indexes, N+1 patterns, suboptimal joins, and full table scans. Interprets EXPLAIN, detects anti-patterns, rewrites queries. Triggers on: "optimize this query", "slow query", "add indexes", "explain plan", "N+1 query", "why is this query slow".'
metadata:
  version: 1.1.1
  category: data
  tags: [sql, performance, database, optimization]
  difficulty: intermediate
  phase: build
---

# SQL Optimizer

Systematic SQL performance analysis: parse query structure, interpret EXPLAIN plans,
detect anti-patterns (N+1, full scans, cartesian joins), recommend indexes, and rewrite
queries — with explanations of WHY each change improves performance, not just WHAT changed.

## Reference Files

| File                              | Contents                                                                  | Load When                          |
| --------------------------------- | ------------------------------------------------------------------------- | ---------------------------------- |
| `references/anti-patterns.md`     | Common SQL anti-patterns with detection rules and fixes                   | Always                             |
| `references/index-strategies.md`  | Index type selection, composite index ordering, covering indexes          | Index recommendations needed       |
| `references/explain-guide.md`     | Reading EXPLAIN output for PostgreSQL, MySQL, SQLite                      | EXPLAIN plan provided              |
| `references/join-optimization.md` | Join type selection, join order optimization, subquery-to-join conversion | Query contains joins or subqueries |

## Prerequisites

- The SQL query to optimize
- Database engine (PostgreSQL, MySQL, SQLite) — optimization differs by engine
- Table schemas and approximate row counts (helpful but not required)
- EXPLAIN output (highly valuable when available)

## Workflow

### Phase 1: Query Analysis

Parse the SQL to understand its structure:

1. **Identify operations** — SELECT columns, FROM tables, JOIN conditions, WHERE filters,
   GROUP BY, ORDER BY, HAVING, subqueries.
2. **Map table relationships** — Which tables are joined? On what keys? Are there
   implicit cartesian products?
3. **Detect immediate red flags**:
   - `SELECT *` — fetching unnecessary columns
   - Functions on indexed columns in WHERE — prevents index use
   - `OR` in WHERE — often prevents index use
   - Correlated subqueries — potential N+1
   - Missing WHERE on DELETE/UPDATE — dangerous

### Phase 2: EXPLAIN Interpretation

If an EXPLAIN plan is provided:

1. **Scan types** — Sequential Scan (bad for large tables), Index Scan (good),
   Index Only Scan (best), Bitmap Index Scan (acceptable).
2. **Join methods** — Nested Loop (good for small tables), Hash Join (good for
   equi-joins), Merge Join (good for sorted data).
3. **Row estimates** — Compare estimated rows with actual rows. Large discrepancies
   indicate stale statistics (`ANALYZE`).
4. **Cost hotspots** — Highest-cost node is the bottleneck. Optimize there first.
5. **Sort operations** — External sorts (disk) are expensive. Consider indexes
   that match ORDER BY.

### Phase 3: Anti-Pattern Detection

Check for known performance anti-patterns (see `references/anti-patterns.md`):

| Pattern                     | Detection                      | Impact                     |
| --------------------------- | ------------------------------ | -------------------------- |
| SELECT \*                   | Star in select list            | Transfers unnecessary data |
| N+1 queries                 | Loop with query inside         | N additional roundtrips    |
| Function on indexed column  | `WHERE UPPER(name) = 'X'`      | Index bypass               |
| Implicit type cast          | String compared to integer     | Index bypass               |
| Missing join condition      | Cartesian product              | Exponential rows           |
| LIKE '%prefix'              | Leading wildcard               | Full scan                  |
| OR with different columns   | `WHERE a=1 OR b=2`             | Index bypass               |
| SELECT DISTINCT as band-aid | Hides duplicate-producing join | Fix the join instead       |

### Phase 4: Optimization

1. **Index recommendations** — Based on WHERE, JOIN, ORDER BY, GROUP BY columns.
   Consider composite indexes for multi-column conditions.
2. **Query rewrite** — Convert correlated subqueries to JOINs, replace `IN (SELECT...)`
   with EXISTS, use CTEs for readability without performance cost (PostgreSQL 12+
   may inline CTEs).
3. **Schema suggestions** — Denormalization, materialized views, partitioning
   (mention only when query-level optimization is insufficient).

### Phase 5: Output

Present the original query, detected issues, recommended indexes, rewritten query,
and explanation of each change.

## Output Format

````mardkown
## SQL Optimization Analysis

### Original Query
```sql
{original SQL}
```

### Issues Detected

| #   | Issue   | Severity          | Location            | Impact           |
| --- | ------- | ----------------- | ------------------- | ---------------- |
| 1   | {issue} | {High/Medium/Low} | {WHERE/JOIN/SELECT} | {what it causes} |

### EXPLAIN Interpretation

{If EXPLAIN provided}

- **Bottleneck:** {node type} on `{table}` (cost: {N})
- **Rows scanned:** {N} (estimated {M})
- **Index used:** {name or "None"}
- **Key insight:** {what this reveals}

### Recommended Indexes

```sql
-- {Reason for this index}
CREATE INDEX {name} ON {table}({columns});
```

### Optimized Query

```sql
{rewritten query}
```

### Change Explanation

1. **{Change}** — {Why this improves performance. Include estimated impact.}

### Expected Improvement

- Scan type: {before} → {after}
- Estimated rows scanned: {before} → {after}
- Index usage: {before} → {after}

````

## Configuring Scope

| Mode       | Input                                 | Depth                                    | When to Use                          |
| ---------- | ------------------------------------- | ---------------------------------------- | ------------------------------------ |
| `quick`    | Single query                          | Anti-pattern scan + index suggestion     | Fast feedback during development     |
| `standard` | Query + schema                        | Full analysis with rewrites              | Default for optimization requests    |
| `deep`     | Query + EXPLAIN + schema + row counts | Full analysis with statistics validation | Production performance investigation |

## Calibration Rules

1. **Measure before optimizing.** Request EXPLAIN output before recommending changes.
   Intuition about query performance is unreliable — a "slow-looking" query may be
   fast with proper indexes, and a "simple" query may scan millions of rows.
2. **Index discipline.** Every index has write overhead. Do not recommend indexes
   that won't be used by the actual query workload. Consider the read/write ratio.
3. **Explain WHY, not just WHAT.** "Add an index on `users.email`" is incomplete.
   "Add an index on `users.email` because the WHERE clause filters by email, currently
   causing a sequential scan of 1M rows" is actionable.
4. **Preserve correctness.** Query rewrites must return identical results. If a
   rewrite changes semantics (e.g., INNER JOIN vs LEFT JOIN), flag it explicitly.
5. **Database engine matters.** PostgreSQL, MySQL, and SQLite have different optimizers,
   index types, and capabilities. Always target the specific engine.

## Error Handling

| Problem                      | Resolution                                                                                                       |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| No EXPLAIN output provided   | Analyze query structure and anti-patterns. Note that recommendations are best-effort without EXPLAIN.            |
| Unknown database engine      | Ask which engine. Default anti-pattern analysis applies to all engines.                                          |
| Query uses ORM-generated SQL | Optimize the SQL, then suggest ORM-level changes (e.g., `select_related` in Django, eager loading).              |
| Schema not provided          | Infer table structure from the query. Note assumptions.                                                          |
| Query is already optimal     | State that no significant improvements are possible. Suggest non-query optimizations (caching, denormalization). |
| Complex multi-CTE query      | Analyze each CTE independently, then analyze the composition.                                                    |

## When NOT to Optimize

Push back if:

- The query runs infrequently and performance is acceptable (one-time admin query)
- The optimization requires schema changes that affect many consumers — suggest an ADR instead
- The real problem is application-level (N+1 from ORM loop) — fix the application code, not the SQL
- The query is auto-generated by a tool (ORM migration, BI tool) — optimize at the tool level

```

```
