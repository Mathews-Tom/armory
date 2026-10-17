# Share copy, poster and finish

## Share copy

Write `RUN_DIR/share-copy.txt` before running `finish`.

- One to three sentences, postable as-is to X, LinkedIn or Discord.
- Specific to the project, in its own words, matching the tone. No "excited to share", no "streamline your workflow".
- One canonical caption. Put platform variants, if useful, in `share-copy-variants.md`.

| Tone | Shape |
|---|---|
| `default` | `Made [Name]. It's [what it does, in the project's own terms]. [Best line from the product.]` |
| `polished` | `Introducing [Name]: [clean one-liner from the project]. Built with [stack, if notable].` |
| `yc-parody` | `We built [Name] to solve [problem stated completely seriously]. [Deadpan feature or stat from the project.]` |
| `chaotic` | `[ALL CAPS CLAIM]. [Name] is [wildly overstated description of what it really does].` |
| `deadpan` | `I made [Name]. It [what it does].` |
| `cinematic` | `[Name]. [Tagline from the project, verbatim or lightly adapted.]` |
| `app-store` | `[Name] is now live. [Feature 1], [Feature 2] and [Feature 3], all in one place.` |

### Credit line

Creative Commons BY licences require attribution wherever the video is shared. For every asset whose `PROVENANCE.json` licence starts with `CC-BY-`, end the share copy with a credit line that contains the asset's recorded `source` exactly and its licence id, written either spaced (`CC BY 4.0`) or as the SPDX id (`CC-BY-4.0`); both pass:

```text
Music: "Track Title" by Creator Name (https://example.org/track), CC BY 4.0.
```

`finish` fails with `credit_missing` until every such asset is credited. It checks the source and licence, not the creator name. Write the creator name as the source page gives it.

## Poster frame

Platforms take their idle thumbnail from frame 0, and several regenerate it server-side, ignoring cover-art metadata. The poster must therefore be frame 0 itself.

Pick the strongest **settled** moment from the storyboard: the hook line, the hero reveal or the final name, after its entrance finishes and before its exit starts. Check the contact sheets to confirm nothing is mid-transition at that time.

```bash
python3 "$SKILL_DIR/scripts/launch_video.py" finish RUN_DIR --poster-at 3.2
```

`finish`:

1. Verifies `RUN_DIR/delivery` against its `RENDER.json` digest.
2. Checks the duration window (15–25s by default), that a composition with `<audio>` produced an audio track, that the poster time is inside the video, and the credit lines.
3. Extracts `poster.jpg` at `--poster-at`, then replaces only frame 0 of the render with it. Frame count, frame rate, dimensions, duration and audio are preserved and re-verified, and frame 0 must match the poster at 30 dB PSNR or better.
4. Writes `launch.mp4`, `poster.jpg`, `CREDITS.txt` (every declared asset, credit-required ones marked) and `LAUNCH.json` (input digests, poster time, probe, outputs).

Outputs are staged and only replace earlier ones when every check passes. If the poster lands mid-animation, change `--poster-at` by a few tenths of a second and run `finish` again.

## Tell the user

Report:

- `RUN_DIR/launch.mp4` and `RUN_DIR/poster.jpg` (the custom thumbnail for platforms that accept an upload).
- The share copy, verbatim.
- One sentence on the creative angle and the tone used.
- Every asset licence from `CREDITS.txt`, and any credit the user must keep when reposting.
- Any fictional stand-ins substituted for real data.
- The offer to re-roll a scene or try another tone.
