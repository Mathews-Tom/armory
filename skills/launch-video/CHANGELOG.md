# Changelog — Launch Video

## 1.0.0

- Add the package: turn the current project into a 15–25 second launch video with a project-specific story, storyboard, tone presets, poster frame and share copy. Creative direction adapted from latent-spaces/brag (MIT) at `069432c`; `references/tones.md` is vendored verbatim.
- Render through the `html-video` package's pinned Hyperframes toolchain and finite-CSS-keyframe contract; never `npx`, GSAP or external Hyperframes skills.
- Bundle no media. Music is user-supplied and declared in `PROVENANCE.json`; `CC-BY-*` assets must be credited in the share copy.
- Add `scripts/launch_video.py`: `start` creates a non-reused run directory; `finish` verifies the html-video delivery digest, duration window, audio presence, poster time and credits, bakes the poster into frame 0, re-verifies frame count, rate, dimensions, duration and audio, confirms frame 0 matches the poster by PSNR, and writes `LAUNCH.json`. Outputs are staged and only replace earlier ones on success.
- Add evaluation cases and tests for credits, run-directory creation, the frame-0 bake and every refusal path.
