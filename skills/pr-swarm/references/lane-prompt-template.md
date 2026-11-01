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
2. Current mergeability and provider-required protections/reviews are satisfied;
   a display state alone is not proof, and queue-ready need not display CLEAN
3. Required, repository-mandated and unclassified applicable CI passed in the
   current required context; report explicitly advisory jobs separately
4. Substantive inline and body-only findings are fixed or have an authorized
   disposition; optional feedback has a reasoned disposition, not a fix commit.
   Preserve provider-required review/thread rules
5. Final current-state read shows no new blocker; no fixed quiet window
6. Working tree clean; local HEAD matches the pushed remote head
7. Observed acceptance and required local/integration-candidate checks passed;
   an open PR is not merged merely to validate it

ORIENTATION:
  gh auth status
  gh pr view {PR_NUMBER} --repo {REPO} \
    --json state,mergeable,mergeStateStatus,headRefOid,headRefName,baseRefName
  gh pr checks {PR_NUMBER} --repo {REPO}

A freshly-launched lane commonly inherits a PR with CI already red or
feedback already unresolved from before this run started — that is normal
starting state, not a reason to wait. Read the checks output and the PR's
existing reviews/threads now. If anything above is already actionable (a
check already reporting FAILURE, an unresolved review thread, or a
body-only review finding), act on it first — review findings go through
TRIAGE below, so only Important ones get a fix. Being unable to
force a fresh CI rerun (`gh run rerun` requires repo admin rights you do
not have) is never a reason to stall — pushing your fix triggers a
genuinely fresh run on its own.

MERGE CONFLICTS: GitHub's mergeStateStatus can be stale. Verify with
`git merge-tree --write-tree <base> <head>` before assuming a real conflict
exists. If clean, `git merge <base> -m "..."` and push rather than replaying
commits with rebase (fixup commits tailored to an older base can conflict
individually even when the net merge doesn't).

TRIAGE: every fix push triggers another bot review round, so fixing every
comment never converges. Tag each finding (inline thread or review body)
before touching code, then act by tag:
- Important (bug, regression, security, broken contract, failing required or
  repository-mandated check): fix the substantive failure.
- Nit (style, naming, "consider", docstring polish, speculative hardening):
  reply with a one-line reason and resolve the thread; no commit.
- Pre-existing (code this PR did not change): reply "pre-existing, out of
  scope for this PR" and resolve; no commit.
- Repeat of a finding already answered: reply pointing to the earlier
  answer and resolve; no commit.
When fixing, name the bug class and fix every instance in this PR's diff in
the same push. Replies carry no @-mentions. A body-only finding has no thread
to resolve: answer it with one `gh pr comment` citing the review URL plus
the fixing commit SHA (Important) or the one-line reason (declined).

ROUND CAP: a round is one push answering review feedback plus the bot
re-review it triggers; merge-only and CI-flake pushes do not count. Round 1
may re-verify the whole PR; from round 2 on, re-verify changed code and
affected interactions, broadening only when a contract or base invalidates evidence.
If new Important findings still arrive after round 3,
stop pushing and report the recurring findings, their bug class, and
whether the approach needs rethinking — a fourth round is the user's call.

WATCH LOOP: inspect individual jobs so a failed blocking check is actionable
while other jobs run. Use ship-workflow's sourced required/advisory policy;
never classify a job as advisory merely because it is slow, red or a bot.
Batch substantive fixes before a coherent push. Re-run checks covering
changed inputs or integration context, not passing unrelated checks.
Once acceptance, required checks and reviews pass, read current PR state,
head/base and feedback again and report readiness. No quiet timer or extra
insurance wait applies. Pending or unreadable required evidence still
blocks; pending advisory feedback does not. Report a later substantive
finding when received without requiring every advisory bot to become silent.

Report your final status against every termination condition explicitly —
don't just say "done" — plus the number of review rounds used. If you cannot
reach all seven conditions, report exactly which ones are unmet and why,
rather than declaring partial success.
```
