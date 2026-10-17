---
name: skill-inventory
type: utility
description: 'Measures installed skill metadata exposure and observed reads or invocations from local OMP, Claude Code and Codex logs. Use this utility when you ask "audit my skill inventory", "how much do skill descriptions cost?", "find unused managed skills", "which skills were read?", "find duplicate skills", or "restore archived skills". Covers offline measurement, conservative archive/merge proposals and reversible OMP managed-skill quarantine. NOT for general session/context audits (usage-audit), catalog installation (skill-library), or static package quality/effectiveness scoring (package-evaluator).'
metadata:
  version: 1.0.0
  category: workflow
  tags: [skills, inventory, exposure, privacy, quarantine]
  difficulty: advanced
utility: {runtime: python, entry_point: scripts/skill_inventory.py, executable: true}
---
# Skill inventory

Measure local skill-file metadata and persisted exposure; propose conservative actions without treating read frequency as usefulness.

## When to use

|Use when|Do not use when|
|---|---|
|Audit installed descriptions, observed reads/invocations or duplicate candidates|General context/token audit: use usage-audit|
|Review managed-skill keep/archive/merge proposals|Install/search the package catalog: use skill-library|
|List or restore a previous managed-skill quarantine|Score static package quality: use package-evaluator|

Triggers group into inventory/exposure ("audit my skill inventory", "how much do skill descriptions cost?"), usage/similarity ("find unused managed skills", "which skills were read?", "find duplicate skills"), and recovery ("restore archived skills").

## Prerequisites

macOS or Linux, Python 3.12+ and uv. The script pins PyYAML 6.0.3 in PEP 723 metadata. Set `UTILITY_ROOT` to the absolute unpacked or generated-wrapper package directory containing `scripts/`, then bootstrap only dependencies/help before reading private inputs:

```bash
uv run --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py" --help
```

Subsequent commands use `uv run --offline --no-project --script`; no repository imports, model calls or collector are required. Missing cached dependencies fail, not fall back to a network fetch. Native Claude installation is `~/.claude/utilities/skill-inventory`; a standalone `.utility` is a ZIP to unpack. Cursor/Codex generated adapters omit utilities; Gemini wraps the utility as a skill and copies scripts, adding one discovery entry rather than zero overhead.

## Workflow

1. Follow the [operator guide](references/operator-guide.md) to choose explicitly approved read roots, a UTC cutoff and fresh private output paths outside every Git repository/package.
2. Run offline `measure --aggregate-only`; inspect status, source/cohort, closure and unavailable channels before interpreting counts.
3. Run read-only `recommend` to produce a private proposal. Independently review pins, provenance, description-only coverage and dependencies; regenerate with reviewed policy. Missing policy or incomplete evidence keeps every skill.
4. Stop unless the owner separately authorizes live action and every approval/baseline gate is met. `archive` rebuilds current evidence and checks the saved proposal digest; choose explicit `--dry-run` before separately authorized `--apply`.
5. Use `restore --list`, then manifest/item dry-run and apply for recovery. Follow the matched before/after and quarantine protocol; no automatic merge or delete exists.

## Operations and common patterns

After the guide's environment setup, these are offline command patterns:

```bash
# Aggregate exposure; preserves incomplete/unavailable rather than claiming zero.
"${INV[@]}" measure "${MEASURE[@]}"
# Private proposal, initially without assertions; incomplete/all-keep is expected.
"${INV[@]}" recommend "${MEASURE[@]}" --proposal "$PRIVATE/preliminary-proposal.json"
# Read-only recovery discovery; identities remain private in manifests.
"${INV[@]}" restore --list
```

The guide supplies complete setup and separate reviewed-policy, archive and per-item restore commands. `--log-root`, `--skill-root`, `--alias-target` and `--reference` are repeatable approved read inputs, not mutation authorization. No utility-specific environment variables are required; shell variables above are operator conveniences.

## Output

Stdout, including errors, is anonymous aggregate JSON. Exit `0` means complete for supported declared inputs/channels; exit `2` means incomplete/refused, not an empty successful measurement. Private snapshots/proposals/reports contain sensitive bindings or installed identities: owner-only `0600`, outside all repositories/packages, create-only or identical idempotent replay. Use fresh names for changed runs. Snapshots bind HMAC integrity, not raw-log copies.

## Safety and limits

Only default OMP discovery can establish managed ownership. Mutation is fixed to `~/.omp/agent/managed-skills`, with quarantine under `~/.omp/agent/skill-inventory-archive`; there is no home/root mutation override. User/shared skills, Claude/plugin/cache skills and all Codex skills remain protected/report-only. Explicit skill-root overrides have unknown ownership. Managed location alone proves neither authorship nor history.

Measured characters and labeled characters/4 estimates are not billed tokens, cache attribution, dollars or utility. OMP main prompts are unavailable; Claude listings can be partial/lower-bound; Codex native reads/invocations are unavailable, and its cached catalog is not enabled inventory. MUST-read policy confounds body-read frequency; descriptions may help without reads. Native atomic no-replace moves require supported Darwin/Linux primitives and one filesystem; unsupported platforms refuse, without unsafe fallback. Batches are journaled but not atomic as a whole.

Live quarantine has not started; its end date is unset. Package completion grants neither live mutation nor study/spend authority. Regression, including no-cost preregistration, remains separately blocked.

## Troubleshooting

- Exit `2`: inspect aggregate fixed codes using the [diagnostic map](references/measurement.md#blocking-diagnostics-and-safe-next-actions), coverage and closure, not just counts; do not patch logs, assert coverage or relax schemas to obtain zero errors.
- Snapshot/output mismatch: preserve old private artifacts, stop writers and choose fresh paths for a genuinely new capture; do not overwrite a saved binding.
- All-keep: review policy and supported closed-cohort evidence; missing age, provenance or observation opportunity is a protection, not an invitation to fill invented values.
- Restore conflict: retain both trees, inspect privately and resolve with the owner; never overwrite a differing live name.

## References

|Document|Purpose|
|---|---|
|[Operator guide](references/operator-guide.md)|Executable setup, private schemas, approvals and recovery protocol|
|[Measurement](references/measurement.md)|Source coverage, exact counting and snapshot semantics|
|[Recommendations](references/recommendations.md)|Conservative eligibility and similarity policy|
|[Archive](references/archive.md)|Fixed-root journal, move and restore invariants|
