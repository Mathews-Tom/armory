# Changelog

## 1.1.1

- Rename-only consumer migration: `concept-to-video` is now `animate` (2.0.0, no alias) in skills, routing tables and evals. Routing precedence is unchanged: existing-video analysis goes to `watch` first, and an explicit engine request outranks content-type preference.

## 1.1.0

- Add standalone `html-video` orchestration for HTML/CSS and Hyperframes video creation. Resolve existing-video analysis before creation, and explicit engine requests before generic subject-based preferences; retain separate Manim and React/Remotion workflows.
