# Verification Receipts — standalone CLI and OMP source adapter

Unregistered development-prefix delivery. Executes an explicitly configured verification command, privately persists its exact result and bounded output, and recomputes freshness against the declared inputs when evidence is reopened. The standalone CLI and OMP 18.12.6 RPC integration are exercised. TUI rendering, live ACP command responses, Claude Code integration, a native package definition and catalog activation are not delivered as verified support. This is not a completed native extension.

## Standalone requirements and invocation

Use the repository's locked Bun 1.3.14 toolchain, Git and a POSIX system. Install the existing workspace dependencies with `bun install --cwd extensions --frozen-lockfile`. No additional dependency or global installation is needed. From the Armory checkout, inspect the actual interface:

```bash
bun extensions/verification-receipts/helpers/cli.ts --help
```

Create a configuration in the project being verified, for example `verification.json`:

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

Invoke only an ID in that configuration. Use an absolute CLI path when running outside this checkout. `--repo` selects the Git worktree; the configuration and command cwd are worktree-relative. Account/session/work-context references are caller-provided labels, not credentials or authenticated identity attestations.

```bash
bun /path/to/armory/extensions/verification-receipts/helpers/cli.ts run \
  --repo /path/to/project --config verification.json \
  --data-root /private/path/to/receipt-state \
  --host standalone --session local-session --account local-account \
  --work-context project-work --gate unit
```

Use the same context arguments with `show --id <execution-id>`, `list` or `reconcile` instead of `run --gate unit`. Session labels may change without moving the evidence partition. Repository, work context, host and account select the private partition; worktree identity is recorded separately. Omitting `--data-root` uses the OS account home, not a substituted `HOME`: `.local/state/armory/verification-receipts` beneath that home. Choose an explicit external private root for disposable use. Existing permissive, foreign, linked or malformed state is rejected, not repaired or overwritten.

## OMP source adapter

The default factory is `omp/index.ts`, typed against the existing workspace OMP API. It uses the same runner, private store and shared evidence projection as the CLI; the CLI still requires `--host standalone` and retains its existing JSON/exit-code semantics.

For a deliberate development source load through OMP's normal extension loader, supply all five explicit string flags. There are no inferred repository, account, work-context or state-root defaults:

```bash
omp --mode rpc --extension /path/to/armory/extensions/verification-receipts/omp/index.ts \
  --armory-receipts-repo /path/to/project \
  --armory-receipts-config verification.json \
  --armory-receipts-data-root /private/path/to/receipt-state \
  --armory-receipts-account local-account \
  --armory-receipts-work-context project-work
```

This source-loading example uses the supported RPC mode and normal extension loader; the native smoke below exercises a detached bundled entry rather than the development checkout. A client must wait for `ready`, request `get_available_commands` and verify both literal commands have `source: "extension"` before submitting a fixed `prompt` such as `/armory-verify unit` followed by `/armory-evidence wait`. Never submit an absent command: the host can route unknown text to its agent. Preserve ordinary credentials, trust, approval and enforcement settings. Loading a configured gate grants no approval exemption: the program runs with the user's ordinary permissions. Account/work-context are opaque partition labels, not authentication attestations. The repository flag may differ from OMP's launch cwd. Receipt context uses `host: "omp"` and the actual host session-manager ID, never a synthetic session flag.

At `session_start` the factory first checks both literal command names for existing dynamic commands, then registers both or neither. A collision is rejected with `command-collision`, not silently shadowed or renamed. Registration requires no filesystem/process work or session-manager access. Repeated unchanged startup keeps the same registrations. The host exposes aggregated command descriptions rather than handler ownership; this preflight is not a global reservation against another extension registering or replacing a command later.

| Command | Behavior |
| --- | --- |
| `/armory-verify <gate-id>` | Start exactly one configured gate asynchronously for this session and report `{"state":"running"}`. Completion reports a safe projection. An overlapping request returns `verification-running` without spawning. |
| `/armory-evidence` | Reopen finalized private receipts and recapture current declared inputs. Does not wait for an active run or substitute a cached freshness result. |
| `/armory-evidence wait` | Await this session's owned task, then reopen and project saved evidence. |
| `/armory-evidence cancel` | Abort this session's owned task through the runner's real `AbortSignal`, await process-group cleanup and durable completion, then reopen saved evidence. |

An unknown gate never executes arbitrary command text. Unknown/extra command arguments and missing/invalid flags fail before filesystem/process work. Session switch and shutdown abort and await every task owned by this factory before clearing its state. No module-global task, timer, daemon or retry loop is added. A late completion or wait from an old session cannot publish into its replacement.

Visible messages use `customType: "armory-receipts"`, `display: true` and `triggerTurn: false`, with JSON text containing only running state, safe receipt projections, `{receipts:[...]}` or a stable `{error:...}` code. Widgets are guarded by the host-reported `mode === "tui"` and `hasUI`; RPC also exposes one-way widget requests, which are not proof of TUI rendering. The adapter adds no user-message injections, model/provider calls or arbitrary host-tool invocations. Native live-text proof comes from actual custom `message_end` RPC frames, not recording-API calls or session-history replay.

The inspected OMP 18.12.6 ACP implementation does not forward custom-message completion events as live text; its `notify` implementation is logging-only and widgets are unsupported there. Live ACP command-response support therefore remains blocked by the host's exposed transport surface. `session/load` replay may reopen historical evidence, but is not a substitute for a live command response. This adapter does not inject ACP protocol frames, spoof assistant messages or change the SDK. A thrown asynchronous-task publication/UI call emits only `{"error":"publication-failed"}` on stderr while receipt persistence and ownership cleanup complete; the void host messaging API exposes no asynchronous delivery acknowledgment.

The actual installed OMP 18.12.6 RPC run passed real success/nonzero execution, fresh-session reopening, unrelated-versus-covered freshness, changed-during-run unknown applicability, explicit cancellation with root/descendant reaping, private output/modes and immediate safe native text. It used the existing normal HOME/profile without credential or enforcement changes. A read-only preflight verified targeted, session-local containment of reviewed optional writers and the Tessera MCP connection before launch; no live-vault connection or write was used. Ordinary native presence/session/log/cache bookkeeping and possible catalog metadata traffic remain permitted. Local command outcomes reported `agentInvoked: false`; session counters and absence of assistant/tool messages are not a network-call meter. TUI rendering and live ACP command-response support remain unverified/unsupported respectively.

Repository, host, account and work-context isolate the evidence partition. A later actual session with the same partition can reopen receipts; changing only the session ID does not erase history. No raw output, configured command, private path, environment value, account label or exception text is rendered or attached as public metadata.

## Result semantics

The CLI prints JSON with execution ID, execution status, current applicability, proof boolean and output hash/byte/truncation metadata. It does not print configured commands, private paths, account labels, raw output or environment values. Files are `0600`; owned state directories are `0700`. Output remains under the private state root, not inside the project or installed package.

- `passed`/`failed` describe the observed configured command's exit, not all project quality. Missing launch, unavailable output, timeout or unproved cleanup are incomplete. Cancellation is persisted separately from failure.
- `current`/`stale`/`unknown` describe applicability. Covered content, additions/deletions, executable mode, configuration, selected keyed environment values and declared dataset identity participate; unrelated edits do not. Input changes across execution make applicability unknown. `show` and `list` make a new observation rather than replaying saved freshness.
- A successful proof requires a passed result, proved owned-group cleanup, current inputs and complete output when the gate requires it. Truncated required output is never a successful proof.
- `reconcile` recovers only committed reservations whose owner PID is demonstrably gone. They remain incomplete/unknown; recovered output has an exact captured-byte hash but unknown total-byte/truncation diagnostics (`null`), not invented completeness. Live or inaccessible owners are left alone. Corrupt finalized records fail rather than being rewritten.

`run` exits 0 for current successful proof, 1 for failed execution, 2 for incomplete/not proof, 130 for cancellation/SIGINT and 143 for SIGTERM. Read commands return 0 for a successful observation even when evidence is stale/unknown; inspect `proof` and `applicability`. Invalid arguments or unusable state return 2 with a sanitized error. Unknown schemas and configuration fields fail explicitly; configuration has no implicit gate defaults.

## Execution and trust boundary

The executable and argument vector are spawned without shell interpolation. The selected configured program is trusted code with the user's ordinary permissions; it can change files or access the network. This is not a sandbox or a source-of-approval mechanism. Never put credentials in persisted command arguments or configuration. Selected environment inputs are stored only as keyed fingerprints; the full inherited environment is not recorded.

On POSIX, the runner owns a process group, applies TERM followed by bounded KILL, drains bounded output and waits for the root to be reaped. `descendantsStopped` refers to absence of that owned group and reaping of its root. Use non-daemonizing verification programs whose descendants inherit that group. Deliberately escaped sessions/groups are not certified by this mechanism; Windows execution records incomplete instead of claiming supported cleanup. Interrupted-owner recovery does not claim that its descendants were stopped.

Fingerprints prove observations of declared inputs, not complete dependency coverage or tamper-proof attestation. Pre/post equality cannot detect a transient modify-and-revert. Private atomic publication prevents cooperative writers from clobbering records; this is not protection against a malicious process with the same OS account or arbitrary filesystem races. No implicit retries, background model calls, credential/enforcement changes or live-vault writes occur.

## Exercised verification

```bash
uv run python scripts/check_extensions.py --feature verification-receipts --stage core
uv run python scripts/check_extensions.py --feature verification-receipts --stage omp
```

The prior standalone prefix was exercised with strict TypeScript, ESLint and 28 behavior tests using actual temporary Git repositories, files and processes. Cases included real success/nonzero/missing launch, private output and inert metacharacters, bounded flooding, timeout, IPC-synchronized root/descendant cancellation and CLI SIGINT/SIGTERM, changed-during-run inputs, scoped freshness, publication boundaries, foreign-state preservation and dead-owner reconciliation. An additional actual standalone CLI journey exercised configured exits 0/7, reopened private receipts, unrelated-edit preservation and covered-edit staleness.

Strict TypeScript, ESLint and all 40 feature behavior tests passed for this slice. `tests/omp.test.ts` covers the real runner/store/snapshot through a recording native-API harness: asynchronous safe output, overlap, explicit cancel, lifecycle cancellation, independent factory ownership, reopened scoped freshness, unknown applicability, partition isolation, private-state rejection and publication failure. These tests are separate from actual-host evidence. The OMP prefix acceptance command also passed its actual detached OMP 18.12.6 RPC journey on macOS arm64 with Bun 1.3.14. Python report-boundary tests passed under Python 3.12; Ruff/format and strict driver typing passed. The broader strict Python invocation still reports existing errors in imported `validate_frontmatter.py` and `validate_evals.py`; it is not a repository-wide green claim.

The default full/native gate intentionally remains incomplete/nonzero. Only the OMP RPC prefix is proven; no TUI rendering or native CI provisioning claim is made by the local run. Claude integration and registered native packaging/activation remain undelivered. Optional scheduling, tracing/sandboxing, generic recovery frameworks and extra measurements remain deferred.
