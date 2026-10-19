# Provenance

- Source repository: <https://github.com/mattpocock/skills>
- Exact source pin: `49dd158d1076134a641b33efb035946536778336`.
- Adapted source: [engineering/wizard/SKILL.md](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/engineering/wizard/SKILL.md) and [engineering/wizard/template.sh](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/engineering/wizard/template.sh).
- License: MIT, copyright (c) 2026 Matt Pocock; retained in package-local `LICENSE`.

## Adapted ideas

Retain the unavoidable-human-only boundary, repository-first discovery of real setup and CI names, ordered stage map, precise/explicitly unknown dashboard journey, hidden secret capture, idempotent destination updates, pre-action confirmation and honest handoff. `walkthrough` is the deliberately retained Armory name; this is a selective adaptation, not a second generic onboarding skill or a verbatim vendoring of upstream code.

The upstream shell helper is evidence for the procedure pattern, not a safe runtime dependency. The local Bash 3.2 launcher and Python standard-library engine replace its implementation: controlling-terminal-only hidden input, validated public JSON plans, strict keys/canonical trusted paths, no symlink or nonregular destination writes, secure atomic same-directory replacement, explicit non-executable JSON-string dotenv consumer, suppressed subprocess diagnostics, and terminal cancellation with nonzero incomplete/failed states. All runtime files stay inside this package; no upstream checkout or cross-package import is required.

## Deliberate omissions and changes

- Do not retain upstream symlink-following writes, same-mode preservation of insecure files, generic temporary file followed by in-place truncation, shell-quoting-as-dotenv or permissive existing-value decoding.
- Do not retain upstream warning-as-success for missing/failed GitHub writes, swallowed EOF, secret-bearing diagnostics or a blanket completion message after skipped required work.
- Do not retain the immutable-library rule: security fixes belong in the owned local engine, not copies frozen to an unsafe upstream implementation.
- Omit screen clearing/color and implicit previous-secret reuse; observable progress and explicit capture take precedence over cosmetic parity.
- Replace stage functions embedded in executable shell with an explicit reviewed JSON plan and a local standard-library engine/consumer. This adds a declared Python 3.9+ prerequisite rather than relying on incompatible GNU/BSD shell utilities for secure filesystem operations.
- Browser launch is not evidence of known UI or completed authorization. Unknown dashboard steps stay unknown. The helper has no real account/service/key defaults.
- No automatic chmod/commit/install, real account setup, GitHub settings change, hosted call or human secret is needed to author/test this package. Ordinary agent work remains agent work.

## Manual resynchronization only

Never auto-sync upstream. A future maintainer must select a new exact pin, compare **both** source files and licensing against this recorded pin, classify each delta against local security/behavior contracts, and intentionally port only appropriate changes. Preserve this history, update attribution when relevant, and exercise local disposable PTY/stub tests under separate execution authority. Neither shorter source nor static conformance proves the new helper safe or the skill effective. Authored eval cases and deterministic tests carry no passing-run claim by themselves.
