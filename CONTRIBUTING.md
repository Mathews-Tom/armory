# Contributing

## Package Types

Armory supports seven package types. Each lives in its own top-level directory with a definition file:

| Type    | Directory    | Definition File | Description                                |
| ------- | ------------ | --------------- | ------------------------------------------ |
| Skill   | `skills/`    | `SKILL.md`      | Prompt-driven workflow for a task domain   |
| Agent   | `agents/`    | `AGENT.md`      | Autonomous multi-step agent with tools     |
| Rule    | `rules/`     | `RULE.md`       | Always-on behavioral constraint            |
| Command | `commands/`  | `COMMAND.md`    | Slash-command triggered workflow           |
| Hook    | `hooks/`     | `HOOK.md`       | Event-driven automation (pre/post actions) |
| Utility | `utilities/` | `UTILITY.md`    | Standalone tool or report generator        |
| Preset  | `presets/`   | `PRESET.md`     | Curated bundle of packages across types    |

## Package Structure

Each package lives in its own directory under the appropriate type directory and must contain its definition file.

Definition frontmatter must be a YAML mapping; empty, scalar, and list-valued frontmatter are rejected. Package versions use exactly `X.Y.Z` with no surrounding whitespace or trailing newline. Shared parsing raises a validation error instead of returning non-mapping YAML values to callers.

### Skill (`SKILL.md`)

```yaml
---
name: my-skill-name
description: What this skill does in plain language.
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
description: What this agent does.
type: agent
metadata:
  version: 1.0.0
---
```

### Rule (`RULE.md`)

```yaml
---
name: my-rule-name
description: What this rule enforces.
type: rule
metadata:
  version: 1.0.0
---
```

### Command (`COMMAND.md`)

```yaml
---
name: my-command-name
description: What this command does.
type: command
metadata:
  version: 1.0.0
---
```

### Hook (`HOOK.md`)

```yaml
---
name: my-hook-name
description: What this hook does.
type: hook
trigger: pre-commit # or post-commit, pre-edit, etc.
metadata:
  version: 1.0.0
---
```

### Utility (`UTILITY.md`)

```yaml
---
name: my-utility-name
description: What this utility does.
type: utility
metadata:
  version: 1.0.0
---
```

### Preset (`PRESET.md`)

```yaml
---
name: my-preset-name
description: What this preset bundles.
type: preset
packages:
  - skills/some-skill
  - rules/some-rule
  - hooks/some-hook
metadata:
  version: 1.0.0
---
```

Optional subdirectories (for any package type):

- `references/` — documents or context files the package uses
- `scripts/` — helper scripts invoked by the package
- `assets/` — images or static files

## Versioning

Packages use [semantic versioning](https://semver.org/) via the `metadata.version` field in their definition file frontmatter.

| Change Type | Bump | Example | Concrete examples |
| --- | --- | --- | --- |
| Breaking change to behavior or schema | MAJOR | `1.0.0` -> `2.0.0` | Removed workflow step, renamed command, changed output format |
| New capability, backward-compatible | MINOR | `1.0.0` -> `1.1.0` | Added workflow step, new reference file, expanded trigger coverage |
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
- Expanded trigger phrases for activation coverage
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

**Why:** Packages are distributed individually via `npx skills add` and archive files. Cross-package references break when a package is installed without its dependency. The skill-evaluator flags this as a CRITICAL D5 finding.

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

- Maximum 1024 characters (sweet spot: 200-800 characters)
- No angle brackets (`<`, `>`)
- No pushy trigger language ("always use", "you must", "never do")
- Include trigger phrases users would type to activate the package
- Include a "Use this skill when..." clause describing activation contexts

## Writing an Effective Description

The frontmatter description controls whether Claude activates your package. A package with deep content but a weak description delivers zero value.

**Include in every description:**

1. What the package does (functional summary)
2. Key operations or subcommands covered
3. Trigger phrases across synonym families (e.g., "review", "audit", "critique", "evaluate")
4. A "Use this skill when..." clause listing concrete activation scenarios
5. Domain-specific terms users associate with the task

**Example (good):**

```yaml
description: >
  Architecture reviews across 7 dimensions: structural integrity, scalability,
  security, performance, enterprise readiness, operational excellence, and data
  architecture. Produces scored reports with prioritized recommendations.
  Triggers on: "review architecture", "critique design", "audit system",
  "evaluate codebase", "assess scalability". Use this skill when the user
  provides a system design document or codebase and asks for feedback.
```

**Example (insufficient):**

```yaml
description: "Review architecture and provide feedback."
```

## Metadata Fields

Every package should include `category`, `tags`, and `difficulty` under `metadata:` in frontmatter.

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

Skills and agents may include three optional sections that improve agent compliance. These are recommended for review, quality, and security packages.

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

Concrete evidence requirements proving the skill was executed correctly. Demands artifacts (test output, build logs, scores), not subjective assessment.

```markdown
## Verification

- [ ] All tests pass with output captured
- [ ] Coverage meets thresholds: 80% overall, 90% new code
- [ ] Linter exits clean: `ruff check` + `mypy --strict`
```

**When to include:** Recommended for skills that produce measurable outcomes (testing, review, deployment).

## Quality Gate — Skill Evaluator

Before submitting a PR, run the [skill-evaluator](skills/skill-evaluator/) against your package:

```bash
claude --add-dir skills/skill-evaluator --add-dir skills/my-skill-name
# Then: "Run a quick audit on skills/my-skill-name"
```

The evaluator scores 6 dimensions:

| Dimension                   | Weight | Minimum for PR |
| --------------------------- | ------ | -------------- |
| D1: Frontmatter Quality     | 20%    | 3/5            |
| D2: Trigger Coverage        | 18%    | 3/5            |
| D3: Structural Completeness | 20%    | 3/5            |
| D4: Content Depth           | 22%    | 3/5            |
| D5: Consistency & Integrity | 12%    | 4/5            |
| D6: CONTRIBUTING Compliance | 8%     | 4/5            |

**Minimum overall score for PR acceptance: 70% (Adequate).**

Packages scoring below 70% need improvement before review. Packages with CRITICAL findings (missing frontmatter, name mismatch) are automatically rejected.

## Eval Cases

Every skill must have eval cases in `skills/<name>/evals/cases.yaml`. These define trigger accuracy — does the skill activate on the right queries and stay silent on the wrong ones?

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
| Active       | 1+ (recommended: 2+)                    | 2+                                       |
| Deprecated   | 0 (must be zero)                        | 2+                                       |

**Deprecating a skill:** Set `metadata.status: deprecated`, then move the package from `skills/<name>/` to `archive/skills/<name>/` (no deprecated skill may remain under `skills/`). Archived skills are retained for reference only and are excluded from discovery, installation, the manifest, and adapters. After moving, regenerate the manifest and adapters and move its row in `README.md` to the "Skills — Deprecated (Archived)" table with an `archive/skills/` link.

**Guidelines:**

- Positive cases should use natural language a real user would type
- Negative cases should test plausible but incorrect triggers (adjacent tasks the skill should NOT handle)
- Each case needs a unique `id` (snake_case)
- Rubric items describe what a correct response looks like, not implementation details

**Validation:**

```bash
uv run python scripts/validate_evals.py
```

CI runs this on every PR. Skills without valid evals will fail the pipeline.

## Testing Locally

Point Claude Code at the package directory:

```bash
claude --add-dir skills/my-skill-name
```

Verify the package loads and behaves as expected before submitting a PR.

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
- [ ] Package name is kebab-case, under 64 characters
- [ ] Description is 200-1024 characters with trigger phrases and "Use when" clause
- [ ] No angle brackets or pushy language in description
- [ ] No secrets, credentials, or internal URLs in any file
- [ ] Tested locally with Claude Code
- [ ] All file references in the definition file resolve to existing files within the package directory
- [ ] No cross-package references (`../other-package/`) — package is fully self-contained
- [ ] Eval cases exist in `evals/cases.yaml` with 1+ positive and 2+ negative triggers (for skills)
- [ ] Evals pass: `uv run python scripts/validate_evals.py`
- [ ] Templates synced (if using shared templates): `uv run python scripts/sync_templates.py`
- [ ] Skill evaluator score is 70% or above (paste the scorecard in your PR)
- [ ] No CRITICAL or HIGH findings from skill evaluator
