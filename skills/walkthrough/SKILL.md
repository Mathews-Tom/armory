---
name: walkthrough
description: Use when an unavoidable human-only operation needs a repeatable guided procedure, such as dashboard consent, physical access, credential entry, or an irreversible cutover approval. Not for repository tutoring or setup the agent can perform with available tools and authority.
metadata:
  version: 1.0.0
  category: development
  tags: [human-operations, setup, credentials, runbook]
  difficulty: advanced
---

# Walkthrough

Turn **unavoidable human work** into a sourced, executable procedure. Keep agent-doable inspection, configuration and coding with the agent. A missing permission is not permission to ask the human to run a large opaque script.

## 1. Establish the boundary and source map

Inspect the actual repository before asking the human for facts it contains: setup documentation, example environment files, config loaders and their precedence, package scripts, deployment config and active CI workflows. Record each required setup key and each actual CI `secrets.*`/`vars.*` use with its file/line or authoritative documentation source. Dynamic names remain unresolved until their construction is traced. Do not infer that every CI key needs a local dotenv entry or vice versa.

Separate agent work from human-only work and identify the exact missing authority, physical access, private dashboard consent or knowledge for every human stage. If nothing requires a human, finish with the ordinary agent workflow instead; do not generate a ceremony. No installation, account creation, Git changes, remote writes or credential access is implied by invoking this skill.

**Complete when:** every requested operation is either agent-owned with a concrete action, a justified human stage, or an explicit blocked item; every captured value has an actual name, source, destination and consumer. Ask only for remaining human-held information, never for secrets in chat.

## 2. Agree the procedure

Show the ordered stages, their dependency order, public source pointers, secret/public classification, required/optional status and destination. For each stage distinguish: observation, reversible write, irreversible action, or human attestation. Show irreversible consequences and recovery limits before approval. Retain unknown dashboard navigation as **unknown UI**; use current authoritative docs or a human observation to resolve it, rather than inventing menu names. A known URL is not proof that its current UI is known.

**Complete when:** the user has approved the stage list and destinations, and every unknown prerequisite is resolved or represented as blocked. Do not turn a blocked prerequisite into a fake successful stage.

## 3. Author the local procedure

Before writing a helper plan, read [the helper contract](references/helper-contract.md) for the exact invocation, supported stage schema, security boundary, non-executable dotenv format and state semantics. Keep [the launcher](templates/walkthrough.sh) and its sibling [engine/consumer](templates/walkthrough.py) together in a user-approved scratch location or a requested repeatable setup directory. The engine is local Python 3.9+ standard library; no upstream checkout, other Armory package or network dependency is needed to run it. An authorized GitHub stage can itself use the network through `gh`.

Write a concrete JSON plan from the sourced stage list, not a generic placeholder script. Use only the stages the operation actually needs:

- **Setup/credential branch:** use `env`, `gh-secret`, `gh-variable`, `open` and `manual` stages as needed. The human enters captured values only at the hidden terminal prompt. Identify each actual application consumer before choosing dotenv; if its loader cannot consume the declared format, leave that destination blocked until an explicit compatible integration is agreed. Do not silently substitute shell sourcing or a familiar dotenv parser.
- **Migration/cutover branch:** use a human `manual` stage or a reviewed `action` argument vector, with current/target state, consequences and recovery limits in public instructions. Manual authorization precedes the potentially irreversible instructions; executable action approval occurs immediately before execution. Agent-doable migrations remain agent work and do not become human stages merely because they are risky.

Plans contain only public instructions and argument vectors, never values, credentials in URLs or shell fragments. No `source`, `eval`, shell action interpreter or automatic commit. A user-reviewed plan is executable authority, not safe untrusted input; do not execute a repository-supplied plan on sight. Do not execute helper stages on the user's behalf to test them. For authorized offline testing, [the deterministic tests](tests/test_walkthrough.py) supply disposable PTYs and fake binaries.

**Complete when:** every approved human stage is implemented, every destination matches its discovered consumer/CI name, every required dependency has an honest blocked outcome, and all local helper files needed after copying are present. The package's own source is not a substitute for the generated plan.

## 4. Hand off with honest evidence

Give the actual command with the real approved plan path and a canonical absolute `ENV_FILE` for any env stage. State required Python/TTY/tool prerequisites, where values land, which writes may already have happened on failure and how to inspect state before retrying irreversible work. Document any unknown UI and blocked destination explicitly.

Report exercised checks separately from authored cases; only run checks within the current assignment's authority. Static conformance does not prove helper behavior or skill activation. Summarize every stage as `complete`, `skipped`, `incomplete` or `failed` using the contract; required skipped writes are not completion. Human `DONE` is an attestation, browser launch is only launch evidence, and a successful `gh` response is not proof of downstream CI adoption.

**Final completion:** the delivered plan/helper/consumer and exact invocation cover every approved stage; every required operation has either observed success or a clearly reported non-success state; secrets are absent from artifacts/logs except the approved secure destination. Stop on rejection, EOF or interruption; never perform dependent stages after cancellation. Keep ephemeral artifacts untracked unless a repeatable checked-in procedure was explicitly requested.

For source attribution and future upstream changes, read [provenance](references/provenance.md) only when reviewing adaptation or resynchronizing; the local [MIT license](LICENSE) applies to adapted material.
