# Stack Model

A stack is an ordered set of branches where each branch depends on the branch before it.

```text
main
  -> feat/parser-core
      -> feat/parser-cache
          -> feat/parser-cli
```

## Sources Of Truth

Use these sources in order:

1. User-supplied explicit branch order.
2. Open PR metadata from the provider: `headRefName` and `baseRefName`.
3. `.stack-prs.yaml` when it exists.
4. Git ancestry only when it produces a single unambiguous parent chain.

Provider PR bases beat ancestry because review diff correctness depends on the hosted base ref, not only the local merge base.

## Inspection Commands

```bash
git rev-parse --show-toplevel
git status --porcelain
git branch --show-current
git for-each-ref --format='%(refname:short)' refs/heads
git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'
gh pr list --state open --json number,title,headRefName,baseRefName,state,url
```

For candidate parent checks:

```bash
git merge-base <branch> <candidate-parent>
git log --oneline <candidate-parent>..<branch>
```

## Native Stack Detection

Run for every open stack PR during Inspect, before any merge planning,
whether or not `github-native` mode was requested. A pull request the
provider already registers as a GitHub-native stack member rejects a plain
synchronous merge mutation outright; detection must happen here, not as a
merge-time failure.

```bash
gh api repos/{owner}/{repo}/pulls/<number> --jq '.stack'
```

A plain `GET`; it mutates nothing and is safe to run for every open PR.
Returns `null` when the PR is not part of a native stack, or an object with
`number` (stack number), `size`, `position`, and `base.ref` when it is.

Do not use `gh stack view` for detection: it reads only the branch currently
checked out and takes no PR argument, so it fails with `current branch
"<branch>" is not part of a stack` when run from any other branch, including
the stack's own base branch.

If the probe cannot run, treat a later `mergePullRequest`/`merge-async`
rejection ("must be merged using the asynchronous merge REST API") as
authoritative detection and switch to `references/github-native.md` § Merge
rather than reporting failure.

## Required Model

Represent each stack entry with:

| Field | Meaning |
| --- | --- |
| `order` | 1-based position above the base branch |
| `branch` | Local head branch |
| `parent` | Base branch for review and rebase |
| `pr_number` | Provider PR number when one exists |
| `pr_state` | Provider state |
| `url` | Provider PR URL |
| `checks` | Latest known validation or provider check state |
| `native` | `true`/`false`/`unknown` from the Native Stack Detection probe |

## Stop Conditions

- No Git repository is detected.
- The stack has fewer than two dependent branches and the user asked for a normal PR.
- A requested branch does not exist locally.
- A branch appears more than once.
- Two candidate parents are equally plausible.
- Provider PR metadata contradicts explicit branch order.
- `.stack-prs.yaml` exists but fails schema validation.

When parent order is ambiguous, stop and request explicit branch order. Do not invent semantic relationships from branch names.
