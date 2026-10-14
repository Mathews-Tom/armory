# appraise

`appraise` estimates the level a software engineer's Git repositories support, using evidence that can be checked. It has two parts. A standard-library Python engine (`scripts/appraise.py`) does the forensics and the calibration. The agent reads the code and records structured judgments. The level comes from rubric rules applied to verified evidence, never from prose.

## Install

The skill ships with Armory:

```bash
uv run scripts/install.py            # interactive; choose skills/appraise
# or copy the directory into ~/.claude/skills/appraise
```

Runtime requirements: `git` and Python 3.11 or newer. An authenticated `gh` is optional; it adds fork and template metadata, pull requests, reviews and CI status. The engine has no third-party Python dependencies.

## Quick start

```bash
RUN=$(mktemp -d)/run
python3 skills/appraise/scripts/appraise.py discover --repo ~/code/service --candidate github:octo --out "$RUN"
less "$RUN/sample-plan.md"                                                                    # what to read
python3 skills/appraise/scripts/appraise.py show --run "$RUN" --repo R1 --path src/service/store.py   # logged read
python3 skills/appraise/scripts/appraise.py grep --run "$RUN" --repo R1 'class .*Store'          # navigation only
cp "$RUN/judgments.template.json" "$RUN/judgments.json"   # fill in evidence and scores
python3 skills/appraise/scripts/appraise.py verify --run "$RUN"
python3 skills/appraise/scripts/appraise.py assess --run "$RUN"
```

Several repositories, a declared upstream, and promotion mode:

```bash
python3 skills/appraise/scripts/appraise.py discover \
  --repo ~/code/fork-of-lib --upstream R1=https://github.com/org/lib \
  --repo https://github.com/octo/tooling \
  --candidate github:octo,email:octo@example.com \
  --mode promotion --target-level staff --out "$RUN"
```

A worked synthetic example (inputs, judgments and every generated file) is in `examples/`.

## What is computed and what is judged

| Computed by the engine | Judged by the agent |
|---|---|
| Pinned revisions, read-only private mirrors | Which code shows which competency |
| Candidate identity across emails, logins and mailmap | Observation, interpretation and caveats per evidence item |
| Fork, template and upstream lineage; inherited vs. delta | Proposed 0–5 scores and their counterevidence |
| Line attribution of every cited span (`git blame`) | Strengths, weaknesses, risks and the development plan |
| Citation verification, permalinks and span hashes | Interview or reflection questions |
| Score caps, N/O reasons, bands, range, confidence, inconclusive | Assessor summary (cannot restate the level) |

## Schemas

`schemas/` holds JSON Schema 2020-12 documents for `input`, `forensics`, `judgments`, `evidence`, `assessment` and `rubric`. The engine validates every artifact it reads or writes with a standard-library validator (`scripts/appraisal/schema.py`); the tests cross-check that validator against the `jsonschema` library. Validate any file with:

```bash
python3 skills/appraise/scripts/appraise.py validate --schema assessment "$RUN/assessment.json"
```

## Tests

```bash
uv run python -m pytest skills/appraise/tests -q
uv run mypy --strict skills/appraise/scripts
```

The tests build deterministic synthetic repositories covering:

- solo, multi-contributor and alias cases;
- an unchanged fork, a dependency-only fork, a deep-refactor fork, upstream syncs and upstream contributions;
- a manual copy without shared history, template and host-declared forks, and an unreachable upstream;
- shallow clones, bots, vendored and generated code, merges and co-authors;
- prompt injection, fabricated citations, execution claims, challenges and self-reports;
- caps and bands, multi-repository runs, modes, reproducibility and recalibration.

## Limitations

- Non-Git snapshots are not supported: attribution needs history.
- GitHub is the only hosting provider adapter. Other hosts work as plain Git, with host signals recorded as unavailable.
- A copy with no declared upstream is only flagged (origin hints in the README, bulk-import commits). Separating inherited code from the delta requires `--upstream`.
- Blame credits the last author of a line. Reformatting commits can shift credit; `-w` ignores whitespace-only changes but not moved code.
- Collaboration evidence beyond commits comes only from GitHub pull requests and reviews in the analysed repositories.
- Repository evidence cannot reach the Distinguished level; it requires external corroboration artifacts.
- The rubric is a generic capability ladder, not any company's leveling framework.
