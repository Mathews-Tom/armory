---
name: storage-audit
description: 'Read-only disk-storage audit for a repository or workspace root. Measures project footprints, identifies rebuildable dependencies, classifies local data and Git-protected paths, and reports project liveness without modifying files. Triggers on: "audit disk space", "storage audit", "find removable build artifacts", "which projects use the most space", "cleanup commands but do not run them", "analyze repository storage", "workspace disk cleanup". Use this skill when a developer needs evidence-backed storage recovery recommendations but must retain control of every deletion.'
metadata:
  version: 0.2.0
  category: development
  tags: [disk-usage, storage, cleanup, safety, git]
  difficulty: intermediate
  phase: review
---

# Storage Audit

Audits allocated disk space without changing the requested root, invoking a package manager, accessing the network, or executing a cleanup command. The bundled Bash script produces deterministic, machine-readable evidence; this skill interprets it and renders a guarded cleanup script only when the user explicitly selects eligible candidates.

## Reference Files

|File|Contents|Load when|
|---|---|---|
|`references/classification-policy.md`|Artifact classes and required evidence|Before interpreting candidates|
|`references/safety-contract.md`|Non-negotiable read-only and script-rendering rules|Always|
|`references/report-schema.md`|JSON and Markdown output contract|When rendering or consuming output|

## Workflow

1. **Resolve scope.** Use the user path. `auto` treats a Git/manifest root as one repository; otherwise it inventories direct children plus nested Git repositories to depth five. Never widen the scan above the user-supplied root.
2. **Run strict audit.** Execute `bash scripts/storage-audit.sh audit --root "<path>" --scope auto --strict --format json`. A strict result with `status:"unstable"` is informational only: do not discuss it as cleanup-ready.
3. **Classify evidence.** Explain Tier A rebuildable entries separately from derived-review, local-data, and Git-protected entries. Never infer that an old commit means the project checkout is disposable.
4. **Report liveness.** Surface Git cleanliness, last commit date, process count, and registered-worktree count. These are review signals, not deletion authorization.
5. **Render script only on follow-up.** Require explicit Tier A IDs from a fresh strict scan. Run `plan` to print a self-contained selected-target script. Do not save or invoke the printed script.

## Supported Operations

|Request|Script invocation|Result|
|---|---|---|
|Audit a repository|`audit --root <repo> --scope repo --strict --format markdown`|Repository footprint and classified artifacts|
|Audit a workspace|`audit --root <workspace> --scope workspace --strict --format json`|Project and nested-repository inventory|
|Fast inventory|`audit --root <path> --fast --format markdown`|Informational report; cleanup suppressed|
|Render cleanup script|`plan --root <path> --candidate A-001`|Preview-by-default Bash script; only the operator may invoke `--execute`|

## Error Handling

|Condition|Required response|
|---|---|
|Missing/unreadable path, filesystem root, symlink root, or control-character path|Stop and report the exact unsafe input; do not approximate|
|Strict scan changes while measuring|Report `UNSTABLE_SNAPSHOT`; ask for a later quiescent scan before script planning|
|Candidate is protected, absent, stale, or not Tier A|Refuse to render a cleanup script|
|Running process associated with a project|Report it and retain the project for review|
|User asks to delete a source checkout or old project|Refuse direct cleanup; provide an archive-review checklist only|

## Output

Return: root, snapshot status, allocated KiB, project liveness rows, classified artifact rows, and exact evidence for every recommendation. State `No command executed.` whenever rendering a cleanup script.
