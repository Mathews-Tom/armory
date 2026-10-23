# Resume Brief (development prefix)

A standalone CLI that records a freshness-checked brief for one explicitly selected Git worktree and, when reopened, reports exactly which branch, plan, blocker, verification, session and approval facts changed since recording, each linked to the source it came from. This prefix contains the pure shared core and the bounded helper CLI only. It has no OMP or Claude Code command, no `EXTENSION.md`, no catalog, install or release entry, and is not a cross-host extension yet; `/armory-brief` and native renderers are planned for the package-bearing delivery.

## Requirements

Git, the locked Bun 1.3.14 toolchain and macOS or glibc Linux. Repository-source containment uses the operating system's `openat` through Bun FFI, pinning every directory and refusing symbolic links during the actual open rather than relying on preflight checks. From an Armory checkout run `bun install --cwd extensions --frozen-lockfile`. The CLI runs from the checkout; no distributed artifact exists for this prefix.

## Select project sources

Commit (or keep) a context artifact anywhere inside the worktree, for example `brief.json`:

```json
{
  "schema": "armory.resume-brief.context/v1",
  "objective": "Ship the parser rewrite",
  "plan": { "path": "docs/PLAN.md" },
  "blockers": { "path": "docs/blockers.json" },
  "pullRequest": { "number": 7, "url": "https://github.com/example/project/pull/7" },
  "approvals": [
    {
      "id": "deploy-staging",
      "scope": "deploy to staging",
      "origin": { "host": "omp", "accountId": "acct-a", "sessionId": "omp-1" },
      "grantedAt": "2026-01-01T00:00:00Z",
      "expiresAt": "2026-01-02T00:00:00Z"
    }
  ]
}
```

`plan`, `blockers`, `pullRequest` and `approvals` are optional. Paths are repository-relative; absolute paths, `..`, `.git` components and any symbolic link on the path are rejected. The plan may be any text file: the brief records its SHA-256, the last commit that touched its literal filename and whether its raw bytes differ from the raw `HEAD` blob. This comparison does not run Git content-conversion filters; it is not Git's normalized working-tree status. An unavailable `HEAD` blob leaves that comparison unknown. The blockers file uses its own schema:

```json
{
  "schema": "armory.resume-brief.blockers/v1",
  "blockers": [{ "id": "flaky-ci", "summary": "CI job times out", "status": "open" }],
  "nextAction": "Rerun the integration suite"
}
```

Unknown fields or schema identifiers are refused, never reinterpreted. Approvals require `expiresAt` (use `null` for none) and UTC `Z` timestamps.

Optional sources outside the repository are selected explicitly per `record`; nothing is discovered or scanned:

- `--omp-session <file.jsonl>`: one OMP JSONL session file whose header is `{"type":"session","version":3,...}` (OMP 18.12.6 `SessionHeader`), optionally preceded by the native version-1 fixed-width title slot. The title is discarded. Only the header `id`, `timestamp` and `cwd`, entry count and last entry id/timestamp are kept. Entries of `type: "custom"` with `customType: "armory.resume-brief.approval"` and `data: {id, scope, grantedAt, expiresAt}` become approval holds whose origin is fixed to `omp` and that session id; that data is feature-written, not host-authenticated. Message bodies are never stored. Other session versions and foreign formats (for example a Claude Code transcript) are `unsupported-schema`.
- `--omp-handoff <handoff-<timestamp>.md>`: an OMP-saved handoff document. Only its file identity, hash and the timestamp encoded in its native file name are recorded; the document text is not interpreted or stored.
- `--receipt <file.json>`: a Verification Receipts schema-1 receipt file. The brief references it by path and SHA-256 with execution id, gate id, status, finish time and whether its repository identity matches the selected worktree. It does not copy the receipt into a new ledger and does not re-prove freshness; use the Verification Receipts CLI for that.

## Commands

```bash
CLI=extensions/resume-brief/helpers/cli.ts
COMMON=(--repo /abs/path/to/worktree --data-root ~/.local/state/armory/resume-brief \
  --host standalone --account my-account --session my-terminal)

bun "$CLI" record "${COMMON[@]}" --context brief.json \
  [--omp-session /abs/session.jsonl] [--omp-handoff /abs/handoff-....md] [--receipt /abs/receipt.json] [--format text]
bun "$CLI" reopen "${COMMON[@]}" --latest            # or --id <snapshot-id>
bun "$CLI" show   "${COMMON[@]}" --id <snapshot-id>
bun "$CLI" list   --repo /abs/path/to/worktree --data-root ... --host standalone
bun "$CLI" --help
```

- `record` observes Git branch, detached state, `HEAD` and upstream plus the selected sources once and stores a new snapshot. Repository-wide dirty state remains explicitly unknown: the reader does not run `git status`, which can execute repository-configured fsmonitor and conversion commands. It prints `{snapshotId, card}`.
- `reopen` re-reads exactly the selection recorded in that snapshot and prints the recorded card, the current card and the field-level `discrepancies`. Each discrepancy names the field, the kind (`changed`, `added`, `removed`, `became-unknown`, `became-known`, `expired-since-record`), recorded and current values, and the source role, reference and both SHA-256 values.
- `show` prints a recorded card without reading any source, re-evaluating approval expiry at the current time.
- `--repo` must be the absolute worktree root itself; a subdirectory alias is rejected. `--account` and `--session` are opaque labels used only to decide whether an approval's origin is the current context.
- Exit codes: `0` success or no discrepancy, `1` reopen found discrepancies, `2` invalid input, rejected state or failure. Errors are one JSON line on stderr: `{"error":"rejected","detail":...}` for this feature's own refusals, or `{"error":"operation-failed"}` without foreign exception text.
- `--format text` renders every value that came from a repository, source file or session as a quoted literal with control, bidirectional, Markdown and shell characters escaped as `\u{..}`.

## Card, unknowns and authority

The card shows the objective, plan reference and revision facts, the referenced last verification, branch/worktree/`HEAD`/upstream/dirty, the declared pull request, blockers and next action, native session facts, approval holds and the identity (role, reference, status, SHA-256, size, mtime, diagnostic) of every source.

A missing, unreadable, special (FIFO, device, directory), oversize, symlinked, malformed, unsupported or changed-while-read source produces a `null` fact plus an `unknowns` entry with the reason; no fact defaults to a successful value. Git branch, `HEAD` and upstream are read before and after the sources; a change in between marks them `changed-during-read`. Repository-wide dirty state is unknown; selected plan changes still have an exact raw-content comparison. Git queries use literal filenames, suppress signature-program invocation and prohibit lazy fetching. The pull request's live state is always `unknown`: the CLI makes no network or GitHub calls and reports only the declared number and URL.

`authority` is always `"none"`, `nextAction.executed` is always `false` and reopen always reports `resumed: false`. Every approval is projected as a hold with `executable: false`. Expiry is judged from the approval's own recorded time, so an unchanged or freshly re-read source never renews it. An origin whose host, account or session differs from the invocation, or is unknown, is marked `foreignOrigin`; approvals never transfer between hosts, accounts or sessions.

## Private state

Snapshots are written to `<data-root>/resume-brief/<repository-id>/snapshots/<snapshot-id>.json`. The data root must be outside the repository, the worktree and this package; it and every directory created under it must be owned 0700 directories, and an existing root with looser permissions is refused rather than changed. Each snapshot is a new 0600 file published with exclusive no-clobber semantics, so earlier snapshots are preserved. Reads refuse links, non-private or multi-link files, unexpected directory entries, oversize content, invalid ids and any structurally unexpected field.

State creation, enumeration, reads and publication use descriptor-pinned, no-follow directory traversal on macOS/glibc Linux. Each operation checks the snapshot directory's owned/private device-and-inode identity; replacing it or an ancestor with a link cannot redirect a write or read. Staging, no-clobber linking, cleanup and directory synchronization stay relative to that pinned descriptor, not a previously checked pathname. macOS staging uses the public fixed-ABI `mkostempsat_np` interface; it does not pass a creation mode through Bun FFI's non-variadic `openat` signature.

A snapshot is a derived cache: it holds the selection, source hashes and the bounded allowlisted facts needed for comparison (objective, blocker ids/summaries/status, next action, declared pull request, approvals, receipt reference fields and session header facts). It holds no plan text, handoff text, receipt body or transcript content, and it is not an authoritative plan, memory or receipt store. Deleting the data root removes only briefs; it never touches project files, handoffs or receipts.

## Limits of this prefix

- Standalone host only; OMP and Claude Code commands, renderers and native qualification are not implemented.
- Claude Code sessions have no supported on-disk export here. Native observation will come through the host API in the adapter delivery; Claude transcripts are refused as unsupported.
- Receipt freshness is not recomputed; only the receipt reference is checked.
- Snapshot pruning is not provided.

## Checks

```bash
bun run --cwd extensions typecheck
bun run --cwd extensions eslint --max-warnings=0 resume-brief
bun test extensions/resume-brief/tests/
uv run --python 3.12 python scripts/check_extensions.py --feature resume-brief --stage core
```

The core stage reports `feature_complete=false`; it certifies only this standalone prefix.
