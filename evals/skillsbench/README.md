# SkillsBench — Bootstrap Benchmark for Memento-Skills Integration

**Purpose:** quantify whether armory's curated skill library provides a real
efficacy advantage over a primitives-only baseline equipped with the
`skill-librarian` write loop. This is the kill-switch experiment for the
Memento-Skills integration (see `MEMENTO_SKILLS_PLAN.md` Phase 4).

## The Experiment

Two configurations run the same task set:

| Config   | Packages loaded                                           | Librarian | Router |
| -------- | --------------------------------------------------------- | --------- | ------ |
| **A**    | Full armory (106+ packages)                               | Passive   | Active |
| **B**    | Primitives only: `web-fetch`, `bash`, `filesystem`, `tavily` | Active    | —      |

Config A measures the curated library's zero-shot performance.
Config B measures what the write loop can grow from scratch on the same tasks.

**Exit criterion (S3 in the plan):** Config A must beat Config B by ≥15
percentage points on pass rate. If Config B converges toward Config A, that
is itself a validation signal for the curation effort — document it.

## Layout

```
evals/skillsbench/
├── README.md          # this file
├── schema.yaml        # task YAML schema reference
├── tasks/             # seed task set (expand before full runs)
│   ├── task_001_*.yaml
│   └── ...
└── results/           # per-run output (gitignored)
    └── YYYY-MM-DD-run-N.json
```

## Running the Benchmark

**Status:** M4's no-cost OMP input, receipt, and dispatcher preflights are
available. They validate the frozen two-target matrix, reviewed treatment
materialization, derived-receipt schema, and all 900 isolated command shapes
without a model request. Live execution remains unavailable until a fresh M4
design gate authorizes the reviewed dispatcher.

```bash
# Validate the frozen corpus and package strata.
uv run python scripts/run_skillsbench.py --validate-manifest
uv run python scripts/validate_skillsbench.py

# Validate the 900-cell OMP subscription contract without a model request.
uv run python scripts/omp_skillsbench.py --preflight

# Materialize reviewed treatment inputs and validate immutable receipt handling.
uv run python scripts/omp_skillsbench_results.py --preflight

# Validate all 900 isolated OMP command shapes without starting OMP.
uv run python scripts/omp_skillsbench_dispatch.py --preflight

# Legacy harness dry-run: validates M2 target linkage and task data only.
uv run python scripts/run_skillsbench.py --dry-run
```

## Task Set Scope

`corpus.yaml` freezes **50 registered tasks** before any comparison result
exists: the five retained seed tasks plus 45 inline tasks spanning development,
review, operations, research, and content work. It resolves the M2 declared
target (`claude-code-opus-xhigh`) and declares the `current`,
`reduced-or-rewritten`, and `strengthened-contract` conditions, three
repetitions, and explicit exclusions. The M3 declaration contains 450 cells.
`omp_run.yaml` expands those conditions over pinned Claude and Codex OMP targets
into the M4 900-cell subscription matrix without running a model.

The legacy seed task files remain directly loadable for focused harness tests.
Their assertion criteria remain useful for prose deliverables. Tasks whose
intended deliverable is an artifact use artifact-aware validation rather than
final-answer prose checks.

`package_strata.yaml` records one active, high-risk-relevant sample for each
of the seven package types and an explicit rationale for every other package's
exclusion. `uv run python scripts/validate_skillsbench.py` rejects duplicate,
missing, undeclared, deprecated-included, and incomplete-type classifications.

## What This Does Not Measure

- **Cost efficiency** — token and time totals are logged but are not part of
  the pass/fail criterion.
- **Semantic artifact quality** — artifact criteria verify existence and
  declared content checks, not correctness beyond those deterministic checks.
- **Librarian drafting quality** — the librarian's drafted skills during
  Config B runs are captured but their correctness is not benchmarked here.
  That belongs to `package-evaluator`, not SkillsBench.

## Gotchas

- **Worktree isolation is required for Config B.** The librarian writes new
  skill files during the run. Without worktree isolation, those writes
  contaminate the live repo. The harness spawns `claude -p` inside a fresh
  worktree per task.
- **Non-determinism.** A single run per task is not a verdict — the plan
  specifies median of 3 runs. The harness supports `--runs N` for this.
- **Context window.** Long tasks may exceed the default context limit. The
  harness fails such tasks loudly rather than silently truncating.

## Reference

- `scripts/run_skillsbench.py` — harness implementation
- `scripts/build_router_index.py` — Config A router index (must be fresh)
- `agents/skill-librarian/AGENT.md` — Config B write-loop agent
- `MEMENTO_SKILLS_PLAN.md` Phase 4 — exit criteria and analysis plan
