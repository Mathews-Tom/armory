# AGENTS.md

## Code Review Rules

- Failure means package instructions in `skills/*/SKILL.md`, `agents/*/AGENT.md`, or `commands/*/COMMAND.md` contradict their bundled scripts/references and make the documented workflow fail or take an unauthorized action.
- Failure means a package description routes a concrete request to the wrong package or excludes an intended invocation; demonstrate the conflicting trigger and workflow rather than guessing from a name.
- Failure means `scripts/generate_manifest.py`, `scripts/generate_adapters.py`, or `scripts/build_router_index.py` drops or misrepresents package metadata, required supporting files, or history-derived routing evidence; identify the affected package/host/request.
- Respect CI coverage: `package.yml` checks manifest drift and regenerates/validates adapters, but does not compare committed adapters for drift; `router-index.yml` rebuilds on main/schedule/manual dispatch, not as a PR synchronization gate. Report semantic generator defects or demonstrated adapter drift at their source, not duplicate manifest/frontmatter/reference/eval-schema gate errors.
- Do not report style, formatting, naming nits, or diagnostics already enforced by Ruff, `mypy --strict`, ESLint, or `tsc` within their configured scopes in `.github/workflows/tests.yml` and `extensions/package.json`; speculative hardening is not a finding.
- Review PR-introduced failures only. Tag unchanged-code issues `Pre-existing` without requesting a fix; do not repeat findings already raised on an earlier commit of the same PR unless the attempted fix introduces a distinct failure.
- Paths to skip for line-by-line review: generated `manifest.yaml`, `adapters/**`, `uv.lock`, and `extensions/bun.lock`; review canonical package definitions, generator logic, and dependency declarations instead. Generated-output comparisons may support a source-level finding.
- Every finding must name `file:line`, the concrete failing scenario and consequence, and the bug class so the author can fix every instance; tag it `Important`, `Nit`, or `Pre-existing`. A suggestive identifier alone is not evidence.
- Start the summary with the count of `Important` findings; when there are no actionable findings, say plainly: "Nothing to fix."
- Keep completion criteria, templates, and eval rubrics conditional on the selected workflow branch: stop, rejection, zero-candidate, and small/no-plan paths must not require artifacts or continuation that their own instructions forbid.
