# Changelog — Watch

## 3.0.0

- BREAKING: remove the cloud video-analysis backend, its CLI and Python options, and the cloud-answer field from evidence JSON. Watch supports only local and transcript evidence engines.
- Retain timestamped captions, bounded frame inspection, focused cue extraction, and explicitly provisioned local speech transcription.
- Remove repository links, source pins, upstream skill references, and the third-party notice and attribution entry.
- Update local-only workflows, evaluation cases, output templates, generated adapters, and the package catalog.

## 2.0.0

- BREAKING: rename the package to `watch`; replace the transcript fetch/scaffold CLIs with `scripts/watch.py` and a shared evidence record. Update routing, profiles, discovery handoffs, evaluation registration, and generated catalogs rather than retaining an old-name alias.
- Preserve quick/standard/deep concept analysis; add question-first answers and source-linked notes grounded in speech and inspected visuals.
- Add bounded local scene/keyframe sampling, explicit cue frames, actual decoded source timestamps, focus intervals, resolution controls, and a deduplication opt-out.
- Keep caption-only requests free of unnecessary media downloads. Preserve available evidence when another modality fails; expose actual caption provenance, language, and evidence gaps.
- Preserve whitespace-only VTT payload lines and normalize word-timed display-hold transitions without removing ordinary adjacent repetitions. Bound FFmpeg reads even when a cue falls between frames and produces no image.
- Add separately provisioned, offline local WhisperX speech recognition. Ordinary invocations do not install models or upload audio.
- Add regression coverage for source-time/pixel alignment, nonzero media starts, frame budgets, caption normalization, private file ownership, and silent focus intervals.
- Make PR quality and eval-coverage checks rename-safe: fetch base history and validate surviving changed definitions instead of removed packages.
- Document runtime dependency terms.
