# Changelog

## 1.3.1

- Rename the optional Manim video consumer to `animate` (2.0.0) in the Tier 3 video options and evaluation cases. Explicit engine requests still outrank subject suggestions and every companion stays optional for text-only posts.

## 1.3.0

- Add `html-video` (HTML and CSS rendered with Hyperframes) as an explicit Tier 3 video option beside `concept-to-video` and `remotion-video`. An explicit engine request outranks the subject-based suggestions, while video stays limited to temporal subjects and every companion stays optional so the base text workflow remains standalone. Add evaluation cases for HTML video routing, pure-text posts with no companion, and a plain HTML page that is not a video request.

## 1.2.4

- Preserve source URLs and every query parameter during prose cleanup, including signed links. Synchronize the shared mechanical-residue guidance and add a signed-source-link evaluation case.
