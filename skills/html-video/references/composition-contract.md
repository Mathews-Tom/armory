# Composition contract

What a renderable composition must declare, and why this package chose finite CSS keyframes for motion. Statements marked *source* were read in the Hyperframes source (commit `2fbaef6abb5207b6f9ef3ba0d94320a6b082fc95`, the snapshot behind the pinned release); statements marked *observed* were seen while exercising the bundled templates with the pinned CLI.

## How motion is seeked

Rendering asks for one frame at a time and never plays the page. For each frame the runtime computes `t = frame / fps` with integer math and seeks every registered animation to `t`.

- *source* The runtime ships a `css` adapter. It discovers elements whose computed `animation-name` is not `none`, finds their browser `CSSAnimation` handles, sets `currentTime` and pauses them. The clip-local time is `max(0, t - start)` where `start` is the `data-start` of the nearest `[data-start]` ancestor (or the element itself).
- *source* Where no live handle exists (for example a clip that is not displayed yet), the adapter pauses and shifts `animation-delay` negatively to reach the same pose.
- *source* Discovery accepts only elements in the XHTML namespace. **SVG child elements are never seeked**; animate an HTML wrapper or build shapes from HTML boxes.
- *source* Only `CSSAnimation` handles are driven. CSS transitions run on the page clock and are not seeked, so the audit warns on them.
- *source* Infinite or unresolved iteration counts have no end the runtime can infer; the audit rejects `infinite`. Use a finite count that covers the visible time.
- *source* `data-no-timeline` on the composition root tells the engine not to wait for `window.__timelines[id]`; without it a timeline-free composition waits out the readiness timeout on every render. CSS-animation compositions are the documented case for this attribute.

These facts make native CSS keyframes a supported, dependency-free path. No GSAP, CDN script, or custom adapter is needed, and nothing in the templates loads a remote resource.

## Declarations the audit enforces

| Item | Rule |
|---|---|
| Root | `data-composition-id`, `data-start="0"`, `data-width`, `data-height`, `data-duration` |
| Dimensions | Positive integers, at most five digits; odd values warn |
| Duration | Plain finite decimal greater than 0 (no exponent, `NaN`, or `Infinity`) |
| Clip | Unique `id`, `data-start`, and `data-duration` (media may omit duration) |
| Start | Number >= 0, or `otherId`, `otherId + n`, `otherId - n`; unknown ids, cycles and negative results are errors |
| Bounds | A clip starting at or after the end, or ending after it, warns |
| Timeline | `data-no-timeline`, or a script that registers `window.__timelines` |
| Viewport meta | If present, must agree with the declared dimensions |

## Motion sidecar

`check` runs motion assertions from `index.motion.json` next to `index.html` (*source*). Supported kinds: `appearsBy` (selector reaches opacity 0.5 by `bySec`), `before` (a appears before b), `staysInFrame`, and `keepsMoving` (optional `withinSelector`, `maxStaticSec`). Selectors must each match one element. Without a sidecar `motion.enabled` is false, which this package treats as unproven for an animated composition.

## Lint behaviour worth knowing

- *observed* A top-level clip containing nested block elements raises `nested_structure_needs_subcomposition`. Bundled templates keep each clip single-level so lint is clean.
- *observed* More than three timed elements on one track raises `timeline_track_too_dense`; elements whose class is `caption-cue` are exempt, and captions must share one track.
- *observed* A zero-height absolutely positioned box stretched to the bottom of the frame. Give shapes real dimensions; the arrowheads use `clip-path`.
- Negative `z-index` can hide behind an opaque parent; the templates set `isolation: isolate` on the root.

## Sampling

*source* `check --at-transitions` collects boundaries from objects registered on `window.__timelines` only. A CSS-only composition therefore passes explicit `--at` times. `plan` produces them: both ends, each clip start and end with one frame before and after, and clip midpoints, snapped to the frame grid. `check` reports sample times rounded to three decimals, so the coverage test allows a 0.001 s tolerance.
