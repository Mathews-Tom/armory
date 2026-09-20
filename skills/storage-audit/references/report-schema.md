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

`status` is `stable` only when the strict pre-scan and post-scan root allocation match. `fast` means the user requested `--fast`; `unstable` means the root changed while scanning. Neither permits cleanup-command output.

`process_count` comes from `lsof +D` without exposing command lines. `-1` means `lsof` is unavailable; Tier A eligibility is then suppressed rather than guessed.

Entry IDs are deterministic within a stable scan: eligible entries are sorted by allocated KiB descending, then canonical path; protected entries use the `P-###` prefix and follow the same ordering. Project rows are canonical-path ordered.

Markdown output contains the same facts in a review table. Allocated KiB describes `du -skx` accounting, not guaranteed physical recovery on copy-on-write filesystems, in snapshots, or for open-but-deleted files.
