# Safety contract

The audit command and invoking agent are read-only with respect to the requested root.

## Prohibited execution

Never invoke `rm`, `rmdir`, `mv`, `cp`, `touch`, `mkdir`, a package manager, `git fetch`, `git gc`, a network client, or a cleanup tool. The only `rm -rf --` text may appear inside a user-copyable script printed by `plan`; the agent never saves or invokes that script.

## Script rendering

Render a script only when all conditions hold:

1. The user explicitly selected all current actionable candidates or one or more current actionable `A-###` candidates. For a subset, every selected ID is bound to its canonical path from the preceding report and the fresh scan must match it.
2. The `plan` command completed a strict candidate scan. Aggregate root allocation may drift while the scan collects evidence.
3. Every path is canonical, absolute, inside the requested root, and contains no control characters.
4. Every candidate remains exactly classified as `rebuildable`.
5. Every path is Git-ignored and has its required manifest/lockfile.
6. No process is associated with any owning project.

Render one self-contained Bash script to standard output. It embeds only the selected absolute paths in a quoted array, previews when invoked without arguments, and removes paths only when the operator invokes it with exactly `--execute`. Before its first removal, it must canonicalize the audit root and every target, verify that each canonical target exists as a directory below that canonical root, then delete only the verified canonical paths. Use one quoted-array deletion loop; never use globs, parent directories, `find -delete`, `xargs`, `sudo`, or a path supplied at generated-script invocation time.

## Archive review

For a project checkout, report only: Git clean/dirty state, last commit, configured remote if explicitly requested, registered worktrees, local-data paths, and process evidence. Require human confirmation that a restorable remote or backup exists before any human considers deletion.
