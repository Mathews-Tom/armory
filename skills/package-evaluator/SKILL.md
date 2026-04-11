---
name: package-evaluator
description: 'Evaluates Claude Code package quality across 6 dimensions for all 7 package types, producing scored audit reports. Triggers on: "evaluate package", "audit agent quality", "score this hook", "package audit", "skill quality check". NOT for LLM prompts, use prompt-lab.'
metadata:
  version: 1.3.1
  category: review
  tags: [quality, audit, scoring, frontmatter]
  difficulty: intermediate
  phase: review
---

# Package Evaluator

Packages that do not activate on relevant queries waste the entire investment in writing
them. A skill can have deep, well-structured content and still deliver zero value if its
frontmatter description lacks the trigger phrases users actually type. An agent without
a decision tree produces inconsistent results. A hook without a handler script is inert.
Quality evaluation catches trigger gaps, missing sections, structural deficiencies, and
shallow content before deployment — turning a package from a static document into a
reliable tool.

## Reference Files

| File                              | Contents                                                                                                                    |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `references/evaluation-rubric.md` | Detailed 1-5 scoring criteria per dimension, weight justifications, type-specific criteria, worked examples for calibration |

## Audit Modes

Two modes, selected by input:

- **Quick Audit**: Evaluate a single package. Produces a full per-dimension scored report
  with findings, severity classifications, and recommendations.
- **Full Audit**: Evaluate all packages in the repository. Produces a comparative ranking
  table sorted by overall score, plus condensed per-package summaries. Optionally filtered
  to a single package type.

### Mode Selection

| Input                                                   | Mode                                           |
| ------------------------------------------------------- | ---------------------------------------------- |
| Path to a specific package directory or definition file | Quick Audit                                    |
| "all", "every package", no path specified               | Full Audit                                     |
| "--type agents" or type filter                          | Full Audit filtered to one type                |
| Multiple specific paths                                 | Quick Audit for each, then comparative summary |

---

## Evaluation Dimensions

Six dimensions, each scored 1-5. Weighted sum determines overall percentage.

### D1: Frontmatter Quality (20%)

Evaluates the YAML frontmatter block for completeness and discoverability.

**Signals:**

- `name` field present and non-empty
- `description` field present and non-empty
- Description length between 200-800 characters (sweet spot for keyword density without bloat)
- Description contains explicit trigger phrases users would type
- Description includes a "Use this skill when..." clause or equivalent
- Description is keyword-dense, not generic filler

**Scoring constraints:** A description under 100 characters caps this dimension at 2/5.
A missing `name` or `description` field caps at 1/5.

### D2: Trigger Coverage (18%)

Evaluates whether the package activates on the queries users actually type.

**Signals:**

- Synonym breadth — multiple phrasings for the same intent (e.g., "review", "audit",
  "critique", "evaluate", "assess", "check")
- Implied contexts — situations where the package applies even without explicit keywords
  (e.g., "user provides a design doc and asks for feedback")
- Domain-specific terms relevant to the package's function
- Explicit trigger phrase list in the description frontmatter
- Coverage of both imperative ("review this") and interrogative ("is this good?") forms

**Scoring constraints:** Fewer than 3 distinct trigger phrases caps at 2/5. Zero trigger
phrases in the description caps at 1/5.

### D3: Structural Completeness (20%)

Evaluates whether the package contains the sections needed to function reliably.

**Signals:**

- Prerequisites or setup instructions (if applicable)
- Multi-phase workflow or step-by-step procedure
- Error handling guidance or edge case documentation
- Output format specification (template, example, or schema)
- Limitations or scope boundaries stated
- Reference file table (if references/ directory exists)
- Calibration rules or quality gates

**Scoring constraints:** A package with no workflow section caps at 2/5. A package with
a workflow but no error handling or output format caps at 3/5.

### D4: Content Depth (22%)

Evaluates the substantive quality of the package's guidance — whether it provides enough
detail for an agent to execute well without human intervention.

**Signals:**

- Multi-step workflows with decision points, not bare command lists
- Error cases documented with recovery actions
- Decision frameworks (when to do X vs Y, mode selection tables)
- Verbatim output examples or templates
- Severity classifications or scoring rubrics (where applicable)
- Cross-cutting analysis or synthesis steps beyond simple checklists

**Scoring constraints:** A package consisting only of bare commands with no explanatory
context caps at 2/5. Reference files count toward this dimension only if they contain
substantive guidance (checklists, rubrics, criteria), not just link collections.

### D5: Consistency and Integrity (12%)

Evaluates internal consistency and structural integrity.

**Signals:**

- Directory name matches the `name` field in frontmatter exactly
- All files referenced in the definition file exist on disk (reference files, scripts, assets)
- Description content aligns with body content (description does not promise features
  the body does not deliver)
- Consistent terminology throughout (same concept uses same term)
- No broken internal links or dangling references
- **Self-containment**: No cross-package references (`../other-package/`) in the definition
  file or reference files. Packages must be standalone — all referenced files must live
  within the package's own directory. Shared content should use the `_templates/` sync
  system to maintain local copies.

**Scoring constraints:** A name mismatch between directory and frontmatter is a CRITICAL
finding and caps at 1/5. Cross-package `../` references are a CRITICAL finding and cap
at 1/5 — they break standalone packaging. Missing referenced files cap at 2/5.

### D6: CONTRIBUTING.md Compliance (8%)

Evaluates adherence to the repository's contribution guidelines.

**Signals:**

- Package name is kebab-case
- Package name is 64 characters or fewer
- Description is 1024 characters or fewer
- No angle brackets in description
- No pushy trigger language in description ("always use", "you must", "never do")
- Valid YAML frontmatter syntax

**Scoring constraints:** Any single violation caps at 3/5. Multiple violations cap at 2/5.
Invalid YAML that prevents parsing caps at 1/5.

---

## Type-Specific Dimensions

In addition to the 6 shared dimensions, each package type has type-specific quality
signals that influence D3 (Structural Completeness) and D4 (Content Depth) scoring.

### Agent-Specific Signals

When evaluating an AGENT.md:

**D3 additions:**

- `model` field specified (opus/sonnet/haiku)
- `color` field specified
- `metadata.category` specified
- `metadata.execution_phase` specified (pre-write/post-write/pre-commit)
- `metadata.language_targets` specified

**D4 additions:**

- Decision tree or algorithm section present with clear phases
- START/END or phase markers for structured execution flow
- Severity classification for findings (CRITICAL/HIGH/MEDIUM/LOW)
- Language-specific patterns documented (not just generic advice)
- VIOLATION/BLOCK/PASS outcome paths defined

**Scoring impact:** An agent without a decision tree caps D4 at 2/5. An agent without
model/category/phase metadata caps D3 at 3/5.

### Hook-Specific Signals

When evaluating a HOOK.md:

**D3 additions:**

- `hook.events` list specified (PreToolUse, PostToolUse, Stop, etc.)
- `hook.handler.type` specified (command/python-module)
- `hook.handler.command` specified
- `handler.sh` or equivalent handler script exists in directory

**D4 additions:**

- Handler script is functional (not placeholder/stub)
- Handler reads stdin JSON correctly
- Exit code semantics documented (non-zero blocks for PreToolUse)
- Edge cases documented (what happens on timeout, malformed input)

**Scoring impact:** A hook without a handler script caps D4 at 1/5. A hook without
documented events caps D3 at 2/5.

### Rule-Specific Signals

When evaluating a RULE.md:

**D3 additions:**

- `metadata.scope` specified (global/project)
- `metadata.applies_to.languages` specified if scope is language-specific

**D4 additions:**

- Concrete, actionable requirements (not vague principles)
- Code examples for key rules
- Anti-patterns shown alongside correct patterns
- Thresholds/limits specified with numbers (not "reasonable" or "appropriate")

**Scoring impact:** A rule with only vague principles and no concrete requirements caps
D4 at 2/5.

### Command-Specific Signals

When evaluating a COMMAND.md:

**D3 additions:**

- `command.syntax` specified with argument documentation
- `command.handler` specified (inline/command)

**D4 additions:**

- Numbered step-by-step workflow
- Decision points clearly marked
- Output format specified
- Termination criteria defined (when to stop the workflow)

**Scoring impact:** A command without a step-by-step workflow caps D4 at 2/5.

### Utility-Specific Signals

When evaluating a UTILITY.md:

**D3 additions:**

- `utility.runtime` specified (python/node/shell)
- `utility.entry_point` specified and the file exists
- `utility.executable` specified

**D4 additions:**

- Entry point script uses argparse or equivalent for CLI
- Script has proper error handling (not bare except)
- Usage examples in the body
- No external dependencies beyond stdlib (or dependencies documented)

**Scoring impact:** A utility without a working entry_point script caps D4 at 1/5.

### Preset-Specific Signals

When evaluating a PRESET.md:

**D3 additions:**

- `preset.packages` specified with at least one type section
- Each referenced package exists in the manifest
- `preset.compatibility.platforms` specified

**D4 additions:**

- Body explains why these packages work together
- Describes the target workflow or use case
- References are to existing packages (not aspirational)

**Scoring impact:** A preset referencing non-existent packages is a CRITICAL finding.

---

## Severity Classification

| Severity | Criteria                                                                                                                       | Score Impact                              |
| -------- | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------- |
| CRITICAL | Package cannot activate or breaks on load — missing frontmatter, name mismatch, invalid YAML, non-existent preset references   | Caps overall score at 40%                 |
| HIGH     | Significant trigger gap or missing core section — no workflow, no error handling, zero trigger phrases, missing handler script | Caps affected dimension at 3/5            |
| MEDIUM   | Weak coverage, shallow content, few trigger synonyms, missing type-specific metadata                                           | Dimension needs improvement but functions |
| LOW      | Minor polish — formatting inconsistencies, slightly short description, missing calibration rules                               | Fix when convenient                       |

---

## Workflow

### Phase 1: Input

1. Determine audit mode from user input (see Mode Selection table above).
2. For Quick Audit: validate the package directory exists and contains a recognized
   definition file. Detect package type from the definition file name:
   `SKILL.md` = skill, `AGENT.md` = agent, `HOOK.md` = hook, `RULE.md` = rule,
   `COMMAND.md` = command, `UTILITY.md` = utility, `PRESET.md` = preset.
   If the path points to a definition file directly, use its parent directory.
3. For Full Audit: enumerate all directories under `skills/`, `agents/`, `hooks/`,
   `rules/`, `commands/`, `utilities/`, and `presets/` that contain a recognized
   definition file. If a `--type` filter is specified, restrict to that type's directory.
4. For each package to evaluate, note the directory name for D5 consistency checks
   and the package type for type-specific signal evaluation.

### Phase 2: Analysis

For each package under evaluation:

1. Read the definition file in full.
2. Parse YAML frontmatter — extract `name` and `description` fields. If YAML parsing
   fails, record a CRITICAL finding and score D1 and D6 as 1/5.
3. Check the `references/` directory for existence and contents. Verify every file
   referenced in the definition file body exists on disk.
4. Scan the definition file and all reference files for cross-package path references
   (`../` patterns pointing outside the package directory). Flag any as CRITICAL D5
   findings.
5. Identify the package type and evaluate type-specific signals (see Type-Specific
   Dimensions above). Apply type-specific scoring caps to D3 and D4 as documented.
6. Evaluate each of the 6 dimensions using the shared criteria above, the type-specific
   signals, and the detailed rubric in `references/evaluation-rubric.md`.
7. Record findings with severity, dimension tag, description, and recommendation.

### Phase 3: Scoring

1. Score each dimension 1-5 using `references/evaluation-rubric.md`.
2. Apply severity caps: if any CRITICAL finding exists, cap overall at 40% regardless
   of dimension scores.
3. Compute weighted score: `Overall% = (sum of dimension_score x weight) / 5 x 100`.
4. Determine verdict from the scale below.

| Range     | Verdict    |
| --------- | ---------- |
| 90-100%   | Exemplary  |
| 80-89%    | Strong     |
| 70-79%    | Adequate   |
| 60-69%    | Needs Work |
| Below 60% | Deficient  |

### Phase 4: Report

Generate the structured output using the appropriate template below.

---

## Output Format

### Quick Audit Template

```text
## Package Audit: {package-name} ({type})

| Dimension | Score | Weight | Weighted | Key Finding |
|-----------|-------|--------|----------|-------------|
| D1: Frontmatter Quality | X/5 | 20% | X.XXX | ... |
| D2: Trigger Coverage | X/5 | 18% | X.XXX | ... |
| D3: Structural Completeness | X/5 | 20% | X.XXX | ... |
| D4: Content Depth | X/5 | 22% | X.XXX | ... |
| D5: Consistency & Integrity | X/5 | 12% | X.XXX | ... |
| D6: CONTRIBUTING Compliance | X/5 | 8% | X.XXX | ... |

**Overall: XX% — {Verdict}**

### Type-Specific Findings

[Findings from type-specific signal evaluation, if any.]

### Findings

[Severity-sorted list. Each entry includes dimension tag, severity, description,
evidence, and recommendation.]

- **[CRITICAL] D5:** ...
- **[HIGH] D2:** ...
- **[MEDIUM] D4:** ...
- **[LOW] D3:** ...

### Score Calculation

D1: {score} x 0.20 = {result}
D2: {score} x 0.18 = {result}
D3: {score} x 0.20 = {result}
D4: {score} x 0.22 = {result}
D5: {score} x 0.12 = {result}
D6: {score} x 0.08 = {result}
Sum = {weighted_sum}
Overall = {weighted_sum} / 5 x 100 = {percentage}% — {Verdict}
```

### Full Audit Template

```text
## Package Repository Audit

| Package | Type | Overall | Verdict | Worst Dimension | Top Issue |
|---------|------|---------|---------|-----------------|-----------|
| {name} | {type} | XX% | {verdict} | {dimension} | {issue} |
| ... | ... | ... | ... | ... | ... |

### Per-Package Summaries

[Condensed Quick Audit for each package: scorecard table, overall score, top 3 findings.
Omit the full Score Calculation section in condensed mode.]
```

---

## Error Handling

| Problem                                               | Cause                                                                                                                 | Fix                                                                                                                       |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Definition file not found in directory                | Path incorrect or file missing                                                                                        | Report as CRITICAL; do not attempt evaluation; surface the path and stop                                                  |
| Unknown definition file                               | Directory has no recognized definition file (SKILL.md, AGENT.md, HOOK.md, RULE.md, COMMAND.md, UTILITY.md, PRESET.md) | Skip directory; report as warning in Full Audit; report as CRITICAL in Quick Audit                                        |
| YAML frontmatter parse failure                        | Invalid YAML syntax (unclosed quotes, bad indentation)                                                                | Report as CRITICAL finding; score D1 and D6 as 1/5; continue evaluating the body content where parseable                  |
| `references/` directory missing                       | Package has no reference files                                                                                        | Not an error — score D5 normally; check only that any files referenced in the definition file body actually exist on disk |
| `references/` exists but referenced file is absent    | File path in definition file body doesn't resolve                                                                     | Record as a CRITICAL D5 finding; missing referenced files cap D5 at 2/5                                                   |
| Empty definition file (zero bytes or whitespace only) | File created but never populated                                                                                      | Treat as CRITICAL; score all dimensions 1/5; overall verdict: Deficient                                                   |
| `references/evaluation-rubric.md` not found           | Evaluator's own reference file missing                                                                                | Note the irony; evaluate using the criteria inline in this SKILL.md; flag D5 as a CRITICAL finding                        |
| Handler script missing for hook                       | HOOK.md references a handler that doesn't exist                                                                       | Record as CRITICAL D4 finding; cap D4 at 1/5                                                                              |
| Preset references non-existent package                | PRESET.md lists a package not in the manifest                                                                         | Record as CRITICAL finding; caps overall at 40%                                                                           |

## Calibration Rules

1. Score what exists, not what could exist — evaluate the package as-is, not its potential.
2. Weight trigger coverage heavily for packages targeting broad domains (e.g., a GitHub skill
   covers issues, PRs, CI, releases, and API — it needs proportionally more trigger synonyms).
3. A package with strong triggers but shallow content scores higher than deep content with
   poor triggers — activation is prerequisite to utility.
4. Reference files count toward Content Depth only if they contain substantive guidance
   (checklists, rubrics, criteria), not link lists or stub files.
5. When evaluating the package-evaluator itself, apply identical standards — no self-inflation.
6. Frontmatter description quality is the single highest-leverage improvement for any package.
7. Score type-specific signals proportionally — a hook's handler quality matters more than
   a rule's handler quality (rules have no handlers). Apply type-specific caps only when
   the signal is relevant to that package type.
