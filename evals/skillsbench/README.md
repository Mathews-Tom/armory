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

**Status:** frozen corpus registered; live execution remains deferred to the
operator. A meaningful run requires hours of live `claude -p` execution and
requires M4's recorded approval, budget, privacy posture, and receipt policy.

```bash
# Validate the frozen task × condition × target × repetition declaration.
uv run python scripts/run_skillsbench.py --validate-manifest

# Full declared corpus, dry-run (validates M2 target linkage and all task data
# without a model request).
uv run python scripts/run_skillsbench.py --dry-run

# One registered task, dry-run.
uv run python scripts/run_skillsbench.py --task task_001_code_review_simple --dry-run

# Full sweep, Config A only. Requires M4 approval before `--live`.
uv run python scripts/run_skillsbench.py --all --config A --live

# Operator workflow for comparison. Requires M4 approval before `--live`.
uv run python scripts/run_skillsbench.py --all --config A --live --output results/run-A.json
uv run python scripts/run_skillsbench.py --all --config B --live --output results/run-B.json
uv run python scripts/run_skillsbench.py --compare results/run-A.json results/run-B.json
```

## Task Set Scope

`corpus.yaml` freezes **50 registered tasks** before any comparison result
exists: the five retained seed tasks plus 45 inline tasks spanning development,
review, operations, research, and content work. It resolves the M2 declared
target (`claude-code-opus-xhigh`) and declares the `current`,
`reduced-or-rewritten`, and `strengthened-contract` conditions, three
repetitions, and explicit exclusions. The matrix therefore contains 450
declared cells.

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
