# New Package Checklist

Complete each phase for a new package. This is an authoring checklist, not a scored quality model. Static conformance and observed behavior are separate evidence; existing effectiveness roadmap requirements, including M4/M8 experimental gates, remain binding.

Authoring guidance is adapted from Matt Pocock's [writing-for-agents](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/writing-for-agents/SKILL.md) and [SKILL-MECHANICS.md](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/writing-for-agents/SKILL-MECHANICS.md) at `49dd158d1076134a641b33efb035946536778336`. Copyright (c) 2026 Matt Pocock; [MIT notice](skills/package-evaluator/LICENSE). For attribution review or manual upstream resync, consult the [adaptation provenance](skills/package-evaluator/references/upstream/provenance.md); Armory's metadata and evidence requirements remain authoritative here.

| Type | Directory | Definition File |
| --- | --- | --- |
| Skill | `skills/` | `SKILL.md` |
| Agent | `agents/` | `AGENT.md` |
| Rule | `rules/` | `RULE.md` |
| Command | `commands/` | `COMMAND.md` |
| Hook | `hooks/` | `HOOK.md` |
| Utility | `utilities/` | `UTILITY.md` |
| Preset | `presets/` | `PRESET.md` |
| Extension | `extensions/` | `EXTENSION.md` |

Native extensions follow every phase plus the extension-specific items in Phase 6 and Phase 7; their source layout and `extension` metadata block are defined in `CONTRIBUTING.md`.

## Phase 1: Scope and Invocation

- [ ] **Define scope** in one sentence and compare against the current `manifest.yaml`. Extend an existing package where appropriate; otherwise document the adjacent-package boundary.
- [ ] **Inventory every distinct invocation branch**: input/context, selection condition, required reference/configuration, output and completion evidence. Synonyms for one intent are not separate branches.
- [ ] **Identify invocation reach**: model discovery, explicit user invocation or both. Discover actual target adapter/harness support before choosing invocation flags or router behavior. Keep Armory's required description in all cases; another harness's mechanics are not portable defaults.
- [ ] **List prerequisites and authority**: binaries, libraries, services, required inputs and any operations needing user permission. Missing prerequisites must have an explicit blocked outcome, not an invented fallback.

## Phase 2: Structure and Metadata

- [ ] **Create directory** `{type-dir}/<package-name>/`: kebab-case, at most 64 characters, matching frontmatter `name` exactly.
- [ ] **Create the definition file** with YAML mapping frontmatter. Skill example:
  ```yaml
  ---
  name: example-package
  description: Use when reviewing a package's invocation branches and observable completion contract.
  metadata:
    version: 1.0.0
    category: review
    tags: [quality, invocation, authoring]
    difficulty: intermediate
    phase: review
  ---
  ```
- [ ] **Preserve required metadata**: exact `metadata.version` in `X.Y.Z` format, `category`, `tags` and `difficulty`; `phase` is optional. Use `CONTRIBUTING.md` and current type validators for valid values.
- [ ] **Include type-required fields** from `scripts/package_types.py` and the additional type validation in `scripts/validate_frontmatter.py`. For example, agents require `model`/`color`, hooks require a `hook` mapping, commands a `command` mapping, utilities a `utility` mapping and presets a `preset` mapping. Do not assume a skill's fields are sufficient for another type.
- [ ] **Add only needed local support files** (`references/`, `scripts/`, `templates/`, `assets/`). Include their actual content, not placeholders. Mark runnable helpers executable where needed; do not mark data-only templates executable.
- [ ] **Create `evals/cases.yaml`** within the package.

## Phase 3: Observable Content

- [ ] **State purpose and boundary**: when to use this package versus adjacent alternatives.
- [ ] **Keep common instructions inline**: prerequisite/authority handling, shared workflow and evidence rules that every branch needs.
- [ ] **Separate conditional branches**: each has an explicit selection condition, required inputs, actions, output and failure/blocked path. Do not force every invocation through unrelated setup or references.
- [ ] **Make completion checkable and exhaustive**: every workflow step ends on an artifact or observed state; the final criterion covers every promised output and applicable input. Replace “understand the setup” with evidence such as “identify each active config source and the loader/precedence selecting it.” A summary alone is not proof that every required item was handled.
- [ ] **Write conditional reference pointers** naming when to load each local reference and what it supplies. Example: “For CLI export, read `references/cli-export.md` before selecting flags; it defines export and error evidence.” This is illustrative: provide real package-local files for the branches actually supported.
- [ ] **Discover configuration from the environment**: inspect project scripts, config/loader files, installed tool help or implementation before selecting commands/keys. Record the source and precedence of chosen values; document unwritten conventions and gotchas rather than caching mutable facts.
- [ ] **Specify branch evidence**. For a CLI branch, identify the sourced invocation, output artifact and observed result. For a config-only branch, identify active config/key/loader and resulting artifact or configuration effect. If a tool/config prerequisite is missing, name it and complete independent branches without claiming execution.
- [ ] **Provide applicable examples, troubleshooting and limitations** alongside the branch they concern. Add rationalizations/red flags only where they address concrete execution risks; section count is not a quality measure.
- [ ] **Index support files with loading conditions**. Ensure each required reference is reachable without reading every reference just to select a branch. Keep one authoritative source for each rule.

## Phase 4: Eval Coverage

- [ ] **Include 2+ positive cases**, covering every distinct supported invocation branch, including type-specific operations where applicable.
- [ ] **Include 2+ adjacent negatives**: plausible requests that this package should not handle.
- [ ] **Give each case** a unique snake_case `id`, natural-language `prompt`, `fixtures: []` when none are supplied, nonempty `rubric` and boolean `trigger_expected`.
- [ ] **Demand observable behavior in rubrics**: the selected branch, required artifact/evidence, exhaustive input coverage and explicit missing-prerequisite outcome. Include conditional-reference and differing CLI/config-environment adversarial cases when applicable.
- [ ] **Avoid proxy judgments**: phrase/character counts, shorter source and word/format matches do not establish routing or task success. Authored cases and schema-valid files are not passing executions.

## Phase 5: Description Contract

- [ ] **Respect static format policy**: 50–1024 characters under the current validator, no angle brackets or pushy trigger language. Length is a format constraint, not an efficacy target.
- [ ] **Lead with invocation context** using “Use when...” or equivalent; include each distinct task branch and the boundary with nearby packages.
- [ ] **Keep workflow in the body** and use domain terms only where they distinguish the task. No synonym-family quotas or keyword-density targets.
- [ ] **Check description/body agreement**: every promised branch has an observable completion contract and eval coverage. Actual routing remains unmeasured until separately exercised.

## Phase 6: Validation and Evidence

Run checks only within the assignment's authority. Record actual commands, outcomes and unresolved prerequisites; never mark an unrun item complete.

- [ ] **Regenerate manifest**: `uv run python scripts/generate_manifest.py`.
- [ ] **Sync registered shared templates**, if used: `uv run python scripts/sync_templates.py`.
- [ ] **Validate frontmatter**: `uv run python scripts/validate_frontmatter.py`. This covers policies not all enforced by the static evaluator, including description limits and required version/type details.
- [ ] **Validate local references**: `uv run python scripts/validate_references.py`.
- [ ] **Validate eval schema**: `uv run python scripts/validate_evals.py`. This checks case structure, not agent behavior.
- [ ] **Run static package conformance**: `uv run python scripts/evaluate_package.py --path <package-directory> --json`. Expect a JSON list of report-v2 records with `static_conformance.status: PASS|FAIL` and `live_effectiveness.status: NOT_MEASURED`. Top-level `status`/`findings` mirror static conformance. Exit 1 means static failure or invalid requested path; a valid passing report exits 0.
- [ ] **Perform authored review** with package-evaluator: inspect every invocation branch, completion criterion, pointer/config source and type-specific requirement. Keep authored findings separate from machine report fields; repair applicable blocking findings.
- [ ] **Exercise authorized behavior**: capture invocation/case identity, environment, observed output/artifact and result for every exercised branch; label all unexercised branches. Normal `scripts/run_evals.py` launches live model sessions and needs authorization. Its dry-run skips execution and is structure-only evidence, even if its summary prints PASS.
- [ ] **Extensions only — run native gates**: `bun install --cwd extensions --frozen-lockfile`, then `bun run --cwd extensions typecheck`, `lint` and `test`, `uv run python scripts/build_extensions.py --feature <name> --output-dir <dist-root>` and `uv run python scripts/check_extensions.py --feature <name>`. Record the JSON report; static, test-kit and lifecycle passes are not native compatibility. Record `--native-smoke` results separately and keep `extension.tested` limited to host versions and surfaces actually exercised.
- [ ] **Extensions only — land complete**: an implementation prefix without `EXTENSION.md` reports its stage with `--stage core|omp` and `feature_complete=false`. Add `EXTENSION.md`, both host adapters, `CHANGELOG.md`, evals, the manifest entry and the excluded classification in `evals/skillsbench/package_strata.yaml` together in the final package-bearing PR.
- [ ] **Preserve evidence limits**: the static evaluator does not inspect references, execute helpers or measure activation/task outcomes. There is no weighted score or percentage acceptance gate; do not relabel static PASS as measured effectiveness or treat this checklist as clearing the effectiveness roadmap.

## Phase 7: Integration

- [ ] **Update README catalog and derived counts** according to current repository conventions.
- [ ] **Keep the package standalone**: local reference/helper paths resolve inside its directory; use registered template synchronization for shared content rather than cross-package filesystem paths.
- [ ] **Exclude secrets and private/internal URLs** from distributable content.
- [ ] **Extensions only — keep installation explicit**: never add an extension to `profiles.yaml`, a preset, `.claude-plugin/plugin.json` or default install paths; document the per-host `--type extension` lifecycle and session-local `--plugin-dir` trial in the package body.
- [ ] **Complete applicable version/changelog, license and provenance integration** under repository conventions.

## Phase 8: PR Submission (Only When Authorized)

- [ ] **Create the feature branch and logical commits** under the authorized shipping workflow.
- [ ] **Attach actual static conformance output**, separate authored findings and branch-level behavioral evidence/limits to the PR; no quality scorecard.
- [ ] **Confirm applicable CI gates** with actual results, distinguishing schema/static validation from behavioral execution.

## Common Mistakes

| Mistake | Consequence | Correction |
| --- | --- | --- |
| Static PASS presented as effective routing | Unmeasured behavior is reported as success | Keep report-v2 live effectiveness NOT_MEASURED and attach separately exercised evidence |
| Many synonymous prompts but an omitted invocation branch | Coverage misses a supported path | Map each branch to a case and observable output |
| Reference list has filenames without loading conditions | Agent cannot select required material from the entrypoint | State the condition and purpose at each pointer |
| Example flags/config keys copied from a different environment | Selected invocation may not exist here | Discover installed help/config loader and record the source |
| Missing tool treated as completed execution | Artifact/result has no evidence | Name the missing prerequisite and affected branch |
| Broken or cross-package file reference | Standalone distribution cannot supply the target | Supply local content or registered synced copies and validate references |
| Description-body mismatch | Invocation promise lacks an implementation contract | Align the branch, completion evidence and cases |
