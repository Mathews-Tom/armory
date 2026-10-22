# Verification Receipts — standalone CLI

Runnable development-prefix delivery. Executes an explicitly configured verification command, privately persists its exact result and bounded output, and recomputes freshness against the declared inputs when evidence is reopened. This is not an OMP extension or Claude Code mod. No native package definition, catalog entry or native compatibility is shipped here.

## Requirements and invocation

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

Fingerprints prove observations of declared inputs, not complete dependency coverage or tamper-proof attestation. Pre/post equality cannot detect a transient modify-and-revert. Private atomic publication prevents cooperative writers from clobbering records; this is not protection against a malicious process with the same OS account or arbitrary filesystem races. No implicit retries, background model calls, credential/enforcement changes, live-vault writes or native-host loading occur in this slice.

## Exercised verification

```bash
uv run python scripts/check_extensions.py --feature verification-receipts --stage core
```

The core gate runs strict TypeScript, ESLint and 28 behavior tests using actual temporary Git repositories, files and processes. Cases include real success/nonzero/missing launch, private output and inert metacharacters, bounded flooding, timeout, IPC-synchronized root/descendant cancellation and CLI SIGINT/SIGTERM, changed-during-run inputs, scoped freshness, publication boundaries, foreign-state preservation and dead-owner reconciliation. An additional actual standalone CLI journey exercised configured exits 0/7, reopened private receipts, unrelated-edit preservation and covered-edit staleness.

The default full/native gate intentionally remains incomplete/nonzero. OMP integration, Claude integration, detached native packaging/activation and native compatibility are not delivered or advertised. Optional scheduling, tracing/sandboxing, generic recovery frameworks and extra measurements are deferred; later-host blockers do not hold this standalone delivery.
