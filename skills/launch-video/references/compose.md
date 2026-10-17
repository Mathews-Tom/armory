# Compose and render with html-video

The `html-video` package owns rendering: its pinned Hyperframes CLI, its static audit, its timing and motion contract, and its delivery bundle. This file maps a launch plan onto that contract. Load the `html-video` skill and use its commands; never run Hyperframes through `npx` or substitute another renderer.

## 1. Create the composition

- Use html-video's `init` with the `title-sequence` template and destination `RUN_DIR/composition`. Replace its three beats with the storyboard's scenes.
- **Format.** Templates are 1920x1080. For vertical (1080x1920) or square (1080x1080), change the root's `data-width` / `data-height`, the `#root` CSS width and height, and the viewport `<meta>` together.
- **Duration.** Set the root `data-duration` to the storyboard total; it must equal the last clip's end.
- **Fonts.** Provision the font files the user supplied with html-video's `fonts add`, recording their licence. Prefer the project's own display and body fonts when the user can supply those files and their licences. When they cannot, use the supplied font and record the substitution in the plan. One variable font file covers several weights with `--weight "100 900"`; with a single static file, design for the weight you have rather than relying on synthesised bold. Never fetch a font.
- **A second family** (a monospace for terminal or code, a separate display face) needs its own `--alias`, for example `--alias "HV Code"`, on every `fonts add` for that family, then `font-family: "HV Code"` in the CSS. `--family` is only the provenance name: without `--alias`, the file is added as another face of the template alias `HV Text` and silently replaces or overlaps the body font.
- Run html-video's `bootstrap` once for the composition.

## 2. Scenes are clips

Every element on screen is a clip with a unique `id`, `data-start` and `data-duration` (seconds, or relative to another clip's id). A scene is a group of clips sharing a time window. Keep each top-level clip single-level (text, or an element without block children) so lint stays clean; build a card from sibling clips positioned together rather than one clip with nested blocks.

## 3. Motion is finite CSS keyframes

html-video seeks finite CSS keyframes on HTML elements with `animation-fill-mode: both`. No GSAP, no CDN script, no wall-clock timers, no unseeded randomness, no `infinite` iterations, no CSS transitions, and no animated SVG children. Every frame must be a pure function of time.

| Plan says | Build it as |
|---|---|
| Staggered crossfade | Old scene's clips fade out (`opacity 1→0`), then the new scene's clips fade in. Overlap at most 0.1s. A plain crossfade between two busy layouts makes a muddy double exposure. |
| Fade through background | Old out, 0.1–0.2s of background only, new in |
| Slide / wipe | `transform: translateX()` keyframes, or `clip-path: inset()` from one edge |
| Hard cut | Adjacent clip windows with no entrance or exit animation. If the incoming scene must enter, move it in (`translate`, `clip-path`) rather than fading from `opacity: 0`: `snapshot` samples cut boundaries, and an opacity-zero entrance leaves the whole frame empty there. |
| Flash | A full-frame accent or white clip lasting 0.1–0.15s between scenes |
| Zoom | `transform: scale()` keyframes on the incoming or outgoing clip |
| Typing | `clip-path: inset(0 100% 0 0)` → `inset(0 0 0 0)` with `steps(N)`, N = character count |
| Simulated click or swipe | A cursor clip moved with `transform` keyframes, then a pressed state on the target via a second keyframe |
| Count-up | Separate clips per displayed value in short consecutive windows, or a `steps()` strip of numbers clipped to one cell |

Keyframe delays are relative to the clip's own `data-start`.

## 4. Show the real thing

Recreate the project's real screens as static HTML and CSS using its exact copy, colours, spacing and fonts. Copy the project's own logos, icons and images into `RUN_DIR/composition/assets/project/` and reference them relatively. Do not load the project's JavaScript bundle or a dev server: the audit rejects remote resources, and arbitrary scripts are neither seek-safe nor network-isolated.

Declare every copied file in the composition's `PROVENANCE.json` (`path`, `source`, `license`). For the user's own project, `source` is the project-relative path or the repository URL, and `license` is the project's declared licence, or `user-owned` when the user confirms they hold the rights. Ask when the rights are unclear; never guess a licence.

Images the project only references remotely (stock-photo or CDN URLs) are not project files, and owning the project does not grant rights to them. Ask the user for a local copy with its source and licence and declare it like any other asset. Without one, leave the image out, design the scene around the project's own copy and UI, and note the omission in the plan. Never fetch it yourself.

### Terminal projects

For a command-line tool, the terminal is the product in use. Recreate a terminal panel in the monospace alias and show the command, its real output, and the line that proves the point.

- Use output the project itself documents, verbatim. When you shorten a path, drop lines or wrap a long line to fit, label the panel on screen (for example "README excerpt, trimmed") and say so in the plan. Run the tool to capture fresh output only when the user asks, and then show only what it printed.
- Terminal text is the hardest thing in the video to read on a phone. Keep it no smaller than the body copy (about 40px at 1920 wide), show at most six lines per scene, and crop or split output rather than shrinking it.
- Reveal it in the order a user sees it: type the command, then the output, then highlight the line that matters with the accent colour.
- The brand banner, logo and install command make the outro; copy them from the project's assets with the project's licence.

## 5. Audio (only user-supplied)

This package bundles no music or sound effects. When the user supplies a track:

1. Copy it into `assets/audio/` and declare it in `PROVENANCE.json` with its real `source` URL and SPDX `license` (for example `CC-BY-4.0`). Add the licence text as `license_file` when the user has it.
2. Add one clip inside the root: `<audio id="music" src="assets/audio/track.mp3" data-start="0" data-duration="TOTAL" data-track-index="20" data-volume="0.35"></audio>`.
3. Volume posture: 0.3–0.4 for a normal bed, 0.12–0.22 for deadpan or restrained parody, never above 0.5. Short effects, if the user supplies them, sit at 0.55–0.85 and stay sparse; repeated small sounds stay quiet.

With the pinned toolchain, an `<audio>` clip renders into an AAC track and `data-volume` scales its level (0.5 measured as −6 dB). `finish` refuses a silent MP4 when the composition declares audio. Fades and audio-reactive visuals are not part of this contract.

If the track is CC BY (any `CC-BY-*` licence), the share copy must credit it; see `deliver.md`.

## 6. Prove the timing

Write `index.motion.json` next to `index.html` from the storyboard:

- One `appearsBy` per line a viewer must read, at the time its entrance completes plus at least 0.1s. `check` samples on a frame grid and reports a hard-cut line as appearing a few hundredths of a second after its `data-start`, so a deadline exactly at the start fails.
- `before` assertions for the storyboard order of scene headlines.
- `keepsMoving` with `maxStaticSec` matching the tone: about 2 for `default` and `chaotic`, up to 4 for `polished` and `deadpan` holds. An always-moving decoration such as a progress rail satisfies this assertion on its own, so it proves nothing about the "make it alive" law; judge the scenes' own motion on the contact sheets instead of adding decoration to pass.

Then run, in order, with html-video: `audit` with provenance required, `run lint`, `run check`, `run snapshot`. Read the coverage fields html-video's skill requires and open **every** contact-sheet page. A green `check` does not catch every visual problem: its contrast proof covers only the pairs it counts in `contrast.checked`, and overlapping shapes can pass layout. Judge each sampled frame against the creative laws yourself: overflow, collisions, the contrast of every readable line, text that leaves before it can be read, and double exposures at transitions. Fix and re-run until clean, then `run render` and `deliver` with `--out RUN_DIR/delivery`.
