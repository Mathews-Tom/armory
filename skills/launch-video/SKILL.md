---
name: launch-video
description: 'Turn the project in the current directory into a 15-25 second launch video: a project-specific story, real UI recreated in HTML/CSS, optional user-supplied music, a poster baked into frame 0, and postable share copy with any required credits. Rendering goes through the html-video package. Triggers on: "/brag", "let''s brag about this", "make a launch video", "launch video for this project", "turn this project into a video", "promo video for what I built". NOT for explaining a concept, algorithm or topic with no project behind it, use animate; NOT for an explicit React or Remotion composition, use remotion-video; NOT for an HTML video whose content is already scripted, use html-video.'
metadata:
  version: 1.0.0
  category: visualization
  tags: [video, launch, promo, share-copy, storyboard, hyperframes]
  difficulty: intermediate
  complements:
    - html-video
    - linkedin-post-style
---

# Launch Video

You built it; now show it off. This skill owns the story: what the project is, the angle, the storyboard, the tone, the share copy and the poster. The `html-video` package owns rendering: the pinned Hyperframes CLI, the asset audit, timing proof and the delivery bundle. Adapted from latent-spaces/brag (MIT); see `references/upstream/provenance.md`.

## When to Use

| Request | Fit |
|---|---|
| "Make a launch video for this project", "/brag", a promo of what the user built | Use this skill |
| Re-roll one scene or try another tone on an earlier run | Use this skill: `start` a new run, copy the earlier `launch-plan.md` and `composition/` into it, run html-video's `doctor` (re-`bootstrap` if it fails), edit, and continue from step 5 |
| A scripted title sequence, comparison or caption video in HTML | `html-video` |
| An algorithm, maths or concept explainer | `animate` |
| A React or Remotion composition | `remotion-video` |
| Analysing an existing video | Not this skill |

## Prerequisites

`SKILL_DIR` is the absolute directory containing this file. Its script needs Python 3.12+ (standard library only) and FFmpeg with ffprobe on `PATH`.

- **The `html-video` package must be installed.** If it is not, stop and report `BLOCKED: install html-video`; never fall back to `npx hyperframes` or another renderer. Rendering also needs everything html-video lists (Node, a Chrome or chrome-headless-shell executable).
- **A font file and its licence from the user.** html-video refuses system and downloaded fonts. Ask for the project's own display and body font files when it has them.
- **Music is optional and user-supplied.** This package bundles no audio, images or fonts. Ask for the track, its source URL and its licence; never download one.

Options, as flags or plain language:

| Option | Default |
|---|---|
| `--tone <preset or freeform>` | inferred; presets in `references/tones.md` |
| `--format landscape\|vertical\|square` | landscape 1920x1080 (vertical 1080x1920, square 1080x1080) |
| `--duration <seconds>` | 18–22, always within 15–25 unless the user sets it |
| `--title <text>` | inferred from the project |
| `--music <file>` | none |

When the user points at one part (a new feature, a new version, one angle), make that the focus.

## Workflow

1. **Start a run.** `python3 "$SKILL_DIR/scripts/launch_video.py" start` prints `RUN_DIR`: `launch-output/`, or a timestamped sibling when that already exists. Every file of this run lives there; earlier runs are never overwritten.
2. **Inspect.** Follow `references/inspect.md`: read the project in priority order, skip secrets, and answer the nine-question rubric in writing. A CLI's documented terminal output counts as its UI; stop and ask only when the project has neither visual nor documented output.
3. **Plan.** Write `RUN_DIR/launch-plan.md` per `references/plan.md`: the angle, hook, 2–3 highlights, punchline, tone, assets with licences, and a storyboard whose scene durations sum to the target. Plan every readable line's hold time.
4. **Collect inputs.** Get the font files and licences, the optional music track with source and licence, and confirm the rights to any project asset whose licence is unclear.
5. **Compose and render with html-video.** Follow `references/compose.md`: `init` the `title-sequence` template into `RUN_DIR/composition`, `fonts add`, `bootstrap`, author the scenes as CSS-keyframe clips, declare every asset in `PROVENANCE.json`, write `index.motion.json` from the storyboard, then `audit`, `run lint`, `run check`, `run snapshot`. Open every contact sheet and fix what fails the creative laws before `run render` and `deliver --out RUN_DIR/delivery`.
6. **Write the share copy.** `RUN_DIR/share-copy.txt` per `references/deliver.md`, including a credit line for every `CC-BY-*` asset.
7. **Finish.** `python3 "$SKILL_DIR/scripts/launch_video.py" finish RUN_DIR --poster-at SECONDS` with the strongest settled moment. It verifies the delivery, bakes the poster into frame 0 and writes `launch.mp4`, `poster.jpg`, `CREDITS.txt` and `LAUNCH.json`.

## Creative Laws

These apply to every tone.

- **Short.** 15–25 seconds; 18–22 is the sweet spot.
- **Clear to a stranger.** After one viewing, someone who has never heard of it knows what it does, who it is for, and how to get it. Lead with that, not with how it is built.
- **The hook is everything.** The first 2 seconds decide whether anyone keeps watching. Plan it first.
- **Show the thing.** At least one scene shows real UI, copy or a key visual from the project. Prefer the working product doing its job over a landing page describing it. Never abstract filler.
- **Specific.** Use the project's own copy and claims. "Streamline your workflow" and other generic SaaS language are banned. No invented numbers, testimonials or logos.
- **Readable.** Pace comes from motion and cuts, not from pulling text early: about 0.8s settled for a short label, 0.3s per word for a sentence.
- **Make it alive.** Things that appear one by one, simulated clicks, swipes and typing beat static slides.
- **Funny earns its place.** Humour comes from the project's own absurdity, not from trying.
- **Every frame postable.** Any frozen frame should be worth sharing, including mid-transition.

## Output

`RUN_DIR` contains `launch-plan.md`, `composition/` (the editable html-video project), `delivery/` (html-video's verified bundle with `RENDER.json`, reports and snapshots), `share-copy.txt`, and from `finish`: `launch.mp4`, `poster.jpg`, `CREDITS.txt` and `LAUNCH.json`.

Report to the user: the `launch.mp4` and `poster.jpg` paths, the share copy verbatim, one sentence on the angle and tone, the asset licences from `CREDITS.txt` and any credit they must keep when reposting, any fictional stand-ins, the html-video coverage numbers you read and the contact-sheet frames you judged, and an offer to re-roll a scene or try another tone.

## Error Handling

`finish` writes nothing unless every check passes.

| Code or symptom | Cause | Fix |
|---|---|---|
| `render_record_missing`, `video_missing` | No html-video delivery in `RUN_DIR/delivery` | Run html-video's `deliver --out RUN_DIR/delivery` |
| `video_digest_mismatch` | The delivered MP4 changed after delivery | Re-run html-video's verification and `deliver` into a fresh directory |
| `duration_out_of_range` | Render outside 15–25s | Retime the storyboard, or pass `--min-seconds` / `--max-seconds` when the user asked for another length |
| `audio_missing` | The composition declares `<audio>` but the MP4 has no audio track | Check the clip's `src`, `data-start` and `data-duration`, then re-render |
| `credit_missing` | A `CC-BY-*` asset is not credited with its source and licence | Add the credit line to `share-copy.txt` |
| `poster_out_of_range` | `--poster-at` is past the last frame | Pick a time inside the video |
| `bake_mismatch`, `poster_not_baked` | The re-encode changed timing or frame 0 does not match the poster | Report the message; do not ship the un-baked render as `launch.mp4` |
| html-video `check`: "appears at 3.01s but should be visible by 3s" | `appearsBy` deadline set exactly at a clip's start | Set each deadline at least 0.1s after the entrance completes (`references/compose.md`) |
| html-video not installed | Missing renderer | Stop `BLOCKED: install html-video` |
| No visual surface in the project | Backend or library with no UI, no documented output and no brand assets | Ask the user what to show; do not invent UI or output |

## Reference

- `references/inspect.md`: what to read, the nine-question rubric, the skip list and the private-data rule
- `references/plan.md`: plan structure, scene counts, duration, reading time, what to show, transitions
- `references/tones.md`: the seven tone presets (vendored verbatim)
- `references/compose.md`: mapping the plan onto html-video clips, CSS keyframes, assets, audio and motion proof
- `references/deliver.md`: share copy, credit lines, poster choice and `finish`
- `references/upstream/provenance.md` and `references/upstream/LICENSE`: upstream source, adaptations and licence
