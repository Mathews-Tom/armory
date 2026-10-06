# Watch Dependencies and License Notices

## Evidence and Privacy Boundaries

Watch acquires timestamped captions, extracts bounded local frames, and optionally runs separately provisioned local speech transcription. Media analysis runs on the agent's execution machine. URL sources receive metadata, caption, and download requests; Watch does not upload video or audio to a media-analysis service. Evidence opened by the host assistant remains subject to that host's data policy.

Frame budgets include cue frames. Source-relative timestamps and focus boundaries are enforced, and sparse sampling is not exhaustive visual coverage. Downloader requests ignore ambient configuration and do not discover browser cookies. Caller-owned source files are preserved.

## Runtime Dependencies

- `youtube-transcript-api`: primary repository https://github.com/jdepoix/youtube-transcript-api; MIT. Retrieves published caption tracks, not visual or speech inference.
- `yt-dlp`: primary repository https://github.com/yt-dlp/yt-dlp. Provides metadata, one selected caption track, and bounded completed media downloads. The owning environment supplies the executable; no binary is redistributed.
- FFmpeg/ffprobe: external media tools, not redistributed. Their license is LGPL 2.1+ with optional GPL components depending on build; https://www.ffmpeg.org/legal.html documents the distinction. Extraction uses decoded source timestamps rather than guessed image labels.
- WhisperX 3.8.6: verified package metadata at https://pypi.org/pypi/whisperx/3.8.6/json; Python >=3.10,<3.14, BSD-2-Clause. Setup uses uv/Python 3.12. Torch, VAD, tokenizer, and speech-model artifacts retain their separate licenses and download terms. Provisioning is explicit; an ordinary invocation installs neither the environment nor a model.
