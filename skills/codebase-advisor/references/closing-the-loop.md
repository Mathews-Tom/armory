# Closing the Loop

The advisor owns plan quality and review. It does not merge code or edit source files in the user's working tree.

This reference covers `execute`, `reconcile`, and `--issues`.

## `execute <plan>`

Use only when the host supports a separate executor in an isolated git worktree. If that capability is unavailable, stop and hand the plan to the operator for manual execution.

### Preconditions

Check before dispatch:

1. The repo is a git repository.
2. The plan file exists.
3. Dependencies are marked DONE in `plans/README.md`.
4. The plan's drift check is clean. If in-scope files changed, reconcile first.
5. The plan is self-contained. If it depends on session context, fix the plan before dispatch.

### Dispatch Prompt

Inline the full plan file. Do not assume uncommitted `plans/` files exist in the worktree.

Use this executor preamble:

```text
You are the executor for the implementation plan below. Follow it step by step. Run every verification command and confirm the expected result before moving on. Touch only files listed as in scope. If any STOP condition occurs, stop immediately and report. Do not improvise around obstacles. Commit your work in the worktree following the plan's git workflow section.

Override: skip the plan's instruction to update `plans/README.md`; your reviewer maintains the index.

Before reporting, audit every claim against an actual tool result from this session. If a verification failed or was skipped, say so plainly.

Report exactly:
STATUS: COMPLETE | STOPPED
STEPS: per step — done/skipped + verification result
STOPPED BECAUSE: only if STOPPED
FILES CHANGED: list
NOTES: deviations, surprises, judgment calls
```

### Review

Treat executor output as untrusted until verified.

1. Re-run every done criterion in the worktree.
2. Check scope: diff stat must include only in-scope files, except documented plan-index handling owned by the reviewer.
3. Read the full diff.
4. Confirm the change solves the plan's stated problem, not just the tests.
5. Audit tests for meaningful assertions and named edge cases.
6. Compare implementation against repo conventions cited in the plan.

### Verdicts

| Verdict | When | Action |
|---|---|---|
| APPROVE | Criteria pass, scope clean, quality holds | Mark DONE in index; report diff summary, worktree path, branch, and notes. Do not merge. |
| REVISE | Fixable gaps | Send specific feedback to the same executor. Max two revision rounds. |
| BLOCK | STOP condition, scope violation, or exhausted revisions | Mark BLOCKED with reason; refine or rewrite the plan using what was learned. |

Documented deviations are judged on merit. Silent deviations fail review.

## `reconcile`

Use when plan files already exist.

1. Read `plans/README.md` and every referenced plan.
2. For DONE plans, spot-check cheap done criteria against current HEAD and note verification in the index when useful.
3. For BLOCKED plans, read the reason, investigate the obstacle, then either refresh the plan, create a replacement with a new number, or mark REJECTED.
4. For stale IN PROGRESS plans, flag that an executor likely died and inspect the worktree if available.
5. For TODO plans, run drift checks. If drifted, re-verify the finding still exists, refresh excerpts and planned-at SHA, or mark REJECTED if fixed independently.
6. Keep numbering monotonic. Do not reuse numbers.

Finish with a short report:

- Verified done.
- Refreshed.
- Rejected.
- Blocked.
- Executable now.

## `--issues`

Publish plans as GitHub issues only when the invocation explicitly includes `--issues`.

### Preflight

1. `gh auth status` succeeds.
2. The repo has a GitHub remote.
3. `gh repo view --json visibility` succeeds.
4. If public and a plan contains security, credential, or sensitive operational details, warn that issues are public and get explicit confirmation before publishing.

### Publishing

1. Show titles about to be created.
2. Create each issue with the plan body.
3. Add labels only when they exist or can be created without blocking the flow: `codebase-advisor` plus category.
4. Record issue URL in the plan Status block and in `plans/README.md`.

If preflight fails, keep local plan files as source of truth and report why issue publishing was skipped.

## Source-Control Boundaries

- The advisor may update plan files and index files.
- The advisor must not commit, merge, push, or edit source code.
- Executors work only in isolated worktrees when dispatched by `execute`.
- Merging executor work is always the operator's decision.