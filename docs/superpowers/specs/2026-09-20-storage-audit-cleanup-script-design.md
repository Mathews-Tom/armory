# Storage Audit Cleanup-Script Design

## Status

Approved for specification on 2026-09-20. Implementation remains gated on review of this written specification.

## Problem

`storage-audit.sh plan` currently emits independent `du -sh` and `rm -rf --` lines after a stable strict scan and explicit Tier A candidate selection. An operator who selects many candidates must manually manage a long list of commands. The result is reviewable but not reusable as a single, guarded cleanup action.

## Goal

After explicit selection of one or more current `A-###` candidates, produce a self-contained Bash script that the operator can save, review, and run. The script must preview by default and remove only its embedded selected artifacts when explicitly invoked with `--execute`.

## Non-Goals

- Change the `audit` operation's read-only contract.
- Write, save, chmod, or execute a cleanup script from the skill or bundled script.
- Remove source checkouts, unknown paths, local data, derived indexes, or Git worktrees.
- Resolve candidate IDs at script execution time.
- Delete entries when the strict snapshot is unstable or a selected candidate is no longer eligible.

## Chosen Approach

Add script rendering to the existing `plan` operation. `plan` continues to perform a fresh strict scan and requires explicit `--candidate A-###` arguments. Once it verifies every selected candidate, it writes the following script text to standard output and performs no cleanup action itself.

The generated script embeds canonical absolute target paths in a Bash array. Candidate IDs are intentionally not resolved later: IDs are deterministically size-sorted during each scan but can change as storage changes. Embedding the paths verified during the plan scan prevents a later scan from remapping an approved ID to a different path.

The script runs in preview mode unless its first argument is exactly `--execute`. Preview prints the embedded targets and the invocation required to execute. Execution first validates every target, then prints allocated sizes with `du -sh --`, then removes each target in a single quoted-array loop.

## Generated-Script Contract

```bash
#!/usr/bin/env bash
set -euo pipefail

readonly AUDIT_ROOT='/canonical/audit/root'
TARGETS=(
  '/canonical/audit/root/project/.venv'
  '/canonical/audit/root/project/.mypy_cache'
)

case "$#" in
  0)
    printf 'Preview only. Review targets, then run: %s --execute\n' "$0"
    printf '%s\n' "${TARGETS[@]}"
    exit 0
    ;;
  1) [ "$1" = '--execute' ] || { printf 'Unknown argument: %s\n' "$1" >&2; exit 64; } ;;
  *) printf 'Usage: %s [--execute]\n' "$0" >&2; exit 64 ;;
esac

for target in "${TARGETS[@]}"; do
  [ -d "$target" ] || { printf 'Missing directory: %s\n' "$target" >&2; exit 1; }
  case "$target" in
    "$AUDIT_ROOT"/*) ;;
    *) printf 'Refusing path outside audit root: %s\n' "$target" >&2; exit 1 ;;
  esac
done

printf 'Selected targets:\n'
du -sh -- "${TARGETS[@]}"
for target in "${TARGETS[@]}"; do
  printf 'Removing %s\n' "$target"
  rm -rf -- "$target"
done
```

A manually modified generated script is outside the plan's guarantee. The operator must review it before invoking `--execute`.

## Safety Invariants

1. `audit` never emits a cleanup script or executes cleanup.
2. `plan` scans again with `STRICT=true`; unstable scans fail before rendering.
3. Every selected ID must still be an `A-###` rebuildable candidate, Git-ignored, manifest-backed, inside the canonical audit root, and owned by a project with no associated process.
4. No target is removed until the generated script receives `--execute`.
5. The generated script verifies all targets are existing directories under `AUDIT_ROOT` before its first removal. A missing or out-of-root target aborts the whole run without partial cleanup.
6. The generated script uses `rm -rf -- "$target"`; no glob, parent directory, shell variable expansion from user input, `find -delete`, `xargs`, `sudo`, or multi-path remove command is permitted.
7. Source checkouts, local data, derived-review assets, and Git-protected worktrees remain ineligible.

## Interfaces

`storage-audit.sh plan --root PATH --candidate A-001 [--candidate A-002 ...]` prints the executable script to standard output. The operator is responsible for saving it outside the audited root or at a reviewed destination. The script does not accept candidate IDs or paths as command-line input; its only accepted action argument is `--execute`.

The skill documentation changes from “prints one cleanup command per selected candidate” to “renders a selected-target script after explicit candidate selection.” The safety contract and report schema are revised to describe rendered script output rather than individual command lines.

## Verification

The shell test must prove all of the following:

- `plan` emits valid Bash and does not invoke a shadowed `rm` while rendering.
- The emitted script previews when invoked without `--execute` and does not invoke a shadowed `rm`.
- `--execute` removes exactly the selected rebuildable fixture directories through the loop.
- A missing selected directory or an out-of-root modified target aborts before any target is removed.
- Selecting a protected `P-###` entry remains rejected.
- Existing audit read-only and local-data sentinel checks remain unchanged.

The Armory package change updates `metadata.version` with a minor bump, adds an eval proving explicit candidate selection plus preview/`--execute` behavior, regenerates adapters and `manifest.yaml`, and passes the repository’s skill validation gate.

## Consequences

The output is safer to reuse across large selections but remains intentionally operator-controlled. The selected paths are a snapshot: an operator must regenerate the plan if the review window is no longer current. This feature does not make source checkouts or protected storage cleanup-eligible.
