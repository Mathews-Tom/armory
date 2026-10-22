# Contributing

Authoring guidance on context pointers, invocation branches, completion criteria and environment discovery is adapted from Matt Pocock's [writing-for-agents](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/writing-for-agents/SKILL.md) and [SKILL-MECHANICS.md](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/productivity/writing-for-agents/SKILL-MECHANICS.md), pinned at `49dd158d1076134a641b33efb035946536778336`. Copyright (c) 2026 Matt Pocock; MIT notice: [package-evaluator/LICENSE](skills/package-evaluator/LICENSE). For attribution review or deliberate upstream resync, read the [adaptation provenance](skills/package-evaluator/references/upstream/provenance.md). Armory's metadata, report-v2 evidence boundaries and harness compatibility rules remain local adaptations.

## Package Types

Armory supports eight package types. Each lives in its own top-level directory with a definition file:

| Type    | Directory    | Definition File | Description                                |
| ------- | ------------ | --------------- | ------------------------------------------ |
| Skill   | `skills/`    | `SKILL.md`      | Prompt-driven workflow for a task domain   |
| Agent   | `agents/`    | `AGENT.md`      | Autonomous multi-step agent with tools     |
| Rule    | `rules/`     | `RULE.md`       | Always-on behavioral constraint            |
| Command | `commands/`  | `COMMAND.md`    | Slash-command triggered workflow           |
| Hook    | `hooks/`     | `HOOK.md`       | Event-driven automation (pre/post actions) |
| Utility | `utilities/` | `UTILITY.md`    | Standalone tool or report generator        |
| Preset  | `presets/`   | `PRESET.md`     | Curated bundle of packages across types    |
| Extension | `extensions/` | `EXTENSION.md` | Optional native OMP / Claude Code runtime module, installed only explicitly per host |

## Package Structure

Each package lives in its own directory under the appropriate type directory and must contain its definition file.

Definition frontmatter must be a YAML mapping; empty, scalar, and list-valued frontmatter are rejected. Package versions use exactly `X.Y.Z` with no surrounding whitespace or trailing newline. Shared parsing raises a validation error instead of returning non-mapping YAML values to callers.

### Skill (`SKILL.md`)

```yaml
---
name: my-skill-name
description: Use when a request falls within this skill's task domain.
metadata:
  version: 1.0.0
  category: development
  tags: [keyword1, keyword2, keyword3]
  difficulty: intermediate
---
```

### Agent (`AGENT.md`)

```yaml
---
name: my-agent-name
description: Use when an autonomous agent must carry out this task domain's multi-step investigation.
type: agent
model: sonnet
color: blue
metadata:
  version: 1.0.0
  category: development
  tags: [investigation, automation, workflow]
  difficulty: intermediate
---
```

### Rule (`RULE.md`)

```yaml
---
name: my-rule-name
description: Use when reviewing or applying this rule's concrete constraints within its declared scope.
type: rule
metadata:
  version: 1.0.0
  category: development
  tags: [constraints, standards, review]
  difficulty: intermediate
---
```

### Command (`COMMAND.md`)

```yaml
---
name: my-command-name
description: Use when explicitly invoking this command's documented operation with its supported arguments.
type: command
command:
  syntax: /my-command-name
  handler: inline
metadata:
  version: 1.0.0
  category: development
  tags: [command, automation, workflow]
  difficulty: intermediate
---
```

### Hook (`HOOK.md`)

```yaml
---
name: my-hook-name
description: Use when configuring this event-driven hook and its documented handler input and output contract.
type: hook
hook:
  events: [PreToolUse]
  handler:
    type: command
    command: ./handler.sh
metadata:
  version: 1.0.0
  category: operations
  tags: [hook, events, automation]
  difficulty: intermediate
---
```

### Utility (`UTILITY.md`)

```yaml
---
name: my-utility-name
description: Use when invoking this standalone utility to produce its documented output from supported inputs.
type: utility
utility:
  runtime: python
metadata:
  version: 1.0.0
  category: development
  tags: [utility, automation, output]
  difficulty: intermediate
---
```

### Preset (`PRESET.md`)

```yaml
---
name: my-preset-name
description: Use when selecting this package bundle for its documented combined workflow and supported targets.
type: preset
preset:
  packages:
    - skills/some-skill
    - rules/some-rule
    - hooks/some-hook
metadata:
  version: 1.0.0
  category: operations
  tags: [preset, bundle, workflow]
  difficulty: intermediate
---
```

### Extension (`EXTENSION.md`)

Native extensions are executable host modules, not prompt files. Each feature owns one directory under the Bun workspace in `extensions/` (Python stays on uv):

```text
extensions/<feature>/
  EXTENSION.md        # definition; its presence registers the feature
  CHANGELOG.md
  core/               # pure TypeScript rules: no Bun/Node/host imports, timers, fs, network or clock
  omp/                # OMP adapter; factory entry declared under hosts.omp
  claude-code/        # Claude Code mod; register(on, options) entry declared under hosts.claude
  claude-code/mod-checks/*.test.ts   # `claude plugin test` cases (claude-code/testing)
  helpers/*.ts        # optional CLI helpers, bundled to helpers/<name>.js with Bun
  runner/*.ts         # optional real-process helper entries; also bundled to helpers/<name>.js
  tests/*.test.ts     # bun test cases
  evals/cases.yaml
```

```yaml
---
name: my-extension
description: Use when ... (what the native commands do, on which hosts).
metadata:
  version: 1.0.0
  category: workflow
  tags: [native, extension, workflow]
  difficulty: intermediate
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
  commands: [armory-my-command]       # literal names, armory- prefix, no shadowing
  helpers: [helpers/my-helper.ts]     # optional
  storage: none                       # none | user-private (needs fs.write)
  permissions: [process.spawn]        # fs.read | fs.write | process.spawn | network
  tested:                             # optional: only versions/surfaces actually exercised
    omp:
      - version: "<exact observed version>"
        surfaces: [terminal-interactive]
---
```

Unknown keys are refused, including any minimum-host-version claim; `tested` records exact exercised versions and surfaces, never a compatibility floor.

Helper entrypoints must be `.ts` files directly under `helpers/` or `runner/`, with unique filename stems. Their static dependency graph may use `core/`, `helpers/` and `runner/` only; every included file is checked before Bun receives immutable snapshots. Claude modules may statically import only `hooks/` modules and the pure `core/`; executable helpers must run through explicit host process effects. Import syntax is parsed with the pinned TypeScript compiler rather than matched with line-oriented regular expressions. Generated-output ancestors must remain real directories, and a rebuild refuses modified or foreign artifact files rather than deleting them. Publishing both host artifacts retains the previous pair for rollback; this is not a crash-atomic multi-directory filesystem transaction. A failed restoration preserves its recovery trees and reports their location; an unexpected occupied destination, including an empty directory, is retained rather than overwritten during rollback.

Claude permission checks follow the registered hook callback's API binding rather than its spelling. Local aliases, object destructuring and static dot/optional access are resolved with lexical shadowing. Computed API access, API escapes into other functions or nested closures, unresolved callback registration and mutation of tracked API/callback bindings are refused. Keep callback references local and statically resolvable. This is bounded static auditing of trusted code, not a sandbox or native-host compatibility proof.


- **Build:** `uv run python scripts/build_extensions.py --feature <name> --output-dir <path>` writes `<path>/extensions/<name>/omp/` (`package.json` with `omp.extensions`) and `<path>/extensions/<name>/claude/` (`.claude-plugin/plugin.json`, `hooks/hooks.json`, static relative modules). Each artifact carries its adapter, the exact core, bundled helpers, `LICENSE` and an `armory-extension.json` content manifest with feature/core/schema identity, entrypoints, commands, storage, permissions and file digests. Symlinks, special files, hidden files, secret/data-shaped files, test-only files, bare imports outside host type packages, dynamic imports and Claude `$` effects without a declared permission fail the build. Identical sources build to identical bytes in any output root; output inside canonical source is refused.
- **Check:** `uv run python scripts/check_extensions.py --feature <name>` runs definition, toolchain, typecheck, lint, unit tests, reproducible builds, the OMP factory probe, `claude plugin validate --strict --json`, `claude plugin test` and a disposable-root lifecycle round trip. Absent tools or zero executed cases fail. `--native-smoke` adds real-host proof and stays incomplete (exit 3) until a real-host driver exercises the feature. `--all --catalog` checks every registered extension plus manifest, evaluator and explicit-install consumers; `--ci` runs exactly the gates the committed files select.
- **Prefix stages:** a feature without `EXTENSION.md` is an unregistered implementation prefix. `--stage core` (core sources, typecheck, lint, unit tests) and `--stage omp` (plus the OMP adapter probe and OMP native smoke) certify only that stage and always report `feature_complete=false`; the full gate stays incomplete. A `claude-code/` directory without `EXTENSION.md` is refused: the complete package, definition, catalog entry and CHANGELOG land together in one PR.
- **Install:** never through profiles, presets, interactive selection or "all". Use `uv run python scripts/install.py --type extension --platform <omp|claude> --name <feature> --action <install|update|disable|remove> --target-root <host root> --yes`. For OMP the root is the agent directory (`~/.omp/agent`, or `PI_CODING_AGENT_DIR`): the payload goes to `<root>/extensions/<feature>/` and disable adds `extension-module:<feature>` to `disabledExtensions` in `<root>/config.yml`. For Claude Code the root is the configuration directory (`~/.claude`, or `CLAUDE_CONFIG_DIR`): the payload goes to `<root>/.armory-native/claude-plugins/<feature>/` and is registered in `env.CLAUDE_CODE_PLUGIN_DIRS` of `<root>/settings.json`; disable removes exactly that entry. To try an artifact for one session without installing, use `omp --plugin-dir <artifact>` or `claude --plugin-dir <artifact>`.
- **Lifecycle safety:** a private ownership record under `<root>/.armory-native/ownership/` binds feature, host, version, root, owned file digests and exact configuration/ownership preimages. Every action holds an advisory host-root lock and writes a durable journal before activation. Recovery rolls back an interrupted pre-commit action; after a durable commit it finishes cleanup instead of restoring retired files. Foreign or locally modified files, special files, symlinked paths, name collisions and malformed journals are refused. Ambiguous recovery preserves the journal and payload trees rather than guessing which data to delete. Targeted configuration edits preserve comments, formatting and foreign path segments; removal deletes only unchanged owned files and the exact registration Armory added. Extension data, other features and foreign configuration survive.
- **Platforms:** native lifecycle operations require POSIX host-root locking. Other platforms fail before changing native files or configuration; legacy copy and adapter routes do not import the native-only locking dependency.
- **Fixtures:** packaging tests use fictional complete packages under `extensions/_fixtures/`, outside registered discovery. They are never cataloged or released; lifecycle tests install them only under disposable test roots.
- **Eval boundary:** `scripts/run_evals.py --package extensions/<name> --dry-run` validates eval structure only. Live prompt loading cannot load native commands and is refused with a nonzero exit; use the explicit native check/smoke driver for host execution. Legacy model-fit manifests and website profile membership/counts exclude native extensions even when the profile selects `all`.

Optional subdirectories (for any package type except extensions, whose layout is fixed above):

- `references/` — documents or context files the package uses
- `scripts/` — helper scripts invoked by the package
- `assets/` — images or static files

## Versioning

Packages use [semantic versioning](https://semver.org/) via the `metadata.version` field in their definition file frontmatter.

| Change Type | Bump | Example | Concrete examples |
| --- | --- | --- | --- |
| Breaking change to behavior or schema | MAJOR | `1.0.0` -> `2.0.0` | Removed workflow step, renamed command, changed output format |
| New capability, backward-compatible | MINOR | `1.0.0` -> `1.1.0` | Added workflow step, new reference file, support for a distinct invocation branch |
| Bug fix, typo, clarification | PATCH | `1.0.0` -> `1.0.1` | Typo fix, description improvement, eval case addition |

After changing a version, regenerate the manifest:

```bash
uv run scripts/generate_manifest.py
```

### Per-Package Changelogs

For packages with active development (frequent updates across multiple PRs), add an optional `CHANGELOG.md` in the package directory:

```markdown
# Changelog — package-name

## 2.0.0

- BREAKING: removed Phase 3 (merged into Phase 2)
- Added error handling section

## 1.1.0

- Added reference file for edge cases
- Added a distinct configuration-discovery invocation branch with its own output and completion criteria
```

Changelogs are optional. Single-version packages and packages with only a few changes do not need them — the git history suffices.

## Naming Rules

- Package names: kebab-case, maximum 64 characters
- Directory name must match the `name` field in frontmatter

## Self-Containment

Packages must be standalone. Every file a package references must live within its own directory.

**Blocked:**

- `../other-package/references/file.md` — cross-package path references
- Absolute paths to files outside the package directory
- References to files that only exist in other packages

Native extensions extend this to runtime code: each built host artifact contains every module it loads, and an installed copy never imports the repository, a sibling package or anything from npm.

**Why:** Packages are distributed individually via `npx skills add` and archive files. Cross-package file references break when a package is installed without its dependency. Check this with `scripts/validate_references.py` and package-content review; the report-v2 static evaluator does not inspect reference targets.

**Shared content:** If multiple packages need the same reference file, use the template sync system (see below). Each package gets its own physical copy, managed by `scripts/sync_templates.py`.

## Shared Templates

The `_templates/` directory holds reference files shared across multiple packages. The sync system copies templates into each consuming package's `references/` directory.

**How it works:**

1. Source files live in `_templates/` (e.g., `_templates/detection-patterns.md`)
2. `scripts/sync_templates.py` defines which packages consume each template via `TEMPLATE_CONSUMERS`
3. Running the script copies templates to `{type-dir}/{consumer}/references/{template}`
4. A pre-commit hook runs sync automatically when templates or references change
5. CI runs the same synchronizer and fails if any registered copy needs updating; run `uv run python scripts/sync_templates.py` and commit the resulting copies before pushing

**To add a shared template:**

1. Create the file in `_templates/`
2. Add the template name and consumer list to `TEMPLATE_CONSUMERS` in `scripts/sync_templates.py`
3. Run `uv run python scripts/sync_templates.py` to populate copies
4. Commit both the template and the synced copies

**To use an existing template in a new package:**

1. Add your package name to the consumer list in `scripts/sync_templates.py`
2. Run `uv run python scripts/sync_templates.py`
3. Reference the file as `references/{template}` in your definition file (local path, not `../`)

Current templates:

| Template                | Consumers                                        | Purpose                          |
| ----------------------- | ------------------------------------------------ | -------------------------------- |
| `detection-patterns.md` | humanize, linkedin-post-style, manuscript-review | AI writing detection patterns    |
| `project-detection.md`  | ship-workflow, plan-review, qa-systematic        | Stack-agnostic project detection |

## Description Rules

- Keep descriptions within the current validator's 50–1024 character range. These are static format limits, not evidence of effectiveness.
- No angle brackets (`<`, `>`) or pushy trigger language ("always use", "you must", "never do").
- Describe concrete invocation contexts and the boundary with adjacent packages, using a "Use when..." clause or equivalent.
- Cover each distinct invocation branch. Repeated synonyms for one task do not cover a different task.
- Preserve the required `description` field even for explicit user invocation. Invocation flags and router behavior are harness-specific: discover support in the target adapter/configuration rather than copying another harness's frontmatter.

### Writing a discoverable description

The description is a context pointer: it tells an agent or person when to reach the package. Put the triggering situation before implementation details. State capabilities only as needed to distinguish the task; keep the workflow in the body.

```yaml
description: >
  Use when reviewing a system design document or codebase for architecture risks,
  or comparing proposed architectures before implementation. For a line-level
  code diff review, use the PR review workflow instead.
```

This example names distinct document/codebase and comparison branches and an adjacent boundary. Whether it routes correctly requires observed invocation cases; wording, phrase counts and character counts cannot establish that.

## Observable Authoring Contracts

For each supported invocation, identify its input, selected branch, required reference/configuration, observable output and completion criterion. A criterion must be checkable and exhaustive: "every changed model has a migration decision and evidence pointer" rather than "understand the models" or merely "write a summary." Each step ends with the artifact, observed state or explicit unresolved prerequisite that distinguishes done from not done.

Keep instructions every branch needs in the definition file. Put branch-only detail behind a package-local pointer stating **when to load it** and **what it supplies**. For example, "For a CLI-backed export, read `references/cli-export.md` before selecting flags; it defines export/error evidence." A config-only invocation should not have to read that reference. A references table with filenames alone is not a loading contract. Keep a concept's rules and caveats together and retain one authoritative source for each requirement.

Discover mutable facts from the environment: package scripts, configuration files, directory layout and the installed tool's help/implementation. Record the source of chosen commands, config keys and precedence. Explain only conventions or gotchas that those sources cannot reveal; do not cache a repository's current test command as a universal instruction. If a required tool or config source is missing, name it, report which branch is blocked and complete independent work without inventing flags or successful execution.

Use a branch matrix, not a synonym inventory:

| Invocation branch (illustrative) | Conditional material/config discovery | Observable completion evidence |
| --- | --- | --- |
| Export through an installed CLI | Load the CLI export reference; inspect installed help and the project script selecting that CLI | Artifact path, exact sourced command, exit result and artifact inspection; or exact missing CLI prerequisite |
| Export through a config-only integration | Load the config integration reference; inspect the active config and its loader/precedence | Config source/key and resulting artifact or observed configuration effect; or exact missing loader/config prerequisite |

These filenames and commands are illustrative, not files to create for every package. Provide real local pointers and package-specific evidence for every branch actually promised. Split a branch into a separate package only when independent invocation earns a separate discovery surface, not merely to shorten source. Source shortening and structural conformance do not prove better agent behavior.

## Metadata Fields

Every package must include `category`, `tags`, and `difficulty` under `metadata:` in frontmatter. These authoring requirements are broader than report-v2's minimal static checks.

Maintain these fields directly in each package definition. The manifest generator mirrors declared metadata; it does not infer categories, tags, or difficulty.

### Category

Assign one category from the table below:

| Category        | Use For                                                    |
| --------------- | ---------------------------------------------------------- |
| `development`   | Coding tools, build, debug, test, IDE integration          |
| `review`        | Code review, PR review, quality checks, auditing           |
| `security`      | Security scanning, secrets detection, vulnerability checks |
| `research`      | Literature review, academic research, critique             |
| `content`       | Writing, presentations, video, publishing                  |
| `business`      | Idea validation, market sizing, feasibility, proposals     |
| `visualization` | Diagrams, images, video rendering, visual artifacts        |
| `operations`    | Release, deployment, CI/CD, git workflow, presets           |
| `data`          | SQL, database, migration, benchmarks                       |

### Tags

Add 3-6 lowercase kebab-case tags that help users discover the package. Include:

- Domain keywords (e.g., `sql`, `python`, `security`)
- Action verbs (e.g., `code-review`, `test-generation`)
- Technology names (e.g., `pytest`, `manim`, `remotion`)

### Difficulty

| Level          | Criteria                                                   |
| -------------- | ---------------------------------------------------------- |
| `beginner`     | Simple single-purpose tools, minimal setup                 |
| `intermediate` | Multi-step workflows, some domain knowledge needed         |
| `advanced`     | Complex multi-phase analysis, deep domain expertise needed |

### Phase (optional)

Lifecycle phase indicating when in the development workflow this package is used. Helps the `/route` command and orchestrator agents sequence work correctly.

| Phase      | When                                                          |
| ---------- | ------------------------------------------------------------- |
| `define`   | Idea validation, requirements gathering, market research      |
| `plan`     | Task breakdown, estimation, architecture decisions            |
| `build`    | Writing code, generating tests, debugging, optimization       |
| `verify`   | Running benchmarks, QA testing, validation                    |
| `review`   | Code review, security audit, architecture review, refactoring |
| `ship`     | Release, changelog, documentation, deployment                 |

```yaml
metadata:
  version: 1.0.0
  category: review
  tags: [code-review, quality]
  difficulty: intermediate
  phase: review
```

## Task-Conditioned Entries (Memento-Skills)

The `immune` skill (v3.1.0+) supports optional task-conditioned retrieval,
which implements the read phase of the Memento-Skills reflective loop
(arXiv 2603.18743). Antibodies and cheatsheet strategies may carry an
optional `triggers` field that filters and ranks them per-task, so that
unrelated entries are excluded from the active context.

**Adding a task-conditioned entry to immune memory:**

```json
{
  "id": "AB-042",
  "domains": ["code"],
  "pattern": "SQL injection via string concatenation",
  "severity": "critical",
  "correction": "Use parameterized queries (?, $1, bind)",
  "seen_count": 12,
  "first_seen": "2026-03-01",
  "last_seen": "2026-04-05",
  "triggers": {
    "task_signatures": ["code query review sql", "audit code sql"],
    "domains": ["code"]
  }
}
```

**Field reference:**

| Field                      | Type          | Purpose                                                                                             |
| -------------------------- | ------------- | --------------------------------------------------------------------------------------------------- |
| `triggers.task_signatures` | `list[str]`   | Canonical task signatures where this entry has historically been relevant. Use `task_signature()`. |
| `triggers.domains`         | `list[str]`   | Hard filter — prompts outside these domains skip the entry entirely (unless the list contains `_global`). |

**Back-compatibility:** entries without a `triggers` field behave as
always-on (the v3.0.0 default). Adding `triggers` is purely additive — do
not remove or change existing entries without understanding downstream
scanner behavior.

**Producing canonical signatures:**

```bash
python -c 'from scripts.task_signature import task_signature; print(task_signature("Review this SQL query for injection"))'
# -> "injection query review sql"
```

The signature string is the space-joined, sorted set of normalized content
tokens. Always produce signatures through `scripts.task_signature` rather
than writing them by hand, so that the same normalization rules apply at
write time and at retrieval time.

## Optional Content Sections

Skills and agents may include these optional sections when they address a concrete execution risk. Their presence alone does not establish agent compliance.

### Rationalizations

A table of common excuses agents use to skip the skill's workflow, paired with factual rebuttals. Preemptively closes escape hatches.

```markdown
## Rationalizations

| Rationalization | Reality |
|---|---|
| "Tests pass, so the code is fine" | Tests are necessary but insufficient — they miss architecture and security |
| "It's a small diff" | Small changes cause most production incidents |
```

**When to include:** Recommended for any skill where partial compliance is dangerous (review, security, testing, migration).

### Red Flags

Observable patterns indicating the skill isn't being followed correctly during execution. Provides runtime self-correction signals.

```markdown
## Red Flags

- Approving without reading every changed file in full
- No file:line references in findings
- Skipping a review dimension because "it looks fine"
```

**When to include:** Recommended for skills with multi-step workflows where steps can be silently skipped.

### Verification

Concrete evidence requirements distinguish completed work from an assertion of success. Require artifacts (test output, build logs, inspected output) covering every applicable acceptance criterion, and identify unexercised cases explicitly.

```markdown
## Verification

- [ ] All tests pass with output captured
- [ ] Coverage meets thresholds: 80% overall, 90% new code
- [ ] Linter exits clean: `ruff check` + `mypy --strict`
```

**When to include:** Recommended for skills that produce measurable outcomes (testing, review, deployment).

## Quality Gate — Static Conformance and Authored Review

Run the current repository interface before submitting a PR:

```bash
uv run python scripts/evaluate_package.py --path skills/my-skill-name --json
```

`scripts/evaluate_package.py` emits a JSON **list** of report-v2 package records (`report_version: 2`). Each record separates:

- `static_conformance.status`: `PASS` or `FAIL`, with `requirements` and `findings`. It checks definition/frontmatter presence, type-required fields, name/directory agreement, kebab-case directory naming and version syntax when a version is present.
- `live_effectiveness.status`: `NOT_MEASURED`, with the designated runner and type-specific dimensions. A static pass does not measure activation, task outcomes or configuration effects.
- Top-level `status` and `findings`: mirrors of static conformance, not a second quality verdict.

The command exits 1 for a static failure or invalid requested path and 0 when all evaluated records pass. It has `--path` and `--json`; omitting `--path` evaluates the catalog. Type filtering is a reviewer-selected scope, not a `--type` evaluator flag.

Run the separate frontmatter, reference and eval-schema validators as well: the static evaluator does not enforce every authoring policy (including the description cap), inspect reference targets or execute helpers. Use the [package-evaluator](skills/package-evaluator/SKILL.md) for an evidence-backed authored review of branch contracts, reference loading, configuration discovery and type-specific behavior. Keep authored findings distinct from machine output; do not rewrite the machine status to incorporate them.

There is no weighted package-quality score, percentage acceptance threshold or scorecard in this interface. Attach actual conformance output, remaining authored findings and the scope/limits of behavioral evidence to the PR. A conformant package is not thereby effective. Existing effectiveness roadmap requirements, including M4/M8 experimental gates, remain binding; this static gate does not clear them.

## Eval Cases

Every active package must have `evals/cases.yaml` within its own directory. Cases specify intended invocation and task behavior, including adjacent tasks that should leave the package inactive. Authored cases are coverage specifications, not observed successes.

**Schema:**

```yaml
cases:
  - id: unique_snake_case_id
    prompt: "What the user would type"
    fixtures: []
    rubric:
      - "Expected behavior point 1"
      - "Expected behavior point 2"
    trigger_expected: true # or false
```

**Requirements:**

| Skill Status | Positive Cases (trigger_expected: true) | Negative Cases (trigger_expected: false) |
| ------------ | --------------------------------------- | ---------------------------------------- |
| Active       | 2+; cover every distinct invocation branch | 2+                                    |
| Deprecated   | 0 (must be zero)                        | 2+                                       |

**Deprecating a skill:** Set `metadata.status: deprecated`, then move the package from `skills/<name>/` to `archive/skills/<name>/` (no deprecated skill may remain under `skills/`). Archived skills are retained for reference only and are excluded from discovery, installation, the manifest, and adapters. After moving, regenerate the manifest and adapters and move its row in `README.md` to the "Skills — Deprecated (Archived)" table with an `archive/skills/` link.

**Guidelines:**

- Positive cases use natural language a real user would type and cover every distinct invocation branch, not just synonyms of one branch.
- Negative cases test plausible adjacent tasks the package should not handle.
- Each case needs a unique `id` (snake_case), `prompt`, `fixtures: []` when no fixture is supplied, `rubric` and boolean `trigger_expected`.
- Rubric items specify observable artifacts/evidence and exhaustive completion, including the selected reference/config path and behavior when a prerequisite is missing.
- Include adversarial conditional-reference and differing CLI/config-environment cases when applicable. A file existing does not show that the right branch loads it.
- Keep authored rubrics, structural validation/dry-runs, deterministic helper tests and separately authorized live invocation results distinct. Assertions matching words or formats do not establish task success by themselves.

**Validation:**

```bash
uv run python scripts/validate_evals.py
```

CI runs this on every PR. Skills without valid evals will fail the pipeline.

## Testing Locally

Discover the current harness setup and runner modes from configuration, implementation and help before selecting an invocation. Only run model sessions when authorized. Record the package/case identity, environment, actual invocation, output/artifact and observed result; do not infer activation from a directory being accessible.

`scripts/run_evals.py` normally launches live Claude sessions. Its `--dry-run` skips execution, so skipped cases (even a printed summary saying PASS) are structure-only evidence, not activation or effectiveness. Keep evaluator `live_effectiveness` as `NOT_MEASURED`; attach separately authorized measured evidence without relabeling the static report.

## Packaging

Run the packaging script to produce a distributable archive:

```bash
uv run scripts/package.py skills/my-skill-name
```

## RFCs — Design Proposals

For changes to the package system, adapter architecture, new package types, or infrastructure decisions, open an [RFC discussion](https://github.com/Mathews-Tom/armory/discussions/new?category=rfcs) before writing code. RFCs ensure alignment on design before implementation effort is spent.

An RFC should include: problem statement, proposed solution, alternatives considered, and migration impact.

## Contribution Opportunities

See [WANTED.md](WANTED.md) for missing skill domains, requested agents, and infrastructure improvements. Each item lists difficulty and scope to help you pick the right contribution.

## Pull Request Checklist

Before opening a PR, confirm:

- [ ] Definition file has valid YAML frontmatter with `name`, `description`, and `metadata.version`
- [ ] Version bumped according to semver (MAJOR/MINOR/PATCH)
- [ ] Manifest regenerated: `uv run scripts/generate_manifest.py`
- [ ] Package name is kebab-case, at most 64 characters
- [ ] Description satisfies the current 50–1024 character validator range and names distinct invocation contexts and adjacent boundaries
- [ ] No angle brackets or pushy language in description
- [ ] No secrets, credentials, or internal URLs in any file
- [ ] Actual authorized local checks and behavioral evidence recorded, with unmeasured/skipped cases and prerequisites explicit
- [ ] All file references in the definition file resolve to existing files within the package directory
- [ ] No cross-package references (`../other-package/`) — package is fully self-contained
- [ ] Eval cases exist in `evals/cases.yaml` with 2+ positive cases covering every distinct invocation branch and 2+ adjacent negatives
- [ ] Eval schema validated: `uv run python scripts/validate_evals.py` (not a behavioral pass)
- [ ] Templates synced (if using shared templates): `uv run python scripts/sync_templates.py`
- [ ] Report-v2 static conformance is PASS; actual output and separate authored findings attached
- [ ] Frontmatter/reference validation and applicable authored-review findings resolved; effectiveness claims limited to separately measured evidence
