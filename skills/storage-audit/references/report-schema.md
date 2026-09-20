# Report schema

`audit --format json` returns one deterministic object:

```json
{
  "root": "/absolute/path",
  "scope": "workspace",
  "strict": true,
  "status": "stable",
  "allocated_kib": 1234,
  "projects": [
    {
      "path": "/absolute/path/project",
      "project_type": "repository",
      "nested_repo_count": 0,
      "allocated_kib": 900,
      "git_status": "clean",
      "last_commit": "2026-09-20",
      "process_count": 0,
      "worktree_count": 1
    }
  ],
  "entries": [
    {
      "id": "A-001",
      "class": "rebuildable",
      "path": "/absolute/path/project/target",
      "allocated_kib": 800,
      "reason": "ignored Cargo build output",
      "rebuild": "cargo build",
      "cleanup_eligible": true
    }
  ]
}
```

`status` is `stable` only when the strict pre-scan and post-scan root allocation match. `fast` means the user requested `--fast`; `unstable` means the root changed while scanning. Neither permits cleanup-script output.
`project_type` is `repository` for a valid Git checkout, `repository-container` for a direct workspace folder containing one or more discovered Git markers, `invalid-repository` when a `.git` marker exists but Git cannot open it, and `directory` otherwise. `nested_repo_count` counts discovered repository markers below that row. Discovery recognizes both `.git/` directories and `.git` files used by linked worktrees.


`process_count` comes from `lsof +D` without exposing command lines. `-1` means `lsof` is unavailable; cleanup eligibility is then suppressed rather than guessed.

Entry IDs are deterministic within a stable scan: cleanup-eligible entries use the `A-###` prefix for **actionable**, sorted by allocated KiB descending and then canonical path. Protected or review-required entries use the `P-###` prefix and follow the same ordering. Project rows are canonical-path ordered.

Markdown output contains project-liveness and classified-entry review tables. A stable report with at least one cleanup-eligible entry ends with a copy-ready request containing every actual actionable ID from that report. The user removes any IDs they do not approve before replying; the report never emits an ID placeholder. Allocated KiB describes `du -skx` accounting, not guaranteed physical recovery on copy-on-write filesystems, in snapshots, or for open-but-deleted files.

`plan` is not an audit-report format. It requires explicit actionable `A-###` selection from a fresh stable strict scan and writes a self-contained Bash script to standard output. The rendered script previews its embedded canonical targets by default, rejects unknown or extra arguments, and removes only those targets when the operator invokes it with exactly `--execute`. Rendering never writes or executes that script.
