---
name: run-preflight
description: Check explicitly declared OMP managed-run prerequisites in OMP and Claude Code, retain unknown quota, refuse stale or unsupported admission at the owned dispatch boundary, and optionally exercise one bounded local sentinel without a provider call.
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
    - armory-preflight
  helpers:
    - helpers/cli.ts
  storage: none
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
      - version: 2.1.310
        surfaces:
          - interactive-macos-arm64
          - headless-macos-arm64
---

# Run Preflight

Check one explicitly declared OMP SkillsBench invocation without querying a provider, inferring quota from a signed-in profile or launching a paid campaign. Package and shared core versions are 1.0.0. Native output separates ready, blocked and unknown prerequisites from actual consumed admission. The project-local version-1 adapter consumes a complete current record immediately before its existing managed runner; a native check alone does not launch or authorize that runner.

## Commands

```text
/armory-preflight check {"config":"/absolute/project.json","declaration":"/absolute/declaration.json"} [--json]
/armory-preflight probe {"config":"/absolute/project.json","declaration":"/absolute/declaration.json"} [--json]
/armory-preflight help
```

Select exactly two canonical absolute JSON paths. JSON strings preserve spaces; arguments are never interpreted by a shell. The selected project config must name this installed package root and its own `helpers/cli.js`. There is no cwd-based project discovery, Armory-checkout fallback, account selection or native `admit` command. Help does not read selected project data.

1. Use `check` to observe the declared config, source/data/identity bindings, checkpoint, quota timestamp, caps and explicit authorization. Missing, changed, expired or unsupported prerequisites refuse readiness. Unknown quota remains unknown, with its observation and expiry times; it is not capacity.
2. Inspect the projected text or JSON. It exposes declared nonsecret provider/profile/run/cell observations when available, not credentials, the account fingerprint, complete declaration/admission record, bridge argv, file identities or raw child output. Declared identity is a local attestation, not an authentication probe.
3. Use `probe` only for an explicitly bounded `synthetic-local-sentinel` declaration. The trusted configured project bridge reaches the actual dispatch boundary and runs one genuine Python `pass` child. It reports `terminal-receipt-unavailable` and zero provider calls, never a model receipt or completed benchmark result. Synthetic declarations do not inherit the native host account's authority.

## Admission and limits

The project adapter binds the canonical cell/invocation and complete consumed-input inventory. It reobserves files and directories immediately before dispatch; source/config/data/account/cell/cap/checkpoint changes or expired evidence refuse an earlier record. Required unsupported call, worker, concurrency, token or currency limits block. The existing runner owns its 600-second maximum and 630-second outer timeout; advisory caps remain caller discipline. There is no shared counter, dollar enforcement, signed or single-use authority, sandbox, protection of arbitrary bypasses, or transfer of existing live-study approval.

Each native command owns its bounded helper process. Replacement, cancellation and session changes revoke publication and await owned cleanup. Failed or unconfirmed cleanup prevents later readiness results rather than silently continuing. Command collisions fail instead of shadowing another registration. Source-controlled strings are inert data, not instructions. Neither host makes an automatic model call, starts a daemon or writes a feature store; an explicit synthetic probe uses only disposable project/checkpoint/temporary process data.

## Errors and lifecycle

Invalid selection, malformed helper protocol, failed or signalled execution and unavailable sessions produce explicit failures without readiness. A validated blocked report remains blocked even when the helper's documented malformed-prerequisite exit is 2. Cancellation and context changes cannot publish stale results into a new invocation. A successful command or zero exit is not permission to launch a study.

Install, update, disable and remove only Armory-owned native package paths through the existing lifecycle route. Foreign configuration and data must survive. Project declarations and selected input data remain project-owned; removing the extension does not grant deletion authority over them. Reverting the project adapter together with the package removes this managed-admission integration; do not bypass it with a boolean-only record or compatibility shim.

## Qualification

The compatibility entries are gated by detached-artifact command qualification with normal HOME/default authentication, genuine user/managed enforcement and disposable selected data. The native gate must prove real process/refusal/freshness/race/cancellation/reopening/privacy/text behavior on each advertised surface before this package is published. Unsupported headless behavior must be reported explicitly, never relabeled success. Missing tools, trust or supported controls fail closed.

Credential-free CI covers deterministic behavior, pinned adapter/test-kit contracts, offline validation, reproducible contained builds and owned lifecycle consumers. It does not initialize authenticated host sessions or certify native compatibility. See [README.md](README.md) for configuration, project-local integration, the harmless local walkthrough, exact validation commands and scope limitations.
