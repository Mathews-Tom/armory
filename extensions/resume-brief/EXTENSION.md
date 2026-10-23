---
name: resume-brief
description: Record and reopen a freshness-checked resume card for an explicitly selected project in OMP and Claude Code, reporting source-linked branch, plan, blocker, session and approval discrepancies without executing or authorizing anything.
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
    - armory-brief
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
          - headless-macos-arm64
---

# Resume Brief

Re-enter one explicitly selected Git worktree with a card that separates what was recorded from what is observed now. Package and shared core versions are 1.0.0. The card shows the objective and plan revision, the referenced last verification, branch/worktree/declared pull request, blockers and the next action, native session facts and every recorded approval as a non-executable hold. Reopening re-reads the same selection and lists each changed fact with the source it came from and both content hashes. Source observation is read-only; recording writes only the private derived cache. It runs no configured verification, executes no next action, resumes nothing and grants no permission.

## Command

`/armory-brief <record | reopen [id] | show [id] | list | help> [--json]`

- `record` observes the selected repository and sources once and stores a private derived snapshot.
- `reopen` (default latest) re-reads exactly the recorded selection and reports discrepancies. It is refused when the configured selection differs from the recorded one, before any source is read.
- `show` (default latest) prints a recorded card without reading sources; approval expiry is evaluated now.
- `list` lists snapshots for the selected repository.
- `--json` prints the same validated answer as ASCII-escaped JSON. Text output escapes every repository-, file- and session-derived value.

## Selection and identity

Selection is explicit; nothing is discovered or scanned. OMP takes `--armory-brief-repo`, `--armory-brief-data-root`, `--armory-brief-account`, `--armory-brief-context` and optional `--armory-brief-omp-session`, `--armory-brief-omp-handoff` and `--armory-brief-receipt`. Claude Code reads the matching `ARMORY_BRIEF_*` environment values. The current session identity always comes from the host API. Account labels are opaque references used to judge approval origin, not authentication.

OMP sessions and handoffs are read only from explicitly selected JSONL/handoff files with allowlisted header, entry-count and feature-owned approval fields. Claude Code sessions are observed through `$.session` at invocation time and reduced to identity, locations, turn count, start time and counts over the newest 4096 transcript rows; message text, tool input and tool results are never read into the projection. A full 4096-row window is reported as incomplete, and denied or malformed host answers remain unknown.

## Privacy, authority and failure

Snapshots are 0600 files in owned 0700 directories under an explicit data root outside the repository and the installed payload. They hold hashes, references and bounded allowlisted facts, never plan, handoff, receipt or transcript bodies, and they are a derived cache rather than an authoritative plan, memory or receipt store. Missing, unreadable, linked, special, oversize, malformed, unsupported or changed-while-read sources yield unknown facts, never defaults. Approvals keep their own expiry; a fresh read cannot renew them and approvals from another or unknown host, account or session are marked foreign.

See [README.md](README.md) for configuration, host commands, lifecycle and qualification. Install, update, disable and remove only through explicit host-aware extension selection; profiles, presets, "all" and the all-in-one plugin never enable it. Lifecycle operations never touch snapshots, project files, handoffs or receipts.

## Compatibility

Actual detached artifacts exercised OMP 18.12.6 RPC and Claude Code 2.1.309 interactive and whole-command headless text on macOS arm64. Qualification covered durable record/reopen, exact branch/plan/blocker discrepancies, missing/rejected sources, expired/foreign non-executable approvals and private escaped output. Claude uses a disposable development-loader copy; normal installed-loader, SDK, OMP TUI/ACP, other versions/platforms and injected in-flight cancellation are not certified. Headless Claude prefixes the command result with `resume-brief: `; `--json` selects the validated JSON payload after that host-owned prefix.

Credential-free CI covers deterministic behavior, pinned SDK/adapter contracts, offline Claude validation and test kits, reproducible contained builds, package/catalog checks and owned lifecycle operations; none is a native compatibility claim. Explicit local/manual qualification preserves normal HOME/default authentication and user/managed enforcement, contains reviewed optional writers and stops on genuine trust/policy/login requirements.
