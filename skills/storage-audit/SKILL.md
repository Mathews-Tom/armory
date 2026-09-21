---
name: storage-audit
description: 'Read-only disk-storage audit for a repository or workspace root. Measures project footprints, identifies rebuildable dependencies, classifies local data and Git-protected paths, and reports project liveness without modifying files. Triggers on: "audit disk space", "storage audit", "find removable build artifacts", "which projects use the most space", "cleanup commands but do not run them", "analyze repository storage", "workspace disk cleanup". Use this skill when a developer needs evidence-backed storage recovery recommendations but must retain control of every deletion.'
metadata:
  version: 0.6.0
  category: development
  tags: [disk-usage, storage, cleanup, safety, git]
  difficulty: intermediate
  phase: review
---

# Storage Audit

Audits allocated disk space without changing the requested root, invoking a package manager, accessing the network, or executing a cleanup command. The bundled Bash script produces deterministic, machine-readable evidence; it renders a guarded cleanup script after the user explicitly selects current actionable candidates.

## Reference Files

|File|Contents|Load when|
|---|---|---|
|`references/classification-policy.md`|Artifact classes and required evidence|Before interpreting candidates|
|`references/safety-contract.md`|Non-negotiable read-only and script-rendering rules|Always|
|`references/report-schema.md`|JSON and Markdown output contract|When rendering or consuming output|

## Workflow

1. **Resolve scope.** Use the user path. A request covering all projects or subfolders is `workspace` scope even when the root contains a Git marker or package manifest; do not let `auto` collapse that request into one repository. Otherwise, `auto` treats a Git/manifest root as one repository. Workspace discovery inventories direct children plus nested Git repositories to depth five and accepts both `.git/` directories and `.git` files used by linked worktrees. Keep top-level multi-repository folders as `repository-container` rows with a `nested_repo_count`; list each nested repository separately. Report a discovered Git marker that Git cannot open as `invalid-repository`, not as an ordinary directory. Never widen the scan above the user-supplied root.
2. **Run strict audit.** Execute `bash scripts/storage-audit.sh audit --root "<path>" --scope <resolved-scope> --strict --format json`. A strict result captures candidate identity and evidence at scan time; `status:"unstable"` means only that aggregate allocation drifted during collection.
3. **Classify evidence.** Explain cleanup-eligible `rebuildable` entries separately from derived-review, local-data, and Git-protected entries. `A-###` means actionable candidate; `P-###` means protected or review-required candidate. Never infer that an old commit means the project checkout is disposable.
4. **Report liveness.** Surface project type, nested-repository count, Git cleanliness, last commit date, process count, and registered-worktree count. These are review signals, not deletion authorization.
5. **Give the next action.** After a strict audit with cleanup-eligible candidates, request a concise explicit selection: `render all` for every actionable candidate from that audit, or `render A-001, A-002` for a subset. Do not paste the complete candidate list or tell the user to rerun the audit because aggregate allocation drifted.
6. **Render script after selection.** For `render all`, run `plan --root <path> --scope <scope> --all`. For a subset, bind every requested ID to its canonical `path` from the preceding report: `--candidate A-001 --expected-path <canonical-path>`. `plan` collects a fresh strict candidate snapshot and rejects an ID whose current path differs from the selected path, then prints one self-contained selected-target script. Do not save or invoke it.

## Supported Operations

|Request|Script invocation|Result|
|---|---|---|
|Audit a repository|`audit --root <repo> --scope repo --strict --format markdown`|Repository footprint and classified artifacts|
|Audit a workspace|`audit --root <workspace> --scope workspace --strict --format json`|Project and nested-repository inventory|
|Fast inventory|`audit --root <path> --fast --format markdown`|Informational report; cleanup suppressed|
|Render cleanup script|`plan --root <path> --scope <scope> --all` or `plan --root <path> --candidate A-001 --expected-path <canonical-path>`|Preview-by-default Bash script; only the operator may invoke `--execute`|

## Error Handling

|Condition|Required response|
|---|---|
|Missing/unreadable path, filesystem root, symlink root, or control-character path|Stop and report the exact unsafe input; do not approximate|
|Strict scan changes while measuring|Report `UNSTABLE_SNAPSHOT`; explain that candidate evidence remains a strict point-in-time capture and may render a script for its current actionable candidates.|
|Candidate path changed since audit|Refuse to render a subset script; the selected ID must still resolve to the audited canonical path|
|Running process associated with a project|Report it and retain the project for review|
|User asks to delete a source checkout or old project|Refuse direct cleanup; provide an archive-review checklist only|

## Output

Return: root, snapshot status, allocated KiB, project type and nested-repository count, project liveness rows, classified artifact rows, and exact evidence for every recommendation. A strict report with cleanup-eligible candidates ends with concise `render all` and subset-selection instructions. State `No command executed.` whenever rendering a cleanup script.
