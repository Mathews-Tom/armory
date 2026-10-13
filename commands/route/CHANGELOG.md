# Changelog — Route

## 1.2.0

- Route explicit full shipping requests to `/ship` or `ship-workflow` with the `clean` default; keep PR publication at `pr` and CI/status requests read-only.
- Assign explicitly authorized version and changelog preparation to `release-captain`, with a PR-only shipping handoff. Ordinary shipping does not prepare release artifacts.
- Keep dependent-PR topology/provenance under `stacked-prs` and `/stack-pr`, with one shared shipping execution owner.

## 1.1.1

- Rename-only consumer migration: `concept-to-video` is now `animate` (2.0.0, no alias) in routing tables and evals. Analysis still routes to `watch` before creation, and an explicit engine request outranks content type.

## 1.1.0

- Add routing for videos authored as HTML and CSS and rendered with Hyperframes to `html-video`.
- Clarify engine-specific precedence for video creation: explicit Hyperframes selects `html-video`, explicit Manim selects `concept-to-video`, explicit React or Remotion selects `remotion-video`.
- Distinguish video creation from existing-video analysis (`watch`) and from ordinary web pages with no video output.
- Add routing evaluation cases for the new route and its boundaries.
