# Evaluation Rubric

Use this reference for authored contract review, type-specific criteria and report/evidence calibration. It is not a scoring model and does not extend the machine report schema.

## Evidence Boundaries

| Evidence layer | Establishes | Does not establish |
| --- | --- | --- |
| `scripts/evaluate_package.py`, report_version 2 | The implemented static checks returned PASS or FAIL for the evaluated package | Full authoring-policy compliance, resolved references, executable behavior, activation or task effectiveness |
| Separate frontmatter/reference/eval-schema validators | Their implemented structural requirements for the checked scope | Correct conditional reference loading or successful agent execution |
| Authored review | Source-backed contract findings and coverage gaps | Observed model behavior or an efficacy estimate |
| Deterministic helper smoke | The specific exercised input/output or side effect in its recorded environment | Model discovery, all invocation branches or general effectiveness |
| Separately authorized live cases | Observed invocation/task behavior for the actual case/environment and evidence collected | Unexercised branches or clearance of broader experimental gates |
| Authored cases or dry-run | Intended coverage or structure-only traversal | Passing behavioral cases; skipped cases remain unmeasured |

Keep the existing effectiveness roadmap, including M4/M8 experimental gates, binding. No prose review, source shortening, phrase count or character count clears those gates.

## Exact Static Interface

The CLI supports `--path <package-directory>` and `--json`. Without `--path` it scans the registered type directories for definitions. It has no type-filter, score or threshold flag. Normalize a supplied definition-file path before passing its parent directory. For multiple/type-filtered audits, select scope separately and invoke supported paths.

JSON output is a **list** of records. This illustrative record shows the current fields for a hypothetical conformant skill, not an executed result:

```json
[
  {
    "report_version": 2,
    "name": "example-package",
    "type": "skill",
    "static_conformance": {
      "status": "PASS",
      "requirements": [
        "definition file",
        "valid YAML frontmatter",
        "type-required frontmatter",
        "matching package name",
        "kebab-case package directory"
      ],
      "findings": []
    },
    "live_effectiveness": {
      "status": "NOT_MEASURED",
      "runner": "scripts/run_evals.py",
      "dimensions": ["routing", "task outcome"]
    },
    "status": "PASS",
    "findings": []
  }
]
```

Static failures populate `findings` with severity/message entries and set both static and top-level status to FAIL. The current evaluator uses CRITICAL for its static findings. Its checks include version syntax when a version is present; missing version is a separate frontmatter-validator/policy issue, not a reason to invent a static finding. Exit status is 1 for static failure or invalid requested path, otherwise 0. Invalid input can emit an error without a JSON record. A default catalog scan skips directories without the expected definition: reconcile requested inventory separately.

Live-effectiveness dimensions vary by type:

| Type | Declared dimensions (not measured by this CLI) |
| --- | --- |
| Skill / agent | routing; task outcome |
| Hook | event handling; observable side effect |
| Rule | routing; constraint adherence |
| Command / utility | command invocation or utility invocation, respectively; task outcome |
| Preset | preset loading; configuration effect |

Preserve actual output. NOT_RUN may be an execution note in an authored report, but is not a machine status. There are no weighted dimensions, numeric quality grades, score caps, percentage acceptance thresholds or quality scorecards in report-v2. Do not overwrite a static PASS because an authored finding exists, and do not interpret PASS as acceptance of unmeasured behavior.

## Common Authored Criteria

Apply all applicable criteria to every in-scope package; record source evidence, a finding or the precise reason a criterion is inapplicable/uninspectable. Do not require ceremonial headings in place of the actual contract.

| Criterion | Observable review evidence | Finding example |
| --- | --- | --- |
| Identity and metadata | Definition/type, name/directory agreement, YAML mapping, exact X.Y.Z version, category/tags/difficulty and required type fields | Name mismatch or absent required type data; distinguish the responsible validator from authored policy |
| Invocation boundary | Description names each distinct supported context and adjacent alternatives; body delivers every promised branch | Export promised for CLI and config integration, but only CLI flow exists |
| Completion | Every step has a checkable end condition; final criteria account for every applicable input and promised output | “Understand config, then summarize” leaves active files, precedence and unhandled inputs unaccounted for |
| Common versus branch-only instructions | Shared prerequisites/authority/evidence inline; branch selection precedes conditional material | Config-only review must perform unrelated CLI installation before it can inspect a config |
| Reference loading | Each pointer supplies a load condition and purpose; selected branch can find required rules without reading all references | A filenames-only list conceals a required error-evidence reference |
| Environment discovery | Commands, keys and precedence traced to current scripts/config/loader/help or implementation | Unsupported flags copied from an older CLI; hardcoded config path conflicts with the active loader |
| Integrity and self-containment | Every promised file/helper exists locally; no cross-package filesystem dependency; consistent names/claims | Broken required reference or helper; a full installed copy cannot supply the target |
| Recovery and authority | Required inputs, authorization, missing-prerequisite/error/cancellation outcomes explicit | Missing binary produces a fabricated success artifact or a dangerous automatic setup |
| Invocation coverage | Every distinct branch mapped to a positive case and output/evidence; adjacent negatives and relevant adversarial variants | Several “audit/review/evaluate” prompts cover only one branch while catalog/config handling has no case |
| Claim discipline | Actual static output, authored findings, deterministic results and live evidence separated | Schema validity or dry-run PASS described as effective activation |

The current frontmatter validator enforces a 50–1024 character description range; naming policy allows at most 64 characters. Keep required metadata and those limits. Length is a static format constraint, not a routing measure: a conformant short description is not defective because another is longer, and a long description is not effective because it contains more trigger phrases. Prefer distinct contexts and boundaries over synonym quotas. Preserve a description for explicit-only invocation and discover actual target-harness flag/router support; do not transplant another runtime's invocation assumptions.

## Conditional Reference and Configuration Examples

The following are synthetic review examples, not commands or files supplied by this package. Apply the evidence contract to the real audited package's local targets.

| Branch | Pointer/config discovery | Completion artifact/evidence | Adversarial distinction |
| --- | --- | --- | --- |
| CLI-backed export | “For CLI export, load `references/cli-export.md` before selecting flags; it defines output and error evidence.” Inspect the installed CLI's help/implementation and the project script selecting it. | Record sourced invocation, output artifact path, actual exit and artifact inspection when authorized; otherwise exact unexecuted prerequisite. | New CLI omits a flag cached in an old example: use current source, report incompatibility if needed, never invent success. |
| Config-only integration | “For config export, load `references/config-export.md` before choosing keys; it describes loader precedence and output evidence.” Inspect actual config and loader. | Record each active config source/key, precedence and resulting artifact or observed configuration effect; if no loader is available, identify that missing prerequisite. | CLI is absent but config/loader are available: do not require unrelated CLI setup or load its branch reference. |
| Either branch missing a prerequisite | Apply common authority/blocked handling, then the affected branch's local guidance if available. | Identify missing binary/config/loader/reference, affected outputs and completed independent work. | Absence is not a fallback implementation, completed side effect or measured routing failure. |

Reference integrity and loading behavior are separate: a local file can exist while its pointer gives no way to select it. An authored audit checks both. Auditing the CLI pointer does not establish the config branch is covered. Synonyms such as “export” and “dump” are one branch unless they require genuinely different inputs/actions/outputs.

## Type-Specific Criteria

Consult the section matching the audited definition type. Required machine fields come from the current registry/validators, not from this list of authored behavior questions. Inspect declared optional metadata only when it affects the promised contract; do not turn generic preferences into requirements.

### Skill (`SKILL.md`)

- Map model-discovery and explicit invocation promises to actual target-harness support, without removing required description metadata.
- Procedural skills need branch-specific actions, outputs and termination conditions. Reference-only skills need an exhaustive, checkable application criterion rather than a fake procedure.
- Evidence: branch-to-case matrix, local loading pointers and each promised output's evidence requirement.

### Agent (`AGENT.md`)

- Check required `model` and `color` and applicable declared metadata such as execution phase or language targets against current validators/configuration.
- Inspect decisions, allowed operations, phase transitions and completion/blocked handoff. Language-specific guidance is required only where the agent promises language-specific behavior.
- Evidence: each decision path terminates in an artifact, finding or explicit blocker; model/tool availability and authority limitations are recorded. Phase markers or a decision-tree heading alone do not demonstrate correct execution.

### Hook (`HOOK.md`)

- Check `hook.events`, handler type/command, local executable target and declared input/output protocol against actual schema/handler code.
- Inspect malformed input, timeout, cancellation and exit/side-effect semantics for the actual event. Never assume all events use the same nonzero/blocking convention.
- Evidence: sourced event/handler mapping and an artifact/exit/side-effect requirement per path; actual runtime proof only when safely authorized. A present handler is not proof it works, and an audit is not permission to fire it.

### Rule (`RULE.md`)

- Inspect declared scope/language applicability and concrete obligations. Each relevant rule needs an observable adherence/violation criterion, with examples where ambiguity warrants them.
- Use justified numeric limits only when the domain requires them; inventing thresholds is not a substitute for a checkable rule.
- Evidence: representative compliant/violating scenarios tied to actual constraints and applicability boundaries, not broad principles alone.

### Command (`COMMAND.md`)

- Check the `command` mapping and actual invocation/argument handling, supported modes, handler and target-harness configuration.
- Inspect missing/invalid arguments, decisions, permitted actions and termination conditions.
- Evidence: distinct argument/mode branches each map to an output/error artifact and case. Documented syntax does not establish that the runtime can invoke it.

### Utility (`UTILITY.md`)

- Check the `utility` mapping/runtime and any declared entry point or executable against actual local files and configuration.
- Inspect CLI/input protocol, dependencies, errors and output/side-effect contract. A stdlib-only implementation is not universally required; declared dependencies must be discoverable and handled.
- Evidence: sourced invocation, each output/error path and prerequisite/authority handling; runtime results only for inputs actually exercised.

### Preset (`PRESET.md`)

- Check the `preset` mapping/package entries against current manifest and installer representation; do not assume a top-level `packages` field satisfies the actual schema.
- Inspect compatibility, included package existence, intended combined workflow and configuration effect. Preset package identifiers are intentional bundle dependencies, not cross-package file-reference violations.
- Evidence: every declared entry resolved or explicitly missing, supported-target loading/configuration expectations and actual observations when authorized. Manifest membership is not proof that the bundle loaded.

## Severity and Reporting Calibration

1. Tie each finding to a specific source, branch and observable impact. CRITICAL/HIGH/MEDIUM/LOW prioritize authored repairs; they do not alter report-v2 statuses or produce a numeric grade.
2. Classify a demonstrated missing executable/distribution target or unsafe required action as CRITICAL; a missing promised branch, uncheckable completion, unusable required pointer or invented command/config as HIGH. Use MEDIUM for incomplete adversarial/adjacent coverage or ambiguous recovery, LOW for local clarity without a blocked contract.
3. Distinguish absent required data from sparse but valid metadata, optional preferences and lack of measured behavior. “Not measured” is an evidence limit, not automatic evidence of failure.
4. Account for all requested packages and each supported invocation branch. An unreadable target or unavailable reference remains an explicit unresolved entry, not silently dropped coverage.
5. When comparing packages, prioritize evidenced defects rather than assigning efficacy rankings from static inspection. Apply the same criteria to self-evaluation.
6. Keep one finding per underlying defect with all affected evidence/branches; do not inflate severity by repeating the same gap across headings.
7. Report commands/exit/artifact pointers only when observed. A blocked check receives an execution note, never a fabricated JSON report. Keep live_effectiveness NOT_MEASURED in actual evaluator output even when attaching separate valid behavioral evidence.

## Worked Interpretation (Synthetic)

A hypothetical package has valid required frontmatter, matching directory/name and parseable version, but promises both CLI and config exports while only documenting CLI flags.

- An actual report-v2 run could return static PASS and live NOT_MEASURED; no run is asserted here.
- Authored review records the missing config branch as HIGH with its description/body evidence and required config/loader/output contract.
- A CLI helper smoke, if separately authorized and observed, demonstrates only that invocation's artifact/result. It does not fill the config gap or demonstrate model routing.
- Completion requires accounting for both promised branches, sourcing current environment configuration and recording unexercised outcomes. Neither a static pass nor a more verbose description closes the finding.
