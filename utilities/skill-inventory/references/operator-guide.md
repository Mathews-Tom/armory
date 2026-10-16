# Skill inventory operator guide

This guide works from an unpacked package: no Armory repository modules are imported. Commands below are Bash, run locally by the owner. They are instructions, not permission to access logs or change the live inventory. Review [measurement](measurement.md), [recommendations](recommendations.md) and [archive](archive.md) for implementation contracts.

## 1. Bootstrap, then stay offline

Use macOS or Linux with Python 3.12+ and uv through your approved local tooling. Set `UTILITY_ROOT` to the absolute package directory containing `scripts/` and either `UTILITY.md` (native/unpacked) or the generated `SKILL.md` (Gemini wrapper). The native Claude location is shown:

```bash
UTILITY_ROOT="$HOME/.claude/utilities/skill-inventory"
uv run --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py" --help
INV=(uv run --offline --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py")
```

For a standalone `.utility` ZIP, unpack it and change `UTILITY_ROOT` to that directory first. The bootstrap may obtain Python/dependencies; it opens no logs. PEP 723 pins `PyYAML==6.0.3`; all following calls are offline and fail if that dependency is unavailable. No API key/model/provider is needed. Cursor/Codex generated adapters omit utilities; Gemini's wrapper adds one skill entry, so discovery overhead is not zero.

## 2. Declare the private run

Obtain owner approval for the actual input roots and any instruction/agent reference files before reading them. The example selects OMP's default log directory explicitly and leaves skill discovery at its default; it is not authority to read that directory. Replace the cutoff with the agreed UTC instant for your run. The shown date is a fictional example, not an observed session date. Choose closed, stable inputs through that cutoff; stop writers when necessary outside this utility.

```bash
umask 077
PRIVATE_BASE="$HOME/.local/state/skill-inventory-private"
mkdir -p "$PRIVATE_BASE"
chmod 700 "$PRIVATE_BASE"
PRIVATE=$(mktemp -d "$PRIVATE_BASE/run.XXXXXXXX")
AS_OF_UTC='2026-01-15T00:00:00Z'
APPROVED_LOG_ROOT="$HOME/.omp/agent/sessions"
MEASURE=(--harness omp --aggregate-only --as-of "$AS_OF_UTC" --window-days 90
  --snapshot "$PRIVATE/measurement-snapshot.json" --log-root "$APPROVED_LOG_ROOT")
"${INV[@]}" measure "${MEASURE[@]}" --private-report "$PRIVATE/measurement-private.json"
rc=$?
printf 'utility_exit=%s\n' "$rc"
```

Before running, ensure `PRIVATE_BASE` is outside **every** Git repository and package, not a symlink into one, with acceptable owner/ancestor permissions. Generated private files are `0600`. Do not redirect private JSON into a repository, paste it into chat/CI, or use shell tracing. Keep the `PRIVATE` variable locally; the utility intentionally does not print identifying paths. Use a new `mktemp` run and output names for each changed capture.

`--reference "$APPROVED_REFERENCE"` may be repeated, but only after assigning that variable to an owner-approved actual file. Missing dependency references remain a coverage gap; omission does not declare an empty complete protection set. Repeat `--log-root` to replace log discovery with multiple approved roots. Explicit `--skill-root` overrides are read-only and unknown ownership, even when a path ends in `managed-skills`; do not use them to enable archive.

Default read discovery includes:

|Harness|Log roots|Skill-file roots and limits|
|---|---|---|
|OMP|`~/.omp/agent/sessions`|`~/.omp/agent/managed-skills`; protected `~/.omp/agent/skills` and `~/.agents/skills`|
|Claude Code|`~/.claude/projects`|Protected `~/.claude/skills`, shared skills and versioned installed-plugin registry resources|
|Codex|`~/.codex/sessions`|Protected `~/.codex/skills`, `.system`, shared skills and supported plugin-cache manifest resources|

To inspect another harness, start a **fresh** private run, change both `--harness` and the approved log root, and do not reuse the OMP binding. Paths found inside logs do not authorize new filesystem roots. Claude/Codex catalogs and all user/shared skills are report-only. Cache presence is not active/enabled inventory.

## 3. Interpret aggregate results before recommendations

Exit `0` means complete for declared prefixes and supported channels, not universal coverage or permission to archive. Exit `2` means incomplete or refused; partial aggregates can still be useful. Unknown versions, wrong types and conflicts fail loudly with fixed codes, never silent successful zeros. Read `status`, `coverage`, `diagnostics`, `snapshot.closed` and source/cohort availability together. An unavailable/null channel is not zero use.

`snapshot.cohorts` is capture-time physical placement; `scope.files_by_cohort` is decoder-resolved logical role. These populations can differ without a parsing contradiction; see the [field map and blocking-diagnostic actions](measurement.md#blocking-diagnostics-and-safe-next-actions). Inspect catalog aliases only privately within already-approved installed roots, never by following new paths from logs. Retain incomplete status when no safe owner-reviewed resolution exists.

Persisted disclosure characters are measured Unicode code points; `token_estimate_chars_div_4` is explicitly a characters/4 estimate, not tokenizer/request/billing/cache evidence. Keep exposure sources and cohorts separate. OMP main prompts are not persisted; native invocation is unavailable. Claude initial listing truncation/downgrades yield lower bounds, and dynamic listings are partial rather than additive initial exposure. Codex native reads and invocations are unavailable. Read frequency is confounded by matching-skill MUST-read policy; description-only value is unmeasured. Never-read does not mean useless.

Snapshots freeze complete JSONL prefixes with private HMAC integrity bindings, not copies of raw logs. Replays require the same cutoff, window, approved roots and inventory. Appends/new files can make an old prefix nonclosed; unchanged-prefix replay is not unchanged-corpus replay. Changed output bytes require a new path rather than overwriting an old report.

An invalid initial capture can report populated snapshot metadata without persisting the requested binding file. `snapshot.valid=false` is not evidence that a reusable snapshot exists. Preserve the aggregate result and obtain stable approved inputs before a fresh capture; do not fabricate the missing binding. Exposure monthly summaries retain full history through the cutoff; `--window-days` is not a filter that turns those summaries into a matched new-session dogfood cohort.

## 4. Preliminary proposal and independent policy review

Generate installed identities/digests privately, without asserting history or counts:

```bash
"${INV[@]}" recommend "${MEASURE[@]}" \
  --proposal "$PRIVATE/preliminary-proposal.json"
```

Missing pins/attestations and incomplete coverage normally produce exit `2` and all-keep. The private proposal still enables human review of installed-file identities. View it in a local editor, not a terminal transcript or shared report. Never hand-author measurement counts, session groups, dates of observation, or a proposal. The utility generates the proposal and its digest.

The owner must independently establish authored provenance, exact tree lineage, description-only behavior, dependencies/aliases/autoload, historical opportunities and ordinary-session baseline. A directory under managed-skills is not proof that it was harness-generated or never user-authored. Pins/high-risk workflows, unresolved coverage, periodic/incident workflows and still-needed coverage remain protected. Missing or mismatched item evidence means keep.

Create these two private documents in a local editor, then `chmod 600` them. JSON schemas are exact, version `1`; extra/unknown fields or wrong types refuse. Examples below are **fictional syntax only**, not ready-to-approve files and not attestations for any installed skill.

Pins schema:

```json
{"schema_version":1,"pins":["fictional-pinned-example"]}
```

Populate `pins` with reviewed exact installed names. An explicitly reviewed empty list is allowed; do not substitute `[]` for missing review. Attestations schema:

```json
{
  "schema_version": 1,
  "items": [{
    "name": "fictional-generated-example",
    "tree_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "harness_generated": true,
    "never_user_authored": true,
    "historical_identity_attested_since": "2025-01-01T00:00:00Z",
    "description_only_reviewed": true,
    "coverage_still_needed": false,
    "periodic_or_incident_workflow": false
  }]
}
```

Copy only real installed names and matching tree digests from the **private preliminary proposal**, then review every assertion independently. These are owner assertions, not cryptographic historical proof. The timestamp must be a defensible UTC string ending `Z` or `+00:00`, not inferred from mtime; `null` is invalid. Unknown history means omit that item, leaving `attestation_missing` and keep. Do not prefill actual items with the fictional truth values above. Save as `$PRIVATE/pins.json` and `$PRIVATE/attestations.json`.

```bash
chmod 600 "$PRIVATE/pins.json" "$PRIVATE/attestations.json"
"${INV[@]}" recommend "${MEASURE[@]}" \
  --pins "$PRIVATE/pins.json" --attestations "$PRIVATE/attestations.json" \
  --proposal "$PRIVATE/reviewed-proposal.json"
```

If inputs drifted, stop and start a fresh capture/proposal instead. Eligibility requires a window of at least 90 days, reliable lower-bound age, at least 20 distinct logical observed subagent sessions across at least five proven captured parent-main groups, and complete supported closed evidence. Zero supported-window reads/invocations can support a never-read candidate only after all protections. Rare use (one or two) additionally requires known historical gap and idle time at least `max(window_days, 2 * gap)`; unknown gaps keep. Similarity uses frozen-stopword weighted Jaccard (name .4, description .4, headings .2; threshold .70), not transitive auto-clustering. Merge suggestions remain human review only, never executable merges.

## 5. Separate authorization and archive dry-run

**Live inventory quarantine is NOT STARTED; its end date is unset. This package delivery does not authorize it.** Stop here unless the owner separately authorizes live action. No regression/study, including no-cost preregistration, is authorized; separate 3a/3b/3c/3d and M2 model-fit/M4 pilot gates remain required. No benchmark harness or paid call belongs in this workflow.

Before any live batch, the owner must actually disable auto-learning and stop every inventory writer through harness configuration/process controls outside the utility. The utility never changes those settings. Review coverage and ordinary-session baseline, then explicitly approve a nonempty subset of at most ten currently eligible names/digests. Save `$PRIVATE/approval.json` privately with this exact schema; the fictional values below are not an approval:

```json
{
  "schema_version": 1,
  "proposal_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "items": [{
    "name": "fictional-generated-example",
    "tree_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }],
  "auto_learning_disabled": true,
  "writers_stopped": true,
  "coverage_reviewed": true,
  "ordinary_sessions_attested": true,
  "baseline_reviewed": true
}
```

Use the generated reviewed proposal's exact `proposal_digest` and selected item identities; never compute a replacement from edited evidence. Set the five flags to true **only after** the owner confirms the real facts; ordinary-session coverage is an assertion, not inferred from session counts. Missing confirmation means no action. Preserve policy/proposal/approval privately, without inventing a satisfied record.

```bash
chmod 600 "$PRIVATE/approval.json"
"${INV[@]}" archive "${MEASURE[@]}" \
  --pins "$PRIVATE/pins.json" --attestations "$PRIVATE/attestations.json" \
  --proposal "$PRIVATE/reviewed-proposal.json" --approval "$PRIVATE/approval.json" \
  --dry-run
```

Archive remeasures current inputs, rebuilds the proposal and requires exact saved digest equality. A dry-run writes nothing; it does not authorize apply. Only after inspecting a successful dry-run and receiving explicit apply authority, run the same command with `--apply` **instead of** `--dry-run`. Both modes are explicit/mutually exclusive. Stale proposals, changed files or incomplete evidence refuse rather than bypass checks.

Mutation has no root override: source is `~/.omp/agent/managed-skills`, destination is `~/.omp/agent/skill-inventory-archive/<run-id>/skills/<name>`, with private `0700` archive directories and `0600` `manifest.json`. Native atomic no-replace directory moves on supported Darwin/Linux must stay on one filesystem; unsupported primitives/platforms refuse without unsafe fallback. Stable whole listings, modes and bytes are checked. Write-ahead/fsync and atomic journal replacement support recovery, but a batch is not one atomic transaction. No user/Claude/Codex archive, automatic merge or deletion exists.

## 6. Baseline, after cohort and 21-day quarantine

This is a prospective protocol, not evidence that a run occurred:

1. Before mutation, collect **20 new supported closed session initializations**, not requests or copied files, from an explicitly matched source/cohort within a 21-day collection deadline. Retain separate source/cohort availability and closure evidence. The owner confirms these include ordinary sessions; counts alone cannot establish that.
2. Save/review that baseline and all approval facts before the first batch. If supported coverage or sufficient sessions is unavailable, stop; do not fill counts, widen claims or infer utility from character estimates.
3. After each separately approved batch of at most ten items, collect 20 new supported closed session initializations from the matched source/cohort within 21 days, with the same counting rules. Use fresh private capture/report paths and an explicit new cutoff. Record observed results privately, not imagined summaries.
4. Restore an affected skill on a covered failure. Stop further batches when outcomes worsen or sufficient comparable evidence cannot be obtained. A smaller description surface is not proof of success or token/money savings.
5. The next batch requires **both** at least seven days elapsed and at least 20 new proven sessions, plus new review/approval. Each batch remains quarantined at least 21 days; the overall end is after the final batch's quarantine, not 21 days after the first. There is no automatic purge at expiry.

No live end date or utility win is claimed. Any planned inventory reduction or estimated token target is a hypothesis, not an outcome.

The matched 20-session/21-day cohort collection and covered-failure review are operator gates, not an automatic outcome classifier. The archive command independently enforces the ten-item limit and later-batch seven-day/twenty-observation dwell. Do not attest `baseline_reviewed` until the prospective cohort protocol and ordinary-session review are actually satisfied.

## 7. Read-only list and reversible recovery

```bash
"${INV[@]}" restore --list
```

Listing is read-only and anonymous; it cannot combine with `--manifest`, `--item`, `--dry-run` or `--apply`. To locate a run, inspect your fixed private archive directory locally in a file manager, open its manifest privately, and select its actual run ID/item. Do not expect identifying paths or names on stdout. Set the following variables to the selected actual values before running; the guard prevents accidental unset paths:

```bash
: "${SELECTED_RUN_ID:?Set from the private archive directory}"
MANIFEST="$HOME/.omp/agent/skill-inventory-archive/$SELECTED_RUN_ID/manifest.json"
"${INV[@]}" restore --manifest "$MANIFEST" --dry-run
# After explicit restore authority, restore the whole selected manifest:
"${INV[@]}" restore --manifest "$MANIFEST" --apply
```

For a subset, choose the exact installed name recorded in that private manifest:

```bash
: "${SELECTED_ITEM:?Set from the private manifest}"
"${INV[@]}" restore --manifest "$MANIFEST" --item "$SELECTED_ITEM" --dry-run
# After explicit restore authority:
"${INV[@]}" restore --manifest "$MANIFEST" --item "$SELECTED_ITEM" --apply
```

Repeat `--item` for multiple selected items. Dry-run performs no filesystem writes. Restore checks manifest/tree integrity and fixed roots; it never overwrites an occupied differing live name. Identical externally restored trees leave both copies and close the item; conflicts preserve both for owner review. A planned never-moved item with no archive may close in place while preserving edited live bytes. Completed terminal items do not block later legitimate edits. Partial failure requires reviewing the journal and using restore, not manually deleting directories or editing the manifest. Keep private artifacts for the quarantine/recovery period; no utility command deletes them.

Pass the fixed absolute manifest path exactly as shown. Relative paths and symlinked spellings are refused as `manifest_path_invalid`; do not substitute an alternate root or edit the journal to bypass recovery checks.
