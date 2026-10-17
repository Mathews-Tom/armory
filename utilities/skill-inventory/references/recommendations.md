# Skill inventory recommendations

`recommend` turns one complete `measure` result into **recommendations for human review**. It never moves, edits or deletes a skill, reads a log, opens a path that a log named, calls a model or uses the network. Recommendation alone never authorizes mutation: only a later, exact human approval of the proposal digest and per-item tree digests does, and only for OMP's managed root.

Read frequency is not utility. A skill with zero body reads can still act through its description, and main-session presence is unmeasured. Every candidate therefore carries explicit counter-evidence and needs a human "is coverage still needed?" decision.

## Two outputs, never confused

| | Public aggregate report | Private proposal |
|---|---|---|
| Kind | `skill-inventory-recommendation-report` | `skill-inventory-proposal` |
| Audience | stdout, tickets, review comments | the owner and the archive tool |
| Contains | counts, thresholds, fixed reason/diagnostic codes, calendar and opportunity aggregates, `proposal_digest` | installed skill names, per-skill tree hashes, the whole managed-root tree, normalized evidence rows, similar-pair token explanations, pin/reference names |
| Never contains | a skill name, path, description, tree hash, attestation, binding key or log identity | log-derived names, paths, session identifiers, prompts or message text |
| Persistence | none; print it | explicit `--proposal`-style path, owner-only (`0600`), outside every Git repository and the package; create-only, identical rewrite accepted |

`proposal_digest` is safe to publish: the proposal also hashes the private snapshot binding, whose random key means the digest cannot be used to guess names or trees.

## Inputs

`recommend(report, private_report, inventory, *, as_of, window_days, binding_path, pins_path, attestations_path)` consumes:

- `report`: the actual `measure` output (`status`, `scope`, `snapshot.valid`, `snapshot.closed`);
- `private_report`: the installed-name rows from `measure --private-report`, plus `inventory_observations_by_utc_day` (counts only, one earliest complete inventory observation per proven logical subagent session, within the window). Rows carry `name`, `ownership`, `installation_date`, `first_observed_inventory_date`, `window_read_attempts`, `window_invocation_attempts`, `window_first_use_date`, `window_last_use_date`, `largest_observed_inter_use_gap_days`, `inventory_present_subagent_snapshots`, `inventory_present_main_task_groups` and `inventory_presence_grouping_complete`. Rows are installed-file identities; no log identity is present. The opportunity fields are window-scoped counts of distinct logical subagent sessions and of the parent main groups proven from captured file membership. Unknown grouping is `false`, never inflated;
- `private_report["observed_activity_after_as_of"]`: a boolean computed by `measure` from the valid skill activity already present in the captured prefix **before** as-of filtering. `true` means later activity exists, so a historical cutoff must not authorize archiving; a missing value is unknown. Both make the proposal `incomplete`. It is counter-evidence only: window counts are unchanged, and the caller cannot supply a value or a count;
- `private_report["skills"][].log_observed_dependency`: an installed-name-only boolean from recognized OMP autoload and agent-injection dependencies. True protects the skill even with zero read/invocation events; missing is unknown and keeps it. This is conservative dependency evidence across captured valid records, not an invocation or a new exported log identity;
- `inventory`: the freshly loaded installed catalog and its approved reference names;
- the private snapshot binding (its keyed seal is verified, and its harness, `as_of`, window and inventory integrity must match);
- the private pins file and the private attestation file.

### Pins (`schema_version: 1`)

```json
{"schema_version": 1, "pins": ["fictional-skill-a", "fictional-skill-b"]}
```

An explicit `[]` is valid and means "nothing pinned". An absent file is *not* an empty list: it makes the proposal `incomplete`. Duplicate names or any extra key fail with `pins_invalid`. A pinned installed name is kept regardless of age or use; pins naming nothing installed are counted, not rejected.

### Attestations (`schema_version: 1`)

```json
{
  "schema_version": 1,
  "items": [
    {
      "name": "fictional-skill-a",
      "tree_digest": "<64 lowercase hex: the current source tree digest>",
      "harness_generated": true,
      "never_user_authored": true,
      "historical_identity_attested_since": "2026-05-04T00:00:00Z",
      "description_only_reviewed": true,
      "coverage_still_needed": false,
      "periodic_or_incident_workflow": false
    }
  ]
}
```

Attestations are **owner assertions, not cryptographic proof of history**. Each binds one item to its current source tree: edit the skill after attesting and the digest no longer matches, so the item is kept (`attestation_digest_mismatch`). A missing item is kept (`attestation_missing`). Wrong types, unknown keys, duplicate names, a short or uppercase digest, or a timestamp that is not UTC (`Z`/`+00:00`) raise `attestations_invalid`. Booleans may record an unfavorable answer (`periodic_or_incident_workflow: true`); such an item is kept with that reason.

`historical_identity_attested_since` says the same installed name has meant the same generated skill since that instant. It is what makes log matches by name and the "first observed" date reliable lineage evidence.

## Classification precedence

1. **Keep** if any protection or insufficiency applies. Reasons list every one that applies:
   - harness other than OMP (`harness_not_mutable`); ownership `user`, `protected` or `unknown`; an alias or link; a duplicated installed name;
   - pinned; a high-risk whole token (`auth, authentication, approval, security, secret, secrets, privacy, permission, permissions, irreversible, payment, payments, migration, release, publish, restore, benchmark, provenance`) in the name, description or any heading, matched after Unicode NFC + casefold tokenization (so `authority` and `unreleased` do not match, `pre-release` and `SECURITY` do);
   - referenced by an approved instruction/agent definition, or by another installed skill's body through `skill://name`, `/skill:name`, `autoloadSkills` or dependency fields (the directory name also counts; a skill never protects itself);
   - no exact attestation for the current tree, a directory name different from the skill name, or an attestation whose lineage starts after `min(as_of − 90 days, window start)`;
   - age lower bound under 90 days (earliest of the file's birth time and an observation inside the attested lineage), a window shorter than 90 days, or fewer than 20 inventory-present subagent snapshots across 5 main-task groups, or unknown/incomplete grouping.
2. **Merge candidate**: both skills of a ≥ 0.70 pair are unprotected. Pairs involving a protected skill are shown for review but are non-actionable.
3. **Archive candidate**, for a skill that survived every protection:
   - *never read*: zero observed loads and invocations in the window (not lifetime);
   - *rare*: one or two combined observed loads/invocations in the window, the last at least 60 days old, and a window at least twice the largest observed inter-use gap. An unknown gap, unknown dates or an unavailable channel keeps the skill.
4. Otherwise **keep**, with the use-based reason (`use_above_rare_threshold`, `recent_use`, `gap_unknown`, `window_below_twice_gap`, `use_dates_missing`, `use_channel_unavailable`).

Merge similarity is deterministic and package-local: `0.4 × name Jaccard + 0.4 × description Jaccard + 0.2 × heading Jaccard` over frozen-stopword-filtered casefolded token sets; an empty feature contributes zero; compared with exact fractions against `7/10`. Pairs are listed in canonical order with no transitive clustering (A~B and B~C never implies A~C). Each private pair lists the matching tokens per feature, description tokens unique to each side, and negative-boundary tokens (clauses containing `not`, `never`, `without`, `except`, …) unique to each side, so a reviewer can see where scopes differ. No body merge exists.

## Incomplete, never empty-protected

These do not guess: the proposal gets `status: incomplete`, every skill is kept with `proposal_incomplete`, merge pairs are non-actionable, and the public `diagnostics` carry fixed counts:

`measurement_incomplete`, `snapshot_invalid`, `snapshot_not_closed`, `snapshot_binding_missing`, `inventory_drift`, `pins_missing`, `attestations_missing`, `references_not_provided`, `catalog_<blocking coverage code>`, `skill_body_unreadable`, `observation_calendar_missing`, `observed_activity_after_as_of`, `observed_activity_after_as_of_unknown`, `managed_root_unresolved`, `managed_tree_unavailable` (any link, hardlink, special file, foreign owner, group/world-writable mode or unstable listing under the managed root), `managed_tree_mismatch`.

Malformed or mismatched inputs raise a fixed-code `SchemaError` instead: wrong pin/attestation/binding schema, a binding for another harness/cutoff/window, report and private rows that do not describe the same inventory, an `as_of` that is not UTC, a non-boolean activity flag, or an observation day outside the window.

## Proposal schema

```json
{
  "schema_version": 1, "kind": "skill-inventory-proposal", "harness": "omp",
  "as_of_utc": "2026-10-01T00:00:00Z", "window_days": 90, "status": "complete",
  "snapshot_digest": "<hex>", "inventory_digest": "<hex>", "policy_digest": "<hex>",
  "measurement_scope": {"complete": true, "valid": true, "closed": true},
  "managed_root": "<absolute managed-skills path>", "managed_tree": {"root_mode": 448, "directories": [["name", 448]], "files": [["name/SKILL.md", "<sha256>", 384, 123]], "digest": "<hex>"},
  "source_root_digest": "<the managed_tree digest>",
  "policy_inputs": {"pins_digest": "<hex>", "attestations_digest": "<hex>", "references_digest": "<hex>"},
  "skills": [{"name": "…", "classification": "keep|archive_candidate|merge_candidate", "reasons": ["…"], "counter_evidence": ["…"], "tree_digest": "<hex>|null", "generated_only_attested": true, "never_user_authored_attested": true, "historical_lineage_attested": true, "description_only_reviewed": true, "coverage_still_needed": false, "periodic_or_incident_workflow": false, "eligible": true, "evidence": {"…normalized private row…": null}}],
  "merge_pairs": [{"a": "…", "b": "…", "score": 0.8857, "features": {"name": 1.0, "description": 0.714286, "headings": 1.0}, "matched": {"name": [], "description": [], "headings": []}, "differences": {"description_only_a": [], "description_only_b": [], "negative_boundaries_only_a": [], "negative_boundaries_only_b": []}, "a_protected": false, "b_protected": false, "actionable": true, "review": "human_required"}],
  "pin_names": [], "reference_names": [], "inventory_observations_by_utc_day": {"2026-09-30": 4},
  "approval_policy": {"max_batch": 10, "dwell_days": 7, "dwell_sessions": 20, "quarantine_days": 21, "cohort_deadline_days": 21},
  "proposal_digest": "<sha256 of every other field>"
}
```

- `eligible` is true exactly for archive candidates. An eligible item is a managed-root child directory named like the skill, with `tree_digest` equal to that child's digest inside the embedded whole-root `managed_tree`. The whole-root tree supports quiescence checks: `without_children(tree, {archived names})` is the expected root after a move.
- `validate_proposal` re-checks shapes, fixed code sets, tree/digest consistency, the policy digest and the proposal digest. A hand edit needs `seal_proposal`, which cannot hide an inconsistent tree or an eligible keep.
- A tree digest covers sorted relative paths, exact file and directory modes, sizes and every file's SHA-256. Scans are descriptor-relative, refuse links and special files, and fail on any change during the read.

## Public report keys

`schema_version`, `kind`, `status`, `scope`, `policy` (thresholds), `inputs` (`provided`/`missing` per input), `counts` (keep/archive/merge, pins and attestations matched, similar and actionable pairs), `reasons` and `counter_evidence` (code → count), `calendar` (days with observations, coverage fraction, largest gap including window edges), `opportunities` (how many entries reach 20 snapshots and 5 groups), `cohorts`, `diagnostics`, `limits` and `proposal_digest`.

## Fictional end-to-end workflow

The script below builds an invented home in a temporary directory, so it touches no real skill, log or configuration. Run it with `UTILITY_ROOT` set to this package directory:

```bash
UTILITY_ROOT=/path/to/skill-inventory \
  uv run --offline --no-project --script recommend_walkthrough.py
```

```python
# workflow: recommend-end-to-end
# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML==6.0.3"]
# ///
import json
import os
import secrets
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["UTILITY_ROOT"]) / "scripts"))

from inventory_io import (  # noqa: E402
    BINDING_VERSION,
    SNAPSHOT_POLICY,
    canonical_json,
    keyed_digest,
    write_private_json,
)
from inventory_policy import (  # noqa: E402
    recommend,
    scan_tree,
    subtree_state,
    validate_proposal,
)
from inventory_types import InstalledSkill, Inventory  # noqa: E402

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)
WINDOW_DAYS = 90


def stamp(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def ago(days: int) -> datetime:
    return AS_OF - timedelta(days=days)


def summarize(step: str, public: dict) -> None:
    counts = public["counts"]
    print(
        json.dumps(
            {
                "step": step,
                "status": public["status"],
                "diagnostics": public["diagnostics"],
                "keep": counts["keep"],
                "archive_candidates": counts["archive_candidates"],
                "reasons": public["reasons"],
            },
            sort_keys=True,
        )
    )


with tempfile.TemporaryDirectory() as scratch:
    base = Path(os.path.realpath(scratch))
    managed = base / "home" / ".omp" / "agent" / "managed-skills"
    skill_dir = managed / "invoice-tidy"
    skill_dir.mkdir(parents=True)
    os.chmod(managed, 0o700)
    os.chmod(skill_dir, 0o700)
    skill_file = skill_dir / "SKILL.md"
    description = "Reformat fictional invoices into a flat table."
    skill_file.write_text(
        f"---\nname: invoice-tidy\ndescription: {description}\n---\n\n"
        "# Steps\n\nReformat one invoice at a time.\n",
        encoding="utf-8",
    )
    os.chmod(skill_file, 0o600)
    private = base / "private"
    private.mkdir(mode=0o700)

    installed = ago(200)
    entry = InstalledSkill(
        name="invoice-tidy",
        description=description,
        path=skill_file,
        aliases=(),
        ownership="managed",
        installed_at=installed,
        headings=("Steps",),
    )
    # An empty reference-name set with coverage free of references_not_provided
    # stands for "approved instruction/agent definitions were supplied; none match".
    inventory = Inventory(
        entries=[entry],
        approved_roots=(managed,),
        coverage=Counter(),
        integrity="a" * 64,
    )

    scope = {
        "harness": "omp",
        "as_of_utc": stamp(AS_OF),
        "window_days": WINDOW_DAYS,
    }
    row = {
        "name": "invoice-tidy",
        "ownership": "managed",
        "installation_date": stamp(installed),
        "first_observed_inventory_date": stamp(ago(120)),
        "window_read_attempts": 0,
        "window_invocation_attempts": 0,
        "largest_observed_inter_use_gap_days": None,
        "inventory_present_subagent_snapshots": 24,
        "inventory_present_main_task_groups": 6,
        "inventory_presence_grouping_complete": True,
        "log_observed_dependency": False,
    }
    report = {
        "schema_version": 1,
        "status": "complete",
        "scope": scope,
        "snapshot": {"valid": True, "closed": True},
    }
    private_report = {
        "schema_version": 1,
        "status": "complete",
        "scope": scope,
        "skills": [row],
        "observed_activity_after_as_of": False,
        "inventory_observations_by_utc_day": {"2026-09-20": 12, "2026-09-28": 12},
    }

    key = secrets.token_hex(32)
    body = {
        "version": BINDING_VERSION,
        "policy": SNAPSHOT_POLICY,
        "harness": "omp",
        "as_of": stamp(AS_OF),
        "window_days": WINDOW_DAYS,
        "key": key,
        "roots": [],
        "files": [],
        "inventory": inventory.integrity,
    }
    seal = keyed_digest(bytes.fromhex(key), "seal", canonical_json(body))
    binding = private / "binding.json"
    write_private_json(binding, {**body, "seal": seal})

    def run(pins: Path | None, attestations: Path | None):
        return recommend(
            report,
            private_report,
            inventory,
            as_of=AS_OF,
            window_days=WINDOW_DAYS,
            binding_path=binding,
            pins_path=pins,
            attestations_path=attestations,
        )

    # 1. No pins and no attestations: incomplete, everything kept.
    public, _ = run(None, None)
    summarize("no policy inputs", public)

    # 2. The owner supplies an explicit empty pin list and an exact attestation.
    digest = subtree_state(scan_tree(managed), "invoice-tidy").digest
    pins = private / "pins.json"
    attestations = private / "attestations.json"
    write_private_json(pins, {"schema_version": 1, "pins": []})
    write_private_json(
        attestations,
        {
            "schema_version": 1,
            "items": [
                {
                    "name": "invoice-tidy",
                    "tree_digest": digest,
                    "harness_generated": True,
                    "never_user_authored": True,
                    "historical_identity_attested_since": stamp(ago(150)),
                    "description_only_reviewed": True,
                    "coverage_still_needed": False,
                    "periodic_or_incident_workflow": False,
                }
            ],
        },
    )
    public, proposal = run(pins, attestations)
    validate_proposal(proposal)
    write_private_json(private / "proposal.json", proposal)
    summarize("attested", public)
    leaked = "invoice-tidy" in json.dumps(public) or digest in json.dumps(public)
    print(json.dumps({"public_report_has_names_or_hashes": leaked}))
    print(
        json.dumps(
            {
                "proposal_file_mode": oct(
                    (private / "proposal.json").stat().st_mode & 0o777
                )
            }
        )
    )

    # 3. The skill changes after it was attested: the attestation no longer binds.
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8") + "\nEdited after attestation.\n",
        encoding="utf-8",
    )
    public, _ = run(pins, attestations)
    summarize("edited after attestation", public)
```

Expected shape of the output: step 1 is `incomplete` with `pins_missing` and `attestations_missing`; step 2 is `complete` with one archive candidate and no names or hashes in the public report; step 3 is `complete` with the skill kept for `attestation_digest_mismatch`. A real run also re-loads the inventory and compares its integrity before writing a proposal, and the owner reviews `description_only_influence_unmeasured` for every candidate before any approval.

## Hand-off to archive

Only `archive_candidate` items with `eligible: true` can enter an approval. The archive tool re-validates the saved proposal and a freshly rebuilt one, requires identical digests, re-scans the managed root and moves nothing unless the approval names the exact proposal digest and per-item tree digests. See `archive.md`.
