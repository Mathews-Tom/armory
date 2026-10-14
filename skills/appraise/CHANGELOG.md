# Changelog — appraise

## 1.0.0

- Discovery, which is deterministic and read-only:
  - private bare mirrors and revision pinning;
  - email-keyed identity resolution, corroborated by host login, mailmap or a GitHub noreply address;
  - fork, template and declared-upstream lineage, with shared-history and content-baseline analysis;
  - blame-based line attribution with shallow-boundary and bulk-import handling;
  - path exclusions;
  - stratified sampling: manifest-declared entry points, Python import centrality, signals, subsystems and history bins;
  - evaluator-directed text flags;
  - AI co-author and AI-mention counts.
- Evidence verification:
  - rejects fabricated paths, lines, commits and artifacts;
  - computes span attribution, recording every cap in `attribution_basis`, plus permalinks and span digests;
  - downgrades execution claims that have no log;
  - resolves challenges and self-reports.
- Coverage auditing: `show` logs every read. A line counts only when it was both printed and declared, and is weighed against each sample item's read budget. `tree` and `grep` navigate without counting as reading.
- Rubric-driven calibration:
  - not-observable reasons;
  - evidence-threshold caps, where `repository_claimed` items are never independent sources;
  - technical band and scope/influence band, the latter with `partial` status;
  - conservative overall level, with an evidence-bounded plausible range in which medium confidence reaches at most one level above;
  - factorised confidence, inconclusive triggers and target-level comparison;
  - every level rule carries a plain-language `explanation`. The determination, next-level blockers and confidence note are written in plain words, so the report states why a level was reached, what blocks the next one, and why confidence is what it is.
- Modes `review`, `self`, `promotion` and `manager` (consent-gated); multi-repository runs; recalibration and longitudinal `compare`.
- Contributor-aware discovery for large third-party repositories:
  - declared GitHub handles are linked through the commit-author API, so the candidate is never missed among hundreds of identities;
  - files the candidate touched are blamed first, and only skipped candidate files lower confidence;
  - an undeclared-origin hint lowers confidence only when the candidate made the initial or bulk import;
  - the sample narrows to files with at least five candidate-authored lines;
  - a file the candidate touched but blame skipped shows an unknown share, not 0%.
- A weakness cited on the same span as a strength stays a separate item; citations of merged duplicates resolve to the kept item.
- `show --commit` prints author and committer names only and redacts emails in trailers.
- JSON Schemas for input, forensics, judgments, evidence, assessment and rubric. Markdown and a self-contained, offline `assessment.html` (level scale, competency bars, decision trace, filterable evidence register, repository forensics; light/dark, mobile, print) are rendered from the JSON. A reproducible synthetic example is in `examples/`.
