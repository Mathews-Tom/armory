# Verification Receipts 1.0.0

A cross-host native package for deliberately running configured verification gates, privately saving their exact results and bounded output, and reopening evidence against freshly observed declared inputs. Package and shared core versions are 1.0.0. This documents the implemented package, not a claim that it has already been merged, tagged or published.

## Configure a gate

Use Git, the locked Bun 1.3.14 toolchain and a POSIX system. From an Armory checkout, install workspace dependencies with `bun install --cwd extensions --frozen-lockfile`. The configured executable must also be available. Put a configuration such as `verification.json` in the Git worktree being verified:

```json
{
  "schemaVersion": 1,
  "configId": "project-verification",
  "gates": {
    "unit": {
      "criterionId": "unit-tests",
      "kind": "unit",
      "executable": "bun",
      "args": ["test", "tests"],
      "cwd": ".",
      "timeoutMs": 60000,
      "maxOutputBytes": 65536,
      "requiresCompleteOutput": true,
      "scope": {
        "paths": ["src", "tests"],
        "configPaths": ["package.json", "bun.lock"],
        "environmentNames": [],
        "datasetIdentity": null
      }
    }
  }
}
```

Only configured gate IDs execute; command text is not accepted as an alternative. Configuration and command cwd are worktree-relative. Unknown fields and schemas fail explicitly, with no implicit gate defaults. Do not put credentials in configuration or persisted command arguments.

## Build and exercise an owned installation

From the Armory checkout, install Python development dependencies (including the dev-only `pyte` terminal parser) and build both host artifacts:

```bash
uv sync --locked
uv run python scripts/build_extensions.py --feature verification-receipts \
  --output-dir /tmp/armory-receipts-build
```

The output directories are `/tmp/armory-receipts-build/extensions/verification-receipts/omp` and `/tmp/armory-receipts-build/extensions/verification-receipts/claude`. OMP's package-root entry is `index.ts`, exporting the bundled `omp/index.js`; Claude's plugin manifest is `.claude-plugin/plugin.json` and its native module is `hooks/register.ts`, declared by `hooks/hooks.json`. Helpers are bundled under `helpers/`; artifacts do not depend on a development checkout at runtime.

Use fresh disposable **host configuration roots**, not your real profile. The installer builds its own payload from the checkout; the build command above is for inspecting or explicitly loading artifacts. For OMP:

```bash
uv run python scripts/install.py --type extension --platform omp \
  --name verification-receipts --action install \
  --target-root /tmp/armory-receipts-omp-profile --yes
uv run python scripts/install.py --type extension --platform omp \
  --name verification-receipts --action disable \
  --target-root /tmp/armory-receipts-omp-profile --yes
# install also re-enables an owned disabled package.
uv run python scripts/install.py --type extension --platform omp \
  --name verification-receipts --action install \
  --target-root /tmp/armory-receipts-omp-profile --yes
uv run python scripts/install.py --type extension --platform omp \
  --name verification-receipts --action update \
  --target-root /tmp/armory-receipts-omp-profile --yes
uv run python scripts/install.py --type extension --platform omp \
  --name verification-receipts --action remove \
  --target-root /tmp/armory-receipts-omp-profile --yes
```

For Claude, target its own disposable configuration root:

```bash
uv run python scripts/install.py --type extension --platform claude \
  --name verification-receipts --action install \
  --target-root /tmp/armory-receipts-claude-profile --yes
uv run python scripts/install.py --type extension --platform claude \
  --name verification-receipts --action disable \
  --target-root /tmp/armory-receipts-claude-profile --yes
uv run python scripts/install.py --type extension --platform claude \
  --name verification-receipts --action install \
  --target-root /tmp/armory-receipts-claude-profile --yes
uv run python scripts/install.py --type extension --platform claude \
  --name verification-receipts --action update \
  --target-root /tmp/armory-receipts-claude-profile --yes
uv run python scripts/install.py --type extension --platform claude \
  --name verification-receipts --action remove \
  --target-root /tmp/armory-receipts-claude-profile --yes
```

These operations modify only the chosen configuration root; installing there does not select it for a running host. Do not change HOME, authentication or enforcement merely to launch a test. There is no separate rollback action: run `update` from the deliberately selected older compatible checkout against the same host/root. Review that version first. Owned updates, rollback, disable/re-enable and removal preserve external receipt data and foreign host state. Modified/foreign payloads are refused rather than silently overwritten. Never delete unknown files to bypass that refusal.

Keep receipt data outside both the worktree and installed payload, for example in a newly created private directory `/tmp/armory-receipts-state` with mode 0700. Lifecycle removal is not receipt deletion. Do not reuse a foreign or permissive state directory; unsafe, linked or malformed state is rejected, not repaired.

## Deliberate native invocation

Both hosts expose exactly two literal commands. First verify that the native host actually lists them; never submit an absent command, which could instead become an agent prompt. Loading the package grants no approval exemption. Keep normal trust, credentials, approvals and enforcement intact.

### OMP RPC

Load the built package-root entry, with all five explicit string flags:

```bash
omp --mode rpc \
  --extension /tmp/armory-receipts-build/extensions/verification-receipts/omp/index.ts \
  --armory-receipts-repo /path/to/project \
  --armory-receipts-config verification.json \
  --armory-receipts-data-root /tmp/armory-receipts-state \
  --armory-receipts-account local-account \
  --armory-receipts-work-context project-work
```

There are no inferred repository/account/work-context/state-root defaults. The adapter obtains the actual native session identity. An RPC client must wait for `ready`, call `get_available_commands`, and verify both commands have `source: "extension"` before sending a fixed `prompt` such as `/armory-verify unit`, then `/armory-evidence wait`. Registration checks both names at session start and rejects collisions instead of shadowing them; it is not a global reservation against later extensions replacing commands.

### Claude Code interactive native module

Supply all five explicit environment variables; the session ID comes from the real native `session.id()` API, not an environment label:

```bash
export ARMORY_RECEIPTS_REPO=/path/to/project
export ARMORY_RECEIPTS_CONFIG=verification.json
export ARMORY_RECEIPTS_DATA_ROOT=/tmp/armory-receipts-state
export ARMORY_RECEIPTS_ACCOUNT=local-account
export ARMORY_RECEIPTS_WORK_CONTEXT=project-work
```

For development loading, copy the built Claude artifact into a separately owned, disposable runtime directory and pass that copy to `claude --plugin-dir`. The development loader writes generated SDK types and tsconfig into its copy. Do not point it at a lifecycle-owned payload, delete unknown generated files, or weaken lifecycle ownership checks to make an update succeed. The native driver below makes its own separate runtime copy. This qualification does not establish normal installed-loader behavior.

Start in an already trusted cwd with your reviewed additive settings:

```bash
claude --settings "$ARMORY_CLAUDE_NATIVE_SETTINGS" \
  --plugin-dir /path/to/disposable-claude-runtime-copy
```

`ARMORY_CLAUDE_NATIVE_SETTINGS` is an explicitly reviewed private 0600 settings file, not a supplied default or a permission bypass. Inspect the cwd's optional writers, plugins, hooks and MCP inventory first. Leave user/managed enforcement and normal authentication in place; do not answer trust/login prompts as part of automation. Discover the commands through the native command surface before invoking them. Missing configuration or command collisions fail closed.

### Commands and cancellation

| Command | Behavior |
| --- | --- |
| `/armory-verify <gate-id>` | Start one configured gate asynchronously, returning `{"state":"running"}`. An overlapping request does not spawn another run. |
| `/armory-evidence` | Reopen finalized evidence and recapture current inputs; does not wait for an active run. |
| `/armory-evidence wait` | Await the session-owned task and reopen durable evidence. |
| `/armory-evidence cancel` | Request cancellation of the owned task, await its settlement and reopen evidence. Host-specific cleanup guarantees below still apply. |

OMP cancellation reaches the runner's AbortSignal, awaits owned process-group cleanup and durable completion. Session switch/shutdown abort and await owned work; old sessions cannot publish into replacements. Safe custom RPC text uses `triggerTurn: false`, without a model turn.

Claude uses the native process stream and immediate command responses, without a model prompt. Closing that stream is **not** a descendant-cleanup receipt. After early closure the wrapper conservatively returns `state: "cancellation-unconfirmed"`, `applicability: "unknown"`, with reopened `evidence`, even when that evidence contains an actual durable cancelled receipt. The actual tested cancellation produced durable cancellation exit 143 and proved root/descendant absence, but does not strengthen the generic stream API contract. Interrupted owners may instead reconcile as incomplete/unknown. Session end revokes old context and attempts original-scope cancellation/reconciliation; its bounded host hook is not an unconditional cleanup guarantee.

## Standalone inspection

The standalone CLI remains available without a native host:

```bash
bun /path/to/armory/extensions/verification-receipts/helpers/cli.ts --help
bun /path/to/armory/extensions/verification-receipts/helpers/cli.ts run \
  --repo /path/to/project --config verification.json \
  --data-root /tmp/armory-receipts-state \
  --host standalone --session local-session --account local-account \
  --work-context project-work --gate unit
```

Use the same context arguments with `show --id <execution-id>`, `list` or `reconcile` in place of `run --gate unit`. Repository, host, account and work context select the private partition; worktree identity is recorded separately. Changing only session identity permits reopening history. Standalone and native host partitions are intentionally distinct. Account/work-context labels are not credentials or authenticated identity attestations. If standalone `--data-root` is omitted, the default is `.local/state/armory/verification-receipts` beneath the OS account home, not a substituted HOME; prefer an explicit disposable root.

## Evidence, privacy and execution limits

- Result (`passed`, `failed`, cancellation or incomplete) records the configured execution, not overall project quality. Missing launch, missing output, timeout and unproved cleanup cannot establish successful proof.
- Applicability (`current`, `stale`, `unknown`) is recomputed on reopening. Covered content, untracked additions/deletions, executable mode, configuration, selected keyed environment fingerprints and declared dataset identity matter; unrelated edits do not. Changed-during-run inputs make applicability unknown.
- Proof requires matching feature/core versions, passed execution, proved owned cleanup, current inputs and complete output when required. Supported-schema historical receipts with a version mismatch retain their original result and immutable output, but applicability is unknown and proof false until rerun.
- Output is bounded, privately stored and hashed. Files are 0600 and owned state directories 0700. Native/public text contains safe projections, hashes, byte counts, truncation information and stable error codes—not credentials, configured commands, private paths, raw output, environment values, account labels or exception text.
- `reconcile` recovers only committed reservations whose owner PID is demonstrably gone, without claiming descendant cleanup or success. Recovered captured bytes retain an exact hash; unknown total-byte/truncation diagnostics remain `null`. Live/inaccessible owners are left alone; corrupt final records fail closed.

Standalone `run` exits 0 for current successful proof, 1 for failed execution, 2 for incomplete/not proof, 130 for cancellation/SIGINT and 143 for SIGTERM. Successful read observations exit 0 even for stale/unknown evidence: inspect `proof` and `applicability`. Invalid arguments/unusable state return sanitized errors and exit 2.

Executables and argument vectors run without shell interpolation, with ordinary user permissions. A configured program is trusted code and can write or access the network: this is not a sandbox or approval system. POSIX execution owns a process group, applies TERM then bounded KILL, drains bounded output and reaps the root. `descendantsStopped` means that owned group is absent and its root reaped; deliberately escaped groups/sessions are outside that guarantee. Use non-daemonizing gates. Windows execution is incomplete, not certified cleanup. Declared-input fingerprints are observations, not complete dependency coverage or tamper-proof attestations; pre/post equality cannot detect modify-and-revert. Private atomic storage does not defend against a malicious same-account process. No implicit retries, model calls or live-vault writes are added by the package.

## Offline CI and manual native qualification

```bash
uv run python scripts/check_extensions.py --ci
uv run python scripts/check_extensions.py --feature verification-receipts
```

These are offline gates, not authenticated host startups: behavior/integration tests, pinned API typechecking, strict native validation/test kits, reproducible contained builds and owned lifecycle checks. Missing offline tools and failed checks remain nonzero. CI reports live smoke as not requested, never native proof.

For explicit local/manual qualification, first review the real host context. Claude requires both a trusted cwd and the reviewed private 0600 additive settings file; there is no fabricated safe default:

```bash
export ARMORY_CLAUDE_NATIVE_CWD=/path/to/already-trusted-reviewed-directory
export ARMORY_CLAUDE_NATIVE_SETTINGS=/path/to/reviewed-private-settings.json
uv run python scripts/check_extensions.py --feature verification-receipts --native-smoke
```

The driver uses those explicit Claude prerequisites and a separate owned runtime copy, preserving normal HOME, authentication and enforcement. It fails closed on unavailable hosts/prerequisites or unreviewed versions, rather than treating missing native proof as a pass. Review optional writers and MCP containment for OMP too. No persistent owner installation or live vault write is needed. Native host bookkeeping and possible catalog metadata traffic are not model-call meters.

Actual production-contained artifacts passed all eight scenario groups separately on macOS arm64 with Bun 1.3.14: **OMP 18.12.6 RPC** and **Claude Code 2.1.309 real interactive TTY**. Scenarios covered exits 0/7, fresh-session reopening, covered modification/untracked addition/deletion/config changes versus unrelated edits, changed-during-run unknown applicability, durable cancellation with root and descendant absence, private output hashes/modes and safe native text. Real receipt lifecycle exercises covered both hosts, update/rollback and foreign-state refusal; same-feature builds were byte-identical across roots.

Pinned Claude Code 2.1.308 strict offline validation and five native-test-kit cases passed; these are **not native 2.1.308 compatibility certification**. No Windows, Linux-native, OMP TUI rendering or live ACP response claim is made. Inspected OMP 18.12.6 ACP does not forward live custom-message completion text; historical session replay is not a replacement. No normal installed Claude loader claim is inferred from `--plugin-dir` qualification. Requalify changed artifacts, native versions and surfaces rather than carrying proof forward automatically.
