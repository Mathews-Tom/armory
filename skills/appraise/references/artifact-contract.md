# Artifact Contract

## Commands, statuses, exit codes

Every command prints a single JSON object.

| Command | Success status | Other statuses |
|---|---|---|
| `discover` | `READY` (0) | `NEEDS_CANDIDATE` (3), `BLOCKED` (5) |
| `show` | Prints numbered lines or the commit patch and appends the read to `show-log.jsonl` | `BLOCKED` (5) |
| `tree` | Prints analysed files: lines, candidate share, category, signals | `BLOCKED` (5) |
| `grep` | Prints `path:line:text` matches at the pinned revision; not logged as reading. Patterns are POSIX extended regular expressions (no PCRE such as `(?i)`). `--path` limits the pathspec; `--limit` (200) caps total lines and `--max-per-file` (20) caps matches per file, each with a notice when reached | `NO_MATCH` (0), `BLOCKED` (5) |
| `verify` | `VERIFIED` (0) | `INVALID_JUDGMENTS` (4), `BLOCKED` (5) |
| `assess` | `ASSESSED` (0) | `INVALID_JUDGMENTS` (4), `BLOCKED` (5) |
| `compare` | `COMPARED` (0) | `BLOCKED` (5) |
| `validate --schema NAME FILE` | `VALID` (0) | `INVALID` (4); `error_count` gives the total when only the first 50 errors are listed |

Usage errors exit 2 (argparse).

`discover` flags: `--repo` (repeatable), `--candidate`, `--display`, `--mode`, `--consent subject_informed`, `--target-level`, `--specialization`, `--domain`, `--rubric PATH`, `--depth`, `--output-format`, `--upstream R<n>=LOCATOR`, `--rev R<n>=REV`, `--artifact PATH::KIND`, `--offline`, `--input input.json`, `--out DIR`, `--now ISO`.

Depth budgets:

| Depth | Sample files | Sample commits | Read budget per item (lines) | Blamed files | Host identity lookups |
|---|---|---|---|---|---|
| `quick` | 10 | 5 | 150 | 1000 | 10 |
| `standard` | 24 | 12 | 400 | 2000 | 30 |
| `deep` | 48 | 24 | 1000 | unlimited | 60 |

## Run directory

| Path | Produced by | Schema |
|---|---|---|
| `input.json` | discover | `schemas/input.schema.json` |
| `forensics.json` | discover | `schemas/forensics.schema.json` |
| `sample-plan.md` | discover | Human and agent reading list |
| `judgments.template.json` | discover | Starting point for `judgments.json` |
| `mirrors/R<n>.git` | discover | Private bare mirrors; the only place history is read |
| `judgments.json` | you | `schemas/judgments.schema.json` |
| `evidence.json` | verify, assess | `schemas/evidence.schema.json` |
| `assessment.json` | assess | `schemas/assessment.schema.json` |
| `assessment.html` | assess | Self-contained visual report rendered from `assessment.json`, `evidence.json` and `forensics.json`. Strings are HTML-escaped; links are http(s) only; a Content-Security-Policy blocks network loads; the one inline script only filters evidence rows |
| `assessment.md`, `questions.md`, `limitations.md`, `changes.md` | assess | Rendered from `assessment.json` |

`run_id` is a hash of the normalized input and the pinned revisions, so `judgments.json` must carry the same `run_id`. `assessment_id` is a hash of everything except timestamps: identical forensics, judgments and rubric produce an identical id and identical Markdown (pass `--now` to pin `generated_at`).

## judgments.json field reference

The schema (`schemas/judgments.schema.json`) is authoritative; every object rejects unknown keys.

| Section | Required fields and patterns |
|---|---|
| top level | `schema_version` "1.0", `run_id` (copy from the template), `summary` (≤2400 chars), and all list sections below, even when empty |
| `inspected[]` | `repo` (`R1`…); plus `path` with optional `line_start`/`line_end`, or `commit`; optional `sample_id` (`S-R1-001`) |
| `evidence[]` | See `evidence-extraction.md`. `id` `E-001`…; kind-specific location fields |
| `competencies[]` | One per rubric competency: `id`, `score` (0–5 or null), `rationale`, `supporting_evidence_ids`, `counterevidence_ids`, `counterevidence_reviewed`, `confidence`; optional `not_observable_reason` |
| `strengths[]`, `confirmed_weaknesses[]`, `potential_risks[]` | `summary`, `evidence_ids` (≥1); optional `competencies`. A finding none of whose evidence verifies is dropped and recorded as a limitation. |
| `development_plan[]` (≥3) | `id` `P-01`…, `category`, `title`, `competencies` (≥1), `source_evidence_ids`, `why`, `action`, `success_criterion`, `effort` S/M/L, `priority` P1–P3, `horizon_days` 1–365 |
| `interview_questions[]` (5–10) | `id` `Q-01`…, `question` (≥10 chars), `competencies` (≥1), `evidence_ids`, `would_change` |
| `self_reports[]` | `id` `SR-01`…, `question_id` or null, `answer`, `competencies`, `contradicts_evidence_ids`, `corroborating_evidence_ids` |
| `challenges[]` | `evidence_id`, `claim` (not_authored, misinterpreted, outdated, other), `note` |

Evidence ids in any list may reference agent evidence (`E-…`), engine host records (`H-R1-…`) or self-reports (`SR-…`).

## Coverage semantics

- Each sample item has `read_budget` = min(item size, the depth's read budget). File size is in lines; a commit's size is its changed lines.
- A line counts as read only when `show` printed it (`show-log.jsonl`) **and** it lies inside a range declared in `inspected`. Declaring a range you did not print earns nothing, and printing a range you did not declare earns nothing. `show --commit` output is numbered like a file and accepts `--lines`; declare the commit range you actually read. A commit declared without a range is credited for everything `show` printed for it.
- `sample_coverage` is the mean over sample items of min(1, lines read / read_budget). For a commit, lines read are the patch lines `show --commit` printed.
- `sample_items_inspected` counts declared items; `sample_items_audited` counts items with at least one read line. When fewer are audited than declared, the `inspection_self_declared` limitation is recorded.
- `candidate_line_coverage` is the share of candidate-attributed surviving lines that were read, estimated proportionally per file. Below 10% it adds the `candidate_line_coverage_low` limitation.
- Coverage confidence uses the mean `sample_coverage` across repositories (high ≥ 0.8, medium ≥ 0.5).

## Key forensics fields

| Field | Meaning |
|---|---|
| `identity.matched[].match` | How an identity was linked: `declared_email`, `github_noreply`, `host_linked` (high confidence), `mailmap` (medium), `sole_contributor` (medium), `declared_name` (low) |
| `identity.unconfirmed_aliases` | Same display name or handle-like email with no corroboration; never credited |
| `lineage.relationship` | `none`, `host_fork`, `template`, `declared_upstream`, `local_upstream_remote` |
| `lineage.ancestry` | `shared_history`, `no_common_ancestor` (content baseline used), `unknown` (shallow or unavailable), `not_applicable` |
| `lineage.delta_kind` | `unchanged`, `dependency_only`, `docs_or_config_only`, `modified`, `substantial`, `unknown`, `not_a_fork` |
| `attribution.surviving_lines` | Blame totals at the revision: candidate, inherited, bulk_import, unknown |
| `attribution.role` | `exclusive_author`, `primary_author`, `significant_contributor`, `minor_contributor`, `upstream_contributor_only`, `none`, `unknown` |
| `attribution.attribution_confidence` | Identity confidence lowered one step for each of: shallow history, unavailable upstream, an undeclared-origin hint, a bulk-import share above 30%, or incomplete blame |
| `collaboration.opportunity` | `true` when other humans committed or the candidate reviewed others' PRs; `false` for solo history; `null` when host data was unavailable |
| `exclusions.counts` | Paths never used for authorship: vendored, generated, build_output, lockfile, minified, fixture, benchmark_result, data, binary |
| `host_evidence` | `H-R<n>-…` records the agent may cite: authored PRs, reviews of others' PRs, merged upstream PRs, CI check runs |
| `injection_flags` | Evaluator-directed text locations |
| `limitations` | Coded, with impact on attribution, coverage, lineage, collaboration, verification, identity or freshness |

## External integrations

| Integration | Needed for | Without it |
|---|---|---|
| `git` | Everything | `BLOCKED` |
| `gh` (authenticated) | Fork, parent and template metadata, linking emails to logins, PRs, reviews, check runs, private GitHub repositories | `--offline`: lineage needs `--upstream`; collaboration falls back to commit history (`access_limited` when a host exists but cannot be read) |
| Network | Remote locators and upstream fetches | Use local checkouts; declare a local upstream path |

## Organization rubrics

Copy `rubrics/software_engineering.json`, edit competencies, clauses and thresholds, validate it with `appraise.py validate --schema rubric FILE`, and pass it with `--rubric FILE`. A new domain is a new file named after `--domain`; the engine reads clause types (`at_least`, `none_below`, `min_distinct_scopes`, `min_distinct_repos`, `evidence_kind`) and needs no code change.
