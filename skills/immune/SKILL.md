---
name: immune
description: 'Hybrid adaptive memory: Cheatsheet (positive patterns pre-generation) and Immune (negative patterns post-generation) with Hot/Cold tiered auto-learning. Triggers on: "scan for errors", "immune scan", "check output quality", "antibody scan". NOT for PR review (use pr-review) or repo audits (use repo-sentinel).'
metadata:
  version: 1.0.1
  status: active
  classification: tooling-wrapper
  source: https://github.com/contactjccoaching-wq/immune
  category: review
  tags: [memory, error-detection, antibodies, adaptive]
  difficulty: intermediate
---

# Immune System v3 — Hybrid Cheatsheet + Immune

You operate a hybrid adaptive system with two complementary memories:

- **Cheatsheet** (positive patterns): domain-specific strategies injected BEFORE generation to improve output quality
- **Immune** (negative patterns): antibodies that detect known errors and discover new threats AFTER generation

Both memories use Hot/Cold tiering to keep context lean.

## Input Parsing

The user invokes with content to scan. Parse these parameters:

- **input**: The text/code/content to scan (required — either inline or from context)
- **domain**: One of: fitness, code, writing, research, strategy, webdesign, \_global (default: auto-detect)
- **domains**: Array of domains (overrides single domain). Example: `domains=fitness,code`
- **constraints**: Any specific requirements the output should satisfy (optional)
- **mode**: `full` (cheatsheet + scan, default) | `scan-only` (skip cheatsheet) | `cheatsheet-only` (return cheatsheet, no scan)

<examples>
<example>
/immune Check this function for common pitfalls
→ domains=["code"] (auto-detected), mode=full
</example>
<example>
/immune domain=fitness Vérifie ce programme de musculation
→ domains=["fitness"] (explicit)
</example>
<example>
/immune domains=fitness,code Check this workout generator API
→ domains=["fitness", "code"] (multi-domain)
</example>
<example>
/immune
→ scans the most recent output in the conversation
</example>
</examples>

If no inline text is provided, scan the last substantive output in the conversation.

**Domain auto-detection:** Read `config.yaml` (co-located with this skill) and match content against `domain_keywords`. If no strong match, use `["_global"]`. If single `domain` string provided, wrap in array: `domains = [domain]`.

## Task-Conditioned Retrieval (v3.1.0+)

Antibodies and cheatsheet strategies may carry an optional `triggers` field for
per-task filtering. This implements the read phase of the Memento-Skills
reflective loop (arXiv 2603.18743) — entries are ranked by lexical overlap
between the current task and their historical contexts.

**Schema (additive, optional):**

```json
{
  "id": "AB-042",
  "domains": ["code"],
  "pattern": "SQL injection via string concatenation",
  "severity": "critical",
  "correction": "Use parameterized queries",
  "triggers": {
    "task_signatures": ["code query review sql", "audit code sql"],
    "domains": ["code"]
  }
}
```

**Back-compat:** entries without `triggers` behave as always-on (the v3.0.0
behavior). The `task_conditioned_retrieval: true` flag in `config.yaml` enables
the filter. When disabled, all entries load regardless of task.

**Ranking helper:** `scripts/retrieve.py` implements the scoring logic. Callers
(including the scanner agent, the skill-librarian in P2, and the skill-router
in P3) invoke `retrieve(prompt, entries, active_domains, historical_success)`
to obtain the ranked subset before tier classification. Scoring uses Jaccard
similarity over normalized task signatures from `scripts/task_signature.py`,
multiplied by an optional per-entry success rate derived from
`evals/history.jsonl`.

During load (Phase 0 cheatsheet, Phase 1 antibodies), after the domain filter
and before Hot/Cold tier classification, apply the retrieve step:

1. Compute `task_signature(prompt)` for the current task.
2. Pass entries through `retrieve(...)` with the active domains set.
3. Feed only the returned subset into the tier classification below.

Entries filtered out at retrieval never reach Hot/Cold — this is what keeps
the scan context lean and task-focused.

## Execution

### Step 0 — Cheatsheet Injection (positive patterns)

Skip this step if `mode == "scan-only"`.

**0a. Load cheatsheet:**
Read `cheatsheet_memory.json` (co-located with this skill).

**0b. Filter by domains:**
Keep strategies where ANY of the strategy's `domains` overlaps with the detected `domains`, OR strategy has `"_global"` in its domains.

**0c. Classify into tiers (same logic as antibodies):**
A strategy is HOT if ANY of:

- `effectiveness >= 0.7`
- `seen_count >= 3`
- `last_seen` less than 30 days ago

Everything else is COLD.

**0d. Cap HOT strategies:**
Sort by effectiveness descending, then seen_count descending.
Keep max **15** (from `config.yaml` → `cheatsheet.max_hot`).

**0e. Build cheatsheet block:**
Format HOT strategies as XML:

```xml
<cheatsheet domain="{domains}">
  <strategy id="{id}" effectiveness="{effectiveness}">
    {pattern}
    Example: {example}
  </strategy>
  ...
</cheatsheet>
```

If there are COLD strategies, add a one-liner:

```xml
<cheatsheet_cold>Also consider: {comma-separated COLD pattern keywords}</cheatsheet_cold>
```

If `mode == "cheatsheet-only"`, output the cheatsheet block and stop here.

Log:

```
[IMMUNE] Cheatsheet: {n_hot} HOT + {n_cold} COLD strategies (domains: {domains})
```

**0f. Present cheatsheet to user:**
If running standalone (`/immune`), show the cheatsheet as context the user should apply to their next generation. If called by another system, return the XML block for injection into prompts.

### Step 1 — Load & Classify Antibodies (Hot/Cold)

Read `immune_memory.json` and `config.yaml` (co-located with this skill).

**1a. Filter by domains:**
Keep antibodies where ANY of the antibody's `domains` overlaps with detected `domains`, OR antibody has `"_global"` in its domains.

**Backwards compatibility:** If an antibody has `"domain"` (string) instead of `"domains"` (array), treat it as `domains = [domain]`.

**1b. Classify into tiers:**
For each filtered antibody, classify as HOT if **any** of these is true:

- `severity == "critical"`
- `seen_count >= 3`
- `last_seen` is less than 30 days ago (relative to today's date)

Everything else is COLD.

**1c. Cap HOT antibodies:**
Sort HOT by: severity (critical > warning > info), then seen_count descending.
Keep max **15** (from `config.yaml` → `tiers.hot.max_per_scan`).
If more than 15 qualify as HOT, overflow goes to COLD.

**1d. Build COLD summary:**
For each COLD antibody, extract a short keyword from its `pattern` field.
Join as comma-separated list. Example: `"SQL transactions, épicondylite, debug flags, tautologies"`

Log:

```
[IMMUNE] Tier split: {n_hot} HOT + {n_cold} COLD / {total} total (domains: {domains})
```

### Step 2 — Scan

Spawn the `immune-scan` agent (Haiku) with the following XML-structured prompt:

```xml
<scan_request>
  <domains>{detected_domains as JSON array}</domains>
  <task>{task description or "Scan the following content for errors and threats"}</task>
  <constraints>{constraints or "none"}</constraints>

  <content>
{the input text/code/content to scan}
  </content>

  <hot_antibodies>
{JSON array of HOT antibodies — full objects with id, domains, pattern, severity, correction}
  </hot_antibodies>

  <cold_summary>
Dormant patterns (not detailed, for awareness only): {comma-separated COLD keywords}
  </cold_summary>

  <cheatsheet_applied>
{list of strategy IDs and patterns that were injected in Step 0, or "none" if scan-only mode}
  </cheatsheet_applied>
</scan_request>
```

Log: `[IMMUNE] Scanning... ({n_hot} active antibodies)`
Wait for result.

If corrections applied:
Log: `[IMMUNE] Match {antibody_id}: {original} → {corrected}`
If new threats detected:
Log: `[IMMUNE] New threat: {pattern}`
If new strategies detected:
Log: `[IMMUNE] New strategy: {pattern}`

### Step 3 — Update Immune Memory (with COLD deduplication)

Read current `immune_memory.json`.

**3a. Matched HOT antibodies:**
For each antibody matched by the scanner, increment `seen_count` and update `last_seen` to today.

**3b. New threats — deduplicate against COLD:**
For each new threat in `new_threats_detected`:

1. Compare its `pattern` against ALL COLD antibodies (fuzzy match — same domains + similar keywords).
2. **If it matches a COLD antibody** → REACTIVATE:
   - Increment the COLD antibody's `seen_count`
   - Update its `last_seen` to today
   - Log: `[IMMUNE] Reactivated COLD antibody {id}: {pattern}`
   - Do NOT create a new antibody (prevents duplicates)
3. **If no COLD match** AND `auto_add_threats` is true → CREATE new antibody:
   - id: "AB-{next_number}"
   - domains: from the threat's `recommended_antibody.domains` (array)
   - pattern, severity, correction: from the threat's `recommended_antibody`
   - seen_count: 1
   - first_seen: today's date
   - last_seen: today's date
   - Log: `[IMMUNE] + New antibody {id}: {pattern}`

**3c. Update stats:**

- Increment `stats.outputs_checked`
- Increment `stats.issues_caught` by number of corrections + new threats
- Update `stats.antibodies_total` to current antibody count

Write back to `immune_memory.json`.

Log: `[IMMUNE] Memory: {total} antibodies ({n_hot} hot, {n_cold} cold) | +{new} added | Reactivated: {reactivated}`

### Step 3b — Update Cheatsheet Memory (positive patterns)

Skip if `mode == "scan-only"` or no `new_strategies_detected` in scan result.

Read current `cheatsheet_memory.json`.

**3b-i. Deduplicate:**
For each new strategy in `new_strategies_detected`:

1. Compare against ALL existing strategies (fuzzy match — overlapping domains + similar pattern).
2. **If it matches an existing strategy** → REINFORCE:
   - Increment `seen_count`
   - Update `last_seen` to today
   - Adjust `effectiveness`: `new_eff = old_eff * 0.8 + reported_eff * 0.2` (exponential moving average)
   - Log: `[IMMUNE] Reinforced strategy {id}: {pattern} (eff: {old}→{new})`
3. **If no match** AND `auto_add_strategies` is true → CREATE new strategy:
   - id: "{prefix}-{next_number}" (prefix from `config.yaml` → `cheatsheet.id_prefix.{domain}`)
   - domains: from the strategy (array)
   - pattern, example: from the strategy
   - effectiveness: from the strategy (or `config.yaml` → `cheatsheet.default_effectiveness`)
   - seen_count: 1
   - first_seen: today's date
   - last_seen: today's date
   - Log: `[IMMUNE] + New strategy {id}: {pattern}`

**3b-ii. Prune low-effectiveness:**
If any strategy has `effectiveness < config.cheatsheet.min_effectiveness` AND `seen_count >= 5`:

- Remove it
- Log: `[IMMUNE] - Pruned strategy {id}: {pattern} (eff: {eff})`

**3b-iii. Update stats:**

- Increment `stats.outputs_assisted`
- Increment `stats.strategies_applied` by number of cheatsheet strategies that were used
- Update `stats.strategies_total` to current count

Write back to `cheatsheet_memory.json`.

Log: `[IMMUNE] Cheatsheet: {total} strategies | +{new} added | Reinforced: {reinforced}`

### Step 4 — Output

**If clean:**

```
───
IMMUNE v3 | domains={domains} | Status: CLEAN
   Cheatsheet: {n_strategies} strategies applied | Antibodies: {n_hot}/{max} HOT, {n_cold} COLD
   No issues detected
───
```

**If corrections or threats found:**

```
───
IMMUNE v3 | domains={domains} | Status: {CORRECTED|FLAGGED}

Corrections Applied:
  [AB-XXX] {pattern} → {correction}

New Threats Detected:
  [{severity}] {pattern} — {suggested_correction}

Reactivated:
  [AB-XXX] {pattern} (was COLD, now HOT)

New Strategies Learned:
  [CS-XXX] {pattern} (eff: {effectiveness})

───
Corrected Output:
{the corrected content, formatted for the domain}
───
Memory: {total_ab} antibodies + {total_cs} strategies | +{new_ab} AB | +{new_cs} CS
───
```

Then present the corrected output in a human-readable format appropriate to the domain.

## Error Handling

- If `immune_memory.json` does not exist: create it with `{"version": 3, "antibodies": [], "stats": {"outputs_checked": 0, "issues_caught": 0, "antibodies_total": 0}}`
- If `cheatsheet_memory.json` does not exist: create it with `{"version": 3, "strategies": [], "stats": {"outputs_assisted": 0, "strategies_applied": 0, "strategies_total": 0}}`
- If `immune_memory.json` has `"version": 2`: auto-migrate by converting each antibody's `"domain"` to `"domains": ["domain_value"]` and set version to 3. Write back immediately.
- If the agent returns invalid JSON: retry once. If still invalid, report the raw output with a warning.
- If no input is provided and no recent output exists: ask the user what to scan.
- If all antibodies are COLD (none qualify as HOT): still send the scan with empty `hot_antibodies` array and full `cold_summary`. Haiku can still detect new threats via Phase 2.
