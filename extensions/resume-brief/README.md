# Resume Brief 1.0.0

A standalone, cross-host native package that records a freshness-checked brief for one explicitly selected Git worktree and reports source-linked differences when reopened. Package and shared core versions are 1.0.0. It executes no recorded action, resumes no task and grants no authority. The compatibility section identifies exercised native surfaces; implementation and qualification do not assert merge or publication.

## Requirements

Git, the locked Bun 1.3.14 toolchain and macOS or glibc Linux. Repository-source containment uses the operating system's `openat` through Bun FFI, pinning every directory and refusing symbolic links during the actual open rather than relying on preflight checks. From an Armory checkout run `bun install --cwd extensions --frozen-lockfile`. Both native artifacts bundle their helpers and do not import another feature or require an Armory checkout at runtime. Native compatibility is limited to the exact versions and surfaces declared below; Linux support in deterministic filesystem checks is not native Linux qualification.

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

**Standalone-prefix cache format:** the complete native package writes `armory.resume-brief.snapshot/v2` and refuses the earlier PR1 prefix's `snapshot/v1` files rather than guessing missing native-session fields. `show`, `reopen` and `list` can therefore reject an old cache. Keep the old root and files unchanged. Select a new external private data root with `--data-root` (standalone), `--armory-brief-data-root` (OMP) or `ARMORY_BRIEF_DATA_ROOT` (Claude), then explicitly `record` a new brief from the original selected sources. Do not edit schema identifiers, mix old snapshots into the new root or treat the new record as a renewal of any approval.

## Build and owned lifecycle

Run from the Armory checkout:

```bash
uv sync --locked
uv run python scripts/build_extensions.py --feature resume-brief \
  --output-dir /tmp/armory-brief-build
```

The host artifacts are `/tmp/armory-brief-build/extensions/resume-brief/omp` and `/tmp/armory-brief-build/extensions/resume-brief/claude`. OMP loads the package-root `index.ts`; Claude uses `.claude-plugin/plugin.json`, `hooks/hooks.json` and `hooks/register.ts`. Bundled helpers live under `helpers/`.

Select the extension and host explicitly. Use separate disposable configuration roots for lifecycle exercises:

```bash
uv run python scripts/install.py --type extension --platform omp \
  --name resume-brief --action install --target-root /tmp/armory-brief-omp-profile --yes
uv run python scripts/install.py --type extension --platform omp \
  --name resume-brief --action update --target-root /tmp/armory-brief-omp-profile --yes
uv run python scripts/install.py --type extension --platform omp \
  --name resume-brief --action disable --target-root /tmp/armory-brief-omp-profile --yes
uv run python scripts/install.py --type extension --platform omp \
  --name resume-brief --action install --target-root /tmp/armory-brief-omp-profile --yes
uv run python scripts/install.py --type extension --platform omp \
  --name resume-brief --action remove --target-root /tmp/armory-brief-omp-profile --yes

uv run python scripts/install.py --type extension --platform claude \
  --name resume-brief --action install --target-root /tmp/armory-brief-claude-profile --yes
uv run python scripts/install.py --type extension --platform claude \
  --name resume-brief --action update --target-root /tmp/armory-brief-claude-profile --yes
uv run python scripts/install.py --type extension --platform claude \
  --name resume-brief --action disable --target-root /tmp/armory-brief-claude-profile --yes
uv run python scripts/install.py --type extension --platform claude \
  --name resume-brief --action install --target-root /tmp/armory-brief-claude-profile --yes
uv run python scripts/install.py --type extension --platform claude \
  --name resume-brief --action remove --target-root /tmp/armory-brief-claude-profile --yes
```

`install` re-enables an owned disabled package. There is no rollback action: deliberately select a reviewed older compatible checkout and run `update` against the same host/root. Modified or foreign payloads are refused, not overwritten; do not delete unknown files to bypass ownership checks. Lifecycle preserves private snapshots, selected sources and foreign host state. Configuration roots do not automatically select a running host. Profiles, presets, `all` selection and the all-in-one plugin do not enable extensions.

## Deliberate native invocation

Keep normal HOME, default authentication, trust, permissions and enforcement. Do not automate login/trust prompts or substitute an isolated HOME to make a host start. Use an explicitly selected disposable synthetic project and sources, and an external private data root (0700). Account labels are references, not credentials or authenticated identity attestations.

### OMP

```bash
omp --mode rpc \
  --extension /tmp/armory-brief-build/extensions/resume-brief/omp/index.ts \
  --armory-brief-repo /absolute/path/to/project \
  --armory-brief-data-root /tmp/armory-brief-state \
  --armory-brief-account local-account \
  --armory-brief-context brief.json
```

Optional string flags are `--armory-brief-omp-session /absolute/session.jsonl`, `--armory-brief-omp-handoff /absolute/handoff-<timestamp>.md` and `--armory-brief-receipt /absolute/receipt.json`. No session is discovered automatically; the current invocation session identity comes from the host. Wait for RPC readiness, query `get_available_commands` and verify `armory-brief` has extension provenance before sending any literal command. Do not submit an absent slash command as a model prompt.

### Claude Code

```bash
export ARMORY_BRIEF_REPO=/absolute/path/to/project
export ARMORY_BRIEF_DATA_ROOT=/tmp/armory-brief-state
export ARMORY_BRIEF_ACCOUNT=local-account
export ARMORY_BRIEF_CONTEXT=brief.json
claude --settings "$ARMORY_CLAUDE_NATIVE_SETTINGS" \
  --plugin-dir /path/to/disposable-claude-runtime-copy
```

Copy the built Claude artifact into a separately owned disposable runtime directory first: the development loader may generate SDK types and configuration there. Do not load a lifecycle-owned payload with this development loader or remove generated files to evade ownership checks. `ARMORY_CLAUDE_NATIVE_SETTINGS` must name an explicitly reviewed private 0600 additive settings file; no permission bypass or fabricated safe default is supplied. Start in an already trusted, reviewed cwd with optional writers, plugins, hooks and MCP inventory inspected. These instructions do not establish normal installed-loader compatibility.

Optional environment values are `ARMORY_BRIEF_OMP_SESSION`, `ARMORY_BRIEF_OMP_HANDOFF` and `ARMORY_BRIEF_RECEIPT`, each an explicit absolute source path. The current Claude session comes from `$.session`, not an environment label or invented on-disk export. Only identity, locations, start time, turn count and counts over the newest 4096 rows are projected. A full window is incomplete; denied/malformed host answers remain unknown. No message text, tool input or tool results enter the projection.

For an already discovered native command, the same reviewed context supports a whole-command headless invocation with no widget or person:

```bash
claude --settings "$ARMORY_CLAUDE_NATIVE_SETTINGS" \
  --plugin-dir /path/to/disposable-claude-runtime-copy \
  --output-format text -p "/armory-brief reopen --json"
```

Claude 2.1.309 emits `resume-brief: ` followed by the command's JSON payload. Strip exactly that host-owned prefix before decoding JSON; a refusal contains `error`, not a successful brief. Do not treat process exit 0 alone as a successful observation. This exercises the native command path, not a model prompt or the Agent SDK.

### Commands

Discover `/armory-brief` in the real native command surface before invoking it. Both adapters use:

```text
/armory-brief record
/armory-brief reopen
/armory-brief reopen <snapshot-id>
/armory-brief show <snapshot-id>
/armory-brief list
/armory-brief help
/armory-brief reopen --json
```

`reopen` and `show` default to the latest snapshot. `record` and `reopen` require the context selection; `show` and `list` do not re-read selected sources. Reopen refuses a configured selection different from the recorded selection before reading sources; record a new brief instead of widening the old selection. JSON is ASCII-escaped and native text renders untrusted values as escaped literals. Commands are local observations without a model turn, verification run, automatic resumption or executable approval.

Once command arguments are valid, `--json` also returns refusals as `{"error": "<code>", "detail": null | "<safe diagnostic>"}`. This includes missing configuration, changed invocation scope and rejected or truncated helper answers. Invalid command syntax is reported as usage text because no command was accepted. Private helper stderr and foreign exception text are never included.

Session transitions revoke publication into a replacement context. A bounded helper already running may finish its read; cancellation or interruption is not a successful record/reopen or a general process-tree cleanup guarantee. Inspect the actual command result and durable snapshot state rather than inferring completion from a closed UI or stream.

## Offline checks and manual native qualification

```bash
uv run python scripts/check_extensions.py --ci
uv run python scripts/check_extensions.py --feature resume-brief
```

These request credential-free deterministic/integration checks, pinned SDK/adapter contracts, offline Claude validation/test kits, reproducible contained builds, package/catalog and owned lifecycle checks. They are not authenticated host startups or native compatibility evidence. Actual detached-artifact qualification exercised OMP 18.12.6 RPC and Claude Code 2.1.309 interactive and whole-command headless text on macOS arm64; the metadata names only those versions/surfaces.

Explicit local/manual qualification uses real hosts with normal authentication and enforcement:

```bash
export ARMORY_CLAUDE_NATIVE_CWD=/path/to/already-trusted-reviewed-directory
export ARMORY_CLAUDE_NATIVE_SETTINGS=/path/to/reviewed-private-settings.json
uv run python scripts/check_extensions.py --feature resume-brief --native-smoke
```

Feature-owned `tests/omp-smoke.py` and `tests/claude-smoke.py` cover success, failure, reopen, freshness, changed-during-run, cancellation, private-output and native-text categories with host/version/mode and the current artifact manifest. Missing prerequisites are unavailable/nonzero; runtime failures cannot count as success. Separate actual headless Claude qualification exercised `record`, changed-source `reopen`, durable `show`/`list` and JSON refusal with the invocation above. The generic cancellation category proves completed-command/session disposal, not injected in-flight cancellation. Normal installed Claude loading, SDK and OMP TUI/ACP are not certified. Offline results, historical replay and a standalone CLI are not native substitutes.

## Limits

- Live pull request state is unknown; only declared references are shown.
- Receipt freshness is not recomputed; only the existing receipt reference is checked.
- Claude on-disk session exports are unsupported, not inferred from another format.
- Snapshot pruning is not provided.
- No Windows or unexercised native surface/version compatibility is claimed.
