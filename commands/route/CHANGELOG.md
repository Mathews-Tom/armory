# Changelog — Route

## 1.3.1

- Route standalone throwaway prototypes to `prototype`; keep prototypes used as evidence for a decision on `decision-map`, which now delegates the artifact to `prototype`.
- Route shallow-module scans and single-module interface/seam design to `module-deepening`.
- Add routing cases for both; these are not live execution evidence.

## 1.3.0

- Route asynchronous external-recipient discovery to `intake`, persistent human learning to `learning-workspace`, active domain challenge to `domain-modeling`, and unavoidable human operations to `walkthrough`.
- Distinguish live elicitation, one-off repo tutoring, agent memory, context scaffolding, ADR writing and agent-doable setup from those routes.
- Keep disposable prototypes within `decision-map` as decision evidence, without adding a duplicate package.
- Author positive and adjacent-boundary routing cases; these are not live execution evidence.

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
