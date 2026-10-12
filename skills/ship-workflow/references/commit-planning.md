# Commit planning contract

Dirty work becomes logical commits in three steps: a read-only inventory, an assistant-authored grouping draft compiled into an exact commit plan, and snapshot-bound execution. Grouping, messages and ownership are judgment; everything else is executable and verified. The plan is data. It never contains commands.

## Inventory

```bash
uv run --no-project --python 3.12 python /absolute/installed/ship-workflow/scripts/ship.py --inventory
```

Inventory runs Git with `GIT_OPTIONAL_LOCKS=0` and hashes working-tree content with `git hash-object` without `-w`. It writes no object, index, ref, journal, cache or lock and never fetches. Every staged, unstaged, untracked and deleted path is one item:

| Field | Meaning |
| --- | --- |
| `id` | Stable identity derived from the exact path bytes |
| `path` | Base64 of the exact Git path bytes; `display` is for humans only |
| `head`, `index`, `worktree` | `{mode, oid}` or `null` (absent, deleted, or intent-to-add index) |
| `staged`, `unstaged`, `untracked`, `deleted` | Derived flags |
| `concerns` | `potential-secret`, `generated-artifact`, `bulk-artifact`, `submodule`: committing needs an explicit acknowledgement |
| `blockers` | `submodule-dirty`, `nested-repository`, `unsupported-kind`: never committable, only excluded with a reason |

`ignored` lists ignored paths (directories collapsed). They are never committed and never reach validation. Secret detection is a path and pattern heuristic, not the outgoing scan, and never proves absence. Conflicts or an in-progress Git operation block execution.

## Gate decision packet

Gates are a separate source-provenanced decision passed explicitly with `--gates`; repository files are never auto-loaded.

```json
{
  "schema_version": 1,
  "sources": ["justfile:34 test target", ".github/workflows/tests.yml:41"],
  "gates": [{"name": "unit", "argv": ["uv", "run", "pytest", "-q"]}],
  "secret_scan": {"argv": ["gitleaks", "git", "--log-opts={base}..{head}", "."]},
  "local_gates_free": false
}
```

Names are simple identifiers. Every group references at least one gate unless `local_gates_free` is explicitly true, in which case no gates exist and groups reference none. `secret_scan` is mandatory; `{base}` and `{head}` are replaced with the validated parent and new commit identities, nothing else is substituted. A missing executable is `BLOCKED`, never replaced by a weaker check.

## Grouping draft

The assistant decides dispositions and grouping; `--draft` writes the proposed blob and tree objects (an explicitly authorized authoring operation: no index, ref, working-tree, journal or lock change) and prints the complete validated plan.

```bash
ship.py --draft /abs/draft.json --gates /abs/gates.json
```

```json
{
  "schema_version": 1,
  "base": {"ref": "main", "oid": "<full base commit>"},
  "placement": {"mode": "new", "branch": "feat/parser"},
  "dispositions": [
    {"item": "<id>", "disposition": "include", "reason": null, "acknowledge": []},
    {"item": "<id>", "disposition": "exclude", "reason": "unrelated experiment", "acknowledge": []}
  ],
  "groups": [
    {"id": "fix", "message": "fix(parser): reject empty tokens", "requires": [], "validation": ["unit"],
     "changes": [{"item": "<id>", "blob_file": "/abs/partial-content", "mode": "100644"}]},
    {"id": "feat", "message": "feat(parser): add arrays", "requires": ["fix"], "validation": ["unit"],
     "changes": [{"item": "<id>", "content": "final"}]}
  ]
}
```

`content: "final"` is the item's exact working-tree state, including deletion, mode, symlink target and gitlink. `blob_file` holds the exact intermediate bytes of a same-file split; the final group touching that file uses `final`. Each item has exactly one disposition; exclusions need a reason; inclusions acknowledge exactly the item's concerns.

## Commit plan

```json
{
  "schema_version": 1,
  "repository": {"root": "/abs/checkout", "common_dir": "/abs/checkout/.git"},
  "source": {"head": "<oid>", "branch": "main", "snapshot": "<sha256>", "index": "<sha256>"},
  "inventory": "<sha256>",
  "base": {"ref": "main", "oid": "<oid>"},
  "placement": {"mode": "new", "branch": "feat/parser"},
  "items": [{"id": "<id>", "path": "<base64>", "disposition": "include", "reason": null, "acknowledge": []}],
  "groups": [{"id": "fix", "message": "...", "items": ["<id>"], "requires": [], "tree": "<tree oid>", "validation": ["unit"]}],
  "final_tree": "<tree oid>"
}
```

The plan identity is the SHA-256 of its canonical JSON. Unknown or missing fields, non-canonical base64, traversal, `.git` components, NUL, unsupported modes, file/directory collisions and future-group dependencies are malformed input.

Validation binds the plan to the current checkout and reports `NEEDS_JUDGMENT` with exact details when:

- repository, HEAD, branch, snapshot, index or inventory identity changed;
- an item lacks exactly one disposition, a blocker is included, or a concern is unacknowledged;
- a group changes nothing, changes a path outside its listed items, or lists an item it does not change;
- a later group edits a path an earlier group edited without requiring it (directly or transitively);
- an intermediate state contains content absent from the snapshot-bound HEAD, original index and final working-tree states (binary, link and submodule states must equal an inventoried state; modes absent from those states are rejected);
- the last group's tree is not `final_tree`, or `final_tree` differs from the original content of every included item (excluded paths keep their base state);
- a proposed tree or blob is missing from the repository.

Intermediate regular-file content must be an ordered selection of the captured source line occurrences, not merely a collection of known line values. Each occurrence retains its exact terminator bytes, including CRLF, lone CR and missing final newline; normalization is not invented source content. No intermediate line can occur more often than its maximum count in a captured state, including when the states reordered other shared lines. A staged state that the working tree later reverted or deleted must appear in a group or receive an explicit exclusion/regrouping disposition; it cannot disappear from the plan.

## Placement

| Mode | When | Result |
| --- | --- | --- |
| `current` | Checked-out feature branch descending from `base.oid` | Commits on top of its existing history; the branch, HEAD and index move together |
| `new`, base is HEAD | Dirty default branch or detached base | A new branch at the commits; HEAD moves to it; the old branch is untouched |
| `new`, base differs | Dirty unrelated feature branch | Commits start at the base, never importing that branch's history; HEAD, index and working tree stay as they were |

`base.oid` must be reachable from the actual named local base branch or its cached remote-tracking ref; an unrelated feature tip cannot masquerade as that base. Missing or contradictory branch-base proof requires judgment without an implicit fetch. New commits never land on the intended base branch. When included paths differ between HEAD and a different base, the work cannot move losslessly and execution stops with the paths for a placement decision.

## Execution

1. Re-inventory and validate. A changed snapshot invalidates the plan.
2. Journal the group (`parent`, `tree`, message SHA-256) before creating it. Create the commit with the user's own `git commit` and hooks in a private shared clone checked out at exactly the planned tree, with the source repository's effective identity and signing settings, including conditional global configuration. A hook refusal or hook-modified content stops with `NEEDS_JUDGMENT`; hooks are never bypassed. Import the byte-identical commit object.
3. Run each referenced gate and the secret scan in a fresh clean clone of exactly that commit. Ignored or untracked files of the user's checkout cannot exist there. A failed or timed-out gate is `NEEDS_JUDGMENT` with a redacted diagnostic tail; a scan finding is `BLOCKED`. Nothing local moves.
4. Under the cooperative lock, require the original snapshot, named-base proof and an unused non-colliding feature ref again before changing the index. Ref collisions include case-folded and Unicode-normalized equality and directory/file ancestry; refusal precedes any index rewrite. Journal the exact index and ref update (old/new branch identity, expected index listing digest, HEAD symbolic ref before/after) and the original retained-work identity, apply the index entries of included paths, move the branch with a compare-and-swap, and switch HEAD when the placement requires it.
5. Before recording confirmation, verify every working-tree byte is unchanged, committed items are clean and excluded items keep their exact index and working-tree state. A failed preservation proof leaves the update pending and blocks the invocation; a later invocation must prove the original retained state again before confirming it.

The working tree is never written. Nothing is stashed, reset, cleaned, forced or added blindly. Validated commit objects are recorded and reused by a resubmitted plan with the same parent, tree, message and gates; nothing is recreated blindly.

## Recovery

A journaled update is reconciled before anything else: a branch at the new commit with the expected index is checked against the original retained-work identity before confirmation (completing a pending HEAD switch), an applied index with the old branch completes the branch move and performs the same preservation check, an untouched index and branch marks the update not applied, and anything else needs judgment. Rerunning a confirmed plan is a verified no-op. A historical update without a retained-work identity remains unknown; only an all-included, non-transplanted matching plan with clean committed paths and no retained work can establish the empty-state proof. There is no override for accepting changed retained work. The receipt stores identities and sanitized outcomes, never messages, source content or gate output.

## Limits

Validation requires that every new commit can be checked out on this filesystem; a commit whose tree holds a path the filesystem cannot represent is `BLOCKED`. Clean/smudge filters run as Git runs them. Interactive signing prompts are bounded by the commit deadline. A repository squash merge may later collapse these commits on the base; that consequence is reported, not prevented.
