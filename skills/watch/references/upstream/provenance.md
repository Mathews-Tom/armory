# Watch Upstream Provenance

## Source

- Repository: https://github.com/bradautomates/claude-video
- Pinned commit: `03ceb42f7fa2c4439aca01752118044baabffb8f` (upstream release 0.3.2).
- License: MIT; copyright 2026 Bradley Bonanno. The upstream permission notice is preserved verbatim in `LICENSE` beside this record.
- Source concept demonstrated in https://www.youtube.com/watch?v=qSuCPooR3E4: question-driven native video analysis with a local frame/transcript alternative.

## What was vendored

The MIT notice is copied. Runtime modules are independently implemented; no upstream setup wizard, plugin manifest, or runtime module is copied wholesale. The timestamped-evidence workflow and privacy distinctions are adapted conceptually from upstream `skills/watch/SKILL.md`, `frames.py`, `download.py`, `transcribe.py`, and `gemini.py`.

## What was adapted

- Armory's existing transcript-analysis package is renamed to `watch`; the 2.0.0 major version records the package/CLI/output cutover.
- Existing concept-analysis patterns remain, extended to separate speech, inspected visuals, provider observations, and interpretation.
- Acquisition modules share one typed JSON evidence contract rather than introducing a second caption interface.
- Actual decoded frame times and focus boundaries are enforced independently. An upstream smoke run reported 02:28 outside a requested 02:00–02:25 interval; that behavior is not an accepted invariant here.
- Frame budgets include cue frames and remain bounded; cue overflow is explicit rather than silently omitting requested evidence.
- Gemini requires explicit invocation consent. Credentials are read only from the process environment; key availability never selects cloud processing.
- Local speech provisioning is explicit and isolated; an ordinary invocation neither installs models nor selects a cloud fallback.
- Downloader requests ignore ambient configuration and do not discover browser cookies. Source files and caller-owned directories are preserved.

## What was skipped

- Upstream marketplace/plugin packaging, host-specific setup wizard, Homebrew installation, configuration-file key lookup, and asking users to paste credentials into chat.
- Automatic Gemini selection from available credentials; automatic provider/engine switching.
- Uncapped “token-burner” sampling, fixed image-token pricing claims, guaranteed free analysis, universal website access, or claims of perfect video recognition.
- Groq/OpenAI speech backends, diarization, forced alignment, browser-cookie discovery, analytics collection, video generation, and a new wiki storage subsystem.
- Upstream benchmark figures as Armory performance claims. Google's comparisons concern its agentic versus static video processing, not this package's caption-only baseline.

## Runtime Dependency Verification

- `youtube-transcript-api`: existing Armory dependency; primary repository https://github.com/jdepoix/youtube-transcript-api and its MIT notice were checked. It retrieves published caption tracks, not visual or speech inference.
- `yt-dlp`: existing Armory dependency; primary repository https://github.com/yt-dlp/yt-dlp. The runtime uses metadata, one selected caption track, and bounded completed media downloads. The owning environment supplies the executable; no binary is redistributed.
- FFmpeg/ffprobe: external media tools, not redistributed. Their license is LGPL 2.1+ with optional GPL components depending on build; https://www.ffmpeg.org/legal.html documents the distinction. Extraction uses decoded timestamp evidence rather than guessed image labels.
- WhisperX 3.8.6: verified at https://pypi.org/pypi/whisperx/3.8.6/json, published 2026-05-25, Python >=3.10,<3.14, BSD-2-Clause. Setup uses uv/Python 3.12. Torch, VAD, tokenizer, and speech-model artifacts retain their separate licenses and download terms; not all runtime components are MIT.
- Gemini: optional native video service, not a vendored SDK. The Interactions and Files API contracts, public YouTube restriction, agentic/static distinction, and free-tier limits were checked against https://ai.google.dev/gemini-api/docs/video-understanding. Google's service/data-use terms remain separate from upstream MIT permission.

## Re-sync policy

Do not auto-sync. Compare candidate changes against the pinned commit; preserve the permission notice and Armory's explicit consent, ownership, frame-cap, and source-time invariants. Re-run package evaluation, contract tests, and real-media smoke scenarios before adopting upstream changes. Do not inherit provider pricing or quotas as durable guarantees.
