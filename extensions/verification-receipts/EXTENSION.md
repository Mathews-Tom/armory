---
name: verification-receipts
description: Execute explicitly configured local verification gates and reopen private, scoped evidence with current input freshness in OMP and Claude Code.
metadata:
  version: 1.0.0
extension:
  schema_version: 1
  runtime: bun
  core:
    version: 1.0.0
  hosts:
    omp:
      entry: omp/index.ts
    claude:
      entry: claude-code/register.ts
  commands:
    - armory-verify
    - armory-evidence
  helpers:
    - helpers/claude-cli.ts
  storage: user-private
  permissions:
    - fs.read
    - fs.write
    - process.spawn
  tested:
    omp:
      - version: 18.12.6
        surfaces:
          - rpc-macos-arm64
    claude:
      - version: 2.1.309
        surfaces:
          - interactive-macos-arm64
---

# Verification Receipts

Run an explicitly configured local check and retain its exact result, private bounded output and declared-input fingerprint. Reopening evidence makes a new freshness observation instead of treating an old successful exit as current verification. This optional executable extension does not intercept arbitrary shell commands, confer mutation authority or require a model turn.

## Commands

- `/armory-verify <gate-id>` starts one gate from the selected project configuration. An unknown ID or overlapping request does not spawn another command.
- `/armory-evidence` reopens durable receipts and recomputes applicability. Execution status, applicability and successful proof are separate fields.
- `/armory-evidence wait` waits for this session's owned execution and then reopens evidence.
- `/armory-evidence cancel` requests owned cancellation. OMP awaits its runner; Claude preserves the host stream's conservative `cancellation-unconfirmed` boundary. Inspect the durable cancelled/incomplete receipt and cleanup evidence rather than treating stream settlement as proof that descendants stopped.

## Configuration and installation

Require the pinned Bun toolchain, Git and a POSIX environment. Select an explicit Git worktree, worktree-relative configuration, external private data root, account label and work context. OMP receives the five `--armory-receipts-*` flags; Claude receives `ARMORY_RECEIPTS_REPO`, `ARMORY_RECEIPTS_CONFIG`, `ARMORY_RECEIPTS_DATA_ROOT`, `ARMORY_RECEIPTS_ACCOUNT` and `ARMORY_RECEIPTS_WORK_CONTEXT`. Native session identity comes from the selected host API, not from an imported approval or credential.

A configured gate declares its executable/argument vector, relative cwd, time/output bounds and covered paths/configuration/environment/dataset identity. There is no shell interpolation or implicit command configuration. Account/work-context strings partition evidence; they are not authentication attestations. See [README.md](README.md) for a complete configuration and host-specific invocation/lifecycle commands.

Install, update, disable and remove only through explicit host-aware extension selection. Profiles, presets, "all" and the legacy all-in-one plugin never enable this extension. Lifecycle operations refuse changed or unknown payload files and preserve foreign packages/configuration and private evidence outside the payload.

## Evidence, privacy and trust

Saved output and receipts are private; native text exposes only execution identity, status, applicability, proof and output hash/size/truncation metadata. Configured commands, private paths, raw output, account labels and environment values are not rendered. Selected environment inputs are keyed fingerprints, not plaintext values.

Covered modification/addition/deletion/configuration drift makes historical success stale; unrelated edits do not. Mutation during execution is unknown, never fresh. Supported-schema records from another feature/core version remain readable with the exact original result/output but unknown applicability and no current proof. Reverification establishes a new result; it never overwrites history.

Configured programs retain the user's ordinary operating-system permissions and may have side effects. This is not a sandbox or an approval grant. POSIX cleanup covers the owned process group and reaped root, not deliberately escaped daemons. Unknown schemas, unsafe storage, missing prerequisites and unproved completion/cleanup fail explicitly rather than manufacturing success. Do not store credentials in gate arguments or configuration.

## Exercised compatibility

The metadata records exact native versions/surfaces exercised on macOS arm64, not minimum-version or all-platform claims. Actual detached artifacts exercised success/nonzero execution, fresh-host reopening, scoped freshness, mutation during execution, cancellation with root/descendant/group absence, private output hashes/modes and safe native text. OMP TUI and ACP live responses are not certified. Windows execution and native Linux compatibility are not advertised.

Credential-free CI covers deterministic behavior, pinned SDK/adapter contracts, offline Claude validation/test kits, reproducible contained builds, package/catalog checks and owned lifecycle operations. Claude 2.1.308 strict static validation/test-kit results are offline evidence, not native 2.1.308 compatibility. Explicit local/manual native qualification preserves normal HOME/default authentication and user/managed enforcement, requires reviewed containment of optional writers, and stops on genuine trust/policy/login requirements. CI success is not native qualification.
