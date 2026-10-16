# Archive and restore of managed OMP skills

The only mutating operation this utility has is moving a reviewed, harness-generated skill directory out of the OMP managed root into a private archive run, and moving it back. It never deletes, edits, chmods or rewrites a skill, never reads or changes harness configuration, and never touches Claude, Codex, plugin or user skill roots. Everything below is conservative by design: any doubt refuses.

## Fixed locations

| What | Location (under the home directory) |
|---|---|
| Source (only mutable root) | `.omp/agent/managed-skills/<name>` |
| Archive root (owner-only, `0700`) | `.omp/agent/skill-inventory-archive/` |
| Utility lock | `.omp/agent/skill-inventory-archive/.lock` |
| Run root (owner-only) | `.omp/agent/skill-inventory-archive/<run-id>/` |
| Private manifest and journal (`0600`) | `.omp/agent/skill-inventory-archive/<run-id>/manifest.json` |
| Archived entries (owner-only) | `.omp/agent/skill-inventory-archive/<run-id>/skills/<name>` |

`<run-id>` is generated (`YYYYMMDDTHHMMSSZ-<8 hex>`). The home directory is the current user's home in production; there is no flag to point the mutation at another root. The manifest is private installed-file data: it holds installed skill names, complete file hashes and modes, and the proposal/approval binding. Keep it; do not paste it into reports. Public output never contains names, hashes or paths.

A move is a same-filesystem directory rename, so bytes and modes are preserved exactly and nothing is copied. Roots and every ancestor below the home directory must be real directories (no symlinks), owned by you, and not group- or world-writable; the archive root, run roots and `skills/` must additionally be owner-only. A Git work tree anywhere above the archive root (including a Git-managed home directory) makes the private-file boundary refuse, by design.

## Before you apply

You, not the tool, do these. The tool cannot see harness configuration and does not try to.

1. Disable auto-learning through the harness's supported setting and stop every runtime that can write to the managed root (all OMP sessions, subagents and background jobs). A utility lock is not a harness-writer lock.
2. Capture the baseline: 20 ordinary new subagent init snapshots across at least 5 main tasks, with a stable harness, configuration and renderer. Do not run paid sessions only to fill the count.
3. Run `measure`, then `recommend`. Review the private proposal: pins, generated-only attestations and their tree digests, every item, and each merge pair. Existing files carry no generation marker, so each selected item needs your attestation that it was harness-generated and never user-authored; location alone never authorizes a move.
4. Write the approval document (below) to a private file outside Git and the package. List only the items you reviewed, at most 10, least risky first.
5. Run the archive dry-run. It rebuilds the proposal from fresh inputs, requires its digest to equal the saved one, re-scans the whole managed tree, enforces the dwell rules, and creates nothing (no directory, lock or manifest). It reports only aggregates.
6. Apply only if the dry-run is `complete`/`dry_run_ready`.

### Approval document (schema 1)

```json
{
  "schema_version": 1,
  "proposal_digest": "<saved proposal digest>",
  "items": [{"name": "<installed name>", "tree_digest": "<tree digest from the proposal>"}],
  "auto_learning_disabled": true,
  "writers_stopped": true,
  "coverage_reviewed": true,
  "ordinary_sessions_attested": true,
  "baseline_reviewed": true
}
```

Every attestation must be exactly `true`; the items must be a non-empty subset (at most 10, no duplicates) of the proposal's `archive_candidate` entries whose attestation flags hold and whose tree digests match. Anything else is refused. Without an approval, apply is refused and the dry-run reports `approval_required`.

## What apply does

1. Validates both proposals, the approval, roots, devices and history, then re-scans the whole managed tree (every byte, mode and listing) under the lock.
2. Stages a private run root, writes the manifest with every item `planned`, fsyncs it, and renames the run root into place. This is the write-ahead journal: nothing moves before it is durable.
3. For each item: re-verify the whole source tree equals the original minus the items already moved, rename the entry into `skills/` by descriptor, fsync both directories, verify the archived bytes and modes, record `moved` (atomic replace plus fsync), then verify the source again.
4. Stops at the first deviation (a concurrent writer, a recreated name, an unexpected destination). Items already moved stay recorded; later items stay `planned`. There is no batch-wide atomicity, and the tool never undoes a move on its own.

## Dwell and quarantine

* Quarantine is 21 days per batch; the overall earliest end is the final move date plus 21 days, with a complete post-measurement cohort. Reports show the dates; nothing is deleted at day 21. Unexercised items return to keep or are restored unless you explicitly renew the quarantine.
* A later batch needs at least 7 calendar days and at least 20 proven ordinary inventory observations strictly after the prior batch's last move day (the move day is partial and discarded). The observations are counted from the current proposal's daily histogram, never from a number you type. Missing history, an unfinished run, an unresolved conflict or an incomplete proposal refuses.
* A proposal whose as-of is later than the real operation time is refused (`future_evidence_cutoff`); an analysis clock cannot age evidence.

## Restore

Listing is read-only and aggregate-only; it reconciles filesystem evidence in memory and creates nothing:

```bash
uv run --offline --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py" restore --list
```

An unreadable or unknown-schema run is reported as damaged (never as zero); a missing archive root is the explicit `no_runs`. Restore one item, review, then apply (repeat `--item` for a subset; omit it for every item in the run):

```bash
uv run --offline --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py" restore --manifest "$PRIVATE_MANIFEST" --item "$INSTALLED_SKILL_NAME" --dry-run
uv run --offline --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py" restore --manifest "$PRIVATE_MANIFEST" --item "$INSTALLED_SKILL_NAME" --apply
```

`PRIVATE_MANIFEST` is the fixed manifest path of one run; paths outside the archive root or with a different name are refused. Each item ends in one of these states:

| State | Meaning |
|---|---|
| `planned` | Journaled; may or may not have moved. Reconciled from the filesystem. |
| `moved` | In the archive run, original bytes and modes verified. |
| `restored` | Back in the managed root with the original bytes and modes, or safely closed in place when a planned item never moved and was subsequently edited. Edited live bytes are preserved. |
| `externally_restored` | An identical live copy already existed (bytes and modes). It is recorded; neither copy is deleted or touched. |
| `conflict` | A different entry with the same name is live, the archived copy changed, or it is missing. Both copies are kept and nothing is overwritten. |

`restored` and `externally_restored` are final and idempotent: later edits to a restored skill are yours and are never reverted or flagged. A `conflict` is re-evaluated on the next restore; resolve it yourself (for example, move the live entry aside), then restore again. Same-name or similar recreation is a quarantine restore trigger, not proof of utility and never permission to overwrite.

If both the live and archived copies are absent, recovery cannot distinguish a never-moved deletion from an unjournaled move whose archive was later removed. It stays a conflict and blocks later batches. Recover the original bytes and modes from an independent backup at the fixed live or archive location, then run restore again; never fabricate a replacement or discard the journal to bypass the conflict.

### After an interruption

If a run was interrupted (crash, power loss, `incomplete` output), do not start another batch. Use `restore --list`: a rename that happened without its journal record shows as `moved` and needs reconciliation; a restore that happened without its record shows as `restored`. Run `restore --apply` for the items you want back; the same call records the true state of every other item without moving it (so a partly finished batch you want to keep stays archived). Items that never moved remain `planned` until you restore them (a no-op that records them as restored). A later batch is refused while any item is still `planned` or in `conflict`. Leftover staging directories (`.stage-*`) and journal temporaries (`.manifest-*.tmp`) are inert and are never deleted by the tool.

## Public report vocabulary

Reports are JSON with `schema_version`, `operation`, `mode` (`dry_run`, `apply`, `list`), `status`, `outcome`, `counts`, `diagnostics` (fixed codes mapped to counts), and, where relevant, `run_id` and dates. `status` is `complete` for success; `incomplete` and `refused` are failures for exit-code purposes.

| Operation | Outcomes |
|---|---|
| archive | `dry_run_ready`, `approval_required`, `applied`, `partial`, `refused` |
| restore | `listed`, `no_runs`, `dry_run_ready`, `restored`, `conflict`, `partial`, `refused` |

Common refusal codes: `proposal_drift`, `proposal_incomplete`, `source_changed`, `tree_mismatch`, `tree_entry_unsafe`, `root_unsafe`, `cross_device`, `approval_*`, `future_evidence_cutoff`, `dwell_days_insufficient`, `dwell_sessions_insufficient`, `unfinished_run`, `unresolved_conflict`, `history_unreadable`, `archive_locked`, `manifest_integrity`, `manifest_schema_unsupported`, `manifest_invalid`, `destination_unexpected`, `restore_item_unknown`, `manifest_path_invalid`. They describe the class of failure only; they never contain a name, hash or path.

## Limitations

* The manifest integrity digest detects accidental damage and naive edits. It is not a signature: a same-user adversary who recomputes it is outside the threat model, and attestations are owner assertions, never proof of history.
* The lock serializes this utility only. It cannot stop a harness writer; that is why the attestations above are mandatory and why the whole tree is re-verified around every move.
* A batch is not atomic. Individual moves use native atomic no-replace rename on Darwin/Linux, including empty concurrently created destinations. Unsupported platforms or filesystems fail closed; there is no non-atomic fallback.
* On macOS the tool additionally requests a full device flush for each fsync when the filesystem supports it.
* Anything outside the OMP managed root (Claude, Codex, plugins, user skills) is out of scope and is never touched.
