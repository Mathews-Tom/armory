# Lane Prompt Template

Render this verbatim per PR, substituting `{PR_NUMBER}`, `{REPO}`, `{WORKTREE_PATH}`, and `{OTHER_PR_NUMBERS}` (comma-separated list of the swarm's other PR numbers, used only for the isolation instruction below — never their content). Write the rendered result to `{WORKTREE_PATH}/.pr-swarm-prompt.md` and pass that file's contents as the `claude -p` argument (see `references/launch-mechanics.md`).

---

```text
Own PR #{PR_NUMBER} in {REPO} until it is merge-ready. Your working directory is
{WORKTREE_PATH} — a dedicated git worktree already checked out to this PR's branch.
Do not touch any other worktree or branch.

ISOLATION: PRs {OTHER_PR_NUMBERS} are being driven concurrently by separate,
independent sessions in this same repository. They are unrelated to your task.
Never reference, read, or discuss their diffs, feedback, or state. If you notice
your changes might overlap with theirs, stop and report it — do not attempt to
coordinate directly.

TERMINATION CONDITIONS (all must hold before you report done):
1. PR state == OPEN (check this every iteration, not just once — a PR can be
   closed externally at any point; if it happens, stop pushing and report
   plainly instead of continuing to work on a dead PR)
2. mergeStateStatus == CLEAN and mergeable == MERGEABLE
3. Latest CI: every non-skipped check passed, none pending
4. Zero unresolved review threads — including findings embedded in a review's
   raw body text with no inline comment backing it (a bot reviewer can post a
   full review whose body describes a finding via a blob permalink instead of
   an inline comment; scan every COMMENTED/CHANGES_REQUESTED review's body,
   not just reviewThreads)
5. No new feedback landed in the last ~10 minutes (quiet window)
6. Working tree clean; local HEAD matches the pushed remote head
7. The repository's own test/typecheck/lint gate passes on the merged tree

ORIENTATION:
  gh auth status
  gh pr view {PR_NUMBER} --repo {REPO} \
    --json state,mergeable,mergeStateStatus,headRefOid,headRefName,baseRefName
  gh pr checks {PR_NUMBER} --repo {REPO} | grep -v skipping

A freshly-launched lane commonly inherits a PR with CI already red or
feedback already unresolved from before this run started — that is normal
starting state, not a reason to wait. Read the checks output and the PR's
existing reviews/threads now. If anything above is already actionable (a
check already reporting FAILURE, an unresolved review thread, or a
body-only review finding), fix it as your first action. Being unable to
force a fresh CI rerun (`gh run rerun` requires repo admin rights you do
not have) is never a reason to stall — pushing your fix triggers a
genuinely fresh run on its own.

MERGE CONFLICTS: GitHub's mergeStateStatus can be stale. Verify with
`git merge-tree --write-tree <base> <head>` before assuming a real conflict
exists. If clean, `git merge <base> -m "..."` and push rather than replaying
commits with rebase (fixup commits tailored to an older base can conflict
individually even when the net merge doesn't).

WATCH LOOP: after each push, CI starts a new run. Poll per-job status via
`gh pr checks {PR_NUMBER}`, not just the run-level aggregate — the moment
any single non-skipped check reports FAILURE, or new review feedback lands,
stop waiting on the rest of that run's still-pending checks and act on it
immediately. You never need every check in a run to finish, or the full
~10-minute quiet window to elapse, before reacting to something already
actionable. Only treat the ~10-minute wait as genuine idle time once every
currently-visible check is passing or still pending with zero failures and
there is no unaddressed feedback. Reset the quiet-window timer on any new
feedback or push. Run one extra quiet window before declaring done, as
insurance against reviewer lag.

Report your final status against every termination condition explicitly —
don't just say "done." If you cannot reach all seven conditions, report
exactly which ones are unmet and why, rather than declaring partial success.
```
