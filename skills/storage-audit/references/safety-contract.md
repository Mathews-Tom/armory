# Safety contract

The script and the invoking agent are read-only with respect to the requested root.

## Prohibited execution

Never invoke `rm`, `rmdir`, `mv`, `cp`, `touch`, `mkdir`, a package manager, `git fetch`, `git gc`, a network client, or a cleanup tool. The only `rm -rf --` text may appear in stdout as a user-copyable command produced by `plan`.

## Command rendering

Render a command only when all conditions hold:

1. The user explicitly selected a current `A-###` candidate.
2. A strict scan reports `stable`.
3. The path is canonical, absolute, inside the requested root, and contains no control characters.
4. The candidate remains exactly classified as `rebuildable`.
5. The path is Git-ignored and has its required manifest/lockfile.
6. No process is associated with its project.

Render one path per block. Quote the absolute path. Never use globs, shell variables, parent directories, `find -delete`, `xargs`, `sudo`, or a multi-path deletion command.

## Archive review

For a project checkout, report only: Git clean/dirty state, last commit, configured remote if explicitly requested, registered worktrees, local-data paths, and process evidence. Require human confirmation that a restorable remote or backup exists before any human considers deletion.
