---
name: storage-audit
description: 'Read-only disk-storage audit for a repository or workspace root. Measures project footprints, identifies rebuildable dependencies, classifies local data and Git-protected paths, and reports project liveness without modifying files. Triggers on: "audit disk space", "storage audit", "find removable build artifacts", "which projects use the most space", "cleanup commands but do not run them", "analyze repository storage", "workspace disk cleanup". Use this skill when a developer needs evidence-backed storage recovery recommendations but must retain control of every deletion.'
metadata:
  version: 0.4.0
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

1. **Resolve scope.** Use the user path. A request covering all projects or subfolders is `workspace` scope even when the root contains a Git marker or package manifest; do not let `auto` collapse that request into one repository. Otherwise, `auto` treats a Git/manifest root as one repository. Workspace discovery inventories direct children plus nested Git repositories to depth five and accepts both `.git/` directories and `.git` files used by linked worktrees. Keep top-level multi-repository folders as `repository-container` rows with a `nested_repo_count`; list each nested repository separately. Report a discovered Git marker that Git cannot open as `invalid-repository`, not as an ordinary directory. Never widen the scan above the user-supplied root.
2. **Run strict audit.** Execute `bash scripts/storage-audit.sh audit --root "<path>" --scope <resolved-scope> --strict --format json`. A strict result with `status:"unstable"` is informational only: do not discuss it as cleanup-ready.
3. **Classify evidence.** Explain cleanup-eligible `rebuildable` entries separately from derived-review, local-data, and Git-protected entries. `A-###` means actionable candidate; `P-###` means protected or review-required candidate. Never infer that an old commit means the project checkout is disposable.
4. **Report liveness.** Surface project type, nested-repository count, Git cleanliness, last commit date, process count, and registered-worktree count. These are review signals, not deletion authorization.
5. **Give the next action.** After every stable audit with cleanup-eligible candidates, end with a copy-ready prompt containing every actual actionable ID from that report: `Use the storage-audit skill to run a fresh strict scan of <root> and render—but do not save or execute—a cleanup script for cleanup-eligible candidates A-001, A-002.` Tell the user to remove any IDs they do not approve before replying. Never emit a placeholder such as `<selected IDs>`.
6. **Render script only on follow-up.** Require explicit actionable candidate IDs from a fresh strict scan. Run `plan` to print a self-contained selected-target script. Do not save or invoke the printed script.

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
|Candidate is protected, absent, stale, or not cleanup-eligible|Refuse to render a cleanup script|
|Running process associated with a project|Report it and retain the project for review|
|User asks to delete a source checkout or old project|Refuse direct cleanup; provide an archive-review checklist only|

## Output

Return: root, snapshot status, allocated KiB, project type and nested-repository count, project liveness rows, classified artifact rows, and exact evidence for every recommendation. A stable report with cleanup-eligible candidates must end with the copy-ready cleanup-script request from step 5 containing the report's actual actionable IDs. State `No command executed.` whenever rendering a cleanup script.
