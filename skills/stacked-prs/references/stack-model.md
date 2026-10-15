# Stack Model

A stack is a directed acyclic parent graph of branches rooted at one explicit trunk. Each node has exactly one parent: the trunk or another node. Several children may share one parent (siblings), a linear chain is the special case where every parent has one child, and a parent may already be landed while its children are still open.

```text
main
  -> feat/parser-core
      -> feat/parser-cache
          -> feat/parser-cli
      -> feat/parser-docs
```

`feat/parser-cache` and `feat/parser-docs` are siblings: both depend on `feat/parser-core` and on nothing in each other.

## Sources Of Truth

Use these sources in order:

1. User-supplied explicit order and parents, or an explicit stack decision packet passed with `--stack-plan` (below).
2. Open PR metadata from the provider: head repository, `headRefName`, head OID and `baseRefName`.
3. `.stack-prs.yaml` when it exists, as operator-authored evidence (`references/metadata-format.md`).
4. Git ancestry only when it yields exactly one plausible parent for a branch.

Provider PR bases beat ancestry because review diff correctness depends on the hosted base ref, not only the local merge base. Any contradiction between sources stops mutation; it is never resolved by picking one.

## Inspection Commands

```bash
git rev-parse --show-toplevel
git status --porcelain
git branch --show-current
git for-each-ref --format='%(refname:short)' refs/heads
git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'
gh pr list --state open --json number,title,headRefName,headRefOid,baseRefName,state,url
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
`number` (stack number), `size`, `position`, and `base.ref` when it is. For a
native PR, read the complete ordered membership with `gh api
repos/{owner}/{repo}/stacks/<stack-number>` (`references/github-native.md` §
Detecting an already-native stack).

Do not use `gh stack view` for detection: it reads only the branch currently
checked out and takes no PR argument, so it fails with `current branch
"<branch>" is not part of a stack` when run from any other branch, including
the stack's own base branch.

If the probe cannot run, membership is unknown: record `native: unknown` and
do not author a landing packet until it is known. The delegated run classifies
membership itself and stops a selection whose stack number, position, size or
base it cannot read.

A native member is never handled by the manual graph path described in this reference set: no ordinary merge, promotion push or retarget is dispatched for it, and a manual stack is never converted to a native one (or back) automatically. Native members are landed only through the guarded prefix request described in `references/github-native.md` § Landing policy.

## Required Model

Represent each stack node with:

| Field | Meaning |
| --- | --- |
| `order` | Stable 1-based topological position: every node comes after its parent; siblings are ordered by PR number. A position, not a promise that the graph is linear |
| `branch` | Head branch (with its head repository when it lives in a fork) |
| `parent` | The parent node, or the trunk. Distinct from `order`: two siblings have different `order` values and the same `parent` |
| `base` | The provider PR base: the parent's head branch, or the trunk once the parent landed and the child was retargeted |
| `head_sha` | Exact observed head OID |
| `pr_number` | Provider PR number when one exists |
| `pr_state` | Provider state: open, merged, or closed unmerged |
| `url` | Provider PR URL |
| `checks` | Latest known validation or provider check state |
| `native` | `true`/`false`/`unknown` from the Native Stack Detection probe |

## Explicit Stack Decision Packet

The executable owner of manual and native graph continuation is the installed `ship-workflow` skill: `scripts/ship.py --stack-plan PATH [--until pr|merged|clean] [--dry-run] [--resume [RUN_ID]] [--wait-timeout SECONDS] [--repo [HOST/]OWNER/REPO]`, run from the absolute base directory the client reports when that registered skill loads, never from a source checkout or a path relative to this package. A missing `ship-workflow` skill is `BLOCKED` naming it. A saved graph run also resumes with `--resume RUN_ID` alone. `--until pr` only observes, `merged` lands without deleting branches, and `clean` (the default for a new run) also cleans up. The packet is a bounded JSON file read only from the path given with `--stack-plan`. It is never discovered or auto-loaded from the repository and is not a repository policy language. `--stack-plan` cannot be combined with the single-PR target, publication and planning flags (`--pr`, `--branch`, `--plan`, `--policy`, `--gates`, `--head-repo`, `--title`, `--body-file`, `--inventory`, `--draft`).

```json
{
  "schema_version": 1,
  "repository": "owner/repo",
  "trunk": "main",
  "nodes": [
    {
      "pr": 11,
      "parent": null,
      "select": true,
      "head": {"repo": "owner/repo", "ref": "feat/parser-core", "sha": "<40-hex head oid>"},
      "base": "main",
      "decision": {
        "sources": ["<where the gate decision comes from>"],
        "expected_checks": ["test"],
        "merge_method": "squash",
        "post_merge_commands": []
      },
      "provenance": {"disposition": "preserve", "sources": ["<trailers, PR body or .stack-prs.yaml inspected>"]}
    },
    {
      "pr": 12,
      "parent": 11,
      "select": true,
      "head": {"repo": "owner/repo", "ref": "feat/parser-cache", "sha": "<40-hex head oid>"},
      "base": "feat/parser-core",
      "fork": "<40-hex old parent head the child's own commits sit on>",
      "decision": {
        "sources": ["<source>"],
        "expected_checks": ["test"],
        "merge_method": "squash",
        "post_merge_commands": []
      },
      "provenance": {"disposition": "preserve", "sources": ["<source>"]}
    },
    {
      "pr": 13,
      "parent": 11,
      "select": false,
      "head": {"repo": "owner/repo", "ref": "feat/parser-docs", "sha": "<40-hex head oid>"},
      "base": "feat/parser-core"
    }
  ]
}
```

| Field | Rule |
| --- | --- |
| `schema_version` | `1`; any other version is rejected |
| `repository` | `OWNER/REPO` or `HOST/OWNER/REPO` of the base repository |
| `trunk` | Explicit trunk branch the graph is rooted at |
| `nodes[*].pr` | Positive PR number, unique in the packet |
| `nodes[*].parent` | Another node's PR number, or `null` for the trunk |
| `nodes[*].select` | `true`: authorized to be landed (if not already landed). `false`: context that is preserved untouched |
| `nodes[*].head` | Exact observed `repo`, `ref` and full `sha`; a head `repo`+`ref` appears at most once and is never the trunk |
| `nodes[*].base` | Expected current provider base: the trunk, or the parent's head ref when the parent's head lives in the base repository |
| `nodes[*].fork` | Optional full OID of the old parent head the node's own slice sits on; only for nodes with a parent, never the node's own head. Needed when the node does not sit on its parent's final head: a fork is never fetched by object id |
| `nodes[*].decision` | Selected nodes only, required: revision-free lifecycle decision bound to current head/base. `merge_method` is `merge`, `squash` or `rebase`; routine assurance is default. Omitted `expected_checks` uses current provider evidence; explicit inventories and sourced `ci_free` remain authoritative. Optional: `sources`, `post_merge_commands`, `allowed_skips`, `head_only_checks`, `protected_refs`, `assurance`. Explicit `assurance: "high"` requires the sourced inventory and checkout attestation |
| `nodes[*].provenance` | Selected nodes only, required: `disposition` `preserve` (the only accepted value) and a nonempty `sources` list naming what was inspected |

Unknown keys, wrong types, oversize files, duplicate PR numbers or heads, cycles, a parent that is not a node, a base that is neither the trunk nor the parent's head, and a selected node missing its decision or provenance are rejected before anything is observed or mutated. The packet never declares a node merged: current provider facts decide that, and a packet that contradicts them (head, base, state or parent) for a selected node or any of its ancestors stops mutation. Unselected nodes are context: their refs, PRs, bases and local branches are preserved. A change to an unselected node outside every selected node's ancestry (a sibling or child that moved, was retargeted or closed) is reported, not a stop; while such a node stays open it keeps the branch it uses retained.

The delegated executable also accepts `--gates PATH` for local validation before pushes. Gate packets, per-commit selection, timeout limits and saved-run validation are specified in `ship-workflow/references/commit-planning.md`, loaded through the registered companion skill. Keep repository hooks and CI job names unchanged. Routine checks distinguish workflow, event, publisher, job and current attempt; strict provider-required current-base checks and renewed retarget evidence remain authoritative.

## Stop Conditions

- No Git repository is detected.
- The stack has fewer than two dependent branches and the user asked for a normal PR.
- A requested branch does not exist locally.
- A branch appears more than once.
- The parent relation has a cycle.
- A node has two equally plausible parents.
- Provider PR metadata contradicts explicit order or parents.
- The stack decision packet contradicts observed provider facts for a selected node or one of its ancestors: head repository, ref or OID, base, state, or parent.
- A selected node has an unselected ancestor that is not yet merged; parent-first scope is never silently expanded.
- A selected node or one of its ancestors is closed unmerged.
- `.stack-prs.yaml` exists but fails schema validation.

When parent order is ambiguous, stop and request explicit parents. Do not invent semantic relationships from branch names.
